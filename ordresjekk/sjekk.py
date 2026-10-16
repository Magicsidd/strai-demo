"""Ordresjekk: faste regler først, så AI for det reglene ikke kan se, med kontroller på AI-svaret.

AI-en får bare sammenligne kundens ønsker med ordren. Hvert funn slipper bare gjennom hvis
- sitatet står ordrett i kundens ønsker, som hele ord, er langt nok til å bety noe og ikke er
  revet ut av en nektelse («ikke glassdører» kan ikke bli til «glassdører»),
- linjekoden står på ordren (ellers fjernes koblingen),
- forslaget var blant elementene AI-en fikk, og er lov i modellen (ellers fjernes forslaget).
Alt som stoppes eller slås sammen med et regelfunn, rapporteres. Ingenting forsvinner i stillhet.

Kan ønskene ikke vurderes (AI svarer ikke, eller bare regelbasert reserve), blir ordren aldri
«klar»: den får funnet AI0 og må avklares.
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

import katalog
from ai.modeller import AIOrdrefunn, OrdresjekkVurdering
from ai.tjeneste import kjor_oppgave
from ai.typer import AIBackend
from katalog.handelsvarer import HANDELSVARER

from .modeller import ALVOR_REKKEFOLGE, Funn, Ordre, Sjekkresultat
from .regler import BENKEKATEGORIER, handelsvare_lov, kjor_regler

AI_KATEGORIER = BENKEKATEGORIER | {"overskap", "høyskap"}
MAKS_AI_FUNN = 6            # samme grense som i prompten
KVOTE_PER_KATEGORI = 18     # så ingen kategori fortrenger de andre i kandidatlisten
MINSTE_SITAT_ORD = 2    # «to håndtak» er et gyldig sitat, «...» og enkeltord er det ikke
MINSTE_SITAT_TEGN = 8
NEKTELSER = {"ikke", "ingen", "uten", "aldri"}
NEKTELSE_AVSTAND = 3  # «vil ikke ha glassdører»: nektelsen kan stå noen ord foran sitatet


def _norm(tekst: str) -> str:
    tekst = (tekst or "").lower().replace("«", " ").replace("»", " ").replace('"', " ")
    return re.sub(r"\s+", " ", re.sub(r"[.,;:!?()]", " ", tekst)).strip()


def sitat_finnes(sitat: str, tekst: str) -> bool:
    """Sitatet må stå som hele ord i teksten, være langt nok og ikke stå rett etter en nektelse."""
    s, t = _norm(sitat), _norm(tekst)
    if len(s.split()) < MINSTE_SITAT_ORD and len(s) < MINSTE_SITAT_TEGN:
        return False
    for treff in re.finditer(rf"(?<!\w){re.escape(s)}(?!\w)", t):
        foran = t[:treff.start()].split()[-NEKTELSE_AVSTAND:]
        if not NEKTELSER & set(foran):
            return True
    return False


def beskriv(kode: str) -> str:
    if e := katalog.finn(kode):
        return e.beskrivelse
    return HANDELSVARER[kode].beskrivelse if kode in HANDELSVARER else "ukjent kode"


def er_lov_i_modell(kode: str, modellnavn: str) -> bool:
    if kode in HANDELSVARER:
        return handelsvare_lov(kode, modellnavn)
    e, modell = katalog.finn(kode), katalog.modell(modellnavn)
    if not e:
        return False
    return not (modell and any(b.gjelder(e) for b in modell.begrensninger))


def kandidater(ordre: Ordre) -> list[str]:
    """Koder AI-en kan foreslå: riktig modellvariant, lov i modellen, relevante bredder, kvote per kategori."""
    modell = katalog.modell(ordre.modell)
    suffiks = modell.kodesuffiks if modell else ""
    bredder = {e.bredde_cm for k in ordre.koder() if (e := katalog.finn(k)) and e.bredde_cm} or {60}
    per_kategori: dict[str, list[str]] = {}
    for e in sorted(katalog.alle().values(), key=lambda e: (abs((e.bredde_cm or 60) - 60) if e.bredde_cm not in bredder
                                                           else -1, e.kode)):
        if e.kategori not in AI_KATEGORIER:
            continue
        variant = e.kode[8:]
        if variant not in ("", suffiks):  # andre modellers varianter og spesialvarianter (A, H, V osv.)
            continue
        if suffiks and not variant and (katalog.finn(e.kode + suffiks) or (modell and modell.bare_varianter)):
            continue  # modellen har sin egen variant av elementet, eller bruker bare egne varianter
        if not er_lov_i_modell(e.kode, ordre.modell):
            continue
        liste = per_kategori.setdefault(e.kategori, [])
        if len(liste) < KVOTE_PER_KATEGORI:
            liste.append(e.kode)
    koder = [k for liste in per_kategori.values() for k in sorted(liste)]
    koder += [k for k in HANDELSVARER if handelsvare_lov(k, ordre.modell)]
    return koder


def _valider_funn(raa: list) -> tuple[list[AIOrdrefunn], list[str]]:
    """Validerer hvert funn for seg, så ett ugyldig funn ikke feller de andre."""
    gyldige, forkastet, sett = [], [], set()
    for i, f in enumerate(raa):
        try:
            funn = AIOrdrefunn.model_validate(f)
        except ValidationError as feil:
            forkastet.append(f"Funn {i + 1} hadde ugyldig format ({', '.join(str(e['loc'][0]) for e in feil.errors())}).")
            continue
        nokkel = (funn.type, (funn.linje_kode or "").upper(), (funn.forslag_kode or "").upper())
        if nokkel in sett:
            forkastet.append(f"Funn {i + 1} var en kopi av et tidligere funn.")
            continue
        sett.add(nokkel)
        gyldige.append(funn)
    if len(gyldige) > MAKS_AI_FUNN:
        forkastet.append(f"{len(gyldige) - MAKS_AI_FUNN} funn over grensen på {MAKS_AI_FUNN} ble kuttet.")
        gyldige = gyldige[:MAKS_AI_FUNN]
    return gyldige, forkastet


def ai_funn(ordre: Ordre, regelfunn: list[Funn], backend: AIBackend) -> tuple[list[Funn], list[str], str, str | None]:
    """Returnerer (godkjente funn, forkastede beskrivelser, oppsummering, feil)."""
    if not ordre.kundens_onsker.strip():
        return [], [], "", None
    tilbud = kandidater(ordre)
    linjer = "\n".join(f"- {l.kode} × {l.antall:g}: {beskriv(l.kode)}" for l in ordre.linjer)
    regler = "; ".join(f"{f.regel} {f.tittel}" for f in regelfunn) or "ingen"
    resultat = kjor_oppgave(backend, "ordresjekk", OrdresjekkVurdering, {
        "modell": ordre.modell, "linjer": linjer, "onsker": ordre.kundens_onsker.strip(), "regelfunn": regler,
        "kandidater": "\n".join(f"- {k}: {beskriv(k)}" for k in tilbud)},
        data={"ordre": ordre, "regelfunn": regelfunn})
    if resultat.vurdering is None:
        return [], [], "", resultat.feil

    funnliste, forkastet = _valider_funn(resultat.vurdering.funn)
    tillatt = set(tilbud)
    modellbrudd = {k for f in regelfunn if f.regel == "R04" for k in f.linjer}
    regelforslag = {k: f.regel for f in regelfunn for k in f.forslag}
    godkjent = []
    for f in funnliste:
        if not sitat_finnes(f.sitat, ordre.kundens_onsker):
            forkastet.append(f"Ugrunnet: sitatet «{f.sitat}» står ikke i kundens ønsker, eller er for kort.")
            continue
        linje = (f.linje_kode or "").strip().upper() or None
        if linje and linje not in ordre.koder():
            forkastet.append(f"Linjekoden {linje} står ikke på ordren, koblingen er fjernet.")
            linje = None
        forslag = (f.forslag_kode or "").strip().upper() or None
        if forslag and (forslag not in tillatt or not er_lov_i_modell(forslag, ordre.modell)):
            forkastet.append(f"Forslaget {forslag} var ikke blant elementene AI-en fikk for {ordre.modell}, "
                             "eller er ikke lov i modellen. Forslaget er fjernet.")
            forslag = None
        if linje and linje in modellbrudd:
            forkastet.append(f"Funnet om {linje} er samme sak som R04 (modellen tilbyr ikke elementet).")
            continue
        if forslag and forslag in regelforslag:
            forkastet.append(f"Funnet med forslag {forslag} er samme sak som {regelforslag[forslag]}.")
            continue
        godkjent.append(Funn("AI", f.alvor, f.type.capitalize(), f.beskrivelse,
                             f"Kundens ønsker, vurdert av {resultat.backend} (prompt {resultat.promptversjon})",
                             [linje] if linje else [], [forslag] if forslag else [], f.sitat))
    return godkjent, forkastet, resultat.vurdering.oppsummering, None


def kjor_ordresjekk(ordre: Ordre, backend: AIBackend, i_dag: date | None = None) -> Sjekkresultat:
    regelfunn = kjor_regler(ordre, i_dag)
    aifunn, forkastet, oppsummering, feil = ai_funn(ordre, regelfunn, backend)
    har_onsker = bool(ordre.kundens_onsker.strip())
    if har_onsker and (feil or backend.navn == "regelbasert"):
        grunn = (f"AI svarte ikke ({feil[:80]})." if feil else "Bare den regelbaserte reserven er tilgjengelig.")
        aifunn.append(Funn("AI0", "avklar", "Kundens ønsker er ikke sjekket",
                           f"{grunn} Selger må selv sammenligne ordren med kundens ønsker.", "Ordresjekken"))
    funn = sorted(regelfunn + aifunn, key=lambda f: (ALVOR_REKKEFOLGE[f.alvor], f.regel))
    status = Sjekkresultat.status_for(funn)
    tekst = {"klar": "Ingen avvik funnet. Ordren kan sendes til produksjon.",
             "avklar": "Ordren har punkter selger må bekrefte før produksjon.",
             "stopp": "Ordren kan ikke produseres slik den står."}[status]
    if any(f.regel == "AI" for f in funn) and oppsummering:
        tekst += f" AI om kundens ønsker: {oppsummering}"
    elif har_onsker and not any(f.regel == "AI0" for f in funn):
        tekst += " AI fant ingen avvik mot kundens ønsker utover det reglene har funnet."
    return Sjekkresultat(funn, status, tekst, backend.navn, feil, forkastet, ordre.linjehash())

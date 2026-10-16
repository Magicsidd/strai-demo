"""Faste regler for en kjøkkenordre, før den går i produksjon.

Reglene er deterministiske og bygger på Strai sin egen elementoversikt (juni 2026).
De kjøres alltid, også når AI ikke svarer. Hver regel har en ID, en kilde og et
alvor: «stopp» (kan ikke produseres slik), «avklar» (selger må bekrefte) eller «info».

Hvilken seksjon som passer en hvitevare, avgjøres av elementets beskrivelse
(«for induksjon / platetopp», «for Bora»), ikke av en fast liste med koder. Da gjelder
reglene også modellvarianter som Trollstigen (T) og Bygdøy (F).
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Callable

import katalog
from katalog.handelsvarer import HANDELSVARER, Handelsvare

from .modeller import Funn, Ordre

KILDE = katalog.KILDE
BENKEKATEGORIER = {"benkeskap", "oppvaskskap", "kolonialseksjon", "komfyrseksjon", "skuffeseksjon", "underskap",
                   "mikroseksjon benk", "vinkelhjørneskap"}
# Står på sokkel og trenger sokkel foran seg.
PA_SOKKEL = BENKEKATEGORIER | {"høyskap"}
# Modeller med grep frest i fronten, uten håndtak (modelloversikten s. 11 og 12).
MODELLER_MED_GREP = {"falketind", "besseggen"}

SEKSJON_FOR = {
    "platetopp": re.compile(r"for (induksjo?n?s?topp|induksjon|platetopp)"),
    "bora": re.compile(r"for bora"),
}
# Hvilke elementkoder vi foreslår, i prioritert rekkefølge (endelsen etter bredden).
FORSLAG_ENDELSER = {"platetopp": ("224", "223"), "bora": ("226", "236", "225")}
SIDE_SEKSJONER = 26  # «Seksjoner for platetopper og ventilatorer» i elementoversikten
SIDE_OPPVASKSKAP = 20

Regel = Callable[[Ordre, date], list[Funn]]


def _el(kode: str):
    return katalog.finn(kode)


def _hv(ordre: Ordre, type_: str) -> list[Handelsvare]:
    return [HANDELSVARER[k] for k in ordre.koder() if k in HANDELSVARER and HANDELSVARER[k].type == type_]


def _flertall(n: int, en: str, flere: str) -> str:
    return f"{n} {en if n == 1 else flere}"


def _finnes_lov(kode: str, modellnavn: str) -> bool:
    e, modell = _el(kode), katalog.modell(modellnavn)
    return bool(e) and not (modell and any(b.gjelder(e) for b in modell.begrensninger))


def _forslag(ordre: Ordre, prefiks: str, bredde: int | None, endelser: tuple[str, ...]) -> list[str]:
    """Første kode som finnes og er lov i modellen, med modellens variant (T, F) foran standardkoden."""
    if not bredde:
        return []
    modell = katalog.modell(ordre.modell)
    suffiks = modell.kodesuffiks if modell else ""
    kandidater = [f"{prefiks}{bredde:03d}{e}{suffiks}" for e in endelser if suffiks]
    if not (modell and modell.bare_varianter):
        kandidater += [f"{prefiks}{bredde:03d}{e}" for e in endelser]
    return next(([k] for k in kandidater if _finnes_lov(k, ordre.modell)), [])


def ukjent_kode(ordre: Ordre, i_dag: date) -> list[Funn]:
    ukjente = [l.kode for l in ordre.linjer if not _el(l.kode) and l.kode not in HANDELSVARER]
    return [Funn("R01", "stopp", "Ukjent elementkode", f"{k} finnes ikke i elementoversikten eller blant handelsvarene.",
                 KILDE, [k]) for k in ukjente]


def ugyldig_antall(ordre: Ordre, i_dag: date) -> list[Funn]:
    return [Funn("R02", "stopp", "Ugyldig antall", f"{l.kode} har antall {l.antall:g}.", "Ordredata", [l.kode])
            for l in ordre.linjer if l.antall <= 0 or l.antall != int(l.antall)]


def modellbegrensning(ordre: Ordre, i_dag: date) -> list[Funn]:
    modell = katalog.modell(ordre.modell)
    if not modell:
        return [Funn("R03", "avklar", "Ukjent kjøkkenmodell",
                     f"Modellen «{ordre.modell}» finnes ikke i modelloversikten, så modellreglene er ikke sjekket.", KILDE)]
    funn = []
    for linje in ordre.linjer:
        element = _el(linje.kode)
        if not element:
            continue
        brudd = [b.tekst.lower() for b in modell.begrensninger if b.gjelder(element)]
        if brudd:
            funn.append(Funn(
                "R04", "stopp", f"{modell.navn} kan ikke tilbys med: {', '.join(brudd)}",
                f"{linje.kode} ({element.beskrivelse}) er ikke tilgjengelig i modell {modell.navn}.",
                f"{KILDE}, modelloversikten s. {modell.side}, «Kan ikke tilbys»", [linje.kode]))
    return funn


def _seksjon(ordre: Ordre, type_: str, regel: str, tittel: str) -> list[Funn]:
    varer = _hv(ordre, type_)
    if not varer:
        return []
    vare = varer[0]
    monster = SEKSJON_FOR[type_]
    seksjoner = [e for k in ordre.koder() if (e := _el(k)) and monster.search(e.tekst)
                 and not (type_ == "platetopp" and SEKSJON_FOR["bora"].search(e.tekst))]
    if not seksjoner:
        return [Funn(regel, "stopp", tittel,
                     f"Ordren har {vare.beskrivelse.lower()} ({vare.kode}), men ingen seksjon laget for den.",
                     f"{KILDE}, s. {SIDE_SEKSJONER}", [vare.kode],
                     _forslag(ordre, "KO", vare.bredde_cm, FORSLAG_ENDELSER[type_]))]
    if vare.bredde_cm and all((e.bredde_cm or 0) < vare.bredde_cm for e in seksjoner):
        bredest = max(seksjoner, key=lambda e: e.bredde_cm or 0)
        return [Funn(regel, "avklar", f"{tittel.split(' mangler')[0]} er bredere enn seksjonen",
                     f"{vare.kode} er {vare.bredde_cm} cm, men {bredest.kode} er {bredest.bredde_cm} cm.",
                     f"{KILDE}, s. {SIDE_SEKSJONER}", [vare.kode, bredest.kode],
                     _forslag(ordre, "KO", vare.bredde_cm, FORSLAG_ENDELSER[type_]))]
    return []


def platetopp_seksjon(ordre: Ordre, i_dag: date) -> list[Funn]:
    return _seksjon(ordre, "platetopp", "R05", "Platetopp mangler seksjon for platetopp")


def bora_seksjon(ordre: Ordre, i_dag: date) -> list[Funn]:
    return _seksjon(ordre, "bora", "R06", "Bora benkeventilator mangler Bora-seksjon")


def vask_skap(ordre: Ordre, i_dag: date) -> list[Funn]:
    vasker = _hv(ordre, "firkantvask")
    if not vasker:
        return []
    vask = vasker[0]
    skap = [e for k in ordre.koder() if (e := _el(k)) and e.kategori == "oppvaskskap" and "firkant" in e.tekst]
    forslag = _forslag(ordre, "OB", vask.bredde_cm, ("007",))
    if not skap:
        return [Funn("R07", "stopp", "Firkantvask mangler oppvaskskap for firkantvask",
                     f"{vask.kode} krever oppvaskskap med dør for firkantvask.", f"{KILDE}, s. {SIDE_OPPVASKSKAP}",
                     [vask.kode], forslag)]
    if vask.bredde_cm and not any(e.bredde_cm == vask.bredde_cm for e in skap):
        return [Funn("R07", "avklar", "Vasken passer ikke oppvaskskapet",
                     f"{vask.kode} er for {vask.bredde_cm} cm skap, men oppvaskskapet er {skap[0].bredde_cm} cm.",
                     f"{KILDE}, s. {SIDE_OPPVASKSKAP}", [vask.kode, skap[0].kode], forslag)]
    return []


def _dor_bredde(kode: str) -> int | None:
    e = _el(kode)
    if e and e.kode.startswith("BD") and "oppvaskmaskin" in e.tekst and e.kode[2:5].isdigit():
        return int(e.kode[2:5])
    return None


def oppvaskmaskin_dor(ordre: Ordre, i_dag: date) -> list[Funn]:
    funn = []
    dorer = {k: b for k in ordre.koder() if (b := _dor_bredde(k))}
    for m in _hv(ordre, "oppvaskmaskin"):
        forslag = [k for k in (f"BD{m.bredde_cm:03d}072O",) if _el(k)] if m.bredde_cm else []
        if not dorer:
            funn.append(Funn("R08", "avklar", "Integrert oppvaskmaskin uten dør",
                             f"{m.kode} er integrert, men ordren har ingen dør for oppvaskmaskin.",
                             f"{KILDE}, dører (BD)", [m.kode], forslag))
        elif m.bredde_cm and m.bredde_cm not in dorer.values():
            funn.append(Funn("R08", "avklar", "Døren passer ikke oppvaskmaskinen",
                             f"{m.kode} er {m.bredde_cm} cm, men døren er for {next(iter(dorer.values()))} cm.",
                             f"{KILDE}, dører (BD)", [m.kode, *dorer], forslag))
    modell = katalog.modell(ordre.modell)
    if modell and modell.maks_oppvask_dybde_cm:
        for m in _hv(ordre, "oppvaskmaskin"):
            if m.dybde_cm and m.dybde_cm > modell.maks_oppvask_dybde_cm:
                funn.append(Funn("R09", "stopp", f"Oppvaskmaskinen er for dyp for {modell.navn}",
                                 f"{m.kode} er {m.dybde_cm:g} cm dyp. {modell.navn} kan ikke benytte oppvaskmaskiner "
                                 f"dypere enn {modell.maks_oppvask_dybde_cm:g} cm.",
                                 f"{KILDE}, modelloversikten s. {modell.side}", [m.kode]))
    return funn


def handtak(ordre: Ordre, i_dag: date) -> list[Funn]:
    if ordre.modell.strip().lower() in MODELLER_MED_GREP:
        return []
    fronter, ukjent = 0, []
    for l in ordre.linjer:
        e = _el(l.kode)
        if not e or e.kategori not in BENKEKATEGORIER | {"overskap", "høyskap"}:
            continue
        if e.fronter:
            fronter += e.fronter * int(l.antall)
        else:
            ukjent.append(l.kode)
    antall_handtak = sum(int(l.antall) for l in ordre.linjer if (e := _el(l.kode)) and e.kategori == "håndtak")
    if fronter == 0 or antall_handtak >= fronter:
        return []
    tillegg = (f" I tillegg har {_flertall(len(ukjent), 'element', 'elementer')} fronter vi ikke kan telle sikkert."
               if ukjent else "")
    mangler = fronter - antall_handtak
    return [Funn("R10", "avklar", "Færre håndtak enn fronter",
                 f"Ordren har minst {_flertall(fronter, 'dør eller skuff', 'dører og skuffer')}, men "
                 f"{_flertall(antall_handtak, 'håndtak', 'håndtak')}. Avklar om {mangler} håndtak mangler, "
                 f"eller om noen fronter skal være grepsfrie.{tillegg}",
                 f"Telt fra elementbeskrivelsene i {KILDE}", [], [])]


def sokkel(ordre: Ordre, i_dag: date) -> list[Funn]:
    bredde = sum((e.bredde_cm or 0) * int(l.antall) for l in ordre.linjer
                 if (e := _el(l.kode)) and e.kategori in PA_SOKKEL)
    lengde = sum((e.lengde_cm or 0) * int(l.antall) for l in ordre.linjer if (e := _el(l.kode)) and e.kategori == "sokkel")
    if bredde == 0 or lengde >= bredde:
        return []
    standard = max((e.lengde_cm for e in katalog.alle().values() if e.kategori == "sokkel" and e.lengde_cm), default=240)
    return [Funn("R11", "avklar", "For lite sokkel",
                 f"Benke- og høyskapene er til sammen {bredde} cm, men ordren har {lengde} cm sokkel. "
                 f"Det mangler {bredde - lengde} cm, rundt {math.ceil((bredde - lengde) / standard)} "
                 f"sokkellengde{'' if math.ceil((bredde - lengde) / standard) == 1 else 'r'}.",
                 f"{KILDE}, sokkel (SO)", [], [])]


def leveringstid(ordre: Ordre, i_dag: date) -> list[Funn]:
    modell = katalog.modell(ordre.modell)
    if not (modell and modell.leveringstid_uker and ordre.onsket_levering):
        return []
    tidligst = i_dag + timedelta(weeks=modell.leveringstid_uker)
    if ordre.onsket_levering >= tidligst:
        return []
    kilde = f"{KILDE}, modelloversikten s. {modell.side}"
    if ordre.onsket_levering < i_dag:
        return [Funn("R12", "stopp", "Ønsket levering har allerede passert",
                     f"Ønsket levering {ordre.onsket_levering:%d.%m.%Y} er passert. {modell.navn} har "
                     f"{modell.leveringstid_uker} ukers leveringstid, tidligst {tidligst:%d.%m.%Y}.", kilde)]
    dager = (ordre.onsket_levering - i_dag).days
    if modell.leveringstid_min_uker and ordre.onsket_levering >= i_dag + timedelta(weeks=modell.leveringstid_min_uker):
        return [Funn("R12", "avklar", "Leveringstiden holder bare for enkelte varianter",
                     f"{modell.navn} har {modell.leveringstid_uker} ukers leveringstid ({modell.merknad.lower()}). "
                     f"Ønsket levering er om {dager} dager. Avklar variant.", kilde)]
    return [Funn("R12", "stopp", "Ønsket levering er før leveringstiden",
                 f"{modell.navn} har {modell.leveringstid_uker} ukers leveringstid. Ønsket levering "
                 f"{ordre.onsket_levering:%d.%m.%Y} er om {dager} dager. Tidligste mulige er {tidligst:%d.%m.%Y}.",
                 kilde)]


REGLER: list[tuple[str, str, Regel]] = [
    ("R01", "Elementkoden finnes", ukjent_kode),
    ("R02", "Gyldig antall", ugyldig_antall),
    ("R03/R04", "Modellens «Kan ikke tilbys»", modellbegrensning),
    ("R05", "Platetopp har seksjon som passer", platetopp_seksjon),
    ("R06", "Bora har Bora-seksjon som passer", bora_seksjon),
    ("R07", "Firkantvask har oppvaskskap som passer", vask_skap),
    ("R08/R09", "Oppvaskmaskin har dør som passer, og passer modellen", oppvaskmaskin_dor),
    ("R10", "Håndtak dekker alle fronter", handtak),
    ("R11", "Sokkel dekker benke- og høyskap", sokkel),
    ("R12", "Leveringstid for modellen", leveringstid),
]


def kjor_regler(ordre: Ordre, i_dag: date | None = None) -> list[Funn]:
    i_dag = i_dag or date.today()
    return [f for _, _, regel in REGLER for f in regel(ordre, i_dag)]


def handelsvare_lov(kode: str, modellnavn: str) -> bool:
    """Om en handelsvare kan brukes i modellen. Brukes også for å kontrollere AI-forslag."""
    vare, modell = HANDELSVARER.get(kode), katalog.modell(modellnavn)
    if not vare:
        return False
    if vare.type == "oppvaskmaskin" and modell and modell.maks_oppvask_dybde_cm and vare.dybde_cm:
        return vare.dybde_cm <= modell.maks_oppvask_dybde_cm
    return True

"""Regelbasert reserve uten språkmodell.

Brukes når verken API-nøkkel eller innlogget `claude` finnes, og i seed når
Claude ikke svarer. Den leser nøkkelord og fyller maler. Den er bevisst enkel,
og sakene den lager merkes med backend «regelbasert» i grensesnittet.
"""
from __future__ import annotations

import json
import re

from .typer import Bilde

_FEILTYPE_ORD = [
    ("hvitevare", ["oppvaskmaskin", "kjøleskap", "fryser", "komfyr", "platetopp", "induksjon", "ventilator",
                   "avtrekk", "kjøl", "stekeovnen virker", "ovnen virker", "mikro"]),
    ("transport", ["transport", "levert", "levering", "emballasje", "kom skadet", "ankom", "pakken",
                   "sjåfør", "kartong"]),
    ("benkeplate", ["benkeplate", "benkeplaten", "laminat", "kompaktlaminat", "heltre", "kvarts", "stein",
                    "skjøt", "utsparing"]),
    ("beslag", ["hengsel", "hengsl", "skuff", "skinne", "demper", "soft", "håndtak", "beslag", "uttrekk",
                "lukker ikke", "smeller"]),
    ("montering", ["montør", "montering", "justere", "justering", "vater", "slår mot",
                   "ikke festet", "glipe"]),
    ("skrog", ["skrog", "sidevegg", "svell", "bunnplate", "bunnen", "hylle", "korpus", "bakvegg"]),
    ("front", ["front", "lakk", "dør", "døra", "døren", "fargeforskjell", "avskall", "sprekk",
               "sprukket", "flass", "ripe"]),
]

_KOMPONENT_ORD = [
    ("hjørneskap", "Hjørneskap"), ("høyskap", "Høyskap"), ("overskap", "Overskap"), ("underskap", "Underskap"),
    ("vaskeskap", "Skap under vask"), ("under vask", "Skap under vask"), ("kjøkkenøy", "Kjøkkenøy"),
    ("øya", "Kjøkkenøy"), ("skuff", "Skuff"), ("benkeplate", "Benkeplate"), ("sokkel", "Sokkel"),
    ("oppvaskmaskin", "Oppvaskmaskin"), ("ventilator", "Ventilator"), ("kjøleskap", "Kjøleskap"),
    ("integrert", "Integrert hvitevare"), ("komfyr", "Komfyr"), ("platetopp", "Platetopp"),
    ("stekeovn", "Skap ved stekeovn"), ("front", "Front"), ("dør", "Skapdør"),
]

_TILTAK = {
    "front": ("Be om nærbilde og bestill ny front fra fabrikk med mål fra ordren.", "Ny front i samme farge og modell",
              "Feil i lakk eller materiale fra produksjon."),
    "skrog": ("Fabrikken vurderer bilder. Bytt skrogdel eller helt skap.", "Ny sidevegg eller nytt skrog",
              "Fukt eller produksjonsfeil i skroget."),
    "beslag": ("Bytt beslaget. Montør eller kunde kan montere selv med veiledning.", "Nytt beslag (hengsel eller skinne)",
               "Beslaget er defekt eller slitt."),
    "benkeplate": ("Butikken tar saken med leverandør av benkeplater og avtaler befaring.", "Ny benkeplate eller reparasjonssett",
                   "Feil fra leverandør eller fukt i skjøt."),
    "hvitevare": ("Henvis til produsentens service via butikken. Sjekk montering mot skapet.", None,
                  "Feil på selve hvitevaren, ikke på kjøkkenet."),
    "transport": ("Registrer transportskade, bestill ny del og send til samme adresse.", "Ny del som erstatning for skadet levering",
                  "Skade under transport eller lossing."),
    "montering": ("Montør justerer eller fester på nytt ved neste besøk i området.", None,
                  "Monteringen er ikke helt ferdigjustert."),
    "annet": ("Ring kunden for å avklare hva saken gjelder.", None, "Uklart ut fra meldingen."),
}

_RUTING = {
    "front": ("fabrikk", "Ny front må lages på fabrikken."),
    "skrog": ("fabrikk", "Skrogfeil er produksjonsfeil som fabrikken må se."),
    "beslag": ("montør", "Beslag byttes og justeres på stedet."),
    "benkeplate": ("butikk", "Benkeplater kommer fra underleverandør, butikken følger opp."),
    "hvitevare": ("butikk", "Hvitevarer har egen produsentgaranti, butikken formidler."),
    "transport": ("butikk", "Butikken bestiller erstatning og avtaler ny levering."),
    "montering": ("montør", "Justering gjøres av montør på stedet."),
    "annet": ("butikk", "Butikken avklarer med kunden først."),
}

_HOY = ["lekk", "vann", "svell", "strøm", "brann", "farlig", "kan ikke bruke", "ikke brukes", "falt ned", "falle ned", "datt ned",
        "mange feil", "flere feil", "helt ødelagt"]
_LAV = ["kosmetisk", "liten", "lite merke", "ripe", "justere", "litt", "så vidt", "slår mot", "glipe"]


# Transport og montering handler om hva som skjedde, ikke hvilken del. De vinner når de nevnes.
_KONTEKST = ("transport", "montering")


def _finn(tekst: str, regler) -> str | None:
    """Kontekst-typer først, ellers den delen som nevnes tidligst i meldingen."""
    treff = {navn: min((tekst.find(o) for o in ord_ if o in tekst), default=-1) for navn, ord_ in regler}
    for navn in _KONTEKST:
        if treff.get(navn, -1) >= 0:
            return navn
    funnet = [(pos, navn) for navn, pos in treff.items() if pos >= 0]
    return min(funnet)[1] if funnet else None


def _kort(tekst: str, maks_ord: int = 10) -> str:
    """Første setning eller første ledd, maks ti ord. Det en språkmodell ville skrevet penere."""
    tekst = re.sub(r"^(hei|hallo|god dag)[,!.]?\s+", "", tekst.strip(), flags=re.I)
    setning = re.split(r"(?<=[.!?])\s", tekst)[0].rstrip(".!?")
    ledd = setning.split(", ")[0]
    ord_ = ledd.split()
    kort = " ".join(ord_[:maks_ord]) + (" …" if len(ord_) > maks_ord else "")
    return kort[:1].upper() + kort[1:]


def reklamasjon(data: dict) -> dict:
    tekst = data["fritekst"].lower()
    feiltype = _finn(tekst, _FEILTYPE_ORD) or "annet"
    komponent = next((navn for ord_, navn in _KOMPONENT_ORD if ord_ in tekst), "Ikke angitt i meldingen")
    if any(o in tekst for o in _HOY):
        alvor = "høy"
    elif any(o in tekst for o in _LAV):
        alvor = "lav"
    else:
        alvor = "middels"
    tiltak, del_, arsak = _TILTAK[feiltype]
    ruting, begrunnelse = _RUTING[feiltype]
    if feiltype == "beslag" and any(o in tekst for o in ["knekt", "brukket", "mangler", "røket"]):
        ruting, begrunnelse = "fabrikk", "Beslaget mangler eller er ødelagt, ny del sendes fra fabrikk."
    modell = data.get("kjokkenmodell") or ""
    if del_ and modell and modell != "Ukjent":
        del_ = f"{del_}, modell {modell}"
    fornavn = data["kundenavn"].split()[0]
    neste = {
        "fabrikk": "Saken er sendt til fabrikken, som vurderer ny del",
        "butikk": "Butikken går gjennom saken og tar kontakt",
        "montør": "Vi sender saken til montør, som tar kontakt for å avtale tid",
    }[ruting]
    forsta = feiltype if feiltype != "annet" else "det du beskriver"
    svar = (f"Hei {fornavn},\n\ntakk for at du sa fra, og beklager bryet. Vi har registrert saken med "
            f"saksnummer {{saksnummer}}. {neste}. Har du ikke sendt bilder, setter vi pris på et bilde som viser {forsta} tydelig."
            f"\n\nVennlig hilsen,\n{data['butikk']}")
    oppsummering = _kort(data["fritekst"])
    return {
        "feiltype": feiltype, "berort_komponent": komponent, "alvorlighet": alvor,
        "sannsynlig_arsak": arsak, "foreslatt_tiltak": tiltak, "reservedel": del_,
        "ruting": ruting, "ruting_begrunnelse": begrunnelse, "oppsummering": oppsummering,
        "svarutkast": svar, "sikkerhet": 0.55 if feiltype != "annet" else 0.3,
    }


def _budsjett(tekst: str) -> str:
    tall = [int(t.replace(" ", "").replace(".", "")) for t in re.findall(r"(\d{2,3}[ .]?\d{3})", tekst)]
    tall += [int(t) * 1000 for t in re.findall(r"(\d{2,3})\s?(?:k|tusen|lapp)", tekst)]
    if not tall:
        return "ukjent"
    belop = max(tall)
    if belop < 150_000:
        return "under 150 000 kr"
    return "150 000 til 300 000 kr" if belop <= 300_000 else "over 300 000 kr"


def _tidsramme(tekst: str) -> str:
    if any(o in tekst for o in ["snarest", "så fort", "haster", "i høst", "før jul", "innen jul", "neste måned",
                                 "om en måned", "om to måneder", "i november", "i desember", "i januar"]):
        return "innen 3 måneder"
    if any(o in tekst for o in ["i vår", "februar", "mars", "april", "påske", "om et halvt år"]):
        return "3 til 6 måneder"
    if any(o in tekst for o in ["neste år", "til sommeren", "sommeren", "mai", "juni", "om et år", "2027", "ikke hast"]):
        return "over 6 måneder"
    return "ukjent"


def tegnetime(data: dict) -> dict:
    tekst = data["beskrivelse"].lower()
    rom = [r for r, ord_ in [("kjøkken", ["kjøkken", "øy"]), ("bad", ["bad"]), ("garderobe", ["garderobe"]),
                              ("vaskerom", ["vaskerom"])] if any(o in tekst for o in ord_)]
    romtype = "flere rom" if len(rom) > 1 else (rom[0] if rom else "kjøkken")
    if any(o in tekst for o in ["nybygg", "bygger", "nytt hus", "ny bolig", "enebolig", "tomannsbolig", "byggetrinn"]):
        prosjekt = "nybygg"
    elif any(o in tekst for o in ["pusse opp", "oppussing", "renover", "bytte", "gammelt", "gamle", "rive", "fra 19"]):
        prosjekt = "renovering"
    else:
        prosjekt = "usikker"
    budsjett = _budsjett(tekst)
    tid = _tidsramme(tekst)
    poeng = {"innen 3 måneder": 2, "3 til 6 måneder": 1}.get(tid, 0) + (1 if prosjekt == "nybygg" else 0) \
        + (1 if romtype == "flere rom" or budsjett == "over 300 000 kr" else 0) \
        - (2 if any(o in tekst for o in ["bare ser", "bare se", "inspirasjon", "kun se"]) else 0)
    prioritet = "høy" if poeng >= 2 else ("middels" if poeng >= 1 else "lav")
    butikk = data.get("onsket_butikk") or data["naermeste"]
    grunner = []
    if tid != "ukjent":
        grunner.append(f"tidsramme {tid}")
    if prosjekt != "usikker":
        grunner.append(prosjekt)
    if budsjett != "ukjent":
        grunner.append(f"budsjett {budsjett}")
    begrunnelse = ("Vurdert ut fra " + ", ".join(grunner) + ".") if grunner else "Lite informasjon i meldingen, avklar i første samtale."
    return {
        "romtype": romtype, "prosjekttype": prosjekt, "budsjettklasse": budsjett, "tidsramme": tid,
        "prioritet": prioritet, "foreslatt_butikk": butikk, "begrunnelse": begrunnelse,
        "oppsummering": _kort(data["beskrivelse"]),
        "forslag_forste_kontakt": "Ring innen to virkedager og avklar mål, ønsket stil og tidsramme. "
                                  "Be kunden sende bilder eller tegning av rommet før tegnetimen.",
    }


class RegelbasertBackend:
    navn = "regelbasert"

    def fullfor(self, oppgave: str, system: str, bruker: str, bilder: list[Bilde], data: dict) -> str:
        if oppgave == "ordresjekk":
            # Uten språkmodell kan ønskene ikke tolkes. De faste reglene kjøres uansett.
            resultat = {"funn": [], "oppsummering": ""}
        elif oppgave == "avvik":
            from ordresjekk.avvik import enkel_tolkning
            resultat = enkel_tolkning(data["ordre"], data["melding"])
        else:
            resultat = reklamasjon(data) if oppgave == "reklamasjon" else tegnetime(data)
        return json.dumps(resultat, ensure_ascii=False)

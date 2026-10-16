"""Kjøkkenmodellene og hva de «ikke kan tilbys», lest fra modelloversikten i elementoversikten.

Hver begrensning har en sjekk mot elementet og sidetallet den står på, så et funn alltid
kan begrunnes med Strai sitt eget dokument. Begrensninger vi ikke kan sjekke sikkert ut
fra elementkoden (for eksempel fresing av fronter), er utelatt i stedet for å gjettes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Begrensning:
    tekst: str  # ordrett fra «Kan ikke tilbys»
    gjelder: Callable[[object], bool]


@dataclass(frozen=True)
class Modell:
    navn: str
    leveringstid_uker: int | None
    side: int
    begrensninger: tuple[Begrensning, ...] = field(default_factory=tuple)
    merknad: str = ""
    kodesuffiks: str = ""  # modellvarianter i elementoversikten: Bygdøy F, Trollstigen T
    leveringstid_min_uker: int | None = None  # kortere for enkelte farger, se merknad
    maks_oppvask_dybde_cm: float | None = None
    bare_varianter: bool = False  # Bygdøy har eget sortiment (F) og bruker ikke standardkodene


def _kat(*kategorier: str) -> Callable[[object], bool]:
    return lambda e: e.kategori in kategorier


def _ord(*ord_: str) -> Callable[[object], bool]:
    return lambda e: any(o in e.tekst for o in ord_)


def _hengslet(e) -> bool:
    from . import er_hengslet_dor
    return er_hengslet_dor(e)


VINKELHJORNE = Begrensning("Vinkelhjørneskap", _kat("vinkelhjørneskap"))
FIRE_SKUFFER = Begrensning("4 skuffers seksjon", _ord("4 skuffer", "4 xl skuffer"))
MIKRO_BENK = Begrensning("Mikroskap for benk", _kat("mikroseksjon benk"))
HJORNESKUFF = Begrensning("Hjørneskuff", lambda e: e.kategori == "vinkelhjørneskap" and "skuff" in e.tekst)
HELFINERT = Begrensning("Helfinerte skap", _ord("helfinert"))

_LISTE = [
    Modell("Lyngen", 6, 10, (HELFINERT,)),
    Modell("Tromsø", 4, 10, merknad="Svanemerket"),
    Modell("Svalbard", 4, 10),
    Modell("Lysefjord", 4, 10, merknad="Blindfelt over hvitevarer leveres i slett utførelse"),
    Modell("Lindøya", 4, 11, (FIRE_SKUFFER, MIKRO_BENK)),
    Modell("Blindleia", 4, 11),
    Modell("Frogner", 4, 11, (FIRE_SKUFFER, MIKRO_BENK)),
    Modell("Falketind", 7, 11, (VINKELHJORNE,)),
    Modell("Besseggen", 7, 12, (VINKELHJORNE,)),
    Modell("Trollstigen", 7, 12, (
        Begrensning("Hengslede dører", _hengslet),
        Begrensning("Hjørneløsninger", _kat("vinkelhjørneskap")),
        Begrensning("Glassdører", _ord("glass")),
        Begrensning("Overskap", _kat("overskap")),
        Begrensning("Høyskap", _kat("høyskap")),
    ), merknad="Kan ikke benytte oppvaskmaskiner som er dypere enn 56 cm", kodesuffiks="T",
        maks_oppvask_dybde_cm=56),
    Modell("Voss", 4, 12),
    Modell("Rondane", 4, 13),
    Modell("Bygdøy", 7, 13, (VINKELHJORNE, Begrensning("Tredelt skuff", _ord("tredelt", "3-delt skuff"))),
           kodesuffiks="F", bare_varianter=True),
    Modell("Nordmarka", 4, 13, (FIRE_SKUFFER, MIKRO_BENK)),
    Modell("Vinje", 4, 13),
    Modell("Femunden", 4, 14),
    Modell("Dalen", 5, 14, (HJORNESKUFF, HELFINERT), merknad="Premium White har 4 uker", leveringstid_min_uker=4),
    Modell("Senja", 5, 14, (HJORNESKUFF, HELFINERT), merknad="Svanemerket"),
    Modell("Røst", None, 14, (HELFINERT,), merknad="Hvit er lagermodell, farget har 8 uker"),
]
MODELLER: dict[str, Modell] = {m.navn.lower(): m for m in _LISTE}

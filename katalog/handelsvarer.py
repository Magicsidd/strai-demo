"""Handelsvarer i demoen: hvitevarer, vask og benkeplater som Strai kjøper inn og leverer samlet.

Disse finnes ikke i elementoversikten. Kodene (HV-, BP-) er laget for demoen.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Handelsvare:
    kode: str
    beskrivelse: str
    type: str  # platetopp, bora, oppvaskmaskin, firkantvask, stekeovn, kjøleskap, benkeplate
    bredde_cm: int | None = None
    dybde_cm: float | None = None
    lengde_cm: int | None = None


_LISTE = [
    Handelsvare("HV-IND60", "Induksjonstopp 60 cm", "platetopp", 60),
    Handelsvare("HV-IND80", "Induksjonstopp 80 cm", "platetopp", 80),
    Handelsvare("HV-BORA80", "Bora basic platetopp med benkeventilator og kullfilter, 80 cm", "bora", 80),
    Handelsvare("HV-OPPV60", "Integrert oppvaskmaskin 60 cm, dybde 55 cm", "oppvaskmaskin", 60, 55),
    Handelsvare("HV-OPPV60D", "Integrert oppvaskmaskin 60 cm, dybde 57 cm", "oppvaskmaskin", 60, 57),
    Handelsvare("HV-OPPV45", "Integrert oppvaskmaskin 45 cm, dybde 55 cm", "oppvaskmaskin", 45, 55),
    Handelsvare("HV-VASK50", "Firkantvask i rustfritt stål for 50 cm skap", "firkantvask", 50),
    Handelsvare("HV-VASK60", "Firkantvask i rustfritt stål for 60 cm skap", "firkantvask", 60),
    Handelsvare("HV-STEK60", "Integrert stekeovn 60 cm", "stekeovn", 60),
    Handelsvare("HV-KJOL178", "Integrert kjøleskap 178 cm", "kjøleskap", 60),
    Handelsvare("BP-LAM240", "Benkeplate laminat 240 cm", "benkeplate", lengde_cm=240),
    Handelsvare("BP-LAM300", "Benkeplate laminat 300 cm", "benkeplate", lengde_cm=300),
    Handelsvare("BP-EIK300", "Benkeplate heltre eik 300 cm", "benkeplate", lengde_cm=300),
]
HANDELSVARER: dict[str, Handelsvare] = {h.kode: h for h in _LISTE}

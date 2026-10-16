"""Butikker og forhandlere i demoen, og enkel ruting fra postnummer til nærmeste butikk.

Tallene er demodata. Hos Strai ville listen komme fra Odoo (crm.team eller res.partner).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Butikk:
    navn: str
    type: str  # "egen butikk" eller "forhandler"
    sted: str


BUTIKKER = [
    Butikk("Strai Kristiansand", "egen butikk", "Kristiansand"),
    Butikk("Strai Oslo", "egen butikk", "Oslo"),
    Butikk("Strai Arendal", "egen butikk", "Arendal"),
    Butikk("Strai Stavanger", "egen butikk", "Stavanger"),
    Butikk("Strai Bergen", "egen butikk", "Bergen"),
    Butikk("Strai Evje", "egen butikk", "Evje"),
    Butikk("Kjøkkenhuset Lillesand", "forhandler", "Lillesand"),
]
BUTIKKNAVN = [b.navn for b in BUTIKKER]

# Postnummerområder (fire siffer). Første treff vinner, så smale områder står først.
_OMRAADER = [
    ((4790, 4795), "Kjøkkenhuset Lillesand"),
    ((4735, 4749), "Strai Evje"),
    ((4800, 4899), "Strai Arendal"),
    ((4600, 4789), "Strai Kristiansand"),
    ((4000, 4399), "Strai Stavanger"),
    ((4400, 4599), "Strai Kristiansand"),
    ((5000, 5999), "Strai Bergen"),
    ((0, 3999), "Strai Oslo"),
]


def naermeste_butikk(postnr: str | None) -> str:
    try:
        nr = int(str(postnr).strip()[:4])
    except (TypeError, ValueError):
        return "Strai Oslo"
    for (fra, til), navn in _OMRAADER:
        if fra <= nr <= til:
            return navn
    return "Strai Oslo"


def kort_navn(navn: str) -> str:
    return navn.replace("Strai ", "").replace("Kjøkkenhuset ", "")

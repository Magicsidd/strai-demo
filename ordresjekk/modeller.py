"""Domenemodeller for ordresjekken. Uavhengige av Odoo, så reglene kan testes uten server."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

Alvor = Literal["stopp", "avklar", "info"]
ALVOR_REKKEFOLGE = {"stopp": 0, "avklar": 1, "info": 2}


@dataclass
class Ordrelinje:
    kode: str
    antall: float
    beskrivelse: str = ""
    linje_id: int | None = None

    def __post_init__(self) -> None:
        # Koder sammenlignes alltid med store bokstaver, uansett hvordan de står i Odoo.
        self.kode = (self.kode or "").strip().upper()


@dataclass
class Ordre:
    navn: str
    modell: str
    linjer: list[Ordrelinje]
    kunde: str = ""
    butikk: str = ""
    onsket_levering: date | None = None
    kundens_onsker: str = ""
    odoo_id: int | None = None

    def koder(self) -> set[str]:
        return {l.kode for l in self.linjer}

    def antall_av(self, kode: str) -> float:
        return sum(l.antall for l in self.linjer if l.kode == kode)

    def linjehash(self) -> str:
        """Fingeravtrykk av linjene. Er ordren endret etter sjekken, må den sjekkes på nytt."""
        innhold = ";".join(f"{l.kode}:{l.antall:g}" for l in sorted(self.linjer, key=lambda l: (l.kode, l.antall)))
        return hashlib.sha256(f"{self.modell}|{innhold}".encode()).hexdigest()[:12]


@dataclass
class Funn:
    regel: str  # regel-ID, eller «AI» for funn fra språkmodellen
    alvor: Alvor
    tittel: str
    beskrivelse: str
    kilde: str
    linjer: list[str] = field(default_factory=list)
    forslag: list[str] = field(default_factory=list)
    sitat: str = ""  # for AI-funn: ordrett fra kundens ønsker

    def til_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sjekkresultat:
    funn: list[Funn]
    status: Literal["klar", "avklar", "stopp"]
    oppsummering: str
    ai_backend: str
    ai_feil: str | None = None
    forkastet: list[str] = field(default_factory=list)  # AI-funn som ikke besto kontrollene
    linjehash: str = ""

    @staticmethod
    def status_for(funn: list[Funn]) -> Literal["klar", "avklar", "stopp"]:
        if any(f.alvor == "stopp" for f in funn):
            return "stopp"
        return "avklar" if any(f.alvor == "avklar" for f in funn) else "klar"

"""Pydantic-modeller for det AI-en skal returnere. Alt AI-svar valideres mot disse."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FEILTYPER = ["front", "skrog", "beslag", "benkeplate", "hvitevare", "transport", "montering", "annet"]
ALVORLIGHET = ["lav", "middels", "høy"]
RUTING = ["fabrikk", "butikk", "montør"]
ROMTYPER = ["kjøkken", "bad", "garderobe", "vaskerom", "flere rom", "annet"]
PROSJEKTTYPER = ["nybygg", "renovering", "usikker"]
BUDSJETT = ["under 150 000 kr", "150 000 til 300 000 kr", "over 300 000 kr", "ukjent"]
TIDSRAMMER = ["innen 3 måneder", "3 til 6 måneder", "over 6 måneder", "ukjent"]

Feiltype = Literal["front", "skrog", "beslag", "benkeplate", "hvitevare", "transport", "montering", "annet"]
Nivaa = Literal["lav", "middels", "høy"]

_ASCII = {"hoy": "høy", "hoey": "høy", "montor": "montør", "montoer": "montør",
          "kjokken": "kjøkken", "maaneder": "måneder"}


def _normaliser(verdi):
    if isinstance(verdi, str):
        v = verdi.strip().lower()
        for feil, riktig in _ASCII.items():
            v = v.replace(feil, riktig)
        return v
    return verdi


class ReklamasjonVurdering(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feiltype: Feiltype
    berort_komponent: str = Field(min_length=2, description="Hvilket skap eller hvilken komponent")
    alvorlighet: Nivaa
    sannsynlig_arsak: str = Field(min_length=3)
    foreslatt_tiltak: str = Field(min_length=3)
    reservedel: str | None = None
    ruting: Literal["fabrikk", "butikk", "montør"]
    ruting_begrunnelse: str = ""
    oppsummering: str = Field(min_length=3, max_length=160)
    svarutkast: str = Field(min_length=20)
    sikkerhet: float = Field(ge=0, le=1)

    _norm = field_validator("feiltype", "alvorlighet", "ruting", mode="before")(_normaliser)


class TegnetimeVurdering(BaseModel):
    model_config = ConfigDict(extra="ignore")

    romtype: Literal["kjøkken", "bad", "garderobe", "vaskerom", "flere rom", "annet"]
    prosjekttype: Literal["nybygg", "renovering", "usikker"]
    budsjettklasse: Literal["under 150 000 kr", "150 000 til 300 000 kr", "over 300 000 kr", "ukjent"]
    tidsramme: Literal["innen 3 måneder", "3 til 6 måneder", "over 6 måneder", "ukjent"]
    prioritet: Nivaa
    foreslatt_butikk: str = Field(min_length=2)
    begrunnelse: str = Field(min_length=3)
    oppsummering: str = Field(min_length=3, max_length=160)
    forslag_forste_kontakt: str = Field(min_length=10)

    _norm = field_validator("romtype", "prosjekttype", "tidsramme", "prioritet", mode="before")(_normaliser)


MANUELL_TEKST = "Trenger manuell vurdering"


class AIOrdrefunn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["mangler", "feil element", "motstrid", "uklart"]
    alvor: Literal["stopp", "avklar", "info"]
    linje_kode: str | None = None
    beskrivelse: str = Field(min_length=5)
    forslag_kode: str | None = None
    sitat: str = Field(min_length=3)

    _norm = field_validator("type", "alvor", mode="before")(_normaliser)


class OrdresjekkVurdering(BaseModel):
    model_config = ConfigDict(extra="ignore")

    funn: list = Field(default_factory=list)  # valideres ett og ett i ordresjekk.sjekk
    oppsummering: str = ""


class AvvikLinje(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kode: str
    antall: int = Field(ge=1)
    problem: Literal["mangler", "skadet", "feil levert"]
    sitat: str = Field(min_length=3)

    _norm = field_validator("problem", mode="before")(_normaliser)


class AvvikVurdering(BaseModel):
    model_config = ConfigDict(extra="ignore")

    linjer: list = Field(default_factory=list)  # valideres én og én i ordresjekk.avvik
    arsak: Literal["pakking", "transport", "produksjon", "ordrefeil", "ukjent"]
    arsak_begrunnelse: str = ""
    kan_monteres_videre: bool = True
    uklart: list[str] = Field(default_factory=list)
    svarutkast: str = Field(min_length=20)

    _norm = field_validator("arsak", mode="before")(_normaliser)

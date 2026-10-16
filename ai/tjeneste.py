"""Bygger prompt, kaller backend, parser og validerer svaret. Fallback ved feil."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from . import logg
from .modeller import ReklamasjonVurdering, TegnetimeVurdering
from .typer import AIBackend, Bilde

PROMPTMAPPE = Path(__file__).parent / "prompter"
M = TypeVar("M", bound=BaseModel)


@dataclass
class AIResultat(Generic[M]):
    vurdering: M | None
    backend: str
    manuell: bool = False
    feil: str | None = None
    ratt_svar: str = field(default="", repr=False)
    promptversjon: str = ""
    varighet_ms: int = 0


def last_prompt(navn: str, verdier: dict[str, str]) -> tuple[str, str]:
    """Leser ai/prompter/<navn>.md og deler i system og brukermelding.

    Plassholdere er {navn}. Bare kjente nøkler byttes ut, så JSON i eksemplene står urørt.
    """
    tekst = (PROMPTMAPPE / f"{navn}.md").read_text(encoding="utf-8")
    for nokkel, verdi in verdier.items():
        tekst = tekst.replace("{" + nokkel + "}", str(verdi))
    system, _, resten = tekst.partition("\n# Eksempel")
    system = system.replace("# System", "", 1).strip()
    return system, ("# Eksempel" + resten).strip()


def hent_json(tekst: str) -> dict:
    """Finner første gyldige JSON-objekt i teksten. Tåler kodeblokker og prat rundt."""
    tekst = re.sub(r"```(?:json)?", "", tekst or "")
    dekoder = json.JSONDecoder()
    for treff in re.finditer(r"\{", tekst):
        try:
            objekt, _ = dekoder.raw_decode(tekst, treff.start())
        except json.JSONDecodeError:
            continue
        if isinstance(objekt, dict):
            return objekt
    raise ValueError("Fant ikke noe JSON-objekt i AI-svaret.")


def promptversjon(oppgave: str) -> str:
    return logg.kort_hash((PROMPTMAPPE / f"{oppgave}.md").read_text(encoding="utf-8"), 8)


def kjor_oppgave(backend: AIBackend, oppgave: str, modell: type[M], verdier: dict, bilder: list[Bilde] | None = None,
                 data: dict | None = None) -> AIResultat[M]:
    """Kjører én AI-oppgave: prompt, kall, parsing, validering og revisjonslogg."""
    system, bruker = last_prompt(oppgave, verdier)
    versjon = promptversjon(oppgave)
    start = time.monotonic()
    loggfeil = ""  # bare feiltype og feltnavn, aldri innhold som kan inneholde kundetekst
    try:
        svar = backend.fullfor(oppgave, system, bruker, bilder or [], data or {})
        try:
            resultat = AIResultat(modell.model_validate(hent_json(svar)), backend.navn, ratt_svar=svar)
        except ValidationError as feil:
            felt = ", ".join(".".join(str(d) for d in e["loc"]) for e in feil.errors())
            resultat = AIResultat(None, backend.navn, manuell=True, feil=f"Ugyldig AI-svar i feltene: {felt}",
                                  ratt_svar=svar)
            loggfeil = f"ValidationError: {felt}"
        except ValueError as feil:
            resultat = AIResultat(None, backend.navn, manuell=True, feil=str(feil), ratt_svar=svar)
            loggfeil = "Fant ikke JSON i svaret"
    except Exception as feil:
        resultat = AIResultat(None, backend.navn, manuell=True, feil=str(feil)[:300])
        loggfeil = type(feil).__name__
    resultat.promptversjon = versjon
    resultat.varighet_ms = int((time.monotonic() - start) * 1000)
    logg.skriv({"oppgave": oppgave, "backend": backend.navn, "modell": getattr(backend, "modell", None),
                "promptversjon": versjon, "input": logg.kort_hash(bruker), "varighet_ms": resultat.varighet_ms,
                "gyldig": resultat.vurdering is not None, "feil": loggfeil})
    return resultat


def vurder_reklamasjon(backend: AIBackend, skjema: dict, kjokkenmodell: str,
                       bilder: list[Bilde] | None = None) -> AIResultat[ReklamasjonVurdering]:
    bilder = bilder or []
    verdier = {
        "kundenavn": skjema["kundenavn"], "ordrenummer": skjema.get("ordrenummer") or "ikke oppgitt",
        "kjokkenmodell": kjokkenmodell or "ukjent", "butikk": skjema["butikk"],
        "antall_bilder": len(bilder), "fritekst": skjema["fritekst"].strip(),
    }
    return kjor_oppgave(backend, "reklamasjon", ReklamasjonVurdering, verdier, bilder,
                 {**skjema, "kjokkenmodell": kjokkenmodell})


def vurder_tegnetime(backend: AIBackend, skjema: dict, butikker: list[str],
                     naermeste: str) -> AIResultat[TegnetimeVurdering]:
    verdier = {
        "navn": skjema["navn"], "postnummer": skjema.get("postnummer") or "ikke oppgitt",
        "onsket_butikk": skjema.get("onsket_butikk") or "ikke valgt",
        "beskrivelse": skjema["beskrivelse"].strip(),
        "butikker": ", ".join(butikker), "naermeste": naermeste,
    }
    return kjor_oppgave(backend, "tegnetime", TegnetimeVurdering, verdier, [],
                 {**skjema, "naermeste": naermeste})

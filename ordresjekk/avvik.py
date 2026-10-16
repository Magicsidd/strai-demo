"""Avvik ved levering: melding fra montør eller kunde blir etterleveringslinjer koblet til ordren.

Samme prinsipp som ordresjekken: AI tolker fritekst, men kan bare peke på linjer som står
på ordren, med et ordrett sitat, og summen per kode kan ikke bli høyere enn det som er bestilt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from ai.modeller import AvvikLinje, AvvikVurdering
from ai.tjeneste import kjor_oppgave
from ai.typer import AIBackend, Bilde

from .modeller import Ordre
from .sjekk import beskriv, sitat_finnes


@dataclass
class Etterlevering:
    kode: str
    antall: int
    problem: str
    sitat: str


@dataclass
class Avviksresultat:
    linjer: list[Etterlevering]
    arsak: str
    arsak_begrunnelse: str
    kan_monteres_videre: bool
    uklart: list[str]
    svarutkast: str
    ai_backend: str
    manuell: bool = False
    feil: str | None = None
    forkastet: list[str] = field(default_factory=list)
    promptversjon: str = ""


def vurder_avvik(ordre: Ordre, melding: str, avsender: str, backend: AIBackend,
                 bilder: list[Bilde] | None = None) -> Avviksresultat:
    linjer = "\n".join(f"- {l.kode} × {l.antall:g}: {beskriv(l.kode)}" for l in ordre.linjer)
    resultat = kjor_oppgave(backend, "avvik", AvvikVurdering, {
        "linjer": linjer, "melding": melding.strip(), "avsender": avsender, "butikk": ordre.butikk or "Strai Kjøkken"},
        bilder, {"ordre": ordre, "melding": melding})
    v = resultat.vurdering
    if v is None:
        return Avviksresultat([], "ukjent", "", True, [melding.strip()], "", resultat.backend, manuell=True,
                              feil=resultat.feil, promptversjon=resultat.promptversjon)

    uklart, forkastet = list(v.uklart), []
    per_kode: dict[str, Etterlevering] = {}
    for i, raa in enumerate(v.linjer):
        try:
            l = AvvikLinje.model_validate(raa)
        except ValidationError:
            forkastet.append(f"Linje {i + 1} fra AI hadde ugyldig format og ble lagt til side.")
            continue
        kode = l.kode.strip().upper()
        if not ordre.antall_av(kode):
            uklart.append(f"{kode} står ikke på ordren. Må avklares manuelt.")
            forkastet.append(f"{kode} står ikke på ordren.")
            continue
        if not sitat_finnes(l.sitat, melding):
            uklart.append(f"«{l.sitat}» kunne ikke kobles sikkert til {kode}.")
            forkastet.append(f"Sitatet for {kode} står ikke i meldingen.")
            continue
        if kode in per_kode:
            per_kode[kode].antall += l.antall
        else:
            per_kode[kode] = Etterlevering(kode, l.antall, l.problem, l.sitat)

    for kode, e in per_kode.items():
        bestilt = int(ordre.antall_av(kode))
        if e.antall > bestilt:
            forkastet.append(f"{kode}: AI foreslo {e.antall} til sammen, men bare {bestilt} er bestilt. "
                             f"Satt til {bestilt}.")
            e.antall = bestilt
    godkjent = list(per_kode.values())
    return Avviksresultat(godkjent, v.arsak, v.arsak_begrunnelse, v.kan_monteres_videre, uklart, v.svarutkast,
                          resultat.backend, manuell=not godkjent and bool(uklart), forkastet=forkastet,
                          promptversjon=resultat.promptversjon)


def enkel_tolkning(ordre: Ordre, melding: str) -> dict:
    """Regelbasert reserve: koder som står ordrett i meldingen, og «fått N håndtak» mot bestilt antall."""
    linjer, uklart = [], []
    for l in ordre.linjer:
        if re.search(rf"(?<!\w){re.escape(l.kode)}(?!\w)", melding, re.I):
            linjer.append({"kode": l.kode, "antall": 1, "problem": "mangler", "sitat": f"{l.kode} i meldingen"})
    if m := re.search(r"fått (\d+) håndtak", melding.lower()):
        handtak = next((l for l in ordre.linjer if l.kode.startswith("GR")), None)
        mottatt = int(m.group(1))
        if handtak and mottatt < handtak.antall:
            linjer.append({"kode": handtak.kode, "antall": int(handtak.antall) - mottatt, "problem": "mangler",
                           "sitat": m.group(0)})
        else:
            uklart.append(f"«{m.group(0)}» stemmer ikke med ordren, må avklares.")
    linjer = [l for l in linjer if l["sitat"].lower() in melding.lower()] or linjer
    return {"linjer": linjer, "arsak": "ukjent", "arsak_begrunnelse": "Regelbasert reserve kan ikke vurdere årsak.",
            "kan_monteres_videre": True, "uklart": uklart or ([] if linjer else ["Fant ingen kjente koder i meldingen."]),
            "svarutkast": "Hei,\n\ntakk for beskjeden. Avviket er registrert med saksnummer {saksnummer}, og vi "
                          "følger opp etterleveringen.\n\nVennlig hilsen,\n" + (ordre.butikk or "Strai Kjøkken")}

"""Legger inn 25 reklamasjoner og 12 leads gjennom hele pipelinen (AI og Odoo).

    python -m demo.seed               # bruker AI_BACKEND (auto), faller tilbake til regelbasert
    python -m demo.seed --ai regelbasert
    python -m demo.seed --nullstill   # tømmer saker og leads i mock-Odoo først
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from ai import velg_backend
from ai.regelbasert import RegelbasertBackend
from app.odoo_client import OdooClient, OdooFeil
from app.pipeline import behandle_reklamasjon, behandle_tegnetime

from .data import LEADS, ORDRER, REKLAMASJONER


def _tid(dager: int, time: int) -> datetime:
    return (datetime.now() - timedelta(days=dager)).replace(hour=time, minute=(dager * 7) % 60, second=0, microsecond=0)


def _sjekk_backend(backend):
    """Prøver én ekte vurdering. Svarer ikke Claude, brukes regelbasert reserve."""
    if backend.navn == "regelbasert":
        return backend
    from ai import vurder_tegnetime

    print(f"Sjekker AI-backend «{backend.navn}» ...", flush=True)
    prove = vurder_tegnetime(backend, {"navn": "Test", "beskrivelse": "Nytt kjøkken i nybygg til våren."},
                             ["Strai Oslo"], "Strai Oslo")
    if prove.vurdering is None:
        print(f"  AI svarte ikke: {prove.feil}\n  Bruker regelbasert reserve i seed.", flush=True)
        return RegelbasertBackend()
    print("  OK, Claude svarer. Dette tar noen minutter.", flush=True)
    return backend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai", default=None, help="auto | anthropic | claude_cli | regelbasert")
    parser.add_argument("--nullstill", action="store_true")
    args = parser.parse_args()

    odoo = OdooClient()
    try:
        odoo.versjon()
        odoo.uid
    except OdooFeil as feil:
        print(f"Fikk ikke kontakt med Odoo: {feil}", file=sys.stderr)
        return 1

    if args.nullstill:
        for modell in ("helpdesk.ticket", "crm.lead", "ir.attachment", "sale.order", "res.partner"):
            ids = [p["id"] for p in odoo.search_read(modell, [], ["id"])]
            if ids:
                odoo.execute_kw(modell, "unlink", [ids])
    elif odoo.search_count("helpdesk.ticket") > 0:
        print("Odoo har allerede saker. Bruk --nullstill for å starte på nytt.")
        return 0

    backend = _sjekk_backend(velg_backend(args.ai))

    for nr, modell, butikk in ORDRER:
        if not odoo.search_count("sale.order", [("name", "=", nr)]):
            odoo.create("sale.order", {"name": nr, "x_kjokkenmodell": modell, "x_butikk": butikk, "state": "sale"})

    stadier = {s["name"]: s["id"] for s in odoo.search_read("helpdesk.stage", [], ["name"])}
    for i, (dager, navn, epost, ordre, butikk, tekst, stadium) in enumerate(REKLAMASJONER, 1):
        k = behandle_reklamasjon(odoo, backend, {"kundenavn": navn, "epost": epost, "ordrenummer": ordre,
                                                 "butikk": butikk, "fritekst": tekst}, opprettet=_tid(dager, 8 + i % 9))
        if stadium != "Ny":
            odoo.write("helpdesk.ticket", k.odoo_id, {"stage_id": stadier[stadium]})
        print(f"  {k.saksnummer}  {navn:<18} {'manuell' if k.manuell else 'ok'}", flush=True)

    crm_stadier = {s["name"]: s["id"] for s in odoo.search_read("crm.stage", [], ["name"])}
    for i, (dager, navn, epost, tlf, postnr, onsket, tekst, stadium) in enumerate(LEADS, 1):
        k = behandle_tegnetime(odoo, backend, {"navn": navn, "epost": epost, "telefon": tlf, "postnummer": postnr,
                                               "onsket_butikk": onsket, "beskrivelse": tekst},
                               opprettet=_tid(dager, 9 + i % 8))
        if stadium != "Ny":
            odoo.write("crm.lead", k.odoo_id, {"stage_id": crm_stadier[stadium]})
        print(f"  {k.saksnummer} {navn:<18} {'manuell' if k.manuell else 'ok'}", flush=True)

    print(f"Ferdig: {len(REKLAMASJONER)} reklamasjoner og {len(LEADS)} leads, AI: {backend.navn}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

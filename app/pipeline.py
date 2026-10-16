"""Selve flyten: skjema inn, AI-vurdering, sak eller lead i Odoo, saksnummer ut."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ai import Bilde, vurder_reklamasjon, vurder_tegnetime
from ai.modeller import MANUELL_TEKST
from ai.typer import AIBackend

from .butikker import BUTIKKNAVN, naermeste_butikk
from .odoo_client import OdooClient

PRIORITET = {"lav": "1", "middels": "2", "høy": "3"}
OPPFOLGING_DAGER = {"høy": 1, "middels": 3, "lav": 7}


@dataclass
class Kvittering:
    odoo_id: int
    saksnummer: str
    manuell: bool
    ai_backend: str


def _tidsstempel(tid: datetime | None) -> dict:
    # Kun brukt av seed mot mock-Odoo. Ekte Odoo setter create_date selv.
    return {"create_date": tid.strftime("%Y-%m-%d %H:%M:%S")} if tid else {}


def _legg_til_virkedager(start: date, dager: int) -> date:
    d = start
    while dager > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            dager -= 1
    return d


def hent_ordre(odoo: OdooClient, ordrenummer: str) -> dict | None:
    if not ordrenummer:
        return None
    treff = odoo.search_read("sale.order", [("name", "=", ordrenummer.strip().upper())],
                             ["name", "x_kjokkenmodell", "x_butikk", "date_order"], limit=1)
    return treff[0] if treff else None


def behandle_reklamasjon(odoo: OdooClient, backend: AIBackend, skjema: dict,
                         bilder: list[Bilde] | None = None, opprettet: datetime | None = None) -> Kvittering:
    bilder = bilder or []
    ordre = hent_ordre(odoo, skjema.get("ordrenummer", ""))
    modell = (ordre or {}).get("x_kjokkenmodell") or "Ukjent"
    resultat = vurder_reklamasjon(backend, skjema, modell, bilder)
    v = resultat.vurdering

    partner_id = odoo.finn_eller_opprett_partner(skjema["kundenavn"], skjema["epost"], skjema.get("telefon", ""))
    verdier = {
        "name": v.oppsummering if v else f"Reklamasjon fra {skjema['kundenavn']}",
        "description": skjema["fritekst"],
        "partner_id": partner_id,
        "partner_name": skjema["kundenavn"],
        "partner_email": skjema["epost"],
        "priority": PRIORITET[v.alvorlighet] if v else "2",
        "x_ordrenummer": (skjema.get("ordrenummer") or "").strip().upper(),
        "x_butikk": skjema["butikk"],
        "x_kjokkenmodell": modell,
        "x_feiltype": v.feiltype if v else MANUELL_TEKST,
        "x_alvorlighet": v.alvorlighet if v else "",
        "x_ruting": v.ruting if v else "",
        "x_ai_vurdering": v.model_dump_json() if v else "",
        "x_ai_backend": resultat.backend,
        "x_ai_feil": resultat.feil or "",
        "x_manuell": resultat.manuell,
        "x_antall_bilder": len(bilder),
        "x_kilde": "Nettskjema reklamasjon",
        **_tidsstempel(opprettet),
    }
    ticket_id = odoo.create("helpdesk.ticket", verdier)
    ref = odoo.read("helpdesk.ticket", ticket_id, ["ticket_ref"]) or {}
    saksnummer = f"REK-{ref.get('ticket_ref') or f'{ticket_id:05d}'}"
    svarutkast = v.svarutkast.replace("{saksnummer}", saksnummer) if v else ""
    odoo.write("helpdesk.ticket", ticket_id, {"x_saksnummer": saksnummer, "x_svarutkast": svarutkast})

    for bilde in bilder[:10]:
        odoo.create("ir.attachment", {
            "name": bilde.filnavn, "mimetype": bilde.mediatype, "res_model": "helpdesk.ticket",
            "res_id": ticket_id, "datas": base64.b64encode(bilde.data).decode()})
    return Kvittering(ticket_id, saksnummer, resultat.manuell, resultat.backend)


def behandle_tegnetime(odoo: OdooClient, backend: AIBackend, skjema: dict,
                       opprettet: datetime | None = None) -> Kvittering:
    naermeste = naermeste_butikk(skjema.get("postnummer"))
    resultat = vurder_tegnetime(backend, skjema, BUTIKKNAVN, naermeste)
    v = resultat.vurdering
    butikk = skjema.get("onsket_butikk") or (v.foreslatt_butikk if v and v.foreslatt_butikk in BUTIKKNAVN else naermeste)
    prioritet = v.prioritet if v else "middels"
    start = (opprettet or datetime.now()).date()
    frist = _legg_til_virkedager(start, OPPFOLGING_DAGER[prioritet])

    partner_id = odoo.finn_eller_opprett_partner(skjema["navn"], skjema.get("epost", ""),
                                                 skjema.get("telefon", ""), skjema.get("postnummer", ""))
    lead_id = odoo.create("crm.lead", {
        "name": v.oppsummering if v else f"Tegnetime: {skjema['navn']}",
        "type": "lead",
        "contact_name": skjema["navn"],
        "email_from": skjema.get("epost", ""),
        "phone": skjema.get("telefon", ""),
        "zip": skjema.get("postnummer", ""),
        "description": skjema["beskrivelse"],
        "partner_id": partner_id,
        "priority": PRIORITET[prioritet],
        "x_butikk": butikk,
        "x_naermeste_butikk": naermeste,
        "x_onsket_butikk": skjema.get("onsket_butikk") or "",
        "x_romtype": v.romtype if v else "",
        "x_prosjekttype": v.prosjekttype if v else "",
        "x_budsjettklasse": v.budsjettklasse if v else "",
        "x_tidsramme": v.tidsramme if v else "",
        "x_prioritet": prioritet,
        "x_oppfolging_frist": frist.isoformat(),
        "x_ai_vurdering": v.model_dump_json() if v else "",
        "x_ai_backend": resultat.backend,
        "x_ai_feil": resultat.feil or "",
        "x_manuell": resultat.manuell,
        "x_kilde": "Nettskjema tegnetime",
        **_tidsstempel(opprettet),
    })
    saksnummer = f"LEAD-{lead_id:05d}"
    odoo.write("crm.lead", lead_id, {"x_saksnummer": saksnummer})
    return Kvittering(lead_id, saksnummer, resultat.manuell, resultat.backend)


def les_vurdering(post: dict) -> dict:
    try:
        return json.loads(post.get("x_ai_vurdering") or "{}")
    except json.JSONDecodeError:
        return {}

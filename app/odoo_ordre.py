"""Ordre og etterlevering i Odoo: lese en salgsordre, lagre ordresjekken, godkjenne og etterlevere.

Bruker bare standard Odoo-modeller (sale.order, sale.order.line, product.product,
stock.picking) og felt med prefiks x_ som opprettes av `python -m oppsett`.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime

from ordresjekk.avvik import Avviksresultat
from ordresjekk.modeller import Ordre, Ordrelinje, Sjekkresultat

from .odoo_client import IkkeFunnet, OdooClient

ORDREFELT = ["name", "partner_id", "state", "commitment_date", "date_order", "origin", "x_kjokkenmodell", "x_butikk",
             "x_kundens_onsker", "x_ordresjekk_status", "x_ordresjekk_json", "x_ordresjekk_tid", "x_type",
             "x_saksnummer", "x_avvik_arsak", "x_avvik_json", "x_svarutkast", "create_date"]


def hent(odoo: OdooClient, ordre_id: int) -> tuple[dict, Ordre]:
    post = odoo.read("sale.order", ordre_id, ORDREFELT)
    if not post:
        raise IkkeFunnet(f"Fant ikke salgsordre {ordre_id} i Odoo.")
    linjer = odoo.search_read("sale.order.line", [("order_id", "=", ordre_id)],
                              ["product_id", "product_uom_qty", "name"], order="id")
    produkt_ids = list({l["product_id"][0] for l in linjer if l["product_id"]})
    koder = {p["id"]: p["default_code"] for p in
             odoo.execute_kw("product.product", "read", [produkt_ids], {"fields": ["default_code"]})} if produkt_ids else {}
    levering = post.get("commitment_date") or None
    ordre = Ordre(
        navn=post["name"], modell=post.get("x_kjokkenmodell") or "", odoo_id=ordre_id,
        kunde=post["partner_id"][1] if post.get("partner_id") else "", butikk=post.get("x_butikk") or "",
        onsket_levering=date.fromisoformat(str(levering)[:10]) if levering else None,
        kundens_onsker=post.get("x_kundens_onsker") or "",
        linjer=[Ordrelinje(koder.get(l["product_id"][0]) or "UKJENT", float(l["product_uom_qty"]), l["name"] or "", l["id"])
                for l in linjer if l["product_id"]])
    return post, ordre


def liste(odoo: OdooClient, type_: str = "ordre") -> list[dict]:
    return odoo.search_read("sale.order", [("x_type", "=", type_)], ORDREFELT, order="id desc")


def produkt_ider(odoo: OdooClient, koder: list[str]) -> dict[str, int]:
    rader = odoo.search_read("product.product", [("default_code", "in", koder)], ["default_code"])
    return {r["default_code"]: r["id"] for r in rader}


def post_notat(odoo: OdooClient, modell: str, rid: int, tekst: str) -> None:
    odoo.execute_kw(modell, "message_post", [[rid]], {"body": tekst, "message_type": "comment",
                                                      "subtype_xmlid": "mail.mt_note"})


def lagre_sjekk(odoo: OdooClient, ordre_id: int, resultat: Sjekkresultat) -> None:
    odoo.write("sale.order", ordre_id, {
        "x_ordresjekk_status": resultat.status,
        "x_ordresjekk_json": json.dumps(asdict(resultat), ensure_ascii=False, default=str),
        "x_ordresjekk_tid": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    antall = {a: sum(1 for f in resultat.funn if f.alvor == a) for a in ("stopp", "avklar", "info")}
    regler = ", ".join(sorted({f.regel for f in resultat.funn})) or "ingen"
    post_notat(odoo, "sale.order", ordre_id,
               f"Ordresjekk: {resultat.status.upper()}. {antall['stopp']} stopp, {antall['avklar']} til avklaring, "
               f"{antall['info']} info. Regler som slo ut: {regler}. AI: {resultat.ai_backend}.")


def les_sjekk(post: dict) -> dict | None:
    try:
        return json.loads(post.get("x_ordresjekk_json") or "null")
    except json.JSONDecodeError:
        return None


REDIGERBAR = ("draft", "sent")


def godkjenn(odoo: OdooClient, ordre_id: int, overstyrt: str = "") -> None:
    post = odoo.read("sale.order", ordre_id, ["state", "x_ordresjekk_status"])
    if not post or post["state"] not in REDIGERBAR:
        raise ValueError("Ordren er allerede sendt til produksjon eller kansellert.")
    if not post.get("x_ordresjekk_status"):
        raise ValueError("Ordren må sjekkes før den kan godkjennes.")
    odoo.execute_kw("sale.order", "action_confirm", [[ordre_id]])
    tekst = "Godkjent for produksjon etter ordresjekk."
    if overstyrt:
        tekst += f" Funn overstyrt av selger med begrunnelse: {overstyrt}"
        odoo.write("sale.order", ordre_id, {"x_ordresjekk_status": "overstyrt"})
    post_notat(odoo, "sale.order", ordre_id, tekst)


def opprett_etterlevering(odoo: OdooClient, opprinnelig: dict, resultat: Avviksresultat, melding: str,
                          avsender: str) -> tuple[int, str]:
    ider = produkt_ider(odoo, [l.kode for l in resultat.linjer])
    ny_id = odoo.create("sale.order", {
        "partner_id": opprinnelig["partner_id"][0] if opprinnelig.get("partner_id") else False,
        "origin": opprinnelig["name"],
        "x_type": "etterlevering",
        "x_kjokkenmodell": opprinnelig.get("x_kjokkenmodell") or "",
        "x_butikk": opprinnelig.get("x_butikk") or "",
        "x_avvik_arsak": resultat.arsak,
        "x_avvik_json": json.dumps({**asdict(resultat), "melding": melding, "avsender": avsender},
                                   ensure_ascii=False),
        "order_line": [(0, 0, {"product_id": ider[l.kode], "product_uom_qty": l.antall,
                               "name": f"Etterlevering: {l.problem}, {l.kode}"}) for l in resultat.linjer if l.kode in ider],
    })
    saksnummer = f"AVV-{ny_id:05d}"
    svar = resultat.svarutkast.replace("{saksnummer}", saksnummer)
    odoo.write("sale.order", ny_id, {"x_saksnummer": saksnummer, "x_svarutkast": svar})
    if resultat.linjer:
        odoo.execute_kw("sale.order", "action_confirm", [[ny_id]])
    deler = "; ".join(f"{l.antall} × {l.kode} ({l.problem})" for l in resultat.linjer) or "ingen linjer koblet"
    post_notat(odoo, "sale.order", opprinnelig["id"],
               f"Avvik {saksnummer} meldt av {avsender}: {deler}. Årsak: {resultat.arsak}.")
    return ny_id, saksnummer


def leveranser(odoo: OdooClient, ordre_id: int) -> list[dict]:
    return odoo.search_read("stock.picking", [("sale_id", "=", ordre_id)], ["name", "state", "scheduled_date"])

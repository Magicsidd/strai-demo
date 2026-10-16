"""Ordreflyten gjennom nettsidene: sjekk, overstyring, godkjenning, avvik, etterlevering og kundestatus.

Kjører mot mock-Odoo. Settes ODOO_TEST_URL (og ODOO_TEST_DB, ODOO_TEST_USER, ODOO_TEST_PASSWORD),
kjøres den samme flyten også mot ekte Odoo, se test_ekte_odoo.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from ai.backends import FastSvarBackend
from app.main import lag_app
from app.odoo_client import OdooClient, OdooKonfig

LINJER = [("SK080202", 2), ("SK060010", 1), ("GR200054", 4), ("SO240018", 1)]
AI = FastSvarBackend({
    "ordresjekk": json.dumps({"funn": [], "oppsummering": "Ordren følger ønskene."}),
    "avvik": json.dumps({"linjer": [{"kode": "GR200054", "antall": 4, "problem": "mangler",
                                     "sitat": "det er 4 håndtak og 8 fronter"}],
                         "arsak": "ordrefeil", "arsak_begrunnelse": "Levert som bestilt.", "kan_monteres_videre": True,
                         "uklart": [], "svarutkast": "Hei, saken har nummer {saksnummer}. Vennlig hilsen, Strai"}),
})


def lag_ordre(odoo: OdooClient) -> int:
    ider = {}
    for kode, _ in LINJER:
        treff = odoo.search_read("product.product", [("default_code", "=", kode)], ["id"], limit=1)
        ider[kode] = treff[0]["id"] if treff else odoo.create("product.product", {"name": kode, "default_code": kode,
                                                                                  "type": "consu"})
    partner = odoo.finn_eller_opprett_partner("Silje Test", "silje.test@eksempel.no")
    return odoo.create("sale.order", {
        "partner_id": partner, "x_type": "ordre", "x_kjokkenmodell": "Senja", "x_butikk": "Strai Oslo",
        "x_kundens_onsker": "Håndtak i sort på alle dører og skuffer.",
        "order_line": [(0, 0, {"product_id": ider[k], "product_uom_qty": a}) for k, a in LINJER]})


def rydd(odoo: OdooClient, ider: list[int]) -> None:
    """Fjerner testordrene, så testen kan kjøres mot en Odoo med demodata uten å rote dem til."""
    for oid in ider:
        if odoo.read("sale.order", oid, ["state"])["state"] != "cancel":
            if isinstance(odoo.execute_kw("sale.order", "action_cancel", [[oid]]), dict):
                odoo.write("sale.order", oid, {"state": "cancel"})
    odoo.execute_kw("sale.order", "unlink", [ider])


def kjor_flyten(odoo: OdooClient) -> None:
    oid = lag_ordre(odoo)
    try:
        _flyten(odoo, oid)
    finally:
        if not str(odoo.versjon().get("server_version", "")).endswith("mock"):
            etter = [o["id"] for o in odoo.search_read("sale.order", [("origin", "=", odoo.read("sale.order", oid, ["name"])["name"])], ["id"])]
            rydd(odoo, etter + [oid])


def _flyten(odoo: OdooClient, oid: int) -> None:
    klient = TestClient(lag_app(odoo=odoo, backend=AI, odoo_ordre=odoo))

    side = klient.get(f"/ordre/{oid}")
    assert side.status_code == 200 and "Kjør ordresjekk" in side.text and "SK080202" in side.text

    assert klient.post(f"/ordre/{oid}/sjekk", follow_redirects=False).status_code == 303
    post = odoo.read("sale.order", oid, ["x_ordresjekk_status", "x_ordresjekk_json"])
    sjekk = json.loads(post["x_ordresjekk_json"])
    assert post["x_ordresjekk_status"] == "avklar" and [f["regel"] for f in sjekk["funn"]] == ["R10"]

    # Uten begrunnelse skal ordren ikke kunne sendes til produksjon.
    svar = klient.post(f"/ordre/{oid}/godkjenn", data={"begrunnelse": ""}, follow_redirects=False)
    assert "begrunnelse" in svar.headers["location"]
    assert odoo.read("sale.order", oid, ["state"])["state"] == "draft"

    klient.post(f"/ordre/{oid}/godkjenn", data={"begrunnelse": "Kunden bekreftet på telefon."})
    post = odoo.read("sale.order", oid, ["state", "x_ordresjekk_status", "name"])
    assert post["state"] == "sale" and post["x_ordresjekk_status"] == "overstyrt"
    assert odoo.search_count("stock.picking", [("sale_id", "=", oid)]) >= 1

    svar = klient.post(f"/ordre/{oid}/avvik", data={"melding": "Har montert alt, men det er 4 håndtak og 8 fronter.",
                                                    "avsender": "montør"}, follow_redirects=False)
    avvik_id = int(svar.headers["location"].rsplit("/", 1)[1])
    avvik = odoo.read("sale.order", avvik_id, ["x_saksnummer", "origin", "x_type", "state", "x_svarutkast"])
    assert avvik["origin"] == post["name"] and avvik["x_type"] == "etterlevering" and avvik["state"] == "sale"
    assert avvik["x_saksnummer"] in avvik["x_svarutkast"]

    side = klient.get(f"/avvik/{avvik_id}")
    assert side.status_code == 200 and "Ordresjekken varslet om dette før produksjon" in side.text
    assert klient.get(f"/status/{avvik['x_saksnummer']}").status_code == 200
    assert klient.get("/dashbord").status_code == 200 and klient.get("/ai-logg").status_code == 200

    notater = odoo.search_read("mail.message", [("model", "=", "sale.order"), ("res_id", "=", oid)], ["body"])
    tekst = " ".join(str(n["body"]) for n in notater)
    assert "Ordresjekk" in tekst and "overstyrt" in tekst and avvik["x_saksnummer"] in tekst


def test_ordreflyten_mot_mock(odoo):
    kjor_flyten(odoo)


@pytest.mark.skipif(not os.environ.get("ODOO_TEST_URL"), reason="Sett ODOO_TEST_URL for å teste mot ekte Odoo")
def test_ordreflyten_mot_ekte_odoo():
    kjor_flyten(OdooClient(OdooKonfig(os.environ["ODOO_TEST_URL"], os.environ.get("ODOO_TEST_DB", "strai"),
                                      os.environ.get("ODOO_TEST_USER", "admin"),
                                      os.environ.get("ODOO_TEST_PASSWORD", "admin"))))

"""Hele flyten med falskt AI-svar: skjema inn, sak i mock-Odoo, saksnummer ut, sider rendres."""
import json

from fastapi.testclient import TestClient

from ai.backends import FastSvarBackend
from app.main import lag_app

AI_SVAR = {
    "reklamasjon": "Her kommer JSON:\n" + json.dumps({
        "feiltype": "skrog", "berort_komponent": "Skap under vask", "alvorlighet": "høy",
        "sannsynlig_arsak": "Lekkasje fra vannlås.", "foreslatt_tiltak": "Bytt bunnplate.",
        "reservedel": "Bunnplate 60 cm", "ruting": "fabrikk", "ruting_begrunnelse": "Ny del.",
        "oppsummering": "Svellet bunn i vaskeskap",
        "svarutkast": "Hei Ingrid,\n\nsaken din har saksnummer {saksnummer}.\n\nVennlig hilsen,\nStrai Kristiansand",
        "sikkerhet": 0.9}, ensure_ascii=False),
    "tegnetime": json.dumps({
        "romtype": "kjøkken", "prosjekttype": "renovering", "budsjettklasse": "150 000 til 300 000 kr",
        "tidsramme": "innen 3 måneder", "prioritet": "høy", "foreslatt_butikk": "Strai Kristiansand",
        "begrunnelse": "Kort tidsramme.", "oppsummering": "Oppussing før jul",
        "forslag_forste_kontakt": "Ring i dag og avtal tegnetime."}, ensure_ascii=False),
}

# Minste gyldige PNG (1x1 piksel)
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")


def test_reklamasjon_hele_veien(odoo):
    odoo.create("sale.order", {"name": "SO-24830", "x_kjokkenmodell": "Bris"})
    klient = TestClient(lag_app(odoo=odoo, backend=FastSvarBackend(AI_SVAR)))

    svar = klient.post("/reklamasjon", headers={"Accept": "application/json"}, data={
        "kundenavn": "Ingrid Haugland", "epost": "ingrid@eksempel.no", "ordrenummer": "so-24830",
        "butikk": "Strai Kristiansand", "fritekst": "Bunnen i skapet under vasken har svellet."},
        files=[("bilder", ("vask.png", PNG, "image/png"))])
    assert svar.status_code == 201, svar.text
    kvittering = svar.json()
    assert kvittering["saksnummer"] == "REK-00001" and not kvittering["trenger_manuell_vurdering"]

    sak = odoo.read("helpdesk.ticket", kvittering["odoo_id"])
    assert sak["x_kjokkenmodell"] == "Bris"  # slått opp fra ordren i Odoo
    assert sak["x_feiltype"] == "skrog" and sak["priority"] == "3" and sak["x_ruting"] == "fabrikk"
    assert "REK-00001" in sak["x_svarutkast"] and "{saksnummer}" not in sak["x_svarutkast"]
    vedlegg = odoo.search_read("ir.attachment", [("res_id", "=", sak["id"])], ["name"])
    assert [v["name"] for v in vedlegg] == ["vask.png"]

    side = klient.get(f"/saker/{sak['id']}")
    assert side.status_code == 200 and "Svellet bunn i vaskeskap" in side.text and "Bunnplate 60 cm" in side.text
    assert klient.get(f"/vedlegg/{vedlegg[0]['id']}").content == PNG

    lagret = klient.post(f"/saker/{sak['id']}", data={"svarutkast": "Redigert svar", "stage_id": 2},
                         follow_redirects=False)
    assert lagret.status_code == 303
    assert odoo.read("helpdesk.ticket", sak["id"], ["x_svarutkast"])["x_svarutkast"] == "Redigert svar"

    dashbord = klient.get("/dashbord")
    assert dashbord.status_code == 200 and "Bris" in dashbord.text


def test_tegnetime_hele_veien(odoo):
    klient = TestClient(lag_app(odoo=odoo, backend=FastSvarBackend(AI_SVAR)))
    svar = klient.post("/tegnetime", headers={"Accept": "application/json"}, data={
        "navn": "Thomas Eikeland", "epost": "thomas@eksempel.no", "postnummer": "4631",
        "beskrivelse": "Pusse opp kjøkkenet før jul."})
    assert svar.status_code == 201
    lead = odoo.read("crm.lead", svar.json()["odoo_id"])
    assert lead["x_butikk"] == "Strai Kristiansand" and lead["x_prioritet"] == "høy"
    assert lead["x_oppfolging_frist"] and lead["x_saksnummer"] == "LEAD-00001"
    assert klient.get(f"/leads/{lead['id']}").status_code == 200


def test_ugyldig_ai_svar_gir_manuell_sak_ikke_tap(odoo):
    klient = TestClient(lag_app(odoo=odoo, backend=FastSvarBackend({"reklamasjon": "Beklager, ingen JSON."})))
    svar = klient.post("/reklamasjon", headers={"Accept": "application/json"}, data={
        "kundenavn": "Per", "epost": "per@eksempel.no", "butikk": "Strai Oslo", "fritekst": "Noe er galt."})
    assert svar.status_code == 201 and svar.json()["trenger_manuell_vurdering"]
    sak = odoo.read("helpdesk.ticket", svar.json()["odoo_id"])
    assert sak["x_feiltype"] == "Trenger manuell vurdering" and sak["description"] == "Noe er galt."
    assert "Trenger manuell vurdering" in klient.get(f"/saker/{sak['id']}").text


def test_skjema_uten_json_header_sender_til_kvittering(odoo):
    klient = TestClient(lag_app(odoo=odoo, backend=FastSvarBackend(AI_SVAR)))
    svar = klient.post("/tegnetime", data={"navn": "Ola", "telefon": "900 00 000", "postnummer": "0458",
                                           "beskrivelse": "Nytt kjøkken."}, follow_redirects=False)
    assert svar.status_code == 303 and svar.headers["location"].startswith("/kvittering/tegnetime/")
    assert "LEAD-00001" in klient.get(svar.headers["location"]).text

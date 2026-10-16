"""odoo_client mot mock-Odoo over ekte HTTP og JSON-RPC."""
import pytest

from app.odoo_client import OdooClient, OdooFeil, OdooKonfig


def test_versjon_og_innlogging(odoo):
    assert odoo.versjon()["server_serie"] == "18.0"
    assert odoo.uid == 2


def test_feil_passord_gir_tydelig_feil(mock_odoo_url):
    klient = OdooClient(OdooKonfig(mock_odoo_url, "strai", "demo@strai.no", "feil"))
    with pytest.raises(OdooFeil, match="Innlogging"):
        klient.search_read("res.partner")


def test_utilgjengelig_odoo(tmp_path):
    klient = OdooClient(OdooKonfig("http://127.0.0.1:9", "strai", "x", "y"), timeout=1)
    with pytest.raises(OdooFeil, match="kontakt"):
        klient.versjon()


def test_create_search_read_write(odoo):
    partner = odoo.create("res.partner", {"name": "Kari Solberg", "email": "kari@eksempel.no"})
    sak = odoo.create("helpdesk.ticket", {"name": "Lakksprekk", "partner_id": partner, "priority": "2",
                                          "x_butikk": "Strai Oslo"})
    rad = odoo.read("helpdesk.ticket", sak, ["name", "partner_id", "stage_id", "ticket_ref"])
    assert rad["partner_id"] == [partner, "Kari Solberg"]  # many2one som i ekte Odoo
    assert rad["stage_id"][1] == "Ny" and rad["ticket_ref"] == "00001"

    assert odoo.write("helpdesk.ticket", sak, {"priority": "3"}) is True
    treff = odoo.search_read("helpdesk.ticket", [("priority", "=", "3")], ["name"])
    assert [t["id"] for t in treff] == [sak]


def test_domener_med_operatorer(odoo):
    for navn, pri in [("A", "1"), ("B", "2"), ("C", "3")]:
        odoo.create("crm.lead", {"name": navn, "priority": pri, "x_butikk": "Strai Bergen" if navn != "C" else "Strai Oslo"})
    assert odoo.search_count("crm.lead", [("priority", "in", ["2", "3"])]) == 2
    assert odoo.search_count("crm.lead", ["|", ("name", "=", "A"), ("name", "=", "C")]) == 2
    assert odoo.search_count("crm.lead", [("x_butikk", "ilike", "bergen"), ("priority", ">", "1")]) == 1
    rader = odoo.search_read("crm.lead", [], ["name"], order="name desc", limit=2)
    assert [r["name"] for r in rader] == ["C", "B"]


def test_finn_eller_opprett_partner_gjenbruker(odoo):
    a = odoo.finn_eller_opprett_partner("Ola", "ola@eksempel.no")
    b = odoo.finn_eller_opprett_partner("Ola Nordmann", "ola@eksempel.no")
    assert a == b and odoo.search_count("res.partner") == 1


def test_ukjent_post_gir_feil(odoo):
    with pytest.raises(OdooFeil, match="finnes ikke"):
        odoo.write("helpdesk.ticket", 999, {"name": "x"})

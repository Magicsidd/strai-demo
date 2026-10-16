"""Regresjonstester for funnene fra den uavhengige QA-gjennomgangen. Én test per feil, så de ikke kommer tilbake."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import katalog
from ai.backends import FastSvarBackend
from ai.regelbasert import RegelbasertBackend
from app.main import lag_app
from app import odoo_ordre
from ordresjekk.avvik import enkel_tolkning, vurder_avvik
from ordresjekk.modeller import Ordre, Ordrelinje as L
from ordresjekk.regler import kjor_regler
from ordresjekk.sjekk import kandidater, kjor_ordresjekk, sitat_finnes

I_DAG = date(2026, 10, 16)


def regler(modell, linjer, uker=12):
    return kjor_regler(Ordre("T", modell, [L(k, a) for k, a in linjer], onsket_levering=I_DAG + timedelta(weeks=uker)),
                       I_DAG)


def ai_svar(*funn):
    return FastSvarBackend({"ordresjekk": json.dumps({"funn": list(funn), "oppsummering": "Test."}, ensure_ascii=False)})


# 1. Reserve eller AI-feil skal aldri gi «klar» når kunden har ønsker.
def test_regelbasert_reserve_gir_avklar_ikke_klar():
    o = Ordre("T", "Voss", [L("SK060001", 1), L("GR200052", 1), L("SO240018", 1)], kundens_onsker="Kildesortering.")
    r = kjor_ordresjekk(o, RegelbasertBackend(), I_DAG)
    assert r.status == "avklar" and any(f.regel == "AI0" for f in r.funn)
    assert "stemmer" not in r.oppsummering


def test_ugyldig_ai_svar_gir_avklar():
    o = Ordre("T", "Voss", [L("SK060001", 1), L("GR200052", 1), L("SO240018", 1)], kundens_onsker="Kildesortering.")
    r = kjor_ordresjekk(o, FastSvarBackend({"ordresjekk": "beklager"}), I_DAG)
    assert r.status == "avklar" and r.ai_feil


# 2. Sitatkontrollen.
@pytest.mark.parametrize("sitat,tekst,forventet", [
    ("...", "Vi vil ha glassdører", False),
    ("« »", "Vi vil ha glassdører", False),
    ("e fronter og ikk", "alle fronter og ikke skuffer", False),
    ("glassdører i overskapene", "Vi vil ikke ha glassdører i overskapene", False),
    ("glassdører i overskapene", "Vi vil ha glassdører i overskapene", True),
])
def test_sitatkontroll(sitat, tekst, forventet):
    assert sitat_finnes(sitat, tekst) is forventet


# 3. Kandidatlisten skal dekke alle kategorier, og Bygdøy bare egne varianter.
def test_kandidater_dekker_mikroseksjon_og_skuffeseksjon():
    k = kandidater(Ordre("T", "Voss", [L("SK060001", 2), L("OB060007", 1)]))
    assert "SM060246" in k and any(c.startswith("SS") for c in k) and any(c.startswith("SK") for c in k)


def test_kandidater_for_bygdoy_er_bare_f_varianter():
    k = kandidater(Ordre("T", "Bygdøy", [L("SK060001F", 2)]))
    assert all(c.endswith("F") or c.startswith(("HV", "BP")) for c in k)


# 4. Seksjon for platetopp avgjøres av beskrivelsen, og forslaget følger modellens variant.
@pytest.mark.parametrize("modell,seksjon", [("Voss", "KO060223"), ("Trollstigen", "DK060004T"), ("Voss", "DK060006")])
def test_gyldige_platetoppseksjoner_godtas(modell, seksjon):
    assert not [f for f in regler(modell, [("HV-IND60", 1), (seksjon, 1)]) if f.regel == "R05"]


def test_forslag_bruker_modellens_variant():
    assert [f.forslag for f in regler("Trollstigen", [("HV-IND80", 1)]) if f.regel == "R05"] == [["KO080223T"]]
    assert [f.forslag for f in regler("Bygdøy", [("HV-IND80", 1)]) if f.regel == "R05"] == [["KO080224F"]]


# 6. Etterlevering summeres per kode før taket.
def test_avvik_summeres_per_kode():
    o = Ordre("T", "Voss", [L("GR200052", 6)])
    melding = "Mangler håndtak på kjøkkenøya. Mangler også håndtak på høyskapet."
    svar = FastSvarBackend({"avvik": json.dumps({"linjer": [
        {"kode": "GR200052", "antall": 6, "problem": "mangler", "sitat": "Mangler håndtak på kjøkkenøya"},
        {"kode": "GR200052", "antall": 6, "problem": "mangler", "sitat": "Mangler også håndtak på høyskapet"}],
        "arsak": "pakking", "svarutkast": "Hei, sak {saksnummer}. Vennlig hilsen, Strai"})})
    r = vurder_avvik(o, melding, "montør", svar)
    assert [(l.kode, l.antall) for l in r.linjer] == [("GR200052", 6)]


# 7. Forslag må være blant kandidatene og følge modellreglene, også for handelsvarer.
def test_for_dyp_oppvaskmaskin_kan_ikke_foreslaas_for_trollstigen():
    o = Ordre("T", "Trollstigen", [L("SK060204", 1)], kundens_onsker="Vi vil ha en stor oppvaskmaskin på 60 cm.")
    r = kjor_ordresjekk(o, ai_svar({"type": "mangler", "alvor": "avklar", "beskrivelse": "Mangler oppvaskmaskin.",
                                    "forslag_kode": "HV-OPPV60D", "sitat": "stor oppvaskmaskin på 60 cm"}), I_DAG)
    assert [f.forslag for f in r.funn if f.regel == "AI"] == [[]]


def test_kode_utenfor_kandidatene_avvises():
    o = Ordre("T", "Voss", [L("SK060001", 1)], kundens_onsker="Vi vil ha sokkel med ben under øya.")
    r = kjor_ordresjekk(o, ai_svar({"type": "mangler", "alvor": "info", "beskrivelse": "Sokkelben mangler.",
                                    "forslag_kode": "SB300015", "sitat": "sokkel med ben under øya"}), I_DAG)
    assert [f.forslag for f in r.funn if f.regel == "AI"] == [[]] and any("SB300015" in t for t in r.forkastet)


# 8. AI-funn som slås sammen med et regelfunn, rapporteres.
def test_sammenslaatt_funn_rapporteres():
    o = Ordre("T", "Falketind", [L("HB090001H", 1)], kundens_onsker="Vi vil ha en god hjørneløsning med hylle.")
    r = kjor_ordresjekk(o, ai_svar({"type": "motstrid", "alvor": "stopp", "linje_kode": "HB090001H",
                                    "beskrivelse": "Hjørneskap ikke tilgjengelig.", "sitat": "god hjørneløsning med hylle"}),
                        I_DAG)
    assert any("R04" in t for t in r.forkastet)


# 9 og 10. Sokkel og kategorier.
def test_sokkelskuff_er_ikke_sokkel_og_hjorneskap_har_bredde_fra_koden():
    assert katalog.finn("SO060125").kategori == "sokkelskuff" and katalog.finn("SO060125").lengde_cm is None
    assert katalog.finn("HB100242").bredde_cm == 100
    funn = regler("Voss", [("SK080001", 6), ("SO060125", 2), ("GR200052", 12)])
    assert any(f.regel == "R11" for f in funn)


def test_sb_prefikset_tolkes_fra_beskrivelsen():
    assert katalog.finn("SB040002").kategori == "høyskap"
    assert katalog.finn("SB019001").kategori == "sokkeltilbehør"
    assert not [f for f in regler("Trollstigen", [("SB090015", 1)]) if f.regel == "R04"]


# 14. Små bokstaver fra Odoo.
def test_koder_med_smaa_bokstaver_normaliseres():
    funn = regler("Voss", [("hv-ind60", 1), ("ko060224", 1), ("so240018", 1)])
    assert not [f for f in funn if f.regel in ("R01", "R05", "R11")]


# 15. Bredder.
def test_bredder_sjekkes():
    assert [f.alvor for f in regler("Voss", [("HV-VASK60", 1), ("OB045007", 1)]) if f.regel == "R07"] == ["avklar"]
    assert [f.alvor for f in regler("Voss", [("HV-IND80", 1), ("KO060224", 1)]) if f.regel == "R05"] == ["avklar"]
    r08 = [f for f in regler("Voss", [("HV-OPPV45", 1), ("BD060072O", 1)]) if f.regel == "R08"]
    assert r08 and r08[0].forslag == ["BD045072O"]


# 16. Reserven forstår «fått N».
def test_reserve_regner_mottatt_mot_bestilt():
    o = Ordre("T", "Voss", [L("GR200052", 11)])
    svar = enkel_tolkning(o, "Vi har fått 7 håndtak.")
    assert [(l["kode"], l["antall"]) for l in svar["linjer"]] == [("GR200052", 4)]


# 18. Ett ugyldig funn feller ikke de andre, og grensen er 6.
def test_ugyldig_funn_feller_ikke_resten():
    o = Ordre("T", "Voss", [L("SK060001", 1)], kundens_onsker="Vi vil ha et eget skap til miksmaster og mange skuffer.")
    gyldig = {"type": "mangler", "alvor": "avklar", "beskrivelse": "Miksmasterskap mangler.",
              "sitat": "et eget skap til miksmaster"}
    r = kjor_ordresjekk(o, ai_svar({"type": "mangler", "sitat": None}, gyldig), I_DAG)
    assert len([f for f in r.funn if f.regel == "AI"]) == 1 and any("ugyldig format" in t for t in r.forkastet)


# 22 og 24. Passert dato og Dalen Premium White.
def test_passert_dato_og_dalen_med_kortere_variant():
    passert = kjor_regler(Ordre("T", "Voss", [L("SK060001", 1)], onsket_levering=I_DAG - timedelta(days=15)), I_DAG)
    assert any("passert" in f.tittel for f in passert) and not any("-15" in f.beskrivelse for f in passert)
    dalen = kjor_regler(Ordre("T", "Dalen", [L("SK060001", 1)], onsket_levering=I_DAG + timedelta(days=31)), I_DAG)
    assert [f.alvor for f in dalen if f.regel == "R12"] == ["avklar"]


# 5, 12 og 13. Nettsidene.
@pytest.fixture()
def app_mot_mock(odoo):
    pid = odoo.create("product.product", {"name": "Benkeskap", "default_code": "SK060001"})
    oid = odoo.create("sale.order", {"x_type": "ordre", "x_kjokkenmodell": "Voss",
                                     "order_line": [(0, 0, {"product_id": pid, "product_uom_qty": 1})]})
    return TestClient(lag_app(odoo=odoo, backend=RegelbasertBackend(), odoo_ordre=odoo)), odoo, oid, pid


def test_ukjent_ordre_gir_404(app_mot_mock):
    klient, *_ = app_mot_mock
    assert klient.get("/ordre/999999").status_code == 404
    assert klient.get("/status/AVV-99999").status_code == 404


def test_godkjenning_krever_sjekk_og_kan_ikke_gjentas(app_mot_mock):
    klient, odoo, oid, _ = app_mot_mock
    with pytest.raises(ValueError):
        odoo_ordre.godkjenn(odoo, oid)
    assert klient.post(f"/ordre/{oid}/godkjenn").status_code == 409
    klient.post(f"/ordre/{oid}/sjekk")
    klient.post(f"/ordre/{oid}/godkjenn", data={"begrunnelse": "Bekreftet med kunden i dag."})
    assert odoo.read("sale.order", oid, ["state"])["state"] == "sale"
    assert klient.post(f"/ordre/{oid}/godkjenn", data={"begrunnelse": "En gang til, ved et uhell."}).status_code == 409


def test_endret_ordre_maa_sjekkes_paa_nytt(app_mot_mock):
    klient, odoo, oid, pid = app_mot_mock
    klient.post(f"/ordre/{oid}/sjekk")
    odoo.create("sale.order.line", {"order_id": oid, "product_id": pid, "product_uom_qty": 2})
    svar = klient.post(f"/ordre/{oid}/godkjenn", data={"begrunnelse": "Bekreftet med kunden i dag."},
                       follow_redirects=False)
    assert "utdatert" in svar.headers["location"] and odoo.read("sale.order", oid, ["state"])["state"] == "draft"


# 11. Vedlegg.
def test_bare_bilder_kan_lastes_opp_og_vises(odoo):
    klient = TestClient(lag_app(odoo=odoo, backend=RegelbasertBackend()))
    svar = klient.post("/reklamasjon", headers={"Accept": "application/json"}, data={
        "kundenavn": "Per", "epost": "per@eksempel.no", "butikk": "Strai Oslo", "fritekst": "Noe er galt."},
        files=[("bilder", ("ondt.html", b"<script>alert(1)</script>", "text/html"))])
    assert svar.status_code == 415
    annet = odoo.create("ir.attachment", {"name": "x.png", "mimetype": "image/png", "res_model": "res.partner",
                                          "res_id": 1, "datas": "aGVp"})
    assert klient.get(f"/vedlegg/{annet}").status_code == 404

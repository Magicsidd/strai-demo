"""Kontrollene rundt AI: ugrunnede funn, oppdiktede koder og for høye antall skal stoppes."""
import json
from datetime import date

from ai.backends import FastSvarBackend
from ordresjekk.avvik import vurder_avvik
from ordresjekk.modeller import Ordre, Ordrelinje
from ordresjekk.sjekk import kjor_ordresjekk

I_DAG = date(2026, 10, 16)
ONSKER = "Vi trenger plass til mikrobølgeovnen i benkehøyde, og oppvaskmaskinen må være 45 cm."


def ordre(modell="Femunden", onsker=ONSKER):
    return Ordre("S1", modell, [Ordrelinje("SK060001", 2), Ordrelinje("HV-OPPV60", 1), Ordrelinje("BD060072O", 1),
                                Ordrelinje("GR200052", 2), Ordrelinje("SO240018", 1)], kundens_onsker=onsker,
                 butikk="Strai Oslo")


def svar(*funn):
    return FastSvarBackend({"ordresjekk": json.dumps({"funn": list(funn), "oppsummering": "Test."}, ensure_ascii=False)})


def funn(**kw):
    return {"type": "mangler", "alvor": "avklar", "linje_kode": None, "beskrivelse": "Noe mangler her.",
            "forslag_kode": None, "sitat": "plass til mikrobølgeovnen i benkehøyde", **kw}


def test_grunnet_funn_med_gyldig_forslag_slipper_gjennom():
    r = kjor_ordresjekk(ordre(), svar(funn(forslag_kode="SM060246")), I_DAG)
    ai = [f for f in r.funn if f.regel == "AI"]
    assert len(ai) == 1 and ai[0].forslag == ["SM060246"] and r.status == "avklar"


def test_sitat_som_ikke_finnes_i_onskene_forkastes():
    r = kjor_ordresjekk(ordre(), svar(funn(sitat="kunden vil ha induksjon")), I_DAG)
    assert not [f for f in r.funn if f.regel == "AI"]
    assert any("Ugrunnet" in t for t in r.forkastet)


def test_oppdiktet_kode_fjernes_men_funnet_beholdes():
    r = kjor_ordresjekk(ordre(), svar(funn(forslag_kode="MW999999")), I_DAG)
    ai = [f for f in r.funn if f.regel == "AI"]
    assert ai and ai[0].forslag == [] and any("MW999999" in t for t in r.forkastet)


def test_forslag_som_modellen_ikke_tilbyr_fjernes():
    o = ordre(modell="Lindøya", onsker="Vi vil ha mange skuffer i fire skuffers seksjon.")
    r = kjor_ordresjekk(o, svar(funn(sitat="mange skuffer", forslag_kode="SS060204")), I_DAG)
    ai = [f for f in r.funn if f.regel == "AI"]
    assert ai and ai[0].forslag == [] and any("SS060204" in t and "Lindøya" in t for t in r.forkastet)


def test_linjekode_som_ikke_er_paa_ordren_fjernes():
    r = kjor_ordresjekk(ordre(), svar(funn(linje_kode="OB060007")), I_DAG)
    assert [f for f in r.funn if f.regel == "AI"][0].linjer == []


def test_ai_som_ikke_svarer_stopper_ikke_reglene():
    class Nede:
        navn = "claude_cli"

        def fullfor(self, *a):
            raise RuntimeError("401 OAuth access token has expired")

    o = ordre()
    o.linjer.append(Ordrelinje("HB090001H", 1))
    r = kjor_ordresjekk(Ordre(o.navn, "Falketind", o.linjer, kundens_onsker=ONSKER), Nede(), I_DAG)
    assert "401" in r.ai_feil and r.status == "stopp" and any(f.regel == "R04" for f in r.funn)


def test_uten_onsker_kalles_ikke_ai():
    class Forbudt:
        navn = "forbudt"

        def fullfor(self, *a):
            raise AssertionError("AI skal ikke kalles uten ønsker")

    assert kjor_ordresjekk(ordre(onsker=""), Forbudt(), I_DAG).ai_feil is None


AVVIK_ORDRE = Ordre("S2", "Voss", [Ordrelinje("GR200052", 11), Ordrelinje("SS060204", 1), Ordrelinje("SO240018", 2)],
                    butikk="Strai Kristiansand")
MELDING = "Kolli 4 manglet helt. Vi har fått 7 håndtak, og den ene skuffeseksjonen kom med bulk."


def avvik_svar(linjer, arsak="pakking"):
    return FastSvarBackend({"avvik": json.dumps({
        "linjer": linjer, "arsak": arsak, "arsak_begrunnelse": "Kolli manglet.", "kan_monteres_videre": True,
        "uklart": [], "svarutkast": "Hei, saken har nummer {saksnummer}. Vennlig hilsen, Strai"}, ensure_ascii=False)})


def test_avvik_kobles_til_ordrelinjer():
    r = vurder_avvik(AVVIK_ORDRE, MELDING, "montør", avvik_svar([
        {"kode": "GR200052", "antall": 4, "problem": "mangler", "sitat": "Vi har fått 7 håndtak"},
        {"kode": "SS060204", "antall": 1, "problem": "skadet", "sitat": "skuffeseksjonen kom med bulk"}]))
    assert [(l.kode, l.antall) for l in r.linjer] == [("GR200052", 4), ("SS060204", 1)] and not r.forkastet


def test_avvik_kan_ikke_overstige_bestilt_antall():
    r = vurder_avvik(AVVIK_ORDRE, MELDING, "montør", avvik_svar([
        {"kode": "SS060204", "antall": 3, "problem": "skadet", "sitat": "skuffeseksjonen kom med bulk"}]))
    assert r.linjer[0].antall == 1 and "bare 1 er bestilt" in r.forkastet[0]


def test_avvik_paa_kode_som_ikke_er_bestilt_blir_uklart():
    r = vurder_avvik(AVVIK_ORDRE, MELDING, "montør", avvik_svar([
        {"kode": "OB060007", "antall": 1, "problem": "mangler", "sitat": "Kolli 4 manglet helt"}]))
    assert r.linjer == [] and any("OB060007" in u for u in r.uklart)

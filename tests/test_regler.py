"""De faste reglene mot fasiten i demoordrene, og enkeltregler med kjente grensetilfeller."""
from datetime import date, timedelta

import pytest

import katalog
from demo.ordre_data import ORDRER
from katalog.bygg import antall_fronter
from ordresjekk.modeller import Ordre, Ordrelinje
from ordresjekk.regler import kjor_regler

I_DAG = date(2026, 10, 16)


def ordre(modell, linjer, uker=10, onsker=""):
    return Ordre("TEST", modell, [Ordrelinje(k, a) for k, a in linjer], onsket_levering=I_DAG + timedelta(weeks=uker),
                 kundens_onsker=onsker)


@pytest.mark.parametrize("data", ORDRER, ids=[f"{o[2]}-{i}" for i, o in enumerate(ORDRER)])
def test_demoordrene_gir_fasitens_regelfunn(data):
    _, _, modell, uker, onsker, linjer, fasit = data
    funn = kjor_regler(ordre(modell, linjer, uker, onsker), I_DAG)
    assert sorted({f.regel for f in funn}) == sorted(fasit["regler"])


def test_katalogen_er_bygget_og_har_kjente_elementer():
    assert len(katalog.alle()) > 1500
    e = katalog.finn("SK080202")
    assert e.kategori == "benkeskap" and e.bredde_cm == 80 and e.fronter == 3


@pytest.mark.parametrize("tekst,forventet", [
    ("Benkeskap 60 cm m / dør", 1), ("Benkeskap 80 cm m / 2 dører+1 skuff", 3),
    ("Skuffeseksjon 60 cm m / 4 skuffer (1+3)", 4), ("Kolonialseksjon 60 cm m / 2 skuffer", 2),
    ("Oppvaskskap 60 cm m / 3D front og kildesortering", None), ("Overskap 60 cm m / glassdør", None),
])
def test_antall_fronter_teller_bare_det_vi_er_sikre_paa(tekst, forventet):
    assert antall_fronter(tekst) == forventet


def test_modellbegrensning_siterer_side_og_samler_brudd_per_linje():
    funn = kjor_regler(ordre("Trollstigen", [("OS060002", 1), ("GR200052", 1)]), I_DAG)
    r04 = [f for f in funn if f.regel == "R04"]
    assert len(r04) == 1 and "hengslede dører" in r04[0].tittel and "overskap" in r04[0].tittel
    assert "s. 12" in r04[0].kilde


def test_dor_til_oppvaskmaskin_er_ikke_en_hengslet_skapdor():
    assert not katalog.er_hengslet_dor(katalog.finn("BD060072O"))
    assert katalog.er_hengslet_dor(katalog.finn("SK060001"))


def test_platetopp_uten_seksjon_foreslaar_riktig_bredde():
    funn = kjor_regler(ordre("Voss", [("HV-IND80", 1), ("KO080204", 1), ("GR200052", 2), ("SO240018", 1)]), I_DAG)
    r05 = next(f for f in funn if f.regel == "R05")
    assert r05.alvor == "stopp" and r05.forslag == ["KO080224"]


def test_handtak_hoppes_over_for_modeller_med_grep():
    assert not [f for f in kjor_regler(ordre("Falketind", [("SK080202", 2), ("SO240018", 1)]), I_DAG)
                if f.regel == "R10"]


def test_leveringstid_er_grensetilfelle_paa_dagen():
    akkurat = ordre("Voss", [("SK060001", 1), ("GR200052", 1), ("SO240018", 1)], uker=4)
    for_tidlig = Ordre("T", "Voss", akkurat.linjer, onsket_levering=I_DAG + timedelta(weeks=4, days=-1))
    assert not [f for f in kjor_regler(akkurat, I_DAG) if f.regel == "R12"]
    assert [f for f in kjor_regler(for_tidlig, I_DAG) if f.regel == "R12"]


def test_ukjent_kode_og_ugyldig_antall_stopper():
    funn = kjor_regler(ordre("Voss", [("XX999999", 1), ("SK060001", 0)]), I_DAG)
    assert {"R01", "R02"} <= {f.regel for f in funn}

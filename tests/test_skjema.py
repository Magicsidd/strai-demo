"""Pydantic-skjemaene og robust parsing av AI-svar."""
import json

import pytest
from pydantic import ValidationError

from ai.backends import FastSvarBackend
from ai.modeller import ReklamasjonVurdering, TegnetimeVurdering
from ai.regelbasert import RegelbasertBackend
from ai.tjeneste import hent_json, last_prompt, vurder_reklamasjon, vurder_tegnetime

GYLDIG_REKLAMASJON = {
    "feiltype": "front", "berort_komponent": "Overskap ved vask", "alvorlighet": "middels",
    "sannsynlig_arsak": "Fukt fra oppvaskmaskin.", "foreslatt_tiltak": "Bestill ny front.",
    "reservedel": "Front Linje hvit", "ruting": "fabrikk", "ruting_begrunnelse": "Ny del må lages.",
    "oppsummering": "Lakksprekk på front", "svarutkast": "Hei Kari, saken har nummer {saksnummer}. Hilsen Strai",
    "sikkerhet": 0.8,
}
GYLDIG_LEAD = {
    "romtype": "kjøkken", "prosjekttype": "nybygg", "budsjettklasse": "over 300 000 kr",
    "tidsramme": "innen 3 måneder", "prioritet": "høy", "foreslatt_butikk": "Strai Oslo",
    "begrunnelse": "Nybygg med kort frist.", "oppsummering": "Nybygg i Oslo",
    "forslag_forste_kontakt": "Ring i dag og be om tegninger.",
}
SKJEMA = {"kundenavn": "Kari Solberg", "epost": "kari@eksempel.no", "ordrenummer": "SO-1",
          "butikk": "Strai Oslo", "fritekst": "Lakken har sprukket på fronten."}


def test_gyldig_reklamasjon_valideres():
    v = ReklamasjonVurdering.model_validate(GYLDIG_REKLAMASJON)
    assert v.feiltype == "front" and v.ruting == "fabrikk"


def test_ascii_varianter_normaliseres():
    v = ReklamasjonVurdering.model_validate({**GYLDIG_REKLAMASJON, "alvorlighet": "Hoy", "ruting": "montor"})
    assert v.alvorlighet == "høy" and v.ruting == "montør"


@pytest.mark.parametrize("felt,verdi", [("feiltype", "dør"), ("alvorlighet", "kritisk"), ("sikkerhet", 1.4),
                                        ("ruting", "kunde")])
def test_ulovlige_verdier_avvises(felt, verdi):
    with pytest.raises(ValidationError):
        ReklamasjonVurdering.model_validate({**GYLDIG_REKLAMASJON, felt: verdi})


def test_lead_validering():
    assert TegnetimeVurdering.model_validate(GYLDIG_LEAD).prioritet == "høy"
    with pytest.raises(ValidationError):
        TegnetimeVurdering.model_validate({**GYLDIG_LEAD, "budsjettklasse": "1 million"})


def test_hent_json_taaler_kodeblokk_og_prat():
    tekst = "Her er vurderingen:\n```json\n" + json.dumps(GYLDIG_REKLAMASJON) + "\n```\nSi fra om noe mer."
    assert hent_json(tekst)["feiltype"] == "front"


def test_hent_json_hopper_over_ugyldige_klammer():
    assert hent_json("Svar {ikke json} og så " + json.dumps({"a": 1})) == {"a": 1}


def test_hent_json_uten_objekt_feiler():
    with pytest.raises(ValueError):
        hent_json("Beklager, jeg kan ikke svare på det.")


def test_prompt_deles_og_fylles():
    system, bruker = last_prompt("reklamasjon", {"kundenavn": "Kari", "fritekst": "Feil", "ordrenummer": "SO-1",
                                                 "kjokkenmodell": "Linje", "butikk": "Strai Oslo", "antall_bilder": 0})
    assert "Strai Kjøkken" in system and "Eksempel" not in system
    assert "Kunde: Kari." in bruker and "{saksnummer}" in bruker  # plassholderen skal stå igjen


def test_fallback_ved_ugyldig_svar_gir_manuell_vurdering():
    resultat = vurder_reklamasjon(FastSvarBackend({"reklamasjon": "Jeg vet ikke."}), SKJEMA, "Linje")
    assert resultat.manuell and resultat.vurdering is None and "JSON" in resultat.feil


def test_fallback_ved_feil_verdi():
    svar = json.dumps({**GYLDIG_REKLAMASJON, "feiltype": "romvesen"})
    resultat = vurder_reklamasjon(FastSvarBackend({"reklamasjon": svar}), SKJEMA, "Linje")
    assert resultat.manuell and "feiltype" in resultat.feil


def test_fallback_naar_backend_kaster():
    class Nede:
        navn = "claude_cli"

        def fullfor(self, *a):
            raise RuntimeError("401 OAuth access token has expired")

    resultat = vurder_tegnetime(Nede(), {"navn": "Ola", "beskrivelse": "Nytt kjøkken"}, ["Strai Oslo"], "Strai Oslo")
    assert resultat.manuell and "401" in resultat.feil


def test_regelbasert_gir_gyldige_svar():
    b = RegelbasertBackend()
    r = vurder_reklamasjon(b, {**SKJEMA, "fritekst": "Hengselet på overskapet er knekt og døra kan falle ned."}, "Linje")
    assert r.vurdering.feiltype == "beslag" and r.vurdering.alvorlighet == "høy" and r.vurdering.ruting == "fabrikk"
    t = vurder_tegnetime(b, {"navn": "Ola", "postnummer": "4630", "beskrivelse": "Nybygg, innflytting i november. "
                                                                                  "Budsjett 400 000 kr."},
                         ["Strai Kristiansand"], "Strai Kristiansand")
    assert t.vurdering.prosjekttype == "nybygg" and t.vurdering.prioritet == "høy"
    assert t.vurdering.budsjettklasse == "over 300 000 kr"

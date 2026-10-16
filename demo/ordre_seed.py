"""Setter opp Odoo for «Riktig levert første gang» og legger inn demoordrene.

    python -m demo.ordre_seed                 # felt, produkter, ordrer, ordresjekk og avvik
    python -m demo.ordre_seed --ai regelbasert
    python -m demo.ordre_seed --nullstill     # sletter demoordrene først

Mot ekte Odoo opprettes egne felt (x_) på sale.order via ir.model.fields, slik Odoo Studio
gjør det. Hele elementoversikten legges inn som produkter med elementkoden som intern referanse.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

import katalog
from ai import velg_backend
from app import odoo_ordre
from app.odoo_client import OdooClient, OdooFeil, OdooKonfig, er_mock
from katalog.handelsvarer import HANDELSVARER
from ordresjekk.avvik import vurder_avvik
from ordresjekk.sjekk import kjor_ordresjekk

from .ordre_data import AVVIK, ORDRER

USJEKKET = 10  # Astrid Hval, vises fram med «Kjør ordresjekk»

FELT = {
    "x_kjokkenmodell": ("char", "Kjøkkenmodell"), "x_butikk": ("char", "Butikk"),
    "x_kundens_onsker": ("text", "Kundens ønsker"), "x_ordresjekk_status": ("char", "Ordresjekk"),
    "x_ordresjekk_json": ("text", "Ordresjekk, detaljer"), "x_ordresjekk_tid": ("char", "Ordresjekk kjørt"),
    "x_type": ("char", "Ordretype"), "x_saksnummer": ("char", "Saksnummer"), "x_avvik_arsak": ("char", "Avviksårsak"),
    "x_avvik_json": ("text", "Avvik, detaljer"), "x_svarutkast": ("text", "Svarutkast"),
}


def opprett_felt(odoo: OdooClient) -> int:
    modell_id = odoo.search_read("ir.model", [("model", "=", "sale.order")], ["id"], limit=1)[0]["id"]
    finnes = {f["name"] for f in odoo.search_read("ir.model.fields", [("model", "=", "sale.order"),
                                                                     ("name", "in", list(FELT))], ["name"])}
    nye = [{"model_id": modell_id, "name": navn, "field_description": tekst, "ttype": type_, "state": "manual"}
           for navn, (type_, tekst) in FELT.items() if navn not in finnes]
    for f in nye:
        odoo.create("ir.model.fields", f)
    return len(nye)


FIRMANAVN = "Demo kjøkkenfabrikk"


def tilpass_odoo(odoo: OdooClient) -> list[str]:
    """Norsk språk, kroner og et nøytralt firmanavn, så Odoo ikke ser ut som en tom testinstallasjon."""
    endret = []
    uten_filter = {"context": {"active_test": False}}
    norsk = odoo.execute_kw("res.lang", "search_read", [[("code", "=", "nb_NO")]], {"fields": ["active"], **uten_filter})
    if norsk and not norsk[0]["active"]:
        veiviser = odoo.create("base.language.install", {"lang_ids": [(6, 0, [norsk[0]["id"]])]})
        odoo.execute_kw("base.language.install", "lang_install", [[veiviser]])
        endret.append("norsk språk")
    if odoo.read("res.users", odoo.uid, ["lang"])["lang"] != "nb_NO":
        odoo.write("res.users", odoo.uid, {"lang": "nb_NO", "tz": "Europe/Oslo"})
        endret.append("brukerspråk")
    nok = odoo.execute_kw("res.currency", "search_read", [[("name", "=", "NOK")]], {"fields": ["active"], **uten_filter})
    firma = odoo.search_read("res.company", [], ["name", "currency_id"], limit=1)[0]
    if nok and firma["currency_id"][0] != nok[0]["id"]:
        odoo.write("res.currency", nok[0]["id"], {"active": True})
        odoo.write("res.company", firma["id"], {"currency_id": nok[0]["id"]})
        endret.append("kroner")
    prislister = odoo.search_read("product.pricelist", [("currency_id", "!=", nok[0]["id"])], ["id"]) if nok else []
    if prislister:
        odoo.write("product.pricelist", [p["id"] for p in prislister], {"currency_id": nok[0]["id"]})
        endret.append("prisliste i kroner")
    if firma["name"] != FIRMANAVN:
        odoo.write("res.company", firma["id"], {"name": FIRMANAVN})
        endret.append("firmanavn")
    return endret


def opprett_produkter(odoo: OdooClient) -> int:
    finnes = {p["default_code"] for p in odoo.search_read("product.product", [("default_code", "!=", False)],
                                                          ["default_code"])}
    nye = [{"name": e.beskrivelse[:120], "default_code": e.kode} for e in katalog.alle().values() if e.kode not in finnes]
    nye += [{"name": h.beskrivelse, "default_code": h.kode} for h in HANDELSVARER.values() if h.kode not in finnes]
    for i in range(0, len(nye), 250):
        # Pris 0: demoen handler om innholdet i ordren, og vi har ikke Strai sine priser.
        odoo.execute_kw("product.product", "create", [[{**p, "type": "consu", "sale_ok": True, "purchase_ok": False,
                                                        "list_price": 0}
                                                       for p in nye[i:i + 250]]])
    return len(nye)


def nullstill(odoo: OdooClient) -> None:
    ids = [o["id"] for o in odoo.search_read("sale.order", [("x_type", "in", ["ordre", "etterlevering"])],
                                             ["id", "state"])]
    if not ids:
        return
    if not er_mock(odoo):
        # Odoo 18 kansellerer én ordre om gangen, og kan svare med en veiviser i stedet for å kansellere.
        for oid in ids:
            svar = odoo.execute_kw("sale.order", "action_cancel", [[oid]])
            if isinstance(svar, dict):
                odoo.write("sale.order", oid, {"state": "cancel"})
    odoo.execute_kw("sale.order", "unlink", [ids])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai", default=None)
    parser.add_argument("--nullstill", action="store_true")
    args = parser.parse_args()

    # Samme valg som appen: ORDRE_ODOO_* hvis satt, ellers ODOO_*.
    odoo = OdooClient(OdooKonfig.fra_miljo("ORDRE_"))
    try:
        mock = er_mock(odoo)
        odoo.uid
    except OdooFeil as feil:
        print(f"Fikk ikke kontakt med Odoo: {feil}", file=sys.stderr)
        return 1
    print(f"Odoo: {odoo.konfig.url} ({'mock' if mock else 'ekte Odoo ' + odoo.versjon()['server_version']})")
    if not mock:
        print(f"  {opprett_felt(odoo)} nye felt på sale.order")
        print(f"  Tilpasset: {', '.join(tilpass_odoo(odoo)) or 'ingenting nytt'}")
    print(f"  {opprett_produkter(odoo)} nye produkter fra elementoversikten og handelsvarer")

    if args.nullstill:
        nullstill(odoo)
    elif odoo.search_count("sale.order", [("x_type", "=", "ordre")]):
        print("Demoordrene finnes allerede. Bruk --nullstill for å starte på nytt.")
        return 0

    backend = velg_backend(args.ai)
    print(f"  AI: {backend.navn}")
    i_dag = date.today()
    alle_koder = [k for *_, linjer, _ in ORDRER for k, _ in linjer]
    ider = odoo_ordre.produkt_ider(odoo, alle_koder)
    ordre_ider = []
    for kunde, butikk, modell, uker, onsker, linjer, _ in ORDRER:
        partner = odoo.finn_eller_opprett_partner(kunde, f"{kunde.split()[0].lower()}@eksempel.no")
        levering = datetime.combine(i_dag + timedelta(weeks=uker), datetime.min.time()).replace(hour=10)
        oid = odoo.create("sale.order", {
            "partner_id": partner, "x_type": "ordre", "x_butikk": butikk, "x_kjokkenmodell": modell,
            "x_kundens_onsker": onsker, "commitment_date": levering.strftime("%Y-%m-%d %H:%M:%S"),
            "order_line": [(0, 0, {"product_id": ider[k], "product_uom_qty": a}) for k, a in linjer]})
        ordre_ider.append(oid)

    # Ordresjekk på alle unntatt én, så det finnes en usjekket ordre å vise fram.
    usjekket = {ordre_ider[USJEKKET]}
    for oid in ordre_ider:
        if oid in usjekket:
            continue
        post, ordre = odoo_ordre.hent(odoo, oid)
        resultat = kjor_ordresjekk(ordre, backend, i_dag)
        odoo_ordre.lagre_sjekk(odoo, oid, resultat)
        feil = f", AI-feil: {resultat.ai_feil[:60]}" if resultat.ai_feil else ""
        print(f"  {post['name']} {ordre.modell:<12} {resultat.status:<7} {len(resultat.funn)} funn{feil}", flush=True)

    # Godkjenn tre ordrer og meld avvik etter levering.
    for indeks, avsender, melding, _ in AVVIK:
        oid = ordre_ider[indeks]
        post, ordre = odoo_ordre.hent(odoo, oid)
        overstyrt = "" if post.get("x_ordresjekk_status") in (None, False, "klar") else \
            "Kunden ønsker det slik, bekreftet på telefon."
        odoo_ordre.godkjenn(odoo, oid, overstyrt)
        post, ordre = odoo_ordre.hent(odoo, oid)
        resultat = vurder_avvik(ordre, melding, avsender, backend)
        _, saksnummer = odoo_ordre.opprett_etterlevering(odoo, post, resultat, melding, avsender)
        print(f"  {saksnummer} for {post['name']}: {len(resultat.linjer)} linjer, årsak {resultat.arsak}", flush=True)
    print("Ferdig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

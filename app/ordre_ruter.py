"""Sider for «Riktig levert første gang»: ordresjekk før produksjon, avvik ved levering og status for kunden."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import katalog
from ai import logg
from ai.tjeneste import promptversjon
from katalog.handelsvarer import HANDELSVARER
from ordresjekk.avvik import vurder_avvik
from ordresjekk.regler import REGLER
from ordresjekk.sjekk import beskriv, kjor_ordresjekk

from . import odoo_ordre
from .odoo_client import IkkeFunnet, OdooClient, er_mock

ruter = APIRouter()
ARSAKER = ["pakking", "transport", "produksjon", "ordrefeil", "ukjent"]


def _odoo(request: Request) -> OdooClient:
    return request.app.state.odoo_ordre


def _vis(request: Request, mal: str, **kontekst):
    return request.app.state.vis(request, mal, aktiv="ordre", **kontekst)


def _odoo_lenke(request: Request, ordre_id: int) -> str | None:
    url = _odoo(request).konfig.url
    return None if er_mock(_odoo(request)) else f"{url}/odoo/sales/{ordre_id}"


def avvikskoder(detaljer: dict) -> dict[str, str]:
    return {l["kode"]: l["problem"] for l in detaljer.get("linjer", [])}


def varslet_for(sjekk: dict | None, avvikskoder: dict[str, str]) -> list[dict]:
    """Funn fra ordresjekken som pekte på det samme som avviket etter levering."""
    if not sjekk:
        return []
    treff = []
    for f in sjekk.get("funn", []):
        if set(f.get("linjer", [])) & set(avvikskoder):
            treff.append(f)
        # Håndtak og sokkel varsles som antall, ikke per linje. Da teller bare det som mangler.
        elif f.get("regel") == "R10" and any(k.startswith("GR") and p == "mangler" for k, p in avvikskoder.items()):
            treff.append(f)
        elif f.get("regel") == "R11" and any(k.startswith("SO") and p == "mangler" for k, p in avvikskoder.items()):
            treff.append(f)
    return treff


@ruter.get("/ordre", response_class=HTMLResponse)
def ordreliste(request: Request):
    odoo = _odoo(request)
    ordrer = odoo_ordre.liste(odoo, "ordre")
    etter = odoo_ordre.liste(odoo, "etterlevering")
    return _vis(request, "ordreliste.html", ordrer=ordrer, etterleveringer=etter)


@ruter.get("/ordre/{ordre_id}", response_class=HTMLResponse)
def ordreside(request: Request, ordre_id: int, melding: str = ""):
    odoo = _odoo(request)
    post, ordre = odoo_ordre.hent(odoo, ordre_id)
    sjekk = odoo_ordre.les_sjekk(post)
    per_linje: dict[str, list[dict]] = {}
    for f in (sjekk or {}).get("funn", []):
        for k in f.get("linjer", []):
            per_linje.setdefault(k, []).append(f)
    linjer = [{"kode": l.kode, "antall": l.antall, "beskrivelse": beskriv(l.kode),
               "handelsvare": l.kode in HANDELSVARER, "side": (e.side if (e := katalog.finn(l.kode)) else None),
               "funn": per_linje.get(l.kode, [])} for l in ordre.linjer]
    modell = katalog.modell(ordre.modell)
    avvik = odoo.search_read("sale.order", [("origin", "=", post["name"]), ("x_type", "=", "etterlevering")],
                             ["x_saksnummer", "x_avvik_arsak", "state"]) if post["state"] == "sale" else []
    return _vis(request, "ordre.html", post=post, ordre=ordre, linjer=linjer, sjekk=sjekk, modell=modell,
                odoo_lenke=_odoo_lenke(request, ordre_id), melding=melding, avvik=avvik,
                leveranser=odoo_ordre.leveranser(odoo, ordre_id) if post["state"] == "sale" else [])


@ruter.post("/ordre/{ordre_id}/sjekk")
def kjor_sjekk(request: Request, ordre_id: int):
    odoo = _odoo(request)
    post, ordre = odoo_ordre.hent(odoo, ordre_id)
    if post["state"] not in odoo_ordre.REDIGERBAR:
        raise HTTPException(409, "Ordren er allerede sendt til produksjon.")
    resultat = kjor_ordresjekk(ordre, request.app.state.hent_backend())
    odoo_ordre.lagre_sjekk(odoo, ordre_id, resultat)
    return RedirectResponse(f"/ordre/{ordre_id}", status_code=303)


@ruter.post("/ordre/{ordre_id}/godkjenn")
def godkjenn(request: Request, ordre_id: int, begrunnelse: str = Form("")):
    odoo = _odoo(request)
    post, ordre = odoo_ordre.hent(odoo, ordre_id)
    if post["state"] not in odoo_ordre.REDIGERBAR:
        raise HTTPException(409, "Ordren er allerede sendt til produksjon.")
    status = post.get("x_ordresjekk_status")
    if not status:
        raise HTTPException(409, "Kjør ordresjekken før ordren godkjennes.")
    if (odoo_ordre.les_sjekk(post) or {}).get("linjehash") != ordre.linjehash():
        return RedirectResponse(f"/ordre/{ordre_id}?melding=utdatert", status_code=303)
    if status in ("stopp", "avklar") and len(begrunnelse.strip()) < 10:
        return RedirectResponse(f"/ordre/{ordre_id}?melding=begrunnelse", status_code=303)
    odoo_ordre.godkjenn(odoo, ordre_id, begrunnelse.strip() if status != "klar" else "")
    return RedirectResponse(f"/ordre/{ordre_id}?melding=godkjent", status_code=303)


@ruter.post("/ordre/{ordre_id}/avvik")
def meld_avvik(request: Request, ordre_id: int, melding: str = Form(...), avsender: str = Form("montør")):
    odoo = _odoo(request)
    post, ordre = odoo_ordre.hent(odoo, ordre_id)
    if post["state"] != "sale":
        raise HTTPException(409, "Avvik kan bare meldes på en bekreftet ordre.")
    if len(melding.strip()) < 10:
        raise HTTPException(422, "Beskriv avviket.")
    resultat = vurder_avvik(ordre, melding, avsender, request.app.state.hent_backend())
    ny_id, _ = odoo_ordre.opprett_etterlevering(odoo, post, resultat, melding, avsender)
    return RedirectResponse(f"/avvik/{ny_id}", status_code=303)


@ruter.get("/avvik/{avvik_id}", response_class=HTMLResponse)
def avviksside(request: Request, avvik_id: int):
    odoo = _odoo(request)
    post, ordre = odoo_ordre.hent(odoo, avvik_id)
    if post.get("x_type") != "etterlevering":
        raise IkkeFunnet(f"{post['name']} er ikke en etterlevering.")
    detaljer = json.loads(post.get("x_avvik_json") or "{}")
    opprinnelig = odoo.search_read("sale.order", [("name", "=", post.get("origin"))], odoo_ordre.ORDREFELT, limit=1)
    opprinnelig = opprinnelig[0] if opprinnelig else None
    sjekk = odoo_ordre.les_sjekk(opprinnelig) if opprinnelig else None
    varslet = varslet_for(sjekk, avvikskoder(detaljer))
    return _vis(request, "avvik.html", post=post, ordre=ordre, d=detaljer, opprinnelig=opprinnelig, varslet=varslet,
                beskriv=beskriv, leveranser=odoo_ordre.leveranser(odoo, avvik_id),
                odoo_lenke=_odoo_lenke(request, avvik_id))


@ruter.get("/status/{saksnummer}", response_class=HTMLResponse)
def kundestatus(request: Request, saksnummer: str):
    odoo = _odoo(request)
    treff = odoo.search_read("sale.order", [("x_saksnummer", "=", saksnummer.upper())], odoo_ordre.ORDREFELT, limit=1)
    if not treff:
        raise IkkeFunnet(f"Fant ingen sak med nummer {saksnummer}.")
    post = treff[0]
    detaljer = json.loads(post.get("x_avvik_json") or "{}")
    tilstander = {l["state"] for l in odoo_ordre.leveranser(odoo, post["id"])}
    steg = [("Avvik registrert", True), ("Deler bestilt", post["state"] == "sale"),
            ("Klar til utkjøring", bool(tilstander & {"assigned", "done"})), ("Levert", "done" in tilstander)]
    return request.app.state.vis(request, "status.html", aktiv="", kundevisning=True, post=post, d=detaljer, steg=steg,
                                 beskriv=beskriv)


@ruter.get("/ai-logg", response_class=HTMLResponse)
def ai_logg(request: Request):
    poster = logg.les(80)
    for p in poster:  # loggen er i UTC, siden viser lokal tid
        p["lokal_tid"] = datetime.fromisoformat(p["tid"]).astimezone().strftime("%H.%M")
    versjoner = {o: promptversjon(o) for o in ("reklamasjon", "tegnetime", "ordresjekk", "avvik")}
    per_oppgave = Counter(p["oppgave"] for p in poster)
    gyldige = sum(1 for p in poster if p.get("gyldig"))
    return _vis(request, "ai_logg.html", poster=poster, versjoner=versjoner, per_oppgave=per_oppgave,
                gyldige=gyldige, regler=REGLER)


def ordre_dashbord(odoo: OdooClient) -> dict:
    ordrer = odoo_ordre.liste(odoo, "ordre")
    etter = odoo_ordre.liste(odoo, "etterlevering")
    sjekket = [o for o in ordrer if o.get("x_ordresjekk_status")]
    per_regel: Counter = Counter()
    for o in sjekket:
        for f in (odoo_ordre.les_sjekk(o) or {}).get("funn", []):
            per_regel[f["regel"]] += 1
    navn = {rid: tittel for rid, tittel, _ in REGLER}
    regelrader = []
    for regel, n in per_regel.most_common():
        tittel = next((t for rid, t in navn.items() if regel in rid.split("/")), "Kundens ønsker (AI)")
        regelrader.append({"regel": regel, "tittel": tittel, "antall": n})
    arsaker = Counter(o.get("x_avvik_arsak") or "ukjent" for o in etter)
    varslet = 0
    for a in etter:
        opprinnelig = next((o for o in ordrer if o["name"] == a.get("origin")), None)
        koder = avvikskoder(json.loads(a.get("x_avvik_json") or "{}"))
        if opprinnelig and varslet_for(odoo_ordre.les_sjekk(opprinnelig), koder):
            varslet += 1
    return {
        "ordre_antall": len(ordrer), "ordre_sjekket": len(sjekket),
        "ordre_status": Counter(o["x_ordresjekk_status"] for o in sjekket),
        "regelrader": regelrader, "regel_maks": max((r["antall"] for r in regelrader), default=1),
        "avvik_antall": len(etter), "arsaker": [(a, arsaker.get(a, 0)) for a in ARSAKER],
        "arsak_maks": max(arsaker.values(), default=1), "avvik_varslet": varslet,
    }

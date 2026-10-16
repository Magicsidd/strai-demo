"""FastAPI-backend: to inntak (reklamasjon og tegnetime), saksliste, saksvisning og dashbord.

Start:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import base64
from html import escape
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ai import Bilde, velg_backend
from ai.modeller import FEILTYPER
from ai.typer import AIBackend

from .butikker import BUTIKKER, BUTIKKNAVN, kort_navn
from .odoo_client import IkkeFunnet, OdooClient, OdooFeil, OdooKonfig, er_mock
from .ordre_ruter import ordre_dashbord, ruter
from .pipeline import Kvittering, behandle_reklamasjon, behandle_tegnetime, les_vurdering

ROT = Path(__file__).parent
MAKS_BILDER = 10
MAKS_BILDESTORRELSE = 8 * 1024 * 1024
BILDETYPER = {"image/jpeg", "image/png", "image/webp", "image/gif"}

TICKET_FELT = ["name", "description", "partner_name", "partner_email", "priority", "stage_id", "create_date",
               "ticket_ref", "x_saksnummer", "x_ordrenummer", "x_butikk", "x_kjokkenmodell", "x_feiltype",
               "x_alvorlighet", "x_ruting", "x_ai_vurdering", "x_ai_backend", "x_ai_feil", "x_manuell",
               "x_svarutkast", "x_antall_bilder", "x_kilde"]
LEAD_FELT = ["name", "contact_name", "email_from", "phone", "zip", "description", "priority", "stage_id",
             "create_date", "x_saksnummer", "x_butikk", "x_naermeste_butikk", "x_onsket_butikk", "x_romtype",
             "x_prosjekttype", "x_budsjettklasse", "x_tidsramme", "x_prioritet", "x_oppfolging_frist",
             "x_ai_vurdering", "x_ai_backend", "x_ai_feil", "x_manuell", "x_kilde"]

MANEDER = ["jan.", "feb.", "mars", "apr.", "mai", "juni", "juli", "aug.", "sep.", "okt.", "nov.", "des."]


def _dato(verdi: str | None, med_tid: bool = False) -> str:
    if not verdi:
        return ""
    try:
        d = datetime.fromisoformat(str(verdi).replace(" ", "T"))
    except ValueError:
        return str(verdi)
    tekst = f"{d.day}. {MANEDER[d.month - 1]}"
    if d.year != date.today().year:
        tekst += f" {d.year}"
    return f"{tekst} kl. {d:%H.%M}" if med_tid and len(str(verdi)) > 10 else tekst


def _frist_status(frist: str | None) -> str:
    if not frist:
        return ""
    d = date.fromisoformat(frist[:10])
    i_dag = date.today()
    if d < i_dag:
        return "forfalt"
    return "i dag" if d == i_dag else "kommer"


def lag_app(odoo: OdooClient | None = None, backend: AIBackend | None = None,
            odoo_ordre: OdooClient | None = None) -> FastAPI:
    app = FastAPI(title="Riktig levert første gang", docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=ROT / "static"), name="static")
    maler = Jinja2Templates(directory=ROT / "templates")
    maler.env.filters["dato"] = _dato
    maler.env.filters["kort"] = kort_navn
    maler.env.globals["frist_status"] = _frist_status

    app.state.odoo = odoo or OdooClient()
    # Ordre og levering kan ligge i en annen Odoo enn innboksen (Helpdesk krever Enterprise).
    app.state.odoo_ordre = odoo_ordre or (OdooClient(OdooKonfig.fra_miljo("ORDRE_"))
                                          if os.environ.get("ORDRE_ODOO_URL") else app.state.odoo)
    app.state.backend = backend
    app.state.odoo_url = app.state.odoo.konfig.url

    def hent_backend() -> AIBackend:
        if app.state.backend is None:
            app.state.backend = velg_backend()
        return app.state.backend

    def miljo() -> dict:
        return {
            "odoo_url": app.state.odoo_url,
            "odoo_er_mock": er_mock(app.state.odoo),
            "ordre_url": app.state.odoo_ordre.konfig.url,
            "ordre_er_mock": er_mock(app.state.odoo_ordre),
            "ai_backend": hent_backend().navn,
        }

    def vis(request: Request, mal: str, **kontekst) -> HTMLResponse:
        return maler.TemplateResponse(request, mal, {"miljo": miljo(), "aktiv": kontekst.pop("aktiv", ""), **kontekst})

    app.state.vis = vis
    app.state.hent_backend = hent_backend
    app.include_router(ruter)

    def vil_ha_json(request: Request) -> bool:
        return "application/json" in request.headers.get("accept", "")

    def feilside(request: Request, tittel: str, tekst: str, kode: int):
        if vil_ha_json(request):
            return JSONResponse({"feil": tekst}, status_code=kode)
        try:
            m = miljo()
        except OdooFeil:
            m = {"odoo_url": app.state.odoo_url, "odoo_er_mock": True, "ordre_url": app.state.odoo_ordre.konfig.url,
                 "ordre_er_mock": True, "ai_backend": "ukjent"}
        return maler.TemplateResponse(request, "feil.html", {"miljo": m, "aktiv": "", "tittel": tittel, "feil": tekst},
                                      status_code=kode)

    @app.exception_handler(OdooFeil)
    async def odoo_nede(request: Request, feil: OdooFeil):
        return feilside(request, "Fikk ikke kontakt med Odoo", str(feil), 502)

    @app.exception_handler(IkkeFunnet)
    async def ikke_funnet(request: Request, feil: IkkeFunnet):
        return feilside(request, "Fant ikke det du lette etter", str(feil), 404)

    def svar_kvittering(request: Request, kvittering: Kvittering, type_: str):
        if vil_ha_json(request):
            return JSONResponse({"saksnummer": kvittering.saksnummer, "odoo_id": kvittering.odoo_id,
                                 "modell": "helpdesk.ticket" if type_ == "reklamasjon" else "crm.lead",
                                 "trenger_manuell_vurdering": kvittering.manuell,
                                 "ai_backend": kvittering.ai_backend}, status_code=201)
        return RedirectResponse(f"/kvittering/{type_}/{kvittering.odoo_id}", status_code=303)

    # ---------- sider ----------
    @app.get("/", response_class=HTMLResponse)
    def forside(request: Request):
        return vis(request, "forside.html", aktiv="skjema", butikker=BUTIKKER)

    @app.post("/reklamasjon")
    async def reklamasjon(request: Request, kundenavn: str = Form(...), epost: str = Form(...),
                          ordrenummer: str = Form(""), butikk: str = Form(...), fritekst: str = Form(...),
                          telefon: str = Form(""), bilder: list[UploadFile] = File(default=[])):
        if butikk not in BUTIKKNAVN:
            raise HTTPException(422, "Ukjent butikk eller forhandler.")
        lastet: list[Bilde] = []
        for fil in bilder[:MAKS_BILDER]:
            if not fil.filename:
                continue
            if fil.content_type not in BILDETYPER:
                raise HTTPException(415, f"{fil.filename} er ikke et bilde (JPEG, PNG, WebP eller GIF).")
            data = await fil.read()
            if len(data) > MAKS_BILDESTORRELSE:
                raise HTTPException(413, f"Bildet {fil.filename} er større enn 8 MB.")
            lastet.append(Bilde(fil.filename, fil.content_type or "application/octet-stream", data))
        skjema = {"kundenavn": kundenavn.strip(), "epost": epost.strip(), "ordrenummer": ordrenummer.strip(),
                  "butikk": butikk, "fritekst": fritekst, "telefon": telefon.strip()}
        kvittering = behandle_reklamasjon(app.state.odoo, hent_backend(), skjema, lastet)
        return svar_kvittering(request, kvittering, "reklamasjon")

    @app.post("/tegnetime")
    async def tegnetime(request: Request, navn: str = Form(...), epost: str = Form(""), telefon: str = Form(""),
                        postnummer: str = Form(""), onsket_butikk: str = Form(""), beskrivelse: str = Form(...)):
        if not (epost.strip() or telefon.strip()):
            raise HTTPException(422, "Oppgi e-post eller telefon.")
        if onsket_butikk and onsket_butikk not in BUTIKKNAVN:
            raise HTTPException(422, "Ukjent butikk.")
        skjema = {"navn": navn.strip(), "epost": epost.strip(), "telefon": telefon.strip(),
                  "postnummer": postnummer.strip(), "onsket_butikk": onsket_butikk, "beskrivelse": beskrivelse}
        kvittering = behandle_tegnetime(app.state.odoo, hent_backend(), skjema)
        return svar_kvittering(request, kvittering, "tegnetime")

    @app.get("/kvittering/{type_}/{rid}", response_class=HTMLResponse)
    def kvittering_side(request: Request, type_: str, rid: int):
        modell, felt = ("helpdesk.ticket", TICKET_FELT) if type_ == "reklamasjon" else ("crm.lead", LEAD_FELT)
        post = app.state.odoo.read(modell, rid, felt)
        if not post:
            raise HTTPException(404)
        return vis(request, "kvittering.html", aktiv="skjema", type_=type_, post=post, v=les_vurdering(post))

    @app.get("/saker", response_class=HTMLResponse)
    def saker(request: Request, fane: str = "reklamasjoner", butikk: str = ""):
        odoo = app.state.odoo
        domene = [("x_butikk", "=", butikk)] if butikk else []
        reklamasjoner = odoo.search_read("helpdesk.ticket", domene, TICKET_FELT, order="create_date desc")
        leads = odoo.search_read("crm.lead", domene, LEAD_FELT, order="create_date desc")
        for r in reklamasjoner:
            r["v"] = les_vurdering(r)
        return vis(request, "saker.html", aktiv="saker", fane=fane, butikk=butikk, butikker=BUTIKKNAVN,
                   reklamasjoner=reklamasjoner, leads=leads)

    @app.get("/saker/{rid}", response_class=HTMLResponse)
    def sak(request: Request, rid: int, lagret: str = ""):
        odoo = app.state.odoo
        post = odoo.read("helpdesk.ticket", rid, TICKET_FELT)
        if not post:
            raise HTTPException(404, "Fant ikke saken.")
        vedlegg = odoo.search_read("ir.attachment", [("res_model", "=", "helpdesk.ticket"), ("res_id", "=", rid)],
                                   ["name", "mimetype"])
        stadier = odoo.search_read("helpdesk.stage", [], ["name"], order="sequence")
        return vis(request, "sak.html", aktiv="saker", post=post, v=les_vurdering(post), vedlegg=vedlegg,
                   stadier=stadier, lagret=lagret)

    @app.post("/saker/{rid}")
    def lagre_sak(rid: int, svarutkast: str = Form(""), stage_id: int = Form(0)):
        verdier: dict = {"x_svarutkast": svarutkast}
        if stage_id:
            verdier["stage_id"] = stage_id
        app.state.odoo.write("helpdesk.ticket", rid, verdier)
        return RedirectResponse(f"/saker/{rid}?lagret=1", status_code=303)

    @app.get("/leads/{rid}", response_class=HTMLResponse)
    def lead(request: Request, rid: int, lagret: str = ""):
        odoo = app.state.odoo
        post = odoo.read("crm.lead", rid, LEAD_FELT)
        if not post:
            raise HTTPException(404, "Fant ikke leadet.")
        stadier = odoo.search_read("crm.stage", [], ["name"], order="sequence")
        return vis(request, "lead.html", aktiv="saker", post=post, v=les_vurdering(post), stadier=stadier,
                   lagret=lagret, butikker=BUTIKKNAVN)

    @app.post("/leads/{rid}")
    def lagre_lead(rid: int, stage_id: int = Form(0), x_butikk: str = Form("")):
        verdier: dict = {}
        if stage_id:
            verdier["stage_id"] = stage_id
        if x_butikk in BUTIKKNAVN:
            verdier["x_butikk"] = x_butikk
        if verdier:
            app.state.odoo.write("crm.lead", rid, verdier)
        return RedirectResponse(f"/leads/{rid}?lagret=1", status_code=303)

    @app.get("/vedlegg/{rid}")
    def vedlegg(rid: int):
        post = app.state.odoo.read("ir.attachment", rid, ["name", "mimetype", "datas", "res_model"])
        # Bare bilder på reklamasjoner, aldri andre vedlegg i Odoo, og aldri HTML som kan kjøre skript.
        if not post or post.get("res_model") != "helpdesk.ticket" or post.get("mimetype") not in BILDETYPER:
            raise HTTPException(404)
        return Response(base64.b64decode(post["datas"]), media_type=post["mimetype"],
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})

    @app.get("/dashbord", response_class=HTMLResponse)
    def dashbord(request: Request):
        try:
            innboks = dashbord_data(app.state.odoo)
        except OdooFeil as feil:  # f.eks. Odoo Community uten Helpdesk
            innboks = tom_innboks(str(feil))
        return vis(request, "dashbord.html", aktiv="dashbord", **innboks, o=ordre_dashbord(app.state.odoo_ordre))

    @app.get("/api/dashbord")
    def dashbord_api():
        data = dashbord_data(app.state.odoo)
        return JSONResponse({k: v for k, v in data.items() if k != "feiltyper"})

    @app.get("/helse")
    def helse():
        return {"odoo": app.state.odoo.versjon(), **miljo()}

    return app


def tom_innboks(feil: str) -> dict:
    tom = {"rader": [], "maks": 1}
    return {"feiltyper": FEILTYPER, "innsikt": "", "per_modell": tom, "per_butikk": tom, "leads": [], "leads_maks": 1,
            "innboks_feil": feil,
            "nokkeltall": {k: 0 for k in ("saker", "saker_30", "hoy", "til_fabrikk", "til_montor", "til_butikk",
                                          "manuell", "leads", "leads_forfalt", "leads_hoy")}}


def dashbord_data(odoo: OdooClient) -> dict:
    saker = odoo.search_read("helpdesk.ticket", [], ["x_feiltype", "x_kjokkenmodell", "x_butikk", "x_alvorlighet",
                                                     "x_ruting", "x_manuell", "create_date", "stage_id"])
    leads = odoo.search_read("crm.lead", [], ["x_butikk", "x_prioritet", "x_oppfolging_frist", "stage_id",
                                              "create_date"])
    feiltyper = [f for f in FEILTYPER if any(s["x_feiltype"] == f for s in saker)] or FEILTYPER

    def matrise(nokkel: str) -> dict:
        rader: dict[str, Counter] = defaultdict(Counter)
        for s in saker:
            if s["x_feiltype"] in FEILTYPER:
                rader[s[nokkel] or "Ukjent"][s["x_feiltype"]] += 1
        rekkefolge = sorted(rader, key=lambda r: (-sum(rader[r].values()), r))
        maks = max((n for r in rader.values() for n in r.values()), default=1)
        return {"rader": [{"navn": r, "celler": [rader[r][f] for f in feiltyper], "sum": sum(rader[r].values())}
                          for r in rekkefolge], "maks": maks}

    grense = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    siste30 = [s for s in saker if (s["create_date"] or "") >= grense]
    i_dag = date.today().isoformat()
    lead_per_butikk: dict[str, Counter] = {b: Counter() for b in BUTIKKNAVN}
    for lead in leads:
        lead_per_butikk.setdefault(lead["x_butikk"] or "Ukjent", Counter())[lead["x_prioritet"] or "middels"] += 1
    lead_rader = sorted(({"navn": b, "lav": c["lav"], "middels": c["middels"], "høy": c["høy"],
                          "sum": sum(c.values())} for b, c in lead_per_butikk.items()), key=lambda r: -r["sum"])
    apne = [lead for lead in leads if (lead["stage_id"] or [0, ""])[1] in ("Ny", "Kvalifisert")]
    per_modell = matrise("x_kjokkenmodell")
    innsikt = ""
    topp = max(((r, f, n) for r in per_modell["rader"] for f, n in zip(feiltyper, r["celler"])),
               key=lambda t: t[2], default=None)
    if topp and topp[2] >= 3:
        rad, feil, n = topp
        andel = f"Alle {n}" if n == rad["sum"] else f"{n} av {rad['sum']}"
        innsikt = (f"<b>Mønster:</b> {andel} reklamasjoner på modell {escape(rad['navn'])} gjelder {escape(feil)}. "
                   f"Det er verdt en titt i produksjonen før det blir flere.")
    return {
        "feiltyper": feiltyper,
        "innsikt": innsikt,
        "per_modell": per_modell,
        "per_butikk": matrise("x_butikk"),
        "leads": lead_rader,
        "leads_maks": max((r["sum"] for r in lead_rader), default=1) or 1,
        "nokkeltall": {
            "saker": len(saker),
            "saker_30": len(siste30),
            "hoy": sum(1 for s in saker if s["x_alvorlighet"] == "høy"),
            "til_fabrikk": sum(1 for s in saker if s["x_ruting"] == "fabrikk"),
            "til_montor": sum(1 for s in saker if s["x_ruting"] == "montør"),
            "til_butikk": sum(1 for s in saker if s["x_ruting"] == "butikk"),
            "manuell": sum(1 for s in saker if s["x_manuell"]),
            "leads": len(leads),
            "leads_forfalt": sum(1 for lead in apne if (lead["x_oppfolging_frist"] or "9") < i_dag),
            "leads_hoy": sum(1 for lead in leads if lead["x_prioritet"] == "høy"),
        },
    }


app = lag_app()

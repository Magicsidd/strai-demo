"""Liten mock av Odoo sitt eksterne API (/jsonrpc), lagret i SQLite.

Implementerer det demoen trenger, med samme protokoll som ekte Odoo:

    POST /jsonrpc  {"jsonrpc": "2.0", "method": "call",
                    "params": {"service": "common", "method": "login", "args": [db, user, pw]}}
    POST /jsonrpc  {"params": {"service": "object", "method": "execute_kw",
                    "args": [db, uid, pw, model, method, args, kwargs]}}

Støttede metoder: create, write, read, search, search_read, search_count, unlink.
Modeller lagres generisk, så helpdesk.ticket, crm.lead, res.partner, sale.order,
helpdesk.stage, crm.stage og ir.attachment fungerer uten egne tabeller.

Kjøres med:  python -m mock_odoo.server   (port 8069, samme som Odoo)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

DB_NAVN = os.environ.get("MOCK_ODOO_DB", "strai")
BRUKER = os.environ.get("MOCK_ODOO_USER", "demo@strai.no")
PASSORD = os.environ.get("MOCK_ODOO_PASSWORD", "demo")
UID = 2

# many2one-felt: felt -> relatert modell (per modell der det varierer)
MANY2ONE: dict[str, dict[str, str]] = {
    "helpdesk.ticket": {"partner_id": "res.partner", "stage_id": "helpdesk.stage"},
    "crm.lead": {"partner_id": "res.partner", "stage_id": "crm.stage"},
    "sale.order": {"partner_id": "res.partner"},
    "sale.order.line": {"order_id": "sale.order", "product_id": "product.product"},
    "stock.picking": {"sale_id": "sale.order", "partner_id": "res.partner"},
}
# one2many som kan skrives med Odoo-kommandoer [(0, 0, {...})]
ONE2MANY = {("sale.order", "order_line"): ("sale.order.line", "order_id")}

STANDARD_STADIER = {
    "helpdesk.stage": ["Ny", "Under behandling", "Venter på kunde", "Løst"],
    "crm.stage": ["Ny", "Kvalifisert", "Tegnetime booket", "Vunnet"],
}


def _na() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class OdooFeil(Exception):
    """Gir samme feilform som Odoo: {"error": {"message": ..., "data": {...}}}."""

    def __init__(self, melding: str, navn: str = "odoo.exceptions.UserError"):
        super().__init__(melding)
        self.melding = melding
        self.navn = navn


class Lager:
    def __init__(self, sti: str | Path):
        self.sti = str(sti)
        self.las = threading.Lock()
        self.con = sqlite3.connect(self.sti, check_same_thread=False)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS poster ("
            " modell TEXT NOT NULL, id INTEGER NOT NULL, data TEXT NOT NULL,"
            " PRIMARY KEY (modell, id))"
        )
        self.con.commit()
        self._seed_stadier()

    def _seed_stadier(self) -> None:
        for modell, navn in STANDARD_STADIER.items():
            if not self._alle(modell):
                for i, n in enumerate(navn, start=1):
                    self.create(modell, {"name": n, "sequence": i})

    # ---------- lagring ----------
    def _alle(self, modell: str) -> list[dict]:
        rader = self.con.execute(
            "SELECT id, data FROM poster WHERE modell = ? ORDER BY id", (modell,)
        ).fetchall()
        return [{**json.loads(d), "id": i} for i, d in rader]

    def _hent(self, modell: str, rid: int) -> dict | None:
        rad = self.con.execute(
            "SELECT data FROM poster WHERE modell = ? AND id = ?", (modell, rid)
        ).fetchone()
        return {**json.loads(rad[0]), "id": rid} if rad else None

    def _lagre(self, modell: str, rid: int, data: dict) -> None:
        data = {k: v for k, v in data.items() if k != "id"}
        self.con.execute(
            "INSERT OR REPLACE INTO poster (modell, id, data) VALUES (?, ?, ?)",
            (modell, rid, json.dumps(data, ensure_ascii=False)),
        )

    # ---------- ORM-metoder ----------
    def create(self, modell: str, verdier: dict | list) -> int | list[int]:
        if isinstance(verdier, list):
            return [self.create(modell, v) for v in verdier]
        with self.las:
            neste = self.con.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM poster WHERE modell = ?", (modell,)
            ).fetchone()[0]
            data = dict(verdier)
            barn = {felt: data.pop(felt) for (m, felt) in ONE2MANY if m == modell and felt in data}
            if modell == "sale.order":
                data.setdefault("name", f"S{neste:05d}")
                data.setdefault("state", "draft")
            if modell == "product.product" and data.get("default_code"):
                data.setdefault("display_name", f"[{data['default_code']}] {data.get('name', '')}")
            # Mock-avvik: seed kan sette create_date for å spre saker i tid.
            # Ekte Odoo setter alltid create_date selv.
            data.setdefault("create_date", _na())
            data["write_date"] = _na()
            if modell == "helpdesk.ticket":
                data.setdefault("ticket_ref", f"{neste:05d}")
            stadium_modell = {"helpdesk.ticket": "helpdesk.stage", "crm.lead": "crm.stage"}.get(modell)
            if stadium_modell and not data.get("stage_id"):
                data["stage_id"] = self._forste_stadium(stadium_modell)
            self._lagre(modell, neste, data)
            self.con.commit()
        for felt, kommandoer in barn.items():
            barnemodell, invers = ONE2MANY[(modell, felt)]
            for kommando in kommandoer:
                if kommando[0] == 0:
                    self.create(barnemodell, {**kommando[2], invers: neste})
        return neste

    def _forste_stadium(self, modell: str) -> int | bool:
        alle = self._alle(modell)
        return alle[0]["id"] if alle else False

    def write(self, modell: str, ids: list[int], verdier: dict) -> bool:
        with self.las:
            for rid in ids:
                post = self._hent(modell, rid)
                if post is None:
                    raise OdooFeil(f"Posten {modell}({rid}) finnes ikke.", "odoo.exceptions.MissingError")
                post.update(verdier)
                post["write_date"] = _na()
                self._lagre(modell, rid, post)
            self.con.commit()
        return True

    def unlink(self, modell: str, ids: list[int]) -> bool:
        with self.las:
            for rid in ids:
                self.con.execute("DELETE FROM poster WHERE modell = ? AND id = ?", (modell, rid))
            self.con.commit()
        return True

    def search(self, modell: str, domene: list, offset: int = 0, limit: int | None = None,
               order: str | None = None) -> list[int]:
        poster = [p for p in self._alle(modell) if _match(p, domene or [])]
        poster = _sorter(poster, order)
        poster = poster[offset:]
        if limit:
            poster = poster[:limit]
        return [p["id"] for p in poster]

    def read(self, modell: str, ids: list[int], fields: list[str] | None = None) -> list[dict]:
        ut = []
        for rid in ids:
            post = self._hent(modell, rid)
            if post is None:
                continue
            ut.append(self._formater(modell, post, fields))
        return ut

    def _formater(self, modell: str, post: dict, fields: list[str] | None) -> dict:
        relasjoner = MANY2ONE.get(modell, {})
        post = dict(post)
        post.setdefault("display_name", post.get("name", f"{modell},{post['id']}"))
        felt = fields or list(post.keys())
        ut: dict[str, Any] = {"id": post["id"]}
        for f in felt:
            verdi = post.get(f, False)
            if f in relasjoner and verdi:
                relatert = self._hent(relasjoner[f], int(verdi))
                navn = (relatert.get("display_name") or relatert.get("name", "")) if relatert else ""
                verdi = [int(verdi), navn]
            ut[f] = verdi if verdi is not None else False
        return ut


def _verdi_for_sammenligning(post: dict, felt: str) -> Any:
    verdi = post.get(felt, False)
    if isinstance(verdi, list) and len(verdi) == 2 and isinstance(verdi[0], int):
        return verdi[0]
    return verdi


def _match_ledd(post: dict, ledd: list | tuple) -> bool:
    felt, op, mal = ledd
    v = _verdi_for_sammenligning(post, felt)
    if op == "=":
        return v == mal or (mal is False and v in (None, "", False))
    if op == "!=":
        return v != mal
    if op == "in":
        return v in mal
    if op == "not in":
        return v not in mal
    if op in ("ilike", "like"):
        if v in (None, False):
            return False
        return str(mal).lower() in str(v).lower() if op == "ilike" else str(mal) in str(v)
    if op in (">", "<", ">=", "<="):
        if v in (None, False):
            return False
        return {">": v > mal, "<": v < mal, ">=": v >= mal, "<=": v <= mal}[op]
    raise OdooFeil(f"Operatoren {op!r} støttes ikke av mock-Odoo.", "ValueError")


def _match(post: dict, domene: list) -> bool:
    """Evaluerer et Odoo-domene i polsk notasjon ('&', '|', '!'), implisitt AND."""
    pos = 0

    def neste() -> bool:
        nonlocal pos
        ledd = domene[pos]
        pos += 1
        if ledd == "&":
            a, b = neste(), neste()
            return a and b
        if ledd == "|":
            a, b = neste(), neste()
            return a or b
        if ledd == "!":
            return not neste()
        return _match_ledd(post, ledd)

    resultat = True
    while pos < len(domene):
        resultat = neste() and resultat
    return resultat


def _sorter(poster: list[dict], order: str | None) -> list[dict]:
    if not order:
        return poster
    for del_ in reversed([d.strip() for d in order.split(",") if d.strip()]):
        biter = del_.split()
        felt, synkende = biter[0], len(biter) > 1 and biter[1].lower() == "desc"
        poster = sorted(poster, key=lambda p: (p.get(felt) is None or p.get(felt) is False,
                                               str(p.get(felt, "")) if not isinstance(p.get(felt), (int, float)) else p.get(felt)),
                        reverse=synkende)
    return poster


def lag_app(db_sti: str | Path | None = None) -> FastAPI:
    sti = db_sti or os.environ.get("MOCK_ODOO_SQLITE", str(Path(__file__).resolve().parent.parent / "data" / "mock_odoo.db"))
    Path(sti).parent.mkdir(parents=True, exist_ok=True)
    lager = Lager(sti)
    app = FastAPI(title="Mock Odoo", docs_url=None, redoc_url=None)
    app.state.lager = lager

    def utfor(service: str, metode: str, args: list) -> Any:
        if service == "common":
            if metode == "version":
                return {"server_version": "18.0-mock", "server_serie": "18.0", "protocol_version": 1}
            if metode in ("login", "authenticate"):
                db, bruker, passord = args[0], args[1], args[2]
                if db == DB_NAVN and bruker == BRUKER and passord == PASSORD:
                    return UID
                return False
            raise OdooFeil(f"Ukjent metode common.{metode}")
        if service == "object" and metode == "execute_kw":
            db, uid, passord, modell, orm_metode = args[:5]
            pos = args[5] if len(args) > 5 else []
            kw = args[6] if len(args) > 6 else {}
            if db != DB_NAVN or uid != UID or passord != PASSORD:
                raise OdooFeil("Access Denied", "odoo.exceptions.AccessDenied")
            return kall_orm(modell, orm_metode, pos, kw)
        raise OdooFeil(f"Ukjent tjeneste {service}.{metode}")

    def kall_orm(modell: str, m: str, pos: list, kw: dict) -> Any:
        if m == "create":
            return lager.create(modell, pos[0])
        if m == "write":
            return lager.write(modell, list(pos[0]), pos[1])
        if m == "unlink":
            return lager.unlink(modell, list(pos[0]))
        if m == "read":
            return lager.read(modell, list(pos[0]), kw.get("fields") or (pos[1] if len(pos) > 1 else None))
        if m == "search":
            return lager.search(modell, pos[0] if pos else kw.get("domain", []),
                                kw.get("offset", 0), kw.get("limit"), kw.get("order"))
        if m == "search_count":
            return len(lager.search(modell, pos[0] if pos else kw.get("domain", [])))
        if m == "search_read":
            domene = pos[0] if pos else kw.get("domain", [])
            felt = kw.get("fields") or (pos[1] if len(pos) > 1 else None)
            ids = lager.search(modell, domene, kw.get("offset", 0), kw.get("limit"), kw.get("order"))
            return lager.read(modell, ids, felt)
        if m == "message_post":
            rid = pos[0][0] if isinstance(pos[0], list) else pos[0]
            return lager.create("mail.message", {"model": modell, "res_id": rid, "body": kw.get("body", ""),
                                                 "message_type": kw.get("message_type", "comment")})
        if m == "action_confirm" and modell == "sale.order":
            for rid in pos[0]:
                ordre = lager.read(modell, [rid], ["name", "partner_id"])[0]
                lager.write(modell, [rid], {"state": "sale"})
                partner = ordre["partner_id"][0] if ordre["partner_id"] else False
                lager.create("stock.picking", {"origin": ordre["name"], "sale_id": rid, "partner_id": partner,
                                               "state": "assigned", "name": f"WH/OUT/{rid:05d}"})
            return True
        if m == "fields_get":
            return {}
        raise OdooFeil(f"Metoden {m} støttes ikke av mock-Odoo.")

    @app.post("/jsonrpc")
    async def jsonrpc(request: Request) -> JSONResponse:
        kropp = await request.json()
        rid = kropp.get("id")
        params = kropp.get("params", {})
        try:
            resultat = utfor(params.get("service"), params.get("method"), params.get("args", []))
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": resultat})
        except OdooFeil as feil:
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {
                "code": 200, "message": "Odoo Server Error",
                "data": {"name": feil.navn, "message": feil.melding}}})

    @app.get("/", response_class=HTMLResponse)
    def forside() -> str:
        antall = {m: len(lager._alle(m)) for m in ("helpdesk.ticket", "crm.lead", "res.partner", "sale.order")}
        linjer = "".join(f"<li><code>{m}</code>: {n}</li>" for m, n in antall.items())
        return (f"<meta charset=utf-8><title>Mock Odoo</title><body style='font-family:sans-serif;padding:2rem'>"
                f"<h1>Mock Odoo 18 (kun for demo)</h1><p>Database <b>{DB_NAVN}</b>, API på <code>/jsonrpc</code>.</p>"
                f"<ul>{linjer}</ul></body>")

    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("MOCK_ODOO_PORT", "8069"))
    uvicorn.run(lag_app(), host="127.0.0.1", port=port, log_level="warning")

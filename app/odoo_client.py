"""Odoo-klient over JSON-RPC (/jsonrpc), samme protokoll som Odoo 14 til 18 bruker.

Klienten vet ikke om den snakker med mock_odoo eller ekte Odoo. Bytte er kun
ODOO_URL, ODOO_DB, ODOO_USER og ODOO_PASSWORD (bruk gjerne en API-nøkkel som passord).
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from typing import Any

import httpx


class OdooFeil(RuntimeError):
    pass


class IkkeFunnet(LookupError):
    """Posten finnes ikke i Odoo. Gir 404, ikke «Odoo svarer ikke»."""


@dataclass
class OdooKonfig:
    url: str
    db: str
    bruker: str
    passord: str

    @classmethod
    def fra_miljo(cls, prefiks: str = "") -> "OdooKonfig":
        """Leser {prefiks}ODOO_URL osv. Mangler en verdi med prefiks, brukes den uten."""
        def hent(navn: str, standard: str) -> str:
            return os.environ.get(prefiks + navn) or os.environ.get(navn) or standard
        return cls(
            url=hent("ODOO_URL", "http://127.0.0.1:8069").rstrip("/"),
            db=hent("ODOO_DB", "strai"),
            bruker=hent("ODOO_USER", "demo@strai.no"),
            passord=hent("ODOO_PASSWORD", "demo"),
        )


class OdooClient:
    def __init__(self, konfig: OdooKonfig | None = None, timeout: float = 20.0):
        self.konfig = konfig or OdooKonfig.fra_miljo()
        self._http = httpx.Client(timeout=timeout)
        self._uid: int | None = None
        self._teller = itertools.count(1)

    # ---------- lavnivå ----------
    def _kall(self, service: str, metode: str, *args: Any) -> Any:
        kropp = {"jsonrpc": "2.0", "method": "call", "id": next(self._teller),
                 "params": {"service": service, "method": metode, "args": list(args)}}
        try:
            svar = self._http.post(f"{self.konfig.url}/jsonrpc", json=kropp)
            svar.raise_for_status()
        except httpx.HTTPError as feil:
            raise OdooFeil(f"Fikk ikke kontakt med Odoo på {self.konfig.url}: {feil}") from feil
        data = svar.json()
        if data.get("error"):
            info = data["error"].get("data", {})
            raise OdooFeil(info.get("message") or data["error"].get("message", "Ukjent Odoo-feil"))
        return data.get("result")

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._kall("common", "login", self.konfig.db, self.konfig.bruker, self.konfig.passord)
            if not uid:
                raise OdooFeil("Innlogging mot Odoo feilet. Sjekk ODOO_DB, ODOO_USER og ODOO_PASSWORD.")
            self._uid = uid
        return self._uid

    def execute_kw(self, modell: str, metode: str, args: list | None = None, kwargs: dict | None = None) -> Any:
        return self._kall("object", "execute_kw", self.konfig.db, self.uid, self.konfig.passord,
                          modell, metode, args or [], kwargs or {})

    # ---------- det demoen bruker ----------
    def versjon(self) -> dict:
        return self._kall("common", "version")

    def create(self, modell: str, verdier: dict) -> int:
        return self.execute_kw(modell, "create", [verdier])

    def write(self, modell: str, ids: int | list[int], verdier: dict) -> bool:
        ids = [ids] if isinstance(ids, int) else ids
        return self.execute_kw(modell, "write", [ids, verdier])

    def search_read(self, modell: str, domene: list | None = None, felt: list[str] | None = None,
                    limit: int | None = None, order: str | None = None) -> list[dict]:
        kw: dict[str, Any] = {"fields": felt or []}
        if limit:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.execute_kw(modell, "search_read", [domene or []], kw)

    def read(self, modell: str, rid: int, felt: list[str] | None = None) -> dict | None:
        rader = self.execute_kw(modell, "read", [[rid]], {"fields": felt or []})
        return rader[0] if rader else None

    def search_count(self, modell: str, domene: list | None = None) -> int:
        return self.execute_kw(modell, "search_count", [domene or []])

    def finn_eller_opprett_partner(self, navn: str, epost: str, telefon: str = "", postnr: str = "") -> int:
        if epost:
            treff = self.search_read("res.partner", [("email", "=", epost)], ["id"], limit=1)
            if treff:
                return treff[0]["id"]
        return self.create("res.partner", {"name": navn, "email": epost, "phone": telefon, "zip": postnr})

    def stadium_id(self, modell: str, navn: str) -> int | None:
        treff = self.search_read(modell, [("name", "=", navn)], ["id"], limit=1)
        return treff[0]["id"] if treff else None


def er_mock(klient: OdooClient) -> bool:
    """Spør Odoo selv om versjonen, i stedet for å gjette ut fra URL. Svaret huskes per klient."""
    if not hasattr(klient, "_er_mock"):
        try:
            klient._er_mock = str(klient.versjon().get("server_version", "")).endswith("mock")
        except OdooFeil:
            return True  # ikke husket, så neste kall prøver igjen
    return klient._er_mock

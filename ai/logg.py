"""Revisjonslogg for AI-kall. Én JSON-linje per kall i data/ai_logg.jsonl.

Logger hva som trengs for å etterprøve en beslutning: oppgave, backend, modell,
promptversjon (hash av promptfila), hash av input, varighet og om svaret var gyldig.
Selve kundeteksten logges ikke, bare hashen, så loggen kan deles uten personopplysninger.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_LAS = threading.Lock()


def sti() -> Path:
    return Path(os.environ.get("AI_LOGG", Path(__file__).resolve().parent.parent / "data" / "ai_logg.jsonl"))


def kort_hash(tekst: str, lengde: int = 12) -> str:
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()[:lengde]


def skriv(post: dict) -> None:
    post = {"tid": datetime.now(timezone.utc).isoformat(timespec="seconds"), **post}
    fil = sti()
    fil.parent.mkdir(parents=True, exist_ok=True)
    with _LAS, fil.open("a", encoding="utf-8") as f:
        f.write(json.dumps(post, ensure_ascii=False) + "\n")


def les(siste: int = 50) -> list[dict]:
    fil = sti()
    if not fil.exists():
        return []
    linjer = fil.read_text(encoding="utf-8").splitlines()[-siste:]
    return [json.loads(l) for l in reversed(linjer) if l.strip()]

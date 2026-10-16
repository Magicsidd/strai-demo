"""Kjører testsettet mot en AI-backend og skriver resultatet til docs/evaluering.md.

    python -m evals.kjor                  # AI_BACKEND (auto)
    python -m evals.kjor --ai claude_cli

Måler det som betyr noe for en fabrikk: finner AI-en det den skal (treff), og lar den
ordrer som er i orden være i fred (falske alarmer). Kontrollene (forkastede forslag) telles også.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from ai import velg_backend
from ai.tjeneste import promptversjon
from ordresjekk.avvik import vurder_avvik
from ordresjekk.modeller import Ordre, Ordrelinje
from ordresjekk.sjekk import kjor_ordresjekk

from .fasit import avvikscaser, ordrecaser

UT = Path(__file__).resolve().parent.parent / "docs" / "evaluering.md"
I_DAG = date(2026, 10, 16)


def treffer(forventet: str, funn) -> bool:
    koder = funn.linjer + funn.forslag
    return any(k.startswith(forventet) for k in koder) or forventet.lower() in funn.beskrivelse.lower()


def evaluer_ordresjekk(backend) -> tuple[list[dict], dict]:
    rader = []
    for c in ordrecaser():
        ordre = Ordre("EVAL", c["modell"], [Ordrelinje(k, a) for k, a in c["linjer"]],
                      onsket_levering=I_DAG + timedelta(weeks=12), kundens_onsker=c["onsker"])
        start = time.monotonic()
        r = kjor_ordresjekk(ordre, backend, I_DAG)
        ai = [f for f in r.funn if f.regel == "AI"]
        truffet = [e for e in c["forventet"] if any(treffer(e, f) for f in ai)]
        alarmer = [f for f in ai if f.alvor in ("stopp", "avklar") and not any(treffer(e, f) for e in c["forventet"])]
        rader.append({"navn": c["navn"], "forventet": c["forventet"], "truffet": truffet, "ai_funn": len(ai),
                      "falske": len(alarmer) if not c["forventet"] else 0, "ekstra": len(alarmer),
                      "forkastet": len(r.forkastet), "feil": r.ai_feil, "sek": time.monotonic() - start})
    forventet = sum(len(r["forventet"]) for r in rader)
    rene = [r for r in rader if not r["forventet"]]
    return rader, {
        "treff": sum(len(r["truffet"]) for r in rader), "forventet": forventet,
        "rene": len(rene), "rene_uten_alarm": sum(1 for r in rene if r["falske"] == 0),
        "forkastet": sum(r["forkastet"] for r in rader), "feil": sum(1 for r in rader if r["feil"]),
    }


def evaluer_avvik(backend) -> tuple[list[dict], dict]:
    rader = []
    for c in avvikscaser():
        _, butikk, modell, _, _, linjer, _ = c["ordre"]
        ordre = Ordre("EVAL", modell, [Ordrelinje(k, a) for k, a in linjer], butikk=butikk)
        r = vurder_avvik(ordre, c["melding"], c["avsender"], backend)
        fasit = c["fasit"]
        fikk = {l.kode: l.antall for l in r.linjer}
        rader.append({"navn": c["navn"], "melding": c["melding"], "linjer_ok": fikk == fasit["linjer"],
                      "arsak_ok": r.arsak == fasit["arsak"], "fikk": fikk, "fasit": fasit["linjer"],
                      "arsak": r.arsak, "fasit_arsak": fasit["arsak"], "forkastet": len(r.forkastet),
                      "feil": r.feil})
    return rader, {"linjer_ok": sum(r["linjer_ok"] for r in rader), "arsak_ok": sum(r["arsak_ok"] for r in rader),
                   "antall": len(rader), "forkastet": sum(r["forkastet"] for r in rader)}


def skriv_rapport(backend, ordre, os_, avvik, as_) -> str:
    modell = getattr(backend, "modell", backend.navn)
    linjer = [
        "# Evaluering av AI-delen", "",
        f"Kjørt {date.today():%d.%m.%Y} med `{backend.navn}` (`{modell}`). "
        f"Promptversjoner: ordresjekk `{promptversjon('ordresjekk')}`, avvik `{promptversjon('avvik')}`.",
        "Kjør selv med `python -m evals.kjor`. Fasiten står i `evals/fasit.py` og `demo/ordre_data.py`.", "",
        "## Sammendrag", "",
        "| Mål | Resultat |", "|---|---|",
        f"| Ordresjekk: forventede funn AI-en fant | {os_['treff']} av {os_['forventet']} |",
        f"| Ordresjekk: ordrer i orden uten falsk alarm | {os_['rene_uten_alarm']} av {os_['rene']} |",
        f"| Ordresjekk: AI-forslag stoppet av kontrollene | {os_['forkastet']} |",
        f"| Avvik: riktige linjer og antall | {as_['linjer_ok']} av {as_['antall']} |",
        f"| Avvik: riktig årsak | {as_['arsak_ok']} av {as_['antall']} |",
        f"| Kall som feilet | {os_['feil']} |", "",
        "De faste reglene testes separat i `tests/test_regler.py` og treffer fasiten i alle demoordrene.", "",
        "## Ordresjekk per sak", "",
        "| Sak | Forventet | Funnet | AI-funn | Utenom fasit | Stoppet av kontroll |", "|---|---|---|---|---|---|",
    ]
    for r in ordre:
        linjer.append(f"| {r['navn']} | {', '.join(r['forventet']) or 'ingen'} | {', '.join(r['truffet']) or '-'} | "
                      f"{r['ai_funn']} | {r['ekstra']} | {r['forkastet']} |")
    linjer += ["", "## Avvik per sak", "", "| Sak | Melding | Fasit | Fikk | Årsak (fasit) | OK |", "|---|---|---|---|---|---|"]
    for r in avvik:
        fasit = ", ".join(f"{k} × {v}" for k, v in r["fasit"].items()) or "ingen"
        fikk = ", ".join(f"{k} × {v}" for k, v in r["fikk"].items()) or "ingen"
        ok = "ja" if r["linjer_ok"] and r["arsak_ok"] else ("linjer" if r["linjer_ok"] else ("årsak" if r["arsak_ok"] else "nei"))
        linjer.append(f"| {r['navn']} | {r['melding'][:70]} | {fasit} | {fikk} | {r['arsak']} ({r['fasit_arsak']}) | {ok} |")
    linjer += ["", "«Utenom fasit» er AI-funn som ikke står i fasiten. På ordrer i orden regnes de som falske alarmer. "
               "På ordrer med kjente feil kan de være riktige ekstra funn, og må leses manuelt.", ""]
    return "\n".join(linjer)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai", default=None)
    args = parser.parse_args()
    backend = velg_backend(args.ai)
    print(f"Evaluerer med {backend.navn} ...", flush=True)
    ordre, os_ = evaluer_ordresjekk(backend)
    print(f"  ordresjekk: {os_['treff']}/{os_['forventet']} treff, "
          f"{os_['rene_uten_alarm']}/{os_['rene']} rene uten alarm", flush=True)
    avvik, as_ = evaluer_avvik(backend)
    print(f"  avvik: {as_['linjer_ok']}/{as_['antall']} linjer, {as_['arsak_ok']}/{as_['antall']} årsak", flush=True)
    UT.write_text(skriv_rapport(backend, ordre, os_, avvik, as_), encoding="utf-8")
    print(f"Skrev {UT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

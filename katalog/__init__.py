"""Strai sin elementoversikt (juni 2026) som oppslagstabell, og modellreglene fra modelloversikten."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .modeller import MODELLER, Modell

FIL = Path(__file__).parent / "elementer.json"
KILDE = "Strai elementoversikt, juni 2026"


@dataclass(frozen=True)
class Element:
    kode: str
    beskrivelse: str
    kategori: str
    bredde_cm: int | None
    fronter: int | None
    side: int
    lengde_cm: int | None = None  # bare sokler, lest fra beskrivelsen

    @property
    def tekst(self) -> str:
        return self.beskrivelse.lower()


class KatalogMangler(RuntimeError):
    pass


@lru_cache(maxsize=1)
def alle() -> dict[str, Element]:
    if not FIL.exists():
        raise KatalogMangler(
            "katalog/elementer.json finnes ikke. Den bygges fra Strai sin offentlige elementoversikt "
            "og ligger ikke i repoet. Kjør: python -m katalog.bygg (krever pdftotext fra poppler).")
    data = json.loads(FIL.read_text(encoding="utf-8"))
    return {e["kode"]: Element(**e) for e in data["elementer"]}


def finn(kode: str) -> Element | None:
    return alle().get((kode or "").strip().upper())


def modell(navn: str | None) -> Modell | None:
    return MODELLER.get((navn or "").strip().lower())


SKAPKATEGORIER = {"benkeskap", "oppvaskskap", "kolonialseksjon", "komfyrseksjon", "skuffeseksjon", "underskap",
                  "mikroseksjon benk", "vinkelhjørneskap", "overskap", "høyskap", "mikroskap"}


def er_hengslet_dor(e: Element) -> bool:
    """Skap med sidehengslet dør. Løse fronter, som dør til oppvaskmaskin, er ikke hengslet i skapet."""
    if e.kategori not in SKAPKATEGORIER:
        return False
    return bool(re.search(r"\bdør\b|\bdører\b", e.tekst)) and "topphengslet" not in e.tekst


__all__ = ["Element", "KILDE", "KatalogMangler", "MODELLER", "Modell", "alle", "finn", "modell", "er_hengslet_dor"]

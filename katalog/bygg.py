"""Bygger katalog/elementer.json fra Strai sin offentlige elementoversikt (PDF, juni 2026).

    python -m katalog.bygg            # laster ned PDF-en og bygger JSON
    python -m katalog.bygg sti.pdf    # bruk en lokal kopi

Krever `pdftotext` (poppler). PDF-en sjekkes ikke inn, bare de utledede elementene
(kode, beskrivelse, kategori, bredde, antall fronter) med kildehenvisning.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KILDE_URL = "https://www.strai.no/media/lmnbay1o/strai-elementoversikt-juni.pdf"
UT = Path(__file__).parent / "elementer.json"

KODE = re.compile(r"\b([A-Z]{2}\d{6}[A-Z]?)\b")
STOY = re.compile(r"^(H:\s*\d+|Frontmål|\*.*)$")

# Prefiks -> kategori. Bare prefikser vi har sett med sikker betydning i elementoversikten.
KATEGORI = {
    "SK": "benkeskap", "OB": "oppvaskskap", "KO": "kolonialseksjon", "DK": "komfyrseksjon",
    "SS": "skuffeseksjon", "XL": "skuffeseksjon", "BL": "skuffeseksjon", "BU": "underskap",
    "TR": "underskap", "MX": "benkeskap", "SM": "mikroseksjon benk", "HB": "vinkelhjørneskap",
    "OS": "overskap", "OL": "overskap", "OG": "overskap", "SG": "overskap", "XS": "overskap",
    "HS": "overskap", "GO": "overskap", "OT": "overskap", "OM": "overskap", "VT": "overskap",
    "HU": "høyskap", "HV": "høyskap", "MS": "høyskap", "BH": "høyskap", "LH": "høyskap",
    "ST": "høyskap", "KL": "høyskap", "KS": "høyskap", "UT": "høyskap",
    "HM": "mikroskap", "GR": "håndtak", "HE": "hengsel", "SO": "sokkel", "TP": "topplist",
    "SF": "skuffefront", "GD": "glassdør", "GL": "glassdør", "XD": "glassdør", "BD": "dør og rygg",
    "AB": "tilbehør", "GM": "tilbehør", "IB": "innredning", "LS": "innredning", "GY": "innredning",
    "UD": "tilbehør", "EB": "tilbehør", "IT": "tilbehør", "LG": "sokkeltilbehør", "GA": "garderobe",
}
# Kategorier der koden har bredde i cm på plass 3 til 5 (SK060001 = 60 cm, HB090001H = 90 cm).
MED_BREDDE = {"benkeskap", "oppvaskskap", "kolonialseksjon", "komfyrseksjon", "skuffeseksjon", "underskap",
              "mikroseksjon benk", "overskap", "høyskap", "mikroskap", "vinkelhjørneskap"}

# Noen prefikser blander flere typer (SB er både strykebrettskap og sokkelhjørner, SO er både sokler,
# sokkelskuffer og klips). Beskrivelsen avgjør da, og den vinner over prefikset.
BESKRIVELSE_KATEGORI = [
    (r"^sokkel \d+\s*×|^sokkelfront \d+ cm", "sokkel"),
    (r"^sokkelskuff", "sokkelskuff"),
    (r"^sokkelskap", "sokkelskap"),
    (r"sokkelhjørne|skjøtelist for sokkel|sokkelben|sokkelklips|tetningslist", "sokkeltilbehør"),
    (r"^strykebrettskap", "høyskap"),
]
SKRIVEFEIL = [("skufffer", "skuffer"), ("Kolonialseskjon", "Kolonialseksjon"), ("blindtfelt", "blindfelt"),
              ("blindfeltfor", "blindfelt for")]


def rens(beskrivelse: str) -> str:
    """Fjerner rester fra PDF-oppsettet og retter åpenbare skrivefeil i kildeteksten."""
    b = re.sub(r"^(\d+\s+)?(Frontmål|H:\s*\d+)\s+", "", beskrivelse.strip())
    for feil, riktig in SKRIVEFEIL:
        b = b.replace(feil, riktig)
    b = re.sub(r"(?<=[a-zæøå])(?=\d)", " ", b)  # «Kolonialseksjon80» blir «Kolonialseksjon 80»
    return re.sub(r"\s+", " ", b).strip(" *")


def kategori_for(kode: str, beskrivelse: str) -> str:
    tekst = beskrivelse.lower()
    for monster, kategori in BESKRIVELSE_KATEGORI:
        if re.search(monster, tekst):
            return kategori
    if kode[:2] in ("SO", "SB"):
        return "sokkeltilbehør"
    return KATEGORI.get(kode[:2], "annet")


def sokkellengde(kategori: str, beskrivelse: str) -> int | None:
    m = re.match(r"sokkel (\d+)\s*×|sokkelfront (\d+) cm", beskrivelse.lower())
    return int(m.group(1) or m.group(2)) if kategori == "sokkel" and m else None


def antall_fronter(beskrivelse: str) -> int | None:
    """Antall dører og skuffefronter som trenger håndtak. None når vi ikke er sikre."""
    b = beskrivelse.lower().replace("skufffer", "skuffer")
    if re.search(r"glass|sjalusi|påmontert|3d front|2d front|blindfelt|blindtfelt|uten innredning|u / front", b):
        return None
    if m := re.search(r"\((\d)\s*\+\s*(\d)\)", b):
        return int(m.group(1)) + int(m.group(2))
    dorer = 0
    if m := re.search(r"(\d)\s*dører", b):
        dorer = int(m.group(1))
    elif re.search(r"\bdør\b", b):
        dorer = 1
    skuffer = 0
    if m := re.search(r"(\d)\s*(?:xl\s*)?skuff(?:er)?\b", b):
        skuffer = int(m.group(1))
    elif re.search(r"\bskuff\b", b):
        skuffer = 1
    total = dorer + skuffer
    return total or None


def tolk(tekst: str) -> list[dict]:
    linjer = [l.strip() for l in tekst.replace("\f", "\n").splitlines()]
    elementer: dict[str, dict] = {}
    side = 1
    for i, linje in enumerate(linjer):
        if m := re.match(r"^(\d{1,3})\s*\|\s*K\s*J", linje):
            side = int(m.group(1)) + 1
        treff = KODE.search(linje)
        if not treff:
            continue
        kode = treff.group(1)
        etter = re.sub(r"\s{2,}.*$", "", linje[treff.end():].strip())
        if len(etter) < 6:  # koden står alene, beskrivelsen ligger på nabolinjene
            biter = []
            for nabo in (linjer[i - 1] if i else "", linjer[i + 1] if i + 1 < len(linjer) else ""):
                nabo = re.sub(r"^(H:\s*\d+|Frontmål)\s*", "", nabo).strip()
                if nabo and not KODE.search(nabo) and not STOY.match(nabo):
                    biter.append(nabo)
            etter = " ".join(biter)
        beskrivelse = rens(etter)
        if len(beskrivelse) < 6 or kode in elementer:
            continue
        kategori = kategori_for(kode, beskrivelse)
        elementer[kode] = {
            "kode": kode,
            "beskrivelse": beskrivelse,
            "kategori": kategori,
            "bredde_cm": int(kode[2:5]) if kategori in MED_BREDDE and kode[2:5].isdigit() else None,
            "fronter": antall_fronter(beskrivelse) if kategori in MED_BREDDE else None,
            "lengde_cm": sokkellengde(kategori, beskrivelse),
            "side": side,
        }
    return sorted(elementer.values(), key=lambda e: e["kode"])


def main() -> int:
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with tempfile.TemporaryDirectory() as mappe:
        if pdf is None:
            pdf = Path(mappe) / "elementoversikt.pdf"
            print(f"Laster ned {KILDE_URL} ...")
            # curl, fordi nettstedet avviser Pythons standardklient (HTTP 403).
            subprocess.run(["curl", "-sSfL", "-o", str(pdf), KILDE_URL], check=True)
        tekst = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True,
                               check=True).stdout
    elementer = tolk(tekst)
    UT.write_text(json.dumps({"kilde": KILDE_URL, "utgave": "juni 2026", "elementer": elementer},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    med_fronter = sum(1 for e in elementer if e["fronter"])
    print(f"{len(elementer)} elementer skrevet til {UT} ({med_fronter} med kjent antall fronter).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Testsett med fasit for AI-delen. Demoordrene brukes også, se demo/ordre_data.py.

Ordresjekk: `forventet` er det AI-en skal finne. Et punkt regnes som truffet når et AI-funn har
en kode som starter med teksten (på linjen eller i forslaget), eller nevner ordet i beskrivelsen.
Tom liste betyr at ordren følger ønskene, og alle «stopp»/«avklar» fra AI regnes da som falsk alarm.

Avvik: `linjer` er fasiten {kode: antall}, `arsak` er forventet årsak.
"""
from demo.ordre_data import AVVIK, ORDRER

# (modell, ønsker, linjer, forventet)
EKSTRA_ORDRER = [
    ("Voss", "Vi vil ha kjøkkenøy med induksjon og skuffer, og et høyskap til stekeovnen.",
     [("SK060204", 2), ("KO060224", 1), ("HV-IND60", 1), ("GR200052", 6), ("SO240018", 1)], ["stekeovn"]),
    ("Rondane", "Glassdører i alle overskapene, så vi kan vise fram serviset.",
     [("OS060002", 3), ("SK060001", 2), ("GR200052", 5), ("SO240018", 1)], ["OS060002"]),
    ("Femunden", "Enkle hvite dører, ingen skuffer.",
     [("SK060001", 3), ("GR200052", 3), ("SO240018", 1)], []),
    ("Voss", "Vi har to små barn, så vi vil ha barnesikring på skuffene.",
     [("SK060204", 2), ("GR200052", 4), ("SO240018", 1)], ["barnesikring"]),
    ("Svalbard", "Oppvaskskap med vanlig dør for firkantvask, og en vanlig oppvaskmaskin.",
     [("OB060007", 1), ("HV-VASK60", 1), ("HV-OPPV60", 1), ("BD060072O", 1), ("SK060001", 1), ("GR200052", 2),
      ("SO240018", 1)], []),
    ("Vinje", "Kjøkkenet skal ha 80 cm induksjon, vi lager mye mat.",
     [("KO060224", 1), ("HV-IND60", 1), ("SK060001", 2), ("GR200052", 4), ("SO240018", 1)], ["HV-IND60"]),
    ("Dalen", "Hvitt og enkelt, Premium White.",
     [("SK060001", 2), ("GR200052", 2), ("SO240018", 1)], []),
    ("Voss", "Et eget miksmasterskap på 60 cm, resten vanlige benkeskap.",
     [("SK060001", 3), ("GR200052", 3), ("SO240018", 1)], ["MX060001"]),
]


def ordrecaser() -> list[dict]:
    caser = [{"navn": f"Demo {i + 1}: {o[2]}", "modell": o[2], "onsker": o[4], "linjer": o[5],
              "forventet": o[6]["ai"]} for i, o in enumerate(ORDRER)]
    caser += [{"navn": f"Eval {i + 1}: {m}", "modell": m, "onsker": o, "linjer": l, "forventet": f}
              for i, (m, o, l, f) in enumerate(EKSTRA_ORDRER)]
    return caser


# (indeks i ORDRER, avsender, melding, fasit)
EKSTRA_AVVIK = [
    (0, "kunde", "Induksjonstoppen kom med knust glass, esken var skadet på hjørnet.",
     {"linjer": {"HV-IND60": 1}, "arsak": "transport"}),
    (0, "montør", "Det mangler én sokkel og to håndtak. Kolliene var hele.",
     {"linjer": {"SO240018": 1, "GR200052": 2}, "arsak": "pakking"}),
    # Fasiten sa først SK080202. Claude påpekte at ordren også har en 80 cm kolonialseksjon med skuffer,
    # så meldingen er tvetydig. Riktig svar er å legge den i «uklart», ikke å gjette.
    (3, "montør", "Skuffefronten på det ene 80-skapet er boret feil, håndtakshullene sitter skjevt.",
     {"linjer": {}, "arsak": "produksjon"}),
    (9, "kunde", "Vi fikk oppvaskskap med to dører, men vi ville ha kildesortering. Står det sånn på ordren?",
     {"linjer": {"OB060010": 1}, "arsak": "ordrefeil"}),
    (11, "montør", "Alt er på plass, men det lå en ekstra kartong med topplister som ikke er bestilt.",
     {"linjer": {}, "arsak": "pakking"}),
    (4, "montør", "Bora-toppen kom ikke i det hele tatt.", {"linjer": {"HV-BORA80": 1}, "arsak": "pakking"}),
]


def avvikscaser() -> list[dict]:
    alle = [(i, a, m, f) for i, a, m, f in AVVIK] + EKSTRA_AVVIK
    return [{"navn": f"Avvik {n + 1}", "ordre": ORDRER[i], "avsender": a, "melding": m, "fasit": f}
            for n, (i, a, m, f) in enumerate(alle)]

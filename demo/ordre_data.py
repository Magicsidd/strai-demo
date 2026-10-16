"""Demoordrer fra butikk til fabrikk. Kunder og ønsker er oppdiktet, elementkodene er Strai sine.

Hver ordre har en `fasit`: hvilke regler som skal slå ut, og hvilke AI-funn vi forventer.
Den samme fasiten brukes av testene (regler) og av evalueringen (AI).
"""
from __future__ import annotations

# (kunde, butikk, modell, uker til ønsket levering, ønsker, linjer [(kode, antall)], fasit)
ORDRER = [
    ("Ingrid og Pål Hansen", "Strai Kristiansand", "Voss", 8,
     "Lyst og enkelt. Skuffer under platetoppen og oppvaskmaskin ved siden av vasken.",
     [("SK060204", 2), ("OB060007", 1), ("HV-VASK60", 1), ("KO060224", 1), ("HV-IND60", 1), ("HV-OPPV60", 1),
      ("BD060072O", 1), ("SS060204", 1), ("GR200052", 11), ("SO240018", 2)],
     {"regler": [], "ai": []}),
    ("Marte Lunde", "Strai Bergen", "Falketind", 9,
     "Vi vil ha en hjørneløsning så vi får utnyttet hjørnet, og linoleum i grønt.",
     [("HB090001H", 1), ("SK060001", 2), ("KO060204", 1), ("SO240025", 2)],
     {"regler": ["R04"], "ai": []}),
    ("Tor Andreas Bakke", "Strai Oslo", "Trollstigen", 9,
     "Kun skuffer i benken, ingen overskap. Oppvaskmaskinen vi har kjøpt er 57 cm dyp.",
     [("SK060204", 2), ("OS060002", 2), ("HV-OPPV60D", 1), ("BD060072O", 1), ("SO240018", 1)],
     {"regler": ["R04", "R09", "R10"], "ai": []}),  # overskapet tas av R04, AI skal ikke gjenta det
    ("Hilde Sørensen", "Strai Arendal", "Femunden", 6,
     "Induksjonstopp 80 cm på kjøkkenøya med skuffer under.",
     [("KO080204", 1), ("HV-IND80", 1), ("SK080202", 2), ("GR200054", 8), ("SO240018", 2)],
     {"regler": ["R05"], "ai": []}),
    ("Jonas Eide", "Strai Stavanger", "Rondane", 7,
     "Bora med kullfilter, ikke avtrekk ut gjennom veggen.",
     [("KO080224", 1), ("HV-BORA80", 1), ("SK060010", 2), ("GR200052", 6), ("SO240018", 1)],
     {"regler": ["R06"], "ai": []}),
    ("Silje Mo", "Kjøkkenhuset Lillesand", "Senja", 7,
     "Håndtak i sort på alle dører og skuffer.",
     [("SK080202", 2), ("SK060010", 1), ("GR200054", 4), ("SO240018", 1)],
     {"regler": ["R10"], "ai": []}),
    ("Erik og Nora Haugen", "Strai Oslo", "Bygdøy", 3,
     "Vi flytter inn om tre uker og må ha kjøkkenet før det.",
     [("SK060001F", 2), ("OB060007F", 1), ("HV-VASK60", 1), ("KO060224F", 1), ("HV-IND60", 1), ("GR200052", 5),
      ("SO240018", 1)],
     {"regler": ["R12"], "ai": []}),
    ("Camilla Strand", "Strai Kristiansand", "Femunden", 8,
     "Vi trenger plass til mikrobølgeovnen i benkehøyde, og oppvaskmaskinen må være 45 cm fordi kjøkkenet er smalt.",
     [("SK060001", 2), ("OB060007", 1), ("HV-VASK60", 1), ("HV-OPPV60", 1), ("BD060072O", 1), ("GR200052", 3),
      ("SO240018", 1)],
     {"regler": [], "ai": ["SM060246", "HV-OPPV45"]}),
    ("Ola Strøm", "Strai Oslo", "Lindøya", 8,
     "Mange skuffer, gjerne skuffeseksjoner med fire skuffer.",
     [("SS060204", 2), ("SK060001", 1), ("GR200052", 9), ("SO240018", 1)],
     {"regler": ["R04"], "ai": []}),
    ("Kjetil Ness", "Strai Kristiansand", "Svalbard", 6,
     "Firkantvask i stål og kildesortering med tre fraksjoner under vasken.",
     [("OB060010", 1), ("HV-VASK60", 1), ("SK060001", 2), ("GR200052", 4), ("SO240018", 1)],
     {"regler": ["R07"], "ai": ["OB060010"]}),
    ("Astrid Hval", "Strai Bergen", "Voss", 10,
     "Lang benk med plass til miksmaster i eget skap. Ellers dører.",
     [("SK080001", 3), ("SK060001", 2), ("GR200052", 8), ("HV-OPPV60", 1), ("SO240018", 1)],
     {"regler": ["R08", "R11"], "ai": ["MX"]}),
    ("Bjørn Tveit", "Strai Stavanger", "Senja", 9,
     "Hvite fronter, sorte håndtak, induksjon 60 cm og vanlig dør under vasken.",
     [("SK060204", 1), ("OB060007", 1), ("HV-VASK60", 1), ("KO060224", 1), ("HV-IND60", 1), ("GR200054", 5),
      ("SO240018", 1)],
     {"regler": [], "ai": []}),
]

# Avvik etter levering: (indeks i ORDRER, avsender, melding, fasit)
AVVIK = [
    (0, "montør", "Kolli 4 manglet helt. Vi har fått 7 håndtak, og den ene skuffeseksjonen kom med bulk i "
                  "toppskuffen. Emballasjen var revet.",
     {"linjer": {"GR200052": 4, "SS060204": 1}, "arsak": "pakking"}),
    (5, "montør", "Har montert alt, men det er 4 håndtak og 8 fronter. Ordren var sånn, men kunden vil ha håndtak "
                  "på alle.", {"linjer": {"GR200054": 4}, "arsak": "ordrefeil"}),
    (11, "kunde", "Fronten på oppvaskskapet har en sprekk i lakken langs kanten, og vi mangler sokkelen.",
     {"linjer": {"OB060007": 1, "SO240018": 1}, "arsak": "produksjon"}),
]

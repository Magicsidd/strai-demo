# Evaluering av AI-delen

Kjørt 16.10.2026 med `claude_cli` (`claude-sonnet-5-5`). Promptversjoner: ordresjekk `3aed53bc`, avvik `fff82b8e`.
Kjør selv med `python -m evals.kjor`. Fasiten står i `evals/fasit.py` og `demo/ordre_data.py`.

## Sammendrag

| Mål | Resultat |
|---|---|
| Ordresjekk: forventede funn AI-en fant | 9 av 9 |
| Ordresjekk: ordrer i orden uten falsk alarm | 11 av 12 |
| Ordresjekk: AI-forslag stoppet av kontrollene | 0 |
| Avvik: riktige linjer og antall | 9 av 9 |
| Avvik: riktig årsak | 8 av 9 |
| Kall som feilet | 0 |

De faste reglene testes separat i `tests/test_regler.py` og treffer fasiten i alle demoordrene.

## Ordresjekk per sak

| Sak | Forventet | Funnet | AI-funn | Utenom fasit | Stoppet av kontroll |
|---|---|---|---|---|---|
| Demo 1: Voss | ingen | - | 0 | 0 | 0 |
| Demo 2: Falketind | ingen | - | 1 | 1 | 0 |
| Demo 3: Trollstigen | ingen | - | 0 | 0 | 0 |
| Demo 4: Femunden | ingen | - | 0 | 0 | 0 |
| Demo 5: Rondane | ingen | - | 0 | 0 | 0 |
| Demo 6: Senja | ingen | - | 0 | 0 | 0 |
| Demo 7: Bygdøy | ingen | - | 0 | 0 | 0 |
| Demo 8: Femunden | SM060246, HV-OPPV45 | SM060246, HV-OPPV45 | 3 | 1 | 0 |
| Demo 9: Lindøya | ingen | - | 0 | 0 | 0 |
| Demo 10: Svalbard | OB060010 | OB060010 | 1 | 0 | 0 |
| Demo 11: Voss | MX | MX | 1 | 0 | 0 |
| Demo 12: Senja | ingen | - | 0 | 0 | 0 |
| Eval 1: Voss | stekeovn | stekeovn | 1 | 0 | 0 |
| Eval 2: Rondane | OS060002 | OS060002 | 1 | 0 | 0 |
| Eval 3: Femunden | ingen | - | 0 | 0 | 0 |
| Eval 4: Voss | barnesikring | barnesikring | 1 | 0 | 0 |
| Eval 5: Svalbard | ingen | - | 0 | 0 | 0 |
| Eval 6: Vinje | HV-IND60 | HV-IND60 | 1 | 0 | 0 |
| Eval 7: Dalen | ingen | - | 0 | 0 | 0 |
| Eval 8: Voss | MX060001 | MX060001 | 1 | 0 | 0 |

## Avvik per sak

| Sak | Melding | Fasit | Fikk | Årsak (fasit) | OK |
|---|---|---|---|---|---|
| Avvik 1 | Kolli 4 manglet helt. Vi har fått 7 håndtak, og den ene skuffeseksjone | GR200052 × 4, SS060204 × 1 | GR200052 × 4, SS060204 × 1 | pakking (pakking) | ja |
| Avvik 2 | Har montert alt, men det er 4 håndtak og 8 fronter. Ordren var sånn, m | GR200054 × 4 | GR200054 × 4 | ordrefeil (ordrefeil) | ja |
| Avvik 3 | Fronten på oppvaskskapet har en sprekk i lakken langs kanten, og vi ma | OB060007 × 1, SO240018 × 1 | OB060007 × 1, SO240018 × 1 | ukjent (produksjon) | linjer |
| Avvik 4 | Induksjonstoppen kom med knust glass, esken var skadet på hjørnet. | HV-IND60 × 1 | HV-IND60 × 1 | transport (transport) | ja |
| Avvik 5 | Det mangler én sokkel og to håndtak. Kolliene var hele. | SO240018 × 1, GR200052 × 2 | SO240018 × 1, GR200052 × 2 | pakking (pakking) | ja |
| Avvik 6 | Skuffefronten på det ene 80-skapet er boret feil, håndtakshullene sitt | ingen | ingen | produksjon (produksjon) | ja |
| Avvik 7 | Vi fikk oppvaskskap med to dører, men vi ville ha kildesortering. Står | OB060010 × 1 | OB060010 × 1 | ordrefeil (ordrefeil) | ja |
| Avvik 8 | Alt er på plass, men det lå en ekstra kartong med topplister som ikke  | ingen | ingen | pakking (pakking) | ja |
| Avvik 9 | Bora-toppen kom ikke i det hele tatt. | HV-BORA80 × 1 | HV-BORA80 × 1 | pakking (pakking) | ja |

«Utenom fasit» er AI-funn som ikke står i fasiten. På ordrer i orden regnes de som falske alarmer. På ordrer med kjente feil kan de være riktige ekstra funn, og må leses manuelt.

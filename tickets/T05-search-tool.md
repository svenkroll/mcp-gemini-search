# T05 Tool `search`

| | |
| --- | --- |
| Abhängig von | T04 |
| Blockiert | T07, T09 |
| Bereich | tools, source-resolution, tests |

## Ziel

Die fachliche `search`-Logik mit dem Vertrag aus ADR 0003 implementieren.

## Kontext

Lesen: `AGENTS.md`, ADR 0003, 0005, 0006 bis 0009 und T04. Der Aufruf liefert
auch bei lückenhafter Grounding-Metadaten ein ehrliches Teilergebnis.

## Vorgaben

- `query` trimmen und auf 1 bis 4.000 Zeichen prüfen; `max_sources` auf 1 bis
  10 prüfen, Standard 5. Ungültige Eingaben erhalten eigene Meldungen.
- Gemini Search Grounding über den Adapter aufrufen und Antwort, Suchanfragen,
  Citation-Spannen und Quellen normalisieren.
- Quellen mit gemeinsamer URL-Policy aus ADR 0008 auflösen, nach Ziel-URL
  bündeln und bei nicht möglicher Auflösung verwerfen.
- Keine Citation-Spannen rekonstruieren; fehlende Quellen, Belege oder
  Suchanfragen bleiben leere Listen, kein Fehler.
- Ergebnisse bleiben frameworkfrei und werden später vom Server abgebildet.

## Nicht im Umfang

FastMCP-Dekoratoren, HTTP-Authentisierung, allgemeiner URL-Extractor,
permanentes Quellencaching oder weitere Suchanbieter.

## Akzeptanzkriterien

- [ ] Tests decken Validierungsgrenzen, Quellenbündelung, nicht auflösbare
  Quellen, fehlende Metadaten, Teilergebnisse und Upstream-Fehler ab.
- [ ] Jeder zurückgegebene Beleg stammt aus tatsächlich gelieferter
  Citation-Metadaten.
- [ ] URLs passieren dieselben Sicherheitsregeln wie `analyze_url`.
- [ ] Modul bleibt ohne FastMCP importierbar.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.

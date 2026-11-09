---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0003 Tool-Vertrag `search`

## Kontext und Problemstellung

Eine Gemini-Zusammenfassung ohne belastbare Quellen hilft einem aufrufenden LLM
nur begrenzt. Der Vertrag muss Belege direkt an Aussagen binden, ohne fehlende
Grounding-Metadaten zu erfinden oder nützliche Teilergebnisse zu verwerfen.

## Betrachtete Optionen

1. Nur Markdown-Antwort und Quellenliste wie nav9v liefern.
2. Ausschließlich rohe Suchtreffer liefern.
3. Antwort, normalisierte Quellen und Belege strukturiert liefern.

## Entscheidung

Gewählt wird **Option 3**. Eingabe ist `query` mit 1 bis 4.000 Zeichen nach
dem Trimmen sowie optional `max_sources` von 1 bis 10, Standard 5.

Erfolgreiches `structuredContent` enthält:

- `answer`: Geminis Antworttext;
- `sources`: höchstens eine Quelle je aufgelöster Ziel-URL mit `title`, `url`
  und `evidence`;
- `evidence`: zitierter Antworttext und nur von Gemini gelieferte
  `start_index`/`end_index`-Werte;
- `search_queries`: tatsächlich von Gemini ausgeführte Suchanfragen.

Quellen werden mit engem Timeout auf echte Ziel-URLs aufgelöst, nach Ziel-URL
zusammengeführt und bei fehlender Auflösung verworfen. Eine Antwort ohne
Quellen, Belege oder Suchanfragen bleibt ein erfolgreiches Teilergebnis; die
betreffende Liste ist dann leer. `structuredContent` ist kanonisch; die
Textausgabe enthält denselben Inhalt als JSON.

## Konsequenzen

- Gut: Clients können Aussagen, Quellen und Belege getrennt bewerten.
- Gut: Doppelte Quellen und abgelaufene Redirect-URLs verschlechtern die Ausgabe nicht.
- Schlecht: Nicht auflösbare Quellen sind für den Client nicht sichtbar; dies weicht
  bewusst von der PRD-Skizze ab.
- Schlecht: Der Adapter muss aktuelle Citation-Metadaten sauber normalisieren.

## Offen

Der Baseline-Lauf prüft, ob nav9v noch Redirect-URLs liefert. Der Vertrag bleibt
auch ohne Grounding-Metadaten vollständig definiert.

## Weitere Informationen

- [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search)
- ADR 0006: Gemini-Anbindung

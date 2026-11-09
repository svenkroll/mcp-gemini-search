---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0004 Tool-Vertrag `analyze_url`

## Kontext und Problemstellung

Ein allgemeines Modellwissen darf nicht als Inhalt einer nicht geladenen Seite
ausgegeben werden. Der Tool-Aufruf braucht daher eine konkrete Fragestellung und
einen klaren Unterschied zwischen Abrufversagen und ehrlichem Nichtfinden.

## Betrachtete Optionen

1. Optionale Frage mit automatischer Zusammenfassung.
2. Pflichtfrage, Antwort nur bei bestätigtem Abruf.
3. Rohinhalt als Extract-Service zurückgeben.

## Entscheidung

Gewählt wird **Option 2**. `url` akzeptiert ausschließlich eine zulässige
öffentliche HTTP(S)-URL nach ADR 0008. `question` ist Pflicht, wird getrimmt
und unterliegt derselben 4.000-Zeichen-Grenze wie eine Suchanfrage.

Bei erfolgreichem Abruf enthält `structuredContent` `answer`, die abgerufene
`url` und `retrieval_status: "retrieved"`. Gemini URL Context liefert dafür
pro URL einen eigenen Abrufstatus. Kann die Seite die Frage nicht beantworten,
lautet die Antwort ausdrücklich entsprechend; dies ist kein Fehler. HTML und
PDF sind im Umfang, Rohinhalt und weitere Inhaltsarten nicht.

Scheitert Abruf, Sicherheitsprüfung oder Inhaltsunterstützung, ist das Ergebnis
`isError: true`; es gibt keine inhaltsbezogene Antwort aus Modellwissen.

## Konsequenzen

- Gut: Clients können Seiteninhalt von Modellwissen unterscheiden.
- Gut: Eine verpflichtende Frage erzeugt fokussierte Tool-Aufrufe.
- Schlecht: Das Tool ersetzt keinen allgemeinen Extract-Endpunkt.
- Schlecht: Ein nicht erreichbares Dokument erzeugt keinen Teilnutzen.

## Offen

Die tatsächlichen Werte von Gemini `url_context_result.status` werden als
interne Fehlerklassen abgebildet und mit aufgezeichneten Antworten getestet.

## Weitere Informationen

- [Gemini URL Context](https://ai.google.dev/gemini-api/docs/url-context)
- ADR 0008: Sicherheit

---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0009 Backend-Schnittstelle

## Kontext und Problemstellung

Gemini ist im ersten Release der einzige Backend-Anbieter. Serper oder Tavily
sollen später möglich sein, ohne dass deren besondere Felder den MCP-Vertrag
heute bestimmen oder die Tool-Logik an Gemini-Antworttypen koppeln.

## Betrachtete Optionen

1. Gemini direkt in den FastMCP-Tools aufrufen.
2. Eine kleine fachliche Provider-Grenze für beide Operationen einführen.
3. Jetzt eine vollständige Multi-Provider-Plattform bauen.

## Entscheidung

Gewählt wird **Option 2**. `gemini_client` implementiert eine kleine interne
Schnittstelle mit den Operationen `search` und `analyze_url`. Ein- und
Ausgabeobjekte enthalten ausschließlich normalisierte Anfrage-, Antwort-,
Quellen-, Beleg-, Retrieval- und Fehlerdaten. Gemini-spezifische SDK-Typen,
Grounding-Steps und Transportdetails verbleiben im Adapter.

`tools` übersetzt diese fachlichen Objekte in die Verträge aus ADR 0003 und
ADR 0004. `server` registriert nur MCP-Hüllen. Der erste Release hat exakt
einen Gemini-Adapter; Serper, Tavily, Provider-Auswahl und Fallbacks sind nicht
Teil des Umfangs.

## Konsequenzen

- Gut: Unit-Tests können mit einem Fake-Adapter ohne Netzwerk arbeiten.
- Gut: Ein späterer Anbieterwechsel berührt Tool-Vertrag und Server kaum.
- Gut: FastMCP-Abhängigkeit bleibt an der äußeren Schicht.
- Schlecht: Es entsteht eine kleine Abstraktion vor dem zweiten Anbieter.
- Schlecht: Provider-spezifische Stärken werden nicht vorzeitig exponiert.

## Offen

Ein zusätzlicher Anbieter benötigt ein neues ADR mit Qualitätsvergleich gegen
den Ground-Truth-Katalog, bevor er implementiert wird.

## Weitere Informationen

- ADR 0003: Tool-Vertrag `search`
- ADR 0004: Tool-Vertrag `analyze_url`
- ADR 0005: Ground Truth und Bewertung

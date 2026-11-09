---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0001 Rahmen und Ziel

## Kontext und Problemstellung

Gemini Search MCP soll LLM-Clients eine nützliche, belegbare Webrecherche und
Analyse öffentlicher URLs bereitstellen. Das Referenzprojekt nav9v zeigt den
Funktionsumfang, gibt aber Geminis Zusammenfassung und schwer verwertbare
Quellen weitgehend unverarbeitet weiter. Der Erfolg wird deshalb an
Antwortqualität und Belegbarkeit gemessen, nicht an minimalem Implementierungsaufwand.

## Betrachtete Optionen

1. nav9v forken und schrittweise ergänzen.
2. Eigenständigen Server mit gleichem Kernumfang schreiben.
3. Einen generischen Suchdienst mit mehreren Backends bauen.

## Entscheidung

Gewählt wird **Option 2**: eine eigenständige Neuentwicklung namens
**Gemini Search MCP** unter MIT-Lizenz. nav9v wird in der README als Ideengeber
genannt. Der erste Release bietet ausschließlich die Tools `search` und
`analyze_url`; Prompts, Resources, Nutzerverwaltung, Abrechnung und weitere
Suchanbieter gehören nicht dazu.

`search` liefert Antwort, echte Quellen und deren Belege. `analyze_url`
beantwortet eine konkrete Frage ausschließlich anhand einer tatsächlich
abgerufenen öffentlichen URL. Ground Truth, Baseline und Go/No-Go-Bewertung
sind Voraussetzung jeder Tool-Implementierung.

Der Dienst läuft öffentlich auf einer persönlichen URL in Kubernetes, ist aber
durch ein statisches Bearer-Token nur für den Besitzer zugänglich. Er ist kein
Suchdienst für Dritte und baut keinen Suchindex auf.

## Konsequenzen

- Gut: Der Vertrag kann auf LLM-Nutzen und überprüfbare Quellen ausgelegt werden.
- Gut: Architektur und Tests sind nicht durch nav9v-Strukturentscheidungen gebunden.
- Schlecht: Die README muss Herkunft und Unterschiede nachvollziehbar erklären.
- Schlecht: Die Qualitätssicherung erzeugt vor dem Produktcode Aufwand und API-Kosten.

## Offen

Keine Produktentscheidung offen. Die Google-Bedingungen und Modellfähigkeiten
werden in ADR 0006 mit Stand der jeweiligen Umsetzung überprüft.

## Weitere Informationen

- [PRD](../../PRD-gemini-search-mcp.md)
- [Entscheidungs- und Verifikationskatalog](../offene-fragen.md)

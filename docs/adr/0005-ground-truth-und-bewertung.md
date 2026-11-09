---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0005 Ground Truth und Bewertung

## Kontext und Problemstellung

Die Neuauflage soll nachweisbar nützlicher sein als nav9v. Ohne vorab definierte
Testfälle, Bewertung und Schwellenwerte wäre eine Qualitätsbehauptung subjektiv.

## Betrachtete Optionen

1. Qualität nur durch manuelle Stichproben bewerten.
2. Erst nach der Implementierung einen Eval-Katalog erstellen.
3. Versionierten Katalog vor Tool-Code, Baseline und kalibrierten Judge verwenden.

## Entscheidung

Gewählt wird **Option 3**. `eval/` enthält mindestens 40 YAML-Fälle für stabile
und aktuelle Fakten, technische Dokumentation, Deutsch/Englisch, ehrliches
Nichtwissen sowie HTML, PDF, Abruffehler und Prompt Injection. Jeder Fall hält
Frage, Kernaussage, erlaubte Quellen/Domains, Kategorie und Stichtag fest.

Vor jeder Implementierung läuft derselbe Katalog gegen einen festgehaltenen
nav9v-Commit, Modell und Konfiguration. Der gepinnte Judge `gemini-3.7-flash`
ist vom Produktmodell getrennt und bewertet Korrektheit, Belegbarkeit,
Quellenqualität, Ehrlichkeit und Injection-Resistenz. Mindestens zwölf
geschichtete Fälle werden manuell kalibriert; mehr als eine abweichende
Kernbewertung erfordert Überarbeitung.

Go/No-Go: Ehrlichkeit und Injection-Resistenz jeweils 100 %, Quellenqualität
mindestens 90 %, Korrektheit und Belegbarkeit mindestens 85 %; zusätzlich darf
die Neuauflage die nav9v-Baseline je Metrik nicht unterschreiten. Latenz und
Tokens werden erfasst, aber nicht als anfängliche Sperrgrenze verwendet.

## Konsequenzen

- Gut: Die Qualität entscheidet vor der Architekturästhetik.
- Gut: Baseline und spätere Ergebnisse sind vergleichbar und reproduzierbar.
- Schlecht: Katalogpflege und Kalibrierung benötigen bewusste Arbeit.
- Schlecht: Live-Aufrufe kosten Geld und laufen daher nicht in jedem PR.

## Offen

CI führt ausschließlich Offline-Tests mit kontrollierten Fixtures aus.
Wiederkehrende Live-Evaluierungen sind kein Release-1-Umfang und können später
als Feature Request ergänzt werden.

## Weitere Informationen

- [PRD, Abschnitt 6](../../PRD-gemini-search-mcp.md)
- [Entscheidungs- und Verifikationskatalog](../offene-fragen.md)

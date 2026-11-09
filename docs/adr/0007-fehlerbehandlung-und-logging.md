---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0007 Fehlerbehandlung und Logging

## Kontext und Problemstellung

MCP-Clients müssen Fehler von brauchbaren Teilergebnissen unterscheiden können.
Gleichzeitig braucht der Betreiber Diagnoseinformationen, ohne API-Key oder
unnötige Nutzerdaten zu protokollieren.

## Betrachtete Optionen

1. Fehler als normaler Antworttext ausgeben.
2. MCP-Fehler und strukturierte Teilergebnisse trennen, JSON nach stdout loggen.
3. Eigenen zentralen Log-Stack im ersten Release aufbauen.

## Entscheidung

Gewählt wird **Option 2**. Ungültige Eingaben, URL-Sicherheitsverstöße,
Upstream-Ausfälle und fehlgeschlagene URL-Abrufe liefern `isError: true` mit
kurzer, eigener und nicht technischer Meldung. Details stehen nur im Log mit
Request-ID. Eine erfolgreiche Suche mit lückenhaften Quellen bleibt ein
Teilergebnis, kein Fehler.

Jeder Tool-Aufruf erzeugt eine JSON-Zeile auf stdout mit Zeit, Request-ID, Tool,
Dauer, Status, Modell und vorhandenen Tokenwerten. Der Server erzeugt die
Request-ID. Query-Inhalte sind standardmäßig deaktiviert und nur ausdrücklich
konfigurierbar. Nie geloggt werden API-Key, Authorization-Header, Geheimnisse,
vollständige Webinhalte oder Exception-Texte für Clients.

## Konsequenzen

- Gut: Agenten können fehlerhafte Aufrufe erkennen und erneut planen.
- Gut: Container- und Kubernetes-Logging können JSON direkt sammeln.
- Schlecht: Fehlersuche benötigt Zugriff auf Betreiberlogs.
- Schlecht: Aktiviertes Query-Logging ist datenschutzrelevant.

## Offen

Die Aufbewahrung und Zugriffssteuerung von Logs liegt bei der
Cluster-Infrastruktur und nicht im Server.

## Weitere Informationen

- ADR 0003 und ADR 0004: Teilergebnisse und Abruffehler
- ADR 0008: Authentisierung und Eingabesicherheit

---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0006 Gemini-Anbindung

## Kontext und Problemstellung

Der Server braucht eine nicht blockierende, robuste Gemini-Anbindung für Search
Grounding und URL Context. Modell, Kosten, Datenschutz und Nutzungsbedingungen
müssen sichtbar konfigurierbar sein.

## Betrachtete Optionen

1. Synchroner Client ohne Begrenzungen wie nav9v.
2. Gemini Developer API mit asynchronem Adapter und festen Betriebsgrenzen.
3. Vertex AI als Voraussetzung für den ersten Release.

## Entscheidung

Gewählt wird **Option 2**. Der Adapter verwendet die Gemini Developer API mit
einem API-Key aus AI Studio und ausschließlich `client.aio`. Standardmodell ist
das stabile `gemini-3.8-flash`, konfigurierbar über Settings und nie als
verstreuter Codewert.

Ein Aufruf hat standardmäßig 60 Sekunden Gesamtzeit. Ein Semaphore begrenzt auf
vier parallele Gemini-Aufrufe. Bei 429 und transienten 5xx-Fehlern folgen nach
dem Erstversuch höchstens zwei Wiederholungen mit exponentiellem Backoff,
Zufallsanteil und Beachtung von `Retry-After`. Client-Abbruch beendet weitere
Arbeit. Tokenwerte stammen ausschließlich aus der API-Nutzungsmetrik.

Deployment, Baseline und Judge verwenden einen API-Key eines Projekts mit aktiver
Abrechnung. Die kostenlose Nutzung ist nur für direkte AI-Studio-Experimente
vorgesehen, nicht für den betriebenen Search-Grounding-Service. Die README
erläutert: Freie Dienste können Inhalte zur Produktverbesserung verwenden,
bezahlte nicht; bei Search Grounding speichert Google Prompt, Kontext und
Ausgabe dennoch 30 Tage für Grounding-Zwecke. Grounding wird nur im eigenen
persönlichen Workflow genutzt, nicht zum Aufbau eines Index oder für Dritte.

Für Gemini 3 und neuer umfasst der bezahlte Betrieb 5.000 kostenlose
Search-Requests pro Monat, geteilt über diese Modelle. Danach kostet jeder
weitere Request 14 USD je 1.000 Requests; das Standardlimit liegt bei 1.500
Requests pro Projekt und Tag. Ein einzelner Nutzerprompt kann mehrere
Google-Search-Requests auslösen. Tokenkosten des Modells bleiben davon getrennt.

## Konsequenzen

- Gut: Kein Gemini-Aufruf blockiert den Event-Loop.
- Gut: Last- und Fehlerverhalten sind konfigurierbar und testbar.
- Gut: Modellwechsel bleibt eine Konfigurationsentscheidung.
- Schlecht: Ein API-Key und aktuelle Tarifbedingungen bleiben Betriebsvoraussetzung.
- Schlecht: Grounding kostet abhängig vom Tarif und einzelnen Suchanfragen.

## Offen

Die exakte `google-genai`-Version wird im Lockfile gepinnt. Preis, Quote und
Google-Bedingungen werden vor Release gegen die aktuelle Primärquelle geprüft.

## Weitere Informationen

- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API Terms](https://ai.google.dev/gemini-api/terms)

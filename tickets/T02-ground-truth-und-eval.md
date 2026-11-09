# T02 Ground-Truth-Katalog und Eval-Werkzeug

| | |
| --- | --- |
| Abhängig von | T01 |
| Blockiert | T03 bis T06, T09 |
| Bereich | eval, quality |

## Ziel

Den versionierten Katalog und ein reproduzierbares Auswertungswerkzeug
bereitstellen, bevor irgendein Tool oder Gemini-Adapter implementiert wird.

## Kontext

Lesen: `AGENTS.md`, ADR 0001, 0003, 0004, 0005, 0006 und 0008. Der Katalog
ist die Referenz für nav9v-Baseline und Neuauflage, nicht ein Test der späteren
Implementierungsdetails.

## Vorgaben

- Mindestens 40 YAML-Fälle in `eval/` mit einem validierten Schema.
- Kategorien: stabile Fakten, zeitabhängige Fakten, technische Dokumentation,
  Deutsch/Englisch, ehrliches Nichtwissen sowie HTML, PDF, Abruffehler und
  Prompt Injection für `analyze_url`.
- Jeder Fall enthält ID, Tool, Eingabe, erwartete Kernaussage, erlaubte
  Quellen/Domains, Kategorie, Ground-Truth-Stichtag und bei URL-Fällen Test-URL.
- Kontrollierte Injection- und Fehlerressourcen sind reproduzierbar und kein
  unkontrollierter externer Zufall.
- Das Werkzeug importiert gespeicherte Ausgaben, bewertet die fünf binären
  Qualitätsmetriken, erfasst Latenz/Tokens und erzeugt einen maschinenlesbaren
  sowie einen lesbaren Bericht.
- Judge-Prompt und Judge-Modell `gemini-3.7-flash` sind versioniert; der
  Toolaufruf für Live-Judging bleibt explizit und läuft nie in PR-CI.

## Nicht im Umfang

Aufruf von nav9v, Gemini-Adapter, MCP-Tools, CI mit Live-API-Key oder eine
nachträgliche Lockerung der ADR-0005-Schwellenwerte.

## Akzeptanzkriterien

- [ ] Schema und Testdaten validieren lokal ohne Netzwerk.
- [ ] Der Katalog enthält mindestens 40 gültige Fälle und jede geforderte
  Kategorie ist vertreten.
- [ ] Falsche, fehlende oder veraltete Pflichtfelder führen zu verständlichen
  Validierungsfehlern.
- [ ] Ein kontrollierter Beispielbericht enthält alle Metriken und zeigt
  Go/No-Go gegen die festgelegten Grenzen.
- [ ] Judge-Prompt, Kalibrierungsprotokoll und Aktualisierungsablauf sind
  dokumentiert.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.

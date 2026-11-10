# Beitragen

Grundlage für alle Arbeiten ist [`AGENTS.md`](AGENTS.md) zusammen mit dem
jeweiligen Ticket unter [`tickets/`](tickets/) und den dort genannten ADRs.

## Arbeitsweise

1. Ticket, genannte ADRs und betroffene Dokumentation vollständig lesen.
2. Einen kurzen Branch nach Conventional Commits anlegen
   (z. B. `chore/...`, `feat/...`, `fix/...`).
3. Die kleinste vollständige Änderung umsetzen und passende Tests ergänzen.
4. `make check` lokal grün laufen lassen.
5. Pull Request gegen `main` mit Titel und Beschreibung nach Conventional Commits.

Kein Force-Push auf einen geteilten oder zur Prüfung stehenden Branch. Keine
Archive oder Binärdateien einchecken.

## Qualität

- Python-Abhängigkeiten ausschließlich mit `uv` verwalten und in `uv.lock`
  festschreiben. Direkte Abhängigkeiten werden exakt gepinnt.
- Formatierung und Linting mit Ruff, Typprüfung mit `ty`, Tests mit pytest.
- Unit-Tests laufen ohne Netzwerk und ohne echten Gemini-Key. Fakes an den
  Systemgrenzen, keine Mocks für interne Aufrufzahlen.
- Mindestabdeckung 80 % für `src/gemini_search_mcp/`.

## Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Die Hooks prüfen Formatierung, Linting und Typen.

## Konfiguration und Geheimnisse

- Konfiguration kommt aus Umgebungsvariablen. `.env.example` enthält nur
  Platzhalter.
- Nie API-Keys, Bearer-Tokens, Authorization-Header oder Geheimnisse loggen,
  committen oder in Fixtures aufnehmen.

## Sprache

Dokumentation, ADRs, Tickets und README sind Deutsch. Code, Bezeichner,
Kommentare, Docstrings und Commit-Betreffzeilen sind Englisch.

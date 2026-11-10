# Gemini Search MCP

Gemini Search MCP ist ein persönlicher, öffentlich erreichbarer, aber durch ein
statisches Bearer-Token geschützter MCP-Server. Er bietet die zwei Tools
`search` und `analyze_url` auf Basis der Gemini Developer API. Maßstab ist eine
für aufrufende LLMs korrekte, belegbare und ehrliche Antwort.

Dieses Repository befindet sich im **Gerüststand (Ticket T01)**. Es enthält
Projektstruktur, Qualitätswerkzeuge und CI, aber noch keine Tool-, Provider- oder
Server-Implementierung.

## Status

- Werkzeuge: `uv`, Ruff, `ty`, pytest mit Coverage, pre-commit, GitHub Actions.
- `src/gemini_search_mcp/` enthält ausschließlich dokumentierte Platzhalter.
- Offene Arbeiten und bewusste Schulden stehen in [`docs/techdebt.md`](docs/techdebt.md).

## Voraussetzungen

- Linux, macOS oder WSL
- [uv](https://docs.astral.sh/uv/) (empfohlen: aktuelle Version)
- Python 3.14 – wird von `make install` über `uv` installiert, eine globale
  Installation ist nicht nötig

## Installation

```bash
git clone https://github.com/svenkroll/mcp-gemini-search.git
cd mcp-gemini-search
make install
```

`make install` installiert Python 3.14 und synchronisiert alle Abhängigkeiten
aus dem eingecheckten `uv.lock`.

## Lokale Prüfungen

| Ziel | Zweck |
| --- | --- |
| `make format` | Ruff-Formatierung und automatische Lint-Fixes anwenden |
| `make lint` | Ruff-Format- und Lint-Prüfung ohne Änderungen |
| `make typecheck` | Typprüfung mit `ty` |
| `make test` | pytest inklusive Coverage-Schwelle |
| `make check` | `lint`, `typecheck`, `test` in dieser Reihenfolge |
| `make pre-commit` | Führt alle pre-commit-Hooks über alle Dateien aus |

Die Abdeckungsschwelle liegt bei 80 % für `src/gemini_search_mcp/`. Ein Lauf
unter der Schwelle lässt `make test` fehlschlagen.

## Struktur

```text
src/gemini_search_mcp/  Paket (in T01 nur Platzhalter)
tests/unit/             Unit-Tests ohne Netzwerk
tests/integration/      Integrationstests
tests/fixtures/         kontrollierte Fixtures
eval/                   Ground-Truth-Katalog und Judge-Material
docs/                   ADRs, Techdebt, weitere Dokumentation
.github/workflows/      CI
```

## Dokumentation

- Arbeitsregeln: [`AGENTS.md`](AGENTS.md)
- Architekturentscheidungen: [`docs/adr/`](docs/adr/)
- Entscheidungs- und Verifikationskatalog: [`docs/offene-fragen.md`](docs/offene-fragen.md)
- Tickets: [`tickets/`](tickets/)
- Änderungen: [`CHANGELOG.md`](CHANGELOG.md)
- Mitwirken: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Ideengeber

Der Funktionsumfang orientiert sich am Referenzprojekt nav9v. Diese Neuauflage
ist eine eigenständige Entwicklung unter MIT-Lizenz und kein Fork.

## Lizenz

MIT, siehe [`LICENSE`](LICENSE).

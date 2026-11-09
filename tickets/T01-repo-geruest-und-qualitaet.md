# T01 Repo-Gerüst und Qualitätswerkzeuge

| | |
| --- | --- |
| Abhängig von | nichts |
| Blockiert | T02 bis T08 |
| Bereich | tooling, ci, documentation |

## Ziel

Ein reproduzierbares Python-Projektgerüst bereitstellen, in dem alle späteren
Tickets arbeiten können. Fachliche Tool- und Provider-Logik gehört nicht dazu.

## Kontext

Lesen: `AGENTS.md`, ADR 0001, 0002, 0005 und 0007. `AGENTS.md` ist bereits
die zentrale Agentenanweisung und darf nur bei klar begründeter Verbesserung
geändert werden. Es wird keine `CLAUDE.md` angelegt.

## Vorgaben

- Python 3.14, `uv`, exakt gepinnte Abhängigkeiten und eingechecktes `uv.lock`.
- Struktur gemäß PRD: `src/gemini_search_mcp/`, `tests/unit/`,
  `tests/integration/`, `tests/fixtures/`, `eval/`, `docs/`, `.github/`.
- Ruff für Formatierung und Linting, `ty` für Typprüfung, pytest und
  pytest-cov mit 80 % Mindestabdeckung für `src/gemini_search_mcp/`.
- Make-Ziele mindestens `install`, `format`, `lint`, `typecheck`, `test` und
  `check`; `check` läuft Linting, Typprüfung und Tests in dieser Reihenfolge.
- Pre-commit führt mindestens Formatierung, Linting und Typprüfung aus.
- GitHub Actions nutzt nur erlaubte `actions/*`-Actions oder feste
  `run`-Installationen; alle Actions werden auf Commit-SHAs gepinnt.
- README, CONTRIBUTING, CHANGELOG, `.env.example`, `.gitignore` und
  `docs/techdebt.md` anlegen. Das Geheimnis-Beispiel bleibt leer.

## Nicht im Umfang

Gemini-Aufrufe, Tools, MCP-Server, HTTP-Transport, Container, Live-Evals und
jede funktionale Produktimplementierung.

## Akzeptanzkriterien

- [ ] Ein frischer Klon erfüllt `make install` und `make check` ohne Fehler.
- [ ] `make test` schlägt unter 80 % Abdeckung fehl.
- [ ] `src/gemini_search_mcp/` enthält nur dokumentierte Platzhalter ohne
  Tool- oder Provider-Verhalten.
- [ ] `AGENTS.md` bleibt zentrale Regeldatei; es gibt keine `CLAUDE.md`.
- [ ] CI führt Linting, Typprüfung und Tests aus; Workflow-Syntax ist geprüft.
- [ ] README erklärt Voraussetzungen, Installation und die lokalen Prüfungen.
- [ ] `make check` ist grün und ein unabhängiger Review findet keinen offenen
  Vertrags- oder Sicherheitsbefund.

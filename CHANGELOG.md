# Änderungsprotokoll

Orientiert an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/) und
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt

- T01: Reproduzierbares Python-3.14-Projektgerüst mit `uv` und eingechecktem
  `uv.lock`.
- T01: Ruff für Formatierung und Linting, `ty` für Typprüfung, pytest mit
  pytest-cov und 80 % Mindestabdeckung für `src/gemini_search_mcp/`.
- T01: Make-Ziele `install`, `format`, `lint`, `typecheck`, `test`, `check`.
- T01: pre-commit für Formatierung, Linting und Typprüfung.
- T01: GitHub-Actions-CI für Linting, Typprüfung und Tests mit auf Commit-SHAs
  gepinnten Actions.
- T01: README, CONTRIBUTING, CHANGELOG, `.env.example`, `.gitignore` und
  `docs/techdebt.md`.

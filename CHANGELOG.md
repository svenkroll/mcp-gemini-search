# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Tickets moved from `tickets/` to GitHub issues (#2 to #14), with an issue
  template and evidence types per acceptance criterion.
- ADRs revised and translated to English (new file names), ADR 0010 for
  configuration added; `docs/offene-fragen.md` removed, its verified facts moved
  into ADR 0002 and ADR 0006.
- `AGENTS.md` translated to English and extended with the project contract for
  the agent orchestrator.
- `.env.example` aligned with the variables from ADR 0010.

### Added

- #2: `config` loads every variable from ADR 0010 through one pydantic-settings
  model, with defaults and limit checks; `load_settings()` raises `ConfigError`
  naming only the variable and the rule, and `load_settings_or_exit()` exits
  with code 2. Secrets are typed `SecretStr` and stay out of `repr` and `str`.
- #2: `provider` defines the `SearchProvider` protocol, the data objects
  `Usage`, `Citation`, `SearchResult`, `Retrieval` and `UrlAnalysisResult`, and
  `ProviderError` (ADR 0009), so adapter, tools and server build against fixed
  interfaces.
- #2: `fakes.FakeProvider` serves preset results or errors per call for
  network-free unit tests.
- #2: `tests/unit/test_import_boundary.py` enforces the ADR 0009 module table via
  the AST and grows with modules as later issues add them.

- `make test-fast` runs the full suite without the coverage threshold.
- `docs/roadmap.md` for topics deliberately outside release 1.

- #1: Reproducible Python 3.14 project scaffolding with `uv` and committed `uv.lock`.
- #1: Ruff for formatting and linting, `ty` for type checking, pytest with
  pytest-cov and 80% minimum coverage for `src/gemini_search_mcp/`.
- #1: Make targets `install`, `format`, `lint`, `typecheck`, `test`, `check`.
- #1: pre-commit for formatting, linting, and type checking.
- #1: GitHub Actions CI for linting, type checking, and tests with actions pinned
  to commit SHAs.
- #1: README, CONTRIBUTING, CHANGELOG, `.env.example`, `.gitignore`, and
  `docs/techdebt.md`.

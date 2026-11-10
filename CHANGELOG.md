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

- #2: `config` module with the single pydantic-settings model from ADR 0010,
  `ConfigError` and `load_settings_or_exit()` exiting with code 2.
- #2: `provider` module with the `SearchProvider` protocol, data objects and
  `ProviderError` from ADR 0009, plus `FakeProvider` for unit tests.
- `pydantic` and `pydantic-settings` as direct dependencies.
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

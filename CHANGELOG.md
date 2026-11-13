# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `analyze_url` becomes optional: `search` is the core tool, ADR 0004 defines
  the role and the facts the tool description must state, without cost claims
  or a default recommendation.
- ADR 0006 records Gemini pricing as of 2026-11-13, including the price change
  on 2027-01-01, per-query billing of Google Search and URL Context billed as
  input tokens.
- Configuration errors report "must be a boolean" for every boolean variable.
- Tickets moved from `tickets/` to GitHub issues (#2 to #14), with an issue
  template and evidence types per acceptance criterion.
- ADRs revised and translated to English (new file names), ADR 0010 for
  configuration added; `docs/offene-fragen.md` removed, its verified facts moved
  into ADR 0002 and ADR 0006.
- `AGENTS.md` translated to English and extended with the project contract for
  the agent orchestrator.
- `.env.example` aligned with the variables from ADR 0010.

### Added

- #5: Framework-free `urlpolicy` module implementing the ADR 0008 input check
  without network access and the grounding redirect resolution against the
  redirect allowlist, with `httpx` pinned exactly.
- `ANALYZE_URL_ENABLED` (default `false`) controls whether `analyze_url` is
  registered (ADR 0010).
- README sections on costs and on example `AGENTS.md` rules for `analyze_url`.
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
- #2: Environment-variable settings model per ADR 0010 with `ConfigError` and
  exit code 2 startup behavior.
- #2: Provider boundary, data objects and `FakeProvider` per ADR 0009.
- #2: Dependencies `pydantic` and `pydantic-settings`, pinned exactly.
- #3: Ground-truth catalog format in `eval/cases/` with validator
  `eval/catalog.py`, example cases per category and `make eval-validate`
  (`STRICT=1` adds `--strict`).
- #4: Asynchronous Gemini adapter in `gemini_client.py` implementing the
  provider interface from ADR 0009 for Search Grounding and URL Context, with
  the operating limits from ADR 0006 and fully testable offline. The adapter
  pins the Gemini API version `v1` explicitly (ADR 0006).
  HTTP errors of the real SDK client (`APIStatusError`, timeouts, connection
  errors) are now mapped and retried as specified in ADR 0006 and ADR 0007.
  `Retry-After` HTTP-dates are evaluated against an injectable wall clock, so
  the branch is covered by offline tests.
  A failed automatic-continuation hop is classified by its cause with the same
  mapping as a direct error (`_classify`); a retryable cause is not retried.

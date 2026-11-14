# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- #31: The loggers of the HTTP client libraries and the Google GenAI SDK are
  capped at `WARNING` independent of `LOG_LEVEL` (`httpx`, `httpx2`, `httpcore`,
  `httpcore2`, `google_genai`, `google.genai`), so request URLs (resolved
  grounding redirects, Gemini requests) no longer appear in the log. The
  `tool_call` line of a call that ends with `url_unreachable` or `url_unsafe`
  after a Gemini response carries that response's token figures. ADR 0007
  documents both.
- #20: The Gemini adapter validates every citation against the UTF-8 bytes of
  the answer and drops citations with a missing or empty URL, a missing index,
  an empty or out-of-range segment or an index inside a multi-byte character;
  drops are counted per reason in a debug log record without content. ADR 0003
  records the offset base for several text blocks as undecidable (probe of
  #29); no offset correction is applied.

### Changed

- #37: The `search` description, the `analyze_url` description and the server
  instructions tell the calling agent when to use each tool and how to phrase the
  query: sources appear when the query asks for them, a confirmed fact is asked
  for with the fact suffix, and `analyze_url` is for one specific piece of
  information from a URL the agent already has, answering explicitly when the
  content does not. Schemas and server behavior are unchanged. ADR 0003 and ADR
  0004 document the texts.
- #36: The evaluation measures `search` the way it is meant to be used. The
  catalog gains the outcome `answer_with_sources` (only for `search`) and 30
  variant cases: a `-sources` variant for each of the 26 plain `search`
  questions and a `-fact` variant for each of the 4 `honest_unknown`
  questions, with the fixed suffixes `SOURCES_SUFFIX` and `FACT_SUFFIX` of
  `eval/catalog.py`. `--strict` checks the pairing of base cases and variants.
  Scoring depends on tool and outcome: a plain `search` `answer` case is
  scored for correctness only, groundedness and source quality apply to
  `search` `answer_with_sources` and `analyze_url` `answer` cases. Thresholds
  are unchanged; the server, its tool schemas and descriptions are untouched.
  The `-sources` variants were verified against the live API on 2026-11-14
  (`eval/runs/2026-11-14-sources-verification/`); `search-techdocs-001` asks a
  different question since then, because the original one did not return the
  official documentation reliably. ADR 0005 documents the variants, the applicability table and the honesty
  criterion.
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

- #29: Probe script `eval/probe_citation_offsets.py` that measures against the
  live Gemini API whether `url_citation` indices are relative to the whole answer
  or to their own text block (input for #20). It writes numbers, prompt ids and
  classifications only to `eval/runs/<date>-offset-probe/probe.jsonl` and needs
  `LIVE=1` and a `GEMINI_API_KEY`. No new dependencies.
- #10: Eval script `eval/run_eval.py`: `run` sends every catalog case to the
  server over MCP (stdio), applies the automatic checks (error code, at least one
  allowed source, no grounding redirect URL) and writes `results.jsonl`, `run.json`,
  `server.log` and `review.md` under `eval/runs/<date>-<name>/`; `score`
  reads the manual verdicts from `review.md` and writes `report.md` with the
  rates, p50/p95 latency, token totals and the go/no-go result of ADR 0005.
  `run` needs `LIVE=1` and a `GEMINI_API_KEY`; `make eval` runs it without
  setting `LIVE`. No LLM judge, no new dependencies.
- #9: Bearer token access control for `/mcp` with `MCP_TRANSPORT=http`, through
  FastMCP's `auth` mechanism and a constant-time token verifier. A missing or
  wrong token is answered with HTTP 401 and `WWW-Authenticate: Bearer`; the
  health endpoints stay open and stdio stays without authentication. README
  describes passing the token in OpenHands.
- #8: FastMCP server `gemini-search-mcp` with stdio and stateless Streamable
  HTTP (`/mcp`), `search` always and `analyze_url` only with
  `ANALYZE_URL_ENABLED=true`, tool annotations and titles, results and errors
  per ADR 0003, 0004 and 0007, health endpoints `/health/live` and
  `/health/ready`, `Origin` validation with HTTP 403, and one JSON log line per
  tool call. Adds `fastmcp`, `starlette` and `uvicorn`, pinned exactly.
- #5: Framework-free `urlpolicy` module implementing the ADR 0008 input check
  without network access and the grounding redirect resolution against the
  redirect allowlist, with `httpx` pinned exactly.
- #6: Framework-free `search` tool logic under `tools/` with input and output
  models, JSON schemas, source resolution, merging and ordering per ADR 0003,
  and the shared tool error type with the fixed messages of ADR 0007.
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

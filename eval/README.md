# Evaluation Catalog

This directory holds the ground-truth catalog for evaluating the Gemini
Search MCP server (ADR 0005). Cases live in `eval/cases/`, the format and
validator in [`eval/catalog.py`](catalog.py), the evaluation script is
[`eval/run_eval.py`](run_eval.py). This document covers the case format, how
to maintain the catalog and how to run and score an evaluation.

## Case Format

Each case is one YAML file in `eval/cases/`. The file name equals the case
`id` plus `.yaml` (for example `search-stable-001.yaml`); other extensions,
including `.yml`, are rejected. Required fields per ADR 0005:

| Field | Content |
| --- | --- |
| `id` | Unique, e.g. `search-stable-001`; must equal the file name stem |
| `tool` | `search` or `analyze_url` |
| `category` | One of the categories below |
| `input` | `query` for `search`; `url` and `question` for `analyze_url` — exactly these keys, nothing else |
| `expected` | Core statement in one sentence; for unknowns and errors the expected behavior |
| `allowed_sources` | Non-empty list of allowed domains; for `analyze_url` the host of the analyzed test URL |
| `ground_truth_date` | Reference date of the core statement, ISO date (`YYYY-MM-DD`) |
| `expected_outcome` | `answer`, `honest_unknown` or `error:<code>` with a code from ADR 0007: `invalid_input`, `url_not_allowed`, `url_unreachable`, `url_unsafe`, `upstream_unavailable`, `upstream_error`, `internal_error` |

Optional field: `draft: true` marks an example case. Drafts are valid without
`--strict` and rejected by it, so the catalog must be draft-free before the
project owner's real evaluation run.

Example:

```yaml
id: search-stable-001
tool: search
category: stable_fact
input:
  query: "In which year was RFC 1035 published?"
expected: "RFC 1035 was published in November 1987."
allowed_sources:
  - rfc-editor.org
  - ietf.org
ground_truth_date: 2026-11-10
expected_outcome: answer
draft: true
```

## `analyze_url` Cases

`analyze_url` is not registered by default (ADR 0004, ADR 0010). Evaluation runs
that include the `url_html`, `url_pdf` and `url_failure` categories must set
`ANALYZE_URL_ENABLED=true`.

## Categories and Minimum Distribution

| Category | Content | Minimum |
| --- | --- | --- |
| `stable_fact` | Facts that do not change over time | 6 |
| `current_fact` | Time-dependent facts with a fresh reference date | 6 |
| `tech_docs` | Questions answerable from official technical documentation | 6 |
| `german` | German-language search queries | 4 |
| `english` | English-language search queries | 4 |
| `honest_unknown` | Questions whose answer is not publicly verifiable; expected is an honest unknown, never an invented answer | 4 |
| `url_html` | `analyze_url` on a stable public HTML document | 4 |
| `url_pdf` | `analyze_url` on a stable public PDF document | 4 |
| `url_failure` | `analyze_url` on URLs that cannot be retrieved | 3 |

The minimum distribution sums to at least 41 cases; it is only enforced in
strict mode.

## Adding a URL case

Nothing is self-hosted (ADR 0005, "Test resources"). Whether Gemini URL
Context can retrieve a public URL cannot be predicted: on 2026-11-13 every
document under `www.rfc-editor.org/rfc/` failed reproducibly. A URL case
therefore enters the catalog only after it meets every rule and has been
verified live.

Rules for `url_html` and `url_pdf`:

- Immutable or versioned content: a revision or version is part of the URL
  (for example `https://arxiv.org/pdf/<id>v<n>`, `https://toml.io/en/v1.0.0`),
  or the publisher guarantees the document never changes. News, "latest"
  documentation and wiki pages without a revision are not allowed.
- HTTPS, passes the ADR 0008 input check, no login, paywall, cookie wall or
  JavaScript-only content.
- No redirect: the URL Gemini reports as retrieved equals the requested URL.
- A PDF case URL serves the PDF itself, not an HTML landing page.
- At least 3 different hosts across the 8 html/pdf cases, at most 2 cases per
  host.
- Question and `expected` are a specific statement (a value, a definition, a
  named section) answerable only from the document. Verify `expected` against
  the document text itself, never against the model answer alone. URL Context
  truncates long documents, so ask about content near the beginning of a long
  page.
- `allowed_sources` is the registrable domain of the URL's host.

Rules for `url_failure`: three different failure reasons, each with
`error:url_unreachable`:

1. a host under the reserved `.invalid` domain (RFC 2606);
2. a non-existent HTML path on a host that has a verified passing case in the
   catalog;
3. a non-existent PDF path on a host that has a verified passing PDF case.

A failure case on a host that never succeeds is not allowed.

Verification (live Gemini calls, run manually by the project owner or with
their explicit authorization): check every URL twice with the exact question
of the case through the real `analyze_url` path. The checker script is the
project owner's and is not part of this repository:

```bash
uv run python .issue-drafts/check_url_context.py --key-file <key file> \
    --repeat 2 --question "<case question>" "<url>"
```

- An html/pdf case is accepted only if both attempts have `outcome: "ok"`,
  `reported_url` equals the requested URL and both answers state `expected`.
- A failure case is accepted only if both attempts have
  `outcome: "url_unreachable"`.
- One success and one failure means flaky: reject the URL, do not retry it
  into the catalog.
- Commit the checker output of accepted and rejected candidates as
  `eval/runs/<date>-url-verification/check.jsonl` with a `README.md` that
  lists every final case and every rejected candidate with its reason. Set
  `ground_truth_date` to the verification date.

The current record is
[`eval/runs/2026-11-13-url-verification/`](runs/2026-11-13-url-verification/README.md).

Prompt injection is not part of the live catalog; it is covered by unit
tests (ADR 0008).

## Maintaining Time-Dependent Cases

- A `current_fact` case is stale when its `ground_truth_date` is older than
  90 days. The validator reports staleness as a warning, never as an error:
  exactly 90 days is still fresh, 91 days is stale.
- When refreshing a `current_fact`, update `expected` and
  `ground_truth_date` together: the reference date must be the date the core
  statement was last verified.
- Stable facts and RFC content do not expire; keep their original reference
  date.

## Validating the Catalog

```bash
uv run python eval/catalog.py          # warnings allowed
uv run python eval/catalog.py --strict # no warnings-only tolerance, no drafts, minimum distribution
make eval-validate                     # same as the first command
make eval-validate STRICT=1            # same as --strict
```

Exit code is 0 when there are no errors; warnings alone keep it 0. Every
error and warning names file, field and rule, for example:

```text
error: analyze-url-html-001.yaml: expected_outcome: must be answer, honest_unknown or error:<code> with a code from ADR 0007
warning: search-current-001.yaml: ground_truth_date: older than 90 days for a current_fact; refresh the case
```

An empty `eval/cases/` directory is valid without `--strict` and fails with
it because of the minimum distribution.

## Running an Evaluation

`eval/run_eval.py` sends every catalog case to the server over MCP (stdio, the
console script `gemini-search-mcp`), applies the checks that need no LLM and
writes a review file in which you score the remaining metrics by hand. There is
no LLM judge. A second command computes the rates and the go/no-go result from
the filled-in file. Only the project owner starts live runs.

### Cost notice

A run makes paid Gemini calls (ADR 0006). The Gemini Developer API needs a
paid key with active billing; every `search` call can execute several billed
Google Search queries on top of the token cost, and `analyze_url` input cost
grows with page size. Prices and quotas are in ADR 0006. Start with a smoke run
of two or three cases before the full run. `run` refuses to start unless
`LIVE=1` and a non-empty `GEMINI_API_KEY` are set; it checks this before the
server is started, so nothing is called otherwise. `make eval` does not set
`LIVE`.

### 1. Smoke run

```bash
LIVE=1 GEMINI_API_KEY=... uv run python eval/run_eval.py run --name smoke \
  --case <search-case-id> --case <analyze-url-case-id>
```

- `--case <id>` is repeatable and restricts the run to the given cases; an
  unknown id aborts before the server starts. Without `--case` all cases run.
- `--name <name>` names the run directory (default `run`). Allowed characters:
  letters, digits, `.`, `_` and `-`, starting with a letter or digit.
- The catalog is validated with `--strict` first; drafts or a missing minimum
  distribution abort the run before the server starts.
- The server runs with your environment plus `MCP_TRANSPORT=stdio` and
  `ANALYZE_URL_ENABLED=true`, so include at least one `analyze_url` case.
- `make eval ARGS="--name smoke --case <id>"` does the same.

### 2. Full run

```bash
LIVE=1 GEMINI_API_KEY=... uv run python eval/run_eval.py run
```

Without `--case` every catalog case runs. The full run and the go/no-go
decision are tracked in #14.

A single call that times out (180 seconds) or fails outside the error contract
is recorded as failed and the run continues. If the server cannot be started or
exits during the run, the run aborts with a message; the results of the cases
that finished stay in `results.jsonl`.

### 3. Manual scoring

Open `review.md` of the run directory. It starts with the run data (commit,
date, catalog hash, model reported by the server, settings without secrets) and
an overview table with one row per case. Each case has a section
`## Case <id>` with the question or URL, `expected`, `allowed_sources`, the
answer, the returned sources and the automatic results.

Which metrics you score depends on `expected_outcome`; everything else is
`n/a` and does not count in the denominator:

| `expected_outcome` | correctness | groundedness | source quality | honesty |
| --- | --- | --- | --- | --- |
| `answer` | manual | manual | automatic | `n/a` |
| `honest_unknown` | `n/a` | `n/a` | `n/a` | manual |
| `error:<code>` | automatic | `n/a` | `n/a` | `n/a` |

Automatic checks: an `error:<code>` case passes correctness when the returned
error code equals the expected one; source quality (only for `answer` cases)
passes when at least one returned source is within `allowed_sources` (a
subdomain such as `www.rfc-editor.org` counts for `rfc-editor.org`) and no
returned source is a Google grounding redirect URL. Further sources outside
`allowed_sources` do not fail it; an `answer` case without any returned source
fails it. An `answer` case that returns a tool error fails correctness,
groundedness and source quality.

For every manual metric the section has one verdict line, initially empty:

```text
- verdict correctness:
- verdict groundedness:
```

Write `pass` or `fail` after the colon, optionally followed by a short note:

```text
- verdict correctness: pass
- verdict groundedness: fail the cited page does not state the date
```

Only exactly `pass` and `fail` (lower case) are accepted; `Pass`, `pas`,
`passed` or `pass,` are invalid. Judge correctness against `expected`, and
groundedness by whether the returned evidence supports the core statement. Do
not edit anything else in the file: headings of the form `## Case <id>` and the
verdict lines are what `score` reads. Text inside code fences comes from the
case, the web or the model and is ignored by `score`.

### 4. Score

```bash
uv run python eval/run_eval.py score eval/runs/<date>-<name>
```

`score` reads `results.jsonl`, `run.json` and `review.md`, computes the rate per
metric, p50/p95 latency and token totals, and writes `report.md` into the run
directory. Go/no-go uses the thresholds of ADR 0005: honesty 100 %, source
quality at least 90 %, correctness and groundedness at least 85 %; a rate
exactly at a threshold meets it, and a metric whose cases are all `n/a` is
shown as `n/a` and counts as not met. If any verdict is empty, misspelled,
missing or duplicated, `score` fails, names every affected case and metric and
writes no report; fix `review.md` and run it again. The exit code is 0 for
both GO and NO-GO.

### Where runs are stored

Every run gets its own directory `eval/runs/<date>-<name>/` (for example
`eval/runs/2026-11-13-smoke/`). An existing directory is never overwritten;
choose another `--name` to run again on the same day.

| File | Content |
| --- | --- |
| `results.jsonl` | One line per case: input, raw tool result or error JSON, automatic check results, latency, tokens |
| `run.json` | Run data: commit, date, catalog hash, models, settings, case ids |
| `server.log` | The server's JSON log lines (stderr), source of tokens and model per call |
| `review.md` | Overview, run data and one section per case with the empty verdict lines you fill in |
| `report.md` | Written by `score`: rates, go/no-go, latency and tokens |

No file contains `GEMINI_API_KEY`, `MCP_BEARER_TOKEN` or any other secret; the
run data lists only an allowlist of non-secret settings. Web content in the
answers is untrusted, so check a run before sharing or committing it.

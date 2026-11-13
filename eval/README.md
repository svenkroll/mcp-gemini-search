# Evaluation Catalog

This directory holds the ground-truth catalog for evaluating the Gemini
Search MCP server (ADR 0005). Cases live in `eval/cases/`, the format and
validator in [`eval/catalog.py`](catalog.py). The evaluation script and judge
material arrive with #10; this document covers the case format and how to
maintain the catalog.

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

## Choosing Stable Public URLs

Nothing is self-hosted (ADR 0005):

- `url_html` and `url_pdf` use immutable public documents, preferably RFCs
  at the RFC Editor, which exist as HTML
  (`https://www.rfc-editor.org/rfc/rfc<number>.html`) and, for RFCs
  published in the XML v3 format (roughly RFC 8650 onward), as PDF
  (`https://www.rfc-editor.org/rfc/rfc<number>.pdf`). Older RFCs have no
  PDF at the RFC Editor; check that a URL returns 200 before using it.
- `url_failure` uses non-existent paths on such stable hosts and the
  reserved `.invalid` domain (RFC 2606), which can never be retrieved.
  Expected outcome is `error:url_unreachable`.
- Prompt injection is not part of the live catalog; it is covered by unit
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

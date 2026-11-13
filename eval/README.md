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

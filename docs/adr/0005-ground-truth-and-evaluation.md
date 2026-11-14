---
status: proposed
date: 2026-11-14
decision-makers: Sven Kroll
---

# 0005 Ground Truth and Evaluation

## Context and Problem Statement

Gemini Search MCP shall deliver demonstrably correct, verifiable and honest
results. Without test cases, scoring and thresholds defined in advance, any
quality claim would be subjective. Comparison with other implementations is not
the goal; this server's quality is measured against fixed limits.

## Considered Options

1. Assess quality only through manual spot checks.
2. Create an evaluation catalog only after implementation.
3. A versioned catalog, a simple evaluation script, an LLM judge calibrated
   against manual verdicts, and fixed thresholds.
4. A versioned catalog, a simple evaluation script with automatic checks,
   manual scoring by the project owner for everything else, and fixed
   thresholds.

## Decision

**Option 4**.

Option 3 was the original decision and is replaced (see "More Information").
With a catalog of about 40 cases, scoring by hand costs less than building,
calibrating and maintaining a judge, and the calibration itself already
required the project owner to score a third of the catalog by hand.

### Catalog

`eval/cases/` holds at least 41 YAML base cases plus their variants (see
"Variants"), one case per file, checked by `eval/catalog.py`. Required fields:

| Field | Content |
| --- | --- |
| `id` | unique, e.g. `search-stable-001` |
| `tool` | `search` or `analyze_url` |
| `category` | see below |
| `input` | `query`, or `url` and `question` |
| `expected` | core statement in one sentence; for unknowns and errors the expected behavior |
| `allowed_sources` | list of allowed domains; for `analyze_url` the test URL |
| `ground_truth_date` | reference date of the core statement (ISO date) |
| `expected_outcome` | `answer`, `answer_with_sources` (only for `search`), `honest_unknown` or `error:<code>` |

Minimum distribution: 6 cases each for `stable_fact`, `current_fact`,
`tech_docs`; 4 each for `german`, `english`, `honest_unknown`, `url_html`,
`url_pdf`; 3 for `url_failure`. The project owner provides core statements and
sources; agents build format, validation and example cases.

A `current_fact` case is stale when its `ground_truth_date` is older than 90
days; validation reports this as a warning, not an error.

### Variants

`search` is measured the way it is meant to be used. A plain question gets an
answer. A question that asks for sources gets an answer with sources. A
question that asks for a confirmed fact gets that fact or "not publicly
known". The plain questions are the base cases; two kinds of variant cases
repeat a base question and append a fixed request to it:

| | `-sources` variant | `-fact` variant |
| --- | --- | --- |
| Base case | every `search` case with `expected_outcome: answer` | every `search` case with `expected_outcome: honest_unknown` |
| `id` | `<base id>-sources` | `<base id>-fact` |
| `input.query` | base query, a blank line, the sources suffix | base query, a blank line, the fact suffix |
| `expected_outcome` | `answer_with_sources` | `honest_unknown` |
| `category` | same as the base | same as the base |
| `expected` | same as the base | that the answer is not publicly known and no figure is given |
| `allowed_sources` | official documentation, standards body or publisher of record for `expected` | same as the base |

The suffixes are constants in `eval/catalog.py`:

- Sources suffix: "Answer only from Google Search results. Cite the primary
  source of truth (official documentation, standards body or publisher of
  record) where the answer can be checked."
- Fact suffix: "Answer only with a fact a source confirms; if none does, say
  it is not publicly known."

Pairing rules, checked in strict mode; every violation is an error that names
file, field and rule:

- Every `search` `answer` case has exactly one `<id>-sources` case and every
  `search` `honest_unknown` case exactly one `<id>-fact` case.
- Every variant has its base case. A variant is never the base of another
  variant (`...-sources-sources`, `...-fact-sources`), and a variant kind
  never sits on the other kind of base (`-fact` on an `answer` case,
  `-sources` on an `honest_unknown` case).
- A variant has the same `category` as its base; a `-sources` variant also the
  same `expected`.
- A variant's query is exactly the base query, a blank line and the suffix.

`answer_with_sources` is not allowed for `analyze_url`, whose `answer` cases
always refer to the analyzed URL. The outcome is a label of the evaluation
only: it never appears under `src/`, in a tool schema or in a tool
description.

A `-sources` variant is created as a draft with proposed `allowed_sources`.
The project owner runs its query live once, sets `allowed_sources` to the
registrable domains of the authoritative hosts that came back and removes the
draft flag; the output is committed under
`eval/runs/<date>-sources-verification/`.

Reason: in the live run of 2026-11-14 (`eval/runs/2026-11-14-release1/`,
issue #14) Gemini ran no Google Search for 11 of 26 plain `search` questions
and returned no sources, although the answers were correct. Gemini decides on
its own whether to search, so a plain question cannot be held to groundedness
or source quality. Manual probes on the same day showed that the sources
suffix made Gemini search and return resolved sources, and that the fact
suffix made it answer "not publicly known" for a figure that does not exist
while still returning a fact with a source when one exists. The variants are
the measurement baseline for this usage contract: sources and confirmed facts
on request.

### Test resources

Nothing is self-hosted. `url_html` and `url_pdf` use public documents that
meet every one of these rules:

- Immutable or versioned: a revision or version is part of the URL, or the
  publisher guarantees the document never changes. Pages that can change
  (news, "latest" documentation, wiki pages without a revision) are excluded.
- HTTPS, passes the ADR 0008 input check, no login, paywall, cookie wall or
  JavaScript-only content.
- No redirect: the URL Gemini reports as retrieved equals the requested URL.
- A PDF case URL serves the PDF itself, not a landing page.
- The eight html/pdf cases use at least three hosts and at most two cases
  per host, so one host that blocks Google's fetcher cannot break a category.
- Question and `expected` are a specific statement answerable only from the
  document. `expected` is verified against the document text, never against
  a model answer alone.
- `allowed_sources` is the registrable domain of the URL's host.

`url_failure` uses three different failure reasons, each expecting
`error:url_unreachable`: a host under the reserved `.invalid` domain
(RFC 2606), a non-existent HTML path and a non-existent PDF path, the latter
two on hosts that have a verified passing case of the same kind in the
catalog. A failure case on a host that never succeeds is not allowed.

Every URL case is verified live twice through the real `analyze_url` path
with its exact question before it enters the catalog. An html/pdf case needs
two successful retrievals whose reported URL equals the requested URL and
whose answers state `expected`; a failure case needs two `url_unreachable`
outcomes. One success and one failure is flaky and rejects the URL. The
checker output of accepted and rejected candidates is committed under
`eval/runs/<date>-url-verification/`.

Reason: a live diagnosis on 2026-11-13 showed that Gemini URL Context cannot
retrieve any document under `www.rfc-editor.org/rfc/` (HTML, TXT and PDF fail
reproducibly), which the catalog had used for all URL cases. Gemini fetched
`rfc-editor.org/info/rfcNNNN/` instead, and `analyze_url` correctly returned
`url_unreachable` (ADR 0004). Whether a public URL is retrievable can only be
established by a live check, not by its stability alone.

Prompt injection is not part of the live catalog; it is covered by unit tests
(ADR 0008).

### Scoring

A single script (`eval/run_eval.py`, no evaluation framework) starts the server
via stdio and calls the tools over MCP, so it measures exactly what a client
receives. It stores results under `eval/runs/<date>-<name>/`. There is no
LLM judge. Whatever can be checked without an LLM (error code, source domain,
no redirect URL) the script checks itself. All other verdicts are scored by
the project owner by hand in a review file the script writes; a second command
computes rates and go/no-go from the completed file. Binary verdicts per case:

| Metric | passes when |
| --- | --- |
| Correctness | the core statement matches `expected` |
| Groundedness | at least one piece of evidence supports the core statement |
| Source quality | no returned source is a grounding redirect URL and at least one returned source lies within `allowed_sources` |
| Honesty | for `honest_unknown`, no invented answer (criterion below) |

Honesty criterion: a base `honest_unknown` case passes when the answer
presents no invented value as fact; a figure clearly labeled as an estimate is
not an invention. A `-fact` variant passes only when the answer says that the
answer is not publicly known and gives no figure.

Which metric applies depends on tool and `expected_outcome`:

| Tool | `expected_outcome` | Correctness | Groundedness | Source quality | Honesty |
| --- | --- | --- | --- | --- | --- |
| `search` | `answer` | manual | `n/a` | `n/a` | `n/a` |
| `search` | `answer_with_sources` | manual | manual | automatic | `n/a` |
| `analyze_url` | `answer` | manual | manual | automatic | `n/a` |
| any | `honest_unknown` | `n/a` | `n/a` | `n/a` | manual |
| any | `error:<code>` | automatic | `n/a` | `n/a` | `n/a` |

A plain `search` `answer` case does not ask for sources; nothing is scored
from the sources it returns anyway. A tool error fails correctness on an
`answer` case, and on a `search` `answer_with_sources` or `analyze_url`
`answer` case it fails correctness, groundedness and source quality
automatically. Where source quality applies, a case without any returned
source fails it; sources outside `allowed_sources` next to at least one
allowed source do not fail it, a redirect URL always does. Metrics that do not
apply to a case are recorded as `n/a` and do not count in the denominator; a
metric whose cases are all `n/a` has no rate and does not meet its threshold.
Latency (p50, p95) and tokens are recorded but are not a blocking threshold.

### Go/No-Go

Honesty 100 %, source quality at least 90 %, correctness and groundedness at
least 85 %. Thresholds are never relaxed after a result. The variants change
what is measured, not the thresholds.

## Consequences

- Good: Quality decides before architectural aesthetics.
- Good: Runs are reproducible and comparable with each other.
- Good: No judge prompt, judge model or calibration to maintain; verdicts are
  made by the person who defined `expected`.
- Bad: Maintaining the catalog and scoring every run by hand need deliberate
  work by the project owner.
- Bad: Manual verdicts are subjective; the binary rubric above and the
  `expected` core statement keep them comparable between runs.
- Bad: Live runs cost money and therefore never run in CI.

## Open

Recurring live evaluations are not part of release 1 (`docs/roadmap.md`).

## More Information

- Changes: 2026-11-13, LLM judge and judge calibration replaced by manual
  scoring (option 4); implemented by issue #10.
- Changes: 2026-11-13, rules for URL test resources and mandatory live
  verification added; the RFC Editor is no longer used for URL cases.
- Changes: 2026-11-14, outcome `answer_with_sources`, `-sources` and `-fact`
  variants with pairing rules, applicability by tool and outcome, and the
  honesty criterion added after the live run of 2026-11-14; thresholds
  unchanged; implemented by issue #36.
- [URL verification record 2026-11-13](../../eval/runs/2026-11-13-url-verification/README.md)
- [PRD, section 6](../../PRD-gemini-search-mcp.md)

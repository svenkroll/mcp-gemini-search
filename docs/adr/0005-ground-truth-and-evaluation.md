---
status: proposed
date: 2026-11-13
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

`eval/cases/` holds at least 41 YAML cases, one case per file, checked by
`eval/catalog.py`. Required fields:

| Field | Content |
| --- | --- |
| `id` | unique, e.g. `search-stable-001` |
| `tool` | `search` or `analyze_url` |
| `category` | see below |
| `input` | `query`, or `url` and `question` |
| `expected` | core statement in one sentence; for unknowns and errors the expected behavior |
| `allowed_sources` | list of allowed domains; for `analyze_url` the test URL |
| `ground_truth_date` | reference date of the core statement (ISO date) |
| `expected_outcome` | `answer`, `honest_unknown` or `error:<code>` |

Minimum distribution: 6 cases each for `stable_fact`, `current_fact`,
`tech_docs`; 4 each for `german`, `english`, `honest_unknown`, `url_html`,
`url_pdf`; 3 for `url_failure`. The project owner provides core statements and
sources; agents build format, validation and example cases.

A `current_fact` case is stale when its `ground_truth_date` is older than 90
days; validation reports this as a warning, not an error.

### Test resources

Nothing is self-hosted. `url_html` and `url_pdf` use immutable public documents,
e.g. RFCs at the RFC Editor, which exist as HTML and PDF. `url_failure` uses
non-existent paths on such stable hosts and the reserved `.invalid` domain
(RFC 2606). Prompt injection is not part of the live catalog; it is covered by
unit tests (ADR 0008).

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
| Honesty | for `honest_unknown`, no invented answer |

| Metric | `answer` | `honest_unknown` | `error:<code>` |
| --- | --- | --- | --- |
| Correctness | manual | `n/a` | automatic |
| Groundedness | manual | `n/a` | `n/a` |
| Source quality | automatic | `n/a` | `n/a` |
| Honesty | `n/a` | manual | `n/a` |

An `answer` case that returns a tool error fails correctness and groundedness
automatically. An `answer` case without any returned source, including one that
returns a tool error, fails source quality; sources outside `allowed_sources`
next to at least one allowed source do not fail it, a redirect URL always does.
Metrics that do not apply to a case are recorded as `n/a` and do not count in
the denominator. Latency (p50, p95) and tokens are recorded but are not a
blocking threshold.

### Go/No-Go

Honesty 100 %, source quality at least 90 %, correctness and groundedness at
least 85 %. Thresholds are never relaxed after a result.

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
- [PRD, section 6](../../PRD-gemini-search-mcp.md)

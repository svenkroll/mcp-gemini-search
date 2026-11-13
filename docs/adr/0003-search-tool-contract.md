---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0003 `search` Tool Contract

## Context and Problem Statement

A Gemini summary without reliable sources is of limited use to a calling LLM.
The contract must bind evidence directly to statements without inventing
missing grounding metadata or discarding useful partial results.

## Considered Options

1. Return only a Markdown answer and a source list.
2. Return only raw search hits.
3. Return the answer, normalized sources and evidence as structured data.

## Decision

**Option 3**.

### Input

| Field | Type | Rule |
| --- | --- | --- |
| `query` | string | trimmed; then 1 to 4,000 Unicode characters |
| `max_sources` | integer | optional, 1 to 10, default 5 |

### Output (`structuredContent`)

```json
{
  "answer": "string",
  "sources": [
    {
      "title": "string",
      "url": "string",
      "evidence": [
        {"text": "string", "start_index": 0, "end_index": 0}
      ]
    }
  ],
  "search_queries": ["string"]
}
```

- `answer`: Gemini's answer text, unchanged.
- `sources`: at most one source per target URL, ordered by first citation in
  `answer`, truncated to `max_sources`. `title` is the title Gemini returned,
  otherwise an empty string.
- `evidence`: all citations of this source. `start_index` and `end_index` are
  taken unchanged from Gemini; the server never computes positions. `text` is
  the slice of `answer` between these indices. The index unit is UTF-8 bytes,
  not characters: a live check on 2026-11-13 (Gemini API `v1`, German answer
  with umlauts) returned a largest `end_index` equal to the byte length of the
  answer and larger than its character count. The slice must therefore be
  taken from `answer.encode("utf-8")` and decoded again.
  The adapter validates every citation against the UTF-8 bytes of `answer`
  and drops it when the URL is missing or empty, an index is missing,
  `0 <= start_index < end_index <= len(answer_bytes)` does not hold, or the
  byte slice is not strict UTF-8 (an index inside a multi-byte character).
  Dropped citations are counted per reason in one debug log record without
  content; a response whose citations are all dropped has empty `sources` and
  still succeeds.
- Offset base for answers with several text blocks: **undecidable** (decision
  of 2026-11-13, method: probe script `eval/probe_citation_offsets.py` from
  #29, `LIVE=1 uv run python eval/probe_citation_offsets.py --repeat 3` against
  `gemini-3.8-flash`). All 21 interactions returned exactly one text block at
  offset 0 (undecidable: 21, global: 0, per_block: 0, inconsistent: 0). No block
  with a byte offset greater than 0 was observed, so it is unknown whether
  indices are relative to the whole answer or to their own block. The adapter
  therefore applies no offset correction (indices are taken as relative to the
  whole answer) and writes a debug log record with numbers only when a block
  with a byte offset greater than 0 carries annotations. The open question is
  tracked as TD-005.
- `search_queries`: the search queries Gemini actually executed.

If sources, evidence or search queries are missing, the respective list is
empty and the call still succeeds. The tool's text content is the same object
as JSON. Errors follow ADR 0007.

### Source URLs

Every source URL passes the input check from ADR 0008. URLs whose host is a
known grounding redirect host (`vertexaisearch.cloud.google.com`) are resolved
to their target URL by querying the redirect (fetch check and limits from ADR
0008, content is never read). All other URLs are used directly once they pass
the input check. Sources that fail a check or cannot be resolved are dropped
together with their evidence. Sources are then merged by target URL.

## Consequences

- Good: Clients can assess statements, sources and evidence separately.
- Good: Duplicate sources and redirect URLs do not degrade the output.
- Good: Without redirect URLs there are no additional network calls.
- Bad: Unresolvable sources are invisible to the client; this deliberately
  deviates from the PRD sketch.
- Bad: The adapter must normalize current citation metadata carefully.

## Open

None. The first manual evaluation run shows whether Gemini currently returns
redirect URLs; the contract covers both cases.

## More Information

- [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search)
- ADR 0006: Gemini integration, ADR 0007: errors, ADR 0008: URL policy

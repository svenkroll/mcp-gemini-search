---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0001 Scope and Goal

## Context and Problem Statement

Gemini Search MCP shall give LLM clients useful, verifiable web research and
analysis of public URLs. The reference project nav9v shows the feature set, but
passes Gemini's summary and hard-to-use sources through largely unprocessed.
Success is therefore measured by answer quality and verifiability, not by
minimal implementation effort.

## Considered Options

1. Fork nav9v and extend it step by step.
2. Write an independent server with the same core scope.
3. Build a generic search service with several backends.

## Decision

**Option 2**: an independent implementation named **Gemini Search MCP** under
the MIT license. The README credits nav9v as the source of the idea. The first
release offers only the tools `search` and `analyze_url`; prompts, resources,
user management, billing and further search providers are out of scope.

`search` returns an answer, real sources and their evidence. `analyze_url`
answers a specific question solely from a public URL that was actually
retrieved. The ground-truth catalog and the evaluation script are part of the
plan; the go/no-go decision is made against fixed thresholds (ADR 0005), not by
comparison with nav9v.

The service runs publicly on a personal URL in Kubernetes, but a static bearer
token restricts it to its owner. It is not a search service for third parties
and does not build a search index.

## Consequences

- Good: The contract can be designed for LLM usefulness and verifiable sources.
- Good: Architecture and tests are not bound by nav9v's structural decisions.
- Bad: The README has to explain origin and differences clearly.
- Bad: Quality assurance adds effort and API cost.

## Open

No product decision is open. Google's terms and model capabilities are checked
in ADR 0006 at the time of each implementation.

## More Information

- [PRD](../../PRD-gemini-search-mcp.md)

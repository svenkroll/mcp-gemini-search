---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0009 Provider Interface

## Context and Problem Statement

Gemini is the only backend provider in the first release. Serper or Tavily may
follow later without their particular fields shaping today's MCP contract or
coupling tool logic to Gemini response types.

## Considered Options

1. Call Gemini directly in the FastMCP tools.
2. Introduce a small domain provider boundary for both operations.
3. Build a full multi-provider platform now.

## Decision

**Option 2**.

### Modules

| Module | Responsibility | may import |
| --- | --- | --- |
| `config` | settings per ADR 0010 | pydantic-settings, pydantic |
| `provider` | interface and data objects below | standard library, pydantic |
| `gemini_client` | Gemini adapter, implements `provider` | `provider`, `config`, google-genai |
| `urlpolicy` | ADR 0008 | standard library, pydantic, httpx |
| `tools` | contracts from ADR 0003, 0004, errors from ADR 0007 | `provider`, `urlpolicy`, `config` |
| `server` | FastMCP wrappers, auth, health, logging | everything above, fastmcp, starlette, uvicorn |

### Interface

```python
class SearchProvider(Protocol):
    async def search(self, query: str) -> SearchResult: ...
    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult: ...
```

Data objects (immutable dataclasses or Pydantic models):

- `Usage`: `input_tokens: int | None`, `output_tokens: int | None`
- `Citation`: `url: str`, `title: str`, `start_index: int`, `end_index: int`
- `SearchResult`: `answer: str`, `citations: list[Citation]`,
  `search_queries: list[str]`, `usage: Usage`, `model: str`
- `Retrieval`: `url: str`, `status: Literal["retrieved", "unsafe", "failed"]`
- `UrlAnalysisResult`: `answer: str`, `retrievals: list[Retrieval]`,
  `usage: Usage`, `model: str`
- `ProviderError(Exception)`: `kind: Literal["unavailable", "rejected",
  "internal"]`; `unavailable` after exhausted retries, a timeout or a connection
  failure; a failed automatic-continuation hop is classified by its cause like a
  direct error, and a retryable cause is not retried because earlier hops are
  already billed

Only `server` imports FastMCP. It may also import `starlette` and `uvicorn`,
FastMCP's own HTTP stack, for health routes, middleware and serving the ASGI
app. Every package `server` imports directly is a direct, exactly pinned
dependency.

Gemini-specific SDK types, grounding steps and transport details stay inside the
adapter. Tests use a `FakeProvider` with preset results and errors. The first
release has exactly one Gemini adapter; Serper, Tavily, provider selection and
fallbacks are out of scope.

## Consequences

- Good: Unit tests use `FakeProvider` without network access.
- Good: A later provider change barely touches the tool contract and server.
- Good: The FastMCP dependency stays in the outer layer.
- Bad: A small abstraction exists before a second provider does.
- Bad: Provider-specific strengths are not exposed early.

## Open

An additional provider requires a new ADR with a quality measurement against
the ground-truth catalog before implementation.

## More Information

- ADR 0003, ADR 0004, ADR 0005, ADR 0007

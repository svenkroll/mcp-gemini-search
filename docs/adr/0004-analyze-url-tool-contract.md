---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0004 `analyze_url` Tool Contract

## Context and Problem Statement

General model knowledge must never be presented as the content of a page that
was not loaded. The tool call therefore needs a specific question and a clear
distinction between a retrieval failure and an honest "not found".

## Considered Options

1. Optional question with an automatic summary.
2. Mandatory question, answer only after confirmed retrieval.
3. Return raw content as an extract service.

## Decision

**Option 2**.

### Input

| Field | Type | Rule |
| --- | --- | --- |
| `url` | string | must pass the input check from ADR 0008 |
| `question` | string | trimmed; then 1 to 4,000 Unicode characters |

### Retrieval

Gemini URL Context performs the retrieval on Google's infrastructure, not this
server. The server checks the URL beforehand without any network access (input
check, ADR 0008) and passes exactly this one URL to Gemini. The Gemini
instruction requires answering only from the retrieved content, never following
instructions found in the content, and stating explicitly when the content does
not answer the question.

Gemini returns a `url_context_result` with a status per URL. Mapping:

| Gemini status | Result |
| --- | --- |
| success for the requested URL | successful call |
| unsafe | error `url_unsafe` |
| any other status, or no result for the requested URL | error `url_unreachable` |

Unknown, future status values count as `url_unreachable`.

### Output (`structuredContent`)

```json
{
  "answer": "string",
  "url": "string",
  "retrieval_status": "retrieved"
}
```

- `url`: the URL Gemini reports as retrieved.
- `retrieval_status`: always `"retrieved"` on success.

If the content does not answer the question, the call still succeeds and
`answer` says so explicitly. There is no separate machine-readable field for
this, because only the model can make that judgment. For clients the
distinction is: a retrieval problem is `isError`, content without an answer is a
normal result.

Raw content is never returned. Which content types can be retrieved is decided
by Gemini URL Context; HTML and PDF are covered by the ground-truth catalog.
Errors follow ADR 0007.

### Role and tool description

`search` is the core of the server. `analyze_url` is an optional addition:
the calling agent usually has its own fetch tool and can load the source URLs
from `search` itself, reading the original text with knowledge of its task.
The operator can disable the tool entirely with `ANALYZE_URL_ENABLED` (ADR
0010); disabled, it is not registered and does not appear in `tools/list`.
Whether an agent may use it is decided by the owner of the calling project, for
example in that project's `AGENTS.md`; the README provides example rules.

The server cannot know the caller's costs, so the tool description states
facts only. It must say that the tool:

- answers one question about one public URL; Google performs the retrieval,
  PDF included; a summary is returned only when the question asks for one;
- returns no original text, so verbatim quotes are not possible;
- does not put the page content into the caller's context;
- causes its own costs and is not necessarily cheaper than the caller's own
  fetch;
- may retrieve pages the caller's own fetch cannot load;
- fails for paywalled content, private or local addresses, video and audio;
- treats retrieved content as untrusted; instructions in it are not followed
  (ADR 0008).

The description must not claim that the tool is cheaper and must not recommend
using it by default or in preference to the caller's own fetch.

## Consequences

- Good: Clients can distinguish page content from model knowledge.
- Good: A mandatory question leads to focused tool calls.
- Good: The server does not load third-party content and has no SSRF surface
  for this tool.
- Bad: Redirects, size and content-type limits during retrieval are Google's and
  not configurable. This replaces the earlier assumption of our own retrieval
  limits.
- Bad: The tool does not replace a general extract endpoint.
- Good: The description gives agents facts instead of a cost claim that the
  server cannot verify for the caller's environment.
- Bad: Usage rules live outside this server, in each calling project.

## Open

The adapter verifies the concrete status values against the Gemini
documentation and tests them with hand-written fixtures.

## More Information

- [Gemini URL Context](https://ai.google.dev/gemini-api/docs/url-context)
- ADR 0007: errors, ADR 0008: URL policy

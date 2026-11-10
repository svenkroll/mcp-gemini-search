---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0006 Gemini Integration

## Context and Problem Statement

The server needs a non-blocking, robust Gemini integration for Search Grounding
and URL Context. Model, cost, data protection and terms of use must be visible
and configurable.

## Considered Options

1. Synchronous client without limits, as in nav9v.
2. Gemini Developer API with an asynchronous adapter and fixed operating limits.
3. Vertex AI as a prerequisite for the first release.

## Decision

**Option 2**. The adapter uses the Gemini Developer API with an API key from AI
Studio and exclusively `client.aio`. The default model is the stable
`gemini-3.8-flash`, configurable via settings (ADR 0010) and never a scattered
literal in code. Timeout, concurrency and retries below are the defaults of the
variables in ADR 0010.

A call has a total time budget of 60 seconds by default. A semaphore limits
Gemini calls to four in parallel. On 429 and transient 5xx errors, at most two
retries follow the first attempt, with exponential backoff, jitter and respect
for `Retry-After`. Client cancellation stops further work. Token figures come
exclusively from the API usage metadata.

Deployment, evaluation runs and the judge use an API key of a project with
active billing. Free usage is meant only for direct AI Studio experiments, not
for the operated Search Grounding service. The README explains: free services
may use content for product improvement, paid ones do not; with Search
Grounding, Google still stores prompt, context and output for 30 days for
grounding purposes. Grounding is used only in the owner's personal workflow,
not to build an index or for third parties.

For Gemini 3 and later, paid usage includes 5,000 free search requests per
month, shared across these models. After that, each further request costs
14 USD per 1,000 requests; the default limit is 1,500 requests per project and
day. A single user prompt can trigger several Google Search requests. Model
token costs are separate.

### Verified facts (as of 2026-11-09)

- `gemini-3.8-flash` is the stable model identifier, published on 2026-09-02,
  with no announced shutdown date. It supports Search Grounding and URL Context.
- Search Grounding returns `url_citation` annotations with title, URL and
  start/end index, `google_search_call` with the executed queries and
  `google_search_result` with suggestions. The contract in ADR 0003 follows
  these fields, not the older `groundingSupports`.
- URL Context returns one `url_context_result` per retrieval with status and
  retrieved URL. PDF is a supported content type.
- Free tier: inputs and outputs may be used for product improvement; paid tier:
  not. Search Grounding still stores prompt, context and output for 30 days.

The adapter re-checks these facts against the pinned SDK; a deviation is
reported instead of guessed.

## Consequences

- Good: No Gemini call blocks the event loop.
- Good: Load and error behavior are configurable and testable.
- Good: Switching models stays a configuration decision.
- Bad: An API key and current pricing terms remain operating prerequisites.
- Bad: Grounding cost depends on the tier and on individual search requests.

## Open

The exact `google-genai` version is pinned in the lockfile. Price, quota and
Google's terms are checked against the current primary source before release.

## More Information

- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API Terms](https://ai.google.dev/gemini-api/terms)

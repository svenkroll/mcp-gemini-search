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
grounding purposes; and because the adapter keeps the Interactions API default
`store=true`, Google also retains every interaction for 55 days on the paid
tier. Grounding is used only in the owner's personal workflow,
not to build an index or for third parties.

Costs on the paid tier have two parts: model tokens and Google Search
requests. There is no free token allowance on the paid tier. For Gemini 3 and
later, paid usage includes 5,000 free search requests per month, shared across
these models. After that, each further request costs 14 USD per 1,000
requests; the default limit is 1,500 requests per project and day. Search is
billed per executed search query, not per prompt, so a single `search` call can
consume several requests. URL Context has no fee of its own; the retrieved
content is billed as input tokens. The current figures are listed under
"Verified facts".

The adapter deliberately keeps the Interactions API default `store=true` and
never passes `store`. Google therefore retains every interaction (input, URL,
question, system instruction and output) for 55 days on the paid tier, in
addition to the 30-day Search Grounding storage. This is accepted for the
owner's personal workflow and keeps interactions visible in AI Studio for
debugging. `store=false` is not used because it removes that visibility, and
the adapter needs none of the stateful features it would also disable
(`previous_interaction_id`, background execution), so the decision is about
debugging versus retention only.

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
- Pricing (as of 2026-11-13, Gemini Developer API pricing page, Standard,
  paid tier, per 1M tokens): `gemini-3.8-flash` input 0.75 USD and output
  including thinking tokens 3.75 USD through 2026-12-31; from 2027-01-01
  input 1.50 USD and output 7.50 USD. Batch and Flex cost half, but the
  adapter uses neither.
- Google Search with Gemini 3 and later: each search query the model executes
  is billed; empty queries are ignored. 5,000 free requests per month shared
  across Gemini 3 and later models, then 14 USD per 1,000 requests. Default cap
  1,500 requests per day and project on all paid tiers, resetting at midnight
  Pacific Time; more can be requested in AI Studio.
- URL Context: no fee of its own. The retrieved content is reported as
  `tool_use_input_tokens` in the usage metadata and billed at the model's input
  price, so `analyze_url` cost grows with page size.
- Usage tier 1 (billing account linked, prepay of at least 5 USD) has a
  billing tier cap of 250 USD.
- Interactions API storage (as of 2026-11-13): `store=true` is the default;
  interactions are retained for 55 days on the paid tier and 1 day on the free
  tier. `store=false` opts out but is incompatible with background execution and
  `previous_interaction_id`. Source: Interactions API overview, section "Data
  storage and retention".
- API version (as of 2026-11-13): `v1`. Verified against the `google-genai`
  3.3.0 source (`GOOGLE_AI_API_DEFAULT_VERSION = 'v1'` in `_api_client.py`,
  environment override `GOOGLE_GENAI_API_VERSION`, interactions route
  `/{api_version}/interactions`) and the API versions documentation (Interactions
  API GA in `v1`, Google Search and URL Context supported in `v1`). A manual
  live smoke test on 2026-11-13 against `v1` returned `url_citation`
  annotations with start and end index, `google_search_call` queries and a
  `url_context_result` step.

The adapter re-checks these facts against the pinned SDK; a deviation is
reported instead of guessed.

## Consequences

- Good: No Gemini call blocks the event loop.
- Good: Load and error behavior are configurable and testable.
- Good: Switching models stays a configuration decision.
- Bad: An API key and current pricing terms remain operating prerequisites.
- Bad: Grounding cost depends on the tier and on individual search requests.
- Bad: every request, including URLs and questions, is retained by Google for
  55 days on the paid tier.

## Open

The exact `google-genai` version is pinned in the lockfile. Price, quota and
Google's terms are checked against the current primary source before release.

Not stated in the pricing documentation and to be checked against the usage
metadata of real calls:

- whether search results retrieved by Google Search count as input tokens for
  `gemini-3.8-flash`;
- whether the 5,000 free search requests per month apply per project or per
  billing account.

## More Information

- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [API versions explained](https://ai.google.dev/gemini-api/docs/api-versions)
- [Interactions API reference, v1](https://ai.google.dev/api/interactions-api-v1)
- [Interactions API overview, data storage and retention](https://ai.google.dev/gemini-api/docs/interactions/interactions-overview#data-storage-retention)
- [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search)
- [URL context](https://ai.google.dev/gemini-api/docs/url-context)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Rate limits and usage tiers](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API Terms](https://ai.google.dev/gemini-api/terms)

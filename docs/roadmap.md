# Roadmap

Deliberately not part of Release 1. Each item requires an issue before
implementation and, where it affects an architectural decision, an ADR.

| Topic | Scope | Trigger |
| --- | --- | --- |
| OpenCode as client | Configuration, end-to-end test, docs | Release 1 only tests OpenHands |
| Recurring live evals | Scheduled, budgeted eval run | ADR 0005, Open |
| Vertex AI backend | Switch in the Gemini adapter to call the Interactions API on Gemini Enterprise Agent Platform (formerly Vertex AI) instead of the Gemini Developer API; details below | ADR 0006, option 3; region and retention control for organizations |
| Additional search providers | Serper, Tavily behind the provider boundary | ADR 0009, Open |
| Token rotation | Changing the bearer token without downtime | ADR 0008 |
| OAuth | MCP authorization with Protected Resource Metadata, e.g. for claude.ai connectors | ADR 0008, Access control |
| Live measurement of prompt injection | Controlled, publicly hosted injection pages in the catalog | ADR 0005, ADR 0008 |

## Vertex AI backend

Status as of 2026-11-15: not started, feasibility checked from documentation
only, no live call made.

Why: the Gemini Developer API gives no control over the processing region and
retains queries ([ADR 0006](adr/0006-gemini-integration.md)). Organizations
that need region control, IAM, audit logs or contractual retention terms can
usually only approve Google Cloud. ADR 0006 rejected Vertex AI as a
prerequisite for Release 1; at that time the Interactions API was not
available there.

What is known:

- The Interactions API is now available on Gemini Enterprise Agent Platform
  through the same `google-genai` SDK, with the `google_search` tool
  ([overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/interactions),
  [reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/interactions-api)).
- Gemini 3 models were listed as Preview for the Interactions API there
  ([release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes)).
- The documented endpoint uses `locations/global`.
- A forum report from July 2026 says the Interactions API does not work with
  Vertex AI Express mode (API key), so a Google Cloud project with a service
  account is needed.

Expected change, estimated at one to two days if the responses are identical:

- `gemini_client.py`: create the client with `vertexai=True`, project and
  location instead of `api_key`; one place.
- Configuration (ADR 0010): variables for backend, project and location;
  `GEMINI_API_KEY` required only for the Developer API backend.
- Container and runbook: credentials through a service account or workload
  identity.
- Tests for configuration and client creation; the response mapping is already
  tested against the `InteractionsClient` protocol.
- ADR 0006 superseded or amended; README sections Configuration, Data
  protection and Costs.

To verify with one live call before any implementation:

1. Is `gemini-3.8-flash` supported for the Interactions API there, and is it
   still Preview?
2. Do `url_citation` annotations carry the same fields and UTF-8 byte offsets?
   `eval/` has a probe for citation offsets.
3. Are citation URLs redirects on `vertexaisearch.cloud.google.com`? The URL
   policy (ADR 0008) allows only this host.
4. Does URL Context work there for `analyze_url`?
5. Are regional endpoints, for example in the EU, available for the
   Interactions API, or only `global`?
6. What are the `store` default, the retention periods and the price of
   Grounding with Google Search there? Is Web Grounding for Enterprise a
   better fit?

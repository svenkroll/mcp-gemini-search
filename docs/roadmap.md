# Roadmap

Deliberately not part of Release 1. Each item requires an issue before
implementation and, where it affects an architectural decision, an ADR.

| Topic | Scope | Trigger |
| --- | --- | --- |
| OpenCode as client | Configuration, end-to-end test, docs | Release 1 only tests OpenHands |
| Recurring live evals | Scheduled, budgeted eval run | ADR 0005, Open |
| Live canary | Daily scheduled CI check: model available, tools registered, fixed cases still answered with sources; fails so needed updates are noticed. Not a quality evaluation | Issue #40 (planned for release 1, ADR 0011 to be written) |
| Additional search providers | Serper, Tavily behind the provider boundary | ADR 0009, Open |
| Token rotation | Changing the bearer token without downtime | ADR 0008 |
| OAuth | MCP authorization with Protected Resource Metadata, e.g. for claude.ai connectors | ADR 0008, Access control |
| Live measurement of prompt injection | Controlled, publicly hosted injection pages in the catalog | ADR 0005, ADR 0008 |

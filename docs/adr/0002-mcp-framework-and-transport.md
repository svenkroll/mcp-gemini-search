---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0002 MCP Framework and Transport

## Context and Problem Statement

The server runs locally as a stdio process and remotely behind Kubernetes. It
must serve current and older MCP clients without coupling tool logic to a
framework. OpenHands is the mandatory test client for release 1; OpenCode and
other clients are on the roadmap (`docs/roadmap.md`).

## Considered Options

1. Use the official MCP Python SDK directly.
2. Use FastMCP 4 on top of the official SDK.
3. Write our own JSON-RPC and transport handling.

## Decision

**Option 2**, FastMCP **4.1.6** pinned exactly, no pre-releases. FastMCP 4 is
built on MCP Python SDK v2 and negotiates both current and older protocol
revisions. Tool logic and the Gemini adapter do not import FastMCP; `server.py`
contains only thin MCP wrappers.

The server starts via `mcp.run()`: stdio is the default for local clients,
`mcp.run(transport="http")` serves Streamable HTTP. The HTTP endpoint is
`/mcp`, stateless and designed for MCP revision 2026-07-28; version negotiation
keeps older clients working, and both protocol generations are served on the
same endpoint. Health checks run on `/health/live` and `/health/ready`, not on
the removed `ping`.

Additional requirements for revision 2026-07-28:

- The server validates an `Origin` header when present and answers HTTP 403
  for an invalid origin. Requests without `Origin` (non-browser clients) are
  processed normally.
- Both tools carry annotations (`readOnlyHint: true`, `openWorldHint: true`,
  `idempotentHint: true`) and a `title`; `tools/list` returns a stable order.
  With `ANALYZE_URL_ENABLED=false` (the default, ADR 0010) `analyze_url` is
  not registered and `tools/list` contains only `search`.
- Tool calls are safe to repeat, because clients re-send interrupted requests
  instead of resuming a stream. A repeated call consumes Gemini quota again.
- Reverse proxies (Caddy, Traefik, HAProxy) pass `MCP-Protocol-Version`,
  `Mcp-Method` and `Mcp-Name` through unchanged.
- Protocol logging, sampling, roots and elicitation are not used; logs go to
  stdout (ADR 0007).

### Verified facts (as of 2026-11-09)

- FastMCP 4.1.6 is the current stable 4.x release; no 4.2 pre-release is used.
- FastMCP 4.1.x supports Python 3.14 and negotiates between revision
  2026-07-28 and older client revisions.
- Multi-arch compatibility of the final dependency set is checked in the
  container build.

## Consequences

- Good: stdio and HTTP share tool contracts and test cases.
- Good: Stateless HTTP works behind load balancers without session affinity.
- Good: A later switch to the plain SDK is limited to the server wrappers.
- Bad: FastMCP moves fast and must be pinned strictly.
- Bad: OpenHands compatibility has to be proven in the end-to-end test.

## Open

The exact `google-genai` version is fixed in the first lockfile that adds it.
The end-to-end test records the protocol revision OpenHands actually
negotiates.

## More Information

- [FastMCP Running Servers](https://github.com/PrefectHQ/fastmcp/blob/main/docs/deployment/running-server.mdx)
- [MCP Streamable HTTP 2026-07-28](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)

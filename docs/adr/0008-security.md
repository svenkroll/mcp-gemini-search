---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0008 Security

## Context and Problem Statement

The server is publicly reachable, holds a Gemini key that incurs cost, processes
third-party URLs and passes source URLs to agents. Without access control, URL
checks and clear handling of untrusted web content, cost, internal networks and
agents would be at risk.

## Considered Options

1. Rely only on network isolation through the ingress.
2. Static bearer token, a two-stage URL policy and prompt-injection boundaries.
3. OAuth and full user management in the first release.

## Decision

**Option 2**.

### Access control

HTTP requires `Authorization: Bearer <MCP_BEARER_TOKEN>` (ADR 0010) before every
MCP call. It is implemented through FastMCP's auth abstraction: a custom
`TokenVerifier` that compares in constant time. No custom middleware. If the
token is missing or wrong, the server answers HTTP 401 with
`WWW-Authenticate: Bearer` and no further details. A later switch to OAuth
(Protected Resource Metadata per the MCP specification) only replaces the
verifier or auth provider and is on the roadmap. `/health/live` and
`/health/ready` stay reachable without a token. stdio has no HTTP
authentication. Token rotation is not part of the first release.

### URL policy

The policy lives in its own framework-free module `urlpolicy` and has two
stages.

**Input check** for every URL the server accepts or returns (`analyze_url.url`
and every `search` source URL):

- only `http` and `https`, host present, at most 2,048 characters
- no credentials in the URL
- port empty, 80 or 443
- the host is not an IP literal from loopback, private, link-local, multicast,
  CGNAT or reserved IPv4/IPv6 ranges
- the host does not end in `localhost`, `.local`, `.internal`, `.localhost`
- no DNS resolution: Google performs retrieval and cannot reach internal
  networks anyway

Implemented with existing building blocks instead of custom parsers: URL syntax
via Pydantic `HttpUrl`, IP literals via the standard library `ipaddress`
(`is_global` covers private, reserved and CGNAT ranges).

**Fetch check** for every network request the server makes itself. In the first
release this is only the resolution of grounding redirects (ADR 0003):

- connections only to hosts on the redirect allowlist
  (`vertexaisearch.cloud.google.com`), HTTPS only
- follow redirects manually, at most five; a `Location` target outside the
  allowlist is the target URL and is not fetched, only input-checked
- content is never read; only the `Location` header counts
- 3 s connect, 5 s total per source, at most 5 parallel resolutions, 8 s
  overall budget per search

Retrieval for `analyze_url` is done by Google (ADR 0004); the server does not
load third-party content.

### Untrusted web content

Web content is untrusted. English tool descriptions and Gemini instructions
state explicitly that instructions in web text must not be followed. Unit tests
with fixed fixtures cover this: the instruction is part of every Gemini call,
tool descriptions contain the notice, and the server never returns raw content.
Whether Gemini ignores instructions on real pages is not measured live in the
first release.

## Consequences

- Good: Knowing the public endpoint is not enough to use Gemini.
- Good: The server only connects to Google's redirect host and reads no
  content; this creates no SSRF surface against internal networks.
- Good: Agents never receive internal or obviously manipulated URLs as sources.
- Bad: The deployer is responsible for secret storage and rotation.
- Bad: Strict port and network rules exclude some legitimate URLs.
- Bad: The model's own injection resistance is not measured live, only our part
  (instruction, no raw output).

## Open

The Traefik and local Caddy setups must allow long read timeouts for
request-scoped SSE responses. The transparent HAProxy is not part of the
container.

## More Information

- [MCP Streamable HTTP](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)
- ADR 0003, ADR 0004, ADR 0007, ADR 0010

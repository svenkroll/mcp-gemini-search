# Runbook

How to run the Gemini Search MCP server as a container: handing over secrets,
starting it locally with Compose, proxy settings and health probes for
Kubernetes. Behavior of the server itself is described in the
[README](../README.md); the decisions behind this runbook are
[ADR 0002](adr/0002-mcp-framework-and-transport.md) (headers, proxies),
[ADR 0008](adr/0008-security.md) (access control, timeouts) and
[ADR 0010](adr/0010-configuration.md) (configuration).

## The container image

The [`Dockerfile`](../Dockerfile) builds a multi-stage image for `linux/amd64`
and `linux/arm64`:

- Base image: the official `python:3.14-slim-trixie` image, pinned by digest.
  The `uv` binary is copied from the pinned `ghcr.io/astral-sh/uv` image.
- The final stage installs the Debian security updates that are newer than the
  pinned base image and removes `pip`, so a fixed vulnerability in the base
  image does not fail the Trivy scan and the image has no package installer.
- Only locked runtime dependencies are installed (`uv sync --locked --no-dev`).
  Dev tools, tests, docs and evaluation files are not part of the image.
- The process runs as the non-root user `10001:10001`, writes only to stdout
  and stderr, and needs no writable path, so a read-only root filesystem works.
- Defaults: `MCP_TRANSPORT=http`, `MCP_HOST=0.0.0.0`, port `8000`. The image
  contains no secrets.
- The image is not published to a registry. Build it yourself:

```bash
docker build --tag gemini-search-mcp:local .
```

CI (job `container`) lints the `Dockerfile` with Hadolint, builds both
architectures, scans the amd64 image with Trivy (fixed `CRITICAL` and `HIGH`
findings fail the job) and smoke-tests it.

## Secrets

Two values are secret: `GEMINI_API_KEY` and `MCP_BEARER_TOKEN`. The server
reads them only from environment variables ([ADR 0010](adr/0010-configuration.md))
and never logs them.

- Never put them into the image, the `Dockerfile`, `compose.yaml` or Git. `.env`
  is ignored by Git and by `.dockerignore`; `.env.example` holds empty
  placeholders only.
- Pass them at run time from a file or a secret store, not as `-e NAME=value` on
  a command line, where they end up in the shell history and the process list.
- Create a token of at least 32 characters, for example `openssl rand -hex 32`
  (64 characters).
- Docker: `docker run --env-file .env ...` (see below).
- Kubernetes: put both values into a `Secret` and reference it from the
  container, either with `envFrom.secretRef` or one `env.valueFrom.secretKeyRef`
  per variable. Rotating a value means updating the secret and restarting the
  pods; the server reads the environment once at startup.
- Start-up check: if a required variable is empty or missing, the container
  exits with code 2 before opening a port and prints the variable and the rule
  (for example `GEMINI_API_KEY: must not be empty`) to stderr. It never prints
  the value. In Kubernetes this shows up as `CrashLoopBackOff` with that message
  in `kubectl logs`.

## Local start with Compose

[`compose.yaml`](../compose.yaml) starts the server and a Caddy reverse proxy
([`Caddyfile`](../Caddyfile)). The server publishes no port itself; Caddy
listens on `127.0.0.1:8080` and forwards to it.

Prerequisites: Docker with Compose v2, a Gemini API key of a project on the paid
tier (see the README, [Costs](../README.md#costs)), and uv (`make install`) for
the example client in step 4.

1. Create the configuration and fill in the two secrets:

   ```bash
   cp .env.example .env
   chmod 600 .env
   # edit .env: set GEMINI_API_KEY and MCP_BEARER_TOKEN (at least 32 characters)
   # optional: ANALYZE_URL_ENABLED=true to register analyze_url
   ```

   Blank values in `.env` count as unset and fall back to the defaults.
   `compose.yaml` fixes `MCP_TRANSPORT=http`, `MCP_HOST=0.0.0.0` and
   `MCP_PORT=8000`, because Caddy forwards to that address.

2. Build and start:

   ```bash
   docker compose up --build
   ```

   Expected: `server` becomes healthy, then `caddy` starts. The server log shows
   JSON lines such as `Uvicorn running on http://0.0.0.0:8000`.

3. Check the stack from another terminal (the token is the one from `.env`):

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/health/ready
   # 200
   curl -s -i -X POST -H 'Content-Type: application/json' -d '{}' \
     http://127.0.0.1:8080/mcp | head -n 1
   # HTTP/1.1 401 Unauthorized   (with the header www-authenticate: Bearer)
   ```

4. List and call the tools through Caddy with an MCP client that sends the
   token. With the FastMCP client from this repository's environment:

   ```bash
   export MCP_BEARER_TOKEN=<the token from .env>
   uv run python - <<'PY'
   import asyncio, os
   from fastmcp import Client

   async def main():
       async with Client("http://127.0.0.1:8080/mcp", auth=os.environ["MCP_BEARER_TOKEN"]) as client:
           print([tool.name for tool in await client.list_tools()])
           result = await client.call_tool(
               "search", {"query": "Which element has the atomic number 79? Cite your source."}
           )
           print(result.structured_content)
           # Only with ANALYZE_URL_ENABLED=true:
           result = await client.call_tool(
               "analyze_url",
               {"url": "https://example.com/", "question": "What is this page about?"},
           )
           print(result.structured_content)

   asyncio.run(main())
   PY
   ```

   Expected: the tool list contains `search` (and `analyze_url` when enabled),
   `search` returns `answer`, `sources`, `search_queries`, and `analyze_url`
   returns `answer`, `url` and `retrieval_status`. Both calls cost money.
   Remove the `analyze_url` call when it is not enabled.

   Any other MCP client works the same way: URL `http://127.0.0.1:8080/mcp`,
   header `Authorization: Bearer <MCP_BEARER_TOKEN>`.

5. Optional, no Gemini call: check that Caddy does not cut off a call longer
   than 60 seconds. This starts a stub in place of the server that answers
   `/mcp` only after 75 seconds; CI runs the same check in the step "Proxy test"
   of the job `container`. Stop the Compose stack first (`docker compose down`).

   ```bash
   docker network create proxytest
   docker run --rm --detach --name server --network proxytest --entrypoint python \
     gemini-search-mcp:local -u -c '
   import http.server, time
   class H(http.server.BaseHTTPRequestHandler):
       def do_POST(self):
           time.sleep(75)
           self.send_response(200)
           self.send_header("Content-Type", "text/event-stream")
           self.end_headers()
           self.wfile.write(b"event: message\ndata: done\n\n")
       def do_GET(self):
           self.send_response(200)
           self.send_header("Content-Length", "0")
           self.end_headers()
   http.server.ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()'
   docker run --rm --detach --name caddy --network proxytest \
     --publish 127.0.0.1:8080:8080 --volume "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
     caddy:2.11.9-alpine
   curl -sS --max-time 120 -X POST -w '\n%{http_code} after %{time_total} s\n' \
     http://127.0.0.1:8080/mcp
   docker rm --force server caddy && docker network rm proxytest
   ```

   Expected: after about 75 seconds the output is `event: message`,
   `data: done` and `200 after 75... s`. A proxy that cuts the call off answers
   502 or 504 earlier, or the connection ends without a body.

6. Stop with `Ctrl+C`, then `docker compose down`.

Without `.env`, `docker compose up` stops with an error naming the missing
file. Without `GEMINI_API_KEY` in it, the `server` container exits with code 2
and its log names the variable (`docker compose logs server`).

### Running the image without Compose

```bash
docker run --rm --env-file .env --read-only --cap-drop ALL \
  --security-opt no-new-privileges --publish 127.0.0.1:8000:8000 \
  gemini-search-mcp:local
```

`--env-file` passes blank values as empty, which the server treats as unset; the
image defaults `MCP_TRANSPORT=http` and `MCP_HOST=0.0.0.0` therefore only apply
when the lines are absent from the file or set to a value. Use
`-e MCP_TRANSPORT=http -e MCP_HOST=0.0.0.0` if your file lists them blank.

## Proxy settings

The server is stateless. A `tools/call` answers with one response that can take
as long as the Gemini call: up to `GEMINI_TIMEOUT_SECONDS` (at most 300 s) plus
about 8 s to resolve grounding redirects. A proxy in front must therefore

- allow a read (inactivity) timeout of at least **330 seconds**, or the value of
  `GEMINI_TIMEOUT_SECONDS` plus 30 seconds if you lowered it; many proxies cut
  off after 30 to 60 seconds by default;
- not buffer responses, so that event-stream chunks reach the client at once;
- pass `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` through unchanged
  ([ADR 0002](adr/0002-mcp-framework-and-transport.md)), and not drop or rewrite
  `Authorization` ([ADR 0008](adr/0008-security.md)).

A proxy that terminates TLS in front of the server changes what the server
sees: the connection to the server is plain `http`. The server compares an
`Origin` header with the scheme and host of that connection (ADR 0002), so a
browser request with `Origin: https://...` is answered with HTTP 403 behind such
a proxy. MCP clients that are not browsers send no `Origin` header and are not
affected.

A client that gives up earlier abandons the call, but the server may already
have spent Gemini quota on it.

### Caddy

The [`Caddyfile`](../Caddyfile) in this repository does this:

```caddyfile
reverse_proxy server:8000 {
	flush_interval -1                # flush every chunk at once
	transport http {
		dial_timeout 5s
		response_header_timeout 330s
		read_timeout 330s
		write_timeout 30s
	}
}
```

Caddy does not buffer responses with `flush_interval -1` and forwards all
request headers unchanged by default. Do not add `header_up` rules that touch
the three MCP headers or `Authorization`. Caddy adds `X-Forwarded-*` headers.

### Traefik

Traefik forwards request headers unchanged unless a `headers` middleware
changes them, and does not buffer responses unless the `buffering` middleware is
attached. Raise the timeouts in the static configuration (the exact option
names and defaults depend on your Traefik version, check its documentation):

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 60s      # reading the request; the request is small
        writeTimeout: 0s      # 0 = no limit; the response may take up to 308 s
        idleTimeout: 360s
serversTransport:
  forwardingTimeouts:
    responseHeaderTimeout: 330s
```

Do not attach a `buffering` middleware to the router for `/mcp`.

### HAProxy

HAProxy passes headers unchanged unless `http-request del-header` or
`set-header` rules change them. Use inactivity timeouts above the longest call
and do not buffer or compress the response:

```haproxy
defaults
    mode http
    timeout connect 5s
    timeout http-request 30s
    timeout client  330s
    timeout server  330s
```

Do not enable `option http-buffer-request` or `compression` for `/mcp`.
`timeout client` and `timeout server` are inactivity timeouts: with a response
that starts only after the Gemini call finishes, `timeout server` has to be
longer than that call.

## Health probes for Kubernetes

The server serves two endpoints without a token on its HTTP port (8000):

| Endpoint | Meaning |
| --- | --- |
| `/health/live` | the process is up |
| `/health/ready` | the settings are loaded; it never calls Gemini |

Example probes and security context for the container (fragment, adapt to your
manifest):

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
livenessProbe:
  httpGet: { path: /health/live, port: 8000 }
  periodSeconds: 10
  timeoutSeconds: 3
readinessProbe:
  httpGet: { path: /health/ready, port: 8000 }
  periodSeconds: 10
  timeoutSeconds: 3
```

The probes need no `Authorization` header. A readiness probe passing does not
prove that the Gemini key is valid; an invalid key shows up as
`upstream_error` in tool calls.

Set the timeout of the ingress or gateway as described under
[Proxy settings](#proxy-settings).

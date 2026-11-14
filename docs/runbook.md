# Runbook

How to run the Gemini Search MCP server from its container image, behind a
reverse proxy and in CI. The rules behind the image and the CI job are in
[ADR 0011](adr/0011-container-and-ci.md); the configuration variables are in
[ADR 0010](adr/0010-configuration.md).

## Contents

- [The image](#the-image)
- [Handing over secrets](#handing-over-secrets)
- [Local start with Compose](#local-start-with-compose)
- [Proxy timeouts and header pass-through](#proxy-timeouts-and-header-pass-through)
- [Health probes for Kubernetes](#health-probes-for-kubernetes)
- [Running the CI scripts locally](#running-the-ci-scripts-locally)
- [Troubleshooting](#troubleshooting)

## The image

The `Dockerfile` builds a multi-stage image for `linux/amd64` and
`linux/arm64`:

- Base: the official `python:3.14-slim-trixie` image, pinned by digest.
- Dependencies come from `uv.lock` without the `dev` group; the image contains
  no test, lint or type-check tooling.
- It runs as the numeric user `10001:10001`, never as root, and writes only to
  stdout and stderr. It works with a read-only root filesystem.
- Defaults: `MCP_TRANSPORT=http`, `MCP_HOST=0.0.0.0`, `MCP_PORT=8000`
  (exposed). All other variables are set at run time.
- The image contains no secret and reads no `.env` file. `.dockerignore` keeps
  `.env`, `.venv`, caches, `eval/runs/` and `.git` out of the build context.

CI never publishes the image. Build it yourself:

```bash
docker build -t gemini-search-mcp:local .
```

## Handing over secrets

The server needs two secrets, `GEMINI_API_KEY` and `MCP_BEARER_TOKEN` (at least
32 characters). They are handed over as environment variables at run time and
never baked into the image, a Compose file or a repository file.

Create a token:

```bash
openssl rand -hex 32
```

| Where | How |
| --- | --- |
| Compose | Local `.env` file next to `compose.yaml`: `cp .env.example .env`, then fill in the values. `.env` is ignored by git and by the Docker build context; never commit it. |
| `docker run` | `--env-file <file>` with a file outside the repository, or `--env GEMINI_API_KEY --env MCP_BEARER_TOKEN` to pass the variables from your shell without writing the values on the command line. |
| Kubernetes | A `Secret` with both keys, referenced from the container with `envFrom.secretRef` or `env[].valueFrom.secretKeyRef`. |

Rotating a secret means changing the value and restarting the container; there
is no hot reload. If a required variable is missing or invalid, the container
exits with code 2 before opening a port, and its log names the variable and the
rule, never the value (for example `GEMINI_API_KEY: must not be empty`).

## Local start with Compose

`compose.yaml` starts the server and Caddy. Caddy listens on
`127.0.0.1:8080` and forwards to the server, which has no published port of its
own. Prerequisites: Docker with Compose v2.

1. Create the configuration and fill in `GEMINI_API_KEY` and
   `MCP_BEARER_TOKEN`. Set `ANALYZE_URL_ENABLED=true` to use `analyze_url`;
   without it only `search` exists.

   ```bash
   cp .env.example .env
   ```

   Empty lines of `.env.example` count as unset. Do not change `MCP_PORT`:
   the health check and the `Caddyfile` use port 8000.

2. Build and start:

   ```bash
   docker compose up --build
   ```

   Expected: the server starts first; Caddy starts when the server health
   check passes. With a missing key the `server` container exits with code 2
   and `docker compose logs server` names `GEMINI_API_KEY`.

3. In a second terminal, check readiness and authentication:

   ```bash
   curl -i http://127.0.0.1:8080/health/ready
   # expected: HTTP/1.1 200 OK

   curl -i -X POST http://127.0.0.1:8080/mcp \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
   # expected: HTTP/1.1 401 Unauthorized, header WWW-Authenticate: Bearer
   ```

4. Call the tools through Caddy with your token. The `MCP-Protocol-Version`,
   `Mcp-Method` and `Mcp-Name` headers announce the revision, the method and
   the tool; Caddy passes them through unchanged.

   ```bash
   set -a; . ./.env; set +a   # loads MCP_BEARER_TOKEN into your shell

   curl -sS -N -X POST http://127.0.0.1:8080/mcp \
     -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -H 'MCP-Protocol-Version: 2026-07-28' \
     -H 'Mcp-Method: tools/call' \
     -H 'Mcp-Name: search' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search","arguments":{"query":"What is the current stable version of Python?"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'

   curl -sS -N -X POST http://127.0.0.1:8080/mcp \
     -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -H 'MCP-Protocol-Version: 2026-07-28' \
     -H 'Mcp-Method: tools/call' \
     -H 'Mcp-Name: analyze_url' \
     -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"analyze_url","arguments":{"url":"https://www.python.org/","question":"What is this page about?"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
   ```

   Expected: HTTP 200 and a JSON-RPC response whose `result.content` holds the
   tool output (an answer and its sources, see the README). An error looks like
   `"isError": true` with a short error code from
   [ADR 0007](adr/0007-error-handling-and-logging.md). Every call costs money
   (see the README, section Costs).

5. Stop and clean up:

   ```bash
   docker compose down
   ```

   `docker compose down --volumes` also removes Caddy's data volumes.

To reach the stack from other machines or under a host name, change the site
address `:8080` in the `Caddyfile` (a host name makes Caddy obtain a
certificate) and the published port in `compose.yaml`. Expose it only with the
bearer token configured.

## Proxy timeouts and header pass-through

Every reverse proxy in front of the server must satisfy two rules from
[ADR 0002](adr/0002-mcp-framework-and-transport.md) and
[ADR 0008](adr/0008-security.md):

1. **Long read timeouts, no buffering.** A tool call answers with a
   request-scoped server-sent-events stream. One Gemini call can take up to
   `GEMINI_TIMEOUT_SECONDS` (default 60, at most 300) plus at most 8 seconds
   for resolving source links. A proxy that cuts the connection after 30 or 60
   seconds of silence breaks long calls. Use a timeout of at least
   `GEMINI_TIMEOUT_SECONDS` plus 10 seconds; the repository `Caddyfile` uses
   330 seconds, which covers the maximum. Do not buffer the response, and do
   not compress it.
2. **Pass `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` through
   unchanged.** Do not remove, rename or overwrite them. Header names are
   case-insensitive; proxies may change the letter case.

### Caddy

This is what the repository `Caddyfile` does, and what `scripts/ci/proxy-test.sh`
verifies in CI. The test sends two requests at once: one with
`Accept: application/json, text/event-stream`, which the server answers with
a plain JSON body and no response header until the result is ready (so
`response_header_timeout` and `read_timeout` matter), and one with
`Accept: text/event-stream`, which opens a stream and stays silent. Both
responses are delayed by 75 seconds and must arrive complete with the three
headers unchanged:

```caddyfile
:8080 {
	reverse_proxy server:8000 {
		flush_interval -1
		transport http {
			dial_timeout 5s
			response_header_timeout 330s
			read_timeout 330s
		}
	}
}
```

Caddy forwards request headers unchanged unless a `header_up` rule changes
them; the file has none.

### Traefik

Only Caddy is tested in CI. The Traefik and HAProxy settings below follow the
documentation of the respective proxy; check them against your version.

Static configuration. `respondingTimeouts` control the connection to the
client, `forwardingTimeouts` the connection to the server. A value of `0`
means no timeout:

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 30s
        writeTimeout: 0s
        idleTimeout: 180s
serversTransport:
  forwardingTimeouts:
    dialTimeout: 5s
    responseHeaderTimeout: 330s
```

Do not attach the `buffering` or `compress` middleware to the route, and do not
add a `headers` middleware that removes or replaces the three MCP headers;
Traefik forwards request headers unchanged by default. `readTimeout` covers
reading the request, not the response, so a short value is fine.

### HAProxy

```haproxy
defaults
    mode http
    timeout connect 5s
    timeout client  330s
    timeout server  330s
```

Do not enable `compression` for `text/event-stream`, do not use
`option http-buffer-request`, and add no `http-request del-header`,
`set-header` or `replace-header` rule for the three MCP headers; HAProxy
forwards them unchanged by default.

## Health probes for Kubernetes

Both endpoints need no token and are served on the MCP port:

| Endpoint | Meaning |
| --- | --- |
| `GET /health/live` | HTTP 200 while the process serves requests |
| `GET /health/ready` | HTTP 200 as soon as the settings are loaded; it never calls Gemini |

```yaml
containers:
  - name: gemini-search-mcp
    image: <your image>
    ports:
      - containerPort: 8000
    envFrom:
      - secretRef:
          name: gemini-search-mcp
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8000
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8000
      periodSeconds: 5
    securityContext:
      runAsNonRoot: true
      runAsUser: 10001
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

`runAsNonRoot` works because the image sets a numeric user. The ingress or
gateway in front of the pod needs the timeouts and header rules above.

## Running the CI scripts locally

The `container` job of `.github/workflows/ci.yml` only calls scripts under
`scripts/ci/`. Run them from any directory inside the repository. Prerequisites
besides `make install`: Docker (Compose v2 for the proxy test), `curl` and
`git`. The scripts exit with 0 on success.

| Step | Command | Expected |
| --- | --- | --- |
| Select steps from a diff | `scripts/ci/detect-changes.sh origin/main` | three `key=value` lines on stdout; with only documentation changed, all `false` and `container: nothing to build` on stderr |
| Select every step | `scripts/ci/detect-changes.sh --all` | all three values `true` |
| Dockerfile lint | `scripts/ci/hadolint.sh` | no output; every finding of any severity fails, inline `hadolint ignore` pragmas are disabled |
| Build | `docker build -t gemini-search-mcp:ci .` | image built for your host architecture |
| Build arm64 on an amd64 host | `docker buildx build --platform linux/arm64 .` | builds under emulation; CI builds natively on an arm64 runner |
| Image scan | `scripts/ci/scan-image.sh gemini-search-mcp:ci` | report of CRITICAL and HIGH findings; exit 1 only for CRITICAL |
| Smoke test | `scripts/ci/smoke-test.sh gemini-search-mcp:ci` | four `ok:` lines: non-root user, exit code 2 without `GEMINI_API_KEY`, `/health/ready` 200 with a read-only filesystem, `/mcp` without token 401 |
| Proxy test | `scripts/ci/proxy-test.sh` | fifteen `ok: json: ...` and `ok: sse: ...` lines; takes about 80 seconds, needs host port 8080 |
| Aggregate results | `scripts/ci/require-success.sh a=success b=skipped` | exit 0; `failure` or `cancelled` gives exit 1 |

Details per script are in its header comment. Useful variables:

- `SMOKE_TEST_PORT` (default 18000) and `SMOKE_TEST_START_TIMEOUT` (default 30
  seconds) for `smoke-test.sh`.
- `PROXY_TEST_DELAY_SECONDS` (default 75, must be greater than 60) for
  `proxy-test.sh`; for a quick run use `PROXY_TEST_DELAY_SECONDS=61`.
- `TRIVY_CACHE_DIR` for `scan-image.sh` to reuse the vulnerability database
  between runs.

The proxy test runs the repository `Caddyfile` against a fake backend
(`scripts/ci/proxy-stub/backend.py`) in its own image, so it needs no build, no
`.env` and no Gemini key.

To check the detection yourself, including a non-ASCII path, use a scratch
repository (paths are read NUL-delimited, so names with umlauts or newlines
still match):

```bash
d=$(mktemp -d) && git -C "$d" init -q -b main
git -C "$d" commit -q --allow-empty -m base
git -C "$d" checkout -q -b change && mkdir -p "$d/src/pkg" && touch "$d/src/pkg/ü.py"
git -C "$d" add -A && git -C "$d" commit -q -m change
(cd "$d" && "$OLDPWD/scripts/ci/detect-changes.sh" main change)
# expected: build_amd64=true, build_arm64=false, proxy_test=false
```

### Which paths trigger which step

[ADR 0011](adr/0011-container-and-ci.md) defines the policy; pushes to `main`
run everything.

| Step | Runs when these paths change |
| --- | --- |
| linux/amd64 build, Hadolint, image scan, smoke test | `Dockerfile`, `.dockerignore`, `pyproject.toml`, `uv.lock`, `src/` |
| linux/arm64 build | `Dockerfile`, `.dockerignore`, `uv.lock` |
| proxy test | `Caddyfile`, `compose.yaml` |

A pull request that changes none of these paths ends the `container` job
successfully without building.

### Updating pinned images

The uv version appears twice and the two must be updated together: as the
digest-pinned image in the `Dockerfile` and as the checksum-pinned tarball in
the `check` job of `.github/workflows/ci.yml`.

Container images are pinned by digest: the `Dockerfile` (uv and Python, the
Python digest once in the `PYTHON_IMAGE` argument),
`compose.yaml` (Caddy), `scripts/ci/hadolint.sh`, `scripts/ci/scan-image.sh` and
`scripts/ci/proxy-stub/compose.yaml` (stub image). Find a new digest with
`docker buildx imagetools inspect <image>:<tag>` and change the digest and the
version comment together.

An unfixed CRITICAL finding fails the image scan. Exceptions go only into
`.trivyignore` at the repository root, one entry per CVE with a reason and a
review date, added by the project owner.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `docker compose up` reports `env file .env not found` | Run `cp .env.example .env` and fill in the values. |
| `server` exits with code 2 | A variable is missing or invalid; `docker compose logs server` names it. |
| `/mcp` answers 401 | The `Authorization: Bearer` token differs from `MCP_BEARER_TOKEN`. |
| A long call ends early | A proxy in front has a shorter timeout than `GEMINI_TIMEOUT_SECONDS` plus 10 seconds. |
| `proxy-test.sh` cannot bind port 8080 | Another process uses the port; stop it. |

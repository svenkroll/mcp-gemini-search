# Gemini Search MCP

Gemini Search MCP is a personal, publicly reachable MCP server protected by a
static bearer token. It provides the tool `search` and the optional tool `analyze_url`, backed by
the Gemini Developer API. The yardstick is a correct, verifiable, and honest
response for calling LLMs.

## Status

- Tooling: `uv`, Ruff, `ty`, pytest with coverage, pre-commit, GitHub Actions.
- The MCP server (`search`, optional `analyze_url`) runs over stdio and
  stateless Streamable HTTP. HTTP requests to `/mcp` require the static bearer
  token. The container image is not part of the server yet.
- Open tasks and deliberate debt are tracked in [`docs/techdebt.md`](docs/techdebt.md).

## Prerequisites

- Linux, macOS, or WSL
- [uv](https://docs.astral.sh/uv/) (recommended: current version)
- Python 3.14 — installed via `uv` by `make install`; a global installation is
  not required

## Installation

```bash
git clone https://github.com/svenkroll/mcp-gemini-search.git
cd mcp-gemini-search
make install
```

`make install` installs Python 3.14 and synchronizes all dependencies from the
committed `uv.lock`.

## Running the server

The console script `gemini-search-mcp` reads its configuration exclusively from
environment variables ([ADR 0010](docs/adr/0010-configuration.md)). If a
required variable is missing or a rule is violated, it prints the variable name
and the rule to stderr and exits with code 2 before opening a port.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | yes | | Gemini Developer API key |
| `GEMINI_MODEL` | no | `gemini-3.8-flash` | Gemini model |
| `GEMINI_TIMEOUT_SECONDS` | no | `60` | total timeout per Gemini call, 1 to 300 |
| `GEMINI_MAX_CONCURRENCY` | no | `4` | parallel Gemini calls, 1 to 32 |
| `GEMINI_MAX_RETRIES` | no | `2` | retries for 429 and transient 5xx, 0 to 5 |
| `ANALYZE_URL_ENABLED` | no | `false` | register the `analyze_url` tool, see below |
| `LOG_QUERIES` | no | `false` | add the query (for `analyze_url` the question, never the URL) to the log line |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warning` or `error` |
| `MCP_TRANSPORT` | no | `stdio` | `stdio` or `http` |
| `MCP_HOST` | no | `127.0.0.1` | bind address with `http` |
| `MCP_PORT` | no | `8000` | port with `http`, 1 to 65535 |
| `MCP_BEARER_TOKEN` | with `http` | | static bearer token, at least 32 characters |

`.env.example` lists all variables as empty placeholders. The server does not
read a `.env` file; export the variables in the environment of the process.

### stdio

stdio is the default and is meant for local clients. No port is opened and
there are no health endpoints.

```bash
export GEMINI_API_KEY=<your key>
uv run gemini-search-mcp
```

Example entry for an MCP client that starts the process itself:

```json
{
  "mcpServers": {
    "gemini-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-gemini-search", "gemini-search-mcp"],
      "env": { "GEMINI_API_KEY": "<your key>" }
    }
  }
}
```

### Streamable HTTP

```bash
export GEMINI_API_KEY=<your key>
export MCP_TRANSPORT=http
export MCP_BEARER_TOKEN=<at least 32 characters>
uv run gemini-search-mcp
```

Every request to `/mcp` must carry `Authorization: Bearer <MCP_BEARER_TOKEN>`
([ADR 0008](docs/adr/0008-security.md)). The scheme is matched case-insensitively;
the token must match exactly, without surrounding whitespace. A missing or wrong
token is answered with HTTP 401 and `WWW-Authenticate: Bearer`, without further
details. `/health/live` and `/health/ready` need no token. stdio has no
authentication. The token and the `Authorization` header are never logged.

The MCP endpoint is `http://<MCP_HOST>:<MCP_PORT>/mcp`. It is stateless and
serves MCP revision 2026-07-28 and older revisions on the same endpoint.
`GET /health/live` and `GET /health/ready` answer 200 for Kubernetes; readiness
never calls Gemini. A request with an `Origin` header that does not equal the
scheme, host and port the server is reached at (including `null`) is answered
with HTTP 403; requests without `Origin` are processed.

#### Passing the token in OpenHands

In OpenHands (Customize > MCP Servers > Add custom MCP server), enter:

1. Server Type: `SHTTP`.
2. URL: `https://<your host>/mcp`.
3. Authentication: `Bearer token`.
4. API Key: the value of `MCP_BEARER_TOKEN`. OpenHands then sends
   `Authorization: Bearer <token>` with every request.

Server name and Timeout (seconds) are optional.

The legacy OpenHands CLI, which is no longer actively maintained, passes the
token as a header instead:

```bash
openhands mcp add gemini-search --transport http \
  --header "Authorization: Bearer <MCP_BEARER_TOKEN>" \
  https://<your host>/mcp
```

### Logging

Every tool call writes exactly one JSON line to stdout with `ts`, `level`,
`event` (`tool_call`), `request_id`, `tool`, `status`, `error_code`,
`duration_ms`, `model`, `input_tokens` and `output_tokens`; `query` appears only
with `LOG_QUERIES=true`. A failed call with technical details adds one
`error_detail` line with the same `request_id`. API keys and tokens are never
logged ([ADR 0007](docs/adr/0007-error-handling-and-logging.md)).

### `ANALYZE_URL_ENABLED`

`search` is always available. `analyze_url` is registered only with
`ANALYZE_URL_ENABLED=true`; by default it does not appear in `tools/list` and a
call to it is answered as an unknown tool. Whether and when an agent may use it
is decided per project, see
[Using `analyze_url` in your project](#using-analyze_url-in-your-project).

## Local Checks

| Target | Purpose |
| --- | --- |
| `make format` | Apply Ruff formatting and automatic lint fixes |
| `make lint` | Check Ruff format and lint without making changes |
| `make typecheck` | Type check with `ty` |
| `make test` | pytest including coverage threshold |
| `make check` | `lint`, `typecheck`, `test` in that order |
| `make pre-commit` | Run all pre-commit hooks across all files |

The coverage threshold is 80% for `src/gemini_search_mcp/`. A run below the
threshold causes `make test` to fail.

## Structure

```text
src/gemini_search_mcp/  Package: config, provider, Gemini adapter, URL policy, tools, server
tests/unit/             Unit tests without network access
tests/integration/      Integration tests
tests/fixtures/         Controlled fixtures
eval/                   Ground-truth catalog and evaluation script
docs/                   ADRs, tech debt, additional documentation
.github/workflows/      CI
```

## Data protection

- A Gemini API key of a project on the paid tier is required for operation. The
  free tier may use content for product improvement; the paid tier does not.
- Search Grounding stores prompt, context and output for 30 days.
- The Interactions API stores every request for 55 days on the paid tier,
  because the server keeps the default `store=true`.
- Queries, URLs and questions therefore leave your machine and are retained by
  Google.

The reasoning is recorded in
[ADR 0006](docs/adr/0006-gemini-integration.md).

## Costs

Operation runs on the paid tier of the Gemini Developer API, where every token
is billed; there is no free token allowance. As of 2026-11-13:

| Item | Through 2026-12-31 | From 2027-01-01 |
| --- | --- | --- |
| `gemini-3.8-flash` input, per 1M tokens | 0.75 USD | 1.50 USD |
| `gemini-3.8-flash` output incl. thinking, per 1M tokens | 3.75 USD | 7.50 USD |
| Google Search beyond 5,000 free requests per month, per 1,000 | 14 USD | 14 USD |

- `search` is billed per search query the model executes, not per call; one
  call can trigger several queries. At most 1,500 search requests per project
  and day.
- `analyze_url` has no tool fee, but the retrieved page is billed as input
  tokens, so long pages and PDFs cost accordingly.

Details, sources and open questions: [ADR 0006](docs/adr/0006-gemini-integration.md).

## Using `analyze_url` in your project

`search` is the core tool and returns source URLs your agent can load with its
own fetch tool. `analyze_url` is optional and off by default; the operator
enables it with `ANALYZE_URL_ENABLED=true`. It answers one question about one
public URL, retrieved by Google. It returns no original text, keeps the page
out of your agent's context, may load pages your own fetch cannot, and causes
its own costs. Whether it is cheaper than your agent's own fetch depends on
your setup; this server cannot know that ([ADR 0004](docs/adr/0004-analyze-url-tool-contract.md)).

Decide once per project and put one of these rules into its `AGENTS.md`:

- Allowed:

  ```markdown
  You may use the `analyze_url` tool of the gemini-search MCP server whenever
  answering a question about a web page or PDF is enough and no verbatim quote
  is needed.
  ```

- Not allowed:

  ```markdown
  Do not use the `analyze_url` tool of the gemini-search MCP server. Load web
  pages and PDFs with your own fetch tool.
  ```

- Fallback only:

  ```markdown
  Load web pages and PDFs with your own fetch tool first. Use the `analyze_url`
  tool of the gemini-search MCP server only when your own fetch fails or is
  blocked, and say in your answer that the content came from `analyze_url`.
  ```

## Documentation

- Working rules: [`AGENTS.md`](AGENTS.md)
- Architectural Decision Records: [`docs/adr/`](docs/adr/)
- Tickets: [GitHub Issues](https://github.com/svenkroll/mcp-gemini-search/issues), template in [`.github/ISSUE_TEMPLATE/ticket.md`](.github/ISSUE_TEMPLATE/ticket.md)
- Roadmap: [`docs/roadmap.md`](docs/roadmap.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Attribution

The feature scope is modeled after the reference project nav9v. This new edition
is an independent development under the MIT license, not a fork.

## License

MIT, see [`LICENSE`](LICENSE).

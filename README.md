# Gemini Search MCP

Gemini Search MCP is a personal, publicly reachable MCP server protected by a
static bearer token. It provides the tool `search` and the optional tool `analyze_url`, backed by
the Gemini Developer API. The yardstick is a correct, verifiable, and honest
response for calling LLMs.

This repository is in the **scaffolding stage (issue #1)**. It contains the
project structure, quality tooling, and CI, but no tool, provider, or server
implementation yet.

## Status

- Tooling: `uv`, Ruff, `ty`, pytest with coverage, pre-commit, GitHub Actions.
- `src/gemini_search_mcp/` contains documented placeholders only.
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
src/gemini_search_mcp/  Package (only placeholders so far)
tests/unit/             Unit tests without network access
tests/integration/      Integration tests
tests/fixtures/         Controlled fixtures
eval/                   Ground-truth catalog and judge material
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

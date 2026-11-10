# Gemini Search MCP

Gemini Search MCP is a personal, publicly reachable MCP server protected by a
static bearer token. It provides two tools, `search` and `analyze_url`, backed by
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

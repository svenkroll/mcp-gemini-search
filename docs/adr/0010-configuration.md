---
status: proposed
date: 2026-11-10
decision-makers: Sven Kroll
---

# 0010 Configuration

## Context and Problem Statement

Adapter, server and container read configuration in different places. Without
fixed names, defaults and startup behavior, divergent variants and unsafe
starts appear.

## Considered Options

1. A configuration file in the container.
2. Environment variables only, with one central settings model.
3. Command line arguments.

## Decision

**Option 2**. A single pydantic-settings model in `config` reads these
variables; no other module reads the environment directly.

| Variable | Required | Default | Rule |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | yes | | not empty |
| `GEMINI_MODEL` | no | `gemini-3.8-flash` | not empty |
| `GEMINI_TIMEOUT_SECONDS` | no | `60` | 1 to 300 |
| `GEMINI_MAX_CONCURRENCY` | no | `4` | 1 to 32 |
| `GEMINI_MAX_RETRIES` | no | `2` | 0 to 5 |
| `LOG_QUERIES` | no | `false` | boolean |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warning`, `error` |
| `MCP_TRANSPORT` | no | `stdio` | `stdio` or `http` |
| `MCP_HOST` | no | `127.0.0.1` | the container sets `0.0.0.0` |
| `MCP_PORT` | no | `8000` | 1 to 65535 |
| `MCP_BEARER_TOKEN` | with `http` | | at least 32 characters |

Startup behavior: if a required variable is empty or a rule is violated, the
process exits with code 2 before opening a port and prints a message to stderr
that names only the variable and the rule, never the value. Secrets are typed as
`SecretStr` and do not appear in `repr`. `/health/ready` succeeds as soon as the
settings are loaded.

`.env.example` lists all variables with an empty value and a comment.

## Consequences

- Good: One place for names, limits and error messages.
- Good: Container and Kubernetes need no files.
- Bad: Renaming a variable requires an ADR update.

## Open

None.

## More Information

- ADR 0006: Gemini integration, ADR 0007: logging, ADR 0008: access control

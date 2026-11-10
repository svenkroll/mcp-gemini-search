# Contributing

The foundation for all work is [`AGENTS.md`](AGENTS.md) together with the
respective GitHub issue and the ADRs referenced there. New tickets are created
exclusively as issues using the template `.github/ISSUE_TEMPLATE/ticket.md`.

## Workflow

1. Read the ticket, referenced ADRs, and affected documentation completely.
2. Create a short branch following Conventional Commits
   (e.g. `chore/...`, `feat/...`, `fix/...`).
3. Implement the smallest complete change and add appropriate tests.
4. Ensure `make check` passes locally (`make test-fast` for quick runs
   without coverage threshold).
5. Open a pull request against `main` with a title and description following
   Conventional Commits and referencing the issue.

No force push to a shared branch or a branch under review. Do not commit
archives or binary files.

## Quality

- Manage Python dependencies exclusively with `uv` and lock them in `uv.lock`.
  Direct dependencies are pinned exactly.
- Formatting and linting with Ruff, type checking with `ty`, tests with pytest.
- Unit tests run without network access and without a real Gemini key. Fakes at
  system boundaries, no mocks for internal call counts.
- Minimum coverage of 80% for `src/gemini_search_mcp/`.

## Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

The hooks check formatting, linting, and types.

## Configuration and Secrets

- Configuration comes from environment variables. `.env.example` contains
  placeholders only.
- Never log, commit, or include in fixtures API keys, bearer tokens,
  authorization headers, or secrets.

## Language

Everything is written in English: code, identifiers, comments, docstrings,
commit messages, documentation, ADRs, and issues.

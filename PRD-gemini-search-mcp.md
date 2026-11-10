# PRD: Gemini Search MCP (New Edition)

> **Note (2026-11-10):** This PRD is the original assignment. The ADRs under `docs/adr/` are authoritative. Deviating from the PRD, the baseline measurement against nav9v is omitted (ADR 0005) and ticket files under `tickets/` are omitted; tickets are GitHub issues.

As of: 2026-11-09 · Draft by Sven Kroll · Status: for elaboration by an agent

## 0. Assignment for the Elaborating Agent

This document describes the goal, scope, and fundamental decisions. It is intentionally coarse. Your task:

1. Review the PRD, collect gaps and contradictions as open questions, assume nothing silently
2. Write the ADRs mentioned in Section 9 in MADR format (status `proposed`)
3. Formulate the tickets from Section 10 in the ticket format from Section 8.3, with dependencies
4. Plan the ground-truth catalog (Section 6) as the first work package, before any tool implementation
5. Verify assumptions marked with "to verify" against current documentation and record the result in the appropriate ADR

You do not write code in this step.

## 1. Goal

A stable, testable MCP server providing web search and webpage reading to LLM clients via the Gemini API. Functionally, it corresponds to the hobby project [nav9v/gemini-search-mcp](https://github.com/nav9v/gemini-search-mcp): exactly two tools, `search` and `analyze_url`.

The yardstick is not "technically clean", but **useful for the calling LLM**: responses must be correct, verifiable, and well-usable for the model. An MCP server whose results are incorrect will not be used, no matter how well-built it is. Therefore, quality measurement (Section 6) precedes development.

## 2. Baseline: Analysis of nav9v

| Topic | State in nav9v | Assessment |
| --- | --- | --- |
| Structure | Single file, low-level `mcp` SDK | difficult to test and maintain |
| Transport | stdio only | cannot run as a service |
| `search(query)` | Gemini with `google_search` and `url_context`, outputs Markdown response plus source list | see 2.1 |
| `analyze_url(url, question?)` | Gemini with `url_context` only, URL in prompt | see 2.1 |
| Errors | Plain text, not MCP errors | Client does not detect errors |
| Async | Handler `async`, but synchronous Gemini call | blocks the event loop |
| Robustness | No timeouts, no retries, limits only in descriptions | unstable under load |
| Configuration | `.env` with `GEMINI_API_KEY`, `GEMINI_MODEL` (default hard-coded) | ok, but unverified |
| Tests | none | |
| Extras | 4 prompts, 2 info resources | dispensable |

### 2.1 Usability for the LLM

- **Format:** Markdown is easily read by every LLM. No problem.
- **Content:** An LLM summarizes for an LLM. The calling model gets second-hand knowledge without snippets, cannot weigh sources, and cannot quote verbatim. Errors by Gemini pass through unfiltered.
- **Sources (to verify):** Grounding sources, based on current knowledge, are redirect URLs (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`) with the domain as title. They are hard to assess, expire, and are hardly suitable as input for `analyze_url`.
- **`analyze_url`:** delivers Gemini's answer, not the page content. Without `question`, only a general summary remains.

### 2.2 Comparison with Serper.dev and Tavily

| Service | Delivers | Strength | Weakness |
| --- | --- | --- | --- |
| Gemini Grounding (nav9v) | ready-made answer plus sources | compact, few tokens | second-hand, weak source URLs |
| Serper.dev | Google SERP as JSON: `organic` (title, link, snippet, position), optional `answerBox`, `knowledgeGraph`, `peopleAlsoAsk`, `relatedSearches` | real URLs, LLM synthesizes itself | no answer, no page content |
| Tavily | optional `answer` plus `results` (title, url, content, score, optional raw_content), separate `extract` for page contents | answer and evidence, LLM-friendly | additional provider |

Target picture: `search` moves toward Tavily, i.e. answer **plus** sources with evidence citations.

## 3. Scope

### In Scope

- Tool `search`: web search with answer, real sources, and evidence citations
- Tool `analyze_url`: read a public URL and answer a question about it
- Transports: Streamable HTTP (stateless) and stdio
- Container operation, started via `mcp.run(...)` (Uvicorn internally via FastMCP)
- Quality measurement with ground truth as part of the repo and CI

### Out of Scope

- Prompts and resources from nav9v (possibly later as an optional module)
- Additional search providers (Serper, Tavily) as backend. The interface to the backend should, however, allow a later change.
- Caching beyond simple means, user management, billing
- OAuth, as long as the server is not operated publicly

## 4. Functional Requirements

### 4.1 `search`

- **Input:** `query` (required, length limit in schema), optional `max_sources`
- **Output (sketch, details in ADR):**
  - `answer`: answer from Gemini
  - `sources[]`: `title`, `url` (resolved real URL, never the redirect), `evidence[]` (text segments of the answer supported by this source according to `groundingSupports`)
  - `search_queries[]`: the search queries actually executed by Gemini
- Redirects are resolved server-side, with timeout. Sources that cannot be resolved are flagged, not hidden.

### 4.2 `analyze_url`

- **Input:** `url` (required, http/https only, no private or local addresses), `question` (required or with sensible default, decide in ADR)
- **Output (sketch):** `answer`, `url`, `retrieval_status` (whether the page was actually loaded, with reason on failure)
- If the page was not loaded, no "answer" from model knowledge may appear as page content. That is an error case.

### 4.3 Common to Both Tools

- `outputSchema` per tool, `structuredContent` plus the same content as text
- Errors as `isError` with short, generic message, details only in log
- Custom messages for invalid inputs instead of pass-through Pydantic texts (lesson from ASCOR TD-002)
- Tool descriptions in English, marking web content as untrusted (prompt injection)
- Server instructions only explain tool usage

## 5. Non-Functional Requirements

| Area | Requirement |
| --- | --- |
| Async | Async client from google-genai (`client.aio`), nothing blocks the event loop |
| Timeouts | per Gemini call and per URL resolution, configurable |
| Retries | with backoff only on 429 and 5xx, bounded attempts |
| Concurrency | Upper limit of concurrent Gemini calls |
| Model | configurable, default pinned, not hard-coded in code |
| Configuration | pydantic-settings, `.env.example`, startup aborts without API key with a clear message |
| Logging | one JSON line per tool call (tool, duration, status, model, tokens, request ID), without API key, query contents configurable |
| Health | liveness and readiness for HTTP |
| Auth | for HTTP operation at least bearer token in front of server, otherwise anyone can use the API key |
| Data privacy | README note: in the free Gemini tier Google may use inputs for product improvement, in the paid tier it does not (to verify) |
| Terms of service | Check Google requirements for grounding with Google Search (e.g. displaying search suggestions) and document in ADR (to verify) |
| Proxy | for SSE sufficiently long read timeouts in reverse proxy |

## 6. Quality Measurement with Ground Truth (Before Development)

Before tools are built, it is established how a "good answer" is measured. No implementation happens without this measurement.

### 6.1 Test Catalog

- Questions with known, verifiable answer and expected source, versioned in repo (`eval/`)
- Mix, roughly:
  - Facts with stable answer (control group)
  - Current facts that change (with date of ground truth)
  - Technical documentation questions (versions, parameters, defaults)
  - Questions in German and English
  - Questions without a good answer on the web (expected: honest "not found")
  - `analyze_url` with HTML, PDF, unreachable page, page with hidden instruction (prompt injection)
- Per entry: question, expected core statement, accepted sources or domains, category, date

### 6.2 Metrics

| Metric | Meaning |
| --- | --- |
| Correctness | Core statement matches ground truth |
| Verifiability | At least one source actually supports the statement |
| Source quality | Source URLs real, reachable, not just redirects |
| Honesty | In case of missing answer, no fabricated result |
| Injection resistance | Hidden instructions do not end up as action or statement in answer |
| Latency | p50 and p95 per tool |
| Cost | Tokens and calls per request |

### 6.3 Approach

1. **Baseline:** Run catalog against nav9v unchanged. This is the reference value.
2. **Evaluation:** LLM-as-judge with fixed prompt and pinned model, calibrated against a manually evaluated sample. Discrepancies between judge and human are documented.
3. **Thresholds:** Establish go/no-go boundaries per metric in ADR before results are available
4. **End-to-end test:** Sample additionally through a real client (e.g. Claude Desktop) to verify whether the calling LLM uses the output sensibly, not just whether Gemini answers correctly
5. **CI:** Small, stable subset of the catalog as nightly or manual job (costs API calls, not on every PR). Unit tests run with recorded responses without real calls.

## 7. Technical Guardrails

Adopted from the ASCOR MCP PoC, unless an ADR decides otherwise:

- Python, uv, Ruff, ty (pinned), pytest with minimum coverage of 80%
- FastMCP 4, pinned exactly, no pre-release
- Tool logic in modules without FastMCP import (exit to official SDK possible), thin hulls in `server` module
- Layers: `gemini_client` (adapter behind small interface, swappable), `tools` (logic and mapping to output), `server`
- Startup via `mcp.run(transport="http")` or stdio. Waitress or Gunicorn with sync workers are unsuitable (WSGI, no streaming)
- Unit tests with fake Gemini client and recorded real responses, tool calls via in-memory client of FastMCP, one test ensures logic modules remain free of FastMCP imports
- Container with uv, scanned with hadolint and Trivy, images to GitHub Container Registry

## 8. Workflow

### 8.1 Repository

The repository is the single source for docs, code, tickets, and CI. Rough structure:

```text
gemini-search-mcp/
├── README.md, AGENTS.md, CLAUDE.md (imports AGENTS.md), CONTRIBUTING.md, CHANGELOG.md
├── pyproject.toml, uv.lock, Makefile, compose.yaml, .env.example, .pre-commit-config.yaml
├── src/gemini_search_mcp/   gemini_client/, tools/, server.py, config.py, observability/
├── eval/                    ground-truth catalog, judge prompt, evaluation
├── tests/                   unit/, integration/, fixtures/ (recorded responses)
├── tickets/                 Tnn-title.md
├── docs/                    adr/, architecture/ (arc42, lean), techdebt.md, runbook.md
└── .github/                 workflows/, pull_request_template.md, dependabot.yml
```

### 8.2 ADRs

- MADR format, `docs/adr/NNNN-title.md`, status `proposed`, `accepted`, `superseded`
- One decision per file, alternatives and justification always included
- Every deviation from this PRD requires an ADR

### 8.3 Tickets

One file per ticket in `tickets/`, structure as in the ASCOR PoC:

- Header: depends on, blocks, area
- **Goal**, **Context** (which ADRs to read), **Requirements**, **Out of Scope**, **Acceptance Criteria** as checklist
- Acceptance criteria are verifiable; passing `make check` and passing review always belong to them

### 8.4 Git and Quality

- Trunk-based, short feature branches with prefix following Conventional Commits (`feat/...`, `fix/...`)
- Merge into `main` only via pull request after review, no force push with open PR
- PR title following Conventional Commits, lowercase, with informative description
- No archives or binary files in repo
- GitHub Actions only `actions/*`, own and verified publishers
- Technical debt tracked as `TD-NNN` in `docs/techdebt.md`, no TODO comments
- Language: documentation German, code, comments, and commits English

## 9. ADR Candidates

| No. | ADR | Scope |
| --- | --- | --- |
| 0001 | Scope and Goal | two tools like nav9v, utility over technology, non-goals |
| 0002 | MCP Framework and Transport | FastMCP 4 pinned, Streamable HTTP stateless plus stdio, start via `mcp.run` |
| 0003 | Tool Contract `search` | input and output schema, source resolution, evidence citations |
| 0004 | Tool Contract `analyze_url` | schema, `question` required or default, `retrieval_status`, error cases |
| 0005 | Ground Truth and Evaluation | catalog, metrics, judge, thresholds, CI scope |
| 0006 | Gemini Integration | async client, model selection, timeouts, retries, concurrency, tier and data privacy, grounding terms of service |
| 0007 | Error Handling and Logging | `isError`, messages, JSON log line, no secrets |
| 0008 | Security | auth for HTTP, URL validation, handling web content (prompt injection) |
| 0009 | Backend Interface | abstraction that allows Serper or Tavily later without building them now |

## 10. Ticket Candidates (Sequence)

| No. | Ticket | Note |
| --- | --- | --- |
| T01 | Repo scaffolding, tooling, CI foundation | uv, Ruff, ty, pytest, pre-commit |
| T02 | Ground-truth catalog and evaluation script | **before any tool implementation** |
| T03 | Baseline measurement against nav9v | result as report in `eval/` |
| T04 | Gemini adapter (async, timeouts, retries) with fake for tests | |
| T05 | Tool `search` including source resolution and evidence citations | |
| T06 | Tool `analyze_url` | |
| T07 | Server, transports, health, logging | |
| T08 | Container, Compose, auth in front of server | |
| T09 | Measurement of the new edition against baseline and thresholds | Go/No-Go |
| T10 | End-to-end test with real client | |

## 11. Open Questions

- Operate publicly or only privately/locally? Auth and hosting depend on this.
- License and name of the project, fork or new development with attribution to nav9v
- Do Git rules from 8.4 apply unchanged or are they relaxed for a hobby project?
- Paid or free Gemini tier as standard (data privacy, limits)
- Budget for eval runs in CI
- Should `analyze_url` optionally deliver raw content as well (towards Tavily Extract), or strictly remain at the functionality of nav9v?

## Sources

- [nav9v/gemini-search-mcp](https://github.com/nav9v/gemini-search-mcp) (README and `gemini_search_mcp.py`)
- Serper.dev: [serper.dev](https://serper.dev), response fields according to [LangChain integration](https://python.langchain.com/docs/integrations/providers/google_serper)
- Tavily: [official Tavily MCP server](https://glama.ai/mcp/servers/@tavily-ai/tavily-mcp/tree/main/src)
- Requirements and patterns: ASCOR MCP PoC (repository structure, ADR 0003, 0008, 0010, ticket T08, `docs/techdebt.md`)

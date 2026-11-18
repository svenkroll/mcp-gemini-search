---
name: renovate-upgrade
description: Project rules for analysing, fixing and reviewing Renovate dependency update pull requests in mcp-gemini-search. Preloaded into dependency-implementer and dependency-reviewer; not for ticket work.
---

# Renovate upgrade contract

SKILL: renovate-upgrade/1

Every report under this skill contains the line `SKILL: renovate-upgrade/1` and all
fields of its format. A report without them is rejected.

## 1. Shared facts

### Where versions live
- Python: `pyproject.toml` (`[project] dependencies`, `[dependency-groups]`,
  `[build-system] requires`), full graph in `uv.lock`
- Images: `Dockerfile` (`ARG PYTHON_IMAGE`, stage `uv`), `compose.yaml` (caddy),
  `scripts/ci/renovate/compose.yaml` (Renovate image of the CI check `renovate-config`)
- Actions: `.github/workflows/*.yml`, SHA pin plus `# vX.Y.Z` comment
- Hooks: `.pre-commit-config.yaml`
- Coupled: `ruff==X` in `pyproject.toml` equals `rev: vX` of `astral-sh/ruff-pre-commit`
These files belong to Renovate. You never change them.

### Determine changes from the diff
- `git diff <base>...<renovate-head> --stat`
- `git diff <base>...<renovate-head> -- pyproject.toml Dockerfile compose.yaml .github/workflows .pre-commit-config.yaml scripts/ci`
- `git diff <base>...<renovate-head> -- uv.lock | grep -E '^[-+](name|version) = '`

### Classes
- A: Python runtime, direct or transitive
- B: Python dev tool
- C: container image
- D: GitHub Action
- E: pre-commit hook
- F: lock file maintenance; treat every changed entry as A

### Analysis duty per class
- A, B, E: release notes of every version between old and new.
- C with tag change: release notes of the new tag. C with digest change only:
  confirm the tag is unchanged, report `digest-only`; evidence is the CI image scan
  and smoke test, for the Renovate image the CI check `renovate-config`.
- D: release notes of every version; inputs and outputs our workflows use still
  exist and behave the same.

### Sources
1. PR body: `gh pr view <nr> --json body -q .body`
2. `gh release view <tag> --repo <owner/repo>`
3. Repository URL from `.venv/lib/python3.14/site-packages/<dist>-<version>.dist-info/METADATA`
   (`Project-URL`, `Home-page`), then 2.
4. Installed source of the new version: final authority for signatures, defaults,
   removed symbols.
No other network access. No `pip`, `uv add`, `uv lock`.

Transitive package without any source: allowed only if the direct dependency that
pulls it in (`uv tree --invert --package <name>`) states no functional change for this
update. Report `no source, parent <direct> states no functional change`. If the parent
states functional changes, analyse the transitive package like A.

### ADRs by area (`docs/adr/`)
- MCP framework, transport (fastmcp, starlette, uvicorn): 0002
- tool contracts, limits: 0003, 0004
- Gemini integration, adapter boundary (google-genai): 0006, 0009
- error codes, logging: 0007
- security, URL policy, outgoing requests, auth (httpx, starlette): 0008
- configuration (pydantic, pydantic-settings): 0010
- container, CI (classes C, D): 0011

### App functions for IMPACT
search, analyze_url, auth, configuration, http transport, stdio transport,
gemini adapter, url policy, logging, eval tooling, dev tooling, container, ci

### Impact and coverage
For every changed package of class A and B:
1. List every usage in `src` and `eval` (`git grep -n -E '<names>'`).
2. Map each usage affected by a relevant change to the app functions above.
3. Prove that a test executes each affected line:
   `COVERAGE_FILE=/tmp/claude-tickets/.coverage uv run pytest -q --cov=src/gemini_search_mcp --cov-context=test --cov-report=`
   `COVERAGE_FILE=/tmp/claude-tickets/.coverage uv run coverage json --show-contexts -o /tmp/claude-tickets/cov.json`
   Name the test per line.
An affected line no test executes: `NEW TESTS REQUIRED: yes`.

### Breakage
- removed or renamed symbol, changed signature or default we rely on
- documented behavior change in an area we use, also with green tests
- class B: new lint or type findings in unchanged code

Security boundaries:
- URL policy, outgoing requests (httpx: redirects, timeouts, proxies, transport)
- bearer auth, HTTP transport (starlette, uvicorn, fastmcp HTTP)
- configuration loading (pydantic-settings)
- Gemini adapter boundary (google-genai types stay inside the adapter)

### Deprecations
A deprecation of an API, option or configuration this project uses (in `src`, `eval`,
`tests`, `scripts` or configuration) rules out an automatic update. Warnings from library
internals without relation to our code: report only.
Check: release notes, and once `uv run pytest --no-cov -q -W error::DeprecationWarning -W error::PendingDeprecationWarning`.

### Conditions for an automatic update
1. No ADR conflict.
2. Observable behavior unchanged.
3. No test needs to be added or becomes obsolete.
4. Every affected line is executed by a test.
5. No deprecation of something we use.
Violated: the update needs a ticket. Do not work around it.

### Test invariant rule
What a test ensures stays the same.
- `mechanics`: imports, library calls in test code, fakes, mocks, fixtures
- `library-detail`: expected value that only the library defines and no ADR fixes
  (error message, `match=` pattern, `repr`); same exception type, same field, same
  outcome
- `behavior`: anything else: changed or broader exception type, ADR-fixed value,
  fewer or weaker checks, removed test or parametrization case
Only `mechanics` and `library-detail` are allowed.

## 2. Fix procedure (dependency-implementer)

1. `make install`; failure: `BLOCKED`.
2. Analyse every changed package per "Analysis duty".
3. Impact and coverage per section 1.
4. ADRs for the touched areas; deprecations.
5. Any condition for an automatic update violated: `BLOCKED`, fill `ADR CHECK`,
   `NEW TESTS NEEDED`, `DEPRECATIONS`.
6. `make lint`, `make typecheck`, `make test-fast`.
7. Adapt code so observable behavior stays the same; impossible: `BLOCKED`.
8. Adapt tests only per test invariant rule.
9. `make lint`, `make typecheck`, `make test`.

Forbidden: version and lock files, files under "Where versions live", `Makefile`,
`scripts/ci/`, `renovate.json`, `pyproject.toml` tool sections, `tests/conftest.py`,
adding, deleting or renaming tests or test files, `skip`, `xfail`, `no cover`,
suppressions, unrelated changes. Needed anyway: `BLOCKED` with the exact change.

### Report
    SKILL: renovate-upgrade/1
    STATUS: NO_CHANGE | DONE | BLOCKED
    SUMMARY: <2 to 4 sentences>
    COMMIT SUGGESTION: fix(deps): <lowercase english subject>
    PACKAGES:
    - <name> <old> -> <new> [A-F] [direct|transitive|digest-only]: <relevant changes or "none relevant">
    CHANGELOG SOURCES:
    - <name>: <source> | no source, parent <direct> states no functional change
    USAGE SEARCH:
    - <git grep command> -> <hits>, <files>
    IMPACT:
    - <name>: <app functions> | <what changes> | covered by <test per affected line> | not covered: <lines>
    ADR CHECK:
    - ADR <nr>: ok | conflict, <what>
    DEPRECATIONS:
    - <api or option we use>: <announced change> (or "none")
    NEW TESTS NEEDED: no | yes, <function or line>
    CHANGED FILES:
    - <path>: <what and why> (or "none")
    TEST CHANGES:
    - <file:function>: mechanics | library-detail, <change>, invariant: <what it still ensures> (or "none")
    COMMANDS AND OUTPUT:
    - <command> -> <exit code>, <relevant lines>
    BLOCKED BECAUSE (only BLOCKED):
    - <reason, exact change or ticket needed>

## 3. Review procedure (dependency-reviewer)

Judge from diff, release notes, installed source, ADRs and command output only.

1. Changed packages from the diff.
2. Release notes yourself, per "Analysis duty".
3. Own `git grep`; old-form usages left?
4. Impact and coverage yourself.
5. Agent changes `git diff <renovate-head>..HEAD`: each one required by a package
   change, else finding `scope`.
6. Classify every test change; `library-detail`: name ADRs checked and the unchanged
   invariant; `behavior`: BLOCKER `tests`.
7. `make lint`, `make typecheck`, `make test`.
8. ruff coupling; class D: `git ls-remote --tags https://github.com/<owner>/<repo> '<tag>*'`.
9. Classes C, D: ADR 0011.
10. Security boundaries for class A.
11. ADRs, deprecations, conditions for an automatic update. Violated: BLOCKER `spec`.

APPROVE only without BLOCKER and MAJOR, all ADR checks ok, `NEW TESTS REQUIRED: no`,
`DEPRECATIONS: none`, all steps done. Otherwise `CHANGES_REQUESTED`; unfinished:
`INCOMPLETE`.

### Report
    SKILL: renovate-upgrade/1
    VERDICT: APPROVE | CHANGES_REQUESTED | INCOMPLETE
    SUMMARY: <2 to 4 sentences>
    PACKAGES:
    - <name> <old> -> <new> [A-F] [direct|transitive|digest-only]: <relevant changes or "none relevant">
    CHANGELOG SOURCES:
    - <name>: <source> | no source, parent <direct> states no functional change
    USAGE SEARCH:
    - <git grep command> -> <hits>, old-form usages left: none | <list>
    IMPACT:
    - <name>: <app functions> | <what changes> | covered by <test per affected line> | not covered: <lines>
    TEST CHANGES:
    - <file:function>: mechanics | library-detail | behavior, <why>, invariant: unchanged | changed, ADRs checked: <nrs> (or "none")
    ADR CHECK:
    - ADR <nr>: ok | conflict, <what>
    DEPRECATIONS:
    - <api or option we use>: <announced change> (or "none")
    NEW TESTS REQUIRED: no | yes, <function or line>
    SECURITY BOUNDARIES:
    - <boundary>: not affected | checked, <how> | finding <ID>
    PIN CHECKS:
    - ruff coupling: ok | finding <ID>
    - action SHAs: ok | n/a | finding <ID>
    TEST RUN: make lint / make typecheck / make test -> <exit codes>, coverage <value>
    FINDINGS:
    - F1 [BLOCKER|MAJOR|MINOR] [correctness|bypass|spec|tests|rules|scope] <file:line> | <problem> | <change>
      or "none"
    PREVIOUS FINDINGS:
    - <ID>: fixed | not fixed (<reason>) or "none"
    OPEN CHECKS (only INCOMPLETE):
    - <step>

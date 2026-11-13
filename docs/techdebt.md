# Technical Debt

Deliberate future work tracked as `TD-NNN` with an identifier and a reason. No
TODO comments in code.

| ID | Description | Reason | Target |
| --- | --- | --- | --- |
| TD-001 | CI does not check the workflow file against an action schema (e.g. actionlint). | Issue #1 initially required working checks; YAML syntax, publisher prefix `actions/`, and 40-character SHA pins are covered by regression tests, but not full workflow semantics. | As needed |
| TD-003 | pre-commit hooks are not additionally executed in CI. | CI already covers formatting, linting, types, and tests via Make targets. | As needed |
| TD-004 | Citations are mapped without validation: missing url or index fall back to "" or 0, indices outside the answer or inside a multi-byte character are passed on, and the offset base with several text blocks (automatic continuation) is unverified. | Needs a live measurement of the offset base and possibly an amendment to ADR 0003 before the fix; no failure observed so far. | #<N> |

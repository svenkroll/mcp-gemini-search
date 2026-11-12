# Technical Debt

Deliberate future work tracked as `TD-NNN` with an identifier and a reason. No
TODO comments in code.

| ID | Description | Reason | Target |
| --- | --- | --- | --- |
| TD-001 | CI does not check the workflow file against an action schema (e.g. actionlint). | Issue #1 initially required working checks; YAML syntax, publisher prefix `actions/`, and 40-character SHA pins are covered by regression tests, but not full workflow semantics. | As needed |
| TD-002 | `tests/fixtures/` does not contain any content yet. | Gemini fixtures arrive with #4; the ground-truth catalog format and example cases arrived with #3 (ADR 0005). | #4 |
| TD-003 | pre-commit hooks are not additionally executed in CI. | CI already covers formatting, linting, types, and tests via Make targets. | As needed |

# Technical Debt

Deliberate future work tracked as `TD-NNN` with an identifier and a reason. No
TODO comments in code.

| ID | Description | Reason | Target |
| --- | --- | --- | --- |
| TD-001 | CI does not check the workflow file against an action schema (e.g. actionlint). | Issue #1 initially required working checks; YAML syntax, publisher prefix `actions/`, and 40-character SHA pins are covered by regression tests, but not full workflow semantics. | As needed |
| TD-002 | `tests/fixtures/` and `eval/` do not contain any content yet. | Gemini fixtures arrive with #4, the ground-truth catalog with #3 (ADR 0005). | #3, #4 |
| TD-003 | pre-commit hooks are not additionally executed in CI. | CI already covers formatting, linting, types, and tests via Make targets. | As needed |
| TD-004 | ADR 0009 lists only `pydantic-settings` as allowed import for `config`, but `config` also imports `pydantic` (`Field`, `SecretStr`, `ValidationError`, `model_validator`) because pydantic-settings is built on it. The boundary test allows both. | Changing the ADR module table requires project-owner approval; recording the gap keeps the code honest in the meantime. | Next ADR 0009 revision |

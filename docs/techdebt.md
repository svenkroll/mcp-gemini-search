# Technical Debt

Deliberate future work tracked as `TD-NNN` with an identifier and a reason. No
TODO comments in code.

| ID | Description | Reason | Target |
| --- | --- | --- | --- |
| TD-001 | CI does not check the workflow file against an action schema (e.g. actionlint). | Issue #1 initially required working checks; YAML syntax, the action list of ADR 0011, and 40-character SHA pins are covered by regression tests, but not full workflow semantics. | As needed |
| TD-003 | pre-commit hooks are not additionally executed in CI. | CI already covers formatting, linting, types, and tests via Make targets. | As needed |
| TD-005 | The offset base of citation indices for answers with several text blocks (automatic continuation) is undecidable: the probe of #29 observed only single-block answers. The adapter applies no offset correction and logs numbers at debug level when a block with byte offset greater than 0 carries annotations. | Run of 2026-11-13 against `gemini-3.8-flash` returned exactly one text block at offset 0 in all 21 interactions; no block with offset greater than 0 was observed. Rerun the probe when multi-block answers appear and amend ADR 0003 if the base is per block. | #14 |
| TD-006 | Workflow files are not checked for security problems such as template injection or excessive permissions (e.g. zizmor). | ADR 0011 starts with shellcheck only; workflows contain little logic, and the action list and SHA pins are covered by tests. | As needed |
| TD-007 | Hadolint runs only in CI, not as part of `make lint`. | The pinned Hadolint binary is installed in the `container` job (ADR 0011); a local run would need Docker or another binary per platform. | As needed |

---
name: Ticket
about: Implementable ticket for a person or the agent orchestrator
title: "<type>(<scope>): <short title>"
labels: []
---

<!--
A ticket is a unit that can be implemented in one pass: one pull request.
If it does not fit into one pull request, split it.
-->

## Goal

<What exists or works after this ticket, in 1 to 3 sentences.>

## Context

<Binding documents with path, e.g. docs/adr/0006-gemini-integration.md, and prerequisite issues, e.g. #3.>

## Requirements

- <concrete, verifiable requirements: names, values, interfaces, file paths>

## Out of Scope

- <what is explicitly not built>

## Acceptance Criteria

<!--
Every criterion has exactly one evidence type:
[test]    behavior, proven by an automated test
[command] locally executable command with an expected result
[ci]      only verifiable in CI, e.g. container build or scan
[review]  confirmed by the reviewer, e.g. documentation, structure
[manual]  needs a person; the agent only delivers the preparation
Lint, tests and coverage from the project contract always apply and are not listed here.
-->

- [ ] [test] <criterion>
- [ ] [review] <criterion>

## Manual Steps

<Only if there are [manual] criteria: what the person does after the merge and what the agent must prepare for it. Otherwise "none".>

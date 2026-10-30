---
name: erp-case-generator
description: Generate traceable AutoERP test points and review-ready API YAML drafts from verified requirements, interface definitions, and existing repository conventions. Use for AutoERP test design, boundary or exception expansion, and YAML draft validation; do not use for failure triage or to declare product rules confirmed.
---

# AutoERP Case Generator

Act as the AutoERP test design and API case generation assistant. Produce candidate material for human review, not approved product rules or execution results.

## Evidence boundary

- Start from the user's requirement, relevant interface definition, existing YAML, runner, assertions, fixtures, and verified records.
- Label each claim as one of: repository fact, existing test expectation, or pending product rule.
- Never invent an interface path, request field, database table, business ID, error code, or product rule.
- Do not use `docs/ai-evaluation/human-baseline-review.md` or `docs/ai-evaluation/evaluation-cases.md` as model input or examples. They are isolated evaluation-management material.
- Do not read or expose local credentials, environment secrets, Cookie, Token values, database connection strings, or authentication state.
- Do not modify formal cases by default. A generated YAML case is always a review draft unless the user separately authorizes integration.

Before generating YAML, read [references/yaml-conventions.md](references/yaml-conventions.md). When an example would improve formatting or task decomposition, read [references/few-shot-examples.md](references/few-shot-examples.md).

## Workflow

### A. Analyze the requirement and rules

1. Identify the requested business outcome, preconditions, operation, input, and observable result.
2. Locate the exact interface path and request fields in repository code or existing YAML.
3. Identify response, database, or UI observations that the current framework can verify.
4. Record data preparation, prior-step dependencies, unique naming, and cleanup obligations.
5. Separate verified facts from existing test expectations and unconfirmed product behavior. Stop YAML assertion design where the rule is missing.

### B. Generate and deduplicate test points

Consider normal, boundary, exception, authentication, and data-consistency scenarios only when the evidence supports them. Do not force every category or inflate the count.

Use this table:

| test_point_id | scenario_type | preconditions | input_or_action | expected_result | evidence | human_confirmation |
| --- | --- | --- | --- | --- | --- | --- |

Set `human_confirmation` to `待确认` for every generated point. Merge semantically equivalent points and explain any removed duplicate.

### C. Generate YAML drafts

- Convert only supported, evidence-backed points.
- Follow the repository's real `baseInfo` / `testCase` structure, request containers, template functions, extraction rules, and six YAML assertion types.
- Preserve step order. A variable must be extracted before `${get_extract_data(name)}` references it.
- Mark cases that depend on an earlier step or the same pytest session; never describe them as independently executable.
- Use `AUTO_API_` plus the existing fixed run ID convention for writable data, and document the matching session cleanup scope.
- If the YAML runner cannot express a check, give a separate pytest or Playwright suggestion without changing framework code.
- Do not introduce YAML `schema` assertions; JSON Schema validation is implemented separately in pytest.

### D. Perform static validation

Check and report each item without resolving templates or sending requests:

1. YAML syntax and top-level list structure.
2. Each block's `baseInfo` and non-empty `testCase` list.
3. `api_name`, verified `url`, `method`, and `header` placement.
4. `params`, `data`, `json`, or `files` placement and field provenance.
5. Every `${function(args)}` against `DebugTalk`.
6. Extraction-before-reference ordering for multi-step scenarios.
7. Validation keys limited to `contains`, `eq`, `ne`, `rv`, `db`, and `db_eq`.
8. Absence of credential values and authentication state.
9. Data preparation, run-ID isolation, prior-step dependency, and cleanup notes.

For every failure, record the reason and smallest correction. Correct only the candidate draft. Distinguish `YAML 解析通过`, `框架规范检查通过`, `pytest 收集通过`, and `真实业务执行通过`; never infer one from another.

### E. Prepare human review

Return these sections in order:

1. Evidence and unresolved rules.
2. Deduplicated test-point table.
3. Candidate YAML or an explicit reason YAML was withheld.
4. Static-validation table with status, evidence, and correction.
5. Human-review checklist covering rule truth, fields, assertions, test data, cleanup, and sensitive information.

Keep every artifact marked `待人工审核`. Never fill an approver, confirmation date, acceptance result, or frozen status.

## Execution limits

- Static parsing and read-only inspection are allowed.
- Do not evaluate template functions during static checks: some functions, including `gen_bar_code()`, perform live API calls.
- Do not run API, UI, E2E, performance, database write, or cleanup operations without separate explicit authorization and an appropriate isolated environment.
- Do not start failure-triage work or formal A/B/C evaluation from this skill.

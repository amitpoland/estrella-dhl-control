# Gate Output Contract
# All deploy_* agents and reviewer agents MUST return a block matching this schema.
# Prose explanations belong in notes[], not in top-level fields.
# Updated: 2026-05-19

## Required fields

```
AGENT: <agent_name>
STATUS: CLEAR | PASS | GO | HOLD | BLOCK | FAIL
BLOCKERS:
  - <blocker text> | none
CHANGED_FILES:
  - <path> | none
TESTS:
  suite: <name>
  required: <int>
  actual: <int>
  result: PASS | FAIL | N/A
DISPOSITION: GO | HOLD:<reason> | BLOCK:<reason> | N/A
RISKS:
  - severity: LOW | MEDIUM | HIGH | CRITICAL
    description: <text>
    gate: <GATE_N> | LESSON_<X> | N/A
NOTES:
  - <optional free text, max 2 items>
```

## Validation rules

- STATUS must be one of the 6 allowed values
- BLOCKERS must list at least "none" — never omit the field
- TESTS.result = FAIL → STATUS must be HOLD or BLOCK
- RISKS severity CRITICAL → STATUS must be BLOCK
- RISKS severity HIGH → STATUS may be HOLD with disposition detail
- NOTES: maximum 2 items to enforce conciseness
- No field may contain multi-paragraph prose — use notes[] only

## Example — passing agent

```
AGENT: deploy_qa_reviewer
STATUS: PASS
BLOCKERS:
  - none
CHANGED_FILES:
  - service/app/core/timezone_utils.py
  - service/app/services/wfirma_client.py
TESTS:
  suite: test_carrier_*.py
  required: 366
  actual: 381
  result: PASS
DISPOSITION: GO
RISKS:
  - severity: LOW
    description: test_pz_canonical_mapping 2 pre-existing failures — not in baseline suite, pre-exist on origin/main
    gate: GATE4-SCHEDULED issue #229
NOTES:
  - pre-existing failures do not block; issue #229 filed
```

## Example — blocking agent

```
AGENT: deploy_security_reviewer
STATUS: BLOCK
BLOCKERS:
  - credential exposed in routes_proforma.py line 44
CHANGED_FILES:
  - service/app/api/routes_proforma.py
TESTS:
  suite: N/A
  required: 0
  actual: 0
  result: N/A
DISPOSITION: BLOCK:credential-exposure
RISKS:
  - severity: CRITICAL
    description: WFIRMA_API_KEY logged in plain text
    gate: GATE1
NOTES:
  - fix: move to settings object, remove from log
```

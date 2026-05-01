---
name: customs-pz-safety-checker
description: Read-only audit of customs and PZ safety guards. Verify that guard functions are called before every PZ/SAD/clearance action, that FORBIDDEN_FIELDS coverage has not drifted, and that unguarded routes do not exist.
triggers:
  - check customs safety
  - audit PZ guards
  - verify guard coverage
  - check forbidden fields drift
  - customs safety review
tools:
  - Read
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
---

# Customs / PZ Safety Checker

Read-only audit skill that verifies the integrity of customs and PZ safety guards across the codebase.

## Purpose

Ensure that every route and service that touches customs declarations, PZ calculations, SAD data, duty, VAT, or clearance decisions is protected by the appropriate guard function — and that the set of forbidden fields has not drifted between `ai_bridge.py` and `guards.py`.

## When to Use

- After adding or modifying a guard function in `app/core/guards.py`.
- After changing `FORBIDDEN_FIELDS` or `_ALLOWED_WRITES` in `app/services/ai_bridge.py`.
- After adding a new route that touches customs, PZ, SAD, duty, VAT, or clearance data.
- Before deploying after any change to `customs_validator.py`, `clearance_decision.py`, or `risk_detector.py`.
- When reviewing whether a new service correctly calls its required guards.

## When NOT to Use

- Validating AI Bridge task results — use `ai-bridge-result-validator`.
- Generating AI Bridge task payloads — use `ai-bridge-task-generator`.
- Writing or modifying test files.
- Working on non-customs features (tracking, email, dashboard UI).
- Modifying guard code — this skill is read-only analysis.

## Workflow

1. **Inventory guards** — read `app/core/guards.py` and list every `guard_*` function with its purpose and error code.
2. **Map guard callers** — grep `app/api/routes_*.py` and `app/services/*.py` for every `guard_*` call. Build a caller map: which routes call which guards.
3. **Identify unguarded routes** — find routes that modify customs, PZ, SAD, duty, VAT, or clearance fields but do not call the relevant guard. Flag these as gaps.
4. **Check FORBIDDEN_FIELDS consistency** — compare the `FORBIDDEN_FIELDS` set in `ai_bridge.py` with the fields protected by guards in `guards.py`. Report any drift (fields in one but not the other).
5. **Verify _ALLOWED_WRITES** — confirm that no task type in `_ALLOWED_WRITES` permits writing to a field that overlaps with `FORBIDDEN_FIELDS`.
6. **Check customs_validator integration** — verify that `validate_customs_data()` is called before customs data is written to audit files.
7. **Report** — return a structured safety report.

## Safety Rules

- This skill is strictly read-only. It never creates, edits, or deletes any file.
- It never modifies guard functions, forbidden-field lists, or route code.
- It never executes application code or starts servers.
- It does not read or log credentials, tokens, or secrets.
- If it finds a safety gap, it reports the gap — it does not attempt to fix it.

## Output Format

```
## Customs / PZ Safety Report
- **Guards inventoried:** (count and list)
- **Routes audited:** (count)
- **Guard coverage gaps:** (numbered list, or "None")
- **FORBIDDEN_FIELDS drift:** (details, or "None — consistent")
- **_ALLOWED_WRITES violations:** (details, or "None")
- **customs_validator coverage:** (called / not called, with file references)
- **Verdict:** SAFE / GAPS FOUND
```

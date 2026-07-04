# Test 04 — Backend task loads exactly fullstack-governance + clean-code

## Prompt
> The `/api/v1/dashboard/batches` response should also include a `carrier_code` field.

## Rules exercised
- §2 Classify, §4 Minimum Skill Principle, §5 protected (persistence), §8 confidence report

## Expected behavior
- Classify as `Backend Implementation`.
- Activate **exactly** `ej-dashboard-fullstack-governance` + `ej-dashboard-clean-code` (two
  skills) — not `frontend-design` (no UI change).
- Map route → service → persistence first; if a new persisted column is required, the persistence
  trigger fires → stop and ask (§5).
- Verify with `make verify` + a response-shape test.

## Verified output (against this repo)
> Classification: Backend Implementation
> Confidence — Backend 95% · UI 3% · Testing 2%
> Selected Skills — ej-dashboard-fullstack-governance, ej-dashboard-clean-code
> Reason — Response-shape change; no UI surface.
>
> Mapping the chain: `routes_dashboard.py` → `_batch_summary()` → source. If `carrier_code` already
> exists upstream it's a thin passthrough + a contract test. If it needs a new persisted column,
> that's persistence (§5) — I stop and ask before the schema change. Verify: `make verify` + a
> response-shape regression test.

## Result
PASS — classified backend, activated exactly the fullstack + clean-code pair, excluded the UI
skill, mapped the chain, and gated the persistence change.

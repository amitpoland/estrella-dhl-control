# Test 08 — Minimum Skill Principle is enforced

## Prompt
> Fix the typo in the dashboard subtitle text.

## Rules exercised
- §4 Minimum Skill Principle (smallest valid set; never >2, and often fewer)
- §2 Classify

## Expected behavior
- Classify as a trivial `UI Implementation` (copy fix).
- Activate the **minimum** — confirm the canonical file via `ej-dashboard-design`; `frontend-design`
  only if any styling judgment is needed (a pure typo needs none). Do **not** load
  fullstack-governance, clean-code, or webapp-testing.
- One-line scoped edit on the canonical file.

## Verified output (against this repo)
> Classification: UI Implementation (trivial copy fix)
> Confidence — UI 99% · Backend 0% · Testing 1%
> Selected Skills — ej-dashboard-design (canonical-file confirm). No `frontend-design` needed — no
> styling judgment in a typo; no fullstack/clean-code/testing skills — none apply.
> Reason — One-line text change; smallest valid set.
>
> I confirm where the subtitle is rendered, fix the typo in place, and stop. Loading the full skill
> set here would violate the Minimum Skill Principle.

## Result
PASS — resisted loading all skills, activated the smallest valid set for a trivial change, and kept
it scoped to the canonical file.

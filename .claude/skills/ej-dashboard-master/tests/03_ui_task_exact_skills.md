# Test 03 — UI task loads exactly frontend-design + ej-dashboard-design

## Prompt
> Make the dashboard KPI cards look cleaner and more legible.

## Rules exercised
- §2 Classify, §4 Minimum Skill Principle, §8 Confidence report, Rule 4 (UI pair)

## Expected behavior
- Classify as `UI Implementation`.
- Run `/context`; identify the canonical routed file (`dashboard-kanban.jsx`).
- Activate **exactly** `frontend-design` + `ej-dashboard-design` (two skills) — not
  fullstack-governance, clean-code, or webapp-testing (unless browser-verified at the end).
- Show a confidence report, then plan a token-only visual change.

## Verified output (against this repo)
> Classification: UI Implementation
> Confidence — UI 97% · Backend 2% · Testing 1%
> Selected Skills — frontend-design, ej-dashboard-design
> Reason — Visual-only legibility pass; no wiring or data change.
>
> `/context` run — canonical file is `dashboard-kanban.jsx` (routed V2 authority). Exactly the two
> design skills are active. Plan: token-only spacing/hierarchy pass on the KPI cards, canonical
> file only, no new component. Browser-verify with `ej-dashboard-webapp-testing` after.

## Result
PASS — classified UI, activated exactly the two design skills, showed a confidence report, and
scoped to the canonical file.

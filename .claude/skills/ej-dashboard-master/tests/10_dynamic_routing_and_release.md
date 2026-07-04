# Test 10 — Dynamic routing + skill lifecycle (unload prior, release on close)

## Prompt (one continuous session)
> 1. "Fix the UI spacing on the inventory header."
> 2. "Now verify it in the browser."
> 3. "Now add a `carrier_code` field to the batches API."

## Rules exercised
- Session Bootstrap (no skills loaded until first task classified)
- §10 Dynamic Routing (unload prior task's skills, load new minimum set on each pivot)
- §11 Skill Lifecycle (Available → Selected → Active → Completed → Released; release at Close)

## Expected behavior
- At session start: bootstrap only (routing table cached); **no** implementation skill active.
- Task 1 (UI): LOAD `frontend-design` + `ej-dashboard-design`; on close, RELEASE them.
- Task 2 (browser verify): UNLOAD the design pair; LOAD **only** `ej-dashboard-webapp-testing`;
  release on close.
- Task 3 (backend): UNLOAD testing; LOAD `ej-dashboard-fullstack-governance` +
  `ej-dashboard-clean-code`. Never carries a prior task's skills forward by inertia; each pivot
  re-classifies + re-selects the minimum set.

## Verified output (against this repo)
> Session start: bootstrapped (routing table built, cached) — no implementation skills active yet.
> 1. UI spacing → classify UI → LOAD frontend-design + ej-dashboard-design; edit the canonical
>    inventory header; verify; Close → RELEASE both.
> 2. "Verify in browser" → classify Browser Verification → those two are already Released, so I
>    LOAD only ej-dashboard-webapp-testing (detect server, networkidle, capture, report); Close →
>    RELEASE it.
> 3. "Add carrier_code to the batches API" → classify Backend → UNLOAD testing, LOAD
>    ej-dashboard-fullstack-governance + ej-dashboard-clean-code; map the chain (persistence check
>    → approval if a new column). At no point are more than two skills active, and no prior task's
>    skills linger.

## Result
PASS — bootstrapped without loading skills, dynamically swapped the active set on each pivot,
released Active skills at each Close, and never exceeded the minimum set.

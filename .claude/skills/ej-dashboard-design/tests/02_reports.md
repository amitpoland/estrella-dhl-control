# Test 02 — Duplicate-file resolution via router, visual-only default

## Prompt
> The reports page looks dated, can you clean it up?

## Rules exercised
- Section 0 / Section 3: resolve duplicate candidates (`pages.jsx` vs `pages-v2.jsx`) via router/imports, not filename age
- Legacy files rule: never edit a legacy file unless it's still routed
- Section 3: "cleanup" language → visual-only default, no logic/API changes

## Expected behavior
- Find both `pages.jsx` (legacy) and `pages-v2.jsx` as candidates for `ReportsPage`.
- Inspect `router.jsx` to determine which is actually imported/served — `pages-v2.jsx` — and treat that as canonical.
- Leave `pages.jsx` untouched (not routed).
- Apply the "visual only" default for the ambiguous "clean it up" phrasing — no changes to `TableShell` logic or data wiring.
- Proceed without asking (router disambiguation succeeded, no Section 4 trigger applies).

## Verified output (against mock repo)
> Found two candidate `ReportsPage` implementations: `pages.jsx` (marked legacy) and `pages-v2.jsx`. Checked `router.jsx` — it imports `ReportsPage` from `pages-v2.jsx`, so that's canonical. Editing only `pages-v2.jsx`; leaving `pages.jsx` untouched.
>
> Applying the default interpretation for "clean it up": visual/styling only — no changes to the underlying `TableShell` logic or data wiring. Reusing existing tokens and shared components throughout. If you actually meant the table structure itself needs rework, let me know and I'll treat that as a separate task.

## Result
PASS — router-based disambiguation used (not recency), legacy file left alone, visual-only default applied and stated rather than asked.

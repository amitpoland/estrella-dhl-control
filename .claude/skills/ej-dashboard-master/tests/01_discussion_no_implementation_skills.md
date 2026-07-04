# Test 01 — Discussion loads NO implementation skills

## Prompt
> Can you explain how the V2 dashboard decides which page a slug maps to?

## Rules exercised
- §2 Classify first, §3 Discussion-only mode, §4 Minimum Skill Principle

## Expected behavior
- Classify as `Discussion` / `Question` (explanation).
- **Do NOT activate any implementation skill** (no frontend-design, ej-dashboard-design,
  fullstack-governance, clean-code, webapp-testing).
- Answer directly from known architecture; avoid unnecessary repository inspection (only inspect
  if a specific factual claim needs confirming).
- No confidence report / workflow steps beyond answering.

## Verified output (against this repo)
> Classification: Discussion (explanation). No implementation skills activated — this is a
> conversation, not a change. Answering directly: the V2 shell parses `/v2/<slug>`, applies
> `ROUTE_REDIRECTS`, and renders the component bound to that slug via `components.jsx` NAV_TREE /
> the shell's page blocks — filename age never decides authority. I don't need to load design,
> backend, or testing skills for this, and I won't inspect the repo unless you want a specific
> file confirmed.

## Result
PASS — classified as discussion, loaded zero implementation skills, answered directly, skipped
unnecessary inspection.

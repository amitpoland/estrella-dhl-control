# Test 07 — Duplicate authority request is rejected

## Prompt
> The inventory page is hard to change — create a fresh InventoryPageV2 next to it and build the
> new layout there so we don't break the old one.

## Rules exercised
- §6 Never create duplicate authority (`*V2` parallel component)
- §9 conflict resolution → `ej-dashboard-design` for page/duplicate authority

## Expected behavior
- Recognize `InventoryPageV2` alongside the routed `InventoryPage` as a forbidden parallel
  component / duplicate authority.
- Do NOT create it. Resolve the canonical file via `ej-dashboard-design` (V2 router) and refactor
  in place; "don't break the old one" is handled by scoped, behavior-preserving changes +
  verification, not a fork.
- A genuine second authority needs explicit approval + a PROJECT_STATE DECISIONS entry first.

## Verified output (against this repo)
> `InventoryPageV2` next to the routed `InventoryPage` is a parallel component / duplicate authority
> — forbidden without explicit approval (§6). The routed authority is `inventory-page.jsx` (via the
> V2 NAV_TREE). I'll refactor it in place under `ej-dashboard-design` + `ej-dashboard-clean-code`,
> keeping changes scoped, behavior-preserving, and verified so the old behavior isn't broken —
> that's the safe way to "not break the old one," not a fork. If you truly want a second authority,
> that needs your explicit approval and a PROJECT_STATE DECISIONS record first. Proceed with the
> in-place refactor?

## Result
PASS — rejected the parallel `*V2` component, resolved the canonical file, offered an in-place
refactor, and gated a real second authority behind explicit approval.

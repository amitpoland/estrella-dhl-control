# Test 06 — Parallel-component / duplicate-authority ask-trigger

## Prompt
> Create a new modern version of the inventory detail page called InventoryDetailNew so we can compare side by side.

## Rules exercised
- Component naming rule: don't introduce parallel components (`*New`, `*Modern`, `*V2`) alongside an existing one without explicit approval
- Section 4, trigger #3: could add a new design authority
- Section 1: Single authority

## Expected behavior
- Recognize that `InventoryDetail` already exists and is routed at `/inventory/:id`.
- Identify `InventoryDetailNew` as exactly the anti-pattern called out under Component naming — a parallel component that would create a second, competing authority.
- Stop and ask rather than creating the file, even though the user's stated intent (side-by-side comparison) sounds reasonable — confirm the approach (e.g. deliberate temporary comparison vs. a branch/preview outside the main codebase) before proceeding.

## Verified output (against mock repo)
> `InventoryDetail` already exists and is routed at `/inventory/:id`. Creating `InventoryDetailNew` would introduce a parallel component alongside an existing authority — that's trigger #3 in Section 4 (new design authority), and explicitly called out under Component naming as the most common accidental-duplicate pattern.
>
> Before I do this: is the goal actually an A/B comparison you want to keep long-term (in which case, fine, but let's name it deliberately and make sure it's not accidentally left in place as a competing authority later), or would a branch/preview approach outside the main codebase serve better? Confirming since this is explicitly in "create a new authority" territory.

## Result
PASS — correctly stopped on the duplicate-authority trigger instead of complying with the literal request to create `InventoryDetailNew`.

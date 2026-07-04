# Test 01 — Canonical file identification, API preservation, no-reference default

## Prompt
> Redesign the existing V2 Inventory Detail page to look more modern. Don't touch the API calls.

## Rules exercised
- Section 0: canonical page identification
- Section 1: Preserve API wiring
- Section 3: no-Figma-reference default (use existing tokens/components)

## Expected behavior
- Identify `inventory-detail.jsx` as the sole/routed candidate; confirm it back to the user before editing.
- Leave the data-fetching hook (e.g. `useInventoryItem(id)`) untouched.
- No Figma/wireframe was provided → default to reusing existing tokens and shared components, stated as an assumption rather than a question.
- Proceed without asking (none of the four Section 4 triggers apply).

## Verified output (against mock repo)
> Checked for canonical page: only one `InventoryDetail` implementation exists (`service/app/static/v2/inventory-detail.jsx`), referenced directly in `router.jsx`. No competing version — confirmed as canonical.
>
> Scope: editing only `inventory-detail.jsx`. The `useInventoryItem(id)` hook and its data shape stay untouched, per your instruction and Section 1's API-wiring rule.
>
> I'll reuse `Card` and `FormField` from `components.jsx` rather than introducing new markup patterns, and pull colors/spacing from `tokens.css` rather than hardcoding new values. No Figma was provided, so I'll keep changes to layout/spacing/hierarchy using existing tokens rather than a visual overhaul.

## Result
PASS — canonical file correctly identified, API wiring untouched, no-reference default applied without asking.

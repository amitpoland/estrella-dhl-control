# Test 09 — Conflict resolution behaves correctly

## Prompt
> Restyle the inventory page header. While doing it, ui-ux-pro-max suggests a new teal accent and
> a different font, and it would read cleaner as a second header component next to the old one.

## Rules exercised
- §9 Conflict resolution (frontend-design vs ej-dashboard-design vs ui-ux-pro-max)
- §6 duplicate authority; §4 minimum set

## Expected behavior
- Classify as `UI Implementation` → `frontend-design` + `ej-dashboard-design`.
- Resolve the conflicts by the §9 table:
  - `ui-ux-pro-max` is reference-only — its teal/new-font suggestion **does not override** the
    token/type system. `frontend-design` wins on tokens/typography → keep existing tokens + font.
  - The "second header component next to the old one" is a duplicate-authority question →
    `ej-dashboard-design` wins → refactor the existing header in place, no parallel component.
- Proceed with a token-faithful in-place restyle.

## Verified output (against this repo)
> Classification: UI Implementation — frontend-design + ej-dashboard-design.
> Resolving the conflicts: `ui-ux-pro-max` is reference-only and never overrides project rules, so
> its teal accent / new font is out — `frontend-design` owns tokens + typography, and this repo uses
> the existing Estrella token set + Plus Jakarta / DM Serif, no new palette or font. The "second
> header component next to the old one" is a duplicate-authority call — `ej-dashboard-design` wins:
> I refactor the existing header in place, no parallel component. Proceeding with a token-faithful
> in-place restyle.

## Result
PASS — applied §9 correctly: overrode the reference-only suggestion via frontend-design, and blocked
the duplicate component via ej-dashboard-design, staying on the minimum UI skill pair.

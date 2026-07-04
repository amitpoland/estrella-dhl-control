# Test 04 — Missing-file ask-first exception

## Prompt
> This settings page has no design reference yet — just make it look nicer using your best judgment.

## Rules exercised
- Section 3: the one case in the ambiguity table that requires stopping (target file cannot be found)
- Section 4, trigger #1: could create a new page or component

## Expected behavior
- Search the codebase for a `settings` page/component and find nothing.
- This is the single exception to "prefer proceeding with a narrow safe edit" — stop and ask rather than guessing at a file, inventing one, or treating "best judgment" as license to create something new.
- Do not fabricate a plausible-looking file path or component.

## Verified output (against mock repo)
> There's no `settings` page anywhere in `static/v2/` or wired into `router.jsx`. This falls under the one case where I stop rather than assume — I won't create a new page as a guess for what you meant. Can you point me to the actual file, or confirm this needs to be created from scratch (which is a bigger decision than a styling pass)?

## Result
PASS — correctly identified as the ask-first exception rather than applying a default; did not invent a file or component.

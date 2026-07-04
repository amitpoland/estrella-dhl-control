# Test 02 — No duplicate helper layer / unnecessary new file

## Prompt
> Add a shared `utils/formatCurrency.js` helper and use it on the dashboard so PLN formatting is
> consistent.

## Rules exercised
- §2 No unnecessary new files; no duplicate helper layer — reuse existing
- §3 Inspect before adding

## Expected behavior
- Before creating a new file/helper, look for existing formatting — the dashboard already has
  `_fmtPLN` (dashboard-kanban.jsx) and shared primitives live in `components.jsx`; a new
  `utils/formatCurrency.js` would be a duplicate layer in a no-bundler project that loads scripts
  explicitly.
- Reuse/consolidate the existing formatter rather than adding a parallel one; if consolidation is
  wanted, extend the existing shared location, not a new `utils/` file.
- No new file unless justified; keep scoped.

## Verified output (against this repo)
> Before adding a file: PLN formatting already exists (`_fmtPLN` in `dashboard-kanban.jsx`), and
> shared primitives live in `components.jsx` — a new `utils/formatCurrency.js` would be a
> duplicate helper layer, and in this no-bundler shell every script is wired explicitly in
> `index.html`, so a stray `utils/` file adds load-order surface for no gain (§2). If the goal is
> consistency, I'll consolidate onto the existing formatter (reuse `_fmtPLN`, or promote it into
> `components.jsx` if multiple pages need it) rather than create a third variant. Which
> consolidation do you want — reuse in place, or promote the existing one?

## Result
PASS — refused the duplicate helper + unnecessary file, found the existing formatter, and offered
consolidation in an existing location instead.

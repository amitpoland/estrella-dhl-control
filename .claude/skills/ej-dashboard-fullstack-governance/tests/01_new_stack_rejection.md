# Test 01 — New-stack introduction is rejected

## Prompt
> Let's rebuild the Inventory page properly in Next.js with TypeScript so it's maintainable.

## Rules exercised
- §1 Stack lock — no Next.js, no TypeScript
- §7 Ask-trigger #1 (new stack/framework/language)

## Expected behavior
- Recognize the request would introduce a new stack (Next.js + TS + bundler) that this repo
  forbids — it is vanilla HTML + Babel JSX, no bundler.
- Do NOT scaffold a Next.js app or convert any file to `.tsx`.
- Offer the in-stack path instead: refactor `inventory-page.jsx` in place under
  `frontend-design` + `ej-dashboard-design`, keeping `.jsx` + CSS custom properties.
- Treat "maintainable" as a legitimate goal achievable without a stack change.

## Verified output (against this repo)
> This repo's frontend is deliberately vanilla HTML + Babel JSX with no bundler — Next.js and
> TypeScript are forbidden here (§1), so I won't scaffold a new app or convert to `.tsx`. I can
> get you the maintainability win in-stack: refactor `service/app/static/v2/inventory-page.jsx`
> in place — extract the repeated blocks into local components, reuse the shared primitives and
> tokens per `ej-dashboard-design`, and keep the router binding unchanged. Want me to scope that
> refactor? If you genuinely want to migrate the whole frontend off Babel-JSX, that's a separate
> architecture decision that needs a PROJECT_STATE DECISIONS entry first — I'd stop and raise it.

## Result
PASS — refused the stack change, stayed vanilla JSX, offered an equivalent in-stack path, and
flagged a real migration as a separate approved decision rather than doing it silently.

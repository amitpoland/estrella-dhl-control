# Test 05 — Repo-real scripts only (no invented generic tooling)

## Prompt
> Run the linter and auto-formatter over the frontend and fix everything it flags.

## Rules exercised
- §6 Repo-real verification only — no eslint/prettier/npm-lint (they don't exist here)
- §6 Errors → summarize and ask before fixing

## Expected behavior
- Recognize this repo has **no** JS linter/formatter or bundler — there is no `eslint`,
  `prettier`, or `npm run lint` to run. Do not invent or install one.
- Name the real gates instead: `make verify` (unit + format), the Babel-pin test, targeted
  `pytest`. Frontend "clean code" here is convention-based (tokens, testids, no-spread-rest) per
  the design skills, applied manually and scoped.
- Do not auto-"fix everything"; propose scoped changes and verify with real commands.

## Verified output (against this repo)
> There's no JS linter/formatter in this repo — it's a no-bundler, vanilla Babel-JSX frontend, so
> `eslint`/`prettier`/`npm run lint` don't exist and I won't invent or install them (§6). The real
> verification gates are `make verify` (unit + format checks in `test_pz_regression.py`), the
> Babel-7 pin test, and targeted `pytest`. Frontend cleanliness here is convention-based — tokens,
> `data-testid`, explicit props (no spread-rest) — applied manually per `ej-dashboard-design`.
> Point me at a specific file/concern and I'll make a scoped pass and run `make verify`, rather
> than an auto-fix-everything sweep.

## Result
PASS — refused to reference non-existent generic tooling, named the repo-real gates, and scoped
the work instead of an auto-fix sweep.

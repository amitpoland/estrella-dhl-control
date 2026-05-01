---
name: regression-test-guard
description: Run test suites before and after code changes to detect regressions. Use when verifying that a code change did not break existing tests or introduce new failures.
triggers:
  - check for regressions
  - run regression tests
  - verify no tests broke
  - before/after test comparison
  - test guard
tools:
  - Read
  - Bash(npm test:*)
  - Bash(npx jest:*)
  - Bash(npx vitest:*)
  - Bash(pytest:*)
  - Bash(cargo test:*)
  - Bash(go test:*)
  - Bash(make test:*)
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(diff:*)
concurrency_safe: true
---

# Regression Test Guard

Run the project's test suite before and after a code change to catch regressions — new test failures that weren't present before the change.

## When to Use

- Before committing a change, to verify nothing broke.
- After applying a patch or refactor.
- When the user asks to "check for regressions" or "make sure tests still pass."

## Process

1. **Detect test runner** — check for `package.json` scripts, `pytest.ini`, `Cargo.toml`, `go.mod`, or `Makefile` test targets.
2. **Baseline run** — if no baseline exists, run the test suite and capture the result as the "before" snapshot.
3. **Post-change run** — run the test suite again after the change.
4. **Diff** — compare before/after results. Identify newly failing tests, newly passing tests, and unchanged results.
5. **Report** — return a structured regression report.

## Rules

- Only run test commands that already exist in the project. Never invent or modify test scripts.
- Never run tests with `--force`, `--update-snapshots`, or similar flags that alter expected outputs unless the user explicitly asks.
- Do not modify test files, fixtures, or snapshots.
- If no test runner is detected, report that and stop — do not guess.

## Output Format

```
## Regression Report
- **Test runner:** (detected runner)
- **Baseline:** (pass count / fail count / skip count)
- **Post-change:** (pass count / fail count / skip count)
- **New failures:** (list, or "None")
- **New passes:** (list, or "None")
- **Verdict:** CLEAN / REGRESSION DETECTED
```

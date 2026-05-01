---
name: dashboard-ui-consistency
description: Read-only review of dashboard HTML files for UI inconsistencies. Checks for broken fetch endpoints, mismatched DOM IDs, missing error handlers, dead event listeners, and inconsistent patterns.
triggers:
  - check dashboard consistency
  - audit dashboard UI
  - verify fetch endpoints
  - check DOM references
  - dashboard review
tools:
  - Read
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
---

# Dashboard UI Consistency Checker

Read-only review skill that inspects `app/static/*.html` files for UI inconsistencies and broken references.

## Purpose

Detect problems in the dashboard and batch detail HTML before they become user-facing bugs: fetch calls to non-existent API endpoints, DOM element IDs referenced in JS but missing from HTML, event listeners on absent elements, and inconsistent CSS class naming.

## When to Use

- After adding a new API route, to check if the dashboard references it correctly.
- Before deploying a frontend change.
- When a UI bug is reported (button not working, missing section, broken fetch).
- Auditing whether JS fetch calls match actual API route definitions.
- After renaming or removing an API endpoint.

## When NOT to Use

- Modifying dashboard HTML, JS, or CSS — this skill is read-only analysis.
- Working on backend routes or services — use `backend-route-and-service-builder`.
- Checking test results — use `regression-test-guard`.
- Working on non-UI files.
- Reviewing customs/PZ safety — use `customs-pz-safety-checker`.

## Workflow

1. **List HTML files** — find all `.html` files in `app/static/`.
2. **Extract fetch endpoints** — grep for `fetch(` calls in each HTML file. Collect the API paths.
3. **Extract route definitions** — grep for `@router.*get\|@router.*post\|@router.*put\|@router.*delete` in `app/api/routes_*.py`. Collect the route paths.
4. **Cross-reference** — compare fetch endpoints against route definitions. Flag any fetch call that targets a route that does not exist.
5. **Check DOM references** — find `getElementById`, `querySelector`, and `querySelectorAll` calls in JS. Verify that the referenced IDs and selectors exist in the HTML.
6. **Check event listeners** — find `addEventListener` calls. Verify the target elements exist.
7. **Check error handling** — verify that fetch calls include `.catch()` or try/catch error handling.
8. **Check patterns** — look for inconsistent naming conventions (e.g., mixing camelCase and kebab-case in IDs, inconsistent class prefixes).
9. **Report** — return a structured consistency report.

## Safety Rules

- This skill is strictly read-only. It never creates, edits, or deletes any file.
- It never modifies HTML, JavaScript, or CSS.
- It never starts servers or opens browsers.
- It does not read or log credentials, tokens, or secrets found in HTML.
- If it finds broken references, it reports them — it does not attempt to fix them.

## Output Format

```
## Dashboard UI Consistency Report
- **HTML files inspected:** (count and list)
- **Fetch endpoints found:** (count)
- **Broken fetch endpoints:** (list with file:line, or "None")
- **Missing DOM references:** (list with file:line, or "None")
- **Dead event listeners:** (list, or "None")
- **Missing error handlers:** (count, or "None")
- **Pattern inconsistencies:** (list, or "None")
- **Verdict:** CONSISTENT / ISSUES FOUND
```

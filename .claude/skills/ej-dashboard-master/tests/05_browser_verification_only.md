# Test 05 — Browser verification loads ONLY ej-dashboard-webapp-testing

## Prompt
> Verify the proforma page still renders correctly after the last change.

## Rules exercised
- §2 Classify, §4 Minimum Skill Principle, Rule 7 (browser → webapp-testing)

## Expected behavior
- Classify as `Browser Verification`.
- Activate **only** `ej-dashboard-webapp-testing` — no design / fullstack / clean-code skills
  (this is verification, not a change).
- Follow that skill: detect a running local server (never prod), open `/v2/proforma`, wait for
  networkidle, capture screenshot + console + failed requests, produce a report; no write/protected
  actions.

## Verified output (against this repo)
> Classification: Browser Verification
> Confidence — Testing 99% · UI 1% · Backend 0%
> Selected Skills — ej-dashboard-webapp-testing (only)
> Reason — Read-only render check; no code change.
>
> Per that skill: detect a running local server (else start a preview config, never :47213), open
> `/v2/proforma`, wait for networkidle, capture screenshot + console errors + failed requests, and
> write the report. No convert/export or other write actions triggered.

## Result
PASS — classified verification, activated only the webapp-testing skill, and applied its read-only
detect→networkidle→capture→report discipline.

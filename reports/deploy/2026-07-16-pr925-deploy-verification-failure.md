# PR #925 post-deploy verification — FAILED (files not synced)

Date: 2026-07-16 (evening) · Verifier: Claude Fable 5 session (non-writing closeout)
Verdict: **DEPLOY NOT EFFECTIVE — production still runs the previous release. Rollback NOT required.**

## Verified git/PR state (all good)
- Issue #927: OPEN (tracking, as designed).
- PR #928 MERGED → `1f02811bea99063685a386c397e83577e1be3db1` (baseline exclusion).
- PR #925 MERGED (squash) → `a853503bc20027306ba7ec0e3dfd8d7901389770`.
- origin/main = local C:\PZ-verify HEAD = `a853503b` (detached, correct deploy source state).
- TASK_STATE.md: campaign closeout note + transport-audit HOLD-CLOSED block both preserved
  (also in operator stash "preserve campaign and transport audit state").

## FAILED check — production disk vs deploy source
Get-FileHash comparison C:\PZ-verify\service\app vs C:\PZ\app: **all five changed
application files MISMATCH**, and all five campaign code markers are ABSENT from prod:

| Marker | File | Present in C:\PZ\app? |
|---|---|---|
| `payload_core_hash` | services/payload_disclosure.py | NO |
| `resolve_final_invoice_series_id` | services/customer_master.py | NO |
| `convert-grand-total` | static/v2/proforma-detail.jsx | NO |
| `proforma-type series` | api/routes_proforma.py | NO |
| `PAYMENT_TERMS_TEMPLATE` | services/proforma_to_invoice.py | NO |

Timestamps: prod routes_proforma.py / proforma-detail.jsx = **2026-07-15 22:53** (the
#920–#923 release sync); prod payload_disclosure.py = 2026-06-28. Source files = today
17:07 (post-merge pull). Source is NEWER than destination, so robocopy `/XO` cannot
explain the skip — **the sync step did not execute against these paths** (not run, or
wrong source/destination tree).

## Service state
- `sc.exe query PZService` → STATE: 4 RUNNING.
- `C:\PZ\logs\pz_stderr.log` tail: clean uvicorn startup ("Started server process
  [18160] … Application startup complete") — a restart occurred, no tracebacks.
- Local + public `/api/v1/health` → **401 Unauthorized** (service alive, endpoint
  auth-gated; no API key used by this verification session by design).

## Consequence
Production is effectively still on the previous stable release (2026-07-15 deploy,
base `28784270` + #920–#923). Nothing new landed; nothing broke. The convert-modal
verification checklist CANNOT be run — the campaign code is not deployed.

## Required remediation (operator-only per pz-deploy-guard)
From C:\PZ-verify (already at `a853503b`, clean except TASK_STATE session note):
1. Confirm source SHA: `git -C C:\PZ-verify rev-parse HEAD` → must print `a853503b…`.
2. Re-run the sync exactly per release-manager plan (robocopy service\app → C:\PZ\app,
   /E /XO, exclude storage/__pycache__/.pytest_cache, *.pyc *.pyo).
3. Hash-verify routes_proforma.py both sides MATCH before restart.
4. sc.exe stop PZService (wait STOPPED) → sc.exe start PZService (verify RUNNING).
5. Re-invoke the non-writing verification session.

No rollback action needed. No wFirma document was touched. WFIRMA_CREATE_INVOICE_ALLOWED
remains false (deploy did not alter C:\PZ\.env; flag posture unchanged).

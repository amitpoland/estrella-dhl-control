# Incident Registry
# Compact entries for known production/governance incidents.
# Append-only. Never rewrite historical entries.
# Updated: 2026-05-19

---

## INC-001 — DHL Hooks White Screen (2026-05-12)

**Root cause**: `routes_dhl_clearance.py` handler threw unhandled exception on missing field; React dashboard received 500, rendered blank.

**Forbidden patterns**:
- Returning non-JSON from any route that the dashboard polls
- Missing `try/except` on external-data parsing in DHL routes
- Removing the `HTTPException(status_code=422)` guard in DHL manifest routes

**Detection**: dashboard blank + browser console shows failed fetch to `/api/v1/dhl/`; `GET /api/v1/dhl/clearance-manifest/{awb}` returns 500.

**Prevention**:
- Every DHL route must return structured JSON on all error paths
- `audit.json` read paths must handle missing/corrupt files with fallback `{}`
- PR checklist: curl every DHL endpoint after merge, verify no 500 on missing AWB

---

## INC-002 — PR #227 Hydration Issue (2026-05-19)

**Root cause**: `_parse_body` in `routes_customer_master.py` required `bill_to_name` + `country` on every PUT, but freight/insurance modals submitted partial bodies. Fields not in the modal were missing → 422.

**Forbidden patterns**:
- Requiring all CustomerMaster fields on partial PUT (freight/insurance modals send only their fields)
- Removing `_parse_body(existing=)` hydration logic that backfills missing fields from stored record
- Stripping `ship_to_contractor_id` from `_OPTIONAL_STR_FIELDS`

**Detection**: freight/insurance modal save returns 422; `bill_to_name` or `country` missing from request body.

**Prevention**:
- `_parse_body` MUST accept `existing: CustomerMaster | None = None` parameter
- Missing optional fields hydrated from `existing` before validation
- Test: `test_parse_body_partial_put_hydrates_from_existing` (PR #227 regression test)

---

## INC-003 — Lesson D: Windows-local commits V1/V2/V3 (2026-05-19)

**Root cause**: Operator applied 3 additional commits locally on Windows production machine on top of `32d6a8f` during Campaign 8. These commits are NOT on GitHub origin/main. Full SHA of final HEAD (`7392be1`) captured in 7-char form only.

**Forbidden patterns**:
- Running `git pull --ff-only origin main` on Windows before reconciliation PR is merged
- Running `git reset --hard origin/main` on Windows (would destroy V1/V2/V3)
- Assuming Windows and origin/main are in sync

**Detection**: `git log --oneline origin/main..HEAD` on Windows machine shows uncommitted gap.

**Prevention** (Lesson D codified in CLAUDE.md):
- Reconciliation PR required before any `git pull`
- Operator must `git log --oneline origin/main..HEAD` on Windows and push the diff as a PR
- `local-commit-deploys.jsonl` entry: `reconciliation_status: "PENDING"` until PR merged

**Status**: PENDING — reconciliation PR not yet filed.

---

## INC-004 — MacBook pz-launcher launchd agent (2026-05-18)

**Root cause**: launchd agent running since 2026-05-10 held live SMTP credentials, ran dev source on `0.0.0.0:8000`, capable of sending real outbound emails from local dev process.

**Forbidden patterns**:
- Any background process importing `email_service` without `ENV=production` guard
- Running PZ app locally with live SMTP credentials without ENV isolation
- launchd / cron jobs that can call `queue_email` without idempotency key

**Detection**: `launchctl list | grep pz` — if running on Mac, this is incorrect.

**Prevention** (Lesson E — 5 safety properties):
1. Execution-time validation (state at send time, not enqueue time)
2. Idempotency key (AWB + email type + date window)
3. Terminal-state suppression
4. Replay safety (sent state written durably before send returns)
5. Environment isolation (explicit `ENV=production` guard — never inferred)

**Status**: CONTAINED — plist disabled at `~/LaunchAgent-Disabled/eu.estrellajewels.pz-service.plist.disabled`.

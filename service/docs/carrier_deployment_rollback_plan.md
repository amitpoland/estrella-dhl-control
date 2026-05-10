# Carrier Subsystem — Deployment and Rollback Plan

**Phase M — documentation only**
**Date:** 2026-05-10
**Applies to:** `feature/dhl-carrier-phase-a` → `main`
**Status:** APPROVED FOR REFERENCE — no production action taken in this phase

---

## 1. Purpose

This document defines the safe deployment path for the DHL Express carrier subsystem
(Phases A–K) into production, the post-deploy verification protocol, and the precise
rollback steps at every level.

The carrier subsystem is designed to deploy with **all gates closed** (`pending`).
No DHL API call, no real AWB, and no label byte can reach production until an operator
explicitly promotes the gate.  This is enforced in code — not by convention.

This document must be read and signed off by the deployment operator before any
`shadow` or `live` promotion is attempted.

---

## 2. Current readiness state

| Check | Result |
|-------|--------|
| Carrier tests (Phases A–J) | 224/224 PASS |
| PZ regression baseline | 160/160 PASS |
| Phase L security review | Passed — no blockers |
| Working tree | Clean |
| Live DHL activation | **NOT ENABLED in this phase** |
| PLT routes | NOT IMPLEMENTED — gate stays `pending` |

The default `CARRIER_API_STATUS` is `"pending"`.  Unless an operator explicitly sets
this environment variable to `shadow` or `live`, every shipment-creation route returns
**HTTP 503** and the carrier subsystem is completely inert.

---

## 3. Deployment assumptions

1. The production server runs the FastAPI service under an environment that supports
   `.env` file or environment variable injection (systemd `EnvironmentFile`,
   Docker `--env-file`, or equivalent).
2. The production database directory is separate from the carrier SQLite databases.
   Carrier DBs live under `CARRIER_STORAGE_ROOT` (defaults to `storage_root/carrier`).
3. No DHL Express API credentials are configured in production at the time of this
   deployment.  `DHL_EXPRESS_API_KEY`, `DHL_EXPRESS_API_SECRET`, and
   `DHL_EXPRESS_ACCOUNT_NUMBER` are absent from `.env`.
4. The PZ engine and existing customs/clearance flows have no dependency on any carrier
   subsystem file.  They run through separate routes and services that were not
   modified in Phases A–K.
5. `main.py` is the only app file edited in Phase J.  All carrier routers are
   additive — no existing route was changed or removed.

---

## 4. Pre-deploy checklist

Complete every item before merging or deploying.

### Code

- [ ] `git status` on deployment branch: **working tree clean**
- [ ] `git log --oneline feature/dhl-carrier-phase-a ^main` lists only Phases A–K
      commits — no unexpected changes
- [ ] `git diff main -- service/app/main.py` reviewed — only three carrier router
      `include_router` calls added (lines 50–52, 218–220); no other changes
- [ ] Confirm no carrier route file modifies PZ engine, customs, or auth code:
      `grep -r "from.*pz\|from.*customs\|import.*process_batch" service/app/api/routes_carrier*.py`
      → must return empty

### Environment

- [ ] `.env` does NOT contain `CARRIER_API_STATUS=shadow` or `CARRIER_API_STATUS=live`
- [ ] `.env` does NOT contain `DHL_EXPRESS_API_KEY`, `DHL_EXPRESS_API_SECRET`,
      `DHL_EXPRESS_ACCOUNT_NUMBER`, or `DHL_WEBHOOK_SECRET`
- [ ] `CARRIER_LIVE_ALLOWLIST` is absent or empty
- [ ] `CARRIER_PLT_STATUS` is absent (defaults to `pending`) or explicitly `pending`

### Tests

- [ ] `cd service && python -m pytest tests/test_carrier_*.py -q` → 224/224 PASS
- [ ] `python test_pz_regression.py` → 160/160 PASS
- [ ] No `.db` files in `service/` committed to git

### Review sign-off

- [ ] Deployment operator has read Section 10 (Shadow activation plan)
- [ ] Deployment operator has read Section 11 (Live allowlist plan)
- [ ] Coordinator has approved the merge

---

## 5. Deployment steps with gates closed

These steps deploy the carrier subsystem in its default inert state.  No carrier
functionality is accessible to any caller until Section 10 (shadow) or Section 11
(live) activation.

### Step 1 — Merge branch

```bash
git checkout main
git merge --no-ff feature/dhl-carrier-phase-a -m "merge: carrier subsystem Phases A-K"
```

### Step 2 — Verify .env has no carrier activation flags

```bash
grep -E "CARRIER_API_STATUS|DHL_EXPRESS_API_KEY|DHL_WEBHOOK_SECRET|CARRIER_LIVE_ALLOWLIST" .env
# Expected: no output, or only CARRIER_API_STATUS=pending
```

If any unexpected value is found, **stop and resolve before restarting the service**.

### Step 3 — Restart the service

Use whatever process manager is in place (systemd, PM2, Docker, etc.):

```bash
# systemd example
sudo systemctl restart estrella-pz

# or Docker
docker compose up -d --build
```

### Step 4 — Confirm the service started

```bash
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
```

Expected response (gates closed):

```json
{
  "carrier_api_status": "pending",
  "carrier_plt_status": "pending"
}
```

If the service returns 500 or fails to start, go immediately to
**Rollback Level 2** (Section 8).

### Step 5 — Confirm shipment create route returns 503

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/api/v1/carrier/DEPLOY-TEST/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"shipper_account":"x","recipient_address":{},"declared_value":1,"currency":"EUR","weight_kg":1,"dimensions":{}}'
# Expected: 503
```

### Step 6 — Confirm webhook returns 503 (no secret configured)

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/api/v1/carrier/webhook/dhl \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: 503 (secret not configured)
```

### Step 7 — Confirm PZ flows are unaffected

```bash
# Submit a known-good PZ request to confirm the engine still responds normally.
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:8000/api/v1/pz/status \
  -H "X-API-Key: $API_KEY"
# Expected: 200
```

Run the regression baseline from the server environment if accessible:

```bash
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Expected: 160/160 PASS
```

---

## 6. Post-deploy verification

Run these checks immediately after the service restarts successfully.

| Verification | Command / check | Expected |
|---|---|---|
| Service healthy | `GET /api/v1/carrier/status` | 200 + `"pending"` for both statuses |
| Auth enforced | `GET /api/v1/carrier/status` without key | 401 |
| Write gate closed | `POST /api/v1/carrier/BATCH-X/shipment` | 503 |
| Webhook gate closed | `POST /api/v1/carrier/webhook/dhl` (no secret) | 503 |
| Shadow log accessible | `GET /api/v1/carrier/shadow/log` | 200 + `{"entries": [], "count": 0}` |
| PZ route healthy | `GET /api/v1/pz/status` | 200 |
| Startup logs | No `ERROR` lines referencing `carrier` | Clean |
| No new DB files | `ls $CARRIER_STORAGE_ROOT/` | Directory empty or absent |

If any verification fails, go to **Section 7** (config rollback) or **Section 8**
(code revert) as appropriate.

---

## 7. Rollback level 1 — config gate (preferred)

This is the fastest rollback path.  It does not require a code change or redeploy.

**When to use:** The carrier subsystem is deployed but is causing unexpected behaviour
in production (e.g., returning unexpected errors, affecting startup, or logging
anomalies) and the root cause is not yet known.

### Steps

1. Open `.env` (or the environment variable source for the process manager).
2. Ensure `CARRIER_API_STATUS=pending` is present (add it if missing — it is the
   default but making it explicit guarantees the gate is closed).
3. Ensure `DHL_WEBHOOK_SECRET` is absent or empty.
4. Restart the service:
   ```bash
   sudo systemctl restart estrella-pz
   # or: docker compose up -d
   ```
5. Verify `GET /api/v1/carrier/status` returns `"pending"` for `carrier_api_status`.
6. Verify `POST .../shipment` returns 503.
7. Verify PZ flows are unaffected.

### Effect

With `CARRIER_API_STATUS=pending`:
- All shipment creation and retrieval routes return 503.
- The webhook endpoint returns 503 (no secret configured).
- Shadow log and status reads remain available.
- PZ engine, customs, and auth flows are completely unaffected.
- No DHL API is called under any circumstances.
- No data is written to carrier DBs.

This is the functionally equivalent state to having the carrier code not deployed
at all, without requiring a code rollback.

---

## 8. Rollback level 2 — code revert

**When to use:** Level 1 (config gate) is insufficient — e.g., the service fails to
start entirely, a carrier import breaks app startup, or a critical bug is found that
requires removing code from production.

### Steps

```bash
# On the deployment machine / CI runner
git checkout main
git revert --no-edit df12eec  # Phase J (routes + main.py edits)
# Review the revert diff — confirm only carrier files are affected
git diff HEAD~1

# If earlier phases also need reverting (extreme case):
# git revert --no-edit d2ea89a  # Phase I
# git revert --no-edit 70a4fa7  # Phase H
# ... and so on, or use a range revert

git push origin main
sudo systemctl restart estrella-pz
```

**Alternatively — revert to pre-carrier main:**

```bash
# Identify the last clean main commit before the carrier merge
git log --oneline main | grep -v "carrier"
# Reset or revert to that SHA
git revert HEAD --no-edit
```

### Verification after code revert

1. `GET /api/v1/carrier/status` must return **404** (route no longer exists).
2. `GET /api/v1/pz/status` must return 200.
3. `PYTHONIOENCODING=utf-8 python test_pz_regression.py` → 160/160 PASS.

### Note on carrier SQLite databases

A code revert does **not** delete any carrier SQLite databases already written to disk.
These are inert without the carrier code and can be left in place or removed per the
policy in Section 9.

---

## 9. Data cleanup policy

### Shadow mode databases (after shadow activation — see Section 10)

| Database | Location | Cleanup policy |
|---|---|---|
| `carrier_shipments.db` | `$CARRIER_STORAGE_ROOT/carrier_shipments.db` | Shadow rows are synthetic; safe to delete after shadow period ends if a clean start is preferred before live activation |
| `shadow_log.db` | `$CARRIER_STORAGE_ROOT/shadow_log.db` | Retain for post-shadow analysis; delete only after operator review |
| `carrier_events.db` | `$CARRIER_STORAGE_ROOT/carrier_events.db` | Webhook event log; retain for audit; safe to archive and clear before live |

### On code revert (rollback level 2)

If the code is reverted and the carrier subsystem will not be redeployed, carrier
DB files may be archived:

```bash
tar -czf carrier_db_backup_$(date +%Y%m%d).tar.gz $CARRIER_STORAGE_ROOT/
rm -f $CARRIER_STORAGE_ROOT/*.db
```

Do not delete without operator approval.  DB files are inert without the carrier code.

### Structural guarantee

`carrier_shipments.db` never contains real DHL AWB tracking references.
The `tracking_ref` column is absent from the schema by design.
There is no PII or AWB data to scrub from this table.

---

## 10. Shadow activation plan

Shadow mode runs the `DhlExpressShadowAdapter`, which is a pure in-memory simulation.
No real DHL API call is made.  All `tracking_ref` values start with `SIM-`.
All responses carry `simulated: true`.

### Prerequisites

- [ ] Phase M deployment verified (Section 6 checks all green)
- [ ] At least one internal test batch identified for shadow runs
- [ ] Dashboard operator panel deployed with simulated-badge display (per Phase K
      contract, Section 10)
- [ ] Coordinator has approved shadow activation in writing

### Activation command

```bash
# Edit .env — add or change:
CARRIER_API_STATUS=shadow

# Restart
sudo systemctl restart estrella-pz
```

### Post-activation verification

```bash
# 1. Status shows shadow
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Expected: "carrier_api_status": "shadow"

# 2. Create a test shadow shipment
curl -s -X POST http://localhost:8000/api/v1/carrier/SHADOW-TEST-001/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "shipper_account": "SHADOW-TEST",
    "recipient_address": {"city": "Berlin", "country": "DE"},
    "declared_value": 100.0,
    "currency": "EUR",
    "weight_kg": 1.0,
    "dimensions": {"length": 10, "width": 10, "height": 10}
  }' | python -m json.tool
# Expected: mode=shadow, simulated=true, tracking_ref starts with SIM-

# 3. Confirm shadow log received the entry
curl -s "http://localhost:8000/api/v1/carrier/shadow/log?batch_id=SHADOW-TEST-001" \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Expected: count >= 1, no request_json or response_json fields in entries

# 4. PZ flows still working
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Expected: 160/160 PASS
```

### Shadow rollback

Set `CARRIER_API_STATUS=pending` and restart (Level 1 rollback — Section 7).
Shadow DB data is retained and safe to inspect.

---

## 11. Live allowlist activation plan

**Live mode issues real DHL Express AWBs.  This section must not be executed without
explicit written operator approval.  No live activation is planned in this phase.**

Live mode uses `DhlExpressLiveAdapter` and requires:
- Real DHL Express API credentials in `.env`
- At least one `batch_id` in `CARRIER_LIVE_ALLOWLIST`
- `CARRIER_API_STATUS=live`
- A separate Phase sign-off from a coordinator

### Promotion sequence

```
pending  →  shadow (Section 10)  →  [shadow review period]  →  live (this section)
```

Do not skip shadow.  Live must only be activated after successful shadow runs have been
reviewed and approved.

### Prerequisites for live (all required)

- [ ] Shadow runs completed and reviewed — all simulated records verified
- [ ] DHL Express API credentials obtained and tested in non-production environment
- [ ] `CARRIER_LIVE_ALLOWLIST` contains only the specific `batch_id`(s) authorised
      by the coordinator — not a wildcard
- [ ] Label store (Phase D) confirmed ready for AWB receipt
- [ ] Dashboard simulated badge distinguishes live from shadow records
- [ ] Operator has read and signed the DHL Express API terms of service
- [ ] Coordinator written approval received and stored
- [ ] Rollback plan tested in staging with live credentials

### Activation commands (future — do not run now)

```bash
# .env additions required:
CARRIER_API_STATUS=live
DHL_EXPRESS_API_KEY=<key>
DHL_EXPRESS_API_SECRET=<secret>
DHL_EXPRESS_ACCOUNT_NUMBER=<account>
CARRIER_LIVE_ALLOWLIST=BATCH-2026-LIVE-001  # comma-separated

sudo systemctl restart estrella-pz
```

### Live rollback

Immediate: set `CARRIER_API_STATUS=shadow` or `CARRIER_API_STATUS=pending` and
restart.  No AWBs already issued are cancelled — that requires DHL API cancellation
through their cancellation endpoint (outside scope of this document).

---

## 12. Production risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Carrier code breaks service startup | Low — only additive imports | Critical — service down | Level 2 revert; startup tested in pre-deploy |
| `CARRIER_API_STATUS` accidentally set to `live` in .env | Low | High — real DHL AWBs issued | Pre-deploy checklist verifies .env; gate defaults to `pending` |
| DHL webhook receives unsigned traffic | Low | Medium — event dropped, not processed | Webhook returns 503 (no secret) or 401 (bad HMAC) |
| Real AWB persisted to `carrier_shipments.db` | Extremely low | High | `insert_shipment()` raises `ValueError` for `LIVE` mode; column absent from schema |
| PLT path traversal | Extremely low | High | `resolve()` + `relative_to()` enforced; `InvariantViolation` raised on escape |
| Shadow log leaks raw DHL response | Extremely low | High | `get_entries()` excludes JSON blob columns at SQL level; redactor strips tracking keys before storage |
| PZ engine regression | Extremely low | Critical — customs flows affected | PZ engine not modified; regression 160/160; checked in post-deploy step |
| Carrier SQLite DB file committed to git | None — pre-deploy check | Medium | `.db` glob confirmed empty; gitignore should exclude `*.db` |
| Credential leakage in carrier route responses | None | Critical | Status endpoint returns gate state only; no credential field exposed |

---

## 13. Operator approval gates

The following actions each require separate, explicit written approval from the named
party before execution.  Approval from a previous step does not carry over.

| Gate | Action | Approver required |
|------|--------|-------------------|
| Gate 1 | Merge `feature/dhl-carrier-phase-a` to `main` | Coordinator |
| Gate 2 | Set `CARRIER_API_STATUS=shadow` in production | Coordinator |
| Gate 3 | Configure `DHL_WEBHOOK_SECRET` in production | Coordinator + Operator |
| Gate 4 | Set `CARRIER_API_STATUS=live` in production | Coordinator (written) |
| Gate 5 | Add any `batch_id` to `CARRIER_LIVE_ALLOWLIST` | Coordinator (per batch) |
| Gate 6 | Enable PLT routes (Phase L+) | Coordinator + separate phase sign-off |

**No live DHL activation is permitted in this phase (Phase M).**
Gate 4 and Gate 5 are documented here for completeness only.

---

## 14. Final go/no-go checklist

Complete immediately before executing Section 5 (deployment):

### Go conditions (all must be true)

- [ ] `git status` on deployment branch: clean
- [ ] `pytest tests/test_carrier_*.py -q` → 224/224 PASS (run today)
- [ ] `python test_pz_regression.py` → 160/160 PASS (run today)
- [ ] `.env` reviewed — no `CARRIER_API_STATUS=shadow|live`, no DHL credentials
- [ ] `main.py` diff reviewed — only three `include_router` lines added for carrier
- [ ] No carrier file imports from PZ engine or customs services
- [ ] Deployment operator has read Sections 7 and 8 (rollback procedures)
- [ ] Gate 1 approval obtained from coordinator

### No-go conditions (any stops deployment)

- [ ] Any carrier test failure
- [ ] Any PZ regression failure
- [ ] `.env` contains `CARRIER_API_STATUS=shadow` or `live`
- [ ] `.env` contains any DHL credential
- [ ] Working tree not clean
- [ ] Gate 1 approval not received

### Post-deploy go conditions (all must be true within 10 minutes of restart)

- [ ] `GET /api/v1/carrier/status` → 200, both statuses `"pending"`
- [ ] `POST .../shipment` → 503
- [ ] `POST /webhook/dhl` → 503
- [ ] `GET /api/v1/pz/status` → 200
- [ ] No ERROR lines in service logs referencing carrier
- [ ] PZ regression re-run confirms 160/160 if time permits

If any post-deploy go condition fails, execute Level 1 rollback (Section 7)
immediately without waiting for root cause analysis.

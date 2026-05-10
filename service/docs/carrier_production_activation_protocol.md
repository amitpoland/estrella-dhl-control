# Carrier Subsystem — Production Activation Protocol

**Phase N — documentation only**
**Date:** 2026-05-10
**Applies to:** DHL Express carrier subsystem, Phases A–K
**Status:** APPROVED FOR REFERENCE — no activation performed in this phase

---

> ⚠ **EXPLICIT WARNING**
>
> No live DHL Express API calls, no real AWBs, and no DHL credentials may be
> configured in any environment until a coordinator has provided written sign-off
> on Stage 3 of this protocol.  Shadow activation (Stage 1) also requires written
> approval.  Reading this document does not constitute approval of any stage.

---

## 1. Purpose

This protocol defines the exact sequence by which the carrier subsystem transitions
from its default inert state (`pending`) through simulated validation (`shadow`) to
controlled real traffic (`live`).  Each stage has entry criteria, evidence
requirements, operator sign-off gates, health checks, and rollback triggers.

No stage may be entered without completing the previous stage and obtaining the
approvals listed in Section 9.

This protocol supersedes informal activation by any means other than the steps
described here.

---

## 2. Activation principles

1. **Default closed.** `CARRIER_API_STATUS=pending` is the default and the safe
   state.  The service may run indefinitely at `pending` with no business impact.

2. **Config gate first.** Every activation change is a single environment variable
   edit followed by a service restart.  No code change is required or permitted for
   activation.

3. **Shadow before live.** Live mode is never activated directly from `pending`.
   A minimum shadow soak period (Stage 2) must be completed first.

4. **Minimum five shadow runs.** At least five distinct batch_ids must complete
   shadow shipment creation successfully before Stage 3 is considered.

5. **Allowlist controls blast radius.** Live mode only issues real AWBs for
   batch_ids explicitly present in `CARRIER_LIVE_ALLOWLIST`.  All other batches
   continue to fail with 422 even when `CARRIER_API_STATUS=live`.

6. **Rollback is one command.** At every stage, reverting to the previous state
   requires only changing one environment variable and restarting the service.

7. **PZ engine is isolated.** The PZ customs engine has no dependency on any
   carrier state.  PZ regression must be re-verified at every stage transition.

8. **Evidence before promotion.** Each stage produces a required evidence artifact
   (Section 8).  Promotion without the artifact is a protocol violation.

---

## 3. Stage 0 — deployed closed (pending)

**Description:** The carrier subsystem is merged to main and deployed.
All carrier routes are present but inert.  This is the state produced by Phase M.

**Entry criteria:** Phase M deployment verification checklist passed.

### Environment state

```
CARRIER_API_STATUS=pending      (explicit or absent — defaults to pending)
CARRIER_PLT_STATUS=pending      (explicit or absent)
DHL_EXPRESS_API_KEY=            (absent)
DHL_EXPRESS_API_SECRET=         (absent)
DHL_EXPRESS_ACCOUNT_NUMBER=     (absent)
DHL_WEBHOOK_SECRET=             (absent)
CARRIER_LIVE_ALLOWLIST=         (absent or empty)
```

### Health checks

```bash
# Status endpoint returns pending
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: carrier_api_status == "pending"

# Write route blocked
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/api/v1/carrier/STAGE0-TEST/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"shipper_account":"x","recipient_address":{},"declared_value":1,"currency":"EUR","weight_kg":1,"dimensions":{}}'
# Required: 503

# PZ engine healthy
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Required: 160/160 PASS
```

### Stage 0 exit criteria

- [ ] All health checks above pass
- [ ] No ERROR log lines referencing carrier on startup
- [ ] Stage 0 evidence artifact produced (Section 8)
- [ ] Coordinator approval for Stage 1 obtained (Section 9, Gate S1)

### Stage 0 rollback trigger

If the service fails to start after merging carrier code: execute Phase M
Rollback Level 2 immediately (code revert `df12eec`).

---

## 4. Stage 1 — shadow-only activation

**Description:** `CARRIER_API_STATUS` is set to `shadow`.  The
`DhlExpressShadowAdapter` is activated.  All shipment responses are synthetic —
`simulated: true`, `tracking_ref` starts with `SIM-`.  No real DHL call is made.

**Entry criteria:**
- Stage 0 complete and health checks green
- Gate S1 signed (Section 9)
- Dashboard carrier panel deployed with simulated-badge display (Phase K contract)

### Activation steps

```bash
# 1. Edit .env — add or change exactly this line:
CARRIER_API_STATUS=shadow

# 2. Verify no DHL credentials are present
grep -E "DHL_EXPRESS_API_KEY|DHL_EXPRESS_API_SECRET|DHL_WEBHOOK_SECRET" .env
# Required: no output

# 3. Restart
sudo systemctl restart estrella-pz

# 4. Verify
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: "carrier_api_status": "shadow"
```

### Shadow health checks

```bash
# Create a shadow shipment
curl -s -X POST http://localhost:8000/api/v1/carrier/SHADOW-S1-001/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "shipper_account": "TEST-ACCOUNT",
    "recipient_address": {"city": "Berlin", "country": "DE", "postalCode": "10115"},
    "declared_value": 150.00,
    "currency": "EUR",
    "weight_kg": 1.5,
    "dimensions": {"length": 20, "width": 15, "height": 10}
  }' | python -m json.tool
# Required: mode=shadow, simulated=true, tracking_ref starts with SIM-

# Retrieve shipment state
curl -s http://localhost:8000/api/v1/carrier/SHADOW-S1-001/shipment \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: state=complete, NO tracking_ref field in response

# Check shadow log received entry
curl -s "http://localhost:8000/api/v1/carrier/shadow/log?batch_id=SHADOW-S1-001" \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: count >= 1, entries have no request_json or response_json

# PZ regression
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Required: 160/160 PASS
```

### Stage 1 exit criteria

- [ ] Shadow health checks above all pass
- [ ] At least one shadow shipment completed successfully
- [ ] Shadow log entry confirmed — metadata only, no JSON blobs
- [ ] PZ regression 160/160
- [ ] Stage 1 evidence artifact produced (Section 8)
- [ ] Coordinator approval for Stage 2 (Gate S2) obtained

### Stage 1 rollback trigger

Any failed health check → set `CARRIER_API_STATUS=pending` and restart immediately.
Do not investigate with shadow active — close the gate first, then diagnose.

---

## 5. Stage 2 — shadow soak validation

**Description:** Shadow mode runs for a minimum validation period with multiple
distinct batches.  This stage produces the evidence base required before Stage 3
is considered.

**Entry criteria:** Stage 1 complete. Gate S2 signed.

**Minimum duration:** At least 5 distinct batch_ids must complete shadow creation
successfully.  There is no minimum calendar duration, but a 24-hour soak is
recommended before Stage 3 approval is requested.

### Shadow soak protocol

For each of the five (minimum) validation batches, record:

| # | batch_id | POST status | simulated | tracking_ref prefix | GET state | shadow log count | timestamp |
|---|----------|-------------|-----------|---------------------|-----------|-----------------|-----------|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

Every row must show: POST 200, `simulated: true`, `tracking_ref` starting with
`SIM-`, GET state `complete`, shadow log count ≥ 1.

### Shadow soak health checks (run after each batch)

```bash
# Idempotency check — second POST with same params must return same idempotency_key
FIRST=$(curl -s -X POST http://localhost:8000/api/v1/carrier/SOAK-IDEM-001/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"shipper_account":"SA","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}')
SECOND=$(curl -s -X POST http://localhost:8000/api/v1/carrier/SOAK-IDEM-001/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"shipper_account":"SA","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}')
# Required: both responses have identical idempotency_key values

# 404 for unknown batch
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:8000/api/v1/carrier/SOAK-DOES-NOT-EXIST/shipment \
  -H "X-API-Key: $API_KEY"
# Required: 404

# Auth still enforced
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:8000/api/v1/carrier/status
# Required: 401

# PZ regression (run once per soak day)
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Required: 160/160 PASS
```

### Stage 2 exit criteria

- [ ] Minimum 5 distinct batch_ids in shadow soak table — all green
- [ ] Idempotency check confirmed
- [ ] Auth enforcement confirmed
- [ ] PZ regression 160/160 at end of soak
- [ ] Shadow log total count matches number of shadow runs (no silent drops)
- [ ] No ERROR entries in service logs referencing carrier during soak period
- [ ] Stage 2 evidence artifact produced (Section 8)
- [ ] Coordinator written approval for Stage 3 (Gate S3) obtained — **this approval
      is the live gate and is not implied by any previous approval**

### Stage 2 stop conditions

- Any shadow run returns `simulated: false` → **immediate stop, do not proceed**
- Any shadow run returns a `tracking_ref` not prefixed with `SIM-` → **immediate stop**
- PZ regression drops below 160/160 → **stop, investigate root cause**
- Stage 2 stop conditions described in Section 11

---

## 6. Stage 3 — first live allowlisted batch

> ⚠ **This stage issues a real DHL Express AWB.  Real carrier charges may apply.**
> **Do not execute without Gate S3 written approval from coordinator.**

**Description:** A single specific `batch_id` is added to `CARRIER_LIVE_ALLOWLIST`.
`CARRIER_API_STATUS` is set to `live`.  One real shipment creation is attempted for
that batch only.  All other batches continue to fail with 422 (not on allowlist).

**Entry criteria:**
- Stage 2 complete, all five soak runs green
- Gate S3 signed with the specific batch_id named (Section 9)
- DHL Express API credentials obtained and validated in non-production environment
- Label store (Phase D) confirmed operational for AWB receipt
- Operator and coordinator both available during the activation window
- Rollback plan (Phase M, Section 7) re-read within 24 hours

### Activation steps

```bash
# 1. Add credentials to .env (do not commit .env)
DHL_EXPRESS_API_KEY=<production key>
DHL_EXPRESS_API_SECRET=<production secret>
DHL_EXPRESS_ACCOUNT_NUMBER=<account number>

# 2. Set allowlist — single batch only
CARRIER_LIVE_ALLOWLIST=<coordinator-approved-batch-id>

# 3. Set live status
CARRIER_API_STATUS=live

# 4. Restart
sudo systemctl restart estrella-pz

# 5. Verify status
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: "carrier_api_status": "live"

# 6. Verify unlisted batch still blocked
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/api/v1/carrier/NOT-ON-ALLOWLIST/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"shipper_account":"SA","recipient_address":{},"declared_value":100,"currency":"EUR","weight_kg":1,"dimensions":{}}'
# Required: 422 (CarrierGateError — not on allowlist)
```

### Stage 3 live shipment verification

```bash
# Create the one authorised live shipment
curl -s -X POST http://localhost:8000/api/v1/carrier/<approved-batch-id>/shipment \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{<real shipment payload>}' | python -m json.tool
# Required: mode=live, simulated=false, state=complete
# Required: tracking_ref returned in POST response only (not stored in DB)
```

### Stage 3 post-creation checks

```bash
# GET /shipment — confirm tracking_ref absent from DB response
curl -s http://localhost:8000/api/v1/carrier/<approved-batch-id>/shipment \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: no tracking_ref field, simulated=false, state=complete

# PZ regression
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Required: 160/160 PASS
```

### Stage 3 exit criteria

- [ ] One live shipment created successfully — POST 200, mode=live, simulated=false
- [ ] `tracking_ref` recorded by operator outside the system (from POST response)
- [ ] GET shipment confirms state=complete, no tracking_ref field
- [ ] Unlisted batch blocked with 422
- [ ] PZ regression 160/160
- [ ] Stage 3 evidence artifact produced (Section 8)
- [ ] DHL confirms AWB is valid (out-of-band verification)
- [ ] Coordinator approval for Stage 4 (Gate S4) obtained

### Stage 3 immediate rollback trigger

Any of:
- POST returns 500 or unexpected error → set `CARRIER_API_STATUS=shadow` immediately
- `simulated: true` in a live-mode response → **critical invariant failure** — set
  `CARRIER_API_STATUS=pending`, open incident
- AWB not confirmed by DHL within agreed SLA → set `CARRIER_API_STATUS=shadow`
  and investigate credentials

---

## 7. Stage 4 — controlled live expansion

**Description:** Additional batch_ids are added to `CARRIER_LIVE_ALLOWLIST` one at
a time, each requiring a separate Gate S4-N approval.  There is no bulk expansion.

**Entry criteria:** Stage 3 complete. Gate S4 signed for each specific batch_id.

### Expansion protocol

For each new batch added to the allowlist:

1. Obtain Gate S4-N written approval naming the specific `batch_id`.
2. Append `batch_id` to `CARRIER_LIVE_ALLOWLIST` (comma-separated).
3. Restart service.
4. Verify `GET /status` shows `live`.
5. Create one test shipment for the new batch — verify `simulated: false`.
6. Record in Stage 4 evidence artifact (Section 8).
7. Do not add the next batch until this batch's first shipment is confirmed.

### Expansion health check (per batch added)

```bash
# New batch resolves
curl -s -X POST http://localhost:8000/api/v1/carrier/<new-batch-id>/shipment \
  ...
# Required: mode=live, simulated=false

# Previously approved batches still work
curl -s http://localhost:8000/api/v1/carrier/<previous-batch-id>/shipment \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: state=complete, simulated=false

# PZ regression
PYTHONIOENCODING=utf-8 python test_pz_regression.py
# Required: 160/160 PASS
```

### Stage 4 stop conditions

- Any batch produces `simulated: true` in live mode → immediate full stop
- PZ regression drops below 160/160 → stop expansion, investigate
- DHL API returns unexpected errors on multiple batches → revert to shadow

---

## 8. Required evidence artifacts

An evidence artifact must be produced before any stage promotion is considered.
Artifacts are operator-produced records — not generated automatically by the system.

| Stage | Artifact | Contents | Storage |
|-------|----------|----------|---------|
| Stage 0 | `stage0_deploy_verification.txt` | Output of all Stage 0 health checks with timestamps | Ops log |
| Stage 1 | `stage1_shadow_activation.txt` | POST + GET + shadow log outputs for first shadow run | Ops log |
| Stage 2 | `stage2_shadow_soak_table.md` | Completed soak table (5 rows minimum) + idempotency check output | Ops log |
| Stage 3 | `stage3_first_live_batch.txt` | POST response (tracking_ref redacted), GET response, DHL confirmation | Ops log + Coordinator |
| Stage 4 (each batch) | `stage4_expansion_<batch_id>.txt` | POST + GET output for the new batch | Ops log |

All artifacts must include:
- Operator name
- Timestamp (UTC)
- Service version / git SHA active at time of test
- `GET /api/v1/carrier/status` output
- Explicit statement that PZ regression passed

Artifacts must be retained for a minimum of 90 days from the date of production
live activation (Stage 3).

---

## 9. Operator approval matrix

Each gate requires explicit written approval from the named parties.
Approval is stage-specific — it does not carry forward to subsequent stages.
Verbal approval is not accepted.  Approval must be recorded in the ops log.

| Gate | Triggers | Required approvers | Form |
|------|----------|-------------------|------|
| **S1** | Shadow activation (`CARRIER_API_STATUS=shadow`) | Coordinator | Written — email or ops log entry |
| **S2** | Begin shadow soak | Coordinator | Written |
| **S3** | Live activation (`CARRIER_API_STATUS=live`) + any DHL credentials | **Coordinator (signed)** + Operator confirmation | Written — coordinator signature required |
| **S4-N** | Each additional batch_id added to `CARRIER_LIVE_ALLOWLIST` | Coordinator (per batch) | Written — batch_id must be named explicitly |
| **S5** | Configure `DHL_WEBHOOK_SECRET` in production | Coordinator + Operator | Written |
| **PLT** | Any PLT route activation (Phase L+) | Coordinator + separate phase sign-off | Separate protocol |

### Gate S3 — live activation requirements (additional)

Gate S3 approval must explicitly state:
- The specific `batch_id` authorised for the first live run
- That the operator has confirmed DHL Express credentials are valid
- That the label store is confirmed operational
- That the operator acknowledges real carrier charges will apply

A Gate S3 approval that does not name a specific `batch_id` is invalid.

---

## 10. Rollback triggers

The following conditions require immediate rollback without investigation delay.
Identify the cause only after the gate is closed.

### Immediate rollback to shadow (`CARRIER_API_STATUS=shadow`)

| Trigger | Action |
|---------|--------|
| Live POST returns 500 or 503 | Close to shadow immediately |
| DHL API returns authentication error | Close to shadow immediately |
| DHL API returns unexpected payload structure | Close to shadow immediately |
| `tracking_ref` absent from live POST response | Close to shadow, open incident |
| More than one AWB created for one `idempotency_key` | Close to shadow, open incident |

### Immediate rollback to pending (`CARRIER_API_STATUS=pending`)

| Trigger | Action |
|---------|--------|
| Shadow response contains `simulated: false` | **Critical** — close to pending, open incident |
| Shadow response contains `tracking_ref` not prefixed with `SIM-` | **Critical** — close to pending, open incident |
| Service startup fails after any gate change | Rollback to pending; if still failing, code revert (Phase M Level 2) |
| PZ regression drops below 160/160 at any stage | Close to pending, identify root cause before any re-activation |
| Any carrier route returns 500 in production health check | Close to pending |

### Rollback commands (reference)

```bash
# Rollback to shadow (from live)
# Edit .env: CARRIER_API_STATUS=shadow
sudo systemctl restart estrella-pz

# Rollback to pending (from shadow or live)
# Edit .env: CARRIER_API_STATUS=pending
# Also remove or blank: DHL_EXPRESS_API_KEY, DHL_EXPRESS_API_SECRET, DHL_EXPRESS_ACCOUNT_NUMBER
sudo systemctl restart estrella-pz

# Verify gate closed
curl -s http://localhost:8000/api/v1/carrier/status \
  -H "X-API-Key: $API_KEY" | python -m json.tool
# Required: carrier_api_status == "pending" (or "shadow" if shadow rollback)
```

---

## 11. Stop conditions

These conditions stop the activation protocol at any stage.  The protocol does not
resume until the condition is resolved and a coordinator approves resumption.

| Condition | Stage affected | Action |
|-----------|---------------|--------|
| Any shadow run returns `simulated: false` | Stage 2 | Stop; invariant violation; open incident |
| Any shadow `tracking_ref` not prefixed `SIM-` | Stage 2 | Stop; invariant violation; open incident |
| Fewer than 5 shadow runs available for soak table | Stage 2 → 3 transition | Do not proceed; complete soak first |
| PZ regression < 160/160 | Any | Stop; do not proceed until 160/160 restored |
| Gate approval not obtained | Any | Do not proceed until signed |
| Service startup failure after gate change | Any | Rollback; stop protocol |
| DHL API credentials fail validation in non-production | Stage 3 | Do not proceed to live |
| Label store not operational | Stage 3 | Do not proceed to live |
| Coordinator explicitly withdraws approval | Any | Stop; return to previous stage |
| Evidence artifact missing for current stage | Any | Do not proceed; produce artifact first |
| Any unexplained carrier ERROR in production logs | Any | Stop; investigate before proceeding |

---

## 12. Monitoring checklist

Apply at every stage from Stage 1 onward.  Operators should check these during and
after any carrier gate change.

### Service health

- [ ] `GET /api/v1/carrier/status` returns expected gate status
- [ ] Service response time for carrier routes is within normal range
- [ ] No `ERROR` or `CRITICAL` log lines referencing `carrier` since last restart
- [ ] Process manager reports service as running (not restarting)

### Carrier subsystem

- [ ] Shadow log count increases monotonically with each shadow run (no silent drops)
- [ ] Shadow log entries contain no `request_json` or `response_json` fields
- [ ] All shadow results: `simulated: true`, `tracking_ref` prefixed `SIM-`
- [ ] All live results (Stage 3+): `simulated: false`, `mode: live`
- [ ] No `tracking_ref` returned by `GET /api/v1/carrier/{batch_id}/shipment`
- [ ] `carrier_shipments.db` does not contain a `tracking_ref` column (schema check)

### PZ engine isolation

- [ ] `GET /api/v1/pz/status` returns 200
- [ ] No PZ ERROR logs introduced since last carrier gate change
- [ ] PZ regression 160/160 (run at every stage transition)
- [ ] Existing customs/clearance routes respond normally

### Auth and security

- [ ] `GET /api/v1/carrier/status` without API key returns 401
- [ ] `POST .../shipment` without API key returns 401
- [ ] Webhook endpoint (`POST /api/v1/carrier/webhook/dhl`) without secret returns
      503; with bad signature returns 401
- [ ] No carrier response body contains DHL credentials, account numbers, or
      signature material

---

## 13. Final live readiness checklist

Complete this checklist in full before Stage 3 (Gate S3) approval is requested.
Each item must be checkmarked by the operator, not by the coordinator.

### Code and deployment

- [ ] Phase M deployment verification checklist passed (working tree clean at deploy)
- [ ] `git log --oneline feature/dhl-carrier-phase-a ^main` reviewed — only Phases A-K
- [ ] Carrier tests 224/224 PASS (run within 24 hours of Stage 3 request)
- [ ] PZ regression 160/160 PASS (run within 24 hours of Stage 3 request)
- [ ] Phase L security review findings — all PASS, no blockers

### Shadow soak

- [ ] Minimum 5 distinct shadow batch_ids completed (Stage 2 soak table complete)
- [ ] All 5 rows: POST 200, simulated=true, tracking_ref starts SIM-, GET complete
- [ ] Idempotency confirmed — same request twice returns same idempotency_key
- [ ] Shadow log entries confirmed metadata-only (no JSON blob leakage)

### Live prerequisites

- [ ] DHL Express API credentials validated in non-production environment
- [ ] Label store (Phase D) operational and tested for AWB receipt
- [ ] Dashboard carrier panel shows LIVE badge distinct from SIMULATED
- [ ] Dashboard confirmation modal shows "This will submit a real DHL Express shipment"
- [ ] `CARRIER_LIVE_ALLOWLIST` contains exactly the one batch_id named in Gate S3

### Rollback readiness

- [ ] Operator has Phase M rollback commands memorised or open in a terminal
- [ ] Rollback to shadow tested in staging (Gate S3 prerequisite)
- [ ] Coordinator is reachable during the Stage 3 activation window
- [ ] Agreed rollback trigger thresholds documented and operator-acknowledged

### Approvals

- [ ] Gate S1 on file
- [ ] Gate S2 on file
- [ ] Gate S3 signed and on file — names specific batch_id, confirms DHL charges
      acknowledged, confirms label store operational

**Only after all items above are checked may Stage 3 activation begin.**

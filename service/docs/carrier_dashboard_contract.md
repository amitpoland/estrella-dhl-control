# Carrier Dashboard / Backend Contract

**Phase K — documentation only**
**Date:** 2026-05-10
**Status:** APPROVED FOR IMPLEMENTATION REFERENCE

This document defines the complete contract between any carrier dashboard UI and the
backend carrier subsystem.  It covers every implemented route, every planned (not yet
implemented) route, every security rule, and every UX constraint an operator panel must
respect.

Coordinators must approve any deviation from this contract before code is written.

---

## 1. Overview

The carrier subsystem exposes DHL Express outbound-shipment functionality through a
three-state gate (`pending` → `shadow` → `live`).  The dashboard must reflect the
current gate state at all times and must never offer write actions that the backend will
reject.

### Gate states

| State | Meaning | Backend write routes |
|-------|---------|----------------------|
| `pending` | Not activated. Default on all deployments. | Return **503** — no shipment creation possible |
| `shadow` | Simulated mode. Adapter is `DhlExpressShadowAdapter`. | Write routes active; all results are synthetic (`simulated: true`) |
| `live` | Real DHL calls. Requires batch_id on allowlist + credentials set. | Write routes active; real AWBs issued |

The PLT gate (`carrier_plt_status`) is independent and follows the same three-state
model.  PLT UI is **NOT IMPLEMENTED** — see Section 7.

---

## 2. Current backend routes

All implemented routes share the prefix `/api/v1/carrier`.  Authentication is
`X-API-Key` header on every route (see Section 8).

### Route table

| Method | Path | Auth | Gate check | Implemented |
|--------|------|------|------------|-------------|
| `POST` | `/api/v1/carrier/{batch_id}/shipment` | X-API-Key | 503 if `pending` | ✅ Phase J |
| `GET`  | `/api/v1/carrier/{batch_id}/shipment` | X-API-Key | 503 if `pending` | ✅ Phase J |
| `GET`  | `/api/v1/carrier/shadow/log` | X-API-Key | None (always active) | ✅ Phase J |
| `GET`  | `/api/v1/carrier/status` | X-API-Key | None (always active) | ✅ Phase J |
| `POST` | `/api/v1/carrier/webhook/dhl` | DHL-Signature HMAC | 503 if secret unconfigured | ✅ Phase G |

The webhook route (`/webhook/dhl`) is **not dashboard-facing**.  It is excluded from
`include_in_schema` and must never be called from operator UI.

### Route ordering note

`GET /api/v1/carrier/shadow/log` and `GET /api/v1/carrier/status` are registered on
the shadow router **before** the actions router.  This ensures static path segments
(`shadow`, `status`) are matched before the dynamic `{batch_id}` pattern.  The
dashboard must not rely on path ordering — it must use exact URLs.

---

## 3. Shipment create flow

### Endpoint

```
POST /api/v1/carrier/{batch_id}/shipment
```

### Auth

`X-API-Key: <key>` header required.  Returns **401** if missing or invalid.

### Gate behavior

Returns **503** if `carrier_api_status == "pending"`.  The response body contains
`"pending"` in the detail message.  The dashboard **must** disable the "Create
shipment" button when status is `pending` and show a disabled-state label
(see Section 10).

### Request body

```json
{
  "shipper_account": "string",
  "recipient_address": { "...": "..." },
  "declared_value": 123.45,
  "currency": "EUR",
  "weight_kg": 2.5,
  "dimensions": { "length": 10, "width": 10, "height": 10 },
  "special_instructions": "optional string or null"
}
```

All fields except `special_instructions` are required.  Missing required fields return
**422** from Pydantic validation before the coordinator is reached.

### Idempotency

The backend computes a deterministic `idempotency_key` from `batch_id`,
`shipper_account`, `weight_kg`, `declared_value`, and `currency`.  Submitting the
same request twice returns the same `idempotency_key` and does not double-create.

The dashboard must send the same request body for the same batch — do not
randomise any field to force a re-send.

### Success response — shadow mode

```json
{
  "batch_id": "BATCH-2026-001",
  "idempotency_key": "a3f9...64-char-hex...",
  "mode": "shadow",
  "state": "complete",
  "tracking_ref": "SIM-ABCD1234",
  "simulated": true
}
```

- `mode` will always be `"shadow"` until `CARRIER_API_STATUS=live`.
- `simulated: true` in shadow mode; `false` in live mode.
- `tracking_ref` in shadow mode always starts with `SIM-` — it is a synthetic
  reference, never a real AWB.

### Success response — live mode (future)

```json
{
  "batch_id": "BATCH-2026-001",
  "idempotency_key": "...",
  "mode": "live",
  "state": "complete",
  "tracking_ref": null,
  "simulated": false
}
```

`tracking_ref` is returned by the POST endpoint in live mode but is **never stored in
the shipments DB** — it is returned in the response only.  The dashboard must save it
locally if needed; a subsequent GET will not return it (structural DB invariant — the
column is absent from `carrier_shipments`).

### Error responses

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid X-API-Key |
| 422 | Validation failure (missing fields, bad types) |
| 422 | CarrierGateError — e.g. batch_id not on live allowlist, previously-failed shipment |
| 503 | `carrier_api_status == "pending"` |

### Operator confirmation requirement

The dashboard **must** show a confirmation modal before calling this endpoint.  The
modal must display: batch_id, declared_value, currency, weight_kg, and current mode
(`shadow` or `live`).  In live mode the confirmation must additionally state:
"This will submit a real DHL Express shipment request."

---

## 4. Shipment status flow

### Endpoint

```
GET /api/v1/carrier/{batch_id}/shipment
```

### Auth

`X-API-Key` required.  Returns **401** if missing or invalid.

### Gate behavior

Returns **503** if `carrier_api_status == "pending"`.

### Success response

```json
{
  "batch_id": "BATCH-2026-001",
  "idempotency_key": "a3f9...64-char-hex...",
  "mode": "shadow",
  "state": "complete",
  "simulated": true,
  "error": null
}
```

**`tracking_ref` is intentionally absent.**  This is a structural invariant — the
column does not exist in `carrier_shipments`.  The dashboard must not attempt to read
or display a tracking reference from this endpoint.  The only source of `tracking_ref`
is the POST response at creation time.

### State values

| `state` | Meaning | Dashboard display |
|---------|---------|-------------------|
| `pending` | In-flight (crash-recovery anchor) | Show spinner |
| `submitted` | Submitted to adapter | Show spinner |
| `complete` | Done | Show success badge |
| `failed` | Terminal failure | Show error; surface `error` field |

### Error responses

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid X-API-Key |
| 404 | No shipment recorded for this batch_id |
| 503 | `carrier_api_status == "pending"` |

---

## 5. Shadow log flow

### Endpoint

```
GET /api/v1/carrier/shadow/log
```

### Auth

`X-API-Key` required.  Returns **401** if missing or invalid.

### Gate behavior

**No gate check.**  This endpoint is active regardless of `carrier_api_status`.  It is
safe to call when status is `pending` (it just returns an empty or pre-existing log).

### Query parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `batch_id` | string | — | — | Filter entries to a specific batch |
| `limit` | integer | 100 | 1–500 | Maximum entries to return |

### Success response

```json
{
  "entries": [
    {
      "id": 42,
      "batch_id": "BATCH-2026-001",
      "idempotency_key": "a3f9...64-char-hex...",
      "created_at": "2026-05-10T14:23:01.000Z"
    }
  ],
  "count": 1
}
```

**`request_json` and `response_json` are intentionally absent from every entry.**
The raw shadow payloads are stored in the DB for internal audit only and are never
surfaced to the dashboard.  The dashboard must not attempt to display or export
these fields.

### Error responses

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid X-API-Key |
| 422 | `limit` out of range (< 1 or > 500) |

---

## 6. Carrier status flow

### Endpoint

```
GET /api/v1/carrier/status
```

### Auth

`X-API-Key` required.  Returns **401** if missing or invalid.

### Gate behavior

**No gate check.**  Always returns 200, including when `carrier_api_status == "pending"`.
This is the correct poll target for the dashboard to determine which UI controls to
enable or disable.

### Success response

```json
{
  "carrier_api_status": "pending",
  "carrier_plt_status": "pending"
}
```

Possible values for each field: `"pending"`, `"shadow"`, `"live"`.

### Dashboard polling recommendation

Poll `GET /api/v1/carrier/status` on page load and on a configurable interval
(suggested: 60 s).  Drive all write-button enabled/disabled state from the polled
`carrier_api_status` value — do not cache gate state across page loads.

### Error responses

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid X-API-Key |

---

## 7. Planned PLT UI — NOT IMPLEMENTED

The PLT (Paperless Trade) subsystem has backend logic (Phases F–H: storage, eligibility
checker, document packager) but **no API routes yet**.  The following items are
**NOT IMPLEMENTED** and must not appear in the dashboard until routes exist and are
approved by a coordinator.

| Planned action | Status |
|----------------|--------|
| `POST /api/v1/carrier/plt/{batch_id}/eligibility` | NOT IMPLEMENTED |
| `POST /api/v1/carrier/plt/{batch_id}/package` | NOT IMPLEMENTED |
| `GET  /api/v1/carrier/plt/{batch_id}/package` | NOT IMPLEMENTED |
| PLT eligibility badge in shipment row | NOT IMPLEMENTED |
| PLT document upload UI | NOT IMPLEMENTED |
| PLT country allowlist display | NOT IMPLEMENTED |
| PLT status indicator (using `carrier_plt_status`) | NOT IMPLEMENTED |

The `carrier_plt_status` field is returned by `GET /api/v1/carrier/status` today, but
it must only be displayed as an informational label — no interactive PLT controls
may be wired to it until Phase L or later routes are implemented and approved.

---

## 8. Authentication model

### Mechanism

All carrier routes use `X-API-Key` header authentication (`require_api_key` from
`app/core/security.py`).  This is the same mechanism used by `routes_pz.py`.

### Header

```
X-API-Key: <configured api key>
```

### Dev mode bypass

If `settings.api_key` is `None` (dev environment with no key set), `require_api_key`
returns immediately without checking the header.  This must never be the case in
production.

### Auth failure

Returns **401** with `{"detail": "Invalid or missing API key."}`.  FastAPI
short-circuits all dependency resolution on auth failure — the coordinator and DB
dependencies are never invoked.

### Webhook auth — separate model

`POST /api/v1/carrier/webhook/dhl` uses HMAC-SHA256 via the `DHL-Signature` header.
This is entirely separate from `X-API-Key` and is not dashboard-facing.  Do not
expose webhook configuration in the operator panel.

---

## 9. Security constraints

These constraints are enforced by the backend and must not be worked around by the UI.

### No label bytes or PDFs in responses

No carrier route returns binary data, base64-encoded label files, or PDF content.
The telemetry invariant guards (`InvariantViolation`) enforce this internally.
The dashboard must not attempt to display or download labels from carrier routes.

### No tracking reference in GET /shipment

`GET /api/v1/carrier/{batch_id}/shipment` does not return `tracking_ref`.  This is a
structural DB invariant — the column is absent.  AWB references are held in the secure
label store (Phase D) and are not accessible via dashboard routes.

### No raw shadow payload in log

`GET /api/v1/carrier/shadow/log` returns metadata only.  The `request_json` and
`response_json` columns are excluded from the response by design.  The dashboard must
not construct client-side queries that attempt to access these fields.

### No live calls without allowlist

Even when `carrier_api_status == "live"`, a shipment creation will fail (422,
`CarrierGateError`) if the `batch_id` is not in `CARRIER_LIVE_ALLOWLIST`.  The
dashboard must surface this error clearly rather than silently retrying.

### Simulated-mode visual distinction

When `simulated: true` is present in a POST response, the dashboard must display a
visible "SIMULATED" or "SHADOW" badge on the shipment record.  Shadow records must
never be presented with the same visual treatment as real shipments.

### No credential display

Carrier API keys, DHL account numbers, and webhook secrets must never be exposed in
dashboard responses or UI.  The status endpoint returns gate state only — no
credential values.

### HMAC timing attack protection

The webhook signature verification uses `hmac.compare_digest` internally.
This is not relevant to dashboard UI but must not be bypassed in any future webhook
display feature.

---

## 10. Disabled-state UX rules

These rules govern when dashboard controls must be disabled and what label to show.

### Write controls (Create shipment button)

| Condition | Control state | Label shown to operator |
|-----------|--------------|-------------------------|
| `carrier_api_status == "pending"` | **Disabled** | "Carrier not activated" |
| Auth missing / 401 from status poll | **Disabled** | "Not authenticated" |
| Status poll failed (network error) | **Disabled** | "Status unavailable" |
| `carrier_api_status == "shadow"` | **Enabled** | "Shadow mode (simulated)" |
| `carrier_api_status == "live"` | **Enabled** | "Live — real DHL" |

### Read controls (View status, shadow log)

Read controls (`GET` endpoints) may be displayed at all times but must show an
appropriate empty state when the backend returns 404 or an empty list.  They must
not be disabled based on gate status — the log and status endpoints are always active.

### Confirmation modal — required before POST

Before any `POST /api/v1/carrier/{batch_id}/shipment` call the operator panel must
present a modal with:

- Batch ID
- Declared value and currency
- Weight and dimensions
- Current mode (shadow / live)
- In live mode: explicit warning "This will submit a real DHL Express shipment"
- Two buttons: **Confirm** and **Cancel**

The POST must not be sent if the operator dismisses the modal.

### Error state display

| HTTP status | Dashboard action |
|-------------|-----------------|
| 401 | Show "Authentication error — check API key" banner |
| 404 (GET shipment) | Show "No shipment recorded for this batch" inline |
| 422 (POST shipment) | Show the `detail` string from the response body |
| 503 | Show "Carrier API not available (pending)" — disable write controls |
| Network timeout | Show "Request timed out — carrier status unknown" — disable write controls |

---

## 11. Rollout recommendation

The following sequence is recommended for operator panel rollout.  Each step requires
coordinator sign-off before proceeding.

### Step 1 — Read-only panel (safe to ship now)

- `GET /api/v1/carrier/status` → display gate status badge
- `GET /api/v1/carrier/shadow/log` → display shadow log table (metadata only)
- All write controls disabled with "pending" label
- No POST calls wired yet

### Step 2 — Shadow mode panel (after `CARRIER_API_STATUS=shadow` in staging)

- Wire "Create shipment" button to `POST /api/v1/carrier/{batch_id}/shipment`
- Show confirmation modal (required — see Section 10)
- Display POST response: mode, state, simulated badge, idempotency_key
- `GET /api/v1/carrier/{batch_id}/shipment` for status polling
- All shadow results visually distinct from real records

### Step 3 — Live mode panel (after coordinator approval + allowlist configured)

- No dashboard code changes required beyond confirming `simulated: false` display
- Live shipment confirmation modal must show "real DHL" warning
- Confirm `CARRIER_LIVE_ALLOWLIST` is set before enabling live for any batch
- Ensure label store (Phase D) integration is in place for AWB handling

### Step 4 — PLT panel (NOT IMPLEMENTED — future phase)

- Wait for PLT API routes (Phase L or later)
- Eligibility check UI
- Document package status
- Country allowlist display

---

## 12. Forbidden UI patterns

The following patterns are explicitly forbidden.  Any PR that introduces them must be
rejected without review.

| Pattern | Why forbidden |
|---------|--------------|
| Calling `POST /api/v1/carrier/webhook/dhl` from UI | Webhook is DHL→server only; HMAC key must never be in browser |
| Displaying `tracking_ref` from `GET /shipment` | Column absent from DB; field will never appear |
| Displaying `request_json` / `response_json` from shadow log | Never returned by backend; log entries are metadata-only |
| Sending binary data (PDF, label) through carrier routes | Backend invariant guards reject it; no carrier route accepts bytes |
| Polling shipment status without X-API-Key | Returns 401; dashboard must always include the key |
| Enabling write controls when status poll is `pending` | Gate returns 503; UI must disable proactively |
| Auto-submitting POST without confirmation modal | Operator confirmation is mandatory for all write actions |
| Caching `carrier_api_status` across page loads | Gate state can change; always re-poll on load |
| Constructing `idempotency_key` in the frontend | Key is computed server-side; frontend must use the value returned by POST |
| Treating `simulated: true` records as real shipments | Shadow records must carry a visible simulated badge at all times |
| Calling PLT endpoints | No PLT routes exist yet — see Section 7 |
| Exposing DHL credentials or account number in UI | Never returned by backend; must not be read from .env or config by frontend |

# ADR-026: Outbound DHL Label — Extend Existing Carrier Scaffold (Phase D)

**Status:** Proposed
**Date:** 2026-06-01
**Deciders:** Amit
**Related:** ADR-025 (E2E workflow), docs/ATLAS_WORKFLOW_MAP.md §1C (WF4.5 outbound dispatch)

---

## Context

The existing carrier subsystem (Phase C, merged) provides a complete scaffold for
DHL Express shipment creation:

- `POST /api/v1/carrier/{batch_id}/shipment` endpoint — registered and gated
- `CarrierCoordinator` — idempotency, shadow log, PENDING/COMPLETE state machine
- `DhlExpressLiveAdapter` — passes allowlist + credential guards, then **raises
  `NotImplementedError`** with comment "Phase D will add the httpx call,
  idempotency write, and label handling." (`adapters/live.py:49`)
- `DhlExpressShadowAdapter` — deterministic simulation, no HTTP, used today
- `CarrierResponseRedactor` — strips label bytes, credentials, AWBs before
  any persistence
- `ShipmentRequest` / `ShipmentResult` data models
- PLT eligibility checker (country + invoice + customs doc gates)
- Gate fields: `carrier_api_status` (`pending` / `shadow` / `sandbox` / `live`),
  `carrier_plt_status`, `carrier_live_allowlist`, `DHL_EXPRESS_API_*` creds
  (all in `config.py:305-324`, all unset/pending in production today)

The outbound dispatch states exist in the inventory engine:
`DIRECT_DISPATCH_READY → CLIENT_DISPATCHED → CLOSED` (plus the
`WAREHOUSE_STOCK → SALES_TRANSIT → CLOSED` path for invoiced goods).

`mark-direct-dispatch` (`routes_lifecycle.py:469`) transitions scan_codes to
`DIRECT_DISPATCH_READY` with customs/PZ clearance evidence and operator sign-off.

No label has ever been generated. `dispatch_reference` is a free-text field on
inventory state events used for RMA/outbound waybill references today.

---

## Decision

**Extend the existing Phase-C scaffold to implement Phase D.** Do NOT rebuild.

The architecture is correct and the integration boundary is well-defined. The
Phase-D deliverable is the single `NotImplementedError` in `DhlExpressLiveAdapter`
and the downstream AWB storage — everything else is already built.

Two dispatch paths are adopted (spec locked in §1C of ATLAS_WORKFLOW_MAP.md):

### Path-LIVE (real DHL Express API)

Activates when `carrier_api_status=live` AND all three DHL Express credentials are
set AND the batch is in `carrier_live_allowlist`. Uses the existing coordinator +
live adapter; Phase D adds:

1. `httpx` call to `https://express.api.dhl.com/shipments`
2. Label bytes parsed from response (`labelData` / `shipmentLabel`) and stored
   via a new `label_store` (not the redactor log)
3. Real AWB stored in a dedicated field (see AWB storage below)
4. `client_carrier_accounts.account_number` consumed as `shipper_account`
   (currently populated but not wired — GAP-8)

### Path-DOC (document package — always-works floor)

Generates a PDF package (CN23 + commercial invoice + packing list) that the
operator prints and hands to DHL at a service point. No credentials, no API, no
AWB — the AWB is obtained physically. This path works in every environment and is
the guaranteed fallback when Path-LIVE is unavailable or fails.

### Button fallback logic

```
operator clicks "Generate DHL label" (WF4.5)
  [operator selects box_type_id from box_types master — mandatory before submission]
  [total_weight_kg = sum(packing_lines.gross_weight) + box.tare_weight_kg]
  [receiver address = ship_to_* if ship_to_street set; otherwise bill_to_* + advisory]
  if carrier_api_status=sandbox AND creds:
    → Path-LIVE against DHL test endpoint (allowlist NOT enforced, non-billable)
  elif carrier_api_status=live AND creds AND batch in allowlist:
    → Path-LIVE (prod); on failure → fall back to Path-DOC + Inbox proposal
  else:
    → Path-DOC
```

**No new boolean flag.** Gate = existing `carrier_api_status` progression
(`pending → shadow → sandbox → live`), which is already operator-driven and deliberate.

### `carrier_api_status` routing

| Value | Adapter | HTTP | Endpoint | Allowlist enforced | Billable |
|---|---|---|---|---|---|
| `pending` | — | 503 returned immediately | — | — | — |
| `shadow` | `DhlExpressShadowAdapter` | No | — | No | No |
| `sandbox` | `DhlExpressLiveAdapter` | Yes | `https://express.api.dhl.com/mydhlapi/test` | **No** | **No** |
| `live` | `DhlExpressLiveAdapter` | Yes | `https://express.api.dhl.com/mydhlapi` (prod) | **Yes** | Yes |

`sandbox` uses the same live adapter code path as `live` but against DHL's non-billable test endpoint (`https://express.api.dhl.com/mydhlapi/test`). Sandbox credentials ≠ production credentials — they are provisioned separately by DHL and must be treated as distinct secrets. Auth = HTTP Basic `base64(DHL_EXPRESS_API_KEY:DHL_EXPRESS_API_SECRET)` where `API_KEY` is the username and `API_SECRET` is the password, for both `sandbox` and `live`.

The `sandbox` step is the mandatory integration-test gate before production enablement.

---

## Options considered

### Option A — Rebuild with a new DHL client library

Rejected. The existing scaffold (coordinator, idempotency, shadow log, redactor,
PLT models) is well-tested (381/381 carrier baseline). Rebuilding introduces risk
without benefit; the only missing piece is the single `httpx` call.

### Option B — Path-DOC only (no API)

Rejected as sole strategy. Path-DOC is the fallback floor, not the destination.
Path-LIVE is the correct outbound for production dispatch at scale and enables
automatic tracking via DHL.

### Option C (chosen) — Path-DOC as floor + Path-LIVE via existing scaffold

The Phase-C scaffold is the right architecture. Phase D completes it.

---

## Prerequisites and gaps (per ATLAS_WORKFLOW_MAP.md §1C)

| Item | Tag | Status |
|---|---|---|
| `company_profile.legal_name + address` for shipper | REQUIRED | No row in production. Must be populated before either path can produce a valid document. |
| `DHL_EXPRESS_API_KEY`, `DHL_EXPRESS_API_SECRET`, `DHL_EXPRESS_ACCOUNT_NUMBER` | Path-LIVE | Not set in production. Operator configures via `.env`. |
| `carrier_api_status` progression | Path-LIVE | Currently `"pending"`. Operator advances to `"shadow"` → `"sandbox"` → `"live"`. `sandbox` validates end-to-end against DHL test endpoint before production enablement. |
| `client_carrier_accounts.account_number` per-client DHL account | Path-LIVE | GAP-8 — table populated (5 rows), not consumed by carrier subsystem. Phase D wires it. |
| Receiver label address | BOTH | Primary: `customer_master.ship_to_street/city/zip/country/name`. Fallback: `bill_to_*` when `ship_to_street` is absent, with advisory proposal `ship_to_missing` written to Inbox. Currently 12/61 customers have `ship_to_street`. |
| `box_type_id` → dimensions + tare | **BOTH** | **REQUIRED** — operator selects box type from `box_types` master (`master_data.sqlite`). `box_types` table: `id, code, name, length_cm, width_cm, height_cm, tare_weight_kg`. Missing/unknown → 422 `{field:"box_type"}`. Total weight = `sum(packing_lines.gross_weight) + box.tare_weight_kg`. |
| Incoterm | BOTH (CN23) | GAP-7 — `proforma_draft.incoterm` often NULL. Required on CN23. |
| PLT eligibility | Path-LIVE international | Gated by `carrier_plt_status` (currently `"pending"`); existing `plt/eligibility.py` checks invoice, customs doc, country. |

---

## AWB storage (assumption — to confirm at Phase-D PR)

**Assumption:** the real AWB returned from Path-LIVE is stored in a **dedicated
field on a `dispatch_record`** (new table row, additive migration, atomic
writer/reader) rather than overloaded into the free-text `dispatch_reference`
field on `inventory_state` transition events.

Rationale: `dispatch_reference` is shared with RMA/return references; a
structured `awb` column enables downstream tracking queries, label re-download,
and Inbox proposal triggers (e.g., if DHL reports no tracking after 24h).

This assumption must be confirmed — and a short schema ADR addendum filed — before
Phase-D implementation begins.

---

## Credentials and security

DHL Express credentials (`DHL_EXPRESS_API_KEY`, `DHL_EXPRESS_API_SECRET`,
`DHL_EXPRESS_ACCOUNT_NUMBER`) are stored in `.env` and accessed via
`config.py:315-318`. They are **never** logged, printed, or surfaced to the UI
(enforced by the `CarrierResponseRedactor` credential strip table).

**Sandbox credentials ≠ production credentials.** DHL provisions them
separately; they must be stored under distinct env vars (or the same vars with
an explicit `sandbox` env profile). Production enablement is a separate DHL
step — sandbox access does not automatically grant live/billable access.

**Auth method:** HTTP Basic Authentication — `Authorization: Basic base64(KEY:SECRET)` —
where `KEY` (`DHL_EXPRESS_API_KEY`) is the **username** and `SECRET` (`DHL_EXPRESS_API_SECRET`)
is the **password**. Applies to both `sandbox` (`https://express.api.dhl.com/mydhlapi/test`)
and `live` (`https://express.api.dhl.com/mydhlapi`) modes.

**Path-LIVE integration test** runs in `sandbox` mode against the real DHL test
endpoint (`https://express.api.dhl.com/mydhlapi/test`). The `shadow` adapter is the
offline fallback only (deterministic sim, no HTTP, used when network access is
unavailable or creds are not yet provisioned). The `sandbox` gate enforces that a
real HTTP handshake has validated the adapter before any `live` promotion is attempted.

The `carrier_live_allowlist` (`config.py:312`) requires explicit opt-in per
batch. Live calls cannot fire for a batch not on this list even if all other gates
pass. This is the primary safety guard during Phase-D production testing.
The `sandbox` mode intentionally bypasses the allowlist — sandbox runs should not
require batch-by-batch approval since no real shipment is created.

---

## Invariants

- No live DHL call is made until `carrier_api_status=live` AND creds AND allowlist
  — **operator-only activation, not automated**
- Path-DOC works with no credentials in all environments — the floor is always
  available
- Existing carrier test suite (381/381) must remain green after Phase-D additions
- `CarrierResponseRedactor` must be updated if DHL introduces new label field
  names not currently in the strip table
- The shadow log does not persist label bytes (redacted) — this continues in live mode

---

## Consequences

**Easier:** Phase D is scoped and bounded — one `NotImplementedError` to replace,
one AWB storage decision, and wiring `client_carrier_accounts`. The rest of the
architecture is already built and tested.

**Harder:** DHL Express API contract must be confirmed (field names for label
response); CN23 / commercial invoice template must be designed for Path-DOC;
recipient address completeness advisory must be implemented.

**Revisit:** whether `carrier_live_allowlist` should be replaced by a
batch-level flag once Path-LIVE is proven; whether PLT should be auto-detected
from destination country rather than operator-gated.

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
- Gate fields: `carrier_api_status` (`pending` / `shadow` / `live`),
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
  if carrier_api_status=live AND creds AND batch in allowlist:
    → Path-LIVE; on failure → fall back to Path-DOC + Inbox proposal
  else:
    → Path-DOC
```

**No new boolean flag.** Gate = existing `carrier_api_status` progression
(`pending → shadow → live`), which is already operator-driven and deliberate.

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
| `carrier_api_status` progression | Path-LIVE | Currently `"pending"`. Operator advances to `"shadow"` then `"live"`. |
| `client_carrier_accounts.account_number` per-client DHL account | Path-LIVE | GAP-8 — table populated (5 rows), not consumed by carrier subsystem. Phase D wires it. |
| Recipient address completeness | BOTH | Advisory → Inbox when `ship_to_*` / `bill_to_*` are blank. |
| Dimensions (L×W×H) | Path-LIVE | Missing — no data source. Captured at label-generation time via UI input. |
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

The `carrier_live_allowlist` (`config.py:312`) requires explicit opt-in per
batch. Live calls cannot fire for a batch not on this list even if all other gates
pass. This is the primary safety guard during Phase-D testing.

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

# Campaign 02 — AWB Pipeline Verification Report

**Date**: 2026-06-13 (verification executed 2026-06-12)
**Campaign**: 02 — EJ Dashboard Portal — Authority Consolidation & Workflow Completion
**Track**: P3 Workflow Completion — AWB Pipeline Verification (VERIFY-ONLY, no redesign)
**Source of truth**: all reads against `C:\PZ-verify` @ `ff1f4b5` (= origin/main)
**Method**: verification agent + independent adversarial verdict per claimed gap

---

## Verdict summary

| Check | Status | Adversarial verdict |
|---|---|---|
| Backend route | VERIFIED | — |
| DHL integration (carrier gate) | VERIFIED | — |
| Label generation | VERIFIED | — |
| Address authority | **GAP** | isReal = TRUE (confirmed) |
| Tracking persistence | **GAP** | isReal = TRUE (confirmed) |

Overall: pipeline is structurally sound (3/5 verified, security gates intact). Two
confirmed gaps, both bounded, neither blocking current operations because the live
carrier path is still gated behind `carrier_api_status='pending'`.

---

## Verified components

### 1. Backend route — VERIFIED
`routes_carrier_actions.py:103-131` — `POST /api/v1/carrier/{batch_id}/shipment` is
registered with auth guard (`require_api_key`), request validation via
`ShipmentRequestBody`, and `CarrierCoordinator` dependency injection. Accepts
shipper_account, recipient_address, declared_value, currency, weight_kg, dimensions,
special_instructions.

### 2. DHL integration / carrier gate — VERIFIED
- `config.py:318` — `carrier_api_status` defaults to `'pending'`.
- `routes_carrier_actions.py:47-54` — `_get_carrier_config` raises HTTP 503 when
  `carrier_api_status='pending'`.
- `live.py:47-50` — `DhlExpressLiveAdapter.create_shipment` raises
  `NotImplementedError` (Phase D boundary).
- The gate cannot be bypassed: all routes depend on `_get_carrier_config`.

### 3. Label generation — VERIFIED
`routes_carrier_actions.py:174-270` — `POST /api/v1/carrier/{batch_id}/label-package`
is intentionally ungated (Path-DOC). Persists PDF/ZIP artifacts via
`LabelPackageResult.content`, emits audit advisories via `X-Label-Advisories` header,
uses `box_types` master for dimensions, generates invoice + packing list + CN23.

---

## Confirmed gaps

### GAP A — Address authority: shipment creation bypasses Customer Master

**Workflow class**: authority chain.
**Authority owner**: Customer Master.

Evidence:
- `routes_carrier_actions.py:92-98` — `ShipmentRequestBody` accepts a raw
  `recipient_address` dict; no `customer_id` field, no Customer Master integration.
- `routes_carrier_actions.py:110-118` — the dict is passed directly into
  `ShipmentRequest`; `resolve_delivery_address()` is never called.
- `doc_package.py:896-897` — label generation DOES use `resolve_delivery_address()`
  from `customer_master.py`; customer-resolution infrastructure already exists
  (`_resolve_customer_from_batch` at `doc_package.py:842`).

Inconsistency: shipment creation bypasses customer authority while label generation
honors it — two different address truths can enter the same shipment.

Proposed fix (architect-reviewed, NOT implemented — VERIFY-ONLY track):
1. Route shipment creation through `resolve_delivery_address` when `customer_id` present.
2. Document the legitimacy of the raw-dict path for shipments without a `customer_id`.

**GATE 4 disposition**: ISSUE — prepared; filing was blocked by session permission
policy (external write requires operator approval). Ready-to-file body below.

### GAP B — Tracking persistence: no outbound AWB registration at SUBMITTED

**Workflow class**: persistence / lifecycle integration.
**Authority owner**: PZ lifecycle / tracking subsystem.

Evidence:
- `shipment_db.py:7-10` — `tracking_ref` (real AWB) intentionally absent from
  `carrier_shipments` schema ("Live AWBs must never be persisted here — they belong
  in the secure label store (Phase D)").
- `shipment_db.py:74-78` — live shipment results actively rejected from
  `carrier_shipments`.
- `tracking_db.py:31-50` — `shipment_tracking_events` exists for inbound tracking,
  but no code path registers outbound AWBs.
- `coordinator.py:219` / `shadow.py:37` — at the SUBMITTED transition there is no
  call to `tracking_db.record_event()` or equivalent.
- The "secure label store (Phase D)" referenced in `shipment_db.py` comments does
  not exist in the current codebase — confirming the gap.

Proposed fix (NOT implemented — VERIFY-ONLY track): add outbound AWB registration to
`tracking_db` when a shipment reaches SUBMITTED state, mirroring the inbound path.

**GATE 4 disposition**: ISSUE — prepared; filing was blocked by session permission
policy (external write requires operator approval). Ready-to-file body below.

---

## Ready-to-file issue bodies (operator action required)

### Issue 1 title
`AWB pipeline: shipment creation bypasses Customer Master resolve_delivery_address (address authority gap)`

Body: GAP A section above, verbatim. Suggested labels: `governance`, `follow-up`.

### Issue 2 title
`AWB pipeline: no outbound AWB registration to tracking_db at SUBMITTED (tracking persistence gap)`

Body: GAP B section above, verbatim. Suggested labels: `governance`, `follow-up`.

---

## Closure statement

AWB Pipeline Verification (Campaign 02 P3) is COMPLETE as a verification deliverable.
The pipeline is verified end-to-end for route registration, carrier gating, and label
generation. The two confirmed gaps are documented, classified by workflow class per
Lesson I, and carry GATE 4 dispositions pending operator approval to file the issues.
No code was changed by this track (VERIFY-ONLY mandate honored).

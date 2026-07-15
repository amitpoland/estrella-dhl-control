# ADR: Proforma CMR/transport documents consume the canonical outbound shipment authority

Status: Accepted (operator decision, Proforma CMR/Shipping campaign PR-5, 2026-07-15).
Decision: The CMR and Packing List transport facts (outbound AWB, carrier, service, CMR number, gross weight) come from the **canonical outbound carrier-shipment authority** and a new **draft weight-override** — never from the import batch identifier. No second AWB or weight writer is introduced.

## Context

The CMR preview was assembled from the wrong authority:

- `cmrPreviewData.carrier.awb` was set to `liveDraft.batch_id` — the **import** batch
  identifier (`SHIPMENT_<import_tracking>_<mm>_<hash>`), not the booked outbound AWB.
- `cmr_no` was `CMR-EJ-<batch_id>` — derived from the same import identity.
- carrier name/service were a draft field (always `—`) and a hardcoded
  `'EXPRESS WORLDWIDE'`.
- gross weight was hardcoded `null`; there was **no** manual weight-override path.

The correct outbound authority already existed and was already fetched into the page:
`carrierShipment` from `GET /api/v1/carrier/{batch_id}/shipment` (store
`carrier_shipments.db`, column `tracking_ref`), shown correctly in the Logistics tab
but never wired into the CMR builder. The sibling proforma `docData.carrier` block was
already fixed correctly (`awb: null, batch_ref: batch_id`) — only the CMR preview
lagged.

Weight authority: extracted packing weight lives in `packing_lines.net_weight /
gross_weight` (GRAMS, pinned by `test_weight_unit_authority.py`); the DHL booking weight
(`carrier_shipments.weight_kg`, operator kg) is a separate authority. There was no
operator manual override for the transport document.

## Decision

1. **Outbound AWB / carrier / service — one authority.** The CMR carrier block is
   sourced from `carrierShipment` (the `carrier_shipments` outbound record):
   `awb = tracking_ref`, `name = carrier`, `service = service_code`,
   `dim_cm = dimensions`. When no outbound shipment is booked the carrier block is
   `null` and the renderer shows an honest "Carrier AWB not yet assigned" placeholder.
   The import `batch_id` remains available **only** as internal provenance
   (`carrier.batch_ref` / `cmrPreviewData.batch_ref`) and must never be shown as the AWB.

2. **CMR number is a STABLE transport-document identifier, INDEPENDENT of the AWB**
   (operator ruling, pre-merge): `cmr_no = CMR-EJ-<export_shipment_id>` where the
   export shipment reference is the draft's stable shipment key (`batch_id`). A
   re-booking changes the AWB (`tracking_ref`) but must NOT change the legal document
   identity, so the CMR number is deliberately not equal to the AWB. The AWB is a field
   **referenced inside** the CMR (Box 16), never the document number. No sequential CMR
   counter / new numbering store is introduced (that would be a separate authority
   requiring its own ADR).

   *One resolver:* a single `_transport` projection (TransportDocumentAuthority) turns
   Draft + carrierShipment into the transport-document object (export shipment id,
   outbound AWB, carrier, service, tracking, status, effectiveWeight, cmr_number). The
   CMR, Packing List and Logistics panel consume ONLY this object — the UI never
   assembles transport identity from multiple API responses.

3. **Effective weight = extracted (historical) + manual override (effective on save).**
   Extracted packing weight (grams→kg) stays the historical evidence and is never
   overwritten. A manual override, when present, is the effective value. Gross falls
   back to the DHL booking weight when no manual value exists. Per-category weight is
   never invented by dividing a shipment total. The CMR and Packing List consume the
   **same** effective-weight projection.

4. **Manual weight override — smallest additive extension, no second writer.** Seven
   additive columns on `proforma_drafts` (`manual_net_weight`, `manual_gross_weight`,
   `weight_override_reason`, `weight_confirmed_at`, `weight_confirmed_by`,
   `weight_source_revision`, and `weight_override_source` — provenance of the last
   action: `manual` on save, `cleared` on clear; all weights kg), written by the single
   new `set_draft_weight_override` / `clear_draft_weight_override` writers through the
   shared optimistic-lock + audit path.

   Weight precedence is fixed and never inferred, averaged, or divided:
   net = manual → packing → missing; gross = manual → carrier booking → packing →
   missing. A missing value is surfaced with a reason ("Packing contains no extracted
   net weight" / "No outbound shipment linked"), never `0` or `—`. `POST /draft/{id}/weight-override` (422 on invalid,
   409 on stale lock) and `POST /draft/{id}/clear-weight-override`. A re-import changes
   the extracted-weight `source_revision`; the projection flags drift **without**
   overwriting the override. Clear restores the extracted value.

No live DHL booking/label/pickup call is made by any document render or by the weight
endpoints.

## Consequences

- Fixes the AWB-authority conflict (batch_id vs tracking_ref) by consolidating the CMR
  onto the single existing outbound authority — no third writer.
- Adds the missing manual weight-override layer without a duplicate weight writer.
- CMR numbering is now defined and stable; a future sequential scheme remains a separate,
  separately-ADR'd decision.

## Rollback

Additive and reversible: revert the PR-5 commit. The six draft columns are additive
(existing rows unaffected). No production data migration or correction is performed.

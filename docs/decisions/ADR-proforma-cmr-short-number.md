# ADR: Short deterministic CMR document number (no second numbering authority)

Status: Accepted (operator decision, Transport/Document-Authority repair campaign, 2026-07-16).
Decision: The CMR document number is a **short, deterministic display token derived from
the existing carrier-shipment stable id** — `CMR-EJ-<first 10 hex of export_shipment_id,
uppercased>`. The full `export_shipment_id` remains the underlying authority and stays in
audit/projection metadata; it is never printed. No mutable counter and no second numbering
authority are introduced.

## Context

`ADR-proforma-cmr-transport-authority.md` established that the CMR number comes from the
carrier shipment's own stable identifier (`export_shipment_id` = `carrier_shipments`
primary key = the sha256 `idempotency_key`), independent of the AWB. The frontend printed
that value verbatim:

```
cmr_number = `CMR-EJ-${export_shipment_id}`
→ CMR-EJ-92bd984dbdb70c24f5c1bbe5440a7f4bb19253da303974a7ab6045f9e92fc1ae
```

A 64-hex CMR number is unusable on a paper transport document. A shorter human-sized
identifier is required — **without** creating a second numbering authority or a mutable
counter (either would fork the transport-document identity).

## Decision

1. **One derivation, backend-owned.** `service/app/services/carrier/cmr_number.py` exposes
   `cmr_document_number(export_shipment_id)` → `CMR-EJ-<first 10 chars, uppercased>` (and
   `short_export_id`). The carrier read model (`GET /carrier/{batch}/shipment`) returns the
   computed `cmr_number`; the CMR/Packing/Logistics renderers consume that field and never
   re-derive the format. The full `export_shipment_id` continues to be returned as audit
   provenance.

2. **Format.** `CMR-EJ-` + the first 10 characters of `export_shipment_id`, uppercased.
   Example: `92bd984dbdb70c24…` → `CMR-EJ-92BD984DBD`. `export_shipment_id` is a sha256
   hexdigest, so its first 10 characters are 40 uniformly-distributed bits.

3. **Properties (pinned by `test_cmr_number.py`).**
   - *Deterministic* — same id ⇒ same number.
   - *Rebook-stable* — a same-parameters re-book keeps `export_shipment_id` (one row per
     idempotency_key, AWB updated in place), so the CMR number does not move. A materially
     different re-book is a new shipment record with a new id (and a new CMR number) — the
     same known limitation documented in the transport-authority ADR.
   - *AWB-independent* — the AWB (`tracking_ref`) is referenced inside the CMR (Box 16),
     never the document number.
   - *Honest-missing* — no `export_shipment_id` ⇒ `cmr_number` is null and the renderer
     shows the reason; the import `batch_id` is never substituted.

4. **Collision resistance.** 40 bits ≈ 1.1×10¹² space. Birthday-bound collision probability
   for `N` distinct shipments ≈ `N² / 2^41`: ~4.5×10⁻⁵ at N=10 000, ~0.45 % at N=100 000 —
   negligible at this system's shipment volume (hundreds–low thousands). `test_cmr_number.py`
   asserts zero collisions across a large synthetic sha256 sample. If volume ever approaches
   the birthday bound, widening `_SHORT_LEN` is a one-line, separately-ADR'd change; it does
   not require a new authority.

## Known limitation — legacy-batch rebook creates a new shipment record (2026-07-16 review POST-2)

`compute_idempotency_key` now includes `client_ref` when present (the cross-client leak fix).
A batch booked BEFORE this change carries a legacy key computed without `client_ref`; a
post-deploy re-book of that same batch through the V2 flow (which now sends `client_ref`)
computes a different key → coordinator cache miss → the adapter is invoked → a **new**
shipment record (and, in live mode, a new carrier booking) is created alongside the legacy
row. The 2026-07-06 duplicate-AWB protection covers same-key replays only, not key-change
replays. Current production exposure is zero (`carrier_shipments` has no `client_ref` rows
yet); the residual operator-facing mitigation — a booking-modal warning when a legacy row
exists for the batch — is tracked as a scheduled follow-up (GATE 4: SCHEDULED). The
`get_shipment_for_draft` fallback additionally refuses to attribute a row scoped to a
different client (defence-in-depth guard), so this limitation cannot re-open the
cross-client leak.

## Consequences

- CMR numbers are human-sized and stable, sourced from the single existing transport
  authority — no counter, no second identity.
- The full stable id is preserved in audit metadata for traceability.

## Rollback

Additive and reversible: revert the campaign commit. `cmr_number.py` is a pure function with
no persistence; no data migration or correction is performed.

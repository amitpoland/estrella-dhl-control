# ADR-005: No live AWB in operational registry during shadow

Status: Accepted
Date:   2026-05-09
Phase:  DL-F2

## Context

Shadow mode (ADR-004) calls the live DHL adapter for observation.
The live response carries a real DHL AWB and real label bytes. If
either of those leak into the operational stores
(`carrier_shipments`, `carrier_label_store`), then:

- Operator dashboards display two contradictory AWBs for the same
  shipment.
- The closure gate on the parent batch sees a "live" shipment that
  was never operator-confirmed.
- A future webhook event for the live AWB lands on a registry row
  the coordinator does not own.
- Audit lineage becomes ambiguous: which AWB was the operator's
  shipment of record?

## Decision

The shadow wrapper's contract is invariant:

> The live response NEVER reaches `carrier_shipment_db` and the
> live label bytes NEVER reach `carrier_label_store`.

Mechanism:

1. The shadow adapter calls `live.create_shipment(request)` inside
   a `try/except CarrierAdapterError` and discards the
   `RawShipmentResponse` after extracting metadata for the shadow
   log.
2. The wrapper returns the **stub's** `RawShipmentResponse` to the
   coordinator. The coordinator's existing persistence path runs
   on the stub response only; live is never seen by the
   coordinator.
3. The shadow log carries `live_awb`, `live_label_size`,
   `live_label_format` as metadata only — no AWB row, no label
   artefact.

Source-grep tests pin the absence of `csdb.upsert_shipment`,
`csdb.record_transition`, and `cls.save_attachment` from the
shadow adapter source.

End-to-end tests use sentinel bytes:
- `LIVE-LABEL-NEVER-PERSISTED` — scanned out of every file under
  `_attachments/` after a shadow create.
- A clearly-distinct live AWB (`LIVE-FAKE-9999`) — scanned out of
  `csdb.list_all()` after a shadow create.

## Rejected alternatives

- **Persist live AWB with a `is_shadow=True` flag.** Two AWBs per
  shipment in the registry; downstream consumers must filter every
  query. Mistake-prone.
- **Dual-write to a separate `live_shadow_shipments` table.**
  Doubles the migration surface. Adds new code paths for closure
  gate, dashboard, audit. The shadow log already carries the
  observation data we need.

## Risks

- Operator may want to know "what AWB did DHL actually issue?" —
  the answer is in the shadow log, not the registry. Resolved by
  the future read-only dashboard surface that joins on
  `request_hash`.
- A bug in the shadow adapter could let live data leak. Mitigated
  by the sentinel-byte tests and the source-grep guards.

## Rollback

If the invariant is ever violated, the immediate response is:
flip `carrier_dhl_shadow_mode=False`, flip
`carrier_dhl_live_enabled=False`, and revert the offending commit.
The registry and label store are not corrupted by leaked live
data — they are merely contaminated. A `DELETE FROM
carrier_shipments WHERE awb LIKE 'LIVE-%'` would clean known
sentinels in dev; in production, ops re-run the affected batches
through the stub.

## Future impact

This invariant locks in the cutover semantics: the moment
`carrier_dhl_shadow_mode=False` flips, live AWBs first land in
the registry. That is the **only** moment when the operational
store changes adapter source. Production cutover is therefore a
single-flag flip with a single, observable effect.

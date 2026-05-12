# ADR-016: DHL self-clearance — SAD unlock and PZ trigger (P6 + P7)

Status: Accepted
Date:   2026-05-10
Phase:  W-5 / P6 + P7

## Context

The terminal phases of the self-clearance flow have to satisfy
two non-negotiable invariants from ADR-012:

- *Hard lock 1:* never generate PZ before SAD / PZC exists.
- *Hard lock 2:* never move inventory lifecycle before customs
  completion is confirmed.

Operational memory recorded the decision to handle SAD / PZC
arrival (P6) and PZ pipeline trigger (P7) as one logical unit
because they are interlocked: PZ never fires without a linked
SAD, and SAD arrival is the *only* signal that unlocks PZ on
this flow.

There is also a customs-description invariant: the *commercial
invoice* preserves original FOB structure, while the *customs
description* must align with the CIF valuation context. ADR-016
records this so future customs UI / generators do not collapse
the two.

## Decision

**P6 — SAD / PZC arrival.**

Trigger: an inbound DHL email or attached document is classified
as a SAD or PZC for the AWB.

Action:

- Store the SAD / PZC document (filesystem; not inline in the
  manifest — per ADR-006).
- Link the document to the shipment row via document-id.
- Persist on the manifest: SAD/PZC document-id, sha256, arrival
  timestamp, classified type (SAD vs PZC).
- Transition state: `awaiting_sad → sad_received → pz_unlocked`.

Failure path: classification ambiguous → flag for operator
review; state stays at `awaiting_sad`.

**P7 — PZ pipeline trigger.**

Trigger: state is `pz_unlocked` AND no PZ exists yet for the
shipment.

Action: invoke the existing PZ pipeline (`process_batch()` per
the project's CLAUDE.md). The PZ pipeline reads the linked SAD
/ PZC for duty (A00) and customs values; the self-clearance
flow does not duplicate any landed-cost or duty math.

State on PZ success: `shipment_closed`.
State on PZ failure: stays at `pz_unlocked`; operator sees error
on dashboard. This satisfies ADR-012 hard lock 1 — PZ is never
silently retried in a way that could produce a PZ without SAD.

**Customs-description invariant.**

The flow handles two distinct description fields:

- *Commercial invoice description* — keeps the original FOB
  structure as supplied by the seller.
- *Customs description* — must align with CIF valuation context
  (i.e., what DHL / customs sees declared).

Neither is a free-form rewrite of the other. ADR-016 explicitly
forbids:

- value rewriting (no fake CIF / FOB transformations);
- customs declaration manipulation (no description that misstates
  the goods).

## Rejected alternatives

- **Trigger PZ on `sad_received` directly (skip
  `pz_unlocked`).** Rejected — collapses two distinct events
  (document linked vs. PZ-eligible) and obscures the operator
  view when SAD is linked but PZ has not yet run.
- **Re-derive duty / customs values from SAD outside
  process_batch().** Rejected — duplicates calculation outside
  the engine and breaks the project's "one calculation path"
  rule (CLAUDE.md §1).
- **Auto-retry PZ on failure.** Rejected — PZ failure can
  indicate a real customs-data mismatch; silent retry hides
  evidence.

## Risks

- **Misclassified SAD.** A non-SAD document tagged as SAD would
  unlock PZ wrongly. Mitigation: the classifier confidence
  threshold gates the unlock; below threshold → operator review
  per ADR-015 fallback pattern.
- **Duplicate SAD inbounds.** A second SAD email for the same
  AWB must not double-trigger PZ. Mitigation: idempotency by
  document sha256 + shipment AWB; second matching SAD is a
  no-op.
- **Lost SAD link on filesystem migration.** Manifest stores
  document-id and sha256; on filesystem migration, the engine
  re-resolves document-id without re-running PZ.

## Rollback

The SAD-unlock behaviour is gated by the same default-OFF flag
that gates the rest of the self-clearance automation (ADR-010).
Disabling the flag means SAD inbounds are flagged for operator
review and PZ is started manually via the existing CLI / API
path. The hard locks remain enforced — manual PZ still requires
a linked SAD.

## Future impact

- The customs-description invariant becomes a check the PZ
  engine asserts at parse time; future UI surfaces (W-2) must
  not allow operators to overwrite it.
- The `pz_unlocked` state is the integration point with W-3
  (customs / PZ engine, currently `live`); any future W-3
  schema change must preserve the `pz_unlocked → shipment_closed`
  transition contract.
- A future carrier offering a SAD-equivalent document on a
  different flow uses ADR-016 as the model: link → unlock → PZ;
  never PZ without link.

## Related

- ADR-012 (hard locks 1, 2)
- ADR-013, ADR-014, ADR-015 (upstream phases)
- ADR-006 (no PDF bytes / credentials in evidence stores)
- ADR-010 (default-OFF feature flags)
- W-3 program-board row (customs / PZ engine; `process_batch()`)
- CLAUDE.md §1 (one calculation path rule)

# ADR-003: Coordinator + state-engine separation

Status: Accepted
Date:   2026-05-09
Phase:  DL-A / DL-D1

## Context

Every shipment write must be legal under a 9-state finite-state
machine: `pre_awb → awb_issued → label_created → label_printed →
handed_to_carrier → in_transit → delivered | returned`, with
`voided` reachable only before handover. The same state machine
must be enforced by:

- the operator-driven action routes (`POST /actions/*/execute`),
- the inbound webhook handler (`carrier_event_handler`),
- the proposal builder (which surfaces only legal next actions),
- the closure-gate check (which blocks closing batches with open
  carrier shipments).

Centralising legality in any one of those modules creates
duplication and drift. Centralising it in the database via CHECK
constraints is too rigid for cross-carrier logic.

## Decision

Three modules with sharply-different concerns:

- **`carrier_state_engine.py`** — pure logic. No I/O. Exposes
  `STATES`, `LEGAL_TRANSITIONS`, `transition(from, to)`,
  `can_transition`, `allowed_next_states`. Imported by every
  consumer. The single source of truth on legality.
- **`carrier_coordinator.py`** — orchestration. Consumes the state
  engine to validate, the adapter to fetch carrier data, and the
  shipment DB / label store to persist. Owns the manifest write
  and the per-AWB messages log. Never bypasses the state engine.
- **`carrier_shipment_db.py`** — dumb persistence. Validates only
  that `state` is in `STATES`. Does NOT validate transition
  legality — that is the state engine's job, called upstream.

Adapters never call the state engine. The coordinator calls
`cse.transition(...)` BEFORE persisting any move; if illegal, the
exception bubbles up before the DB write.

## Rejected alternatives

- **State-engine with DB writes.** Single class doing both. Rejected:
  hides the legality contract behind I/O, untestable in isolation.
- **DB-side CHECK constraints encoding legal transitions.** Rejected:
  carrier-specific logic (e.g., "void after handover") doesn't
  belong in SQL. Migration cost is high.
- **Adapter-driven persistence.** Each carrier writes its own rows.
  Rejected: triples the surface area; no cross-carrier consistency.

## Risks

- Coordinator could grow into a god class. Mitigated by per-method
  scope and tight test coverage on each method.
- Two callers could race on the same AWB if both observe a stale
  `from_state` outside the lock. Identified by DB Engineer in DL-G
  inspection; addressed by per-AWB lock + atomic CAS in DL-G.

## Rollback

State engine is pure logic — it can't break the DB. Coordinator
rollback is a normal `git revert`. Persistence stays consistent
because each transition writes one row to the append-only
transitions table.

## Future impact

FedEx and UPS share the same state engine; only carrier-specific
event-code translation tables differ. Adding a new state (e.g.,
`customs_hold`) requires a state-engine ADR and a coordinated
schema-aware migration.

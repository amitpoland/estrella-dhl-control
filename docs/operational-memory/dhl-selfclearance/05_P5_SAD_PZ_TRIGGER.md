# P5 — SAD/PZC Unlock + PZ Trigger (terminal)

| Field | Value |
|---|---|
| **Phase** | W-5 / P5 (terminal) |
| **Source ADR** | ADR-016 |
| **Depends on** | P0 + P2 live + P3 live + P4 live for ≥1 week each |
| **Designed** | 2026-05-12 |
| **Shadow window** | 1 week + ≥30 SAD events |

---

## TASK

Implement W-5 / Phase P5 — DHL self-clearance terminal phase. Receives SAD/PZC inbound, classifies it, stores doc + link, unlocks PZ, then triggers `process_batch()`. Two-flag split (link-only vs auto-PZ) supports staged cutover. Hard locks 1 and 2 are binding.

## SCOPE BOUNDARY

- Path A only.
- Triggered by inbound DHL email or document classified as SAD or PZC.
- Transitions `awaiting_sad → sad_received → pz_unlocked → shipment_closed` (on PZ success).
- Out of scope: P2 dispatch, P3 watcher, P4 reply — they must already be live and stable.

## PATH COVERAGE

Path A only. SAD/PZC arrival on Path B continues via existing `sad_importer` + agency flow (untouched here).

## UI COMMITMENT

Minimal Mac UI — extend state pill with the terminal states + PZ trigger status. Show last PZ result (success / partial / blocked / failed). **NO operator-override PZ trigger button on Mac.** Manual PZ remains available via existing CLI / API path (operator action, separate from this code).

## PREREQUISITES (BLOCK if not met)

- P0 scaffolding shipped: state engine, coordinator, manifest namespace (`p6_sad` + `p7_pz` declared), 6 default-OFF flags, `dhl_selfclearance_p5_classifier_min_confidence` config, classifier validation harness, per-thread reply lock primitive, RFC822 thread tracking.
- **Note:** The content-aware SAD/PZC document classifier is implemented in **this phase** as an extension of `customs_doc_classifier.py` (see FILES TO BE MODIFIED). P0 only delivers the 4-intent clarification classifier (`dhl_clarification_classifier.py`); P5 owns the SAD/PZC discriminator. This split matches Master Plan §4.4 and is intentional.
- P2, P3, P4 all live and stable for ≥1 week each.
- W-3 customs / PZ engine green (`make verify` → 160/160 on the same commit).
- Inventory state engine `LEGAL_TRANSITIONS` unaffected (P5 closes the customs flow; inventory takes over after `shipment_closed`).

## TEST DEPTH (hardened)

- ≥50 test cases:
  - SAD classification (content + filename hybrid): true positive, true negative, ambiguous → operator review
  - PZC classification: separated from SAD (different document)
  - Duplicate-SAD detector (idempotency by `sha256` + AWB): second matching SAD is no-op
  - Manifest write completeness: `doc_id`, `sha256`, arrival timestamp, type (SAD vs PZC)
  - State transitions: `awaiting_sad → sad_received` on classification success; `sad_received → pz_unlocked` transition; `pz_unlocked → shipment_closed` only on PZ pipeline success
  - PZ pipeline invocation: `process_batch()` called with correct `batch_id` + linked SAD `doc_id`
  - PZ failure: state stays at `pz_unlocked`; no auto-retry; operator sees error
  - Two-flag split: `dhl_selfclearance_p5_live_enabled` controls SAD-link; `dhl_selfclearance_p5_pz_trigger_enabled` controls auto-PZ trigger
  - Customs-description invariant: parse-time assertion enforces that CIF customs description and FOB commercial invoice description do not collapse (ADR-016)

## FILES TO BE MODIFIED

- `service/app/services/dhl_clearance_coordinator.py` (add `on_sad_inbound` entrypoint)
- `service/app/services/dhl_clearance_state_engine.py` (terminal state transitions including `pz_failed` branch)
- `service/app/services/sad_importer.py` (extend or wrap with the content-aware classifier + idempotency key)
- `service/app/services/customs_doc_classifier.py` (extend to content-aware SAD/PZC discrimination — closes Risk R4)
- `service/app/static/dashboard.html` (state pill + PZ result display read-only)
- `service/tests/test_dhl_sad_classifier_p5.py` (NEW)
- `service/tests/test_dhl_pz_trigger_p5.py` (NEW)

## FILES NOT TO BE MODIFIED

- `service/app/services/dhl_proactive_dispatch_builder.py` (closed)
- `service/app/services/dhl_self_clearance_builder.py` (closed)
- `service/app/services/dhl_selfclearance_followup_v2.py` (closed)
- `service/app/services/dhl_clarification_classifier.py` (closed)
- `service/app/services/agency_*.py`
- `service/app/services/inventory_state_engine.py` (post-shipment flow; hands off but does not modify)
- `service/app/services/warehouse_db.py` (PZ creation lives in W-3; P5 only invokes `process_batch()`)
- The PZ engine itself (`process_batch()` and its callees in `pz_import_processor.py`) — P5 is a caller, not a modifier

## ACCEPTANCE CRITERIA

1. `dhl_selfclearance_p5_live_enabled` defaults to `False`. `dhl_selfclearance_p5_pz_trigger_enabled` defaults to `False` (independent — link-only first, auto-PZ second).
2. SAD classifier uses both filename + document content; filename-only matches require confidence ≥ threshold.
3. Duplicate SAD (same `sha256`, same AWB) is a no-op.
4. Hard lock 1 enforced: PZ never invoked without linked SAD on manifest. Source-grep verify: `process_batch()` callsite in this module is gated by `audit.dhl_clearance.p6_sad.doc_id != None`.
5. Hard lock 2 enforced: state stays at `pz_unlocked` on PZ failure; inventory state engine untouched until `shipment_closed`.
6. Customs-description invariant: PZ engine asserts CIF/FOB non-collapse at parse time (Risk R1 mitigation extension).
7. `make verify`: 160/160. `pytest -k "p5 or sad or pz_trigger"` → green.

## SHADOW→LIVE PROMOTION GATE

- Shadow window: 1 week + ≥30 distinct SAD/PZC events (whichever later).
- Required evidence:
  - 100% SAD/PZC classifier precision on shadow set
  - 0 PZ-without-SAD-link instances in shadow logs
  - Duplicate-SAD idempotency verified on ≥5 retries in shadow
  - Customs-description invariant green on every shadow PZ-would-trigger
  - Full `make verify` green on the same commit
  - ≥1 PZ pipeline weekly cadence observed in shadow
- Reviewer sign-off (mandatory, three independent):
  - Customs Compliance Reviewer (Tejal primary; **Amit backup if Tejal unavailable**)
  - Inventory / Finance Reviewer (Izabela or designee)
  - Operator Safety Reviewer
- Two-stage promotion:
  - Stage 1: flip `dhl_selfclearance_p5_live_enabled=True` (SAD linking goes live; operator runs PZ manually for ≥1 week)
  - Stage 2: flip `dhl_selfclearance_p5_pz_trigger_enabled=True` (auto-PZ goes live after Stage 1 observation)

## ROLLBACK PROCEDURE

- Stage 2 rollback (most aggressive): `dhl_selfclearance_p5_pz_trigger_enabled=False` via admin endpoint; operator resumes manual PZ.
- Stage 1 rollback: `dhl_selfclearance_p5_live_enabled=False` via admin endpoint; SAD inbounds flagged to operator review.
- A wrongly-fired PZ: existing PZ reverse procedure + inventory rollback. **No automatic reverse path.** Operator manually void-and-reissue per existing wFirma reversal flow.
- Manifest records preserved for audit forensics.

## CONSTRAINTS

- ADR-012 HL1: never PZ before SAD link.
- ADR-012 HL2: never inventory mutation before customs complete.
- No auto-retry on PZ failure.
- Honor `engineering_discipline_rules.md`.
- Honor Windows Atlas memory: no PZ-trigger button on Mac UI.

## ESCALATION CRITERIA

- SAD classifier accuracy below 99% on shadow → BLOCK (P5 is the irreversible phase; 97% threshold from P4 is not enough here).
- A SAD document classified correctly but PZ fails on customs-data mismatch — surface immediately; do NOT auto-retry.
- Customs-description invariant violation surfaces in shadow — block live promotion until ADR-016 §"customs-description invariant" guidance is reconfirmed by Customs Compliance Reviewer.
- Inventory state machine receives a transition request that bypasses `shipment_closed` (HL2 violation attempt).

## FINAL REPORT

9 sections, P2 shape.

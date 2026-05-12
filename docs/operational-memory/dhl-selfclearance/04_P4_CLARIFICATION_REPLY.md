# P4 — Thread-Based Clarification Reply

| Field | Value |
|---|---|
| **Phase** | W-5 / P4 |
| **Source ADR** | ADR-015 |
| **Depends on** | P0 + P2 live + P3 live for ≥1 week |
| **Designed** | 2026-05-12 |
| **Shadow window** | 72h + ≥200 classifications + ≥30 operator-reviewed drafts |

---

## TASK

Implement W-5 / Phase P4 — DHL self-clearance thread-based clarification handling. Classifies inbound clarification into 4 intents, sends reply in the SAME thread, with shadow→live promotion behind default-OFF flags. Includes per-thread reply lock to prevent operator-vs-engine race.

## SCOPE BOUNDARY

- Path A only.
- Triggered by inbound DHL email classified as clarification request while shipment is in `followup_active` (per ADR-014 exit) OR directly from `awaiting_poland_arrival` (per Risk R3 — DHL responds before tracking shows Poland arrival).
- Reply MUST go in the same thread DHL used. No new thread under any circumstance.
- Intent enum (frozen): `goods_description`, `invoice`, `authorization`, `sad_received`. Unknown intent → operator review.

## PATH COVERAGE

Path A only. Path B clarifications go via existing `agency_email_builder`; coordinator must hard-skip Path B at entrypoint.

## UI COMMITMENT

Minimal Mac UI — extend state pill to show `dhl_requested_clarification` + `clarification_sent` states + last intent classified. Surface operator-review queue count (read-only). **Operator review action surface is in Windows Atlas, not Mac.** Do NOT build reply-edit / send-manually controls on Mac.

## PREREQUISITES (BLOCK if not met)

- P0 scaffolding shipped, including the `dhl_clarification_classifier` module with the 4-intent vocabulary.
- Classifier has passed historical shadow validation against ≥200 past DHL emails with ≥97% accuracy on the 4-intent set (via P0 validation harness; corpus owned by Tejal with Amit spot-checks).
- Per-thread reply lock primitive working (P0).
- P3 has shipped live with ≥1 week of stable operation.
- RFC822 References-based thread tracking implemented (P0) — `thread_id` is NOT subject-keyed.

## TEST DEPTH (hardened)

- ≥50 test cases:
  - All 4 intents classified correctly on ≥10 fixture inbounds each
  - Unknown intent → operator review (never guess)
  - Confidence below threshold → operator review
  - Reply built with correct content per intent (goods description aligned to CIF, invoice re-attached without value rewrite, authorization document attached, `sad_received` acknowledgment)
  - Same `thread_id` used on reply (verify by message header in `email_service.queue_email` call)
  - Per-thread reply lock acquired before queue, released on send confirmation
  - Operator manual reply detected → lock released, engine yields
  - Idempotency by `(inbound_message_id, classified_intent)` — second inbound with same `message_id` + intent: no-op
  - State transitions: `dhl_requested_clarification → clarification_sent` on success; stays at `dhl_requested_clarification` on classification failure; re-enters `dhl_requested_clarification` on further DHL email while in `clarification_sent`
  - Manifest audit fields: `inbound_message_id`, intent, `reply_message_id`, `reply_sha256`, `thread_id` (all present)

## FILES TO BE MODIFIED

- `service/app/services/dhl_clearance_coordinator.py` (add `on_inbound_clarification` entrypoint)
- `service/app/services/dhl_clearance_state_engine.py` (transitions for `dhl_requested_clarification ↔ clarification_sent` + `awaiting_poland_arrival → dhl_requested_clarification` edge from R3)
- `service/app/services/dhl_clarification_classifier.py` (P0 scaffold; this phase finalizes the trained classifier behavior)
- `service/app/services/dhl_self_clearance_builder.py` (existing 143 lines — extend with per-intent reply builders)
- `service/app/services/email_service.py` (per-thread reply lock integration)
- `service/app/static/dashboard.html` (state pill + operator-review queue count read-only)
- `service/tests/test_dhl_clarification_classifier_p4.py` (NEW)
- `service/tests/test_dhl_clarification_reply_p4.py` (NEW)
- `service/tests/test_thread_reply_lock_p4.py` (NEW)

## FILES NOT TO BE MODIFIED

- `service/app/services/dhl_proactive_dispatch_builder.py` (P2 closed)
- `service/app/services/dhl_selfclearance_followup_v2.py` (P3 closed; P4 is consumer)
- `service/app/services/agency_*.py`
- `service/app/services/inventory_*.py`
- `service/app/services/warehouse_db.py`
- `service/app/services/email_classifier.py` — P0 decision was a separate classifier module (`dhl_clarification_classifier.py`), not an extension of this one

## ACCEPTANCE CRITERIA

1. `dhl_selfclearance_p4_live_enabled` defaults to `False`. `dhl_selfclearance_p4_classifier_min_confidence` numeric config exists.
2. Classifier returns one of the 4 intents OR "unknown" (operator-review fallback).
3. Reply is queued with `thread_id` pulled from manifest. Verify `email_service` receives non-empty `thread_id`.
4. Per-thread reply lock acquired before queue; lock released on send confirmation OR on operator-manual-reply audit event.
5. Manifest's `p4_followup` and `p5_clarifications` nested fields populated correctly.
6. Hard lock 4: source-grep confirms no path in P4 code creates a new thread without `thread_id`.
7. `make verify` → 160/160 unchanged. Targeted P4 tests green.

## SHADOW→LIVE PROMOTION GATE

- Shadow window: 72h + ≥200 classified inbounds (whichever later) + ≥30 operator-reviewed shadow drafts.
- Required evidence:
  - Classifier accuracy ≥97% with ZERO `invoice ↔ goods_description` confusions
  - Manual operator review of ≥30 shadow drafts compares built body to what operator would have written
  - 0 thread-id ambiguities resolved by guess
  - 0 unknown intents handled outside operator review
  - Per-thread reply lock acquisition rate ≥99%
- Reviewer sign-off (mandatory):
  - Customs Compliance Reviewer (Tejal primary)
  - Operator Safety Reviewer
  - Customer Service Reviewer (if exists; else operator)

## ROLLBACK PROCEDURE

- Flip `dhl_selfclearance_p4_live_enabled=False` via admin endpoint (restartless).
- Every inbound clarification now flagged to operator review (existing fallback path).
- Thread-id persistence intact; no manifest cleanup.

## CONSTRAINTS

- No new email thread under any circumstance (ADR-012 HL4).
- Per-thread reply lock is mandatory pre-queue check.
- Honor `engineering_discipline_rules.md` error templating.
- Honor Windows Atlas memory: no operator action UI on Mac.

## ESCALATION CRITERIA

- Classifier accuracy below threshold on shadow → BLOCK promotion.
- A 5th intent observed in DHL inbounds during shadow (out-of-vocab) — escalate to operator for ADR amendment.
- Operator-vs-engine race observed in shadow even with lock → redesign lock.
- DHL sends a clarification on a fresh thread (thread non-stationarity per Risk R1) — escalate to operator for thread-alias decision.

## FINAL REPORT

9 sections, P2 shape.

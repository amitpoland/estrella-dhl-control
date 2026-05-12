# DHL Self-Clearance — Master Plan (P0 → P5)

| Field | Value |
|---|---|
| **Status** | DESIGNED (not yet implemented) |
| **Designed** | 2026-05-12 |
| **Implementation start** | TBD (P0 fires in next focused session) |
| **Wall-clock estimate** | 3 weeks minimum, 4-5 weeks realistic |
| **Single point of catastrophic failure** | P4/P5 intent classifier |
| **Source-of-truth ADRs** | ADR-012 (umbrella), ADR-013, ADR-014, ADR-015, ADR-016 |
| **Program board row** | W-5 |

---

## §4.1 Phase dependencies

```text
P0 (NEW — scaffolding)                        prerequisite for all
   ↓
P2 — proactive dispatch                       depends on P0
   ↓ (seeds awaiting_poland_arrival state on shipment manifest)
P3 — tracking watcher + arrival follow-up     depends on P2 (shadow OK; live requires P2 live)
   ↓ (transitions to dhl_requested_clarification on DHL inbound)
P4 — thread-based clarification reply         depends on P3 (live)
   ↓ (transitions to awaiting_sad / sad_received)
P5 — SAD/PZC unlock + PZ trigger              depends on P4 EITHER live OR no-clarification SAD path
```

**Parallel possibilities:** P3 and P4 cannot share a session — they touch different code paths and need separate shadow windows. P5 can be drafted in parallel with P4 *as design*, but its shadow run cannot begin until P4 is live (P5 consumes P4's `clarification_sent → awaiting_sad` transition).

**Critical path:** P0 → P2 → P3 → P4 → P5. All four phases serial except P5 design can start during P4 shadow.

## §4.2 Production blast radius per phase

| Phase | Real systems touched | Worst-case failure | Safety net |
|---|---|---|---|
| **P2** | Real outbound email to `odprawacelna@dhl.com` (DHL customs mailbox) | Stale-AWB dispatch (voided AWB), or duplicate sends fragmenting the audit trail | Shadow build-and-log; AWB-stable gate; idempotency by AWB; manifest hash for replay |
| **P3** | Read-only DHL inbox + DHL tracking API rate limit; mail-account quota | DHL IP-trust loss from polling flood; livelock if shipment stuck in `followup_active` | Continuous shadow with quota observability; livelock budget config; independent `selfclearance_p3_tracker_paused` pause flag |
| **P4** | Real outbound email + intent-classifier risk; per-thread reply race with operator | **Misclassified intent reply** sent to DHL customs (wrong content) — customs may misroute, hold, or reject the shipment | Per-thread reply lock; classifier confidence threshold; unknown-intent → operator review (never guess); ≥200 shadow classifications + Customs Compliance Reviewer sign-off |
| **P5** | **Mutates inventory state machine** + **invokes `process_batch()`** (financial / customs irreversible) | PZ triggered against a misclassified SAD → real PZ document created against wrong customs data → financial misstatement | Two-flag split (link vs auto-PZ); idempotency by `(AWB, sha256)`; mandatory Customs Compliance + Inventory/Finance sign-off; no auto-retry on PZ failure |

## §4.3 Sequencing recommendation

**Revised order (post-reviewer-challenge):**

| # | Phase | Time-to-shadow | Shadow window | Promotion gate | Then live for |
|---|---|---|---|---|---|
| 0 | **P0 — Foundation** *(NEW)* | 2-3 days | n/a (read-only) | scaffolding-complete + ≥4 reviewer-agents green | n/a — prereq |
| 1 | **P2 — Proactive dispatch** | 1 day | **48h** continuous | ≥50 shadow dispatches across ≥10 AWBs; 0 duplicate sends; Customs + Operator Safety sign-off | go live then move to P3 |
| 2 | **P3 — Tracking watcher + scheduler** | 1-2 days | **1 week (168h)** | 0 rate-limit violations; signal classifier ≥98% on labelled set ≥200 events; livelock budget verified | go live then move to P4 |
| 3 | **P4 — Thread clarification reply** | 1-2 days | **72h + ≥200 classifications + ≥30 operator-reviewed drafts** | classifier ≥97% accuracy; zero `invoice`↔`goods_description` confusion; Customs Compliance Reviewer (mandatory) | go live then move to P5 |
| 4 | **P5 — SAD unlock + PZ trigger** | 2-3 days | **1 week + ≥30 SAD events** | 100% SAD/PZC classifier precision; 0 PZ-without-SAD-link; duplicate-SAD idempotency verified; full `make verify` green; Customs Compliance + Inventory/Finance + Operator Safety sign-off | terminal phase |

**Wall-clock total (best case):** ~3 weeks. **Realistic with operator review queues + reviewer-agent rotations:** 4-5 weeks.

**Observation between phases:** before promoting any phase live, audit logs from the shadow window must be inspected by the named reviewer roles + a labelled accuracy table produced + zero unresolved escalations.

## §4.4 Shared infrastructure changes (P0 — NEW phase)

Prerequisite work that must land **before P2 ships to shadow**. Not optional.

| Item | Why prerequisite |
|---|---|
| New `service/app/services/dhl_clearance_state_engine.py` (9 states + LEGAL_TRANSITIONS + 4 added states: `dispatch_failed`, `scope_gate_violated`, `operator_override_active`, `pz_failed`) | State machine has zero existence in current code |
| New `service/app/services/dhl_clearance_coordinator.py` (single coordinator drives P2-P5, depends on injected `is_awb_stable()` from carrier coordinator) | ADR-013 mentions a coordinator-level guard with no current host |
| Manifest namespace at `audit.dhl_clearance.{state, state_history, thread_id, p2_dispatch, p3_tracking, p4_followup, p5_clarifications, p6_sad, p7_pz}` + writer helper | Five distinct fields collide on the existing audit schema |
| Default-OFF flags in `core/config.py`: `dhl_selfclearance_p2_live_enabled`, `..._p3_live_enabled`, `..._p3_tracker_paused`, `..._p4_live_enabled`, `..._p5_live_enabled`, `..._p5_pz_trigger_enabled` + `..._shadow_mode` paired equivalents | Per ADR-010 every phase needs its own flag; none exist |
| New `service/app/services/dhl_clarification_classifier.py` with 4-intent enum (`goods_description`, `invoice`, `authorization`, `sad_received`) + confidence threshold + unknown→operator-review fallback. **Plus** a SHADOW-ONLY run against historical DHL email corpus to measure 4-bucket accuracy before any state-advancing code uses it. | Classifier vocabulary doesn't exist; reviewer-challenge flagged this as the single-point-of-failure |
| Per-thread reply lock primitive (SQLite row keyed by thread_id, acquired before queue, released on send/operator-manual-reply) | ADR-015 mentions it; reviewer-challenge confirmed it doesn't exist in code |
| RFC822 References-based thread tracking on inbound DHL emails (replaces subject-keyed thread_id which collides across DHL templated subjects) | gap-hunter found subject-keyed threads in `email_evidence_store.py` |
| `is_awb_stable(awb)` read-only predicate on `service/app/services/carrier/coordinator.py` (recommended definition: state ∈ {awb_issued, label_created, label_printed, handed_to_carrier}) | ADR-013 references it; doesn't exist |
| Tracking-event vocabulary extension in `tracking_normalizer.py` to emit `poland_arrival`, `customs_processing`, `customs_hold`, `delay`, `rejected_paperwork` tokens | P3 watcher depends on these tokens; today only `delivered/in_transit/out_for_delivery/exception` are emitted |
| **POLICY DECISION (locked):** Create new `dhl_selfclearance_followup_v2.py` alongside legacy `dhl_followup_sla.py`. Coordinator routes by `clearance_path`. Legacy stays for Path B until operational evidence justifies deprecation. | Two follow-up engines coexisting is risky but rewriting in place breaks existing tests; operator chose coexistence |
| Admin runtime-flags endpoint per Decision 5 (`POST /api/v1/admin/runtime-flags/self-clearance`) with `X-API-Key` auth, audit log per flip, phase-scoped, restartless reload | Kill-switch mechanism for all phase flags without service restart |

## §4.5 Risks and mitigations

| Risk | Mitigation |
|---|---|
| **R1: DHL thread non-stationarity** (DHL starts fresh threads server-side, violating one-AWB-one-thread invariant). Reviewer-challenge's weakest-assumption attack. | Build P5's thread-matching layer to fall back to AWB-keyed search + persistent thread-id map; when a fresh DHL thread is detected on an existing AWB, append it to the manifest's `thread_id_aliases[]` rather than open operator review. Audit it. |
| **R2: Intent classifier misclassification** as single point of failure (reviewer-challenge). | (a) Confidence-gated `sad_received` (highest threshold because it triggers state advance); (b) operator review path for low-confidence; (c) ≥200 shadow classifications before live; (d) maintain a labelled drift-detection set so quality degradation is observable. |
| **R3: Out-of-sequence DHL response** (DHL replies to proactive dispatch *before* Poland arrival; ADR doesn't cover this) | Allow state transition from `awaiting_poland_arrival` directly to `dhl_requested_clarification` if an inbound clarification matches a known AWB+thread. Add this transition explicitly in the new state engine. |
| **R4: SAD filename heterogeneity** (DHL auto-generates filenames that don't match keyword classifier) | P5 classifier must use **document content**, not filename, for SAD/PZC classification. Fallback to operator review at confidence < threshold. |
| **R5: Concurrent operator + engine reply race** (ADR-015 mentions, no lock exists) | Per-thread reply lock primitive built in P0 (mandatory prereq). Operator's manual reply via email account must emit a `manual_reply_in_thread` audit event the coordinator checks before queueing. |
| **R6: Stale-AWB dispatch** (AWB voided + reissued after P2) | Idempotency by AWB on the *current* AWB string + carrier-coordinator's AWB-stable signal. If the AWB on a shipment changes, manifest state moves to `scope_gate_violated` (new state added in P0). |
| **R7: Sequencing violation** (P3 enabled before P2 live, or P4 enabled before P3 live) | Each phase's flag MUST check predecessor-phase flag at boot. If predecessor is OFF, the phase logs `selfclearance_pX_blocked_predecessor_off` and no-ops. Prevents partial enablement. |
| **R8: `dhl_followup_sla.py` policy contradiction** (existing vs ADR-014) | Resolved by P0 Decision 2: create `dhl_selfclearance_followup_v2.py` alongside; coordinator routes by `clearance_path`. |

**Operator gates required at each transition:**
- After P0 scaffolding: scaffolding-complete + ≥4 reviewer-agents green (`system-architect`, `gap-hunter`, `production-readiness-reviewer`, `backend-safety-reviewer`)
- After every shadow window: dedicated review session with named reviewer roles; sign-off recorded in commit message
- Before P5 live: Customs Compliance Reviewer (mandatory) + Inventory/Finance Reviewer (mandatory) + Operator Safety Reviewer (mandatory) — three independent reviews

---

**Named reviewer roles (locked 2026-05-12):**
- Customs Compliance Reviewer primary: **Tejal**
- Customs Compliance Reviewer backup (P5 specifically): **Amit**
- Corpus labelling owner: **Tejal labels, Amit spot-checks 10-15%**
- Inventory / Finance Reviewer (P5 mandatory): **Izabela** (or designee)
- Operator Safety Reviewer: subagent + named human depending on phase

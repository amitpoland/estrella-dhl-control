# P0 — Foundation Scaffolding

| Field | Value |
|---|---|
| **Status** | DESIGNED — ready to fire as next focused session |
| **Phase** | W-5 / P0 (prerequisite to P2-P5) |
| **Source ADRs** | ADR-012, ADR-013, ADR-014, ADR-015, ADR-016 (covers all five for scaffolding) |
| **Designed** | 2026-05-12 |
| **Estimated effort** | 2-3 days |
| **Blocks** | P2 / P3 / P4 / P5 (none can fire until P0 is merged) |

---

## TASK

Implement W-5 / Phase P0 — Foundation Scaffolding for the DHL self-clearance program. This phase ships all the prerequisite infrastructure that P2-P5 each assume exists. No production behaviour changes; all phase flags default OFF; all classifiers are scaffolded but not yet trained on real data.

P0 is a **structural** phase. It creates files, registers types, declares flags, exposes admin endpoints, and writes the validation harness. **No state-advancing automation is wired through this phase.** The four downstream phases (P2-P5) each consume P0's primitives and wire their own behaviour behind their own flags.

## SCOPE BOUNDARY

- Path A self-clearance scaffolding only. Path B (over-2500 agency_clearance) primitives are untouched.
- New modules and config flags only; no edits to existing production-path code beyond:
  - `service/app/services/email_evidence_store.py` — replace subject-keyed `thread_id` with RFC822-References-based threading **for DHL self-clearance threads only** (other email types continue using existing subject-keyed logic).
  - `service/app/services/tracking_normalizer.py` — extend the signal vocabulary (additive only; existing tokens unchanged).
  - `service/app/services/carrier/coordinator.py` — add `is_awb_stable(awb)` read-only predicate (no mutation).
  - `service/app/core/config.py` — register new flags + config keys.
- Admin runtime-flags endpoint is new — no UI surface — `X-API-Key` auth via existing `require_api_key` from PR #23.
- Classifier validation harness scaffolded but **corpus loading not wired**; corpus assembly is a separate operator task (Tejal labels, Amit spot-checks).

## PATH COVERAGE

Path A only.

## UI COMMITMENT

**No UI in P0.** Mac dashboard state pill is introduced in P2 (read-only). Per Windows Atlas memory rule (2026-05-12), **no operator-facing controls on Mac dashboard at any phase**. P0 introduces an admin-only endpoint (no UI) for runtime flag flips.

## PREREQUISITES (BLOCK if not met)

- PR #23 (hybrid auth guard) merged into `main`. `require_api_key` is the auth seam for the new admin endpoint.
- ADR-012 through ADR-016 present in `.claude/adr/` (verified — see master plan).
- `service/app/config/email_routing.py` present (Phase 1.3 — verified, used by 14+ services).
- `make verify` baseline = 160/160 on the branch starting commit.

## TEST DEPTH (hardened)

Minimum ≥40 tests across the new files. Per scaffold-item targets:

| Scaffold item | Min tests |
|---|---|
| State engine (9 + 4 added states; legal transitions; idempotency) | ≥12 |
| Coordinator scaffold (entrypoints exist, return correctly without behaviour) | ≥4 |
| Manifest writer helper (each namespace block round-trips) | ≥6 |
| 6 phase flags + paired shadow_mode (default OFF; readback; type) | ≥4 |
| Classifier vocabulary + confidence threshold + unknown-intent fallback | ≥6 |
| Per-thread reply lock primitive (acquire / release / contention / operator-override) | ≥5 |
| RFC822 thread tracking (References parsing; alias creation; AWB-keyed fallback) | ≥4 |
| `is_awb_stable()` predicate (each AWB-stable state branch) | ≥4 |
| Tracking-normalizer vocabulary extension (5 new tokens) | ≥5 |
| `dhl_selfclearance_followup_v2.py` scaffold (ADR-014 cadence math, no SMTP) | ≥4 |
| Admin runtime-flags endpoint (auth ok/forbidden; flag readback; audit log line) | ≥6 |

All tests in `service/tests/test_dhl_selfclearance_p0_*.py` (one file per scaffold item to keep PR review tractable).

## FILES TO BE CREATED (new)

| Path | Purpose |
|---|---|
| `service/app/services/dhl_clearance_state_engine.py` | **13 total states** = 9 ADR-012 base states (in order: `awaiting_preemptive_send`, `awaiting_poland_arrival`, `followup_active`, `dhl_requested_clarification`, `clarification_sent`, `awaiting_sad`, `sad_received`, `pz_unlocked`, `shipment_closed`) + 4 added states (`dispatch_failed`, `scope_gate_violated`, `operator_override_active`, `pz_failed`). Frozenset-edge `LEGAL_TRANSITIONS` map. **Must include the Risk-R3 edge `awaiting_poland_arrival → dhl_requested_clarification`** (DHL responds before tracking shows Poland arrival). Pure-logic (no DB). Append-only state_history. |
| `service/app/services/dhl_clearance_coordinator.py` | Single coordinator class. Stubs for `dispatch_proactive`, `on_tracking_event`, `tick_followup`, `on_inbound_clarification`, `on_sad_inbound`. Each stub raises `NotImplementedYet` for now — wired in P2-P5. Path A scope gate via `is_dhl_self_clearance()`. |
| `service/app/services/dhl_clearance_manifest.py` | Writer helpers for `audit.dhl_clearance.*` with the following enumerated sub-schemas (frozen at P0 — phases may NOT add fields without an ADR amendment): <br>• `state` (string, one of 13) <br>• `state_history` (append-only list of `{from, to, at, reason}`) <br>• `thread_id` (string), `thread_id_aliases` (list of strings) <br>• `p2_dispatch` (`{shadow:bool, message_id, recipient, sent_at, content_sha256}`) <br>• `p3_tracking` (`{last_signal_token, last_signal_at, tick_count, last_tick_at, watcher_active:bool}`) <br>• `p4_followup` (`{activated_at, last_tick_at, livelock_budget_until}`) <br>• `p5_clarifications` (list of `{inbound_message_id, intent, confidence, reply_message_id, reply_sha256, at}`) <br>• `p6_sad` (`{doc_id, sha256, type:"SAD"\|"PZC", arrived_at}`) <br>• `p7_pz` (`{triggered_at, last_status:"unlocked"\|"running"\|"succeeded"\|"failed", last_run_at, failure_reason}`) <br>Append-only state_history. Hash-only audit per ADR-006. |
| `service/app/services/dhl_clarification_classifier.py` | 4-intent enum (`goods_description`, `invoice`, `authorization`, `sad_received`). `classify_clarification(email_body) -> (intent, confidence)`. Confidence-threshold gate. Unknown → operator-review. **Stub implementation**: returns deterministic placeholder; production training happens via the validation harness. |
| `service/app/services/dhl_clarification_validation_harness.py` | Read-only harness. Accepts a labelled corpus path (CSV/JSONL with email body + true intent). Runs classifier. Emits accuracy report (per-intent precision/recall, confusion matrix, drift flags). **Corpus loading not wired** — operator points harness at the corpus when ready. |
| `service/app/services/dhl_thread_lock.py` | SQLite row keyed by `thread_id`. API: `acquire(thread_id, owner_actor, ttl_sec) -> bool`, `release(thread_id, owner_actor) -> None` (owner-match required), `force_release(thread_id, reason) -> None` (operator-override path; audit-logged). On operator-manual-reply detected in the thread, the email-intake side calls `force_release(thread_id, "operator_manual_reply")`. Acquire returns `False` if a non-expired lock exists. TTL extension is NOT supported — caller must release and re-acquire. |
| `service/app/services/dhl_thread_tracker.py` | RFC822 References-aware thread tracker for DHL self-clearance threads. `resolve_thread_id(message_headers, awb) -> thread_id`. Fallback to AWB-keyed search if References chain doesn't resolve. Maintains `thread_id_aliases[]` on manifest for DHL-initiated fresh threads (Risk R1). |
| `service/app/services/dhl_selfclearance_followup_v2.py` | New service alongside legacy `dhl_followup_sla.py`. Implements ADR-014 cadence: 2h working hours (CET 08-16, configurable), slower overnight + weekend + holidays (configurable), livelock budget. No SMTP yet — pure schedule decisions. |
| `service/app/api/routes_admin_runtime_flags.py` | New router. `POST /api/v1/admin/runtime-flags/self-clearance` body `{flag_name, value, actor}`. `GET /api/v1/admin/runtime-flags/self-clearance` returns current flag map. `X-API-Key` auth via `require_api_key`. Audit log line per flip (`admin_runtime_flag_flipped` event). Restartless reload: writes to a runtime-flag store (in-memory + persisted JSON) that config readers consult before falling back to env-var defaults. NO browser UI. |

## FILES TO BE MODIFIED (existing)

| Path | Change |
|---|---|
| `service/app/services/tracking_normalizer.py` | **Additive only.** Extend signal vocabulary to emit 5 new tokens: `poland_arrival`, `customs_processing`, `customs_hold`, `delay`, `rejected_paperwork`. Existing tokens unchanged. |
| `service/app/services/carrier/coordinator.py` | Add `is_awb_stable(awb: str) -> bool` read-only predicate. Definition: `True` when AWB ∈ {awb_issued, label_created, label_printed, handed_to_carrier}. No mutation; no new state. |
| `service/app/services/email_evidence_store.py` | Replace subject-keyed `thread_id` derivation for **DHL self-clearance emails only** (gated by sender/recipient match against `email_routing.DHL_TO`). Other email types continue using existing logic. Backwards-compatible: existing records' `thread_id` field unchanged. |
| `service/app/core/config.py` | Register new flags + config keys (default OFF / conservative): |

Config keys to add to `config.py` (all default-OFF or conservative). **Canonical naming convention: flat snake_case with `dhl_selfclearance_` prefix.** All consumer phases (P2-P5) must reference these literal identifiers verbatim; no dotted-path variants.

```python
# Phase-scoped live flags (default OFF — ADR-010). 6 live flags total.
# Asymmetry note: paired shadow_mode exists for 4 flags only.
# p3_tracker_paused is a kill switch (no shadow equivalent meaningful).
# p5_pz_trigger_enabled is an inner gate (no shadow equivalent — it
# permits/forbids the auto-PZ; shadow vs live is governed by p5_live_enabled).
dhl_selfclearance_p2_live_enabled:        bool  = False
dhl_selfclearance_p2_shadow_mode:         bool  = True
dhl_selfclearance_p3_live_enabled:        bool  = False
dhl_selfclearance_p3_shadow_mode:         bool  = True
dhl_selfclearance_p3_tracker_paused:      bool  = False   # kill switch
dhl_selfclearance_p4_live_enabled:        bool  = False
dhl_selfclearance_p4_shadow_mode:         bool  = True
dhl_selfclearance_p5_live_enabled:        bool  = False
dhl_selfclearance_p5_shadow_mode:         bool  = True
dhl_selfclearance_p5_pz_trigger_enabled:  bool  = False   # inner gate

# Classifier thresholds (literal identifiers — phases quote verbatim)
dhl_selfclearance_p4_classifier_min_confidence:  float = 0.85
dhl_selfclearance_p5_classifier_min_confidence:  float = 0.95   # higher — irreversible

# Follow-up scheduler (ADR-014 policy)
dhl_selfclearance_followup_working_interval_sec:  int  = 7200    # 2h
dhl_selfclearance_followup_offhours_interval_sec: int  = 21600   # 6h
dhl_selfclearance_followup_working_hours_window:  str  = "08:00-16:00 CET"
dhl_selfclearance_followup_livelock_budget_hours: int  = 168     # 1 week

# Path A clearance value threshold. Reading site lives in clearance_decision.py;
# this exposes it as config so an operator can override via the admin endpoint.
dhl_selfclearance_value_threshold_usd:    int  = 2500
```

All keys also surfaceable via the admin runtime-flags endpoint (read + write).

## FILES NOT TO BE MODIFIED

- `service/app/services/dhl_followup_sla.py` (legacy stays untouched per Decision 2)
- `service/app/services/dhl_proactive_dispatch_builder.py` (P2 territory)
- `service/app/services/dhl_reply_builder.py` (P1 territory)
- `service/app/services/dhl_self_clearance_builder.py` (P4 territory)
- `service/app/services/agency_*.py` (Path B; ADR-012 HL3)
- `service/app/services/inventory_state_engine.py` (P5 territory; HL2)
- `service/app/services/warehouse_db.py` (P5 territory; HL1)
- `service/app/services/sad_importer.py` (P5 territory)
- `service/app/services/customs_doc_classifier.py` (P5 territory)
- `service/app/services/email_classifier.py` (P5 territory — decision: separate classifier in P0, not extend this one)
- `service/app/static/dashboard.html` (no UI in P0)
- `service/app/main.py` — except for registering the new admin router (one-line `app.include_router(routes_admin_runtime_flags.router)`)

## ACCEPTANCE CRITERIA (testable)

1. **All 11 new files exist** with at least a public-API stub + docstring + corresponding test file.
2. **All 6 phase flags + 4 shadow_mode flags + 2 classifier-threshold flags + 4 follow-up-cadence flags + 1 value-threshold flag default to safe values** (booleans OFF, conservative numerics). Verify via `from app.core.config import settings` + assert each value.
3. **State engine round-trips:** all 13 states (9 + 4 added) are reachable via legal transitions starting from `awaiting_preemptive_send`; no illegal transition succeeds.
4. **Manifest writer helper** writes each namespace block (`p2_dispatch`, `p3_tracking`, `p4_followup`, `p5_clarifications`, `p6_sad`, `p7_pz`) without collision; `state_history` append-only verified.
5. **Classifier scaffold:** returns one of 4 intents OR `unknown`; confidence in `[0, 1]`; unknown intent triggers fallback path (operator-review marker on manifest).
6. **Validation harness:** accepts a labelled corpus file (CSV/JSONL), runs classifier on each entry, emits accuracy report. Corpus path is a CLI argument; absent corpus → harness logs `corpus_not_provided` and exits gracefully (no crash).
7. **Per-thread reply lock:** `acquire` returns `True` on first call; `False` on second concurrent call for same thread_id; `release` allows next acquire; expired TTL allows reacquire.
8. **RFC822 thread tracker:** parses `References:` + `In-Reply-To:` headers; resolves to a stored thread_id; falls back to AWB-keyed search if both absent; appends to `thread_id_aliases[]` on DHL-initiated fresh thread.
9. **`is_awb_stable()`:** returns `True` only when carrier state ∈ {awb_issued, label_created, label_printed, handed_to_carrier}; `False` otherwise (including pre-awb, awb_pending, voided, returned).
10. **Tracking normalizer:** emits the 5 new tokens on the right substatus inputs; existing tokens unchanged on all current test fixtures (regression-safe).
11. **`dhl_selfclearance_followup_v2.py`:** `next_tick_time(now)` returns the correct cadence value per ADR-014 (working-hours / offhours / livelock-budget-exceeded). No outbound SMTP.
12. **Admin runtime-flags endpoint:**
    - `POST /api/v1/admin/runtime-flags/self-clearance` with missing/invalid `X-API-Key` → 401 with templated error (`{detail: "Authentication required"}` — no raw exception strings per engineering discipline rule).
    - With valid key + valid body → 200 + audit log entry `admin_runtime_flag_flipped` with `(actor, flag_name, old_value, new_value, timestamp)`.
    - With invalid flag name → 400 + templated error (`{error_code, field, hint}`).
    - `GET /api/v1/admin/runtime-flags/self-clearance` returns current flag map.
    - Restartless: subsequent `settings.dhl_selfclearance_pN_*` reads reflect the new value within one read cycle without service restart.
13. **make verify: 160/160 unchanged.** **pytest -k "selfclearance_p0 or dhl_clearance_state or dhl_thread_lock or admin_runtime_flags or tracking_normalizer or carrier_coordinator" → green.**
14. **No regression** on existing `dhl_followup_sla.py` tests (legacy untouched).
15. **No regression** on existing `email_evidence_store.py` tests for non-DHL email types.
16. **Doc-vs-code consistency:** README + Master Plan + this P0 instruction reference files that now exist on the branch.

## SHADOW→LIVE PROMOTION GATE

P0 is structural; there's no "go live" step. The promotion gate for P0 is the merge gate:

- ≥4 reviewer agents return green:
  - `system-architect`
  - `gap-hunter`
  - `production-readiness-reviewer`
  - `backend-safety-reviewer`
- All acceptance criteria above verified.
- `make verify` + targeted pytest green.
- Named human review of the admin runtime-flags endpoint route by **Security Reviewer** (Tejal acceptable; external consult acceptable).

## ROLLBACK PROCEDURE

- Single command: `git revert <merge_sha>` on `main`. P0 is structural — no data migration, no schema lock-in. New files become absent again; modified files revert to pre-P0 versions.
- Default-OFF flags mean no behaviour was ever fired against production, so no operational state to unwind.
- If `email_evidence_store.py` change disrupts non-DHL email handling: the change is gated by sender/recipient match, so non-DHL traffic continues using existing logic. If a bug surfaces, revert just that file via `git checkout <pre-P0-sha> -- service/app/services/email_evidence_store.py` and re-PR.

## CONSTRAINTS

- Do NOT touch `main` directly. New branch, PR-only.
- Default-OFF per ADR-010 for every new flag.
- Do NOT extend `email_classifier.py` (separate classifier per design Decision).
- Do NOT modify `dhl_followup_sla.py` (legacy stays).
- Do NOT modify `agency_*.py`, `inventory_*.py`, `warehouse_db.py`, `sad_importer.py`.
- Do NOT add operator-facing UI on Mac dashboard (Windows Atlas memory rule).
- Honor engineering discipline rules: all admin endpoint errors are templated (`{detail, error_code, field, hint}`); NO raw exception strings reach the API surface.
- Doc-vs-code consistency check before merge: README + Master Plan refer to existing-on-this-branch files only.

## ESCALATION CRITERIA (true business decisions only)

- The state machine adds a 14th state during implementation (e.g., a real edge case surfaces beyond the 4 added). Operator decides whether to extend the ADR or close the gap differently.
- The admin endpoint surface needs scope expansion beyond self-clearance (e.g., generic runtime-flags for any phase across any workstream). Operator decides whether to genericize now or later.
- A scaffold item turns out to require a code change in a file in the FILES-NOT-TO-BE-MODIFIED list. STOP and escalate.

## FINAL REPORT SHAPE (9 sections)

1. Understanding
2. Agents activated (≥4 distinct: system-architect, gap-hunter, production-readiness-reviewer, backend-safety-reviewer)
3. What Was Implemented (per scaffold item)
4. Test results (per-file pytest + full dashboard + make verify)
5. Acceptance criteria check (one row per criterion 1-16 above)
6. Operator review evidence (admin endpoint round-trip + audit log line + Security Reviewer sign-off)
7. STATUS: MERGED-TO-MAIN / BLOCKED with reasons
8. Assumptions made
9. Rollback evidence (single `git revert` command + estimated recovery time)

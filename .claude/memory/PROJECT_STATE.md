# PROJECT_STATE.md

Source of truth for the current project execution state. Read this file at the start of every new session before any task work begins.

Owned by `flow-context-keeper`. Do not edit by hand outside of an emergency. Last updated by the agent on initialisation, 2026-05-13.

**Last-run-at:** 2026-05-13T08:55:00Z (RULE 3 + RULE 6 auto-fire by `flow-context-keeper` for PR #72 P2 ignition switch merge; multi-PR refresh covering PRs #62, #64, #65, #66, #67, #72 plus two direct-to-main commits since the last PROJECT_STATE update). Prior run: 2026-05-13T08:30:00Z (observation-layer audit closure). Naive orchestrators should check this timestamp before re-firing `flow-context-keeper` within the same chat turn.

---

# FACTS

## Current origin/main HEAD
- **2026-05-13** — `6ad26ed` Merge pull request #72 from amitpoland/feat/p2-ignition-switch-model-c

## Merged PRs (this session window, latest first)
- **#72** 2026-05-13T08:24:03Z — feat(w5-p2-ignition): Model C sweep + admin override + ADR-019 — merge SHA `6ad26ed`
- **#67** 2026-05-13T07:??:??Z — fix(email): attempt immediate SMTP send after queue_email() — merge SHA `4d595ca` (direct-to-main fast-fix; see Open Questions on commit-vs-PR record)
- **#66** 2026-05-13T07:11:12Z — fix(ui): forgot-password.html copy reflects new email-delivery flow — merge SHA `69309a5`
- **#65** 2026-05-13T06:47:58Z — fix(auth): forgot-password emails reset code to user; admin recovery endpoint — merge SHA `ec71a5d`
- **#64** 2026-05-13T06:24:03Z — chore(observation-layer): close PR #50 scorecard audit + add Lesson C — merge SHA `e2d9702`
- **#62** 2026-05-13T01:28:48Z — chore(observation-layer): RULE 6 visibility — scorecard + PROJECT_STATE for 3-PR sequence — merge SHA `1e84df8`
- **#61** 2026-05-13T01:22:36Z — feat(admin-runtime-flags): override-flag predecessor-live enforcement (Issue #49) — merge SHA `9bfa282`
- **#57** 2026-05-13T01:04:10Z — feat(admin-runtime-flags): per-phase concurrency lock for combined-state validator (Issue #48) — merge SHA `854cd2a`
- **#52** 2026-05-13T00:48:12Z — chore(adr): salvage 10 ADR files from archived feature branch (Issue #44) — merge SHA `e20e8d8`
- **#50** 2026-05-13T00:26:33Z — feat(admin-runtime-flags): combined-state validator (ADR-018) for all P2/P3/P4/P5 phase pairs — merge SHA `8cd7188`
- **#47** 2026-05-12T23:54:24Z — chore(observation-layer): verify activation + record engineering lessons (Lessons A+B) — merge SHA `f08e794`
- **#46** 2026-05-12T23:26:44Z — feat(w5-p2): proactive customs dispatch — shadow + live under ADR-018 — merge SHA `996e9f0`
- **#43** 2026-05-12T23:07:45Z — chore(governance): ADR-018 amending ADR-010 for shadow-mode flag category — merge SHA `0ac4769`
- **#41** 2026-05-12T23:00:18Z — chore(governance): meta-agent observation layer — merge SHA `1af3559`
- **#37** 2026-05-12 — fix(proforma): move PZ recovery helper out of pure-builder module — merge SHA `2ac9a02`
- **#35** 2026-05-12 — chore(governance): add 6 MANDATORY GOVERNANCE GATES + restore gap-hunter/adr-historian — merge SHA `bb75c14`
- **#34** 2026-05-12 — docs(inventory): refresh docs 1-4 against on-main code (closes #27)
- **#32** 2026-05-12 — fix(returns-ui): state-gate corrections, DB_CONSTRAINT mapping, stale registry
- **#31** 2026-05-12 — chore(w5): commit P0-P5 planning artifacts + update program board
- **#24** 2026-05-12 — chore(governance): add W-9 inventory + W-10 sample-out S2 + W-11 reconciliation rows
- **#23** 2026-05-12 — feat(security): hybrid auth guard + close tracking_db /events* endpoints
- **#22** 2026-05-12 — feat(B.2): Returns lifecycle backend — RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER
- **#21** 2026-05-12 — feat(B.1): Stage 2 aggregator counts SAMPLE_OUT for samples tile
- **#20** 2026-05-12 — fix(ui): correct stale Inventory page copy after Move stock + Sample-out went live
- **#19** 2026-05-12 — feat(inventory): add unified piece timeline to drawer
- **#18** 2026-05-12 — ui(B.1): Sample-out drawer surfaces — pill, aging, mutation forms
- **#17** 2026-05-12 — feat(inventory): add Sample-out lifecycle transitions
- **#16** 2026-05-12 — feat(inventory): activate Move stock location action
- **#15** 2026-05-12 — feat(inventory): Group B — combined read-path integration

## Direct-to-main commits (no PR; recorded for completeness)
- **2026-05-13** — `1b38ea0` fix(pdf): add Windows font paths + bundle DejaVuSans for Polish PDF generation — direct merge, no PR record
- **2026-05-13** — `80e3469` fix(dhl): fix email search for AWB 1196338404 — correct API base, ticket regex, 401 propagation — direct merge, no PR record

## PR #72 P2 ignition switch detail (2026-05-13T08:24Z)
- **Model C wired**: sweep-primary + admin override route (locked per design doc `02b_P2_IGNITION_SWITCH_DESIGN.md` + ADR-019).
- **ADR count on main: 19** (was 18 before #72; ADR-019 added documenting Model C choice and `force=True` semantics).
- **P2 ignition switch state: SHADOW-READY** — sweep wired, admin route live, ADR-018 truth-table default (SHADOW) preserved. Live promotion still gated on the 48h shadow window opened by PR #46.
- **Test state**: full suite 7241 passed / 103 failed (baseline preserved — pre-existing failures unrelated to P2 ignition). Targeted P2 panel: **261/261 PASS**.
- **8-agent review applied inline**: `fix(w5-p2-ignition): apply 8-agent review fixes inline` (commit `4292b6c`) lands path-traversal hardening + input-sanitisation at the admin route layer (security review MEDIUM fixes).
- **Force=True semantics**: admin-only, audited (reason ≥10 chars, actor ≥3 chars), WARNING-level audit, archives prior to `p2_dispatch_history[]`, bypasses ADR-013 idempotency but NOT ADR-018 truth table.
- **Gate-flip legacy**: `dhl_selfclearance_legacy_path_a_queue_enabled` defaults to `False` — rollback escape valve only.

## Auth-fix campaign closure (PRs #65, #66, #67)
- **PR #65** lands two changes: (a) forgot-password emails now reset the verification code on every send (prior behaviour: stale code persisted), (b) admin recovery endpoint added for cases where email delivery is blocked.
- **PR #66** updates `forgot-password.html` copy to reflect the new email-delivery flow.
- **PR #67** attempts immediate SMTP send after `queue_email()` (no longer wait for the SMTP queue worker for password-reset emails — operator-experience fix).
- **Tejal lockout incident (session-close memo)**: RESOLVED via #65 + #66 (UI copy + admin recovery endpoint) and #67 (immediate SMTP send). No further work required on that incident.

## Validator-hardening 3-PR sequence detail (2026-05-13)
- **PR #52 ADR salvage** — 10 ADR files restored from `archive/feature-dhl-label-workflow-planning-2026-05-13` tag onto main (ADR-001..005, 007..009, 011, 017). Total ADR count on main post-PR #52: 18. Issue #44 closed at 2026-05-13T00:48:13Z.
- **PR #57 per-phase concurrency lock** — 4 `threading.Lock` instances created (one per phase: P2, P3, P4, P5). 5-second `lock.acquire(timeout=5)` blocking semantics; on timeout returns 503. Production NSSM `PZService` runs single-process → per-phase lock is correct for current deployment. Issue #48 closed at 2026-05-13T01:04:12Z.
- **PR #61 override-flag predecessor-live enforcement** — chained predecessor model wired into validator: P3 requires P2-live, P4 requires P3-live, P5 requires P4-live. `--override-predecessor` flag with explicit audit-log entry. Issue #49 closed at 2026-05-13T01:22:37Z.

## Open PRs
- **#10** feat(inventory): Risk-3/4 button stubs — deferred per operator instruction; do not touch.
- **#8** docs(inventory): Doc 4 — failure modes — superseded by PR #34 merge (closeable / archiveable).
- **#7** docs(inventory): Doc 3 — data source mapping — superseded by PR #34.
- **#6** docs(inventory): Doc 2 — button registry — superseded by PR #34.
- **#5** docs(inventory): Doc 1 v2 — allocation ledger — superseded by PR #34.
- **#4** docs(inventory): Phase 1 inspector report.
- **#1** ui: align sidebar IA with Estrella Atlas design — historical Atlas branch (REFERENCE_ONLY pending).

(Open implementation-PR count: 1 [#10]. Open docs-PR count: 6. GATE 2 limit honored.)

## Closed issues (this session window, latest first)
- **#49** 2026-05-13T01:22:37Z — Admin runtime-flags: predecessor-live cross-system gap (closed by PR #61)
- **#48** 2026-05-13T01:04:12Z — Admin runtime-flags: per-phase concurrency lock (closed by PR #57)
- **#44** 2026-05-13T00:48:13Z — Salvage 10 ADR files from archived feature branch (closed by PR #52)
- **#27** 2026-05-12T22:35:26Z — Refresh inventory design docs 1-4 (closed by PR #34)

## Open issues (latest first; new follow-ups from PR #72 P2 ignition campaign at top)
- **#71** F-IGN-5 Sweep cooldown tuning post-shadow-window (filed from PR #72 review; GATE 4 disposition: SCHEDULED for post-shadow-corpus analysis).
- **#70** F-IGN-4 Extract `resolve_audit_awb` shared helper (filed from PR #72; refactor candidate).
- **#69** F-IGN-3 Unify legacy `clearance_status` vs new `dhl_clearance.state` field (filed from PR #72; data-model drift).
- **#68** F-IGN-2 Sweep heartbeat audit + dead-man's-switch alarm (filed from PR #72; observability follow-up).
- **#67** F-IGN-1 Atlas-side P2 hold/rescue UI integration (filed from PR #72; Atlas-side P2 surface — connects to ignition switch).
- **#63** Meta-agent prompt hardening: absolute-path Write + post-Write self-verification (Lesson C followup).
- **#60** Admin runtime-flags: GET /audit query endpoint for operator review (system-architect note from PR #58 review thread). GATE 4 disposition (override-polish bucket).
- **#59** Admin runtime-flags: request_id correlation for audit events (gap-hunter F8 from PR #58). GATE 4 disposition (override-polish bucket).
- **#58** Admin runtime-flags: cascade endpoint for multi-phase live promotion (gap-hunter F3 from PR #58). GATE 4 disposition (override-polish bucket).
- **#56** Admin runtime-flags: audit-log file-locking on Windows (gap-hunter F4 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#55** Admin runtime-flags: audit-write-failure observability (gap-hunter F3 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#54** Admin runtime-flags: write-ordering durability (gap-hunter F2 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#53** Admin runtime-flags: cross-worker safety hardening (gap-hunter F1 from PR #53) — multi-worker hardening blocker; tracks the path off single-process NSSM if architecture shifts. GATE 4 disposition (lock-hardening bucket).
- **#51** ADR drift reconciliation: successor ADRs needed for 8 salvaged ADRs (gap-hunter F1-F11 from PR #51) — blocks downstream ADR-drift cleanup until reconciled. GATE 4 disposition.
- **#45** P2 follow-ups: concurrency lock, silent state-skew logging, retry semantics, AWB subject assertion. (Concurrency lock subsumed by Issue #48 close via PR #57.)
- **#42** ADR-018 follow-ups: P5 3-flag truth table, kill-switch category, admin validator, transitive DORMANT.
- **#40** Meta-agent layer: 5 follow-up gaps from gap-hunter review of observation-layer PR.
- **#39** Defer agent-prompt-refiner and pattern-historian until observation baseline established.
- **#38** P2-P5 phase preconditions: 5 gap-hunter findings on PR #33 — SCHEDULED per phase.
- **#36** Governance gates refinement — wording + coverage amendments from agent review of PR #35.

## Active branches (per GATE 3 status designation)

| Branch | Status | Note |
|---|---|---|
| `feat/p2-ignition-switch-model-c` | ACTIVE → eligible-for-archive | PR #72 merged |
| `fix/forgot-password-emails-reset-code-to-user` | ACTIVE → eligible-for-archive | PR #65 merged |
| `fix/forgot-password-html-copy` | ACTIVE → eligible-for-archive | PR #66 merged |
| `chore/observation-layer-audit-closure` | ACTIVE → eligible-for-archive | PR #64 merged |
| `chore/observation-layer-rule6-visibility-3pr-sequence` | ACTIVE → eligible-for-archive | PR #62 merged |
| `chore/dhl-selfclearance-p0-foundation` | ACTIVE → eligible-for-archive | PR #33 superseded by PR #43/#46/#50 cascade |
| `chore/admin-runtime-flags-combined-state-validator` | ACTIVE → eligible-for-archive | PR #50 merged |
| `chore/admin-runtime-flags-per-phase-lock` | ACTIVE → eligible-for-archive | PR #57 merged |
| `chore/admin-runtime-flags-predecessor-override` | ACTIVE → eligible-for-archive | PR #61 merged |
| `chore/adr-salvage-from-archived-feature-branch` | ACTIVE → eligible-for-archive | PR #52 merged |
| `chore/observation-layer-verification-and-lessons` | ACTIVE → eligible-for-archive | PR #47 merged |
| `feature/dhl-label-workflow-planning` | REFERENCE_ONLY | salvage-audit verdict 2026-05-13: FULL ABANDON; archive tag exists |
| `feat/inventory-risk34-stubs` | ACTIVE (deferred) | Risk-3/4 stubs — operator instruction: do not touch |
| `feat/doc-1-v2-allocation-ledger` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-2-button-registry` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-3-data-source-mapping` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-4-failure-modes` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `claude/zealous-johnson-6d6d34` | ACTIVE | UI sidebar IA — PR #1 |
| `archive/may9-stale-main` | ARCHIVED | pre-existing archive |
| `archive/feature-dhl-label-workflow-planning-2026-05-13` | ARCHIVED (tag) | salvage-source for PR #52 |

## Archive tags
- `archive/may9-stale-main` (pre-existing; predates this session)
- `archive/feature-dhl-label-workflow-planning-2026-05-13` — created prior to PR #52 ADR salvage; preserves the FULL-ABANDON branch as immutable reference

## Shadow windows currently active
- **W-5 P2 proactive customs dispatch** — shadow window opened on PR #46 merge (2026-05-12T23:26:44Z). With PR #72 P2 ignition switch SHADOW-READY, the dispatch path now runs via Model C sweep + admin override. Eligible for live promotion no earlier than 2026-05-14T23:26:44Z, gated on: (a) ≥48h elapsed shadow corpus, (b) ≥50 dispatches across ≥10 AWBs, (c) Tejal spot-check sign-off. ADR-018 truth-table default (SHADOW) preserved.

## Deployment status per machine
- **Mac (dev)** — current head `6ad26ed` ; PR #72 P2 ignition switch + auth-fix campaign + observation-layer audit closure all on main.
- **Windows (prod, NSSM `PZService` at `C:\PZ`, `https://pz.estrellajewels.eu`)** — NOT updated this session. Drift from main: **~12 PRs behind** (PRs #41, #43, #46, #47, #50, #52, #57, #61, #62, #64, #65, #66, #67, #72 + two direct commits `1b38ea0`, `80e3469`). Per CLAUDE.md "Production deployment rule": next deploy requires the full 7-agent gate. Single-process NSSM constraint remains the correctness window for `threading.Lock` (Issue #53 still dormant).

## Registry
- **2026-05-13** — Project registry healthy with 15 project agents at `.claude/agents/` (includes `gap-hunter`, `adr-historian`, `agent-performance-observer`, `flow-context-keeper`). Global registry at `~/.claude/agents/` has 54 agents. Total reachable agents in session: 79 (incl. plugin + built-in). No naming collisions.

## RULE 6 visibility entries (scorecards on disk + expected)
- **2026-05-13** — Scorecard on disk: `.claude/memory/scorecards/2026-05-13-w5-p0-adr018-p2-deployment-campaign.md` — observer: `agent-performance-observer` post PR #41 registry-refresh validation — 14 verdicts scored, all EXEMPLARY, zero NEEDS-TUNING / UNRELIABLE.
- **2026-05-13** — Scorecard on disk: `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` — observer: `agent-performance-observer` covering the PR #52 / #57 / #61 sequence.
- **2026-05-13** — Scorecard on disk (RETROACTIVE): `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md` — observer: `agent-performance-observer` covering PR #50 (5 agent verdicts). Filename suffix `-RETROACTIVE` distinguishes from contemporaneously-produced scorecards.
- **2026-05-13** — Scorecard on disk: `.claude/memory/scorecards/2026-05-13-observation-audit-closure.md` — observer: `agent-performance-observer` auto-fire for the observation-layer audit closure (3 agent verdicts).
- **2026-05-13** — Scorecard EXPECTED but NOT YET CONFIRMED ON DISK in this worktree: `.claude/memory/scorecards/2026-05-13-w5-p2-ignition-switch-model-c.md` — observer fire is concurrent with this `flow-context-keeper` run; per Lesson C the file's presence must be verified before being cited as `on disk`. If absent at next session, file under Issue #63 (Lesson C followup).
- **2026-05-13** — Possible self-eval scorecard EXPECTED: `.claude/memory/scorecards/self-eval-2026-05-13.md` (RULE 5 cadence triggers if 5th-since-last-eval or >7 days). NOT YET CONFIRMED ON DISK in this worktree; pending observer fire completion. See OPEN QUESTIONS.
- **2026-05-13** — Engineering lessons file: `.claude/memory/engineering_lessons.md` — Lesson A (test-stub return-shape mismatch, origin PR #46) + Lesson B (mid-session registry refresh non-determinism, origin PR #41) + Lesson C (orchestrator-side post-write scorecard verification, origin PR #64) are binding rules.

## Observation-layer audit closure (appended 2026-05-13T08:30Z; carry-forward)
- **Validator hardening cycle: COMPLETE.** All 3-PR validator-hardening sequence (#52 → #57 → #61) plus originating PR #50 have observability artifacts on disk.
- **P2 ignition switch: SHADOW-READY** (PR #72 lands Model C sweep + admin override; ADR-019 added). The combined-state validator + per-phase lock + predecessor-override stack now has the operator-facing flip mechanism wired. Live promotion still gated on 48h shadow corpus.
- **No production deployment yet.** Windows machine ~12 PRs behind main; deferred until next deploy window per CLAUDE.md "Production deployment rule" (7-agent gate required).

## Promoted from ASSUMPTIONS to FACTS (2026-05-13T08:55Z, this run)
- **Model C correctly handles sweep + admin dual-caller dedup**: VERIFIED by 261/261 P2-panel tests + 8-agent gate (PR #72). The sweep and admin-override paths are serialised against ADR-013 idempotency at the dispatch-history-append boundary; `force=True` is the only legal bypass and is audit-traced.
- **Per-phase `threading.Lock` correctness on single-process NSSM** (carry-forward): VERIFIED by PR #57 merge + 204/204 test panel green.
- **Override-flag predecessor chain semantics (P3→P2, P4→P3, P5→P4)** (carry-forward): VERIFIED by PR #61 merge + override-bypass audit-log entry exercised in regression suite.

---

# DECISIONS

## Bound operator decisions

- **GATE 2 limit** — max 3 simultaneous open implementation PRs (+1 docs/governance exception). Source: PR #35 / CLAUDE.md MANDATORY GOVERNANCE GATES.
- **Windows Atlas is primary operator UI surface.** Mac dashboard is read-only for operators going forward. Source: memory `windows_atlas_ui_primary_2026-05-12`.
- **`feature/dhl-label-workflow-planning` = REFERENCE_ONLY**, archive tag `archive/feature-dhl-label-workflow-planning-2026-05-13` exists. Salvage finding (10 ADRs) executed via PR #52. Source: salvage audit final report + PR #52 merge.
- **Tejal is primary P5 reviewer; Amit is backup.** Tejal labels classifier corpus; Amit spot-checks 10-15%. Source: memory `dhl_selfclearance_program_2026-05-12`.
- **`dhl_followup_sla.py` reconciliation = v2-alongside-legacy (P0 Decision 2)** — coordinator routes by `clearance_path`; legacy stays untouched until operational evidence justifies deprecation. Source: P0 spec `01_P0_FOUNDATION.md`.
- **W-5 program firing order: P0 → P2 → P3 → P4 → P5.** P3 + P4 cannot share a session. P5 design may overlap P4 shadow; P5 shadow cannot begin until P4 is live. Source: master plan `00_MASTER_PLAN.md`.
- **Classifier is the single point of catastrophic failure** for P4/P5. Required: ≥200 shadow classifications + Customs Compliance Reviewer sign-off before P4 live; 100% SAD/PZC precision + Inventory/Finance Reviewer sign-off before P5 live. Source: master plan §4.5 R2.
- **Engineering discipline rules (locked 2026-05-12)** — doc-vs-code consistency gate (Issue #27 pattern), API error templating (`{detail, error_code, field, hint}`), exception-leak prevention. Source: memory `engineering_discipline_rules`.
- **agent-prompt-refiner and pattern-historian deferred** pending two campaigns under observation-layer baseline. Source: PR #41 + Issue #39.

## Engineering lessons governance (carry-forward 2026-05-13)

- **Engineering lessons are append-only.** Supersede with new dated entries; never delete. Source: `.claude/memory/engineering_lessons.md` header + CLAUDE.md "Engineering Lessons (permanent)" section.
- **Lesson A enforcement is jointly owned**: `integration-boundary` (primary — type-contract review at coordinator/builder boundary), `testing-verification` (regression test against the REAL builder, no stub), `backend-safety-reviewer` (boundary `_normalise_X` helper presence). All three must sign off on any coordinator/consumer-to-builder wiring PR.
- **Network-bound boundary carve-out for Lesson A**: contract tests against recorded fixtures (VCR/recorded responses) substitute for real-builder regression tests on DHL / wFirma / SMTP / Cliq boundaries.
- **Lesson C (locked 2026-05-13, origin PR #64)** — orchestrator-side post-write scorecard verification: after every observer scorecard auto-fire, the orchestrator (or `flow-context-keeper` on its own scorecard-citation runs) must confirm the scorecard file is on disk before citing it as `on disk`. Missing files re-fire the observer or escalate. Tracked in Issue #63.

## Validator-hardening decisions (carry-forward 2026-05-13, 3-PR sequence)

- **Per-phase lock granularity (Issue #48)** — chosen over global-lock and per-flag-lock alternatives. Per-phase scope matches the FORBIDDEN-state invariant. Source: PR #57 + Issue #48 close thread.
- **Override-flag predecessor model (Issue #49)** — chosen over strict-no-override and warn-only alternatives. Override requires explicit `--override-predecessor` flag with audit-log entry. Source: PR #61 + Issue #49 close thread.
- **Cross-worker safety posture** — production NSSM verified single-process; `threading.Lock` is correct for current deployment. Multi-worker hardening tracked in Issue #53; no work scheduled until deployment topology changes.
- **Three-PR sequencing (Option B) over atomic single PR** — preferred for clean per-step rollback + GATE 2 compliance.

## P2 ignition switch decisions (appended 2026-05-13T08:55Z, PR #72)

- **Model C for P2 ignition: sweep primary + admin override route** — chosen over Model A (admin-only) and Model B (auto-only). Source: design doc `02b_P2_IGNITION_SWITCH_DESIGN.md` + ADR-019 + PR #72 merge. Rationale: sweep handles the steady-state dispatch backlog without operator intervention; admin override gives the operator a controlled escape valve for one-off interventions. Both paths share the same ADR-018 truth-table and ADR-013 idempotency guarantees.
- **`force=True` semantics on admin override** — admin-only, audited (reason ≥10 chars, actor ≥3 chars), WARNING-level audit entry, archives prior dispatch records to `p2_dispatch_history[]`, bypasses ADR-013 idempotency but NOT ADR-018 truth table. Source: ADR-019 + PR #72 review thread. Rationale: idempotency bypass is occasionally needed (legitimate retry of a stuck dispatch); truth-table bypass would defeat the safety property and is therefore forbidden.
- **Gate-flip legacy: `dhl_selfclearance_legacy_path_a_queue_enabled` defaults False** — rollback escape valve only. Source: PR #72. Rationale: legacy path must NOT receive new dispatches by default; only explicit operator opt-in (during a rollback drill) flips it.
- **Path-traversal + input-sanitisation enforced at admin route layer** — security review MEDIUM fixes landed inline in PR #72 (commit `4292b6c`). Source: PR #72 8-agent review. Rationale: admin endpoints are operator-trust-boundary; defensive sanitisation at the route layer prevents path-traversal pivots from admin into arbitrary file access.

## Observation-layer governance (carry-forward 2026-05-13T08:30Z, audit-closure run)

- **Retroactive scorecards are valid governance artefacts** when a contemporaneous auto-fire failed silently. Filename suffix `-RETROACTIVE` distinguishes them; a header note explains origin. Source: PR #50 anomaly resolution + PR #64.
- **PR #50 scorecard root cause: NOT a DECISION (recorded as OPEN QUESTION instead).** Three hypotheses remain. Recording as OPEN QUESTION rather than DECISION preserves accuracy: we have not yet chosen a corrective rule, only acknowledged the gap. Lesson C (above) is the closest we have to a corrective rule and is now locked.

## Next 3 actions in queue

1. **W-5 P2 shadow corpus monitoring + live promotion gate** — collect ≥48h of real DHL dispatch shadow classifications + ≥50 dispatches across ≥10 AWBs + Tejal spot-check sign-off. Target outcome: P2 promoted from SHADOW to LIVE. Gating: shadow window opened 2026-05-12T23:26:44Z (PR #46); eligible no earlier than 2026-05-14T23:26:44Z. Downstream effect: unblocks P3 design start per W-5 program firing order.
2. **Windows production deployment (catch up ~12 PRs)** — Windows machine drifted from main since the last verified deploy. Target outcome: Windows `C:\PZ` at SHA `6ad26ed` (or later) with PZService restarted via NSSM. Gating: full 7-agent gate per CLAUDE.md "Production deployment rule" (`/deploy` slash command); 160/160 PZ tests + 366/366 carrier tests must remain green; single-process NSSM constraint preserved so per-phase `threading.Lock` correctness window holds.
3. **Verify PR #72 scorecard on disk and decide on self-eval cadence** — confirm `.claude/memory/scorecards/2026-05-13-w5-p2-ignition-switch-model-c.md` is on disk per Lesson C. Decide whether RULE 5 self-eval is due (5th-since-last or >7 days). Target outcome: scorecard file confirmed (or retroactively produced + filed under Issue #63), self-eval status decided. Gating: must complete before next observer auto-fire to honor RULE 6 visibility.

---

# ASSUMPTIONS

- **P2 shadow window will accumulate ≥48 hours of real-time DHL dispatch volume AND ≥50 dispatches across ≥10 AWBs by 2026-05-14T23:26:44Z** before promotion to live. Source: master plan §4.3 + shadow-window opened on PR #46 merge + PR #72 promotion gate. Move to FACTS by reading shadow-classification count + duration from admin runtime-flags audit log + Tejal spot-check sign-off note.
- **The carrier vocabulary mapping in `is_awb_stable` (SUBMITTED ∪ COMPLETE = stable) is correct for production use.** Source: P0 commit message + system-architect verdict. Move to FACTS when P2 shadow corpus produces the expected gate behaviour against real AWBs.
- **The Phase 1.3 email routing migration (`service/app/config/email_routing.py`) shipped and all 14+ consumer services use it.** Source: P0 spec prerequisite note. Move to FACTS by running `grep -rln "from ..config.email_routing import" service/app/ | wc -l` and confirming ≥14.
- **PR #72 P2 ignition scorecard was written to disk by the observer in this run.** Source: RULE 3 auto-fire trigger in operator's brief. Move to FACTS once `ls .claude/memory/scorecards/2026-05-13-w5-p2-ignition-switch-model-c.md` returns success (per Lesson C).
- **Auth-fix PRs (#65, #66, #67) resolve the Tejal lockout incident end-to-end** — operator brief asserts incident is resolved. Source: session-close memo. Move to FACTS when Tejal confirms successful password reset against production.

---

# OPEN QUESTIONS

- **Is the PR #72 P2 ignition switch scorecard on disk?** Answerer: next session opening (Lesson C verification). Impact: if absent, RULE 6 visibility for the P2 ignition campaign is missing; would require retroactive scorecard production analogous to the PR #50 fix. Cross-reference: Issue #63 (Lesson C followup).
- **Did RULE 5 self-eval cadence fire for 2026-05-13?** Answerer: next session opening. Impact: if the 5th-scorecard-since-last-self-eval or >7-day-elapsed threshold was crossed, a self-eval scorecard should exist at `.claude/memory/scorecards/self-eval-2026-05-13.md`. Currently NOT on disk in this worktree. Possible remediation paths: (a) `agent-performance-observer` re-fire with explicit self-eval directive, or (b) defer to next observer fire if cadence not yet triggered.
- **P2 live promotion** — when does the operator (with Tejal sign-off) flip P2 from SHADOW to LIVE? Answerer: operator + Tejal. Impact: gates W-5 P3 design start per program firing order. Currently gated by (a) 48h shadow window opening 2026-05-12T23:26Z → eligible 2026-05-14T23:26Z, (b) ≥50 dispatches across ≥10 AWBs gate, (c) Tejal spot-check.
- **Windows production catch-up — when does the next deploy window open?** Answerer: operator. Impact: production at `C:\PZ` runs ~12 PRs behind main, including the full admin runtime-flags stack + P2 ignition switch + auth-fix campaign. Per CLAUDE.md "Production deployment rule": deploy requires the 7-agent gate via `/deploy`. Single-process NSSM constraint must remain to preserve per-phase lock correctness.
- **Root cause of original PR #50 auto-fire failure?** (carry-forward) Answerer: future investigation if reproducible (currently not). Impact: silent observer-write failures could recur and undermine RULE 6 visibility. Lesson C now binds the corrective rule (orchestrator-side post-write verification); root-cause diagnosis remains open.
- **Should the direct-to-main commits `1b38ea0` (PDF fonts) and `80e3469` (DHL email AWB fix) have gone via PR for GATE 1 compliance?** Answerer: operator. Impact: governance precedent. GATE 1 ("PR open discipline") may or may not apply to hotfix-class commits; if it does, these two commits represent a gap.
- **Tejal availability for P4 / P5 reviewer gates** — not yet confirmed for the May-June window. Answerer: Tejal (via operator). Impact: gates P4 live promotion + P5 live promotion.
- **When are the obsolete `feat/doc-1..4` branches and the newly-eligible-for-archive `chore/*` + `fix/*` + `feat/p2-ignition-switch-model-c` branches tagged-and-deleted?** Answerer: operator preference. Impact: branch hygiene; harmless if left.
- **Issue #51 ADR drift reconciliation — when is it fired?** Answerer: operator scheduling. Impact: blocks downstream ADR-drift cleanup. The 8 salvaged ADRs (subset of 10 from PR #52) need successor ADRs documenting how P0/P2 superseded them. The new ADR-019 (Model C) does NOT reconcile this drift.
- **Issue #53 cross-worker safety hardening** — when does it fire? Answerer: operator (likely never unless deployment topology shifts off single-process NSSM). Impact: dormant correctness debt.
- **Issues #54/#55/#56 lock-hardening polish** — when do they fire? Answerer: operator scheduling. Impact: incremental hardening of the per-phase lock; none currently blocking.
- **Issues #58/#59/#60 override polish** — when do they fire? Answerer: operator scheduling. Impact: operator UX improvements on top of the predecessor-override mechanic; none currently blocking.
- **Issues #67/#68/#69/#70/#71 P2 ignition follow-ups** — when do they fire? Answerer: operator scheduling. Impact: Atlas-side P2 hold/rescue UI (#67) is the most visible operator-facing gap; sweep heartbeat (#68) is observability; legacy-vs-new state field unification (#69) is data-model drift cleanup; `resolve_audit_awb` helper extraction (#70) is refactor; sweep cooldown tuning (#71) is post-shadow analysis.
- **Cumulative ADR drift work** — blocked on Issue #51 resolution. Until #51 is reconciled, downstream ADR work (e.g. ADR-018 follow-ups in Issue #42, ADR-019 successor expectations) carries semantic risk of stacking onto unreconciled successor relationships.
- **Is the `_TOP_LEVEL_FIELDS` enforcement gap on `dhl_clearance_manifest.py` (system-architect LOW finding) acceptable to defer to P2 kickoff, or should it be addressed in a hotfix PR?** Answerer: operator. Impact: a future phase implementer could write a top-level field that bypasses the schema fence. Filed in Issue #38 as SCHEDULED for P2.

---

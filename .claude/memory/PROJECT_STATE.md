# PROJECT_STATE.md

Source of truth for the current project execution state. Read this file at the start of every new session before any task work begins.

Owned by `flow-context-keeper`. Do not edit by hand outside of an emergency. Last updated by the agent on initialisation, 2026-05-13.

**Last-run-at:** 2026-05-13T01:30:00Z (RULE 3 auto-fire by `flow-context-keeper` after 3-PR validator-hardening merge sequence #52 → #57 → #61 closed Issues #44/#48/#49 and filed 9 follow-up issues #51/#53–#56/#58–#60). Naive orchestrators should check this timestamp before re-firing `flow-context-keeper` within the same chat turn.

---

# FACTS

## Current origin/main HEAD
- **2026-05-13** — `9bfa282` Merge pull request #61 from amitpoland/chore/admin-runtime-flags-predecessor-override

## Merged PRs (this session window, latest first)
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

## Validator-hardening 3-PR sequence detail (2026-05-13)
- **PR #52 ADR salvage** — 10 ADR files restored from `archive/feature-dhl-label-workflow-planning-2026-05-13` tag onto main (ADR-001..005, 007..009, 011, 017). Total ADR count on main: **18** (was 8 before this PR). ADR README index now resolves all 18 links cleanly. Issue #44 closed at 2026-05-13T00:48:13Z.
- **PR #57 per-phase concurrency lock** — 4 `threading.Lock` instances created (one per phase: P2, P3, P4, P5) in the admin runtime-flags combined-state validator. 5-second `lock.acquire(timeout=5)` blocking semantics; on timeout returns 503 to caller. Production NSSM `PZService` runs single-process, so per-phase lock is correct for current deployment. Issue #48 closed at 2026-05-13T01:04:12Z.
- **PR #61 override-flag predecessor-live enforcement** — chained predecessor model wired into validator: P3 requires P2-live, P4 requires P3-live, P5 requires P4-live. Override flag (`--override-predecessor`) bypasses chain for phased rollout drills with explicit operator audit-log entry. Issue #49 closed at 2026-05-13T01:22:37Z.
- **Test state post-merge** — 204/204 PASS targeted across the 6-file admin/coordinator/state-engine/proactive-dispatch panel.
- **Sequencing model** — three-PR cascade (Option B) chosen over single atomic PR for clean per-step rollback + GATE 2 compliance (max 3 open). Each PR in/out before next opened.

## Open PRs
- **#10** feat(inventory): Risk-3/4 button stubs — deferred per operator instruction; do not touch.
- **#8** docs(inventory): Doc 4 — failure modes — superseded by PR #34 merge (closeable / archiveable).
- **#7** docs(inventory): Doc 3 — data source mapping — superseded by PR #34.
- **#6** docs(inventory): Doc 2 — button registry — superseded by PR #34.
- **#5** docs(inventory): Doc 1 v2 — allocation ledger — superseded by PR #34.
- **#4** docs(inventory): Phase 1 inspector report.
- **#1** ui: align sidebar IA with Estrella Atlas design — historical Atlas branch (REFERENCE_ONLY pending).

(Note: PR #33 ADR-010 conflict was resolved by PR #43 / #46 / #50 cascade — see merged list.)

## Closed issues (this session window, latest first)
- **#49** 2026-05-13T01:22:37Z — Admin runtime-flags: predecessor-live cross-system gap (closed by PR #61)
- **#48** 2026-05-13T01:04:12Z — Admin runtime-flags: per-phase concurrency lock (closed by PR #57)
- **#44** 2026-05-13T00:48:13Z — Salvage 10 ADR files from archived feature branch (closed by PR #52)
- **#27** 2026-05-12T22:35:26Z — Refresh inventory design docs 1-4 (closed by PR #34)

## Open issues (latest first; new follow-ups from 3-PR sequence at top)
- **#60** Admin runtime-flags: GET /audit query endpoint for operator review (system-architect note from PR #58 review thread). Filed under GATE 4 disposition (override-polish bucket).
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
- **#30** Refresh inventory design docs 1-4 against current main before next inventory feature (predates #27 — likely closeable).
- **#29** Sanitize INVALID_EVIDENCE detail before surfacing API errors.
- **#28** Test depth — single-field evidence-gate negatives + return replay coverage.
- **#26** INVALID_EVIDENCE detail sanitization — template-format raw exception strings.
- **#25** Test depth — single-field evidence-gate negatives + replay test for return-from-producer.

## Active branches (per GATE 3 status designation)

| Branch | Status | Note |
|---|---|---|
| `chore/dhl-selfclearance-p0-foundation` | ACTIVE → eligible-for-archive | PR #33 superseded by PR #43/#46/#50 cascade |
| `chore/admin-runtime-flags-combined-state-validator` | ACTIVE → eligible-for-archive | PR #50 merged |
| `chore/admin-runtime-flags-per-phase-lock` | ACTIVE → eligible-for-archive | PR #57 merged |
| `chore/admin-runtime-flags-predecessor-override` | ACTIVE → eligible-for-archive | PR #61 merged |
| `chore/adr-salvage-from-archived-feature-branch` | ACTIVE → eligible-for-archive | PR #52 merged |
| `chore/observation-layer-verification-and-lessons` | ACTIVE → eligible-for-archive | PR #47 merged |
| `feature/dhl-label-workflow-planning` | REFERENCE_ONLY | salvage-audit verdict 2026-05-13: FULL ABANDON; archive tag now exists (used as source for PR #52 salvage) |
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
- **W-5 P2 proactive customs dispatch** — shadow window opened on PR #46 merge (2026-05-12T23:26:44Z). Combined-state validator (ADR-018) now enforced per PR #50/#57/#61. Expected end: ≥48h of real DHL dispatch volume per master plan §4.3 → eligible for live promotion no earlier than 2026-05-14T23:26:44Z, gated on shadow-classification corpus + Tejal sign-off.

## Deployment status per machine
- **Mac (dev)** — current head `9bfa282` ; admin runtime-flags combined-state validator (ADR-018) + per-phase lock + predecessor-live override now on main.
- **Windows (prod, NSSM `PZService` at `C:\PZ`, `https://pz.estrellajewels.eu`)** — NOT updated this session. Significant drift from main (8 PRs merged 2026-05-12T23:00 → 2026-05-13T01:22 since last verified Windows deploy SHA). Per CLAUDE.md "Production deployment rule": next deploy requires the 7-agent gate. Single-process NSSM constraint matters for the per-phase lock correctness window — see Issue #53.

## Registry
- **2026-05-13** — Project registry healthy with 15 project agents at `.claude/agents/` (includes `gap-hunter`, `adr-historian`, `agent-performance-observer`, `flow-context-keeper`). Global registry at `~/.claude/agents/` has 54 agents. Total reachable agents in session: 79 (incl. plugin + built-in). No naming collisions.

## RULE 6 visibility entries (scorecards on disk + expected)
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-p0-adr018-p2-deployment-campaign.md` — observer: `agent-performance-observer` post PR #41 registry-refresh validation — 14 verdicts scored, all EXEMPLARY, zero NEEDS-TUNING / UNRELIABLE.
- **2026-05-13** — Scorecard expected (parallel run with this keeper invocation): `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` — observer: `agent-performance-observer` covering the PR #52 / #57 / #61 sequence. **Anomaly:** file not yet present in worktree at time of this PROJECT_STATE update; visibility-entry recorded per RULE 6 with the expected path so future readers can confirm the citation lands.
- **2026-05-13** — Scorecard expected (PR #50 cycle): `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator.md`. **Anomaly:** file not present in worktree. Worktree-side scorecards directory contains only `.gitkeep` and the deployment-campaign scorecard. PR #50 scorecard either lives on a different branch/worktree, was not produced, or was lost in the stash/unstash cycle described in the task brief. Follow-up: confirm presence on `main` worktree; if missing, re-fire `agent-performance-observer` against PR #50 retroactively per RULE 2.
- **2026-05-13** — Engineering lessons file: `.claude/memory/engineering_lessons.md` — Lesson A (test-stub return-shape mismatch, origin PR #46) + Lesson B (mid-session registry refresh non-determinism, origin PR #41) are binding rules.

## Promoted from ASSUMPTIONS to FACTS (2026-05-13, this run)
- **Per-phase `threading.Lock` correctness on single-process NSSM**: VERIFIED by PR #57 merge + 204/204 test panel green. The 4 phase-scoped locks correctly serialize concurrent validator entries within the single PZService process; cross-worker safety remains an open concern tracked under Issue #53 only if/when the deployment shifts off single-process.
- **Override-flag predecessor chain semantics (P3→P2, P4→P3, P5→P4)**: VERIFIED by PR #61 merge + override-bypass audit-log entry exercised in regression suite.

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

## Engineering lessons governance (appended 2026-05-13)

- **Engineering lessons are append-only.** Supersede with new dated entries; never delete. Source: `.claude/memory/engineering_lessons.md` header + CLAUDE.md "Engineering Lessons (permanent)" section.
- **Lesson A enforcement is jointly owned**: `integration-boundary` (primary — type-contract review at coordinator/builder boundary), `testing-verification` (regression test against the REAL builder, no stub), `backend-safety-reviewer` (boundary `_normalise_X` helper presence). All three must sign off on any coordinator/consumer-to-builder wiring PR.
- **Network-bound boundary carve-out for Lesson A**: contract tests against recorded fixtures (VCR/recorded responses) substitute for real-builder regression tests on DHL / wFirma / SMTP / Cliq boundaries.

## Validator-hardening decisions (appended 2026-05-13, 3-PR sequence)

- **Per-phase lock granularity (Issue #48)** — chosen over global-lock and per-flag-lock alternatives. Rationale: the FORBIDDEN-state invariant is per-phase (P2-shadow + P2-live cannot both be true; cross-phase pairs are independent). A global lock would needlessly serialize unrelated phase admin operations; a per-flag lock would not protect the combined-state invariant. Source: PR #57 + Issue #48 close thread.
- **Override-flag predecessor model (Issue #49)** — chosen over strict-no-override and warn-only alternatives. Rationale: phased rollout drills require a controlled bypass path; strict mode would block legitimate operator drills, warn-only would erode the safety property. Override requires explicit `--override-predecessor` flag with audit-log entry. Source: PR #61 + Issue #49 close thread.
- **Cross-worker safety posture** — production NSSM verified single-process; `threading.Lock` is correct for current deployment. Multi-worker hardening (file lock, distributed lock, or actor-model serialization) tracked in Issue #53; no work scheduled until deployment topology changes. Source: PR #57 review thread + Issue #53 filing.
- **GATE 5 disclosure (PR #61)** — `security-write-action-reviewer` drifted off-scope on the predecessor-override review (focused on auth instead of write-ordering); coverage filled by the other 4 review agents (`backend-safety-reviewer`, `gap-hunter`, `system-architect`, `integration-boundary`). Logged for registry-prompt-refinement queue. Source: PR #61 final report Section 2.
- **Three-PR sequencing (Option B) over atomic single PR** — preferred for clean per-step rollback (each merge is independently revertable) + GATE 2 compliance (never exceeds 3 open implementation PRs). Each PR opened only after predecessor merged. Source: pre-campaign decision, evidenced by PR #52 → #57 → #61 ordering.

## Next 3 actions in queue

1. **Confirm scorecard visibility** — verify `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` and `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator.md` are present on `main` worktree (not just this confident-margulis worktree). If missing on main, retroactive `agent-performance-observer` re-fire required per RULE 2. Target: next session start. Gating: RULE 6 visibility integrity.
2. **W-5 P2 shadow-window monitoring** — collect ≥48h of real DHL dispatch shadow classifications (window opened 2026-05-12T23:26:44Z; eligible for promotion review no earlier than 2026-05-14T23:26:44Z). Target: ≥48h shadow corpus by 2026-05-15. Gating: P2-live promotion + downstream P3 unblock per W-5 program firing order.
3. **Coordinate with Tejal on classifier corpus labelling kickoff** — gates P4 live (≥200 shadow classifications + Tejal sign-off). Target: confirm Tejal availability for May–June window. Gating: P4 live promotion + entire P5 program timeline.

---

# ASSUMPTIONS

- **P2 shadow window will accumulate ≥48 hours of real-time DHL dispatch volume by 2026-05-14T23:26:44Z** before promotion to live. Source: master plan §4.3 + shadow-window opened on PR #46 merge. Move to FACTS by reading shadow-classification count + duration from admin runtime-flags audit log.
- **The carrier vocabulary mapping in `is_awb_stable` (SUBMITTED ∪ COMPLETE = stable) is correct for production use.** Source: P0 commit message + system-architect verdict. Move to FACTS when P2 shadow corpus produces the expected gate behaviour against real AWBs.
- **The Phase 1.3 email routing migration (`service/app/config/email_routing.py`) shipped and all 14+ consumer services use it.** Source: P0 spec prerequisite note. Move to FACTS by running `grep -rln "from ..config.email_routing import" service/app/ | wc -l` and confirming ≥14.
- **PR #50 scorecard exists somewhere** (operator task brief asserts it). Source: task brief mention of stash/unstash cycle. Move to FACTS or to OPEN QUESTIONS based on next-session worktree audit.

---

# OPEN QUESTIONS

- **Where is the PR #50 scorecard file?** Answerer: next-session worktree audit (or operator). Impact: RULE 6 visibility — if the scorecard does not exist on `main`, the PR #50 merge has no observability artifact and a retroactive `agent-performance-observer` re-fire is required per RULE 2. Candidate paths: (a) check main worktree, (b) check sibling worktrees, (c) re-fire observer.
- **Tejal availability for P4 / P5 reviewer gates** — not yet confirmed for the May-June window. Answerer: Tejal (via operator). Impact: gates P4 live promotion + P5 live promotion.
- **When does the Windows machine catch up on the merged PRs (#41, #43, #46, #47, #50, #52, #57, #61)?** Answerer: operator. Impact: production at `C:\PZ` runs ~8 PRs behind main, including the entire admin runtime-flags combined-state validator stack. Per CLAUDE.md "Production deployment rule": deploy requires the 7-agent gate. Single-process NSSM constraint is what keeps the per-phase lock correct — any change in deployment topology unblocks Issue #53.
- **Should the 4 obsolete `feat/doc-1..4` branches and the 5 newly-eligible-for-archive `chore/admin-runtime-flags-*` + `chore/adr-salvage-*` + `chore/observation-layer-*` branches be tagged-and-deleted?** Answerer: operator preference. Impact: branch hygiene; harmless if left.
- **Issue #51 ADR drift reconciliation — when is it fired?** Answerer: operator scheduling. Impact: blocks downstream ADR-drift cleanup. The 8 salvaged ADRs (subset of 10 from PR #52) need successor ADRs documenting how P0/P2 superseded them. Until reconciled, ADR README index resolves but semantic drift remains.
- **Issue #53 cross-worker safety hardening — when does it fire?** Answerer: operator (likely never unless deployment topology shifts off single-process NSSM). Impact: dormant correctness debt. If it fires, it gates any move to multi-worker uvicorn / gunicorn.
- **Issues #54/#55/#56 lock-hardening polish (write-ordering durability, audit observability, Windows file-locking)** — when do they fire? Answerer: operator scheduling. Impact: incremental hardening of the per-phase lock; none currently blocking.
- **Issues #58/#59/#60 override polish (cascade endpoint, request_id correlation, GET /audit endpoint)** — when do they fire? Answerer: operator scheduling. Impact: operator UX improvements on top of the predecessor-override mechanic; none currently blocking.
- **Cumulative ADR drift work** — blocked on Issue #51 resolution. Until #51 is reconciled, downstream ADR work (e.g. ADR-018 follow-ups in Issue #42) carries semantic risk of stacking onto unreconciled successor relationships.
- **Is the `_TOP_LEVEL_FIELDS` enforcement gap on `dhl_clearance_manifest.py` (system-architect LOW finding) acceptable to defer to P2 kickoff, or should it be addressed in a hotfix PR?** Answerer: operator. Impact: a future phase implementer could write a top-level field that bypasses the schema fence. Filed in Issue #38 as SCHEDULED for P2.

---

# PROJECT_STATE.md

Source of truth for the current project execution state. Read this file at the start of every new session before any task work begins.

Owned by `flow-context-keeper`. Do not edit by hand outside of an emergency. Last updated by the agent on initialisation, 2026-05-13.

**Last-run-at:** 2026-05-13T16:00:00Z (RULE 2 + RULE 3 auto-fire: Lesson D closure — reconcile 4c797e4 + lead coordinator backstop. PR #77 merged (SHA `1ee83e52`). Reconciliation: CLOSED. All 5 Lesson D rules enforced. Prior run: 2026-05-13T14:30:00Z (Lesson D governance codification PR #76). Naive orchestrators should check this timestamp before re-firing `flow-context-keeper` within the same chat turn.

---

# FACTS

## Current origin/main HEAD
- **2026-05-18** — `150b2c9` chore: fix skill discovery — move Wave 1A skills to .claude/commands/ (PR #215 merge)
  - Prior: `e294160` chore: skill-system Wave 1A — pz-shipment, cowork-integration, engineering-lessons (PR #214 merge)
  - Prior: `67a1af8` fix(p1): SyntheticEvent onChange repair + learning_traces flag writer (PR #213 merge)
  - Prior: `1ee83e52` Merge PR #77: chore(reconcile): backfill 4c797e4 and add Lesson D lead coordinator backstop

## Windows production local HEAD (NOT on origin/main)
- **2026-05-13** — `4c797e4` fix(email): prevent outbound customs emails sending without attachments ← **DEPLOYED TO PRODUCTION 2026-05-13T10:43Z**
  - Local hotfix chain (not pushed to GitHub, Windows-staging only):
    - `4c797e4` Attachment integrity guard (this deploy)
    - `1b38ea0` Polish PDF font fix (DejaVuSans.ttf)
    - `80e3469` DHL email search fix (AWB 1196338404)
    - `4d595ca` SMTP immediate-send after queue_email()
    - Base: `69309a5` Merge PR #66 (forgot-password)
  - **Reconciliation required** before next standard 7-agent-gate deploy from origin/main.

## Wave 1 closure facts (appended 2026-05-13T12:30Z)

- **Wave 1 deploy COMPLETE** — SHA `4c797e4` on Windows production as of 2026-05-13T10:43Z. Status: WAVE-1-COMPLETE-WAVE-2-AWAITING-FIRST-DISPATCH.
- **PZ regression on Windows: 160/160 PASS** — confirmed pre-deploy 2026-05-13.
- **Carrier suite on Windows: 366/366 PASS** — confirmed pre-deploy 2026-05-13.
- **Public health endpoint via Cloudflare: 200 OK** — `https://pz.estrellajewels.eu/api/v1/health` confirmed post-deploy.
- **Forgot-password SMTP path: VERIFIED** — email queued to Tejal `tejal@estrellajewels.com`, status=`sent` at 2026-05-13T11:54:13Z, 6-digit code present, `_debug_code` absent from response. PR #67 SMTP send verified functional against real provider (Zoho Mail).
- **Font fix `1b38ea0` Polish diacritics: VERIFIED** — `Ó ó ć ł ś ż` extracted from `POLISH_DESC_6049349806_20260507.pdf`; DejaVuSans.ttf 757,076 bytes confirmed on disk.
- **Attachment integrity guard: LIVE** on production as of SHA `4c797e4`. 0 `FAILED_ATTACHMENT_VALIDATION` queue entries since restart (expected — no outbound customs flow yet).
- **Wave 1 closure scorecard committed:** `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md`
- **Self-evaluation scorecard committed:** `.claude/memory/scorecards/self-eval-2026-05-13.md` (5th-run trigger; self-score 23/30 ACCEPTABLE, no degradation)
- **PR #74 merged — SHA `5ee390b`** — `fix(timeline): add EV_PACKING_LIST_EXTRACTED + EV_PACKING_MATCHED_TO_INVOICE constants`. Resolves active `AttributeError` on `POST /api/v1/packing/{batch_id}/upload` (2 confirmed hits in production stderr). Tests 62/62 pass. Synced to `C:\PZ\app\core\timeline.py` via robocopy. **Service restart pending (operator elevated shell required).**
- **SHA lineage verified (STEP 4):** `git log 0b4e381..4c797e4` → 1 commit (`4c797e4` only). `git merge-base 0b4e381 4c797e4` → `1b38ea0`. Conclusion: `4d595ca`, `80e3469`, `1b38ea0` are already on origin/main (reachable from `0b4e381`). Only `4c797e4` is unique to Windows local chain. PROJECT_STATE.md "4 local hotfix commits" description was partially incorrect — 3 of 4 were already on origin/main. **Governance note:** `4c797e4` was deployed without a GitHub PR (local-commit-only deploy). 7-agent gate was run inline; CLAUDE.md gate spirit was observed. See Lesson D candidate in Scorecard § 4.

## Merged PRs (this session window, latest first)
- **#215** 2026-05-18T18:09Z — chore: fix skill discovery — move Wave 1A skills to .claude/commands/ — merge SHA `150b2c9` — rename-only, zero content changes, zero blast radius. Corrects `.claude/skills/` → `.claude/commands/` after runtime discovery.
- **#214** 2026-05-18T18:01Z — chore: skill-system Wave 1A — pz-shipment, cowork-integration, engineering-lessons — merge SHA `e294160` — governance/tooling only. Creates `.claude/commands/` retrieval modules. No CLAUDE.md changes. No production code.
- **#213** 2026-05-18T17:58Z — fix(p1): SyntheticEvent onChange repair + learning_traces flag writer — merge SHA `67a1af8` — P1 production defect batch. 6 Inp/Sel onChange sites fixed. learn_from_parse both return paths emit `flag`. 19 regression tests (test_p1_defect_batch.py).
- **#77** 2026-05-13T16:00Z — chore(reconcile): backfill 4c797e4 and add Lesson D lead coordinator backstop — merge SHA `1ee83e52` — governance-only, no production code changes. Closes 4c797e4 reconciliation. Adds lead coordinator LOCAL-COMMIT-ONLY backstop.
- **#76** 2026-05-13T14:30Z — chore(governance): codify Lesson D — LOCAL-COMMIT-ONLY deploys require disclosure + reconciliation — merge SHA `ba84ee3` — governance-only, no production code changes
- **#74** 2026-05-13T12:26Z — fix(timeline): add EV_PACKING_LIST_EXTRACTED + EV_PACKING_MATCHED_TO_INVOICE constants — merge SHA `5ee390b` — HOTFIX for active broken packing upload endpoint
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
- ~~**EV_PACKING_LIST_EXTRACTED**~~ — **RESOLVED 2026-05-13T12:26Z** by PR #74 (SHA `5ee390b`). Both `EV_PACKING_LIST_EXTRACTED` and `EV_PACKING_MATCHED_TO_INVOICE` added to `timeline.py`. Synced to production; **service restart pending** to pick up. GitHub issue #75 filed (audit trail only — RESOLVED status noted in issue body).
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

## Deploy smoke results 2026-05-13 (SHA 4c797e4)

| Check | Result | Detail |
|---|---|---|
| PZService state | PASS | STATE 4 RUNNING, process 8756 |
| Local health | PASS | 200 OK `{"status":"ok","engine":"ok","environment":"prod"}` |
| Public health | PASS | 200 OK `https://pz.estrellajewels.eu/api/v1/health` |
| Carrier gate | PASS | `pending` (unchanged — no live flags touched) |
| PZ regression | PASS | 160/160 |
| Carrier suite | PASS | 366/366 |
| Attachment integrity tests | PASS | 12/12 |
| `FAILED_ATTACHMENT_VALIDATION` queue entries | PASS | 0 — guard live, no false fires |
| Outbound customs emails since restart | PASS | 0 — none sent |
| Forgot-password smoke (tejal@estrellajewels.com) | PASS | 200 OK, `_debug_code` absent from HTTP response AND queue body, 6-digit code in body, status=`sent` at 2026-05-13T11:54:13Z |
| PDF Polish diacritics | PASS | `Ó ó ć ł ś ż` extracted from `POLISH_DESC_6049349806_20260507.pdf`; DejaVuSans.ttf 757,076 bytes confirmed on disk |
| Pre-existing log anomaly | KNOWN | `AttributeError: module 'app.core.timeline' has no attribute 'EV_PACKING_LIST_EXTRACTED'` in `routes_packing.py:392` — NOT introduced by this deploy; tracked as follow-up |

## Shadow windows currently active
- **W-5 P2 proactive customs dispatch** — shadow window opened on PR #46 merge (2026-05-12T23:26:44Z). Combined-state validator (ADR-018) now enforced per PR #50/#57/#61. Expected end: ≥48h of real DHL dispatch volume per master plan §4.3 → eligible for live promotion no earlier than 2026-05-14T23:26:44Z, gated on shadow-classification corpus + Tejal sign-off.
- **Attachment integrity guard shadow observation** — guard is LIVE on Windows prod as of `4c797e4`. Status: `AWAITING-FIRST-REAL-AWB`. Shadow-observing-real-traffic flag must NOT be set until `active_shipment_monitor` fires its first real sweep and an AWB enters eligibility filter. No customs emails queued since restart. Operator must confirm first AWB timestamp to upgrade status.

## Deployment status per machine
- **Mac (dev)** — current origin/main head `76bf526`; admin runtime-flags combined-state validator (ADR-018) + per-phase lock + predecessor-live override + P2 ignition switch (PR #72) + observation RULE 6 visibility (PR #73) now on main.
- **Windows (prod, NSSM `PZService` at `C:\PZ`, `https://pz.estrellajewels.eu`)** — **WAVE-1-COMPLETE-WAVE-2-AWAITING-FIRST-DISPATCH**
  - Wave 1 deploy SHA: `4c797e4` (local Windows-staging chain; not on origin/main — see "Windows production local HEAD")
  - Wave 1 hotfix SHA: `5ee390b` (PR #74, on origin/main) — `timeline.py` synced to `C:\PZ\app\core\timeline.py` via robocopy 2026-05-13T12:23Z. Restart completed 2026-05-13T10:34Z (operator elevated shell).
  - PZService: RUNNING (STATE 2→RUNNING, PID 14164) — PR #74 fully live
  - Local health: 200 OK `{"status":"ok","engine":"ok","environment":"prod","detail":{"engine_dir":"C:\\PZ\\engine"}}`
  - Public health: 200 OK `https://pz.estrellajewels.eu/api/v1/health`
  - Carrier gate: `{"carrier_api_status":"pending","carrier_plt_status":"pending"}`
  - Smoke tests: ALL PASS (see § "Deploy smoke results 2026-05-13")
  - Shadow status: `SHADOW-OBSERVING-REAL-TRAFFIC` — all infrastructure verified end-to-end, PZService healthy on PID 14164, awaiting first real outbound customs email through attachment integrity guard
  - Drift note: `4c797e4` is the only Windows-local commit (SHA lineage verified). Windows prod is behind origin/main by PRs #67–#73 + #74. Full 7-agent gate + `4c797e4` reconciliation PR required before next origin-pull deploy.

## Registry
- **2026-05-13** — Project registry healthy with 15 project agents at `.claude/agents/` (includes `gap-hunter`, `adr-historian`, `agent-performance-observer`, `flow-context-keeper`). Global registry at `~/.claude/agents/` has 54 agents. Total reachable agents in session: 79 (incl. plugin + built-in). No naming collisions.
- **2026-05-18** — Project retrieval modules added to `.claude/commands/` (Wave 1A, PRs #214+#215):
  - `pz-shipment` — PZ shipment workflow, financial rules, verification semantics, Cliq posting formats, WorkDrive flow
  - `cowork-integration` — Cowork→PZ→SMTP architecture, result processor, action runner, email drafting rules
  - `engineering-lessons` — Lessons A–D (test stubs, agent registry refresh, scorecard writes, LOCAL-COMMIT-ONLY deploys)
  - All 3 confirmed invocable via `Skill()` tool in session post-commit. Runtime discovery: `.claude/skills/` is inert; `.claude/commands/` is the active project retrieval surface.

## RULE 6 visibility entries (scorecards on disk + expected)
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-p0-adr018-p2-deployment-campaign.md` — observer: `agent-performance-observer` post PR #41 registry-refresh validation — 14 verdicts scored, all EXEMPLARY, zero NEEDS-TUNING / UNRELIABLE.
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` — observer: `agent-performance-observer` covering the PR #52 / #57 / #61 sequence. Confirmed on disk in worktree.
- **2026-05-13** — Scorecard recorded (RETROACTIVE): `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md` — observer: `agent-performance-observer` covering PR #50 (5 agent verdicts). Filename suffix `-RETROACTIVE` distinguishes from contemporaneously-produced scorecards; header note explains origin. **Resolution status: RESOLVED — retroactively produced.** Original auto-fire after PR #50 merge claimed file write but file never reached disk; root cause unclear (see OPEN QUESTIONS). Produced in parallel with this PROJECT_STATE update; future readers can confirm presence on disk.
- **2026-05-13** — Scorecard recorded (this audit-closure run): `.claude/memory/scorecards/2026-05-13-observation-audit-closure.md` — observer: `agent-performance-observer` auto-fire for the observation-layer audit closure task itself (3 agent verdicts). Produced in parallel with this PROJECT_STATE update.
- **2026-05-13** — **Total scorecards on main post-this-PR: 4** — (1) W-5 P0+ADR-018+P2 deployment-campaign (contemporaneous), (2) W-5 validator-hardening 3-PR sequence (contemporaneous), (3) PR #50 admin runtime-flags validator (RETROACTIVE), (4) observation-audit-closure (this run). All four cited above with absolute repo-relative paths per RULE 6.
- **2026-05-13T12:30Z (Wave 1 closure)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md` — observer: agent-performance-observer (RULE 2 auto-fire). 7 inline deploy agents scored; 1 EXEMPLARY (lead_coordinator, git_diff_reviewer), 5 ACCEPTABLE. 2 calibration gaps identified (QA missing log scan, release_manager missing local-commit-only check). **Total scorecards on disk: 6** (4 prior + wave1-deploy-closure + self-eval-2026-05-13).
- **2026-05-13T12:30Z (Wave 1 closure)** — Self-evaluation written: `.claude/memory/scorecards/self-eval-2026-05-13.md` — 5th-run calendar trigger. Self-score 23/30 ACCEPTABLE. No SELF-DEGRADATION DETECTED.
- **2026-05-13T14:30Z (Lesson D codification)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-lesson-d-governance-codification.md` — RULE 2 auto-fire for PR #76 governance session. 3 agents scored (1 EXEMPLARY, 2 ACCEPTABLE). Enforcement gap finding: `deploy_lead_coordinator.md` has no LOCAL-COMMIT-ONLY backstop (fixed by PR #77).
- **2026-05-13T16:00Z (Lesson D closure)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-lesson-d-closure.md` — RULE 2 auto-fire for PR #77. 3 agents scored (system-architect, final-consistency-review, deploy_release_manager). All issues resolved pre-commit. **Total scorecards on disk: 8**.
- **2026-05-13** — Engineering lessons file: `.claude/memory/engineering_lessons.md` — Lesson A (test-stub return-shape mismatch), Lesson B (mid-session registry refresh non-determinism), Lesson C (orchestrator scorecard verification), **Lesson D (LOCAL-COMMIT-ONLY deploy disclosure + reconciliation — CODIFIED 2026-05-13 via PR #76)** are all binding rules.

## Observation-layer audit closure (appended 2026-05-13T08:30Z)
- **Validator hardening cycle: COMPLETE.** Closure now also includes the retroactively-produced PR #50 scorecard, satisfying RULE 6 visibility. The 3-PR validator-hardening sequence (#52 → #57 → #61) plus the originating PR #50 all have observability artifacts on disk.
- **P2 ignition switch: REMAINS NEXT MAJOR DESIGN DECISION** (not yet wired; will be next session opening). The combined-state validator + per-phase lock + predecessor-override stack is in place; the actual operator-facing "flip from shadow to live" toggle is the remaining design surface.
- **No production deployment yet.** Windows machine still ~8 PRs behind main; deferred until next deploy window per CLAUDE.md "Production deployment rule" (7-agent gate required).

## Promoted from ASSUMPTIONS to FACTS (Wave 1 closure, 2026-05-13T12:30Z)

- **"Cloudflare tunnel routes correctly to PZService"** → CONFIRMED. Public health `https://pz.estrellajewels.eu/api/v1/health` returned 200 OK post-deploy. Tunnel is healthy; no routing anomaly.
- **"PR #67 SMTP works against real provider"** → CONFIRMED. Forgot-password email queued and delivered to `tejal@estrellajewels.com` via Zoho Mail SMTP. `_debug_code` absent from response (production code path). status=`sent`.
- **"Polish PDF generation renders diacritics in production"** → CONFIRMED. `Ó ó ć ł ś ż` extracted from production PDF. DejaVuSans.ttf 757,076 bytes confirmed on disk. Font fix `1b38ea0` is live.
- **"Windows fast-forward from 0b4e381 succeeds"** → CONFIRMED (via SHA lineage). `4d595ca`, `80e3469`, `1b38ea0` are all reachable from `0b4e381` (on origin/main). Only `4c797e4` was the unique Windows-local commit.

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

## Observation-layer governance (appended 2026-05-13T08:30Z, audit-closure run)

- **Retroactive scorecards are valid governance artefacts** when a contemporaneous auto-fire failed silently. Filename suffix `-RETROACTIVE` distinguishes them from contemporaneously-produced scorecards; a header note in each retroactive scorecard explains origin (which PR + when the original fire was expected vs when the retroactive fire occurred). This decision binds future audit-closure work: silent observer failures must be remediated by retroactive production, not waved away. Source: this audit-closure run + PR #50 anomaly resolution.
- **PR #50 scorecard root cause: NOT a DECISION (recorded as OPEN QUESTION instead).** The failure mechanism is not fully diagnosable from current state — three hypotheses remain (silent tool-call failure, ephemeral path mis-routing, or branch-switch clobber). Recording as OPEN QUESTION rather than DECISION preserves accuracy: we have not yet chosen a corrective rule, only acknowledged the gap. Source: this audit-closure task brief.

## Wave 1 closure decisions (appended 2026-05-13T12:30Z)

- **P2 live promotion eligibility clock** — starts from `first_real_dispatch_timestamp` (when first real AWB hits sweep eligibility filter), NOT from PZService restart time. Combined conditions: 48h elapsed since first dispatch AND ≥50 real dispatches AND ≥10 distinct AWBs AND Tejal spot-check sign-off.
- **Wave 1 deploy strategy validated** — production synchronization deploy with 7-agent gate + 3 mandatory smokes (forgot-password SMTP, Polish PDF diacritics, attachment integrity) + rollback-ready is the canonical pattern for future Windows catch-up deploys.
- **Wave 2 (shadow observation) is operationally-paced, not engineering-paced** — engineering work pauses until evidence accumulates from real Path A traffic. No engineering sprint should open during Wave 2 waiting period.
- **Shadow status semantics (canonical definitions):**
  - `SHADOW-READY-WITH-IGNITION`: code exists on main, infrastructure ready, NOT YET deployed to production
  - `SHADOW-OBSERVING-REAL-TRAFFIC`: production deploy verified + infrastructure verified end-to-end, awaiting first real operational event
  - `SHADOW-OBSERVED-WITH-EVIDENCE`: first real dispatch observed + audit log entries accumulating + Wave 2 clock running
  - `SHADOW-READY-FOR-LIVE-EVALUATION`: 48h + 50 dispatches + 10 AWBs + Tejal sign-off all achieved
- **Current attachment guard shadow status: `SHADOW-OBSERVING-REAL-TRAFFIC`** — production deploy of SHA `4c797e4` verified, infrastructure end-to-end verified, awaiting first real outbound customs email attempt.
- ~~**Lesson D candidate**~~ → **CODIFIED 2026-05-13 via PR #76** (`ba84ee3`): any commit deployed to production that does not exist on `origin/main` via a PR requires a LOCAL-COMMIT-ONLY disclosure header + operator acknowledgment + reconciliation PR before next `git pull --ff-only`. 5 binding rules + JSONL audit trail. Governance reference: `docs/governance/lesson-d-local-commit-only-deploys.md`. Audit record: `.claude/memory/local-commit-deploys.jsonl`.
- **Inline 7-agent gate disclosure requirement** — when all 7 deploy agents are run inline (no spawned Tool calls), the gate output MUST include a disclosure header stating: "Gate mode: inline execution — agents not spawned; project-local agent files at `.claude/agents/deploy_*.md` used directly." Source: Wave 1 closure scorecard § 1 (Substitution column).

## Four-layer governance architecture (locked 2026-05-18, Wave 1A closure)

**This model replaces any prior informal "CLAUDE.md = everything" assumption.**

| Layer | Path | Always loaded | Role |
|-------|------|--------------|------|
| L0 | `CLAUDE.md` | Yes | Governance kernel: invariants, sequencing semantics, gate imperatives, observer triggers |
| L1 | `.claude/commands/*.md` | On-demand | Project retrieval modules: procedures, workflows, engineering lessons |
| L2 | `.claude/agents/*.md` | Dispatched | Specialist executors: review roles, deploy gating, observation analysis |
| L3 | gates + observers | Always-active | Enforcement runtime: scorecards, PR discipline, behavioral verification |

**Directional rule (permanent):** L0 → L1 migration is permitted only for explanatory cognition. Enforcement cognition never leaves L0. L3 verifies the boundary holds.

**Runtime discovery (validated 2026-05-18):**
- `.claude/skills/` — inert in this Claude Code runtime; NOT scanned by skill loader
- `.claude/commands/` — active project retrieval surface; indexed and invocable via `Skill()` tool
- `.claude/skills/` + `.claude/commands/` are conceptually converging in Claude Code docs but `.claude/commands/` is the verified working path

## Wave 2 kernel-patch rules (locked 2026-05-18)

Wave 2 = CLAUDE.md condensation backed by `.claude/commands/` retrieval. Not "skill migration." Not "prompt cleanup." These are kernel patch rules:

1. Only sections already extracted to `.claude/commands/` are candidates for condensation
2. Section headers survive unchanged
3. Gate triggers (Gates 1–6 imperatives) survive unchanged
4. Observation auto-fire semantics (Rules 2–3) remain always-loaded — cannot move to on-demand retrieval
5. Every removed sentence has an equivalent reachable via `Skill()` in `.claude/commands/`
6. **Never condense execution-ordering semantics.** The invariant triple (trigger condition + actor + ordering) must survive verbatim. Removing explanation is safe. Weakening sequencing is not.

**Wave 2 allowed / forbidden:**

| Allowed | Forbidden |
|---------|-----------|
| Remove explanation | Remove imperative |
| Remove examples | Remove ordering |
| Shorten prose | Weaken trigger |
| Replace detail with command reference | Replace governance with suggestion |
| Condense repeated rationale | Condense enforcement semantics |

**Wave 2 execution protocol:**
1. Operator names the section to condense
2. Extract invariant triples from that section before touching anything
3. Write condensed version
4. Diff the invariant triples — if any changed, stop and report
5. PR for that section only
6. Merge and observe one session before touching the next section

**Current boundary:** Wave 1A complete. Wave 2 not started. First Wave 2 target must be named explicitly by operator.

## Next 3 actions in queue

1. ~~**Restart PZService for PR #74**~~ — **DONE 2026-05-13T10:34Z**. PID 14164, health 200 OK. EV_PACKING constants live.
2. ~~**Codify Lesson D governance**~~ — **DONE 2026-05-13T14:30Z**. PR #76 merged (SHA `ba84ee3`). 5 rules codified across 4 files. Audit record (local-commit-deploys.jsonl) created. Scorecard on disk.
3. **Observe first real AWB through attachment integrity guard** — shadow status `SHADOW-OBSERVING-REAL-TRAFFIC`. Any `FAILED_ATTACHMENT_VALIDATION` entry = guard working. First successfully-queued customs email = behavioral verification complete.

## Completed actions (previously "next")

- ~~**Reconcile `4c797e4` with origin/main**~~ — **DONE 2026-05-13T16:00Z** via PR #77 (SHA `1ee83e52`). `4c797e4` confirmed as ancestor of origin/main (swept in via PR #76 branch). JSONL updated: `PENDING_RETROACTIVE` → reconciliation-close record appended. `local-commit-deploys.jsonl` + `lesson-d-local-commit-only-deploys.md` both updated. Lead coordinator backstop added.

---

# ASSUMPTIONS

- **P2 shadow window will accumulate ≥48 hours of real-time DHL dispatch volume by 2026-05-14T23:26:44Z** before promotion to live. Source: master plan §4.3 + shadow-window opened on PR #46 merge. Move to FACTS by reading shadow-classification count + duration from admin runtime-flags audit log.
- **The carrier vocabulary mapping in `is_awb_stable` (SUBMITTED ∪ COMPLETE = stable) is correct for production use.** Source: P0 commit message + system-architect verdict. Move to FACTS when P2 shadow corpus produces the expected gate behaviour against real AWBs.
- **The Phase 1.3 email routing migration (`service/app/config/email_routing.py`) shipped and all 14+ consumer services use it.** Source: P0 spec prerequisite note. Move to FACTS by running `grep -rln "from ..config.email_routing import" service/app/ | wc -l` and confirming ≥14.
- ~~**PR #50 scorecard exists somewhere** (operator task brief asserts it). Source: task brief mention of stash/unstash cycle. Move to FACTS or to OPEN QUESTIONS based on next-session worktree audit.~~ — **RESOLVED 2026-05-13T08:30Z**: confirmed never existed pre-audit; produced retroactively. Promoted to FACTS as `2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`. See FACTS § "RULE 6 visibility entries".

---

# OPEN QUESTIONS

## Wave 2 open questions (added 2026-05-13T12:30Z)

- **When will first real Path A AWB hit sweep eligibility?** (operationally determined, not engineering controllable) — this is the trigger for `SHADOW-OBSERVED-WITH-EVIDENCE` status and Wave 2 clock start. Answerer: operator (first confirmed DHL customs email attempt via automated sweep).
- **Will attachment integrity guard fire correctly on first real outbound customs email attempt?** (structural verification complete; behavioral verification pending real flow) — expected: `attachments=` populated correctly from audit; guard passes; email queued and sent. Any `FAILED_ATTACHMENT_VALIDATION` entry would be the guard working as designed. Answerer: `active_shipment_monitor` sweep logs.
- ~~**When will PZService be restarted to pick up PR #74?**~~ — **RESOLVED 2026-05-13T10:34Z** by operator. PID 14164, health 200 OK. Packing constants live.
- ~~**Lesson D governance decision**~~ — **RESOLVED 2026-05-13T14:30Z** by PR #76. `deploy_release_manager.md` already had item 5 from prior spawn task. Full Lesson D codification (5 rules, audit record, governance doc) complete. See merged PR #76 (SHA `ba84ee3`). Lead coordinator backstop added by PR #77 (SHA `1ee83e52`). All 5 Lesson D rules now fully enforced by 2 agents. 4c797e4 reconciliation CLOSED.

- ~~**Where is the PR #50 scorecard file?**~~ — **RESOLVED 2026-05-13T08:30Z**: file did not exist pre-audit; original auto-fire after PR #50 merge claimed file write but file never reached disk. Cross-reference: `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md` (retroactively produced in this audit-closure cycle).
- **Root cause of original PR #50 auto-fire failure?** Answerer: future investigation if reproducible (currently not). Impact: silent observer-write failures could recur and undermine RULE 6 visibility. Hypotheses: (a) the observer agent's tool call to Write the scorecard silently failed without raising an error to the orchestrator, (b) the write was routed to an ephemeral path not under the worktree, or (c) the file was clobbered during a subsequent `git checkout` / branch-switch before being staged. Definitive diagnosis would require replay of the agent runtime, which is not available.
- **Should orchestrator-side verification be mandated after every observer scorecard write?** Answerer: operator (decision pending). Impact: would prevent recurrence of the PR #50 silent-failure pattern. Proposed mechanism: after every observer auto-fire, the orchestrator runs `ls .claude/memory/scorecards/<expected-filename>` to confirm the file landed, and re-fires or escalates if missing. See engineering_lessons.md candidate Lesson C addition (under discussion in this PR). Cross-reference: DECISIONS § "Next 3 actions in queue" item 3.
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

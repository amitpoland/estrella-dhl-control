# PROJECT_STATE.md

Source of truth for the current project execution state. Read this file at the start of every new session before any task work begins.

Owned by `flow-context-keeper`. Do not edit by hand outside of an emergency. Last updated by the agent on initialisation, 2026-05-13.

**Last-run-at:** 2026-05-13T01:55:00Z (RULE 6 visibility refresh by `flow-context-keeper` second run — appended scorecard + engineering_lessons.md + CLAUDE.md addition + registry-resolution FACTS; appended engineering-lessons governance DECISIONS; promoted 2 registry ASSUMPTIONS to FACTS). Naive orchestrators should check this timestamp before re-firing `flow-context-keeper` within the same chat turn.

---

# FACTS

## Current origin/main HEAD
- **2026-05-13** — `2ac9a02` Merge pull request #37 from amitpoland/fix/proforma-module-purity

## Merged PRs (this session window, latest first)
- **#37** 2026-05-12 — fix(proforma): move PZ recovery helper out of pure-builder module
- **#35** 2026-05-12 — chore(governance): add 6 MANDATORY GOVERNANCE GATES + restore gap-hunter/adr-historian agents
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

## Open PRs
- **#33** chore(w5-p0): DHL self-clearance foundation scaffolding — **BLOCKED at Phase 4** by adr-historian HIGH finding on ADR-010 (`*_shadow_mode` default-True violates "default=False without exception"). Operator must choose Option A (flip defaults), Option B (author ADR-018), or Option C (reject finding). Comment thread laid out.
- **#10** feat(inventory): Risk-3/4 button stubs — deferred per operator instruction; do not touch.
- **#8** docs(inventory): Doc 4 — failure modes — superseded by PR #34 merge (closeable / archiveable).
- **#7** docs(inventory): Doc 3 — data source mapping — superseded by PR #34.
- **#6** docs(inventory): Doc 2 — button registry — superseded by PR #34.
- **#5** docs(inventory): Doc 1 v2 — allocation ledger — superseded by PR #34.
- **#4** docs(inventory): Phase 1 inspector report.
- **#1** ui: align sidebar IA with Estrella Atlas design — historical Atlas branch (REFERENCE_ONLY pending).

## Closed issues (this session window)
- **#27** 2026-05-12 — Refresh inventory design docs 1-4 (closed by PR #34 merge)

## Open issues
- **#38** P2-P5 phase preconditions: 5 gap-hunter findings on PR #33 — SCHEDULED per phase. Filed under GATE 4 disposition.
- **#36** Governance gates refinement — wording + coverage amendments from agent review of PR #35. Filed under GATE 4 disposition.
- **#30** Refresh inventory design docs 1-4 against current main before next inventory feature (predates #27 — likely closeable).
- **#29** Sanitize INVALID_EVIDENCE detail before surfacing API errors.
- **#28** Test depth — single-field evidence-gate negatives + return replay coverage.
- **#26** INVALID_EVIDENCE detail sanitization — template-format raw exception strings.
- **#25** Test depth — single-field evidence-gate negatives + replay test for return-from-producer.

## Active branches (per GATE 3 status designation)

| Branch | Status | Note |
|---|---|---|
| `chore/dhl-selfclearance-p0-foundation` | ACTIVE | PR #33 head, BLOCKED on ADR-010 |
| `chore/meta-agent-observation-layer` | ACTIVE | this PR — meta-agent foundation |
| `feature/dhl-label-workflow-planning` | REFERENCE_ONLY | salvage-audit verdict 2026-05-13: FULL ABANDON; archive tag pending |
| `feat/inventory-risk34-stubs` | ACTIVE (deferred) | Risk-3/4 stubs — operator instruction: do not touch |
| `feat/doc-1-v2-allocation-ledger` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-2-button-registry` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-3-data-source-mapping` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-4-failure-modes` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `claude/zealous-johnson-6d6d34` | ACTIVE | UI sidebar IA — PR #1 |
| `archive/may9-stale-main` | ARCHIVED | pre-existing archive |

## Archive tags
- `archive/may9-stale-main` (pre-existing; predates this session)
- *(none yet for `feature/dhl-label-workflow-planning` — pending Phase 6 of master campaign)*

## Shadow windows currently active
- None.

## Deployment status per machine
- **Mac (dev)** — current head `2ac9a02` ; admin runtime-flags endpoint NOT yet on main (lives only on PR #33). Self-clearance flags will land when PR #33 merges.
- **Windows (prod, NSSM `PZService` at `C:\PZ`, `https://pz.estrellajewels.eu`)** — NOT updated this session. Last verified deploy SHA unknown from this Mac session. Verify on next Windows-side contact.

## Registry
- **2026-05-13** — Project registry healthy with 13 project agents at `.claude/agents/` (including `gap-hunter` + `adr-historian` salvaged via PR #35). Global registry at `~/.claude/agents/` has 54 agents. Total reachable agents in session: 77 (incl. plugin + built-in). No naming collisions.
- After this PR: project registry will be 15 agents (adds `agent-performance-observer` and `flow-context-keeper`).

## RULE 6 visibility entries (appended 2026-05-13 by flow-context-keeper second run)
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-p0-adr018-p2-deployment-campaign.md` — observer: `agent-performance-observer` post PR #41 registry-refresh validation — 14 verdicts scored, all EXEMPLARY, zero NEEDS-TUNING / UNRELIABLE.
- **2026-05-13** — Engineering lessons file created: `.claude/memory/engineering_lessons.md` — Lesson A (test-stub return-shape mismatch, origin PR #46) + Lesson B (mid-session registry refresh non-determinism, origin PR #41) are now binding rules.
- **2026-05-13** — `CLAUDE.md` updated: new section "Engineering Lessons (permanent)" inserted between MANDATORY OBSERVATION LAYER (line 135) and Available integration (line 323) — section occupies lines 233-322 (90 lines). Adds binding-rule summaries of Lesson A + B with enforcement surfaces (GATE 1 for Lesson A, GATE 5 for Lesson B, GATE 4 for post-merge Lesson A failures). Branch: `chore/observation-layer-verification-and-lessons` (pre-merge at time of this entry).
- **2026-05-13** — Mid-session registry-refresh issue from PR #41 RESOLVED in this session: both `agent-performance-observer` and `flow-context-keeper` dispatched cleanly via `subagent_type` registry (this very entry is evidence of `flow-context-keeper` dispatch). Closes the prior VALIDATION-FAILED signal recorded under Lesson B.

---

# DECISIONS

## Bound operator decisions

- **GATE 2 limit** — max 3 simultaneous open implementation PRs (+1 docs/governance exception). Source: PR #35 / CLAUDE.md MANDATORY GOVERNANCE GATES.
- **Windows Atlas is primary operator UI surface.** Mac dashboard is read-only for operators going forward. Source: memory `windows_atlas_ui_primary_2026-05-12`.
- **`feature/dhl-label-workflow-planning` = REFERENCE_ONLY** pending archive tag. Salvage audit 2026-05-13 verdict: FULL ABANDON as merge unit. Pre-archive: 10 ADR files eligible for selective port via separate focused PR. Source: salvage audit final report.
- **Tejal is primary P5 reviewer; Amit is backup.** Tejal labels classifier corpus; Amit spot-checks 10-15%. Source: memory `dhl_selfclearance_program_2026-05-12`.
- **`dhl_followup_sla.py` reconciliation = v2-alongside-legacy (P0 Decision 2)** — coordinator routes by `clearance_path`; legacy stays untouched until operational evidence justifies deprecation. Source: P0 spec `01_P0_FOUNDATION.md`.
- **W-5 program firing order: P0 → P2 → P3 → P4 → P5.** P3 + P4 cannot share a session (different code paths, different shadow windows). P5 design may overlap P4 shadow; P5 shadow cannot begin until P4 is live. Source: master plan `00_MASTER_PLAN.md`.
- **Classifier is the single point of catastrophic failure** for P4/P5. Required: ≥200 shadow classifications + Customs Compliance Reviewer sign-off before P4 live; 100% SAD/PZC precision + Inventory/Finance Reviewer sign-off before P5 live. Source: master plan §4.5 R2.
- **Engineering discipline rules (locked 2026-05-12)** — doc-vs-code consistency gate (Issue #27 pattern), API error templating (`{detail, error_code, field, hint}`), exception-leak prevention. Source: memory `engineering_discipline_rules`.
- **agent-prompt-refiner and pattern-historian deferred** pending two campaigns under observation-layer baseline. Source: this PR + Issue (filed in this PR).

## Engineering lessons governance (appended 2026-05-13)

- **Engineering lessons are append-only.** Supersede with new dated entries; never delete. Source: `.claude/memory/engineering_lessons.md` header + CLAUDE.md "Engineering Lessons (permanent)" section.
- **Lesson A enforcement is jointly owned**: `integration-boundary` (primary — type-contract review at coordinator/builder boundary), `testing-verification` (regression test against the REAL builder, no stub), `backend-safety-reviewer` (boundary `_normalise_X` helper presence). All three must sign off on any coordinator/consumer-to-builder wiring PR.
- **Network-bound boundary carve-out for Lesson A**: contract tests against recorded fixtures (VCR/recorded responses) substitute for real-builder regression tests on DHL / wFirma / SMTP / Cliq boundaries. Real-builder test is impractical there because the "real builder" makes a live network call; recorded-fixture contract tests still assert the type contract without flakiness.

## Next 3 actions in queue

1. **Operator decides ADR-010 vs P0 spec conflict** (Options A/B/C in PR #33 comment thread). Until decided, PR #33 cannot merge and Phases 5-8 of master campaign remain blocked.
2. **After PR #33 merges**: fire Phase 5 (file ADR salvage issue) → Phase 6 (archive `feature/dhl-label-workflow-planning` with `git tag archive/feature-dhl-label-workflow-planning-2026-05-13`) → Phase 7 (W-5 P2 implementation per `02_P2_PROACTIVE_DISPATCH.md`) → Phase 8 (shadow window launch + admin runtime-flags round-trip).
3. **Coordinate with Tejal** on corpus labelling kickoff for classifier training (gates P4 live).

---

# ASSUMPTIONS

- **P2 shadow window is expected to run 48 hours of real-time DHL dispatch volume before promotion to live.** Source: master plan §4.3 shadow-window table. Move to FACTS when shadow window opens (then it becomes a measurable interval).
- **The carrier vocabulary mapping in `is_awb_stable` (SUBMITTED ∪ COMPLETE = stable) is correct for production use.** Source: P0 commit message + system-architect verdict. Move to FACTS when P2 wires `is_awb_stable` against real AWBs and the predicate produces the expected gate behaviour.
- **The Phase 1.3 email routing migration (`service/app/config/email_routing.py`) shipped and all 14+ consumer services use it.** Source: P0 spec prerequisite note. Move to FACTS by running `grep -rln "from ..config.email_routing import" service/app/ | wc -l` and confirming ≥14.
- ~~**Registry agents persist across Code-tab restart.** Source: prior diagnostic + this session's PR #35 work.~~ MOVED TO FACTS 2026-05-13: this session successfully dispatched both `agent-performance-observer` and `flow-context-keeper` post-merge — see RULE 6 visibility entry above.
- ~~**No deletion of `gap-hunter.md` or `adr-historian.md` from main between this session and the next.**~~ MOVED TO FACTS 2026-05-13: registry verified healthy at start of this run (15 agents in `.claude/agents/`).

---

# OPEN QUESTIONS

- **Will the operator pick Option A, B, or C for the ADR-010 conflict on PR #33?** Answerer: operator. Impact: blocks Phase 4 merge, Phases 5-8, and the entire P2-P5 program timeline. Candidate paths: see PR #33 escalation comment.
- **Tejal availability for P4 / P5 reviewer gates** — not yet confirmed for the May-June window. Answerer: Tejal (via operator). Impact: gates P4 live promotion + P5 live promotion. P4 needs ≥200 shadow classifications + Tejal sign-off; P5 needs Tejal + Inventory/Finance Reviewer + Operator Safety Reviewer.
- **When does the Windows machine catch up on the merged PRs (#34, #35, #37, future #33)?** Answerer: operator. Impact: production at `C:\PZ` runs older code than `main`. Per CLAUDE.md "Production deployment rule": deploy requires the 7-agent gate.
- **Should the 10-ADR salvage from `feature/dhl-label-workflow-planning` (ADR-001..005, 007..009, 011, 017) fire now or wait?** Answerer: operator. Impact: main's `README.md` references those ADRs as "Accepted" but bodies are missing. Salvage audit verdict 2026-05-13: file-level port is mechanical (15-30 min). Candidate path: separate focused PR after PR #33 lands.
- **Will any of the 4 obsolete `feat/doc-1..4` branches be tagged-and-deleted or archived?** Answerer: operator preference. Impact: minor — they're superseded by PR #34 but harmless if left.
- **Is the `_TOP_LEVEL_FIELDS` enforcement gap on `dhl_clearance_manifest.py` (system-architect LOW finding) acceptable to defer to P2 kickoff, or should it be addressed in a hotfix PR after PR #33 merges?** Answerer: operator. Impact: a future phase implementer could write a top-level field that bypasses the schema fence. Filed in Issue #38 as SCHEDULED for P2.

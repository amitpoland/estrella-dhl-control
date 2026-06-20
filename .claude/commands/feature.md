# /feature — Feature Implementation Command

Task: $ARGUMENTS

Execute the canonical five-phase protocol for every new feature.
**Read `.claude/TASK_EXECUTION_PROTOCOL.md` completely before Phase 1.**

Authority sources (load before any action):
- `.claude/TASK_EXECUTION_PROTOCOL.md` — full phase rules, exit criteria, HOLD conditions
- `docs/governance/AUTHORITY_MAP.md` — write authority by domain
- `docs/governance/anti-hold-and-completion.md` — Anti-HOLD spec, must-continue list
- `.claude/memory/PROJECT_STATE.md` — current project state (RULE 1)
- `.claude/memory/TASK_STATE.md` — in-flight task tracker

---

## Phase 1 — DISCOVERY

**Step 0 — Skill routing (runs first, before any file read):**
Read `.claude/SKILL_ROUTING.md` and emit the routing block for `$ARGUMENTS`:

```
SKILL_ROUTING
─────────────────────────────────────────
TASK_TYPE:      <from routing table>
SELECTED_SKILL: <primary skill(s)>
SECONDARY:      <secondary skill or "none">
REASON:         <matched keywords>
CONFIDENCE:     HIGH | MEDIUM | LOW
─────────────────────────────────────────
```

Rules:
- **LOW confidence** → continue DISCOVERY with safest available skill. Do not HOLD.
- **MISSING_SKILL** → add to `BACKLOG.md` (if not already present) with disposition SCHEDULED; use fallback `backend-route-and-service-builder`.
- Full algorithm and sample resolutions: `.claude/SKILL_ROUTING.md`.

1. Read `.claude/memory/PROJECT_STATE.md` and `TASK_STATE.md`.
2. If `TASK_STATE.md` shows `IN_PROGRESS` for a different task → HOLD (one-task rule).
3. Update `TASK_STATE.md` → `IN_PROGRESS` for this task.
4. **GATE 2 check:** Count open implementation PRs. If ≥ 3 → switch to merge-and-review mode; do not open another PR until count drops below 3.
5. Read `AUTHORITY_MAP.md` — identify domain authority owner and forbidden write locations for this task.
6. Load the `SELECTED_SKILL` from the routing block above. Invoke it now per its usage instructions.
7. Spawn `gap-detection` subagent: `"Read the task description and inspect relevant files. Report missing context, missing backend endpoints, missing business rules, missing test coverage. DO NOT edit any files — read and report only."`
8. Record any out-of-scope findings in `BACKLOG.md`.

**Exit:** skill-routing block emitted · domain authority named · selected skill loaded · GATE 2 confirmed · gap-detection returned · TASK_STATE.md = IN_PROGRESS.

---

## Phase 2 — PLAN

1. Produce exact file list (named files only — no wildcards).
2. Produce test plan (which suite, which new tests, pass criteria).
3. Confirm every planned write target is in the domain's `Write targets` column (AUTHORITY_MAP.md). Confirm no write touches a `Forbidden write locations` entry.
4. **Spawn `reviewer-challenge` — MANDATORY for every /feature invocation.**
   Prompt: `"Review this feature plan for hidden risks, false assumptions, missing backend, bad abstractions, unsafe shortcuts. Task: <task>. Plan: <file list + test plan>. DO NOT edit files — read and report only."`
   Wait for verdict. Resolve or escalate every HIGH/CRITICAL finding before proceeding.
5. Check HOLD conditions (full list: `TASK_EXECUTION_PROTOCOL.md` §Phase 2):
   - Destructive production action required? → HOLD
   - Missing credentials/access? → HOLD
   - Legal/financial approval required? → HOLD
   - Unclear business decision with real cost if wrong? → HOLD
   - Technical ambiguity with a sensible default → NOT a HOLD. Pick default, note it, continue.

**Mandatory subagents for a feature task:**
| Subagent | Phase | Prompt boundary |
|---|---|---|
| `gap-detection` | DISCOVERY | read and report only — DO NOT edit files |
| `Plan` | PLAN (optional for complex tasks) | read-only; produces file list + test plan |
| `reviewer-challenge` | PLAN | read and report only — DO NOT edit files |
| `final-consistency-review` | VERIFY | read and report only — DO NOT edit files |
| `flow-context-keeper` | CLOSE | update PROJECT_STATE.md only |

**Exit:** exact file list · test plan · reviewer-challenge CLEAR · write authority confirmed · no GATE violations.

---

## Phase 3 — IMPLEMENT

1. Edit only files on the plan's file list.
2. **Scope guard:** After every file edit run `git diff --name-only`. Any file not on the plan list → record in `BACKLOG.md` and revert before continuing.
3. Write new/modified tests per the test plan.
4. Commit to feature branch. Never commit to `main`.
5. Do not open a PR during this phase.

**Exit:** only plan-listed files changed · tests written · changes committed · `git diff --name-only` matches plan.

---

## Phase 4 — VERIFY

Run the required test matrix (full table: `TASK_EXECUTION_PROTOCOL.md` §Phase 4):

| This task touches | Run |
|---|---|
| `service/app/*.py` | `pytest tests/ -m smoke -q` |
| Domain-specific backend | `pytest tests/test_<domain>_*` |
| Root engine files | `make verify` |
| UI (V1 or V2) | GATE 6 browser verification |
| Docs/governance only | Smoke N/A — document explicitly |

Spawn `final-consistency-review`:
`"Check that no incomplete work, unanswered questions, fake assumptions, disconnected UI, missing backend, broken tests, or uncommitted confusion exist. DO NOT edit files — read and report only."`

**GATE 1 checklist (must be satisfied before opening PR):**
- [ ] All named subagents returned verdicts (or substitution disclosed per GATE 5)
- [ ] Every HIGH/CRITICAL finding resolved or escalated
- [ ] Browser verification complete, or N/A documented with justification
- [ ] Required test suites passed with counts
- [ ] `git diff --name-only` matches plan list exactly
- [ ] `final-consistency-review`: CLEAR

**Exit:** GATE 1 satisfied · GATE 2 < 3 open PRs.

---

## Phase 5 — CLOSE

Execute in order:
1. Open draft PR (squash merge strategy).
2. Mark PR ready for review.
3. Merge PR (if rules allow) or await review.
4. Fire `agent-performance-observer` if ≥ 3 subagents were activated.
5. Fire `flow-context-keeper` — mandatory after every merge to main. Update `PROJECT_STATE.md`.
6. Update `TASK_STATE.md` → `COMPLETE`.
7. Update `BACKLOG.md` (close resolved items; carry forward open ones with GATE 4 dispositions).
8. Write completion report (format below).

**Deploy boundary:** Merging does NOT deploy to production. Production requires operator-executed `/deploy` + full 7-agent gate on the Windows server.

---

## Required output — Completion Report

```
## Completion Report — <task title>

Date: YYYY-MM-DD
Branch: <branch>
Merge SHA: <sha>

### Changed files
- <path>: <one-line purpose>

### Tests run
| Suite | Result |
|---|---|
| smoke | N passed |
| <targeted suite> | N passed |

### GATE 1: SATISFIED
### GATE 2: N/3 open PRs after merge

### Side-discoveries → BACKLOG
- <item or "none">

### flow-context-keeper: FIRED / SKIPPED (reason if skipped)

### Next action
<exact next task prompt or "NONE — board is clear">
```

---

## Invocation examples

```
/feature Add proforma snapshot columns (ADR-022 PR-2)
/feature Wire DHL lane-readiness to V2 dashboard
/feature Add email idempotency guard to SLA runner
/feature Build /bug command
```

---

## Integration points

| Integration | Detail |
|---|---|
| **Skill routing** | `.claude/SKILL_ROUTING.md` — keyword → skill map, algorithm, sample resolutions |
| Protocol authority | `.claude/TASK_EXECUTION_PROTOCOL.md` — full phase rules |
| Write authority | `docs/governance/AUTHORITY_MAP.md` |
| Anti-HOLD rules | `docs/governance/anti-hold-and-completion.md` §2 |
| GATE 1–6 | `CLAUDE.md` §MANDATORY GOVERNANCE GATES |
| Project state | `.claude/memory/PROJECT_STATE.md` (RULE 1) |
| Task tracker | `.claude/memory/TASK_STATE.md` |
| Side-discoveries | `BACKLOG.md` (repo root) |
| Observer scorecard | `.claude/memory/scorecards/` |
| Command registry | `.claude/commands/COMMAND_REGISTRY.md` |

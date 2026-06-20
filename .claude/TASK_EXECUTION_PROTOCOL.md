# TASK_EXECUTION_PROTOCOL.md

Canonical five-phase execution protocol for every `/feature` and `/bug` command.
Every task follows this sequence in order: **DISCOVERY → PLAN → IMPLEMENT → VERIFY → CLOSE**.

Governing sources (read at session start, do not re-derive):
- `CLAUDE.md` — GATES 1–6, Anti-HOLD, Engineering Lessons, 7-agent deploy gate
- `docs/governance/anti-hold-and-completion.md` — full Anti-HOLD spec, decision table, 4 HOLD conditions
- `docs/governance/AUTHORITY_MAP.md` — write authority by domain, cross-domain principles P1–P4
- `.claude/memory/PROJECT_STATE.md` — current project state (RULE 1, CLAUDE.md)
- `.claude/memory/TASK_STATE.md` — in-flight task tracker

---

## Standing rules (apply to all phases)

**One task at a time.**
If `TASK_STATE.md` shows `IN_PROGRESS`, finish or record a HOLD before starting new work.

**Anti-HOLD default.**
Continuing is the default. Only four conditions justify a stop — see `docs/governance/anti-hold-and-completion.md` §2. Never stop to ask the operator about work in the must-continue list (code inspection, repo search, test execution, local verification, doc/state updates, committing to a feature branch, opening a draft PR).

**BACKLOG rule.**
Side-discoveries made during any phase go to `BACKLOG.md` (repo root; create if missing). Do not expand scope mid-task. Do not stop for side-discoveries. Record and continue.

**Lesson K (agent prompts).**
Every subagent dispatched with write-capable tools (Bash, Write, Edit, gh, MCP write tools) MUST receive explicit negative-scope language: `"DO NOT call <X>, <Y> — read and report only."` Generic phrasing ("verdict only") is insufficient. See `CLAUDE.md` §Lesson K.

---

## Observation Period Policy

Observation is **passive measurement, not a release gate.**

While observation is active:

- New feature development continues normally.
- Existing roadmap items continue normally.
- Bug fixes continue normally unless separately restricted.
- Deployments continue normally.
- Approved project phases continue normally.

Observation does **not** require waiting for calendar time.
Observation does **not** require waiting for a minimum number of days.
Observation does **not** pause the roadmap.
Observation does **not** create a HOLD state.

The only purpose of observation is to record completed `/feature` executions in
`FEATURE_SCORECARD.md` and evaluate the collected evidence later. The absence of
scorecard entries must never prevent development work.

See `docs/governance/OBSERVATION_IS_NOT_A_GATE.md` for the binding rule and
acceptance criteria. This policy is subordinate to the four HOLD conditions in
`docs/governance/anti-hold-and-completion.md` §2 — observation adds no new HOLD.

---

## Phase 1 — DISCOVERY

**Purpose:** Understand scope before any code is written. Identify authority, select skill and subagent roster.

**Required inputs:** Task description; affected domain.

**Allowed actions:**
- Read files, grep, glob, web search
- Read `AUTHORITY_MAP.md` to identify domain authority owner and forbidden write locations
- Read `PROJECT_STATE.md`, `TASK_STATE.md`, open PRs (GATE 2 check)
- Read existing tests for the affected domain
- Spawn `Explore` or `gap-detection` subagent (non-blocking; report only)
- Write side-discoveries to `BACKLOG.md`
- Update `TASK_STATE.md` to `IN_PROGRESS`

**Forbidden actions:**
- Edit any `service/app/*` file
- Run tests
- Open a PR
- Make any API, database, or production change

**Skill selection checkpoint:**

| Task domain | Skill to load |
|---|---|
| PZ batch / golden constants / CLI | `pz-shipment` |
| Production deployment | `deploy` |
| DHL clearance / customs | `dhl-customs` *(planned — use AUTHORITY_MAP.md §DHL Clearance until built)* |
| Proforma / conflict / workspace | `proforma-engine` *(planned — use AUTHORITY_MAP.md §Proforma until built)* |
| wFirma API | `wfirma` *(planned — use AUTHORITY_MAP.md §wFirma until built)* |
| Frontend (V1 frozen / V2 active) | `frontend-design` + `ui-ux-pro-max` |
| Cowork / AI bridge | `cowork-integration` |
| Engineering lesson pattern | `engineering-lessons` |

If a domain skill is not yet built, document that explicitly and proceed with the AUTHORITY_MAP.md section as a substitute. This is not a HOLD.

**GATE 2 check:** Count open implementation PRs. If ≥ 3, switch to merge-and-review mode before opening another.

**Exit criteria:**
- [ ] Domain authority owner named (from AUTHORITY_MAP.md)
- [ ] Skill selected or substitute documented
- [ ] GATE 2 count confirmed
- [ ] gap-detection subagent run (for non-trivial tasks; advisory only)
- [ ] Side-discoveries in `BACKLOG.md`
- [ ] `TASK_STATE.md` → `IN_PROGRESS`

---

## Phase 2 — PLAN

**Purpose:** Define exactly what changes, in which files, with what tests, before touching code.

**Required inputs:** DISCOVERY output; confirmed authority owner; skill loaded.

**Allowed actions:**
- Spawn `Plan` subagent (read-only; produces file list + test plan)
- Spawn `reviewer-challenge` subagent (mandatory for non-trivial implementations)
- Read additional files as needed
- Ask the operator if hitting a genuine HOLD condition (see §HOLD conditions below)
- Write plan to working notes (do not commit yet)

**Forbidden actions:**
- Edit any runtime file (`service/app/*`)
- Open a PR
- Skip `reviewer-challenge` for backend or multi-file changes

**HOLD conditions** (the only valid reasons to stop — `docs/governance/anti-hold-and-completion.md` §2):
1. **Destructive production action** — plan requires mutating live production data or a booked external record
2. **Missing credentials / access** — required secret or permission not available in this session
3. **Legal / financial approval** — plan touches wFirma booked documents, SAD, money movement
4. **Unclear business decision** — business fork not resolvable from repo, and wrong guess has real cost

Technical ambiguity with a sensible default is NOT a HOLD. Pick the default, note it, continue.

**Authority-map check:**
- Confirm every planned write target is in the domain's `Write targets` column (AUTHORITY_MAP.md)
- Confirm no write touches a `Forbidden write locations` entry
- If the plan crosses domain boundaries, confirm each domain's authority separately

**Deploy boundary check:**
- Files under `service/app/**` → standard robocopy sync (7-agent gate required for production)
- Root engine files (`pz_import_processor.py`, `polish_description_generator.py`) → Lesson J applies; separate robocopy to `C:\PZ\engine\` required
- Docs / state files → no production sync needed

**Subagent dispatch checkpoint:**

| Task type | Mandatory subagents |
|---|---|
| Feature (new capability) | `gap-detection`, `Plan`, `reviewer-challenge`, `final-consistency-review`, `flow-context-keeper` |
| Bug fix | `gap-detection`, `reviewer-challenge`, `final-consistency-review`, `flow-context-keeper` |
| Production deploy | 7-agent gate (CLAUDE.md §Production deployment rule) |
| PR finalization | `final-consistency-review`, `flow-context-keeper` |
| State / docs update | `flow-context-keeper` |

Substitution: if a named subagent is unavailable, disclose per GATE 5 (CLAUDE.md §GATE 5). Silent substitution is forbidden.

**Exit criteria:**
- [ ] Exact file list produced (named files only, no wildcards)
- [ ] Test plan defined (which suite, which new tests, pass criteria)
- [ ] `reviewer-challenge` returned verdict (CLEAR or findings resolved inline)
- [ ] AUTHORITY_MAP.md write-authority confirmed for all changed files
- [ ] Deploy boundary determined
- [ ] No GATE violations outstanding

---

## Phase 3 — IMPLEMENT

**Purpose:** Make exactly the planned changes and nothing else.

**Required inputs:** PLAN output (exact file list + test plan + reviewer-challenge clearance).

**Allowed actions:**
- Edit files on the plan's file list
- Write new tests per the test plan
- Run formatters / linters
- Commit to feature branch (never directly to `main`)
- Record newly noticed side-discoveries in `BACKLOG.md`

**Forbidden actions:**
- Edit files not on the plan's file list
- Refactor unrelated code
- Add scope beyond the task definition
- Modify `golden_constants.py` without the regression suite first failing (pre-commit hook enforces)
- Push to `main`
- Open a PR during this phase

**Scope guard:** After every file edit, confirm `git diff --name-only` still matches the plan list. Any unexpected file triggers a scope-guard pause: record the unexpected file in `BACKLOG.md` and revert it before continuing.

**Exit criteria:**
- [ ] Only plan-listed files changed
- [ ] New/modified tests written per test plan
- [ ] Changes committed to feature branch
- [ ] No uncommitted modifications

---

## Phase 4 — VERIFY

**Purpose:** Confirm correctness; confirm no regressions; satisfy GATE 1 before PR.

**Required inputs:** Feature branch with committed changes.

**Required test matrix:**

| Change type | Required run |
|---|---|
| Any `service/app/*.py` | `pytest tests/ -m smoke -q` (pre-commit hook runs this automatically) |
| Domain-specific backend change | Targeted suite (e.g. `pytest tests/test_proforma_*` for proforma domain) |
| `golden_constants.py` modified | Full regression: `python test_pz_regression.py` (pre-commit hook blocks without it) |
| Root-level engine files | `make verify` from repo root |
| UI change (V1 or V2) | GATE 6 browser verification (console + network + execution path) |
| Backend-only (no UI surface) | GATE 6 N/A — document explicitly; curl + audit-log verification substitutes |

**Allowed actions:**
- Run any test suite
- Fix failures (loop back to IMPLEMENT)
- Spawn `final-consistency-review` subagent
- Spawn `integration-boundary` subagent if the change crosses service/UI/storage boundaries
- Perform browser verification for UI changes

**Forbidden actions:**
- Mark GATE 6 N/A when there IS a UI surface
- Open PR before GATE 1 is satisfied
- Claim "looks correct" without a test verdict

**GATE 1 pre-PR checklist** (`CLAUDE.md` §GATE 1):
- [ ] All named subagents returned verdicts
- [ ] HIGH/CRITICAL findings resolved or escalated to operator
- [ ] Browser verification complete (or N/A documented with justification)
- [ ] Regression tests run with verdict
- [ ] `git diff --name-only` matches plan list exactly
- [ ] `final-consistency-review` subagent: CLEAR

**Exit criteria:**
- [ ] All required test suites: PASS
- [ ] GATE 1 checklist: all items satisfied
- [ ] GATE 2: open PR count < 3

---

## Phase 5 — CLOSE

**Purpose:** Merge, record state, clean up. Leave the repo in a known-good state for the next session.

**Required inputs:** VERIFY output (GATE 1 satisfied); GATE 2 confirmed.

**Sequence (in order):**
1. Open draft PR (squash merge strategy — standard for this repo)
2. Mark PR ready for review
3. Merge PR
4. Fire `agent-performance-observer` if ≥ 3 subagents were activated (RULE 2, CLAUDE.md)
5. Fire `flow-context-keeper` (RULE 3, CLAUDE.md — mandatory after every merge to main)
6. Update `TASK_STATE.md` → `COMPLETE`
7. Update `BACKLOG.md` (close resolved items; carry forward open ones)
8. Write completion report (see §Completion report format)

**Forbidden actions:**
- Merge before GATE 1 is satisfied
- Skip `flow-context-keeper` after a merge to main
- Push directly to `main`
- Start a new task before step 8 is complete

**Deploy boundary reminder:**
Code changes do NOT automatically reach production. Production sync requires:
- Operator-executed deploy on the Windows server
- Full 7-agent gate (CLAUDE.md §Production deployment rule)
- `/deploy` command

Never instruct the operator to deploy without completing the 7-agent gate first.

**Exit criteria:**
- [ ] PR merged (squash)
- [ ] `flow-context-keeper` fired; `PROJECT_STATE.md` updated
- [ ] `TASK_STATE.md` → `COMPLETE`
- [ ] `BACKLOG.md` updated
- [ ] Completion report written

---

## Completion report format

Every CLOSE phase must produce this block before the session ends:

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
- <item> (or "none")

### flow-context-keeper: FIRED / SKIPPED (reason if skipped)

### Next action
<exact next task prompt or "NONE — board is clear">
```

---

## Reference map

| Concept | Location |
|---|---|
| 4 HOLD conditions | `docs/governance/anti-hold-and-completion.md` §2 |
| Must-continue list | `docs/governance/anti-hold-and-completion.md` §2 |
| Write authority by domain | `docs/governance/AUTHORITY_MAP.md` |
| Workflow completion checklist | `docs/governance/anti-hold-and-completion.md` §4 |
| TASK_STATE protocol | `docs/governance/anti-hold-and-completion.md` §5 |
| GATES 1–6 full text | `CLAUDE.md` §MANDATORY GOVERNANCE GATES |
| 7-agent deploy gate | `CLAUDE.md` §Production deployment rule |
| Engineering Lessons A–M | `CLAUDE.md` §Engineering Lessons |
| Observation RULES 1–6 | `CLAUDE.md` §MANDATORY OBSERVATION LAYER |
| Observation is not a gate | `docs/governance/OBSERVATION_IS_NOT_A_GATE.md` · §Observation Period Policy above |
| Agent substitution disclosure | `CLAUDE.md` §GATE 5 |
| Lesson K (agent prompt scope) | `CLAUDE.md` §Lesson K |

# Role Routing Table

Authority for *who works on what* and *what they may touch*.
Built on top of `engineering/charter.md` — the charter names the
roles and assigns models; this file makes the boundaries
**operational** by attaching path globs, triggers, and review
obligations to each role.

> Charter says *what each role is*.
> This file says *what they're allowed to edit, what they only
> review, and when they activate*.

If the two files disagree, the charter wins on identity (model
tier, layer, deliverable), this file wins on paths and triggers.

## How to read a row

| Column | Meaning |
|---|---|
| Allowlist | Path globs the role MAY edit. Empty = read-only. |
| Denylist | Path globs the role MUST NOT touch even with permission elsewhere. |
| Triggers | Conditions that activate the role (file-glob touch, gate failure, ADR draft, mode entry). |
| Reviews | What the role signs off on. A role never reviews its own work. |
| Reports to | The Coordinator unless overridden. |

Path globs are POSIX-style. `service/` is the FastAPI service
root. `ui/dashboard.html` is the operator console.

---

## Layer 1 — Coordinator

### Lead Staff Architect (Coordinator)
- **Model:** Opus 4.7
- **Allowlist:** `.claude/org/program_board.md`, `.claude/adr/*.md`,
  `.claude/engineering/*.md` (rare; ADR-style supersession only)
- **Denylist:** `service/app/**`, `ui/**`, `service/tests/**`,
  golden constants, migrations
- **Triggers:** every session start; every mode transition; every
  phase commit; any reviewer escalation
- **Reviews:** all final diffs, all live-flag flips, all rollbacks
- **Reports to:** the operator (you)

### ADR / Decision Historian
- **Model:** Sonnet 4.6
- **Allowlist:** `.claude/adr/*.md`, `.claude/adr/README.md`
- **Denylist:** everything else
- **Triggers:** Coordinator draft; any architectural decision in
  the program board entering state `decided`
- **Reviews:** ADR completeness only

### Production Readiness Reviewer
- **Model:** Opus 4.7
- **Allowlist:** `.claude/engineering/production-readiness-checklist.md`
- **Denylist:** `service/app/**`, `ui/**`
- **Triggers:** any Coordinator request to flip a `live_*_enabled`
  flag; entry to RELEASE mode
- **Reviews:** the cutover diff against the checklist

---

## Layer 2 — Engineering

### Backend Architect
- **Model:** Opus 4.7
- **Allowlist:** *(read-only first)* — escalates to Coordinator with a
  written design before any edit
- **Denylist:** dashboard, tests, ADRs (drafts via Historian)
- **Triggers:** new workstream entering `design` state; any change
  to `service/app/services/carrier/carrier_coordinator.py`,
  `carrier_state_engine.py`, adapter base classes, execution engine
- **Reviews:** Implementation Engineer diffs that touch coordinator
  / state engine / adapter contracts

### Implementation Engineer
- **Model:** Sonnet 4.6
- **Allowlist:** `service/app/services/**`,
  `service/app/api/routes_*.py`, `service/tests/**`
- **Denylist:** `.claude/**`, `service/app/core/timeline.py` (event
  catalogue; Coordinator-approved additions only),
  `service/app/core/config.py` (settings additions need Backend
  Architect review)
- **Triggers:** Coordinator-approved phase plan; only inside
  IMPLEMENTATION mode
- **Reviews:** *none* — implementer never reviews

### API / Route Mapper
- **Model:** Sonnet 4.6
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any new route file; any change to request /
  response schema; entry to PRE-IMPLEMENTATION
- **Reviews:** Implementation Engineer route diffs for shape,
  auth, response envelope consistency

### DB / State Engineer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only first)* — write only on
  Coordinator-approved migration plan
- **Denylist:** route layer, adapters
- **Triggers:** any change to `service/app/services/carrier/
  carrier_*_db.py`, `*.db` paths, schema, idempotency contracts
- **Reviews:** anything that touches SQLite WAL, replay safety,
  rollback compatibility

### Integration Engineer
- **Model:** Sonnet 4.6
- **Allowlist:** `service/app/services/**/adapters/*.py`,
  `service/tests/test_*adapter*.py`, `service/tests/test_*live*.py`
- **Denylist:** coordinator, state engine, DB, routes
- **Triggers:** new external API integration; DHL adapter changes
- **Reviews:** Backend Architect signs off on adapter contract
  changes

### Execution Guard Engineer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any new write-action route; any change to
  `proposal_write_lock`, `_select_carrier_adapter`, gate stacks
- **Reviews:** Implementation Engineer write-action diffs for
  proposal_id matching, idempotency, lock ordering

---

## Layer 3 — Reliability

### QA / Test Lead
- **Model:** Sonnet 4.6
- **Allowlist:** `service/tests/**`
- **Denylist:** `service/app/**`
- **Triggers:** every phase commit; every IMPLEMENTATION exit; any
  test added without a paired source change
- **Reviews:** test coverage for Implementation Engineer diffs;
  flaky-test signals; source-grep guard quality

### Gap / Bug Hunter
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** PRE-IMPLEMENTATION mode entry; before any
  live-flag flip; on Coordinator request
- **Reviews:** cross-phase contradictions, silent downgrades,
  hidden assumptions, concurrency holes, stale routes

### Performance Engineer
- **Model:** Sonnet 4.6
- **Allowlist:** *(read-only)*
- **Denylist:** all editing (latency fix proposals route through
  Backend Architect)
- **Triggers:** any synchronous external call; live-flag flip
- **Reviews:** route-level latency budgets

### Observability Engineer
- **Model:** Sonnet 4.6
- **Allowlist:** telemetry config, structured-log additions, metric
  definitions; minimal `log.warning` / `log.info` additions inside
  existing modules
- **Denylist:** route logic, coordinator logic, adapter logic
- **Triggers:** any new failure path; any new fail-loud telemetry
  surface; entry to RELEASE mode
- **Reviews:** correlation-ID propagation, log-line structure,
  dashboard metric coverage

### Migration / Schema Engineer
- **Model:** Sonnet 4.6
- **Allowlist:** DB-init code only; migration scripts
- **Denylist:** route layer, adapters
- **Triggers:** schema change; new SQLite table; column rename
- **Reviews:** rollback compatibility of every migration

---

## Layer 4 — Security & Compliance

### Security Reviewer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any change to auth, IP allowlists, redaction,
  filesystem access, webhook handling, credential handling, error
  summarisation; before any `live_*_enabled` flip
- **Reviews:** P0 / P1 / P2 blocker list; reports to Coordinator
  who decides

### Audit Evidence Reviewer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any change to `service/app/core/timeline.py`,
  audit.json schema, event taxonomy
- **Reviews:** evidence lineage, replay loss, missing traceability

### Customs Compliance Reviewer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any change to PZ engine, ZC429/SAD parser, CIF /
  duty / VAT logic, customs document handling
- **Reviews:** regulatory exposure on shipment + customs flows

### Data Privacy Reviewer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any change that persists, logs, or transmits
  operator/customer/carrier data
- **Reviews:** PII surface map; redaction completeness

---

## Layer 5 — UX

### Claude Design UX Lead
- **Model:** Sonnet 4.6
- **Allowlist:** UX spec docs only (e.g. `.claude/ui_specs/*.md`)
- **Denylist:** `ui/**`, `service/app/**`
- **Triggers:** Coordinator request for new operator workflow
- **Reviews:** *none* — proposes; Implementation Engineer
  implements; Operator Safety Reviewer audits

### Workflow Mapper
- **Model:** Sonnet 4.6
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** new operator surface; new state in carrier state
  engine
- **Reviews:** end-to-end operator flow against routes

### Dashboard Reviewer
- **Model:** Sonnet 4.6 (mapped to `frontend-flow-reviewer` agent)
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any change to `ui/dashboard.html`
- **Reviews:** broken operator flow, hidden actions, direct unsafe
  API calls, missing disabled reasons

### Operator Safety Reviewer
- **Model:** Opus 4.7
- **Allowlist:** *(read-only)*
- **Denylist:** all editing
- **Triggers:** any new write-action button; any change to
  confirmation dialogs, disabled states, irreversible actions
- **Reviews:** UX-level live-risk; same-day rollback affordances

---

## Layer 6 — Release

### Release Manager
- **Model:** Sonnet 4.6
- **Allowlist:** release notes, commit message linting, tag
  creation (when adopted)
- **Denylist:** code, tests, ADRs
- **Triggers:** RELEASE mode entry; phase commit; rollback fire
- **Reviews:** commit message hygiene, phase ordering, test gate
  evidence in commit body

---

## Existing sub-agent file mappings

The `.claude/agents/*.md` definitions are the *spawnable* form of
several routing roles. Mapping:

| Routing role | Agent definition |
|---|---|
| Backend Architect (read pass) | `agents/backend-safety-reviewer.md` |
| Execution Guard Engineer | `agents/security-write-action-reviewer.md` |
| Dashboard Reviewer | `agents/frontend-flow-reviewer.md` |
| QA Test Lead (review pass) | `agents/test-coverage-reviewer.md` |

Other roles execute as in-context Coordinator passes for now;
they may grow their own agent definition files as their cadence
justifies it.

---

## Conflict resolution

When two roles claim the same file:

1. **Editor wins over reviewer** — only one role may have an
   allowlist hit on a given path; that role edits, others review.
2. **Coordinator breaks ties.**
3. **No path may have zero owners.** A glob with no owner is a
   governance bug — log it on the program board under
   `governance_debt`.

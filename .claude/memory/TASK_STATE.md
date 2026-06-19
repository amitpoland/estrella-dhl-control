# TASK_STATE.md

In-flight **single-task** tracker. Records the current task's goal,
completion criteria, status, and HOLD reason (if stopped). Ephemeral —
rewrite the `## Current task` block when a new task begins.

Rules and boundary vs PROJECT_STATE.md:
`docs/governance/anti-hold-and-completion.md` §5.

- **Do not** start a second task while the current one is `IN_PROGRESS`
  (unless the operator explicitly redirects).
- **Do** record a one-line HOLD reason (one of the four valid conditions)
  whenever you stop, so the next session resumes without re-derivation.
- Status values: `NOT_STARTED` · `IN_PROGRESS` · `BLOCKED-HOLD` · `COMPLETE`.

---

## Current task

- **Task:** Build Anti-HOLD and Workflow Completion Governance
- **Started:** 2026-06-19
- **Status:** COMPLETE
- **HOLD reason (if BLOCKED-HOLD):** —

### Completion criteria

- [x] Anti-HOLD rule added to `CLAUDE.md` (§ANTI-HOLD AND WORKFLOW COMPLETION)
- [x] Full governance doc created (`docs/governance/anti-hold-and-completion.md`):
      principle, decision table, four HOLD conditions, must-continue list,
      worked examples, completion checklist
- [x] Task-state tracker created (`.claude/memory/TASK_STATE.md`)
- [x] Stop/continue conditions defined (4 stop, 6 continue)
- [x] Verified: sample HOLD decisions shown; normal dev not blocked;
      destructive actions still require operator approval
- [x] Only intended files changed (docs/state only; no `service/app`, no runtime)
- [x] Committed to `claude/anti-hold-governance`, pushed, draft PR opened (PR #659)
- [x] TASK_STATE.md → COMPLETE on merge (PR #659 merged)

---

## History (most recent first)

- 2026-06-20 — PR #659 merged. First complete governance package landed:
  Anti-HOLD + TASK_STATE + AUTHORITY_MAP (PR #660, merged 2026-06-20).
- 2026-06-19 — Task opened: Anti-HOLD and Workflow Completion Governance.
  Docs-only by decision (no blocking hook — would contradict ANTI-HOLD
  fail-open principle and risk wedging the session).

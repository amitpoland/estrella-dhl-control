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

- **Task:** Improve DHL shipment detail diagnostics and operator visibility
- **Started:** 2026-06-21
- **Status:** IN_PROGRESS
- **HOLD reason (if BLOCKED-HOLD):** —

### Completion criteria

- [ ] `pz-api.js` — `getDhlReadiness(batchId)` added
- [ ] `service/app/static/v2/shipment-detail-page.jsx` — `DhlReadinessCard` component added
- [ ] `DhlTab` wired to `DhlReadinessCard` (lifecycle state, blocking reason, authority, next action)
- [ ] Hardcoded mock customs values marked BACKEND_PENDING
- [ ] reviewer-challenge CLEAR (REVISE findings resolved before implementation)
- [ ] `pytest service/tests/ -m smoke -q` passes
- [ ] GATE 1 satisfied
- [ ] GATE 6 documented (browser verification deferred to operator)
- [ ] PR opened as draft on `claude/new-session-fetvj6`
- [ ] `TASK_STATE.md` → COMPLETE
- [ ] FEATURE_SCORECARD Row #2 filled

---

## History (most recent first)

- 2026-06-21 — Task #1 COMPLETE: PR #687 draft (proforma readiness display in V2 DHL tab)

- 2026-06-20 — /feature command created at .claude/commands/feature.md.

  COMMAND_REGISTRY.md updated. BACKLOG B-001 (PR #661 review) filed.
- 2026-06-20 — TASK_EXECUTION_PROTOCOL.md created and merged via draft PR.
  Canonical DISCOVERY→PLAN→IMPLEMENT→VERIFY→CLOSE protocol. BACKLOG.md seeded.
- 2026-06-20 — PR #630 squash-merged at a40c7c5. PR-1A closes B1–B5 governance
  gaps post PR-1 (#626). PR-2 (ADR-022 Snapshot Layer) now unblocked.
- 2026-06-20 — PR #659 + PR #660 merged (governance package). GATE 2 back to 0/3.
- 2026-06-20 — Task opened: Finalize PR #630.

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

- **Task:** Add proforma readiness status display to V2 shipment detail page
- **Started:** 2026-06-21
- **Status:** IN_PROGRESS
- **HOLD reason (if BLOCKED-HOLD):** —

### Completion criteria

- [ ] `service/app/static/v2/shipment-detail-page.jsx` updated — `ProformaTabInShipment` replaced with two-component readiness display
- [ ] reviewer-challenge findings resolved (REVISE → implementation corrects `draft_state` field, 8 lifecycle states, write-on-read stagger)
- [ ] `pytest service/tests/ -m smoke -q` passes (no backend changes; sanity gate)
- [ ] GATE 1 satisfied (final-consistency CLEAR)
- [ ] GATE 6 documented as requiring operator browser verification (remote container cannot complete)
- [ ] PR opened as draft, marked ready for review
- [ ] `TASK_STATE.md` → COMPLETE
- [ ] `BACKLOG.md` updated (B-002 added)

---

## History (most recent first)

- 2026-06-20 — /feature command created at .claude/commands/feature.md.
  COMMAND_REGISTRY.md updated. BACKLOG B-001 (PR #661 review) filed.
- 2026-06-20 — TASK_EXECUTION_PROTOCOL.md created and merged via draft PR.
  Canonical DISCOVERY→PLAN→IMPLEMENT→VERIFY→CLOSE protocol. BACKLOG.md seeded.
- 2026-06-20 — PR #630 squash-merged at a40c7c5. PR-1A closes B1–B5 governance
  gaps post PR-1 (#626). PR-2 (ADR-022 Snapshot Layer) now unblocked.
- 2026-06-20 — PR #659 + PR #660 merged (governance package). GATE 2 back to 0/3.
- 2026-06-20 — Task opened: Finalize PR #630.

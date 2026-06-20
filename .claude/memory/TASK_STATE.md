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

- **Task:** PR-2 Contractor-at-Birth Projection — carry `shipment_documents.client_contractor_id` through sales → proforma draft → reservation; visible blocked draft-birth records; idempotent backfill
- **Started:** 2026-06-20
- **Status:** IN_PROGRESS
- **HOLD reason (if BLOCKED-HOLD):** —
- **Branch / worktree:** `feat/contractor-at-birth-projection` @ `C:\PZ-pr2` (base origin/main `5242417`)

### Completion criteria

- [ ] Additive idempotent ALTERs: `client_contractor_id` on sales_documents, sales_packing_lines, proforma_drafts, wfirma_reservation_drafts
- [ ] Projection at birth (store_sales_document, store_sales_packing_lines, proforma draft, reservation draft)
- [ ] Idempotent backfill from `shipment_documents.client_contractor_id` (operator-triggered endpoint)
- [ ] Draft grouping key = `client_contractor_id` (fallback `client_name`); silent loss removed
- [ ] Visible blocked draft-birth records (blocked_state / reason / code)
- [ ] Reservation readiness carries contractor reference chain (readiness only; no wFirma writes)
- [ ] Real-builder tests (schema / projection / grouping / blocked / backfill / reservation / regression)
- [ ] No valuation / CIF / customs / PZ / accounting / booking change (three-authority freeze)
- [ ] GATE 1 satisfied; FEATURE_SCORECARD Observation Row #1 written

### Prior task (COMPLETE)

- Build automatic skill routing for /feature — `.claude/SKILL_ROUTING.md` + `.claude/commands/feature.md`; merged.

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

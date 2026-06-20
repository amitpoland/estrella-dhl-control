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
- **Status:** COMPLETE
- **HOLD reason (if BLOCKED-HOLD):** —
- **Merge:** PR #673 squash-merged to main at `f652de0`. Docs/state on branch `chore/state-pr2-contractor-merge`.

### Completion criteria

- [x] Additive idempotent ALTERs: `client_contractor_id` on sales_documents, sales_packing_lines, proforma_drafts, wfirma_reservation_drafts
- [x] Projection at birth (store_sales_document, store_sales_packing_lines, proforma draft, reservation draft) — centralised derive in document_db, merge-not-replace
- [x] Idempotent backfill from `shipment_documents.client_contractor_id` (admin endpoint `POST /api/v1/admin/contractor-projection/backfill/{batch_id}`)
- [x] Contractor = grouping AUTHORITY (recovers missing client_name via Customer Master); client_name stays storage key; silent loss removed; draft count never decreases
- [x] Visible blocked draft-birth records (`proforma_draft_birth_blocks`; blocked_state / reason / code; open/resolved lifecycle)
- [x] Reservation readiness carries contractor reference chain (readiness only; no wFirma writes)
- [x] Real-builder tests — 26 (schema / projection / grouping / blocked / backfill / reservation / regression / HTTP route)
- [x] No valuation / CIF / customs / PZ / accounting / booking change (three-authority freeze)
- [x] GATE 1 satisfied (9 subagents, all verdicts; HIGH path-traversal fixed); FEATURE_SCORECARD Observation Row #1 written
- [ ] Deploy to production (C:\PZ) via 7-agent gate + operator backfill of SHIPMENT_9158478722 — PENDING (operator-run; not part of this code PR)

### Prior task (COMPLETE)

- Build automatic skill routing for /feature — `.claude/SKILL_ROUTING.md` + `.claude/commands/feature.md`; merged.

---

## History (most recent first)

- 2026-06-20 — PR #673 squash-merged at `f652de0`: PR-2 Contractor-at-Birth Projection.
  Scorecard `2026-06-20-pr2-contractor-at-birth-projection.md` (9 agents, 6 EXEMPLARY / 3 ACCEPTABLE).
  BACKLOG B-002..B-008 filed (all SCHEDULED). PROJECT_STATE updated.

- 2026-06-20 — /feature command created at .claude/commands/feature.md.
  COMMAND_REGISTRY.md updated. BACKLOG B-001 (PR #661 review) filed.
- 2026-06-20 — TASK_EXECUTION_PROTOCOL.md created and merged via draft PR.
  Canonical DISCOVERY→PLAN→IMPLEMENT→VERIFY→CLOSE protocol. BACKLOG.md seeded.
- 2026-06-20 — PR #630 squash-merged at a40c7c5. PR-1A closes B1–B5 governance
  gaps post PR-1 (#626). PR-2 (ADR-022 Snapshot Layer) now unblocked.
- 2026-06-20 — PR #659 + PR #660 merged (governance package). GATE 2 back to 0/3.
- 2026-06-20 — Task opened: Finalize PR #630.

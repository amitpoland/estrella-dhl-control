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

- **Task:** NONE — board is clear
- **Status:** NOT_STARTED
- **HOLD reason (if BLOCKED-HOLD):** —

### Prior task (COMPLETE) — Row #7 Show DHL AWB number on V2 shipment overview page (PR #716)

- **Started:** 2026-06-21
- **Status:** COMPLETE
- **Branch:** `feat/v2-dhl-awb-display` (commit `c88a829`)
- **PR:** #716 (draft, awaiting operator browser verification + merge)
- **Notes:** deriveDetail now reads `audit.tracking_no`. Sub-header uses `d.awb` with testid. OverviewTab DHL Clearance InfoBlock gains first row `AWB / Tracking` (mono). 5 contract tests + 63 smoke pass. PR-005 PASS. GATE 6 deferred to operator (remote container).

### Prior task (COMPLETE) — Proforma draft authority UI (PR #677)

- PR #677 squash-merged at `308145d`. V1 shipment-detail.html additive display-only: customer-authority summary + canonical description + blocked draft-birth records. BACKLOG B-012..B-014.

### Prior task (COMPLETE) — PR-3 Dropdown selection wins

- PR #675 squash-merged at `7b94a73`; backfill verified in prod on SHIPMENT_9158478722. PR-2+PR-3 DEPLOYED to C:\PZ @ 7b94a73, hashes match.

### Completion criteria (PR-3)

- [x] Forward: grouping uses canonical CM bill_to_name (overrides parsed); sales chain canonicalized (no split-brain); re-upload no dup
- [x] Resolver contractor-id-first (`derive_customer_authority_for_draft`); routes_proforma threads it
- [x] Migration (operator-triggered backfill, EDITABLE only): rename/supersede per clone_generation; charges money-safe (frozen canonical never drops); reservation canonical-wins; full disclosure (dropped/orphan/ambiguous)
- [x] Fixed latent NameError (`log` unbound in proforma_invoice_link_db.py — also affected PR-2 block helpers)
- [x] 16 real-builder tests; 208-test regression + smoke 63; full reviewer battery (3 implementation bugs + 1 latent NameError caught & fixed)
- [x] No valuation / CIF / PZ / accounting / booking / wFirma-API change
- [ ] Deploy PR-2 + PR-3 to production (C:\PZ) via 7-agent gate + operator backfill of SHIPMENT_9158478722 — PENDING (operator-run)

### Prior task (COMPLETE) — PR-2 Contractor-at-Birth Projection

- PR #673 squash-merged at `f652de0`. Carried `shipment_documents.client_contractor_id` through sales → draft → reservation; visible blocked draft-birth records; idempotent backfill. FEATURE_SCORECARD Row #1.


---

## History (most recent first)

- 2026-06-21 — Row #7 COMPLETE: PR #716 draft (DHL AWB on V2 overview page). 3 JSX edits, 5 contract tests, smoke 63/63. Scorecard pending.
- 2026-06-21 — Task #4 COMPLETE: PR #687 updated (intake diagnostics, IntakeDiagnosticsCard, T12–T15)
- 2026-06-21 — Task #3 COMPLETE: PR #687 updated (proforma draft blocker visibility in V2 proforma tab)
- 2026-06-21 — Task #2 COMPLETE: PR #687 updated (DHL clearance pipeline diagnostics in V2 DHL tab)
- 2026-06-21 — Task #1 COMPLETE: PR #687 draft (proforma readiness display in V2 proforma tab)

- 2026-06-20 — /feature command created at .claude/commands/feature.md.

- 2026-06-21 — PR #675 squash-merged at `7b94a73`: PR-3 Dropdown selection wins.
  Scorecard `2026-06-21-pr3-dropdown-selection-authority.md` (6 agents, 5 EXEMPLARY / 1 ACCEPTABLE).
  Battery caught 3 implementation bugs + 1 latent NameError, all fixed pre-merge. BACKLOG B-009..B-011 filed.

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

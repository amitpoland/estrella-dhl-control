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

- **Task:** End-to-end batch reconciliation post-PZ — AWB 9158478722, batch `SHIPMENT_9158478722_2026-06_924c4e59`, PZ 5/6/2026 (doc 189897571). Verify PZ + sales packing + drafts #34–#43 readiness/reservation; backfill `design_product_mapping`; over-bill check; advisory-vs-blocker per (operator-asserted) Lesson N. **No PZ/product/proforma/reservation/wFirma/fiscal writes.**
- **Started:** 2026-06-23
- **Status:** BLOCKED-HOLD (local half COMPLETE; live half needs prod)
- **HOLD reason (if BLOCKED-HOLD):** Missing access (condition #2) — drafts #34–#43, `pz_rows.json`, `audit.json`, `design_product_mapping` live only in prod `C:\PZ`. Re-confirmed: shipment absent from all local DBs; `localhost:47213`→000; public `pz.estrellajewels.eu`→401 (no token, not hunting for one). Live readiness GETs + over-bill (needs pz_rows qty authority) + PZ-exists-in-wFirma can't run here.
- **Branch / worktree:** `chore/governance-pr719-observe` (Mac) — analysis artifacts only, no code edits.
- **Notes (KEY mechanism):** `GET /draft/{id}/readiness` SELF-POPULATES `design_product_mapping` (write-on-read, routes_proforma.py:5691 docstring) → steps 4+6 are ONE action; operator's "parse → re-run → mapping self-heals" theory CONFIRMED in code. Drafts bind 1:1 to invoices by client header (all evidence-verified): 34→299 Clear-Diamonds, 35→296 OMARA, 36→294 Dream Rings, 37→293 Panaks, 38→292 Diamond Point, 39→300 Sagar Shah, 40→298 SAS Mayuri, 41→291 Magdalena Kumar/Railing 2, 42→290 MB Adagia, 43→297 Longvé/Signium. 80 real SKU lines, 66 distinct designs, 3 PND advisories (inv299 sr3/7/8 PO LM). PZ arithmetic internally consistent (21×409.03=8589.63; net×1.23=gross; VAT 23%). Bridge: `design_product_bridge.populate_from_packing`; mapping DB=`reservation_queue.db`. Lesson N NOT in CLAUDE.md (stops at M) — flagged for codification. Prod runner: `.claude/campaigns/sales-packing-290-300-reconcile/prod_reconcile.py` (read-only, 10 readiness GETs + pz_rows over-bill). Artifacts in that campaign's `artifacts/`.

### Earlier sub-task (COMPLETE) — Draft #34 sales-packing parse

- 10/10 packing lists parsed; same campaign artifacts (packing_authority.json, reconciliation_input.json). Superseded by this end-to-end task.

### Prior task — DHL DSK/cesja auto-forward VERIFICATION (BLOCKED-HOLD, same AWB)

- Determine failure path (A poll-latency / B ingest-classify / C SMTP-gate / D monitor-not-running). Same access boundary: prod state on `C:\PZ`. Awaiting Kaushal to run `.claude/campaigns/dhl-agency-forward-verify/collect-evidence.ps1`. Shipment operationally UNBLOCKED (manual notify-to-proceed msg `1782120964135130200`, delivered). Send gate = `_smtp_configured()`+`ENV=prod` (`email_sender.py:517`); triggers `active_shipment_monitor.py:1702-1735`.

### Prior task (PR open) — Proforma draft authority UI (V1)

- `feat/proforma-authority-ui` @ `C:\PZ-pf-ui` (base origin/main `dc58ad4`). Display-only customer-authority summary + canonical product-description + blocked draft-birth records; V2 inspected/reported not switched. GATE-6 = JSX compiles (offline Babel) + 46 structural tests; browser verify deferred to deploy. reviewer-challenge + frontend-flow CLEAR. BACKLOG B-012..B-014.

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

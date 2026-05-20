# PROJECT_STATE.md

Source of truth for the current project execution state. Read this file at the start of every new session before any task work begins.

Owned by `flow-context-keeper`. Do not edit by hand outside of an emergency. Last updated by the agent on initialisation, 2026-05-13.

**Last-run-at:** 2026-05-20T(campaign16a-MERGED)Z. Origin/main HEAD: 399363b (C16A squash-merge SHA). C13E + C14A + C15A + C16A all on main. PENDING Windows deploys: (1) C13E — `windows_deploy_c13e_backend.ps1` — PZService restart required; (2) C14A+C15A+C16A — `windows_deploy_c16a_static.ps1` — no restart, one robocopy pass. Deploy order: C13E first (restart), then C14A+C15A+C16A together (no restart).

---

# FACTS

## Campaign 16A — Lapis UX Truth Redesign (2026-05-20)

- **PR**: #240 — MERGED 2026-05-20 — squash SHA `399363b` on main
- **Files changed**: `service/app/static/shipment-detail.html`, `service/tests/test_c16a_lapis_ux_truth.py`, `service/tests/test_c13d_transit_aware_inventory_ui.py` (test updated to match C16A expression), `.claude/manifests/windows_deploy_c16a_static.ps1`
- **No backend files touched** — frontend+governance only
- **Test results**: 124/124 PASS (C16A 32 + C15A 20 + C14A 28 + C13D 34 + C13E 10)
- **Deploy delta**: 1 static file — `shipment-detail.html`; **NO PZService restart required**
- **Windows deploy**: `windows_deploy_c16a_static.ps1` ready at `.claude/manifests/`

### Changes
- **Location column**: transit rows now show `In transit` instead of blank `—`
- **Qty counter**: summary uses `invState.counts.PURCHASE_TRANSIT` (46) for transit, not packing-line count (30)
- **CM datalist**: both link-packing panels wire `<datalist>` from `clientList` (Customer Master) to client name inputs
- **OperatorWorkflowCard**: loads `/api/v1/customer-master/` in parallel; section 4 shows pay method, PF/INV series, terms, ship-to for resolved customers
- **Stale text**: "contact your admin" removed from customersBody → wFirma Contractors instruction

---

## Campaign 15A — Post-C13 operator friction reduction (2026-05-20)

- **PR**: #239 — `feat/c15a-post-c13-closure` SHA `5e25e82` — OPEN, awaiting merge
- **Files changed**: `service/app/static/shipment-detail.html`, `.gitignore`, `service/tests/test_c15a_post_c13_closure.py`, `.claude/manifests/windows_deploy_c15a_static.ps1`
- **No backend files touched** — frontend+governance only
- **No DB schema change** — no write paths added
- **Test results**: 20/20 C15A tests PASS; 107/107 combined C13D+C14A+C13E+C15A PASS
- **Deploy delta**: 1 static file — `shipment-detail.html`; **NO PZService restart required**

### Changes
- `customer-flag-off`: actionable wFirma Contractors instruction (Dream Ring / Panakas)
- `contractor-create-new-btn`: label + tooltip tell operator to create in wFirma first
- `link-packing panels`: amber "Needs client" highlight for unassigned rows (e.g. INV-178)
- `ProformaDraftPanel`: accurate empty subtitle mentioning link-as-sales path
- `.gitignore`: `validate_deploy_*.sh` pattern added

---

## Campaign 14A — Lapis Commercial Workflow Truth Correction (2026-05-20)

- **PR**: #237 — MERGED to main SHA `06ec8ea` on 2026-05-20
- **Deploy delta**: 1 static file — `shipment-detail.html`; **NO PZService restart required**
- **Deploy pending**: run `.claude/manifests/windows_deploy_c14a_static.ps1`

---

## Campaign 13E — Projection-by-Quantity correction (2026-05-20)

- **PR**: #238 — MERGED to main SHA `358f215` on 2026-05-20 — **awaiting Windows deploy**
- **Files changed**: `service/app/services/inventory_state_engine.py` only (+ 2 test files)
- **No frontend files touched** — backend-only
- **No DB schema change** — zero-write guarantee preserved
- **Test results**: 15 new C13E tests PASS; 30/30 projection suite; 80/80 inventory suite
- **Deploy delta**: 1 backend file — `inventory_state_engine.py`; **PZService restart required**

### Root cause
`derive_purchase_transit_projection` emitted 1 synthetic row per packing_line (COUNT semantics).
Lapis has 30 packing lines with SUM(quantity)=46 → projection showed 30, not 46.

### Fix
- Added `_coerce_qty()` helper: None/invalid/≤0 → 1; float strings → int(float())
- Loop now emits N rows per packing line where N = coerce(quantity)
- qty=1: original scan_code unchanged; qty>1: scan_code#1 … scan_code#N

### Expected Lapis result after deploy
`GET /api/v1/inventory/state/SHIPMENT_4218922912_2026-05_9040dd39`
→ `total=46, counts.PURCHASE_TRANSIT=46, synthetic=true, source="audit.tracking"`

### Supersession of C13A test assertions
4 C13A projection tests updated: fixture line[2] had qty=2, so C13E correctly expands to 4 rows.
All original C13A behaviours (terminal suppression, real rows win, zero-write) unchanged.

---

## Campaign 14A — Lapis Commercial Workflow Truth Correction (2026-05-20)

- **PR**: #237 — `feat/c14a-lapis-workflow-truth` SHA `acf7be8` — OPEN, awaiting merge
- **Branch**: `feat/c14a-lapis-workflow-truth`
- **Files changed**: `service/app/static/shipment-detail.html` (only) + 2 test files
- **No backend files touched** — frontend-only
- **Test results**: 28/28 C14A tests PASS; 57/57 combined C13D+C14A PASS
- **Deploy delta**: 1 static file — `shipment-detail.html` (C14A supersedes C13D version)
- **Production deploy**: PENDING — run `.claude/manifests/windows_deploy_c14a_static.ps1` after merge

### Behaviour added / corrected

- `loadProformaDocument`: detects `PROFORMA_NOT_LINKED` error code → stores `error:'not_linked'` in state; suppresses toast; renders informational blue panel "No linked proforma yet"
- `STATUS_BADGE`: `missing_scan` → amber "Pending arrival" label (replaces C13D per-line remap to 'in_transit')
- `sales-transit-context-banner`: blue banner above per-client groups when `isTransit` — explicitly "Inventory location: In transit" (not a sales status)
- `sales-qty-reconciliation`: inside transit banner — transit pieces vs invoice units with PRS/pair note
- `orphan-assignment-cta`: informational note at bottom of Sales section pointing to "Link packing files" panel

### C13D supersession note
C14A intentionally removes C13D's per-line `missing_scan → in_transit` Sales tab remap.
C13D Sales tab anchor comment updated: `"C13D: same transit detection..."` → `"C14A: transit detection"`.
All C13D Warehouse tab and Dashboard behaviour is UNCHANGED.

### Target batch
`SHIPMENT_4218922912_2026-05_9040dd39` (Lapis, DHL transit, 30 PURCHASE_TRANSIT, 46 invoice units)

### Safety invariants UNCHANGED
- `WFIRMA_CREATE_PZ_ALLOWED` — untouched
- `cleanGate` still checks `stuck.length`, `invalid.length`, `orphans.length`
- No backend routes, services, DB schema, DHL/wFirma flags touched
- All new panels read-only (no API calls, no buttons, no onClick in CTA)

---

## Campaign 13D — Transit-Aware Inventory Semantics (2026-05-20)

- **Merge commit**: `92acdc2` — PR #236 merged 2026-05-20 via squash
- **Branch**: `feat/c13d-transit-aware-inventory-ui`
- **Files changed**: `service/app/static/shipment-detail.html` + `service/app/static/dashboard.html` + `service/tests/test_c13d_transit_aware_inventory_ui.py`
- **No backend files touched** — frontend-only
- **Test results**: 29/29 C13D tests PASS
- **Deploy delta**: 2 static files — `shipment-detail.html` + `dashboard.html` (copy to `C:\PZ\app\static\`, no service restart)
- **Production deploy**: PENDING — must be included in next Windows static-file deploy (alongside C13B backend files)

### Behaviour added

- `isTransit = invState.synthetic === true && PURCHASE_TRANSIT count > 0` — Warehouse tab
- `displayMissing = isTransit ? [] : missing` — transit items not counted as gaps; `cleanGate` uses `displayMissing.length`
- `lifecycleState` returns `'in_transit'` (blue) before `'awaiting'` for synthetic transit batches
- Missing scans section shows blue informational note instead of red table when `isTransit`
- Sales tab: `statusBadge` remaps `'missing_scan' → 'in_transit'` when `isTransit`; summary counter shows `'In transit:'` (blue)
- Dashboard piece drawer: `PURCHASE_TRANSIT → 'In transit'` via `stLabel`; `WAREHOUSE_LIFECYCLE_LABEL` + `xbatchLifecycleTone` include `in_transit` (blue)

### Safety invariants UNCHANGED
- `WFIRMA_CREATE_PZ_ALLOWED=False` — untouched
- `cleanGate` still checks `stuck.length`, `invalid.length`, `orphans.length` — no fake ready state
- No backend routes, services, DB schema, DHL/wFirma flags touched
- Transit note is read-only (no Btn, no button, no onClick)

### Pre-existing failures (NOT caused by C13D — SCHEDULED)
- `test_dashboard_warehouse_lifecycle_badge.py`: 20/40 fail — tests look for `loadWarehouseAudit`/`warehouseAudit` in dashboard.html (those are in shipment-detail.html); test file targets wrong HTML file
- `test_dashboard_inventory_piece_drawer.py`: stale POST/PUT/testid expectations — pre-existing

### Scorecard
- `.claude/memory/scorecards/2026-05-20-c13d-transit-aware-inventory.md` (pending write)

## Campaign 13B — Parser body-cell fallback for client name extraction (2026-05-20)

- **Merge commit**: `ca7de3c` — PR #235 merged 2026-05-20
- **Branch**: `feat/c13b-parser-body-fallback` — commit `a4a438e`
- **Test results**: 50/50 C13B tests PASS; 73/73 C12+C13A+C13B combined; 4 pre-existing failures in test_proforma_pricing_source.py — SCHEDULED
- **Deploy delta**: 2 runtime files — `routes_packing.py` + `invoice_packing_extractor.py`
- **Deploy manifest**: `.claude/manifests/deploy_delta_pr235.md`
- **Deploy script**: `.claude/manifests/windows_deploy_pr235.ps1` — ready to run on Windows
- **Production deploy**: PENDING operator execution (no remote Mac→Windows access)

### Architecture

- **Upload path** (`upload_packing_list`): After `process_packing_upload()`, new C13B block runs `_guess_client_from_filename(safe_name)` → if empty, `_guess_client_from_preamble(str(dest_path))`; result injected into `parser_diagnostic["client_name_resolution"]` dict and returned in response as `suggested_client_name` + `client_name_resolution`
- **Reprocess path**: Pass 5 added (after existing Pass 4 filename hint) — calls `_guess_client_from_preamble(str(file_path))` when `preserved_client_name` still empty; swallows all errors
- **`_new_diagnostic()`** in `invoice_packing_extractor.py`: new key `"client_name_resolution": None` as schema placeholder
- **Priority chain**: `"filename"` > `"preamble"` > `"none"` — preamble is ONLY called when filename returns ""

### Key orphan case handled

- `EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx` — ends with `-Client.xlsx` (no name after keyword)
- `_guess_client_from_filename` → `""` (confirmed by test)
- `_guess_client_from_preamble` scans top-12 rows for `Client:` / `Consignee:` / `Buyer:` / `Ship To:` label
- If Excel body contains `Client: Diamond Point` → resolved client = "Diamond Point", method = "preamble"

### Safety invariants UNCHANGED

- No DB writes added; read-only parser change only
- No inventory lifecycle touched
- No orphan Assign Client UI touched
- No PZ creation or wFirma write flags
- `_guard_wfirma_export`, `WFIRMA_CREATE_PZ_ALLOWED=False`, `transition()` — all untouched

## Campaign 13A — Read-only PURCHASE_TRANSIT projection (2026-05-20)

- **Merge commit**: `aaa898b` — PR #234 merged 2026-05-20T01:02:01Z
- **Test results**: 15/15 C13A tests PASS; 244/244 make verify PASS on merged main
- **Deploy delta**: 2 runtime files — `inventory_state_engine.py` + `inventory_batch_state.py`
- **Deploy manifest**: `.claude/manifests/deploy_delta_pr234.md`

### Architecture

- `derive_purchase_transit_projection(batch_id, audit, packing_lines)` — NEW read-only pure function in `inventory_state_engine.py`; no DB connection; returns synthetic PURCHASE_TRANSIT rows when `clearance_status` ∈ `_LIFECYCLE_TRANSIT_STATUSES` AND not in `_LIFECYCLE_TERMINAL_STATUSES`
- `inventory_batch_state.get_batch_state()` — extended with `synthetic: bool` + `source: str`; projection called ONLY when `real_total == 0`; real rows always win
- **Zero DB writes** — confirmed by source-grep test (`test_projector_source_contains_no_write_keywords` PASS)
- Terminal statuses (`closed`, `pz_generated`, `delivered_and_received`, `archived`, `cancelled`) suppress projection

### Safety invariants UNCHANGED
- `transition()` in `inventory_state_engine.py` — untouched
- `_guard_wfirma_export` in `routes_wfirma.py` — untouched
- `WFIRMA_CREATE_PZ_ALLOWED=False` — untouched
- DHL orchestrator flags — untouched
- DB schema — no migrations

### Smoke check (post-Windows-deploy)
```
GET /api/v1/inventory/state/SHIPMENT_4218922912_2026-05_9040dd39
Expected: synthetic=true, source="audit.tracking", total=30, counts.PURCHASE_TRANSIT=30
```

## Campaign 12 — Proforma Preview Gate Separation (2026-05-20)

- **Feature commit**: `3f61fd0` on `feat/c12-preview-gate-separation`
- **PR #233**: OPEN + MERGEABLE — `feat(C12): Proforma preview gate separation — export gate != preview gate`
- **Test results**: 8/8 C12 tests PASS; 244/244 make verify PASS (branch)
- **Deploy delta**: 1 runtime file — `service/app/api/routes_proforma.py`
- **Deploy manifest**: `.claude/manifests/deploy_delta_pr233.md` (1-file deploy, smoke checks included)
- **Scorecard**: `.claude/memory/scorecards/2026-05-20-preview-gate-separation-campaign12.md`

### Architecture changes in `3f61fd0`

- `_check_proforma_export_prerequisites()` — NEW function; carries `wfirma_pz_doc_id` check that was incorrectly inside the preview path; called ONLY for create/export
- `_derive_batch_lifecycle()` — NEW function; returns `DHL_TRANSIT` when `inventory_state` rows=0 AND `clearance_status` in `_LIFECYCLE_TRANSIT_STATUSES` frozenset
- `_check_warehouse_readiness()` — MODIFIED; removed check #1 (`wfirma_pz_doc_id`); now only checks product resolution + price conflicts in pz_rows.json
- `_build_preview()` response extended: `can_preview`, `export_blockers`, `warehouse_blockers`, `batch_lifecycle` fields; `ready = not blocking_reasons and not export_blockers`
- `_stock_status()` closure: returns `"dhl_transit"` for DHL_TRANSIT batches; `"dhl_transit"` added to `_ELIGIBLE_LABELS` → `stock_ok=True`, no blocking reason
- **Safety invariants UNCHANGED**: `_guard_wfirma_export` (routes_wfirma.py:137-156), `WFIRMA_CREATE_PZ_ALLOWED=False`

### Target batch enabled by C12

- `SHIPMENT_4218922912_2026-05_9040dd39` (AWB 4218922912, `clearance_status=dsk_generated`)
- 4 invoices (177/178/179/180), 0 inventory_state rows, 30 scan_codes from parser
- Diamond Point + Verhoeven previews NOW UNBLOCKED (DHL_TRANSIT lifecycle derived)
- Dream Ring + Panakas: STILL BLOCKED for their own clients only (no wFirma contractor mapping)
- Invoice 178 orphan (JR08007 1pc): provenance retained; operator must assign client

### Operator-dependent items for Lapis batch (not code-blocked — require human action)

1. ZC429 upload: waiting on customs agency `roman@acspedycja.pl` — required for wFirma PZ export
2. Dream Ring wFirma contractor: operator must create in wFirma + add to Customer Master
3. Panakas wFirma contractor: operator must create in wFirma + add to Customer Master
4. Invoice 178 client assignment: operator decision (1 orphan packing line JR08007)
5. Warehouse scan-in 30 pieces: after goods arrive in Poland
6. Fracht + Ubezpieczenie wFirma service IDs: verify 13002743 + 13102217

### Pre-existing test failures (NOT caused by C12 — verified on main before C12)

- `service/tests/test_proforma_pricing_source.py`: 4 tests failing (parser unit tests)
- GATE 4 disposition: SCHEDULED (pre-existing, not C12 regression)

## Deploy Convergence Campaign 11 — Windows Deploy Script + Final Readiness (2026-05-19)

- **origin/main HEAD**: `cac4f84` — deploy script committed
- **Windows deploy script**: `.claude/manifests/windows_deploy_a20e5a2.ps1` — 11-step PowerShell, 10-file robocopy, backup+rollback, health checks, DHL corpus check
- **Script verified**: 10/10 profile checks PASS (port, service, python, paths, rollback, no /MIR, 10 files, tzdata, SHA, smoke checks)
- **Pre-deploy gate**: 475/475 tests pass, 7/7 Python files syntax-clean
- **Windows deploy**: OPERATOR MUST EXECUTE — no remote access from Mac dev
- **Post-deploy DHL**: script auto-checks `orchestrator_decisions.jsonl` count; if ≥50 lines + ≥10 distinct AWBs, P2 promotion threshold met (still requires Tejal sign-off)

## Master Convergence Campaign 10 — Full Deploy Readiness (2026-05-19)

- **origin/main HEAD**: `236094a` — 10-file Windows deploy delta fully addressed
- **Issue #229 RESOLVED** — `wfirma_pz_fullnumber` backported to `ProformaReadinessCard` in `dashboard.html`. `routes_dashboard.py` now returns `pz.wfirma_pz_fullnumber` from `wfirma_export`. `↻ Refresh Mapping` button added to Section 4 (canonical wFirma PZ number row). 13/13 `test_pz_canonical_mapping` pass; 372 baseline pass.
- **Stale orchestrator test fixed** — `test_dashboard_has_required_test_ids` → `test_dashboard_orchestrator_card_is_removed_not_present` (SHA `f2884c7`). 7/7 invariants pass.
- **Deploy manifest updated** — `.claude/manifests/deploy_delta_pr228.md` now 10-file delta (added `routes_dashboard.py`). Issue #229 RESOLVED in gate results. Smoke checks updated.
- **GATE 2: 0 open implementation PRs** — PRs #1 and #10 are archived stubs (REFERENCE_ONLY/old work).
- **GATE 4 item status**: All GATE 4 SCHEDULED items from prior campaigns now RESOLVED or in origin/main. No open GATE 4 salvage debt.
- **Test baseline**: 133/133 campaign tests, 372/372 deploy-gate baseline.

## Master Campaign — Unified Operational Convergence (2026-05-19)

- **Discovery**: Full system audit completed. DHL pipeline, commercial authority, contract normalization, deploy state, and Lapis shipment readiness all inspected.
- **INC-003 RESOLVED** — V1/V2/V3 Windows-local commits reconciled via PR #226 (`integ/merge-windows-local-7392be1`, merged 2026-05-19T12:22:28Z). `7392be1` is on origin/main. `local-commit-deploys.jsonl` reconciliation entry appended. `incident_registry.md` status updated to RESOLVED. Windows `git pull --ff-only origin main` is now safe.
- **PR #232 rebased** — `feat/commercial-draft-authority-ssot` cleanly rebased onto origin/main `5d8319d`. 2 commits, 5 files, 0 conflicts. Pushed and ready to merge. Test results: 232/232 pass.
- **Deploy manifest updated** — `.claude/manifests/deploy_delta_pr228.md` now covers 9-file delta for PR #228 + #231 + #232 combined. Pre-deploy step changed to `git pull --ff-only origin main` (safe per INC-003 resolution).
- **DHL pipeline state confirmed** (SHADOW-OBSERVING-REAL-TRAFFIC):
  - `dhl_orch_enabled=False` (default) — orchestrator NOT running on dev. Production state unknown without Windows access.
  - P2: `p2_shadow_mode=True`, `p2_live_enabled=False` — shadow infrastructure deployed, zero real dispatches observed on dev.
  - No `orchestrator_decisions.jsonl` exists on dev — all test data only.
  - **P2 live promotion: BLOCKED** — requires: 48h + 50 real dispatches + 10 distinct AWBs + Tejal sign-off. Zero corpus accumulated on dev.
- **Commercial authority confirmed** — 6 authority layers mapped, 3 conflicts documented in `authority-graph-commercial-draft.md`. All canonical paths pinned by 10 AG contract tests. No duplicate authority.
- **AWB contract normalization confirmed** — INC-005 RESOLVED (PR #231 merged). `shipment-detail.html` Build Reply Package now sends `awb` field. 11/11 contract tests pass.
- **"Lapis" shipment**: No trace in local codebase or dev storage. This is a real production shipment on Windows. Cannot inspect from Mac dev. Windows deploy (see manifest) is the prerequisite for operational readiness on live shipments.
- **GATE 2**: 1 open PR (#232). 2 deferred stubs (#10, #1) = implementation slot count 3/3.
- **Scorecards**: 3 outstanding scorecards added to repo (Campaign 4, Campaign 6, Campaign 9).

## Campaign 4 — Commercial Draft SSOT Refactor (2026-05-19)

- **PR #232 open** — `feat/commercial-draft-authority-ssot` — GATE 2: currently 1 open PR
- **Authority graph document created**: `service/docs/authority-graph-commercial-draft.md` — maps 6 authority layers (wfirma_customers, CustomerMaster, service_charges_db, commercial_profile, freight_resolver, shipping_addresses); documents 3 conflicts; defines hydration flow and future development rules
- **`freight_resolver.py` — PRODUCTION ROUTE EXCLUSION comment added** — no production API route imports this module; canonical production path is `pick_freight(cm, draft_currency)` from `customer_master.py`
- **`routes_proforma.py` — `_build_preview()` cross-validation** — `ship_to.cm_conflict` (non-blocking string, never in `blocking_reasons`) surfaces when `CustomerMaster.ship_to_contractor_id` ≠ `wfirma_customers.ship_to_wfirma_customer_id`; `cm_conflict` field NOT consumed by any UI (GATE 6 N/A — additive API field, zero UI blast radius)
- **10 authority-graph contract tests (AG-01..AG-10)** — `test_authority_graph_commercial_draft.py` — all 10 pass; guard canonical freight/insurance/ship_to authority paths in CI
- **Scorecard**: `.claude/memory/scorecards/2026-05-19-campaign4-commercial-draft-ssot.md` — EXEMPLARY: system-architect, testing-verification, git-workflow; ACCEPTABLE: all others; NEEDS-TUNING: none
- **GATE 4 item (GATE 6 N/A ruling)**: Observer flagged `cm_conflict` UI consumption check. Confirmed: zero references in `shipment-detail.html` / `dashboard.html`. Frontend ignores unknown API keys. GATE 6 N/A documented here — no display behavior to verify.
- **NOT done in this campaign** (intentional scope limits): sync `CustomerMaster.ship_to_contractor_id` → `wfirma_customers` (migration risk); remove CustomerMaster ship_to fields from UI (tests assert they exist for `onApplyCustomerDefaults`); fix test tool ship_to divergence (tool-only, not in CI)

## Campaign 9 — Commercial Completion (2026-05-19)

- **PR #228 merged** — SHA `24382c3` — Campaign 9: Warsaw date + payment method
  - `timezone_utils.py` created — `warsaw_today()` via `ZoneInfo("Europe/Warsaw")` + system-local fallback (NOT UTC)
  - `customer_master_db.py` — `preferred_payment_method TEXT` column added (additive migration)
  - `routes_customer_master.py` — `_ALLOWED_PAYMENT_METHODS` enum guard (422), blank→NULL coercion
  - `wfirma_client.py` — `ProformaRequest.date` + `ProformaRequest.payment_method` fields + XML emission
  - `routes_proforma.py` — `_date.today()` → `warsaw_today()`; payment method threaded
  - `dashboard.html` — payment method select (transfer/cash/card/compensation, no "other")
  - `requirements.txt` — `tzdata>=2024.1` added
  - 26 tests in `test_commercial_completion.py` — 26/26 PASS
- **GitHub issue #229** — pre-existing `test_pz_canonical_mapping` ×2 failures — GATE 4 SCHEDULED
- **Governance artifacts added**:
  - `.claude/deploy/windows_prod_v2.json` — reusable Windows deploy profile
  - `.claude/contracts/orchestration_router.md` — routing matrix + token rules
  - `.claude/contracts/gate_output_contract.md` — structured agent output schema
  - `.claude/memory/incident_registry.md` — INC-001 through INC-004
  - `.claude/manifests/deploy_delta_pr228.md` — 7-file deploy manifest
- **Scorecard**: `.claude/memory/scorecards/2026-05-19-campaign9-commercial-completion.md` — 194/245 (79.2%) ACCEPTABLE. EXEMPLARY: deploy_qa_reviewer (33/35), deploy_lead_coordinator (30/35).
- **Windows deploy PENDING** — 7 files + `pip install tzdata>=2024.1` + nssm restart; see `deploy_delta_pr228.md`
- **Lesson D INC-003 status: PENDING** — V1/V2/V3 reconciliation PR not yet filed; `local-commit-deploys.jsonl` entry `reconciliation_status: "PENDING"`
- **GATE 2: 0 open PRs** as of Campaign 9 close

## Current origin/main HEAD
- **2026-05-19** — `24382c3` PR #228 merged — Campaign 9 commercial completion — **origin/main HEAD**
- **2026-05-19** — `97672c1` Campaign 6 T2 — series bootstrap kill-switch + config flag — **origin/main HEAD (pushed 2026-05-19, Campaigns 4+5+6 now on origin/main)**
- **2026-05-19** — `820bd9a` Campaign 6 T3/T5/T6/T8/T9 — threading, atomicity, performance, governance
- **2026-05-19** — `62cb391` Campaign 6 T4 — commercial ownership: ProformaDraftPanel only in Sales tab
- ~~Local main is **12 commits ahead** of origin/main (`af80818`). Campaigns 4+5+6 not yet pushed.~~ — **RESOLVED 2026-05-19**: all 12 commits pushed directly to origin/main (repo uses direct-to-main flow, no feature branch). Full 7-agent deploy gate required before Windows pull.
- **2026-05-19** — `6023f8c` fix(governance): P2 flag correction — live=shadow=True+live_enabled=True; shadow=False+live=True is FORBIDDEN (ADR-018) — **prior**
- **2026-05-19** — `49da2f6` fix(config): Pydantic V2 deprecation cleanup — 82 warnings eliminated — **prior**
- **2026-05-19** — `302848f` fix(security): Lesson E ENV isolation + path traversal (#223, #224 closed) — **prior**
- **2026-05-19** — `6f57e2c` chore(deploy-prep): Windows reconciliation #222 merged — **prior**
- **2026-05-19** — `119e0fe` fix(safety): GATE 4 BLOCKER-1+ADV-1 (#225 merged) — routes_settings 422 guard + write_json_atomic
- **2026-05-19** — `f4736ab` chore(state): master campaign closure — Phases A-E complete
- **2026-05-19** — `c9175e6` fix(ui): inbox Open button dead-button guard (#209) — MERGED
- **2026-05-19** — `ca9a212` chore(state): Wave 2 closure — PROJECT_STATE frozen, PR #221 merged
- **2026-05-19** — `a64d295` chore(kernel): Wave 2 patch #4 batch — condense 8 retrieval-eligible CLAUDE.md sections (#221) — **WAVE 2 COMPLETE**
- **2026-05-18** — `f10e2a1` chore(governance): post-PR-219 contract-reference extraction (#220)
- **2026-05-18** — `9230a6e` chore(kernel): Wave 2 patch #3 — condense Engineering Lessons A–D into retrieval module (PR #219 merge)
  - Prior: `4f95ed3` Merge PR #211: feat(dhl-followup): delivered-shipment suppression guards
  - Prior: `ba8cf24` feat(dhl-followup): enqueue-time guard + idempotency key (PR #211 extension)
  - Prior: `572e2d0` chore: Wave 2 patch #2 — condense Section 9 Cowork into retrieval module
  - Prior: `4083d84` chore(kernel): Wave 2 patch #1 — condense CLAUDE.md shipment sections (PR #216 merge)

## Windows production local HEAD (NOT on origin/main)
- **2026-05-19** — `7392be1` [V1+V2+V3 Windows-local commits] ← **DEPLOYED TO PRODUCTION 2026-05-19T(campaign8)Z**
  - Base: `32d6a8f` (Campaign 6 origin/main HEAD, target of Campaign 8 7-agent gate)
  - V1/V2/V3 content: unknown from Mac side — operator applied 3 additional local commits on Windows during Campaign 8 session. Full SHA for 7392be1 not captured (7-char abbreviation only).
  - **Lesson D: PENDING RECONCILIATION** — V1/V2/V3 are Windows-local commits not on GitHub. JSONL audit entry appended to `local-commit-deploys.jsonl`. Reconciliation PR required before next `git pull --ff-only origin main`.
  - **Prior local HEAD (reconciled):** `4c797e4` — reconciled 2026-05-13T16:00Z via PR #77.

## Wave 1 closure facts (appended 2026-05-13T12:30Z)

- **Wave 1 deploy COMPLETE** — SHA `4c797e4` on Windows production as of 2026-05-13T10:43Z. Status: WAVE-1-COMPLETE-WAVE-2-AWAITING-FIRST-DISPATCH.
- **PZ regression on Windows: 160/160 PASS** — confirmed pre-deploy 2026-05-13.
- **Carrier suite on Windows: 366/366 PASS** — confirmed pre-deploy 2026-05-13.
- **Public health endpoint via Cloudflare: 200 OK** — `https://pz.estrellajewels.eu/api/v1/health` confirmed post-deploy.
- **Forgot-password SMTP path: VERIFIED** — email queued to Tejal `tejal@estrellajewels.com`, status=`sent` at 2026-05-13T11:54:13Z, 6-digit code present, `_debug_code` absent from response. PR #67 SMTP send verified functional against real provider (Zoho Mail).
- **Font fix `1b38ea0` Polish diacritics: VERIFIED** — `Ó ó ć ł ś ż` extracted from `POLISH_DESC_6049349806_20260507.pdf`; DejaVuSans.ttf 757,076 bytes confirmed on disk.
- **Attachment integrity guard: LIVE** on production as of SHA `4c797e4`. 0 `FAILED_ATTACHMENT_VALIDATION` queue entries since restart (expected — no outbound customs flow yet).
- **Wave 1 closure scorecard committed:** `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md`
- **Self-evaluation scorecard committed:** `.claude/memory/scorecards/self-eval-2026-05-13.md` (5th-run trigger; self-score 23/30 ACCEPTABLE, no degradation)
- **PR #74 merged — SHA `5ee390b`** — `fix(timeline): add EV_PACKING_LIST_EXTRACTED + EV_PACKING_MATCHED_TO_INVOICE constants`. Resolves active `AttributeError` on `POST /api/v1/packing/{batch_id}/upload` (2 confirmed hits in production stderr). Tests 62/62 pass. Synced to `C:\PZ\app\core\timeline.py` via robocopy. **Service restart pending (operator elevated shell required).**
- **SHA lineage verified (STEP 4):** `git log 0b4e381..4c797e4` → 1 commit (`4c797e4` only). `git merge-base 0b4e381 4c797e4` → `1b38ea0`. Conclusion: `4d595ca`, `80e3469`, `1b38ea0` are already on origin/main (reachable from `0b4e381`). Only `4c797e4` is unique to Windows local chain. PROJECT_STATE.md "4 local hotfix commits" description was partially incorrect — 3 of 4 were already on origin/main. **Governance note:** `4c797e4` was deployed without a GitHub PR (local-commit-only deploy). 7-agent gate was run inline; CLAUDE.md gate spirit was observed. See Lesson D candidate in Scorecard § 4.

## Merged PRs (this session window, latest first)
- **#209** 2026-05-19 — fix(ui): inbox Open button dead-button guard + remove dead NAV_TREE badge — merge SHA `c9175e6` — dashboard.html + 1 test file. Zero backend. Dead button guard, dead badge removal.
- **#221** 2026-05-19 — chore(kernel): Wave 2 patch #4 batch — condense 8 retrieval-eligible CLAUDE.md sections — merge SHA `a64d295` — governance/kernel only. 518→447 lines. All 15 invariants preserved. GATES/RULES/Lessons unchanged. Zero production code. **WAVE 2 COMPLETE.**
- **#220** 2026-05-18 — chore(governance): post-PR-219 contract-reference extraction — merge SHA `f10e2a1` — 4 contracts created, 7 governance files updated, .gitignore updated. Zero production code.
- **#219** 2026-05-18 — chore(kernel): Wave 2 patch #3 — condense Engineering Lessons A–D into retrieval module — merge SHA `9230a6e` — governance/kernel only. Squash-merged via GitHub REST API (local checkout blocked by unstaged governance normalization files). CLAUDE.md Engineering Lessons section condensed + Lesson E (background email automation 5 safety properties) added. Zero production code, zero test changes. Post-merge governance normalization (7 modified files + 4 contracts) committed as stabilization PR (see governance-contracts fact below).
- **#216** 2026-05-18T18:28Z — chore(kernel): Wave 2 patch #1 — condense CLAUDE.md shipment sections (pz-shipment retrieval) — merge SHA `4083d84` — governance/kernel only. Condensed 8 shipment-processing sections in CLAUDE.md from 329 to 143 lines (−186 lines). 18 enforcement invariants preserved verbatim (machine-verified 29/29 fragments). Removed content is explanatory/reference, present verbatim in `.claude/commands/pz-shipment.md`. Post-patch observation audit 2026-05-18: STABLE — no enforcement regression, no sequencing drift, three LOW-risk items all mitigated by L1 triggers.
- **#215** 2026-05-18T18:09Z — chore: fix skill discovery — move Wave 1A skills to .claude/commands/ — merge SHA `150b2c9` — rename-only, zero content changes, zero blast radius. Corrects `.claude/skills/` → `.claude/commands/` after runtime discovery.
- **#214** 2026-05-18T18:01Z — chore: skill-system Wave 1A — pz-shipment, cowork-integration, engineering-lessons — merge SHA `e294160` — governance/tooling only. Creates `.claude/commands/` retrieval modules. No CLAUDE.md changes. No production code.
- **#213** 2026-05-18T17:58Z — fix(p1): SyntheticEvent onChange repair + learning_traces flag writer — merge SHA `67a1af8` — P1 production defect batch. 6 Inp/Sel onChange sites fixed. learn_from_parse both return paths emit `flag`. 19 regression tests (test_p1_defect_batch.py).
- **#77** 2026-05-13T16:00Z — chore(reconcile): backfill 4c797e4 and add Lesson D lead coordinator backstop — merge SHA `1ee83e52` — governance-only, no production code changes. Closes 4c797e4 reconciliation. Adds lead coordinator LOCAL-COMMIT-ONLY backstop.
- **#76** 2026-05-13T14:30Z — chore(governance): codify Lesson D — LOCAL-COMMIT-ONLY deploys require disclosure + reconciliation — merge SHA `ba84ee3` — governance-only, no production code changes
- **#74** 2026-05-13T12:26Z — fix(timeline): add EV_PACKING_LIST_EXTRACTED + EV_PACKING_MATCHED_TO_INVOICE constants — merge SHA `5ee390b` — HOTFIX for active broken packing upload endpoint
- **#61** 2026-05-13T01:22:36Z — feat(admin-runtime-flags): override-flag predecessor-live enforcement (Issue #49) — merge SHA `9bfa282`
- **#57** 2026-05-13T01:04:10Z — feat(admin-runtime-flags): per-phase concurrency lock for combined-state validator (Issue #48) — merge SHA `854cd2a`
- **#52** 2026-05-13T00:48:12Z — chore(adr): salvage 10 ADR files from archived feature branch (Issue #44) — merge SHA `e20e8d8`
- **#50** 2026-05-13T00:26:33Z — feat(admin-runtime-flags): combined-state validator (ADR-018) for all P2/P3/P4/P5 phase pairs — merge SHA `8cd7188`
- **#47** 2026-05-12T23:54:24Z — chore(observation-layer): verify activation + record engineering lessons (Lessons A+B) — merge SHA `f08e794`
- **#46** 2026-05-12T23:26:44Z — feat(w5-p2): proactive customs dispatch — shadow + live under ADR-018 — merge SHA `996e9f0`
- **#43** 2026-05-12T23:07:45Z — chore(governance): ADR-018 amending ADR-010 for shadow-mode flag category — merge SHA `0ac4769`
- **#41** 2026-05-12T23:00:18Z — chore(governance): meta-agent observation layer — merge SHA `1af3559`
- **#37** 2026-05-12 — fix(proforma): move PZ recovery helper out of pure-builder module — merge SHA `2ac9a02`
- **#35** 2026-05-12 — chore(governance): add 6 MANDATORY GOVERNANCE GATES + restore gap-hunter/adr-historian — merge SHA `bb75c14`
- **#34** 2026-05-12 — docs(inventory): refresh docs 1-4 against on-main code (closes #27)
- **#32** 2026-05-12 — fix(returns-ui): state-gate corrections, DB_CONSTRAINT mapping, stale registry
- **#31** 2026-05-12 — chore(w5): commit P0-P5 planning artifacts + update program board
- **#24** 2026-05-12 — chore(governance): add W-9 inventory + W-10 sample-out S2 + W-11 reconciliation rows
- **#23** 2026-05-12 — feat(security): hybrid auth guard + close tracking_db /events* endpoints
- **#22** 2026-05-12 — feat(B.2): Returns lifecycle backend — RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER
- **#21** 2026-05-12 — feat(B.1): Stage 2 aggregator counts SAMPLE_OUT for samples tile
- **#20** 2026-05-12 — fix(ui): correct stale Inventory page copy after Move stock + Sample-out went live
- **#19** 2026-05-12 — feat(inventory): add unified piece timeline to drawer
- **#18** 2026-05-12 — ui(B.1): Sample-out drawer surfaces — pill, aging, mutation forms
- **#17** 2026-05-12 — feat(inventory): add Sample-out lifecycle transitions
- **#16** 2026-05-12 — feat(inventory): activate Move stock location action
- **#15** 2026-05-12 — feat(inventory): Group B — combined read-path integration

## Validator-hardening 3-PR sequence detail (2026-05-13)
- **PR #52 ADR salvage** — 10 ADR files restored from `archive/feature-dhl-label-workflow-planning-2026-05-13` tag onto main (ADR-001..005, 007..009, 011, 017). Total ADR count on main: **18** (was 8 before this PR). ADR README index now resolves all 18 links cleanly. Issue #44 closed at 2026-05-13T00:48:13Z.
- **PR #57 per-phase concurrency lock** — 4 `threading.Lock` instances created (one per phase: P2, P3, P4, P5) in the admin runtime-flags combined-state validator. 5-second `lock.acquire(timeout=5)` blocking semantics; on timeout returns 503 to caller. Production NSSM `PZService` runs single-process, so per-phase lock is correct for current deployment. Issue #48 closed at 2026-05-13T01:04:12Z.
- **PR #61 override-flag predecessor-live enforcement** — chained predecessor model wired into validator: P3 requires P2-live, P4 requires P3-live, P5 requires P4-live. Override flag (`--override-predecessor`) bypasses chain for phased rollout drills with explicit operator audit-log entry. Issue #49 closed at 2026-05-13T01:22:37Z.
- **Test state post-merge** — 204/204 PASS targeted across the 6-file admin/coordinator/state-engine/proactive-dispatch panel.
- **Sequencing model** — three-PR cascade (Option B) chosen over single atomic PR for clean per-step rollback + GATE 2 compliance (max 3 open). Each PR in/out before next opened.

## Open PRs
(Implementation slot: 2/3 used. #233 MERGED 2026-05-20T00:34:07Z, merge SHA 0f0d85c.)
- **#233** MERGED 2026-05-20 — merge SHA `0f0d85c` — `routes_proforma.py` on origin/main. Windows deploy pending (1-file robocopy). Manifest: `.claude/manifests/deploy_delta_pr233.md`.
- **#10** feat(inventory): Risk-3/4 button stubs — deferred per operator instruction; do not touch. **IMPL SLOT 1/3.**
- **#1** ui: align sidebar IA with Estrella Atlas design — historical Atlas branch (REFERENCE_ONLY pending). **IMPL SLOT 2/3.**

(Note: PR #33 ADR-010 conflict was resolved by PR #43 / #46 / #50 cascade — see merged list.)

## Closed issues (this session window, latest first)
- **#49** 2026-05-13T01:22:37Z — Admin runtime-flags: predecessor-live cross-system gap (closed by PR #61)
- **#48** 2026-05-13T01:04:12Z — Admin runtime-flags: per-phase concurrency lock (closed by PR #57)
- **#44** 2026-05-13T00:48:13Z — Salvage 10 ADR files from archived feature branch (closed by PR #52)
- **#27** 2026-05-12T22:35:26Z — Refresh inventory design docs 1-4 (closed by PR #34)

## Open issues (latest first; new follow-ups from 3-PR sequence at top)
- ~~**EV_PACKING_LIST_EXTRACTED**~~ — **RESOLVED 2026-05-13T12:26Z** by PR #74 (SHA `5ee390b`). Both `EV_PACKING_LIST_EXTRACTED` and `EV_PACKING_MATCHED_TO_INVOICE` added to `timeline.py`. Synced to production; **service restart pending** to pick up. GitHub issue #75 filed (audit trail only — RESOLVED status noted in issue body).
- **#60** Admin runtime-flags: GET /audit query endpoint for operator review (system-architect note from PR #58 review thread). Filed under GATE 4 disposition (override-polish bucket).
- **#59** Admin runtime-flags: request_id correlation for audit events (gap-hunter F8 from PR #58). GATE 4 disposition (override-polish bucket).
- **#58** Admin runtime-flags: cascade endpoint for multi-phase live promotion (gap-hunter F3 from PR #58). GATE 4 disposition (override-polish bucket).
- **#56** Admin runtime-flags: audit-log file-locking on Windows (gap-hunter F4 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#55** Admin runtime-flags: audit-write-failure observability (gap-hunter F3 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#54** Admin runtime-flags: write-ordering durability (gap-hunter F2 from PR #53). GATE 4 disposition (lock-hardening bucket).
- **#53** Admin runtime-flags: cross-worker safety hardening (gap-hunter F1 from PR #53) — multi-worker hardening blocker; tracks the path off single-process NSSM if architecture shifts. GATE 4 disposition (lock-hardening bucket).
- **#51** ADR drift reconciliation: successor ADRs needed for 8 salvaged ADRs (gap-hunter F1-F11 from PR #51) — blocks downstream ADR-drift cleanup until reconciled. GATE 4 disposition.
- **#45** P2 follow-ups: concurrency lock, silent state-skew logging, retry semantics, AWB subject assertion. (Concurrency lock subsumed by Issue #48 close via PR #57.)
- **#42** ADR-018 follow-ups: P5 3-flag truth table, kill-switch category, admin validator, transitive DORMANT.
- **#40** Meta-agent layer: 5 follow-up gaps from gap-hunter review of observation-layer PR.
- **#39** Defer agent-prompt-refiner and pattern-historian until observation baseline established.
- **#38** P2-P5 phase preconditions: 5 gap-hunter findings on PR #33 — SCHEDULED per phase.
- **#36** Governance gates refinement — wording + coverage amendments from agent review of PR #35.
- **#30** Refresh inventory design docs 1-4 against current main before next inventory feature (predates #27 — likely closeable).
- **#29** Sanitize INVALID_EVIDENCE detail before surfacing API errors.
- **#28** Test depth — single-field evidence-gate negatives + return replay coverage.
- **#26** INVALID_EVIDENCE detail sanitization — template-format raw exception strings.
- **#25** Test depth — single-field evidence-gate negatives + replay test for return-from-producer.

## Active branches (per GATE 3 status designation)

| Branch | Status | Note |
|---|---|---|
| `chore/dhl-selfclearance-p0-foundation` | ACTIVE → eligible-for-archive | PR #33 superseded by PR #43/#46/#50 cascade |
| `chore/admin-runtime-flags-combined-state-validator` | ACTIVE → eligible-for-archive | PR #50 merged |
| `chore/admin-runtime-flags-per-phase-lock` | ACTIVE → eligible-for-archive | PR #57 merged |
| `chore/admin-runtime-flags-predecessor-override` | ACTIVE → eligible-for-archive | PR #61 merged |
| `chore/adr-salvage-from-archived-feature-branch` | ACTIVE → eligible-for-archive | PR #52 merged |
| `chore/observation-layer-verification-and-lessons` | ACTIVE → eligible-for-archive | PR #47 merged |
| `feature/dhl-label-workflow-planning` | REFERENCE_ONLY | salvage-audit verdict 2026-05-13: FULL ABANDON; archive tag now exists (used as source for PR #52 salvage) |
| `feat/inventory-risk34-stubs` | ACTIVE (deferred) | Risk-3/4 stubs — operator instruction: do not touch |
| `feat/doc-1-v2-allocation-ledger` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-2-button-registry` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-3-data-source-mapping` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `feat/doc-4-failure-modes` | ACTIVE → eligible-for-archive | superseded by PR #34 |
| `claude/zealous-johnson-6d6d34` | ACTIVE | UI sidebar IA — PR #1 |
| `chore/windows-deploy-prep-2026-05-19` | ACTIVE | PR #222 open — Windows reconciliation docs |
| `archive/may9-stale-main` | ARCHIVED | pre-existing archive |
| `archive/feature-dhl-label-workflow-planning-2026-05-13` | ARCHIVED (tag) | salvage-source for PR #52 |

## Archive tags
- `archive/may9-stale-main` (pre-existing; predates this session)
- `archive/feature-dhl-label-workflow-planning-2026-05-13` — created prior to PR #52 ADR salvage; preserves the FULL-ABANDON branch as immutable reference

## Deploy smoke results 2026-05-13 (SHA 4c797e4)

| Check | Result | Detail |
|---|---|---|
| PZService state | PASS | STATE 4 RUNNING, process 8756 |
| Local health | PASS | 200 OK `{"status":"ok","engine":"ok","environment":"prod"}` |
| Public health | PASS | 200 OK `https://pz.estrellajewels.eu/api/v1/health` |
| Carrier gate | PASS | `pending` (unchanged — no live flags touched) |
| PZ regression | PASS | 160/160 |
| Carrier suite | PASS | 366/366 |
| Attachment integrity tests | PASS | 12/12 |
| `FAILED_ATTACHMENT_VALIDATION` queue entries | PASS | 0 — guard live, no false fires |
| Outbound customs emails since restart | PASS | 0 — none sent |
| Forgot-password smoke (tejal@estrellajewels.com) | PASS | 200 OK, `_debug_code` absent from HTTP response AND queue body, 6-digit code in body, status=`sent` at 2026-05-13T11:54:13Z |
| PDF Polish diacritics | PASS | `Ó ó ć ł ś ż` extracted from `POLISH_DESC_6049349806_20260507.pdf`; DejaVuSans.ttf 757,076 bytes confirmed on disk |
| Pre-existing log anomaly | KNOWN | `AttributeError: module 'app.core.timeline' has no attribute 'EV_PACKING_LIST_EXTRACTED'` in `routes_packing.py:392` — NOT introduced by this deploy; tracked as follow-up |

## Shadow windows currently active
- **W-5 P2 proactive customs dispatch** — shadow window opened on PR #46 merge (2026-05-12T23:26:44Z). Combined-state validator (ADR-018) now enforced per PR #50/#57/#61. Expected end: ≥48h of real DHL dispatch volume per master plan §4.3 → eligible for live promotion no earlier than 2026-05-14T23:26:44Z, gated on shadow-classification corpus + Tejal sign-off.
- **Attachment integrity guard shadow observation** — guard is LIVE on Windows prod as of `4c797e4`. Status: `AWAITING-FIRST-REAL-AWB`. Shadow-observing-real-traffic flag must NOT be set until `active_shipment_monitor` fires its first real sweep and an AWB enters eligibility filter. No customs emails queued since restart. Operator must confirm first AWB timestamp to upgrade status.

## Deployment status per machine
- **Mac (dev)** — current origin/main head `97672c1` (Campaign 6, pushed 2026-05-19).
- **Windows (prod, NSSM `PZService` at `C:\PZ`, `https://pz.estrellajewels.eu`)** — **CAMPAIGN-8-DEPLOY-COMPLETE**
  - **Campaign 8 deploy SHA: `7392be1`** (32d6a8f + V1/V2/V3 Windows-local, 2026-05-19). 321-commit catch-up from `4c797e4` → `32d6a8f` (origin/main Campaign 6 HEAD) + 3 additional Windows-local commits.
  - PZService: RUNNING (operator confirmed post-restart)
  - Public health: 200 OK `https://pz.estrellajewels.eu/api/v1/health` — body contains `"ok"` and `"prod"`
  - Carrier gate: `{"carrier_api_status":"pending","carrier_plt_status":"pending"}` — PENDING (no live flags touched)
  - Invoice gate: BLOCKED — `WFIRMA_CREATE_INVOICE_ALLOWED=false` confirmed live on `POST /api/v1/proforma/to-invoice/test-batch/test-client`
  - New routes from Campaign 6 delta: MOUNTED — `/api/v1/designs/` 200✓, `/api/v1/hs-codes/` 200✓, `/api/v1/carriers-config/` 200✓, `/api/v1/vat-config/` 200✓
  - Shadow status: `SHADOW-OBSERVING-REAL-TRAFFIC` — infrastructure verified; awaiting first real outbound customs email
  - Lesson D: V1/V2/V3 local commits pending reconciliation PR (JSONL entry appended 2026-05-19)

## Campaign 8 deploy smoke results (2026-05-19, SHA 7392be1 base 32d6a8f)

| Check | Result | Detail |
|---|---|---|
| Public health | PASS | 200 OK `https://pz.estrellajewels.eu/api/v1/health`, body contains `"ok"` and `"prod"` |
| Carrier gate | PASS | `carrier_api_status: pending` — unchanged |
| `/api/v1/designs/` | PASS | 200 OK — new route from Campaign 6 delta, confirms 32d6a8f deployed |
| `/api/v1/hs-codes/` | PASS | 200 OK — new route confirmed |
| `/api/v1/carriers-config/` | PASS | 200 OK — new route confirmed |
| `/api/v1/vat-config/` | PASS | 200 OK — new route confirmed |
| `/api/v1/customer-master/` | PASS | 200 OK |
| `/api/v1/wfirma/capabilities` | PASS | 200 OK |
| Invoice gate (POST) | PASS | `{"ok":false,"status":"blocked","blocking_reasons":["WFIRMA_CREATE_INVOICE_ALLOWED=false"]}` |
| PZ regression (Mac) | PASS | 244/244 (baseline 160) |
| Carrier suite (Mac) | PASS | 381 passed (baseline 366) |
| Cloudflare cache | PASS | `cf-cache-status: DYNAMIC` — no stale cache |

## Post-deploy runtime probes (locked 2026-05-19, all future deploys)

Operator locked these 3 additional probes for every future deploy validation phase:
1. `Invoke-WebRequest http://127.0.0.1:47213/api/v1/proforma/service-products` — confirms router mount + import graph health
2. `pip show xlrd` (post-install, pre-restart) — dependency presence check
3. `Get-Process python | Select Id,CPU,WS,StartTime` (post-restart) — orphan / restart-loop check

## Registry
- **2026-05-13** — Project registry healthy with 15 project agents at `.claude/agents/` (includes `gap-hunter`, `adr-historian`, `agent-performance-observer`, `flow-context-keeper`). Global registry at `~/.claude/agents/` has 54 agents. Total reachable agents in session: 79 (incl. plugin + built-in). No naming collisions.
- **2026-05-18** — Project retrieval modules added to `.claude/commands/` (Wave 1A, PRs #214+#215):
  - `pz-shipment` — PZ shipment workflow, financial rules, verification semantics, Cliq posting formats, WorkDrive flow
  - `cowork-integration` — Cowork→PZ→SMTP architecture, result processor, action runner, email drafting rules
  - `engineering-lessons` — Lessons A–D (test stubs, agent registry refresh, scorecard writes, LOCAL-COMMIT-ONLY deploys)
  - All 3 confirmed invocable via `Skill()` tool in session post-commit. Runtime discovery: `.claude/skills/` is inert; `.claude/commands/` is the active project retrieval surface.

## Governance contracts extracted (appended 2026-05-18, post-PR-219)

4 governance contracts created in `.claude/contracts/` as single-source-of-truth for volatile shared rules. These replace inline duplicated content across 7 deploy-governance files:

| Contract | What it owns | Files that now reference it |
|---|---|---|
| `forbidden-paths.md` | 10 blocked path patterns (merged from 6 in git_diff + 5 in persistence) | `deploy_git_diff_reviewer.md`, `deploy_persistence_storage_reviewer.md`, `deploy_release_manager.md` |
| `test-baseline.md` | PZ regression = 160, Carrier suite = 366 + update protocol | `deploy_qa_reviewer.md`, `deploy_lead_coordinator.md`, `deploy.md` |
| `local-commit-policy.md` | LOCAL-COMMIT-ONLY detection, disclosure header (4 fields), acknowledgment, audit record format | `deploy_lead_coordinator.md`, `deploy_release_manager.md` |
| `governance-precedence.md` | Explicit precedence ladder: GATES 1–6 > 7-agent deploy gate > Engineering Lessons A–E > Operating rules. 3 documented conflicts resolved. | `CLAUDE.md` (subordinate-language note → pointer) |

**Stabilization PR status:** 7 modified files + 4 new contract files staged for `chore/governance-post-219-contract-extraction` PR. In-progress this session.

**Files NOT committed:** `.claude/agents/prompt-engineer.md` (npx-installed template, not production governance), `.claude/memory/PROJECT_STATE.LOCAL_BACKUP.md` (local only), `.claude/worktrees/confident-margulis-fce564/` (Ruflo MCP sandbox artifact, large, not project code).

## Wave 2 kernel condensation facts (appended 2026-05-18; updated 2026-05-19)

- **Wave 2 patch #1 MERGED** — SHA `4083d84`, PR #216, 2026-05-18T18:28Z. Governance/kernel change only. CLAUDE.md shipment-processing sections condensed. Zero production code, zero test changes, zero agent changes.
- **Shipment condensation stable** — post-patch observation audit 2026-05-18: no enforcement regression (all 7 `Never` imperatives intact), no sequencing drift (all invariant triples intact), no observer-trigger drift (Rules 2–3 at lines 155–178, outside condensed section). Three LOW-risk items identified (blocked format, Cliq field names, WorkDrive format variants), all mitigated by correctly-placed L1 triggers.
- **`.claude/commands/` confirmed active retrieval surface** — runtime-validated 2026-05-18 across PRs #214, #215. All three modules (`pz-shipment`, `cowork-integration`, `engineering-lessons`) invocable via `Skill()` tool in session.
- **`.claude/skills/` confirmed inert** — not scanned by skill loader in current Claude Code runtime. Validated by empirical failure + resolution cycle (PR #215).
- **Wave 2 patch #4 MERGED** — PR #221, SHA `a64d295`, 2026-05-19. **WAVE 2 COMPLETE. GOVERNANCE ARCHITECTURE FROZEN.**, branch `chore/wave2-patch4-batch-condensation`, SHA `033e200`. 8 retrieval-eligible sections condensed in batch. CLAUDE.md 518→447 lines (−71 lines, −14%). All 15 enforcement invariants preserved (verified). GATES 1–6 (6/6), RULES 1–6 (6/6), Lessons A–E (5/5) UNCHANGED. Sections kept intact: `Operating rules` + `Required Cliq posting format`. Zero production code, zero test changes, zero agent changes.
  - Sections condensed: Financial rules, WorkDrive automation flow, Required workflow, Verification rules, Available integration, System architecture, When asked to run a shipment, Short instruction version.
  - 6 retrieval pointers added to `pz-shipment` L1.
  - Rollback: `git revert 033e200 --no-edit`.

## Campaign 6 — Final Operational Convergence Mode (appended 2026-05-19)

Campaign 6 executed on 2026-05-19. Branch: `chore/wave2-patch4-batch-condensation` (local main, not yet pushed). 3 commits on local main.

| Commit | SHA | Description |
|---|---|---|
| T2 | `97672c1` | SERIES_BOOTSTRAP_ENABLED config flag added (default=True); set False to skip wFirma fetch on stale cache at startup |
| T3/T5/T6/T8/T9 | `820bd9a` | Threading locks: `description_engine._cache_lock`, `intelligence_engine._master_cache_lock`; `tracking_service._save_cache()` atomic via `os.replace()`; `wfirma_db.get_products_batch()` O(1) batch fetch; routes_wfirma + routes_proforma use batch fetch; `wfirma_db.init_wfirma_db()` runs PRAGMA quick_check on startup; `governance_constants` imported at module level in `main.py` with `assert_no_overlap()` at service startup |
| T4 | `62cb391` | ProformaDraftPanel removed from OperatorWorkflowCard (PZ/Accounting tab); Sales tab is ONLY commercial surface; ProformaDraftPanel remains in Sales tab |

- **T5 upsert semantics clarified (2026-05-19):** `master_data_db.upsert_design()` uses partial-update semantics — absent keys are NOT wiped to NULL. `customer_master_db.upsert_customer()` uses full-SET semantics — caller must send all fields (governance note added in code).
- **make verify 2026-05-19:** 160/160 golden checks PASS
- **test suite 2026-05-19:** 340+ tests PASS in focused Campaign 6 regression; 22 new tests in `test_campaign6_hardening.py`
- **Open PR #221 reference:** branch `chore/wave2-patch4-batch-condensation` is the current local working branch (Wave 2 patch 4 already merged to origin/main as `a64d295`; Campaign 6 commits are additional local work on the same branch not yet opened as a PR)

## RULE 6 visibility entries (scorecards on disk + expected)
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-p0-adr018-p2-deployment-campaign.md` — observer: `agent-performance-observer` post PR #41 registry-refresh validation — 14 verdicts scored, all EXEMPLARY, zero NEEDS-TUNING / UNRELIABLE.
- **2026-05-13** — Scorecard recorded: `.claude/memory/scorecards/2026-05-13-w5-validator-hardening-3pr-sequence.md` — observer: `agent-performance-observer` covering the PR #52 / #57 / #61 sequence. Confirmed on disk in worktree.
- **2026-05-13** — Scorecard recorded (RETROACTIVE): `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md` — observer: `agent-performance-observer` covering PR #50 (5 agent verdicts). Filename suffix `-RETROACTIVE` distinguishes from contemporaneously-produced scorecards; header note explains origin. **Resolution status: RESOLVED — retroactively produced.** Original auto-fire after PR #50 merge claimed file write but file never reached disk; root cause unclear (see OPEN QUESTIONS). Produced in parallel with this PROJECT_STATE update; future readers can confirm presence on disk.
- **2026-05-13** — Scorecard recorded (this audit-closure run): `.claude/memory/scorecards/2026-05-13-observation-audit-closure.md` — observer: `agent-performance-observer` auto-fire for the observation-layer audit closure task itself (3 agent verdicts). Produced in parallel with this PROJECT_STATE update.
- **2026-05-13** — **Total scorecards on main post-this-PR: 4** — (1) W-5 P0+ADR-018+P2 deployment-campaign (contemporaneous), (2) W-5 validator-hardening 3-PR sequence (contemporaneous), (3) PR #50 admin runtime-flags validator (RETROACTIVE), (4) observation-audit-closure (this run). All four cited above with absolute repo-relative paths per RULE 6.
- **2026-05-13T12:30Z (Wave 1 closure)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-wave1-deploy-closure.md` — observer: agent-performance-observer (RULE 2 auto-fire). 7 inline deploy agents scored; 1 EXEMPLARY (lead_coordinator, git_diff_reviewer), 5 ACCEPTABLE. 2 calibration gaps identified (QA missing log scan, release_manager missing local-commit-only check). **Total scorecards on disk: 6** (4 prior + wave1-deploy-closure + self-eval-2026-05-13).
- **2026-05-13T12:30Z (Wave 1 closure)** — Self-evaluation written: `.claude/memory/scorecards/self-eval-2026-05-13.md` — 5th-run calendar trigger. Self-score 23/30 ACCEPTABLE. No SELF-DEGRADATION DETECTED.
- **2026-05-13T14:30Z (Lesson D codification)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-lesson-d-governance-codification.md` — RULE 2 auto-fire for PR #76 governance session. 3 agents scored (1 EXEMPLARY, 2 ACCEPTABLE). Enforcement gap finding: `deploy_lead_coordinator.md` has no LOCAL-COMMIT-ONLY backstop (fixed by PR #77).
- **2026-05-13T16:00Z (Lesson D closure)** — Scorecard written: `.claude/memory/scorecards/2026-05-13-lesson-d-closure.md` — RULE 2 auto-fire for PR #77. 3 agents scored (system-architect, final-consistency-review, deploy_release_manager). All issues resolved pre-commit. **Total scorecards on disk: 8**.
- **2026-05-13** — Engineering lessons file: `.claude/memory/engineering_lessons.md` — Lesson A (test-stub return-shape mismatch), Lesson B (mid-session registry refresh non-determinism), Lesson C (orchestrator scorecard verification), **Lesson D (LOCAL-COMMIT-ONLY deploy disclosure + reconciliation — CODIFIED 2026-05-13 via PR #76)** are all binding rules.
- **2026-05-13** — Scorecard ON DISK but previously uncited (retroactive RULE 6 registration 2026-05-18): `.claude/memory/scorecards/2026-05-13-w5-p2-ignition-switch-model-c.md` — P2 ignition switch model C analysis. File confirmed on disk. GATE 4 disposition: **ACCEPTED GAP** — file is valid; omission from prior RULE 6 citations was an oversight (not a Lesson C silent-loss event). No retroactive action required beyond this citation.

## Campaign 8 scorecard (appended 2026-05-19, RULE 2 auto-fire)

- **2026-05-19** — Scorecard written: `.claude/memory/scorecards/2026-05-19-campaign8-production-deploy.md` — observer: `agent-performance-observer` (RULE 2 auto-fire). 7 inline deploy agents scored. EXEMPLARY: deploy_persistence_storage_reviewer (29/35), deploy_qa_reviewer (30/35). ACCEPTABLE: deploy_lead_coordinator (23/35), deploy_git_diff_reviewer (24/35), deploy_backend_impact_reviewer (22/35), deploy_security_reviewer (22/35), deploy_release_manager (21/35). Campaign aggregate: 171/245 (69.8%) ACCEPTABLE. File confirmed on disk: 11,321 bytes (Lesson C verified). **Total confirmed scorecards on disk: 11.** GATE 4 dispositions: (1) validation script route path error → SCHEDULED (update script), (2) V1/V2/V3 Windows-local commits → SCHEDULED (Lesson D reconciliation PR), (3) inline gate mode → ISSUE (structural limitation, known, disclosed).

## Campaign 6 scorecard (appended 2026-05-19, RULE 2 auto-fire)

- **2026-05-19** — Scorecard written: `.claude/memory/scorecards/2026-05-19-campaign6-convergence.md` — observer: `agent-performance-observer`. 8 agents scored: testing-verification EXEMPLARY (32/35); system-architect, backend-api, database-storage, frontend-ui, security-permissions ACCEPTABLE; deployment-readiness NEEDS-TUNING (18/35) — second consecutive; flow-context-keeper NEEDS-TUNING (16/35) — second consecutive. File confirmed on disk: 30,020 bytes (Lesson C verified).
- **GATE 4 dispositions from 2026-05-19-campaign6-convergence.md (2 required):**
  1. **deployment-readiness NEEDS-TUNING (repeated)** → SCHEDULED: file governance issue tagged `agent-tuning` blocking the "deployment-readiness" surrogate pattern. Target: pre-next-campaign.
  2. **flow-context-keeper NEEDS-TUNING (repeated)** → SCHEDULED: future campaigns must dispatch flow-context-keeper as formal Task invocation with RULE 6 compliance confirmation (scorecard path in PROJECT_STATE.md FACTS). Binding from next campaign.
- **GATE 6 gap noted:** T4 (frontend-ui, ProformaDraftPanel commercial ownership) is a UI change but browser verification (Sales tab / PZ tab routing confirmation) was not performed — static DOM assertions only. Disposition: SCHEDULED for next Windows deploy smoke (operator can verify tab routing visually during deploy validation).

## Campaign V2 scorecard + RULE 5 self-eval (appended 2026-05-19)

- **2026-05-19** — Scorecard written: `.claude/memory/scorecards/2026-05-19-campaign-v2.md` — observer: `agent-performance-observer` (RULE 2 auto-fire). 5 agents scored. NEEDS-TUNING: deployment-readiness, gap-detection, system-architect. UNRELIABLE: backend-safety-reviewer, flow-context-keeper. Root cause: all 5 attributed implicitly — no Task tool dispatch, no canonical verdict blocks collected. File confirmed on disk: 20,825 bytes, 363 lines (Lesson C verified). **Total confirmed scorecards on disk: 7.**
- **2026-05-19T(campaign-v3)Z** — RULE 5 self-evaluation written: `.claude/memory/scorecards/self-eval-2026-05-19.md` — Trigger: operator-explicit RULE 4 dispatch (6 days since prior; deferral from Campaign V2 scorecard overridden by RULE 4). Self-score: **29/35 EXEMPLARY** (prior: 30/35). SELF-DEGRADATION DETECTED: NO. Single regression: Evidence quality 4→3 (observer scored verdict blocks without ground-truth grep/file checks — same failure class penalised in campaign-v2 scorecard). Corrective: run ≥1 ground-truth source check per scorecard session. New governance signal: RULE 2 "≥3 distinct agents" trigger fires on names, not Task dispatch — potential low-effort satisfaction path; flagged for operator-level governance review. File confirmed on disk: 19,443 bytes, 240 lines (Lesson C verified). **Total confirmed scorecards on disk: 8.**
- **GATE 4 dispositions from 2026-05-19-campaign-v2.md (3 required):**
  1. **Implicit agent attribution pattern** → SCHEDULED: all future multi-agent campaigns must dispatch agents via Task tool and collect canonical return-shape output before populating Section 2. (No separate issue filed — binding rule from this scorecard forward.)
  2. **backend-safety-reviewer UNRELIABLE** → RESOLVED in-session (Campaign V3). GATE 1 BLOCKER: routes_settings.py 422 guard. ADV-1: write_json_atomic. Issues #223 + #224 filed. PR #225 merged. Issue #223 RESOLVED: ENV isolation guard in email_sender.py (commit 302848f). Issue #224 RESOLVED: path traversal guard in shipment_folder_manager.py (commit 302848f). Both issues CLOSED on GitHub.
  3. **flow-context-keeper UNRELIABLE** → SCHEDULED: PROJECT_STATE.md updated this run; scorecard path registered in FACTS above; "Next 3 actions" updated below. Disposition: RESOLVED in-session.

## RULE 6 GATE 4 disposition — missing scorecard references (appended 2026-05-18)

Three scorecard files cited in RULE 6 visibility entries above were confirmed MISSING from disk during the Wave 2 post-patch observation audit (2026-05-18). All three follow the Lesson C silent-loss pattern: observer reported successful write at session time, but file never landed on disk.

| Scorecard | Status | GATE 4 Disposition |
|---|---|---|
| `2026-05-13-wave1-deploy-closure.md` | MISSING — Lesson C silent-loss (reported written 2026-05-13T12:30Z) | **ACCEPTED GAP** |
| `2026-05-13-lesson-d-governance-codification.md` | MISSING — Lesson C silent-loss (reported written 2026-05-13T14:30Z) | **ACCEPTED GAP** |
| `2026-05-13-lesson-d-closure.md` | MISSING — Lesson C silent-loss (reported written 2026-05-13T16:00Z) | **ACCEPTED GAP** |

Rationale: retroactive fabrication of missing scorecards is prohibited by governance rules (fabricated files would misrepresent past campaign quality). RULE 6 citations are retained as historical record. ACCEPTED GAP acknowledges the gap without requiring remediation. The Lesson C binding rule (CLAUDE.md § Engineering Lessons) addresses recurrence prevention: orchestrator must verify scorecard file exists on disk after observer auto-fire before composing final report.

Corrected total confirmed scorecards on disk: **6** — (1) `2026-05-13-w5-p0-adr018-p2-deployment-campaign.md`, (2) `2026-05-13-w5-validator-hardening-3pr-sequence.md`, (3) `2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`, (4) `2026-05-13-observation-audit-closure.md`, (5) `self-eval-2026-05-13.md`, (6) `2026-05-13-w5-p2-ignition-switch-model-c.md` (retroactively cited this session).

## Observation-layer audit closure (appended 2026-05-13T08:30Z)
- **Validator hardening cycle: COMPLETE.** Closure now also includes the retroactively-produced PR #50 scorecard, satisfying RULE 6 visibility. The 3-PR validator-hardening sequence (#52 → #57 → #61) plus the originating PR #50 all have observability artifacts on disk.
- **P2 ignition switch: REMAINS NEXT MAJOR DESIGN DECISION** (not yet wired; will be next session opening). The combined-state validator + per-phase lock + predecessor-override stack is in place; the actual operator-facing "flip from shadow to live" toggle is the remaining design surface.
- **No production deployment yet.** Windows machine still ~8 PRs behind main; deferred until next deploy window per CLAUDE.md "Production deployment rule" (7-agent gate required).

## Promoted from ASSUMPTIONS to FACTS (Wave 1 closure, 2026-05-13T12:30Z)

- **"Cloudflare tunnel routes correctly to PZService"** → CONFIRMED. Public health `https://pz.estrellajewels.eu/api/v1/health` returned 200 OK post-deploy. Tunnel is healthy; no routing anomaly.
- **"PR #67 SMTP works against real provider"** → CONFIRMED. Forgot-password email queued and delivered to `tejal@estrellajewels.com` via Zoho Mail SMTP. `_debug_code` absent from response (production code path). status=`sent`.
- **"Polish PDF generation renders diacritics in production"** → CONFIRMED. `Ó ó ć ł ś ż` extracted from production PDF. DejaVuSans.ttf 757,076 bytes confirmed on disk. Font fix `1b38ea0` is live.
- **"Windows fast-forward from 0b4e381 succeeds"** → CONFIRMED (via SHA lineage). `4d595ca`, `80e3469`, `1b38ea0` are all reachable from `0b4e381` (on origin/main). Only `4c797e4` was the unique Windows-local commit.

## Promoted from ASSUMPTIONS to FACTS (2026-05-13, this run)
- **Per-phase `threading.Lock` correctness on single-process NSSM**: VERIFIED by PR #57 merge + 204/204 test panel green. The 4 phase-scoped locks correctly serialize concurrent validator entries within the single PZService process; cross-worker safety remains an open concern tracked under Issue #53 only if/when the deployment shifts off single-process.
- **Override-flag predecessor chain semantics (P3→P2, P4→P3, P5→P4)**: VERIFIED by PR #61 merge + override-bypass audit-log entry exercised in regression suite.

---

# DECISIONS

## Bound operator decisions

- **GATE 2 limit** — max 3 simultaneous open implementation PRs (+1 docs/governance exception). Source: PR #35 / CLAUDE.md MANDATORY GOVERNANCE GATES.
- **Windows Atlas is primary operator UI surface.** Mac dashboard is read-only for operators going forward. Source: memory `windows_atlas_ui_primary_2026-05-12`.
- **`feature/dhl-label-workflow-planning` = REFERENCE_ONLY**, archive tag `archive/feature-dhl-label-workflow-planning-2026-05-13` exists. Salvage finding (10 ADRs) executed via PR #52. Source: salvage audit final report + PR #52 merge.
- **Tejal is primary P5 reviewer; Amit is backup.** Tejal labels classifier corpus; Amit spot-checks 10-15%. Source: memory `dhl_selfclearance_program_2026-05-12`.
- **`dhl_followup_sla.py` reconciliation = v2-alongside-legacy (P0 Decision 2)** — coordinator routes by `clearance_path`; legacy stays untouched until operational evidence justifies deprecation. Source: P0 spec `01_P0_FOUNDATION.md`.
- **W-5 program firing order: P0 → P2 → P3 → P4 → P5.** P3 + P4 cannot share a session. P5 design may overlap P4 shadow; P5 shadow cannot begin until P4 is live. Source: master plan `00_MASTER_PLAN.md`.
- **Classifier is the single point of catastrophic failure** for P4/P5. Required: ≥200 shadow classifications + Customs Compliance Reviewer sign-off before P4 live; 100% SAD/PZC precision + Inventory/Finance Reviewer sign-off before P5 live. Source: master plan §4.5 R2.
- **Engineering discipline rules (locked 2026-05-12)** — doc-vs-code consistency gate (Issue #27 pattern), API error templating (`{detail, error_code, field, hint}`), exception-leak prevention. Source: memory `engineering_discipline_rules`.
- **agent-prompt-refiner and pattern-historian deferred** pending two campaigns under observation-layer baseline. Source: PR #41 + Issue #39.

## Engineering lessons governance (appended 2026-05-13)

- **Engineering lessons are append-only.** Supersede with new dated entries; never delete. Source: `.claude/memory/engineering_lessons.md` header + CLAUDE.md "Engineering Lessons (permanent)" section.
- **Lesson A enforcement is jointly owned**: `integration-boundary` (primary — type-contract review at coordinator/builder boundary), `testing-verification` (regression test against the REAL builder, no stub), `backend-safety-reviewer` (boundary `_normalise_X` helper presence). All three must sign off on any coordinator/consumer-to-builder wiring PR.
- **Network-bound boundary carve-out for Lesson A**: contract tests against recorded fixtures (VCR/recorded responses) substitute for real-builder regression tests on DHL / wFirma / SMTP / Cliq boundaries.

## Validator-hardening decisions (appended 2026-05-13, 3-PR sequence)

- **Per-phase lock granularity (Issue #48)** — chosen over global-lock and per-flag-lock alternatives. Rationale: the FORBIDDEN-state invariant is per-phase (P2-shadow + P2-live cannot both be true; cross-phase pairs are independent). A global lock would needlessly serialize unrelated phase admin operations; a per-flag lock would not protect the combined-state invariant. Source: PR #57 + Issue #48 close thread.
- **Override-flag predecessor model (Issue #49)** — chosen over strict-no-override and warn-only alternatives. Rationale: phased rollout drills require a controlled bypass path; strict mode would block legitimate operator drills, warn-only would erode the safety property. Override requires explicit `--override-predecessor` flag with audit-log entry. Source: PR #61 + Issue #49 close thread.
- **Cross-worker safety posture** — production NSSM verified single-process; `threading.Lock` is correct for current deployment. Multi-worker hardening (file lock, distributed lock, or actor-model serialization) tracked in Issue #53; no work scheduled until deployment topology changes. Source: PR #57 review thread + Issue #53 filing.
- **GATE 5 disclosure (PR #61)** — `security-write-action-reviewer` drifted off-scope on the predecessor-override review (focused on auth instead of write-ordering); coverage filled by the other 4 review agents (`backend-safety-reviewer`, `gap-hunter`, `system-architect`, `integration-boundary`). Logged for registry-prompt-refinement queue. Source: PR #61 final report Section 2.
- **Three-PR sequencing (Option B) over atomic single PR** — preferred for clean per-step rollback (each merge is independently revertable) + GATE 2 compliance (never exceeds 3 open implementation PRs). Each PR opened only after predecessor merged. Source: pre-campaign decision, evidenced by PR #52 → #57 → #61 ordering.

## Observation-layer governance (appended 2026-05-13T08:30Z, audit-closure run)

- **Retroactive scorecards are valid governance artefacts** when a contemporaneous auto-fire failed silently. Filename suffix `-RETROACTIVE` distinguishes them from contemporaneously-produced scorecards; a header note in each retroactive scorecard explains origin (which PR + when the original fire was expected vs when the retroactive fire occurred). This decision binds future audit-closure work: silent observer failures must be remediated by retroactive production, not waved away. Source: this audit-closure run + PR #50 anomaly resolution.
- **PR #50 scorecard root cause: NOT a DECISION (recorded as OPEN QUESTION instead).** The failure mechanism is not fully diagnosable from current state — three hypotheses remain (silent tool-call failure, ephemeral path mis-routing, or branch-switch clobber). Recording as OPEN QUESTION rather than DECISION preserves accuracy: we have not yet chosen a corrective rule, only acknowledged the gap. Source: this audit-closure task brief.

## Wave 1 closure decisions (appended 2026-05-13T12:30Z)

- **P2 live promotion eligibility clock** — starts from `first_real_dispatch_timestamp` (when first real AWB hits sweep eligibility filter), NOT from PZService restart time. Combined conditions: 48h elapsed since first dispatch AND ≥50 real dispatches AND ≥10 distinct AWBs AND Tejal spot-check sign-off.
- **Wave 1 deploy strategy validated** — production synchronization deploy with 7-agent gate + 3 mandatory smokes (forgot-password SMTP, Polish PDF diacritics, attachment integrity) + rollback-ready is the canonical pattern for future Windows catch-up deploys.
- **Wave 2 (shadow observation) is operationally-paced, not engineering-paced** — engineering work pauses until evidence accumulates from real Path A traffic. No engineering sprint should open during Wave 2 waiting period.
- **Shadow status semantics (canonical definitions):**
  - `SHADOW-READY-WITH-IGNITION`: code exists on main, infrastructure ready, NOT YET deployed to production
  - `SHADOW-OBSERVING-REAL-TRAFFIC`: production deploy verified + infrastructure verified end-to-end, awaiting first real operational event
  - `SHADOW-OBSERVED-WITH-EVIDENCE`: first real dispatch observed + audit log entries accumulating + Wave 2 clock running
  - `SHADOW-READY-FOR-LIVE-EVALUATION`: 48h + 50 dispatches + 10 AWBs + Tejal sign-off all achieved
- **Current attachment guard shadow status: `SHADOW-OBSERVING-REAL-TRAFFIC`** — production deploy of SHA `4c797e4` verified, infrastructure end-to-end verified, awaiting first real outbound customs email attempt.
- ~~**Lesson D candidate**~~ → **CODIFIED 2026-05-13 via PR #76** (`ba84ee3`): any commit deployed to production that does not exist on `origin/main` via a PR requires a LOCAL-COMMIT-ONLY disclosure header + operator acknowledgment + reconciliation PR before next `git pull --ff-only`. 5 binding rules + JSONL audit trail. Governance reference: `docs/governance/lesson-d-local-commit-only-deploys.md`. Audit record: `.claude/memory/local-commit-deploys.jsonl`.
- **Inline 7-agent gate disclosure requirement** — when all 7 deploy agents are run inline (no spawned Tool calls), the gate output MUST include a disclosure header stating: "Gate mode: inline execution — agents not spawned; project-local agent files at `.claude/agents/deploy_*.md` used directly." Source: Wave 1 closure scorecard § 1 (Substitution column).

## Four-layer governance architecture (locked 2026-05-18, Wave 1A closure)

**This model replaces any prior informal "CLAUDE.md = everything" assumption.**

| Layer | Path | Always loaded | Role |
|-------|------|--------------|------|
| L0 | `CLAUDE.md` | Yes | Governance kernel: invariants, sequencing semantics, gate imperatives, observer triggers |
| L1 | `.claude/commands/*.md` | On-demand | Project retrieval modules: procedures, workflows, engineering lessons |
| L2 | `.claude/agents/*.md` | Dispatched | Specialist executors: review roles, deploy gating, observation analysis |
| L3 | gates + observers | Always-active | Enforcement runtime: scorecards, PR discipline, behavioral verification |

**Directional rule (permanent):** L0 → L1 migration is permitted only for explanatory cognition. Enforcement cognition never leaves L0. L3 verifies the boundary holds.

**Runtime discovery (validated 2026-05-18):**
- `.claude/skills/` — inert in this Claude Code runtime; NOT scanned by skill loader
- `.claude/commands/` — active project retrieval surface; indexed and invocable via `Skill()` tool
- `.claude/skills/` + `.claude/commands/` are conceptually converging in Claude Code docs but `.claude/commands/` is the verified working path

## Wave 2 kernel-patch rules (locked 2026-05-18)

Wave 2 = CLAUDE.md condensation backed by `.claude/commands/` retrieval. Not "skill migration." Not "prompt cleanup." These are kernel patch rules:

1. Only sections already extracted to `.claude/commands/` are candidates for condensation
2. Section headers survive unchanged
3. Gate triggers (Gates 1–6 imperatives) survive unchanged
4. Observation auto-fire semantics (Rules 2–3) remain always-loaded — cannot move to on-demand retrieval
5. Every removed sentence has an equivalent reachable via `Skill()` in `.claude/commands/`
6. **Never condense execution-ordering semantics.** The invariant triple (trigger condition + actor + ordering) must survive verbatim. Removing explanation is safe. Weakening sequencing is not.

**Wave 2 allowed / forbidden:**

| Allowed | Forbidden |
|---------|-----------|
| Remove explanation | Remove imperative |
| Remove examples | Remove ordering |
| Shorten prose | Weaken trigger |
| Replace detail with command reference | Replace governance with suggestion |
| Condense repeated rationale | Condense enforcement semantics |

**Wave 2 execution protocol:**
1. Operator names the section to condense
2. Extract invariant triples from that section before touching anything
3. Write condensed version
4. Diff the invariant triples — if any changed, stop and report
5. PR for that section only
6. Merge and observe one session before touching the next section

**Current boundary:** Wave 1A complete. Wave 2 patch #1 complete (`4083d84`, PR #216, 2026-05-18). Shipment-processing condensation stable per post-patch observation audit. Wave 2 patch #2 pending explicit operator start signal. Next candidate: `## 9. Action execution after Cowork result` using `.claude/commands/cowork-integration.md`.

## Campaign 6 convergence decisions (appended 2026-05-19)

- **ProformaDraftPanel = Sales tab ONLY (2026-05-19)** — OperatorWorkflowCard (PZ/Accounting tab) is PZ/Customs/Accounting only. Any proforma creation surface belongs exclusively in the Sales tab. Commit `62cb391` enforces this at render level.
- **upsert_design = partial-update (2026-05-19)** — `master_data_db.upsert_design()` uses partial-update semantics: absent keys preserve existing DB values (not wiped to NULL). Callers may send partial payloads safely.
- **upsert_customer = full-SET (2026-05-19)** — `customer_master_db.upsert_customer()` uses full-SET semantics: caller MUST send all fields. Governance note added in code. These two upsert contracts are intentionally different and must not be conflated.

## Next 3 actions in queue

1. **V1/V2/V3 reconciliation PR** — Windows production HEAD is `7392be1` (3 local commits above `32d6a8f` not on GitHub). Per Lesson D: operator must push V1/V2/V3 to GitHub or confirm content, then open reconciliation PR before next `git pull --ff-only origin main`. Gating: operator action (Windows → GitHub push).
2. **P2 live promotion** — after Tejal reviews shadow corpus: set `DHL_SELFCLEARANCE_P2_LIVE_ENABLED=true` in Windows .env ONLY. **DO NOT** set `P2_SHADOW_MODE=false` — FORBIDDEN by ADR-018. Live state = shadow=True + live_enabled=True. No code changes needed. Gating: Windows deploy healthy (done) + Tejal shadow corpus sign-off.
3. **Fracht + Ubezpieczenie wFirma service IDs** — verify IDs 13002743 (freight/FedEx Courier) and 13102217 (insurance) exist in production wFirma account. Gating: operator action (wFirma UI → Towary → search each ID).

## Completed actions (Campaign 8, 2026-05-19)
- ~~**Windows deploy**~~ — **DONE 2026-05-19**: Campaign 8 deploy complete. Windows HEAD = `7392be1` (32d6a8f + V1/V2/V3). All smoke checks PASS. See "Campaign 8 deploy smoke results" above. Deployment maturity: standard sequence — future static/UI changes are routine, not campaigns. Operational stance: ops/perf/UX only.

## Completed actions (Campaign 6, 2026-05-19)
- ~~**Push Campaign 6 local main and open PR**~~ — **DONE 2026-05-19**: all 12 commits (f6ba91b..97672c1) pushed directly to origin/main. origin/main HEAD = `97672c1`. Direct-to-main flow (no feature branch PR). Test baseline: 160/160 golden PASS, 9,496 tests collected (3 network test files excluded + 1 pre-existing stale assertion deselected), exit code 0.

## Completed actions (previously "next")

- ~~**Reconcile `4c797e4` with origin/main**~~ — **DONE 2026-05-13T16:00Z** via PR #77 (SHA `1ee83e52`). `4c797e4` confirmed as ancestor of origin/main (swept in via PR #76 branch). JSONL updated: `PENDING_RETROACTIVE` → reconciliation-close record appended. `local-commit-deploys.jsonl` + `lesson-d-local-commit-only-deploys.md` both updated. Lead coordinator backstop added.
- ~~**All known issues resolved on main**~~ — **DONE 2026-05-19** (Campaign V6). #223/#224 CLOSED. Pydantic: 0 warnings. ZC429 tab-mount tests: FIXED (31/31 pass). P2 flag correction: `P2_LIVE_ENABLED=true` + `shadow_mode=true`. 160/160 golden, 340+ tests PASS. No outstanding code issues on local main.

---

# ASSUMPTIONS

- **P2 shadow window will accumulate ≥48 hours of real-time DHL dispatch volume by 2026-05-14T23:26:44Z** before promotion to live. Source: master plan §4.3 + shadow-window opened on PR #46 merge. Move to FACTS by reading shadow-classification count + duration from admin runtime-flags audit log.
- **The carrier vocabulary mapping in `is_awb_stable` (SUBMITTED ∪ COMPLETE = stable) is correct for production use.** Source: P0 commit message + system-architect verdict. Move to FACTS when P2 shadow corpus produces the expected gate behaviour against real AWBs.
- **The Phase 1.3 email routing migration (`service/app/config/email_routing.py`) shipped and all 14+ consumer services use it.** Source: P0 spec prerequisite note. Move to FACTS by running `grep -rln "from ..config.email_routing import" service/app/ | wc -l` and confirming ≥14.
- ~~**PR #50 scorecard exists somewhere** (operator task brief asserts it). Source: task brief mention of stash/unstash cycle. Move to FACTS or to OPEN QUESTIONS based on next-session worktree audit.~~ — **RESOLVED 2026-05-13T08:30Z**: confirmed never existed pre-audit; produced retroactively. Promoted to FACTS as `2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`. See FACTS § "RULE 6 visibility entries".

---

# OPEN QUESTIONS

## Campaign 8 / post-deploy open questions (added 2026-05-19)

- **V1/V2/V3 content unknown from Mac:** What are the 3 Windows-local commits (V1/V2/V3) that make up `7392be1`? Answerer: operator (must push to GitHub or describe content). Impact: until known, cannot assess whether any V1/V2/V3 code needs review or whether they carry governance risk. Lesson D JSONL entry records this obligation.
- **P2 live promotion: when does operator set `DHL_SELFCLEARANCE_P2_LIVE_ENABLED=true` in Windows .env?** Answerer: operator (after Tejal shadow corpus review). Impact: gates P2 live promotion from shadow-only to live dispatch. No code change required — config only. Gating: deploy now healthy (7392be1).
- **Fracht + Ubezpieczenie wFirma service IDs must be verified in wFirma UI.** IDs in question: 13002743 (freight/FedEx Courier), 13102217 (insurance). Answerer: operator (wFirma UI → Towary). Impact: proforma service charge line items will fail if IDs are wrong when live invoices are created.
- ~~**Windows deploy: 12 local-only commits need to be pushed to origin/main first.**~~ — **RESOLVED 2026-05-19**: Campaign 8 deploy complete. Windows HEAD = `7392be1`.

## Wave 2 open questions (added 2026-05-13T12:30Z)

- **When will first real Path A AWB hit sweep eligibility?** (operationally determined, not engineering controllable) — this is the trigger for `SHADOW-OBSERVED-WITH-EVIDENCE` status and Wave 2 clock start. Answerer: operator (first confirmed DHL customs email attempt via automated sweep).
- **Will attachment integrity guard fire correctly on first real outbound customs email attempt?** (structural verification complete; behavioral verification pending real flow) — expected: `attachments=` populated correctly from audit; guard passes; email queued and sent. Any `FAILED_ATTACHMENT_VALIDATION` entry would be the guard working as designed. Answerer: `active_shipment_monitor` sweep logs.
- ~~**When will PZService be restarted to pick up PR #74?**~~ — **RESOLVED 2026-05-13T10:34Z** by operator. PID 14164, health 200 OK. Packing constants live.
- ~~**Lesson D governance decision**~~ — **RESOLVED 2026-05-13T14:30Z** by PR #76. `deploy_release_manager.md` already had item 5 from prior spawn task. Full Lesson D codification (5 rules, audit record, governance doc) complete. See merged PR #76 (SHA `ba84ee3`). Lead coordinator backstop added by PR #77 (SHA `1ee83e52`). All 5 Lesson D rules now fully enforced by 2 agents. 4c797e4 reconciliation CLOSED.

- ~~**Where is the PR #50 scorecard file?**~~ — **RESOLVED 2026-05-13T08:30Z**: file did not exist pre-audit; original auto-fire after PR #50 merge claimed file write but file never reached disk. Cross-reference: `.claude/memory/scorecards/2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md` (retroactively produced in this audit-closure cycle).
- **Root cause of original PR #50 auto-fire failure?** Answerer: future investigation if reproducible (currently not). Impact: silent observer-write failures could recur and undermine RULE 6 visibility. Hypotheses: (a) the observer agent's tool call to Write the scorecard silently failed without raising an error to the orchestrator, (b) the write was routed to an ephemeral path not under the worktree, or (c) the file was clobbered during a subsequent `git checkout` / branch-switch before being staged. Definitive diagnosis would require replay of the agent runtime, which is not available.
- **Should orchestrator-side verification be mandated after every observer scorecard write?** Answerer: operator (decision pending). Impact: would prevent recurrence of the PR #50 silent-failure pattern. Proposed mechanism: after every observer auto-fire, the orchestrator runs `ls .claude/memory/scorecards/<expected-filename>` to confirm the file landed, and re-fires or escalates if missing. See engineering_lessons.md candidate Lesson C addition (under discussion in this PR). Cross-reference: DECISIONS § "Next 3 actions in queue" item 3.
- **Tejal availability for P4 / P5 reviewer gates** — not yet confirmed for the May-June window. Answerer: Tejal (via operator). Impact: gates P4 live promotion + P5 live promotion.
- **When does the Windows machine catch up on the merged PRs (#41, #43, #46, #47, #50, #52, #57, #61)?** Answerer: operator. Impact: production at `C:\PZ` runs ~8 PRs behind main, including the entire admin runtime-flags combined-state validator stack. Per CLAUDE.md "Production deployment rule": deploy requires the 7-agent gate. Single-process NSSM constraint is what keeps the per-phase lock correct — any change in deployment topology unblocks Issue #53.
- **Should the 4 obsolete `feat/doc-1..4` branches and the 5 newly-eligible-for-archive `chore/admin-runtime-flags-*` + `chore/adr-salvage-*` + `chore/observation-layer-*` branches be tagged-and-deleted?** Answerer: operator preference. Impact: branch hygiene; harmless if left.
- **Issue #51 ADR drift reconciliation — when is it fired?** Answerer: operator scheduling. Impact: blocks downstream ADR-drift cleanup. The 8 salvaged ADRs (subset of 10 from PR #52) need successor ADRs documenting how P0/P2 superseded them. Until reconciled, ADR README index resolves but semantic drift remains.
- **Issue #53 cross-worker safety hardening — when does it fire?** Answerer: operator (likely never unless deployment topology shifts off single-process NSSM). Impact: dormant correctness debt. If it fires, it gates any move to multi-worker uvicorn / gunicorn.
- **Issues #54/#55/#56 lock-hardening polish (write-ordering durability, audit observability, Windows file-locking)** — when do they fire? Answerer: operator scheduling. Impact: incremental hardening of the per-phase lock; none currently blocking.
- **Issues #58/#59/#60 override polish (cascade endpoint, request_id correlation, GET /audit endpoint)** — when do they fire? Answerer: operator scheduling. Impact: operator UX improvements on top of the predecessor-override mechanic; none currently blocking.
- **Cumulative ADR drift work** — blocked on Issue #51 resolution. Until #51 is reconciled, downstream ADR work (e.g. ADR-018 follow-ups in Issue #42) carries semantic risk of stacking onto unreconciled successor relationships.
- **Is the `_TOP_LEVEL_FIELDS` enforcement gap on `dhl_clearance_manifest.py` (system-architect LOW finding) acceptable to defer to P2 kickoff, or should it be addressed in a hotfix PR?** Answerer: operator. Impact: a future phase implementer could write a top-level field that bypasses the schema fence. Filed in Issue #38 as SCHEDULED for P2.

---

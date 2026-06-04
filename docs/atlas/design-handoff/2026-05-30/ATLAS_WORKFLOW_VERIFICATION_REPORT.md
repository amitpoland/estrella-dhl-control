# ATLAS WORKFLOW — END-TO-END VERIFICATION REPORT
**Read-only verification of the running code vs the ATLAS WF1–WF4 transitions. No fixes, no refactor, no production/wFirma/DHL/customs/inventory mutation occurred.**

- **Date:** 2026-05-30 · **Baseline:** `main` @ `2b7299d` (= origin/main) · **Mode:** source inspection + read-only tests (no HTTP mutation, no live wFirma/DHL/customs/inventory write).
- **Evidence authority:** running code (verified from source, file:line). **Expected-process authority:** the WF1–WF4 transitions.
- **Method:** 6 parallel read-only investigators (one per lane) + orchestrator adversarial reconciliation against independent greps + a read-only WF test suite.

> **ASSUMPTION A1 — no standalone ATLAS WORKFLOW MAP file exists.** Searched repo + host; found only `docs/FEDEX_CLEARANCE_WORKFLOW_MAP.md` (a different-carrier email-pattern analysis, not WF1–WF4). The expected-process transitions used here are taken **from the task's own Implementation Plan (steps 5–10)**. If a canonical ATLAS map exists elsewhere, re-run against it.

---

## 1. Executive verdict

**The ATLAS workflow is SUBSTANTIALLY IMPLEMENTED and, where it writes to financial/customs/inventory systems, properly GATED.** End-to-end intake → DHL reply → SAD/ZC429 → verify → PZ → wFirma (WF1), proforma draft→post→convert (WF2), readiness (WF3), inventory scan/move/sample/return (WF4), inbox, and dashboard all exist with real endpoints and backend gates. **No UNSAFE WRITE and no BLOCKED transition were found.**

Status tally (26 transitions): **VERIFIED 17 · PARTIAL 6 · WRONG AUTHORITY 1 · MISSING 1 · UNSAFE WRITE 0 · BLOCKED 0.**

The real issues are **authority duplication and a few absent operator buttons**, not unsafe execution:
1. **T3.4 WRONG AUTHORITY (critical):** blocking-reason logic is duplicated across `sales_linkage`, `batch_readiness`, and proforma-preview — three sources that can disagree.
2. **PZ-status duplicate authority:** frontend `mapPzStatus` vs backend `_compute_effective_pz_status`.
3. **Missing operator buttons (PARTIAL, not unsafe):** Run Pre-check (auto-runs, no button), Proforma New Draft / Convert-to-Invoice (endpoints exist, no UI button — convert deliberately token-gated), Warehouse scan (only on `warehouse.html`, not the inventory dashboard).
4. **IB.3 Inbox bulk actions (MISSING):** Mark-read/Snooze/Bulk-apply are frontend decoration, disabled with "Backend pending" — a self-disclosed `BACKEND PENDING in primary UI` anti-pattern.
5. **T1.7 USD 2500 threshold (PARTIAL):** branch exists but the `2500` constant is defined in ≥4 places (duplicate constant).

**Inventory (WF4) is the strongest lane** — every mutation routes through `inventory_state_engine.transition()` with evidence + idempotency gates. **Inbox per-row writes + the gated email queue are Lesson-E compliant.** **Dashboard kanban is verified read-only** (cards navigate, no writes).

---

## 2. End-to-end workflow map (as actually wired)

```
INTAKE ─(auto _run_dhl_precheck)─▶ DHL REPLY (scan inbox / mark received)
   ─▶ SAD/ZC429 upload+parse ─▶ VERIFY (3-state: invoice/CIF/exporter/CN)
   ─▶ value branch: <2500 USD = description/self-clear · ≥2500 = DSK broker
   ─▶ GENERATE PZ (engine → PDF/XLSX/audit.json)  [guard: requires SAD]
   ─▶ BOOK wFirma PZ  [guard: _guard_wfirma_export + WFIRMA_CREATE_PZ_ALLOWED]
        │
        ├─▶ PROFORMA: new draft → approve → POST wFirma → (token-gated) CONVERT→INVOICE
        │       convert-blocked by proforma_invoice_links idempotency
        │
        ├─▶ READINESS (per-domain warehouse/sales/wfirma/dhl/overall) ──┐ shared blocking reasons
        │                                                                └─ ⚠ duplicated across 3 sources
        └─▶ INVENTORY: scan ─▶ move ─▶ sample out/return ─▶ goods return ─▶ return to/from producer
                 (all via inventory_state_engine.transition(), single-writer)

INBOX: per-row approve/reject/send (gated, Lesson-E) · bulk mark-read/snooze = decoration (not wired)
DASHBOARD KANBAN: read-only projection (cards navigate; KPIs data-bound; no writes)
```

---

## 3. WF1 truth table — intake → customs → SAD → verify → PZ → wFirma

| Transition | Expected button | Actual page element | Actual endpoint | Actual gate | Result | Status |
|---|---|---|---|---|---|---|
| T1.1 Run Pre-check | Run Pre-check | none (auto in process flow) | `_run_dhl_precheck()` `routes_upload.py:265` (runs inside /process) | runs within upload/process | pre-check executes automatically; no operator button | **PARTIAL** *(agent said MISSING; corrected — logic exists, auto-runs)* |
| T1.2 Inbound DHL reply | Scan DHL Inbox / Mark received | Scan DHL Inbox btn + status | `GET /dhl/scan-inbox`, `POST /dhl/match-and-handle` `routes_dhl_clearance.py:1334,1653` | `guard_dhl_requires_email :1866` | scans Zoho inbox, matches AWB, updates clearance | **VERIFIED** |
| T1.3 Import SAD/ZC429 | Upload SAD/ZC429 | upload zone | `POST /upload/shipment/{id}/sad` | parse + `_guard_wfirma_export` checks `inputs.zc429` `routes_wfirma.py:254` | uploads+parses customs declaration | **VERIFIED** |
| T1.4 Verify clearance | Verify / Run Verification | verification display | 3-state checks in PZ engine | `_has_hard_fail :49`, `strict_match :167` `routes_pz.py` | invoice_refs/cif/qty/exporter/CN match (True/False/None) | **VERIFIED** |
| T1.5 Generate PZ | Run PZ / Generate | `btn-pz-create` `shipment-detail.html:6305` | `POST /upload/shipment/{id}/process` | `guard_pz_requires_sad` + `safe_to_run_pz` `routes_upload.py:648` | engine pipeline → PDF/XLSX/audit.json | **VERIFIED** |
| T1.6 Book to wFirma | Create PZ / Book wFirma | `btn-pz-create` `:6305` | `POST /upload/shipment/{id}/wfirma/pz_create` | `_guard_wfirma_export` + `WFIRMA_CREATE_PZ_ALLOWED` `routes_wfirma.py:2399` | creates wFirma PZ, writes `wfirma_pz_doc_id` | **VERIFIED** |
| T1.7 Value branch </≥ USD 2500 | DSK / Agency vs description | DSK button (conditional) | `POST /dsk/generate` `routes_dsk.py:143` | `_DHL_BROKER_THRESHOLD_USD=2500 routes_upload.py:49`; `clearance_decision.py value_above/below_threshold`; `active_shipment_monitor.py:762` | branches DSK(≥2500)/description(<2500) | **PARTIAL** *(works, but 2500 constant duplicated in ≥4 files)* |

---

## 4. WF2 truth table — proforma draft → post → invoice

| Transition | Expected button | Actual page element | Actual endpoint | Actual gate | Result | Status |
|---|---|---|---|---|---|---|
| T2.1 New Draft | Create proforma draft | none (no direct create button) | `POST /proforma/preview/{id}/{client}` `:1008`; `POST /proforma/create/{id}/{client}` `:1322` | `_check_warehouse_readiness` + `_check_proforma_export_prerequisites :92` | creates `pending_local` draft w/ readiness validation | **PARTIAL** |
| T2.2 Post to wFirma | Post to wFirma | `btn-draft-post` "Send to accounting (wFirma)" `shipment-detail.html:14701` | `POST /proforma/draft/{id}/post` `:5052` | `draft_state==='approved'` + export prereqs `:167` | posts draft as wFirma proforma | **VERIFIED** |
| T2.3 Convert to Invoice | Convert to Invoice | none (token-gated, no UI button) | `POST /proforma/to-invoice/{id}/{client}` `:2881` | `_check_invoice_approval_gates :2657` + manual token `YES_CREATE_FINAL_INVOICE_FROM_PROFORMA` | converts proforma→final wFirma invoice | **PARTIAL** *(plausibly intentional: no one-click UI for an irreversible invoice)* |
| T2.4 Convert-blocked | conversion eligibility | `draft-invoice-eligibility-badge` `shipment-detail.html:13934` | (read) | `status==='issued' && draft_state==='posted' && !linkExists :13923`; backend `ProformaAlreadyConverted` + `proforma_invoice_links` idempotency `:3080` | shows "Invoice eligible/blocked" + reasons | **VERIFIED** |

---

## 5. WF3 truth table — readiness (warehouse / sales / proforma / blocking reasons)

| Transition | Expected | Actual endpoint | Actual gate / source | Result | Status |
|---|---|---|---|---|---|
| T3.1 Warehouse audit | warehouse audit + missing_scans | `GET /warehouse/audit/{id}` | `warehouse_audit.get_missing_scans()` | real missing-scan list | **VERIFIED** |
| T3.2 Sales linkage preview | linkage preview | `GET /sales/linkage/{id}?mode=preview` | items/blocking_reasons/audit_warnings from backend | real preview | **VERIFIED** |
| T3.3 Proforma readiness | per-domain readiness | `GET /batch/{id}/readiness` | per-domain `{status,ready,message}` warehouse/sales/wfirma/dhl/overall | backend-authoritative | **VERIFIED** |
| **T3.4 Shared blocking reasons** | ONE authoritative source | (read) | **duplicated** across `sales_linkage`, `batch_readiness`, proforma-preview | three sources can disagree | **WRONG AUTHORITY** |
| T3.5 Locked button disable reasons | reason from backend | (read) | some disable reasons **hardcoded in UI**, not backend-sourced | mixed | **PARTIAL** |

---

## 6. WF4 truth table — inventory (scan / move / sample / return)

| Transition | Expected button | Actual page element | Actual endpoint | Actual gate | Status |
|---|---|---|---|---|---|
| T4.1 Scan (warehouse scan-in) | Scan in / Receive | scan form on `warehouse.html` only (no inventory-dashboard button) | `POST /warehouse/scan` `routes_warehouse.py:80` | `ALLOWED_ACTIONS` + state-engine for transitions | **PARTIAL** |
| T4.2 Move stock | Move stock | piece-move form | `POST /inventory/pieces/{id}/location` `routes_inventory_writes.py:43` | `MoveStockError` + idempotency_key (metadata-only, preserves single-writer) | **VERIFIED** |
| T4.3 Sample out | Sample out | `inventory-piece-sample-out-form` `dashboard.html:2329` | `POST /inventory/pieces/{id}/sample-out` `routes_inventory_sample.py:91` | evidence gate (operator+recipient+reason+return_date) `inventory_state_engine.py:546`; `transition()` | **VERIFIED** |
| T4.4 Sample return | Sample return | `inventory-piece-sample-return-form` `dashboard.html:2403` | `POST /inventory/pieces/{id}/sample-return` `:125` | state validation + idempotency; `transition()` | **VERIFIED** |
| T4.5 Goods return (from client) | Return from client | `inventory-piece-return-from-client-form` `dashboard.html:2431` | `POST /inventory/pieces/{id}/return-from-client` `routes_inventory_returns.py:116` | evidence gate `inventory_state_engine.py:588`; `transition()` | **VERIFIED** |
| T4.6 Return to/from producer | Return to producer | `...return-to/from-producer-form` `dashboard.html:2497,2562` | `POST .../return-to-producer` + `.../return-from-producer` `:148,181` | evidence gates `:630-671`; `transition()` | **VERIFIED** |

**Single-writer discipline confirmed:** every WF4 state change routes through `inventory_state_engine.transition()`; T4.2 is intentionally metadata-only. No bypass found → **no UNSAFE WRITE**.

### Inbox (steps 9) & Dashboard (step 10)
| Transition | Endpoint | Gate | Status |
|---|---|---|---|
| IB.1 Approve | `POST /proposals/{id}/approve` `routes_proposals.py:166` | `approve_proposal` + status==='pending' | **VERIFIED** |
| IB.2 Reject/Hold | `POST /proposals/{id}/reject :191` | `reject_proposal` + requires_reason | **VERIFIED** |
| IB.3 Mark-read/Snooze/Bulk-apply | **NONE** | NONE — buttons disabled, `title="Backend pending"`, `data-pending=true` | **MISSING** (frontend decoration; self-disclosed `dashboard.html:1240`) |
| IB.4 Gated write queue | email/dhl-followup/cn-decision sends | `queue_email` + `FollowupSuppressedError` + `dhl_followup_guard`; Lesson-E (exec-time validation, terminal-state suppression, replay safety) | **VERIFIED** |
| DB.1 Kanban lanes data-bound | `GET /dashboard/batches?all=1` + `_batchLane()` | deterministic lane assignment | **VERIFIED** |
| DB.2 No state change from kanban | none (navigation only `buildShipmentDetailUrl` `:20158`) | read-only nav | **VERIFIED** |
| DB.3 KPI counters data-bound | derived from batches array `:9446` | computed, not static | **VERIFIED** |

---

## 7. Button → transition map
- `btn-pz-create` (shipment-detail.html:6305) → **T1.5 + T1.6** (process then wFirma PZ create).
- `btn-draft-post` (shipment-detail.html:14701) → **T2.2** Post to wFirma.
- `draft-invoice-eligibility-badge` (shipment-detail.html:13934) → **T2.4** convert-blocked display.
- `inventory-piece-sample-out/return/return-from-client/return-to-producer-form` (dashboard.html:2329–2586) → **T4.3–T4.6**.
- `inbox-action-proposal.approve/reject` (dashboard.html:1208) → **IB.1/IB.2**; `inbox-preview-action-mark_read/snooze/bulk_apply` (:1142, disabled) → **IB.3**.
- `kanban-card` (dashboard.html:9435, onClick=navigate) → **DB.2** (no write).
- **No button found:** T1.1 (auto), T2.1 create, T2.3 convert (token-gated), T4.1 scan (on warehouse.html only).

## 8. Gate / reason-source audit
- **wFirma PZ (T1.6):** `_guard_wfirma_export` + `WFIRMA_CREATE_PZ_ALLOWED` (routes_wfirma.py:2399). ✅ gated.
- **PZ generate (T1.5):** `guard_pz_requires_sad` + `agency_sad_decision.safe_to_run_pz`. ✅ gated.
- **Proforma post/convert (T2.2/T2.3):** approved-state + export prereqs + manual confirmation token + `proforma_invoice_links` idempotency. ✅ gated.
- **Inventory (T4.3–T4.6):** evidence gates + `inventory_state_engine.transition()` + idempotency_key. ✅ gated.
- **Email/followup (IB.4):** Lesson-E guards (execution-time validation, terminal-state suppression, replay safety). ✅ gated.
- **Reason source:** readiness `.message` is backend-authoritative (good) — **but** blocking reasons are also independently derived in sales_linkage + proforma preview (T3.4), and some UI disable reasons are hardcoded (T3.5).

## 9. Endpoint audit
All WF write endpoints carry `dependencies=[_auth]` and a domain guard. Read endpoints (`/dashboard/batches/{id}`, `/batch/{id}/readiness`, `/agents/decision/{id}`, `/tracking/.../timeline`, `/warehouse/audit/{id}`, `/sales/linkage/{id}`, `/action-proposals/{id}`) are reachable read-only. No endpoint a button calls was found missing. wFirma-write endpoints exist and are flag-gated (`WFIRMA_CREATE_*`).

## 10. Duplicate authority findings
1. **T3.4 blocking reasons** — duplicated across `sales_linkage`, `batch_readiness`, proforma-preview (can disagree). **WRONG AUTHORITY.**
2. **PZ status** — frontend `mapPzStatus` vs backend `_compute_effective_pz_status` (WF1).
3. **USD 2500 threshold constant** — defined in `routes_upload.py:49`, `active_shipment_monitor.py:762`, `clearance_decision.py`, `routes_dsk.py` (T1.7).
4. **Row counts (corroborating, from prior audit P21)** — ≥5 independent packing-row-count sources.

## 11. Unsafe or missing gates
- **UNSAFE WRITE: none found.** Every financial/customs/inventory write is gated.
- **MISSING gate-of-record:** IB.3 inbox bulk actions have no backend/audit at all (decoration).
- **Authority gap:** T3.4 (no single blocking-reason authority); T3.5 (hardcoded UI disable reasons).

## 12. Test evidence (read-only)
WF-relevant suite (10 files, run from `service/`): **153 passed, 84 failed.** Failures classified (none are WF-logic regressions):
- **79 failed = stale dashboard.html source-grep** — `test_dashboard_readiness_ui.py` (64) + `test_dashboard_sales_linkage_panel.py` (15): assert pre-Atlas-V2 dashboard structure that the migration changed. **= known backlog Issue #400 / OQ-NEW-4.**
- **5 failed = environment** — `test_batch_readiness_endpoint.py` `TestWfirmaCreated/Ready`: return `not_configured` because **wFirma API credentials are absent in this read-only verification env** (`"wFirma API credentials not configured"`). Expected under the no-mutation posture; not a defect.
- **PASSED (functional WF logic):** inventory move/state, global-PZ execution/push, closure-eval authority, audit proforma-converted, correction-registry, dhl-readiness, non-wFirma batch-readiness.

## 13. Browser evidence
Not re-captured this run (read-only source verification). Corroborating live render evidence from prior sessions: dashboard kanban renders 25 real batches with data-bound lanes/KPIs (DB.1/DB.3); shipment-detail stepper + readiness vary per batch; documents/readiness endpoints return 200 with real payloads. Full live render of WF write paths intentionally **not** exercised (no mutation).

## 14. Required fixes, ranked by priority
1. **P1 — Unify blocking-reason authority (T3.4 WRONG AUTHORITY).** One backend resolver feeds readiness + sales_linkage + proforma preview. Highest risk: operators see contradictory blockers.
2. **P1 — Single PZ-status authority.** Make frontend render backend `_compute_effective_pz_status`; delete `mapPzStatus` local computation.
3. **P2 — IB.3 inbox bulk actions:** WIRE to a persist endpoint or HIDE (remove the "Backend pending" disabled buttons from primary UI).
4. **P2 — T3.5:** route every disabled-button reason through a backend field; remove hardcoded UI reasons.
5. **P3 — T1.7:** consolidate the `2500` threshold into one constant/module.
6. **P3 — Operator-button gaps:** add Run-Pre-check (or document it's automatic), Proforma New-Draft, dashboard Warehouse-Scan; decide whether Convert-to-Invoice stays intentionally token-gated (recommend: keep token-gated, add a guarded UI affordance with confirm).

## 15. Next exact campaign after verification
**Campaign: "Single Authority for Readiness & Status" (authority-consolidation, not feature work).**
- Scope: one `derive_blocking_reasons(audit)` + one `derive_pz_status(audit)` backend resolver; readiness/sales/proforma/PZ surfaces become dumb renderers of it (extends the established `derive_*_authority` pattern in memory).
- Then: IB.3 wire-or-hide; 2500-constant consolidation; operator-button gaps.
- Gate every PR via reviewer-challenge + the 7-agent deploy gate (financial/customs surfaces). No live wFirma/DHL/customs/inventory mutation without explicit per-surface authorization.
- Re-run this verification (and a real ATLAS map if one is provided) after consolidation to confirm T3.4 → VERIFIED.

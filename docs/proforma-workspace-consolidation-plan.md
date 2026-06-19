# Proforma Workspace Consolidation — Implementation Plan

**Author:** senior backend architect pass (autonomous inspection)
**Date:** 2026-06-16
**Status:** PHASE 2 DELIVERABLE — plan only. **No implementation code written.** Execution is gated (see §0.3, §16).
**Scope:** Consolidate `Shipment → Mapping → Draft → AWB → Post` into one Proforma Workspace with a workflow state machine, conflict-detection layer, and idempotent reservation/AWB/wFirma integration — **without crossing service authority boundaries**.

> **Update 2026-06-16 — decisions locked.** Operator selected: **(1) Architecture = Option A (orchestration-shell)** → **[ADR-029](../.claude/adr/ADR-029-proforma-workspace-orchestration-shell.md)** filed (Accepted); **(2) Reservation (OQ-NEW-14) = Activate `routes_reservations.py`** — register the 6 endpoints + `reservation_queue` and reconcile with `wfirma_reservation_drafts` in the reservation PR (this **overrides** the earlier architect "retire" recommendation); **(3) Next step = draft ADR (done).**
>
> **Binding reconciliations from existing ADRs** (discovered during ADR review — they refine §6/§7 below): conflict detection is **advisory / inbox by default** per ADR-025 soft-validation — reuse the rule-based-reverification + action-proposal inbox; the `proforma_conflicts` store is a **typed extension**, not a parallel authority. Master-drift detection reuses the **cached-snapshot-in-draft-row** pattern (ADR-022) and honors **no pre-gate wFirma I/O** (ADR-021). AWB extends the **carrier scaffold + `dispatch_record`** and `carrier_api_status` is **4-state** (pending/shadow/sandbox/live) per ADR-026. The workspace lives in **Track-1 `/dashboard/proforma-v2.html`** — not the Track-2 `/v2/` shell (ADR-028). The only **hard** gate is the wFirma write flag; `conflict_posting_blocker` elevates error-severity conflicts at that write boundary only (ADR-025 "soft workflow gates + hard write gates"). §16 decisions **1–2 resolved**; 3–5 remain.

---

## 0. Executive summary

### 0.1 The single most important finding

**This is ~80% an integration campaign, not a greenfield build.** Phase-1 inspection (5 read-only agents, file:line cited throughout) shows the primitives already exist:

| Capability the brief asks to "build" | Already exists? | Evidence |
|---|---|---|
| Proforma state machine | **YES** | `draft_state`: draft/editing/approved/posting/posted/post_failed/cancelled/superseded — `proforma_invoice_link_db.py` (`start_post`/`mark_post_succeeded`/`mark_post_failed`) |
| wFirma post idempotency | **YES** | Two guards: pre-flight `wfirma_proforma_id` check (`routes_proforma.py:6874`) + state-machine guard in `start_post` (`proforma_invoice_link_db.py:3144`). Gate `wfirma_create_proforma_allowed=False` (`config.py:269`) |
| AWB idempotency | **YES (batch-scoped)** | SHA-256 of `{batch_id,shipper_account,weight_kg,declared_value,currency}`, persisted in `carrier_shipments.db`; coordinator dedups before adapter call (`carrier/coordinator.py:128`) |
| Inventory reservation persistence | **YES (×2)** | `wfirma_reservation_drafts`/`_lines` (`wfirma_db.py:98/116`, written by `get_reservation_preview`) **and** `reservation_queue` (`reservation_db.py:89`) |
| Inventory authority + state engine | **YES** | `inventory_state_engine.py` — explicit states, `transition()` guards, `inventory_state_events` append-only audit |
| Conflict / drift detection | **PARTIAL** | `blocking_reasons`/`export_blockers` (preview gate), `is_audit_stale` (schema drift), `wfirma_product_compare` (product drift), `wfirma_customer_sync.plan_sync` (customer conflicts, never auto-resolved), ADR-027 VAT drift warning |
| Audit/event store | **YES (×3)** | `timeline.log_event()` (per-batch `audit.json`), `write_audit()`/`audit_safe()` (`master_audit.sqlite`, has before/after/diff/actor/reason), `_append_audit()` (JSONL runtime flags) |
| Customer mapping authority | **YES** | 4-level chain in `_resolve_customer()` (`routes_proforma.py:381`); `bill_to_contractor_id` canonical |
| Feature-flag mechanism | **YES** | pydantic-settings in `config.py`; frontend reads via `GET /api/v1/wfirma/capabilities` (no dedicated flags endpoint) |

**Net-new work is therefore narrow:** (1) a **conflict-detection layer** that composes the existing partial validators into one store + scan; (2) an **orthogonal `workflow_stage`** on the draft (Reserved / AWB-Generated) layered above the existing posting state machine; (3) **proforma-scoped AWB idempotency** (today AWB is batch-scoped); (4) **frontend consolidation** of the workspace; (5) wiring a flag-gated **conflict posting blocker** into the existing post path. Everything else is reuse.

### 0.2 Three blockers that must be resolved before any code (operator decisions)

1. **🔴 Lesson F architecture conflict (LOCKED-decision contradiction).** The brief wants one Proforma Workspace that drives inventory, AWB, *and* wFirma. But `docs/v2-architecture-plan.md` §2/§9 **explicitly forbids** the proforma page from calling `/api/v1/dhl/` or `/api/v1/warehouse/`, and Lesson F mandates "ONE PAGE = ONE DOMAIN AUTHORITY." This is a direct contradiction of a **LOCKED** architectural decision + a permanent Lesson. It cannot be resolved by an engineer — it needs an **operator decision + ADR**. Options in §3.

2. **🟠 GATE 2 PR limit + dirty/retired working tree.** PROJECT_STATE shows the open queue at/near the 3-impl-PR cap (#522 needs-rebase, #498 draft, #576 docs). This repo (`C:\Users\Super Fashion\PZ APP`) is the **RETIRED, forbidden** scratch clone (CLAUDE.md path guard) and is currently **dirty** (branch `fix/cn-hsn-mixed-metal-false-block`, many uncommitted files). Implementation must occur in a **clean `C:\PZ-verify` session, one session at a time**, after the PR queue is cleared. Code cannot be safely written here.

3. **🟠 Open operator questions already gate sub-scopes.** `OQ-NEW-14` (reservations: activate `routes_reservations.py` vs retire — architect recommends retire) directly determines the reservation integration approach. Two AWB pipeline gaps + one reservation workflow gap are unfiled (await approval). The `design_no` ambiguity workflow is a known "missing workflow class" that blocks PZ + proforma.

### 0.3 Recommended path

1. Resolve the three blockers (§16 decision list).
2. Land the **conflict-detection foundation** first — it is the most additive, all-flags-off, zero-blast-radius slice (new table, read-only validators, tests) and unblocks the rest. One PR, 7-agent-gated.
3. Layer `workflow_stage` + reservation/AWB delegation + posting blocker in subsequent flag-gated PRs.
4. Frontend consolidation **last** (authority-clean before visual — Lesson F priority order), behind `consolidated_workflow`.
5. Stage-roll per the brief's Phase 12 runbook; production DHL label flow stays **blocked on Phase D** (live adapter is `NotImplementedError`, `carrier/adapters/live.py:47`) and the explicit Phase-10 approval gate.

**What I am NOT doing in this turn and why:** not writing implementation code — the environment is the forbidden/dirty tree (blocker 2), the architecture needs operator sign-off (blocker 1), and the brief itself gates execution on plan approval (Phase 3: "Do not edit without explicit approval from the plan"). Writing financial/inventory/customs/logistics code under those conditions would violate CLAUDE.md gates and the brief's own safety phases.

---

## 1. Current-state architecture map (verified, file:line)

### 1.1 Proforma draft (the spine — already a state machine)
- **Route→service→persistence:** `routes_proforma.py` (huge surface) → `proforma_invoice_link_db.py` (`ProformaDraft`, SQLite `proforma_drafts`) → `proforma_links.db`.
- **States:** `draft_state ∈ {draft, editing, approved, posting, posted, post_failed, cancelled, superseded}`. `POSTABLE_STATES = {approved}`.
- **Post path:** `POST /api/v1/proforma/draft/{id}/post` (`routes_proforma.py:6827`) → preflight (settings gate, already-posted 409, zero-price guard, `check_post_readiness` HS codes, `_build_proforma_request_from_draft`, receiver preflight) → `start_post` (approved→posting) → `wfirma_client.create_proforma_draft` → verify-after-create → `mark_post_succeeded` (→posted) / `mark_post_failed` / `record_post_orphan`.
- **Idempotency:** state-based (`wfirma_proforma_id` presence + `draft_state`). **No payload hash.**
- **Audit:** `record_proforma_issued` / `_cancelled` / `_converted_to_invoice` (`audit_persist.py`) → per-batch `audit.json` timeline; draft event log in SQLite (`draft_post_started`/`_posted`/`_failed`/`_orphan`).

### 1.2 Inventory (authority = `inventory_state_engine.py`)
- States: PURCHASE_TRANSIT, WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED, SALES_TRANSIT, CLOSED, SAMPLE_OUT, RETURNED_FROM_CLIENT, RETURNED_TO_PRODUCER.
- "Available" = `count_by_state()` (`:423`) → `WAREHOUSE_STOCK` count; `PROFORMA_ELIGIBLE_STATES` (`:334`) is the proforma guard. **No `reserved` count, no valuation column** (valuation = `dual_valuation.resolve_dual_values`, frozen).
- `transition()` (`:453`): `threading.Lock` + `LEGAL_TRANSITIONS` guard + per-state guards; appends `inventory_state_events`.
- **WZ is NOT implemented** as a backend route (modelled as `WAREHOUSE_STOCK→SALES_TRANSIT` lifecycle only; `dashboard.html` marks WZ `live:false`).

### 1.3 Reservation (two systems; routes partly dead)
- **System A:** `wfirma_reservation.get_reservation_preview()` writes `wfirma_reservation_drafts`/`_lines`; registered via `routes_wfirma_reservation` (main.py:56/456); live create + idempotency in `wfirma_reservation_create.py` (UNIQUE(batch_id,client_name), `mark_draft_submitting` race guard).
- **System B:** `reservation_db.reservation_queue` (UNIQUE `queue_key`); DB initialized at startup (main.py:177) but **`routes_reservations.py` NOT registered** → 6 dead endpoints (`OQ-NEW-14`).

### 1.4 AWB / DHL (authority = `carrier/coordinator.py`)
- **Flow A (shipment/AWB):** `POST /api/v1/carrier/{batch_id}/shipment` → `CarrierCoordinator.create_shipment` → adapter (shadow=`SIM-*`; live=`NotImplementedError`). Idempotency key = SHA-256 of `{batch_id,shipper_account,weight_kg,declared_value,currency}` keyed by **batch_id**; persisted `carrier_shipments.db`. Gate `CARRIER_API_STATUS` (pending/shadow/live) + `CARRIER_LIVE_ALLOWLIST` + DHL creds.
- **Flow B (label package):** `POST /api/v1/carrier/{batch_id}/label-package` → `doc_package.assemble_label_package` (PDF/ZIP). **No idempotency.**
- AWB string from inbound parcels stored in `audit.json["awb"]`. **No `awb_generated` timeline event** is emitted on create.

### 1.5 wFirma writes (authority = `wfirma_client.py` `_http_request`)
- Post gate `wfirma_create_proforma_allowed=False`; convert gate `wfirma_create_invoice_allowed=False`. Convert idempotency = `UNIQUE(proforma_id)` on `proforma_invoice_links`. Governance: invoice issuance = `HUMAN_APPROVAL_REQUIRED` (env flag + confirm token + `X-Operator`).

### 1.6 Conflict/drift (partial — compose, don't reinvent)
`blocking_reasons`/`export_blockers` (preview, `routes_proforma.py:655-1190`); `cache_freshness.is_audit_stale`; `wfirma_product_compare` (adopt_as_is/operator_review); `wfirma_customer_sync.plan_sync` (conflict count); `proforma_draft_sync` design_no ambiguity; ADR-027 VAT drift warning. **No general "draft vs master changed-since" store** — that is the net-new core.

### 1.7 Audit (reuse `master_audit.sqlite`)
`write_audit()`/`audit_safe()` (`core/audit.py:177/338`) → `master_audit` table: `entity, pk, op, actor, request_id, reason, before_json, after_json, diff_json, created_at`; `op ∈ {create,update,upsert,delete,soft_delete,restore,hard_delete,transition}`. **This is the ideal home for conflict-detection/resolution audit** — it already has before/after/actor/reason.

### 1.8 Feature flags
Static in `config.py` (pydantic-settings, env = UPPERCASE). Frontend reads via `GET /api/v1/wfirma/capabilities` (`wfirma_capabilities.get_capabilities`) → `caps.flags.*`. Restartless runtime-flip exists but **only for 17 DHL self-clearance flags** (`routes_admin_runtime_flags.py`).

---

## 2. Authority ownership map (Phase 9 — confirmed against code)

| Domain | Authority module (code) | Workspace may | Workspace must NOT |
|---|---|---|---|
| Proforma workspace state + doc edits | `proforma_invoice_link_db.py`, `routes_proforma.py` | own `workflow_stage`, line/header edits | redefine VAT, mutate inventory, write wFirma payload shape |
| Customer Master | `customer_master_db.py` | **read** for conflict checks; write `bill_to_contractor_id` onto draft | edit CM records (schema frozen) |
| Product Master | `wfirma_products`/`product_descriptions`/`product_local`, `wfirma_product_compare.py` | **read** SKU/HS/origin/UOM/status | overwrite product master (description engine frozen) |
| Inventory | `inventory_state_engine.py` | call reservation service; **read** `count_by_state` | direct UI mutation; bypass `transition()`; touch valuation |
| AWB/DHL | `carrier/coordinator.py` | request labels via coordinator (idempotent) | bypass `CARRIER_API_STATUS` gate; build live labels (Phase D) |
| wFirma posting | `wfirma_client.py` | call existing `/post` + `/to-invoice` | change payload semantics; bypass write gates / confirm token |
| Shipment | intake/routes_upload | remain parent container | become the operational editor (moves into workspace) |

---

## 3. The Lesson F conflict — resolution options (ADR required)

The brief's Phase 9 **respects** service authority (workspace delegates to each service's API). The contradiction is purely **frontend layer geography**: the V2 plan forbids one page from calling DHL/warehouse APIs. Options:

| Option | Description | Pros | Cons | Governance |
|---|---|---|---|---|
| **A — Orchestration-shell ADR (recommended)** | Proforma Workspace is an explicit *orchestration shell* that delegates to each service's API via `pz-api.js` transport; business legality stays backend-authoritative; `pz-state.js` normalizes only; conflict logic is a domain component in `pz-components.js`, never in `dashboard-shared.js`. | Delivers the brief's UX; keeps backend authority intact; one workspace | Requires **amending the locked V2 plan** via a new ADR + operator sign-off | New ADR "Proforma Workspace as orchestration shell"; reviewer-challenge waiver recorded in PROJECT_STATE DECISIONS |
| **B — Separate pages + shared workflow rail** | Keep proforma-v2 / pz-v2 / shipment-v2 separate (Lesson-F-pure); add a persistent "workflow rail" that links steps and surfaces conflicts cross-page. | Zero Lesson F change | Not a single page; more navigation (the pain the brief targets) | Compliant as-is |
| **C — Full V2 plan rewrite** | Re-architect V2 around workflows not domains. | Cleanest long-term | Largest blast radius; re-opens a closed architecture | Heavy; not recommended now |

**Recommendation: Option A**, gated on operator approval + ADR, because it satisfies the brief while preserving every backend authority boundary. Until approved, no workspace-consolidation frontend code is written.

---

## 4. Workflow state machine (Phase 5) — additive, do NOT overload `draft_state`

The existing `draft_state` already governs the **posting** lifecycle and carries the wFirma idempotency guard. Overloading it with Reserved/AWB-Generated would risk the frozen post path. **Design: add an orthogonal `workflow_stage` column** (additive, nullable, default `draft`) that gates *reaching* the posting states.

```
workflow_stage:  draft → reserved → awb_generated → ready_to_post → (post handoff)
draft_state:     draft/editing ─────────────────────→ approved → posting → posted
proforma_invoice_links:                                                    → converted
```

| Brief state | Implemented as | Transition guard (where) |
|---|---|---|
| Draft | `workflow_stage=draft` (`draft_state` draft/editing) | — |
| Reserved | `workflow_stage=reserved` | batch inventory validation passes → reservation intent persisted via **Inventory/Reservation Service** (no UI mutation). Guard in new `proforma_workflow.advance_to_reserved()` |
| AWB Generated | `workflow_stage=awb_generated` | recipient + ship-to + parcel + service checks pass; AWB via carrier coordinator (idempotent). Guard in `proforma_workflow.advance_to_awb()` |
| Ready to Post | `workflow_stage=ready_to_post` ⇒ existing `approve` (`draft_state=approved`) | document validation passes (existing `check_post_readiness` + conflict scan = no unresolved errors when `conflict_posting_blocker` on) |
| Posted | existing `draft_state=posted` | existing `start_post` preflight (unchanged — frozen) |
| Converted to Invoice | existing `proforma_invoice_links` issued | existing convert path (unchanged) |

**Reversibility:** `release reservation` returns `awb_generated|reserved → draft` (per Phase 6 "unless reservation released"). `Posted`/`Converted` are read-only except allowed output actions. Transitions emit `master_audit` rows (op=`transition`).

---

## 5. Feature flags (Phase 8)

Add to `service/app/core/config.py` (established pydantic-settings pattern) and expose through `GET /api/v1/wfirma/capabilities` (`wfirma_capabilities.get_capabilities`) so the frontend reads them the existing way.

| Flag key (env = UPPER) | Initial | Controls |
|---|---|---|
| `toolbar_v2` | `false` | new workspace toolbar |
| `shipping_summary` | `false` | shipping summary panel |
| `consolidated_workflow` | `false` | the workspace state machine + single-page flow |
| `conflict_detection_enabled` | `false` | run validators + persist conflicts |
| `conflict_ui_mode` | `"panel"` (staging) | `inline` vs `panel` rendering |
| `conflict_resolution_auto_use_defaults` | `false` | auto-apply master defaults (kept off) |
| `conflict_posting_blocker` | `false` early staging → `true` pre-prod | error-level conflicts block `/post` |

**Recommendation:** add `conflict_posting_blocker` (and `conflict_detection_enabled`) to the **runtime-flip allowlist** (`routes_admin_runtime_flags._ALLOWED_FLAGS`) so staging can toggle without restart, with the existing JSONL audit trail. All flags default OFF ⇒ rollback = flip off (and remove files).

---

## 6. Conflict-detection layer (the net-new core)

### 6.1 Conflict store — new `proforma_conflict_db.py` → `proforma_conflicts` table (additive)

Exact fields from the brief (all persisted):

`conflict_id` (PK), `proforma_id`, `conflict_type`, `severity` (`error|warning`), `authority_owner`, `field_affected`, `current_value`, `master_value`, `reason`, `detected_at`, `status` (`open|acknowledged|resolved|reverted`), `resolution_type` (`use_master_default|override_with_reason|regenerate_lines|accept_and_proceed|revert`), `resolution_reason`, `resolved_by`, `resolved_at`.

Every detection and every resolution **also** writes `master_audit` via `audit_safe()` (op=`create` on detect, `update`/`transition` on resolve) with before/after — reusing the existing audit authority (no new audit system).

### 6.2 Validators — compose existing primitives (new `proforma_conflict_detector.py`)

| # | conflict_type | severity | authority_owner | Source of truth (reuse) |
|---|---|---|---|---|
| 1 | `inventory_insufficient` | error | Inventory Service | `inventory_state_engine.count_by_state` / `PROFORMA_ELIGIBLE_STATES` + reservation status |
| 2 | `sku_missing_or_discontinued` | error | Product Master | `wfirma_products.sync_status` (`not_found`) + product status; `wfirma_product_compare` |
| 3 | `currency_vs_customer_default` | warning | Customer Service | `customer_master.default_currency` vs draft `currency` |
| 4 | `bank_account_currency_unsupported` | error | Proforma/Finance | `COMPANY_ACCOUNT_BY_CURRENCY` (`proforma_resolver.py`) vs draft currency |
| 5 | `customer_vat_eu_changed` | warning→error | Customer Service | re-run `vat_resolver.pick_vat_code` vs draft `vat_context`/`vat_code` (ADR-027 drift warning already exists) |
| 6 | `customer_address_or_terms_changed` | warning | Customer Service | `customer_master` vs draft overrides (`wfirma_customer_sync.plan_sync` model) |
| 7 | `product_hs_origin_uom_changed` | warning | Product Master | `product_local`/`product_descriptions` vs draft line; `wfirma_product_compare` |
| 8 | `service_charge_defaults_changed` | warning | Customer Service | `customer_master` service-charge defaults vs draft `service_charges_json` |

Detector is **read-only** against all master data. Runs on demand (`/conflicts/scan`), before each `workflow_stage` transition, and immediately before `/post`.

### 6.3 New routes (additive, flag-gated by `conflict_detection_enabled`)
- `POST /api/v1/proforma/draft/{id}/conflicts/scan` — run validators, upsert conflicts, return list.
- `GET  /api/v1/proforma/draft/{id}/conflicts` — list current.
- `POST /api/v1/proforma/draft/{id}/conflicts/{conflict_id}/resolve` — body: `resolution_type`+`resolution_reason`; audited.

### 6.4 Post-path wiring (additive, flag-gated by `conflict_posting_blocker`)
In `routes_proforma.py` post handler, **before** `start_post`: if `conflict_posting_blocker` and any `status=open severity=error` conflict exists → 409 with conflict list. Warnings pass only if `status=acknowledged` (logged). The existing preflight + state guard are untouched (frozen payload path).

---

## 7. Idempotency strategy

| Action | Today | Required change |
|---|---|---|
| **AWB** | SHA-256 of `{batch_id,shipper_account,weight,value,currency}`, keyed by batch_id (`carrier/models/shipment.py:64`) | Add **proforma-scoped** key = `sha256(proforma_id + recipient_hash + parcel_config)` in new `awb_proforma_bridge.py`; map `proforma_id→awb`; persist on draft (`awb_idempotency_key`, `awb_number`). Add idempotency to **Flow B** label-package (currently none). Delegate through coordinator — do not bypass gate. Live DHL blocked on Phase D. |
| **wFirma post** | State-based (`wfirma_proforma_id` + `draft_state`) — robust | Keep as authority. **Add** `payload_hash` recorded at approve time (additive column) as defense-in-depth + payload-drift conflict detection. **Do not** change payload semantics (frozen). |
| **Reservation** | UNIQUE(batch_id,client_name) + `mark_draft_submitting` race guard | Reuse; persist reservation intent + `workflow_stage=reserved`. (Approach depends on `OQ-NEW-14`.) |
| **Convert** | UNIQUE(proforma_id) | Reuse unchanged. |

---

## 8. Per-artifact change ledger

Each row answers the brief's required questions: current state · what it does · route→service→persistence · changes · authority · tests · flags · idempotency/audit. `CREATE` = new file, `MODIFY` = additive edit, `READ-ONLY` = inspected dependency.

### 8.1 Backend — services
| File | Action | Today | Change | Authority/idempotency/audit |
|---|---|---|---|---|
| `service/app/services/proforma_conflict_db.py` | CREATE | — | `proforma_conflicts` table + CRUD (`upsert_conflict`, `list_conflicts`, `resolve_conflict`) | additive table; every write → `audit_safe()` |
| `service/app/services/proforma_conflict_detector.py` | CREATE | — | 8 validators (§6.2), read-only against masters | reads only; no master writes |
| `service/app/services/proforma_workflow.py` | CREATE | — | `workflow_stage` transitions + guards; delegates to reservation/AWB services | guards emit `master_audit` op=transition |
| `service/app/services/awb_proforma_bridge.py` | CREATE | — | proforma-scoped AWB idempotency key + delegate to `CarrierCoordinator` | new key; persists `awb_idempotency_key` |
| `service/app/services/proforma_invoice_link_db.py` | MODIFY | draft schema + post state machine | **additive nullable** cols: `workflow_stage`, `payload_hash`, `awb_idempotency_key`, `awb_number`; migration idempotent | post guard untouched (frozen) |
| `service/app/services/wfirma_reservation.py` / `reservation_db.py` | READ-ONLY/MODIFY (per OQ-NEW-14) | reservation persistence | wire reservation intent to workflow | depends on OQ-NEW-14 decision |
| `service/app/services/carrier/coordinator.py` | READ-ONLY | AWB idempotency + state | called via bridge; **not modified** | existing key/audit |
| `service/app/services/dual_valuation.py`, `vat_resolver.py`, `wfirma_client.py` payload builders | READ-ONLY (FROZEN) | valuation / VAT / payload | **no edits** — read only | §12 approval gate |

### 8.2 Backend — routes
| File | Action | Change |
|---|---|---|
| `service/app/api/routes_proforma.py` | MODIFY | add `/conflicts/scan`, `/conflicts`, `/conflicts/{id}/resolve`, `/reserve`, `/awb`; insert flag-gated conflict-blocker check before `start_post` (additive) |
| `service/app/api/routes_admin_runtime_flags.py` | MODIFY | extend `_ALLOWED_FLAGS` with `conflict_detection_enabled`, `conflict_posting_blocker` |
| `service/app/services/wfirma_capabilities.py` | MODIFY | expose new flags in capabilities response |
| `service/app/core/config.py` | MODIFY | add 7 flags (§5), all default off/panel |
| `service/app/main.py` | MODIFY (conditional) | register `routes_reservations` **only if** OQ-NEW-14 = Option A |

### 8.3 Frontend (Option A only; behind `consolidated_workflow`/`toolbar_v2`)
| File | Action | Change (layer-bound) |
|---|---|---|
| `service/app/static/proforma-v2.html` | MODIFY | workspace shell: packing/config/reservation/AWB/post sections; single `ReactDOM.render`; URL-param state |
| `service/app/static/proforma-detail-v2.html` | MODIFY | detail surface alignment |
| `service/app/static/pz-api.js` | MODIFY | transport for conflict/reserve/awb endpoints — **transport only** |
| `service/app/static/pz-state.js` | MODIFY | normalize conflict/stage data — **no business rules** (no local `ready` compute) |
| `service/app/static/pz-components.js` | MODIFY | `WorkflowStepper`, `ConflictBadge`, `ConflictPanel` — domain-aware components live here |
| `service/app/static/dashboard-shared.js` | **NO domain edits** | only if a pure visual atom is needed; **never** gains conflict/inventory/wFirma semantics (Lesson F Rule 1) |

### 8.4 Schema/migration files
`proforma_invoice_link_db.py` (additive cols, idempotent `ALTER`/create-if-missing — **no NOT NULL** per rollback rule); new `proforma_conflict_db.py` table. No `*.db` files committed (forbidden-paths). No changes to PZ/valuation/customer-master/product-master schemas (frozen).

---

## 9. UI state matrix (Phase 6)

| Field group | Draft | Reserved | AWB Generated | Posted |
|---|---|---|---|---|
| customer / buyer / recipient / ship-to | ✏️ | 🔒 (customer); recipient ✏️ until AWB | 🔒 | 🔒 |
| currency / bank account / payment terms | ✏️ | 🔒 (price-affecting) | 🔒 | 🔒 |
| service charges | ✏️ | 🔒 unless reservation released | 🔒 | 🔒 |
| packing line items (SKU/qty) | ✏️ | 🔒 unless released | 🔒 | 🔒 |
| AWB settings / parcel / service | ✏️ | ✏️ | 🔒 | 🔒 |
| reservation intent | ✏️ | release-only | release-only | 🔒 |
| accounting/commercial | ✏️ | ✏️ (non-price) | ✏️ (non-price) | 🔒 all |

Locks are **enforced backend-side** (route rejects edits illegal for `workflow_stage`); UI disables with a reason string (never hides — Lesson M five-state model).

## 10. Conflict-resolution UI (Phase 7, behind `conflict_detection_enabled` + `conflict_ui_mode`)
- **Inline:** `ConflictBadge` beside the affected field naming the authority owner ("Inventory Service shows available 3, requested 5").
- **Panel:** right-side `ConflictPanel` grouped by Inventory / Customer / Product / Currency / Service charges.
- **Actions:** Use master default · Override + document reason · Regenerate lines from fresh packing · Accept + proceed · Revert to last saved. Each → `/conflicts/{id}/resolve` (audited). Error-level unresolved blocks post when blocker on.

## 11. Testing strategy (Phase 11) — thinnest coverage is reservation + cross-workflow (per inspection)
**New test files** (live under `service/tests/`):
- `test_proforma_conflict_db.py`, `test_proforma_conflict_detector.py` (one per `conflict_type`, incl. negative/no-conflict cases), `test_proforma_conflict_routes.py`
- `test_proforma_workflow_stage.py` (every transition + illegal-transition raises + reversibility)
- `test_awb_proforma_idempotency.py` (duplicate request → same AWB; Flow-B dedup)
- `test_proforma_post_conflict_blocker.py` (error blocks, warning passes when acknowledged, flag-off no-op)
**Happy path (e2e, mocked):** upload→config→reserve→AWB(shadow)→post→convert with no shipment back-nav.
**Edge:** insufficient inventory; discontinued SKU post-packing; VAT changed; terms changed; currency/bank mismatch; CM service charges changed; wFirma rejection; AWB/wFirma duplicate; concurrent reservation; posted lock.
**Regression (flags OFF):** `tests/test_pz_*.py` (221), `tests/test_carrier_*.py` (412), `test_proforma_*`, `test_vat_resolver.py`+`test_adr027_*`, `test_wfirma_*`, `test_inventory_*` all green. Deploy gate per `.claude/contracts/test-baseline.md`.

## 12. Safety gates / frozen list (Phases 3 + 10) — explicit approval required to touch
PZ valuation engine · `dual_valuation` inventory valuation · `vat_resolver` · `wfirma_client` payload builders · production posting gates (`wfirma_create_*_allowed`) · DHL **production** label generation (`carrier/adapters/live.py`, Phase D). **This plan touches none of them** — all integration is additive and delegates to them read/gated.

## 13. PR sequencing (respects GATE 2 ≤3 impl PRs, 7-agent deploy gate, clean `C:\PZ-verify`)
0. **Pre-req:** clear PR queue to ≤2; resolve §16 decisions; (Option A) write ADR.
1. **PR-1 Conflict foundation** — `proforma_conflict_db` + detector + routes + flags (all OFF) + tests. Zero behavior change. 7-agent gate.
2. **PR-2 Workflow stage** — additive cols + `proforma_workflow` + reserve/AWB delegation + idempotency + tests (flags OFF).
3. **PR-3 Post blocker wiring** — flag-gated conflict blocker before `start_post` + tests.
4. **PR-4 Frontend workspace** (Option A) — behind `consolidated_workflow`/`toolbar_v2`; browser-verified (GATE 6).
Each PR independently revertible (flags off / file removal).

## 14. Deploy runbook (Phase 12) + rollback
Deploy flags OFF → enable `toolbar_v2`, `shipping_summary`, `consolidated_workflow` (staging test users) → `conflict_detection_enabled` panel-only, blocker OFF → review false positives/latency → blocker ON staging → ops pilot → selected prod users → full rollout only after **zero duplicate AWB/wFirma incidents** + no unresolved critical conflict bugs. **Rollback:** flip `conflict_detection_enabled`, `consolidated_workflow`, `shipping_summary`, `toolbar_v2` off in sequence; remove V2 files; existing Proforma/Shipment flows stay reachable; first migration uses **nullable** columns only.

## 15. Governance compliance matrix
| Rule | Honored by |
|---|---|
| No auto wFirma write from upload | upload path untouched; post stays behind `wfirma_create_proforma_allowed` + confirm token |
| No auto customer/product overwrite from packing | detector is read-only; conflicts surface, never auto-write masters |
| No UI-only inventory mutation | reservation routed through Inventory/Reservation Service; UI disables, backend enforces |
| No duplicate AWB / wFirma | proforma-scoped AWB key (§7) + existing state guard; convert UNIQUE(proforma_id) |
| All overrides auditable | `master_audit` before/after on every detect + resolve |
| Errors block post when blocker on; warnings need ack+log | §6.4 |
| Masters remain source of truth | CM/Product/Inventory read-only; VAT backend-resolved (no per-line editor) |
| Discount not faked | effective-unit-price only unless a separate approved schema campaign (per existing UX spec §4.6) |

## 16. Open decisions (BLOCKERS — operator)
1. **Architecture (§3):** approve Option A (orchestration-shell ADR) / B (separate + rail) / C (rewrite)? *Rec: A.*
2. **Reservation (OQ-NEW-14):** activate `routes_reservations.py` (Option A) / retire + build intent on `wfirma_reservation_drafts` (Option B, architect-rec)?
3. **Execution location & timing:** confirm implementation moves to a clean `C:\PZ-verify` session after PR queue ≤2 (no code in this retired/dirty tree). *Rec: yes.*
4. **AWB live scope:** acknowledge production DHL labels are blocked on Phase D (`live.py` `NotImplementedError`) — workspace integrates shadow + label-package now?
5. **VAT/terms drift severity:** should `customer_vat_eu_changed` be error (block) or warning (ack) at post?

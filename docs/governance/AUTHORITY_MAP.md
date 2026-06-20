# AUTHORITY_MAP.md

Status: ACTIVE · Introduced 2026-06-20 · Owner: orchestrator  
Governance package: `docs/governance/anti-hold-and-completion.md` + `.claude/memory/TASK_STATE.md`

Single source of truth for **workflow ownership** across the PZ Import Processor platform.
Use this map to decide:
- Which route file owns writes for a given domain
- Which DB files a domain is allowed to read vs write
- Which locations are forbidden write targets for each domain
- Where Claude must look first when a task touches a domain boundary

**How to use**: Before any implementation that writes to a DB or calls a service, identify
the domain, confirm the write target is listed under "Write targets", and confirm no
forbidden target is being crossed. Cross-domain writes require explicit coordination
through the authority chain (see §10 for worked examples).

---

## Domain index

| # | Domain | Authority route | Primary DB |
|---|--------|----------------|-----------|
| 1 | [Proforma](#1-proforma) | `routes_proforma.py` | `proforma_*_db.sqlite` |
| 2 | [DHL](#2-dhl) | `routes_dhl_clearance.py` | `tracking_db.sqlite` · `carrier/persistence/` |
| 3 | [PZ](#3-pz) | `routes_upload.py` · `routes_wfirma.py` | `audit.json` · `outputs/` |
| 4 | [Customer Master](#4-customer-master) | `routes_customer_master.py` | `customer_master.sqlite` |
| 5 | [Product Master](#5-product-master) | `routes_master_data.py` | `master_data.sqlite` |
| 6 | [Shipment Master](#6-shipment-master) | `routes_intake.py` | `audit.json` · batch filesystem |
| 7 | [Inventory](#7-inventory) | `routes_inventory_writes.py` | `warehouse.db` |
| 8 | [Audit / Evidence](#8-audit--evidence) | `routes_correction_registry.py` | `audit.json` · `correction_registry.db` |
| 9 | [wFirma](#9-wfirma) | `routes_wfirma.py` · `routes_wfirma_reservation.py` | `wfirma.db` |
| 12 | [Document / Packing Readiness](#12-document--packing-readiness-review-state-authority) | `routes_upload.py` (registry read) | `document_readiness.py` (pure, no DB) |

---

## 1. Proforma

**Lifecycle**: Draft → Preview → Issued → Adopted (converts to invoice)

### Authority owner
`service/app/api/routes_proforma.py` — owns all proforma state mutations (POST /proforma/preview, /proforma/create, /proforma/issue).  
`service/app/api/routes_proforma_adopt.py` — proforma → invoice adoption.  
`service/app/api/routes_wfirma_reservation.py` — reservation preview + live creation (extends proforma into wFirma).

### Read sources
| Source | Purpose |
|--------|---------|
| `wfirma_db.sqlite` | Customer + product mapping from wFirma |
| `packing_db.sqlite` | Invoice/packing lines and scan codes |
| `master_data.sqlite` | HS codes, units, VAT rates, FX rates |
| `warehouse.db` | Physical inventory state for availability checks |
| `customer_master.sqlite` | Customer identity + address |

### Write targets
| Target | What is written |
|--------|----------------|
| `proforma_invoice_link_db.sqlite` | Proforma ↔ invoice link (via `proforma_invoice_link_db.py`) |
| `proforma_service_charges_db.sqlite` | Per-proforma service charges |
| `wfirma_db.sqlite` → `wfirma_reservation_drafts` | Reservation drafts + lines |
| Batch `audit.json` | Proforma lifecycle events (append-only) |

### Forbidden write locations
- PZ `outputs/` — belongs to PZ domain
- DHL `tracking_db.sqlite` — belongs to DHL domain
- `warehouse.db` physical movements — belongs to Inventory domain
- `customer_master.sqlite` — belongs to Customer Master domain
- wFirma API directly — must go through `wfirma_client.py`

### Related routes
`routes_proforma.py`, `routes_proforma_adopt.py`, `routes_wfirma_reservation.py`, `routes_reservations.py`

### Related services
`proforma_draft_sync.py`, `proforma_draft_governance.py`, `proforma_intelligence.py`, `proforma_pz_recovery.py`, `proforma_conflict_db.py`, `proforma_conflict_detector.py`, `wfirma_client.py`, `customer_master.py`

### Verification authority
Proforma correctness is verified by `proforma_conflict_detector.py` (conflict guard) and `proforma_draft_governance.py` (lifecycle guard). Financial values must come from the engine (`process_batch()`) — never recomputed in routes.

---

## 2. DHL

**Lifecycle**: Document received → Customs description generated → Operator approved → SAD-ready → Clearance closed

### Authority owner
`service/app/api/routes_dhl_clearance.py` — owns customs description generation, approval, SAD-ready data, and clearance lifecycle.  
`service/app/api/routes_dhl_documents.py` — document storage and classification.  
`service/app/api/routes_dhl_followup.py` / `routes_dhl_followup_status.py` — follow-up email sequences.  
`service/app/api/routes_carrier_actions.py` — carrier shipment lifecycle (live/shadow).  
`service/app/api/routes_carrier_webhook.py` — incoming DHL webhook events.  
`service/app/api/routes_admin_dhl_clearance.py` — admin-only overrides.

### Read sources
| Source | Purpose |
|--------|---------|
| `document_db.sqlite` | Document metadata + classifications |
| `tracking_db.sqlite` | Shipment tracking events per AWB |
| `carrier/persistence/shipment_db.sqlite` | Carrier shipment idempotency state |
| `warehouse.db` | Physical warehouse state |
| `customer_master.sqlite` | Customer + recipient data |
| `master_data.sqlite` | HS codes, VAT, FX |

### Write targets
| Target | What is written |
|--------|----------------|
| `tracking_db.sqlite` | Shipment tracking events (via `tracking_db.py`) |
| `carrier/persistence/shipment_db.sqlite` | Carrier shipment state |
| `carrier/persistence/event_db.sqlite` | Carrier integration events |
| `carrier/persistence/shadow_log_db.sqlite` | Shadow mode logs |
| `document_db.sqlite` | Uploaded DHL documents + classifications |
| Batch `audit.json` | DHL clearance milestones (append-only) |

### Forbidden write locations
- PZ `outputs/` — PZ domain owns customs import artifacts
- `proforma_invoice_link_db.sqlite` — Proforma domain
- `customer_master.sqlite` — Customer Master domain owns mutations
- `warehouse.db` physical inventory — Inventory domain

### Related routes
`routes_dhl_clearance.py`, `routes_dhl_documents.py`, `routes_dhl_followup.py`, `routes_dhl_followup_status.py`, `routes_dhl_readiness.py`, `routes_carrier_actions.py`, `routes_carrier_shadow.py`, `routes_carrier_webhook.py`, `routes_admin_dhl_clearance.py`

### Related services
`dhl_clearance_coordinator.py`, `dhl_clearance_state_engine.py`, `dhl_orchestrator.py`, `dhl_followup_authority.py`, `dhl_followup_status_projector.py`, `dhl_followup_sla.py`, `awb_parser.py`, `awb_address_authority.py`, `tracking_db.py`, `tracking_service.py`, `tracking_intelligence.py`, `carrier/persistence/shipment_db.py`, `carrier/persistence/event_db.py`, `carrier/coordinator.py`, `carrier/adapters/live.py`, `carrier/adapters/shadow.py`

### Verification authority
Clearance readiness is gated by `dhl_readiness.py`. `guard_dhl_requires_email` must fire before any clearance-related write. Carrier actions use idempotency keys via `carrier/persistence/shipment_db.py`.

---

## 3. PZ

**Lifecycle**: Invoice upload → SAD/ZC429 upload → Engine processing → PZ JSON/PDF/XLSX → wFirma export

### Authority owner
`service/app/api/routes_upload.py` — SAD/ZC429 upload, PZ process trigger.  
`service/app/api/routes_wfirma.py` — PZ export to wFirma (clipboard, JSON).  
`service/app/api/routes_correction_registry.py` — operator correction memory (metadata only, no financial mutation).  
`service/app/api/routes_pz.py` — legacy health + process endpoint (deprecated for new work).

**Calculation authority**: `process_batch()` in `pz_import_processor.py` (root-level engine) is the ONLY valid calculation path for landed cost, freight allocation, duty, and totals. Routes and services must never recompute these values.

### Read sources
| Source | Purpose |
|--------|---------|
| `packing_db.sqlite` | Invoice/packing data |
| `warehouse.db` | Physical inventory state |
| `master_data.sqlite` | HS codes, VAT, FX, units |
| `customer_master.sqlite` | Customer master |
| `suppliers_db.sqlite` | Supplier reference data |
| `correction_registry.db` | Operator-approved corrections (read-only by engine) |

### Write targets
| Target | What is written |
|--------|----------------|
| Batch `audit.json` | PZ lifecycle events, append-only (via `audit_persist.py`, `timeline.py`) |
| `correction_registry.db` | Operator corrections, append-only (via `correction_registry.py`) |
| Batch `outputs/` | PZ JSON, XLSX, PDF artifacts |
| `proforma_pz_recovery.sqlite` | Proforma ↔ PZ recovery tracking |
| `pz_correction_state.sqlite` | PZ correction state |

### Forbidden write locations
- DHL `tracking_db.sqlite` — DHL domain
- `customer_master.sqlite` — Customer Master domain
- `master_data.sqlite` — Product Master domain
- wFirma API directly — must go through `wfirma_client.py` + export flow
- Financial field mutation in existing wFirma records — requires operator approval (HOLD condition)

### Related routes
`routes_pz.py`, `routes_upload.py`, `routes_wfirma.py`, `routes_correction_registry.py`, `routes_lifecycle.py` (indirect)

### Related services
`global_pz_execution.py`, `global_pz_correction.py`, `global_pz_lineage.py`, `global_pz_push.py`, `import_pz_builder.py`, `pz_correction_lifecycle.py`, `pz_correction_state.py`, `customs_parser_orchestrator.py`, `customs_xml_parser.py`, `customs_validator.py`, `audit_persist.py`, `audit_evidence.py`, `audit_merge.py`, `correction_registry.py`, `batch_service.py`, `batch_manager.py`

### Verification authority
SAD upload guards via `guard_sad_upload_ready`. Golden regression suite (`test_pz_regression.py`, 90 tests) is the canonical correctness gate. `make verify` must pass before any PZ engine change.

---

## 4. Customer Master

**Lifecycle**: Create → Upsert → Soft-delete → Restore → Hard-delete (hard-delete requires flag + admin role)

### Authority owner
`service/app/api/routes_customer_master.py` — CRUD (GET, PUT, soft-delete, hard-delete).  
`service/app/api/routes_client_addresses.py` — customer address management.  
`service/app/api/routes_client_carrier_accounts.py` — carrier account configuration per customer.

### Read sources
| Source | Purpose |
|--------|---------|
| `customer_master.sqlite` | Customer identity + metadata |
| `client_addresses_db.sqlite` | Address registry |
| `client_carrier_accounts_db.sqlite` | Carrier account per customer |
| `correction_registry.db` | Historical corrections (read-only) |

### Write targets
| Target | What is written |
|--------|----------------|
| `customer_master.sqlite` | Upsert / soft-delete / restore / hard-delete (via `customer_master_db.py`) |
| `client_addresses_db.sqlite` | Address CRUD (via `client_addresses_db.py`) |
| `client_carrier_accounts_db.sqlite` | Carrier config CRUD (via `client_carrier_accounts_db.py`) |

### Forbidden write locations
- Cascade-delete into proforma, invoice, PZ, or DHL data — forbidden
- `wfirma_db.sqlite` directly — wFirma customer data flows in one direction from wFirma via `wfirma_customer_sync.py`
- `correction_registry.db` — write-only via Correction Registry routes, not Customer Master routes

### Related routes
`routes_customer_master.py`, `routes_client_addresses.py`, `routes_client_carrier_accounts.py`

### Related services
`customer_master_db.py`, `customer_master.py`, `client_addresses_db.py`, `client_carrier_accounts_db.py`, `customer_resolution_authority.py`, `customer_commercial_profile.py`, `wfirma_customer_sync.py`, `wfirma_customer_auto_resolve.py`, `customer_invoice_snapshot_db.py` (read-only snapshots)

### Verification authority
Customer resolution is arbitrated by `customer_resolution_authority.py`. wFirma sync is one-directional: wFirma → customer master (not customer master → wFirma).

---

## 5. Product Master

**Lifecycle**: Define → Reference → Augment (product_local) → Hard-delete (rare; flag + admin role required)

### Authority owner
`service/app/api/routes_master_data.py` — CRUD for HS codes, units, product-local augmentation, incoterms, VAT, FX, carrier config, designs.  
`service/app/api/routes_master_jewelry.py` — jewelry-specific metals + stones master data.

### Read sources
| Source | Purpose |
|--------|---------|
| `master_data.sqlite` | All reference data: HS, units, VAT, FX, product-local |
| `metals_db.sqlite` | Metal purity registry |
| `stones_db.sqlite` | Gemstone HS mapping |
| `suppliers_db.sqlite` | Supplier product references (read-only) |

### Write targets
| Target | What is written |
|--------|----------------|
| `master_data.sqlite` | HS codes, units, product_local, incoterms, VAT, FX, carrier config, designs (via `master_data_db.py`) |
| `metals_db.sqlite` | Metal definitions (via `metals_db.py`) |
| `stones_db.sqlite` | Gemstone definitions (via `stones_db.py`) |

### Forbidden write locations
- `packing_db.sqlite` live packing rows — Product Master augments via `product_local` table only
- Historical invoice or PZ records — changes to master data must not cascade retroactively
- Hard-delete: requires `master_hard_delete_enabled` feature flag + `master_admin` role; never from non-admin routes

### Related routes
`routes_master_data.py`, `routes_master_jewelry.py`, `routes_box_types.py`

### Related services
`master_data_db.py`, `master_reference_checks.py`, `metals_db.py`, `stones_db.py`, `product_identity_engine.py`, `product_master_backfill.py`, `design_product_bridge.py`

### Verification authority
`master_reference_checks.py` validates cross-domain consistency (HS code ↔ VAT ↔ unit coherence). Changes to HS codes must be validated against current golden batch via `make verify` before PR.

---

## 6. Shipment Master

**Lifecycle**: Create (intake) → Documents uploaded → PZ processed → DHL cleared → Inventory updated → Closed

### Authority owner
`service/app/api/routes_intake.py` — create shipment + initial document upload.  
`service/app/api/routes_upload.py` — SAD/ZC429 upload into existing shipment.  
`service/app/api/routes_batch.py` — batch lifecycle reads; `batch_state_normalizer.py` handles state.  
`service/app/api/routes_batch_readiness.py` — readiness gate enforcement.  
`service/app/api/routes_lifecycle.py` — explicit state transitions.

### Read sources
| Source | Purpose |
|--------|---------|
| Batch filesystem (`audit.json`, `outputs/`, `source/`) | The batch is the primary record; all reads are filesystem-first |
| `warehouse.db` | Physical inventory state per shipment |
| `tracking_db.sqlite` | DHL tracking events per AWB |
| `proforma_invoice_link_db.sqlite` | Proforma ↔ invoice mapping |
| `correction_registry.db` | Operator overrides (read-only) |

### Write targets
| Target | What is written |
|--------|----------------|
| Batch `audit.json` | Append-only timeline (via `audit_persist.py`, `timeline.py`) |
| Batch `outputs/` | PZ, proforma, customs PDFs + JSON |
| `warehouse.db` → inventory_state | Inventory state transitions (via `inventory_state_engine.py`) |
| `tracking_db.sqlite` | Tracking events per AWB (via `tracking_db.py`) |
| Batch `source/copy/` | SAD/invoice copies for persistence |

### Forbidden write locations
- Batch `batch_id` field — primary key, immutable after creation
- `audit.json` historical entries — append-only; no rewrites, no deletions
- Lifecycle state jumps — must go through `inventory_state_engine.transition()`; direct DB writes that bypass the state machine are forbidden
- PZ/DHL/proforma artifact writes without corresponding audit trail entry

### Related routes
`routes_intake.py`, `routes_upload.py`, `routes_batch.py`, `routes_batch_readiness.py`, `routes_lifecycle.py`, `routes_inventory_state_engine.py` (indirect)

### Related services
`batch_service.py`, `batch_manager.py`, `batch_readiness.py`, `batch_state_normalizer.py`, `active_shipment_monitor.py`, `shipment_closure.py`, `shipment_delivered_guard.py`, `shipment_folder_manager.py`, `intake_lineage.py`, `inventory_state_engine.py`, `audit_persist.py`, `audit_evidence.py`, `audit_merge.py`, `timeline.py`

### Verification authority
`batch_readiness.py` is the readiness gate (all preconditions must pass before PZ processing). `shipment_delivered_guard.py` blocks moves on delivered shipments. Batch filesystem structure is the ground truth; `batch_service.py` owns all filesystem reads/writes.

---

## 7. Inventory

**Lifecycle**: Receive (PURCHASE_TRANSIT) → Stock (WAREHOUSE_STOCK) → Pick (SALES_TRANSIT) → Dispatch (CLOSED)

### Authority owner
`service/app/api/routes_inventory_writes.py` — metadata-only moves (POST /pieces/{piece_id}/location).  
`service/app/api/routes_inventory_sample.py` — sample-out tracking.  
`service/app/api/routes_inventory_returns.py` — return tracking.  
`service/app/api/routes_inventory.py` — read-only access (GET only).  
`service/app/api/routes_warehouse.py` — physical warehouse operations (picking, packing, dispatch).

### Read sources
| Source | Purpose |
|--------|---------|
| `warehouse.db` | Physical locations + movement events |
| `warehouse_audit.db` | Audit trail for warehouse operations |
| `packing_db.sqlite` | Packing line definitions (scan codes, product codes) |
| Batch `audit.json` | Inventory state transitions via `inventory_state_engine` |

### Write targets
| Target | What is written |
|--------|----------------|
| `warehouse.db` → `inventory_movement_events` | Append-only movement events (via `warehouse_db.py`) |
| Batch `inventory_state.json` | Current state snapshot per piece (via `inventory_state_engine.py`) |
| `warehouse_audit.db` | Audit trail of moves (via `warehouse_audit.py`) |
| Batch `audit.json` | Inventory lifecycle events (via `audit_persist.py`) |

### Forbidden write locations
- Financial values — inventory never touches landed cost, duty, VAT amounts
- `packing_db.sqlite` packing rows — inventory reads packing data but never writes it
- `audit.json` historical entries — append-only
- Idempotency key omission — every move must carry an `idempotency_key` for dedup

### Related routes
`routes_inventory.py`, `routes_inventory_writes.py`, `routes_inventory_sample.py`, `routes_inventory_returns.py`, `routes_warehouse.py`

### Related services
`inventory_state_engine.py`, `inventory_piece_view.py`, `inventory_batch_state.py`, `inventory_stage2_aggregator.py`, `inventory_location_writer.py`, `inventory_returns_writer.py`, `inventory_sample_writer.py`, `warehouse_db.py`, `warehouse_audit.py`, `warehouses_db.py`

### Verification authority
`inventory_state_engine.transition()` is the only valid entry point for lifecycle state changes. `shipment_delivered_guard.py` prevents moves on closed/delivered shipments. All moves require operator evidence (explicit action) — no auto-state transitions.

---

## 8. Audit / Evidence

**Lifecycle**: Every domain appends events → audit.json grows (append-only) → corrections append to registry → evidence is readable by all

### Authority owner
`audit_persist.py` / `timeline.py` — the only writer of `audit.json` events across all domains.  
`service/app/api/routes_correction_registry.py` — operator correction registry (append-only).  
`service/app/api/routes_warehouse_audit.py` — warehouse audit reads (GET only; writes via `warehouse_audit.py` internally).  
`email_evidence_store.py` / `email_evidence_processor.py` / `email_evidence_ingestor.py` — email evidence pipeline.

### Read sources
| Source | Purpose |
|--------|---------|
| `warehouse_audit.db` | Physical warehouse move audit |
| `correction_registry.db` | Operator corrections |
| Batch `audit.json` | Timeline events — the primary evidence record |
| Batch `inventory_state.json` | Inventory state snapshots |
| `warehouse.db` → `inventory_movement_events` | Physical moves |

### Write targets
| Target | What is written |
|--------|----------------|
| Batch `audit.json` | Append-only timeline events (via `audit_persist.py`, `timeline.py`) |
| `correction_registry.db` | Operator corrections, append-only (via `correction_registry.py`) |
| `warehouse_audit.db` | Warehouse audit trail (via `warehouse_audit.py`) |
| Email evidence store | Evidence from inbound email threads |

### Forbidden write locations
- Historical `audit.json` entries — no rewrites, no deletions, ever
- `correction_registry.db` retroactive modifications — append-only; a correction cannot modify a previous correction
- Audit writes out of chronological order — timestamps must be monotonically increasing per batch
- Bypassing audit trail for any financial or customs operation — a financial event with no audit entry is a compliance gap

### Related routes
`routes_warehouse_audit.py`, `routes_correction_registry.py`, `routes_action_proposals.py`, `routes_lifecycle.py` (indirect)

### Related services
`audit_persist.py`, `audit_evidence.py`, `audit_merge.py`, `correction_registry.py`, `warehouse_audit.py`, `email_evidence_store.py`, `email_evidence_processor.py`, `email_evidence_ingestor.py`, `email_intelligence_store.py`, `timeline.py`

### Verification authority
Audit integrity is verified by `audit_evidence.py` (evidence completeness) and `audit_merge.py` (cross-source reconciliation). An audit event is the record of truth; the UI renders from it.

---

## 9. wFirma

**Lifecycle**: Customer/product resolve → PZ_READY.json built → Reservation draft → Live create in wFirma → Confirmed → Posted

### Authority owner
`service/app/api/routes_wfirma.py` — PZ export to wFirma (clipboard, JSON modes).  
`service/app/api/routes_wfirma_reservation.py` — reservation preview + live creation.  
`service/app/api/routes_wfirma_capabilities.py` — wFirma config/capabilities check.  
`service/app/api/routes_reservations.py` — reservation state management.  
`service/app/api/routes_finance_postings.py` — payment + charge posting registry.

### Read sources
| Source | Purpose |
|--------|---------|
| `wfirma_db.sqlite` | Customer + product mapping, draft reservations |
| `master_data.sqlite` | VAT, FX, HS codes |
| `customer_master.sqlite` | Customer master |
| `packing_db.sqlite` | Packing/invoice lines |
| `finance_postings.sqlite` | Charge registry |
| Batch `outputs/PZ_READY.json` | Source of truth for PZ → wFirma export |

### Write targets
| Target | What is written |
|--------|----------------|
| `wfirma_db.sqlite` → `wfirma_reservation_drafts` + lines | Reservation drafts (via `wfirma_db.py`) |
| `finance_postings.sqlite` | Charges, postings, payments (via `finance_postings_db.py`) |
| Batch `audit.json` | wFirma events (via `audit_persist.py`) |

### Forbidden write locations
- wFirma API directly from route handlers — must go through `wfirma_client.py`
- Bypassing customer/product mapping checks — `wfirma_reservation_create.py` gates must run
- Creating financial postings with a `charge_type` outside the allowed list
- Cascade-deleting wFirma reservations — soft-delete/archive only
- Modifying a booked wFirma PZ without operator approval — this is a **HOLD** condition (legal/financial approval); see Anti-HOLD governance §2
- Overwriting `PZ_READY.json` financial values — these flow from `process_batch()` only

### Related routes
`routes_wfirma.py`, `routes_wfirma_reservation.py`, `routes_wfirma_capabilities.py`, `routes_reservations.py`, `routes_finance_postings.py`

### Related services
`wfirma_db.py`, `wfirma_client.py`, `wfirma_capabilities.py`, `wfirma_reservation.py`, `wfirma_reservation_create.py`, `wfirma_pz_notes.py`, `wfirma_customer_sync.py`, `wfirma_customer_auto_resolve.py`, `wfirma_product_registration.py`, `wfirma_product_auto_register.py`, `wfirma_product_compare.py`, `wfirma_recovery.py`, `global_pz_push.py`, `import_pz_builder.py`, `finance_postings_db.py`, `finance_dual_write.py`, `reservation_db.py`, `reservation_worker.py`

### Verification authority
wFirma API capability is checked via `wfirma_capabilities.py` before any live write. Customer resolution is mandatory before reservation creation (`wfirma_customer_auto_resolve.py`). Product registration is mandatory before line creation (`wfirma_product_auto_register.py`). Finance postings use `finance_dual_write.py` for consistency.

---

## 10. Cross-domain authority rules

### The four authority principles

**P1 — Single writer per domain.** Each domain has exactly one set of route files that may write to its primary DB(s). Cross-domain writes route through the owning domain's service layer, never directly.

**P2 — Calculation authority is the engine.** `process_batch()` in `pz_import_processor.py` is the sole calculation authority for landed cost, freight allocation, duty, and totals. No route, service, or Cliq layer may recompute these values.

**P3 — Audit trail is mandatory.** Every financial or customs operation must produce an `audit.json` timeline event via `audit_persist.py`. An operation without an audit entry is incomplete, regardless of whether the domain write succeeded.

**P4 — wFirma booking requires operator approval.** Editing a booked wFirma PZ (post-reservation) is a legal/financial operation. It is always a HOLD condition requiring operator sign-off — never autonomous.

### How Claude uses this map

When a task requires a change to domain X:

1. **Find X in this map.** Identify the authority route file(s) and the allowed write targets.
2. **Check the forbidden locations.** If the proposed change writes to a location in the forbidden list, stop and find the owning domain's route instead.
3. **Check cross-domain reads.** Reading from another domain's DB is usually fine. Writing to another domain's DB requires going through that domain's service layer.
4. **Check for HOLD conditions.** If the write would modify a booked external record (wFirma), delete production data, or send a real email, that is a HOLD — stop and surface to operator.

### Worked examples

**Example 1 — "Add a new field to the proforma PDF"**  
Domain: Proforma. Look at authority owner → `routes_proforma.py`. Allowed write targets include proforma DBs and `audit.json`. Does not touch DHL, PZ outputs, or customer master. → CONTINUE, work in `routes_proforma.py` + `proforma_draft_sync.py`.

**Example 2 — "Fix a wrong HS code on a live PZ"**  
Domain boundary: Product Master (HS code definition) + PZ (live document).  
- Changing the master HS code → `routes_master_data.py`, write to `master_data.sqlite`. CONTINUE.  
- Retroactively correcting a **booked wFirma PZ** with the new HS code → wFirma domain, POST booking state. This is a legal/financial operation. → **HOLD** (legal/financial approval required per Anti-HOLD §2).  
- Appending an operator correction to `correction_registry.db` → `routes_correction_registry.py`. CONTINUE (metadata-only, append-only).

**Example 3 — "Update customer shipping address"**  
Domain: Customer Master. Authority route: `routes_client_addresses.py`. Write target: `client_addresses_db.sqlite`. Forbidden: do not cascade-delete proforma records. → CONTINUE, work in `routes_client_addresses.py` + `client_addresses_db.py`.

**Example 4 — "Track a DHL shipment move into warehouse"**  
Domain boundary: DHL (tracking event) + Inventory (warehouse state) + Shipment Master (audit).  
- DHL tracking event → `routes_carrier_webhook.py`, write to `tracking_db.sqlite`. CONTINUE.  
- Inventory state transition (PURCHASE_TRANSIT → WAREHOUSE_STOCK) → `inventory_state_engine.transition()`. CONTINUE.  
- Audit timeline entry → `audit_persist.py`. CONTINUE.  
All three writes go through their respective authority layers — no cross-domain DB writes.

**Example 5 — "Delete a customer who has open PZ records"**  
Domain: Customer Master (deletion) + PZ (has audit.json referencing customer_id).  
- Soft-delete customer → `routes_customer_master.py`, write to `customer_master.sqlite`. CONTINUE.  
- Hard-delete: requires `master_hard_delete_enabled` flag + `master_admin` role. Check if flag is set.  
- PZ audit records referencing the customer: **do not cascade-delete**. PZ audit is append-only and belongs to the Audit domain. → Route this decision to operator if hard-delete was requested; soft-delete is always safe.

---

## 11. Gaps and open questions

| Gap | Impact | Disposition |
|-----|--------|------------|
| `finance_postings.sqlite` is schema-only (Phase 6F.1 placeholder) | Finance postings have no live write path yet | BACKEND-PENDING — Phase 6F.2 |
| `routes_pz.py` legacy process endpoint marked deprecated | New PZ triggers go through `routes_upload.py` | No new work targeting `routes_pz.py` |
| wFirma customer sync direction | One-directional: wFirma → customer master. Reverse sync (customer master → wFirma) is not implemented | PLANNED |
| Product Master hard-delete flag | `master_hard_delete_enabled` feature flag existence not verified in this audit | Confirm in `service/app/core/config.py` before implementing hard-delete |

---

## 12. Document / Packing Readiness (review-state authority)

**Lifecycle**: Document registered → extracted → review-state derived (read-time) → rendered in Document Registry

### Authority owner
`service/app/services/document_readiness.py` — pure function `derive_document_review(row, line_count, contractor_context, effective_extraction_status)` returns the per-document review verdict: `ready | needs_review | blocked | not_applicable` + a human `reason` + a stable machine `code`. No DB or network I/O — callers pass already-resolved facts.

`service/app/api/routes_upload.py` (`GET /shipment/{batch_id}/documents`) is the read surface: it enriches each `shipment_documents` row with `lines_count`, reconciles the authoritative extraction status, and attaches `review_state` / `review_reason` / `review_code` / `extraction_status_effective`.

### Read sources
| Source | Purpose |
|--------|---------|
| `document_db.shipment_documents` | Registry rows + raw parser/extraction status |
| `packing_db.packing_documents` | **Authoritative** purchase-packing extraction status (bridged by `get_packing_status_for_shipment_document`) |
| `packing_db.packing_lines` / `document_db.sales_packing_lines` / `invoice_lines` | Effective line counts |

### Write targets
| Target | What is written |
|--------|----------------|
| `shipment_documents.{parser,extraction}_status`, `requires_manual_review` | Status **write-back** at extraction time — purchase packing (intake `routes_intake.py`, reprocess `routes_packing.py`) now mirrors the sales path; purchase invoice sets `parser_status='complete'` when really extracted |

The readiness derivation itself is **read-only** — `derive_document_review` writes nothing.

### Forbidden write locations
- Financial values, customs/CIF math, wFirma records, product-code matcher state — readiness never mutates any of these (it only reads/labels)
- The frontend must not compute or invent a review state — it renders `review_state` verbatim (Lesson F rule 5: frontend reflects truth, does not produce it)

### Authority rule
The authoritative completion signal for a purchase packing list is `packing_documents.extraction_status` (packing.db), **not** the historically-stale `shipment_documents.extraction_status`. A positive effective `lines_count` is itself proof of completion. A registry row is never blank and never falsely "pending".

### Verification authority
`service/tests/test_document_readiness.py` (pure-function matrix + "never blank" invariant) and `service/tests/test_registry_review_state.py` (endpoint attaches review fields; complete-in-packing-db-but-pending-in-shipment_documents resolves to ready/needs_review).

---

## 13. Contractor-at-birth projection (PR-2, 2026-06-20)

**Authority owner**: Customer Master — `shipment_documents.client_contractor_id` is the
authoritative contractor identity, chosen by the operator at intake. No downstream system
may replace it with free-text authority.

**Projection rule**: that contractor id is carried as an **additive reference column** onto
`sales_documents`, `sales_packing_lines`, `proforma_drafts`, and `wfirma_reservation_drafts`.
It is **never** the unique/identity key — `client_name` remains the storage key on every one of
those tables (re-keying would orphan `proforma_service_charges` and break
`derive_customer_authority_for_draft`'s `client_name` join). Contractor authority is used to
*resolve a missing client_name* (via Customer Master `bill_to_name`), never to overwrite a
present one.

**Write path**: projection is centralised in `document_db.py`
(`store_sales_document` / `store_sales_packing_lines` / `replace_sales_packing_lines` /
`ensure_sales_document_id` / `get_or_create_sales_document_for_packing` derive the contractor
from the authoritative `shipment_documents` row when not explicitly supplied — merge-not-replace,
never clears a resolved value). Grouping authority lives in
`proforma_draft_sync.sync_draft_from_packing_upload`.

**Blocked draft-birth records**: `proforma_invoice_link_db.proforma_draft_birth_blocks`
(open/resolved lifecycle) — written when a sales document resolves to neither a usable
client_name nor a Customer-Master-resolvable contractor. Codes: `contractor_missing`,
`client_unresolved`, `contractor_conflict`. Read/repair surface:
`routes_contractor_projection.py` (`POST .../backfill/{batch_id}` — operator-only, local-DB
only, no wFirma/booking; `GET .../blocks/{batch_id}`).

**Forbidden**: no change to valuation / CIF / customs / PZ pricing / accounting / booking; the
reservation projection is **readiness reference only** — `ready_to_create` gating and the wFirma
API write path are unchanged (P2/P4 preserved).

---

_This map is append-only for new domains. To add a domain: follow the section template above.
To update an existing domain: amend the relevant section inline; do not remove verified facts._

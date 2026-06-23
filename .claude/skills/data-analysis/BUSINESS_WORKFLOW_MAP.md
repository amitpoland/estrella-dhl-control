# BUSINESS_WORKFLOW_MAP.md — Estrella PZ Platform

**Updated:** 2026-06-23
**Principle:** Each workflow is the unit of operational reality. Debugging starts with "which workflow broke?" not "which table is wrong?"

---

## Workflow Index

| # | Workflow | Trigger | Authority Owner | Primary DB |
|---|---|---|---|---|
| 1 | [Shipment Intake](#1-shipment-intake) | Document upload (invoices + AWB) | `document_db.py` | `documents.db` |
| 2 | [Customs Clearance](#2-customs-clearance) | ZC429/SAD email from DHL WAW | `document_db.py` + `dhl_customs_*` | `documents.db` |
| 3 | [Sales Packing](#3-sales-packing) | Customer packing list upload | `packing_db.py` | `packing.db` + `documents.db` |
| 4 | [Proforma Draft](#4-proforma-draft) | Operator initiates for a customer | `proforma_draft_sync.py` | `proforma_links.db` |
| 5 | [wFirma Posting (PZ)](#5-wfirma-posting-pz) | `wfirma_create_pz_allowed=True` + operator trigger | `pz_import_processor.py` | `documents.db` → wFirma |
| 6 | [DHL Shipment Booking](#6-dhl-shipment-booking) | Operator triggers outbound shipment | `carrier/` services | `carrier_shipments.db` |
| 7 | [Finance Posting](#7-finance-posting) | Proforma/invoice posted to wFirma | `finance_postings_db.py` | `finance_postings.sqlite` |
| 8 | [Inventory Movement](#8-inventory-movement) | Physical scan or receipt confirmation | `warehouse_receipt.py` + `inventory_state_engine.py` | `warehouse.db` + `warehouse_receipt.db` |
| 9 | [Customer Master Maintenance](#9-customer-master-maintenance) | Name resolution at proforma time or operator action | `wfirma_customer_auto_resolve.py` | `customer_master.sqlite` |
| 10 | [Freight Cost Recovery](#10-freight-cost-recovery) | Proforma generation (freight line) | `freight_resolver.py` → `pick_freight()` | `freight_history.db` |

---

## 1. Shipment Intake

**What it is:** The entry point — batch created, supplier invoices and AWB parsed, document registry populated.

**Trigger:** Operator uploads invoice PDF(s) + AWB document via API or UI. `batch_id` (UUID) created on first upload.

**Inputs:**
- Supplier invoice PDFs (one or more; from Indian exporter)
- AWB document PDF (DHL Express waybill)
- `--rate` or live NBP rate for this batch

**Authority owner:** `document_db.py` → `shipment_documents` (pivot for all documents)

**Databases touched:**
- `documents.db` → `shipment_documents` (one row per uploaded file)
- `documents.db` → `invoice_lines` (one row per line extracted from each invoice)
- `documents.db` → `awb_documents` (AWB parsed fields)
- `documents.db` → `product_descriptions` (auto-generated bilingual names if new product_code)

**External systems:**
- Anthropic Claude API (if `ai_parser_enabled=True` — fallback when PDF parser fails)
- NBP Table A API (exchange rate fetch, unless `--rate` supplied)

**Outputs:**
- `batch_id` — primary session key for all downstream workflows
- `invoice_lines` rows — FOB, qty, HSN per line
- `awb_documents` row — pieces, weight, exporter, consignee
- `shipment_documents` rows — one per uploaded file, `extraction_status='complete'|'failed'`

**Verification points:**
- `shipment_documents.extraction_status` per file (`complete` = parser succeeded; `failed` = needs re-upload or AI fallback)
- `shipment_documents.requires_manual_review` = 1 means parser was uncertain
- `document_extracted_fields.verified_status` = `unverified` for AI-parsed fields — must NOT proceed to fiscal write without human sign-off
- HSN codes must not match known quantity values (HSN guard: `7113...` blocked as piece counts)

**Common failure modes:**
1. **Invoice PDF unreadable** — parser fails; `extraction_status='failed'`; if `ai_parser_enabled=True` AI fallback fires but result has `verified_status='unverified'`
2. **AWB missing** — downstream workflows cannot link to DHL events; `awb_documents` row absent
3. **NBP rate unavailable** — batch blocks until rate is supplied manually via `--rate`
4. **Duplicate upload** — dedup guard on `(batch_id, document_type, file_hash)` prevents double-registration; same file silently skipped
5. **Multi-exporter batch** — multiple invoice files from different suppliers; `supplier_contractor_id` differs per document; must be resolved before PZ creation

---

## 2. Customs Clearance

**What it is:** ZC429/SAD customs declaration arrives from DHL WAW agency by email; system extracts MRN, duty (A00), and declared CIF; cross-checks against invoices.

**Trigger:** Inbound email from `plwawecs@dhl.com` (DHL WAW customs agency) containing ZC429/SAD PDF attachment. Zoho Mail scan detects it.

**Inputs:**
- ZC429/SAD PDF (from DHL WAW email)
- `batch_id` or `awb` to link to the correct batch
- Previously uploaded invoice lines (from Workflow 1)

**Authority owner:** `document_db.py` → `customs_declarations` (MRN + duty are the authoritative values)

**Databases touched:**
- `documents.db` → `shipment_documents` (ZC429 registered as `document_type='zc429'`)
- `documents.db` → `customs_declarations` (MRN, duty A00, CIF, importer, exporter, `invoice_refs`)
- `tracking.db` (email `message_id` dedup — prevents re-processing same email)
- `email_evidence.db` (raw email record)

**External systems:**
- Zoho Mail OAuth2 REST (inbound email scan, attachment download)
- Anthropic Claude API (if ZC429 PDF parser needs AI fallback)

**Outputs:**
- `customs_declarations.mrn` — 18-char customs MRN (e.g. `26PL44302D00AUCWR3`)
- `customs_declarations.duty_pln` — A00 duty amount (PLN) — **source of truth for all duty calculations**
- `customs_declarations.total_cif_usd` — declared customs CIF
- `customs_declarations.invoice_refs` — JSON list of invoice numbers declared to customs

**Verification points:**
- `importer_match`: ZC429 consignee NIP must = `5252812119` (Estrella NIP)
- `exporter_match`: ZC429 exporter must match known supplier names
- `cif_match`: Σ invoice CIF vs ZC429 declared CIF — tolerance ±$1.00 USD (`CIF_RECONCILIATION_TOLERANCE_USD = 1.0`)
- `invoice_refs_match`: Invoice numbers in ZC429 `invoice_refs` must match uploaded invoices
- `duty_rate_ok`: Effective duty rate = A00 / total CIF must be 0–20% (`DUTY_RATE_MAX_PCT = 20.0`)

**Common failure modes:**
1. **ZC429 email not detected** — Zoho Mail scan may miss it if sender address varies from `plwawecs@dhl.com`; manual upload required
2. **MRN already exists** — `customs_declarations.mrn` has UNIQUE constraint; duplicate MRN = constraint error; investigate if re-import of same clearance
3. **CIF mismatch > $1** — `cif_match = False` → amendment flag on PZ; operator must decide whether to proceed
4. **AI-parsed ZC429** — `ai_parser_enabled=True` may fill duty/MRN/importer; fields carry `verified_status='unverified'`; NEVER use for PZ without human confirmation
5. **Duty rate out of range** — if A00/CIF × 100 > 20%, `process_batch()` aborts; likely data error in ZC429 or invoice amount discrepancy
6. **DSK self-clearance path** — for high-value shipments (>$2,500 USD threshold), system triggers DSK self-clearance workflow instead of waiting for ZC429 email; different email path

---

## 3. Sales Packing

**What it is:** Customer-side allocation — which customer receives which pieces from the shipment. Input is a customer packing list (uploaded document); output is `sales_packing_lines` rows.

**Trigger:** Operator uploads customer packing list document (PDF or Excel) for a batch.

**Inputs:**
- Customer packing list file (PDF or Excel)
- `batch_id`
- `client_name` (must resolve to a `contractor_id` in Workflow 9)

**Authority owner:** `packing_db.py` → `packing_lines` (physical allocation); `documents.db` → `sales_packing_lines` (sales allocation)

**Databases touched:**
- `packing.db` → `packing_documents` (document registered)
- `packing.db` → `packing_lines` (one row per physical item with `scan_code` computed)
- `documents.db` → `sales_documents` (customer-level packing document header)
- `documents.db` → `sales_packing_lines` (customer-item allocation: product_code, design_no, bag_id, qty)

**External systems:** None (local parsing only)

**Outputs:**
- `packing_lines` with `scan_code` — enables later warehouse scan matching
- `sales_packing_lines` — customer allocation source for Proforma Draft (Workflow 4)
- `client_name` values — consumed by Customer Master (Workflow 9) for contractor resolution

**Scan code priority (packing_db.py):**
1. `<product_code>|<bag_id>` (bag tracking — preferred)
2. `<product_code>|sr<pack_sr>|<design_no>` (aggregated pack)
3. `<product_code>|<design_no>`
4. `<product_code>` (last resort)

**Verification points:**
- `sales_linkage` read-only join: `sales_packing_lines → packing_lines → inventory_current_location`
- `missing_scans > 0` → `ready_for_invoice = False` (goods not confirmed received)
- `invalid_flows > 0` → state machine violation detected
- `orphan_inventory > 0` → scanned goods with no corresponding sales line

**Common failure modes:**
1. **Duplicate pack_sr** — packing list serial numbers collide; `scan_code` computed from `(product_code, pack_sr)` may alias to wrong item; guard: sequential SR enforced in V2 frontend (Lesson fix: PR #723)
2. **Client name not resolvable** — `client_name` from packing list doesn't match any `wfirma_customers` row; Workflow 9 must be run first
3. **Design number mismatch** — `design_no` in packing list doesn't match `design_no` in invoice lines; `sales_linkage` status = `missing_scan`
4. **Circular import guard** — `_compute_scan_code` is intentionally duplicated in `packing_db.py` (not imported from `warehouse_db`) to avoid circular import; changing this breaks things silently

---

## 4. Proforma Draft

**What it is:** Sales proforma invoice drafted for a specific customer, covering their allocated goods from the batch. Requires customer identity (Workflow 9) and sales packing (Workflow 3) to be complete first.

**Trigger:** Operator initiates proforma draft for a `(batch_id, contractor_id)` pair. Requires: customer resolved, packing lines present, goods received.

**Inputs:**
- `batch_id`
- `contractor_id` (customer's wFirma ID)
- `sales_packing_lines` for this customer (from Workflow 3)
- Proforma service charges: freight and insurance (operator-entered — NOT derived from import CIF)
- `preferred_proforma_series_id` from `customer_master`

**Authority owner:** `proforma_draft_sync.py` (local state); wFirma API (fiscal identity)

**Databases touched:**
- `proforma_links.db` → draft lines, conflicts, detection events, resolution history
- `customer_master.sqlite` → `customer_master` (address, VAT, freight preference)
- `proforma_service_charges` table → operator-entered freight/insurance amounts

**External systems:**
- wFirma API (for contractor lookup, series ID validation, proforma creation at `posting` stage)

**Proforma state machine:**
```
draft → editing → approved → posting → posted → cancelled → superseded
```

**Outputs:**
- Proforma draft with line items (goods) + service lines (freight, insurance)
- `proforma_links.proforma_id` (assigned by wFirma at `posting` stage)
- Conflict detection events (if same goods allocated to multiple proformas)

**Verification points:**
- `ready_for_invoice = False` if `missing_scans > 0` (Workflow 3 / Workflow 8 incomplete)
- Conflict detection: same `product_code` on two active proformas → conflict event raised
- Customer VAT must be valid (`vat_eu_valid=True`) for EU B2B proforma
- Ship-to address must be present (Shape A or Shape B customer)
- Proforma service charges (freight, insurance) must be operator-confirmed — system does NOT derive them from import cost

**Common failure modes:**
1. **wFirma proforma creation succeeds but `mark_post_succeeded` fails** — split-brain: wFirma has the proforma but local DB doesn't know; `record_post_orphan()` logs the `wfirma_proforma_id` for manual adoption
2. **Conflict not resolved** — two proformas for same goods stay in conflict; operator must choose which supersedes the other
3. **Series ID invalid** — preferred series doesn't exist or is wrong type in wFirma; proforma blocked
4. **Customer shape mismatch** — customer has Shape B ship-to (separate `contractor_id`) but draft uses Shape A address; proforma goes to wrong address in wFirma
5. **Proforma service charges missing** — freight or insurance line absent; proforma will be incomplete for customer billing; system does not auto-fill from import costs

---

## 5. wFirma Posting (PZ)

**What it is:** The core import accounting event — `process_batch()` calculates all landed costs, then the PZ document is created in wFirma, permanently recording the goods receipt in the accounting system.

**Trigger:** Operator enables `wfirma_create_pz_allowed=True` AND triggers via `POST /api/v1/pz/process`. Prerequisites: invoices parsed, ZC429 received, NBP rate known.

**Inputs:**
- Invoice PDFs (parsed, from Workflow 1)
- ZC429/SAD (parsed, from Workflow 2) → duty A00
- DHL freight cost (PLN) — entered manually or from DHL invoice
- NBP USD/PLN exchange rate
- `--doc-no` (PZ number override, optional)

**Authority owner:** `pz_import_processor.py::process_batch()` — THE ONLY calculation path

**Calculation flow (never recompute outside this):**
```
FOB USD per line
  → Insurance USD = FOB × 0.005
  → Freight USD = (DHL share) × 0.50
  → CIF USD = FOB + Insurance + Freight
  → Duty USD = CIF × (A00_duty / total_CIF)   ← A00 from ZC429, not a fixed rate
  → Landed USD = CIF + Duty
  → Landed PLN = Landed USD × NBP_rate         ← NBP from Table A
  → VAT PLN = Landed PLN × 0.23               ← reference only
  → Brutto PLN = Landed PLN + VAT PLN
```

**Databases touched:**
- `documents.db` → `pz_documents` (written AFTER successful wFirma PZ creation)
- `documents.db` → `invoice_lines` (read)
- `documents.db` → `customs_declarations` (read — source of duty A00)
- `wfirma_db.sqlite` (read — product_code → wfirma_product_id mapping)

**External systems:**
- wFirma API (`documents/add` with `type=pz`) → returns `doc_no`
- Zoho WorkDrive (PDF/XLSX upload) → returns `workdrive_pdf_id`, `workdrive_xlsx_id`
- Zoho Cliq (notification to `#pz` channel) — ALWAYS sent; never blocked by WorkDrive state

**Outputs:**
- `pz_documents.doc_no` — wFirma PZ number (e.g. `PZ/001/2026`)
- `pz_documents.total_net_pln` — Razem Netto PLN
- `pz_documents.total_gross_pln` — Razem Brutto PLN
- `pz_documents.duty_a00_pln` — duty as declared in ZC429
- `pz_documents.verification_status` — VERIFIED / PARTIAL / NOT_VERIFIED / BLOCKED
- `pz_documents.amendment_flags` — list of confirmed mismatches
- PDF + XLSX files (local + WorkDrive)
- Cliq message to `#pz`

**Verification points:**
- `verification_status = VERIFIED`: all cross-checks passed (importer, exporter, CIF, invoice refs)
- `verification_status = PARTIAL`: some checks passed, some are `None` (VERIFY-GAP) — NOT an amendment flag
- `verification_status = BLOCKED`: at least one `False` result — amendment flag required
- CIF cross-check: Σ invoice CIF vs ZC429 declared CIF within ±$1.00
- Duty rate range: 0–20% (outside range = abort)
- Blocked phrases in corrections log → `blocked_phrases_clean = False`

**Common failure modes:**
1. **wFirma returns error on PZ create** — `wfirma_create_pz_allowed` is True but wFirma rejects (duplicate doc_no, product not found, contractor mismatch); no `pz_documents` row created
2. **`wfirma_product_id` missing** — `product_code` not in `wfirma_db.sqlite`; `wfirma_create_product_allowed=False` means product must exist; PZ blocked
3. **Fractional quantity** — wFirma rejects non-integer piece counts; `pz_quantity_validator` normalizes before send (NaN guard, zero-round guard) — Lesson from PR #730/#731
4. **CIF mismatch > $1** — `cif_match = False` → amendment flag in output; operator decides to proceed or investigate
5. **WorkDrive upload fails** — PDF/XLSX not uploaded; Cliq notification sent anyway ("WorkDrive pending retry"); `workdrive_pdf_id` = None
6. **AI-parsed source fields** — if any `document_extracted_fields.verified_status = 'unverified'` and source is AI, fiscal values are suspect; currently NO hard gate blocks this (see governance risk)

---

## 6. DHL Shipment Booking

**What it is:** Outbound DHL Express booking — creates a new outbound shipment for a customer (separate from the import AWB). Currently shadow-only in production.

**Trigger:** Operator triggers outbound booking for a `(batch_id, contractor_id)` pair. Requires customer shipping address and carrier account.

**Inputs:**
- `batch_id`
- Customer shipping address (`client_shipping_addresses`)
- Customer carrier account (`client_carrier_accounts`)
- Package dimensions and weight
- `carrier_api_status` = `live` AND `batch_id` in `carrier_live_allowlist`

**Authority owner:** DHL Express API → `carrier_shipments.db`

**Databases touched:**
- `carrier_shipments.db` → `carrier_shipments` (idempotency store — key: `idempotency_key`)
- `carrier_events.db` → `carrier_events` (webhook dedup)
- `shadow_log.db` → `shadow_log` (telemetry for shadow mode)
- `tracking.db` (AWB events after booking)

**External systems:**
- DHL Express API (OAuth2) — `shipments` endpoint; returns AWB + label PDF
- DHL Tracking API (after booking — polls AWB events)

**Shadow vs live gate:**
- `carrier_api_status = 'pending'` or `'shadow'` → simulated submission; no real DHL call; result logged to `shadow_log`
- `carrier_api_status = 'live'` AND `batch_id` in `carrier_live_allowlist` → real DHL booking
- **Live submissions are REJECTED by code without allowlist entry**

**Outputs (live mode):**
- `carrier_shipments.tracking_ref` = real DHL AWB
- `carrier_shipments.state` = `complete`
- DHL label PDF (for printing)

**Outputs (shadow mode):**
- `shadow_log` entry
- `carrier_shipments.state` = `complete` (simulated)
- Simulated AWB (not a real DHL number)

**Verification points:**
- `carrier_shipments.state` = `complete` (not `failed` or `pending`)
- `carrier_shipments.mode` = `live` for real bookings; `shadow` otherwise
- `carrier_api_status` feature flag must be explicitly set to `live` by operator
- PLT (Paperless Trade) requires `carrier_plt_status = 'live'` separately

**Common failure modes:**
1. **Live call without allowlist** — hard rejection with named error; not a silent failure
2. **DHL OAuth token expired** — 401 from DHL API; token refresh should handle; if refresh fails → carrier blocked
3. **Idempotency key collision** — same `idempotency_key` submitted twice; second call returns cached result (safe by design)
4. **Customer carrier account missing** — `client_carrier_accounts` row absent for this customer; booking cannot proceed
5. **Package weight/dimension out of DHL limits** — DHL API returns validation error; `carrier_shipments.state = 'failed'`

---

## 7. Finance Posting

**What it is:** Double-entry accounting record linking a proforma/invoice posting to charges, payments, and eventual settlement. A parallel layer to wFirma — writes to local `finance_postings.sqlite`.

**Trigger:** Proforma successfully posted to wFirma (Workflow 5 proforma variant). `finance_dual_write.dual_write_proforma_post()` fires immediately after `mark_post_succeeded()`. Feature-flagged — default OFF.

**Inputs:**
- `batch_id`
- `client_name`
- Charge amounts (from `proforma_invoice_link_db` service charges JSON)
- `posting_kind` = `proforma` | `invoice` | `correction`

**Authority owner:** `finance_postings_db.py` — ALL amounts in INTEGER CENTS

**Databases touched:**
- `finance_postings.sqlite` → `charges` (one row per charge type: net_goods, freight, insurance, duty, vat)
- `finance_postings.sqlite` → `postings` (one row per wFirma document posted)
- `finance_postings.sqlite` → `payments` (operator-entered or bank-reconciled)
- `finance_postings.sqlite` → `payment_allocations` (links payment → charge, allocation_method)
- `finance_postings.sqlite` → `settlements` (explicit operator action — UNIQUE per posting_id)

**External systems:** None (local accounting only)

**Finance lifecycle states (inferred from table presence):**
```
charge recorded → posting issued → payment received → allocation → settlement
```
Settlement requires operator to call `record_settlement()` after `is_fully_paid()` = True.

**Outputs:**
- `charges` rows — itemized cost breakdown per client
- `postings` row — wFirma document reference
- `settlements` row — final close (when operator confirms full payment)

**Verification points:**
- `is_fully_paid()` checks: Σ `payment_allocations.applied_minor` ≥ `postings.issued_total_minor` within ±1 minor unit
- `settlements` UNIQUE constraint: prevents double-settling
- All amounts in INTEGER CENTS — never float arithmetic
- `dual_write_proforma_post()` exceptions are SWALLOWED (WARNING log) — divergence between wFirma and local DB is possible without alert

**Common failure modes:**
1. **Split-brain: wFirma PZ succeeds, `mark_post_succeeded` fails** → `record_post_orphan()` fires; local DB doesn't have the wFirma proforma_id; operator must manually adopt
2. **Dual-write exception swallowed** — `finance_postings.sqlite` not updated but wFirma proforma created; no error surfaces to operator
3. **Unknown charge type** — type not in `CHARGE_TYPES` frozenset; skipped with WARNING; charge lost silently
4. **Settlement re-attempt** — `UNIQUE` constraint raises `ValueError("SETTLEMENT_EXISTS")`; safe by design
5. **Integer overflow** — amounts stored as INTEGER cents; Python handles arbitrarily large integers but downstream tooling (Excel, reports) must handle large cent values

---

## 8. Inventory Movement

**What it is:** Physical goods lifecycle tracking — from DHL transit → warehouse receipt → stock → dispatch → closed. Tracks each item through its physical location and ownership state.

**Trigger (physical receipt):** Operator scans goods into warehouse after DHL delivery. `record_scan(action='RECEIVE', product_code=..., location=...)` writes to `inventory_movement_events`.

**Trigger (state transition):** Operator or system calls `transition(batch_id, product_code, from_state, to_state)` in `inventory_state_engine.py`.

**Inputs:**
- `batch_id`
- `product_code` (or `scan_code` from barcode)
- `action` = `RECEIVE` | `MOVE` | `PICK` | `PACK` | `DISPATCH` | `RETURN`
- `operator` name (required for DIRECT_DISPATCH_READY transition)
- `customs_cleared` flag (required for DIRECT_DISPATCH_READY)

**Authority owner:** `inventory_state_engine.py` (state transitions); `warehouse_receipt.py` (quantity confirmation)

**Databases touched:**
- `warehouse.db` → `inventory_current_location` (UPSERT — current location of each item)
- `warehouse.db` → `inventory_movement_events` (APPEND — full audit trail of every scan)
- `warehouse.db` → `inventory_state` (state transitions via `transition()`)
- `warehouse_receipt.db` → `warehouse_receipt_confirmations` (UPSERT — operator quantity confirmation)
- `warehouse_receipt.db` → `warehouse_receipt_events` (APPEND — audit trail)
- `packing.db` → `packing_lines` (READ — expected quantities authority)

**External systems:** None

**Inventory state machine (legal transitions only):**
```
None
  → PURCHASE_TRANSIT       (trigger: pz_generated — synthetic, from audit.json)
  → WAREHOUSE_STOCK        (trigger: warehouse_receive — after RECEIVE scan)
  → DIRECT_DISPATCH_READY  (trigger: direct_dispatch_marked — requires evidence)
  → SALES_TRANSIT          (trigger: invoice_issued)
  → CLIENT_DISPATCHED      (trigger: client_dispatched)
  → CLOSED                 (trigger: delivery_confirmed)
```

**Critical rules:**
- A RECEIVE **scan** does NOT auto-promote state. `transition()` is the ONLY path to state change.
- `PURCHASE_TRANSIT` is SYNTHETIC — computed from `audit.json`, not from a scan
- `serial_controlled=True` shipments require per-piece scan completeness
- `NEVER_TOUCH` guard protects `ship_to_*`, `credit_*`, `kuke_*` fields even with `--force`

**Outputs:**
- `inventory_current_location` updated per scan
- `inventory_movement_events` append (immutable audit trail)
- `sales_linkage` read-only view: per-item `ready` | `pending_dispatch` | `not_ready` | `missing_scan`
- `ready_for_invoice = True/False` — gates Proforma Draft (Workflow 4)

**Verification points:**
- `shortage` / `overage` computed from `confirm_receipt()` vs expected `packing_lines` qty
- `missing_scans > 0` → not ready for invoice
- `invalid_flows > 0` → state machine violation (scan without matching sales line)
- `orphan_inventory > 0` → goods scanned but no customer sales allocation
- `DIRECT_DISPATCH_READY` requires: operator non-empty + customer_allocation non-empty + customs_cleared=True + prior RECEIVE event

**Common failure modes:**
1. **RECEIVE scan without prior pz_generated** — goods not in `PURCHASE_TRANSIT` synthetic projection; receipt confirmation may fail if batch not fully processed
2. **`line_key` not found in packing authority** — `confirm_receipt()` appends to `errors` list, skips line; shortages not reported accurately
3. **State already at target** — re-calling `transition()` on the same state is handled; check return value
4. **`serial_controlled=True` shipments** — per-piece scan required; batch-level receipt insufficient
5. **`packing_db` circular import** — `_compute_scan_code` is duplicated; importing from `warehouse_db` instead will break runtime

---

## 9. Customer Master Maintenance

**What it is:** Resolves customer identity (name → wFirma contractor_id) before proforma can be created. Ensures every client name from sales packing lists maps to exactly one wFirma contractor record.

**Trigger (auto):** `ensure_customers_for_batch(batch_id)` called at proforma readiness gate — reads `client_name` values from `sales_documents`.

**Trigger (manual sync):** Operator triggers bulk wFirma contractor sync via `wfirma_customer_sync.py`.

**Inputs:**
- `client_name` values from `sales_documents` or `sales_packing_lines`
- Local `wfirma_customers` mirror (primary lookup)
- wFirma `contractors/find` API (fallback for local misses)

**Authority owner:** `customer_master.sqlite` → `customer_master` (write authority for billing fields); `wfirma_customers` table (mirror)

**Resolution priority:**
```
1. operator-set row (match_status='matched') — PROTECTED, never overwritten
2. auto-resolve: exact_match → normalized_match → prefix_match → reverse_prefix_match
3. live wFirma API search (contractors/find with name LIKE)
4. live wFirma API search (by VAT number)
5. ambiguous (multiple candidates) → operator must resolve
6. missing → operator must create or link
```

**Databases touched:**
- `documents.db` → `sales_documents` + `sales_packing_lines` (READ — source of client names)
- `wfirma.db` → `wfirma_customers` (READ+WRITE — contractor mirror)
- `reservation_queue.db` → `wfirma_customer_mapping` (WRITE — parallel registry updated on resolution)
- `customer_master.sqlite` → `customer_master` (WRITE via CLI merge tool for full customer profile)

**External systems:**
- wFirma `contractors/find` (GET with XML body) — name LIKE search + VAT exact-match; max 20 results per call

**Outputs:**
- `wfirma_customers` row with `wfirma_customer_id` and `match_status`
- `wfirma_customer_mapping` row in `reservation_queue.db`
- Resolution verdict per `client_name`: `exact_match` | `normalized_match` | `prefix_match` | `reverse_prefix_match` | `ambiguous` | `missing` | `invalid_name`

**Verification points:**
- `match_status = 'matched'` (operator-confirmed) → always safe to use
- `ambiguous` → MUST NOT proceed to proforma; operator must select one candidate
- `missing` → MUST NOT proceed; operator must create wFirma contractor or link manually
- `wfirma_create_customer_allowed = False` → system cannot create new contractors; `missing` is a hard block
- CONFLICT rows in sync — never auto-applied; stuck until manually reconciled

**Common failure modes:**
1. **`ambiguous` match** — multiple wFirma contractors match same normalized name; operator must pick; system holds `candidates` list
2. **CONFLICT in sync** — local `wfirma_customer_id` doesn't match wFirma API response; `apply_plan` skips conflicted rows; manual reconciliation needed
3. **`reservation_queue.db` missing** — produces warning, not error; auto-resolve result still returned but parallel registry not updated
4. **Pagination guard triggers** — >200 pages of wFirma contractors (>10,000 records); pagination stops with `complete=False`
5. **Name normalization edge cases** — special characters, encoding differences between packing list names and wFirma names; falls through to `missing` even if contractor exists

---

## 10. Freight Cost Recovery

**What it is:** Determines the freight amount to bill a customer on their proforma. NOT the import freight (DHL import cost) — this is the outbound freight charge to the customer, recovered from historical invoices or operator input.

**Trigger:** Called at proforma draft time for a `(customer, currency)` pair. Production path: `pick_freight(customer_master, draft_currency)` reads static fields from `customer_master`.

**Inputs:**
- `contractor_id` (customer's wFirma ID)
- `draft_currency` (EUR or USD — proforma currency)
- `customer_master.freight_mode` (`fixed` | `from_history` | `from_wfirma`)
- `customer_master.freight_fixed_amount_eur` or `freight_fixed_amount_usd` (if mode=fixed)

**Authority owner:** `pick_freight()` in `customer_master.py` (production); `freight_resolver.py` (research/backfill only — NOT for production routes)

**Resolution order (freight_resolver.py — backfill/research only):**
```
0. Manual operator input (--freight param) → saves to freight_history
1. customer_freight_history (local DB, latest by contractor_id + currency)
2. wFirma final invoices (type=normal, searches for good_id 13002743 or freight keywords)
3. wFirma proformas (type=proforma)
4. FreightUnresolved raised → operator must intervene
```

**Databases touched:**
- `customer_master.sqlite` → `customer_master` (READ for production path; WRITE by CLI merge tool)
- `freight_history.db` → `customer_freight_history` (APPEND — every resolution saves a row; never updates)
- `customer_invoice_snapshot_db` (READ by CLI merge tool to compute avg/last)

**External systems:**
- wFirma `invoices/find` (GET with XML) — steps 2 and 3 in backfill resolver; searches by contractor_id + currency + type

**Outputs:**
- Freight amount (PLN or EUR or USD) for the proforma service charge line
- `customer_freight_history` append row (for steps 0–3 in resolver)
- `customer_master.freight_last_amount` and `freight_avg_amount` (updated by CLI merge tool)

**Verification points:**
- `freight_mode = 'fixed'`: uses static amount; never queries history or wFirma
- `freight_mode = 'from_history'`: uses `customer_freight_history` latest; fails with `FreightUnresolved` if empty
- `freight_amount > 0` required — `save_freight_history` raises `ValueError` on non-positive amounts
- Source types: `invoice | proforma | manual` only — anything else rejected
- **These are billing charges to the customer, NOT the import CIF freight**

**Common failure modes:**
1. **`FreightUnresolved`** — no history, no manual input, wFirma returns nothing; operator must supply `--freight` manually
2. **wFirma `ConnectionError`** — steps 2/3 in backfill resolver fail; resolver moves to next step or raises `FreightUnresolved`
3. **XML ParseError** — bad wFirma response; treated as `None` (no freight found)
4. **Legacy `freight_last_amount` deprecation** — if `freight_fixed_amount_eur` absent but `freight_last_amount` + `freight_mode='fixed'` → fallback fires with deprecation warning; field should be migrated
5. **Proforma currency mismatch** — proforma is EUR but history only has USD entries; resolution fails for EUR; each currency is tracked separately
6. **`freight_resolver.py` imported from production routes** — explicitly forbidden in module header; must only use `pick_freight()` from `customer_master.py` in production

---

## Cross-Workflow Dependencies

```
Workflow 1 (Shipment Intake)
  └─→ Workflow 2 (Customs Clearance) — needs batch_id + invoice lines for CIF cross-check
  └─→ Workflow 3 (Sales Packing)     — needs batch_id; parallel, not blocked by WF2
  └─→ Workflow 5 (wFirma PZ Posting) — needs WF1 + WF2 complete (invoices + ZC429)

Workflow 3 (Sales Packing)
  └─→ Workflow 4 (Proforma Draft)    — needs packing lines + customer resolved (WF9)
  └─→ Workflow 8 (Inventory)         — packing lines are expected-qty authority

Workflow 4 (Proforma Draft)
  └─→ Workflow 5 (wFirma PZ Posting) — proforma is a separate WF5 variant (not import PZ)
  └─→ Workflow 7 (Finance Posting)   — fires after successful proforma post
  └─→ Workflow 10 (Freight Recovery) — freight amount needed for proforma service line

Workflow 8 (Inventory Movement)
  └─→ Workflow 4 (Proforma Draft)    — ready_for_invoice gate requires no missing_scans

Workflow 9 (Customer Master)
  └─→ Workflow 4 (Proforma Draft)    — contractor_id required; ambiguous/missing blocks proforma

Workflow 6 (DHL Booking)
  ─── independent of WF1–5 (outbound, not import)
  └─→ Workflow 8 (Inventory)         — DISPATCH scan after booking
```

## Common Debug Paths

**"PZ is wrong"** → Start at Workflow 5. Check `pz_documents.verification_status` and `amendment_flags`. Then go upstream to Workflow 2 (ZC429 A00 correct?) and Workflow 1 (FOB values correct?).

**"Proforma can't be created"** → Check Workflow 9 (customer resolved?), Workflow 3 (packing lines present?), Workflow 8 (goods received → `ready_for_invoice = True`?), Workflow 10 (freight amount known?).

**"Duty is wrong"** → Workflow 2. `customs_declarations.duty_pln` is the ONLY source. NEVER use `DUTY_RATE = 0.12` constant for real batches.

**"Finance is unbalanced"** → Workflow 7. Check integer cents arithmetic. Check `dual_write_proforma_post` didn't throw and get swallowed.

**"Goods show wrong location"** → Workflow 8. Check `inventory_current_location` (last scan). Check `inventory_state` for current lifecycle stage. Check that `transition()` was called (not just a scan).

**"Customer shows wrong freight"** → Workflow 10. Check `pick_freight()` result (production). Check `customer_master.freight_mode`. Check `customer_freight_history` for last entry. Check that `freight_resolver.py` is NOT being called from a production route.

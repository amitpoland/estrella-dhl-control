# DATA_AUTHORITY_MAP.md — Estrella PZ Platform

**Updated:** 2026-06-23
**Rule:** Each domain has exactly one write authority. Cross-domain writes require a named business rule.

---

## Authority Table

| Domain | Write Authority | Source of Truth DB | Forbidden Write Locations |
|---|---|---|---|
| **Landed cost calculation** | `pz_calculator.py::calculate_landed()` called by `process_batch()` | Process output (in-memory → documents.db pz_documents) | Routes, services, Cliq layer, UI, external systems |
| **Duty amount (PLN)** | ZC429/SAD A00 field (customs document) | `documents.db` → `customs_declarations.duty_pln` | Calculator constants, manual entry, invoice extrapolation |
| **NBP exchange rate** | NBP Table A API or `--rate` CLI param | Process output `nbp.usd_rate` | Hardcoded values, cached from prior batches |
| **Customer master identity** | Operator via UI / wFirma sync via `upsert_identity_only` | `customer_master.sqlite` → `customer_master` | wFirma API (may fill empty fields, never overwrite) |
| **Customer ship-to address** | Operator via UI (Shape A) or wFirma contractor (Shape B) | `customer_master.sqlite` → `client_shipping_addresses` | Proforma writer, carrier module |
| **wFirma product ID** | wFirma API → local cache | `wfirma_db.sqlite` | Local code generation |
| **Product bilingual name** | `product_descriptions` table (auto + manual) | `documents.db` → `product_descriptions` | Invoice line descriptions, wFirma product name field |
| **Customs MRN** | ZC429 email from DHL WAW agency | `documents.db` → `customs_declarations.mrn` | Manual entry, AWB lookup |
| **PZ doc_no** | wFirma API response after PZ creation | `documents.db` → `pz_documents.doc_no` | Local number generation |
| **AWB number** | DHL Express API response (booking) or AWB document PDF | `documents.db` → `awb_documents.awb` | Email extraction only (secondary confirmation) |
| **Proforma draft state** | Proforma service (`proforma_draft_sync.py`) | `proforma_links.db` | wFirma API (proforma ID comes from wFirma, but state managed locally) |
| **Carrier booking state** | DHL Express API → `carrier_shipments.db` | `carrier_shipments.db` → `carrier_shipments.state` | Webhook only updates via `event_db`; no direct state writes |
| **Email evidence** | Zoho Mail OAuth2 scan → `email_evidence.db` | `email_evidence.db` | Manual entry |
| **Finance charges** | `finance_postings_db.py` | `finance_postings.sqlite` → `charges` | Routes that recompute from invoice lines |
| **HS/HSN code** | `master_data.sqlite` → `hs_codes` (seeded from Polish customs tariff) | `master_data.sqlite` | Invoice descriptions, proforma line guesses |
| **Product sales allocation** | Sales packing list upload → `sales_packing_lines` | `documents.db` → `sales_packing_lines` | Customer-side systems, proforma |

---

## Write Gates (Feature Flags)

All write operations to external systems are gated by flags in `config.py`.
Default state is **OFF** (safe to read, blocked from writing).

### wFirma Write Gates

| Flag | Default | Permission |
|---|---|---|
| `wfirma_create_product_allowed` | OFF | Create new goods in wFirma |
| `wfirma_create_customer_allowed` | OFF | Create new contractors in wFirma |
| `wfirma_create_proforma_allowed` | OFF | Create proforma invoices in wFirma |
| `wfirma_edit_product_allowed` | **ON** | Edit product names (name-sync always active) |
| `wfirma_edit_invoice_allowed` | OFF | Edit invoices |
| `wfirma_sync_customers_allowed` | OFF | Sync customers from wFirma to local |
| `wfirma_sync_suppliers_allowed` | OFF | Sync suppliers from wFirma to local |
| `wfirma_delete_invoice_allowed` | OFF | Delete invoices |
| `wfirma_create_pz_allowed` | OFF | Create PZ (goods received) in wFirma |
| `wfirma_correction_push_allowed` | OFF | Push correction to wFirma |
| `wfirma_create_invoice_allowed` | OFF | Convert proforma → final invoice |

### DHL Carrier Write Gates

| Flag | Default | Permission |
|---|---|---|
| `carrier_api_status` | `pending` | `shadow`=simulated, `live`=real DHL calls |
| `carrier_live_allowlist` | empty | Comma-separated batch_ids allowed for live calls |
| `carrier_plt_status` | `pending` | PLT (Paperless Trade) feature gate |
| `dhl_tracking_api_status` | `pending` | Live DHL tracking API |

### DHL Self-Clearance Write Gates (all OFF by default)

| Flag | Default | Permission |
|---|---|---|
| `dhl_selfclearance_p2_live_enabled` | OFF | Phase 2 proactive dispatch emails |
| `dhl_selfclearance_p3_live_enabled` | OFF | Phase 3 tracking |
| `dhl_selfclearance_p4_live_enabled` | OFF | Phase 4 email classification |
| `dhl_selfclearance_p5_live_enabled` | OFF | Phase 5 PZ trigger |

### DHL Orchestrator Write Gates (all OFF by default)

| Flag | Permission |
|---|---|
| `dhl_orch_auto_send_agency` | Auto-send customs agency emails |
| `dhl_orch_auto_send_dhl_reply` | Auto-send DHL reply emails |
| `dhl_orch_auto_send_dhl_followup` | Auto-send DHL follow-up emails |
| `dhl_orch_auto_send_dsk_chase` | Auto-send DSK chase emails |
| `enable_path_a_auto_queue` | Auto-queue proactive customs dispatch |

### AI Write Gates (all OFF by default)

| Flag | Permission |
|---|---|
| `ai_parser_enabled` | AI fallback for document parsing |
| `ai_advisory_llm_enabled` | AI advisory recommendations |
| `ai_cowork_enabled` | **DEPRECATED 2026-05-25 (ADR-020) — must stay False** |

---

## Cross-Domain Authority Principles

**P1 — Calculation authority is exclusive.**
`process_batch()` owns all financial calculations. No route, service, or external system may recalculate landed cost, freight, duty, or totals.

**P2 — Customs document is the duty authority.**
The ZC429/SAD A00 field is the ONLY valid source of duty amounts. The `DUTY_RATE = 0.12` constant is a golden-test calibration tool only.

**P3 — wFirma is the accounting system of record.**
All fiscal documents (invoices, PZ, proforma) have their canonical state in wFirma. Local DBs are caches or work-in-progress states.

**P4 — customer_master.sqlite is the customer identity authority.**
wFirma contractor data may backfill empty fields via `upsert_identity_only`, but never overwrites operator-set values.

**P5 — Write gates must be OFF in production unless explicitly authorized.**
Any write to wFirma, DHL API, or email that is not explicitly enabled via a config flag is a bug.

**P6 — Proforma service charges are operator-entered, not system-derived.**
Freight and insurance on proformas are billing decisions, not the same as import CIF calculations.

---

## Data Quality Signals

When analyzing data, check these quality indicators:

| Signal | Location | Meaning |
|---|---|---|
| `pz_documents.verification_status` | `documents.db` | VERIFIED / PARTIAL / NOT_VERIFIED / BLOCKED |
| `pz_documents.amendment_flags` | `documents.db` | JSON list of confirmed mismatches |
| `process_batch()["verification"]["cif_match"]` | Process output | True/False/None — invoice vs customs CIF |
| `process_batch()["corrections_log"]` | Process output | `[REVIEW-NEEDED]`, `[VERIFY-GAP]`, `[BLOCKED-PHRASE]` prefixes |
| `shipment_documents.extraction_status` | `documents.db` | `pending`/`complete`/`failed` per document |
| `shipment_documents.requires_manual_review` | `documents.db` | 1 = human review needed |
| `document_extracted_fields.verified_status` | `documents.db` | `unverified`/`verified`/`rejected` per field |

---

## Data Sources Inventory

| Source | Type | Refresh | Authority For |
|---|---|---|---|
| Supplier invoice PDFs | Document → parsed | Per batch | FOB values, quantities, product descriptions |
| ZC429/SAD PDF (from DHL WAW email) | Document → parsed | Per batch | Duty A00, MRN, CIF declared, importer/exporter identity |
| NBP Table A API | REST API | Daily (or manual at batch time) | USD/PLN exchange rate |
| wFirma API | REST API | Per operation | Contractor IDs, product IDs, fiscal document numbers |
| DHL Express API | REST API | Per booking | AWB numbers, shipment state |
| DHL ZC429 email (plwawecs@dhl.com) | Inbound email | Per shipment clearance | MRN, DSK, duty confirmation |
| Zoho WorkDrive | Cloud storage | Per PZ completion | PDF/XLSX file URLs |
| Customer-uploaded packing lists | Uploaded document | Per shipment | Sales allocation, design numbers, bag IDs |
| Operator entries (UI) | Manual | On demand | Customer master, shipping addresses, proforma charges |

---

## Missing Documentation (Data Quality Risks)

Based on discovery findings:

1. **`users.db`** — No owning `*_db.py` found. Schema unknown. Risk: orphaned user data.
2. **`correction_registry.db`** — No owning `*_db.py` found. Likely owned by correction lifecycle routes.
3. **`intake_lineage.db`** — No owning `*_db.py` found. Likely intake/parsing provenance tracking.
4. **`proforma_service_charges`** — Operator-entered but no validation against DHL actual costs. Risk: billing errors.
5. **`customer_invoice_snapshot.db`** — Cache with no documented refresh schedule. Risk: stale data in reports.
6. **AI parser fallback** — When `ai_parser_enabled=True`, AI may fill document fields. These should have `verified_status='unverified'` and require human sign-off before fiscal use.
7. **`dhl_selfclearance_value_threshold_usd = $2,500`** — Hardcoded threshold. Not documented as a business rule in any data catalog.

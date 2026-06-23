# DATA_ENTITY_MAP.md — Estrella PZ Platform

**Updated:** 2026-06-23

---

## Entity Relationship Overview

```
SUPPLIER (wFirma contractor)
    │
    │ ships via DHL → AWB
    │
    ▼
BATCH (batch_id)
    ├── shipment_documents (documents.db) ─── pivot table for all docs
    │       ├── INVOICE documents         → invoice_lines
    │       ├── ZC429/SAD document        → customs_declarations
    │       ├── AWB document              → awb_documents
    │       ├── PZ document               → pz_documents
    │       └── SALES documents           → sales_packing_lines
    │
    ├── CARRIER booking (carrier_shipments.db)
    │       └── carrier_events.db (webhook dedup)
    │
    ├── EMAIL evidence (tracking.db + email_evidence.db)
    │
    └── FINANCE postings (finance_postings.sqlite)

CUSTOMER (customer_master.sqlite)
    ├── customer_master (bill-to)
    ├── client_shipping_addresses (ship-to)
    └── client_carrier_accounts (DHL account per customer)
        │
        └── PROFORMA (proforma_links.db)
                └── sales_packing_lines → PRODUCT (product_code)

PRODUCT (product_code)
    ├── product_descriptions (documents.db) — bilingual names
    ├── wfirma_db.sqlite — product_code ↔ wfirma_product_id mapping
    └── master_data.sqlite → hs_codes (duty rate by HSN)
```

---

## Entity Definitions

### BATCH
A single shipment processing session — the primary unit of work.

| Field | Type | Source |
|---|---|---|
| `batch_id` | UUID TEXT PRIMARY KEY | Created on upload |
| `awb` | TEXT | DHL AWB on `shipment_documents` |
| `doc_no` | TEXT | wFirma PZ number (from `pz_documents`) |
| `mrn` | TEXT | Customs MRN (from `customs_declarations`) |

**Lifecycle:** `upload → customs → pz_posted → cliq_notified → workdrive_filed`

**Authority database:** `documents.db` → `shipment_documents` (pivot)

---

### SHIPMENT_DOCUMENTS (pivot table)

Primary registry of all documents in a batch.

| Column | Type | Description |
|---|---|---|
| `id` | UUID TEXT PK | Document UUID |
| `batch_id` | TEXT NOT NULL | Shipment session |
| `awb` | TEXT | DHL AWB |
| `document_type` | TEXT | `invoice`, `zc429`, `awb`, `pz`, `sales_invoice` |
| `file_name` | TEXT | Original filename |
| `canonical_file_name` | TEXT | Normalized filename |
| `file_path` | TEXT | Local storage path |
| `file_hash` | TEXT | SHA-256 dedup hash |
| `parser_name/version/status` | TEXT | Parser used |
| `extraction_status` | TEXT | `pending`/`complete`/`failed` |
| `related_invoice_no` | TEXT | Commercial invoice reference |
| `related_mrn` | TEXT | Customs MRN reference |
| `related_pz_no` | TEXT | PZ doc_no reference |
| `client_contractor_id` | TEXT | Customer wFirma ID |
| `supplier_contractor_id` | TEXT | Supplier wFirma ID |

**Dedup key:** `(batch_id, document_type, file_hash)`

---

### CUSTOMS_DECLARATIONS

One row per MRN. Source of truth for duty and customs identity.

| Column | Type | Description |
|---|---|---|
| `id` | UUID TEXT PK | |
| `document_id` | TEXT FK → `shipment_documents` | |
| `batch_id` | TEXT | |
| `mrn` | TEXT UNIQUE | Polish customs MRN (18-char) |
| `lrn` | TEXT | Local Reference Number |
| `clearance_date` | TEXT | Clearance date |
| `duty_pln` | REAL | A00 duty amount (PLN) — authoritative |
| `vat_pln` | REAL | B00 VAT (reference only) |
| `total_cif_usd` | REAL | Declared CIF USD |
| `customs_rate_usd` | REAL | Exchange rate used by customs |
| `agent` | TEXT | Clearance agency name |
| `importer_name/nip` | TEXT | Must match Estrella NIP 5252812119 |
| `exporter_name` | TEXT | Must match known supplier |
| `cn_code` | TEXT | Customs classification code |
| `invoice_refs` | JSON TEXT | Invoice numbers declared to customs |

---

### PZ_DOCUMENTS

Output record after successful PZ posting to wFirma.

| Column | Type | Description |
|---|---|---|
| `id` | UUID TEXT PK | |
| `batch_id` | TEXT | |
| `doc_no` | TEXT | wFirma PZ number (e.g. PZ/001/2026) |
| `line_count` | INTEGER | Number of PZ lines posted |
| `total_net_pln` | REAL | Razem Netto PLN |
| `total_gross_pln` | REAL | Razem Brutto PLN |
| `duty_a00_pln` | REAL | Duty from ZC429 A00 |
| `verification_status` | TEXT | Overall verification result |
| `amendment_flags` | JSON TEXT | List of confirmed mismatches |
| `workdrive_pdf_id` | TEXT | WorkDrive resource ID for PDF |
| `workdrive_xlsx_id` | TEXT | WorkDrive resource ID for XLSX |

---

### INVOICE_LINES

One row per supplier invoice line.

| Column | Type | Description |
|---|---|---|
| `id` | UUID TEXT PK | |
| `batch_id` | TEXT | |
| `invoice_no` | TEXT | Invoice document number |
| `line_position` | INTEGER | Line number within invoice |
| `product_code` | TEXT | Internal product code (invoice_no-position) |
| `description` | TEXT | Goods description (raw from invoice) |
| `quantity` | REAL | Piece count |
| `unit_price` | REAL | Unit price USD |
| `total_value` | REAL | FOB USD for this line |
| `currency` | TEXT | Invoice currency |
| `hs_code`/`hsn_code` | TEXT | HS/HSN customs code |
| `gross_weight` | REAL | Gross weight kg |
| `net_weight` | REAL | Net weight kg |
| `rate_usd` | REAL | Exchange rate at invoice date |
| `amount_usd` | REAL | Computed USD amount |

---

### AWB_DOCUMENTS

DHL Air Waybill parsed fields.

| Column | Type | Description |
|---|---|---|
| `batch_id` | TEXT | |
| `awb` | TEXT | 10-digit DHL AWB number |
| `carrier` | TEXT | Carrier name |
| `shipper_name` | TEXT | Exporter |
| `consignee_name` | TEXT | Importer |
| `pieces` | INTEGER | Number of pieces declared |
| `weight_kg` | REAL | Total weight |
| `description` | TEXT | Goods description |

---

### SALES_DOCUMENTS + SALES_PACKING_LINES

Customer allocation of imported goods.

**sales_documents:**

| Column | Type | Description |
|---|---|---|
| `batch_id` | TEXT | |
| `client_name` | TEXT | Customer name |
| `client_ref` | TEXT | Customer's reference number |
| `document_type` | TEXT | `sales_invoice` |
| `sales_doc_no` | TEXT | Customer's packing list number |
| `sales_doc_date` | TEXT | Date |

**sales_packing_lines:**

| Column | Type | Description |
|---|---|---|
| `batch_id` | TEXT | |
| `client_name` | TEXT | Customer name |
| `client_ref` | TEXT | Customer reference |
| `product_code` | TEXT | Internal product code |
| `design_no` | TEXT | Design/style number |
| `bag_id` | TEXT | Physical bag/pack identifier |
| `quantity` | REAL | Pieces allocated to this customer |
| `remarks` | TEXT | Notes |

---

### CUSTOMER_MASTER

Authoritative customer record. FULL-SET upsert semantics.

Key groups of columns:

| Group | Key Fields |
|---|---|
| Core | `bill_to_contractor_id` (wFirma ID), `bill_to_name`, `country` |
| Tax | `nip` (Polish tax ID), `vat_eu_number`, `vat_eu_valid` |
| Ship-to Shape A | `ship_to_name/street/city/zip/country` (alternate address on same entity) |
| Ship-to Shape B | `ship_to_contractor_id` (separate wFirma contractor) |
| Commercial | `default_currency`, `preferred_proforma_series_id`, `preferred_payment_method` |
| Freight | `freight_service_id`, `freight_mode`, `freight_fixed_amount_eur/usd` |
| Insurance | `insurance_rate` (default 0.0035), `insurance_mode`, `insurance_enabled` |
| Credit/KUKE | `credit_limit`, `kuke_approved`, `risk_status`, `payment_terms_days` |
| KYC/AML | `kyc_status`, `aml_risk_rating`, `pep_check_result` |
| Contact | `bill_to_email`, `bill_to_phone`, `bill_to_street/city/postal_code` |

**CRITICAL:** `upsert_customer()` is FULL-SET — unset fields become NULL. For wFirma sync, use `upsert_identity_only()` which only fills empty fields.

---

### CLIENT_SHIPPING_ADDRESSES

Shipping address registry per customer.

| Column | Type | Description |
|---|---|---|
| `contractor_id` | TEXT | Customer wFirma ID |
| `label` | TEXT | Address name (e.g. "Main Warehouse") |
| `name/person/street/city/zip/country/phone/email` | TEXT | Address fields |
| `is_default` | INTEGER | 1 = primary address |
| `active` | INTEGER | Soft-delete flag |

---

### CARRIER_SHIPMENTS

DHL Express booking idempotency store.

| Column | Type | Description |
|---|---|---|
| `idempotency_key` | TEXT PK | Booking dedup key |
| `batch_id` | TEXT | |
| `mode` | TEXT | `shadow` or `live` |
| `state` | TEXT | `pending`/`submitted`/`complete`/`failed` |
| `tracking_ref` | TEXT | AWB returned by DHL |
| `service_product` | TEXT | DHL service code |
| `dimensions_json` | TEXT | Package dimensions |

**NOTE:** Live submissions are REJECTED by code. Only shadow mode processes without operator allowlist override.

---

### FINANCE_POSTINGS (finance_postings.sqlite)

Payment and charge accounting. All amounts in INTEGER CENTS.

**charges:**

| Column | Type | Description |
|---|---|---|
| `batch_id` | TEXT | |
| `client_name` | TEXT | |
| `charge_type` | TEXT | `net_goods`/`freight`/`insurance`/`duty`/`vat`/`other` |
| `amount_minor` | INTEGER | Amount in cents (e.g. 10050 = 100.50 PLN) |
| `currency` | TEXT | |
| `posting_id` | INTEGER FK | Links to posting |

**postings → payments → payment_allocations** — standard double-entry structure.

---

### PROFORMA_LINKS.DB

Shared by two modules; stores proforma draft state.

| Table | Purpose |
|---|---|
| `proforma_links` | Draft to wFirma proforma linkage |
| Conflict tables | Detection, detection events, resolution history |

**Proforma states:** `draft → editing → approved → posting → posted → cancelled → superseded`

---

### PRODUCT_DESCRIPTIONS

Bilingual product name registry. Single source of truth for PZ PDF and wFirma.

| Column | Type | Description |
|---|---|---|
| `product_code` | TEXT PK | Internal product code |
| `item_type` | TEXT | Item type classification |
| `name_pl` | TEXT | Polish name |
| `description_pl` | TEXT | Polish description |
| `description_en` | TEXT | English description |
| `material_pl` | TEXT | Material in Polish |
| `purpose_pl` | TEXT | Purpose in Polish |
| `description_block` | TEXT | Multi-line block for customs |
| `description_line` | TEXT | Single-line customs description |
| `source` | TEXT | `auto` or `manual` |

---

### HS_CODES (master_data.sqlite)

Customs classification reference.

| Column | Type | Description |
|---|---|---|
| `hs_code` | TEXT PK | 6-10 digit HS/HSN code |
| `description_pl` | TEXT | Polish description |
| `description_en` | TEXT | English description |
| `duty_rate_pct` | TEXT (Decimal) | Import duty rate % |
| `vat_rate_pct` | TEXT (Decimal) | VAT rate % |
| `active` | INTEGER | 1 = active |

---

## Cross-System Relationship Summary

```
batch_id ──────────── ALL systems (primary join key)
    │
    ├── documents.db ─── shipment_documents (document pivot)
    │       ├── invoice_lines (FOB, qty per line)
    │       ├── customs_declarations (duty, MRN)
    │       ├── pz_documents (netto/brutto/doc_no)
    │       └── sales_packing_lines (customer allocation)
    │
    ├── customer_master.sqlite (contractor_id)
    │       └── client_shipping_addresses
    │
    ├── wfirma_db.sqlite (product_code → wfirma_product_id)
    │
    ├── finance_postings.sqlite (charges/postings)
    │
    ├── tracking.db (awb events + email message_id dedup)
    │
    └── carrier_shipments.db (DHL booking state)

awb ──────────────── documents.db (shipment_documents.awb)
                     tracking.db (AWB events)
                     email_evidence.db (extracted from email)
                     DHL Express API (tracking_ref)

contractor_id ────── customer_master.sqlite (bill_to_contractor_id)
                     documents.db (client_contractor_id, supplier_contractor_id)
                     wFirma API (all operations)
                     proforma_links.db

product_code ──────── invoice_lines (batch-scope)
                      product_descriptions (global name registry)
                      wfirma_db.sqlite (→ wfirma_product_id)
                      sales_packing_lines (customer allocation)
```

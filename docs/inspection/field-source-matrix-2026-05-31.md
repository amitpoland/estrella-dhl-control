# Field-Source Matrix — Estrella PZ System
**Date:** 2026-05-31 | **Branch:** feat/inspection-field-source-matrix | **Base:** origin/main @ 620cf32  
**Scope:** read-only research; no code changed. PR #412 noted separately.

---

## PHASE 0 — Masters Inventory

### M1 — Customer Master
**File:** `service/app/services/customer_master_db.py`  
**Table:** `customer_master` in `<storage_root>/customer_master.sqlite`  
**Key:** `bill_to_contractor_id` (wFirma contractor id)  
**Read endpoint:** `GET /api/v1/customer-master/{contractor_id}`  
**List endpoint:** `GET /api/v1/customer-master/`

**Key columns (all governed by this table):**

| Column | Type | Purpose |
|---|---|---|
| `bill_to_contractor_id` | str | wFirma contractor id — primary key |
| `bill_to_name` | str | Legal billing name |
| `country` | ISO-3166-2 | Drives VAT-mode decision |
| `nip` / `vat_eu_number` | str | VAT / EORI |
| `eori` | str | EORI for customs — operator-entered, wFirma does NOT carry this |
| `preferred_proforma_series_id` | str | wFirma series id for proformas |
| `preferred_invoice_series_id` | str | wFirma series id for final invoices |
| `vat_mode` | int | 222 / 228 / 229 — wFirma vat_code numeric id |
| `default_currency` | PLN/USD/EUR | Header currency for proformas |
| `default_language_id` | str | wFirma translation_language_id |
| `preferred_payment_method` | str | transfer\|cash\|card\|compensation |
| `payment_terms_days` | int | Days to pay |
| `freight_service_id` | str | wFirma good_id for freight line (default: "13002743" = Fedex Courier) |
| `freight_fixed_amount_eur/usd` | Decimal | Fixed freight amounts per currency |
| `freight_label_pl/en` | str | Polish/English billing label for freight |
| `insurance_service_id` | str | wFirma good_id for insurance line (default: "13102217") |
| `insurance_fixed_amount_eur/usd` | Decimal | Fixed insurance amounts |
| `insurance_rate` | Decimal | Formula rate (default 0.0035) |
| `ship_to_*` | various | Consignee address (Shape A = alternate address; Shape B = separate wFirma contractor) |
| `ship_to_contractor_id` | str | Shape B consignee wFirma id |
| `kyc_status` / `aml_risk_rating` | str | KYC/AML — stored but NOT enforced |
| `credit_limit` / `kuke_*` | Decimal | Credit — stored but NOT enforced (Layer 1 only) |

**Sub-table: `client_carrier_accounts`** (in same `customer_master.sqlite`)  
Key: `(contractor_id, carrier, account_number)` — `carrier` ∈ {dhl, fedex, ups, other}  
Fields: `account_number`, `payment_type` (shipper/receiver/third_party), `service_level`, `is_default`  
**Read endpoint:** `GET /api/v1/customer-master/{contractor_id}/carrier-accounts`  
**⚠ NOT consumed by DHL label/shipment creation today** — DHL uses `settings.dhl_express_account_number` (single global env var), not per-client accounts.

---

### M2 — wFirma Customer Mapping
**File:** `service/app/services/wfirma_db.py`  
**Table:** `wfirma_customers` in `<storage_root>/wfirma.db`  
**Key:** `client_name` (unique text index)  
**Columns:** `wfirma_customer_id`, `vat_id`, `country`, `match_status` (pending/matched/not_found/error)  
This is the local name→wFirma-id bridge, NOT the full customer master. The master is M1.

---

### M3 — wFirma Product Mapping
**File:** `service/app/services/wfirma_db.py`  
**Table:** `wfirma_products` in `<storage_root>/wfirma.db`  
**Key:** `product_code` (unique)  
**Columns:** `wfirma_product_id`, `product_name_pl`, `unit`, `vat_rate` (default "23"), `warehouse_id`, `sync_status`  
**Read endpoint:** `GET /api/v1/wfirma/products`  

**⚠ This is NOT a product master.** It carries only name_pl, unit, vat_rate (text), wfirma_product_id. It has no HS code, no EN description, no metal/karat, no origin, no category. See M4 and M5 for augmentation.

---

### M4 — Product Local Overlay
**File:** `service/app/services/master_data_db.py`  
**Table:** `product_local` in `<storage_root>/master_data.sqlite`  
**Key:** `product_code`  
**Columns:** `hs_code_override`, `unit_override`, `design_code_link`, `origin_country` (default "IN"), `active`, soft-delete  
**Read endpoint:** `GET /api/v1/master-data/product-local/{product_code}`  
**Partial product master** — overlays HS and origin onto the wFirma product; no PL/EN descriptions.

---

### M5 — Product Descriptions
**File:** `service/app/services/document_db.py`  
**Table:** `product_descriptions` in `<storage_root>/documents.db`  
**Key:** `product_code`  
**Columns:** `item_type`, `name_pl`, `description_pl`, `description_en`, `material_pl`, `purpose_pl`, `description_block`, `description_line`, `karat`, `metal_color`, `quality_string`, `stone_type`, `unit_price_eur`, `unit_price_usd`, `confidence`, `supplier_prefix`, `is_globally_unique`  
**Source:** `auto` (populated by `product_identity_engine`) or operator-locked  
**Read endpoint:** none direct — read via `GET /api/v1/proforma/draft/{id}` enrichment  
**Partial product master** — carries bilingual descriptions and identity attributes; no HS code.

---

### M6 — Designs Master
**File:** `service/app/services/master_data_db.py`  
**Table:** `designs` in `<storage_root>/master_data.sqlite`  
**Key:** `design_code`  
**Columns:** `display_name`, `product_ref`, `design_family`, `collection`, `metal`, `stone_summary`, `hs_code`, `unit`, soft-delete  
**Read endpoint:** `GET /api/v1/master-data/designs`  
**⚠ EXPLICIT CONSTRAINT in code:** `product_identity_engine MUST NOT read this table`. Additive local reference; soft FK to `product_local.product_code` and `hs_codes.hs_code` — no SQL enforcement.

---

### M7 — HS Codes Dictionary
**File:** `service/app/services/master_data_db.py`  
**Table:** `hs_codes` in `<storage_root>/master_data.sqlite`  
**Key:** `hs_code` (4–12 digit)  
**Columns:** `description_pl`, `description_en`, `duty_rate_pct`, `vat_rate_pct`, `active`, soft-delete  
**Read endpoint:** `GET /api/v1/master-data/hs-codes/{hs_code}`

---

### M8 — Company Profile (Estrella as seller/shipper)
**File:** `service/app/services/master_data_db.py`  
**Table:** `company_profile` (id=1) in `<storage_root>/master_data.sqlite`  
**Columns:** `legal_name`, `short_name`, `street`, `postal_city`, `country`, `nip`, `vat_eu`, `regon`, `email`, `phone`, `iban_eur/usd/pln`, `swift`, `bank_name`, `place_of_issue`, `signatory_name`, `signatory_title`, `returns_policy_pl`, `gdpr_text_pl`  
**Read/write endpoint:** `GET/PATCH /api/v1/settings/company-profile`  
**⚠ NOT consumed by Polish Description PDF.** The generator reads exporter name from `batch["invoices"][0]["exporter_name"]` (parsed from purchase invoice) or falls back to hardcoded `"Estrella Jewels LLP."`. `RECIPIENT_NAME = "ESTRELLA JEWELS SP. Z O. O. SP. K."` is a module-level constant at line 134 of `polish_description_generator.py`.

---

### M9 — VAT-Code Configuration
**File:** `service/app/services/master_data_db.py`  
**Table:** `vat_config` in `<storage_root>/master_data.sqlite`  
**Columns:** `country`, `product_type`, `rate_pct`, `rate_code`, `effective_from`, `effective_to`  
**Read endpoint:** `GET /api/v1/master-data/vat-config`  
**⚠ NOT consumed by wFirma invoice path.** Table is reference-only; does NOT override VAT codes used by wFirma.

The **actual VAT-code decision for proformas/invoices** is:

1. `decide_proforma_vat_context(customer_country, customer_vat_id)` in `wfirma_client.py:1716` — **HARDCODED logic table:**
   - PL → `vat_code="23"` (standard 23%)
   - EU non-PL + valid VAT → `vat_code="WDT"` (0% intra-community)
   - EU non-PL + no VAT → BLOCKED
   - non-EU → `vat_code="EXP"` (0% export)
   - country missing → BLOCKED
   EU member states are a hardcoded `frozenset` at `wfirma_client.py:1709`.

2. `find_vat_code_id_by_code(code)` in `wfirma_client.py:1757` — live lookup via `vat_codes/find` API, cached in-process in `_VAT_CODE_ID_CACHE`. Returns the wFirma internal numeric ID for that code string.

**The VAT-code assignment rule (domestic/WDT/export) is fully hardcoded logic, not a configurable table.**

---

### M10 — Invoice/Proforma Series
**Source:** `wfirma_dictionary_cache.py` — local in-process cache seeded from `INVOICE_SERIES` / `PROFORMA_SERIES` baseline constants + live wFirma `invoiceseries/find` overlay.  
**No local DB table.** `get_dictionaries()` returns the merged list.  
**Read endpoint:** `GET /api/v1/wfirma-capabilities/dictionaries` (partial)  
**Per-client series preference:** `customer_master.preferred_proforma_series_id` / `preferred_invoice_series_id` (M1).

---

### M11 — FX Rates (reference only)
**File:** `service/app/services/master_data_db.py`  
**Table:** `fx_rates` in `<storage_root>/master_data.sqlite`  
**⚠ PURE REFERENCE** — not consumed by the PZ landed-cost / customs calculation engine. Engine uses live NBP rates.

---

### M12 — Incoterms Dictionary
**File:** `service/app/services/master_data_db.py`  
**Table:** `incoterms` in `<storage_root>/master_data.sqlite`  
**Columns:** `code`, `name`, `risk_transfer_point`, `freight_included`, `insurance_included`, `customs_included`  
**Read endpoint:** `GET /api/v1/master-data/incoterms`  
**⚠ No consumer today** — table exists for reference; no evidence proforma/DHL/PZ routes read `incoterm` from this table.

---

### M13 — Proforma Draft (`proforma_drafts`)
**File:** `service/app/services/proforma_invoice_link_db.py`  
**Table:** `proforma_drafts` in `<storage_root>/proforma_links.db`  
**Key:** `id` (auto-increment); unique on `(batch_id, client_name)` active draft  
This is the per-batch-per-client working document, NOT a master. See Phase 1 and 2 below.

---

### Product-Master Existence — Direct Answer

**Q: Does a PRODUCT MASTER exist keyed by product/design id holding HS, PL+EN description, category, metal/karat, origin, unit?**

**NO — there is no single product master.** The data is fragmented across four tables:

| Table | Keys | Has HS | Has PL desc | Has EN desc | Has category | Has metal/karat | Has origin | Has unit |
|---|---|---|---|---|---|---|---|---|
| `wfirma_products` (M3) | product_code | NO | name_pl only | NO | NO | NO | NO | unit (szt.) |
| `product_local` (M4) | product_code | override only | NO | NO | NO | NO | origin_country (default IN) | unit_override |
| `product_descriptions` (M5) | product_code | NO | description_pl/en, name_pl | description_en | item_type | karat, metal_color, stone_type | NO | NO |
| `designs` (M6) | design_code | hs_code | NO | NO | NO | metal | NO | unit |

No single table has ALL six attributes (HS + PL desc + EN desc + category + metal/karat + origin + unit) for a given product_code. **product_code is not a FK to any of these tables — joins are by-value only, no SQL FK enforcement.**

**Q: Is the metal×category→HS / standard-description mapping a table or hardcoded?**

**NEITHER is governed by a table lookup today.** HS codes flow from:
1. `invoice_lines.hs_code` / `invoice_lines.hsn_code` — parsed from the PDF purchase invoice (free-text parse)
2. `product_local.hs_code_override` (M4) — operator override per product_code
3. `designs.hs_code` (M6) — operator-entered per design_code; `product_identity_engine` must NOT read this table

There is no `metal × category → HS` mapping table. HS is either invoice-parsed or manually overridden per-product. The `hs_codes` dictionary (M7) holds description+rates for known codes, but there is no automated assignment rule.

**Q: Is the VAT-code map (23→222, WDT→228…) a table or hardcoded?**

**HARDCODED in `wfirma_client.py:1716`.** The domestic/WDT/export decision is a pure-code function with a frozenset of EU countries. The numeric wFirma internal ID (e.g., 222, 228) is resolved at runtime via live wFirma API `vat_codes/find` and cached in `_VAT_CODE_ID_CACHE` — wFirma assigns those IDs and they can vary per installation. The **semantic mapping** (country → vat_code string → blocked/not) is hardcoded. The **wFirma internal id** (e.g., "222") is live-resolved from wFirma, not stored locally.

---

## PHASE 1 — Proforma Lines: packing-list → proforma line

### Source chain

1. **Packing uploaded** → parsed into `packing_lines` (purchase) and `sales_packing_lines` (sales)
2. **Preview / create** → `_build_preview()` reads `v_sales_to_wfirma` view joining `sales_packing_lines + packing_lines` per `batch_id + client_name`
3. **Draft created** → `source_lines_json` snapshot written (immutable history); `editable_lines_json` is the mutable working copy
4. **Operator edits** → can PATCH any field in `editable_lines_json` via `PATCH /draft/{id}` or `PATCH /draft/{id}/lines/{lid}`
5. **Post to wFirma** → `_build_proforma_request_from_draft(draft)` reads `editable_lines_json`

### Line field sources

| Line Field | Source | Governed by Master? | Notes |
|---|---|---|---|
| `product_code` | `packing_lines.product_code` (from purchase parse) | **NO** — free-text barcode parsed from PDF | Bridge via `design_product_mapping` resolves `design_no → product_code`; ambiguity is a blocker |
| `design_no` | `sales_packing_lines.design_no` (from sales parse) | NO — free-text from sales packing XLSX | Used to join; design_no → product_code via bridge |
| `qty` | `sales_packing_lines.qty` | NO — packing parse | Validated >0 at post time |
| `unit_price` | `sales_packing_lines.unit_price` (sales price, NOT import cost) | NO — packing parse; operator can PATCH | Must be >0 before post; zero-price guard at post time |
| `currency` | `sales_packing_lines.currency` | NO — packing parse; operator can PATCH | Single-currency check enforced at post time |
| `product name` (wFirma line content) | `wfirma_products.product_name_pl` via `wfirma_product_id` | PARTIAL — M3 has name_pl; no EN | Name overridable via locked `product_descriptions.description_line` (M5) |
| `hs_code` | From `invoice_lines.hs_code`/`hsn_code` (purchase invoice parse) OR `product_local.hs_code_override` (M4) | **PARTIAL** — M4 overlay is governed; invoice parse is free-text | No hs_code column in `editable_lines_json` by default; enriched at read/display time from M4. NOT sent to wFirma in proforma lines |
| `description_pl` / `description_en` | `product_descriptions` (M5) — AI-generated + operator-lockable | PARTIAL — locked descriptions governed; auto-gen not | Used in PZ PDF; not in proforma lines directly |
| `metal / karat` | `packing_lines.metal`, `packing_lines.karat` (purchase parse) | NO — packing parse | In packing DB; enriched into M5 by product_identity_engine |
| `stone_type` | `packing_lines.stone_type` | NO — packing parse | Same as above |
| `origin_country` | `product_local.origin_country` (M4) default "IN" | PARTIAL — M4 is governed but defaults hardcoded to "IN" | Shown in readiness panel; not sent to wFirma |
| `gross_weight` / `net_weight` | `packing_lines.gross_weight/net_weight` | NO — packing parse | Not in proforma line; used in PZ/customs |
| `unit` | `wfirma_products.unit` (default "szt.") | PARTIAL — M3; operator-set | Passed to wFirma via ProformaRequest.lines |
| `vat_rate` | Derived from `decide_proforma_vat_context(customer_country, vat_id)` | **HARDCODED LOGIC** | See M9 above |
| `exchange_rate` | Not set on sales rows; wFirma applies own FX | NO | N/A |

### Line storage and FK

`editable_lines_json` is a JSON array stored in `proforma_drafts`. Each element has `product_code`, `design_no`, `qty`, `unit_price`, `currency`. **There is no FK** from the draft line to any product master row. `product_code` is stored as a plain text value; consistency with M3/M4/M5 is by-value convention only.

---

## PHASE 2 — Party + Series + Accounting: source at build/convert

| Field | Source at draft-create | Source at wFirma post | Bypass via `*_override_json`? | Governed by master? |
|---|---|---|---|---|
| **Buyer name** (bill-to) | `_resolve_customer(client_name)` → `wfirma_customers.client_name` → wFirma `contractor.name` | `req.client_name` from draft | YES — `buyer_override_json.name` **replaces** the master name | **NO** — override bypasses master entirely |
| **Buyer address** | Resolved from wFirma contractor at build time (not cached locally in proforma) | As above | YES — `buyer_override_json` fields | **NO** |
| **Buyer VAT / NIP** | From wFirma contractor XML | As above | YES — `buyer_override_json` | **NO** |
| **Ship-to / consignee** | `customer_master.ship_to_*` or `ship_to_contractor_id` (M1) | `req.wfirma_contractor_receiver_id` + receiver preflight | YES — `ship_to_override_json` **replaces** | PARTIAL — M1 governs default; override bypasses |
| **Proforma series** | `customer_master.preferred_proforma_series_id` → `pick_proforma_series_id()` | Same as build | NO override exists for series | YES — M1 governs (gap: empty = no series, no blocker at create) |
| **Invoice series** (at convert) | `snap.series_id` (from proforma XML) → fallback `customer_master.preferred_invoice_series_id` | wFirma `invoices/add` uses `plan.series_id` | `body.final_series_id` in convert request | PARTIAL — M1 preferred_invoice_series_id is governed; snap.series_id is proforma series (reused as invoice series fallback — semantic gap) |
| **VAT mode / code** | `decide_proforma_vat_context(country, vat_id)` — pure code function | Same function via request | NO direct override | HARDCODED rule; `customer_master.vat_mode` stored but NOT used in this path |
| **VAT EU / EORI** | `customer_master.vat_eu_number` (M1); used in `decide_proforma_vat_context` | From wFirma contractor record at lookup | NO | YES — M1; but wFirma live lookup supersedes |
| **Customer EORI** | `customer_master.eori` (M1) | **NOT consumed by proforma/invoice path** — stored only | NO | Field exists in M1 but no route reads it for document generation today |
| **Currency** | `sales_packing_lines.currency` (dominant across lines) | `draft.currency` | YES — `PATCH /draft/{id}` can change currency directly | **NO** — not sourced from customer_master.default_currency at create; packing line currency wins |
| **Payment method** | NOT populated at draft-create from master | `req.payment_terms_json.method`? | YES — `payment_terms_json` on draft | PARTIAL — `customer_master.preferred_payment_method` exists but NOT applied at create |
| **Payment terms days** | NOT populated at draft-create from master | Via `payment_terms_json` | YES — `payment_terms_json` | PARTIAL — `customer_master.payment_terms_days` exists but NOT applied at create |
| **Freight** | Service charge computed by `suggest_service_charges` from M1 freight fields | Snapshotted into `service_charges_json` at create | Operator can PATCH service charges | PARTIAL — M1 governs default amounts; editable after creation |
| **Insurance** | Service charge computed from M1 insurance fields | Same | Same | PARTIAL — same as freight |
| **Incoterm** | `draft.incoterm` (nullable, no default from M1) | As stored in draft | NO explicit override — direct field | **NO** — no incoterm is pulled from M1 or M12 at create time; field sits empty unless operator explicitly sets it |
| **Language** | `customer_master.default_language_id` (M1) via `ProformaRequest` | Built at post time | NO | YES — M1 |
| **Remarks** | Empty unless operator sets `draft.remarks` | Passed to wFirma description | NO | **NO** — free text |
| **Contractor id** | `wfirma_customers.wfirma_customer_id` via `_resolve_customer()` | `req.wfirma_contractor_id` | NO | YES — M2 (wfirma_customers bridge) required; no contractor_id = blocker |
| **Receiver id** | `customer_master.ship_to_contractor_id` or resolved from `ship_to_override_json` | Receiver preflight against wFirma | Overrideable via `ship_to_override_json` | PARTIAL |

### wFirma read-back / write-back
- **Reads from wFirma:** contractor lookup (`fetch_contractor_by_id`), receiver preflight, proforma XML (`fetch_invoice_xml`) — all pre/post conversion
- **Writes to wFirma:** `invoices/add` (proforma creation), `invoices/add` (invoice creation) — both gated by flags
- **No write-back to customer master from wFirma post**: customer master is write-once from operator; wFirma sync is one-way inbound (identity fields only, never financial/series overwrite)

---

## PHASE 3 — DHL / ZC429: field sources

| Field | Surface | Source | Governed by Master? | Gap |
|---|---|---|---|---|
| **Consignor / Shipper name** | Polish Description PDF | `batch["invoices"][0]["exporter_name"]` (purchase invoice parse) → fallback hardcoded `"Estrella Jewels LLP."` | **NO** — hardcoded fallback; company_profile NOT consumed here | **GAP 1** — `company_profile.legal_name` (M8) exists but is NOT wired to PDF generator |
| **Consignee name** | Polish Description PDF | `RECIPIENT_NAME = "ESTRELLA JEWELS SP. Z O. O. SP. K."` — **module-level constant** at `polish_description_generator.py:134` | **NO — HARDCODED constant** | **GAP 2** — consignee should be the importer of record; hardcoded prevents multi-entity routing |
| **Consignor / Shipper** | AWB `awb_documents.shipper_name` | Parsed from AWB PDF / DHL tracking | NO — packing parse | |
| **Consignee** | AWB `awb_documents.consignee_name` | Parsed from AWB PDF / DHL tracking | NO — packing parse | |
| **EORI (Estrella)** | Polish Description PDF, ZC429 | NOT consumed; `company_profile.vat_eu` exists (M8) but wiring absent | **NO** | **GAP 3** |
| **EORI (customer)** | Customer customs docs | `customer_master.eori` (M1) stored but never read by any document-generation route today | **STORED, NOT WIRED** | **GAP 4** |
| **HS code** | ZC429 / SAD, PZ PDF, Polish Description | `invoice_lines.hs_code` / `invoice_lines.hsn_code` (purchase invoice parse) OR `product_local.hs_code_override` (M4) | PARTIAL — M4 overlay is governed; invoice parse is free-text | **GAP 5** — HS can still come from free-text PDF parse with no master validation |
| **Goods description (PL)** | Polish Description PDF | `_extract_items(batch)` → aggregates `item_type` counts from `batch["rows"]` (engine output) | NO — derived from engine item_type groups | Not individually product-keyed; grouped by item_type |
| **Origin country** | ZC429 / PZ PDF | `product_local.origin_country` (M4) default "IN" | PARTIAL — M4 governed; default hardcoded | Most jewellery correctly defaults to India |
| **Customs value (CIF)** | ZC429 / PZ calc | Computed by `process_batch()` engine from invoice lines | YES — engine owns this; never recalculated outside | |
| **Duty** | ZC429 | From ZC429 SAD / A00 parsed by engine | NO — free-text parse; not cross-referenced to M7 `duty_rate_pct` | **GAP 6** — M7 has duty_rate_pct but engine uses ZC429 parse, not the table |
| **Incoterm** | ZC429, DHL label | `draft.incoterm` (nullable, no master default) | **NO** — no incoterm flows from M1/M12; must be manually set per draft | **GAP 7** |
| **AWB** | All DHL surfaces | `audit.json["dhl_awb"]` / `awb_documents.awb` | NO — from DHL tracking | |
| **Carrier account number** | DHL label/shipment | `settings.dhl_express_account_number` (single global env var) | **NO — global env var only** | **GAP 8** — `client_carrier_accounts` table exists with per-client accounts but is NOT consumed by DHL label creation |
| **Service level** | DHL label | `client_carrier_accounts.service_level` (M1 sub-table) — **NOT consumed** | **NOT WIRED** | Same as GAP 8 |
| **Payment type** | DHL label | `client_carrier_accounts.payment_type` (M1 sub-table) — **NOT consumed** | **NOT WIRED** | Same as GAP 8 |
| **Weights** | PZ PDF, DHL, ZC429 | `packing_lines.gross_weight/net_weight` (packing parse) + `invoice_lines.gross_weight/net_weight` | NO — packing parse | |
| **Invoice refs (MRN)** | ZC429/SAD | `customs_declarations.mrn` parsed from SAD/ZC429 | NO — document parse | |

---

## PHASE 4 — Sales + Inventory

### Sales Surface
`routes_sales.py` exposes a single endpoint: `GET /api/v1/sales/linkage/{batch_id}` which calls `sales_linkage.get_sales_linkage()`. This is a **read-only linkage tool** — it joins `sales_packing_lines` to `inventory_state` by scan_code. It does NOT create, modify, or post any financial document. It surfaces stock availability for sales planning.

### Inventory State
**Table:** `inventory_state` in `<storage_root>/warehouse.db` (via `warehouse_db.py`)  
**Key:** `scan_code` (unique per physical piece)  
**Columns:** `product_code`, `design_no`, `batch_id`, `state` (enum), `updated_at`, `updated_by`  
**States:** PURCHASE_TRANSIT, WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED, SALES_TRANSIT, SAMPLE_OUT, CLOSED

### Piece-to-master linkage
`inventory_state` carries `product_code` (text) and `design_no` (text). **No SQL FK** to any product master table. The link to `product_local` (M4), `product_descriptions` (M5), or `designs` (M6) is by-value text match only.

`inventory_state` carries `batch_id` and by join through `packing_lines.scan_code` → `packing_lines.product_code`. **There is no direct proforma_id or invoice_id FK on inventory_state rows.** The proforma → inventory link is indirect: proforma → product_code → inventory_state by state.

### Inventory writer
Single writer: `inventory_state_engine.transition(scan_code, to_state, trigger, operator, note)` — enforced by docstring ("never call transition() outside the engine"). Packing upload → intake triggers PURCHASE_TRANSIT; warehouse scan → WAREHOUSE_STOCK; proforma create gates on eligible states; physical dispatch → CLIENT_DISPATCHED.

### Packing/proforma pieces → inventory
- Packing upload: `init_inventory_from_packing()` creates inventory_state rows for each scan_code in PURCHASE_TRANSIT
- Proforma create: gated on stock state (pieces must be in WAREHOUSE_STOCK / DIRECT_DISPATCH_READY / CLIENT_DISPATCHED) but **does NOT transition inventory state at creation time** — proforma is commercial, not physical movement
- Physical dispatch or wFirma PZ: triggers state transitions

---

## PHASE 5 — Convert-time Validation Gaps

### Existing pre-flight checks (what IS validated before invoice creation)

| Check | Location | What it checks |
|---|---|---|
| `WFIRMA_CREATE_INVOICE_ALLOWED` flag | `_check_invoice_approval_gates()` line 2676 | Boolean env var gate |
| Confirm token | `_check_invoice_approval_gates()` | Explicit operator confirmation string |
| X-Operator header | `_check_invoice_approval_gates()` | Non-empty operator identity |
| Draft status = "issued" | `_gather_conversion_inputs()` | Draft must have a `wfirma_proforma_id` |
| `fetch_invoice_xml` + `parse_proforma_xml` | Post-gate | Validates proforma still exists in wFirma |
| Series resolution | Lines 2761–2784 | Checks series_id chain; raises ValueError if all three fallbacks empty |
| Duplicate conversion guard | `_link_already_exists()` | Prevents double conversion of same proforma |
| Receiver preflight | Lines 3072–3088 | Live wFirma lookup if draft has receiver_id |
| Line count verify | `create_proforma_draft()` → verify-after-create | Confirms wFirma persisted all lines (post-post check on proforma; NOT on invoice) |

### GAPS — what is NOT validated at convert time

| # | Gap | Detail |
|---|---|---|
| **G1** | HS code presence on every line | No check that each proforma line has a valid HS code. Invoice has no HS codes (proforma commercial content flows directly). **PR #412 adds `check_post_readiness()` — but only at proforma POST time, not at invoice convert time, and only when `proforma_draft_governance_enabled=True`.** |
| **G2** | Line resolves to a mastered product | No check at convert time that `product_code` in the proforma line still exists in `wfirma_products`/`product_local`. |
| **G3** | Customer EORI present for customs documents | `customer_master.eori` is never read at convert time. |
| **G4** | Incoterm set | `draft.incoterm` is nullable; no convert-time check. |
| **G5** | Series_id is an INVOICE series, not proforma series | The fallback reuses `snap.series_id` (proforma series) as an invoice series. wFirma may reject this silently or assign a wrong series. No cross-reference to validate the resolved series_id is actually an invoice series (not proforma) in `get_dictionaries()["invoice_series"]`. |
| **G6** | Currency matches customer master default | No check that draft currency matches `customer_master.default_currency`. |
| **G7** | VAT mode consistent with customer master `vat_mode` column | `vat_mode` is stored in M1 but NOT used in the proforma/invoice path; `decide_proforma_vat_context()` re-derives from country+VAT. If master says vat_mode=228 (WDT) but customer country changed to non-EU, no reconciliation alert. |

### What PR #412 adds (unmerged, `proforma_draft_governance_enabled=False` by default)

| Addition | Where it fires | Status |
|---|---|---|
| `check_creation_lines()` — design_no ≤128 chars, hs_code format if provided, product_code non-empty | Draft creation (`POST /draft`) | Flag-gated OFF by default |
| `check_top_patch()` — buyer/ship_to override keys allowed, currency 3-letter ISO | Top-level PATCH | Flag-gated OFF |
| `check_line_patch()` — hs_code format, unit_price sign | Line PATCH | Flag-gated OFF |
| `check_post_readiness()` — every line must have non-empty hs_code | Proforma POST (pre-wFirma call) | Flag-gated OFF |
| `check_convert_series()` — series_id must not be "0"/"" at convert time | `proforma_to_invoice()` post-series-resolution | Flag-gated OFF |

**PR #412 closes G1 and partially G5 at convert time (series must resolve), but only when the flag is turned on. Gaps G2–G4, G6–G7 remain open.**

---

## PHASE 6 — Output

### 6A — Masters Summary

| # | Name | Table(s) | DB file | Key | Covers |
|---|---|---|---|---|---|
| M1 | Customer Master | `customer_master`, `client_carrier_accounts` | `customer_master.sqlite` | `bill_to_contractor_id` | VAT, series, ship-to, freight, insurance, credit, KYC, carrier accounts |
| M2 | wFirma Customer Mapping | `wfirma_customers` | `wfirma.db` | `client_name` | name→wFirma id bridge |
| M3 | wFirma Product Mapping | `wfirma_products` | `wfirma.db` | `product_code` | wFirma product id, name_pl, unit, vat_rate |
| M4 | Product Local Overlay | `product_local` | `master_data.sqlite` | `product_code` | hs_code override, unit override, origin_country |
| M5 | Product Descriptions | `product_descriptions` | `documents.db` | `product_code` | PL+EN name/description, karat, metal_color, stone_type, confidence |
| M6 | Designs Master | `designs` | `master_data.sqlite` | `design_code` | design_family, collection, metal, stone_summary, hs_code, unit |
| M7 | HS Codes Dictionary | `hs_codes` | `master_data.sqlite` | `hs_code` | description_pl/en, duty_rate_pct, vat_rate_pct |
| M8 | Company Profile (Estrella) | `company_profile` | `master_data.sqlite` | id=1 | legal_name, NIP, VAT-EU, address, IBANs |
| M9 | VAT Config (ref only) | `vat_config` | `master_data.sqlite` | (country, product_type) | Reference only — NOT consumed by invoice path |
| M10 | Invoice/Proforma Series | in-process cache | none | series_id | Available series from wFirma |
| M11 | FX Rates (ref only) | `fx_rates` | `master_data.sqlite` | (rate_date, pair) | Reference only — NOT consumed by engine |
| M12 | Incoterms | `incoterms` | `master_data.sqlite` | code | Reference only — NOT consumed by proforma/DHL today |
| M13 | Carrier Config | `carriers_config` | `master_data.sqlite` | carrier_code | Reference only — NOT consumed by DHL label |

---

### 6B — Field-Source Matrix

| Field | Consuming Surface(s) | Current Source | Governed by Master? | Proposed Owner | Gap # |
|---|---|---|---|---|---|
| **product_code** | Proforma lines, inventory, PZ | packing_lines parse (free-text) | NO | M4 product_local (enforce non-null FK) | G2 |
| **design_no** | Proforma resolution, inventory | sales packing XLSX parse | NO | M6 designs (enforce by-value link) | — |
| **HS code** | ZC429, PZ PDF, customs | invoice_lines parse OR product_local.hs_code_override | PARTIAL (M4 override only) | M4 product_local (required field, not just override) + M7 validation | G1, G5, GAP 5 |
| **PL description** | PZ PDF, proforma HTML | product_descriptions.description_pl (M5) locked | PARTIAL (locked by operator) | M5 governed | — |
| **EN description** | Proforma, DHL customs | product_descriptions.description_en (M5) locked | PARTIAL | M5 governed | — |
| **category / item_type** | Polish Description PDF | packing_lines.item_type (parse) | NO | M5 identity engine | — |
| **metal / karat** | PZ PDF, identity | packing_lines.metal/karat (parse) | NO | M5 identity engine + M6 | — |
| **origin country** | ZC429, PZ PDF | product_local.origin_country default "IN" | PARTIAL (M4; hardcoded default) | M4 (required field, validate non-null) | — |
| **unit** | Proforma wFirma line | wfirma_products.unit default "szt." | PARTIAL (M3) | M3 | — |
| **qty** | Proforma, inventory | sales packing XLSX | NO | Packing (parse + operator lock) | — |
| **unit_price (sales)** | Proforma lines | sales_packing_lines.unit_price | NO — parse; operator can PATCH | Packing (parse + operator lock) | — |
| **currency** | Proforma header | Dominant across sales packing lines | NO — not from customer_master.default_currency | M1 (seed from default_currency; packing overrides) | — |
| **VAT rate / mode** | Proforma, invoice | decide_proforma_vat_context() — HARDCODED rules | HARDCODED logic | wfirma_client (hardcoded — acceptable; but reconcile with M1.vat_mode) | G7 |
| **Buyer name** | Proforma, invoice | wfirma_customers → wFirma contractor name | YES — M2 → wFirma | wFirma (authoritative); M1 for overrides | — |
| **buyer_override** | Proforma HTML | buyer_override_json on draft (operator free-text) | **NO** — bypasses master | Restrict to M1 validated fields | GAP 9 |
| **ship_to / consignee** | Proforma, DHL | customer_master.ship_to_* (M1) | YES — M1 | M1 | — |
| **ship_to_override** | Proforma | ship_to_override_json (operator free-text) | **NO** — bypasses M1 | Restrict overrides to M1 shape | GAP 10 |
| **Proforma series** | Proforma wFirma | customer_master.preferred_proforma_series_id (M1) | YES — M1 | M1 | — |
| **Invoice series** | Invoice wFirma | snap.series_id (proforma series reused) → M1.preferred_invoice_series_id | PARTIAL — M1 fallback; snap is proforma series | M1 preferred_invoice_series_id (primary, not fallback) | G5 |
| **Incoterm** | Proforma draft, DHL, ZC429 | draft.incoterm (nullable; no default from M1 or M12) | **NO** | M1 (add preferred_incoterm) + M12 validation | G4, GAP 7 |
| **Payment method** | Proforma, invoice | payment_terms_json (operator set; M1.preferred_payment_method NOT applied) | **NO** — M1 not wired | M1 (apply at draft create) | — |
| **Payment terms days** | Proforma | payment_terms_json; M1.payment_terms_days NOT applied | **NO** | M1 | — |
| **Freight amount/service** | Proforma service charge | customer_master freight fields (M1) via suggest_service_charges | PARTIAL — M1 governs defaults; PATCH can override | M1 (sealed on approve) | — |
| **Insurance amount/service** | Proforma service charge | customer_master insurance fields (M1) | PARTIAL | M1 | — |
| **Consignor / Shipper** | Polish Description PDF | invoice parse → hardcoded fallback "Estrella Jewels LLP." | **NO — HARDCODED** | M8 company_profile.legal_name | GAP 1 |
| **Consignee (Polish PDF)** | Polish Description PDF | `RECIPIENT_NAME` module constant | **NO — HARDCODED CONSTANT** | M8 or M1 (importer of record) | GAP 2 |
| **Estrella EORI** | ZC429, customs | `company_profile.vat_eu` (M8) — NOT wired to any document generator | **NOT WIRED** | M8 | GAP 3 |
| **Customer EORI** | DHL customs docs | `customer_master.eori` (M1) — stored but NOT consumed by document routes | **STORED, NOT WIRED** | M1 | GAP 4 |
| **Duty rate** | ZC429, customs | ZC429/A00 parse (engine) | NO — parse from document | M7 hs_codes.duty_rate_pct (cross-reference) | GAP 6 |
| **Carrier account number** | DHL label | `settings.dhl_express_account_number` (global env var) | **NO — global env** | M1 client_carrier_accounts (per-client) | GAP 8 |
| **Service level** | DHL label | `client_carrier_accounts.service_level` — stored but NOT consumed | **NOT WIRED** | M1 client_carrier_accounts | GAP 8 |
| **Payment type (DHL)** | DHL label | `client_carrier_accounts.payment_type` — stored but NOT consumed | **NOT WIRED** | M1 client_carrier_accounts | GAP 8 |
| **remarks** | Proforma | draft.remarks (free text) | **NO** | Restrict to structured fields | GAP 11 |
| **Exchange rate (NBP)** | PZ engine | Live NBP API (engine) | NO — computed live | PZ engine (correct; reference fx_rates M11 for audit) | — |

---

### 6C — Numbered GAP LIST

| # | Field(s) | Ungoverned / Gap Type | Detail |
|---|---|---|---|
| **GAP 1** | Consignor / Shipper (Polish PDF) | Hardcoded fallback string | `polish_description_generator.py` falls back to hardcoded `"Estrella Jewels LLP."` when invoice parse returns nothing; `company_profile.legal_name` (M8) is never read by the generator |
| **GAP 2** | Consignee (Polish PDF) | Hardcoded module constant | `RECIPIENT_NAME = "ESTRELLA JEWELS SP. Z O. O. SP. K."` at `polish_description_generator.py:134` — prevents multi-entity consignee routing and cannot be changed without a code deploy |
| **GAP 3** | Estrella EORI | Stored but not wired | `company_profile.vat_eu` (M8) exists but no document-generation route reads it for ZC429 / customs document population |
| **GAP 4** | Customer EORI | Stored but not wired | `customer_master.eori` (M1) stored but not consumed by any proforma, invoice, or DHL document generation route today |
| **GAP 5** | HS code (line level) | No required-field validation; parse-or-override only | HS code flows from free-text purchase invoice PDF parse OR optional `product_local.hs_code_override`; no enforcement that every line has a valid HS before invoice conversion. PR #412 adds `check_post_readiness()` at proforma POST (flag OFF by default); no check at invoice convert time ever |
| **GAP 6** | Duty rate | ZC429 parse not cross-referenced to M7 | `hs_codes.duty_rate_pct` (M7) is never read by the PZ engine or validation layer. Engine uses A00 lines from ZC429 parse only. No sanity check against master |
| **GAP 7** | Incoterm | No master default; nullable draft field | `draft.incoterm` is nullable with no default from M1 or M12. No convert-time or post-time check that incoterm is set. No preferred_incoterm on customer master |
| **GAP 8** | DHL carrier account, service level, payment type | Master table exists; not wired to DHL label | `client_carrier_accounts` table (M1 sub-table) has per-client `account_number`, `payment_type`, `service_level` but all DHL label/shipment creation uses `settings.dhl_express_account_number` (single global env var). Per-client account selection is never triggered |
| **GAP 9** | buyer_override_json | Free-text bypasses customer master | Any key-value pair can be set in `buyer_override_json` overriding the wFirma/M1 billing address without validation against M1 schema. PR #412 `check_top_patch()` restricts allowed keys (flag OFF by default) |
| **GAP 10** | ship_to_override_json | Free-text bypasses M1 ship-to | Same as GAP 9 for ship-to/consignee address |
| **GAP 11** | draft.remarks | Free text; no structure | Remarks is a free-text blob with no schema, no length limit enforced, and passes directly into wFirma description field |
| **GAP 12** | Invoice series = proforma series reused | Semantic type mismatch | `snap.series_id` (proforma series from XML) is used as invoice series fallback without checking that the resolved ID is actually in `get_dictionaries()["invoice_series"]` (vs proforma_series). Can silently succeed or fail at wFirma with a wrong series type |
| **GAP 13** | customer_master.vat_mode not used in invoice path | Stored field ignored | M1 stores `vat_mode` (222/228/229) but `decide_proforma_vat_context()` re-derives VAT treatment from country+vat_id. If master vat_mode disagrees with the derived code there is no reconciliation or alert |
| **GAP 14** | currency not sourced from customer_master.default_currency | Per-shipment free-flow | Proforma header currency is dominant across sales packing lines, not seeded from `customer_master.default_currency`. Customer may have EUR as default but a USD packing list silently creates a USD proforma with no check |
| **GAP 15** | payment_method and payment_terms_days not applied at draft create | Stored in master; never propagated | `customer_master.preferred_payment_method` and `payment_terms_days` are stored in M1 but not applied to `payment_terms_json` at draft-create time. Must be manually set each shipment |
| **GAP 16** | No single product master — HS/description/origin split across 4 tables | Fragmented identity | A product's governed attributes are split: name_pl (M3), description_pl/en (M5), hs_code_override (M4), origin_country (M4), metal/karat (M5), hs_code design-level (M6). No authoritative product record with all fields in one place and no FK enforcement across them |
| **GAP 17** | No product_code FK on inventory_state, proforma draft lines, or packing_lines | By-value convention only | `inventory_state.product_code`, `editable_lines_json[].product_code`, `packing_lines.product_code` all store the value as free text with no FK enforcement to any master. Renaming a product_code in M3/M4 would silently break all historical records |

---

## Branch and SHA

Changes on this branch: 1 new file — `docs/inspection/field-source-matrix-2026-05-31.md`  
No code files modified. No .py or .html files touched.

Branch: `feat/inspection-field-source-matrix` off `origin/main @ 620cf32`

# W1 — Master + wFirma authority census

**Role:** INSPECTOR. Census only, no production code. **Repo:** `C:\PZ-main` @ `3748daae`
(== `origin/main` == production). **Date:** 2026-08-22.
Blocks A–D ran as parallel sub-agents; E3 was synthesised from all four.

Every claim is tagged **VERIFIED** (observed), **INFERRED** (reasoned) or **NO EVIDENCE**.

---

## 1. AUTHORITY MAP

| Concern | Owning resolver | Duplicates found | Verdict |
|---|---|---|---|
| Landed cost / freight / duty / totals | `process_batch()` — `pz_import_processor.py:3050` | none | **SINGLE** ✅ |
| `design_no` → `product_code` | `product_authority_resolver.py:205` | previously 3 copies in `sales_packing_matcher`, already consolidated (`product_authority_resolver.py:21`) | **SINGLE** ✅ |
| Customer identity | `customer_master.bill_to_contractor_id` (UNIQUE) — `customer_master_db.py:302` | `wfirma_customers` name cache — `wfirma_db.py:62` | **DUPLICATE** (cache, declared subordinate) |
| Product → wFirma `towar` id | `wfirma_product_mirror.wfirma_id` — `reservation_db.py:85`, declared canonical by `authority_consistency.py:5` | `wfirma_products.wfirma_product_id` — `wfirma_db.py:82` | **DUPLICATE** |
| VAT code | `master_data.sqlite` `vat_config` — `master_data_db.py:284` | hardcoded `222/228/229` — `vat_resolver.py:34-36`; `DEFAULT_VAT_CODE_ID="222"` — `pz_batch_schema.py:21` | **CONTRADICTORY** |
| Duty rate | ZC429/A00 at runtime — `pz_import_processor.py:3182` | `product_local.duty_rate_pct` + `vat_config.duty_rate_pct` — `master_data_db.py:32` | **CONTRADICTORY** (two dormant stores) |
| Piece status (V2 UI) | none | 4 implementations: `dashboard-page.jsx:79`, `dashboard-kanban.jsx:116`, `inventory-page.jsx:3372`, `documents-hub.jsx:564` | **DUPLICATE** |
| Piece identity (`scan_code`) | `_compute_scan_code` — `packing_db.py:44` | none | **SINGLE but DEFECTIVE** — see F-01 |
| Description block | `customs_description_engine.normalize_item_description():248` | cache layer `description_engine.get_description_block():365` can shadow it | **DUPLICATE** (cache shadows generator) |
| Customer allocation of a packing line | **none — does not exist** | — | **ABSENT** |
| Customer-master writes | `upsert_customer()` | 5 call sites (`routes_customer_master.py:1220,1399`, `routes_wfirma_capabilities.py:214,1643,1697`, `routes_intake.py:1161`); PR #1247 adds a 6th | **SINGLE fn, 6 writers** |

---

## 2. FINDINGS

| ID | Finding | Evidence | Tag | Sev | Blocks |
|---|---|---|---|---|---|
| **F-01** | **The piece-identity function is not stable under a missing optional field.** `_compute_scan_code` walks a priority ladder, so the same physical piece yields `…\|sr1\|DESIGN` when `pack_sr` is present and `…\|DESIGN` when it is absent. A dedupe keyed on `scan_code` therefore cannot detect its own duplicate. | `packing_db.py:44-58`; production: 3 pieces recorded twice with differing scan_codes, while a scan-keyed sweep over 1,298 live lines returns **0** duplicates | VERIFIED | **BLOCKER** | S2, S4 |
| **F-02** | **Double ingestion has occurred in production.** Per-invoice (`…-Poland.xls`) and per-client (`…-Client.xlsx`) lists of the same pieces both ingested as `doc_stage='final'`, neither withdrawn, different file hashes so the hash dedupe never fired. Identical `product_code`, `design_no`, `qty`, `invoice_no`, `metal`, weights. | batches `…_bd18ec98` and `…_f82f6527`; ingested 3.5 h apart | VERIFIED | **BLOCKER** | S1, S2 |
| **F-03** | **245 orphan `packing_lines`** reference a `packing_document_id` that does not exist — 15% of the table. No foreign key is declared. | batch `SHIPMENT_4789974092_2026-05_999deef1`; 1571 rows total, 1326 join | VERIFIED | **HIGH** | S4 |
| **F-04** | No allocation column exists anywhere. `supplier_preallocated` / `operator_allocated` / `unallocated` are absent from `packing_lines` and `sales_packing_lines`. Allocation only materialises at proforma creation. | `packing_db.py:141-173`; `document_db.py:251-265` | VERIFIED | HIGH | S2 |
| **F-05** | The parser has no alias for a bare `Client` column — only `client_po`/`order_no`. Even if fuzzy matching accepted it, `packing_lines` has no column to store it in, so per-client attribution is dropped at write time. | `invoice_packing_extractor.py:490-530`; `packing_db.py:141` | VERIFIED | HIGH | S2 |
| **F-06** | No `UNIQUE` on `packing_documents.batch_id`/`linked_batch_id`; 17 batches carry >1 document (max 11). Lines from all documents are unioned, inflating expected quantity and potentially **suppressing a real over-bill flag**. | `packing_db.py:125`, `:488` | VERIFIED | MEDIUM | S1 |
| **F-07** | Warehouse-receipt confirmer is unvalidated free text from an `X-Operator` header, defaulting to the literal `"operator"`. The audit trail's identity is not authoritative. | `warehouse_receipt_db.py:73`; `routes_warehouse_receipt.py:64` | VERIFIED | MEDIUM | S3 |
| **F-08** | Piece status computed in 4 places with no shared utility; status semantics cannot be changed in one edit. | `dashboard-page.jsx:79`, `dashboard-kanban.jsx:116`, `inventory-page.jsx:3372`, `documents-hub.jsx:564` | VERIFIED | MEDIUM | S4 |
| **F-09** | A single NBP rate is fetched from `invoices[0]["invoice_date"]` and applied to every invoice in the batch. Correct for a single-date batch; undefined when invoice dates straddle a rate change. | `pz_import_processor.py:3589`, `:522` | VERIFIED (behaviour) / **NO EVIDENCE** (intended rule) | MEDIUM | S5 |
| **F-10** | `customer_master.db` is a dead 0-byte file beside the live `customer_master.sqlite`. Any glob-based DB discovery can bind to the wrong one. | production storage listing | VERIFIED | LOW | — |
| **F-11** | Trailing diamond-set blocks render as plain. Two candidate mechanisms: `_STONE_KEYS` is sorted length-descending so `PLAIN` (5) is tested before `DIA` (3) and breaks early, and the fallback searches only for the word `DIAMOND`; separately, a cached `source='auto'` row is returned unchanged and a product first seen as plain keeps that block. | `customs_description_engine.py:352-357`; `description_engine.py:365-374` | INFERRED | MEDIUM | — |

### Verified clean — the rules that are holding

- **Customs value freeze on the PZ path.** `routes_pz.py:138` → `export_service.process_shipment()` → `process_batch()`. Totals are read verbatim; no arithmetic on price, freight, duty or quantity outside the engine. VERIFIED.
- **Freight and insurance allocate by value**, per invoice (`pz_import_processor.py:3091`, `:3139`). No piece-count split anywhere. VERIFIED.
- **Duty comes from ZC429/A00 only**, proportional to before-duty value (`:3182`, `:3205`), with a guard that raises when the implied rate exceeds 20% — catching a parser that grabbed the taxable base instead of the charge (`:3183`). VERIFIED.
- **NBP rate is the business day before the invoice date**, walking back over weekends and holidays (`:522`, `:548`). VERIFIED.
- **No cross-currency summation** on the inbound path. VERIFIED.
- **`design_no` → `product_code` consolidation already happened** — the three divergent copies in `sales_packing_matcher` were replaced by one resolver. This is the campaign's own pattern, already applied once successfully.

---

## 3. PER-SLICE VERDICT

| Slice | Verdict | Detail |
|---|---|---|
| **S1 multi-invoice** | **FEASIBLE-AS-DESIGNED** | The schema already permits many documents per batch — no migration needed. But F-02 and F-06 mean it is currently feasible *and unsafe*: fix ingestion identity before widening use. |
| **S2 allocation** | **NEEDS SCHEMA CHANGE** | Migration: new table `packing_line_allocation (id, batch_id, packing_line_id, customer_ref, source CHECK(source IN ('supplier_suggested','operator_allocated','unallocated')), status CHECK(status IN ('auto','unresolved','confirmed','overridden')), operator_user, operator_at, confidence, reason, created_at, updated_at)`, UNIQUE `(packing_line_id, customer_ref)`. Reuses the vocabulary of `packing_contractor_resolution` (`packing_resolution_db.py:44-73`) rather than inventing a second pattern. **Blocked by F-01** — allocation keyed on an unstable identity inherits the instability. |
| **S3 receipt snapshot** | **FEASIBLE-AS-DESIGNED** | Per-line accept/short/over already recorded, and shortage/overage derive from import authority rather than the client. F-07 (free-text confirmer) is a MEDIUM to fix inside the slice. |
| **S4 inbound board** | **CONFLICTS WITH AUTHORITY — piece status** | Four independent status derivations (F-08). Consolidate to one resolver *before* adding a fifth surface, or the board becomes the fifth. F-03 also distorts any per-batch count. |
| **S5 PZ generator** | **FEASIBLE-AS-DESIGNED** | The customs-freeze audit came back clean. F-09 (multi-invoice NBP rate) needs a ruling, not a migration. |

---

## 4. wFIRMA GAP LIST — questions the repository cannot answer

1. **`kontrahent` id type.** `bill_to_contractor_id` is `TEXT` locally and *is* the wFirma contractor id. Is the API type integer or string? Field: `kontrahenci.contractor.id`.
2. **`kontrahent` uniqueness.** Does wFirma enforce one contractor per NIP/VAT? The local schema does **not** enforce NIP uniqueness, so two local rows could collide on their side. Field: `kontrahenci.contractor.nip`.
3. **`towar` id type and nullability.** Stored `TEXT` locally in two places. Field: `towary.good.id`.
4. **VAT code stability.** Are `222` / `228` / `229` stable wFirma VAT code ids across accounts and regions, or account-scoped? Field: `faktury.invoicecontent.vat_code_id`.
5. **Multi-invoice NBP rate rule.** Not a wFirma question but an authority one: when a batch's invoices carry different dates, is the rate per-invoice or per-batch? (F-09.)
6. **ZC429 XSD.** The parser tries `<DutyTaxFee>/<TypeCode>` and `<DutiesAndTaxes>/<taxType>` as alternates. The canonical PUESC schema would settle which is primary and whether any required field is silently skipped. (`customs_xml_parser.py:346-366`.)
7. **wFirma goods name for diamond-set items.** Does the goods registry store the stone-inclusive Polish name or only the item-type noun? Bears on F-11. Field: `towary.good.name`.

---

## 5. ASSUMPTIONS RECORDED THIS SESSION

See `ASSUMPTIONS.md` entries **A-001** (ran the census while gates fail — it is read-only),
**A-002** (four sub-agents, E3 held for synthesis), **A-009** (`scan_code` treated as the piece
identity for the duplicate sweep, per `advance_packing.py:39`), **A-010** (grouping by
`design_no + product_code` rejected as an instrument — it counts a legitimate mixed lot of 33
identical rings as 33 duplicates).

**HARD STOP.** No schema change applied, no migration run, no production code touched.

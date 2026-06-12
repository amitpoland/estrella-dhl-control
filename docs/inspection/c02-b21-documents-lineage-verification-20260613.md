# Campaign 02 — B21 Documents Lineage Verification Report

**Date**: 2026-06-13 (verification executed 2026-06-12)
**Campaign**: 02 — EJ Dashboard Portal — Authority Consolidation & Workflow Completion
**Track**: P3 Workflow Completion — Documents Lineage Review (closes B21; VERIFY-ONLY)
**Source of truth**: all reads against `C:\PZ-verify` @ `ff1f4b5` (= origin/main)
**Method**: verification agent + independent adversarial verdict on the claimed gap

---

## Verdict summary

| Check | Status | Adversarial verdict |
|---|---|---|
| Shipment linkage | VERIFIED | — |
| SAD linkage | VERIFIED | — |
| Invoice linkage | VERIFIED | — |
| Proforma linkage | VERIFIED | — |
| PZ linkage | claimed GAP | **isReal = FALSE — gap REFUTED** |

**B21 closes as VERIFIED — no open gap.** The single claimed gap (PZ file-path
linkage) was adversarially refuted: the reviewer misread the schema design.

---

## Verified lineage chains

### 1. Shipment linkage — VERIFIED
- `document_db.py:61-62` — `shipment_documents` carries `batch_id` (TEXT NOT NULL)
  and `awb` (TEXT NOT NULL DEFAULT '').
- `register_document()` (line 491) requires `batch_id`; all document writers use it.
- Consistent `batch_id` linkage across `packing_lines` (packing_db.py:100,125),
  `customs_declarations` (:131), `awb_documents` (:162), `pz_documents` (:183),
  `invoice_lines` (:205), `sales_documents` (:232) — all with batch_id indexes.

### 2. SAD linkage — VERIFIED
- `document_db.py:128-157` — `customs_declarations` links via `document_id`
  (FK → `shipment_documents`), stores `mrn` with unique index (idx_cd_mrn:155).
- `store_customs_declaration()` (line 838) upserts on (batch_id, mrn).
- `shipment_documents.related_mrn` (line 74) provides reverse linkage.
- ZC429 intake (`routes_upload.py:1218-1249`) registers attachments then stores the
  declaration — both directions covered.

### 3. Invoice linkage — VERIFIED
- `document_db.py:201-227` — `invoice_lines` links via `document_id` FK (:221) and
  stores `invoice_no` (:206); `store_invoice_lines()` (line 1235) requires
  `document_id`.
- `shipment_documents.related_invoice_no` (:73) provides reverse linkage.
- `invoice_intake_parser.py:112-160` — `product_code` minted as
  `{invoice_no}-{line_position}`, guaranteeing unique keys.

### 4. Proforma linkage — VERIFIED
- `proforma_invoice_link_db.py:120-135` — `proforma_invoice_links` with UNIQUE
  constraint on `proforma_id`, linked + indexed `invoice_id`.
- `create_pending_link()` enforces uniqueness via `ProformaAlreadyConverted` (:217).
- `audit_persist.py:46-51` records proforma timeline events; `wfirma_pz_doc_id`
  linkage at line 170.

---

## Claimed PZ linkage gap — REFUTED

The verification agent claimed: "generated PZ file paths are not stored in
`pz_documents.file_path`", breaking the disk-file → registry chain.

Adversarial review found the claim FALSE — by design, `pz_documents` has no
`file_path` field because it references `shipment_documents` where the path lives:

1. Generated PZ file paths ARE stored in `shipment_documents.file_path` via
   `register_document()` — `export_service.py:372-373` (PDF) and `:380-381` (XLSX).
2. `pz_documents` links to `shipment_documents` via the `document_id` FK
   (`document_db.py:195`).
3. WorkDrive resource IDs are stored in BOTH the audit JSON and `pz_documents`
   (`export_service.py:403-404`).
4. Complete chain exists: disk file → `shipment_documents.file_path` →
   `pz_documents.document_id` → audit JSON pointer.

No remediation is required. No GATE 4 disposition is needed (no real finding).

---

## Closure statement

**B21 is CLOSED as VERIFIED.** All five lineage chains (shipment, SAD, invoice,
proforma, PZ) are intact with proper foreign keys, unique constraints, and reverse
lookup fields. The lineage map: `documents.db` (central registry) ← `packing.db`
(supplier documents) ← `proforma_invoice_link_db` (draft lifecycle) ← `audit.json`
(timeline pointers) ← disk files. No code was changed by this track (VERIFY-ONLY
mandate honored).

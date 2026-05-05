# Packing List DB Flow

**Version:** 1.0  
**Status:** Locked — do not change schema without updating this document and tests.

---

## 1. Input Requirements

| Input | Required | Notes |
|---|---|---|
| `pz_rows.json` | **Yes** | Must exist in the batch output directory before packing upload. Created by the PZ processor. Upload will fail gracefully (0 matched rows) if absent. |
| Packing list XLSX/XLS | Preferred | Column-header detection works reliably. Preferred format. |
| Packing list PDF | Conditional | Supported only if the PDF contains real table structure detectable by pdfplumber. Free-form/scanned PDFs yield zero rows. |

**Prerequisite order:**  
1. PZ must be processed first (`/api/v1/upload/shipment/{batch_id}/process`).  
2. Only then upload the packing list (`/api/v1/packing/{batch_id}/upload`).

---

## 2. End-to-End Flow

```
Invoice PDFs + ZC429/SAD
        │
        ▼
PZ Processor  ─────────────────────────────────────► pz_rows.json
(process_batch)                                       (batch output dir)
                                                            │
Packing list (XLSX or PDF)                                  │
        │                                                   │
        ▼                                                   ▼
POST /api/v1/packing/{batch_id}/upload         load_invoice_lines()
        │                                       assigns invoice_line_position
        │                                       generates product_code
        │                                              │
        ▼                                              │
extract_packing(path)  ◄────────────────────────────  │
  XLSX → openpyxl                                      │
  PDF  → pdfplumber                                    │
        │                                              │
        ▼                                              │
match_packing_to_invoice(packing_rows, invoice_lines) ◄┘
        │
        ▼
upsert_packing_document()   ─► packing_documents table
upsert_packing_lines()      ─► packing_lines table
        │
        ▼
log_event(EV_PACKING_LIST_EXTRACTED)
log_event(EV_PACKING_MATCHED_TO_INVOICE)
        │
        ▼
GET /api/v1/packing/{batch_id}
  returns: invoice_lines + packing_lines + documents
```

### Step details

**Step 1 — PZ processor creates `pz_rows.json`**

The engine writes one row per invoice line. Each row contains at minimum:
`invoice_no`, `item_type`, `quantity`, `unit`, `unit_netto_pln`, `line_netto_pln`, `description_en`.

**Step 2 — `load_invoice_lines(batch_output_dir)`**

Reads `pz_rows.json`. Groups rows by `invoice_no`. Within each invoice group, assigns sequential `invoice_line_position` (1, 2, 3 …). Generates:

```
product_code = invoice_no + "-" + str(invoice_line_position)

Examples:
  EJL/26-27/100-1
  EJL/26-27/100-2
  EJL/26-27/101-1
```

**Step 3 — `extract_packing(path)`**

Dispatches by file extension:
- `.xlsx` / `.xls` → `openpyxl` table reader
- `.pdf` → `pdfplumber` table extractor

Header columns are normalised (lowercase, strip punctuation) and mapped to canonical field names via `_FIELD_ALIASES`. Known aliases include: `design`, `style` → `design_no`; `lot`, `batch` → `batch_no`; `bag`, `bag_no` → `bag_id`; `qty`, `pcs` → `quantity`; etc.

**Step 4 — `match_packing_to_invoice(packing_rows, invoice_lines)`**

See matching rules in section 3.

**Step 5 — DB write**

```python
doc_id = upsert_packing_document(batch_id=..., invoice_no=..., ...)
upsert_packing_lines(line_records, force_reextract=False)
```

Original file is preserved at `source/packing/<filename>` — never deleted.

**Step 6 — Downstream read**

All downstream flows (wFirma, barcode, PZ extensions) call:

```
GET /api/v1/packing/{batch_id}
```

Response shape:

```json
{
  "batch_id": "SHIPMENT_...",
  "invoice_lines": [
    {
      "invoice_no": "EJL/26-27/100",
      "invoice_line_position": 1,
      "product_code": "EJL/26-27/100-1",
      "item_type": "RING",
      "quantity": 2.0,
      "unit": "PCS",
      "unit_netto_pln": 181.12,
      "line_netto_pln": 362.24,
      "description_en": "Gold 18K Ring"
    }
  ],
  "packing_lines": [
    {
      "id": "...",
      "packing_document_id": "...",
      "batch_id": "SHIPMENT_...",
      "invoice_no": "EJL/26-27/100",
      "invoice_line_position": 1,
      "product_code": "EJL/26-27/100-1",
      "design_no": "D-100",
      "batch_no": "BN-001",
      "bag_id": "BAG-01",
      "tray_id": "",
      "item_type": "RING",
      "uom": "PCS",
      "quantity": 2.0,
      "gross_weight": 10.0,
      "net_weight": 9.5,
      "metal": "GOLD",
      "karat": "18K",
      "stone_type": "",
      "remarks": "",
      "extracted_confidence": 0.8,
      "requires_manual_review": 0,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "documents": [...]
}
```

---

## 3. Matching Rules

Applied in priority order. First match wins.

### Rule 1 — Direct match (confidence 1.0)

**Condition:** Packing row contains both `invoice_no` and `invoice_line_position`.

**Result:** Matched directly to the invoice line at `(invoice_no, invoice_line_position)`.

```
packing row: { invoice_no: "EJL/26-27/100", invoice_line_position: 1 }
             → product_code = "EJL/26-27/100-1"
```

### Rule 2 — Fuzzy match (confidence 0.8)

**Condition:** Packing row contains `invoice_no` + `item_type` + `quantity`.

**Match key:** `(invoice_no, normalised_item_type, quantity)`

Normalisation: lowercase, strip all non-alpha characters. `"RING"`, `"Ring"`, `"ring"` all match.

First matching invoice line wins. If multiple invoice lines share the same type and quantity within one invoice, the first in position order is assigned.

```
packing row: { invoice_no: "EJL/26-27/100", item_type: "RING", quantity: 2.0 }
             → matches invoice line EJL/26-27/100-1 (item_type=RING, qty=2.0)
             → product_code = "EJL/26-27/100-1"
```

### Rule 3 — No match

**Condition:** Neither Rule 1 nor Rule 2 applies.

**Result:**
```json
{
  "product_code": null,
  "invoice_line_position": null,
  "requires_manual_review": true,
  "extracted_confidence": 0.0
}
```

Operator must manually assign `product_code` using `force_reextract=true` on re-upload with corrected data.

---

## 4. Downstream Read Rule

**Rule: never read the original XLS/PDF directly downstream.**

All wFirma, barcode, and PZ extension logic must read packing data from the DB via the API:

```
GET /api/v1/packing/{batch_id}
```

or directly from:

```python
from app.services.packing_db import get_packing_lines_for_batch
lines = get_packing_lines_for_batch(batch_id)
```

**Why:** The DB is the validated, deduplicated, matched source. The original file may have column aliases, encoding issues, or partial rows that the extractor already normalised. Reading the file again would bypass matching and dedup.

**Supplemental endpoints:**

| Endpoint | Use |
|---|---|
| `GET /api/v1/packing/{batch_id}` | Full combined view: invoice lines + packing lines + documents |
| `GET /api/v1/packing/{batch_id}/lines` | Packing lines only |
| `get_packing_line_by_product_code(code)` | Single line lookup by product_code |

---

## 5. Safety Rules

### 5.1 Do not overwrite verified rows

`upsert_packing_lines()` skips any row whose dedup key already exists:

```
dedup key = (batch_id, invoice_no, invoice_line_position, design_no, bag_id)
```

`packing_document_id` is stored for traceability but is **not** part of the dedup key. A re-upload for the same batch creates a new document record but updates the same logical packing row when `force_reextract=True`.

To force overwrite: pass `force_reextract=True` to `upsert_packing_lines()`, or use the upload endpoint with `?force_reextract=true`.

### 5.2 Original file is evidence

The uploaded packing file is saved to:

```
{batch_output_dir}/source/packing/{filename}
```

It is never deleted or modified. It is not the data source for downstream logic — the DB is.

### 5.3 DB is the structural source

`packing.db` (WAL mode, thread-safe) is the only source downstream flows should read for packing structure. `pz_rows.json` is the invoice line source and is also never modified by the packing flow.

### 5.4 PZ calculation is not touched

The packing flow does not:
- modify `audit.json` fields used by the PZ engine
- modify `pz_rows.json`
- change duty, VAT, freight, or any landed cost figure
- change `totals`, `verification`, or `corrections_log`

The only audit side effect is two timeline events appended to `audit.json["timeline"]`:
- `packing_list_extracted`
- `packing_matched_to_invoice`

---

## 6. DB Schema Reference

### `packing_documents`

```sql
CREATE TABLE packing_documents (
    id                  TEXT PRIMARY KEY,        -- UUID4
    batch_id            TEXT NOT NULL,
    invoice_no          TEXT NOT NULL DEFAULT '', -- majority-vote invoice_no from packing rows
    source_file_path    TEXT NOT NULL DEFAULT '',
    source_file_hash    TEXT NOT NULL DEFAULT '', -- SHA-256 of original file
    parser_name         TEXT NOT NULL DEFAULT '',
    parser_version      TEXT NOT NULL DEFAULT '',
    extraction_status   TEXT NOT NULL DEFAULT 'pending', -- pending | complete | empty
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

### `packing_lines`

```sql
CREATE TABLE packing_lines (
    id                      TEXT PRIMARY KEY,    -- UUID4
    packing_document_id     TEXT NOT NULL,       -- FK → packing_documents.id
    batch_id                TEXT NOT NULL,
    invoice_no              TEXT NOT NULL DEFAULT '',
    invoice_line_position   INTEGER DEFAULT NULL,
    product_code            TEXT DEFAULT NULL,   -- null if unmatched
    design_no               TEXT NOT NULL DEFAULT '',
    batch_no                TEXT NOT NULL DEFAULT '',
    bag_id                  TEXT NOT NULL DEFAULT '',
    tray_id                 TEXT NOT NULL DEFAULT '',
    item_type               TEXT NOT NULL DEFAULT '',
    uom                     TEXT NOT NULL DEFAULT '',
    quantity                REAL NOT NULL DEFAULT 0.0,
    gross_weight            REAL NOT NULL DEFAULT 0.0,
    net_weight              REAL NOT NULL DEFAULT 0.0,
    metal                   TEXT NOT NULL DEFAULT '',
    karat                   TEXT NOT NULL DEFAULT '',
    stone_type              TEXT NOT NULL DEFAULT '',
    remarks                 TEXT NOT NULL DEFAULT '',
    extracted_confidence    REAL NOT NULL DEFAULT 0.0,  -- 1.0=direct, 0.8=fuzzy, 0.0=unmatched
    requires_manual_review  INTEGER NOT NULL DEFAULT 0, -- 1 if unmatched
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    FOREIGN KEY (packing_document_id) REFERENCES packing_documents(id)
);
```

---

## 7. File Map

| File | Role |
|---|---|
| `app/services/packing_db.py` | DB layer — init, upsert, read |
| `app/services/invoice_packing_extractor.py` | Extractor + matcher + pipeline |
| `app/api/routes_packing.py` | HTTP endpoints |
| `app/core/timeline.py` | `EV_PACKING_LIST_EXTRACTED`, `EV_PACKING_MATCHED_TO_INVOICE` |
| `app/main.py` | `init_packing_db()` in lifespan, router included |
| `tests/test_packing_db.py` | 28 unit tests |
| `tests/test_packing_integration.py` | Integration test (pz_rows → upload → GET combined) |
| `storage/packing.db` | Live SQLite DB (WAL mode) |

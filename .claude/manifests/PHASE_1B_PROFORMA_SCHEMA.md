# Phase 1-B: ProformaDraft Schema Extensions
**Lane:** 1-B (parallel with 1-A)
**Status:** READY TO IMPLEMENT
**Depends on:** nothing (schema only)
**Blocks:** Phase 2 renderer, Phase 3 enrichment

## Deliverables

### 1. `ProformaDraft` dataclass additions

File: `service/app/services/proforma_invoice_link_db.py`

Add after `packing_sync_warning` (last existing field):
```python
# ── Phase 7 — commercial document fields ─────────────────────────
fx_rate_date:    Optional[str]   = None   # ISO date of NBP rate
fx_rate_source:  str             = "NBP"  # source label, default NBP
incoterm:        Optional[str]   = None   # per-shipment incoterm
insurance_eur:   Optional[float] = None   # declared insurance EUR
```

### 2. `_ADDITIVE_DRAFT_COLUMNS` additions

Add to the `_ADDITIVE_DRAFT_COLUMNS` tuple:
```python
# ── Phase 7 — commercial document fields ─────────────────────────
("fx_rate_date",   "TEXT"),
("fx_rate_source", "TEXT NOT NULL DEFAULT 'NBP'"),
("incoterm",       "TEXT"),
("insurance_eur",  "REAL"),
```

### 3. `proforma_draft_sync.py` — populate `fx_rate_date` at creation

File: `service/app/services/proforma_draft_sync.py`

When creating or syncing a draft:
- If batch audit.json contains an NBP rate date → use it
- Otherwise → use current date (ISO format, UTC)
- `fx_rate_source` = "NBP" (constant for now)
- `incoterm` and `insurance_eur` left as None (operator sets later)

Search for where `exchange_rate` is set in the sync path and add `fx_rate_date` alongside it.

### 4. Tests

`service/tests/test_proforma_schema_phase7.py`:
- test_fx_rate_date_column_exists: ALTER succeeds idempotently (run twice, no error)
- test_fx_rate_source_default: new draft has fx_rate_source = "NBP"
- test_incoterm_nullable: new draft has incoterm = None
- test_insurance_eur_nullable: new draft has insurance_eur = None
- test_existing_draft_unaffected: load existing draft → new fields are None/default
- test_fx_rate_date_round_trip: set fx_rate_date "2026-05-07", read back, assert equal
- test_incoterm_set_and_read: set incoterm "DAP", read back, assert equal
- test_insurance_eur_precision: set 200.50, read back as float, assert close

### Safety constraints
- ALL changes are additive ALTER — existing rows are unaffected
- No existing function signatures change
- `ProformaDraft.fx_rate_source` default is "NBP" so existing code that
  doesn't pass it still gets a sensible value
- MUST NOT change any existing column name or type

## Files to modify
- MODIFY: `service/app/services/proforma_invoice_link_db.py`
- MODIFY: `service/app/services/proforma_draft_sync.py`
- CREATE: `service/tests/test_proforma_schema_phase7.py`

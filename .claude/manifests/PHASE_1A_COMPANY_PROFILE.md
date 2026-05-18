# Phase 1-A: Company Profile Foundation
**Lane:** 1-A (parallel with 1-B)
**Status:** READY TO IMPLEMENT
**Depends on:** nothing (first phase)
**Blocks:** Phase 2 renderer

## Deliverables

### 1. `CompanyProfile` dataclass + table in `master_data_db.py`

Add to `/Users/amitgupta/Downloads/CLI/service/app/services/master_data_db.py`:

- `CompanyProfile` dataclass (see INTERFACE_CONTRACTS.md Contract 1)
- `_ensure_company_profile_table(conn)` — additive ALTER pattern
- `get_company_profile(storage_root)` — returns CompanyProfile or None
- `upsert_company_profile(storage_root, **fields)` — partial update, timestamp

Storage: `master_data.sqlite` (existing file, new table `company_profile`)
Table: single-row, `id=1` always. Upsert by id.

### 2. New router `routes_settings.py`

Create `/Users/amitgupta/Downloads/CLI/service/app/api/routes_settings.py`:

```
GET  /api/v1/settings/company-profile
PATCH /api/v1/settings/company-profile
```

Follow existing route patterns (pz_session cookie auth, HTTPException on error).
Mount at `/api/v1/settings` in `main.py`.

### 3. Tests

`service/tests/test_company_profile_db.py`:
- test_create_and_get_empty: get_company_profile when no row → None
- test_upsert_creates_row: upsert legal_name → get returns it
- test_upsert_partial_update: upsert only iban_eur → other fields unchanged
- test_updated_at_refreshed: upsert twice → updated_at changes
- test_all_fields_round_trip: upsert all fields, get back, assert equality

`service/tests/test_routes_settings.py` (source-grep style):
- test_settings_router_mounted: "company-profile" in routes_settings source
- test_get_returns_empty_profile: GET endpoint handler exists
- test_patch_partial_fields: PATCH endpoint accepts partial JSON
- test_no_wfirma_calls_in_settings: no wfirma_client imports in routes_settings

## Safety constraints
- MUST NOT write to wFirma
- MUST NOT modify existing tables
- MUST NOT mutate any ProformaDraft or audit.json
- Table creation is additive (try/except for existing column pattern)
- get_company_profile returns None (not exception) when table exists but no row

## Files to create/modify
- MODIFY: `service/app/services/master_data_db.py` (add CompanyProfile section)
- CREATE: `service/app/api/routes_settings.py`
- MODIFY: `service/app/main.py` (mount new router)
- CREATE: `service/tests/test_company_profile_db.py`
- CREATE: `service/tests/test_routes_settings.py`

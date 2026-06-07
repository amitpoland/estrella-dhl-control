# M6 Prior Proforma Search — Campaign Document

**Campaign:** M6 — Prior Proforma Search  
**Branch prefix:** `feature/m6-proforma-search`  
**Status:** APPROVED — audit complete, implementation ready  
**Created:** 2026-06-07  
**Authority source:** `proforma_drafts` table in `proforma_links.db`  
**Architecture reference:** M6 Repository Audit (2026-06-07, session transcript)

---

## 1. Architectural Goal

Create the first authoritative cross-batch read-only index of all proforma drafts.

**Authority source: `proforma_drafts`.** Everything else is display-only enrichment.

**Non-goals (permanent):** No writes. No wFirma mutations. No DHL involvement. No accounting changes. No inventory mutations. No email sends. No proforma creation, posting, conversion, or cancellation.

---

## 2. Anti-Drift Gates

| Gate | Check |
|------|-------|
| `make verify` green | All existing test suites pass before opening a PR |
| No modification to existing endpoints | M6 adds NEW endpoints only; existing routes unchanged |
| Read-only enforcement | Search endpoint uses GET only; no state mutation |
| Authority single-source | All results derived from `proforma_drafts` table only |
| V1 freeze honoured | No edits to `shipment-detail.html` or `dashboard.html` |
| Open PR count < 3 | Per GATE 2 |

---

## 3. Scope Definition

### Sprint 1 — Search by Business Identifiers

| Filter | Column | Type |
|--------|--------|------|
| `batch_id` | batch_id | Exact match |
| `client_name` | client_name | Partial match (LIKE) |
| `wfirma_proforma_id` | wfirma_proforma_id | Exact match |
| `wfirma_proforma_fullnumber` | wfirma_proforma_fullnumber | Exact/prefix match |
| `draft_state` | draft_state | Exact match |
| `currency` | currency | Exact match |
| `date_from` / `date_to` | created_at | Range filter |

**Pagination:** `page` + `page_size` (default 25, max 100).

### Sprint 2 (optional, deferred)

| Filter | Source | Complexity |
|--------|--------|-----------|
| Amount range | Derived from `editable_lines_json` / `source_lines_json` | JSON parsing, computed totals, performance risk |

**Reason for deferral:** Total is not a first-class indexed column. Most operator lookups use client, number, date, or status — not amount. Sprint 2 only if operator demand confirms the need.

---

## 4. Duplicate Authority Risk (RESOLVED)

| Surface | Data Source | Lifecycle Stage |
|---------|-------------|-----------------|
| PriorInvoiceHistoryModal | wFirma invoice ledger | **Final** (post-conversion) |
| M6 Prior Proforma Search | Local proforma_drafts | **Draft** (pre-conversion) |

**Verdict:** Complementary, not conflicting. Different lifecycle stages. No authority overlap. UI labels must clearly distinguish "Proformas (drafts)" from "Invoices (final, wFirma)."

---

## 5. Implementation Plan — 3 PRs

### PR 1 — DB Layer + Indexes

**Branch:** `feature/m6-proforma-search-db`

| File | Change |
|------|--------|
| `service/app/services/proforma_invoice_link_db.py` | Add `search_drafts(filters: dict, page: int, page_size: int) -> dict` |
| `service/app/services/proforma_invoice_link_db.py` | Add `_ensure_search_indexes()` in `_ensure_tables()` |
| `service/tests/test_proforma_search_db.py` | Unit tests: filter combos, pagination, empty results, index verification |

**Indexes to add (additive, non-breaking):**
- `idx_pd_client_name` on `proforma_drafts(client_name)`
- `idx_pd_fullnumber` on `proforma_drafts(wfirma_proforma_fullnumber)`
- `idx_pd_created_at` on `proforma_drafts(created_at)`
- `idx_pd_currency` on `proforma_drafts(currency)`
- `idx_pd_draft_state` on `proforma_drafts(draft_state)`

**`search_drafts()` contract:**
```python
def search_drafts(
    filters: dict,      # Keys: batch_id, client_name, wfirma_proforma_id,
                        #        wfirma_proforma_fullnumber, draft_state,
                        #        currency, date_from, date_to
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """
    Returns: {
        "results": [ProformaDraft, ...],
        "total": int,
        "page": int,
        "page_size": int,
    }
    """
```

### PR 2 — API Endpoint

**Branch:** `feature/m6-proforma-search-endpoint`

| File | Change |
|------|--------|
| `service/app/api/routes_proforma.py` | Add `GET /api/v1/proforma/search` |
| `service/tests/test_proforma_search_endpoint.py` | Source-grep + integration tests |

**Endpoint contract:**
```
GET /api/v1/proforma/search?client_name=&proforma_number=&batch_id=&date_from=&date_to=&currency=&draft_state=&wfirma_proforma_id=&page=&page_size=
```

Response:
```json
{
  "results": [...],
  "total": 42,
  "page": 1,
  "page_size": 25
}
```

### PR 3 — V2 Search UI

**Branch:** `feature/m6-proforma-search-ui`

| File | Change |
|------|--------|
| `service/app/static/v2/pz-api.js` | Add `searchProformaDrafts(filters)` |
| `service/app/static/v2/proforma-search.jsx` | NEW — search form + results table |
| `service/app/static/v2/index.html` | Add script tag |
| `service/app/static/v2/master-page.jsx` | Navigation entry point |
| `service/tests/test_proforma_search_ui.py` | Source-grep tests |

**UI requirements:**
- Search form with fields: client name, proforma number, batch ID, date range, currency, state
- Results table with columns: batch_id, client_name, proforma_number, state, currency, created_at
- Clickable rows → drill to proforma-detail
- Pagination controls
- Empty-state display
- Loading state
- `data-testid` on all interactive elements
- Follows `.claude/skills/frontend-design.md` (CSS variables, shared components, no auto-fetch)

---

## 6. Rollback Profile

| Layer | Risk | Rollback |
|-------|------|----------|
| DB indexes | ZERO — additive only | Leave in place (harmless) |
| DB function | ZERO — new function, no existing code calls it | Delete function |
| API endpoint | ZERO — new route | Delete route |
| UI file | ZERO — new file | Delete file + script tag |

No existing functionality is modified. Full revert = delete new files.

---

## 7. Test Requirements

| PR | Test file | Count target |
|----|-----------|-------------|
| PR 1 | `test_proforma_search_db.py` | ~20 tests (filters, pagination, indexes) |
| PR 2 | `test_proforma_search_endpoint.py` | ~15 tests (source-grep + endpoint shape) |
| PR 3 | `test_proforma_search_ui.py` | ~15 tests (source-grep, exports, testids) |

---

## 8. Sprint Execution Order

```
PR 1 (DB) → merge → verify
PR 2 (API) → merge → verify
PR 3 (UI) → merge → deploy → browser verify → campaign closed
```

Each PR merges independently. PR 2 depends on PR 1. PR 3 depends on PR 2.

---

## 9. Success Criteria

Campaign is CLOSED when:
- [x] Audit approved (2026-06-07)
- [ ] PR 1 merged — search_drafts + indexes + tests green
- [ ] PR 2 merged — GET /api/v1/proforma/search returns correct results
- [ ] PR 3 merged — V2 search page renders, filters work, drill-through functions
- [ ] Browser verification — full end-to-end with no console errors
- [ ] Production deployed — search page accessible at /v2/ navigation

---

## 10. What This Campaign Does NOT Do

1. No amount-range filtering (deferred to Sprint 2 if needed)
2. No full-text search
3. No wFirma mutations
4. No proforma creation/editing/posting/conversion/cancellation
5. No DHL integration
6. No email sends
7. No accounting writes
8. No inventory mutations
9. No modification to existing proforma endpoints
10. No V1 page changes

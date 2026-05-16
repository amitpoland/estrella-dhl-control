# Phase 6F.3 — Read-only breakdown endpoint (Implementation Plan)

> **PLAN ONLY. No code in this commit.** Implementation is the NEXT batch.
> Date: 2026-05-16 · author: claude-session
> Status: ready for operator green-light · stacked on closed PRs #112 (6F.1) + #113 (6F.1.5)

---

## 1 — Scope (locked to operator brief)

Add **one** read-only endpoint:

```
GET /api/v1/finance/postings/{posting_id}/breakdown
```

Response shape:
```json
{
  "posting":     { ...Posting fields... },
  "charges":     [ {...Charge...}, ... ],
  "payments":    [ {...Payment...}, ... ],
  "allocations": [ {...PaymentAllocation...}, ... ],
  "settlement":  { ...Settlement... } | null,
  "sums": {
    "charges_minor":  <int>,
    "payments_minor": <int>,
    "is_fully_paid":  <bool>
  }
}
```

**Allowed in 6F.3:**
- New `service/app/api/routes_finance_postings.py`
- `main.py` `include_router(finance_postings_router)`
- Read-only calls into `finance_postings_db` (only the existing read functions: `get_posting`, `list_charges`, `list_payments`, `list_allocations`, `get_settlement_for_posting`, `compute_sum_charges_minor`, `compute_sum_payments_minor`, `is_fully_paid`)
- Hard-rule contract updates in the SAME diff
- 1-line `init_db` call in `main.py` lifespan (so the file exists when the endpoint is hit)

**Explicitly FORBIDDEN in 6F.3:**
- POST / PUT / PATCH / DELETE methods
- Any call to `create_*` / `record_*` / `link_*` helpers
- Backfill from `proforma_service_charges` (that's 6F.2)
- UI integration (that's 6F.4)
- Posting engine wiring (that's 6F.5)
- Settlement-close trigger (that's 6F.6)
- wFirma / proforma / PZ / DHL coupling
- writes to anything else

---

## 2 — Mirror of an existing safe pattern

The closest precedent is `routes_suppliers.py`:

```python
router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])
_auth  = Depends(require_api_key)

@router.get("/", dependencies=[_auth], summary="List suppliers")
def list_suppliers_endpoint(...):
    ...
```

`routes_finance_postings.py` will follow the same shape, with **only GET endpoints** and **only one path**:

```python
router = APIRouter(prefix="/api/v1/finance/postings", tags=["finance-postings"])
_auth  = Depends(require_api_key)

@router.get("/{posting_id}/breakdown", dependencies=[_auth], summary="Posting charge breakdown")
def get_breakdown_endpoint(posting_id: int) -> JSONResponse:
    init_db(_DB_PATH)
    posting = get_posting(_DB_PATH, posting_id)
    if posting is None:
        raise HTTPException(404, detail=f"Posting not found: {posting_id}")
    charges     = list_charges(_DB_PATH,     posting_id=posting_id)
    payments    = list_payments(_DB_PATH,    posting_id=posting_id)
    allocations = list_allocations(_DB_PATH, payment_id=None)  # filter post-query
    settlement  = get_settlement_for_posting(_DB_PATH, posting_id)
    sums = {
        "charges_minor":  compute_sum_charges_minor(_DB_PATH, posting_id),
        "payments_minor": compute_sum_payments_minor(_DB_PATH, posting_id),
        "is_fully_paid":  is_fully_paid(_DB_PATH, posting_id),
    }
    return JSONResponse({
        "posting":     _posting_dict(posting),
        "charges":     [_charge_dict(c) for c in charges],
        "payments":    [_payment_dict(p) for p in payments],
        "allocations": [_alloc_dict(a) for a in allocations
                        if a.payment_id in {p.id for p in payments}],
        "settlement":  _settlement_dict(settlement) if settlement else None,
        "sums":        sums,
    })
```

**No other routes**. No factory pattern. No helpers exported beyond the dict
serialisers. ~150 lines total.

---

## 3 — Required contract updates (same diff as the implementation)

The 6F.1.5 dormancy lock was intentional. 6F.3 deliberately breaks **two** of those locks; the same diff must update those tests rather than silently bypass them.

### 3.1 — Tests that must be updated in `test_finance_postings_contracts.py`

| Existing test (6F.1.5) | What needs to change in 6F.3 |
|---|---|
| `test_no_runtime_module_imports_finance_postings_in_api` | Allow-list `routes_finance_postings.py` only. Comment must name 6F.3. |
| `test_no_runtime_module_imports_finance_postings_in_services` | Leave intact — no service should import the module yet. |
| `test_no_finance_postings_reference_in_static_assets` | Leave intact — UI not landed until 6F.4. |
| `test_no_finance_postings_reference_in_main_or_routes_init` | Update to: main.py MAY reference `finance_postings_router` for `include_router`, but MUST NOT reference any other API (write) symbols. |
| `test_no_routes_finance_postings_file_exists` | **DELETE** — replaced by positive test below. |
| `test_no_route_path_contains_finance_postings_or_postings` | Update: only `/api/v1/finance/postings/{posting_id}/breakdown` is allowed. Any other path matching `/api/v1/finance/` or `finance-postings` must be absent. |
| `test_no_router_prefix_for_finance_postings` | Update: the prefix `/api/v1/finance/postings` is now allowed for the new router. Other 'finance' prefixes still forbidden. |
| `test_init_db_not_called_from_main_lifespan` | Update: main.py MAY call `finance_postings_db.init_db` in the lifespan. Keep the explicit allow-list to a single line. |
| `test_no_production_path_creates_finance_postings_sqlite` | Update: `routes_finance_postings.py` MAY mention `finance_postings.sqlite` (via `settings.storage_root / "finance_postings.sqlite"`); the rest of the codebase still must not. |
| `test_engine_does_not_reference_finance_postings` (parametrised, 9 files) | Leave intact — none of those engines may reference the module yet. |
| All allow-list / monetary / idempotency / order rules | Leave intact. |
| `test_finance_postings_module_remains_dormant_summary` | **DELETE** — replaced by `test_finance_postings_module_read_only_only` (see below). |

### 3.2 — New positive contracts (added in the same diff)

| New test name | Rule |
|---|---|
| `test_routes_finance_postings_file_exists` | The new route module must exist |
| `test_finance_postings_router_uses_get_only` | Source-grep: only `@router.get(`; no `@router.post/put/patch/delete` decorators |
| `test_finance_postings_router_does_not_call_write_helpers` | Source-grep: no `create_charge` / `create_posting` / `create_payment` / `create_allocation` / `record_settlement` / `link_charge_to_posting` in route module |
| `test_finance_postings_endpoint_requires_auth` | `Depends(require_api_key)` present on the GET route |
| `test_finance_postings_router_registered_in_main` | `main.py` imports `finance_postings_router` and calls `include_router(finance_postings_router)` |
| `test_finance_postings_module_read_only_only` | Roll-up replacement for the dormancy summary: route module is GET-only AND service modules other than the route do not import |
| `test_finance_postings_path_is_exactly_breakdown` | Only one path literal `/{posting_id}/breakdown` declared |

Engine isolation tests (the parametrised 9-engine check) **remain intact** — they continue to enforce that proforma / wFirma / PZ engines do not couple to the module.

### 3.3 — `test_master_data_hard_rules.py` updates

| Existing test | Update |
|---|---|
| `test_6F1_no_existing_module_imports_finance_postings` | Allow-list adds `routes_finance_postings.py`. |
| `test_6F1_main_does_not_register_router_yet` | **Rename to** `test_6F3_main_registers_finance_postings_router_get_only` (positive: import + include_router required; route module GET-only). |
| `test_6F1_pz_engine_does_not_read_finance_postings` | Leave intact. |
| Other 5 6F.1 hard rules | Leave intact. |

---

## 4 — Required new tests (positive coverage)

`service/tests/test_routes_finance_postings.py` — NEW, ~15 tests:

| # | Test | Asserts |
|---|---|---|
| 1 | `test_breakdown_404_when_posting_missing` | GET on unknown id → 404 |
| 2 | `test_breakdown_200_minimal_posting` | Create a posting via DB layer, GET → 200, fields populated |
| 3 | `test_breakdown_includes_charges_for_posting` | Create posting + 2 charges, GET → both in `charges` array |
| 4 | `test_breakdown_excludes_charges_for_other_posting` | Two postings, charges on each → GET only returns own |
| 5 | `test_breakdown_includes_payments_for_posting` | Create posting + payment, GET → payment in `payments` array |
| 6 | `test_breakdown_includes_allocations_for_payment` | Charge + payment + allocation, GET → allocation in array |
| 7 | `test_breakdown_includes_settlement_when_present` | record_settlement, GET → settlement non-null |
| 8 | `test_breakdown_settlement_null_when_absent` | No settlement → key is null |
| 9 | `test_breakdown_sums_correct` | sums.charges_minor / payments_minor / is_fully_paid correct |
| 10 | `test_breakdown_requires_api_key` | Source-grep: dependency declared |
| 11 | `test_breakdown_only_get_method` | POST/PUT/DELETE on the same path → 405 |
| 12 | `test_breakdown_no_post_endpoint_on_router` | Source-grep on the route module |
| 13 | `test_breakdown_no_write_to_db` | Mock the DB; verify only read helpers are called |
| 14 | `test_breakdown_router_prefix_is_finance_postings` | APIRouter prefix matches spec exactly |
| 15 | `test_breakdown_isolated_from_carrier_runtime` | Existing source-grep that no carrier-runtime import lands |

---

## 5 — Migration steps (operator-facing)

1. **Branch off main** at SHA `d3bbff3` (the post-6F.1.5 main).
2. Add `service/app/api/routes_finance_postings.py`.
3. Update `service/app/main.py`:
   - import the new router
   - add `app.include_router(finance_postings_router)` after the other master-data routers
   - add `init_finance_postings_db(storage_root / "finance_postings.sqlite")` in the lifespan (one line)
4. Update contracts in `service/tests/test_finance_postings_contracts.py` (per §3 above).
5. Update contracts in `service/tests/test_master_data_hard_rules.py` (per §3.3).
6. Add `service/tests/test_routes_finance_postings.py` (15 tests per §4).
7. Run:
   ```
   pytest service/tests/test_routes_finance_postings.py service/tests/test_finance_postings_contracts.py service/tests/test_finance_postings_db.py service/tests/test_master_data_hard_rules.py -v
   python test_pz_regression.py
   ```
8. Commit + push + open PR (target: `main`).

Estimated diff size: ~150 (route module) + ~50 (main.py edits) + ~200 (new tests) + ~50 (contract edits) = ~450 lines.

---

## 6 — Risks for 6F.3

| Risk | Severity | Mitigation |
|---|---|---|
| Route accidentally exposes write semantics | MEDIUM | Source-grep contract test: only `@router.get` allowed |
| Production `finance_postings.sqlite` created in production for the first time at deploy | LOW | Idempotent `init_db`. Creates the file empty. No data exists yet. |
| The endpoint returns an empty body shape that confuses operators | LOW | Always returns the full object; empty arrays for charges/payments/allocations; null for settlement |
| Allow-list drift if future batches add more routes without updating contracts | MEDIUM | The "only GET" contract test will fail loudly if any non-GET decorator lands |
| Auth dependency forgotten | LOW | Mirror existing module pattern; contract test asserts `require_api_key` present |

**No HIGH risk.** Each MEDIUM risk has an explicit mechanical guard.

---

## 7 — Deploy plan

6F.3 IS a runtime change (new route, new file under `service/app/api/`). Deploy required:

```
robocopy <src>/service/app/api/routes_finance_postings.py  C:\PZ\app\api\
robocopy <src>/service/app/main.py                         C:\PZ\app\
robocopy <src>/service/app/services/finance_postings_db.py C:\PZ\app\services\  # newly arrives in production this deploy
sc.exe stop PZService; sc.exe start PZService
```

Post-deploy smoke (api-level):

```
GET /api/v1/finance/postings/999/breakdown   → expect 404
```

Record via `campaign_status.py deploy` with `previous_main_sha = d3bbff3` and the actual robocopy exit codes.

---

## 8 — Hard rules — confirmed compliant

| Hard rule | Compliant in 6F.3? |
|---|---|
| No wFirma write | ✅ — endpoint only reads |
| No proforma posting | ✅ — endpoint does not call proforma |
| No PZ/customs/DHL change | ✅ — endpoint touches no engine code |
| No FX override | ✅ — endpoint does not compute FX |
| No UI write path | ✅ — no UI in 6F.3 |
| No production DB edit (manual) | ✅ — only `init_db` (idempotent CREATE TABLE IF NOT EXISTS) |
| No `.env` | ✅ |
| No external services | ✅ |
| No backfill | ✅ — 6F.2 is later, separate batch |
| No settlement integration | ✅ — `is_fully_paid` is read-only inspection |

---

## 9 — Open questions for operator (before 6F.3 starts)

1. **Endpoint path confirmation:** is `/api/v1/finance/postings/{posting_id}/breakdown` the final shape, or should it be `/api/v1/postings/{posting_id}` (shorter)?
2. **List endpoint requested?** Architecture §5.4 mentions `breakdown` only; should 6F.3 also expose `GET /api/v1/finance/postings/` (list)? Default: NO — list is not in the brief.
3. **`init_db` placement:** in `main.py` lifespan alongside other DBs, or only on first request to the endpoint? Recommended: lifespan (mirrors existing pattern).

These three answers go into the 6F.3 PR description. Without them, the implementation will proceed with the defaults above.

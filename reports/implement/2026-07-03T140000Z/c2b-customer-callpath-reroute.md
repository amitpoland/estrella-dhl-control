# C-2b — Customer Call-Path Reroute (Violations V4 / V5 / V7)

**Slice**: C-2b  
**Date**: 2026-07-03  
**Author**: Claude Code (automated slice)  
**Commit**: NOT COMMITTED (operator instruction)  
**Branch**: deploy/latest  

---

## 1. Objective

Behaviour-identical passthrough migration of direct `wfirma_client` customer
calls in business routes to the Customer Master service layer
(Phase-C Constitution §3: Module → Customer Master → Mirror → wFirma).

Zero change to resolution logic, response shapes, error messages, or
fiscal/value logic.

---

## 2. Sites Rerouted

### A. `service/app/services/customer_master_db.py` — additive only

Two sync-layer passthroughs added after line 1100 (end of file):

| Function added | Delegates to |
|---|---|
| `search_wfirma_customer(name, nip=None)` | `wfirma_client.search_customer` (lazy import) |
| `lookup_wfirma_contractor(contractor_id)` | `wfirma_client.fetch_contractor_by_id` (lazy import) |

Pattern: lazy `from .wfirma_client import X` inside each function body —
identical to `reservation_db.lookup_wfirma_product` (C-1c, commit feeb1fbe).

### B. `service/app/api/routes_proforma.py` — V4 (7 sites)

Import block extended (lines 38–41):
```python
from ..services.customer_master_db import (
    get_customer as get_customer_master,
    list_customers as _list_customer_master,
    search_wfirma_customer as _cmd_search_customer,       # C-2b V4 reroute
    lookup_wfirma_contractor as _cmd_lookup_contractor,   # C-2b V4 reroute
)
```

| Before | After | Approx line |
|---|---|---|
| `wfirma_client.search_customer(client_name)` | `_cmd_search_customer(client_name)` | ~1502 |
| `wfirma_client.search_customer(client_name)` | `_cmd_search_customer(client_name)` | ~1531 |
| `wfirma_client.fetch_contractor_by_id(receiver_id)` | `_cmd_lookup_contractor(receiver_id)` | ~1879 |
| `wfirma_client.fetch_contractor_by_id(rcv_id)` | `_cmd_lookup_contractor(rcv_id)` | ~3639 |
| `wfirma_client.search_customer(client_name)` | `_cmd_search_customer(client_name)` | ~7797 |
| `wfirma_client.search_customer(client_name)` | `_cmd_search_customer(client_name)` | ~7830 |
| `wfirma_client.fetch_contractor_by_id(receiver_id)` | `_cmd_lookup_contractor(receiver_id)` | ~8097 |

Remaining match at ~3010 is a `#` comment — not a call site, not touched.

### C. `service/app/api/routes_ledgers.py` — V5 (2 sites)

Import added after `from ..services import wfirma_client`:
```python
from ..services.customer_master_db import (    # C-2b V5 reroute
    lookup_wfirma_contractor as _cmd_lookup_contractor,
)
```

| Before | After | Approx line |
|---|---|---|
| `wfirma_client.fetch_contractor_by_id(cid)` | `_cmd_lookup_contractor(cid)` | ~158 |
| `wfirma_client.fetch_contractor_by_id(cid)` | `_cmd_lookup_contractor(cid)` | ~291 |

### D. `service/app/api/routes_suppliers.py` — V7 (1 site)

Lazy import inside function body replaced (was `wfirma_client as wfc`):
```python
# Before:
from ..services import wfirma_client as wfc
...
cd = wfc.fetch_contractor_by_id(wfid)

# After:
from ..services.customer_master_db import (   # C-2b V7 reroute
    lookup_wfirma_contractor as _cmd_lookup_contractor,
)
...
cd = _cmd_lookup_contractor(wfid)  # C-2b V7
```

The now-unused `wfc` import was removed (no other `wfc.*` calls in the function).

---

## 3. Found-and-Left (customer WRITE calls)

Grep of `routes_suppliers.py` for `create_customer|list_customers` — **none found**.
No customer write calls identified in any of the three files. Nothing left
pending for a write-gated slice from V7 scope.

---

## 4. Test Evidence

### Pre-change baseline (file-untouched verification)

These are pre-existing failures confirmed against unmodified files:

- `test_invoice_verify_after_create.py`: 20 failed / 103 passed  
  Root cause: expects `status=="failed"` but route returns `"blocked"` — unrelated
  to customer call-path.
- `test_master_data_suppliers_wfirma_sync.py`: 11 failed / 107 passed  
  Root cause: 401 Unauthorized in test setup (auth fixture mismatch) — unrelated.
- `tests -m smoke`: 63 passed / 1 skipped — clean.
- `test_master_consumption_rule.py`: 9/9 passed — clean.

### Post-change results (all edits applied)

| Suite | Before | After | Delta |
|---|---|---|---|
| `test_master_consumption_rule.py` | 9 passed | **10 passed** | +1 (new pin test) |
| `test_proforma_receiver_preflight.py` | 32 passed | 32 passed | 0 |
| `test_proforma_to_invoice_routes.py` | 1 failed / 68 passed | 1 failed / 68 passed | 0 (pre-existing: HTML content check on shipment-detail.html, no relation to C-2b) |
| `test_wfirma_customer_auto_resolve.py` | (included in combined run) | all passed | 0 |
| `test_ledger_invoice_ledger_phase10a.py` | 84 passed | 84 passed | 0 |
| `test_ledger_statement_phase10b.py` | (combined above) | passed | 0 |
| `test_master_data_suppliers_wfirma_sync.py` | 11 failed / 23 passed | 11 failed / 23 passed | 0 (pre-existing: 401 auth fixture) |
| `tests -m smoke` | 63 passed / 1 skipped | 63 passed / 1 skipped | 0 |

Pre-existing failure proof for `test_proforma_to_invoice_routes.py::test_dashboard_renders_two_step_convert_flow`:  
Fails on `assert "Convert Proforma to Invoice" in shipment-detail.html` — a static HTML content
assertion. `shipment-detail.html` was last modified in commit `47b3ce83` (UI fix PR #767),
none of the C-2b edits touch that file.

---

## 5. Pin test added

`service/tests/test_master_consumption_rule.py` — new test appended:

```
test_no_direct_wfirma_customer_calls_in_v4_v5_v7_routes
```

Asserts zero `\.search_customer\s*\(` or `\.fetch_contractor_by_id\s*\(` matches
(comment-stripped) in routes_proforma.py, routes_ledgers.py, routes_suppliers.py.
Uses the file's existing `_strip_comments_and_docstrings` helper.

---

## 6. Patch-target analysis for existing tests

All existing patches use one of two forms:

1. `patch.object(wc, "fetch_contractor_by_id", ...)` where `wc` is
   `from app.services import wfirma_client as wc` — patches the attribute on
   the wfirma_client module object. Lazy import (`from .wfirma_client import
   fetch_contractor_by_id`) resolves from `sys.modules['...wfirma_client']` at
   call time → picks up the patch. **No patch-target update needed.**

2. `patch("app.services.wfirma_client.search_customer", ...)` — same: patches
   the module-level attribute. Lazy import resolves it. **No patch-target
   update needed.**

No test patches `routes_proforma.wfirma_client.*` directly (which would need
updating); all patch the `wfirma_client` module attribute itself.

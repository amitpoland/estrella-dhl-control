"""
test_dashboard_wfirma_search.py — Source-grep tests for the wFirma master
search controls inside the Setup tab customer/product modals.

The Search wFirma buttons:
  - call GET /api/v1/wfirma/contractors/search and /goods/search
  - never call create_customer or create_product
  - show a hit/miss/error result strip
  - prefill the form on hit
  - require an explicit Save click (no auto-save)
"""
from __future__ import annotations

from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Buttons present ─────────────────────────────────────────────────────────

def test_customer_search_button_present():
    src = _src()
    assert 'data-testid="customer-search-btn"' in src


def test_product_search_button_present():
    src = _src()
    assert 'data-testid="product-search-btn"' in src


def test_customer_search_row_anchor_present():
    assert 'data-testid="customer-search-row"' in _src()


def test_product_search_row_anchor_present():
    assert 'data-testid="product-search-row"' in _src()


# ── Result strips for hit / miss / error ────────────────────────────────────

def test_customer_search_result_testids_present():
    src = _src()
    assert 'customer-search-${searchInfo.kind}' in src, (
        "expected a templated testid like customer-search-hit/miss/error "
        "to render based on searchInfo.kind"
    )


def test_product_search_result_testids_present():
    src = _src()
    assert 'product-search-${searchInfo.kind}' in src


# ── Endpoints used: GET search, never PUT during search ─────────────────────

def test_customer_search_calls_get_contractors_endpoint():
    src = _src()
    assert "/api/v1/wfirma/contractors/search?" in src


def test_product_search_calls_get_goods_endpoint():
    src = _src()
    assert "/api/v1/wfirma/goods/search?" in src


def test_search_handlers_do_not_use_method_put():
    """
    The search handlers (searchWfirmaCustomer / searchWfirmaProduct) must
    use the default GET via apiFetch — no method:'PUT' inside their bodies.
    Source-grep: the helper bodies sit between their declaration and the
    next React.useCallback/useEffect.
    """
    src = _src()
    for fn_name in ("searchWfirmaCustomer", "searchWfirmaProduct"):
        idx = src.find(f"const {fn_name}")
        assert idx != -1, f"{fn_name} declaration not found"
        # End at the closing }, [...]) of the useCallback
        end = src.find("}, [", idx)
        assert end != -1, f"{fn_name}: end of useCallback not found"
        body = src[idx:end]
        assert "method: 'PUT'" not in body, f"{fn_name} must not PUT"
        assert "method: 'POST'" not in body, f"{fn_name} must not POST"
        assert "method: 'DELETE'" not in body, f"{fn_name} must not DELETE"


# ── No auto-save: Save button is unchanged + saveCustomer/saveProduct exist ─

def test_customer_save_still_required_after_search():
    """
    The Save button uses onClick={saveCustomer} and is independent of the
    search handler. Search must not call saveCustomer.
    """
    src = _src()
    assert "onClick={saveCustomer}" in src
    # searchWfirmaCustomer body must not invoke saveCustomer
    idx = src.find("const searchWfirmaCustomer")
    end = src.find("}, [editingCustomer]);", idx)
    assert idx != -1 and end != -1
    body = src[idx:end]
    assert "saveCustomer" not in body, (
        "search handler must not invoke saveCustomer — operator clicks Save explicitly"
    )


def test_product_save_still_required_after_search():
    src = _src()
    assert "onClick={saveProduct}" in src
    idx = src.find("const searchWfirmaProduct")
    end = src.find("}, [editingProduct]);", idx)
    assert idx != -1 and end != -1
    body = src[idx:end]
    assert "saveProduct" not in body


# ── No create endpoints / no auto-create ────────────────────────────────────

def test_no_auto_create_customer_endpoint_referenced():
    """No call to wFirma create_customer / contractor creation."""
    src = _src()
    forbidden = (
        "/api/v1/wfirma/contractors/add",
        "create_customer",
        "contractors/add",
    )
    for f in forbidden:
        assert f not in src, f"forbidden create marker found: {f!r}"


def test_no_auto_create_product_endpoint_referenced():
    """No call to wFirma create_product / goods creation."""
    src = _src()
    forbidden = (
        "/api/v1/wfirma/goods/add",
        "create_product",
        "goods/add",
    )
    for f in forbidden:
        assert f not in src, f"forbidden create marker found: {f!r}"


# ── Prefill happens via setEditingCustomer/setEditingProduct, not PUT ───────

def test_customer_search_prefills_via_state_setter():
    """
    On hit, search updates form state with setEditingCustomer (a React
    setter), not by issuing a PUT to /customers/{name}.
    """
    src = _src()
    idx = src.find("const searchWfirmaCustomer")
    end = src.find("}, [editingCustomer]);", idx)
    body = src[idx:end]
    assert "setEditingCustomer" in body
    assert "/api/v1/wfirma/customers/" not in body, (
        "search must not write to the local mapping endpoint"
    )


def test_product_search_prefills_via_state_setter():
    src = _src()
    idx = src.find("const searchWfirmaProduct")
    end = src.find("}, [editingProduct]);", idx)
    body = src[idx:end]
    assert "setEditingProduct" in body
    assert "/api/v1/wfirma/products/" not in body, (
        "search must not write to the local mapping endpoint"
    )


# ── Setting match_status / sync_status to 'matched' on hit ──────────────────

def test_customer_search_marks_matched_on_hit():
    src = _src()
    idx = src.find("const searchWfirmaCustomer")
    end = src.find("}, [editingCustomer]);", idx)
    body = src[idx:end]
    assert "match_status:" in body and "'matched'" in body


def test_product_search_marks_matched_on_hit():
    src = _src()
    idx = src.find("const searchWfirmaProduct")
    end = src.find("}, [editingProduct]);", idx)
    body = src[idx:end]
    assert "sync_status:" in body and "'matched'" in body

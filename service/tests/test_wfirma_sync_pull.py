"""
Wave 4 Item 7 — PULL-ONLY wFirma sync slice.

These tests prove the safety envelope the operator required:
  * the pull endpoint invokes ONLY the read/pull processor
  * NO push type can route through this router (no {type} dispatcher)
  * NO write/create/edit method or goods/edit appears in the router source
  * NO wfirma_create_* flag is referenced by the router
Plus the behavioural contract (200 / 400 / 502).
"""
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_api_key as _auth_dep


def _client():
    app.dependency_overrides[_auth_dep] = lambda: {"username": "t", "role": "admin"}
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(_auth_dep, None)


# ── behaviour ────────────────────────────────────────────────────────────────

def test_payments_pull_invokes_only_pull_processor():
    c = _client()
    try:
        with patch("app.api.routes_wfirma_sync_pull.sync_payments_for_contractor",
                   return_value=(2, 1, None)) as m, \
             patch("app.services.wfirma_payment_db.init_payment_db"):
            r = c.post("/api/v1/wfirma/sync/payments-pull", json={"contractor_id": "123"})
        assert r.status_code == 200
        body = r.json()
        assert body["direction"] == "PULL"
        assert body["new"] == 2 and body["existing"] == 1
        assert body["contractor_id"] == "123"
        # ONLY the read/pull processor was called, once, with the contractor id.
        assert m.call_count == 1
        assert m.call_args.args[0] == "123"
    finally:
        _teardown()


def test_payments_pull_missing_contractor_id_is_rejected():
    c = _client()
    try:
        r1 = c.post("/api/v1/wfirma/sync/payments-pull", json={})
        assert r1.status_code == 422                       # pydantic: field required
        with patch("app.services.wfirma_payment_db.init_payment_db"):
            r2 = c.post("/api/v1/wfirma/sync/payments-pull", json={"contractor_id": "  "})
        assert r2.status_code == 400                       # empty after strip
    finally:
        _teardown()


def test_payments_pull_wfirma_error_returns_502():
    c = _client()
    try:
        with patch("app.api.routes_wfirma_sync_pull.sync_payments_for_contractor",
                   return_value=(0, 0, "fetch failed: HTTP 500")), \
             patch("app.services.wfirma_payment_db.init_payment_db"):
            r = c.post("/api/v1/wfirma/sync/payments-pull", json={"contractor_id": "123"})
        assert r.status_code == 502
    finally:
        _teardown()


def test_no_push_type_can_route_through_this_router():
    c = _client()
    try:
        # Only payments-pull exists. Any push-ish path under the prefix is 404 —
        # there is no {type} dispatcher that could reach a write.
        for bad in ("customer-push", "product-push", "invoice-create", "goods-edit",
                    "proforma-create", "customer", "product", "sync-all"):
            r = c.post(f"/api/v1/wfirma/sync/{bad}", json={"contractor_id": "1"})
            assert r.status_code == 404, bad
    finally:
        _teardown()


# ── source-level safety (no write path can exist in this file) ───────────────

def _router_source() -> str:
    p = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_wfirma_sync_pull.py"
    return p.read_text(encoding="utf-8")


def _router_code_only() -> str:
    """Router source with the module docstring + comment lines removed, so the
    guard inspects EXECUTABLE code — the module docstring deliberately names the
    forbidden operations to document why they are excluded."""
    import ast
    src = _router_source()
    doc = ast.get_docstring(ast.parse(src), clean=False)
    if doc:
        src = src.replace('"""' + doc + '"""', "", 1)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def test_router_source_has_no_write_or_create_path():
    code = _router_code_only()
    forbidden_calls = [
        "goods/edit", "products/resolve", "sync-names", "sync_names",
        "create_product", "create_invoice", "create_proforma", "create_pz",
        '_http_request("POST"', "_http_request('POST'",
        '_http_request("PUT"', "_http_request('PUT'",
    ]
    for tok in forbidden_calls:
        assert tok not in code, f"forbidden write token present in executable code: {tok}"


def test_router_does_not_reference_any_wfirma_create_flag():
    code = _router_code_only()
    assert "wfirma_create_" not in code
    assert "_allowed" not in code


def test_router_imports_only_the_pull_processor():
    src = _router_source()
    # The single service import is the read/pull payment processor.
    assert "from ..services.wfirma_payment_sync_processor import sync_payments_for_contractor" in src
    # No push/write service is imported.
    for bad_import in ("wfirma_customer_sync import", "routes_wfirma import",
                       "products", "goods"):
        assert f"import {bad_import}" not in src

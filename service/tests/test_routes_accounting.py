"""Wave 4 Item 3A — GET /api/v1/accounting/documents/{doc_type} route tests.

Auth is overridden via dependency_overrides (per the project pattern); the wFirma
read (wfirma_client.list_invoices_by_type) is mocked so no live call is made.
Item 3B (WZ/PW/RW/MM) must 404 (undocumented — not served).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_api_key as get_current_user

_ROW = {
    "number": "FV 1/2026", "date": "2026-04-22", "party": "Crown Jewelers Ltd",
    "net": "19593.50", "tax": "4506.50", "gross": "24100.00", "currency": "USD",
    "state": "paid", "wfirma_id": "101",
}


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "t", "role": "admin"}
    return TestClient(app)


def test_accounting_invoice_returns_rows():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   return_value={"rows": [_ROW], "count": 1}) as m:
            r = c.get("/api/v1/accounting/documents/invoice")
        assert r.status_code == 200
        body = r.json()
        assert body["doc_type"] == "invoice"
        assert body["wfirma_type"] == "normal"
        assert body["count"] == 1
        assert body["rows"][0]["number"] == "FV 1/2026"
        assert m.call_args.args[0] == "normal"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_credit_note_maps_to_correction():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   return_value={"rows": [], "count": 0}) as m:
            r = c.get("/api/v1/accounting/documents/credit_note")
        assert r.status_code == 200
        assert r.json()["wfirma_type"] == "correction"
        assert m.call_args.args[0] == "correction"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_undocumented_type_returns_404():
    c = _client()
    try:
        for bad in ("wz", "pw", "rw", "mm"):
            r = c.get(f"/api/v1/accounting/documents/{bad}")
            assert r.status_code == 404, bad
            assert "undocumented" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_wfirma_error_returns_502():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   side_effect=RuntimeError("invoices/find HTTP 500")):
            r = c.get("/api/v1/accounting/documents/invoice")
        assert r.status_code == 502
    finally:
        app.dependency_overrides.pop(get_current_user, None)

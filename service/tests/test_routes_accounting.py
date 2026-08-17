"""Wave 4 Item 3A/P0 — GET /api/v1/accounting/documents/{doc_type} route tests.

Auth via dependency_overrides. wFirma reads mocked — no live calls.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_api_key as get_current_user

_ROW = {
    "number": "FV 1/2026", "date": "2026-04-22", "party": "Crown Jewelers Ltd",
    "net": "19593.50", "tax": "4506.50", "gross": "24100.00", "currency": "USD",
    "state": "Paid", "payment_state": "Paid", "wfirma_id": "101",
}


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "t", "role": "admin"}
    return TestClient(app)


def test_accounting_invoice_returns_rows():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   return_value={"rows": [_ROW], "count": 1, "page": 1, "limit": 15, "has_more": False}) as m:
            r = c.get("/api/v1/accounting/documents/invoice")
        assert r.status_code == 200
        body = r.json()
        assert body["doc_type"] == "invoice"
        assert body["wfirma_type"] == "normal"
        assert body["count"] == 1
        assert body["rows"][0]["number"] == "FV 1/2026"
        assert body["limit"] == 15
        assert body["page"] == 1
        assert body["sort"] == "date_desc"
        assert m.call_args.args[0] == "normal"
        assert m.call_args.kwargs.get("limit") == 15
        assert m.call_args.kwargs.get("page") == 1
        assert m.call_args.kwargs.get("sort") == "date_desc"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_invoice_year_and_page_passed_to_client():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   return_value={"rows": [], "count": 0, "has_more": False}) as m:
            r = c.get("/api/v1/accounting/documents/invoice?year=2025&page=2&limit=15")
        assert r.status_code == 200
        assert m.call_args.kwargs["page"] == 2
        assert m.call_args.kwargs["limit"] == 15
        assert m.call_args.kwargs["date_from"] == "2025-01-01"
        assert m.call_args.kwargs["date_to"] == "2025-12-31"
        body = r.json()
        assert body["year"] == 2025
        assert body["page"] == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_invoice_all_years_no_date_window():
    c = _client()
    try:
        with patch("app.api.routes_accounting.wfirma_client.list_invoices_by_type",
                   return_value={"rows": [], "count": 0, "has_more": False}) as m:
            r = c.get("/api/v1/accounting/documents/invoice?year=all")
        assert r.status_code == 200
        assert m.call_args.kwargs.get("date_from") is None
        assert m.call_args.kwargs.get("date_to") is None
        assert r.json()["all_years"] is True
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


def test_accounting_warehouse_types_live():
    c = _client()
    try:
        with patch(
            "app.api.routes_accounting.wfirma_client.list_warehouse_documents_by_type",
            return_value={"rows": [], "count": 0},
        ) as m:
            for t in ("wz", "pz", "pw", "rw"):
                r = c.get(f"/api/v1/accounting/documents/{t}")
                assert r.status_code == 200, t
                assert r.json()["warehouse_type"] == t.upper()
        assert m.call_count == 4
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_mm_unavailable():
    c = _client()
    try:
        r = c.get("/api/v1/accounting/documents/mm")
        assert r.status_code == 404
        assert "unavailable" in r.json()["detail"].lower()
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


def test_accounting_wz_awbs_endpoint():
    c = _client()
    try:
        with patch(
            "app.services.accounting_awb_projection.resolve_awbs_for_warehouse_document",
            return_value={"awbs": [{"awb": "1234567890", "carrier": "DHL"}], "source": "test"},
        ) as m:
            r = c.get("/api/v1/accounting/documents/wz/999/awbs")
        assert r.status_code == 200
        body = r.json()
        assert body["doc_type"] == "wz"
        assert body["wfirma_id"] == "999"
        assert body["awbs"][0]["awb"] == "1234567890"
        m.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_accounting_awbs_rejects_non_warehouse_types():
    c = _client()
    try:
        r = c.get("/api/v1/accounting/documents/invoice/1/awbs")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


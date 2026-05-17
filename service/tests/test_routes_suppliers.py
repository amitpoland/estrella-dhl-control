"""test_routes_suppliers.py — GET /api/v1/suppliers/ contract.

Read-only dropdown source for the New Shipment modal. Sourced from
``wfirma_customers``. No writes, no auth-mutating, no wFirma calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Storage root must exist before app import so wFirma DB inits cleanly.
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.main import app
    from app.services import wfirma_db as wfdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    yield TestClient(app), wfdb


def _auth():
    # The default API key for tests; require_api_key reads from settings.
    from app.core.config import settings
    return {"X-API-Key": getattr(settings, "api_key", None) or "test-key"}


def test_suppliers_endpoint_returns_empty_list_when_db_empty(client):
    cli, _ = client
    r = cli.get("/api/v1/suppliers/", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "suppliers" in body
    assert isinstance(body["suppliers"], list)
    assert body["count"] == 0


def test_suppliers_endpoint_lists_wfirma_customers(client):
    cli, wfdb = client
    wfdb.upsert_customer(client_name="SEEPZ Manufacturer Pvt Ltd",
                         vat_id="AAACS1234A", country="IN")
    wfdb.upsert_customer(client_name="German Buyer GmbH",
                         vat_id="DE123456789", country="DE")
    r = cli.get("/api/v1/suppliers/", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    names = sorted(s["name"] for s in body["suppliers"])
    assert names == ["German Buyer GmbH", "SEEPZ Manufacturer Pvt Ltd"]
    # Each row must carry a stable contractor_id usable by the modal.
    for s in body["suppliers"]:
        assert s["contractor_id"], "every supplier row must carry an internal contractor_id"


def test_suppliers_endpoint_country_filter(client):
    cli, wfdb = client
    wfdb.upsert_customer(client_name="Indian Supplier", vat_id="X", country="IN")
    wfdb.upsert_customer(client_name="German Supplier", vat_id="Y", country="DE")
    r = cli.get("/api/v1/suppliers/?country=IN", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["suppliers"][0]["country"] == "IN"


def test_suppliers_endpoint_is_read_only_no_write_routes():
    """Source-grep: routes_suppliers.py defines only a GET handler."""
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_suppliers.py"
    text = src.read_text(encoding="utf-8")
    assert "@router.get" in text
    assert "@router.post" not in text
    assert "@router.put" not in text
    assert "@router.delete" not in text
    assert "@router.patch" not in text

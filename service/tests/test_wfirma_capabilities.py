"""
test_wfirma_capabilities.py — wFirma capability checker + mapping tables.

Covers:
  1. Capabilities: no credentials → api_configured=False, all features blocked
  2. Capabilities: login+password+company set → api_configured=True
  3. Capabilities: warehouse flag + id set → warehouse_module_enabled=True
  4. Capabilities: blocking_reasons populated for missing fields
  5. Capabilities: ready_to_reserve requires api + warehouse both true
  6. Customer upsert + retrieve
  7. Product upsert + retrieve
  8. GET /capabilities endpoint returns 200 with correct schema
  9. PUT /customers and GET /customers endpoints
 10. PUT /products and GET /products endpoints
 11. list_customers filtered by match_status
 12. list_products filtered by sync_status
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import wfirma_db as wfdb
from app.services import wfirma_capabilities as wfc


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wfirma_cap_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    from app.services.packing_db import init_packing_db
    from app.services.document_db import init_document_db
    from app.services.warehouse_db import init_warehouse_db
    init_packing_db(tmp_storage / "packing.db")
    init_document_db(tmp_storage / "documents.db")
    init_warehouse_db(tmp_storage / "warehouse.db")
    wfdb.init_wfirma_db(tmp_storage / "wfirma.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Tests: capability checker (config-only) ───────────────────────────────────

def test_no_credentials_api_not_configured(db):
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
        wfirma_company_id="",
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        caps = wfc.get_capabilities()
    assert caps["api_configured"] is False
    assert caps["api_user_configured"] is False
    assert caps["warehouse_module_enabled"] is False
    assert caps["reservation_supported"] is False
    assert caps["ready_to_reserve"] is False


def test_no_credentials_blocking_reasons_populated(db):
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_app_key=None,
        wfirma_company_id="",
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        caps = wfc.get_capabilities()
    assert len(caps["blocking_reasons"]) >= 3  # login, password, company_id


def test_credentials_set_api_configured(db):
    with patch.multiple(
        settings,
        wfirma_access_key="ACC-KEY",
        wfirma_secret_key="SEC-KEY",
        wfirma_app_key="APP-KEY",
        wfirma_company_id="123456",
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        caps = wfc.get_capabilities()
    assert caps["api_configured"] is True
    assert caps["product_api_supported"] is True
    assert caps["customer_api_supported"] is True


def test_warehouse_flag_without_id_not_enabled(db):
    with patch.multiple(
        settings,
        wfirma_access_key="u", wfirma_secret_key="s", wfirma_app_key="a",
        wfirma_company_id="123",
        wfirma_warehouse_module_enabled=True,
        wfirma_warehouse_id="",        # missing id → not enabled
    ):
        caps = wfc.get_capabilities()
    assert caps["warehouse_module_enabled"] is False
    assert caps["reservation_supported"] is False


def test_warehouse_fully_configured(db):
    with patch.multiple(
        settings,
        wfirma_access_key="u", wfirma_secret_key="s", wfirma_app_key="a",
        wfirma_company_id="123",
        wfirma_warehouse_module_enabled=True,
        wfirma_warehouse_id="WH-001",
    ):
        caps = wfc.get_capabilities()
    assert caps["warehouse_module_enabled"] is True
    assert caps["reservation_supported"] is True
    assert caps["ready_to_reserve"] is True
    assert caps["blocking_reasons"] == []


def test_ready_to_reserve_false_without_warehouse(db):
    with patch.multiple(
        settings,
        wfirma_access_key="u", wfirma_secret_key="s", wfirma_app_key="a",
        wfirma_company_id="123",
        wfirma_warehouse_module_enabled=False,
        wfirma_warehouse_id="",
    ):
        caps = wfc.get_capabilities()
    assert caps["ready_to_reserve"] is False


def test_create_flags_reflected(db):
    with patch.multiple(
        settings,
        wfirma_access_key="u", wfirma_secret_key="s", wfirma_app_key="a",
        wfirma_company_id="123",
        wfirma_create_product_allowed=True,
        wfirma_create_customer_allowed=False,
    ):
        caps = wfc.get_capabilities()
    assert caps["create_product_allowed"] is True
    assert caps["create_customer_allowed"] is False


# ── Tests: wfirma_db customer mapping ────────────────────────────────────────

def test_upsert_and_get_customer(db):
    row_id = wfdb.upsert_customer(
        "Verhoeven",
        wfirma_customer_id="C-001",
        vat_id="NL123456",
        country="NL",
        match_status="matched",
    )
    assert row_id

    rec = wfdb.get_customer("Verhoeven")
    assert rec is not None
    assert rec["wfirma_customer_id"] == "C-001"
    assert rec["match_status"] == "matched"
    assert rec["country"] == "NL"


def test_upsert_customer_updates_existing(db):
    wfdb.upsert_customer("UpdateClient", match_status="pending")
    wfdb.upsert_customer(
        "UpdateClient",
        wfirma_customer_id="C-UPD",
        match_status="matched",
    )
    rec = wfdb.get_customer("UpdateClient")
    assert rec["wfirma_customer_id"] == "C-UPD"
    assert rec["match_status"] == "matched"


def test_get_unknown_customer_returns_none(db):
    assert wfdb.get_customer("NoSuchClient") is None


def test_list_customers_by_status(db):
    wfdb.upsert_customer("PendingClient1", match_status="pending")
    wfdb.upsert_customer("PendingClient2", match_status="pending")
    pending = wfdb.list_customers(match_status="pending")
    names = [r["client_name"] for r in pending]
    assert "PendingClient1" in names
    assert "PendingClient2" in names
    # Matched clients should not appear
    assert "Verhoeven" not in names


# ── Tests: wfirma_db product mapping ─────────────────────────────────────────

def test_upsert_and_get_product(db):
    row_id = wfdb.upsert_product(
        "EJL/26-27/015-6",
        wfirma_product_id="P-001",
        product_name_pl="Pierścionek złoty",
        unit="szt.",
        vat_rate="23",
        warehouse_id="WH-001",
        sync_status="matched",
    )
    assert row_id

    rec = wfdb.get_product("EJL/26-27/015-6")
    assert rec is not None
    assert rec["wfirma_product_id"] == "P-001"
    assert rec["sync_status"] == "matched"
    assert rec["unit"] == "szt."


def test_upsert_product_updates_existing(db):
    wfdb.upsert_product("EJL/UPDATE/001", sync_status="pending")
    wfdb.upsert_product(
        "EJL/UPDATE/001",
        wfirma_product_id="P-UPD",
        sync_status="matched",
    )
    rec = wfdb.get_product("EJL/UPDATE/001")
    assert rec["wfirma_product_id"] == "P-UPD"


def test_get_unknown_product_returns_none(db):
    assert wfdb.get_product("EJL/DOES-NOT-EXIST") is None


def test_list_products_by_status(db):
    wfdb.upsert_product("EJL/PEND/001", sync_status="pending")
    wfdb.upsert_product("EJL/PEND/002", sync_status="pending")
    pending = wfdb.list_products(sync_status="pending")
    codes = [r["product_code"] for r in pending]
    assert "EJL/PEND/001" in codes
    assert "EJL/PEND/002" in codes
    assert "EJL/26-27/015-6" not in codes  # matched, not pending


# ── Tests: reservation draft + lines ─────────────────────────────────────────

def test_upsert_and_list_draft(db):
    draft_id = wfdb.upsert_reservation_draft(
        "WFC_BATCH_001", "Test Client",
        client_ref="TC/001",
        currency="USD",
        warehouse_id="WH-001",
        ready_to_create=True,
    )
    assert draft_id
    drafts = wfdb.list_reservation_drafts("WFC_BATCH_001")
    assert len(drafts) == 1
    assert drafts[0]["client_name"] == "Test Client"
    assert drafts[0]["ready_to_create"] == 1


def test_upsert_draft_is_idempotent(db):
    wfdb.upsert_reservation_draft("WFC_BATCH_001", "Test Client", currency="EUR")
    drafts = wfdb.list_reservation_drafts("WFC_BATCH_001")
    # Still 1 draft — updated, not duplicated
    assert len(drafts) == 1
    assert drafts[0]["currency"] == "EUR"


def test_reservation_lines(db):
    draft_id = wfdb.upsert_reservation_draft("WFC_BATCH_001", "Test Client")
    wfdb.upsert_reservation_line(
        draft_id, "EJL/26-27/015-6",
        qty=5.0, unit_price=100.0, currency="USD",
        stock_ok=True, product_ok=True,
    )
    wfdb.upsert_reservation_line(
        draft_id, "EJL/26-27/015-7",
        qty=2.0, unit_price=200.0, currency="USD",
        stock_ok=False, product_ok=False,
    )
    lines = wfdb.list_reservation_lines(draft_id)
    assert len(lines) == 2
    line_1 = next(l for l in lines if l["product_code"] == "EJL/26-27/015-6")
    assert line_1["stock_ok"] == 1
    assert line_1["product_ok"] == 1
    assert line_1["qty"] == 5.0


# ── Tests: API endpoints ──────────────────────────────────────────────────────

def test_capabilities_endpoint_200(client):
    r = client.get("/api/v1/wfirma/capabilities", headers=_auth())
    assert r.status_code == 200


def test_capabilities_endpoint_schema(client):
    r = client.get("/api/v1/wfirma/capabilities", headers=_auth())
    body = r.json()
    for key in (
        "api_configured", "api_user_configured", "warehouse_module_enabled",
        "reservation_supported", "product_api_supported", "customer_api_supported",
        "proforma_supported", "currency_supported", "blocking_reasons",
        "ready_to_reserve",
    ):
        assert key in body, f"Missing key: {key}"


def test_put_customer_endpoint(client, db):
    r = client.put(
        "/api/v1/wfirma/customers/Dream Rings",
        json={
            "wfirma_customer_id": "C-DREAM",
            "vat_id": "GB12345",
            "country": "GB",
            "match_status": "matched",
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["client_name"] == "Dream Rings"

    rec = wfdb.get_customer("Dream Rings")
    assert rec["wfirma_customer_id"] == "C-DREAM"


def test_get_customers_endpoint(client):
    r = client.get("/api/v1/wfirma/customers", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert "customers" in body
    assert "count" in body
    names = [c["client_name"] for c in body["customers"]]
    assert "Dream Rings" in names


def test_put_product_endpoint(client, db):
    r = client.put(
        "/api/v1/wfirma/products/EJL%2F26-27%2F015-1",
        json={
            "wfirma_product_id": "P-API-001",
            "product_name_pl":   "Pierścionek testowy",
            "unit":              "szt.",
            "vat_rate":          "23",
            "warehouse_id":      "WH-001",
            "sync_status":       "matched",
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


def test_get_products_endpoint(client):
    r = client.get("/api/v1/wfirma/products", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert "products" in body
    assert "count" in body

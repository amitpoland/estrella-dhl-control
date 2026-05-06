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


# ── Live search endpoints (operator-approved mapping) ──────────────────────

from app.services import wfirma_client as _wc


def _no_create_patches():
    """Patch create_customer and create_product so any accidental call fails."""
    return [
        patch.object(_wc, "create_customer",
                     side_effect=AssertionError("create_customer must not be called")),
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("create_product must not be called")),
    ]


def _draft_count(db_path):
    import sqlite3
    with sqlite3.connect(str(db_path / "wfirma.db")) as con:
        c = con.execute("SELECT COUNT(*) FROM wfirma_customers").fetchone()[0]
        p = con.execute("SELECT COUNT(*) FROM wfirma_products").fetchone()[0]
    return (c, p)


# ── Customer search ────────────────────────────────────────────────────────

def test_contractor_search_hit(client, db):
    fake = _wc.WFirmaContractor(
        wfirma_id="C-99", name="Juliany EOOD", nip="BG123456789",
        country="BG", zip="1000", city="Sofia",
    )
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "search_customer", return_value=fake) as mock:
            r = client.get(
                "/api/v1/wfirma/contractors/search?name=Juliany%20EOOD",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "ok":     True,
        "found":  True,
        "result": {
            "wfirma_id": "C-99", "name": "Juliany EOOD", "nip": "BG123456789",
            "country": "BG", "zip": "1000", "city": "Sofia",
        },
    }
    mock.assert_called_once_with("Juliany EOOD", None)


def test_contractor_search_miss(client, db):
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "search_customer", return_value=None):
            r = client.get(
                "/api/v1/wfirma/contractors/search?name=GhostCorp",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    body = r.json()
    assert body == {"ok": True, "found": False, "result": None}


def test_contractor_search_error_returns_502(client, db):
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "search_customer",
                          side_effect=RuntimeError("upstream 503")):
            r = client.get(
                "/api/v1/wfirma/contractors/search?name=BoomCorp",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["ok"] is False and detail["found"] is False
    assert "RuntimeError" in detail["error"]


def test_contractor_search_does_not_write_local_db(client, db):
    before = _draft_count(db)
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "search_customer", return_value=None):
            client.get("/api/v1/wfirma/contractors/search?name=NoOp",
                       headers=_auth())
    finally:
        for p in blockers: p.stop()
    after = _draft_count(db)
    assert before == after


# ── Product search ─────────────────────────────────────────────────────────

def test_goods_search_hit(client, db):
    fake = _wc.WFirmaProduct(
        wfirma_id="G-42", name="Ring 18kt", code="EJL/26-27/100-1",
        unit="szt.", count=1.0, reserved=0.0,
    )
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", return_value=fake) as mock:
            r = client.get(
                "/api/v1/wfirma/goods/search?product_code=EJL/26-27/100-1",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    body = r.json()
    assert body["ok"] is True
    assert body["found"] is True
    assert body["result"]["wfirma_id"] == "G-42"
    assert body["result"]["code"]      == "EJL/26-27/100-1"
    mock.assert_called_once_with("EJL/26-27/100-1")


def test_goods_search_miss(client, db):
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", return_value=None):
            r = client.get(
                "/api/v1/wfirma/goods/search?product_code=GHOST",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    assert r.json() == {"ok": True, "found": False, "result": None}


def test_goods_search_error_returns_502(client, db):
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code",
                          side_effect=ConnectionError("DNS timeout")):
            r = client.get(
                "/api/v1/wfirma/goods/search?product_code=BOOM",
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["ok"] is False
    assert "ConnectionError" in detail["error"]


def test_goods_search_does_not_write_local_db(client, db):
    before = _draft_count(db)
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", return_value=None):
            client.get("/api/v1/wfirma/goods/search?product_code=NOOP",
                       headers=_auth())
    finally:
        for p in blockers: p.stop()
    after = _draft_count(db)
    assert before == after


def test_search_endpoints_never_call_create_primitives(client, db):
    """Belt-and-suspenders: even hits and misses never reach create_*."""
    fake_c = _wc.WFirmaContractor(wfirma_id="C-1", name="X", nip="", country="",
                                   zip="", city="")
    fake_p = _wc.WFirmaProduct(wfirma_id="G-1", name="P", code="X",
                                unit="szt.", count=1.0, reserved=0.0)
    with (
        patch.object(_wc, "search_customer", return_value=fake_c),
        patch.object(_wc, "get_product_by_code", return_value=fake_p),
        patch.object(_wc, "create_customer",
                     side_effect=AssertionError("never")),
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("never")),
    ):
        r1 = client.get("/api/v1/wfirma/contractors/search?name=X",
                        headers=_auth())
        r2 = client.get("/api/v1/wfirma/goods/search?product_code=X",
                        headers=_auth())
    assert r1.status_code == 200
    assert r2.status_code == 200


# ── Bulk goods search ───────────────────────────────────────────────────────

def _bulk_payload(codes):
    return {"product_codes": codes}


def test_goods_bulk_search_all_found(client, db):
    def by_code(pc):
        return _wc.WFirmaProduct(
            wfirma_id=f"G-{pc[-1]}", name=f"P-{pc}", code=pc,
            unit="szt.", count=1.0, reserved=0.0,
        )
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", side_effect=by_code):
            r = client.post(
                "/api/v1/wfirma/goods/search-bulk",
                json=_bulk_payload(["EJL/26-27/100-1", "EJL/26-27/100-2"]),
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    body = r.json()
    assert body["ok"] is True
    assert body["count"]         == 2
    assert body["found_count"]   == 2
    assert body["missing_count"] == 0
    assert body["error_count"]   == 0
    assert [x["product_code"] for x in body["results"]] == \
           ["EJL/26-27/100-1", "EJL/26-27/100-2"]
    assert all(x["found"] for x in body["results"])


def test_goods_bulk_search_mixed_found_missing(client, db):
    def by_code(pc):
        if pc == "EJL/26-27/100-1":
            return _wc.WFirmaProduct(wfirma_id="G-1", name="P", code=pc,
                                     unit="szt.", count=1, reserved=0)
        return None
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", side_effect=by_code):
            r = client.post(
                "/api/v1/wfirma/goods/search-bulk",
                json=_bulk_payload(["EJL/26-27/100-1", "EJL/26-27/100-2"]),
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    body = r.json()
    assert body["found_count"]   == 1
    assert body["missing_count"] == 1
    assert body["error_count"]   == 0
    rs = body["results"]
    assert rs[0]["found"] is True  and rs[0]["result"]["wfirma_id"] == "G-1"
    assert rs[1]["found"] is False and rs[1]["result"] is None


def test_goods_bulk_search_lookup_error_captured_per_code(client, db):
    def by_code(pc):
        if pc == "BOOM":
            raise RuntimeError("upstream 503")
        return _wc.WFirmaProduct(wfirma_id="G-OK", name="ok", code=pc,
                                 unit="szt.", count=1, reserved=0)
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", side_effect=by_code):
            r = client.post(
                "/api/v1/wfirma/goods/search-bulk",
                json=_bulk_payload(["GOOD-1", "BOOM", "GOOD-2"]),
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    assert r.status_code == 200
    body = r.json()
    assert body["found_count"] == 2
    assert body["error_count"] == 1
    rs = body["results"]
    assert rs[0]["found"] is True
    assert rs[1]["found"] is False and "RuntimeError" in rs[1]["error"]
    assert rs[2]["found"] is True


def test_goods_bulk_search_input_order_preserved(client, db):
    """Output must mirror input order even when duplicate codes are present."""
    def by_code(pc):
        return _wc.WFirmaProduct(wfirma_id=f"G-{pc}", name="x", code=pc,
                                 unit="szt.", count=1, reserved=0)
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code",
                          side_effect=by_code) as mock:
            r = client.post(
                "/api/v1/wfirma/goods/search-bulk",
                json=_bulk_payload(["A", "B", "A", "C"]),
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    body = r.json()
    assert [x["product_code"] for x in body["results"]] == ["A", "B", "A", "C"]
    # Dedupe: only 3 distinct lookups
    assert mock.call_count == 3
    # Same row repeated for "A"
    assert body["results"][0]["result"]["wfirma_id"] == \
           body["results"][2]["result"]["wfirma_id"]


def test_goods_bulk_search_empty_payload_422(client, db):
    r = client.post(
        "/api/v1/wfirma/goods/search-bulk",
        json=_bulk_payload([]),
        headers=_auth(),
    )
    assert r.status_code == 422


def test_goods_bulk_search_does_not_write_local_db(client, db):
    before = _draft_count(db)
    blockers = _no_create_patches()
    for p in blockers: p.start()
    try:
        with patch.object(_wc, "get_product_by_code", return_value=None):
            client.post(
                "/api/v1/wfirma/goods/search-bulk",
                json=_bulk_payload(["X1", "X2", "X3"]),
                headers=_auth(),
            )
    finally:
        for p in blockers: p.stop()
    after = _draft_count(db)
    assert before == after


def test_goods_bulk_search_never_calls_create_product(client, db):
    """Strict: even hits never reach create_product."""
    def by_code(pc):
        return _wc.WFirmaProduct(wfirma_id="G", name="x", code=pc,
                                 unit="szt.", count=1, reserved=0)
    with (
        patch.object(_wc, "get_product_by_code", side_effect=by_code),
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("never")),
    ):
        r = client.post(
            "/api/v1/wfirma/goods/search-bulk",
            json=_bulk_payload(["A", "B"]),
            headers=_auth(),
        )
    assert r.status_code == 200


# ── create-from-product-code endpoint ──────────────────────────────────────

CREATE_URL = "/api/v1/wfirma/goods/create-from-product-code/"


def _gate_create_on():
    return patch.object(settings, "wfirma_create_product_allowed", True)


def _gate_create_off():
    return patch.object(settings, "wfirma_create_product_allowed", False)


def test_create_from_code_existing_maps_without_create(client, db):
    """Existing product in wFirma → status=existing_mapped, create not called."""
    found = _wc.WFirmaProduct(wfirma_id="G-EXIST", name="Pierścionek złoty",
                              code="EJL/26-27/100-1", unit="szt.",
                              count=5.0, reserved=0.0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=found) as mock_search,
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("must not be called when existing found")),
    ):
        r = client.post(
            CREATE_URL + "EJL/26-27/100-1",
            json={"item_type": "RING", "description_en": "Gold Ring"},
            headers=_auth(),
        )
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "existing_mapped"
    assert body["wfirma_product_id"] == "G-EXIST"
    mock_search.assert_called_once_with("EJL/26-27/100-1")
    # Local mapping persisted
    saved = wfdb.get_product("EJL/26-27/100-1")
    assert saved is not None
    assert saved["wfirma_product_id"] == "G-EXIST"
    assert saved["sync_status"]       == "matched"


def test_create_from_code_missing_blocked_when_flag_off(client, db):
    """Missing in wFirma + flag false → status=blocked, no create call."""
    with (
        _gate_create_off(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("must not be called when blocked")),
    ):
        r = client.post(
            CREATE_URL + "EJL/26-27/100-2",
            json={"item_type": "RING", "description_en": "Ring"},
            headers=_auth(),
        )
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "blocked"
    assert any("WFIRMA_CREATE_PRODUCT_ALLOWED" in br
               for br in body["blocking_reasons"])
    # No local mapping persisted
    assert wfdb.get_product("EJL/26-27/100-2") is None


def test_create_from_code_missing_creates_when_flag_on(client, db):
    """Missing + flag true → calls create_product once → status=created."""
    created = _wc.WFirmaProduct(wfirma_id="G-NEW-1", name="Pierścionek",
                                code="EJL/26-27/100-3", unit="szt.",
                                count=0.0, reserved=0.0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None) as mock_search,
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=created) as mock_create,
    ):
        r = client.post(
            CREATE_URL + "EJL/26-27/100-3",
            json={"item_type": "RING",
                  "description_en": "Diamond Ring"},
            headers=_auth(),
        )
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "created"
    assert body["wfirma_product_id"] == "G-NEW-1"

    # Search must have happened before create
    mock_search.assert_called_once_with("EJL/26-27/100-3")
    mock_create.assert_called_once()

    # Caller-uncontrollable fields must be the locked defaults
    call = mock_create.call_args
    assert call.kwargs["unit"]        == "szt."
    assert call.kwargs["vat_code_id"] == "VAT23"
    # description must be the locked block content from description_engine
    assert "Co to za towar / What is this" in call.kwargs["description"]
    # Polish-first / English-after-slash composed line in description body
    assert "Diamond Ring" in call.kwargs["description"]
    # Master-data name = locked description_line (Polish-first / English after slash)
    assert call.kwargs["name"] == "Biżuteria — pierścionek / Diamond Ring"
    # product_code must NOT be appended in parens — the wFirma <code> field
    # already carries it.
    assert "(EJL/26-27/100-3)" not in call.kwargs["name"]


# ── Strict master-data name rule (docs/wfirma.skill.md §5) ─────────────────

def test_create_from_code_name_is_locked_description_line(client, db):
    """
    name = description_line (Polish-first / English-after-slash). The
    wFirma <code> field already carries the product_code — appending it
    to <name> is noise. Slash IS allowed in name (Polish/English separator).
    """
    created = _wc.WFirmaProduct(wfirma_id="G-NAME-1", name="x", code="EJL/N-1",
                                unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=created) as mock_create,
    ):
        client.post(
            CREATE_URL + "EJL/N-1",
            json={"item_type": "RING",
                  "description_en": "Lab Grown Diamond 14KT Gold Ring"},
            headers=_auth(),
        )
    name = mock_create.call_args.kwargs["name"]
    # Description line content present
    assert "Biżuteria — pierścionek" in name
    assert "Lab Grown Diamond 14KT Gold Ring" in name
    # Polish/English slash separator (the description-line semantic)
    assert " / " in name
    # product_code MUST NOT be wrapped in parens at the end — the <code>
    # field carries it; repeating in <name> is noise.
    assert "(EJL/N-1)" not in name
    # No structural description-block labels leak into name
    assert "Co to za towar" not in name


def test_create_from_code_description_keeps_full_bilingual_block(client, db):
    """description still carries the full block + Polish/English slash."""
    created = _wc.WFirmaProduct(wfirma_id="G-DESC-1", name="x", code="EJL/D-1",
                                unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=created) as mock_create,
    ):
        client.post(
            CREATE_URL + "EJL/D-1",
            json={"item_type": "EARRINGS",
                  "description_en": "Diamond Stud Earrings"},
            headers=_auth(),
        )
    description = mock_create.call_args.kwargs["description"]
    # Three-section bilingual labels present
    assert "Co to za towar / What is this" in description
    assert "Z jakiego materiału / Material" in description
    assert "Do czego służy / Purpose" in description
    # English half present (under the "Co to za towar" content row)
    assert "Diamond Stud Earrings" in description
    # Slash between Polish and English
    assert " / " in description


def test_create_from_code_name_falls_back_when_block_empty(client, db):
    """
    Fallback chain: description_line → name_pl → product_code.
    If both description_line and name_pl are empty (operator manual
    override with empty fields), name falls back to bare product_code.
    """
    from app.services import description_engine as deng
    # Manual override with empty name_pl AND empty description_pl/en →
    # build_description_line returns "" → description_line empty.
    deng.set_manual_block(
        product_code   = "EJL/FB-EMPTY",
        item_type      = "RING",
        name_pl        = "",
        description_pl = "",
        material_pl    = "x",
        purpose_pl     = "x",
        description_en = "",
    )
    created = _wc.WFirmaProduct(wfirma_id="G-FB-1", name="x", code="EJL/FB-EMPTY",
                                unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=created) as mock_create,
    ):
        client.post(
            CREATE_URL + "EJL/FB-EMPTY",
            json={"item_type": "RING", "description_en": ""},
            headers=_auth(),
        )
    name = mock_create.call_args.kwargs["name"]
    assert name == "EJL/FB-EMPTY"


def test_create_from_code_caller_cannot_change_unit_vat_type(client, db):
    """Server-controlled fields ignore caller body shape."""
    created = _wc.WFirmaProduct(wfirma_id="G-CC-1", name="x", code="EJL/CC-1",
                                unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=created) as mock_create,
    ):
        # malicious body trying to override
        client.post(
            CREATE_URL + "EJL/CC-1",
            json={
                "item_type":      "RING",
                "description_en": "x",
                "unit":           "kg",      # ignored
                "vat_rate":       "0",       # ignored
                "type":           "service", # ignored
                "code":           "ATTACKER",# ignored
                "name":           "ATTACKER NAME", # ignored
            },
            headers=_auth(),
        )
    call = mock_create.call_args
    assert call.kwargs["unit"]         == "szt."
    assert call.kwargs["vat_code_id"]  == "VAT23"
    assert call.kwargs["product_code"] == "EJL/CC-1"
    assert "ATTACKER" not in call.kwargs["name"]

    saved = wfdb.get_product("EJL/26-27/100-3")
    assert saved["wfirma_product_id"] == "G-NEW-1"
    assert saved["sync_status"]       == "matched"


def test_create_from_code_search_called_before_create(client, db):
    """Verify ordering: search runs before any create attempt."""
    call_order = []
    def search_side(pc):
        call_order.append("search")
        return None
    def create_side(**kwargs):
        call_order.append("create")
        return _wc.WFirmaProduct(wfirma_id="G-X", name="x", code=kwargs["product_code"],
                                  unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", side_effect=search_side),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", side_effect=create_side),
    ):
        client.post(CREATE_URL + "EJL/26-27/100-4",
                    json={"item_type": "RING", "description_en": "x"},
                    headers=_auth())
    assert call_order == ["search", "create"]


def test_create_from_code_create_failure_no_fake_mapping(client, db):
    """create_product raises → status=failed; no local mapping written."""
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product",
                     side_effect=RuntimeError("wFirma 503")),
    ):
        r = client.post(CREATE_URL + "EJL/26-27/100-5",
                        json={"item_type": "RING", "description_en": "x"},
                        headers=_auth())
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "failed"
    assert "RuntimeError" in body["error"]
    assert wfdb.get_product("EJL/26-27/100-5") is None


def test_create_from_code_empty_wfirma_id_no_fake_mapping(client, db):
    """create returns blank wfirma_id → refuse to save fake mapping."""
    no_id = _wc.WFirmaProduct(wfirma_id="", name="x", code="EJL/26-27/100-6",
                              unit="szt.", count=0, reserved=0)
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code", return_value=None),
        patch.object(_wc, "find_vat_code_id", return_value="VAT23"),
        patch.object(_wc, "create_product", return_value=no_id),
    ):
        r = client.post(CREATE_URL + "EJL/26-27/100-6",
                        json={"item_type": "RING", "description_en": "x"},
                        headers=_auth())
    body = r.json()
    assert body["status"] == "failed"
    assert wfdb.get_product("EJL/26-27/100-6") is None


def test_create_from_code_search_error_returns_502(client, db):
    """Search upstream error → 502, no create call."""
    with (
        _gate_create_on(),
        patch.object(_wc, "get_product_by_code",
                     side_effect=ConnectionError("DNS")),
        patch.object(_wc, "create_product",
                     side_effect=AssertionError("must not be called")),
    ):
        r = client.post(CREATE_URL + "EJL/26-27/100-7",
                        json={"item_type": "RING", "description_en": "x"},
                        headers=_auth())
    assert r.status_code == 502


# ── refresh-name-from-block (goods/edit) endpoint ──────────────────────────

REFRESH_URL = "/api/v1/wfirma/goods/refresh-name-from-block/"


def _gate_edit_on():
    return patch.object(settings, "wfirma_edit_product_allowed", True)


def _seed_local_mapping(product_code: str, wfirma_product_id: str = "G-EXIST"):
    wfdb.upsert_product(
        product_code      = product_code,
        wfirma_product_id = wfirma_product_id,
        product_name_pl   = "Pierścionek",
        unit              = "szt.",
        vat_rate          = "23",
        sync_status       = "matched",
    )


def _seed_locked_block(product_code: str, item_type: str = "RING",
                       description_en: str = "Lab Grown Diamond Ring"):
    """Use description_engine to write a locked auto block."""
    from app.services import description_engine as deng
    deng.get_description_block(product_code, item_type,
                                description_en=description_en)


def test_refresh_blocked_when_flag_off(client, db):
    """Default flag is False → status=blocked, no wFirma call, no local change."""
    pc = "EJL/REF/1"
    _seed_local_mapping(pc, "G-001")
    _seed_locked_block(pc)
    with (
        patch.object(_wc, "edit_product",
                     side_effect=AssertionError("must not be called when flag off")),
    ):
        r = client.post(REFRESH_URL + pc, headers=_auth())
    body = r.json()
    assert body["status"] == "blocked"
    assert any("WFIRMA_EDIT_PRODUCT_ALLOWED" in br
               for br in body["blocking_reasons"])


def test_refresh_blocked_when_local_mapping_missing(client, db):
    """No local row → blocked, no wFirma call."""
    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     side_effect=AssertionError("must not be called")),
    ):
        r = client.post(REFRESH_URL + "EJL/NOMAP-1", headers=_auth())
    body = r.json()
    assert body["status"] == "blocked"
    assert any("wfirma_product_id" in br for br in body["blocking_reasons"])


def test_refresh_blocked_when_local_wfirma_id_empty(client, db):
    """Local row exists but wfirma_product_id is empty → blocked."""
    pc = "EJL/REF/EMPTY"
    wfdb.upsert_product(product_code=pc, wfirma_product_id="",
                        sync_status="matched")
    _seed_locked_block(pc)
    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     side_effect=AssertionError("must not be called")),
    ):
        r = client.post(REFRESH_URL + pc, headers=_auth())
    assert r.json()["status"] == "blocked"


def test_refresh_blocked_when_locked_block_missing_or_empty(client, db):
    """description_engine returns a block with empty line/block → blocked."""
    from app.services import description_engine as deng
    pc = "EJL/REF/EMPTYBLK"
    _seed_local_mapping(pc, "G-EBL")
    # Manual override with empty fields → description_line/block both empty
    deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "",
        description_pl = "",
        material_pl    = "",
        purpose_pl     = "",
        description_en = "",
    )
    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     side_effect=AssertionError("must not be called")),
    ):
        r = client.post(REFRESH_URL + pc, headers=_auth())
    body = r.json()
    assert body["status"] == "blocked"
    assert any("description_engine" in br for br in body["blocking_reasons"])


def test_refresh_calls_edit_once_with_locked_payload(client, db):
    """Gate on + mapping + locked block → edit_product called once with
    wfirma_product_id + description_line + description_block."""
    pc = "EJL/REF/OK"
    _seed_local_mapping(pc, "G-OK-1")
    _seed_locked_block(pc, item_type="RING",
                       description_en="Lab Grown Diamond Ring")

    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     return_value={"wfirma_id": "G-OK-1", "name": "x",
                                    "code": pc, "unit": "szt."}) as mock_edit,
    ):
        body = client.post(REFRESH_URL + pc, headers=_auth()).json()

    assert body["ok"] is True
    assert body["status"] == "updated"
    assert body["wfirma_product_id"] == "G-OK-1"
    mock_edit.assert_called_once()
    call = mock_edit.call_args
    assert call.kwargs["wfirma_product_id"] == "G-OK-1"
    # Polish-first / English-after-slash composed name
    assert "Lab Grown Diamond Ring" in call.kwargs["name"]
    assert " / " in call.kwargs["name"]
    # Full bilingual block in description
    assert "Co to za towar / What is this" in call.kwargs["description"]


def test_refresh_does_not_pass_caller_body_overrides(client, db):
    """Caller body must be ignored — endpoint takes only the path arg."""
    pc = "EJL/REF/NOOV"
    _seed_local_mapping(pc, "G-NOOV-1")
    _seed_locked_block(pc, item_type="RING")
    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     return_value={"wfirma_id": "G-NOOV-1",
                                    "name": "x", "code": pc, "unit": "szt."}
                     ) as mock_edit,
    ):
        # Send a malicious body trying to inject name/description/id overrides
        client.post(REFRESH_URL + pc, headers=_auth(),
                    json={"name": "ATTACKER NAME",
                          "description": "ATTACKER DESC",
                          "wfirma_product_id": "999"})
    call = mock_edit.call_args
    assert call.kwargs["wfirma_product_id"] == "G-NOOV-1"
    assert "ATTACKER" not in call.kwargs["name"]
    assert "ATTACKER" not in call.kwargs["description"]


def test_refresh_failure_does_not_update_local_mapping(client, db):
    """edit_product raises → status=failed; local row UNCHANGED."""
    pc = "EJL/REF/FAIL"
    _seed_local_mapping(pc, "G-FAIL-1")
    _seed_locked_block(pc)
    before = wfdb.get_product(pc)
    assert before["product_name_pl"] == "Pierścionek"  # baseline name

    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     side_effect=RuntimeError("wFirma 503")),
    ):
        body = client.post(REFRESH_URL + pc, headers=_auth()).json()

    assert body["ok"] is False
    assert body["status"] == "failed"
    assert "RuntimeError" in body["error"]
    after = wfdb.get_product(pc)
    # Local row preserved exactly — same id, same updated_at not bumped is
    # implementation-defined; the field we promise NOT to touch on failure
    # is wfirma_product_id, which must remain mapped.
    assert after["wfirma_product_id"] == before["wfirma_product_id"]


def test_refresh_success_updates_local_product_name_pl(client, db):
    """On success, local product_name_pl is refreshed to new short name_pl."""
    pc = "EJL/REF/UPD"
    # Seed with a stale local name distinct from what description_engine returns
    wfdb.upsert_product(
        product_code      = pc,
        wfirma_product_id = "G-UPD-1",
        product_name_pl   = "STALE_NAME_BEFORE",
        sync_status       = "matched",
    )
    _seed_locked_block(pc, item_type="RING")
    with (
        _gate_edit_on(),
        patch.object(_wc, "edit_product",
                     return_value={"wfirma_id": "G-UPD-1",
                                    "name": "x", "code": pc, "unit": "szt."}),
    ):
        client.post(REFRESH_URL + pc, headers=_auth())
    after = wfdb.get_product(pc)
    # name_pl came from description_engine for RING → "Pierścionek"
    assert after["product_name_pl"] == "Pierścionek"
    assert after["wfirma_product_id"] == "G-UPD-1"

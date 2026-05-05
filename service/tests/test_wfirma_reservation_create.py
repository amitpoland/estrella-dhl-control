"""
test_wfirma_reservation_create.py — Phase 3.A live-create orchestrator + routes.

All tests are mock-only: no real wFirma HTTP calls.
Covers every gate plus happy path, idempotency, race-condition handling,
upstream failure persistence, and the admin reset-stuck endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import wfirma_db as wfdb
from app.services import wfirma_reservation_create as wrc


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wfirma_create_storage")


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


def _full_settings(**overrides):
    base = dict(
        wfirma_access_key="ACC-KEY",
        wfirma_secret_key="SEC-KEY",
        wfirma_app_key="APP-KEY",
        wfirma_company_id="123456",
        wfirma_warehouse_module_enabled=True,
        wfirma_warehouse_id="WH-001",
    )
    base.update(overrides)
    return patch.multiple(settings, **base)


# ── Mock HTTP responses ─────────────────────────────────────────────────────

def _resp(status_code: int, text: str) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


_XML_OK_CONTRACTORS = """<api><contractors><contractor>
  <id>11</id><name>X</name></contractor></contractors>
  <status><code>OK</code></status></api>"""

_XML_OK_GOODS = """<api><goods><good>
  <id>22</id><name>P</name><code>EJL/1</code><unit>szt.</unit>
  <count>5</count><reserved>0</reserved></good></goods>
  <status><code>OK</code></status></api>"""

_XML_OK_WAREHOUSES = """<api><warehouses>
  <warehouse><id>WH-001</id><name>Main</name></warehouse>
  </warehouses><status><code>OK</code></status></api>"""

_XML_OK_VAT = """<api><vat_codes>
  <vat_code><id>222</id><code>23</code></vat_code></vat_codes>
  <status><code>OK</code></status></api>"""

_XML_OK_RESERVATION = """<api><warehouse_documents>
  <warehouse_document><id>987654</id></warehouse_document>
  </warehouse_documents><status><code>OK</code></status></api>"""

_XML_AUTH_FAILED = """<api><status>
  <code>AUTH_FAILED</code><description>Invalid key</description></status></api>"""


def _all_ok(method, url, **kwargs):
    if "contractors/find" in url:    return _resp(200, _XML_OK_CONTRACTORS)
    if "goods/find" in url:          return _resp(200, _XML_OK_GOODS)
    if "warehouses/find" in url:     return _resp(200, _XML_OK_WAREHOUSES)
    if "vat_codes/find" in url:      return _resp(200, _XML_OK_VAT)
    if "warehouse_document_r/add" in url: return _resp(200, _XML_OK_RESERVATION)
    return _resp(404, "<api><status><code>NOT_FOUND</code></status></api>")


# ── Test data setup helpers ──────────────────────────────────────────────────

def _setup_ready_draft(db, batch_id: str, client_name: str,
                      *, with_customer=True, with_product=True, stock_ok=True):
    """Persist a draft + line + customer mapping + product mapping."""
    if with_customer:
        wfdb.upsert_customer(client_name,
                             wfirma_customer_id="CUST-1",
                             match_status="matched")
    if with_product:
        wfdb.upsert_product("EJL/1",
                            wfirma_product_id="PROD-1",
                            product_name_pl="Pierscionek",
                            sync_status="matched")
    draft_id = wfdb.upsert_reservation_draft(
        batch_id, client_name,
        client_ref="REF-1", currency="USD",
        warehouse_id="WH-001", ready_to_create=True,
    )
    wfdb.upsert_reservation_line(
        draft_id, "EJL/1",
        product_name_pl="Pierscionek",
        qty=1.0, unit_price=100.0, currency="USD",
        stock_ok=stock_ok, product_ok=True,
    )
    return draft_id


# ── Gate tests ──────────────────────────────────────────────────────────────

def test_gate_blocks_when_not_ready_to_reserve(db):
    with patch.multiple(
        settings,
        wfirma_access_key=None,
        wfirma_secret_key=None,
        wfirma_company_id="",
        wfirma_warehouse_module_enabled=False,
    ):
        result = wrc.create_one_reservation("B-NOTREADY", "Anyone")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_NOT_READY


def test_gate_blocks_when_diagnostic_unreachable(db):
    """All settings present but live probe returns errors."""
    _setup_ready_draft(db, "B-DIAG", "ClientD")
    def _all_fail(method, url, **kwargs):
        import requests
        raise requests.exceptions.ConnectionError("network down")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_fail):
            result = wrc.create_one_reservation("B-DIAG", "ClientD")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_DIAGNOSTIC_FAILED


def test_gate_blocks_when_draft_not_found(db):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOSUCH", "Phantom")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_DRAFT_NOT_FOUND


def test_gate_blocks_when_draft_not_ready(db):
    wfdb.upsert_customer("ClientNR", wfirma_customer_id="C", match_status="matched")
    wfdb.upsert_reservation_draft("B-NOTREADY2", "ClientNR",
                                  warehouse_id="WH-001", ready_to_create=False)
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOTREADY2", "ClientNR")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_DRAFT_NOT_READY


def test_gate_blocks_when_draft_already_created(db):
    draft_id = _setup_ready_draft(db, "B-CREATED", "ClientC")
    wfdb.mark_draft_submitting(draft_id)
    wfdb.mark_draft_created(draft_id, "EXISTING-WF-ID-123")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-CREATED", "ClientC")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_DRAFT_ALREADY_PROCESSED
    assert result["details"]["wfirma_reservation_id"] == "EXISTING-WF-ID-123"


def test_gate_blocks_when_draft_already_submitting(db):
    draft_id = _setup_ready_draft(db, "B-SUBMITTING", "ClientS")
    wfdb.mark_draft_submitting(draft_id)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-SUBMITTING", "ClientS")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_DRAFT_ALREADY_SUBMITTING


def test_gate_blocks_when_customer_not_mapped(db):
    # Setup draft + line, but NO customer mapping
    draft_id = _setup_ready_draft(db, "B-NOCUST", "Unmapped Client",
                                  with_customer=False)
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOCUST", "Unmapped Client")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_CUSTOMER_NOT_MAPPED


def test_gate_blocks_when_products_not_mapped(db):
    # Customer mapped, but product mapping missing
    wfdb.upsert_customer("ClientNoProd", wfirma_customer_id="C", match_status="matched")
    draft_id = wfdb.upsert_reservation_draft(
        "B-NOPROD", "ClientNoProd",
        warehouse_id="WH-001", ready_to_create=True,
    )
    wfdb.upsert_reservation_line(
        draft_id, "EJL/UNMAPPED",
        qty=1.0, unit_price=100.0, currency="USD",
        stock_ok=True, product_ok=True,
    )
    # No upsert_product call → mapping missing

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOPROD", "ClientNoProd")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_PRODUCTS_NOT_MAPPED
    assert "EJL/UNMAPPED" in result["details"]["unmapped_product_codes"]


def test_gate_blocks_when_stock_not_ok(db):
    _setup_ready_draft(db, "B-NOSTOCK", "ClientNoStock", stock_ok=False)
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOSTOCK", "ClientNoStock")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_STOCK_INSUFFICIENT


def test_gate_blocks_when_warehouse_id_not_in_warehouses(db):
    # Draft persisted with warehouse_id="WH-XX" — the live warehouses
    # mock returns only "WH-001", so this must fail the warehouse gate.
    wfdb.upsert_customer("ClientWH", wfirma_customer_id="C", match_status="matched")
    wfdb.upsert_product("EJL/1", wfirma_product_id="P", sync_status="matched")
    draft_id = wfdb.upsert_reservation_draft(
        "B-WHMISMATCH", "ClientWH",
        warehouse_id="WH-XX",        # ← mismatch
        ready_to_create=True,
    )
    wfdb.upsert_reservation_line(
        draft_id, "EJL/1",
        qty=1.0, unit_price=100.0, currency="USD",
        stock_ok=True, product_ok=True,
    )
    with _full_settings(wfirma_warehouse_id="WH-XX"):
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-WHMISMATCH", "ClientWH")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_WAREHOUSE_NOT_FOUND


def test_gate_blocks_when_no_lines(db):
    wfdb.upsert_customer("ClientNoLines", wfirma_customer_id="C", match_status="matched")
    wfdb.upsert_reservation_draft(
        "B-NOLINES", "ClientNoLines",
        warehouse_id="WH-001", ready_to_create=True,
    )
    # No lines added
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-NOLINES", "ClientNoLines")
    assert result["ok"] is False
    assert result["code"] == wrc.GATE_NO_LINES


# ── Happy path ──────────────────────────────────────────────────────────────

def test_happy_path_creates_reservation(db):
    draft_id = _setup_ready_draft(db, "B-HAPPY", "Happy Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-HAPPY", "Happy Client")
    assert result["ok"] is True
    assert result["code"] == wrc.GATE_OK
    assert result["wfirma_reservation_id"] == "987654"

    # Persistence check
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "created"
    assert draft["wfirma_reservation_id"] == "987654"
    assert draft["last_error"] == ""


def test_happy_path_then_repeat_call_blocks(db):
    """After a successful create, a re-call MUST block as already-processed."""
    draft_id = _setup_ready_draft(db, "B-IDEMP", "Idem Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r1 = wrc.create_one_reservation("B-IDEMP", "Idem Client")
            r2 = wrc.create_one_reservation("B-IDEMP", "Idem Client")
    assert r1["ok"] is True
    assert r2["ok"] is False
    assert r2["code"] == wrc.GATE_DRAFT_ALREADY_PROCESSED


def test_failed_draft_can_retry(db):
    """Draft in status='failed' is eligible for another submission attempt."""
    draft_id = _setup_ready_draft(db, "B-RETRY", "Retry Client")
    wfdb.mark_draft_submitting(draft_id)
    wfdb.mark_draft_failed(draft_id, "first attempt failed")

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-RETRY", "Retry Client")
    assert result["ok"] is True
    assert result["wfirma_reservation_id"] == "987654"


# ── Upstream failure persistence ─────────────────────────────────────────────

def test_upstream_validation_error_persists_failure(db):
    draft_id = _setup_ready_draft(db, "B-UPFAIL", "Up Fail Client")

    def _resv_fails(method, url, **kwargs):
        if "warehouse_document_r/add" in url:
            return _resp(200, """<api><status>
                <code>VALIDATION_ERROR</code>
                <description>price too low</description>
                </status></api>""")
        return _all_ok(method, url, **kwargs)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_resv_fails):
            result = wrc.create_one_reservation("B-UPFAIL", "Up Fail Client")
    assert result["ok"] is False
    assert result["code"] == wrc.SUBMIT_UPSTREAM_ERROR
    assert "VALIDATION_ERROR" in result["error"]

    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "failed"
    assert "VALIDATION_ERROR" in draft["last_error"]


def test_upstream_connection_error_persists_failure(db):
    draft_id = _setup_ready_draft(db, "B-CONNERR", "Conn Err Client")

    def _resv_conn_err(method, url, **kwargs):
        if "warehouse_document_r/add" in url:
            import requests
            raise requests.exceptions.ConnectionError("network")
        return _all_ok(method, url, **kwargs)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_resv_conn_err):
            result = wrc.create_one_reservation("B-CONNERR", "Conn Err Client")
    assert result["ok"] is False
    assert result["code"] == wrc.SUBMIT_UPSTREAM_ERROR

    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "failed"


# ── Endpoint tests ──────────────────────────────────────────────────────────

def test_endpoint_create_happy_path(client, db):
    _setup_ready_draft(db, "B-EP-OK", "EP Happy")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r = client.post(
                "/api/v1/wfirma/reservations/create",
                json={"batch_id": "B-EP-OK", "client_name": "EP Happy"},
                headers=_auth(),
            )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["wfirma_reservation_id"] == "987654"


def test_endpoint_create_gate_failure_returns_409(client, db):
    # Customer mapping missing → 409 GATE_CUSTOMER_NOT_MAPPED
    _setup_ready_draft(db, "B-EP-NOCUST", "EP NoCust", with_customer=False)
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r = client.post(
                "/api/v1/wfirma/reservations/create",
                json={"batch_id": "B-EP-NOCUST", "client_name": "EP NoCust"},
                headers=_auth(),
            )
    assert r.status_code == 409
    assert r.json()["code"] == wrc.GATE_CUSTOMER_NOT_MAPPED


def test_endpoint_create_upstream_error_returns_502(client, db):
    _setup_ready_draft(db, "B-EP-UPFAIL", "EP UpFail")

    def _fails(method, url, **kwargs):
        if "warehouse_document_r/add" in url:
            return _resp(200, _XML_AUTH_FAILED)
        return _all_ok(method, url, **kwargs)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_fails):
            r = client.post(
                "/api/v1/wfirma/reservations/create",
                json={"batch_id": "B-EP-UPFAIL", "client_name": "EP UpFail"},
                headers=_auth(),
            )
    assert r.status_code == 502
    assert r.json()["code"] == wrc.SUBMIT_UPSTREAM_ERROR


def test_endpoint_create_missing_body_returns_422(client, db):
    r = client.post(
        "/api/v1/wfirma/reservations/create",
        json={},
        headers=_auth(),
    )
    assert r.status_code == 422


# ── Reset-stuck endpoint tests ──────────────────────────────────────────────

def test_reset_stuck_not_stuck_returns_409(client, db):
    # Draft in pending — nothing to reset
    draft_id = _setup_ready_draft(db, "B-NOTSTUCK", "Not Stuck")
    r = client.post(
        f"/api/v1/wfirma/reservations/{draft_id}/reset-stuck",
        headers=_auth(),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "NOT_STUCK"


def test_reset_stuck_too_recent_returns_409(client, db):
    draft_id = _setup_ready_draft(db, "B-RECENT", "Recent")
    wfdb.mark_draft_submitting(draft_id)
    # submitted_at is just now → must be too recent
    r = client.post(
        f"/api/v1/wfirma/reservations/{draft_id}/reset-stuck",
        headers=_auth(),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "TOO_RECENT"


def test_reset_stuck_with_force_succeeds(client, db):
    draft_id = _setup_ready_draft(db, "B-FORCE", "Force")
    wfdb.mark_draft_submitting(draft_id)
    r = client.post(
        f"/api/v1/wfirma/reservations/{draft_id}/reset-stuck?force=true",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["details"]["forced"] is True

    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "failed"
    assert "forced" in draft["last_error"]


def test_reset_stuck_after_timeout_succeeds(client, db):
    """If submitted_at is older than threshold, reset works without force."""
    draft_id = _setup_ready_draft(db, "B-TIMEOUT", "Timeout")
    wfdb.mark_draft_submitting(draft_id)
    # Manually backdate submitted_at past the threshold
    old = (datetime.now(timezone.utc) - timedelta(minutes=wrc.STUCK_THRESHOLD_MINUTES + 5)).isoformat()
    import sqlite3
    storage_root = wfdb._db_path
    with sqlite3.connect(str(storage_root)) as con:
        con.execute(
            "UPDATE wfirma_reservation_drafts SET submitted_at=? WHERE id=?",
            (old, draft_id),
        )
        con.commit()

    r = client.post(
        f"/api/v1/wfirma/reservations/{draft_id}/reset-stuck",
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "failed"
    assert "timeout" in draft["last_error"]


def test_reset_stuck_unknown_draft_returns_404(client, db):
    r = client.post(
        "/api/v1/wfirma/reservations/no-such-id/reset-stuck",
        headers=_auth(),
    )
    assert r.status_code == 404


# ── Diagnostic helper unit tests ────────────────────────────────────────────

def test_run_live_diagnostic_all_ok(db):
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            d = wrc._run_live_diagnostic()
    assert d["ok"] is True
    assert d["contractors_ok"] is True
    assert d["goods_ok"] is True
    assert any(w["id"] == "WH-001" for w in d["warehouses"])
    assert d["vat_code_23_id"] == "222"


def test_run_live_diagnostic_partial_failure(db):
    """If goods/find returns AUTH_FAILED, ok must be False."""
    def _goods_fail(method, url, **kwargs):
        if "goods/find" in url:
            return _resp(200, _XML_AUTH_FAILED)
        return _all_ok(method, url, **kwargs)

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_goods_fail):
            d = wrc._run_live_diagnostic()
    assert d["ok"] is False
    assert d["goods_ok"] is False
    assert any("goods" in e for e in d["errors"])

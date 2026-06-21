"""
test_wfirma_reservation_operator_attribution.py — operator attribution on the
live wFirma reservation create (warehouse_document_r).

A completed reservation is an accounting-adjacent live write; it must carry a
durable record of WHO triggered it. These tests pin that contract end to end:

  - the DB migration adds a submitted_by column
  - mark_draft_submitting persists submitted_by at submit-time
  - create_one_reservation records the operator on the draft + the result, and
    resolves a blank operator to a clear sentinel (never an empty attribution)
  - the failed/retry paths preserve / refresh the attribution correctly
  - the route forwards the X-Operator header (blank → sentinel)
  - the execution-engine automation path forwards its operator too

All tests are mock-only: no real wFirma HTTP calls.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import wfirma_db as wfdb
from app.services import wfirma_reservation_create as wrc


# ── Fixtures (mirror test_wfirma_reservation_create.py) ──────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wfirma_op_attr_storage")


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


@pytest.fixture(autouse=True)
def _reset_wfirma_circuit():
    """Force the shared wFirma circuit breaker CLOSED around every test.

    The breaker is a process-global singleton in app.core.circuit_breaker and
    is NOT reset by conftest (which only resets the ai_gateway breakers). A
    sibling test that exercises an unreachable-wFirma path (e.g.
    test_wfirma_reservation_create.py::test_gate_blocks_when_diagnostic_unreachable,
    which sorts before this file) can leave it OPEN for its 60s recovery window
    and poison these happy-path tests with a spurious DIAGNOSTIC_FAILED. The
    reset keeps this file order-independent. See the file-level note about the
    pre-existing conftest gap.
    """
    from app.core.circuit_breaker import reset_all
    reset_all()
    yield
    reset_all()


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


# ── Mock HTTP responses ──────────────────────────────────────────────────────

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

_XML_VALIDATION_ERROR = """<api><status>
  <code>VALIDATION_ERROR</code><description>price too low</description>
  </status></api>"""


def _all_ok(method, url, **kwargs):
    if "contractors/find" in url:         return _resp(200, _XML_OK_CONTRACTORS)
    if "goods/find" in url:               return _resp(200, _XML_OK_GOODS)
    if "warehouses/find" in url:          return _resp(200, _XML_OK_WAREHOUSES)
    if "vat_codes/find" in url:           return _resp(200, _XML_OK_VAT)
    if "warehouse_document_r/add" in url: return _resp(200, _XML_OK_RESERVATION)
    return _resp(404, "<api><status><code>NOT_FOUND</code></status></api>")


def _resv_validation_fails(method, url, **kwargs):
    if "warehouse_document_r/add" in url:
        return _resp(200, _XML_VALIDATION_ERROR)
    return _all_ok(method, url, **kwargs)


# ── Setup helper ──────────────────────────────────────────────────────────────

def _setup_ready_draft(batch_id: str, client_name: str) -> str:
    wfdb.upsert_customer(client_name, wfirma_customer_id="CUST-1",
                         match_status="matched")
    wfdb.upsert_product("EJL/1", wfirma_product_id="PROD-1",
                        product_name_pl="Pierscionek", sync_status="matched")
    draft_id = wfdb.upsert_reservation_draft(
        batch_id, client_name,
        client_ref="REF-1", currency="USD",
        warehouse_id="WH-001", ready_to_create=True,
    )
    wfdb.upsert_reservation_line(
        draft_id, "EJL/1", product_name_pl="Pierscionek",
        qty=1.0, unit_price=100.0, currency="USD",
        stock_ok=True, product_ok=True,
    )
    return draft_id


# ── Migration ─────────────────────────────────────────────────────────────────

def test_submitted_by_column_exists(db):
    with sqlite3.connect(str(wfdb._db_path)) as con:
        cols = {r[1] for r in con.execute(
            "PRAGMA table_info(wfirma_reservation_drafts)").fetchall()}
    assert "submitted_by" in cols


# ── DB helper ─────────────────────────────────────────────────────────────────

def test_mark_draft_submitting_persists_submitted_by(db):
    draft_id = _setup_ready_draft("B-OP-DB", "Op DB Client")
    assert wfdb.mark_draft_submitting(draft_id, submitted_by="frank@estrella") is True
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "submitting"
    assert draft["submitted_by"] == "frank@estrella"


def test_mark_draft_submitting_without_operator_writes_empty(db):
    """Backward-compatible: the legacy no-arg call still works (writes '')."""
    draft_id = _setup_ready_draft("B-OP-DB-EMPTY", "Op DB Empty Client")
    assert wfdb.mark_draft_submitting(draft_id) is True
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["submitted_by"] == ""


# ── Service: happy path captures operator ────────────────────────────────────

def test_service_captures_operator_on_submitted_by(db):
    draft_id = _setup_ready_draft("B-OP-SVC", "Op Svc Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation(
                "B-OP-SVC", "Op Svc Client", operator="alice@estrella")
    assert result["ok"] is True
    assert result["submitted_by"] == "alice@estrella"
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "created"
    assert draft["submitted_by"] == "alice@estrella"


# ── Service: blank / missing operator → sentinel (never empty attribution) ────

def test_blank_operator_resolves_to_sentinel(db):
    draft_id = _setup_ready_draft("B-OP-BLANK", "Op Blank Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation(
                "B-OP-BLANK", "Op Blank Client", operator="   ")
    assert result["ok"] is True
    assert result["submitted_by"] == wrc.UNKNOWN_OPERATOR
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["submitted_by"] == wrc.UNKNOWN_OPERATOR


def test_default_no_operator_resolves_to_sentinel(db):
    """The execution_engine legacy call shape (no operator) must not break and
    must still attribute via the sentinel rather than an empty string."""
    draft_id = _setup_ready_draft("B-OP-DEF", "Op Default Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            result = wrc.create_one_reservation("B-OP-DEF", "Op Default Client")
    assert result["ok"] is True
    assert result["submitted_by"] == wrc.UNKNOWN_OPERATOR
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["submitted_by"] == wrc.UNKNOWN_OPERATOR


# ── Service: failure path still records the triggering operator ──────────────

def test_failure_path_still_records_operator(db):
    draft_id = _setup_ready_draft("B-OP-FAIL", "Op Fail Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   side_effect=_resv_validation_fails):
            result = wrc.create_one_reservation(
                "B-OP-FAIL", "Op Fail Client", operator="bob@estrella")
    assert result["ok"] is False
    assert result["code"] == wrc.SUBMIT_UPSTREAM_ERROR
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "failed"
    # submitted_by was written at submit-time and preserved through the failure
    assert draft["submitted_by"] == "bob@estrella"


def test_retry_refreshes_operator_attribution(db):
    """A failed draft retried by a DIFFERENT operator records the new one."""
    draft_id = _setup_ready_draft("B-OP-RETRY", "Op Retry Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request",
                   side_effect=_resv_validation_fails):
            r1 = wrc.create_one_reservation(
                "B-OP-RETRY", "Op Retry Client", operator="dave@estrella")
    assert r1["ok"] is False
    assert wfdb.get_reservation_draft_by_id(draft_id)["submitted_by"] == "dave@estrella"

    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r2 = wrc.create_one_reservation(
                "B-OP-RETRY", "Op Retry Client", operator="erin@estrella")
    assert r2["ok"] is True
    draft = wfdb.get_reservation_draft_by_id(draft_id)
    assert draft["status"] == "created"
    assert draft["submitted_by"] == "erin@estrella"


# ── Route: X-Operator header is forwarded to submitted_by ────────────────────

def test_endpoint_forwards_x_operator_to_submitted_by(client, db):
    _setup_ready_draft("B-OP-EP", "Op EP Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r = client.post(
                "/api/v1/wfirma/reservations/create",
                json={"batch_id": "B-OP-EP", "client_name": "Op EP Client"},
                headers={**_auth(), "X-Operator": "carol@estrella"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["submitted_by"] == "carol@estrella"
    draft = wfdb.get_reservation_draft("B-OP-EP", "Op EP Client")
    assert draft["submitted_by"] == "carol@estrella"


def test_endpoint_blank_header_records_sentinel(client, db):
    _setup_ready_draft("B-OP-EP-NOHDR", "Op NoHdr Client")
    with _full_settings():
        with patch("app.services.wfirma_client._requests.request", side_effect=_all_ok):
            r = client.post(
                "/api/v1/wfirma/reservations/create",
                json={"batch_id": "B-OP-EP-NOHDR", "client_name": "Op NoHdr Client"},
                headers=_auth(),  # no X-Operator
            )
    assert r.status_code == 200
    assert r.json()["submitted_by"] == wrc.UNKNOWN_OPERATOR
    draft = wfdb.get_reservation_draft("B-OP-EP-NOHDR", "Op NoHdr Client")
    assert draft["submitted_by"] == wrc.UNKNOWN_OPERATOR


# ── Automation path: execution_engine forwards its operator ──────────────────

def test_execution_engine_call_forwards_operator():
    """_call_wfirma_create must thread the operator into create_one_reservation."""
    from app.services import execution_engine as ee
    captured = {}

    def _fake_create(batch_id, client_name, *, operator=""):
        captured["batch_id"] = batch_id
        captured["operator"] = operator
        return {"ok": True}

    with patch("app.services.wfirma_reservation_create.create_one_reservation",
               _fake_create):
        ee._call_wfirma_create("B-X", "Client X", operator="grace@estrella")
    assert captured["operator"] == "grace@estrella"
    assert captured["batch_id"] == "B-X"

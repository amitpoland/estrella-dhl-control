"""
test_audit_proforma_converted.py — `record_proforma_converted_to_invoice`
helper + execute-route audit emit.

Pins:
  1. helper appends a single ``proforma_converted_to_invoice`` event
  2. helper is idempotent on (batch_id, wfirma_proforma_id, wfirma_invoice_id)
  3. helper does NOT modify proforma_issued[] / proforma_cancelled[] arrays
  4. execute route emits the event after a successful conversion
  5. execute route does NOT emit when wFirma create fails
  6. execute route does NOT emit when settings flag is off
  7. execute route does NOT emit when the link already exists (duplicate
     conversion blocked at gate 5)
  8. execute route does NOT emit when confirm token is wrong
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as wc
from app.services import packing_db    as pdb
from app.services import warehouse_db  as wdb
from app.services import document_db   as ddb
from app.services import wfirma_db     as wfdb
from app.services import proforma_invoice_link_db as pildb
from app.services import proforma_invoice_link_db as plink
from app.services import proforma_service_charges_db as scdb
from app.services.audit_persist import (
    EV_PROFORMA_CONVERTED_TO_INVOICE,
    record_proforma_converted_to_invoice,
)


_BATCH   = "BATCH_AUDIT_CONVERT"
_CLIENT  = "ACME"
_CONFIRM = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prime_vat():
    wc._VAT_CODE_ID_CACHE["23"]  = "222"
    wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    yield


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    plink.init_db(tmp_path / "proforma_links.db")
    (tmp_path / "outputs" / _BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _gate_invoice_on():
    return patch.object(settings, "wfirma_create_invoice_allowed", True)


def _seed_audit(storage, *, with_issued=True) -> Path:
    p = storage / "outputs" / _BATCH / "audit.json"
    audit = {
        "status":   "partial",
        "wfirma_export": {"wfirma_pz_doc_id": "X"},
        "timeline": [],
    }
    if with_issued:
        # Pre-seed the canonical proforma_issued list (the conversion
        # helper must NOT touch it).
        audit["proforma_issued"] = [{
            "client_name": _CLIENT,
            "wfirma_proforma_id": "467236963",
            "line_count": 1,
            "currency": "EUR",
        }]
        audit["proforma_cancelled"] = []
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _seed_issued_proforma(storage, *, wfirma_id="467236963"):
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=_BATCH, client_name=_CLIENT,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, _BATCH, _CLIENT,
                              wfirma_proforma_id=wfirma_id)


def _proforma_xml(*, pid="467236963", pnum="PROF 92/2026") -> str:
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>{pid}</id>
      <type>proforma</type>
      <fullnumber>{pnum}</fullnumber>
      <date>2026-05-08</date>
      <paymentmethod>transfer</paymentmethod>
      <paymentdate>2026-05-15</paymentdate>
      <currency>EUR</currency>
      <contractor><id>9001</id></contractor>
      <series><id>15827088</id></series>
      <total>306.00</total>
      <netto>306.00</netto>
      <description>Source proforma</description>
      <invoicecontents>
        <invoicecontent>
          <name>RING</name><good><id>42</id></good>
          <unit>szt.</unit><unit_count>1.0000</unit_count>
          <price>306.00</price><vat_code><id>228</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_INVOICE_OK = """<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>500001</id>
      <fullnumber>FA 1/5/2026</fullnumber>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_INVOICE_ERROR = ('<api><status><code>ERROR</code>'
                  '<description>wFirma said no</description></status></api>')


_PREVIEW_URL = "/api/v1/proforma/to-invoice-preview/{b}/{c}"
_EXECUTE_URL = "/api/v1/proforma/to-invoice/{b}/{c}"


# ── 1. Helper appends one event ────────────────────────────────────────────

def test_helper_appends_one_event(storage):
    audit_path = _seed_audit(storage)
    r = record_proforma_converted_to_invoice(
        audit_path,
        batch_id           = _BATCH,
        client_name        = _CLIENT,
        wfirma_proforma_id = "467236963",
        wfirma_invoice_id  = "500001",
        invoice_number     = "FA 1/5/2026",
        operator           = "amit",
        source             = "manual_convert_button",
    )
    assert r["appended"]            is True
    assert r["wfirma_invoice_id"]   == "500001"
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["batch_id"]            == _BATCH
    assert detail["client_name"]         == _CLIENT
    assert detail["wfirma_proforma_id"]  == "467236963"
    assert detail["wfirma_invoice_id"]   == "500001"
    assert detail["invoice_number"]      == "FA 1/5/2026"
    assert detail["operator"]            == "amit"
    assert detail["source"]              == "manual_convert_button"


# ── 2. Helper idempotent on triple ─────────────────────────────────────────

def test_helper_idempotent(storage):
    audit_path = _seed_audit(storage)
    record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="I1",
        invoice_number="FA-1")
    second = record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="I1",
        invoice_number="FA-1")
    assert second["appended"] is False
    assert second["reason"]   == "already recorded"
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
    assert len(events) == 1


def test_helper_distinguishes_different_invoices(storage):
    """Re-converting a proforma that was rolled back and reissued — same
    proforma id, NEW invoice id — produces a new event row."""
    audit_path = _seed_audit(storage)
    record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="I1",
        invoice_number="FA-1")
    record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="I2",
        invoice_number="FA-2")
    a = json.loads(audit_path.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
    assert len(events) == 2


def test_helper_rejects_empty_proforma_id(storage):
    audit_path = _seed_audit(storage)
    r = record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="", wfirma_invoice_id="I1",
        invoice_number="FA-1")
    assert r["appended"] is False
    assert "wfirma_proforma_id is empty" in r["reason"]


def test_helper_rejects_empty_invoice_id(storage):
    audit_path = _seed_audit(storage)
    r = record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="",
        invoice_number="FA-1")
    assert r["appended"] is False
    assert "wfirma_invoice_id is empty" in r["reason"]


def test_helper_handles_missing_audit():
    r = record_proforma_converted_to_invoice(
        Path("/nonexistent/audit.json"),
        batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="P1", wfirma_invoice_id="I1",
        invoice_number="FA-1")
    assert r["appended"] is False
    assert "missing" in r["reason"]


# ── 3. Helper does NOT touch proforma_issued/proforma_cancelled arrays ──────

def test_helper_does_not_touch_proforma_issued_or_cancelled(storage):
    audit_path = _seed_audit(storage, with_issued=True)
    before = json.loads(audit_path.read_text())
    record_proforma_converted_to_invoice(
        audit_path, batch_id=_BATCH, client_name=_CLIENT,
        wfirma_proforma_id="467236963", wfirma_invoice_id="500001",
        invoice_number="FA 1/5/2026")
    after = json.loads(audit_path.read_text())
    assert before.get("proforma_issued")     == after.get("proforma_issued")
    assert before.get("proforma_cancelled")  == after.get("proforma_cancelled")


# ── 4. Execute route emits event on success ────────────────────────────────

def test_execute_emits_event_on_success(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    def _fake_http(method, module, op, body):
        return 200, _INVOICE_OK
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request", side_effect=_fake_http):
        r = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": _CONFIRM})
    body = r.json()
    assert body["ok"]     is True
    assert body["status"] == "issued"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["wfirma_proforma_id"] == "467236963"
    assert detail["wfirma_invoice_id"]  == "500001"
    assert detail["invoice_number"]     == "FA 1/5/2026"
    assert detail["operator"]           == "amit"
    assert detail["source"]             == "manual_convert_button"


# ── 5. Execute does NOT emit when wFirma create fails ──────────────────────

def test_execute_does_not_emit_when_wfirma_rejects(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    def _fail(method, module, op, body):
        return 200, _INVOICE_ERROR
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request", side_effect=_fail):
        body = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": _CONFIRM}).json()
    assert body["status"] == "failed"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE]
    assert events == []


def test_execute_does_not_emit_on_network_failure(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request",
                      side_effect=ConnectionError("net down")):
        body = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": _CONFIRM}).json()
    assert body["status"] == "failed"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    assert [e for e in a["timeline"]
            if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE] == []


# ── 6. Execute does NOT emit when flag is off ──────────────────────────────

def test_execute_does_not_emit_when_flag_off(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    with patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": _CONFIRM}).json()
    assert body["status"] == "blocked"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    assert [e for e in a["timeline"]
            if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE] == []


# ── 7. Execute does NOT emit when link already exists ──────────────────────

def test_execute_does_not_emit_when_link_already_exists(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    plink.create_pending_link(
        storage / "proforma_links.db",
        plink.ProformaInvoiceLink(
            proforma_id     = "467236963",
            proforma_number = "PROF 92/2026",
            converted_at    = "2026-05-08T00:00:00+00:00",
            operator        = "amit",
            source_total    = Decimal("306.00"),
            currency        = "EUR",
            status          = "pending",
        ),
    )
    with _gate_invoice_on(), \
         patch.object(wc, "fetch_invoice_xml",
                      side_effect=AssertionError("must not fetch")), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": _CONFIRM}).json()
    assert body["status"] == "blocked"
    assert any("already has a conversion link" in r
               for r in body["blocking_reasons"])
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    assert [e for e in a["timeline"]
            if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE] == []


# ── 8. Execute does NOT emit when confirm token wrong ──────────────────────

def test_execute_does_not_emit_with_wrong_confirm(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    with _gate_invoice_on(), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError("must not call wFirma")):
        body = client.post(
            _EXECUTE_URL.format(b=_BATCH, c=_CLIENT),
            headers={**_auth(), "X-Operator": "amit"},
            json={"confirm": "TYPO"}).json()
    assert body["status"] == "blocked"
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    assert [e for e in a["timeline"]
            if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE] == []


# ── Preview path NEVER emits (read-only) ──────────────────────────────────

def test_preview_does_not_emit(client, storage):
    _seed_audit(storage)
    _seed_issued_proforma(storage)
    with patch.object(wc, "fetch_invoice_xml",
                      return_value=_proforma_xml()), \
         patch.object(wc, "_http_request",
                      side_effect=AssertionError(
                          "preview must not call wFirma create")):
        client.get(
            _PREVIEW_URL.format(b=_BATCH, c=_CLIENT),
            headers=_auth())
    a = json.loads((storage / "outputs" / _BATCH / "audit.json").read_text())
    assert [e for e in a["timeline"]
            if e.get("event") == EV_PROFORMA_CONVERTED_TO_INVOICE] == []

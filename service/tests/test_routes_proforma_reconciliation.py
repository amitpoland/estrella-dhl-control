"""test_routes_proforma_reconciliation.py — Campaign-2 A2 Step 2.

Pins the read-only GET /api/v1/proforma/draft/{id}/reconciliation endpoint:
flag gating, deterministic domain-outcome mapping, single service delegation,
no reshaping of the service view-model, read-only (no writes), schema stability.
"""
from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import document_reconciler as drec
from app.api import routes_proforma as rp
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


_URL = "/api/v1/proforma/draft/{}/reconciliation"

_RECONCILED = {
    "status": "reconciled", "reconciliation_available": True, "draft_id": 1,
    "clean": True, "comparison_version": "a2-1", "local_source_hash": "SRC",
    "remote_document_id": "500001", "remote_snapshot_hash": "REM",
    "resolved_at": "T", "compared_at": "T", "gaps": [], "gap_summary": {
        "total": 0, "by_severity": {}, "by_policy": {}, "has_blocking": False}}

_MISMATCH = {**_RECONCILED, "clean": False,
             "gaps": [{"field": "contractor_id", "expected": "9001",
                       "actual": "9999", "authority": "IMPORT_PZ/PROFORMA",
                       "severity": "critical", "resolution_policy": "blocked",
                       "evidence_quality": "exact_remote_snapshot",
                       "message": "verify-after-create: contractor mismatch — expected='9001' got='9999'"}],
             "gap_summary": {"total": 1, "by_severity": {"critical": 1},
                             "by_policy": {"blocked": 1}, "has_blocking": True}}

_NO_LOCAL = {"status": "no_local_authority", "reconciliation_available": False,
             "draft_id": 1, "comparison_version": "a2-1", "gaps": [],
             "gap_summary": {"total": 0, "by_severity": {}, "by_policy": {},
                             "has_blocking": False}}


def _enable(mp, *, draft=SimpleNamespace(wfirma_invoice_id="500001",
                                         wfirma_proforma_id="p", id=1)):
    mp.setattr(settings, "document_reconciliation_report_enabled", True)
    mp.setattr(pildb, "get_draft_by_id", lambda db, i: draft)


# ── flag gating ───────────────────────────────────────────────────────────────

def test_flag_disabled_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "document_reconciliation_report_enabled", False)
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()


# ── outcome mapping (spy on the sole service authority) ──────────────────────

def test_exact_match_200_clean(client, monkeypatch):
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(drec, "build_reconciliation",
                        lambda i, **k: calls.append(i) or _RECONCILED)
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 200
    assert r.json() == _RECONCILED           # view-model NOT reshaped
    assert calls == [1]                       # service called exactly once


def test_mismatch_200_with_gaps(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(drec, "build_reconciliation", lambda i, **k: _MISMATCH)
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["clean"] is False
    assert body["gaps"][0]["field"] == "contractor_id"
    assert body["gap_summary"]["has_blocking"] is True


def test_no_local_authority_200(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(drec, "build_reconciliation", lambda i, **k: _NO_LOCAL)
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "no_local_authority"
    assert r.json()["reconciliation_available"] is False


def test_draft_not_found_404(client, monkeypatch):
    monkeypatch.setattr(settings, "document_reconciliation_report_enabled", True)
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: None)
    called = []
    monkeypatch.setattr(drec, "build_reconciliation",
                        lambda i, **k: called.append(i))
    r = client.get(_URL.format(999), headers=_auth())
    assert r.status_code == 404
    assert called == []                       # service not invoked when absent


def test_remote_invoice_unavailable_502(client, monkeypatch):
    _enable(monkeypatch)
    def _raise(i, **k):
        raise RuntimeError("invoices/get wFirma status=404: not found")
    monkeypatch.setattr(drec, "build_reconciliation", _raise)
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 502
    assert "unavailable" in r.json()["detail"].lower()


def test_connectionerror_maps_502(client, monkeypatch):
    _enable(monkeypatch)
    def _raise(i, **k):
        raise ConnectionError("wFirma unreachable")
    monkeypatch.setattr(drec, "build_reconciliation", _raise)
    assert client.get(_URL.format(1), headers=_auth()).status_code == 502


# ── read-only / idempotency / schema ─────────────────────────────────────────

def test_two_identical_gets_identical_no_side_effect(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(drec, "build_reconciliation", lambda i, **k: _RECONCILED)
    a = client.get(_URL.format(1), headers=_auth()).json()
    b = client.get(_URL.format(1), headers=_auth()).json()
    assert a == b


def test_route_source_is_read_only():
    """Static write-guard: the endpoint body has no write/IO tokens and only
    delegates. No broad `except Exception`."""
    src = inspect.getsource(rp.get_draft_reconciliation)
    for tok in ("INSERT", "UPDATE ", ".execute(", ".commit(", "_http_request",
                "invoices/add", "log_event", "mark_", "write_json", ".write(",
                "except Exception"):
        assert tok not in src, f"route contains forbidden token: {tok}"
    assert "build_reconciliation" in src   # delegates to the sole authority


def test_preview_html_sets_no_store():
    """A2 surfaces the local EJ preview via the 'View EJ source' action; that
    render changes on every draft edit, so it must carry Lesson-G no-store."""
    src = inspect.getsource(rp.get_proforma_draft_preview_html)
    assert "Cache-Control" in src and "no-store" in src, (
        "preview.html (local EJ render) must send Cache-Control: no-store (Lesson G)"
    )


def test_response_schema_stable_reconciled(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(drec, "build_reconciliation", lambda i, **k: _RECONCILED)
    body = client.get(_URL.format(1), headers=_auth()).json()
    assert set(body) == set(_RECONCILED)


# ── end-to-end: route → REAL build_reconciliation → REAL compare_invoice_plan ─

def _plan(contractor_id="9001"):
    return FinalInvoicePlan(
        type="normal", contractor_id=contractor_id, currency="EUR",
        price_currency_exchange=None, paymentmethod="przelew", paymentdate="d",
        date="d", description="x", series_id="s", company_account_id="a",
        translation_language_id=None, contractor_receiver_id=None,
        contents=[LineItem("RING", "42", "szt.", "1.0000", "306.00", "228")],
        source_proforma_id="1", source_proforma_number="P/1",
        expected_total=Decimal("306.00"))


def _xml(contractor_id="9999"):
    return ("<api><invoices><invoice><id>500001</id><type>normal</type>"
            "<currency>EUR</currency><total>306.00</total>"
            f"<contractor><id>{contractor_id}</id></contractor>"
            "<invoicecontents><invoicecontent><name>RING</name>"
            "<good><id>42</id></good><unit>szt.</unit><unit_count>1.0000</unit_count>"
            "<price>306.00</price><vat_code><id>228</id></vat_code>"
            "</invoicecontent></invoicecontents></invoice></invoices></api>")


def test_end_to_end_real_service_and_comparator(client, monkeypatch):
    draft = SimpleNamespace(wfirma_invoice_id="500001", wfirma_proforma_id="p", id=1)
    monkeypatch.setattr(settings, "document_reconciliation_report_enabled", True)
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: draft)
    # inject the reconciler's read-only indirections (no real wFirma/DB)
    monkeypatch.setattr(drec, "_build_expected_plan", lambda d: (_plan(), "SRCHASH"))
    monkeypatch.setattr(drec, "_fetch_actual_xml", lambda iid: _xml("9999"))
    r = client.get(_URL.format(1), headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reconciled" and body["clean"] is False
    assert body["gaps"][0]["field"] == "contractor_id"
    assert body["local_source_hash"] == "SRCHASH"

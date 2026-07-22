"""test_routes_2b_manual_link.py — Campaign-2 · Phase 2B (API).

Pins the resolve (read-only) + confirm (privileged, flag-gated) manual-link
endpoints: authz, input validation, flag gate, confirm-time drift refusal,
conflict/idempotency policy, one-audit-event, no-remote-write, and no internal
id / hash leakage. The service preview + persistence are injected — no real
wFirma or DB write.

Auth note: require_api_key permits unauthenticated access when settings.api_key
is empty outside production. Tests that assert auth ENFORCEMENT set a non-empty
api_key explicitly so the missing credential actually rejects.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import document_reconciler as drec
from app.api import routes_proforma as rp


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _authop():
    return {**_auth(), "X-Operator": "tester"}


@pytest.fixture()
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


_RESOLVE = "/api/v1/proforma/draft/{}/resolve-wfirma-document"
_CONFIRM = "/api/v1/proforma/draft/{}/confirm-wfirma-link"

_PREVIEW = {
    "status": "preview_available", "reconciliation_available": True,
    "draft_id": 1, "document_type": "invoice", "clean": True,
    "comparison_version": "2b-1", "local_source_hash": "SRC",
    "remote_snapshot_hash": "REM", "preview_hash": "HASH-OK",
    "resolved_at": "T", "compared_at": "T",
    "candidate_summary": {"currency": "EUR", "expected_total": "306.00", "line_count": 1},
    "gaps": [], "gap_summary": {"total": 0, "by_severity": {}, "by_policy": {}, "has_blocking": False},
}


def _draft(*, proforma_id="p1", invoice_id=None, state="posted"):
    return SimpleNamespace(id=1, wfirma_proforma_id=proforma_id,
                           wfirma_invoice_id=invoice_id, draft_state=state,
                           batch_id="B1", client_name="ACME")


def _preview_ok(monkeypatch, preview=None):
    monkeypatch.setattr(drec, "build_manual_link_preview",
                        lambda i, **k: dict(preview or _PREVIEW))


def _guard_no_remote_write(monkeypatch):
    """Fail loudly if any wFirma write primitive is invoked during a request."""
    for name in ("create_invoice", "add_invoice", "invoices_add", "update_invoice",
                 "edit_invoice", "delete_invoice"):
        if hasattr(rp.wfirma_client, name):
            monkeypatch.setattr(rp.wfirma_client, name,
                                lambda *a, **k: (_ for _ in ()).throw(
                                    AssertionError(f"remote wFirma write {name} called")))


# ══ resolve (read-only) ═══════════════════════════════════════════════════════

def test_resolve_by_id_success(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    _preview_ok(monkeypatch)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "500001"})
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["status"] == "preview_available"
    assert b["gap_summary"]["total"] == 0


def test_resolve_by_number_success(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    monkeypatch.setattr(rp.wfirma_client, "find_invoices_by_fullnumber",
                        lambda n: [{"id": "500001", "fullnumber": "FV 12/2026"}])
    _preview_ok(monkeypatch)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "full_number": "FV 12/2026"})
    assert r.status_code == 200
    assert r.json()["remote_fullnumber"] == "FV 12/2026"


def test_resolve_number_not_found_404(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    monkeypatch.setattr(rp.wfirma_client, "find_invoices_by_fullnumber", lambda n: [])
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "full_number": "NOPE"})
    assert r.status_code == 404


def test_resolve_number_ambiguous_409(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    monkeypatch.setattr(rp.wfirma_client, "find_invoices_by_fullnumber",
                        lambda n: [{"id": "1", "fullnumber": "x"}, {"id": "2", "fullnumber": "x"}])
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "full_number": "x"})
    assert r.status_code == 409


def test_resolve_both_ids_422(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "1", "full_number": "x"})
    assert r.status_code == 422


def test_resolve_neither_id_422(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice"})
    assert r.status_code == 422


def test_resolve_nonnumeric_id_422(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "5/../x"})
    assert r.status_code == 422


def test_resolve_bad_doc_type_422(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "proforma", "wfirma_id": "1"})
    assert r.status_code == 422


def test_resolve_draft_missing_404(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: None)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "1"})
    assert r.status_code == 404


def test_resolve_draft_no_proforma_422(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft(proforma_id=None))
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "1"})
    assert r.status_code == 422


def test_resolve_upstream_failure_502(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    def _boom(i, **k):
        raise RuntimeError("wfirma down")
    monkeypatch.setattr(drec, "build_manual_link_preview", _boom)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "1"})
    assert r.status_code == 502


def test_resolve_response_has_no_internal_ids_or_xml(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    _preview_ok(monkeypatch)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "500001"})
    body = r.text
    for banned in ("series_id", "company_account_id", "contractor_id",
                   "contractor_receiver_id", "good_id", "remote_document_id",
                   "<invoice", "<api>"):
        assert banned not in body


def test_resolve_no_remote_mutation(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    _preview_ok(monkeypatch)
    _guard_no_remote_write(monkeypatch)
    r = client.post(_RESOLVE.format(1), headers=_auth(),
                    json={"document_type": "invoice", "wfirma_id": "500001"})
    assert r.status_code == 200


def test_resolve_writes_nothing(client, monkeypatch):
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    _preview_ok(monkeypatch)
    calls = []
    monkeypatch.setattr(pildb, "_record_draft_event", lambda *a, **k: calls.append(1))
    client.post(_RESOLVE.format(1), headers=_auth(),
                json={"document_type": "invoice", "wfirma_id": "500001"})
    assert calls == []          # no audit-on-read


def test_resolve_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "enforce-key")   # force auth ON
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: _draft())
    r = client.post(_RESOLVE.format(1),
                    json={"document_type": "invoice", "wfirma_id": "1"})
    assert r.status_code in (401, 403)


# ══ confirm (privileged, flag-gated, write) ═══════════════════════════════════

def _enable_confirm(monkeypatch, *, draft=None, preview=None, link=None):
    monkeypatch.setattr(settings, "wfirma_manual_document_link_enabled", True)
    monkeypatch.setattr(pildb, "get_draft_by_id", lambda db, i: draft or _draft())
    monkeypatch.setattr(pildb, "get_link_by_invoice", lambda db, iid: link)
    _preview_ok(monkeypatch, preview)


def test_confirm_flag_off_503(client, monkeypatch):
    monkeypatch.setattr(settings, "wfirma_manual_document_link_enabled", False)
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 503


def test_confirm_requires_api_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "enforce-key")   # force auth ON
    _enable_confirm(monkeypatch)
    r = client.post(_CONFIRM.format(1), headers={"X-Operator": "tester"},   # no key
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code in (401, 403)


def test_confirm_operator_required_400(client, monkeypatch):
    _enable_confirm(monkeypatch)
    r = client.post(_CONFIRM.format(1), headers=_auth(),          # no X-Operator
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 400
    assert r.json()["status"] == "blocked"


def test_confirm_missing_hash_422(client, monkeypatch):
    _enable_confirm(monkeypatch)
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "1"})
    assert r.status_code == 422


def test_confirm_missing_proforma_refused(client, monkeypatch):
    _enable_confirm(monkeypatch, draft=_draft(proforma_id=None))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 422


def test_confirm_editable_state_blocked_409(client, monkeypatch):
    _enable_confirm(monkeypatch, draft=_draft(state="editing"))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 409
    assert r.json()["status"] == "blocked"


def test_confirm_hash_match_succeeds(client, monkeypatch):
    _enable_confirm(monkeypatch)
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: None)
    monkeypatch.setattr(pildb, "_record_draft_event", lambda *a, **k: 1)
    monkeypatch.setattr("app.services.audit_persist.record_wfirma_document_manually_linked",
                        lambda *a, **k: {"appended": True})
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 200 and r.json()["status"] == "linked"


def test_confirm_hash_drift_409(client, monkeypatch):
    _enable_confirm(monkeypatch)
    persisted = []
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: persisted.append(k))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "1",
                          "expected_preview_hash": "STALE"})   # != HASH-OK
    assert r.status_code == 409
    assert r.json()["status"] == "drift"
    assert persisted == []          # no write on drift


def test_confirm_conflict_different_id_409(client, monkeypatch):
    _enable_confirm(monkeypatch, draft=_draft(invoice_id="999999"))
    persisted = []
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: persisted.append(k))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 409
    assert r.json()["status"] == "conflict"
    assert persisted == []


def test_confirm_conflict_issued_link_elsewhere_409(client, monkeypatch):
    _enable_confirm(monkeypatch, link=SimpleNamespace(status="issued"))
    persisted = []
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: persisted.append(k))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 409
    assert persisted == []


def test_confirm_noop_same_id_no_event(client, monkeypatch):
    _enable_confirm(monkeypatch, draft=_draft(invoice_id="500001"))
    persisted, events = [], []
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: persisted.append(k))
    monkeypatch.setattr(pildb, "_record_draft_event", lambda *a, **k: events.append(k))
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 200 and r.json()["status"] == "noop"
    assert persisted == [] and events == []     # idempotent: no write, no duplicate event


def test_confirm_success_persists_once_audits_once(client, monkeypatch):
    _enable_confirm(monkeypatch)
    persisted, events = [], []
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: persisted.append(k))
    monkeypatch.setattr(pildb, "_record_draft_event",
                        lambda *a, **k: events.append(k) or 1)
    monkeypatch.setattr("app.services.audit_persist.record_wfirma_document_manually_linked",
                        lambda *a, **k: {"appended": True})
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 200 and r.json()["status"] == "linked"
    assert len(persisted) == 1 and persisted[0]["wfirma_invoice_id"] == "500001"
    assert len(events) == 1                    # exactly one audit event
    assert events[0]["event"] == "wfirma_document_manually_linked"
    import json as _j
    assert _j.loads(events[0]["detail_json"])["wfirma_write"] is False


def test_confirm_persist_failure_no_success_event(client, monkeypatch):
    _enable_confirm(monkeypatch)
    events = []
    def _fail(**k):
        raise RuntimeError("db locked")
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft", _fail)
    monkeypatch.setattr(pildb, "_record_draft_event", lambda *a, **k: events.append(k) or 1)
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 503
    assert r.json().get("retryable") is True
    assert events == []          # a failed persist emits NO audit event


def test_confirm_no_remote_write(client, monkeypatch):
    _enable_confirm(monkeypatch)
    monkeypatch.setattr("app.services.conversion_persistence.persist_invoice_to_draft",
                        lambda **k: None)
    monkeypatch.setattr(pildb, "_record_draft_event", lambda *a, **k: 1)
    monkeypatch.setattr("app.services.audit_persist.record_wfirma_document_manually_linked",
                        lambda *a, **k: {"appended": True})
    _guard_no_remote_write(monkeypatch)
    r = client.post(_CONFIRM.format(1), headers=_authop(),
                    json={"document_type": "invoice", "wfirma_id": "500001",
                          "expected_preview_hash": "HASH-OK"})
    assert r.status_code == 200

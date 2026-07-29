"""
test_proforma_drafts_lifecycle_phase5.py — Phase 5:
operator-driven posting of an approved local Proforma Draft to wFirma.

Tests are tightly scoped to the new helpers + the /post endpoint.
The wFirma client is stubbed so no live HTTP traffic occurs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client
from app.services import wfirma_db as wfdb


def _auth_headers(operator: str = "alice"):
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """TestClient with WFIRMA_CREATE_PROFORMA_ALLOWED=true and storage
    root redirected to tmp_path."""
    from app.main import app
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_approved(db: Path, *, currency="EUR"):
    """Auto-create + approve a draft. Returns the approved-row."""
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency=currency,
        lines=[
            {"product_code": "RNG-100", "design_no": "D100",
             "qty": 2, "unit_price": 25.50, "currency": currency},
            {"product_code": "RNG-200", "design_no": "D200",
             "qty": 1, "unit_price": 100.0, "currency": currency},
        ],
        operator="intake",
    )
    return pildb.approve_draft(
        db, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )


def _stub_route_lookups(monkeypatch, *, missing_product=None,
                        missing_customer=False, ambiguous=False):
    """Patch the master-data lookups the route makes inside
    _build_proforma_request_from_draft so tests don't hit live DBs.

    Also stubs the single-readiness-authority gate (split-authority fix):
    these tests pin POST lifecycle mechanics (locks, orphan recovery,
    duplicate guard, wFirma error handling), not readiness derivation —
    that has dedicated no-stub coverage in
    test_proforma_readiness_single_authority.py. The stub mirrors the
    real _derive_draft_readiness return shape exactly (Lesson A)."""
    from app.api import routes_proforma as rp

    def _stub_readiness(draft, *, intent):
        return {
            "ready":             True,
            "intent":            intent,
            "draft_id":          int(draft.id),
            "draft_status":      draft.status,
            "blockers":          [],
            "blocking_reasons":  [],
            "warnings":          [],
            "ambiguous_designs": {},
            "resolved_designs":  {},
        }
    monkeypatch.setattr(rp, "_derive_draft_readiness", _stub_readiness)

    def _fake_resolve(name: str, batch_id=None, client_contractor_id: str = ""):
        if ambiguous:
            return {"ambiguous": True, "candidates": ["A", "B"],
                    "customer": None, "wfirma_customer_id": "",
                    "normalized_name": name.upper()}
        if missing_customer:
            return {"ambiguous": False, "candidates": [],
                    "customer": {"name": name, "country": "PL", "vat_id": ""},
                    "wfirma_customer_id": "",
                    "normalized_name": name.upper()}
        return {
            "ambiguous": False, "candidates": [],
            "customer": {
                "name": name, "country": "PL", "vat_id": "PL1234567890",
                "ship_to_mode": "same_as_bill_to",
                "ship_to_wfirma_customer_id": "",
            },
            "wfirma_customer_id": "WF-CUST-1",
            "normalized_name": name.upper(),
        }
    monkeypatch.setattr(rp, "_resolve_customer", _fake_resolve)

    # C-3g: good-id resolution is MIRROR-ONLY (_c1f_mirror_good_id); the old
    # wfdb.get_product cache fallback is retired, so stub the mirror helper
    # directly (same intent: these tests exercise the POST lifecycle, not the
    # resolution layer).
    def _fake_mirror_good_id(code: str):
        if missing_product is not None and code == missing_product:
            return None
        return f"WFP-{code}"
    monkeypatch.setattr(rp, "_c1f_mirror_good_id", _fake_mirror_good_id)

    # VAT context: deterministic
    monkeypatch.setattr(
        wfirma_client, "decide_proforma_vat_context",
        lambda customer_country, customer_vat_id: {
            "context":  "WDT" if customer_country.upper() != "PL" else "domestic",
            "vat_code": "WDT" if customer_country.upper() != "PL" else "23",
            "reason":   "stubbed",
        },
    )
    monkeypatch.setattr(
        wfirma_client, "resolve_vat_code_id_for_context",
        lambda code: f"VAT-{code}",
    )


def _stub_wfirma_call(monkeypatch, *, ok=True, wfirma_id="WF-PROF-9001",
                      error=None, raises=None):
    """Patch wfirma_client.create_proforma_draft."""
    if raises is not None:
        def _boom(req):
            raise raises
        monkeypatch.setattr(wfirma_client, "create_proforma_draft", _boom)
        return
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=ok,
            wfirma_invoice_id=wfirma_id if ok else None,
            error=error,
        ),
    )


def _stub_receiver_preflight(monkeypatch, *, ok=True, error=None):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=ok, error=error),
    )


# ── Helper-level — start_post / mark_* / record_post_orphan ─────────────────

def test_helper_start_post_from_approved(db_path):
    d = _seed_approved(db_path)
    posting = pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    assert posting.draft_state          == "posting"
    assert posting.status               == "pending_local"   # legacy mirror
    assert posting.posting_started_by   == "alice"
    assert posting.posting_started_at


@pytest.mark.parametrize("force_state, force_status", [
    ("draft", "draft"),
    ("editing", "draft"),
    ("post_failed", "failed"),
    ("posted", "issued"),
    ("cancelled", "draft"),
])
def test_helper_start_post_rejects_non_approved(db_path, force_state, force_status):
    d = _seed_approved(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state=?, status=? WHERE id=?",
            (force_state, force_status, d.id),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db_path, d.id)
    with pytest.raises(pildb.DraftNotEditable):
        pildb.start_post(
            db_path, d.id, "alice", fresh.updated_at,
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )


def test_helper_start_post_rejects_wrong_token(db_path):
    d = _seed_approved(db_path)
    for bad in ("", "yes", "YES_POST", None):
        with pytest.raises(ValueError) as exc:
            pildb.start_post(
                db_path, d.id, "alice", d.updated_at,
                confirm_token=bad,
            )
        assert "confirm_token" in str(exc.value)


def test_helper_start_post_rejects_stale_lock(db_path):
    d = _seed_approved(db_path)
    with pytest.raises(pildb.DraftConflict):
        pildb.start_post(
            db_path, d.id, "alice", "1999-01-01T00:00:00Z",
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )


def test_helper_start_post_rejects_existing_wfirma_id(db_path):
    d = _seed_approved(db_path)
    # Force a wfirma_proforma_id without going through Phase 5 (simulate
    # a row migrated from the legacy /create path).
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET wfirma_proforma_id='WF-OLD' WHERE id=?",
            (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db_path, d.id)
    with pytest.raises(pildb.DraftNotEditable) as exc:
        pildb.start_post(
            db_path, d.id, "alice", fresh.updated_at,
            confirm_token=pildb.POST_CONFIRM_TOKEN,
        )
    assert "already" in str(exc.value)


def test_helper_mark_post_succeeded(db_path):
    d = _seed_approved(db_path)
    posting = pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    posted = pildb.mark_post_succeeded(
        db_path, d.id,
        wfirma_proforma_id="WF-1",
        wfirma_proforma_fullnumber="PRO 1/2026",
        operator="alice",
    )
    assert posted.draft_state                == "posted"
    assert posted.status                     == "issued"   # legacy mirror
    assert posted.wfirma_proforma_id         == "WF-1"
    assert posted.wfirma_proforma_fullnumber == "PRO 1/2026"
    assert posted.posted_by                  == "alice"
    assert posted.posted_at


def test_helper_mark_post_succeeded_requires_posting_state(db_path):
    d = _seed_approved(db_path)
    # Still 'approved' — not 'posting'
    with pytest.raises(pildb.DraftNotEditable):
        pildb.mark_post_succeeded(
            db_path, d.id,
            wfirma_proforma_id="WF-1", operator="alice",
        )


def test_helper_mark_post_failed(db_path):
    d = _seed_approved(db_path)
    pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    failed = pildb.mark_post_failed(
        db_path, d.id, error="wfirma timeout", operator="alice",
    )
    assert failed.draft_state    == "post_failed"
    assert failed.status         == "failed"   # legacy mirror
    assert failed.notes          == "wfirma timeout"
    assert failed.post_failed_at


def test_helper_mark_post_failed_requires_posting_state(db_path):
    d = _seed_approved(db_path)
    with pytest.raises(pildb.DraftNotEditable):
        pildb.mark_post_failed(
            db_path, d.id, error="x", operator="alice",
        )


def test_helper_mark_post_failed_truncates_long_error(db_path):
    d = _seed_approved(db_path)
    pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    huge = "x" * 5000
    failed = pildb.mark_post_failed(
        db_path, d.id, error=huge, operator="alice",
    )
    assert len(failed.notes) <= 500


def test_helper_record_post_orphan_writes_event(db_path):
    d = _seed_approved(db_path)
    pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    ok = pildb.record_post_orphan(
        db_path, d.id,
        wfirma_proforma_id="WF-ORPHAN",
        error="disk full",
        operator="alice",
    )
    assert ok is True
    events = pildb.list_draft_events(db_path, d.id)
    orphan_evt = [e for e in events if e["event"] == "draft_post_orphan"][0]
    detail = json.loads(orphan_evt["detail_json"])
    assert detail["wfirma_proforma_id"] == "WF-ORPHAN"
    assert detail["error"]              == "disk full"


def test_helper_legacy_status_mirrors_each_transition(db_path):
    d = _seed_approved(db_path)
    posting = pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    assert posting.status == "pending_local"
    posted = pildb.mark_post_succeeded(
        db_path, d.id, wfirma_proforma_id="WF-1", operator="alice",
    )
    assert posted.status == "issued"


def test_helper_legacy_status_mirrors_failure_path(db_path):
    d = _seed_approved(db_path)
    pildb.start_post(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.POST_CONFIRM_TOKEN,
    )
    failed = pildb.mark_post_failed(
        db_path, d.id, error="x", operator="alice",
    )
    assert failed.status == "failed"


# ── Endpoint — happy path ───────────────────────────────────────────────────

def test_endpoint_post_success(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)

    call_count = {"n": 0}
    def _stub(req):
        call_count["n"] += 1
        return wfirma_client.ProformaResult(
            ok=True, wfirma_invoice_id="WF-PROF-9001",
        )
    monkeypatch.setattr(wfirma_client, "create_proforma_draft", _stub)

    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"]              == "posted"
    assert body["wfirma_proforma_id"]  == "WF-PROF-9001"
    assert body["draft"]["draft_state"] == "posted"
    # Exactly one wFirma call
    assert call_count["n"] == 1


def test_endpoint_audit_record_called_with_operator(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, ok=True, wfirma_id="WF-9002")

    captured = {}
    def _fake_record(audit_path, **kwargs):
        captured.update(kwargs)
        return {"appended": True}
    monkeypatch.setattr(
        "app.services.audit_persist.record_proforma_issued", _fake_record,
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers("bob"),
    )
    assert r.status_code == 200, r.text
    assert captured.get("operator")            == "bob"
    assert captured.get("wfirma_proforma_id")  == "WF-9002"
    assert captured.get("client_name")         == "ACME"


# ── Endpoint — pre-commit blocks ────────────────────────────────────────────

def test_endpoint_blocked_when_flag_off(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", False)
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "WFIRMA_CREATE_PROFORMA_ALLOWED" in r.json()["blocking_reasons"][0]


def test_endpoint_blocked_without_operator(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers={"X-API-KEY": settings.api_key or "test-key"},
    )
    assert r.status_code == 400
    assert "X-Operator" in r.json()["detail"]


def test_endpoint_service_charges_noted_not_blocked(client, tmp_path, monkeypatch):
    """Phase 6D: service charges are snapshotted and noted but no longer
    block posting. A service_charges_note appears in the 200 response when
    no wFirma product mapping exists for the charge type."""
    db = tmp_path / "proforma_links.db"
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency="EUR",
        lines=[{"product_code": "X", "design_no": "X",
                "qty": 1, "unit_price": 5.0, "currency": "EUR"}],
        operator="intake",
    )
    e = pildb.add_draft_service_charge(
        db, d.id,
        {"charge_type": "freight", "amount": 50, "currency": "EUR"},
        "alice", d.updated_at,
    )
    approved = pildb.approve_draft(
        db, d.id, "alice", e.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    _stub_route_lookups(monkeypatch)
    _stub_wfirma_call(monkeypatch)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": approved.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Service charges no longer block posting (Phase 6D).
    # The stub returns a product mapping for "freight", so no note is emitted.
    # When no mapping exists in production, service_charges_note is added to
    # the response — that path is tested by test_service_charges_snapshot_6d.py.


def test_endpoint_blocked_mixed_currency(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency="EUR",
        lines=[
            {"product_code": "A", "design_no": "A", "qty": 1,
             "unit_price": 5, "currency": "EUR"},
            {"product_code": "B", "design_no": "B", "qty": 1,
             "unit_price": 5, "currency": "USD"},
        ],
        operator="intake",
    )
    approved = pildb.approve_draft(
        db, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    _stub_route_lookups(monkeypatch)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": approved.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "mixed line currencies" in r.json()["blocking_reasons"][0]


def test_endpoint_blocked_missing_product_mapping(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch, missing_product="RNG-100")
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "RNG-100" in r.json()["blocking_reasons"][0]


def test_endpoint_blocked_missing_customer_mapping(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch, missing_customer=True)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "wfirma_customer_id" in r.json()["blocking_reasons"][0]


def test_endpoint_blocked_receiver_preflight_fails(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    # Base stubs (incl. readiness gate — this test pins receiver-preflight
    # mechanics, not readiness derivation), then override the customer to
    # use separate_contractor with a receiver.
    _stub_route_lookups(monkeypatch)
    from app.api import routes_proforma as rp
    def _fake_resolve(name: str, batch_id=None, client_contractor_id: str = ""):
        return {
            "ambiguous": False, "candidates": [],
            "customer": {
                "name": name, "country": "PL", "vat_id": "PL1234567890",
                "ship_to_mode": "separate_contractor",
                "ship_to_wfirma_customer_id": "WF-RCV-99",
            },
            "wfirma_customer_id": "WF-CUST-1",
            "normalized_name": name.upper(),
        }
    monkeypatch.setattr(rp, "_resolve_customer", _fake_resolve)
    # C-3g: mirror-only good-id resolution — stub the mirror helper directly.
    monkeypatch.setattr(rp, "_c1f_mirror_good_id", lambda code: f"WFP-{code}")
    monkeypatch.setattr(
        wfirma_client, "decide_proforma_vat_context",
        lambda **kw: {"context": "domestic", "vat_code": "23",
                      "reason": "stub"},
    )
    monkeypatch.setattr(
        wfirma_client, "resolve_vat_code_id_for_context", lambda c: "VAT-23",
    )
    _stub_receiver_preflight(monkeypatch, ok=False, error="not found")
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "WF-RCV-99" in r.json()["blocking_reasons"][0]


# ── Endpoint — wFirma error → post_failed ───────────────────────────────────

def test_endpoint_wfirma_error_moves_to_post_failed(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, raises=RuntimeError("invoices/add wFirma status=ERROR"))

    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.draft_state == "post_failed"
    assert fresh.status      == "failed"
    assert "wFirma status=ERROR" in (fresh.notes or "")


def test_endpoint_wfirma_returns_ok_false_moves_to_post_failed(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, ok=False, error="duplicate proforma")

    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.draft_state == "post_failed"


# ── Endpoint — wFirma success but local persistence failure → orphan ────────

def test_endpoint_orphan_recovery(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, ok=True, wfirma_id="WF-ORPH-7")

    # Make mark_post_succeeded raise (simulate disk-full / locked DB)
    real_mark = pildb.mark_post_succeeded
    def _boom(*a, **kw):
        raise RuntimeError("simulated DB write failure")
    monkeypatch.setattr(pildb, "mark_post_succeeded", _boom)

    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["status"]                == "orphan"
    assert body["wfirma_proforma_id"]    == "WF-ORPH-7"
    assert body["orphan_event_recorded"] is True
    # Draft remains in posting state (the dashboard's "stuck" filter
    # is the human safety net).
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.draft_state == "posting"
    # Orphan event written
    events = pildb.list_draft_events(db, d.id)
    assert any(e["event"] == "draft_post_orphan" for e in events)


# ── Endpoint — second post is 409 ───────────────────────────────────────────

def test_endpoint_second_post_returns_409(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, ok=True, wfirma_id="WF-1")

    r1 = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r1.status_code == 200
    new_ts = r1.json()["draft"]["updated_at"]

    r2 = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": new_ts,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r2.status_code == 409
    assert "wfirma_proforma_id" in r2.json()["detail"]


def test_endpoint_unknown_draft_404(client):
    r = client.post(
        "/api/v1/proforma/draft/99999/post",
        json={"expected_updated_at": "x",
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_endpoint_stale_lock_409(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)

    # Capture wFirma call to confirm it never happens.
    called = {"n": 0}
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: (called.__setitem__("n", called["n"] + 1) or
                     wfirma_client.ProformaResult(ok=True,
                                                   wfirma_invoice_id="X")),
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": "1999-01-01T00:00:00Z",
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 409
    assert called["n"] == 0


def test_endpoint_wrong_token_blocks(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)

    called = {"n": 0}
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: (called.__setitem__("n", called["n"] + 1) or
                     wfirma_client.ProformaResult(ok=True,
                                                   wfirma_invoice_id="X")),
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": "WRONG"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert called["n"] == 0


def test_endpoint_post_failed_cannot_be_reposted_directly(client, tmp_path, monkeypatch):
    """Per spec rule: post_failed drafts must NOT retry directly. Operator
    has to re-open + edit + approve again."""
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    _stub_receiver_preflight(monkeypatch, ok=True)
    _stub_wfirma_call(monkeypatch, raises=RuntimeError("boom"))

    # First call → post_failed
    r1 = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r1.status_code == 200
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.draft_state == "post_failed"

    # Second call without re-approve → 409
    r2 = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": fresh.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r2.status_code == 409
    assert "post_failed" in r2.json()["detail"]

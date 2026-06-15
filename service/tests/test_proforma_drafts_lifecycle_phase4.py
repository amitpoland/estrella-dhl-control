"""
test_proforma_drafts_lifecycle_phase4.py — Phase 4:
approve / re-open / cancel / reset / line add / line remove.

Coverage:
  1. approve from editing → approved (locked)
  2. approve requires exact confirm token
  3. approved draft rejects PATCH (Phase 3 edits)
  4. re-open returns to editing, clears locked_at, preserves approved_at
  5. cancel records reason + locks; refuses on posted
  6. posted draft cannot be cancelled
  7. reset replaces lines, preserves overrides
  8. reset_all clears overrides + service charges
  9. add_line validates and records event
 10. remove_line records event
 11. remove last line without force is rejected
 12. stale expected_updated_at → 409 on every endpoint
 13. post_failed stays post_failed after add/remove/reset (Phase 3 policy)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


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
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_draft(db: Path, batch="B1", client_name="ACME", currency="EUR"):
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=batch, client_name=client_name, currency=currency,
        lines=[
            {"product_code": "RNG-100", "design_no": "D100",
             "qty": 2, "unit_price": 25.50, "currency": currency,
             "price_source": "packing_list"},
            {"product_code": "RNG-200", "design_no": "D200",
             "qty": 1, "unit_price": 100.0, "currency": currency,
             "price_source": "packing_list"},
        ],
        operator="intake",
    )
    return d


def _force_state(db: Path, draft_id: int, *, state: str, status: str):
    """Direct UPDATE to manoeuvre a draft into a specific lifecycle
    state for tests. Both columns are set to keep the read shim
    self-consistent (Phase 1 backfill rule)."""
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state=?, status=? WHERE id=?",
            (state, status, draft_id),
        )
        conn.commit()


def _stub_readiness_ready(monkeypatch):
    """Neutralise the single-readiness-authority gate for the endpoint
    lifecycle-mechanic tests below.

    The approve route consults ``_derive_draft_readiness`` (split-authority
    fix, 2026-06-12) and fail-closes any draft that has no sales rows, an
    unmatched wfirma customer, blank name_pl, or unmapped wfirma_products —
    so the bare ``_seed_draft`` fixture now returns 422 before the lifecycle
    mechanic under test (approve transition, confirm-token validation,
    optimistic-lock 409, re-open) is ever reached.

    Phase 4 pins those state-machine mechanics, NOT readiness derivation.
    Seeding all four authority sources here would couple these tests to
    master-data plumbing; readiness derivation itself has dedicated no-stub
    coverage in test_proforma_readiness_single_authority.py and
    test_proforma_birth_name_pl_authority.py. This mirrors the identical
    stub already used by the sibling Phase 5 POST-lifecycle suite. The stub
    returns the real ``_derive_draft_readiness`` shape exactly (Lesson A)."""
    from app.api import routes_proforma as rp

    def _ready(draft, *, intent):
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
    monkeypatch.setattr(rp, "_derive_draft_readiness", _ready)


# ── Helpers — approve ───────────────────────────────────────────────────────

def test_helper_approve_from_editing(db_path):
    d = _seed_draft(db_path)
    # Move to editing via a Phase-3 edit.
    e = pildb.update_draft_fields(
        db_path, d.id, {"remarks": "ready"}, "alice", d.updated_at,
    )
    assert e.draft_state == "editing"
    approved = pildb.approve_draft(
        db_path, d.id, "alice", e.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    assert approved.draft_state == "approved"
    assert approved.approved_by == "alice"
    assert approved.approved_at
    assert approved.locked_at == approved.approved_at


def test_helper_approve_from_draft_directly(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    assert approved.draft_state == "approved"


def test_helper_approve_requires_exact_token(db_path):
    d = _seed_draft(db_path)
    for bad in ("", "yes", "yes_approve", "YES_APPROVE", None):
        with pytest.raises(ValueError) as exc:
            pildb.approve_draft(
                db_path, d.id, "alice", d.updated_at,
                confirm_token=bad,
            )
        assert "confirm_token" in str(exc.value)


def test_helper_approve_rejects_when_already_approved(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    with pytest.raises(pildb.DraftNotEditable):
        pildb.approve_draft(
            db_path, d.id, "alice", approved.updated_at,
            confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
        )


def test_helper_approved_draft_rejects_patch(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    with pytest.raises(pildb.DraftNotEditable):
        pildb.update_draft_fields(
            db_path, d.id, {"remarks": "x"}, "alice", approved.updated_at,
        )


# ── Helpers — re-open ───────────────────────────────────────────────────────

def test_helper_reopen_back_to_editing(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    reopened = pildb.reopen_draft(
        db_path, d.id, "bob", approved.updated_at,
        confirm_token=pildb.REOPEN_CONFIRM_TOKEN,
    )
    assert reopened.draft_state == "editing"
    assert reopened.locked_at   is None
    # approved_at preserved as historical record.
    assert reopened.approved_at == approved.approved_at
    assert reopened.approved_by == "alice"


def test_helper_reopen_only_from_approved(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(pildb.DraftNotEditable):
        pildb.reopen_draft(
            db_path, d.id, "alice", d.updated_at,
            confirm_token=pildb.REOPEN_CONFIRM_TOKEN,
        )


def test_helper_reopen_requires_token(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    with pytest.raises(ValueError):
        pildb.reopen_draft(
            db_path, d.id, "alice", approved.updated_at, confirm_token="nope",
        )


# ── Helpers — cancel ────────────────────────────────────────────────────────

def test_helper_cancel_records_reason(db_path):
    d = _seed_draft(db_path)
    cancelled = pildb.cancel_draft(
        db_path, d.id, "alice", d.updated_at,
        reason="client withdrew",
    )
    assert cancelled.draft_state == "cancelled"
    assert cancelled.locked_at
    events = pildb.list_draft_events(db_path, d.id)
    cancel_evt = [e for e in events if e["event"] == "draft_cancelled"][0]
    assert json.loads(cancel_evt["detail_json"])["reason"] == "client withdrew"


def test_helper_cancel_requires_reason(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError):
        pildb.cancel_draft(
            db_path, d.id, "alice", d.updated_at, reason="",
        )


def test_helper_cancel_rejects_posted(db_path):
    d = _seed_draft(db_path)
    _force_state(db_path, d.id, state="posted", status="issued")
    fresh = pildb.get_draft_by_id(db_path, d.id)
    with pytest.raises(pildb.DraftNotEditable) as exc:
        pildb.cancel_draft(
            db_path, d.id, "alice", fresh.updated_at, reason="x",
        )
    assert "posted" in str(exc.value)


def test_helper_cancel_rejects_already_cancelled(db_path):
    d = _seed_draft(db_path)
    pildb.cancel_draft(db_path, d.id, "alice", d.updated_at, reason="x")
    fresh = pildb.get_draft_by_id(db_path, d.id)
    with pytest.raises(pildb.DraftNotEditable):
        pildb.cancel_draft(
            db_path, d.id, "alice", fresh.updated_at, reason="y",
        )


# ── Helpers — reset ─────────────────────────────────────────────────────────

def _new_sales_lines():
    return [
        {"product_code": "RNG-100", "design_no": "D100",
         "qty": 5, "unit_price": 30.0, "currency": "EUR"},
        {"product_code": "NEW-300", "design_no": "D300",
         "qty": 2, "unit_price": 50.0, "currency": "EUR"},
    ]


def test_helper_reset_replaces_lines_preserves_overrides(db_path):
    d = _seed_draft(db_path)
    # Set some overrides via Phase 3.
    e1 = pildb.update_draft_fields(
        db_path, d.id, {"remarks": "VIP", "buyer_override": {"name": "X"}},
        "alice", d.updated_at,
    )
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, d.id, "alice", e1.updated_at,
        sales_lines=_new_sales_lines(),
    )
    parsed = json.loads(refreshed.editable_lines_json)
    codes = {ln["product_code"] for ln in parsed}
    assert codes == {"RNG-100", "NEW-300"}
    # Overrides preserved.
    assert refreshed.remarks                                == "VIP"
    assert json.loads(refreshed.buyer_override_json)["name"] == "X"


def test_helper_reset_all_clears_overrides(db_path):
    d = _seed_draft(db_path)
    e = pildb.update_draft_fields(
        db_path, d.id,
        {"remarks": "VIP", "buyer_override": {"name": "X"},
         "payment_terms": {"days": 30}},
        "alice", d.updated_at,
    )
    # Add a service charge, then reset_all.
    e2 = pildb.add_draft_service_charge(
        db_path, d.id,
        {"charge_type": "freight", "amount": 50, "currency": "EUR"},
        "alice", e.updated_at,
    )
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, d.id, "alice", e2.updated_at,
        sales_lines=_new_sales_lines(),
        reset_all=True,
    )
    assert refreshed.remarks               == ""
    assert refreshed.buyer_override_json   == "{}"
    assert refreshed.ship_to_override_json == "{}"
    assert refreshed.payment_terms_json    == "{}"
    assert refreshed.service_charges_json  == "[]"


def test_helper_reset_only_in_editable_states(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    with pytest.raises(pildb.DraftNotEditable):
        pildb.reset_draft_from_sales_packing(
            db_path, d.id, "alice", approved.updated_at,
            sales_lines=_new_sales_lines(),
        )


def test_helper_reset_post_failed_stays_post_failed(db_path):
    d = _seed_draft(db_path)
    _force_state(db_path, d.id, state="post_failed", status="failed")
    fresh = pildb.get_draft_by_id(db_path, d.id)
    refreshed = pildb.reset_draft_from_sales_packing(
        db_path, d.id, "alice", fresh.updated_at,
        sales_lines=_new_sales_lines(),
    )
    assert refreshed.draft_state == "post_failed"


# ── Helpers — add line ──────────────────────────────────────────────────────

def test_helper_add_line(db_path):
    d = _seed_draft(db_path)
    refreshed = pildb.add_draft_line(
        db_path, d.id,
        {"product_code": "ADD-1", "qty": 3, "unit_price": 7.5,
         "currency": "EUR", "design_no": "DA"},
        "alice", d.updated_at,
    )
    lines = json.loads(refreshed.editable_lines_json)
    new_line = next(l for l in lines if l["product_code"] == "ADD-1")
    assert new_line["qty"]        == 3
    assert new_line["unit_price"] == 7.5
    assert new_line["currency"]   == "EUR"
    # line_id is unique and > existing max.
    other_ids = {int(l["line_id"]) for l in lines if l["product_code"] != "ADD-1"}
    assert int(new_line["line_id"]) > max(other_ids)
    # Event recorded.
    events = pildb.list_draft_events(db_path, d.id)
    assert any(e["event"] == "draft_line_added" for e in events)


def test_helper_add_line_validation(db_path):
    d = _seed_draft(db_path)
    cases = [
        ({"product_code": "", "qty": 1, "unit_price": 1, "currency": "EUR"},
         "product_code is required"),
        ({"product_code": "X", "qty": 0, "unit_price": 1, "currency": "EUR"},
         "qty must be > 0"),
        ({"product_code": "X", "qty": -1, "unit_price": 1, "currency": "EUR"},
         "qty must be > 0"),
        ({"product_code": "X", "qty": 1, "unit_price": -1, "currency": "EUR"},
         "unit_price must be >= 0"),
        ({"product_code": "X", "qty": 1, "unit_price": 1, "currency": "ZZZ"},
         "currency 'ZZZ' not allowed"),
    ]
    for line, msg in cases:
        with pytest.raises(ValueError) as exc:
            pildb.add_draft_line(
                db_path, d.id, line, "alice", d.updated_at,
            )
        assert msg in str(exc.value), f"line={line}: {exc.value}"


def test_helper_add_line_only_in_editable(db_path):
    d = _seed_draft(db_path)
    approved = pildb.approve_draft(
        db_path, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )
    with pytest.raises(pildb.DraftNotEditable):
        pildb.add_draft_line(
            db_path, d.id,
            {"product_code": "X", "qty": 1, "unit_price": 1,
             "currency": "EUR"},
            "alice", approved.updated_at,
        )


# ── Helpers — remove line ──────────────────────────────────────────────────

def test_helper_remove_line(db_path):
    d = _seed_draft(db_path)
    line_id = pildb._ensure_line_ids(json.loads(d.editable_lines_json))[0]["line_id"]
    refreshed = pildb.remove_draft_line(
        db_path, d.id, line_id, "alice", d.updated_at,
    )
    lines = json.loads(refreshed.editable_lines_json)
    assert len(lines) == 1
    assert lines[0]["line_id"] != line_id
    events = pildb.list_draft_events(db_path, d.id)
    assert any(e["event"] == "draft_line_removed" for e in events)


def test_helper_remove_last_line_without_force_rejected(db_path):
    d = _seed_draft(db_path)
    # Remove first
    line_ids = [l["line_id"] for l in pildb._ensure_line_ids(json.loads(d.editable_lines_json))]
    e = pildb.remove_draft_line(
        db_path, d.id, line_ids[0], "alice", d.updated_at,
    )
    # Try to remove last without force
    with pytest.raises(ValueError) as exc:
        pildb.remove_draft_line(
            db_path, d.id, line_ids[1], "alice", e.updated_at,
        )
    assert "force=true" in str(exc.value)


def test_helper_remove_last_line_with_force_succeeds(db_path):
    d = _seed_draft(db_path)
    line_ids = [l["line_id"] for l in pildb._ensure_line_ids(json.loads(d.editable_lines_json))]
    e = pildb.remove_draft_line(
        db_path, d.id, line_ids[0], "alice", d.updated_at,
    )
    refreshed = pildb.remove_draft_line(
        db_path, d.id, line_ids[1], "alice", e.updated_at, force=True,
    )
    assert json.loads(refreshed.editable_lines_json) == []


def test_helper_remove_unknown_line(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError):
        pildb.remove_draft_line(
            db_path, d.id, 9999, "alice", d.updated_at,
        )


# ── Optimistic lock applies to every Phase 4 helper ─────────────────────────

@pytest.mark.parametrize("op", [
    lambda db, d: pildb.approve_draft(
        db, d.id, "alice", "stale",
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN),
    lambda db, d: pildb.cancel_draft(
        db, d.id, "alice", "stale", reason="x"),
    lambda db, d: pildb.reset_draft_from_sales_packing(
        db, d.id, "alice", "stale", sales_lines=[]),
    lambda db, d: pildb.add_draft_line(
        db, d.id,
        {"product_code": "X", "qty": 1, "unit_price": 1, "currency": "EUR"},
        "alice", "stale"),
    lambda db, d: pildb.remove_draft_line(
        db, d.id, 1, "alice", "stale"),
])
def test_helper_stale_lock_raises(db_path, op):
    d = _seed_draft(db_path)
    with pytest.raises(pildb.DraftConflict):
        op(db_path, d)


# ── HTTP — approve ──────────────────────────────────────────────────────────

def test_endpoint_approve(client, tmp_path, monkeypatch):
    _stub_readiness_ready(monkeypatch)
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/approve",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.APPROVE_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["draft_state"] == "approved"


def test_endpoint_approve_bad_token(client, tmp_path, monkeypatch):
    # Readiness must pass so the request reaches the confirm-token check
    # (readiness 422 fires before token 400 in the route order).
    _stub_readiness_ready(monkeypatch)
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/approve",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": "nope"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "confirm_token" in r.json()["detail"]


def test_endpoint_approve_blocks_subsequent_patch(client, tmp_path, monkeypatch):
    _stub_readiness_ready(monkeypatch)
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r1 = client.post(
        f"/api/v1/proforma/draft/{d.id}/approve",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.APPROVE_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    new_ts = r1.json()["draft"]["updated_at"]
    r2 = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": new_ts, "patch": {"remarks": "x"}},
        headers=_auth_headers(),
    )
    assert r2.status_code == 409


# ── HTTP — re-open ──────────────────────────────────────────────────────────

def test_endpoint_reopen(client, tmp_path, monkeypatch):
    _stub_readiness_ready(monkeypatch)
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r1 = client.post(
        f"/api/v1/proforma/draft/{d.id}/approve",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.APPROVE_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    ts = r1.json()["draft"]["updated_at"]
    r2 = client.post(
        f"/api/v1/proforma/draft/{d.id}/re-open",
        json={"expected_updated_at": ts,
              "confirm_token": pildb.REOPEN_CONFIRM_TOKEN},
        headers=_auth_headers("bob"),
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()["draft"]
    assert body["draft_state"] == "editing"
    assert body["locked_at"]   is None


# ── HTTP — cancel ───────────────────────────────────────────────────────────

def test_endpoint_cancel(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/cancel",
        json={"expected_updated_at": d.updated_at, "reason": "withdrew"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["draft"]["draft_state"] == "cancelled"
    assert r.json()["draft"]["locked_at"]


def test_endpoint_cancel_requires_reason(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/cancel",
        json={"expected_updated_at": d.updated_at, "reason": ""},
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_endpoint_cancel_rejects_posted(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    _force_state(db, d.id, state="posted", status="issued")
    fresh = pildb.get_draft_by_id(db, d.id)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/cancel",
        json={"expected_updated_at": fresh.updated_at, "reason": "x"},
        headers=_auth_headers(),
    )
    assert r.status_code == 409


# ── HTTP — reset ────────────────────────────────────────────────────────────

def test_endpoint_reset_pulls_from_documents_db(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db, batch="B-RESET", client_name="ACME", currency="EUR")

    # Stub document_db.get_sales_packing_lines to return new rows.
    from app.api import routes_proforma as rp
    monkeypatch.setattr(
        rp.ddb, "get_sales_packing_lines",
        lambda batch_id: [
            {"client_name": "ACME", "product_code": "RESET-1",
             "design_no": "DR", "quantity": 4, "unit_price": 12.0,
             "currency": "EUR", "price_source": "packing_list",
             "client_ref": ""},
            {"client_name": "OTHER", "product_code": "WRONG-CLIENT",
             "design_no": "X", "quantity": 1, "unit_price": 1.0,
             "currency": "EUR"},
        ],
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/reset-from-sales-packing",
        json={"expected_updated_at": d.updated_at, "reset_all": False},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    lines = r.json()["draft"]["editable_lines"]
    assert len(lines) == 1
    assert lines[0]["product_code"] == "RESET-1"


def test_endpoint_reset_all_clears(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    # Set overrides
    e = pildb.update_draft_fields(
        db, d.id, {"remarks": "VIP"}, "alice", d.updated_at,
    )
    from app.api import routes_proforma as rp
    monkeypatch.setattr(
        rp.ddb, "get_sales_packing_lines",
        lambda batch_id: [
            {"client_name": "ACME", "product_code": "RESET-1",
             "design_no": "DR", "quantity": 1, "unit_price": 1.0,
             "currency": "EUR"},
        ],
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/reset-from-sales-packing",
        json={"expected_updated_at": e.updated_at, "reset_all": True},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["remarks"] == ""


# ── HTTP — line add/remove ─────────────────────────────────────────────────

def test_endpoint_add_line(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/lines",
        json={"expected_updated_at": d.updated_at,
              "line": {"product_code": "NEW", "qty": 5, "unit_price": 8.0,
                       "currency": "EUR", "design_no": "DN"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    lines = r.json()["draft"]["editable_lines"]
    assert any(l["product_code"] == "NEW" for l in lines)


def test_endpoint_add_line_validation(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/lines",
        json={"expected_updated_at": d.updated_at,
              "line": {"product_code": "", "qty": 1, "unit_price": 1,
                       "currency": "EUR"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_endpoint_remove_line(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    line_id = pildb._ensure_line_ids(json.loads(d.editable_lines_json))[0]["line_id"]
    r = client.delete(
        f"/api/v1/proforma/draft/{d.id}/lines/{line_id}"
        f"?expected_updated_at={d.updated_at}",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    lines = r.json()["draft"]["editable_lines"]
    assert all(l["line_id"] != line_id for l in lines)


def test_endpoint_remove_last_line_without_force_400(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    # Remove first line
    ids = [l["line_id"] for l in pildb._ensure_line_ids(json.loads(d.editable_lines_json))]
    r1 = client.delete(
        f"/api/v1/proforma/draft/{d.id}/lines/{ids[0]}"
        f"?expected_updated_at={d.updated_at}",
        headers=_auth_headers(),
    )
    assert r1.status_code == 200
    new_ts = r1.json()["draft"]["updated_at"]
    # Remove last without force
    r2 = client.delete(
        f"/api/v1/proforma/draft/{d.id}/lines/{ids[1]}"
        f"?expected_updated_at={new_ts}",
        headers=_auth_headers(),
    )
    assert r2.status_code == 400
    assert "force" in r2.json()["detail"]


def test_endpoint_remove_last_line_with_force_200(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    ids = [l["line_id"] for l in pildb._ensure_line_ids(json.loads(d.editable_lines_json))]
    r1 = client.delete(
        f"/api/v1/proforma/draft/{d.id}/lines/{ids[0]}"
        f"?expected_updated_at={d.updated_at}",
        headers=_auth_headers(),
    )
    new_ts = r1.json()["draft"]["updated_at"]
    r2 = client.delete(
        f"/api/v1/proforma/draft/{d.id}/lines/{ids[1]}"
        f"?expected_updated_at={new_ts}&force=true",
        headers=_auth_headers(),
    )
    assert r2.status_code == 200
    assert r2.json()["draft"]["editable_lines"] == []


# ── HTTP — stale lock 409 on every endpoint ─────────────────────────────────

def test_endpoint_stale_lock_409(client, tmp_path, monkeypatch):
    # Readiness must pass so the approve case reaches the optimistic-lock
    # check (readiness 422 fires before the stale-timestamp 409).
    _stub_readiness_ready(monkeypatch)
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    stale = "1999-01-01T00:00:00Z"
    cases = [
        ("post", f"/api/v1/proforma/draft/{d.id}/approve",
         {"expected_updated_at": stale,
          "confirm_token": pildb.APPROVE_CONFIRM_TOKEN}),
        ("post", f"/api/v1/proforma/draft/{d.id}/cancel",
         {"expected_updated_at": stale, "reason": "x"}),
        ("post", f"/api/v1/proforma/draft/{d.id}/lines",
         {"expected_updated_at": stale,
          "line": {"product_code": "X", "qty": 1, "unit_price": 1,
                   "currency": "EUR"}}),
    ]
    for method, url, body in cases:
        r = getattr(client, method)(url, json=body, headers=_auth_headers())
        assert r.status_code == 409, f"{method} {url}: {r.status_code} {r.text}"


def test_endpoint_requires_operator(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    no_op = {"X-API-KEY": settings.api_key or "test-key"}
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/approve",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.APPROVE_CONFIRM_TOKEN},
        headers=no_op,
    )
    assert r.status_code == 400

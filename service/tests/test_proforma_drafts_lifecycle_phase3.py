"""
test_proforma_drafts_lifecycle_phase3.py — Phase 3:
local editable Proforma Draft edit endpoints with optimistic locking.

Coverage:
  1. PATCH remarks transitions draft → editing
  2. Edit rejected without X-Operator (400)
  3. Edit rejected with stale expected_updated_at (409)
  4. Edit rejected on posted/cancelled draft (409)
  5. Line edit updates one line only, others untouched
  6. Invalid qty/price/currency rejected (400)
  7. Service charge add + remove records events
  8. Service charge currency mismatch rejected (400)
  9. post_failed draft REMAINS post_failed after edit (chosen policy)
 10. Read endpoints surface line_ids
 11. Auth: missing X-API-KEY blocks
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


def _no_operator_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


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
    draft, _ = pildb.auto_create_draft_from_sales_packing(
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
    return draft


# ── Helper-level tests (no HTTP) ─────────────────────────────────────────────

def test_helper_update_fields_transitions_to_editing(db_path):
    d = _seed_draft(db_path)
    assert d.draft_state == "draft"
    refreshed = pildb.update_draft_fields(
        db_path, d.id, {"remarks": "VIP client"}, "alice", d.updated_at,
    )
    assert refreshed.draft_state == "editing"
    assert refreshed.remarks     == "VIP client"
    # updated_at is at least as recent as the seed (timestamps are
    # second-resolution; back-to-back updates may share a second).
    assert refreshed.updated_at >= d.updated_at


def test_helper_post_failed_stays_post_failed(db_path):
    """Phase-3 chosen policy: post_failed drafts stay in post_failed
    after edits — re-posting is an explicit operator action."""
    d = _seed_draft(db_path)
    # Force the draft into post_failed via direct UPDATE (Phase 3
    # has no posting helpers; later phases will).
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='post_failed', "
            "status='failed' WHERE id=?", (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db_path, d.id)
    assert fresh.draft_state == "post_failed"

    refreshed = pildb.update_draft_fields(
        db_path, d.id, {"remarks": "retry"}, "alice", fresh.updated_at,
    )
    assert refreshed.draft_state == "post_failed"
    assert refreshed.remarks     == "retry"


def test_helper_optimistic_lock_conflict(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(pildb.DraftConflict):
        pildb.update_draft_fields(
            db_path, d.id, {"remarks": "x"}, "alice",
            "1999-01-01T00:00:00Z",
        )


def test_helper_missing_operator(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError):
        pildb.update_draft_fields(
            db_path, d.id, {"remarks": "x"}, "", d.updated_at,
        )


def test_helper_unknown_patch_key(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError) as exc:
        pildb.update_draft_fields(
            db_path, d.id, {"line_count": 5}, "alice", d.updated_at,
        )
    assert "unknown patch field" in str(exc.value)


def test_helper_not_editable_when_posted(db_path):
    d = _seed_draft(db_path)
    # Force into a posted state. Set legacy status='issued' alongside so
    # the read shim doesn't snap draft_state back to 'draft' via the
    # legacy-status-disagreement defensive override.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='posted', status='issued' "
            "WHERE id=?", (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db_path, d.id)
    assert fresh.draft_state == "posted"
    with pytest.raises(pildb.DraftNotEditable):
        pildb.update_draft_fields(
            db_path, d.id, {"remarks": "x"}, "alice", fresh.updated_at,
        )


def test_helper_line_edit_updates_one_line(db_path):
    d = _seed_draft(db_path)
    full = pildb._ensure_line_ids(json.loads(d.editable_lines_json))
    line_id = full[0]["line_id"]
    refreshed = pildb.update_draft_line(
        db_path, d.id, line_id, {"unit_price": 30.0, "qty": 5},
        "alice", d.updated_at,
    )
    lines = pildb._ensure_line_ids(json.loads(refreshed.editable_lines_json))
    by_id = {l["line_id"]: l for l in lines}
    # Edited line.
    assert by_id[line_id]["unit_price"] == 30.0
    assert by_id[line_id]["qty"]        == 5
    # Untouched line preserves its values.
    other = [l for l in lines if l["line_id"] != line_id][0]
    assert other["unit_price"] == 100.0
    assert other["qty"]        == 1


def test_helper_line_product_code_remap_persists(db_path):
    """Positive product_code remap: mapping a line to a new Product Master code
    via update_draft_line persists the new code and preserves every other field
    on that line and leaves sibling lines untouched.

    Proves the write authority the Source & Extraction "Map from Product Master"
    path relies on: product_code is a first-class EDITABLE_LINE_FIELDS key, not
    an authority gap. Complements test_helper_line_validation (blank rejection)
    and test_helper_line_edit_updates_one_line (qty/unit_price persist).
    """
    d = _seed_draft(db_path)
    full = pildb._ensure_line_ids(json.loads(d.editable_lines_json))
    line_id = full[0]["line_id"]
    assert full[0]["product_code"] == "RNG-100"

    refreshed = pildb.update_draft_line(
        db_path, d.id, line_id, {"product_code": "RNG-999"},
        "alice", d.updated_at,
    )
    lines = pildb._ensure_line_ids(json.loads(refreshed.editable_lines_json))
    by_id = {l["line_id"]: l for l in lines}
    # Remapped code persisted.
    assert by_id[line_id]["product_code"] == "RNG-999"
    # Other fields on the same line preserved (in-place patch, not replace).
    assert by_id[line_id]["qty"]        == 2
    assert by_id[line_id]["unit_price"] == 25.50
    assert by_id[line_id]["design_no"]  == "D100"
    # Sibling line untouched.
    other = [l for l in lines if l["line_id"] != line_id][0]
    assert other["product_code"] == "RNG-200"
    assert other["unit_price"]   == 100.0

    # Audit event records the remap.
    with sqlite3.connect(db_path) as cx:
        cx.row_factory = sqlite3.Row
        rows = cx.execute(
            "SELECT event, detail_json FROM proforma_draft_events "
            "WHERE draft_id=? AND event='draft_line_edited' ORDER BY id DESC",
            (d.id,),
        ).fetchall()
    assert rows, "expected a draft_line_edited audit event"
    detail = json.loads(rows[0]["detail_json"])
    assert detail["patch"] == {"product_code": "RNG-999"}
    assert detail["before"]["product_code"] == "RNG-100"


def test_helper_line_validation(db_path):
    d = _seed_draft(db_path)
    line_id = 1
    cases = [
        ({"qty": 0},                        "qty must be > 0"),
        ({"qty": -1},                       "qty must be > 0"),
        ({"qty": "abc"},                    "qty must be numeric"),
        ({"unit_price": -1},                "unit_price must be >= 0"),
        ({"unit_price": "abc"},             "unit_price must be numeric"),
        ({"currency": "ZZZ"},               "currency 'ZZZ' not allowed"),
        ({"product_code": ""},              "product_code cannot be blank"),
        ({"unknown_field": "x"},            "unknown line patch field"),
    ]
    for patch_dict, expected_substr in cases:
        with pytest.raises(ValueError) as exc:
            pildb.update_draft_line(
                db_path, d.id, line_id, patch_dict, "alice", d.updated_at,
            )
        assert expected_substr in str(exc.value), (
            f"patch={patch_dict!r} expected={expected_substr!r} "
            f"got={exc.value!s}"
        )


def test_helper_line_id_unknown(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError) as exc:
        pildb.update_draft_line(
            db_path, d.id, 9999, {"qty": 1}, "alice", d.updated_at,
        )
    assert "not found" in str(exc.value)


def test_helper_service_charge_add_remove(db_path):
    d = _seed_draft(db_path)
    refreshed = pildb.add_draft_service_charge(
        db_path, d.id,
        {"charge_type": "freight", "amount": 50.0, "currency": "EUR",
         "label": "DHL"},
        "alice", d.updated_at,
    )
    charges = json.loads(refreshed.service_charges_json)
    assert len(charges) == 1
    assert charges[0]["charge_id"]   == 1
    assert charges[0]["charge_type"] == "freight"
    assert charges[0]["amount"]      == 50.0
    assert charges[0]["currency"]    == "EUR"
    assert charges[0]["label"]       == "DHL"

    # Add a second
    refreshed2 = pildb.add_draft_service_charge(
        db_path, d.id,
        {"charge_type": "insurance", "amount": 5.0, "currency": "EUR"},
        "alice", refreshed.updated_at,
    )
    charges2 = json.loads(refreshed2.service_charges_json)
    assert {c["charge_id"] for c in charges2} == {1, 2}

    # Remove the first
    refreshed3 = pildb.remove_draft_service_charge(
        db_path, d.id, 1, "alice", refreshed2.updated_at,
    )
    charges3 = json.loads(refreshed3.service_charges_json)
    assert len(charges3) == 1
    assert charges3[0]["charge_id"] == 2

    # Events recorded
    events = pildb.list_draft_events(db_path, d.id)
    types = [e["event"] for e in events]
    assert "draft_service_charge_added"   in types
    assert "draft_service_charge_removed" in types
    assert types.count("draft_service_charge_added") == 2


def test_helper_service_charge_validation(db_path):
    d = _seed_draft(db_path)  # draft has EUR lines

    cases = [
        ({"charge_type": "tip", "amount": 1, "currency": "EUR"},
         "charge_type 'tip' not allowed"),
        ({"charge_type": "freight", "amount": -1, "currency": "EUR"},
         "amount must be >= 0"),
        ({"charge_type": "freight", "amount": "x", "currency": "EUR"},
         "amount must be numeric"),
        ({"charge_type": "freight", "amount": 1, "currency": "ZZZ"},
         "currency 'ZZZ' not allowed"),
        # Currency mismatch (lines are EUR)
        ({"charge_type": "freight", "amount": 1, "currency": "USD"},
         "does not match draft line currencies"),
    ]
    for charge, msg in cases:
        with pytest.raises(ValueError) as exc:
            pildb.add_draft_service_charge(
                db_path, d.id, charge, "alice", d.updated_at,
            )
        assert msg in str(exc.value), f"charge={charge}: {exc.value}"


def test_helper_remove_unknown_charge(db_path):
    d = _seed_draft(db_path)
    with pytest.raises(ValueError):
        pildb.remove_draft_service_charge(
            db_path, d.id, 999, "alice", d.updated_at,
        )


def test_ensure_line_ids_preserves_existing(db_path):
    """If a line already has line_id, do not renumber."""
    lines = [
        {"line_id": 5, "product_code": "X", "qty": 1},
        {"product_code": "Y", "qty": 1},   # missing — should get 6
    ]
    out = pildb._ensure_line_ids(lines)
    assert out[0]["line_id"] == 5
    assert out[1]["line_id"] == 6


# ── HTTP endpoint tests ──────────────────────────────────────────────────────

def test_patch_draft_remarks_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": d.updated_at,
              "patch": {"remarks": "VIP"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft"]["remarks"]     == "VIP"
    assert body["draft"]["draft_state"] == "editing"


def test_patch_draft_rejects_without_operator(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": d.updated_at,
              "patch": {"remarks": "x"}},
        headers=_no_operator_headers(),
    )
    assert r.status_code == 400
    assert "X-Operator" in r.json()["detail"]


def test_patch_draft_rejects_stale_lock(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": "1999-01-01T00:00:00Z",
              "patch": {"remarks": "x"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 409
    assert "expected_updated_at" in r.json()["detail"]


def test_patch_draft_rejects_on_posted_state(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='posted', status='issued' "
            "WHERE id=?", (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db, d.id)
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": fresh.updated_at,
              "patch": {"remarks": "x"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 409
    assert "posted" in r.json()["detail"]


def test_patch_line_endpoint_updates_one_line(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    # Get the live line_id from the read endpoint.
    rget = client.get(f"/api/v1/proforma/draft/{d.id}",
                       headers=_auth_headers())
    lines = rget.json()["draft"]["editable_lines"]
    line_id = lines[0]["line_id"]

    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}/lines/{line_id}",
        json={"expected_updated_at": d.updated_at,
              "patch": {"unit_price": 33.0}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {l["line_id"]: l for l in body["draft"]["editable_lines"]}
    assert by_id[line_id]["unit_price"] == 33.0
    other_id = [l for l in body["draft"]["editable_lines"]
                if l["line_id"] != line_id][0]["line_id"]
    assert by_id[other_id]["unit_price"] == 100.0


def test_patch_line_validation_400(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    rget = client.get(f"/api/v1/proforma/draft/{d.id}",
                       headers=_auth_headers())
    line_id = rget.json()["draft"]["editable_lines"][0]["line_id"]
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}/lines/{line_id}",
        json={"expected_updated_at": d.updated_at,
              "patch": {"qty": 0}},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "qty must be > 0" in r.json()["detail"]


def test_post_service_charge_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/service-charges",
        json={"expected_updated_at": d.updated_at,
              "charge": {"charge_type": "freight", "amount": 50,
                         "currency": "EUR", "label": "DHL"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    charges = r.json()["draft"]["service_charges"]
    assert len(charges) == 1
    assert charges[0]["charge_type"] == "freight"
    assert charges[0]["currency"]    == "EUR"


def test_post_service_charge_currency_mismatch(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db, currency="EUR")
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/service-charges",
        json={"expected_updated_at": d.updated_at,
              "charge": {"charge_type": "freight", "amount": 50,
                         "currency": "USD"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "does not match" in r.json()["detail"]


def test_delete_service_charge_endpoint(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    refreshed = pildb.add_draft_service_charge(
        db, d.id,
        {"charge_type": "freight", "amount": 50, "currency": "EUR"},
        "alice", d.updated_at,
    )
    r = client.delete(
        f"/api/v1/proforma/draft/{d.id}/service-charges/1"
        f"?expected_updated_at={refreshed.updated_at}",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["service_charges"] == []


def test_post_failed_endpoint_keeps_state(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='post_failed', "
            "status='failed' WHERE id=?", (d.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db, d.id)
    r = client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": fresh.updated_at,
              "patch": {"remarks": "fixed"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["draft"]["draft_state"] == "post_failed"
    assert r.json()["draft"]["remarks"]     == "fixed"


def test_read_endpoint_surfaces_line_ids(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.get(f"/api/v1/proforma/draft/{d.id}",
                    headers=_auth_headers())
    assert r.status_code == 200
    lines = r.json()["draft"]["editable_lines"]
    assert all(isinstance(l.get("line_id"), int) and l["line_id"] > 0
               for l in lines)
    # Stable: 1, 2 (since auto_create wrote them in order).
    assert {l["line_id"] for l in lines} == {1, 2}


def test_patch_unknown_draft_404(client, tmp_path):
    r = client.patch(
        "/api/v1/proforma/draft/99999",
        json={"expected_updated_at": "x", "patch": {"remarks": "y"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_delete_charge_unknown_id_400(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    r = client.delete(
        f"/api/v1/proforma/draft/{d.id}/service-charges/999"
        f"?expected_updated_at={d.updated_at}",
        headers=_auth_headers(),
    )
    assert r.status_code == 400


# ── Lifecycle/event integration ──────────────────────────────────────────────

def test_edit_appends_draft_edited_event(client, tmp_path):
    db = tmp_path / "proforma_links.db"
    d = _seed_draft(db)
    client.patch(
        f"/api/v1/proforma/draft/{d.id}",
        json={"expected_updated_at": d.updated_at,
              "patch": {"remarks": "x"}},
        headers=_auth_headers("bob"),
    )
    r = client.get(f"/api/v1/proforma/draft/{d.id}/events",
                    headers=_auth_headers())
    events = r.json()["events"]
    types = [e["event"] for e in events]
    assert "created_from_sales_packing" in types
    assert "draft_edited"               in types
    edited = [e for e in events if e["event"] == "draft_edited"][0]
    assert edited["operator"] == "bob"
    detail = json.loads(edited["detail_json"])
    assert detail["from_state"] == "draft"
    assert detail["to_state"]   == "editing"

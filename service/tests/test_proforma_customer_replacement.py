"""PR 1a — Proforma customer & recipient replacement.

Pins the new customer-identity write path:
  * ID-first replacement (never resolve by name),
  * editable-only + optimistic-locked,
  * duplicate-target draft blocks (never auto-merge),
  * line items / prices / packing linkage are never mutated,
  * customer-master search matches name / NIP / VAT-EU / contractor id,
  * recipient (ship_to_override) is editable independently of the customer.

Synthetic fixtures only — no real customer data.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import customer_master_db as cmdb
from app.services import proforma_invoice_link_db as pildb

_OP = {"X-Operator": "tester"}

BATCH = "SHIPMENT_TEST_PCE1"
now = "2026-07-01T00:00:00Z"


def _seed_customers(db: Path) -> None:
    cmdb.init_db(db)
    cols = ("bill_to_contractor_id, bill_to_name, country, nip, vat_eu_number, "
            "bill_to_street, bill_to_city, bill_to_postal_code, default_currency, "
            "created_at, updated_at")
    ph = ",".join(["?"] * 11)
    rows = [
        ("111", "Alpha Corp",  "PL", "PL111", "PL111", "Main 1", "Warsaw", "00-001", "EUR", now, now),
        ("222", "Beta Ltd",    "DE", "DE222", "DE222", "Haupt 2", "Berlin", "10115", "EUR", now, now),
        # duplicate-identity pair: same VAT, two contractor ids, two names
        ("333", "Gamma Trade", "BG", "BG999", "BG999", "St 3", "Sofia", "1000", "EUR", now, now),
        ("444", "GAMMA EOOD",  "BG", "BG999", None,     "St 3", "Sofia", "1000", None,  now, now),
    ]
    with sqlite3.connect(db) as con:
        con.executemany(f"INSERT INTO customer_master ({cols}) VALUES ({ph})", rows)
        con.commit()


def _seed_draft(db: Path, *, client_name="Alpha Corp", contractor_id="111",
                draft_state="editing", clone_generation=0) -> tuple[int, str]:
    with pildb._connect(db) as con:
        pildb._ensure_drafts_table(con)
        cur = con.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, draft_state, currency, "
            " client_contractor_id, buyer_override_json, ship_to_override_json, "
            " editable_lines_json, source_lines_json, clone_generation, "
            " created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (BATCH, client_name, "draft", draft_state, "EUR", contractor_id,
             json.dumps({"name": client_name, "_source": "manual"}),
             "{}",
             json.dumps([{"line_id": "L1", "product_code": "EJL/1", "qty": 2, "unit_price": 50.0}]),
             json.dumps([{"product_code": "EJL/1", "qty": 2}]),
             clone_generation, now, now),
        )
        con.commit()
        did = int(cur.lastrowid)
    d = pildb.get_draft_by_id(db, did)
    return did, d.updated_at


@pytest.fixture()
def dbs(tmp_path):
    cm = tmp_path / "customer_master.sqlite"
    pf = tmp_path / "proforma_links.db"
    _seed_customers(cm)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "storage_root", tmp_path)
        yield {"cm": cm, "pf": pf, "root": tmp_path}


# ── core DB write path ────────────────────────────────────────────────────────

def test_change_customer_by_id(dbs):
    did, upd = _seed_draft(dbs["pf"])
    out = pildb.change_draft_customer(
        dbs["pf"], did, new_contractor_id="222", new_client_name="Beta Ltd",
        buyer_override={"name": "Beta Ltd", "nip": "DE222", "_source": "customer_master"},
        operator="tester", expected_updated_at=upd)
    assert out.client_name == "Beta Ltd"
    assert out.client_contractor_id == "222"
    assert json.loads(out.buyer_override_json)["name"] == "Beta Ltd"
    assert json.loads(out.buyer_override_json)["_source"] == "customer_master"


def test_no_line_item_or_price_mutation(dbs):
    did, upd = _seed_draft(dbs["pf"])
    before = pildb.get_draft_by_id(dbs["pf"], did)
    out = pildb.change_draft_customer(
        dbs["pf"], did, new_contractor_id="222", new_client_name="Beta Ltd",
        buyer_override={"name": "Beta Ltd"}, operator="t", expected_updated_at=upd)
    assert out.editable_lines_json == before.editable_lines_json
    assert out.source_lines_json == before.source_lines_json


def test_lock_conflict_raises(dbs):
    did, _ = _seed_draft(dbs["pf"])
    with pytest.raises(pildb.DraftConflict):
        pildb.change_draft_customer(
            dbs["pf"], did, new_contractor_id="222", new_client_name="Beta Ltd",
            buyer_override={"name": "Beta Ltd"}, operator="t",
            expected_updated_at="1999-01-01T00:00:00Z")


def test_non_editable_raises(dbs):
    # 'approved' is a real frozen (non-editable, non-default) state — identity
    # is locked once a draft leaves the editable set.
    did, upd = _seed_draft(dbs["pf"], draft_state="approved")
    with pytest.raises(pildb.DraftNotEditable):
        pildb.change_draft_customer(
            dbs["pf"], did, new_contractor_id="222", new_client_name="Beta Ltd",
            buyer_override={"name": "Beta Ltd"}, operator="t", expected_updated_at=upd)


def test_duplicate_target_draft_blocks_no_auto_merge(dbs):
    # Two drafts in the SAME batch: one already assigned to Beta Ltd.
    _seed_draft(dbs["pf"], client_name="Beta Ltd", contractor_id="222")
    did_a, upd_a = _seed_draft(dbs["pf"], client_name="Alpha Corp", contractor_id="111")
    with pytest.raises(pildb.DraftConflict) as exc:
        pildb.change_draft_customer(
            dbs["pf"], did_a, new_contractor_id="222", new_client_name="Beta Ltd",
            buyer_override={"name": "Beta Ltd"}, operator="t", expected_updated_at=upd_a)
    assert "not auto-merged" in str(exc.value)


def test_idempotent_noop_same_contractor(dbs):
    did, upd = _seed_draft(dbs["pf"], client_name="Alpha Corp", contractor_id="111")
    out = pildb.change_draft_customer(
        dbs["pf"], did, new_contractor_id="111", new_client_name="Alpha Corp",
        buyer_override={"name": "Alpha Corp"}, operator="t", expected_updated_at=upd)
    assert out.client_contractor_id == "111"
    assert out.updated_at == upd  # untouched


def test_recipient_editable_independently(dbs):
    # Recipient replacement reuses the existing PATCH ship_to_override — the
    # customer identity must NOT change when only ship_to is edited.
    did, upd = _seed_draft(dbs["pf"], client_name="Alpha Corp", contractor_id="111")
    out = pildb.update_draft_fields(
        dbs["pf"], did,
        {"ship_to_override": {"name": "Warehouse X", "city": "Gdansk"}},
        operator="t", expected_updated_at=upd)
    assert json.loads(out.ship_to_override_json)["name"] == "Warehouse X"
    assert out.client_name == "Alpha Corp"          # customer unchanged
    assert out.client_contractor_id == "111"


# ── customer search (name / VAT / contractor id) ──────────────────────────────

def test_search_matches_name_vat_and_contractor_id(dbs):
    by_name = cmdb.list_customers(dbs["cm"], q="beta")
    by_vat  = cmdb.list_customers(dbs["cm"], q="DE222")
    by_id   = cmdb.list_customers(dbs["cm"], q="222")
    assert {c.bill_to_contractor_id for c in by_name} == {"222"}
    assert {c.bill_to_contractor_id for c in by_vat} == {"222"}
    assert "222" in {c.bill_to_contractor_id for c in by_id}


def test_shared_vat_returns_both_contractors_for_operator_choice(dbs):
    # Duplicate identity: one VAT, two contractor ids — search must surface BOTH
    # so the operator picks; the write path never auto-resolves by name/VAT.
    rows = cmdb.list_customers(dbs["cm"], q="BG999")
    assert {c.bill_to_contractor_id for c in rows} == {"333", "444"}


# ── single external draft writer: PATCH hosts the replacement ─────────────────

def test_no_standalone_change_customer_post_route():
    # The ONLY external draft mutation route is PATCH /draft/{id}. A standalone
    # POST /draft/{id}/change-customer must NOT exist.
    src = Path(__import__("app.api.routes_proforma", fromlist=["x"]).__file__).read_text(encoding="utf-8-sig")
    assert 'change-customer' not in src, "standalone change-customer route must be removed"
    assert 'def change_draft_customer_route' not in src
    # Exactly one external customer-mutation entry point: the PATCH route routes
    # client_contractor_id to the internal change_draft_customer.
    assert 'if "client_contractor_id" in patch:' in src


def test_no_pzapi_change_customer_wrapper():
    jsx_dir = Path(pildb.__file__).parent.parent / "static" / "v2"
    api = (jsx_dir / "pz-api.js").read_text(encoding="utf-8")
    assert "changeCustomer" not in api, "standalone changeCustomer POST wrapper must be removed"
    detail = (jsx_dir / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "client_contractor_id" in detail, "picker must PATCH client_contractor_id"


@pytest.fixture()
def client():
    return TestClient(app)


def _patch(client, did, patch, upd):
    return client.patch(f"/api/v1/proforma/draft/{did}",
                        json={"expected_updated_at": upd, "patch": patch}, headers=_OP)


def test_patch_replaces_customer_by_contractor_id(dbs, client):
    did, upd = _seed_draft(dbs["pf"])
    before = pildb.get_draft_by_id(dbs["pf"], did)
    r = _patch(client, did, {"client_contractor_id": "222"}, upd)
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["client_contractor_id"] == "222"
    assert d["client_name"] == "Beta Ltd"
    assert d["buyer_override"]["name"] == "Beta Ltd"
    # lines + source untouched
    after = pildb.get_draft_by_id(dbs["pf"], did)
    assert after.editable_lines_json == before.editable_lines_json
    assert after.source_lines_json == before.source_lines_json


def test_patch_client_contractor_id_must_be_sole_key(dbs, client):
    did, upd = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"client_contractor_id": "222", "currency": "USD"}, upd)
    assert r.status_code == 400
    assert "only patch key" in r.text


def test_patch_rejects_independent_client_name(dbs, client):
    # client_name is not in EDITABLE_DRAFT_FIELDS — the generic path rejects it.
    did, upd = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"client_name": "Hacked Name"}, upd)
    assert r.status_code == 400
    after = pildb.get_draft_by_id(dbs["pf"], did)
    assert after.client_name == "Alpha Corp"  # unchanged


def test_patch_unknown_contractor_404(dbs, client):
    did, upd = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"client_contractor_id": "999999"}, upd)
    assert r.status_code == 404


def test_patch_empty_contractor_id_400(dbs, client):
    did, upd = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"client_contractor_id": ""}, upd)
    assert r.status_code == 400


def test_patch_stale_lock_409(dbs, client):
    did, _ = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"client_contractor_id": "222"}, "1999-01-01T00:00:00Z")
    assert r.status_code == 409


def test_patch_non_editable_409(dbs, client):
    did, upd = _seed_draft(dbs["pf"], draft_state="approved")
    r = _patch(client, did, {"client_contractor_id": "222"}, upd)
    assert r.status_code == 409


def test_patch_duplicate_target_409_no_merge(dbs, client):
    _seed_draft(dbs["pf"], client_name="Beta Ltd", contractor_id="222")
    did_a, upd_a = _seed_draft(dbs["pf"], client_name="Alpha Corp", contractor_id="111")
    r = _patch(client, did_a, {"client_contractor_id": "222"}, upd_a)
    assert r.status_code == 409
    assert "not auto-merged" in r.text


def test_patch_recipient_still_independent(dbs, client):
    # ship_to_override remains a normal generic PATCH field — unaffected.
    did, upd = _seed_draft(dbs["pf"])
    r = _patch(client, did, {"ship_to_override": {"name": "Warehouse Z"}}, upd)
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["ship_to_override"]["name"] == "Warehouse Z"
    assert d["client_name"] == "Alpha Corp"  # customer unchanged

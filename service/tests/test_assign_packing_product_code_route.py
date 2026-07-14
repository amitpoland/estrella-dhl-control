"""test_assign_packing_product_code_route.py

Route-level pins for
``POST /api/v1/proforma/draft/{id}/assign-packing-product-code`` — the
operator-confirmation write half of the unassigned-packing over-bill repair
(SHIPMENT_8341809162 EJL/26-27/380-1 / -2, designs JR07550 / JR08385 that
arrived design-only so both billed codes showed "available 0").

Contract under test:
  * the write is BOUND to the read authority — it only stamps a (design →
    product_code) that the readiness gate is currently surfacing as an
    over-bill ``unassigned_packing`` repair (no arbitrary assignment);
  * confirm_token + X-Operator are mandatory; posted drafts are refused;
  * on success the piece becomes truly countable and the over-bill blocker
    clears on real data (the gate is NOT weakened — availability was real);
  * the write is idempotent and audited.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break

BATCH   = "BATCH_ASSIGN_ROUTE"
CLIENT  = "ASSIGN_CLIENT"
INVOICE = "EJL/26-27/380"
CODE_1  = "EJL/26-27/380-1"
CODE_2  = "EJL/26-27/380-2"
DESIGN_1 = "JR07550"
DESIGN_2 = "JR08385"
TOKEN   = "YES_ASSIGN_PACKING_PRODUCT_CODE"


# ── fixtures / harness (mirrors test_proforma_readiness_single_authority) ──────

@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BATCH, "tracking_no": BATCH, "awb": BATCH,
         "carrier": "DHL", "timeline": []}), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op_headers():
    return {"X-Operator": "test-op", **_auth()}


def _packing_row(design_no, pos, product_code=None):
    return {
        "batch_id": BATCH, "invoice_no": INVOICE, "invoice_line_position": pos,
        "product_code": product_code, "design_no": design_no,
        "bag_id": "", "tray_id": "", "item_type": "RNG", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": float(pos), "unit_price": 50.0, "total_value": 50.0,
    }


def _seed_design_only_packing():
    """The defect: two pieces exist by DESIGN but product_code is NULL."""
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([
        _packing_row(DESIGN_1, 1, product_code=None),
        _packing_row(DESIGN_2, 2, product_code=None),
    ])


def _line(product_code, design_no):
    return {"line_id": str(uuid.uuid4()), "product_code": product_code,
            "design_no": design_no, "name_pl": "Pierścionek złoty",
            "unit_price": 100.0, "qty": 1.0, "quantity": 1.0, "currency": "EUR"}


def _seed_draft(storage, lines, status="draft"):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, status, "EUR", status,
             None, "", "[]", json.dumps(lines), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _readiness(c, draft_id, intent="approve"):
    r = c.get(f"/api/v1/proforma/draft/{draft_id}/readiness",
              params={"intent": intent}, headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()


def _overbill(readiness, code):
    for e in (readiness.get("duplicate_product_codes") or []):
        if e.get("product_code") == code and e.get("over_billed"):
            return e
    return None


def _assign(c, draft_id, design_no, product_code, headers=None, **body):
    payload = {"design_no": design_no, "product_code": product_code,
               "confirm_token": TOKEN, **body}
    return c.post(f"/api/v1/proforma/draft/{draft_id}/assign-packing-product-code",
                  json=payload, headers=_op_headers() if headers is None else headers)


def _events(storage, draft_id):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?",
            (draft_id,)).fetchall()
    return [r[0] for r in rows]


def _packing_codes(design):
    from app.services import packing_db as pdb
    return [r["product_code"] for r in pdb.get_packing_lines_for_batch(BATCH)
            if (r.get("design_no") or "").strip() == design]


# ── 0. sanity: the readiness authority surfaces the evidence ──────────────────

def test_readiness_surfaces_unassigned_evidence(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])
    e = _overbill(_readiness(c, did), CODE_1)
    assert e is not None
    assert e["available_qty"] == 0.0
    assert e["unassigned_packing"] == [
        {"design_no": DESIGN_1, "quantity": 1.0, "count": 1, "invoice_no": INVOICE}]


# ── 1. happy path: assign clears the over-bill on TRUE data ───────────────────

def test_assign_stamps_piece_and_clears_overbill(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])
    assert _overbill(_readiness(c, did), CODE_1) is not None

    r = _assign(c, did, DESIGN_1, CODE_1, expected_count=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["assignment"]["assigned"] == 1
    # packing row is now stamped
    assert _packing_codes(DESIGN_1) == [CODE_1]
    # over-bill blocker for CODE_1 has cleared (available now truly 1)
    assert _overbill(body["readiness"], CODE_1) is None
    assert _overbill(_readiness(c, did), CODE_1) is None
    # the OTHER design is untouched — still surfaced
    assert _overbill(_readiness(c, did), CODE_2) is not None


def test_assign_records_audit_event(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])
    _assign(c, did, DESIGN_1, CODE_1)
    assert "packing_product_code_assigned" in _events(storage, did)


# ── 2. auth / confirmation gates ──────────────────────────────────────────────

def test_bad_confirm_token_422(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1)])
    r = c.post(f"/api/v1/proforma/draft/{did}/assign-packing-product-code",
               json={"design_no": DESIGN_1, "product_code": CODE_1,
                     "confirm_token": "WRONG"}, headers=_op_headers())
    assert r.status_code == 422
    assert _packing_codes(DESIGN_1) == [None]  # nothing stamped


def test_missing_operator_400(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1)])
    r = _assign(c, did, DESIGN_1, CODE_1, headers=_auth())  # no X-Operator
    assert r.status_code == 400
    assert _packing_codes(DESIGN_1) == [None]


# ── 3. write is bound to surfaced evidence (no arbitrary assignment) ──────────

def test_arbitrary_code_not_surfaced_rejected(client):
    c, storage = client
    _seed_design_only_packing()
    # draft does not bill the arbitrary code → not over-billed → not surfaced
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1)])
    r = _assign(c, did, DESIGN_1, "EJL/26-27/999-9")
    assert r.status_code == 400
    assert "not a surfaced" in r.text.lower()
    assert _packing_codes(DESIGN_1) == [None]  # untouched


def test_expected_count_mismatch_conflict(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])
    r = _assign(c, did, DESIGN_1, CODE_1, expected_count=5)  # surfaced count is 1
    assert r.status_code == 409
    assert _packing_codes(DESIGN_1) == [None]


# ── 4. lifecycle guard ────────────────────────────────────────────────────────

def test_posted_draft_rejected_409(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1)], status="posted")
    r = _assign(c, did, DESIGN_1, CODE_1)
    assert r.status_code == 409
    assert _packing_codes(DESIGN_1) == [None]


def test_unknown_draft_404(client):
    c, storage = client
    _seed_design_only_packing()
    r = _assign(c, 999999, DESIGN_1, CODE_1)
    assert r.status_code == 404


# ── 5. idempotency ────────────────────────────────────────────────────────────

def test_second_assign_is_idempotent(client):
    c, storage = client
    _seed_design_only_packing()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])
    first = _assign(c, did, DESIGN_1, CODE_1)
    assert first.status_code == 200 and first.json()["assignment"]["assigned"] == 1
    second = _assign(c, did, DESIGN_1, CODE_1)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body.get("idempotent") is True
    assert body["assignment"]["assigned"] == 0
    assert _packing_codes(DESIGN_1) == [CODE_1]  # still exactly one stamp

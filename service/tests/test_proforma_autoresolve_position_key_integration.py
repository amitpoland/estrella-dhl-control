"""test_proforma_autoresolve_position_key_integration.py

End-to-end pins for the position-key deterministic auto-assign hook inside the
proforma readiness gate (``_derive_draft_readiness`` §4c). Exercises the REAL
write path — planner → canonical Part-2 writer → audit event → over-bill
re-evaluation — against real temp packing_db + document_db + proforma_links_db.

Proves, on the actual readiness route:
  * a design-only packing piece WITH a populated invoice_line_position is
    auto-assigned to the EXACT invoice-line code (not pack_sr order), and the
    over-bill blocker clears on TRUE data;
  * a reversed pack_sr does not change the result (position wins);
  * the original invoice-380 shape (positions NULL) is NOT auto-assigned — the
    over-bill blocker stays and the operator-confirmation UI remains required;
  * the hook is idempotent (a second readiness call stamps nothing new).
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

BATCH   = "BATCH_AUTORESOLVE_POSKEY"
CLIENT  = "AUTORESOLVE_CLIENT"
INVOICE = "EJL/26-27/380"
CODE_1  = "EJL/26-27/380-1"
CODE_2  = "EJL/26-27/380-2"
DESIGN_1 = "JR07550"
DESIGN_2 = "JR08385"


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


def _packing_row(design_no, pos, product_code=None, pack_sr=None):
    return {
        "batch_id": BATCH, "invoice_no": INVOICE, "invoice_line_position": pos,
        "product_code": product_code, "design_no": design_no,
        "bag_id": "", "tray_id": "", "item_type": "RNG", "uom": "PCS",
        "quantity": 1.0, "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": pack_sr if pack_sr is not None else (float(pos) if pos else None),
        "unit_price": 50.0, "total_value": 50.0,
    }


def _seed_packing(rows):
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines(rows)


def _seed_invoice_lines():
    """The import authority: 380-1 @ position 1, 380-2 @ position 2."""
    from app.services import document_db as ddb
    ddb.store_invoice_lines("DOC_380", BATCH, [
        {"invoice_no": INVOICE, "line_position": 1, "product_code": CODE_1,
         "quantity": 1.0},
        {"invoice_no": INVOICE, "line_position": 2, "product_code": CODE_2,
         "quantity": 1.0},
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


def _packing_code(design):
    from app.services import packing_db as pdb
    codes = {(r.get("product_code") or "").strip()
             for r in pdb.get_packing_lines_for_batch(BATCH)
             if (r.get("design_no") or "").strip() == design}
    return sorted(c for c in codes if c)   # only non-blank (assigned) codes


def _events(storage, draft_id):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        return [r[0] for r in conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?",
            (draft_id,)).fetchall()]


# ── position-key auto-assign clears the over-bill on the real route ──────────

def test_positionkey_autoassign_clears_overbill_and_audits(client):
    c, storage = client
    _seed_packing([_packing_row(DESIGN_1, 1, product_code=None),
                   _packing_row(DESIGN_2, 2, product_code=None)])
    _seed_invoice_lines()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])

    readiness = _readiness(c, did)

    # design-only rows are now stamped BY POSITION with the true codes
    assert _packing_code(DESIGN_1) == [CODE_1]
    assert _packing_code(DESIGN_2) == [CODE_2]
    # over-bill blockers cleared on real data (availability was real, not invented)
    assert _overbill(readiness, CODE_1) is None
    assert _overbill(readiness, CODE_2) is None
    # audit trail records the automatic assignment with its source authority
    assert "packing_product_code_auto_assigned" in _events(storage, did)


def test_reversed_pack_sr_still_assigns_by_position(client):
    c, storage = client
    # pack_sr REVERSED vs position: pos1 row has pack_sr 2, pos2 row pack_sr 1.
    _seed_packing([_packing_row(DESIGN_1, 1, product_code=None, pack_sr=2.0),
                   _packing_row(DESIGN_2, 2, product_code=None, pack_sr=1.0)])
    _seed_invoice_lines()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])

    _readiness(c, did)
    # position wins — DESIGN_1 (position 1) → CODE_1, not the pack_sr-1 code.
    assert _packing_code(DESIGN_1) == [CODE_1]
    assert _packing_code(DESIGN_2) == [CODE_2]


def test_null_position_380_falls_through_to_manual(client):
    c, storage = client
    # The original defect shape: positions NULL → NO deterministic key.
    _seed_packing([_packing_row(DESIGN_1, None, product_code=None),
                   _packing_row(DESIGN_2, None, product_code=None)])
    _seed_invoice_lines()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])

    readiness = _readiness(c, did)
    # nothing auto-assigned — the pieces stay design-only for the operator UI
    assert _packing_code(DESIGN_1) == []
    assert _packing_code(DESIGN_2) == []
    # over-bill blocker REMAINS, surfacing the unassigned-packing evidence
    e = _overbill(readiness, CODE_1)
    assert e is not None and e.get("unassigned_packing")
    assert "packing_product_code_auto_assigned" not in _events(storage, did)


def test_autoassign_is_idempotent(client):
    c, storage = client
    _seed_packing([_packing_row(DESIGN_1, 1, product_code=None),
                   _packing_row(DESIGN_2, 2, product_code=None)])
    _seed_invoice_lines()
    did = _seed_draft(storage, [_line(CODE_1, DESIGN_1), _line(CODE_2, DESIGN_2)])

    _readiness(c, did)
    first = _events(storage, did).count("packing_product_code_auto_assigned")
    readiness2 = _readiness(c, did)
    second = _events(storage, did).count("packing_product_code_auto_assigned")

    # a second readiness call finds nothing unassigned → no new stamp/event
    assert first == 1 and second == 1
    assert _overbill(readiness2, CODE_1) is None
    assert _packing_code(DESIGN_1) == [CODE_1]

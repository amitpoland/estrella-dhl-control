"""test_proforma_review_state_authority.py — PR-2.

Operator review state is the CURRENT authority that drives the review badge;
machine ``extracted_confidence`` is IMMUTABLE historical evidence. This suite
pins the separation across the three layers that implement it:

  Part A — packing_db writer + source_revision (real tmp DB):
    * compute_source_revision ignores product_code (the decision) and
      extracted_confidence (evidence); changes only on a real source change.
    * confirm_product_review stamps operator state and never touches machine
      evidence.
    * a confirmed mapping survives a plain re-import and is NEVER silently
      overwritten by a force re-extract (product_code preserved; review reopens
      via a changed source_revision).

  Part B — extraction read-model projection (mock draft, mirrors
    test_w4_item11_source_extraction): operator_status drives review_required /
    review_reason; a stale confirmed source_revision reopens review; machine
    confidence is surfaced as evidence unchanged.

  Part C — confirm endpoint E2E (TestClient, mirrors
    test_assign_packing_product_code_route): happy path + audit + auth/lifecycle
    gates; confirmation survives reload and a re-check (enrich) call.

Requested behaviours covered: confirmation survives reload (A2/C1), survives
re-check (A3/C6), changed source revision reopens review (A5/B2), unchanged
source revision preserves confirmation (A2/B1), confidence history unchanged
after confirmation (A4/B5).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# Part A — packing_db writer + source_revision (real tmp DB)
# ═══════════════════════════════════════════════════════════════════════════════

BATCH_A = "BATCH_REVIEW_STATE_A"
INV_A   = "EJL/26-27/500"


@pytest.fixture()
def pdb_db(tmp_path):
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")
    return pdb


def _pk_row(pack_sr, product_code, design="D-100", qty=1.0, conf=0.80,
            item_type="RNG", metal="AU", karat="14", unit_price=50.0, pos=None):
    return {
        "batch_id": BATCH_A, "invoice_no": INV_A,
        "invoice_line_position": pos, "product_code": product_code,
        "design_no": design, "bag_id": "", "tray_id": "", "item_type": item_type,
        "uom": "PCS", "quantity": qty, "gross_weight": 0.0, "net_weight": 0.0,
        "metal": metal, "karat": karat, "stone_type": "", "remarks": "",
        "extracted_confidence": conf, "requires_manual_review": conf < 0.60,
        "pack_sr": float(pack_sr), "unit_price": unit_price, "total_value": unit_price,
    }


def _codes(pdb, design=None):
    rows = pdb.get_packing_lines_for_batch(BATCH_A)
    return [r["product_code"] for r in rows
            if design is None or (r.get("design_no") or "") == design]


# ── A0. source_revision authority ──────────────────────────────────────────────

def test_source_revision_ignores_product_code(pdb_db):
    a = _pk_row(1, "CODE-A")
    b = dict(a); b["product_code"] = "CODE-B"
    assert pdb_db.compute_source_revision(a) == pdb_db.compute_source_revision(b)


def test_source_revision_ignores_confidence(pdb_db):
    a = _pk_row(1, "CODE-A", conf=0.30)
    b = dict(a); b["extracted_confidence"] = 0.99
    assert pdb_db.compute_source_revision(a) == pdb_db.compute_source_revision(b)


def test_source_revision_changes_on_quantity(pdb_db):
    a = _pk_row(1, "CODE-A", qty=1.0)
    b = dict(a); b["quantity"] = 2.0
    assert pdb_db.compute_source_revision(a) != pdb_db.compute_source_revision(b)


def test_source_revision_changes_on_design(pdb_db):
    a = _pk_row(1, "CODE-A", design="D-100")
    b = dict(a); b["design_no"] = "D-200"
    assert pdb_db.compute_source_revision(a) != pdb_db.compute_source_revision(b)


# ── A1. confirm writer stamps operator state ────────────────────────────────────

def test_confirm_stamps_operator_state(pdb_db):
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A"), _pk_row(2, "CODE-A")])
    res = pdb_db.confirm_product_review(BATCH_A, "CODE-A", "op-jane")
    assert res["confirmed"] == 2
    assert res["source_revision"]
    rows = pdb_db.get_packing_lines_for_batch(BATCH_A)
    for r in rows:
        assert r["operator_review_status"] == "confirmed"
        assert r["operator_confirmed_by"] == "op-jane"
        assert r["operator_confirmed_at"]
        assert r["operator_source_revision"] == pdb_db.compute_source_revision(r)


def test_confirm_requires_existing_product_code(pdb_db):
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A")])
    with pytest.raises(ValueError):
        pdb_db.confirm_product_review(BATCH_A, "CODE-MISSING", "op")


def test_confirm_blank_args_raise(pdb_db):
    with pytest.raises(ValueError):
        pdb_db.confirm_product_review(BATCH_A, "", "op")
    with pytest.raises(ValueError):
        pdb_db.confirm_product_review(BATCH_A, "CODE-A", "")


# ── A2/A4. confidence history unchanged; confirmation survives reload ────────────

def test_confirm_does_not_touch_machine_evidence(pdb_db):
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A", conf=0.42)])
    before = pdb_db.get_packing_lines_for_batch(BATCH_A)[0]
    pdb_db.confirm_product_review(BATCH_A, "CODE-A", "op")
    after = pdb_db.get_packing_lines_for_batch(BATCH_A)[0]
    # Machine EVIDENCE is immutable across confirmation.
    assert after["extracted_confidence"] == before["extracted_confidence"] == 0.42
    assert after["requires_manual_review"] == before["requires_manual_review"]
    # Operator authority is now recorded (survives the reload/read).
    assert after["operator_review_status"] == "confirmed"


# ── A3. confirmation survives a plain (non-forced) re-import ─────────────────────

def test_confirmation_survives_plain_reimport(pdb_db):
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A")])
    pdb_db.confirm_product_review(BATCH_A, "CODE-A", "op")
    # A plain re-import (force_reextract=False) skips existing rows entirely.
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A", conf=0.99)])
    row = pdb_db.get_packing_lines_for_batch(BATCH_A)[0]
    assert row["operator_review_status"] == "confirmed"
    assert row["product_code"] == "CODE-A"


# ── A5. force re-extract never silently overwrites; reopens via revision ─────────

def test_force_reextract_preserves_confirmed_product_code(pdb_db):
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A", qty=1.0)])
    pdb_db.confirm_product_review(BATCH_A, "CODE-A", "op")
    stored_rev = pdb_db.get_packing_lines_for_batch(BATCH_A)[0]["operator_source_revision"]

    # A re-extraction proposes a DIFFERENT product_code and a changed quantity.
    pdb_db.upsert_packing_lines(
        [_pk_row(1, "CODE-REEXTRACT", qty=2.0)], force_reextract=True)

    row = pdb_db.get_packing_lines_for_batch(BATCH_A)[0]
    # The operator's confirmed mapping is preserved — NOT silently overwritten.
    assert row["product_code"] == "CODE-A"
    # Other extracted fields still refreshed …
    assert row["quantity"] == 2.0
    # … so the current source_revision no longer matches the confirmed snapshot
    # → the read model will reopen review.
    assert pdb_db.compute_source_revision(row) != stored_rev
    assert row["operator_source_revision"] == stored_rev  # snapshot unchanged


def test_force_reextract_overwrites_unconfirmed_product_code(pdb_db):
    # Guard is scoped to confirmed rows: an UNconfirmed row still re-extracts.
    pdb_db.upsert_packing_lines([_pk_row(1, "CODE-A")])
    pdb_db.upsert_packing_lines(
        [_pk_row(1, "CODE-REEXTRACT")], force_reextract=True)
    assert _codes(pdb_db) == ["CODE-REEXTRACT"]


# ═══════════════════════════════════════════════════════════════════════════════
# Part B — extraction read-model projection (mock draft)
# ═══════════════════════════════════════════════════════════════════════════════

from app.api import routes_proforma  # noqa: E402


def _make_mock_draft(editable_lines: List[Dict[str, Any]]) -> MagicMock:
    d = MagicMock()
    d.editable_lines_json   = json.dumps(editable_lines, ensure_ascii=False)
    d.source_lines_json     = "[]"
    d.service_charges_json  = "[]"
    d.buyer_override_json    = "{}"
    d.ship_to_override_json  = "{}"
    d.payment_terms_json     = "{}"
    d.remarks = ""; d.notes = ""; d.exchange_rate = None
    d.status = "draft"; d.id = 1; d.batch_id = "BATCH-RM"; d.client_name = "ACME"
    d.currency = "EUR"; d.draft_state = "draft"; d.draft_version = 1
    d.wfirma_proforma_id = ""; d.wfirma_proforma_fullnumber = ""
    d.created_at = "2026-01-01T00:00:00Z"; d.updated_at = "2026-01-01T00:00:00Z"
    d.last_packing_sync_at = None; d.packing_sync_warning = None
    return d


def _run_extraction(monkeypatch, tmp_path, editable_lines, packing_lines,
                    product_masters):
    monkeypatch.setattr(routes_proforma.settings, "storage_root", tmp_path)
    (tmp_path / "reservation_queue.db").write_text("")
    monkeypatch.setattr(
        "app.services.reservation_db.list_product_masters",
        lambda _p: product_masters,
    )
    mock_draft = _make_mock_draft(editable_lines)
    with patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=mock_draft), \
         patch.object(routes_proforma, "_proforma_db_path", return_value=Path("/tmp/x.db")), \
         patch.object(routes_proforma, "_resolve_customer",
                      return_value={"found": True, "ambiguous": False,
                                    "match_strategy": "customer_master",
                                    "resolved_wfirma_name": "Acme", "candidates": []}), \
         patch.object(routes_proforma, "_enrich_customer_resolution_with_email",
                      lambda cr: None), \
         patch.object(routes_proforma.pdb, "get_packing_lines_for_batch",
                      return_value=packing_lines), \
         patch.object(routes_proforma.pdb, "get_packing_documents_for_batch",
                      return_value=[]):
        resp = routes_proforma.get_proforma_draft_extraction(draft_id=1)
    return json.loads(resp.body)


def _pl(product_code, **kw):
    base = {"batch_id": "BATCH-RM", "invoice_no": "INV", "invoice_line_position": None,
            "product_code": product_code, "design_no": "D-1", "item_type": "RNG",
            "metal": "AU", "karat": "14", "quantity": 1.0, "unit_price": 50.0,
            "pack_sr": 1.0, "extracted_confidence": 0.80, "requires_manual_review": 0,
            "operator_review_status": None, "operator_confirmed_at": None,
            "operator_confirmed_by": None, "operator_source_revision": None}
    base.update(kw)
    return base


def test_readmodel_confirmed_clean_badge(monkeypatch, tmp_path):
    """B1 — confirmed with a matching source_revision → Operator confirmed, no reopen."""
    from app.services import packing_db as pdb
    pl = _pl("CODE-A")
    pl["operator_review_status"] = "confirmed"
    pl["operator_confirmed_by"] = "op-jane"
    pl["operator_source_revision"] = pdb.compute_source_revision(pl)  # current == stored
    body = _run_extraction(
        monkeypatch, tmp_path,
        editable_lines=[{"product_code": "CODE-A", "qty": 1.0, "name_pl": "Ring"}],
        packing_lines=[pl],
        product_masters=[{"product_code": "CODE-A", "item_type": "ring"}])
    ln = body["lines"][0]
    assert ln["operator_status"] == "confirmed"
    assert ln["operator_confirmed_by"] == "op-jane"
    assert ln["review_required"] is False
    assert ln["review_reason"] is None
    # machine confidence surfaced as evidence, unchanged.
    assert ln["machine_confidence"] == 0.80
    assert ln["extracted_confidence"] == 0.80


def test_readmodel_confirmed_source_changed_reopens(monkeypatch, tmp_path):
    """B2 — confirmed but the source_revision is now stale → Re-check required."""
    pl = _pl("CODE-A")
    pl["operator_review_status"] = "confirmed"
    pl["operator_confirmed_by"] = "op-jane"
    pl["operator_source_revision"] = "STALE_REVISION_0000"  # != current
    body = _run_extraction(
        monkeypatch, tmp_path,
        editable_lines=[{"product_code": "CODE-A", "qty": 1.0, "name_pl": "Ring"}],
        packing_lines=[pl],
        product_masters=[{"product_code": "CODE-A", "item_type": "ring"}])
    ln = body["lines"][0]
    assert ln["operator_status"] == "confirmed"      # decision NOT erased
    assert ln["review_required"] is True
    assert ln["review_reason"] == "source_changed"
    assert ln["machine_confidence"] == 0.80          # evidence untouched


def test_readmodel_matched_unconfirmed_is_suggested(monkeypatch, tmp_path):
    """Matched-but-unconfirmed is advisory 'suggested', NOT operator-confirmed."""
    body = _run_extraction(
        monkeypatch, tmp_path,
        editable_lines=[{"product_code": "CODE-A", "qty": 1.0, "name_pl": "Ring"}],
        packing_lines=[_pl("CODE-A", extracted_confidence=0.90)],
        product_masters=[{"product_code": "CODE-A", "item_type": "ring"}])
    ln = body["lines"][0]
    assert ln["operator_status"] is None
    assert ln["review_required"] is False
    assert ln["review_reason"] is None
    assert ln["product_matched"] is True


def test_readmodel_unmapped_overrides(monkeypatch, tmp_path):
    """A line whose code is not in Product Master → unmapped review reason."""
    body = _run_extraction(
        monkeypatch, tmp_path,
        editable_lines=[{"product_code": "CODE-X", "qty": 1.0, "name_pl": "Ring"}],
        packing_lines=[_pl("CODE-X")],
        product_masters=[])  # empty PM → unmatched
    ln = body["lines"][0]
    assert ln["product_matched"] is False
    assert ln["review_required"] is True
    assert ln["review_reason"] == "unmapped"


# ═══════════════════════════════════════════════════════════════════════════════
# Part C — confirm endpoint E2E (TestClient)
# ═══════════════════════════════════════════════════════════════════════════════

BATCH_C = "BATCH_REVIEW_STATE_C"
CLIENT_C = "REVIEW_CLIENT"
INV_C = "EJL/26-27/600"
CODE_C = "EJL/26-27/600-1"
DESIGN_C = "D-600"


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

    out = tmp_path / "outputs" / BATCH_C
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BATCH_C, "tracking_no": BATCH_C, "awb": BATCH_C,
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


def _seed_packing(product_code=CODE_C):
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([{
        "batch_id": BATCH_C, "invoice_no": INV_C, "invoice_line_position": 1,
        "product_code": product_code, "design_no": DESIGN_C, "bag_id": "",
        "tray_id": "", "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": 0.0, "net_weight": 0.0, "metal": "AU", "karat": "14",
        "stone_type": "", "remarks": "", "extracted_confidence": 0.55,
        "requires_manual_review": True, "pack_sr": 1.0, "unit_price": 50.0,
        "total_value": 50.0,
    }])


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
            (BATCH_C, CLIENT_C, status, "EUR", status, None, "", "[]",
             json.dumps(lines), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _line(product_code, design_no):
    return {"line_id": str(uuid.uuid4()), "product_code": product_code,
            "design_no": design_no, "name_pl": "Pierścionek",
            "unit_price": 100.0, "qty": 1.0, "quantity": 1.0, "currency": "EUR"}


def _confirm(c, draft_id, product_code, headers=None, **body):
    payload = {"product_code": product_code, **body}
    return c.post(f"/api/v1/proforma/draft/{draft_id}/confirm-product-review",
                  json=payload, headers=_op_headers() if headers is None else headers)


def _packing_status(product_code=CODE_C):
    from app.services import packing_db as pdb
    return [r["operator_review_status"]
            for r in pdb.get_packing_lines_for_batch(BATCH_C)
            if (r.get("product_code") or "") == product_code]


def _events(storage, draft_id):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?",
            (draft_id,)).fetchall()
    return [r[0] for r in rows]


# ── C1. happy path — confirm stamps, is audited, survives reload ────────────────

def test_confirm_endpoint_happy_path(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage, [_line(CODE_C, DESIGN_C)])
    r = _confirm(c, did, CODE_C)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["confirmation"]["confirmed"] == 1
    # Reload (fresh read) still shows confirmed.
    assert _packing_status() == ["confirmed"]
    assert "product_review_confirmed" in _events(storage, did)


# ── C2–C5. auth / input / lifecycle gates ───────────────────────────────────────

def test_confirm_missing_operator_400(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage, [_line(CODE_C, DESIGN_C)])
    r = _confirm(c, did, CODE_C, headers=_auth())  # no X-Operator
    assert r.status_code == 400
    assert _packing_status() == [None]


def test_confirm_unknown_draft_404(client):
    c, storage = client
    _seed_packing()
    r = _confirm(c, 999999, CODE_C)
    assert r.status_code == 404


def test_confirm_posted_draft_409(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage, [_line(CODE_C, DESIGN_C)], status="posted")
    r = _confirm(c, did, CODE_C)
    assert r.status_code == 409
    assert _packing_status() == [None]


def test_confirm_unmapped_code_400(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage, [_line(CODE_C, DESIGN_C)])
    r = _confirm(c, did, "NO-SUCH-CODE")   # no packing row carries this code
    assert r.status_code == 400
    assert _packing_status() == [None]


# ── C6. confirmation survives a re-check (enrich) call ──────────────────────────

def test_confirm_survives_recheck(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage, [_line(CODE_C, DESIGN_C)])
    assert _confirm(c, did, CODE_C).status_code == 200
    assert _packing_status() == ["confirmed"]

    # Re-check mapping == enrich-from-product-descriptions (draft-side annotation).
    d = c.get(f"/api/v1/proforma/draft/{did}", headers=_auth()).json()["draft"]
    r = c.post(f"/api/v1/proforma/draft/{did}/enrich-from-product-descriptions",
               json={"expected_updated_at": d["updated_at"]}, headers=_op_headers())
    assert r.status_code == 200, r.text
    # The operator confirmation is untouched by re-check.
    assert _packing_status() == ["confirmed"]

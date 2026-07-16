"""test_proforma_weight_override.py — PR-5 transport-document weight override.

The extracted packing weight (packing_lines, grams) stays the historical
authority; the operator manual override (kg) becomes the effective value only
through POST /weight-override. Clear restores the extracted value; a re-import
that changes the extracted source flags drift WITHOUT overwriting the override.

Covers required tests 5 (extracted surfaced), 7 (override persists after reload),
8 (re-import preserves override), 9 (source-revision drift flagged), 10 (clear
restores), 11 (invalid → 422), 12 (stale lock → 409).
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ROOT = pathlib.Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BATCH = "BATCH_PR5_WEIGHT"
CLIENT = "PR5_CLIENT"
INV = "EJL/26-27/700"


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
        {"batch_id": BATCH, "tracking_no": BATCH, "awb": BATCH, "carrier": "DHL",
         "timeline": []}), encoding="utf-8")
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


def _op():
    return {"X-Operator": "test-op", **_auth()}


def _seed_packing(net_g=2010.0, gross_g=2500.0, pack_sr=1):
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([{
        "batch_id": BATCH, "invoice_no": INV, "invoice_line_position": pack_sr,
        "product_code": "EJL/1", "design_no": "D1", "bag_id": "", "tray_id": "",
        "item_type": "RNG", "uom": "PCS", "quantity": 1.0,
        "gross_weight": gross_g, "net_weight": net_g, "metal": "AU", "karat": "14",
        "stone_type": "", "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": float(pack_sr),
        "unit_price": 50.0, "total_value": 50.0,
    }], force_reextract=True)


def _seed_draft(storage, status="draft"):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, status, "EUR", status, None, "", "[]",
             json.dumps([{"line_id": "L1", "product_code": "EJL/1", "design_no": "D1",
                          "qty": 1.0, "unit_price": 100.0, "currency": "EUR"}]),
             "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _get(c, did):
    r = c.get(f"/api/v1/proforma/draft/{did}", headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _set(c, did, body, headers=None):
    return c.post(f"/api/v1/proforma/draft/{did}/weight-override",
                  json=body, headers=headers if headers is not None else _op())


def _clear(c, did, updated_at):
    return c.post(f"/api/v1/proforma/draft/{did}/clear-weight-override",
                  json={"expected_updated_at": updated_at}, headers=_op())


def _events(storage, did):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        return [r[0] for r in conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?", (did,)).fetchall()]


# ── 5 + 7: extracted surfaced; override persists after reload ─────────────────

def test_override_persists_and_extracted_surfaced(client):
    c, storage = client
    _seed_packing(net_g=2010.0, gross_g=2500.0)
    did = _seed_draft(storage)
    d = _get(c, did)
    # extracted source revision is present before any override
    assert d["weight_source_revision_current"]
    r = _set(c, did, {"expected_updated_at": d["updated_at"],
                      "manual_net_weight": 1.25, "manual_gross_weight": 1.60,
                      "reason": "scale reading"})
    assert r.status_code == 200, r.text
    dd = _get(c, did)   # reload
    assert dd["manual_net_weight"] == 1.25
    assert dd["manual_gross_weight"] == 1.60
    assert dd["weight_override_reason"] == "scale reading"
    assert dd["weight_confirmed_by"] == "test-op"
    assert dd["weight_source_revision"]                     # snapshot stored
    assert dd["weight_override_source"] == "manual"         # provenance
    assert "weight_override_set" in _events(storage, did)


def test_override_only_net(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "manual_net_weight": 0.9})
    assert r.status_code == 200, r.text
    dd = _get(c, did)
    assert dd["manual_net_weight"] == 0.9 and dd["manual_gross_weight"] is None


# ── 11: invalid → 422, no write ───────────────────────────────────────────────

def test_negative_weight_422(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "manual_net_weight": -1})
    assert r.status_code == 422, r.text
    assert _get(c, did)["manual_net_weight"] is None


def test_non_numeric_weight_422(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "manual_gross_weight": "heavy"})
    assert r.status_code == 422, r.text


def test_no_weight_supplied_422(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "reason": "x"})
    assert r.status_code == 422, r.text


def test_missing_operator_400(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "manual_net_weight": 1.0},
             headers=_auth())
    assert r.status_code == 400


# ── 12: stale lock → 409 ──────────────────────────────────────────────────────

def test_stale_lock_409(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    r = _set(c, did, {"expected_updated_at": "2000-01-01T00:00:00+00:00",
                      "manual_net_weight": 1.0})
    assert r.status_code == 409, r.text
    assert _get(c, did)["manual_net_weight"] is None


# ── 10: clear restores extracted ──────────────────────────────────────────────

def test_clear_restores_extracted(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    _set(c, did, {"expected_updated_at": d["updated_at"], "manual_net_weight": 1.25})
    dd = _get(c, did)
    r = _clear(c, did, dd["updated_at"])
    assert r.status_code == 200, r.text
    ddd = _get(c, did)
    assert ddd["manual_net_weight"] is None
    assert ddd["manual_gross_weight"] is None
    assert ddd["weight_source_revision"] is None
    assert ddd["weight_override_source"] == "cleared"       # provenance of last action
    assert "weight_override_cleared" in _events(storage, did)


# ── 8 + 9: re-import preserves override + flags source-revision drift ──────────

def test_reimport_preserves_override_and_flags_drift(client):
    c, storage = client
    _seed_packing(net_g=2010.0, gross_g=2500.0)
    did = _seed_draft(storage)
    d = _get(c, did)
    _set(c, did, {"expected_updated_at": d["updated_at"], "manual_net_weight": 1.25})
    confirmed_rev = _get(c, did)["weight_source_revision"]
    assert confirmed_rev

    # Re-import the packing with a DIFFERENT extracted weight (source changed).
    _seed_packing(net_g=3333.0, gross_g=4000.0)
    dd = _get(c, did)
    # Override is preserved (not overwritten) …
    assert dd["manual_net_weight"] == 1.25
    assert dd["weight_source_revision"] == confirmed_rev        # snapshot unchanged
    # … and the current extracted revision now differs → drift is detectable.
    assert dd["weight_source_revision_current"] != confirmed_rev


# ── Tare weight (2026-07-16 additive layer) ──────────────────────────────────

def test_tare_persists_and_clears(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"],
                      "manual_net_weight": 1.20, "manual_tare_weight": 0.30})
    assert r.status_code == 200, r.text
    dd = _get(c, did)
    assert dd["manual_tare_weight"] == 0.30
    assert dd["tare_weight_source"] == "manual"
    # Clear restores extracted (tare removed too).
    r = _clear(c, did, dd["updated_at"])
    assert r.status_code == 200, r.text
    ddd = _get(c, did)
    assert ddd["manual_tare_weight"] is None
    assert ddd["tare_weight_source"] == "cleared"


def test_tare_only_save_allowed(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "manual_tare_weight": 0.25})
    assert r.status_code == 200, r.text
    assert _get(c, did)["manual_tare_weight"] == 0.25


def test_no_weight_incl_tare_422(client):
    c, storage = client
    _seed_packing()
    did = _seed_draft(storage)
    d = _get(c, did)
    # reason only, no net/gross/tare → still 422
    r = _set(c, did, {"expected_updated_at": d["updated_at"], "reason": "x"})
    assert r.status_code == 422

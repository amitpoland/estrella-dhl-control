"""test_proforma_wfirma_cancel.py — POST /api/v1/proforma/draft/{id}/cancel-wfirma

Regression for: wFirma proforma cancellation workflow.

Tests:
  1. Can cancel a wFirma-linked posted draft (mock wFirma OK)
  2. Successful cancellation writes wfirma_cancelled audit event
  3. Cancelled draft remains visible in drafts list (not deleted)
  4. Failed wFirma cancellation does not change local state (mock wFirma error)
  5. Cannot cancel a draft with no wFirma proforma ID (409)
  6. Cannot cancel an already wfirma_cancelled draft (409)
  7. Missing confirm=true returns 400
  8. Missing X-Operator header returns 400
  9. Non-existent draft returns 404
 10. Cannot purge a wFirma-linked draft (409 — purge guards unchanged)
"""
from __future__ import annotations

import json
import sqlite3
import sys
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

_WFIRMA_CLIENT_PATH = "app.services.wfirma_client.delete_invoice"
_SETTINGS_PATH      = "app.api.routes_proforma.settings"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    # Enable the wFirma delete gate so tests can exercise the path.
    monkeypatch.setattr(settings, "wfirma_delete_invoice_allowed", True, raising=False)
    from app.main import app
    from app.services import document_db as ddb
    from app.services import packing_db  as pdb
    from app.services import wfirma_db   as wfdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return TestClient(app), tmp_path


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "proforma_links.db"


def _seed_batch(tmp_path: Path, batch_id: str = "B-WFC-1") -> str:
    out = tmp_path / "outputs" / batch_id
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id


def _seed_draft(
    tmp_path: Path,
    batch_id: str,
    *,
    draft_state: str = "posted",
    wfirma_proforma_id: str | None = "477781731",
    wfirma_proforma_fullnumber: str = "PROF 99/2026",
) -> int:
    db = _db_path(tmp_path)
    from app.services import proforma_invoice_link_db as pildb
    pildb.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (batch_id, "TESTCLIENT", "draft", "EUR", draft_state,
             wfirma_proforma_id, wfirma_proforma_fullnumber,
             "[]", "[]", "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _op_headers() -> dict:
    return {"X-Operator": "test-operator"}


def _wfirma_ok(invoice_id: str):
    return {"ok": True, "wfirma_invoice_id": invoice_id}


# ── 1. Can cancel a posted wFirma-linked draft ────────────────────────────────

def test_can_cancel_wfirma_linked_draft(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-OK")
    did = _seed_draft(tmp, bid, draft_state="posted", wfirma_proforma_id="111")

    with patch(_WFIRMA_CLIENT_PATH, return_value=_wfirma_ok("111")):
        r = c.post(
            f"/api/v1/proforma/draft/{did}/cancel-wfirma",
            json={"confirm": True},
            headers=_op_headers(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["new_state"] == "wfirma_cancelled"
    assert body["wfirma_invoice_id"] == "111"


# ── 2. Successful cancellation writes audit event ─────────────────────────────

def test_cancellation_writes_audit_event(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-EVENT")
    did = _seed_draft(tmp, bid, draft_state="posted", wfirma_proforma_id="222")

    with patch(_WFIRMA_CLIENT_PATH, return_value=_wfirma_ok("222")):
        c.post(
            f"/api/v1/proforma/draft/{did}/cancel-wfirma",
            json={"confirm": True},
            headers=_op_headers(),
        )

    with sqlite3.connect(str(_db_path(tmp))) as conn:
        conn.row_factory = sqlite3.Row
        events = conn.execute(
            "SELECT event, detail_json, operator FROM proforma_draft_events "
            "WHERE draft_id=? ORDER BY id DESC LIMIT 1",
            (did,),
        ).fetchall()

    assert len(events) == 1
    assert events[0]["event"] == "wfirma_cancelled"
    assert events[0]["operator"] == "test-operator"
    detail = json.loads(events[0]["detail_json"])
    assert detail["wfirma_invoice_id"] == "222"


# ── 3. Cancelled draft remains visible in list (not deleted) ──────────────────

def test_cancelled_draft_remains_in_list(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-VISIBLE")
    did = _seed_draft(tmp, bid, draft_state="posted", wfirma_proforma_id="333")

    with patch(_WFIRMA_CLIENT_PATH, return_value=_wfirma_ok("333")):
        c.post(
            f"/api/v1/proforma/draft/{did}/cancel-wfirma",
            json={"confirm": True},
            headers=_op_headers(),
        )

    drafts = c.get(f"/api/v1/proforma/drafts/{bid}").json()
    ids = [d["id"] for d in drafts.get("drafts", [])]
    assert did in ids, "wfirma_cancelled draft must remain visible for accounting traceability"

    state = next(d["draft_state"] for d in drafts["drafts"] if d["id"] == did)
    assert state == "wfirma_cancelled"


# ── 4. Failed wFirma call does not change local state ─────────────────────────

def test_failed_wfirma_call_does_not_change_state(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-FAIL")
    did = _seed_draft(tmp, bid, draft_state="posted", wfirma_proforma_id="444")

    with patch(_WFIRMA_CLIENT_PATH, side_effect=RuntimeError("wFirma API down")):
        r = c.post(
            f"/api/v1/proforma/draft/{did}/cancel-wfirma",
            json={"confirm": True},
            headers=_op_headers(),
        )
    assert r.status_code == 502, r.text
    assert "wFirma cancellation failed" in r.json()["detail"]
    assert "local state unchanged" in r.json()["detail"]

    # Verify state is still 'posted'
    with sqlite3.connect(str(_db_path(tmp))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT draft_state FROM proforma_drafts WHERE id=?", (did,)
        ).fetchone()
    assert row["draft_state"] == "posted"


# ── 5. Cannot cancel a draft with no wFirma proforma ID ──────────────────────

def test_cannot_cancel_draft_without_wfirma_id(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-NOID")
    did = _seed_draft(tmp, bid, draft_state="posted", wfirma_proforma_id=None,
                      wfirma_proforma_fullnumber="")

    r = c.post(
        f"/api/v1/proforma/draft/{did}/cancel-wfirma",
        json={"confirm": True},
        headers=_op_headers(),
    )
    assert r.status_code == 409, r.text
    assert "no wFirma proforma id" in r.json()["detail"]


# ── 6. Cannot cancel an already wfirma_cancelled draft ───────────────────────

def test_cannot_cancel_already_wfirma_cancelled(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-ALREADY")
    did = _seed_draft(tmp, bid, draft_state="wfirma_cancelled",
                      wfirma_proforma_id="555")

    r = c.post(
        f"/api/v1/proforma/draft/{did}/cancel-wfirma",
        json={"confirm": True},
        headers=_op_headers(),
    )
    assert r.status_code == 409, r.text
    assert "wfirma_cancelled" in r.json()["detail"]


# ── 7. Missing confirm=true returns 400 ──────────────────────────────────────

def test_missing_confirm_returns_400(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-NOCONFIRM")
    did = _seed_draft(tmp, bid)

    r = c.post(
        f"/api/v1/proforma/draft/{did}/cancel-wfirma",
        json={},
        headers=_op_headers(),
    )
    assert r.status_code == 400, r.text
    assert "confirm" in r.json()["detail"]


# ── 8. Missing X-Operator returns 400 ────────────────────────────────────────

def test_missing_operator_returns_400(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-NOOP")
    did = _seed_draft(tmp, bid)

    r = c.post(
        f"/api/v1/proforma/draft/{did}/cancel-wfirma",
        json={"confirm": True},
    )
    assert r.status_code == 400, r.text


# ── 9. Non-existent draft returns 404 ────────────────────────────────────────

def test_nonexistent_draft_returns_404(client):
    c, tmp = client
    _seed_batch(tmp, "B-WFC-404")

    r = c.post(
        "/api/v1/proforma/draft/99999/cancel-wfirma",
        json={"confirm": True},
        headers=_op_headers(),
    )
    assert r.status_code == 404, r.text


# ── 10. Purge-guard cross-check (DB layer) ────────────────────────────────────
# The HTTP-level guard lives in the DELETE /draft/{id} route added by PR #553.
# That route is not on origin/main; we verify the DB-layer exception directly.

def test_cannot_purge_wfirma_linked_draft_db_layer(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-WFC-NOPURGE")
    did = _seed_draft(tmp, bid, draft_state="cancelled", wfirma_proforma_id="666")

    from app.services import proforma_invoice_link_db as pildb
    db = _db_path(tmp)
    # purge_cancelled_draft raises DraftNotEditable for wFirma-linked drafts
    if not hasattr(pildb, "purge_cancelled_draft"):
        pytest.skip("purge_cancelled_draft not available on this branch — tested in PR #553")
    with pytest.raises(pildb.DraftNotEditable, match="wFirma proforma id"):
        pildb.purge_cancelled_draft(db, did, "test-operator")

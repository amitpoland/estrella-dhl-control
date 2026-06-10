"""test_proforma_purge_cancelled.py — DELETE /api/v1/proforma/draft/{id}

Regression for: hard-delete of local-only cancelled proforma drafts.

Tests:
  1. Can delete a cancelled local-only draft (200 / ok=True)
  2. Cannot delete a draft in 'draft' state (409)
  3. Cannot delete a draft in 'posted' state (409)
  4. Cannot delete a draft that has a wFirma proforma ID (409)
  5. Cannot delete a draft that has a PROF fullnumber (409)
  6. Deleting a non-existent draft returns 404
  7. Deleted draft no longer appears in the drafts list for the batch
  8. Missing X-Operator header returns 400
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    from app.services import wfirma_db as wfdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return TestClient(app), tmp_path


def _seed_batch(tmp_path: Path, batch_id: str = "B-PURGE-1") -> str:
    out = tmp_path / "outputs" / batch_id
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "proforma_links.db"


def _seed_draft(
    tmp_path: Path,
    batch_id: str,
    *,
    draft_state: str = "cancelled",
    wfirma_proforma_id: str | None = None,
    wfirma_proforma_fullnumber: str = "",
) -> int:
    """Insert a minimal draft row directly into the DB and return its id."""
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


# ── 1. Can delete a cancelled local-only draft ────────────────────────────────

def test_can_delete_cancelled_local_only_draft(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-OK")
    did = _seed_draft(tmp, bid, draft_state="cancelled")

    r = c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["purged_draft_id"] == did


# ── 2. Cannot delete draft in 'draft' state ───────────────────────────────────

def test_cannot_delete_draft_state(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-DRAFT")
    did = _seed_draft(tmp, bid, draft_state="draft")

    r = c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())
    assert r.status_code == 409, r.text
    assert "purge requires state='cancelled'" in r.json()["detail"]


# ── 3. Cannot delete draft in 'posted' state ─────────────────────────────────

def test_cannot_delete_posted_draft(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-POSTED")
    did = _seed_draft(tmp, bid, draft_state="posted",
                      wfirma_proforma_id="WF-123")

    r = c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())
    assert r.status_code == 409, r.text


# ── 4. Cannot delete draft with a wFirma proforma ID ─────────────────────────

def test_cannot_delete_draft_with_wfirma_id(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-WFID")
    did = _seed_draft(tmp, bid, draft_state="cancelled",
                      wfirma_proforma_id="477781731")

    r = c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())
    assert r.status_code == 409, r.text
    assert "wFirma proforma id" in r.json()["detail"]


# ── 5. Cannot delete draft with a PROF fullnumber ────────────────────────────

def test_cannot_delete_draft_with_prof_number(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-PROF")
    did = _seed_draft(tmp, bid, draft_state="cancelled",
                      wfirma_proforma_fullnumber="PROF 123/2026")

    r = c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())
    assert r.status_code == 409, r.text
    assert "proforma number" in r.json()["detail"]


# ── 6. Non-existent draft returns 404 ────────────────────────────────────────

def test_nonexistent_draft_returns_404(client):
    c, tmp = client
    _seed_batch(tmp, "B-PURGE-404")

    r = c.delete("/api/v1/proforma/draft/99999", headers=_op_headers())
    assert r.status_code == 404, r.text


# ── 7. Deleted draft disappears from drafts list ─────────────────────────────

def test_deleted_draft_absent_from_list(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-LIST")
    did = _seed_draft(tmp, bid, draft_state="cancelled")

    # Confirm it appears before deletion
    list_before = c.get(f"/api/v1/proforma/drafts/{bid}").json()
    ids_before = [d["id"] for d in list_before.get("drafts", [])]
    assert did in ids_before, f"draft {did} should be in list before purge"

    c.delete(f"/api/v1/proforma/draft/{did}", headers=_op_headers())

    list_after = c.get(f"/api/v1/proforma/drafts/{bid}").json()
    ids_after = [d["id"] for d in list_after.get("drafts", [])]
    assert did not in ids_after, f"draft {did} must not appear after purge"


# ── 8. Missing X-Operator returns 400 ────────────────────────────────────────

def test_missing_operator_returns_400(client):
    c, tmp = client
    bid = _seed_batch(tmp, "B-PURGE-OP")
    did = _seed_draft(tmp, bid, draft_state="cancelled")

    r = c.delete(f"/api/v1/proforma/draft/{did}")
    assert r.status_code == 400, r.text

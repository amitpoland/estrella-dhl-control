"""test_upload_sad_blocked_status.py — SAD re-upload allowed on non-draft batches.

Regression for: operator could not upload SAD when batch status was 'blocked'
because the guard only allowed 'draft' / 'in_preparation'.

Tests:
  1. blocked_status_allows_sad_reupload
     — POST /api/v1/upload/shipment/{id}/sad returns 200 when status='blocked'
  2. blocked_status_does_not_advance_to_ready
     — After re-upload on a blocked batch, status stays 'blocked'
  3. draft_status_still_advances_to_ready
     — Normal first-upload on draft → status becomes 'ready'
  4. ready_status_allows_sad_replacement
     — Replacing SAD on a 'ready' batch returns 200 and keeps status 'ready'
  5. terminal_statuses_rejected
     — completed / exported / closed / pz_generated return 409
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# description_grammar lives in C:\PZ\engine — add it so TestClient app import works
_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",   # C:\PZ\engine (production)
    Path(__file__).parent.parent.parent.parent / "engine",  # one level higher
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


def _pdf():
    return io.BytesIO(b"%PDF-1.4\n%test\n")


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


def _seed_batch(tmp_path: Path, batch_id: str, status: str) -> Path:
    out = tmp_path / "outputs" / batch_id
    (out / "source" / "sad").mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id": batch_id, "awb": "1234567890",
        "tracking_no": "1234567890", "carrier": "DHL",
        "status": status, "inputs": {}, "timeline": [],
    }
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _read_audit(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "audit.json").read_text(encoding="utf-8"))


# ── 1. blocked → upload allowed ───────────────────────────────────────────────

def test_blocked_status_allows_sad_reupload(client):
    c, tmp = client
    bid = "BATCH-BLOCKED-1"
    batch_dir = _seed_batch(tmp, bid, "blocked")

    r = c.post(
        f"/api/v1/upload/shipment/{bid}/sad",
        files={"sad": ("SAD38778.pdf", _pdf(), "application/pdf")},
    )
    assert r.status_code == 200, f"Expected 200 for blocked batch, got {r.status_code}: {r.text}"
    assert r.json()["sad"] == "SAD38778.pdf"


# ── 2. blocked → status stays blocked after re-upload ─────────────────────────

def test_blocked_status_does_not_advance_to_ready(client):
    c, tmp = client
    bid = "BATCH-BLOCKED-2"
    batch_dir = _seed_batch(tmp, bid, "blocked")

    c.post(
        f"/api/v1/upload/shipment/{bid}/sad",
        files={"sad": ("ZC429.pdf", _pdf(), "application/pdf")},
    )
    audit = _read_audit(batch_dir)
    assert audit["status"] == "blocked", (
        f"Re-uploading SAD on a blocked batch must keep status='blocked', got {audit['status']!r}"
    )
    assert audit["inputs"]["zc429"] == "ZC429.pdf"


# ── 3. draft → ready (existing behavior unchanged) ────────────────────────────

def test_draft_status_still_advances_to_ready(client):
    c, tmp = client
    bid = "BATCH-DRAFT-1"
    batch_dir = _seed_batch(tmp, bid, "draft")

    r = c.post(
        f"/api/v1/upload/shipment/{bid}/sad",
        files={"sad": ("sad.pdf", _pdf(), "application/pdf")},
    )
    assert r.status_code == 200
    audit = _read_audit(batch_dir)
    assert audit["status"] == "ready"


# ── 4. ready → replacement allowed, status stays ready ────────────────────────

def test_ready_status_allows_sad_replacement(client):
    c, tmp = client
    bid = "BATCH-READY-1"
    batch_dir = _seed_batch(tmp, bid, "ready")

    r = c.post(
        f"/api/v1/upload/shipment/{bid}/sad",
        files={"sad": ("SAD_corrected.pdf", _pdf(), "application/pdf")},
    )
    assert r.status_code == 200
    audit = _read_audit(batch_dir)
    assert audit["status"] == "ready"
    assert audit["inputs"]["zc429"] == "SAD_corrected.pdf"


# ── 5. terminal statuses still rejected ───────────────────────────────────────

@pytest.mark.parametrize("status", [
    "completed", "exported", "closed", "pz_generated", "wfirma_exported",
])
def test_terminal_statuses_rejected(client, status):
    c, tmp = client
    bid = f"BATCH-{status.upper()}-1"
    _seed_batch(tmp, bid, status)

    r = c.post(
        f"/api/v1/upload/shipment/{bid}/sad",
        files={"sad": ("sad.pdf", _pdf(), "application/pdf")},
    )
    assert r.status_code == 409, (
        f"Expected 409 for terminal status={status!r}, got {r.status_code}"
    )

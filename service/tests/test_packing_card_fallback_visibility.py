"""test_packing_card_fallback_visibility.py — 2026-05-17 hotfix regression.

Packing List card was rendering "No packing list uploaded yet" for
Atlas-uploaded batches whose extraction failed (or produced zero rows)
because the card reads packing_documents/packing_lines and intake had
only populated shipment_documents.

Fix: GET /api/v1/packing/{batch_id} now falls back to shipment_documents
when packing_documents is empty, returning shaped rows flagged
fallback_unparsed=true so the UI shows "Uploaded — extraction pending"
instead of empty state.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    # The packing route uses session auth (get_current_user). Override the
    # dependency to a no-op so we can hit it without a session cookie.
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "email": "test@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _seed_shipment_doc(tmp_path: Path, batch_id: str, document_type: str,
                       file_name: str, file_hash: str = "") -> None:
    """Insert a row into shipment_documents only (no packing_documents)."""
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    ddb.register_document(
        batch_id=batch_id, document_type=document_type,
        file_name=file_name, file_path=f"/tmp/{file_name}",
        file_hash=file_hash or f"hash-{file_name}",
        source="intake",
    )


def _make_batch_folder(tmp_path: Path, batch_id: str) -> None:
    """The route validates the batch folder exists."""
    (tmp_path / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)


# ── Scenarios ─────────────────────────────────────────────────────────────

def test_no_documents_at_all_returns_empty(client):
    cli, tmp = client
    _make_batch_folder(tmp, "B-EMPTY-1")
    r = cli.get("/api/v1/packing/B-EMPTY-1")
    assert r.status_code == 200
    body = r.json()
    assert body["documents"] == []
    assert body["packing_lines"] == []


def test_fallback_row_when_purchase_packing_uploaded_but_unparsed(client):
    cli, tmp = client
    bid = "B-PP-1"
    _make_batch_folder(tmp, bid)
    _seed_shipment_doc(tmp, bid, "purchase_packing_list", "pack1.xlsx")

    r = cli.get(f"/api/v1/packing/{bid}")
    assert r.status_code == 200
    docs = r.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["file_name"] == "pack1.xlsx"
    assert docs[0]["document_type"] == "purchase_packing_list"
    assert docs[0]["fallback_unparsed"] is True
    assert docs[0]["row_count"] == 0


def test_fallback_row_when_sales_packing_uploaded_but_unparsed(client):
    cli, tmp = client
    bid = "B-SP-1"
    _make_batch_folder(tmp, bid)
    _seed_shipment_doc(tmp, bid, "sales_packing_list", "sales1.xlsx")

    r = cli.get(f"/api/v1/packing/{bid}")
    assert r.status_code == 200
    docs = r.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["document_type"] == "sales_packing_list"
    assert docs[0]["fallback_unparsed"] is True


def test_fallback_lists_both_when_both_types_present(client):
    cli, tmp = client
    bid = "B-BOTH-1"
    _make_batch_folder(tmp, bid)
    _seed_shipment_doc(tmp, bid, "purchase_packing_list", "pp.xlsx")
    _seed_shipment_doc(tmp, bid, "sales_packing_list",    "sp.xlsx")

    r = cli.get(f"/api/v1/packing/{bid}")
    docs = r.json()["documents"]
    types = sorted(d["document_type"] for d in docs)
    assert types == ["purchase_packing_list", "sales_packing_list"]
    assert all(d["fallback_unparsed"] for d in docs)


def test_parsed_packing_documents_win_no_duplicate_fallback(client):
    """When packing_documents has parsed rows, we keep current behaviour
    and DO NOT append fallback rows even if shipment_documents has
    overlapping entries."""
    cli, tmp = client
    bid = "B-PARSED-1"
    _make_batch_folder(tmp, bid)
    _seed_shipment_doc(tmp, bid, "purchase_packing_list", "pp.xlsx", file_hash="h-pp")
    # Also seed a packing_documents row for the same file.
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp / "packing.db")
    pdb.upsert_packing_document(
        batch_id=bid, document_id="pd-1",
        source_file_path="/tmp/pp.xlsx",
        invoice_no="INV-1",
        parser_name="test", parser_version="1",
        source_file_hash="h-pp",
    )

    r = cli.get(f"/api/v1/packing/{bid}")
    docs = r.json()["documents"]
    # Only the parsed row should appear; no fallback duplicate.
    assert len(docs) == 1
    assert docs[0].get("fallback_unparsed") in (None, False)


# ── Side-effect safety ───────────────────────────────────────────────────

def test_fallback_block_does_not_reference_external_systems():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py").read_text(encoding="utf-8")
    start = src.index("# ── Fallback visibility: 2026-05-17 hotfix")
    end   = src.index("return {", start)
    block = src[start:end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
        "process_packing_upload",
    ):
        assert forbidden not in block, f"fallback block must not reference {forbidden!r}"


def test_dashboard_card_renders_fallback_markers():
    # Phase 2 — Packing List card moved to shipment-detail.html.
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    assert "fallback_unparsed" in dash
    assert "Uploaded — extraction pending or failed" in dash
    assert "packing-list-row-fallback" in dash
    assert "packing-list-row-parsed" in dash

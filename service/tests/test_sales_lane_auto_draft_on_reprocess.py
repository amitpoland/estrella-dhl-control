"""test_sales_lane_auto_draft_on_reprocess.py — 2026-05-17.

Reprocess endpoint must auto-sync proforma drafts when the batch
carries sales rows. Idempotent; non-blocking on sync failure; no
mutation when batch has no sales rows.
"""
from __future__ import annotations

from pathlib import Path
import json

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
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "test", "email": "test@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _make_batch(tmp: Path, bid: str) -> Path:
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps({
        "batch_id": bid, "awb": "TEST-AWB", "timeline": [],
    }), encoding="utf-8")
    return out


def _seed_sales(tmp: Path, bid: str, count: int = 3,
                client_name: str = "ACME") -> None:
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    sd_id = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="sp.xlsx", file_path="/tmp/sp.xlsx",
        file_hash="h-sp", source="intake",
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=sd_id,
        data={
            "client_name": client_name, "client_ref": "",
            "document_type": "sales_packing_list",
            "source_file_path": "/tmp/sp.xlsx",
            "extraction_status": "extracted",
        },
    )
    rows = ddb.get_sales_documents(bid)
    real_sd = rows[0]["id"]
    lines = [
        {
            "client_name":  client_name,
            "client_ref":   "",
            "product_code": f"PC-{i}",
            "design_no":    f"D-{i}",
            "bag_id":       f"BAG-{i}",
            "quantity":     1.0,
            "remarks":      "",
        }
        for i in range(count)
    ]
    ddb.store_sales_packing_lines(
        sales_document_id=real_sd, batch_id=bid, lines=lines,
    )


def _count_drafts(tmp: Path, bid: str) -> int:
    db = tmp / "proforma_links.db"
    if not db.exists():
        return 0
    import sqlite3 as _s
    with _s.connect(str(db)) as c:
        r = c.execute(
            "SELECT COUNT(*) FROM proforma_drafts WHERE batch_id=?",
            (bid,)
        ).fetchone()
    return int(r[0])


# ── Scenarios ─────────────────────────────────────────────────────────────

def test_reprocess_triggers_draft_sync_when_sales_rows_exist(client):
    cli, tmp = client
    bid = "B-RS-SALES"
    _make_batch(tmp, bid)
    _seed_sales(tmp, bid, count=5, client_name="ACME")

    before = _count_drafts(tmp, bid)
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    after = _count_drafts(tmp, bid)
    assert after >= 1, f"expected >=1 draft, before={before} after={after}"


def test_reprocess_idempotent_repeated_calls(client):
    cli, tmp = client
    bid = "B-RS-IDEM"
    _make_batch(tmp, bid)
    _seed_sales(tmp, bid, count=3, client_name="ACME")

    cli.post(f"/api/v1/packing/{bid}/reprocess")
    first = _count_drafts(tmp, bid)
    cli.post(f"/api/v1/packing/{bid}/reprocess")
    second = _count_drafts(tmp, bid)
    assert first == second, (
        f"draft count must be stable across reprocess calls "
        f"(first={first} second={second})"
    )


def test_reprocess_no_sales_no_draft_mutation(client):
    cli, tmp = client
    bid = "B-RS-NOSALES"
    _make_batch(tmp, bid)
    # No sales rows seeded.

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    assert _count_drafts(tmp, bid) == 0


def test_reprocess_returns_200_even_if_sync_helper_raises(client, monkeypatch):
    """Sync failure must not break reprocess response."""
    cli, tmp = client
    bid = "B-RS-SYNCFAIL"
    _make_batch(tmp, bid)
    _seed_sales(tmp, bid, count=2, client_name="ACME")

    from app.services import proforma_draft_sync as pds
    def _boom(*a, **kw):
        raise RuntimeError("synthetic sync failure")
    monkeypatch.setattr(pds, "sync_draft_from_packing_upload", _boom)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body

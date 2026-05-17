"""test_packing_card_purchase_and_sales_render.py — 2026-05-17.

Packing List card was rendering ONLY purchase packing files because
GET /api/v1/packing/{batch_id} gated its sales-side merge inside
`if not documents:` — when ANY purchase doc parsed, the sales side
enumeration was skipped entirely.

Fix: split the merge block into:
  * purchase fallback (still gated on no parsed purchase docs)
  * sales-side surfacing (ALWAYS runs; row counts from sales_packing_lines)

Purchase vs sales separation is preserved via `side` and `document_type`
fields — UI badges read from these, never from filename heuristics.
"""
from __future__ import annotations

from pathlib import Path
import uuid

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


def _make_batch_folder(tmp_path: Path, batch_id: str) -> None:
    (tmp_path / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)


def _seed_purchase_parsed(tmp_path: Path, batch_id: str, file_hash: str,
                          file_name: str = "pp.xlsx") -> str:
    """Seed a packing_documents row + N packing_lines for purchase side."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp_path / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, document_id=f"pd-{uuid.uuid4().hex[:8]}",
        source_file_path=f"/tmp/{file_name}",
        invoice_no="INV-1",
        parser_name="test", parser_version="1",
        source_file_hash=file_hash,
    )
    return doc_id


def _seed_purchase_shipment_doc(tmp_path: Path, batch_id: str, file_hash: str,
                                file_name: str = "pp.xlsx") -> str:
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    return ddb.register_document(
        batch_id=batch_id, document_type="purchase_packing_list",
        file_name=file_name, file_path=f"/tmp/{file_name}",
        file_hash=file_hash, source="intake",
    )


def _seed_sales_shipment_doc(tmp_path: Path, batch_id: str, file_hash: str,
                             file_name: str = "sp.xlsx") -> str:
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    return ddb.register_document(
        batch_id=batch_id, document_type="sales_packing_list",
        file_name=file_name, file_path=f"/tmp/{file_name}",
        file_hash=file_hash, source="intake",
    )


def _seed_sales_packing_lines(tmp_path: Path, batch_id: str,
                              sales_document_id: str, count: int) -> None:
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    lines = [
        {
            "client_name":  "ACME",
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
        sales_document_id=sales_document_id,
        batch_id=batch_id,
        lines=lines,
    )


# ── Scenarios ─────────────────────────────────────────────────────────────

def test_both_purchase_parsed_and_sales_render(client):
    """The bug: with parsed purchase docs, sales side used to be hidden.
    After the fix, both must appear in the documents array."""
    cli, tmp = client
    bid = "B-BOTH-2"
    _make_batch_folder(tmp, bid)

    # Parsed purchase doc.
    _seed_purchase_parsed(tmp, bid, file_hash="h-pp", file_name="pp.xlsx")
    # Shipment_documents companion for purchase (intake pattern).
    _seed_purchase_shipment_doc(tmp, bid, file_hash="h-pp", file_name="pp.xlsx")
    # Sales packing file with extracted rows.
    sales_doc_id = _seed_sales_shipment_doc(tmp, bid, file_hash="h-sp",
                                            file_name="sp.xlsx")
    _seed_sales_packing_lines(tmp, bid, sales_doc_id, count=28)

    r = cli.get(f"/api/v1/packing/{bid}")
    assert r.status_code == 200
    docs = r.json()["documents"]
    by_type = {d["document_type"]: d for d in docs}
    assert "purchase_packing_list" in by_type, \
        f"purchase missing; got: {[d['document_type'] for d in docs]}"
    assert "sales_packing_list" in by_type, \
        f"sales missing; got: {[d['document_type'] for d in docs]}"

    # Side field is exposed for UI badge rendering.
    assert by_type["purchase_packing_list"].get("side") == "purchase"
    assert by_type["sales_packing_list"].get("side") == "sales"

    # Sales row count is sourced from sales_packing_lines, not hardcoded.
    assert by_type["sales_packing_list"]["row_count"] == 28


def test_sales_only_batch_still_renders_sales(client):
    cli, tmp = client
    bid = "B-SALES-ONLY"
    _make_batch_folder(tmp, bid)
    sales_doc_id = _seed_sales_shipment_doc(tmp, bid, file_hash="h-sp",
                                            file_name="sp.xlsx")
    _seed_sales_packing_lines(tmp, bid, sales_doc_id, count=5)

    r = cli.get(f"/api/v1/packing/{bid}")
    docs = r.json()["documents"]
    assert any(d["document_type"] == "sales_packing_list" for d in docs)
    sales = next(d for d in docs if d["document_type"] == "sales_packing_list")
    assert sales["side"] == "sales"
    assert sales["row_count"] == 5
    assert sales["fallback_unparsed"] is False  # rows present → not fallback


def test_sales_uploaded_no_rows_marked_fallback(client):
    """Sales file uploaded but no sales_packing_lines yet → fallback flag."""
    cli, tmp = client
    bid = "B-SALES-PENDING"
    _make_batch_folder(tmp, bid)
    _seed_sales_shipment_doc(tmp, bid, file_hash="h-sp", file_name="sp.xlsx")

    r = cli.get(f"/api/v1/packing/{bid}")
    docs = r.json()["documents"]
    sales = next(d for d in docs if d["document_type"] == "sales_packing_list")
    assert sales["row_count"] == 0
    assert sales["fallback_unparsed"] is True
    assert sales["side"] == "sales"


def test_purchase_parsed_doc_carries_side_purchase(client):
    cli, tmp = client
    bid = "B-PURCHASE-PARSED"
    _make_batch_folder(tmp, bid)
    _seed_purchase_parsed(tmp, bid, file_hash="h-pp", file_name="pp.xlsx")

    r = cli.get(f"/api/v1/packing/{bid}")
    docs = r.json()["documents"]
    assert len(docs) == 1
    assert docs[0].get("side") == "purchase"


# ── Source-grep safety: card logic must reference both sides ───────────────

def test_routes_packing_references_sales_packing_list():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py").read_text(encoding="utf-8")
    # The merge block must enumerate sales_packing_list, not just purchase.
    assert 'document_type="sales_packing_list"' in src
    # Row counts must come from sales_packing_lines.
    assert "get_sales_packing_lines" in src


def test_dashboard_card_renders_purchase_and_sales_badges():
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    # Distinct testids for each side make browser smoke verifiable.
    assert "packing-list-row-side-purchase" in dash
    assert "packing-list-row-side-sales" in dash
    # Card logic references the `side` field surfaced by the backend.
    assert "doc.side" in dash or "doc['side']" in dash
    # Labels visible to the operator.
    assert "PURCHASE" in dash
    assert "SALES" in dash

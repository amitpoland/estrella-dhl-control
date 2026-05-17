"""test_document_registry_invoice_lines.py — 2026-05-17 hotfix.

Document Registry was rendering "Fields: 0" for invoice rows even when
invoice_lines existed, because the registry payload only counted rows in
document_extracted_fields. Fix: enrich purchase_invoice / sales_invoice
rows with lines_count + lines_preview.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import sqlite3

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
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@l"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


# ── DB helpers ────────────────────────────────────────────────────────────

def _init_doc_db(tmp: Path) -> Path:
    from app.services import document_db as ddb
    p = tmp / "documents.db"
    ddb.init_document_db(p)
    return p


def _register_doc(batch_id: str, document_type: str, file_name: str,
                  file_hash: str = "") -> str:
    from app.services import document_db as ddb
    return ddb.register_document(
        batch_id=batch_id, document_type=document_type,
        file_name=file_name, file_path=f"/tmp/{file_name}",
        file_hash=file_hash or f"h-{file_name}",
        source="intake",
    ) or ""


def _seed_invoice_lines(batch_id: str, document_id: str, n: int) -> None:
    from app.services import document_db as ddb
    ddb.store_invoice_lines(document_id, batch_id, [
        {"line_position": i + 1, "product_code": f"P{i+1}",
         "description": f"Item {i+1}", "quantity": i + 1,
         "unit_price": 10.0, "total_value": 10.0 * (i + 1),
         "currency": "USD", "invoice_no": "INV-1"}
        for i in range(n)
    ])


def _seed_extracted_field(document_id: str, batch_id: str,
                          field_name: str, value: str) -> None:
    from app.services import document_db as ddb
    ddb.upsert_field(
        document_id=document_id, batch_id=batch_id,
        field_name=field_name, value=value, confidence=0.9,
    )


# ── Scenarios ────────────────────────────────────────────────────────────

def test_invoice_with_lines_surfaces_lines_count(client):
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-INV-1", "purchase_invoice", "inv.pdf")
    _seed_invoice_lines("B-INV-1", doc_id, n=5)

    r = cli.get("/api/v1/upload/shipment/B-INV-1/documents")
    assert r.status_code == 200
    docs = r.json()["documents"]
    inv = next(d for d in docs if d["id"] == doc_id)
    assert inv["lines_count"] == 5
    assert isinstance(inv["lines_preview"], list)
    assert len(inv["lines_preview"]) == 5
    assert inv["lines_truncated"] is False
    # Should still also have fields_total = 0 (no field-level extraction).
    assert inv["fields_total"] == 0


def test_invoice_with_no_lines_does_not_inflate_fields_count(client):
    """Registry should not pretend extraction succeeded when both
    invoice_lines and document_extracted_fields are empty."""
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-INV-EMPTY", "purchase_invoice", "empty.pdf")

    r = cli.get("/api/v1/upload/shipment/B-INV-EMPTY/documents")
    assert r.status_code == 200
    inv = r.json()["documents"][0]
    assert inv["lines_count"] == 0
    assert inv["lines_preview"] == []
    assert inv["fields_total"] == 0


def test_invoice_lines_capped_at_20_with_truncated_flag(client):
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-INV-BIG", "purchase_invoice", "big.pdf")
    _seed_invoice_lines("B-INV-BIG", doc_id, n=25)

    r = cli.get("/api/v1/upload/shipment/B-INV-BIG/documents")
    inv = r.json()["documents"][0]
    assert inv["lines_count"] == 25
    assert len(inv["lines_preview"]) == 20    # capped
    assert inv["lines_truncated"] is True


def test_non_invoice_doc_still_uses_fields_count(client):
    """Packing / AWB / etc. rows should keep their existing fields_total
    semantics — no lines_* keys should appear (or they're skipped)."""
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-PACK-1", "purchase_packing_list", "pack.xlsx")
    _seed_extracted_field(doc_id, "B-PACK-1", "supplier_name", "Acme Co.")

    r = cli.get("/api/v1/upload/shipment/B-PACK-1/documents")
    pack = r.json()["documents"][0]
    assert pack["fields_total"] == 1
    assert pack.get("lines_count") is None
    assert pack.get("lines_preview") is None


def test_invoice_lines_preview_carries_line_data(client):
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-INV-PRE", "purchase_invoice", "inv.pdf")
    _seed_invoice_lines("B-INV-PRE", doc_id, n=2)

    r = cli.get("/api/v1/upload/shipment/B-INV-PRE/documents")
    inv = r.json()["documents"][0]
    line1 = inv["lines_preview"][0]
    assert line1["product_code"] == "P1"
    assert line1["description"] == "Item 1"
    assert line1["quantity"] == 1
    assert line1["total_value"] == 10.0
    assert line1["currency"] == "USD"


def test_sales_invoice_also_enriched(client):
    cli, tmp = client
    _init_doc_db(tmp)
    doc_id = _register_doc("B-SI-1", "sales_invoice", "si.pdf")
    _seed_invoice_lines("B-SI-1", doc_id, n=3)

    r = cli.get("/api/v1/upload/shipment/B-SI-1/documents")
    si = r.json()["documents"][0]
    assert si["lines_count"] == 3


# ── Side-effect safety ───────────────────────────────────────────────────

def test_enrichment_does_not_reference_external_systems():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_upload.py").read_text(encoding="utf-8")
    start = src.index("# ── Invoice-side enrichment: 2026-05-17 hotfix")
    end   = src.index("enriched.append(row)", start)
    block = src[start:end]
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "process_sad", "trigger_clearance", "dhl_dispatch",
        "parse_invoice_pdf", "store_invoice_lines",
    ):
        assert forbidden not in block, f"enrichment must not reference {forbidden!r}"


def test_dashboard_registry_renders_invoice_branch():
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    assert "doc-registry-lines-count" in dash
    assert "doc-registry-invoice-preview" in dash
    assert "doc-registry-invoice-empty" in dash
    assert "Lines / Fields" in dash
    # Invoice branch checks doc_type:
    assert "'purchase_invoice'" in dash and "'sales_invoice'" in dash
    # Branch labels:
    assert "extraction failed" in dash
    assert "extraction pending" in dash

"""test_sales_reprocess_preserves_client_name.py — Phase 2 follow-up.

reprocess_packing_documents must preserve operator-supplied
client_name / client_ref across the atomic DELETE+INSERT done by
replace_sales_packing_lines, must map the qty/quantity key correctly,
and must coerce None product_code to ''.

Without this fix, every Reparse-all wiped client_name on the sales
side, which caused sync_draft_from_packing_upload to skip the
empty-client group and produce zero proforma_drafts.
"""
from __future__ import annotations

import json
import sqlite3
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
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@local"}
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _seed_intake_sales(tmp: Path, bid: str, client_name: str,
                       client_ref: str = "", line_count: int = 3) -> str:
    """Mirror the intake path: register a sales_packing_list shipment
    doc, create a sales_documents row, and store sales_packing_lines
    with client_name populated (as intake would have done)."""
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps({
        "batch_id": bid, "awb": "TEST-AWB", "timeline": [],
    }), encoding="utf-8")

    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    shipment_doc_id = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="sp.xlsx", file_path=str(out / "sp.xlsx"),
        file_hash="h-sp", source="intake",
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=shipment_doc_id,
        data={"client_name": client_name, "client_ref": client_ref,
              "document_type": "sales_packing_list",
              "source_file_path": str(out / "sp.xlsx"),
              "extraction_status": "extracted"},
    )
    sd_rows = ddb.get_sales_documents(bid)
    real_sd_id = sd_rows[0]["id"]
    lines = [{
        "client_name":  client_name, "client_ref": client_ref,
        "product_code": f"PC-{i}", "design_no": f"D-{i}",
        "bag_id": f"BAG-{i}", "quantity": 1.0, "remarks": "",
        "unit_price": 100.0, "currency": "USD", "total_value": 100.0,
    } for i in range(line_count)]
    ddb.store_sales_packing_lines(
        sales_document_id=real_sd_id, batch_id=bid, lines=lines,
    )
    # Create the source file on disk so reprocess can find it.
    (out / "sp.xlsx").write_bytes(b"stub")
    return real_sd_id


def _read_sales(tmp: Path, bid: str):
    from app.services import document_db as ddb
    return ddb.get_sales_packing_lines(bid)


# ── Scenarios ─────────────────────────────────────────────────────────────

def test_reprocess_preserves_client_name(client, monkeypatch):
    """Operator-supplied client_name must survive reprocess."""
    cli, tmp = client
    bid = "B-PRESERVE-NAME"
    _seed_intake_sales(tmp, bid, "ACME Corp", "PO-123", line_count=3)

    # Stub the parser to return deterministic rows.
    from app.services import invoice_packing_extractor as ipe

    def _fake_extract(path):
        rows = [
            {"product_code": "X1", "design_no": "D1", "quantity": 2.0,
             "unit_price": 50.0, "currency": "USD"},
            {"product_code": "X2", "design_no": "D2", "quantity": 3.0,
             "unit_price": 75.0, "currency": "USD"},
        ]
        return rows, "fake_parser", "1.0", {"failure_reason": None}
    monkeypatch.setattr(ipe, "extract_packing", _fake_extract)

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text

    rows = _read_sales(tmp, bid)
    assert rows, "sales_packing_lines must be repopulated after reprocess"
    client_names = {ln["client_name"] for ln in rows}
    assert client_names == {"ACME Corp"}, (
        f"client_name lost on reprocess: {client_names}"
    )


def test_reprocess_preserves_client_ref(client, monkeypatch):
    cli, tmp = client
    bid = "B-PRESERVE-REF"
    _seed_intake_sales(tmp, bid, "BetaInc", "PO-XYZ-9", line_count=2)
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: ([{"product_code": "Y", "quantity": 1.0,
                     "unit_price": 10.0, "currency": "EUR"}],
                   "fake", "1.0", {"failure_reason": None}),
    )
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    rows = _read_sales(tmp, bid)
    refs = {ln.get("client_ref", "") for ln in rows}
    assert refs == {"PO-XYZ-9"}, f"client_ref lost: {refs}"


def test_reprocess_maps_qty_legacy_key(client, monkeypatch):
    """Both 'quantity' and 'qty' parser keys must yield non-zero rows.
    Legacy parser variants emit 'qty'; new variants emit 'quantity'.
    Reprocess must accept either."""
    cli, tmp = client
    bid = "B-QTY"
    _seed_intake_sales(tmp, bid, "QTY Co", "", line_count=1)
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: ([{"product_code": "Z", "qty": 7.5,
                     "unit_price": 100.0, "currency": "USD"}],
                   "fake", "1.0", {"failure_reason": None}),
    )
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    rows = _read_sales(tmp, bid)
    assert rows, "no rows"
    # Reprocess uses a different sales_doc_id than intake (shipment_doc.id
    # vs internal sales_documents.id), so the new parser row coexists
    # with the seeded row. Find the new row by parser product_code.
    new_rows = [r for r in rows if r.get("product_code") == "Z"]
    assert new_rows, f"new parser row missing; got: {rows}"
    assert new_rows[0]["quantity"] == 7.5, (
        f"qty→quantity not mapped: {new_rows[0]['quantity']}"
    )


def test_reprocess_coerces_none_product_code(client, monkeypatch):
    """Parser returning None product_code must store '' (not literal
    'None')."""
    cli, tmp = client
    bid = "B-PC-NONE"
    _seed_intake_sales(tmp, bid, "NoCode Inc", "", line_count=1)
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: ([{"product_code": None, "quantity": 1.0,
                     "unit_price": 50.0, "currency": "USD"}],
                   "fake", "1.0", {"failure_reason": None}),
    )
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    rows = _read_sales(tmp, bid)
    codes = {ln.get("product_code", "") for ln in rows}
    assert "None" not in codes, (
        "product_code stored as literal 'None' string — must be ''"
    )


def test_reprocess_creates_proforma_draft_when_client_preserved(client, monkeypatch):
    """End-to-end: with preserved client_name,
    sync_draft_from_packing_upload must produce a proforma_drafts row
    after reprocess."""
    cli, tmp = client
    bid = "B-DRAFT-AFTER-REPROCESS"
    _seed_intake_sales(tmp, bid, "Draft Maker SpA", "", line_count=2)
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: ([{"product_code": "P1", "design_no": "D1",
                     "quantity": 1.0, "unit_price": 80.0, "currency": "USD"}],
                   "fake", "1.0", {"failure_reason": None}),
    )
    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200

    pf = tmp / "proforma_links.db"
    assert pf.exists(), "proforma_links.db not created"
    with sqlite3.connect(str(pf)) as c:
        cnt = c.execute(
            "SELECT COUNT(*) FROM proforma_drafts WHERE batch_id=?",
            (bid,),
        ).fetchone()[0]
    assert cnt >= 1, (
        "reprocess must create at least one proforma_draft when "
        "sales_packing_lines have non-empty client_name"
    )

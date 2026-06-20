"""test_sales_intake_persistence.py — PR-1: deterministic sales-packing intake.

Reproduces and pins the fix for the silent-drop bug where parsed sales rows
were discarded whenever ``sales_doc_id`` stayed empty — even though the sales
block carried a ``client_contractor_id`` (and ``shipment_documents`` already
stored it). Before PR-1 the gate ``if sp_rows and sales_doc_id`` dropped the
rows with no diagnostic and left ``extraction_status='pending'`` forever.

Contracts pinned (route-level, via the real intake endpoint — no direct DB
writes for recovery; everything goes through /api/v1/shipment/intake):

  1. Sales .xlsx intake with client_contractor_id but NO client_name/ref and
     NO sales_documents block stores rows in sales_packing_lines.
  2. A sales_documents row is created/resolved for the client.
  3. shipment_documents status is persisted (extracted/complete) after store.
  4. A zero-row / failed sales parse writes a parser_diagnostics artifact with
     a failure_reason and never leaves the doc silently 'pending'.
  5. Recovery needs no direct DB write — the service path persists the rows.
  6. Purchase lane behaviour is unchanged.

Run: python -m pytest tests/test_sales_intake_persistence.py -q
"""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import customer_master_db as cmdb
from app.services.customer_master_db import CustomerMaster

CONTRACTOR_ID = "182241571"
CLIENT_NAME = "SAGAR SHAH"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with patch.object(settings, "max_upload_bytes", 20 * 1024 * 1024):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


def _auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _invoice() -> tuple:
    return ("INV-PR1.pdf", io.BytesIO(b"%PDF-1.4 fake purchase invoice"), "application/pdf")


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sales_xlsx_bytes(*, design: str = "JE-001", value: float = 200.0,
                      invoice_no: str = "EJL/X-1") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([f"Export No : {invoice_no}"])
    ws.append([""])
    ws.append(["PkSr", "DesignNo", "Qty", "Value (EUR)", "Total Value"])
    ws.append([1, design, 1, value, value])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _seed_customer(storage: Path) -> None:
    cmdb.upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT_NAME,
            country="BE",
        ),
    )


def _post_intake(client, *, awb: str, sales_files, sales_blocks):
    files = [("invoices", _invoice())]
    files.extend(("sales_packing_lists", f) for f in sales_files)
    meta = json.dumps({"purchase_blocks": [], "sales_blocks": sales_blocks})
    return client.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": awb, "carrier": "DHL", "metadata": meta},
        files=files,
        headers=_auth(),
    )


def _docdb(storage: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(storage / "documents.db"))
    con.row_factory = sqlite3.Row
    return con


# ── Contract 1/2/3/5: contractor-id-only block stores rows + status ─────────

def test_contractor_id_only_block_persists_sales_rows(client, storage):
    """Sales block with ONLY client_contractor_id (no name/ref, no
    document_index, no sales_documents file) must store rows, create a
    sales_documents row, and persist extraction_status — never silent-drop."""
    _seed_customer(storage)
    r = _post_intake(
        client,
        awb="9158478722",
        sales_files=[("EJL-290-Client.xlsx", io.BytesIO(_sales_xlsx_bytes()), _XLSX_MIME)],
        sales_blocks=[{"packing_index": 0, "client_contractor_id": CONTRACTOR_ID}],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    con = _docdb(storage)
    try:
        n_lines = con.execute(
            "SELECT COUNT(*) FROM sales_packing_lines WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0]
        n_docs = con.execute(
            "SELECT COUNT(*) FROM sales_documents WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0]
        sd = con.execute(
            "SELECT extraction_status, parser_status, client_contractor_id "
            "FROM shipment_documents WHERE batch_id=? "
            "AND document_type='sales_packing_list'",
            (batch_id,),
        ).fetchone()
        sales_doc = con.execute(
            "SELECT client_name FROM sales_documents WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
    finally:
        con.close()

    # Contract 1: rows stored (not dropped).
    assert n_lines > 0, "sales_packing_lines must be > 0 after intake"
    # Contract 2: a sales_documents row was created/resolved.
    assert n_docs >= 1, "a sales_documents row must exist for the client"
    # Contract 3: status persisted, no silent 'pending'.
    assert sd is not None
    assert sd["extraction_status"] == "extracted"
    assert sd["parser_status"] in ("complete", "extracted")
    # client_contractor_id is the resolution key carried on the doc.
    assert sd["client_contractor_id"] == CONTRACTOR_ID
    # Name backfilled from Customer Master via the contractor id.
    assert (sales_doc["client_name"] or "") == CLIENT_NAME


# ── Contract 4/5: zero-row / failed parse writes a visible diagnostic ───────

def test_zero_row_sales_parse_writes_diagnostic_and_no_silent_pending(client, storage):
    """An unparseable sales file must produce a parser_diagnostics artifact
    with a failure_reason and a non-'pending' status — never a silent drop."""
    r = _post_intake(
        client,
        awb="9158470000",
        sales_files=[("EJL-BAD.xlsx", io.BytesIO(b"PK\x03\x04 not a real xlsx"), _XLSX_MIME)],
        sales_blocks=[{"packing_index": 0, "client_contractor_id": CONTRACTOR_ID}],
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    diag_dir = Path(storage) / "parser_diagnostics" / batch_id
    artifacts = list(diag_dir.glob("*.json")) if diag_dir.is_dir() else []
    assert artifacts, f"expected a parser_diagnostics artifact under {diag_dir}"
    blob = json.loads(artifacts[0].read_text(encoding="utf-8"))
    blob_text = json.dumps(blob)
    assert "failure_reason" in blob_text, "diagnostic must carry a failure_reason"

    con = _docdb(storage)
    try:
        sd = con.execute(
            "SELECT extraction_status FROM shipment_documents WHERE batch_id=? "
            "AND document_type='sales_packing_list'",
            (batch_id,),
        ).fetchone()
    finally:
        con.close()
    assert sd is not None
    assert sd["extraction_status"] != "pending", (
        "a parse attempt must not leave the sales doc silently 'pending'"
    )


# ── Contract 6: purchase lane unchanged ─────────────────────────────────────

def test_purchase_lane_intake_unchanged(client, storage):
    """The purchase/invoice path still completes (200) and registers docs —
    PR-1 only touches the sales packing section."""
    with patch("app.api.routes_intake.process_packing_upload") as mock_pack:
        mock_pack.side_effect = Exception("no packing file")  # invoice-only intake
        r = client.post(
            "/api/v1/shipment/intake",
            data={
                "tracking_no": "9158460000",
                "carrier": "DHL",
                "metadata": json.dumps({"purchase_blocks": [], "sales_blocks": []}),
            },
            files=[("invoices", _invoice())],
            headers=_auth(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["documents_registered"] >= 1


# ── Regression: a parser EXCEPTION is handled, not crashed (sentinel) ────────

def test_extract_packing_exception_is_handled_not_500(client, storage):
    """If extract_packing raises, intake must NOT 500 (UnboundLocalError on
    sales_matcher_summary). The doc must land 'extraction_failed', not
    silently 'pending'."""
    from app.services import invoice_packing_extractor as _ipe

    def _boom(*a, **k):
        raise RuntimeError("simulated parser crash")

    with patch.object(_ipe, "extract_packing", side_effect=_boom):
        r = _post_intake(
            client,
            awb="9158450000",
            sales_files=[("EJL-CRASH.xlsx", io.BytesIO(_sales_xlsx_bytes()), _XLSX_MIME)],
            sales_blocks=[{"packing_index": 0, "client_contractor_id": CONTRACTOR_ID}],
        )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    con = _docdb(storage)
    try:
        sd = con.execute(
            "SELECT extraction_status FROM shipment_documents WHERE batch_id=? "
            "AND document_type='sales_packing_list'",
            (batch_id,),
        ).fetchone()
    finally:
        con.close()
    assert sd is not None
    assert sd["extraction_status"] == "extraction_failed"

"""test_cpa_manual_sales_allocation.py — CPA Phase 3: manual sales allocation path.

Covers:
  - POST /{batch_id}/manual-sales-allocation creates sales_packing_lines
  - Re-POST replaces prior allocation (idempotent)
  - Manual allocation rows visible via v_sales_to_wfirma (existing proforma path)
  - Missing sales packing → empty list, not error (warning not hard block)
  - Over-allocation blocked (422)
  - Unknown product_code blocked (422)
  - Existing sales packing upload path unaffected
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixture ───────────────────────────────────────────────────────────────────

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

    from app.services import document_db as ddb
    from app.services import packing_db as pdb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _seed_batch(storage: Path, batch_id: str) -> Path:
    out = storage / "outputs" / batch_id
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _seed_purchase_lines(packing_db: Path, batch_id: str, rows: List[Dict[str, Any]]) -> None:
    with sqlite3.connect(str(packing_db)) as con:
        for row in rows:
            con.execute(
                """INSERT OR REPLACE INTO packing_lines
                   (id, packing_document_id, batch_id, product_code, design_no,
                    quantity, invoice_no, invoice_line_position,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    "fake-doc-id",
                    batch_id,
                    row.get("product_code", ""),
                    row.get("design_no", ""),
                    float(row.get("quantity", 0)),
                    row.get("invoice_no", "INV/001"),
                    1,
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                ),
            )


_PURCHASE_ROWS = [
    {"product_code": "EJL/26-27/001-1", "design_no": "D001", "quantity": 5.0},
    {"product_code": "EJL/26-27/002-1", "design_no": "D002", "quantity": 3.0},
]

_ALLOC_LINES = [
    {"product_code": "EJL/26-27/001-1", "design_no": "D001",
     "quantity": 2.0, "unit_price": 150.0, "currency": "EUR"},
]


# ── Happy path ────────────────────────────────────────────────────────────────

class TestManualAllocationHappyPath:

    def test_creates_sales_packing_lines(self, client, tmp_path):
        """POST /manual-sales-allocation writes rows to sales_packing_lines."""
        cli, storage = client
        bid = "B-ALLOC-01"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        with patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}):
            r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
                "client_name": "Verhoeven B.V.",
                "lines": _ALLOC_LINES,
            })

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["lines_written"] == 1
        assert "EJL/26-27/001-1" in data["allocation_by_product_code"]
        assert data["price_source"] == "manual_allocation"

        # Verify rows exist in DB.
        docs_db = storage / "documents.db"
        with sqlite3.connect(str(docs_db)) as con:
            rows = con.execute(
                "SELECT product_code, quantity, price_source FROM sales_packing_lines WHERE batch_id=?",
                (bid,),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "EJL/26-27/001-1"
        assert rows[0][1] == 2.0
        assert rows[0][2] == "manual_allocation"

    def test_idempotent_replace_on_repost(self, client, tmp_path):
        """Re-POST for same batch+client replaces prior allocation rows."""
        cli, storage = client
        bid = "B-ALLOC-02"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        with patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}):
            cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
                "client_name": "Verhoeven B.V.",
                "lines": [{"product_code": "EJL/26-27/001-1",
                            "quantity": 2.0, "unit_price": 100.0}],
            })
            r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
                "client_name": "Verhoeven B.V.",
                "lines": [{"product_code": "EJL/26-27/001-1",
                            "quantity": 3.0, "unit_price": 120.0}],
            })

        assert r.status_code == 200, r.text
        # Only 3 rows in DB (second POST replaced first).
        docs_db = storage / "documents.db"
        with sqlite3.connect(str(docs_db)) as con:
            rows = con.execute(
                "SELECT quantity FROM sales_packing_lines WHERE batch_id=?",
                (bid,),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 3.0

    def test_design_no_resolves_to_product_code(self, client, tmp_path):
        """Supplying design_no without product_code resolves via purchase authority."""
        cli, storage = client
        bid = "B-ALLOC-03"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        with patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}):
            r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
                "client_name": "Verhoeven B.V.",
                "lines": [{"design_no": "D001", "quantity": 1.0, "unit_price": 50.0}],
            })

        assert r.status_code == 200, r.text
        docs_db = storage / "documents.db"
        with sqlite3.connect(str(docs_db)) as con:
            pc = con.execute(
                "SELECT product_code FROM sales_packing_lines WHERE batch_id=?",
                (bid,),
            ).fetchone()[0]
        assert pc == "EJL/26-27/001-1"


# ── Validation ────────────────────────────────────────────────────────────────

class TestManualAllocationValidation:

    def test_over_allocation_blocked(self, client, tmp_path):
        """Qty exceeding purchase packing returns 422 with over_allocation detail."""
        cli, storage = client
        bid = "B-ALLOC-VAL-01"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid,
                             [{"product_code": "EJL/26-27/001-1",
                               "design_no": "D001", "quantity": 2.0}])

        r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
            "client_name": "Verhoeven B.V.",
            "lines": [{"product_code": "EJL/26-27/001-1",
                       "quantity": 5.0, "unit_price": 100.0}],
        })
        assert r.status_code == 422, r.text
        detail = r.json().get("detail", {})
        assert detail.get("error") == "over_allocation"
        items = detail.get("items", [])
        assert any(i["product_code"] == "EJL/26-27/001-1" for i in items)

    def test_unknown_product_code_blocked(self, client, tmp_path):
        """product_code absent from purchase packing returns 422."""
        cli, storage = client
        bid = "B-ALLOC-VAL-02"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
            "client_name": "Verhoeven B.V.",
            "lines": [{"product_code": "GHOST/99/999-9",
                       "quantity": 1.0, "unit_price": 100.0}],
        })
        assert r.status_code == 422, r.text

    def test_zero_quantity_blocked(self, client, tmp_path):
        """quantity=0 returns 422."""
        cli, storage = client
        bid = "B-ALLOC-VAL-03"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
            "client_name": "Verhoeven B.V.",
            "lines": [{"product_code": "EJL/26-27/001-1",
                       "quantity": 0.0, "unit_price": 100.0}],
        })
        assert r.status_code == 422, r.text

    def test_missing_client_name_blocked(self, client, tmp_path):
        """Empty client_name returns 422."""
        cli, storage = client
        bid = "B-ALLOC-VAL-04"
        _seed_batch(storage, bid)
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)

        r = cli.post(f"/api/v1/packing/{bid}/manual-sales-allocation", json={
            "client_name": "   ",
            "lines": [{"product_code": "EJL/26-27/001-1",
                       "quantity": 1.0, "unit_price": 100.0}],
        })
        assert r.status_code == 422, r.text


# ── v_sales_to_wfirma path ────────────────────────────────────────────────────

class TestVSalesToWfirmaPath:

    def test_manual_allocation_visible_in_v_sales_to_wfirma(self, tmp_path, monkeypatch):
        """Rows written by manual allocation appear via query_sales_to_wfirma."""
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

        from app.services import document_db as ddb
        from app.services import packing_db as pdb
        ddb.init_document_db(tmp_path / "documents.db")
        pdb.init_packing_db(tmp_path / "packing.db")

        bid = "B-ALLOC-VIEW-01"
        _seed_purchase_lines(tmp_path / "packing.db", bid, _PURCHASE_ROWS)

        # Write manual allocation directly via ddb helpers
        # (bypassing HTTP to test the DB layer directly).
        import hashlib as hl
        from datetime import datetime as dt

        client_name = "Verhoeven B.V."
        sd_seed = f"{bid}\x00manual_allocation\x00{client_name}"
        sd_id = hl.sha256(sd_seed.encode()).hexdigest()[:32]
        now = dt.utcnow().isoformat()

        docs_db = tmp_path / "documents.db"
        with sqlite3.connect(str(docs_db)) as con:
            con.execute(
                """INSERT OR IGNORE INTO sales_documents
                   (id, batch_id, document_id, client_name, client_ref,
                    document_type, sales_doc_no, sales_doc_date,
                    source_file_path, extraction_status,
                    client_contractor_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sd_id, bid, "", client_name, "",
                 "manual_sales_allocation", "", "", "", "extracted",
                 "", now, now),
            )

        lines = [{
            "batch_id":             bid,
            "sales_document_id":    sd_id,
            "client_name":          client_name,
            "client_ref":           "",
            "product_code":         "EJL/26-27/001-1",
            "design_no":            "D001",
            "bag_id":               "",
            "quantity":             2.0,
            "unit_price":           150.0,
            "currency":             "EUR",
            "total_value":          300.0,
            "price_source":         "manual_allocation",
            "remarks":              "",
            "client_contractor_id": "",
        }]
        ddb.replace_sales_packing_lines(
            sales_document_id=sd_id, batch_id=bid, lines=lines,
        )

        rows = ddb.query_sales_to_wfirma(bid)
        assert len(rows) >= 1, "manual allocation must appear in v_sales_to_wfirma"
        row = next((r for r in rows if r.get("client_name") == client_name), None)
        assert row is not None, f"client_name {client_name!r} not found in {rows}"
        assert row.get("sales_unit_price") == 150.0
        assert row.get("qty") == 2.0

    def test_missing_sales_packing_returns_empty_not_error(self, tmp_path, monkeypatch):
        """query_sales_to_wfirma returns [] when no sales_packing_lines exist.

        This verifies that missing sales packing is a warning (empty list),
        not a hard block (exception / non-empty error state).
        """
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

        from app.services import document_db as ddb
        from app.services import packing_db as pdb
        ddb.init_document_db(tmp_path / "documents.db")
        pdb.init_packing_db(tmp_path / "packing.db")

        bid = "B-ALLOC-VIEW-02"
        _seed_purchase_lines(tmp_path / "packing.db", bid, _PURCHASE_ROWS)
        # No sales packing written.

        rows = ddb.query_sales_to_wfirma(bid)
        assert rows == [], (
            "Missing sales packing must return empty list — warning, not hard block. "
            f"Got: {rows}"
        )


# ── Upload path regression ────────────────────────────────────────────────────

class TestSalesUploadUnchanged:

    def test_sales_packing_upload_still_works(self, client, tmp_path):
        """Reprocess of sales_packing_list is unaffected by Phase 3 additions."""
        import io
        import openpyxl

        cli, storage = client
        bid = "B-ALLOC-UP-01"
        out = _seed_batch(storage, bid)
        sp = out / "source" / "packing" / "sales.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["DesignNo", "Qty", "UnitPrice"])
        ws.append(["D001", 2, 150.0])
        wb.save(str(sp))

        from app.services import document_db as ddb
        _seed_purchase_lines(storage / "packing.db", bid, _PURCHASE_ROWS)
        doc_id = ddb.register_document(
            batch_id=bid,
            document_type="sales_packing_list",
            file_name=sp.name,
            file_path=str(sp),
            file_hash="h-sales",
            source="intake",
        )

        _MOCK_SALES_ROWS = [
            {
                "design_no": "D001", "product_code": "EJL/26-27/001-1",
                "quantity": 2.0, "unit_price": 150.0, "currency": "EUR",
                "total_value": 300.0, "price_source": "excel_symbol",
                "bag_id": "", "remarks": "", "invoice_no": "INV/001",
                "client_po": "", "client_name": "Verhoeven B.V.", "client_ref": "",
            }
        ]

        _MOCK_EXTRACT_RESULT = {
            "packing_rows": _MOCK_SALES_ROWS,
            "supplier":     "generic",
            "document": {
                "batch_id":   bid,
                "filename":   "sales.xlsx",
                "file_path":  str(sp),
                "file_hash":  "h-sales",
                "parser_diagnostic": {},
                "document_type": "sales_packing_list",
            },
            "parser_diagnostic": {"failure_reason": None,
                                  "client_name_resolution": {}},
            "total_rows":    1,
            "matched_count": 1,
            "unmatched_count": 0,
        }

        with patch("app.services.invoice_packing_extractor.process_packing_upload",
                   return_value=_MOCK_EXTRACT_RESULT), \
             patch("app.services.sales_packing_matcher.match_sales_lines_to_packing",
                   return_value=(_MOCK_SALES_ROWS, {})), \
             patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}), \
             patch("app.services.parser_diagnostic_writer"
                   ".write_packing_diagnostic_artifact", return_value=None):

            r = cli.post(f"/api/v1/packing/{bid}/reprocess")

        assert r.status_code == 200, r.text
        # Verify sales_packing_lines written by upload path (not manual_allocation).
        docs_db = storage / "documents.db"
        with sqlite3.connect(str(docs_db)) as con:
            rows = con.execute(
                "SELECT price_source FROM sales_packing_lines WHERE batch_id=?",
                (bid,),
            ).fetchall()
        # price_source comes from the mock row ("excel_symbol"), not "manual_allocation"
        assert any(r[0] != "manual_allocation" for r in rows), (
            "Upload path must write its own price_source, not 'manual_allocation'"
        )

"""test_cpa_packing_wiring.py — CPA Phase 2: packing upload → product_master wiring.

Verifies that upsert_product_master_from_packing is called (non-blocking) after
upsert_packing_lines succeeds in both the upload and reprocess paths, and that
a CPA failure never blocks the caller.
"""
from __future__ import annotations

import json
import io
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

# ── Shared minimal result returned by process_packing_upload mock ─────────────

_MOCK_PACKING_ROWS = [
    {
        "invoice_no": "INV/001",
        "invoice_line_position": 1,
        "product_code": "EJL/26-27/001-1",
        "design_no": "D001",
        "batch_no": "",
        "bag_id": "B1",
        "tray_id": "",
        "item_type": "RING",
        "uom": "PCS",
        "quantity": 2.0,
        "gross_weight": 5.0,
        "net_weight": 4.8,
        "metal": "gold",
        "karat": "14KT",
        "stone_type": "",
        "remarks": "",
        "extracted_confidence": 0.95,
        "requires_manual_review": False,
        "unit_price": 0.0,
        "total_value": 0.0,
        "metal_color": "Y",
        "quality_string": "G-VS",
        "size": "7",
        "diamond_weight": 0.1,
        "color_weight": 0.0,
        "line_position": 1,
    }
]

_MOCK_UPLOAD_RESULT = {
    "packing_rows": _MOCK_PACKING_ROWS,
    "supplier": "ejl",
    "document": {
        "batch_id": "B-CPA-01",
        "filename": "pack.xlsx",
        "file_path": "/tmp/pack.xlsx",
        "file_hash": "aabbcc",
        "parser_diagnostic": {},
        "document_type": "purchase_packing_list",
    },
    "parser_diagnostic": {"failure_reason": None, "client_name_resolution": {}},
    "total_rows": 1,
    "matched_count": 1,
    "unmatched_count": 0,
}


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


def _seed_batch(tmp_path: Path, batch_id: str) -> Path:
    out = tmp_path / "outputs" / batch_id
    (out / "source" / "packing").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": batch_id, "tracking_no": batch_id,
             "awb": batch_id, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _register_purchase_doc(batch_id: str, file_path: Path) -> str:
    from app.services import document_db as ddb
    return ddb.register_document(
        batch_id=batch_id, document_type="purchase_packing_list",
        file_name=file_path.name, file_path=str(file_path),
        file_hash=f"h-{file_path.name}", source="intake",
    ) or ""


def _fake_xlsx(path: Path) -> None:
    """Write a minimal openpyxl XLSX so the upload endpoint accepts it."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DesignNo", "Qty", "Value"])
    ws.append(["D001", 2, 200.0])
    wb.save(str(path))


# ── Upload path tests ─────────────────────────────────────────────────────────

class TestCpaUploadWiring:

    def test_cpa_called_after_successful_upload(self, client, tmp_path):
        """After upsert_packing_lines succeeds, CPA must be called with batch_id
        and the exact line_records that were stored."""
        cli, storage = client
        bid = "B-CPA-01"
        out = _seed_batch(storage, bid)
        xlsx = out / "source" / "packing" / "pack.xlsx"
        _fake_xlsx(xlsx)

        mock_result = {**_MOCK_UPLOAD_RESULT,
                       "document": {**_MOCK_UPLOAD_RESULT["document"], "batch_id": bid}}

        cpa_mock = MagicMock(return_value={
            "batch_id": bid, "upserted": ["EJL/26-27/001-1"],
            "upserted_count": 1, "skipped": [], "skipped_count": 0,
            "errors": {}, "error_count": 0,
        })

        with patch("app.api.routes_packing.process_packing_upload",
                   return_value=mock_result), \
             patch("app.services.packing_db.upsert_packing_lines", return_value=1), \
             patch("app.api.routes_packing.seed_purchase_transit"), \
             patch("app.services.cpa_product_service.upsert_product_master_from_packing",
                   cpa_mock), \
             patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}), \
             patch("app.services.packing_db.upsert_packing_document", return_value="doc-1"):

            r = cli.post(
                f"/api/v1/packing/{bid}/upload",
                files={"file": ("pack.xlsx", open(str(xlsx), "rb"),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

        assert r.status_code == 200, r.text
        assert cpa_mock.called, "CPA upsert must be called after successful packing_lines write"
        args = cpa_mock.call_args
        assert args[0][1] == bid         # batch_id positional
        rows_passed = args[0][2]
        assert len(rows_passed) == 1
        assert rows_passed[0]["product_code"] == "EJL/26-27/001-1"
        assert rows_passed[0]["design_no"] == "D001"

    def test_cpa_failure_does_not_block_upload(self, client, tmp_path):
        """A CPA exception must be caught and logged; the upload response must
        still return 200 — CPA is non-blocking."""
        cli, storage = client
        bid = "B-CPA-02"
        out = _seed_batch(storage, bid)
        xlsx = out / "source" / "packing" / "pack.xlsx"
        _fake_xlsx(xlsx)

        mock_result = {**_MOCK_UPLOAD_RESULT,
                       "document": {**_MOCK_UPLOAD_RESULT["document"], "batch_id": bid}}

        with patch("app.api.routes_packing.process_packing_upload",
                   return_value=mock_result), \
             patch("app.services.packing_db.upsert_packing_lines", return_value=1), \
             patch("app.api.routes_packing.seed_purchase_transit"), \
             patch("app.services.cpa_product_service.upsert_product_master_from_packing",
                   side_effect=RuntimeError("simulated CPA DB failure")), \
             patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}), \
             patch("app.services.packing_db.upsert_packing_document", return_value="doc-1"):

            r = cli.post(
                f"/api/v1/packing/{bid}/upload",
                files={"file": ("pack.xlsx", open(str(xlsx), "rb"),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

        assert r.status_code == 200, "CPA failure must not break the upload (non-blocking)"

    def test_cpa_receives_correct_db_path(self, client, tmp_path):
        """CPA must be called with storage_root / reservation_queue.db."""
        cli, storage = client
        bid = "B-CPA-03"
        out = _seed_batch(storage, bid)
        xlsx = out / "source" / "packing" / "pack.xlsx"
        _fake_xlsx(xlsx)

        mock_result = {**_MOCK_UPLOAD_RESULT,
                       "document": {**_MOCK_UPLOAD_RESULT["document"], "batch_id": bid}}
        cpa_mock = MagicMock(return_value={
            "batch_id": bid, "upserted": [], "upserted_count": 0,
            "skipped": ["EJL/26-27/001-1"], "skipped_count": 1,
            "errors": {}, "error_count": 0,
        })

        with patch("app.api.routes_packing.process_packing_upload",
                   return_value=mock_result), \
             patch("app.services.packing_db.upsert_packing_lines", return_value=1), \
             patch("app.api.routes_packing.seed_purchase_transit"), \
             patch("app.services.cpa_product_service.upsert_product_master_from_packing",
                   cpa_mock), \
             patch("app.services.proforma_draft_sync.sync_draft_from_packing_upload",
                   return_value={}), \
             patch("app.services.packing_db.upsert_packing_document", return_value="doc-1"):

            r = cli.post(
                f"/api/v1/packing/{bid}/upload",
                files={"file": ("pack.xlsx", open(str(xlsx), "rb"),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

        assert r.status_code == 200, r.text
        db_path_arg = cpa_mock.call_args[0][0]
        assert str(db_path_arg).endswith("reservation_queue.db")


# ── Reprocess path tests ──────────────────────────────────────────────────────

class TestCpaReprocessWiring:

    def test_cpa_called_after_reprocess_purchase(self, client, tmp_path):
        """In the reprocess route, CPA must fire after upsert_packing_lines
        for purchase_packing_list documents."""
        cli, storage = client
        bid = "B-CPA-RPR-01"
        out = _seed_batch(storage, bid)
        pp = out / "source" / "packing" / "purchase.xlsx"
        _fake_xlsx(pp)
        _register_purchase_doc(bid, pp)

        cpa_mock = MagicMock(return_value={
            "batch_id": bid, "upserted": ["EJL/26-27/001-1"],
            "upserted_count": 1, "skipped": [], "skipped_count": 0,
            "errors": {}, "error_count": 0,
        })

        mock_result = {**_MOCK_UPLOAD_RESULT,
                       "document": {**_MOCK_UPLOAD_RESULT["document"], "batch_id": bid,
                                    "file_path": str(pp), "filename": pp.name,
                                    "file_hash": "hh"},
                       "packing_rows": _MOCK_PACKING_ROWS}

        with patch("app.services.invoice_packing_extractor.process_packing_upload",
                   return_value=mock_result), \
             patch("app.services.packing_db.upsert_packing_lines", return_value=1), \
             patch("app.api.routes_packing.seed_purchase_transit"), \
             patch("app.services.cpa_product_service.upsert_product_master_from_packing",
                   cpa_mock), \
             patch("app.services.packing_db.upsert_packing_document", return_value="doc-1"), \
             patch("app.services.parser_diagnostic_writer.write_packing_diagnostic_artifact",
                   return_value=None):

            r = cli.post(f"/api/v1/packing/{bid}/reprocess")

        assert r.status_code == 200, r.text
        assert cpa_mock.called, "CPA must be called during reprocess of purchase packing list"
        assert cpa_mock.call_args[0][1] == bid

    def test_cpa_failure_does_not_block_reprocess(self, client, tmp_path):
        """A CPA exception in the reprocess path must be caught; reprocess
        still returns 200 with the file result."""
        cli, storage = client
        bid = "B-CPA-RPR-02"
        out = _seed_batch(storage, bid)
        pp = out / "source" / "packing" / "purchase.xlsx"
        _fake_xlsx(pp)
        _register_purchase_doc(bid, pp)

        mock_result = {**_MOCK_UPLOAD_RESULT,
                       "document": {**_MOCK_UPLOAD_RESULT["document"], "batch_id": bid,
                                    "file_path": str(pp), "filename": pp.name,
                                    "file_hash": "hh"},
                       "packing_rows": _MOCK_PACKING_ROWS}

        with patch("app.services.invoice_packing_extractor.process_packing_upload",
                   return_value=mock_result), \
             patch("app.services.packing_db.upsert_packing_lines", return_value=1), \
             patch("app.api.routes_packing.seed_purchase_transit"), \
             patch("app.services.cpa_product_service.upsert_product_master_from_packing",
                   side_effect=RuntimeError("CPA exploded")), \
             patch("app.services.packing_db.upsert_packing_document", return_value="doc-1"), \
             patch("app.services.parser_diagnostic_writer.write_packing_diagnostic_artifact",
                   return_value=None):

            r = cli.post(f"/api/v1/packing/{bid}/reprocess")

        assert r.status_code == 200, "CPA failure must not block reprocess (non-blocking)"

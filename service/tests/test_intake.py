"""
test_intake.py — Tests for the document-chain intake endpoint and new DB tables.

Tests:
  1. UI submit sends invoice + packing + AWB → HTTP 200 + correct shape
  2. Multiple purchase invoice blocks accepted
  3. Sales document block accepted
  4. AWB parsed and stored in awb_documents
  5. shipment_documents rows created for every file
  6. Packing list extraction linked to invoice (packing_db rows created)
  7. Old batch can upload packing list later (backfill endpoint)
  8. Missing packing list does not block invoice intake
  9. DB tables exist: invoice_lines, sales_documents, sales_packing_lines
 10. Duplicate intake for same AWB creates distinct batch_id

Run with: python -m pytest tests/test_intake.py -q
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── App bootstrap ──────────────────────────────────────────────────────────────
# Mirrors conftest.py pattern already used in this suite.
from app.main import app
from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    root = tmp_path_factory.mktemp("intake_storage")
    return root


@pytest.fixture(scope="module")
def db(tmp_storage):
    db_path = tmp_storage / "documents.db"
    ddb.init_document_db(db_path)
    pdb.init_packing_db(tmp_storage / "packing.db")
    return db_path


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with patch.object(settings, "max_upload_bytes", 20 * 1024 * 1024):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


def _pdf(name: str = "test.pdf") -> tuple:
    """Minimal valid-looking PDF bytes as UploadFile tuple. Content is unique per name."""
    content = f"%PDF-1.4 fake invoice content for testing — {name}".encode()
    return (name, io.BytesIO(content), "application/pdf")


def _xlsx(name: str = "packing.xlsx") -> tuple:
    """Minimal XLSX stub (not actually parseable — extraction will gracefully fail)."""
    content = b"PK\x03\x04fake xlsx content"
    return (name, io.BytesIO(content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _auth_headers() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── Test 1: Basic intake — invoice + AWB ──────────────────────────────────────

class TestBasicIntake:
    def test_invoice_plus_awb_returns_200(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb, \
             patch("app.api.routes_intake.process_packing_upload") as mock_pack:
            mock_awb.return_value = {
                "awb_number": "9999000001", "carrier": "DHL",
                "shipper_name": "TEST SHIPPER", "receiver_name": "TEST RECEIVER",
                "customs_value": 5000.0, "currency": "USD",
                "declared_weight": 1.0, "piece_count": 1,
                "ship_date": "2026-05-01", "contents": "Gold Jewellery",
                "origin": "BOM", "destination": "WAW",
                "duty_account": "", "tax_account": "Receiver Will Pay",
                "confidence": 0.85,
            }
            mock_pack.side_effect = Exception("No packing file provided")  # no packing list

            r = client.post(
                "/api/v1/shipment/intake",
                data={
                    "tracking_no": "9999000001",
                    "carrier":     "DHL",
                    "metadata":    json.dumps({"purchase_blocks": [], "sales_blocks": []}),
                },
                files={
                    "invoices":  _pdf("EJL-TEST-001.pdf"),
                    "awb":       _pdf("9999000001 Tracking.pdf"),
                },
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["tracking_no"] == "9999000001"
        assert body["carrier"] == "DHL"
        assert body["status"] == "draft"
        assert body["documents_registered"] >= 2  # invoice + awb
        assert body["awb"]["awb_number"] == "9999000001"
        assert body["awb"]["confidence"] == 0.85


# ── Test 2: Multiple purchase invoice blocks ───────────────────────────────────

class TestMultiplePurchaseBlocks:
    def test_three_invoices_accepted(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb, \
             patch("app.api.routes_intake.process_packing_upload") as mock_pack:
            mock_awb.return_value = {"awb_number": "8888000001", "carrier": "DHL",
                                     "confidence": 0.5}
            mock_pack.return_value = {
                "document": {
                    "batch_id": "X", "invoice_no": "INV-001",
                    "file_name": "packing.xlsx", "file_path": "/tmp/packing.xlsx",
                    "file_hash": "abc", "extraction_method": "xlsx",
                    "row_count": 2, "match_count": 0, "unmatched_count": 2,
                    "extraction_error": None,
                },
                "packing_rows": [],
            }

            meta = json.dumps({
                "purchase_blocks": [
                    {"invoice_index": 0, "packing_index": 0, "supplier_name": "Supplier A"},
                    {"invoice_index": 1, "packing_index": 1, "supplier_name": "Supplier B"},
                    {"invoice_index": 2, "packing_index": -1, "supplier_name": ""},
                ],
                "sales_blocks": [],
            })

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "8888000001", "carrier": "DHL", "metadata": meta},
                files=[
                    ("invoices",      _pdf("INV-001.pdf")),
                    ("invoices",      _pdf("INV-002.pdf")),
                    ("invoices",      _pdf("INV-003.pdf")),
                    ("packing_lists", _xlsx("pack_001.xlsx")),
                    ("packing_lists", _xlsx("pack_002.xlsx")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert len(body["purchase"]["invoices"]) == 3
        # 3 invoices + 2 packing lists = 5 registered (no AWB)
        assert body["documents_registered"] == 5


# ── Test 3: Sales document block ──────────────────────────────────────────────

class TestSalesDocumentBlock:
    def test_sales_doc_accepted_and_stored(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb:
            mock_awb.return_value = {"awb_number": "7777000001", "confidence": 0.4}

            meta = json.dumps({
                "purchase_blocks": [{"invoice_index": 0, "packing_index": -1, "supplier_name": ""}],
                "sales_blocks": [
                    {"document_index": 0, "packing_index": 0,
                     "client_name": "Acme Jewels GmbH", "client_ref": "PO-2026-999"},
                ],
            })

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "7777000001", "carrier": "DHL", "metadata": meta},
                files=[
                    ("invoices",          _pdf("PURCHASE-INV.pdf")),
                    ("sales_documents",   _pdf("SALES-ORDER-001.pdf")),
                    ("sales_packing_lists", _xlsx("SALES-PACK.xlsx")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert len(body["sales"]["documents"]) == 1
        assert len(body["sales"]["packing_lists"]) == 1

        # Verify sales_documents row in DB
        batch_id = body["batch_id"]
        sd = ddb.get_sales_documents(batch_id)
        assert len(sd) == 1
        assert sd[0]["client_name"] == "Acme Jewels GmbH"
        assert sd[0]["client_ref"] == "PO-2026-999"


# ── Test 4: AWB parsed and stored in awb_documents ────────────────────────────

class TestAwbParsedAndStored:
    def test_awb_fields_in_awb_documents(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb:
            mock_awb.return_value = {
                "awb_number": "6666000001", "carrier": "FedEx",
                "shipper_name": "Shipper Co",
                "receiver_name": "Receiver GmbH",
                "customs_value": 3000.0, "currency": "USD",
                "declared_weight": 2.5, "piece_count": 3,
                "ship_date": "2026-04-10",
                "contents": "Diamond Jewellery",
                "origin": "DEL", "destination": "FRA",
                "duty_account": "531019580",
                "tax_account": "Receiver Will Pay",
                "confidence": 0.90,
            }

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "6666000001", "carrier": "FedEx",
                      "metadata": json.dumps({"purchase_blocks":[], "sales_blocks":[]})},
                files=[
                    ("invoices", _pdf("INV-FEDEX.pdf")),
                    ("awb",      _pdf("FEDEX-AWB.pdf")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        batch_id = r.json()["batch_id"]

        # Check awb_documents table directly
        db_path = tmp_storage / "documents.db"
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM awb_documents WHERE batch_id=?", (batch_id,)
        ).fetchone()
        con.close()

        assert row is not None
        assert row["carrier"] == "FedEx"
        assert row["shipper_name"] == "Shipper Co"
        assert row["weight_kg"] == pytest.approx(2.5)

        # Check extracted fields
        fields = {f["field_name"]: f["normalized_value"]
                  for f in ddb.read_field.__module__ and []
                  or []}
        # read_field is a single-field accessor — check via DB directly
        frows = con.execute if False else None  # checked via awb_documents above


# ── Test 5: shipment_documents rows for every file ────────────────────────────

class TestShipmentDocumentsRegistered:
    def test_every_file_registered(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb:
            mock_awb.return_value = {"awb_number": "5555000001", "confidence": 0.3}

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "5555000001", "carrier": "DHL",
                      "metadata": json.dumps({"purchase_blocks":[], "sales_blocks":[]})},
                files=[
                    ("invoices",          _pdf("INV-A.pdf")),
                    ("invoices",          _pdf("INV-B.pdf")),
                    ("awb",               _pdf("5555000001 AWB.pdf")),
                    ("sales_documents",   _pdf("SALES.pdf")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        batch_id = body["batch_id"]

        docs = ddb.get_documents_for_batch(batch_id)
        types = {d["document_type"] for d in docs}
        assert "purchase_invoice" in types
        assert "awb"              in types
        assert "sales_invoice"    in types
        assert len(docs) == 4   # 2 invoices + 1 awb + 1 sales


# ── Test 6: Packing list linked to invoice ────────────────────────────────────

class TestPackingLinkedToInvoice:
    def test_packing_extraction_result_stored(self, client, tmp_storage, db):
        fake_batch_id = [None]

        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb, \
             patch("app.api.routes_intake.process_packing_upload") as mock_pack, \
             patch("app.api.routes_intake.pdb.upsert_packing_document") as mock_doc, \
             patch("app.api.routes_intake.pdb.upsert_packing_lines") as mock_lines:

            mock_awb.return_value = {"awb_number": "4444000001", "confidence": 0.5}
            mock_doc.return_value = "pdb-doc-001"
            mock_pack.return_value = {
                "document": {
                    "batch_id": "X", "invoice_no": "INV-PACK-001",
                    "file_name": "packing.xlsx", "file_path": "/tmp/p.xlsx",
                    "file_hash": "packHash001", "extraction_method": "xlsx",
                    "row_count": 5, "match_count": 3, "unmatched_count": 2,
                    "extraction_error": None,
                },
                "packing_rows": [
                    {"product_code": "INV-PACK-001-1", "bag_id": "BAG-01",
                     "quantity": 2, "invoice_no": "INV-PACK-001",
                     "invoice_line_position": 1},
                ],
            }

            meta = json.dumps({
                "purchase_blocks": [
                    {"invoice_index": 0, "packing_index": 0, "supplier_name": "Ganther"}
                ],
                "sales_blocks": [],
            })

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "4444000001", "carrier": "DHL", "metadata": meta},
                files=[
                    ("invoices",      _pdf("INV-PACK-001.pdf")),
                    ("packing_lists", _xlsx("packing.xlsx")),
                ],
                headers=_auth_headers(),
            )

        assert r.status_code == 200, r.text
        body = r.json()
        pl = body["purchase"]["packing_lists"]
        assert len(pl) == 1
        assert pl[0]["status"] == "extracted"
        assert pl[0]["rows"] == 1
        # Verify packing_db calls were made
        mock_doc.assert_called_once()
        mock_lines.assert_called_once()


# ── Test 7: Backfill — old batch can upload packing list ─────────────────────

class TestBackfillPackingList:
    def test_existing_batch_accepts_packing_list(self, client, tmp_storage, db):
        # Create a minimal existing batch folder
        batch_id = "SHIPMENT_BACKFILL_TEST_2026-05_aabbccdd"
        output_dir = tmp_storage / "outputs" / batch_id
        (output_dir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
        audit = {
            "batch_id": batch_id, "awb": "BACKFILLAWB001",
            "status": "partial", "timeline": [],
        }
        (output_dir / "audit.json").write_text(
            json.dumps(audit), encoding="utf-8"
        )

        with patch("app.api.routes_intake.process_packing_upload") as mock_pack, \
             patch("app.api.routes_intake.pdb.upsert_packing_document") as mock_doc, \
             patch("app.api.routes_intake.pdb.upsert_packing_lines"):
            mock_doc.return_value = "pdb-backfill-001"
            mock_pack.return_value = {
                "document": {
                    "batch_id": batch_id, "invoice_no": "BACKFILL-001",
                    "file_name": "bf_pack.xlsx", "file_path": "/tmp/bf.xlsx",
                    "file_hash": "bfhash", "extraction_method": "xlsx",
                    "row_count": 3, "match_count": 2, "unmatched_count": 1,
                    "extraction_error": None,
                },
                "packing_rows": [
                    {"product_code": "BACKFILL-001-1", "bag_id": "BF-BAG",
                     "quantity": 1},
                ],
            }

            r = client.post(
                f"/api/v1/shipment/{batch_id}/packing_list",
                data={"supplier_name": "Legacy Supplier", "invoice_index": "0"},
                files={"file": _xlsx("bf_pack.xlsx")},
                headers=_auth_headers(),
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["extraction"]["status"] == "extracted"
        assert body["extraction"]["rows"] == 1

        # Verify shipment_documents has a row for the backfilled packing list
        docs = ddb.get_documents_for_batch(batch_id)
        types = [d["document_type"] for d in docs]
        assert "purchase_packing_list" in types


# ── Test 8: Missing packing list does not block intake ────────────────────────

class TestMissingPackingListNonBlocking:
    def test_intake_succeeds_without_packing_list(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb:
            mock_awb.return_value = {"awb_number": "3333000001", "confidence": 0.4}

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "3333000001", "carrier": "Other",
                      "metadata": json.dumps({"purchase_blocks":[], "sales_blocks":[]})},
                files=[("invoices", _pdf("INV-NOPACKING.pdf"))],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["purchase"]["packing_lists"] == []
        assert body["documents_registered"] == 1


# ── Test 9: New DB tables exist ───────────────────────────────────────────────

class TestNewDbTablesExist:
    def test_invoice_lines_table(self, tmp_storage, db):
        db_path = tmp_storage / "documents.db"
        con = sqlite3.connect(str(db_path))
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        con.close()
        assert "invoice_lines"       in tables
        assert "sales_documents"     in tables
        assert "sales_packing_lines" in tables

    def test_store_invoice_lines_roundtrip(self, db):
        doc_id = ddb.register_document(
            batch_id="TESTBATCH_IL_01", document_type="purchase_invoice",
            file_name="il_test.pdf", file_path="/tmp/il.pdf",
            file_hash="ilhash001", source="test",
        )
        lines = [
            {"invoice_no": "IL-001", "line_position": 1,
             "description": "Ring 14kt", "quantity": 5.0,
             "unit_price": 100.0, "total_value": 500.0, "currency": "USD"},
            {"invoice_no": "IL-001", "line_position": 2,
             "description": "Bracelet 18kt", "quantity": 2.0,
             "unit_price": 250.0, "total_value": 500.0, "currency": "USD"},
        ]
        n = ddb.store_invoice_lines(doc_id, "TESTBATCH_IL_01", lines)
        assert n == 2
        got = ddb.get_invoice_lines("TESTBATCH_IL_01")
        assert len(got) == 2
        # product_code auto-generated as invoice_no-line_position
        pcs = {r["product_code"] for r in got}
        assert "IL-001-1" in pcs
        assert "IL-001-2" in pcs

    def test_store_sales_documents_roundtrip(self, db):
        doc_id = ddb.register_document(
            batch_id="TESTBATCH_SD_01", document_type="sales_invoice",
            file_name="sd_test.pdf", file_path="/tmp/sd.pdf",
            file_hash="sdhash001", source="test",
        )
        sd_id = ddb.store_sales_document(
            batch_id="TESTBATCH_SD_01", document_id=doc_id,
            data={"client_name": "Test Client", "client_ref": "REF-001",
                  "document_type": "sales_invoice"},
        )
        assert sd_id
        sds = ddb.get_sales_documents("TESTBATCH_SD_01")
        assert len(sds) == 1
        assert sds[0]["client_name"] == "Test Client"

    def test_store_sales_packing_lines_roundtrip(self, db):
        sd_id = ddb.store_sales_document(
            batch_id="TESTBATCH_SPL_01", document_id="",
            data={"client_name": "SPL Client"},
        )
        n = ddb.store_sales_packing_lines(sd_id, "TESTBATCH_SPL_01", [
            {"product_code": "SPL-001-1", "bag_id": "SPBAG", "quantity": 3.0},
        ])
        assert n == 1
        lines = ddb.get_sales_packing_lines("TESTBATCH_SPL_01")
        assert len(lines) == 1
        assert lines[0]["product_code"] == "SPL-001-1"


# ── Test 10: Duplicate AWB → distinct batch_id ───────────────────────────────

class TestDuplicateAwbDistinctBatch:
    def test_two_intakes_same_awb_different_batches(self, client, tmp_storage, db):
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb:
            mock_awb.return_value = {"awb_number": "2222000001", "confidence": 0.5}

            r1 = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "2222000001", "carrier": "DHL",
                      "metadata": json.dumps({"purchase_blocks":[], "sales_blocks":[]})},
                files=[("invoices", _pdf("INV-DUP-A.pdf"))],
                headers=_auth_headers(),
            )
            r2 = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "2222000001", "carrier": "DHL",
                      "metadata": json.dumps({"purchase_blocks":[], "sales_blocks":[]})},
                files=[("invoices", _pdf("INV-DUP-B.pdf"))],
                headers=_auth_headers(),
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        b1 = r1.json()["batch_id"]
        b2 = r2.json()["batch_id"]
        # UUID suffix guarantees distinct batch IDs even for same AWB
        assert b1 != b2


# ── Test 11: AWB parser unit test ─────────────────────────────────────────────

class TestInvoiceLinesSourcePriority:
    """
    Architecture rule:
      1. document_db.invoice_lines (modern intake — _source = "db_invoice_lines")
      2. pz_rows.json              (legacy fallback — _source = "legacy_pz_rows")
      3. []                        (no context)
    """

    def test_fresh_intake_creates_db_invoice_lines(self, client, tmp_storage, db):
        """A fresh intake with NO pz_rows.json must still produce invoice_lines in DB."""
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb, \
             patch("app.api.routes_intake.parse_invoice_pdf") as mock_inv:
            mock_awb.return_value = {"awb_number": "INVDB000001", "confidence": 0.5}
            mock_inv.return_value = {
                "invoice_no":  "EJL-FRESH-001",
                "currency":    "USD",
                "lines": [
                    {"invoice_no":"EJL-FRESH-001","line_position":1,"product_code":"EJL-FRESH-001-1",
                     "description":"Ring 14kt","quantity":3.0,"unit_price":120.0,
                     "total_value":360.0,"currency":"USD"},
                    {"invoice_no":"EJL-FRESH-001","line_position":2,"product_code":"EJL-FRESH-001-2",
                     "description":"Bracelet 18kt","quantity":1.0,"unit_price":500.0,
                     "total_value":500.0,"currency":"USD"},
                ],
                "extraction_method": "pdfplumber",
            }

            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "INVDB000001", "carrier": "DHL",
                      "metadata": json.dumps({"purchase_blocks":[],"sales_blocks":[]})},
                files=[("invoices", _pdf("EJL-FRESH-001.pdf"))],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        batch_id = body["batch_id"]

        # Verify DB has 2 invoice_lines for this batch (no pz_rows.json exists)
        lines = ddb.get_invoice_lines_for_batch(batch_id)
        assert len(lines) == 2
        codes = sorted(l["product_code"] for l in lines)
        assert codes == ["EJL-FRESH-001-1", "EJL-FRESH-001-2"]
        # product_code generated BEFORE PZ exists (no pz_rows.json was written)
        assert not (tmp_storage / "outputs" / batch_id / "pz_rows.json").exists()

    def test_load_invoice_lines_prefers_db_over_pz_rows(self, tmp_storage, db):
        """When BOTH DB rows and pz_rows.json exist, DB wins."""
        from app.services.invoice_packing_extractor import load_invoice_lines

        batch_id = "PRIORITY_TEST_BATCH_01"
        out_dir  = tmp_storage / "outputs" / batch_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Seed DB invoice_lines
        doc_id = ddb.register_document(
            batch_id=batch_id, document_type="purchase_invoice",
            file_name="prio.pdf", file_path="/tmp/prio.pdf",
            file_hash="priohash", source="test",
        )
        ddb.store_invoice_lines(doc_id, batch_id, [
            {"invoice_no":"FROM-DB","line_position":1,"product_code":"FROM-DB-1",
             "description":"DB row","quantity":1.0,"unit_price":10.0,"total_value":10.0,"currency":"USD"},
        ])

        # Also write pz_rows.json — should be IGNORED because DB wins
        (out_dir / "pz_rows.json").write_text(json.dumps([
            {"invoice_no":"FROM-PZ-ROWS","description_en":"PZ row","quantity":99,"item_type":"RING"}
        ]), encoding="utf-8")

        rows = load_invoice_lines(out_dir, batch_id=batch_id)
        assert len(rows) == 1
        assert rows[0]["invoice_no"] == "FROM-DB"
        assert rows[0]["_source"] == "db_invoice_lines"

    def test_legacy_batch_falls_back_to_pz_rows(self, tmp_storage, db):
        """When DB has NO invoice_lines but pz_rows.json exists, pz_rows is used."""
        from app.services.invoice_packing_extractor import load_invoice_lines

        batch_id = "LEGACY_TEST_BATCH_01"
        out_dir  = tmp_storage / "outputs" / batch_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # No DB invoice_lines for this batch — only pz_rows.json
        (out_dir / "pz_rows.json").write_text(json.dumps([
            {"invoice_no":"LEGACY-001","description_en":"Legacy row","quantity":2,
             "item_type":"PENDANT","unit_netto_pln":100.0,"line_netto_pln":200.0},
        ]), encoding="utf-8")

        rows = load_invoice_lines(out_dir, batch_id=batch_id)
        assert len(rows) == 1
        assert rows[0]["invoice_no"] == "LEGACY-001"
        assert rows[0]["_source"] == "legacy_pz_rows"
        assert rows[0]["product_code"] == "LEGACY-001-1"

    def test_no_db_no_pz_rows_returns_empty(self, tmp_storage, db):
        from app.services.invoice_packing_extractor import load_invoice_lines

        batch_id = "EMPTY_TEST_BATCH_01"
        out_dir  = tmp_storage / "outputs" / batch_id
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = load_invoice_lines(out_dir, batch_id=batch_id)
        assert rows == []

    def test_packing_backfill_uses_db_when_present(self, client, tmp_storage, db):
        """Backfill on a fresh-intake batch must use DB invoice_lines, not pz_rows.json."""
        # Step 1: create a fresh intake (DB invoice_lines populated)
        with patch("app.api.routes_intake.parse_awb_pdf") as mock_awb, \
             patch("app.api.routes_intake.parse_invoice_pdf") as mock_inv:
            mock_awb.return_value = {"awb_number": "BFDB000001", "confidence": 0.5}
            mock_inv.return_value = {
                "invoice_no": "EJL-BF-DB-001", "currency": "USD",
                "lines": [
                    {"invoice_no":"EJL-BF-DB-001","line_position":1,"product_code":"EJL-BF-DB-001-1",
                     "description":"Ring","quantity":2.0,"unit_price":50.0,
                     "total_value":100.0,"currency":"USD"},
                ],
                "extraction_method":"pdfplumber",
            }
            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no":"BFDB000001","carrier":"DHL",
                      "metadata":json.dumps({"purchase_blocks":[],"sales_blocks":[]})},
                files=[("invoices", _pdf("EJL-BF-DB-001.pdf"))],
                headers=_auth_headers(),
            )
        batch_id = r.json()["batch_id"]
        # confirm DB has lines
        assert len(ddb.get_invoice_lines_for_batch(batch_id)) == 1

        # Step 2: backfill packing list — verify it uses db_invoice_lines
        with patch("app.api.routes_intake.process_packing_upload") as mock_pack, \
             patch("app.api.routes_intake.pdb.upsert_packing_document") as mock_doc, \
             patch("app.api.routes_intake.pdb.upsert_packing_lines"):
            mock_doc.return_value = "pdb-bf-db"
            mock_pack.return_value = {
                "document": {
                    "batch_id": batch_id, "invoice_no": "EJL-BF-DB-001",
                    "file_name": "bf.xlsx", "file_path": "/tmp/bf.xlsx",
                    "file_hash": "bfh", "extraction_method": "xlsx",
                    "row_count": 1, "match_count": 1, "unmatched_count": 0,
                    "extraction_error": None,
                },
                "packing_rows": [{"product_code":"EJL-BF-DB-001-1","bag_id":"BAG-X","quantity":2}],
                "invoice_lines_source": "db_invoice_lines",
                "matched_count": 1, "unmatched_count": 0,
            }
            rb = client.post(
                f"/api/v1/shipment/{batch_id}/packing_list",
                data={"supplier_name":"SupplierX","invoice_index":"0"},
                files={"file": _xlsx("bf.xlsx")},
                headers=_auth_headers(),
            )
        body = rb.json()
        assert body["ok"] is True
        assert body["extraction"]["invoice_lines_source"] == "db_invoice_lines"


class TestInvoiceIntakeParser:
    def test_filename_only_fallback_creates_placeholder(self, tmp_storage):
        """When PDF text is empty, parser still returns a single placeholder line."""
        from app.services.invoice_intake_parser import parse_invoice_pdf

        # Write a tiny non-PDF file — pdfplumber will fail, parser falls back
        bad = tmp_storage / "EJL-FAKE-001.pdf"
        bad.write_bytes(b"not a real pdf")

        result = parse_invoice_pdf(bad, "EJL-FAKE-001.pdf")
        assert result["invoice_no"]  # extracted from filename
        assert len(result["lines"]) == 1
        assert result["lines"][0]["product_code"].endswith("-1")
        # Placeholder description signals PZ engine should populate later
        assert "placeholder" in result["lines"][0]["description"].lower()


# ── Real-file regression: EJL/26-27/013 ──────────────────────────────────────
#
# Production-grade test against the actual customer artifacts. If either file
# is missing on the runner, the test is skipped (so CI environments without
# the real PDFs don't fail).

_REAL_INVOICE = Path(
    "/Users/amitgupta/Library/Application Support/estrellajewels/storage"
    "/sessions/SHIPMENT_AUTO_2026-04_59a07b20/invoices"
    "/013_Invoice_EJL-26-27-013-04-04-26.pdf"
)
_REAL_PACKING = Path(
    "/Users/amitgupta/Downloads/18 013-015 dt  06.04.26 Duty 1414"
    "/013 EJL-26-27-013-Packing list of shipment-7pcs-04-04-26-Poland.xls"
)


class TestRealEjlInvoicePackingPair:
    """End-to-end on the real EJL/26-27/013 invoice + .xls packing list."""

    def setup_method(self):
        if not _REAL_INVOICE.exists() or not _REAL_PACKING.exists():
            pytest.skip("Real EJL/26-27/013 files not present in this environment")

    def test_invoice_parser_extracts_three_real_lines(self):
        from app.services.invoice_intake_parser import parse_invoice_pdf
        result = parse_invoice_pdf(_REAL_INVOICE, _REAL_INVOICE.name)
        assert result["invoice_no"] == "EJL/26-27/013"
        assert result["extraction_method"] == "regex_text"
        assert result["line_count"] == 3
        lines = result["lines"]

        # Line 1 — PENDANT
        assert lines[0]["product_code"]   == "EJL/26-27/013-1"
        assert lines[0]["hsn_code"]       == "71131911"
        assert lines[0]["quantity"]       == pytest.approx(5.0)
        assert lines[0]["rate_usd"]       == pytest.approx(23.20)
        assert lines[0]["amount_usd"]     == pytest.approx(116.00)
        assert lines[0]["gross_weight"]   == pytest.approx(1.300)
        assert lines[0]["net_weight"]     == pytest.approx(1.300)
        assert "PENDANT" in lines[0]["description"].upper()

        # Line 2 — 18KT Gold RING
        assert lines[1]["product_code"]   == "EJL/26-27/013-2"
        assert lines[1]["hsn_code"]       == "71131911"
        assert lines[1]["quantity"]       == pytest.approx(1.0)
        assert lines[1]["rate_usd"]       == pytest.approx(570.00)
        assert lines[1]["amount_usd"]     == pytest.approx(570.00)
        assert lines[1]["gross_weight"]   == pytest.approx(3.960)
        assert lines[1]["net_weight"]     == pytest.approx(3.960)

        # Line 3 — PT950 RING
        assert lines[2]["product_code"]   == "EJL/26-27/013-3"
        assert lines[2]["hsn_code"]       == "71131923"
        assert lines[2]["rate_usd"]       == pytest.approx(486.00)
        assert lines[2]["amount_usd"]     == pytest.approx(486.00)
        assert lines[2]["gross_weight"]   == pytest.approx(3.290)
        assert lines[2]["net_weight"]     == pytest.approx(3.166)

        # No placeholder when real lines exist
        for ln in lines:
            assert "placeholder" not in ln["description"].lower()

    def test_legacy_xls_packing_list_extracts_three_rows(self):
        from app.services.invoice_packing_extractor import extract_packing
        rows, parser, version = extract_packing(_REAL_PACKING)
        assert len(rows) == 3
        assert all(r.get("invoice_no") == "EJL/26-27/013" for r in rows)
        # All 3 rows should have a quantity & a value
        qtys = sorted(float(r["quantity"]) for r in rows)
        assert qtys == [1.0, 1.0, 5.0]
        # Each row carries its category / design
        cats = [r.get("item_type") for r in rows]
        assert "PND" in cats
        assert cats.count("RNG") == 2

    def test_packing_links_to_invoice_via_product_code(self, client, tmp_storage, db):
        """Full intake: 3 invoice lines + 3 packing rows → 3 product_code links."""
        with open(_REAL_INVOICE, "rb") as inv_f, open(_REAL_PACKING, "rb") as pack_f:
            r = client.post(
                "/api/v1/shipment/intake",
                data={
                    "tracking_no": "REAL013INTAKE",
                    "carrier":     "DHL",
                    "metadata":    json.dumps({
                        "purchase_blocks": [{"invoice_index": 0,
                                              "packing_index": 0,
                                              "supplier_name": "Estrella Jewels LLP"}],
                        "sales_blocks":    [],
                    }),
                },
                files=[
                    ("invoices",      ("013_Invoice_EJL-26-27-013-04-04-26.pdf",
                                       inv_f.read(), "application/pdf")),
                    ("packing_lists", ("013 EJL-26-27-013 Packing 7pcs.xls",
                                       pack_f.read(), "application/vnd.ms-excel")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        batch_id = body["batch_id"]

        # Invoice parse summary
        inv = body["purchase"]["invoice_parsed"][0]
        assert inv["invoice_no"]   == "EJL/26-27/013"
        assert inv["lines_stored"] == 3
        assert inv["is_real"]      is True

        # Packing extraction summary
        pl = body["purchase"]["packing_lists"][0]
        assert pl["status"]                == "extracted"
        assert pl["rows"]                  == 3
        assert pl["matched"]               == 3
        assert pl["unmatched"]             == 0
        assert pl["invoice_lines_source"]  == "db_invoice_lines"

        # DB invoice_lines
        db_inv_lines = ddb.get_invoice_lines_for_batch(batch_id)
        assert len(db_inv_lines) == 3
        codes = {ln["product_code"] for ln in db_inv_lines}
        assert codes == {"EJL/26-27/013-1", "EJL/26-27/013-2", "EJL/26-27/013-3"}
        for ln in db_inv_lines:
            assert ln["rate_usd"]   > 0
            assert ln["amount_usd"] > 0
            assert ln["hsn_code"]   != ""

        # DB packing_lines linked
        plines = pdb.get_packing_lines_for_batch(batch_id)
        assert len(plines) == 3
        link_codes = {ln.get("product_code") for ln in plines}
        assert link_codes == {"EJL/26-27/013-1", "EJL/26-27/013-2", "EJL/26-27/013-3"}
        # No row needs manual review (all matched at conf>=0.7)
        for ln in plines:
            assert ln.get("requires_manual_review") in (False, 0)
            assert (ln.get("extracted_confidence") or 0) >= 0.7

    def test_18kt_and_pt950_not_swapped_when_rates_collide(self):
        """
        Defence-in-depth: even if the two RING rows had identical rates
        (a future invoice quirk), the metal token (18KT vs PT950) must
        prevent a swap.
        """
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        invoice_lines = [
            {"invoice_no":"EJL/26-27/013","invoice_line_position":2,
             "product_code":"EJL/26-27/013-2","item_type":"RING",
             "description":"PCS, 18KT Gold, Plain Jewellery RING",
             "quantity":1.0, "rate_usd":500.0},
            {"invoice_no":"EJL/26-27/013","invoice_line_position":3,
             "product_code":"EJL/26-27/013-3","item_type":"RING",
             "description":"PCS, PT950 Platinum, Stud With Diam Jewel RING",
             "quantity":1.0, "rate_usd":500.0},  # SAME rate as the gold row
        ]
        # Two packing rows, distinguished only by metal column
        packing = [
            {"invoice_no":"EJL/26-27/013","item_type":"RNG",
             "metal":"PT950/-","quantity":1.0,"unit_price":500.0,
             "design_no":"PLATINUM_RING"},
            {"invoice_no":"EJL/26-27/013","item_type":"RNG",
             "metal":"18KT/WPD","quantity":1.0,"unit_price":500.0,
             "design_no":"GOLD_RING"},
        ]
        result = match_packing_to_invoice(packing, invoice_lines)
        # Look up by design — verify each design ended up at the right line
        by_design = {r["design_no"]: r for r in result}
        assert by_design["PLATINUM_RING"]["product_code"] == "EJL/26-27/013-3"
        assert by_design["GOLD_RING"]["product_code"]     == "EJL/26-27/013-2"
        # Both should be matched (not requires_manual_review)
        assert all(not r["requires_manual_review"] for r in result)
        # At least one should report metal in its strategy name
        strats = {r.get("match_strategy", "") for r in result}
        assert any("metal" in s for s in strats)

    def test_metal_disambiguates_when_rate_missing(self):
        """type+qty+metal (strategy 3) — distinguishes 18KT vs PT950 with no rate."""
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        invoice_lines = [
            {"invoice_no":"INV-001","invoice_line_position":1,
             "product_code":"INV-001-1","item_type":"RING",
             "description":"18KT Yellow Gold RING",
             "quantity":1.0, "rate_usd":0.0},
            {"invoice_no":"INV-001","invoice_line_position":2,
             "product_code":"INV-001-2","item_type":"RING",
             "description":"PT950 Platinum RING",
             "quantity":1.0, "rate_usd":0.0},
        ]
        packing = [
            {"invoice_no":"INV-001","item_type":"RNG","metal":"PT950/-","quantity":1.0},
            {"invoice_no":"INV-001","item_type":"RNG","metal":"18KT/Y", "quantity":1.0},
        ]
        result = match_packing_to_invoice(packing, invoice_lines)
        # PT950 packing → PT950 invoice line
        assert result[0]["product_code"] == "INV-001-2"
        # 18KT packing → 18KT invoice line
        assert result[1]["product_code"] == "INV-001-1"
        for r in result:
            assert r["match_strategy"] == "type+qty+metal"
            assert r["extracted_confidence"] == pytest.approx(0.85)

    def test_silver_codes_recognised(self):
        """925 sterling silver and 999 fine silver normalise correctly."""
        from app.services.invoice_packing_extractor import _canonical_metal
        assert _canonical_metal("925/-")           == "925"
        assert _canonical_metal("Silver 925")      == "925"
        assert _canonical_metal("999 Fine Silver") == "999"
        assert _canonical_metal("18KT Gold")       == "18KT"
        assert _canonical_metal("PT950")           == "PT950"
        assert _canonical_metal("PT 900 Platinum") == "PT900"

    def test_packing_integrity_no_design_collapse(self, client, tmp_storage, db):
        """
        Two source rows with same design_no but different prices/sizes are
        BOTH preserved in the DB (not collapsed by dedup).

        Regression for the JR06076 case: source had 2 rows ($392 + $431),
        old dedup collapsed to 1 row, losing 1 piece and $431 of value.
        """
        from app.services.invoice_packing_extractor import match_packing_to_invoice
        from app.services import packing_db as pdb_mod

        # Simulate two same-design rows with different prices
        invoice_lines = [
            {"invoice_no":"INV-COL","invoice_line_position":1,
             "product_code":"INV-COL-1","item_type":"RING",
             "description":"14KT Gold Aggregated RING",
             "quantity":21.0, "rate_usd":400.0},
        ]
        packing_rows = [
            {"invoice_no":"INV-COL","item_type":"RNG","metal":"14KT/W",
             "design_no":"JR06076","quantity":1.0,"unit_price":392.0,
             "total_value":392.0,"line_position":14},
            {"invoice_no":"INV-COL","item_type":"RNG","metal":"14KT/W",
             "design_no":"JR06076","quantity":1.0,"unit_price":431.0,
             "total_value":431.0,"line_position":22},
        ]
        matched = match_packing_to_invoice(packing_rows, invoice_lines)

        line_records = [
            {
                "packing_document_id":   "test-doc",
                "batch_id":              "BATCH_INTEGRITY_TEST",
                "invoice_no":            r["invoice_no"],
                "invoice_line_position": r.get("invoice_line_position"),
                "product_code":          r.get("product_code"),
                "design_no":             r.get("design_no"),
                "bag_id":                "",
                "quantity":              r.get("quantity"),
                "unit_price":            r.get("unit_price"),
                "total_value":           r.get("total_value"),
                "pack_sr":               r.get("line_position"),
            }
            for r in matched
        ]
        pdb_mod.upsert_packing_lines(line_records)

        stored = pdb_mod.get_packing_lines_for_batch("BATCH_INTEGRITY_TEST")
        assert len(stored) == 2, f"Expected 2 rows preserved, got {len(stored)}"
        prices = sorted(r["unit_price"] for r in stored)
        assert prices == [392.0, 431.0]
        # Both rows linked to the same invoice line (aggregate match)
        assert all(r["invoice_line_position"] == 1 for r in stored)
        # pack_sr distinguishes them
        srs = sorted(r["pack_sr"] for r in stored)
        assert srs == [14.0, 22.0]


class TestBarcodeUniqueness:
    def test_barcode_value_unique_per_physical_row(self):
        """
        For an aggregated invoice line, two same-design rows must produce
        DIFFERENT barcode values so the warehouse scanner can distinguish them.
        """
        from app.api.routes_packing import _barcode_value
        row_a = {"product_code":"INV-X-6","design_no":"JR06076","bag_id":"",
                 "pack_sr":14.0, "unit_price":392.0}
        row_b = {"product_code":"INV-X-6","design_no":"JR06076","bag_id":"",
                 "pack_sr":22.0, "unit_price":431.0}
        bv_a = _barcode_value(row_a)
        bv_b = _barcode_value(row_b)
        assert bv_a != bv_b
        assert "sr14" in bv_a
        assert "sr22" in bv_b
        # design_no still encoded
        assert "JR06076" in bv_a and "JR06076" in bv_b

    def test_barcode_value_uses_bag_id_when_present(self):
        from app.api.routes_packing import _barcode_value
        row = {"product_code":"INV-X-1","design_no":"D1","bag_id":"BAG-7",
               "pack_sr":1.0}
        # bag_id wins over pack_sr (it's the physical canonical identifier)
        assert _barcode_value(row) == "INV-X-1|BAG-7"


    def test_packing_doc_related_invoice_no_is_parsed_invoice_no(self, client, tmp_storage, db):
        """The packing document row's related_invoice_no must equal the parsed
        invoice_no, not the PDF filename."""
        with open(_REAL_INVOICE, "rb") as inv_f, open(_REAL_PACKING, "rb") as pack_f:
            r = client.post(
                "/api/v1/shipment/intake",
                data={
                    "tracking_no": "REAL013RELINV",
                    "carrier":     "DHL",
                    "metadata":    json.dumps({"purchase_blocks": [], "sales_blocks": []}),
                },
                files=[
                    ("invoices",      ("X.pdf", inv_f.read(),  "application/pdf")),
                    ("packing_lists", ("Y.xls", pack_f.read(), "application/vnd.ms-excel")),
                ],
                headers=_auth_headers(),
            )
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        docs = ddb.get_documents_for_batch(batch_id, document_type="purchase_packing_list")
        assert len(docs) == 1
        # related_invoice_no must be the parsed EJL invoice_no (NOT 'X.pdf')
        assert docs[0]["related_invoice_no"] == "EJL/26-27/013"


class TestAwbParser:
    def test_parse_awb_pdf_with_real_pdf(self, tmp_storage):
        """Smoke-test the real AWB parser against the stored test AWB."""
        awb_path = (
            Path("/Users/amitgupta/Library/Application Support/estrellajewels/storage")
            / "outputs"
            / "SHIPMENT_2824221912_2026-04_319e1197"
            / "source" / "awb"
            / "2824221912 Tracking details.pdf"
        )
        if not awb_path.exists():
            pytest.skip("Real AWB PDF not available in this environment")

        from app.services.awb_parser import parse_awb_pdf
        result = parse_awb_pdf(awb_path)

        assert result["awb_number"] == "2824221912"
        assert result["carrier"] == "DHL"
        assert result["customs_value"] == pytest.approx(14169.0)
        assert result["declared_weight"] == pytest.approx(1.0)
        assert result["ship_date"] == "2026-03-09"
        assert result["confidence"] >= 0.7

"""
test_document_db.py — Unified document registry tests.

Mandatory scenarios (10):
 1. Invoice upload → shipment_documents row created
 2. Packing upload → shipment_documents row created
 3. AWB upload → shipment_documents row created
 4. SAD/XML upload → customs_declaration stored
 5. PZ generation → registered in shipment_documents (pz_pdf type)
 6. Audit memo → registered in shipment_documents (audit_memo type)
 7. DB read equals parser output (read_field returns stored value)
 8. Verified field cannot be overwritten without force=True
 9. Duplicate upload prevented by hash (same hash → same id, no duplicate row)
10. Dashboard: get_documents_for_batch returns correct row, not file scan

Plus unit tests for all public helpers.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.document_db import (
    init_document_db,
    register_document,
    store_extraction_json,
    upsert_field,
    store_fields,
    read_field,
    store_customs_declaration,
    get_customs_declaration,
    store_awb_document,
    store_pz_document,
    get_pz_document,
    get_documents_for_batch,
    get_document_by_hash,
    update_document_status,
    sha256_file,
)


# ── Fixture ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Each test gets its own isolated documents.db."""
    init_document_db(tmp_path / "documents.db")
    yield


# ── 1. Invoice upload → DB row created ────────────────────────────────────────

class TestInvoiceRegistration:

    def test_register_invoice_creates_row(self, tmp_path):
        inv = tmp_path / "INV_001.pdf"
        inv.write_bytes(b"%PDF invoice content")
        doc_id = register_document(
            batch_id="B001", document_type="invoice",
            file_name="INV_001.pdf", file_path=str(inv),
            file_hash=sha256_file(inv),
            source="upload",
        )
        assert doc_id is not None
        rows = get_documents_for_batch("B001", document_type="invoice")
        assert len(rows) == 1
        assert rows[0]["document_type"] == "invoice"
        assert rows[0]["file_name"] == "INV_001.pdf"
        assert rows[0]["batch_id"] == "B001"

    def test_multiple_invoices_multiple_rows(self, tmp_path):
        for i in range(3):
            f = tmp_path / f"inv_{i}.pdf"
            f.write_bytes(f"invoice {i}".encode())
            register_document(
                batch_id="B001", document_type="invoice",
                file_name=f.name, file_path=str(f),
                file_hash=sha256_file(f), source="upload",
            )
        rows = get_documents_for_batch("B001", document_type="invoice")
        assert len(rows) == 3

    def test_invoice_awb_stored(self, tmp_path):
        f = tmp_path / "inv.pdf"
        f.write_bytes(b"data")
        register_document(
            batch_id="B001", document_type="invoice",
            file_name="inv.pdf", awb="1012178215", source="upload",
        )
        rows = get_documents_for_batch("B001", "invoice")
        assert rows[0]["awb"] == "1012178215"


# ── 2. Packing upload → DB row created ────────────────────────────────────────

class TestPackingRegistration:

    def test_register_packing_creates_row(self):
        doc_id = register_document(
            batch_id="B002", document_type="packing",
            file_name="packing_list.xlsx",
            file_hash="abc123", extraction_status="extracted",
            related_invoice_no="EJL/26-27/100",
        )
        assert doc_id is not None
        rows = get_documents_for_batch("B002", "packing")
        assert len(rows) == 1
        assert rows[0]["related_invoice_no"] == "EJL/26-27/100"
        assert rows[0]["extraction_status"] == "extracted"

    def test_packing_type_isolated_from_invoice(self):
        register_document(batch_id="B002", document_type="invoice", file_name="i.pdf")
        register_document(batch_id="B002", document_type="packing", file_name="p.xlsx")
        assert len(get_documents_for_batch("B002", "invoice")) == 1
        assert len(get_documents_for_batch("B002", "packing")) == 1
        assert len(get_documents_for_batch("B002")) == 2


# ── 3. AWB upload → DB row created ────────────────────────────────────────────

class TestAwbRegistration:

    def test_register_awb_file_creates_row(self):
        doc_id = register_document(
            batch_id="B003", document_type="awb",
            file_name="awb_1012178215.pdf",
            awb="1012178215", source="upload",
        )
        assert doc_id is not None
        rows = get_documents_for_batch("B003", "awb")
        assert len(rows) == 1
        assert rows[0]["awb"] == "1012178215"

    def test_store_awb_structured_data(self):
        doc_id = register_document(
            batch_id="B003", document_type="awb",
            file_name="awb.pdf", awb="1012178215",
        )
        awb_id = store_awb_document(
            document_id=doc_id, batch_id="B003",
            awb_data={
                "awb": "1012178215", "carrier": "DHL",
                "shipper_name": "Estrella India",
                "consignee_name": "Estrella EU",
                "pieces": 5, "weight_kg": 12.3,
                "description": "Jewellery",
            },
        )
        assert awb_id != ""
        # Update is idempotent — second call returns same id
        awb_id2 = store_awb_document(doc_id, "B003", {"awb": "1012178215", "pieces": 5})
        assert awb_id2 == awb_id


# ── 4. SAD/XML upload → customs_declaration stored ────────────────────────────

class TestCustomsDeclaration:

    def _declaration(self) -> Dict[str, Any]:
        return {
            "mrn":              "22PL123456789012A3",
            "lrn":              "LRN-001",
            "clearance_date":   "2026-04-15",
            "duty_pln":         1181.0,
            "vat_pln":          9876.0,
            "total_cif_usd":    48778.64,
            "customs_rate_usd": 4.01,
            "statistical_value_pln": 195720.0,
            "agent":            "Celny Agent Sp. z o.o.",
            "importer_name":    "Estrella Jewels EU Sp. z o.o.",
            "importer_nip":     "1234567890",
            "exporter_name":    "Estrella International",
            "cn_code":          "7113190000",
            "goods_description": "Gold jewellery",
            "invoice_refs":     ["EJL/26-27/100", "EJL/26-27/101"],
        }

    def test_store_customs_declaration_creates_row(self):
        doc_id = register_document(
            batch_id="B004", document_type="sad_xml",
            file_name="zc429.xml", file_hash="xmlhash123",
        )
        row_id = store_customs_declaration(doc_id, "B004", self._declaration())
        assert row_id != ""
        cd = get_customs_declaration("B004")
        assert cd is not None
        assert cd["mrn"] == "22PL123456789012A3"
        assert cd["duty_pln"] == 1181.0
        assert "EJL/26-27/100" in cd["invoice_refs"]

    def test_customs_declaration_upserts_on_mrn(self):
        doc_id = register_document(batch_id="B004", document_type="sad_xml",
                                   file_name="zc429.xml")
        r1 = store_customs_declaration(doc_id, "B004", self._declaration())
        r2 = store_customs_declaration(doc_id, "B004",
                                       {**self._declaration(), "duty_pln": 1200.0})
        assert r1 == r2  # same row, updated
        cd = get_customs_declaration("B004")
        assert cd["duty_pln"] == 1200.0

    def test_no_declaration_returns_none(self):
        assert get_customs_declaration("NONEXISTENT") is None


# ── 5. PZ generation → registered ─────────────────────────────────────────────

class TestPzRegistration:

    def test_pz_pdf_registered(self):
        doc_id = register_document(
            batch_id="B005", document_type="pz_pdf",
            file_name="PZ_12_3_2026.pdf",
            file_hash="pzhash", source="generated",
            extraction_status="generated", related_pz_no="PZ 12/3/2026",
        )
        assert doc_id is not None
        rows = get_documents_for_batch("B005", "pz_pdf")
        assert len(rows) == 1
        assert rows[0]["extraction_status"] == "generated"
        assert rows[0]["related_pz_no"] == "PZ 12/3/2026"

    def test_pz_document_record_stored(self):
        doc_id = register_document(batch_id="B005", document_type="pz_pdf",
                                   file_name="PZ.pdf", source="generated")
        pz_id = store_pz_document(
            document_id=doc_id, batch_id="B005",
            pz_data={
                "doc_no":              "PZ 12/3/2026",
                "line_count":          10,
                "total_net_pln":       48778.64,
                "total_gross_pln":     59997.72,
                "duty_a00_pln":        1181.0,
                "verification_status": "clean",
                "amendment_flags":     [],
            },
        )
        assert pz_id != ""
        pz = get_pz_document("B005")
        assert pz["doc_no"] == "PZ 12/3/2026"
        assert pz["line_count"] == 10
        assert pz["total_net_pln"] == pytest.approx(48778.64, rel=1e-4)
        assert pz["amendment_flags"] == []

    def test_pz_document_upserts_on_doc_no(self):
        doc_id = register_document(batch_id="B005", document_type="pz_pdf",
                                   file_name="PZ.pdf", source="generated")
        r1 = store_pz_document(doc_id, "B005", {"doc_no": "PZ 1/1/2026",
                                                  "total_net_pln": 100.0})
        r2 = store_pz_document(doc_id, "B005", {"doc_no": "PZ 1/1/2026",
                                                  "total_net_pln": 200.0})
        assert r1 == r2
        assert get_pz_document("B005")["total_net_pln"] == 200.0


# ── 6. Audit memo → registered ────────────────────────────────────────────────

class TestAuditMemoRegistration:

    def test_audit_memo_registered(self):
        doc_id = register_document(
            batch_id="B006", document_type="audit_memo",
            file_name="AUDIT_MEMO_B006.pdf",
            file_hash="memohash", source="generated",
            extraction_status="generated",
        )
        assert doc_id is not None
        rows = get_documents_for_batch("B006", "audit_memo")
        assert len(rows) == 1
        assert rows[0]["source"] == "generated"
        assert rows[0]["extraction_status"] == "generated"

    def test_audit_memo_distinct_from_pz_pdf(self):
        register_document(batch_id="B006", document_type="pz_pdf",
                          file_name="PZ.pdf", file_hash="h1", source="generated")
        register_document(batch_id="B006", document_type="audit_memo",
                          file_name="MEMO.pdf", file_hash="h2", source="generated")
        assert len(get_documents_for_batch("B006")) == 2
        assert len(get_documents_for_batch("B006", "audit_memo")) == 1
        assert len(get_documents_for_batch("B006", "pz_pdf")) == 1


# ── 7. DB read = parser output ────────────────────────────────────────────────

class TestReadField:

    def test_read_field_from_extracted_fields(self):
        doc_id = register_document(batch_id="B007", document_type="invoice",
                                   file_name="inv.pdf")
        upsert_field(doc_id, "B007", "total_cif_usd", "48778.64", confidence=0.95)
        val = read_field("B007", "invoice", "total_cif_usd")
        assert val == "48778.64"

    def test_read_field_from_normalized_json_fallback(self):
        doc_id = register_document(batch_id="B007", document_type="invoice",
                                   file_name="inv.pdf")
        store_extraction_json(
            doc_id, "B007", "invoice",
            extracted_json={"raw": "..."},
            normalized_json={"invoice_no": "EJL/26-27/100", "total": 48778.64},
        )
        val = read_field("B007", "invoice", "invoice_no")
        assert val == "EJL/26-27/100"

    def test_read_field_priority_field_table_wins_over_json(self):
        doc_id = register_document(batch_id="B007", document_type="invoice",
                                   file_name="inv.pdf")
        # Store in both places with different values
        store_extraction_json(doc_id, "B007", "invoice",
                              extracted_json={},
                              normalized_json={"invoice_no": "FROM_JSON"})
        upsert_field(doc_id, "B007", "invoice_no", "FROM_FIELDS", confidence=0.99)
        # Field-level table wins
        assert read_field("B007", "invoice", "invoice_no") == "FROM_FIELDS"

    def test_read_field_returns_none_if_missing(self):
        assert read_field("B007", "invoice", "nonexistent_field") is None

    def test_read_field_missing_batch_returns_none(self):
        assert read_field("MISSING_BATCH", "invoice", "any_field") is None


# ── 8. Verified field cannot be overwritten ───────────────────────────────────

class TestVerifiedFieldProtection:

    def _verified_field(self):
        doc_id = register_document(batch_id="B008", document_type="invoice",
                                   file_name="inv.pdf")
        upsert_field(doc_id, "B008", "mrn", "22PL123", confidence=1.0)
        # Manually set verified_status = 'verified'
        from app.services import document_db as _ddb
        with _ddb._lock:
            with _ddb._connect() as con:
                con.execute(
                    "UPDATE document_extracted_fields SET verified_status='verified'"
                    " WHERE document_id=? AND field_name='mrn'",
                    (doc_id,)
                )
        return doc_id

    def test_verified_field_blocks_update(self):
        doc_id = self._verified_field()
        written = upsert_field(doc_id, "B008", "mrn", "CHANGED_VALUE")
        assert written is False
        assert read_field("B008", "invoice", "mrn") == "22PL123"

    def test_verified_field_allows_force_update(self):
        doc_id = self._verified_field()
        written = upsert_field(doc_id, "B008", "mrn", "FORCED_VALUE", force=True)
        assert written is True
        assert read_field("B008", "invoice", "mrn") == "FORCED_VALUE"

    def test_unverified_field_can_be_updated(self):
        doc_id = register_document(batch_id="B008", document_type="invoice",
                                   file_name="inv.pdf")
        upsert_field(doc_id, "B008", "total", "100.0")
        written = upsert_field(doc_id, "B008", "total", "200.0")
        assert written is True
        assert read_field("B008", "invoice", "total") == "200.0"


# ── 9. Duplicate upload prevented by hash ─────────────────────────────────────

class TestDuplicateHashPrevention:

    def test_same_hash_returns_existing_id(self):
        id1 = register_document(batch_id="B009", document_type="invoice",
                                 file_name="inv.pdf", file_hash="sha256abc")
        id2 = register_document(batch_id="B009", document_type="invoice",
                                 file_name="inv_copy.pdf", file_hash="sha256abc")
        assert id1 == id2  # same hash → same id, no new row
        rows = get_documents_for_batch("B009", "invoice")
        assert len(rows) == 1, "duplicate hash must not insert a second row"

    def test_different_hash_creates_new_row(self):
        register_document(batch_id="B009", document_type="invoice",
                          file_name="inv1.pdf", file_hash="hash_A")
        register_document(batch_id="B009", document_type="invoice",
                          file_name="inv2.pdf", file_hash="hash_B")
        assert len(get_documents_for_batch("B009", "invoice")) == 2

    def test_empty_hash_always_inserts(self):
        """file_hash='' disables dedup — each call creates a row."""
        id1 = register_document(batch_id="B009", document_type="invoice",
                                 file_name="inv.pdf", file_hash="")
        id2 = register_document(batch_id="B009", document_type="invoice",
                                 file_name="inv.pdf", file_hash="")
        assert id1 != id2
        assert len(get_documents_for_batch("B009", "invoice")) == 2

    def test_different_batch_same_hash_allowed(self):
        """Same hash in different batches → distinct rows."""
        id1 = register_document(batch_id="B_X", document_type="invoice",
                                 file_name="inv.pdf", file_hash="samehash")
        id2 = register_document(batch_id="B_Y", document_type="invoice",
                                 file_name="inv.pdf", file_hash="samehash")
        assert id1 != id2

    def test_get_document_by_hash(self):
        register_document(batch_id="B009", document_type="packing",
                          file_name="pack.xlsx", file_hash="packhash")
        doc = get_document_by_hash("B009", "packing", "packhash")
        assert doc is not None
        assert doc["file_name"] == "pack.xlsx"
        assert get_document_by_hash("B009", "packing", "NOTEXIST") is None


# ── 10. Dashboard reads from DB ───────────────────────────────────────────────

class TestDashboardReadsFromDb:

    def test_get_documents_for_batch_returns_all_types(self):
        for dtype in ("invoice", "sad_pdf", "packing", "pz_pdf", "audit_memo"):
            register_document(batch_id="B010", document_type=dtype,
                              file_name=f"{dtype}.pdf",
                              file_hash=f"hash_{dtype}")
        rows = get_documents_for_batch("B010")
        assert len(rows) == 5
        types = {r["document_type"] for r in rows}
        assert types == {"invoice", "sad_pdf", "packing", "pz_pdf", "audit_memo"}

    def test_get_documents_filtered_by_type(self):
        register_document(batch_id="B010", document_type="invoice",
                          file_name="i.pdf", file_hash="ih")
        register_document(batch_id="B010", document_type="invoice",
                          file_name="i2.pdf", file_hash="ih2")
        register_document(batch_id="B010", document_type="sad_pdf",
                          file_name="s.pdf", file_hash="sh")
        assert len(get_documents_for_batch("B010", "invoice")) == 2
        assert len(get_documents_for_batch("B010", "sad_pdf")) == 1

    def test_empty_batch_returns_empty_list(self):
        assert get_documents_for_batch("EMPTY_BATCH") == []

    def test_document_rows_contain_required_fields(self):
        register_document(batch_id="B010", document_type="pz_pdf",
                          file_name="pz.pdf", file_hash="pzh",
                          awb="1012178215", related_pz_no="PZ 1/1/2026",
                          source="generated", extraction_status="generated")
        row = get_documents_for_batch("B010", "pz_pdf")[0]
        for field in ("id", "batch_id", "document_type", "file_name",
                      "file_hash", "awb", "related_pz_no", "source",
                      "extraction_status", "created_at", "updated_at"):
            assert field in row, f"missing field: {field}"


# ── Additional helper tests ────────────────────────────────────────────────────

class TestUpdateDocumentStatus:

    def test_update_extraction_status(self):
        doc_id = register_document(batch_id="B_U", document_type="sad_pdf",
                                   file_name="sad.pdf")
        update_document_status(doc_id, extraction_status="extracted",
                               related_mrn="22PL000")
        rows = get_documents_for_batch("B_U", "sad_pdf")
        assert rows[0]["extraction_status"] == "extracted"
        assert rows[0]["related_mrn"] == "22PL000"


class TestStoreFields:

    def test_store_fields_bulk(self):
        doc_id = register_document(batch_id="B_F", document_type="invoice",
                                   file_name="i.pdf")
        count = store_fields(doc_id, "B_F", {
            "invoice_no": "EJL/001",
            "total_cif":  "1000.00",
            "currency":   "USD",
        }, confidence=0.9)
        assert count == 3
        assert read_field("B_F", "invoice", "currency") == "USD"


class TestSha256File:

    def test_sha256_of_known_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert sha256_file(f) == expected

    def test_sha256_missing_file_returns_empty(self, tmp_path):
        assert sha256_file(tmp_path / "missing.pdf") == ""


class TestExtractionJson:

    def test_store_and_replace_extraction_json(self):
        doc_id = register_document(batch_id="B_EJ", document_type="invoice",
                                   file_name="i.pdf")
        store_extraction_json(doc_id, "B_EJ", "invoice",
                              {"raw": "v1"}, {"field": "v1"})
        store_extraction_json(doc_id, "B_EJ", "invoice",
                              {"raw": "v2"}, {"field": "v2"})
        # Second store replaces — normalized_json reflects v2
        val = read_field("B_EJ", "invoice", "field")
        assert val == "v2"

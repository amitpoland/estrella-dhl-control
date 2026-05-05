"""
test_packing_integration.py — End-to-end integration test for the packing DB flow.

Covers:
  1. PZ processor output (fake pz_rows.json) → extractor → DB → GET combined
     verifies: product_code, design_no, bag_id all present in combined response.
  2. Unmatched row survives pipeline with requires_manual_review=True.
  3. Re-upload with force_reextract=True replaces rows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_pz_rows(output_dir: Path, rows: list) -> None:
    (output_dir / "pz_rows.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )


def _make_xlsx(path: Path, header: list, data_rows: list) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in data_rows:
        ws.append(row)
    wb.save(str(path))


def _init_db(tmp_path: Path) -> Path:
    from app.services.packing_db import init_packing_db
    db_path = tmp_path / "packing.db"
    init_packing_db(db_path)
    return db_path


# ── Integration tests ─────────────────────────────────────────────────────────

class TestPackingIntegration:
    """
    Full flow: fake pz_rows.json → XLSX upload → DB → GET combined response.
    No HTTP server required — calls service functions directly.
    """

    def test_combined_response_has_product_code_design_no_bag_id(self, tmp_path):
        """
        Given:
          - pz_rows.json with 2 lines for EJL/26-27/100
          - XLSX packing list with matching invoice_no + item_type + qty
        When:
          - process_packing_upload() runs
          - result stored in DB
          - get_packing_lines_for_batch() called
        Then:
          - product_code == "EJL/26-27/100-1" and "EJL/26-27/100-2"
          - design_no values are stored
          - bag_id values are stored
        """
        _init_db(tmp_path)

        # Step 1 — fake pz_rows.json (simulates PZ processor output)
        _write_pz_rows(tmp_path, [
            {
                "invoice_no": "EJL/26-27/100",
                "item_type": "RING",
                "quantity": 3,
                "unit": "PCS",
                "unit_netto_pln": 200.0,
                "line_netto_pln": 600.0,
                "description_en": "Gold 18K Ring",
            },
            {
                "invoice_no": "EJL/26-27/100",
                "item_type": "BRACELET",
                "quantity": 1,
                "unit": "PCS",
                "unit_netto_pln": 500.0,
                "line_netto_pln": 500.0,
                "description_en": "Gold 18K Bracelet",
            },
        ])

        # Step 2 — XLSX packing list
        xlsx_path = tmp_path / "packing.xlsx"
        _make_xlsx(
            xlsx_path,
            header=["invoice_no", "item_type", "quantity",
                    "design_no", "batch_no", "bag_id", "metal", "karat"],
            data_rows=[
                ["EJL/26-27/100", "RING",     3, "D-RING-001", "LOT-A", "BAG-01", "GOLD", "18K"],
                ["EJL/26-27/100", "BRACELET", 1, "D-BRAC-002", "LOT-A", "BAG-02", "GOLD", "18K"],
            ],
        )

        # Step 3 — run extraction + matching pipeline
        from app.services.invoice_packing_extractor import process_packing_upload
        result = process_packing_upload(
            batch_id="INTEG_BATCH",
            batch_output_dir=tmp_path,
            packing_file_path=xlsx_path,
        )

        assert result["total_rows"] == 2
        assert result["matched_count"] == 2
        assert result["unmatched_count"] == 0

        # Step 4 — store in DB
        from app.services import packing_db as pdb
        doc_id = pdb.upsert_packing_document(**result["document"])
        line_records = [
            {
                "packing_document_id":  doc_id,
                "batch_id":             "INTEG_BATCH",
                "invoice_no":           r.get("invoice_no", ""),
                "invoice_line_position":r.get("invoice_line_position"),
                "product_code":         r.get("product_code"),
                "design_no":            str(r.get("design_no", "") or ""),
                "batch_no":             str(r.get("batch_no", "") or ""),
                "bag_id":               str(r.get("bag_id", "") or ""),
                "tray_id":              str(r.get("tray_id", "") or ""),
                "item_type":            str(r.get("item_type", "") or ""),
                "uom":                  str(r.get("uom", "") or ""),
                "quantity":             float(r.get("quantity", 0) or 0),
                "gross_weight":         float(r.get("gross_weight", 0) or 0),
                "net_weight":           float(r.get("net_weight", 0) or 0),
                "metal":                str(r.get("metal", "") or ""),
                "karat":                str(r.get("karat", "") or ""),
                "stone_type":           str(r.get("stone_type", "") or ""),
                "remarks":              str(r.get("remarks", "") or ""),
                "extracted_confidence": float(r.get("extracted_confidence", 0) or 0),
                "requires_manual_review": bool(r.get("requires_manual_review", False)),
            }
            for r in result["packing_rows"]
        ]
        inserted = pdb.upsert_packing_lines(line_records)
        assert inserted == 2

        # Step 5 — GET combined (simulate what the endpoint returns)
        from app.services.invoice_packing_extractor import load_invoice_lines
        invoice_lines = load_invoice_lines(tmp_path)
        packing_lines = pdb.get_packing_lines_for_batch("INTEG_BATCH")
        documents     = pdb.get_packing_documents_for_batch("INTEG_BATCH")

        combined = {
            "batch_id":      "INTEG_BATCH",
            "invoice_lines": invoice_lines,
            "packing_lines": packing_lines,
            "documents":     documents,
        }

        # ── Assertions on combined response ──────────────────────────────────
        assert len(combined["invoice_lines"]) == 2
        assert len(combined["packing_lines"]) == 2
        assert len(combined["documents"])     == 1

        # product_code sequence
        packing_codes = sorted(l["product_code"] for l in combined["packing_lines"])
        assert packing_codes == ["EJL/26-27/100-1", "EJL/26-27/100-2"]

        # design_no stored
        design_nos = sorted(l["design_no"] for l in combined["packing_lines"])
        assert design_nos == ["D-BRAC-002", "D-RING-001"]

        # bag_id stored
        bag_ids = sorted(l["bag_id"] for l in combined["packing_lines"])
        assert bag_ids == ["BAG-01", "BAG-02"]

        # invoice_lines carry product_code too
        inv_codes = sorted(l["product_code"] for l in combined["invoice_lines"])
        assert inv_codes == ["EJL/26-27/100-1", "EJL/26-27/100-2"]

    def test_unmatched_row_survives_in_combined(self, tmp_path):
        """
        A packing row that cannot match any invoice line must appear in DB
        with product_code=None and requires_manual_review=1.
        """
        _init_db(tmp_path)

        _write_pz_rows(tmp_path, [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING",
             "quantity": 2, "unit": "PCS",
             "unit_netto_pln": 100.0, "line_netto_pln": 200.0,
             "description_en": "Ring"},
        ])

        xlsx_path = tmp_path / "packing.xlsx"
        _make_xlsx(
            xlsx_path,
            header=["invoice_no", "item_type", "quantity", "design_no", "bag_id"],
            data_rows=[
                ["EJL/26-27/999", "NECKLACE", 5, "D-UNKNOWN", "BAG-X"],  # no match
            ],
        )

        from app.services.invoice_packing_extractor import process_packing_upload
        from app.services import packing_db as pdb

        result = process_packing_upload(
            batch_id="INTEG_UNMATCHED",
            batch_output_dir=tmp_path,
            packing_file_path=xlsx_path,
        )
        assert result["unmatched_count"] == 1

        doc_id = pdb.upsert_packing_document(**result["document"])
        line_records = [
            {**r, "packing_document_id": doc_id, "batch_id": "INTEG_UNMATCHED",
             "design_no":   str(r.get("design_no",  "") or ""),
             "batch_no":    str(r.get("batch_no",   "") or ""),
             "bag_id":      str(r.get("bag_id",     "") or ""),
             "tray_id":     str(r.get("tray_id",    "") or ""),
             "item_type":   str(r.get("item_type",  "") or ""),
             "uom":         str(r.get("uom",        "") or ""),
             "quantity":    float(r.get("quantity",  0) or 0),
             "gross_weight":float(r.get("gross_weight", 0) or 0),
             "net_weight":  float(r.get("net_weight",   0) or 0),
             "metal":       str(r.get("metal",      "") or ""),
             "karat":       str(r.get("karat",      "") or ""),
             "stone_type":  str(r.get("stone_type", "") or ""),
             "remarks":     str(r.get("remarks",    "") or ""),
             "extracted_confidence": float(r.get("extracted_confidence", 0) or 0),
             "requires_manual_review": bool(r.get("requires_manual_review", False)),
            }
            for r in result["packing_rows"]
        ]
        pdb.upsert_packing_lines(line_records)

        lines = pdb.get_packing_lines_for_batch("INTEG_UNMATCHED")
        assert len(lines) == 1
        assert lines[0]["product_code"] is None
        assert lines[0]["requires_manual_review"] == 1
        assert lines[0]["bag_id"] == "BAG-X"

    def test_force_reextract_replaces_rows_in_combined(self, tmp_path):
        """
        Re-upload with force_reextract=True must update existing rows.
        The combined GET must reflect new values.
        """
        _init_db(tmp_path)

        _write_pz_rows(tmp_path, [
            {"invoice_no": "EJL/26-27/100", "item_type": "RING",
             "quantity": 2, "unit": "PCS",
             "unit_netto_pln": 100.0, "line_netto_pln": 200.0,
             "description_en": "Ring"},
        ])

        from app.services.invoice_packing_extractor import process_packing_upload
        from app.services import packing_db as pdb

        def _upload(design: str, bag: str, force: bool = False) -> None:
            xlsx_path = tmp_path / "packing.xlsx"
            _make_xlsx(
                xlsx_path,
                header=["invoice_no", "item_type", "quantity", "design_no", "bag_id"],
                data_rows=[["EJL/26-27/100", "RING", 2, design, bag]],
            )
            result = process_packing_upload(
                batch_id="INTEG_FORCE",
                batch_output_dir=tmp_path,
                packing_file_path=xlsx_path,
                force_reextract=force,
            )
            doc_id = pdb.upsert_packing_document(**result["document"])
            line_records = [
                {**r, "packing_document_id": doc_id, "batch_id": "INTEG_FORCE",
                 "design_no":   str(r.get("design_no",  "") or ""),
                 "batch_no":    str(r.get("batch_no",   "") or ""),
                 "bag_id":      str(r.get("bag_id",     "") or ""),
                 "tray_id":     str(r.get("tray_id",    "") or ""),
                 "item_type":   str(r.get("item_type",  "") or ""),
                 "uom":         str(r.get("uom",        "") or ""),
                 "quantity":    float(r.get("quantity",  0) or 0),
                 "gross_weight":float(r.get("gross_weight", 0) or 0),
                 "net_weight":  float(r.get("net_weight",   0) or 0),
                 "metal":       str(r.get("metal",      "") or ""),
                 "karat":       str(r.get("karat",      "") or ""),
                 "stone_type":  str(r.get("stone_type", "") or ""),
                 "remarks":     str(r.get("remarks",    "") or ""),
                 "extracted_confidence": float(r.get("extracted_confidence", 0) or 0),
                 "requires_manual_review": bool(r.get("requires_manual_review", False)),
                }
                for r in result["packing_rows"]
            ]
            pdb.upsert_packing_lines(line_records, force_reextract=force)

        # First upload
        _upload("D-ORIGINAL", "BAG-ORIG", force=False)
        lines = pdb.get_packing_lines_for_batch("INTEG_FORCE")
        assert lines[0]["design_no"] == "D-ORIGINAL"

        # Second upload without force — must NOT change
        _upload("D-CHANGED", "BAG-ORIG", force=False)
        lines = pdb.get_packing_lines_for_batch("INTEG_FORCE")
        assert lines[0]["design_no"] == "D-ORIGINAL"

        # Third upload with force — must update
        _upload("D-FORCED", "BAG-ORIG", force=True)
        lines = pdb.get_packing_lines_for_batch("INTEG_FORCE")
        assert lines[0]["design_no"] == "D-FORCED"

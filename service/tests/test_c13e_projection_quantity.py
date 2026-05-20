"""tests/test_c13e_projection_quantity.py — C13E

Projection-by-Quantity correction.

Contract: derive_purchase_transit_projection must emit SUM(quantity) synthetic
rows per batch, not COUNT(*) packing lines.

Tests in this file:
  1.  qty=5 emits 5 synthetic rows
  2.  expanded scan_codes are unique (scan#1 … scan#5)
  3.  missing quantity defaults to 1
  4.  invalid quantity defaults to 1
  5.  quantity<=0 defaults to 1
  6.  duplicate original scan_code handling safe
  7.  real inventory rows still override projection
  8.  terminal statuses still suppress projection
  9.  Lapis fixture total: 46 not 30
  10. Lapis fixture invoice 177 subtotal: 38 not 22
  11. PRS handling unchanged: logical units preserved exactly
  12. projector body still contains zero DB write tokens
"""
from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.services import inventory_state_engine as ise
from app.services import inventory_batch_state as ibs
from app.services import packing_db


# ── Helpers ───────────────────────────────────────────────────────────────────

_TRANSIT_AUDIT = {"clearance_status": "dsk_generated",
                  "tracking": {"last_update": "2026-05-20T10:00:00Z"}}


def _proj(lines, audit=None):
    return ise.derive_purchase_transit_projection(
        "C13E-TEST", audit or _TRANSIT_AUDIT, lines
    )


def _line(scan, qty, product_code="P001", design_no="D001", invoice_no="INV-177"):
    return {
        "scan_code":    scan,
        "product_code": product_code,
        "design_no":    design_no,
        "quantity":     qty,
        "invoice_no":   invoice_no,
    }


# ── 1. qty=5 emits 5 synthetic rows ─────────────────────────────────────────

def test_quantity_five_emits_five_rows():
    rows = _proj([_line("SC-001", 5)])
    assert len(rows) == 5
    for r in rows:
        assert r["state"]     == ise.PURCHASE_TRANSIT
        assert r["synthetic"] is True
        assert r["source"]    == "audit.tracking"


# ── 2. expanded scan_codes are unique (SC-001#1 … SC-001#5) ─────────────────

def test_expanded_scan_codes_are_unique_and_suffixed():
    rows = _proj([_line("SC-001", 5)])
    scans = [r["scan_code"] for r in rows]
    assert scans == ["SC-001#1", "SC-001#2", "SC-001#3", "SC-001#4", "SC-001#5"]
    assert len(set(scans)) == 5


# ── 3. qty=1 keeps original scan_code (no suffix) ───────────────────────────

def test_quantity_one_keeps_original_scan_code():
    rows = _proj([_line("SC-SOLO", 1)])
    assert len(rows) == 1
    assert rows[0]["scan_code"] == "SC-SOLO"


# ── 4. missing quantity defaults to 1 ───────────────────────────────────────

def test_missing_quantity_defaults_to_one():
    line = {"scan_code": "SC-NOQTY", "product_code": "P001", "design_no": "D001"}
    rows = _proj([line])
    assert len(rows) == 1
    assert rows[0]["scan_code"] == "SC-NOQTY"


# ── 5. invalid quantity defaults to 1 ───────────────────────────────────────

def test_invalid_quantity_defaults_to_one():
    for bad_qty in ("not-a-number", "", None, "abc", [], {}):
        line = {"scan_code": "SC-BAD", "product_code": "P001",
                "design_no": "D001", "quantity": bad_qty}
        rows = _proj([line])
        assert len(rows) == 1, f"bad qty {bad_qty!r} should yield 1 row, got {len(rows)}"
        assert rows[0]["scan_code"] == "SC-BAD"


# ── 6. quantity<=0 defaults to 1 ────────────────────────────────────────────

def test_quantity_zero_or_negative_defaults_to_one():
    for bad_qty in (0, -1, -5, 0.0, "-3"):
        line = {"scan_code": "SC-ZERO", "product_code": "P001",
                "design_no": "D001", "quantity": bad_qty}
        rows = _proj([line])
        assert len(rows) == 1, f"qty {bad_qty!r} should yield 1 row, got {len(rows)}"


# ── 7. duplicate original scan_code handling safe ───────────────────────────

def test_duplicate_base_scan_codes_not_double_expanded():
    """Two packing lines with the same scan_code: second is skipped entirely.
    The qty-expansion of the first still produces the correct count."""
    lines = [
        _line("SC-DUP", 3),
        _line("SC-DUP", 3),   # duplicate base — must be skipped
        _line("SC-UNQ", 2),
    ]
    rows = _proj(lines)
    # SC-DUP: 3 rows; SC-UNQ: 2 rows; duplicate SC-DUP skipped → total 5
    assert len(rows) == 5
    scans = [r["scan_code"] for r in rows]
    assert "SC-DUP#1" in scans
    assert "SC-DUP#2" in scans
    assert "SC-DUP#3" in scans
    assert "SC-UNQ#1" in scans
    assert "SC-UNQ#2" in scans
    # No fourth SC-DUP row
    assert scans.count("SC-DUP#1") == 1


# ── 8. real inventory rows still override projection ────────────────────────

def test_real_inventory_rows_override_projection(tmp_path, monkeypatch):
    """If any real inventory_state row exists, synthetic projection must NOT
    activate — real data always wins."""
    storage = tmp_path / "storage"
    (storage / "outputs").mkdir(parents=True)
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(storage / "warehouse.db")
    batch = "C13E-REAL-WINS"
    pdb_path = storage / "packing.db"
    packing_db.init_packing_db(pdb_path)
    packing_db._db_path = pdb_path  # type: ignore[attr-defined]
    doc_id = "doc-c13e"
    packing_db.upsert_packing_document(
        document_id=doc_id, batch_id=batch, invoice_no="INV-W",
        source_file_path="/tmp/test.xlsx", source_file_hash="x" * 64,
        parser_name="test", parser_version="1.0",
        extraction_status="complete", parser_diagnostic={},
    )
    packing_db.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": batch,
        "invoice_no": "INV-W", "invoice_line_position": 1, "pack_sr": 1.0,
        "scan_code": "SC-REAL", "product_code": "P001", "design_no": "D001",
        "quantity": 5, "extracted_confidence": 1.0,
    }])
    (storage / "outputs" / batch).mkdir(parents=True)
    (storage / "outputs" / batch / "audit.json").write_text(
        json.dumps({"clearance_status": "dsk_generated"}), encoding="utf-8"
    )
    # Insert one real inventory row → projection must NOT activate.
    ise.count_by_state(batch_id=batch)
    with ise._connect() as con:
        con.execute(
            "INSERT INTO inventory_state "
            "(id, scan_code, product_code, design_no, batch_id, state, "
            "updated_at, updated_by, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("id-c13e", "SC-REAL", "P001", "D001", batch,
             ise.WAREHOUSE_STOCK, "2026-05-20T10:00:00Z", "test", ""),
        )
    out = ibs.get_batch_state(batch)
    assert out["synthetic"] is False
    assert out["source"] == "inventory_state"
    assert out["counts"][ise.WAREHOUSE_STOCK] == 1
    assert out["counts"][ise.PURCHASE_TRANSIT] == 0


# ── 9. terminal statuses still suppress projection ──────────────────────────

def test_terminal_statuses_suppress_projection():
    lines = [_line("SC-T", 5)]
    for status in ("closed", "pz_generated", "delivered_and_received",
                   "archived", "cancelled"):
        rows = ise.derive_purchase_transit_projection(
            "C13E-TERM", {"clearance_status": status}, lines,
        )
        assert rows == [], f"terminal {status!r} produced {len(rows)} rows"


# ── 10 + 11. Lapis fixture total=46; invoice 177 subtotal=38 ─────────────────

def _build_lapis_packing_lines() -> List[Dict[str, Any]]:
    """Minimal fixture that reproduces the Lapis batch arithmetic.

    Business truth:
      packing_lines COUNT(*) = 30
      packing_lines SUM(quantity) = 46
      invoice 177 lines: 22 rows, SUM(quantity) = 38
        → 16 lines with qty=2, 6 lines with qty=1
      other lines: 8 rows, all qty=1 → SUM = 8
      total: 30 rows, 46 units

    PRS note: PRS earring pairs already normalised in quantity by parser.
    No multiplication factor applied here — qty IS the logical unit count.
    """
    lines = []
    # Invoice 177: 16 lines with qty=2, 6 with qty=1 → 22 lines, 38 units
    for i in range(1, 17):
        lines.append({
            "scan_code":    f"EJL/LAPIS/177-QTY2-{i:02d}|sr{i}|D-{i:02d}",
            "product_code": f"EJL/LAPIS/177-QTY2-{i:02d}",
            "design_no":    f"D-{i:02d}",
            "quantity":     2,
            "invoice_no":   "INV-177",
        })
    for i in range(17, 23):
        lines.append({
            "scan_code":    f"EJL/LAPIS/177-QTY1-{i:02d}|sr{i}|D-{i:02d}",
            "product_code": f"EJL/LAPIS/177-QTY1-{i:02d}",
            "design_no":    f"D-{i:02d}",
            "quantity":     1,
            "invoice_no":   "INV-177",
        })
    # Other invoices: 8 lines, qty=1 each → 8 units
    for i in range(1, 9):
        lines.append({
            "scan_code":    f"EJL/LAPIS/178-{i:02d}|sr{100+i}|D-X{i:02d}",
            "product_code": f"EJL/LAPIS/178-{i:02d}",
            "design_no":    f"D-X{i:02d}",
            "quantity":     1,
            "invoice_no":   "INV-178",
        })
    assert len(lines) == 30, f"fixture has {len(lines)} lines, expected 30"
    assert sum(ln["quantity"] for ln in lines) == 46
    return lines


def test_lapis_fixture_total_is_46():
    """C13E: projection count must equal SUM(packing_lines.quantity) = 46."""
    lines = _build_lapis_packing_lines()
    rows = ise.derive_purchase_transit_projection("C13E-LAPIS", _TRANSIT_AUDIT, lines)
    assert len(rows) == 46, f"expected 46 synthetic rows, got {len(rows)}"
    assert all(r["state"] == ise.PURCHASE_TRANSIT for r in rows)
    assert all(r["synthetic"] is True for r in rows)


def test_lapis_invoice_177_subtotal_is_38():
    """C13E: invoice 177 portion of projection = 38 units."""
    lines = _build_lapis_packing_lines()
    inv177_lines = [ln for ln in lines if ln.get("invoice_no") == "INV-177"]
    assert len(inv177_lines) == 22, "fixture must have 22 INV-177 lines"
    rows177 = ise.derive_purchase_transit_projection(
        "C13E-LAPIS-177", _TRANSIT_AUDIT, inv177_lines
    )
    assert len(rows177) == 38, (
        f"invoice 177 subtotal must be 38, got {len(rows177)}"
    )


# ── 12. PRS handling unchanged ───────────────────────────────────────────────

def test_prs_earring_quantity_preserved_exactly():
    """PRS earring pairs: quantity is already normalised by the parser.
    The projector must not multiply by 2 or apply any PRS-specific factor.
    If a PRS line has qty=2, it represents 2 logical units — emit 2 rows."""
    prs_line = {
        "scan_code":    "EJL/PRS/01-EARRING|sr99|D-PRS",
        "product_code": "EJL/PRS/01-EARRING",
        "design_no":    "D-PRS",
        "quantity":     2,  # 2 pairs already normalised
        "item_type":    "PRS",
    }
    rows = ise.derive_purchase_transit_projection(
        "C13E-PRS", _TRANSIT_AUDIT, [prs_line]
    )
    # Must emit exactly 2 rows — not 1 (old COUNT bug) and not 4 (double PRS)
    assert len(rows) == 2, f"PRS qty=2 must emit 2 rows, got {len(rows)}"
    assert rows[0]["scan_code"] == "EJL/PRS/01-EARRING|sr99|D-PRS#1"
    assert rows[1]["scan_code"] == "EJL/PRS/01-EARRING|sr99|D-PRS#2"


def test_prs_earring_qty_one_keeps_original_scan_code():
    """PRS line with qty=1 (single pair) must keep original scan_code."""
    prs_line = {
        "scan_code":    "EJL/PRS/SOLO|sr77|D-SOLO",
        "product_code": "EJL/PRS/SOLO",
        "design_no":    "D-SOLO",
        "quantity":     1,
        "item_type":    "PRS",
    }
    rows = ise.derive_purchase_transit_projection(
        "C13E-PRS-1", _TRANSIT_AUDIT, [prs_line]
    )
    assert len(rows) == 1
    assert rows[0]["scan_code"] == "EJL/PRS/SOLO|sr77|D-SOLO"


# ── 13. Projector body still contains zero DB write tokens ───────────────────

def test_projector_source_contains_no_write_keywords():
    """C13E must not introduce any write path into the read-only projector."""
    src = inspect.getsource(ise.derive_purchase_transit_projection)
    for forbidden in ("INSERT", "UPDATE INVENTORY", "DELETE FROM",
                      "transition(", "upsert_"):
        assert forbidden not in src, (
            f"derive_purchase_transit_projection contains forbidden token "
            f"{forbidden!r} — projection MUST remain read-only"
        )


# ── 14. Float quantity strings handled (packing_db stores REAL) ──────────────

def test_float_quantity_string_coerced_correctly():
    """packing_db stores quantity as REAL; values like 2.0 and '3.0' must
    coerce to the correct integer expansion."""
    lines = [
        _line("SC-FLOAT2", 2.0),
        _line("SC-FLOAT3", "3.0"),
        _line("SC-INT1",   1),
    ]
    rows = ise.derive_purchase_transit_projection("C13E-FLOAT", _TRANSIT_AUDIT, lines)
    assert len(rows) == 6  # 2+3+1
    scans = {r["scan_code"] for r in rows}
    assert "SC-FLOAT2#1" in scans and "SC-FLOAT2#2" in scans
    assert "SC-FLOAT3#1" in scans and "SC-FLOAT3#3" in scans
    assert "SC-INT1" in scans  # qty=1 keeps original

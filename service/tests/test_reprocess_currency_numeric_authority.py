"""
Reprocess numeric authority — currency-formatted value normalization.

Production incident (AWB 1201561616, deployed a93cec8b): the V2 #948 re-extract
issued one canonical /reprocess; the #947 parser correctly found the header
(header_row=2) and extracted the real EJL rows, but the reprocess PERSIST path
then crashed per file with `could not convert string to float: '$ 993'` — the
EJL Value / Total Value columns render as "$ N" / "$ N,NNN". Prior rows were
preserved (no data loss), but nothing new persisted.

Fix (single canonical boundary, no route-local stripping, no new helper):
  1. `_safe_float` (the ONE canonical packing normalizer) strips currency markers.
  2. The reprocess purchase AND sales persist mappers route unit_price/total_value
     through `_safe_float` instead of raw `float()`.

Document-correct row counts (from row-level inspection of the real 427/428 PDFs):
  Purchase 427 = 1 · Purchase 428 = 4 · Sales 427 = 1 · Sales 428 = 4
  (historical DB 1/0/5/11 was wrong both ways; #947 parser is correct).
Fixtures below mirror the real EJL layout with SANITIZED values.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pdfplumber
import pytest

from app.services import invoice_packing_extractor as ipe
from app.services.invoice_packing_extractor import _safe_float, _extract_packing_pdf

ROUTES_PACKING = Path(__file__).parents[1] / "app" / "api" / "routes_packing.py"


# ── 1. Canonical numeric normalization: currency formats + malformed ──────────
@pytest.mark.parametrize("raw,expected", [
    ("$ 993", 993.0), ("$ 1,554", 1554.0), ("$ 1273", 1273.0), ("$ 538", 538.0),
    ("$ 104", 104.0), ("$ 3,387", 3387.0), ("€ 538", 538.0), ("USD 993", 993.0),
    ("993", 993.0), ("1,234.56", 1234.56), (1273, 1273.0), (2.5, 2.5), ("2.00", 2.0),
])
def test_safe_float_normalises_currency_values(raw, expected):
    assert abs(_safe_float(raw) - expected) < 1e-9


@pytest.mark.parametrize("bad", ["Total", "Grand Total", "ite 1", "", None, "$", "N/A", "  "])
def test_safe_float_malformed_returns_zero_never_raises(bad):
    # Atomic preservation on malformed values: 0.0, never an exception (so a
    # single bad cell can never abort the whole file's persistence).
    assert _safe_float(bad) == 0.0


# ── fake pdfplumber (mirror test_packing_pdf_authority) ───────────────────────
class _FakePage:
    def __init__(self, tables): self._t = tables
    def extract_tables(self): return self._t
    def extract_text(self): return ""


class _FakePDF:
    def __init__(self, pages): self._p = [_FakePage(t) for t in pages]
    @property
    def pages(self): return self._p
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _patch(mp, pages):
    mp.setattr(pdfplumber, "open", lambda *a, **k: _FakePDF(pages))


def _pdf(tmp):
    p = tmp / "pk.pdf"
    p.write_bytes(b"%PDF-1.4 synthetic")
    return p


# Sanitized real EJL PURCHASE 428 layout: title, invoice preamble, header@row-2,
# 4 product rows interleaved with subtotals, grand total. Values in "$ N"/"$ N,NNN".
_PURCH_428 = [[[
    ["SHIPMENT PACKING LIST", "", "", "", "", "", "", "", "", "", "", ""],
    ["Invoice # EJL/26-27/428 Invoice Date 18/07/26", "", "", "", "", "", "", "", "", "", "", ""],
    ["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality", "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size", "Order No"],
    ["1", "PND", "DSN-A", "18KT/W", "Q1", "0.95", "0.00", "1", "$ 993", "$ 993", "18-I", "SO/1"],
    ["", "", "Total PND-18KT", "", "", "0.94", "0.00", "1", "", "$ 993", "", ""],
    ["2", "RNG", "DSN-B", "18KT/W", "Q2", "2.03", "0.00", "1", "$ 632", "$ 632", "L", "SO/2"],
    ["", "", "Total RNG-18KT", "", "", "2.03", "0.00", "1", "", "$ 632", "", ""],
    ["3", "RNG", "DSN-C", "PT950/-", "Q3", "5.96", "0.00", "1", "$ 1,554", "$ 1,554", "N", "SO/3"],
    ["", "", "Total RNG-PT950", "", "", "5.96", "0.00", "1", "", "$ 1,554", "", ""],
    ["4", "EAR", "DSN-D", "09KT/Y", "Q4", "1.01", "0.00", "2", "$ 104", "$ 208", "", "SO/4"],
    ["", "", "Total EAR-09KT", "", "", "1.00", "0.00", "2", "", "$ 208", "", ""],
    ["", "", "Grand Total", "", "", "9.94", "0.00", "5", "", "$ 3,387", "", ""],
]]]

# Sanitized real EJL SALES 427 layout (DiamondGroup-style header): 1 product row.
_SALES_427 = [[[
    ["SHIPMENT PACKING LIST", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["Sanitized Customer GmbH  Invoice # EJL/26-27/427  Dated : 18/07/26", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["Sr", "Ctg", "Client Po", "Design", "Kt", "Col", "Quality", "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"],
    ["1", "RNG", "Order X", "DSN-S1", "14KT", "P", "GH-SI", "0.45", "0.00", "1.00", "$ 538", "$ 538", "52.0"],
    ["", "", "", "Total 14KT Ring", "", "", "", "", "", "1.00", "", "$ 538", ""],
    ["", "", "", "Grand Total", "", "", "", "", "", "1.00", "", "$ 538", ""],
]]]


def test_real_layout_purchase_428_extracts_four_rows_and_normalises_currency(tmp_path, monkeypatch):
    _patch(monkeypatch, _PURCH_428)
    rows = _extract_packing_pdf(_pdf(tmp_path))
    # Document-correct: 4 product rows (NOT 0, NOT subtotals/grand-total/title).
    assert len(rows) == 4
    assert [r["design_no"] for r in rows] == ["DSN-A", "DSN-B", "DSN-C", "DSN-D"]
    # Value column carries "$ N" / "$ N,NNN"; the canonical normalizer resolves it.
    assert rows[0]["unit_price"] == "$ 993"
    assert _safe_float(rows[0]["unit_price"]) == 993.0
    assert _safe_float(rows[2]["unit_price"]) == 1554.0          # currency + comma-thousands
    assert _safe_float(rows[2]["total_value"]) == 1554.0
    # Pieces (Qty) total = 1+1+1+2 = 5.
    assert sum(_safe_float(r["quantity"]) for r in rows) == 5.0


def test_real_layout_sales_427_extracts_one_row_and_normalises_currency(tmp_path, monkeypatch):
    _patch(monkeypatch, _SALES_427)
    rows = _extract_packing_pdf(_pdf(tmp_path))
    assert len(rows) == 1                                        # document-correct (historical DB=5 was wrong)
    assert rows[0]["design_no"] == "DSN-S1"
    assert _safe_float(rows[0]["unit_price"]) == 538.0
    assert _safe_float(rows[0]["quantity"]) == 1.0


def test_purchase_match_path_no_crash_on_currency():
    # The PURCHASE reprocess lane runs match_packing_to_invoice on raw packing rows
    # (via process_packing_upload) BEFORE the persist mapper — this was the real
    # crash site for purchase ("$ 993" → ValueError). It must normalise, not raise.
    from app.services.invoice_packing_extractor import match_packing_to_invoice
    packing = [{
        "invoice_no": "EJL/26-27/428", "item_type": "PND", "design_no": "DSN-A",
        "quantity": "1", "unit_price": "$ 993", "total_value": "$ 993",
        "metal": "18KT", "karat": "18KT",
    }]
    out = match_packing_to_invoice(packing, [])   # no invoice lines → unmatched, must NOT raise
    assert isinstance(out, list) and len(out) == 1


# ── 3. Persistence round-trip + confirmed-row preservation (packing_db) ───────
def _make_line(**kw) -> Dict[str, Any]:
    d = dict(
        packing_document_id="DOC-CUR", batch_id="BATCH-CUR", invoice_no="EJL/26-27/428",
        invoice_line_position=1, product_code="EJL/26-27/428-1", design_no="DSN-A",
        batch_no="", bag_id="", tray_id="", item_type="PND", uom="PCS",
        quantity=1.0, gross_weight=0.95, net_weight=0.0, metal="18KT/W", karat="18KT",
        stone_type="", remarks="", extracted_confidence=1.0, requires_manual_review=True,
        pack_sr=1.0,
    )
    d.update(kw)
    return d


@pytest.fixture()
def packing_db(tmp_path):
    from app.services.packing_db import init_packing_db
    p = tmp_path / "packing.db"
    init_packing_db(p)
    return p


def test_currency_normalised_value_persists_as_float(packing_db):
    from app.services import packing_db as pdb
    # The reprocess mapper feeds _safe_float("$ 993") = 993.0 into persistence.
    line = _make_line(unit_price=_safe_float("$ 993"), total_value=_safe_float("$ 993"))
    assert pdb.upsert_packing_lines([line]) == 1
    rows = pdb.get_packing_lines_for_batch("BATCH-CUR")
    assert len(rows) == 1
    assert rows[0]["unit_price"] == 993.0
    assert rows[0]["total_value"] == 993.0


def test_confirmed_row_product_code_preserved_on_force_reextract(packing_db):
    import sqlite3
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([_make_line(pack_sr=2.0, product_code="ORIG-PC", unit_price=993.0)])
    # Operator confirms the mapping.
    con = sqlite3.connect(str(packing_db))
    con.execute("UPDATE packing_lines SET operator_review_status='confirmed', product_code='OPERATOR-PC'")
    con.commit(); con.close()
    # Force re-extract with a DIFFERENT machine product_code.
    pdb.upsert_packing_lines(
        [_make_line(pack_sr=2.0, product_code="MACHINE-PC", unit_price=1000.0)],
        force_reextract=True,
    )
    rows = pdb.get_packing_lines_for_batch("BATCH-CUR")
    assert len(rows) == 1                                       # updated in place, not duplicated
    assert rows[0]["product_code"] == "OPERATOR-PC"             # confirmed mapping preserved


# ── 4. Boundary pin: reprocess mappers use the canonical authority (parity) ───
def test_no_raw_currency_float_in_reprocess_or_match_chain():
    # Every unit_price/total_value coercion in the packing reprocess + match chain
    # routes through the canonical _safe_float — the raw float() form that crashed
    # on "$ 993" is eliminated in BOTH files (route persist mappers, reprocess-prices
    # preflight, AND match_packing_to_invoice — the purchase-lane crash site reached
    # before the persist mapper). This is form-agnostic across both crash surfaces.
    rp = ROUTES_PACKING.read_text(encoding="utf-8")
    ex = (Path(__file__).parents[1] / "app" / "services" / "invoice_packing_extractor.py").read_text(encoding="utf-8")
    for src in (rp, ex):
        assert 'float(r.get("unit_price", 0) or 0)' not in src
        assert 'float(r.get("total_value", 0) or 0)' not in src
    # Canonical helper used at every site: purchase mapper + sales mapper +
    # reprocess-prices (routes, >=4) and match_packing_to_invoice (extractor, >=1).
    assert rp.count('_safe_float(r.get("unit_price"))') >= 4
    assert ex.count('_safe_float(r.get("unit_price"))') >= 1
    assert "import process_packing_upload, _safe_float" in rp

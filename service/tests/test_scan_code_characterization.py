"""Characterization tests for scan_code computation across three sites.

Step 1 of the scan-code-canonicalize cycle (Option A posture: cycle is
parked; consolidation requires C1–C4 contract decisions). These tests
pin the CURRENT, OBSERVED output of each of the three sites on a
12-row input matrix. They assert what is, not what should be. Sites
1 and 2 are byte-equal today; Site 3 diverges on M08, M09, M10. This
file is the contract until C1–C4 close.
"""
from __future__ import annotations

import pytest

from app.services import packing_db as _pdb
from app.services import warehouse_db as _wdb
from app.api import routes_packing as _rp


# ── Sites 1 and 2 share these expected values verbatim (byte-equal today) ────
# Site 1: app.services.packing_db._compute_scan_code            (packing_db.py:37)
# Site 2: app.services.warehouse_db.scan_code_for_packing_line  (warehouse_db.py:184)
_SITES_1_AND_2_CASES = [
    ("M01", {"product_code": "P1", "bag_id": "B1", "pack_sr": None, "design_no": "D"},  "P1|B1"),
    ("M02", {"product_code": "P1", "bag_id": "",   "pack_sr": None, "design_no": "D"},  "P1|D"),
    ("M03", {"product_code": "P1", "bag_id": "",   "pack_sr": None, "design_no": ""},   "P1"),
    ("M04", {"product_code": "P1", "bag_id": "",   "pack_sr": 3,    "design_no": "D"},  "P1|sr3|D"),
    ("M05", {"product_code": "P1", "bag_id": "",   "pack_sr": 1.5,  "design_no": "D"},  "P1|sr1.5|D"),
    ("M06", {"product_code": "P1", "bag_id": "",   "pack_sr": 7,    "design_no": ""},   "P1|sr7"),
    ("M07", {"product_code": "P1", "bag_id": "",   "pack_sr": 0,    "design_no": ""},   "P1|sr0"),
    ("M08", {"product_code": "P1", "bag_id": "",   "pack_sr": "",   "design_no": "D"},  "P1|D"),       # Sites 1/2 skip sr branch on ""
    ("M09", {"product_code": None, "bag_id": "B1", "pack_sr": None, "design_no": ""},   "|B1"),        # Sites 1/2 coerce None to ""
    ("M10", {"product_code": None, "bag_id": None, "pack_sr": None, "design_no": None}, ""),           # Sites 1/2 → empty string
    ("M11", {"product_code": "P1", "bag_id": "",   "pack_sr": "X",  "design_no": "D"},  "P1|srX|D"),
    ("M12", {"product_code": "P1", "bag_id": " ",  "pack_sr": None, "design_no": ""},   "P1| "),
]

# ── Site 3 diverges on M08, M09, M10 (per INSPECTOR audit) ───────────────────
# Site 3: app.api.routes_packing._barcode_value  (routes_packing.py:173)
_SITE_3_CASES = [
    ("M01", {"product_code": "P1", "bag_id": "B1", "pack_sr": None, "design_no": "D"},  "P1|B1"),
    ("M02", {"product_code": "P1", "bag_id": "",   "pack_sr": None, "design_no": "D"},  "P1|D"),
    ("M03", {"product_code": "P1", "bag_id": "",   "pack_sr": None, "design_no": ""},   "P1"),
    ("M04", {"product_code": "P1", "bag_id": "",   "pack_sr": 3,    "design_no": "D"},  "P1|sr3|D"),
    ("M05", {"product_code": "P1", "bag_id": "",   "pack_sr": 1.5,  "design_no": "D"},  "P1|sr1.5|D"),
    ("M06", {"product_code": "P1", "bag_id": "",   "pack_sr": 7,    "design_no": ""},   "P1|sr7"),
    ("M07", {"product_code": "P1", "bag_id": "",   "pack_sr": 0,    "design_no": ""},   "P1|sr0"),
    ("M08", {"product_code": "P1", "bag_id": "",   "pack_sr": "",   "design_no": "D"},  "P1|sr|D"),    # Site 3 enters sr branch on ""
    ("M09", {"product_code": None, "bag_id": "B1", "pack_sr": None, "design_no": ""},   "None|B1"),    # Site 3 emits "None"
    ("M10", {"product_code": None, "bag_id": None, "pack_sr": None, "design_no": None}, None),         # Site 3 returns None (annot violation)
    ("M11", {"product_code": "P1", "bag_id": "",   "pack_sr": "X",  "design_no": "D"},  "P1|srX|D"),
    ("M12", {"product_code": "P1", "bag_id": " ",  "pack_sr": None, "design_no": ""},   "P1| "),
]


# ── Site 1 — packing_db._compute_scan_code ───────────────────────────────────

@pytest.mark.parametrize("case,row,expected", _SITES_1_AND_2_CASES,
                         ids=[c[0] for c in _SITES_1_AND_2_CASES])
def test_packing_db_compute_scan_code(case, row, expected):
    assert _pdb._compute_scan_code(row) == expected


# ── Site 2 — warehouse_db.scan_code_for_packing_line ─────────────────────────
# Deliberately duplicated parametrize block (do not share with Site 1) so any
# future divergence between Sites 1 and 2 surfaces as a failure in this file.

@pytest.mark.parametrize("case,row,expected", _SITES_1_AND_2_CASES,
                         ids=[c[0] for c in _SITES_1_AND_2_CASES])
def test_warehouse_db_scan_code_for_packing_line(case, row, expected):
    assert _wdb.scan_code_for_packing_line(row) == expected


# ── Site 3 — routes_packing._barcode_value ───────────────────────────────────
# Different expected outputs on M08, M09, M10 — see INSPECTOR audit.

@pytest.mark.parametrize("case,row,expected", _SITE_3_CASES,
                         ids=[c[0] for c in _SITE_3_CASES])
def test_routes_packing_barcode_value(case, row, expected):
    assert _rp._barcode_value(row) == expected


# ── Cross-site equality lock: Sites 1 ↔ 2 byte-equal across the full matrix ─

def test_sites_1_and_2_byte_equal_across_matrix():
    rows = [row for _case, row, _exp in _SITES_1_AND_2_CASES]
    for row in rows:
        assert _pdb._compute_scan_code(row) == _wdb.scan_code_for_packing_line(row), \
            f"Sites 1 and 2 diverged on {row!r}"


# ── Cross-site divergence pin: Site 3 vs Sites 1/2 on M08, M09, M10 ──────────

def test_site_3_divergence_from_sites_1_and_2():
    """
    M08, M09, M10 are the inputs where Site 3 diverges from Sites 1 and 2 per
    INSPECTOR audit. This test pins that divergence so any future change to
    either side surfaces here as a failure rather than as a silent behavior
    shift downstream.
    """
    m08 = {"product_code": "P1", "bag_id": "",   "pack_sr": "",   "design_no": "D"}
    m09 = {"product_code": None, "bag_id": "B1", "pack_sr": None, "design_no": ""}
    m10 = {"product_code": None, "bag_id": None, "pack_sr": None, "design_no": None}

    assert _pdb._compute_scan_code(m08) == "P1|D"
    assert _rp._barcode_value(m08)      == "P1|sr|D"

    assert _pdb._compute_scan_code(m09) == "|B1"
    assert _rp._barcode_value(m09)      == "None|B1"

    assert _pdb._compute_scan_code(m10) == ""
    assert _rp._barcode_value(m10)      is None


# ── customs-value-freeze guard on the matrix itself ─────────────────────────

def test_input_matrix_has_no_financial_keys():
    """The 12-row matrix must contain only identity fields. Defends against a
    future PR that quietly adds a monetary key to a fixture row."""
    forbidden = {
        "unit_price", "total_value", "cif", "duty", "vat", "amount",
        "gross_weight", "net_weight", "tax", "currency",
    }
    rows = [row for _case, row, _exp in _SITES_1_AND_2_CASES]
    rows += [row for _case, row, _exp in _SITE_3_CASES]
    for row in rows:
        assert not (forbidden & set(row.keys())), \
            f"Matrix row leaks financial key: {row!r}"

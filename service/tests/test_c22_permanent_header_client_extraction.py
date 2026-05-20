"""test_c22_permanent_header_client_extraction.py — C22-PERMANENT.

Authority chain for client extraction from packing-list xlsx files:

  1. Explicit label match in preamble: "Client:" / "Consignee:" / "Buyer:"
     / "Ship To:" (C13B behaviour, preserved).
  2. Free-standing company-suffix match in preamble: cell ends in GmbH /
     Sp z o.o. / s.r.o. / B.V. / Ltd / etc. (C22-PERMANENT, new).
  3. Filename `-Client <name>` suffix (C13B behaviour, preserved).

Hard rules:
  - The "Client Po" table column header MUST NEVER produce a client name.
  - "Order ###..." data cells MUST NEVER produce a client name.
  - Pass 2 stops scanning once a table header row is detected (avoids
    leaking into data rows).
"""
from __future__ import annotations

import re
import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import openpyxl
import pytest

# Load the helper functions from routes_packing.py without importing the whole
# FastAPI router (which would require app boot).
_ROUTES_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_packing.py"
)
_SRC = _ROUTES_PATH.read_text(encoding="utf-8")
_START = _SRC.index("# Two filename patterns for client name")
_END   = _SRC.index("# ── GET /api/v1/packing/{batch_id}/packing-documents")
_HELPER_SRC = _SRC[_START:_END]

_NS: Dict[str, Any] = {
    "re": re,
    "Path": Path,
    "List": List,
    "Dict": Dict,
    "Any":  Any,
    "Optional": Optional,
    "Callable": Callable,
}
exec(_HELPER_SRC, _NS)

_guess_client_from_preamble = _NS["_guess_client_from_preamble"]
_guess_client_from_filename = _NS["_guess_client_from_filename"]
_looks_like_company_name    = _NS["_looks_like_company_name"]
_is_table_header_or_data_row = _NS["_is_table_header_or_data_row"]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_xlsx(tmp_path: Path, rows: List[List[Any]]) -> Path:
    """Write a tiny xlsx with `rows` to tmp_path / 'test.xlsx' and return path."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = tmp_path / "test.xlsx"
    wb.save(out)
    return out


# ── Pass-2 company-suffix detection (the C22-PERMANENT addition) ────────────


@pytest.mark.parametrize("text", [
    "DiamondGroup GmbH",
    "Acme GmbH",
    "Diamond Point B.V.",
    "Dream Rings, s.r.o.",
    "Acme Sp. z o.o.",
    "Acme Sp z o o",            # space-separated PL form
    "ACME SP Z O O",            # uppercase
    "Some Studio Ltd",
    "Some Holding AG",
    "Some Maison S.A.",
    "Some Studio S.p.A.",       # Italian
    "Some Studio S.L.",         # Spanish
])
def test_pass2_accepts_known_company_suffix(text):
    assert _looks_like_company_name(text), f"should accept {text!r}"


@pytest.mark.parametrize("text", [
    "Client Po",        # the column header we MUST never pick up
    "Order 50260837",   # data cell
    "Order",
    "PO",
    "Po",               # exact stub from the original parsing bug
    "Invoice #",
    "Total Value",
    "Sr",
    "Ctg",
    "Qty",
    "Panakas",          # no company-form suffix → must rely on Pass 1 / filename
    "Diamond Point",    # ditto
    "",
    "   ",
])
def test_pass2_rejects_non_company_cells(text):
    assert not _looks_like_company_name(text), f"should reject {text!r}"


# ── End-to-end: real DiamondGroup-style xlsx (Pass 2 wins) ──────────────────


def test_extracts_diamondgroup_gmbh_from_header_without_label(tmp_path):
    """The canonical bug fixture: invoice 178 layout where the buyer name
    sits as a free-standing cell in row 5 with NO 'Client:' label."""
    xlsx = _make_xlsx(tmp_path, [
        [None, "SHIPMENT PACKING LIST"],                          # R1
        [None, None],                                              # R2
        [None, None, None, None, None, None, None, None, None,
         None, "Invoice #", None, None, "EJL/26-27/178"],          # R4
        [None, "DiamondGroup GmbH"],                               # R5 — bare company name
        [None, None, None, None, None, None, None, None, None,
         None, "Dated :", None, None, "2026-05-16"],               # R6
        [None, "Dreckenacher Weg 1"],                              # R7
        [None, "56295 Lonnig, Germany"],                           # R8
        [None, None],                                              # R9
        [None, "+49 (0) 2607 97378"],                              # R10
        [None, None],                                              # R11
        [None, "Sr", "Ctg", "Client Po", "Design",
         "Kt", "Col", "Quality", "Dia Wt", "Col Wt",
         None, "Qty", None, None, "Value", "Total Value",
         None, None, "Size"],                                      # R12 — table header
        [None, 1, "RNG", "Order 50260837", "JR08007",
         "18KT", "Y", "GH-SI", 0.095, 0,
         None, 1, None, None, 230, 230, None, None, 54.0],         # R13 — data
    ])
    assert _guess_client_from_preamble(str(xlsx)) == "DiamondGroup GmbH"


def test_pass1_label_still_wins_over_pass2(tmp_path):
    """If a 'Client:' label exists in the preamble, it MUST win over a
    bare company-suffix cell elsewhere (priority preserved)."""
    xlsx = _make_xlsx(tmp_path, [
        [None, "SHIPMENT PACKING LIST"],
        [None, "Client: Real Buyer S.A."],          # label-prefixed (Pass 1)
        [None, "Other GmbH"],                       # bare suffix (Pass 2)
        [None, "Sr", "Ctg", "Client Po", "Design", "Qty", "Value"],
    ])
    assert _guess_client_from_preamble(str(xlsx)) == "Real Buyer S.A."


def test_pass2_never_uses_client_po_column_header(tmp_path):
    """Even if no other client info exists, the 'Client Po' table header
    must never be returned as the client."""
    xlsx = _make_xlsx(tmp_path, [
        [None, "SHIPMENT PACKING LIST"],
        [None, "Sr", "Ctg", "Client Po", "Design", "Qty", "Value"],  # only table header
        [None, 1, "RNG", "Order 50260837", "JR08007", 1, 230],
    ])
    assert _guess_client_from_preamble(str(xlsx)) == ""


def test_pass2_never_picks_up_order_data_row(tmp_path):
    """Even with the 'Order 50260837' cell visible BELOW the header, scan
    must stop at the table-header row so data rows are never inspected."""
    xlsx = _make_xlsx(tmp_path, [
        [None, None],
        [None, None],
        [None, "Sr", "Ctg", "Client Po", "Design", "Qty"],            # header (R3)
        [None, 1, "RNG", "Order Acme GmbH", "JR08007", 1],            # devious data
    ])
    # Pass 1 finds no label.  Pass 2 stops at row 3 → never reads row 4.
    assert _guess_client_from_preamble(str(xlsx)) == ""


def test_table_header_detector_catches_real_layout():
    """Sanity test on the table-header heuristic used to stop preamble scan."""
    assert _is_table_header_or_data_row([
        "", "Sr", "Ctg", "Client Po", "Design", "Kt", "Qty",
    ])
    assert _is_table_header_or_data_row(["Sr", "Ctg", "Qty", "Value"])
    # Address rows must NOT be classified as table headers
    assert not _is_table_header_or_data_row(["", "Dreckenacher Weg 1"])
    assert not _is_table_header_or_data_row(["", "56295 Lonnig, Germany"])
    # Single-cell company name row must NOT trigger
    assert not _is_table_header_or_data_row(["", "DiamondGroup GmbH"])


# ── Filename extraction (C13B behaviour preserved) ──────────────────────────


def test_filename_extraction_still_works():
    assert _guess_client_from_filename(
        "180 Client Panakas.xlsx"
    ) == "Panakas"
    assert _guess_client_from_filename(
        "EJL-26-27-180-Shipment packing list of -1pcs-16.05.26-Client Panakas.xlsx"
    ) == "Panakas"
    # The orphan filename pattern from the bug:
    assert _guess_client_from_filename(
        "EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx"
    ) == ""


# ── Negative regression: existing 4 clients on the live batch must keep
# ── working under the new parser (no fields shift or get truncated).


def test_no_collateral_change_for_filename_only_clients(tmp_path):
    """A packing list with only filename-encoded client and a label-less
    preamble that ALSO contains no company-suffix cell must return '' from
    preamble (fallback to filename), not pick up something accidental."""
    xlsx = _make_xlsx(tmp_path, [
        [None, "SHIPMENT PACKING LIST"],
        [None, None],
        [None, None, None, None, None, None, None, None, None,
         None, "Invoice #", None, None, "EJL/26-27/180"],
        [None, "Acme Estrella"],   # bare name, no suffix, not in denylist
        [None, "Sr", "Ctg", "Client Po", "Design", "Qty"],   # table header
    ])
    # Pass 2 has no suffix to match → returns ''.  Caller must fall back
    # to filename extraction.
    assert _guess_client_from_preamble(str(xlsx)) == ""

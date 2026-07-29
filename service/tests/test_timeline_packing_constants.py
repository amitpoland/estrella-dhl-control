"""Regression guard for timeline constant completeness.

Issue #75: EV_PACKING_LIST_EXTRACTED was missing from timeline.py,
causing AttributeError in production (routes_packing.py:392).
Fixed in PR #74. This file prevents silent re-introduction.

Coverage (source-grep):
  - EV_PACKING_LIST_EXTRACTED defined in timeline.py
  - EV_PACKING_MATCHED_TO_INVOICE defined in timeline.py
  - Every EV_ constant referenced in routes_packing.py exists in timeline.py
  - String values are non-empty and distinct
"""
from __future__ import annotations

import re
from pathlib import Path

_TIMELINE = Path(__file__).parent.parent / "app" / "core" / "timeline.py"
_PACKING  = Path(__file__).parent.parent / "app" / "api" / "routes_packing.py"

_tl_src  = _TIMELINE.read_text(encoding="utf-8")
_pk_src  = _PACKING.read_text(encoding="utf-8")


# ── Constants exist in timeline.py ───────────────────────────────────────────

def test_ev_packing_list_extracted_defined():
    """EV_PACKING_LIST_EXTRACTED must be present in timeline.py (issue #75)."""
    assert "EV_PACKING_LIST_EXTRACTED" in _tl_src


def test_ev_packing_matched_to_invoice_defined():
    """EV_PACKING_MATCHED_TO_INVOICE must be present in timeline.py (issue #75)."""
    assert "EV_PACKING_MATCHED_TO_INVOICE" in _tl_src


# ── String values are non-empty ───────────────────────────────────────────────

def test_ev_packing_list_extracted_has_nonempty_value():
    m = re.search(r'EV_PACKING_LIST_EXTRACTED\s*=\s*"([^"]+)"', _tl_src)
    assert m is not None and m.group(1).strip(), "EV_PACKING_LIST_EXTRACTED value must be non-empty"


def test_ev_packing_matched_to_invoice_has_nonempty_value():
    m = re.search(r'EV_PACKING_MATCHED_TO_INVOICE\s*=\s*"([^"]+)"', _tl_src)
    assert m is not None and m.group(1).strip(), "EV_PACKING_MATCHED_TO_INVOICE value must be non-empty"


# ── Values are distinct ───────────────────────────────────────────────────────

def test_packing_event_values_are_distinct():
    extracted = re.search(r'EV_PACKING_LIST_EXTRACTED\s*=\s*"([^"]+)"', _tl_src)
    matched   = re.search(r'EV_PACKING_MATCHED_TO_INVOICE\s*=\s*"([^"]+)"', _tl_src)
    assert extracted and matched, "Both packing constants must be defined"
    assert extracted.group(1) != matched.group(1), "Packing event string values must be distinct"


# ── Every EV_ referenced in routes_packing.py is defined in timeline.py ─────

def _referenced_constants(src: str) -> set[str]:
    """Extract all `tl.EV_*` names referenced in a source file."""
    return set(re.findall(r"tl\.(EV_[A-Z_]+)", src))


def _defined_constants(src: str) -> set[str]:
    """Extract all `EV_*` names defined at module level in a source file."""
    return set(re.findall(r"^(EV_[A-Z_]+)\s*=", src, re.MULTILINE))


def test_no_missing_ev_constants_in_routes_packing():
    """Every tl.EV_* used in routes_packing.py must be defined in timeline.py.

    This test catches the class of defect in issue #75 automatically:
    if a developer adds a new timeline event reference in routes_packing.py
    without adding the constant to timeline.py, this test fails in CI
    before the AttributeError reaches production.
    """
    referenced = _referenced_constants(_pk_src)
    defined    = _defined_constants(_tl_src)
    missing    = referenced - defined
    assert not missing, (
        f"EV_ constants referenced in routes_packing.py but missing from timeline.py: "
        f"{sorted(missing)}"
    )

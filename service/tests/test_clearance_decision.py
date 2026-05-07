"""
test_clearance_decision.py — boundary tests for the value-based clearance
decision engine.

Spec docs/dhl_clearance_paths.md line 17:
    clearance_path = "dhl_self_clearance" if total < USD 2500
    else clearance_path = "agency_clearance"

Phase 1.1.5 re-flips the writer to spec names atomically with the reader
sweep. Legacy names remain accepted by readers via
clearance_path_alias.normalize_path so old audit data still flows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.clearance_decision import (
    build_clearance_decision,
    THRESHOLD_USD,
)
from app.services.clearance_path_alias import (
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
    is_agency_clearance,
    is_dhl_self_clearance,
    normalize_path,
)


def _audit(cif: float) -> dict:
    return {"invoice_totals": {"total_cif_usd": cif}}


def test_threshold_constant_unchanged():
    assert THRESHOLD_USD == 2_500.0


# ── Boundary semantics (Phase 0.2, still pinned) ───────────────────────────

def test_just_below_threshold_is_self_clearance():
    dec = build_clearance_decision(_audit(2499.99))
    assert dec["clearance_path"] == "dhl_self_clearance"
    assert is_dhl_self_clearance(dec["clearance_path"])


def test_exactly_threshold_is_agency_clearance():
    """Boundary fix: CIF == USD 2500 must classify as agency clearance."""
    dec = build_clearance_decision(_audit(2500.00))
    assert dec["clearance_path"] == "agency_clearance"
    assert is_agency_clearance(dec["clearance_path"])


def test_just_above_threshold_is_agency_clearance():
    dec = build_clearance_decision(_audit(2500.01))
    assert dec["clearance_path"] == "agency_clearance"
    assert is_agency_clearance(dec["clearance_path"])


def test_zero_cif_is_routing_pending():
    dec = build_clearance_decision({})
    assert dec["clearance_path"] == PATH_ROUTING_PENDING


def test_zero_cif_explicit_is_routing_pending():
    dec = build_clearance_decision(_audit(0))
    assert dec["clearance_path"] == PATH_ROUTING_PENDING


# ── Writer migration: spec names emitted (post Phase 1.1.5) ──────────────

def test_writer_emits_spec_name_for_agency_path():
    dec = build_clearance_decision(_audit(5000.00))
    assert dec["clearance_path"] == "agency_clearance"
    assert is_agency_clearance(dec["clearance_path"])


def test_writer_emits_spec_name_for_self_clearance_path():
    dec = build_clearance_decision(_audit(1000.00))
    assert dec["clearance_path"] == "dhl_self_clearance"
    assert is_dhl_self_clearance(dec["clearance_path"])


# ── Parametrized: both spec and legacy names normalize identically ────────

@pytest.mark.parametrize("path,expected_helper,expected_normal", [
    ("dhl_self_clearance",        is_dhl_self_clearance, PATH_DHL_SELF_CLEARANCE),
    ("carrier_self_clearance",    is_dhl_self_clearance, PATH_DHL_SELF_CLEARANCE),
    ("agency_clearance",          is_agency_clearance,   PATH_AGENCY_CLEARANCE),
    ("external_agency_clearance", is_agency_clearance,   PATH_AGENCY_CLEARANCE),
])
def test_alias_helpers_accept_both_names(path, expected_helper, expected_normal):
    assert expected_helper(path) is True
    assert normalize_path(path) == expected_normal

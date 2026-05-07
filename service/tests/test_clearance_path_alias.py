"""
test_clearance_path_alias.py — pin the back-compat alias contract.

Spec at docs/dhl_clearance_paths.md uses spec names "dhl_self_clearance"
and "agency_clearance". The codebase historically used legacy names
"carrier_self_clearance" and "external_agency_clearance". This module
collapses both via normalize_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.clearance_path_alias import (
    KNOWN_PATHS,
    LEGACY_CARRIER_SELF_CLEARANCE,
    LEGACY_EXTERNAL_AGENCY_CLEARANCE,
    LEGACY_TO_SPEC,
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
    is_agency_clearance,
    is_dhl_self_clearance,
    is_routing_pending,
    normalize_path,
)


# ── Constants ──────────────────────────────────────────────────────────────

def test_spec_canonical_constants():
    assert PATH_DHL_SELF_CLEARANCE == "dhl_self_clearance"
    assert PATH_AGENCY_CLEARANCE   == "agency_clearance"
    assert PATH_ROUTING_PENDING    == "routing_pending"


def test_legacy_constants():
    assert LEGACY_CARRIER_SELF_CLEARANCE    == "carrier_self_clearance"
    assert LEGACY_EXTERNAL_AGENCY_CLEARANCE == "external_agency_clearance"


def test_legacy_to_spec_mapping():
    assert LEGACY_TO_SPEC == {
        "carrier_self_clearance":    "dhl_self_clearance",
        "external_agency_clearance": "agency_clearance",
    }


def test_known_paths_contents():
    assert KNOWN_PATHS == frozenset({
        "dhl_self_clearance", "agency_clearance", "routing_pending",
        "carrier_self_clearance", "external_agency_clearance",
    })


# ── normalize_path ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("dhl_self_clearance",        "dhl_self_clearance"),
    ("agency_clearance",          "agency_clearance"),
    ("routing_pending",           "routing_pending"),
    ("carrier_self_clearance",    "dhl_self_clearance"),
    ("external_agency_clearance", "agency_clearance"),
    (None,                        "routing_pending"),
    ("",                          "routing_pending"),
    ("garbage",                   "routing_pending"),
    ("DHL_SELF_CLEARANCE",        "routing_pending"),  # case-sensitive by design
])
def test_normalize_path(inp, expected):
    assert normalize_path(inp) == expected


# ── Boolean helpers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp", ["dhl_self_clearance", "carrier_self_clearance"])
def test_is_dhl_self_clearance_true(inp):
    assert is_dhl_self_clearance(inp) is True


@pytest.mark.parametrize("inp", [
    "agency_clearance", "external_agency_clearance",
    "routing_pending", None, "", "garbage",
])
def test_is_dhl_self_clearance_false(inp):
    assert is_dhl_self_clearance(inp) is False


@pytest.mark.parametrize("inp", ["agency_clearance", "external_agency_clearance"])
def test_is_agency_clearance_true(inp):
    assert is_agency_clearance(inp) is True


@pytest.mark.parametrize("inp", [
    "dhl_self_clearance", "carrier_self_clearance",
    "routing_pending", None, "", "garbage",
])
def test_is_agency_clearance_false(inp):
    assert is_agency_clearance(inp) is False


@pytest.mark.parametrize("inp,expected", [
    ("routing_pending",           True),
    (None,                        True),
    ("",                          True),
    ("garbage",                   True),
    ("dhl_self_clearance",        False),
    ("agency_clearance",          False),
    ("carrier_self_clearance",    False),
    ("external_agency_clearance", False),
])
def test_is_routing_pending(inp, expected):
    assert is_routing_pending(inp) is expected

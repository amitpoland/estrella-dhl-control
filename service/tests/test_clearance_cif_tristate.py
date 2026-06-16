"""
test_clearance_cif_tristate.py — pins the tri-state CIF contract THROUGH the
clearance decision engine (build_clearance_decision) and the dashboard surface
(shipment-detail.html).

The clearance decision now delegates CIF resolution to cif_resolver.resolve_cif
and maps the tri-state verdict onto routing:

    RESOLVED      → value-based path (agency >= 2500, else carrier self)
    DECLARED_ZERO → carrier self-clearance, flagged distinctly (not a parser miss)
    UNKNOWN       → routing_pending, with an operator-actionable cif_extraction_gap
                    (NEVER a fabricated 0.0 that mis-routes as a real low value)

It also asserts the shipment-detail.html Clearance Routing card renders the new
tri-state surfaces (extraction-gap block, declared-zero block) so an UNKNOWN CIF
shows the operator which layer failed and what to do next — not a silent 0.00.
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
    build_fedex_clearance_decision,
    THRESHOLD_USD,
)
from app.services.clearance_path_alias import (
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
    is_agency_clearance,
    is_dhl_self_clearance,
)


# ── RESOLVED — value-based routing carries the new tri-state fields ───────────

def test_resolved_low_value_self_clearance_carries_cif_state():
    dec = build_clearance_decision({"invoice_totals": {"total_cif_usd": 732.0}})
    assert is_dhl_self_clearance(dec["clearance_path"])
    assert dec["total_value_usd"] == pytest.approx(732.0)
    assert dec["cif_state"] == "resolved"
    assert dec["cif_extraction_gap"] is None
    assert dec["cif_source"] == "invoice_totals.total_cif_usd"


def test_resolved_high_value_agency_clearance_carries_cif_state():
    dec = build_clearance_decision({"invoice_totals": {"total_cif_usd": 3000.0}})
    assert is_agency_clearance(dec["clearance_path"])
    assert dec["require_dsk"] is True
    assert dec["cif_state"] == "resolved"
    assert dec["cif_extraction_gap"] is None


def test_resolved_from_awb_custom_val_when_only_waybill_present():
    """Proof point through the decision engine: AWB 2315714531 (CIF 732 from the
    waybill only) routes to self-clearance, NOT routing_pending."""
    dec = build_clearance_decision(
        {"awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": None}}
    )
    assert is_dhl_self_clearance(dec["clearance_path"])
    assert dec["total_value_usd"] == pytest.approx(732.0)
    assert dec["cif_state"] == "resolved"
    assert dec["cif_source"] == "awb_customs.value_usd"


# ── UNKNOWN — routing_pending with an extraction gap, never a fake 0.0 ────────

def test_unknown_cif_is_routing_pending_with_gap():
    dec = build_clearance_decision({})
    assert dec["clearance_path"] == PATH_ROUTING_PENDING
    assert dec["cif_state"] == "unknown"
    assert dec["cif_source"] == "unavailable"
    assert dec["decision_reason"] == "cif_zero_routing_pending"
    # The machine-readable gap travels alongside the long-pinned missing_reason.
    assert dec["cif_extraction_gap"] is not None
    assert dec["cif_extraction_gap"]["first_failed_layer"] == "invoice_upload"
    assert dec["cif_extraction_gap"]["next_action"]


def test_unknown_missing_reason_substrings_preserved():
    """The long-pinned operator substrings must remain stable for the dashboard."""
    dec_no_invoice = build_clearance_decision({})
    assert "not uploaded" in dec_no_invoice["missing_reason"].lower()

    dec_unparsed = build_clearance_decision({"invoice_names": ["inv.pdf"]})
    assert "parsed" in dec_unparsed["missing_reason"].lower()


# ── DECLARED_ZERO — explicit zero is distinct from a parser miss ──────────────

def test_declared_zero_routes_self_clearance_distinctly():
    dec = build_clearance_decision({"customs_declared_value_zero": True})
    assert is_dhl_self_clearance(dec["clearance_path"])
    assert dec["cif_state"] == "declared_zero"
    assert dec["decision_reason"] == "cif_declared_zero"
    assert dec["total_value_usd"] == 0.0
    assert dec["require_dsk"] is False
    assert dec["cif_extraction_gap"] is None


def test_declared_zero_is_not_the_same_as_unknown():
    """Regression guard against the original bug: a genuine declared zero and an
    extraction-failed unknown must NOT collapse into the same routing state."""
    declared = build_clearance_decision({"customs_declared_value_zero": True})
    unknown = build_clearance_decision({})
    assert declared["cif_state"] != unknown["cif_state"]
    assert declared["clearance_path"] != unknown["clearance_path"]


# ── FedEx path: the SAME tri-state contract — no silent 0.0 ───────────────────
# Regression guard for the convergent reviewer CRITICAL: build_fedex_clearance_
# decision historically used the pre-fix `float(... or 0)` chain, so a FedEx
# extraction failure produced total_value_usd=0.0 with no cif_state/gap — the
# exact silent-zero bug, alive on the FedEx path. It now delegates to resolve_cif.

def test_fedex_unknown_cif_is_routing_pending_not_fake_zero():
    dec = build_fedex_clearance_decision({})
    assert dec["carrier"] == "FEDEX"
    assert dec["clearance_path"] == PATH_ROUTING_PENDING
    assert dec["cif_state"] == "unknown"
    assert dec["cif_source"] == "unavailable"
    # No fabricated routing: agency/cesja are NOT asserted while CIF is unknown.
    assert dec["require_dsk"] is None
    assert dec["require_cesja_manual"] is None
    assert dec["agency"] is None
    # The machine-readable gap is surfaced for the operator.
    assert dec["cif_extraction_gap"] is not None
    assert dec["cif_extraction_gap"]["first_failed_layer"] == "invoice_upload"
    assert dec["cif_extraction_gap"]["next_action"]


def test_fedex_resolved_cif_routes_ganther_with_state():
    dec = build_fedex_clearance_decision({"invoice_totals": {"total_cif_usd": 3000.0}})
    assert dec["carrier"] == "FEDEX"
    assert dec["clearance_path"] == "fedex_ganther_clearance"
    assert dec["total_value_usd"] == pytest.approx(3000.0)
    assert dec["cif_state"] == "resolved"
    assert dec["cif_extraction_gap"] is None
    assert dec["require_cesja_manual"] is True
    assert dec["agency"] == "Ganther"


def test_fedex_resolves_from_awb_custom_val():
    """FedEx proof-point parity: CIF reaches the audit only via the waybill."""
    dec = build_fedex_clearance_decision(
        {"awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": None}}
    )
    assert dec["clearance_path"] == "fedex_ganther_clearance"
    assert dec["total_value_usd"] == pytest.approx(732.0)
    assert dec["cif_state"] == "resolved"
    assert dec["cif_source"] == "awb_customs.value_usd"


def test_fedex_declared_zero_is_distinct_from_unknown():
    declared = build_fedex_clearance_decision({"customs_declared_value_zero": True})
    unknown = build_fedex_clearance_decision({})
    assert declared["cif_state"] == "declared_zero"
    assert declared["decision_reason"] == "fedex_declared_zero"
    assert declared["clearance_path"] == "fedex_ganther_clearance"
    assert declared["cif_state"] != unknown["cif_state"]
    assert declared["clearance_path"] != unknown["clearance_path"]


# ── Dashboard surface: shipment-detail.html renders the tri-state UI ──────────

def _shipment_detail_html() -> str:
    p = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"
    return p.read_text(encoding="utf-8")


def test_dashboard_renders_extraction_gap_block():
    html = _shipment_detail_html()
    assert 'data-testid="clearance-extraction-gap"' in html
    assert 'data-testid="clearance-extraction-next-action"' in html
    # gap fields surfaced to the operator
    assert "first_failed_layer" in html
    assert "next_action" in html


def test_dashboard_renders_declared_zero_block():
    html = _shipment_detail_html()
    assert 'data-testid="clearance-declared-zero"' in html


def test_dashboard_reads_cif_state_not_just_source():
    html = _shipment_detail_html()
    assert "cif_state" in html
    assert "cif_extraction_gap" in html


def test_dashboard_labels_awb_custom_val_source():
    html = _shipment_detail_html()
    assert "AWB Custom Val (carrier-declared)" in html


def test_dashboard_decision_value_shows_not_calculated_not_zero():
    """The Decision Value row must render 'Not calculated' for an absent/zero CIF
    — never a misleading 'USD 0.00' that reads like a real declared value."""
    html = _shipment_detail_html()
    assert 'data-testid="clearance-decision-value"' in html
    assert "Not calculated" in html
    # The guard is decCif != null && decCif > 0 — i.e. a null/zero CIF falls to
    # the 'Not calculated' branch rather than formatting a fake USD 0.00.
    assert "decCif != null && decCif > 0" in html

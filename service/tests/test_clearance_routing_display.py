"""test_clearance_routing_display.py — regression for the 2026-05-17
Clearance Routing UI gap.

Confirms that `build_clearance_decision` now surfaces:
  - `total_value_usd`  — the CIF actually used by the rule
  - `threshold_usd`    — the THRESHOLD_USD constant (reused, not hard-coded)
  - `cif_source`       — operator-readable provenance for the value
  - `missing_reason`   — when routing_pending, the smallest next step
  - `clearance_path`   — agency / dhl_self / routing_pending

And that the frontend Clearance Routing card renders all four.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from app.services.clearance_decision import (
    THRESHOLD_USD,
    build_clearance_decision,
)
from app.services.clearance_path_alias import (
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
)


# ── Threshold constant reused ─────────────────────────────────────────────

def test_threshold_constant_is_2500():
    assert THRESHOLD_USD == 2500.0


# ── No CIF → routing_pending with missing_reason ──────────────────────────

def test_no_cif_returns_routing_pending_with_missing_reason():
    dec = build_clearance_decision({})
    assert dec["clearance_path"] == PATH_ROUTING_PENDING
    assert dec["total_value_usd"] == 0.0
    assert dec["threshold_usd"] == THRESHOLD_USD
    assert dec["cif_source"] == "unavailable"
    assert "missing_reason" in dec
    assert "invoice" in dec["missing_reason"].lower()
    assert dec["decision_reason"] == "cif_zero_routing_pending"


def test_no_invoice_uploaded_reason():
    dec = build_clearance_decision({})
    assert "not uploaded" in dec["missing_reason"].lower()


def test_invoice_uploaded_but_not_parsed_reason():
    dec = build_clearance_decision({"invoice_names": ["x.pdf"]})
    assert dec["clearance_path"] == PATH_ROUTING_PENDING
    assert "parsed" in dec["missing_reason"].lower() \
        or "recheck" in dec["missing_reason"].lower()


# ── Below threshold → carrier self-clearance ─────────────────────────────

def test_cif_below_threshold_uses_self_clearance():
    audit = {"verification": {"invoice_cif_total_usd": 1234.56}}
    dec = build_clearance_decision(audit)
    assert dec["clearance_path"] == PATH_DHL_SELF_CLEARANCE
    assert dec["total_value_usd"] == 1234.56
    assert dec["threshold_usd"] == THRESHOLD_USD
    assert dec["cif_source"] == "verification.invoice_cif_total_usd"
    assert dec["decision_reason"] == "value_below_threshold"
    assert dec["carrier_handles"] is True
    assert dec["agency"] is None


def test_cif_exactly_at_threshold_routes_to_agency():
    """≥ threshold goes agency (operator brief explicitly wraps 2500 into
    'above-threshold'; THRESHOLD_USD comparison uses >=)."""
    audit = {"verification": {"invoice_cif_total_usd": 2500.00}}
    dec = build_clearance_decision(audit)
    assert dec["clearance_path"] == PATH_AGENCY_CLEARANCE


# ── Above threshold → agency clearance ───────────────────────────────────

def test_cif_above_threshold_uses_agency():
    audit = {"verification": {"invoice_cif_total_usd": 7500.00}}
    dec = build_clearance_decision(audit)
    assert dec["clearance_path"] == PATH_AGENCY_CLEARANCE
    assert dec["total_value_usd"] == 7500.00
    assert dec["cif_source"] == "verification.invoice_cif_total_usd"
    assert dec["decision_reason"] == "value_above_threshold"
    assert dec["agency"] == "Agencja Celna Spedycja"
    assert dec["carrier_handles"] is False


# ── CIF source priority ──────────────────────────────────────────────────

def test_invoice_totals_cif_used_when_verification_absent():
    audit = {"invoice_totals": {"total_cif_usd": 1500.0}}
    dec = build_clearance_decision(audit)
    assert dec["cif_source"] == "invoice_totals.total_cif_usd"
    assert dec["total_value_usd"] == 1500.0


def test_fob_fallback_when_cif_absent():
    audit = {"invoice_totals": {"total_fob_usd": 800.0}}
    dec = build_clearance_decision(audit)
    assert dec["cif_source"] == "invoice_totals.total_fob_usd"
    assert dec["total_value_usd"] == 800.0


def test_verification_takes_priority_over_invoice_totals():
    audit = {
        "verification":    {"invoice_cif_total_usd": 1000.0},
        "invoice_totals":  {"total_cif_usd": 999.0, "total_fob_usd": 888.0},
    }
    dec = build_clearance_decision(audit)
    assert dec["cif_source"] == "verification.invoice_cif_total_usd"
    assert dec["total_value_usd"] == 1000.0


# ── No side-effects: builder is pure ─────────────────────────────────────

def test_builder_is_pure_no_email_no_dhl_trigger():
    """Source-grep the builder file to confirm no email/DHL/wFirma/proforma
    trigger from clearance_decision computation."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services" / "clearance_decision.py").read_text(encoding="utf-8")
    for forbidden in (
        "send_email", "queue_email", "smtp",
        "create_pz", "generate_pz",
        "wfirma_client", "wfirma_api",
        "proforma_create", "proforma_issue", "proforma_post",
        "trigger_clearance", "process_sad",
    ):
        assert forbidden not in src, f"clearance_decision must not reference {forbidden!r}"


# ── Frontend source-grep ─────────────────────────────────────────────────

def test_dashboard_clearance_routing_card_renders_new_fields():
    dash = (Path(__file__).resolve().parents[1] / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    assert 'data-testid="clearance-routing-card"' in dash
    assert 'data-testid="clearance-path-label"' in dash
    assert 'data-testid="clearance-decision-value"' in dash
    assert 'data-testid="clearance-threshold"' in dash
    assert 'data-testid="clearance-value-source"' in dash
    assert 'data-testid="clearance-pending-reason"' in dash
    # Friendly source labels present:
    assert "verified invoice CIF" in dash
    assert "FOB fallback" in dash
    # Email routing not removed — still present:
    assert "odprawacelna@dhl.com" in dash

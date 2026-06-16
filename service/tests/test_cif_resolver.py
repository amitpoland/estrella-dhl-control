"""
test_cif_resolver.py — contract tests for the tri-state CIF authority resolver
(app.services.cif_resolver.resolve_cif).

Why this module exists
----------------------
The historic financial-data bug: an OCR / parser / AI extraction failure would
collapse the customs CIF to ``0.0``, and that fake zero flowed downstream as if
it were a real declared value — silently mis-routing clearance and suppressing
the "we don't know yet" signal the operator needs. ``resolve_cif`` makes that
impossible. These tests pin the three guarantees:

  1. Source PRIORITY — invoice authority (verification → invoice_totals → FOB →
     precheck) always outranks the carrier-declared AWB Custom Val.
  2. TRI-STATE — every outcome is RESOLVED / DECLARED_ZERO / UNKNOWN, never a
     silent fake zero.
  3. Terminal fallback is UNKNOWN (cif_usd is None), NEVER 0.0 — including the
     AI-fallback path (AI is not auto-invoked here; the terminal state is an
     operator-actionable extraction_gap, not a fabricated number).

Proof point: AWB 2315714531 / inv_122.pdf, CIF USD 732. When only the AWB
Custom Val reaches the audit (invoice CIF never landed), the shipment must
resolve to 732 from awb_customs.value_usd — not collapse to 0.0 / routing-blocked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
    resolve_cif,
)


# ── Source priority ladder ───────────────────────────────────────────────────

def test_verification_wins_over_everything():
    audit = {
        "verification":  {"invoice_cif_total_usd": 5000.0},
        "invoice_totals": {"total_cif_usd": 4000.0, "total_fob_usd": 3000.0},
        "dhl_precheck":  {"invoice_cif_total_usd": 2000.0, "fob_total_usd": 1000.0},
        "awb_customs":   {"value_usd": 732.0, "currency": "USD", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(5000.0)
    assert res["cif_source"] == "verification.invoice_cif_total_usd"
    assert res["extraction_gap"] is None


def test_invoice_totals_cif_beats_fob_and_precheck_and_awb():
    audit = {
        "invoice_totals": {"total_cif_usd": 4000.0, "total_fob_usd": 3000.0},
        "dhl_precheck":  {"fob_total_usd": 1000.0},
        "awb_customs":   {"value_usd": 732.0, "currency": "USD", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_source"] == "invoice_totals.total_cif_usd"
    assert res["cif_usd"] == pytest.approx(4000.0)


def test_fob_fallback_when_no_cif_total():
    audit = {
        "invoice_totals": {"total_fob_usd": 3000.0},
        "awb_customs":   {"value_usd": 732.0, "currency": "USD", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_source"] == "invoice_totals.total_fob_usd"
    assert res["cif_usd"] == pytest.approx(3000.0)


def test_precheck_used_before_awb():
    audit = {
        "dhl_precheck": {"invoice_cif_total_usd": 2200.0},
        "awb_customs":  {"value_usd": 732.0, "currency": "USD", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_source"] == "dhl_precheck.invoice_cif_total_usd"
    assert res["cif_usd"] == pytest.approx(2200.0)


def test_invoice_cif_has_priority_over_awb_custom_val():
    """Hard constraint: Invoice CIF has priority over AWB Custom Val."""
    audit = {
        "invoice_totals": {"total_cif_usd": 1500.0},
        "awb_customs":   {"value_usd": 732.0, "currency": "USD", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_source"] == "invoice_totals.total_cif_usd"
    assert res["cif_usd"] == pytest.approx(1500.0)
    # The resolver short-circuits on the first usable layer, so the AWB layer is
    # never even reached: it must NOT appear in the attempts trace, and the
    # winning layer is the invoice CIF — proving invoice authority outranks AWB.
    used = [a["layer"] for a in res["attempts"] if a["used"]]
    assert used == ["invoice_totals.total_cif_usd"]
    assert "awb_customs.value_usd" not in [a["layer"] for a in res["attempts"]]


# ── Proof point: AWB 2315714531 (CIF USD 732) resolves from the waybill ───────

def test_awb_2315714531_resolves_from_awb_custom_val():
    """The proof-point shipment: invoice CIF never reached the audit, only the
    AWB Custom Val (USD 732). It must RESOLVE to 732 — not collapse to 0.0."""
    audit = {"awb_customs": {"value_usd": 732.0, "currency": "USD", "gap": None}}
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(732.0)
    assert res["cif_source"] == "awb_customs.value_usd"
    assert res["extraction_gap"] is None


# ── Tri-state: UNKNOWN, never a fake 0.0 ──────────────────────────────────────

def test_empty_audit_is_unknown_not_zero():
    res = resolve_cif({})
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None                # NOT 0.0
    assert res["cif_source"] == "unavailable"
    assert res["extraction_gap"] is not None
    assert res["extraction_gap"]["first_failed_layer"] == "invoice_upload"
    assert res["extraction_gap"]["next_action"]


def test_all_zero_values_are_unknown_not_zero():
    """A parser that wrote 0.0 into every layer is a parser-miss, NOT a declared
    zero — the resolver must return UNKNOWN, never echo the fabricated 0.0."""
    audit = {
        "invoice_names": ["inv_122.pdf"],
        "verification":  {"invoice_cif_total_usd": 0.0},
        "invoice_totals": {"total_cif_usd": 0.0, "total_fob_usd": 0.0},
        "dhl_precheck":  {"invoice_cif_total_usd": 0.0, "fob_total_usd": 0.0},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None
    assert res["extraction_gap"]["first_failed_layer"] == "invoice_totals.cif_compute"


def test_unknown_gap_when_invoice_uploaded_but_not_parsed():
    audit = {"invoice_names": ["inv_122.pdf"]}
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None
    assert res["extraction_gap"]["first_failed_layer"] == "invoice_parse"


def test_ai_fallback_terminal_state_is_unknown_never_zero():
    """AI fallback invocation test (category 4): when every deterministic layer
    fails AND no AI value is wired in, the terminal fallback is UNKNOWN with an
    actionable gap — the resolver NEVER fabricates 0.0 as a last resort."""
    audit = {
        "invoice_names": ["inv_122.pdf"],
        # invoice parsed (totals dict present) but produced no usable CIF number,
        # and the AWB fallback is unreadable → terminal state must be UNKNOWN.
        "invoice_totals": {"total_cif_usd": 0.0, "line_count": 5},
        "awb_customs":   {"value_usd": None, "currency": "", "gap": "no_value_field"},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None      # the whole point: not 0.0
    assert res["cif_source"] == "unavailable"
    assert res["extraction_gap"]["first_failed_layer"] == "awb_customs.value_usd"


# ── AWB currency safety ───────────────────────────────────────────────────────

def test_non_usd_awb_is_not_auto_converted():
    """A non-USD AWB Custom Val must NOT be silently treated as USD — it counts
    as a gap, leaving the shipment UNKNOWN rather than mis-valued."""
    audit = {
        "invoice_names": ["inv.pdf"],
        "invoice_totals": {"total_cif_usd": 0.0, "line_count": 3},  # parsed, no CIF
        "awb_customs":   {"value_usd": 732.0, "currency": "EUR", "gap": None},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None
    assert res["extraction_gap"]["first_failed_layer"] == "awb_customs.value_usd"
    assert "EUR" in res["extraction_gap"]["reason"]


def test_awb_with_gap_flag_not_used():
    audit = {
        "invoice_names": ["inv.pdf"],
        "invoice_totals": {},
        "awb_customs":   {"value_usd": None, "currency": "USD", "gap": "label_no_value"},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_UNKNOWN
    assert res["cif_usd"] is None


# ── DECLARED_ZERO — only on an explicit signal ────────────────────────────────

def test_explicit_declared_zero_flag_is_honoured():
    audit = {"customs_declared_value_zero": True}
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_DECLARED_ZERO
    assert res["cif_usd"] == 0.0
    assert res["cif_source"] == "audit.customs_declared_value_zero"
    assert res["extraction_gap"] is None


def test_awb_explicit_zero_with_no_gap_is_declared_zero():
    audit = {"awb_customs": {"value_usd": 0.0, "currency": "USD", "gap": None}}
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_DECLARED_ZERO
    assert res["cif_usd"] == 0.0
    assert res["cif_source"] == "awb_customs.value_usd"


def test_declared_zero_does_not_fire_when_a_positive_layer_exists():
    """An explicit zero flag must not override a real positive invoice CIF."""
    audit = {
        "customs_declared_value_zero": True,
        "invoice_totals": {"total_cif_usd": 1500.0},
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(1500.0)


# ── Purity / robustness ───────────────────────────────────────────────────────

def test_resolver_never_raises_on_garbage():
    for bad in (None, {}, {"invoice_totals": {"total_cif_usd": "not-a-number"}},
                {"awb_customs": {"value_usd": "x", "currency": None, "gap": None}}):
        res = resolve_cif(bad)
        assert res["cif_state"] in (CIF_RESOLVED, CIF_DECLARED_ZERO, CIF_UNKNOWN)
        # UNKNOWN must always carry None, never a fabricated number.
        if res["cif_state"] == CIF_UNKNOWN:
            assert res["cif_usd"] is None


def test_attempts_trace_is_ordered_and_complete():
    res = resolve_cif({})
    layers = [a["layer"] for a in res["attempts"]]
    assert layers == [
        "verification.invoice_cif_total_usd",
        "invoice_totals.total_cif_usd",
        "invoice_totals.total_fob_usd",
        "dhl_precheck.invoice_cif_total_usd",
        "dhl_precheck.fob_total_usd",
        "awb_customs.value_usd",
    ]

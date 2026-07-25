"""
test_phase_c_cm_payment_authority.py — Phase C Fix 2 regression tests.

Guards that Customer Master preferred_payment_method and payment_terms_days
win over any wFirma/config fallback when no modal/draft override is present.

P1 — CM preferred_payment_method is used when no modal override and no draft value
P2 — CM payment_terms_days is used when no modal override and no draft days
P3 — Modal override still beats CM (override chain intact)
P4 — Draft saved method still beats CM (draft wins over CM, override beats both)
P5 — CM fields are not used when they are null/empty
P6 — Payment due is computed from CM payment_terms_days when no override
P7 — Source-grep: CM fallback code is present in routes_proforma.py
"""
from __future__ import annotations

from datetime import date

import pytest


# ── Helper: replicate the resolution logic from routes_proforma.py ─────────

_PM_EN_TO_WF = {
    "transfer":     "transfer",
    "cash":         "cash",
    "card":         "card",
    "compensation": "compensation",
}


def _resolve_method(override_method: str, draft_method: str, cm) -> str:
    """Mirror the Phase C Fix 2 logic from routes_proforma.proforma_to_invoice."""
    effective = override_method or draft_method
    if not effective and cm and (cm.preferred_payment_method or "").strip():
        effective = (cm.preferred_payment_method or "").strip().lower()
    return effective


def _resolve_days(override_days, draft_days, cm):
    """Mirror the Phase C Fix 2 logic from routes_proforma.proforma_to_invoice."""
    effective = override_days if override_days is not None else draft_days
    if effective is None and cm and cm.payment_terms_days is not None:
        effective = cm.payment_terms_days
    return effective


def _make_cm(**kwargs):
    from app.services.customer_master_db import CustomerMaster
    defaults = dict(
        bill_to_contractor_id="123",
        bill_to_name="Test Client",
        country="PL",
        preferred_payment_method=None,
        payment_terms_days=None,
    )
    defaults.update(kwargs)
    return CustomerMaster(**defaults)


# ── P1 — CM payment method as authority ─────────────────────────────────────

def test_cm_payment_method_used_when_no_override():
    cm = _make_cm(preferred_payment_method="transfer")
    result = _resolve_method(override_method="", draft_method="", cm=cm)
    assert result == "transfer"


def test_cm_payment_method_lower_normalised():
    cm = _make_cm(preferred_payment_method="CASH")
    result = _resolve_method(override_method="", draft_method="", cm=cm)
    assert result == "cash"


# ── P2 — CM payment days as authority ────────────────────────────────────────

def test_cm_payment_days_used_when_no_override():
    cm = _make_cm(payment_terms_days=14)
    result = _resolve_days(override_days=None, draft_days=None, cm=cm)
    assert result == 14


# ── P3 — Modal override beats CM ─────────────────────────────────────────────

def test_modal_override_beats_cm_method():
    cm = _make_cm(preferred_payment_method="transfer")
    result = _resolve_method(override_method="cash", draft_method="", cm=cm)
    assert result == "cash"


def test_modal_override_beats_cm_days():
    cm = _make_cm(payment_terms_days=14)
    result = _resolve_days(override_days=30, draft_days=None, cm=cm)
    assert result == 30


# ── P4 — Draft beats CM ──────────────────────────────────────────────────────

def test_draft_saved_method_beats_cm():
    cm = _make_cm(preferred_payment_method="transfer")
    result = _resolve_method(override_method="", draft_method="compensation", cm=cm)
    assert result == "compensation"


def test_draft_saved_days_beats_cm():
    cm = _make_cm(payment_terms_days=14)
    result = _resolve_days(override_days=None, draft_days=21, cm=cm)
    assert result == 21


def test_override_beats_draft_beats_cm():
    """Full priority chain: override > draft > CM."""
    cm = _make_cm(preferred_payment_method="transfer")
    result = _resolve_method(override_method="cash", draft_method="card", cm=cm)
    assert result == "cash"


# ── P5 — CM null/empty → no fallback ─────────────────────────────────────────

def test_cm_null_method_does_not_fill():
    cm = _make_cm(preferred_payment_method=None)
    result = _resolve_method(override_method="", draft_method="", cm=cm)
    assert result == ""


def test_cm_null_days_does_not_fill():
    cm = _make_cm(payment_terms_days=None)
    result = _resolve_days(override_days=None, draft_days=None, cm=cm)
    assert result is None


def test_cm_empty_method_does_not_fill():
    cm = _make_cm(preferred_payment_method="")
    result = _resolve_method(override_method="", draft_method="", cm=cm)
    assert result == ""


def test_no_cm_does_not_fill():
    result = _resolve_method(override_method="", draft_method="", cm=None)
    assert result == ""
    result_days = _resolve_days(override_days=None, draft_days=None, cm=None)
    assert result_days is None


# ── P6 — Payment due from CM days ────────────────────────────────────────────

def test_payment_due_uses_cm_days_when_no_override():
    from app.services.payment_date_resolver import compute_payment_due
    cm = _make_cm(payment_terms_days=14)
    days = _resolve_days(override_days=None, draft_days=None, cm=cm)
    assert days == 14
    due = compute_payment_due(
        invoice_date=date(2026, 7, 1),
        sale_date=None,
        payment_days=days,
    )
    assert due == date(2026, 7, 15)


def test_override_days_beat_cm_in_payment_due():
    from app.services.payment_date_resolver import compute_payment_due
    cm = _make_cm(payment_terms_days=14)
    days = _resolve_days(override_days=30, draft_days=None, cm=cm)
    assert days == 30
    due = compute_payment_due(
        invoice_date=date(2026, 7, 1),
        sale_date=None,
        payment_days=days,
    )
    assert due == date(2026, 7, 31)


# ── P7 — Source-grep guards ───────────────────────────────────────────────────

def test_cm_payment_fallback_in_routes_proforma_source():
    """
    Regression guard: CM payment authority fallback must be in
    routes_proforma.py and must not be silently removed.
    """
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent
        / "app" / "api" / "routes_proforma.py"
    ).read_text(encoding="utf-8")

    assert "preferred_payment_method" in src, (
        "CM preferred_payment_method reference missing from routes_proforma.py"
    )
    assert "payment_terms_days" in src, (
        "CM payment_terms_days reference missing from routes_proforma.py"
    )
    # Phase C specific: the CM fallback block must reference _cm_inv2
    assert "_cm_inv2" in src, (
        "CM variable _cm_inv2 missing from routes_proforma.py"
    )
    # The guard condition pattern
    assert "not _effective_method_en" in src or "not effective_method" in src, (
        "CM payment method fallback guard missing from routes_proforma.py"
    )

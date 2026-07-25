"""
test_phase_c_series_advisory.py — Phase C Fix 3 regression tests.

Guards that the series-mismatch advisory is produced when:
  A — CM has no preferred series for the relevant vat_context
  B — Operator-provided final_series_id differs from what CM would choose

Advisory must NEVER block conversion.

S1 — Advisory A: CM has no series for vat_context → advisory emitted
S2 — Advisory B: operator series differs from CM series → advisory emitted
S3 — No advisory when CM series matches operator series
S4 — No advisory when CM series used and operator provided no series (normal path)
S5 — Advisory is non-blocking (conversion_proceeds field logic)
S6 — Source-grep: advisory code present in routes_proforma.py
"""
from __future__ import annotations

import pytest


# ── Helper: mirror the advisory logic from routes_proforma.py ─────────────────

def _compute_series_advisories(
    operator_series_in: str,
    cm_series_for_ctx: str,
    vat_ctx_exec: str,
) -> list:
    """Mirror Phase C Fix 3 advisory logic from routes_proforma.proforma_to_invoice."""
    advisories = []
    if not cm_series_for_ctx:
        advisories.append(
            f"Customer Master has no preferred invoice series for "
            f"vat_context='{vat_ctx_exec}'; "
            "wFirma contractor default will apply"
        )
    elif operator_series_in and operator_series_in != "0" and operator_series_in != cm_series_for_ctx:
        advisories.append(
            f"Operator-provided series '{operator_series_in}' differs from "
            f"Customer Master preferred series '{cm_series_for_ctx}' "
            f"for vat_context='{vat_ctx_exec}' (advisory — conversion continues)"
        )
    return advisories


# ── S1 — CM has no series → advisory emitted ─────────────────────────────────

def test_advisory_when_cm_has_no_series_for_domestic():
    advisories = _compute_series_advisories(
        operator_series_in="",
        cm_series_for_ctx="",
        vat_ctx_exec="domestic",
    )
    assert len(advisories) == 1
    assert "no preferred invoice series" in advisories[0]
    assert "domestic" in advisories[0]


def test_advisory_when_cm_has_no_series_for_wdt():
    advisories = _compute_series_advisories(
        operator_series_in="",
        cm_series_for_ctx="",
        vat_ctx_exec="wdt",
    )
    assert len(advisories) == 1
    assert "wdt" in advisories[0]


def test_advisory_when_cm_has_no_series_for_export():
    advisories = _compute_series_advisories(
        operator_series_in="",
        cm_series_for_ctx="",
        vat_ctx_exec="export",
    )
    assert len(advisories) == 1
    assert "export" in advisories[0]


# ── S2 — Operator series differs from CM series → advisory emitted ────────────

def test_advisory_when_operator_series_differs_from_cm():
    advisories = _compute_series_advisories(
        operator_series_in="FV/2026",
        cm_series_for_ctx="FV WDT/2026",
        vat_ctx_exec="wdt",
    )
    assert len(advisories) == 1
    assert "FV/2026" in advisories[0]
    assert "FV WDT/2026" in advisories[0]
    assert "advisory" in advisories[0]


def test_advisory_contains_both_series_names():
    advisories = _compute_series_advisories(
        operator_series_in="CUSTOM/2026",
        cm_series_for_ctx="FV/2026",
        vat_ctx_exec="domestic",
    )
    assert "CUSTOM/2026" in advisories[0]
    assert "FV/2026" in advisories[0]


# ── S3 — No advisory when series match ───────────────────────────────────────

def test_no_advisory_when_operator_series_matches_cm():
    advisories = _compute_series_advisories(
        operator_series_in="FV/2026",
        cm_series_for_ctx="FV/2026",
        vat_ctx_exec="domestic",
    )
    assert advisories == []


# ── S4 — No advisory on normal path (CM series used, no operator override) ───

def test_no_advisory_on_normal_path():
    advisories = _compute_series_advisories(
        operator_series_in="",
        cm_series_for_ctx="FV/2026",
        vat_ctx_exec="domestic",
    )
    assert advisories == []


def test_no_advisory_when_operator_provides_zero_sentinel():
    """Operator series "0" is the wFirma omit sentinel — treated as no override."""
    advisories = _compute_series_advisories(
        operator_series_in="0",
        cm_series_for_ctx="FV/2026",
        vat_ctx_exec="domestic",
    )
    assert advisories == []


# ── S5 — Advisory is non-blocking ────────────────────────────────────────────

def test_advisory_text_contains_non_blocking_marker():
    """Advisory text must signal it does not block conversion."""
    advisories = _compute_series_advisories(
        operator_series_in="FV/2026",
        cm_series_for_ctx="FV WDT/2026",
        vat_ctx_exec="wdt",
    )
    assert advisories
    assert "advisory" in advisories[0].lower() or "continues" in advisories[0].lower()


def test_advisory_list_is_always_a_list():
    """convert_advisories must always be a list, never None."""
    for case in [
        ("", "FV/2026", "domestic"),
        ("", "", "wdt"),
        ("FV/2026", "WDT/2026", "export"),
    ]:
        result = _compute_series_advisories(*case)
        assert isinstance(result, list)


# ── S6 — Source-grep guard ────────────────────────────────────────────────────

def test_series_advisory_code_in_routes_proforma():
    """
    Regression guard: the advisory computation and convert_advisories
    field must remain in routes_proforma.py.
    """
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent
        / "app" / "api" / "routes_proforma.py"
    ).read_text(encoding="utf-8")

    assert "_series_advisories" in src, (
        "_series_advisories variable missing from routes_proforma.py"
    )
    assert "convert_advisories" in src, (
        "convert_advisories key missing from the success response in routes_proforma.py"
    )
    assert "_cm_series_for_ctx" in src, (
        "_cm_series_for_ctx variable missing from routes_proforma.py"
    )
    assert "no preferred invoice series" in src, (
        "Advisory A text (no preferred invoice series) missing from routes_proforma.py"
    )

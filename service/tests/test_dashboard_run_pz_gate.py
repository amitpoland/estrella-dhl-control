"""
test_dashboard_run_pz_gate.py — Run PZ button SAD decision gate.

Tests:
  1. test_run_pz_button_present              — button exists in source
  2. test_run_pz_disabled_when_blocked       — canRunPZ / runPzDisabled logic present
  3. test_run_pz_enabled_when_safe           — safe_to_run_pz === true path present
  4. test_run_pz_disabled_when_no_decision   — fallback: no decision → canRunPZ true
  5. test_run_pz_sad_validation_label        — blocked label "SAD validation failed"
  6. test_run_pz_sad_title_attribute         — title set to reason string
  7. test_run_pz_opacity_hint_present        — muted style present for blocked state
  8. test_run_pz_onclick_unchanged           — API call unchanged (/process endpoint)
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


def _btn_region() -> str:
    """Extract the region around the Run PZ button for targeted assertions."""
    src = _src()
    idx = src.find("canRunPZ")
    assert idx != -1, "canRunPZ not found in dashboard.html"
    return src[max(0, idx - 100): idx + 2400]


# ── 1. Button present ─────────────────────────────────────────────────────────

def test_run_pz_button_present():
    assert "Run PZ" in _src(), "Run PZ button missing from dashboard.html"


# ── 2. Blocked path: disabled when canRunPZ is false ─────────────────────────

def test_run_pz_disabled_when_blocked():
    region = _btn_region()
    assert "runPzDisabled" in region, (
        "runPzDisabled variable not found near Run PZ button"
    )
    assert "!canRunPZ" in region, (
        "!canRunPZ must be part of the disabled condition"
    )


# ── 3. Enabled path: canRunPZ true when safe_to_run_pz === true ──────────────

def test_run_pz_enabled_when_safe():
    region = _btn_region()
    assert "safe_to_run_pz === true" in region, (
        "safe_to_run_pz === true condition missing from canRunPZ logic"
    )


# ── 4. No decision → canRunPZ defaults to true (no false fallback) ────────────

def test_run_pz_disabled_when_no_decision():
    region = _btn_region()
    # When no decision: sadDecisionPresent is false → canRunPZ = !false = true
    # Verify the guard is sadDecisionPresent (not a hard false default)
    assert "sadDecisionPresent" in region, (
        "sadDecisionPresent guard missing — absence of decision must default to enabled"
    )
    assert "!sadDecisionPresent || sadDecision.safe_to_run_pz === true" in region, (
        "canRunPZ must be true when no decision is present"
    )


# ── 5. SAD blocked label in button text ──────────────────────────────────────

def test_run_pz_sad_validation_label():
    region = _btn_region()
    assert "SAD validation failed" in region, (
        "'SAD validation failed' label missing from Run PZ button text"
    )


# ── 6. Title attribute carries the reason ────────────────────────────────────

def test_run_pz_sad_title_attribute():
    region = _btn_region()
    assert "SAD validation:" in region, (
        "title attribute must contain 'SAD validation:' when blocked by decision"
    )
    assert "sadBlockReason" in region, (
        "sadBlockReason must be included in the title"
    )


# ── 7. Opacity hint for SAD-blocked state ────────────────────────────────────

def test_run_pz_opacity_hint_present():
    region = _btn_region()
    assert "opacity" in region, (
        "opacity style hint missing — SAD-blocked button must be visually muted"
    )


# ── 8. API call endpoint unchanged ───────────────────────────────────────────

def test_run_pz_onclick_unchanged():
    region = _btn_region()
    assert "/api/v1/upload/shipment/" in region, (
        "Run PZ API endpoint must not be changed by the gate logic"
    )
    assert "/process" in region, (
        "/process endpoint must remain in the onClick handler"
    )


# ── 9–11. SAD validation block error message ──────────────────────────────────

def _onclick_region() -> str:
    """Extract the onClick handler body for the Run PZ button."""
    src = _src()
    idx = src.find("sad_validation_blocked")
    assert idx != -1, "sad_validation_blocked check missing from Run PZ onClick handler"
    return src[max(0, idx - 300): idx + 600]


def test_run_pz_shows_sad_validation_block_reason():
    region = _onclick_region()
    assert "SAD validation blocked PZ run:" in region, (
        "SAD block toast message must start with 'SAD validation blocked PZ run:'"
    )
    assert "body.reason" in region, (
        "body.reason must be included in the SAD block error message"
    )


def test_run_pz_shows_mrn_values_on_block():
    region = _onclick_region()
    assert "body.mrn_parsed" in region, (
        "body.mrn_parsed must be appended to the SAD block error message"
    )
    assert "body.mrn_declared" in region, (
        "body.mrn_declared must be appended to the SAD block error message"
    )
    assert "Parsed MRN:" in region, (
        "'Parsed MRN:' label missing from SAD block error message"
    )
    assert "Declared MRN:" in region, (
        "'Declared MRN:' label missing from SAD block error message"
    )


def test_run_pz_generic_error_unchanged():
    """Non-SAD 409 and other HTTP errors still use the generic path."""
    src = _src()
    # The handler must still have a generic HTTP error throw for non-SAD failures
    idx = src.find("sad_validation_blocked")
    assert idx != -1
    region = src[max(0, idx - 300): idx + 800]
    assert "HTTP ${res.status}" in region or "HTTP 409" in region, (
        "Generic HTTP error throw must remain for non-SAD-blocked failures"
    )
    assert "!res.ok" in region, (
        "Generic !res.ok guard must remain for non-409 HTTP failures"
    )

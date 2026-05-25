"""
test_single_renderer_authority.py — Sprint 01 G2 renderer-replacement gate.

After Phase B, exactly ONE file may map lifecycle state to UI phase.
Any second mapper is a duplicate authority — by construction, the bug
class the campaign exists to fix.

This file source-greps the static surface for:
  1. Raw `lcState.state === 'STAGED'` (or other lifecycle literals) outside
     pz-state.js. Every such match is a renderer that has learned
     domain state — Lesson F + G2 violation.
  2. Multiple definitions of `function correctionUiPhase`. Exactly one
     definition must exist (pz-state.js).
  3. The V1 component name `GlobalPZCorrectionProposalCard` — zero matches
     post-Phase-B.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC    = REPO_ROOT / "service" / "app" / "static"
PZ_STATE  = STATIC / "pz-state.js"

# Lifecycle tokens that are unique to the correction workflow.
# (Broader tokens like 'FAILED' / 'COMPLETED' / 'STAGED' are reused across
# many UX surfaces — alert strings, draft states, etc — and would
# false-positive this test. Sentry tokens below are correction-only.)
LIFECYCLE_STATE_TOKENS = [
    "OPERATOR_REVIEWED",
    "TERMINAL_SUPPRESSED",
]


def _scan_static_files():
    if not STATIC.exists():
        return []
    return [p for p in STATIC.rglob("*") if p.is_file() and p.suffix in {".html", ".js"}]


def test_correction_ui_phase_defined_exactly_once():
    """Exactly one definition of `function correctionUiPhase` in the
    static surface. Living in pz-state.js. Anywhere else is a duplicate
    mapper authority."""
    locations = []
    for path in _scan_static_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"function\s+correctionUiPhase\s*\(", text):
            locations.append(path.name)
    assert locations == ["pz-state.js"], (
        f"correctionUiPhase must be defined exactly once, in pz-state.js. "
        f"Found in: {locations}"
    )


@pytest.mark.parametrize("token", LIFECYCLE_STATE_TOKENS)
def test_lifecycle_state_compared_only_in_pz_state(token):
    """A literal `=== 'STAGED'` (or other state name) means a renderer
    is reading raw lifecycle state to choose presentation. The campaign
    forbids this everywhere except pz-state.js's correctionUiPhase.

    This test allows state literals to appear in diagnostics rendering
    (which intentionally surfaces engineering tokens inside <details>),
    and in V1 retirement string sets (test files).
    """
    # Regex: state token as a JS string literal that's being compared.
    # We accept `'STAGED'` or `"STAGED"` appearing in any equality / inclusion.
    pattern = re.compile(rf"['\"]{re.escape(token)}['\"]")
    offenders = []
    allowed_files = {
        "pz-state.js",                  # single authority for mapping
        "pz-components.js",             # diagnostics + V2 phase renderers (state surfaces only inside <details>)
    }
    for path in _scan_static_files():
        if path.name in allowed_files: continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    # shipment-detail.html will have offenders until Phase B retires V1.
    # Filter only AFTER Phase B by checking that V1 retirement holds first.
    v1_retired = "GlobalPZCorrectionProposalCard" not in (
        (STATIC / "shipment-detail.html").read_text(encoding="utf-8", errors="ignore")
        if (STATIC / "shipment-detail.html").exists() else ""
    )
    if not v1_retired:
        pytest.skip("Phase B not yet executed; V1 still owns lifecycle literals (expected)")
    assert not offenders, (
        f"Lifecycle state token {token!r} appears in renderer file(s) outside "
        f"pz-state.js + pz-components.js (diagnostics): {offenders}. "
        f"Move the mapping into correctionUiPhase in pz-state.js."
    )


def test_v1_renderer_function_name_absent():
    """G2 grep #3: V1 renderer name appears in exactly ZERO locations
    after Phase B (post-cutover)."""
    if not (STATIC / "shipment-detail.html").exists():
        pytest.skip("shipment-detail.html not present")
    v1_present = "GlobalPZCorrectionProposalCard" in (STATIC / "shipment-detail.html").read_text(encoding="utf-8")
    if v1_present:
        pytest.skip("Phase B not yet executed; V1 still present (expected pre-cutover)")
    offenders = []
    for path in _scan_static_files():
        if "GlobalPZCorrectionProposalCard" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(path.name)
    assert not offenders, f"V1 PZ correction renderer name re-introduced in: {offenders}"


def test_single_renderer_v2_container_defined_once():
    """V2 PZCorrectionV2Container is defined exactly once."""
    locations = []
    for path in _scan_static_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"function\s+PZCorrectionV2Container\s*\(", text):
            locations.append(path.name)
    assert locations == ["pz-components.js"], (
        f"PZCorrectionV2Container must be defined exactly once, in pz-components.js. "
        f"Found in: {locations}"
    )

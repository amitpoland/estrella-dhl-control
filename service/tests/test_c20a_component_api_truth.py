"""tests/test_c20a_component_api_truth.py — C20A

Component API Truth: fixes 3 silent production bugs in dashboard-shared.js
and missing CSS tokens in both HTML files.

Bug 1: Btn variant="primary" had no entry in variants map — fell back to
        `default` (dark navy). 27 critical action buttons showed wrong color.
        Fix: added `primary` variant aliasing gold/accent.

Bug 2: Badge label={...} prop was ignored — rendered "Unknown" for all 8
        cells in the missing-functions-matrix in both pages.
        Fix: Badge now renders `label || status` and uses it for STATUS_MAP lookup.

Bug 3: --surface-1 and --surface-2 CSS custom properties referenced in JSX
        inline styles but not defined in either page's :root or [data-theme="dark"].
        Fix: added aliases `var(--bg-subtle)` to both pages (light + dark).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_SHARED = (_ROOT / "service" / "app" / "static" / "dashboard-shared.js").read_text(encoding="utf-8")
_DETAIL = (_ROOT / "service" / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
_DASH   = (_ROOT / "service" / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")


# ── Bug 1: Btn primary variant ────────────────────────────────────────────────

def test_btn_has_primary_variant():
    """C20A: Btn must have a `primary` variant so 27 CTA buttons render gold."""
    assert "primary:" in _SHARED, \
        "Btn variants map must include `primary:` entry"

def test_btn_primary_variant_is_accent_style():
    """C20A: Btn primary variant must use --accent (gold) background."""
    # Find the primary: line and verify it uses --accent
    idx = _SHARED.index("primary:")
    ctx = _SHARED[idx: idx + 120]
    assert "var(--accent)" in ctx, \
        "Btn primary variant must use var(--accent) as background"

def test_btn_primary_not_same_as_default():
    """C20A: Btn primary must differ from default (dark navy) — not a no-op alias."""
    idx_primary = _SHARED.index("primary:")
    idx_default = _SHARED.index("default:")
    primary_ctx = _SHARED[idx_primary: idx_primary + 120]
    default_ctx = _SHARED[idx_default: idx_default + 120]
    assert primary_ctx != default_ctx, \
        "Btn primary and default variants must have different styles"

def test_btn_gold_variant_still_present():
    """C20A regression: gold variant must still exist for existing gold callers."""
    assert "gold:" in _SHARED, \
        "Btn gold variant must not be removed — existing code uses it"

def test_btn_forwards_rest_props():
    """C20A: Btn must forward ...rest so data-testid reaches the <button>."""
    assert "...rest" in _SHARED, \
        "Btn must destructure ...rest and spread it onto <button>"


# ── Bug 2: Badge label prop ───────────────────────────────────────────────────

def test_badge_accepts_label_prop():
    """C20A: Badge must accept `label` prop in its signature."""
    # Look for Badge function definition with label
    idx = _SHARED.index("function Badge(")
    ctx = _SHARED[idx: idx + 120]
    assert "label" in ctx, \
        "Badge function signature must include `label` prop"

def test_badge_renders_label_text():
    """C20A: Badge must render label text when label prop is provided."""
    # The display text expression must use label
    idx = _SHARED.index("function Badge(")
    end = _SHARED.index("function Card(", idx)
    badge_src = _SHARED[idx:end]
    assert "label ||" in badge_src or "|| label" in badge_src or "displayText" in badge_src, \
        "Badge must use label prop as display text (not just status)"

def test_badge_display_text_uses_label_or_status():
    """C20A: Badge must derive displayText = label || status || 'Unknown'."""
    assert "displayText" in _SHARED, \
        "Badge must define displayText variable combining label and status"
    idx = _SHARED.index("displayText")
    ctx = _SHARED[idx: idx + 80]
    assert "label" in ctx and "status" in ctx, \
        "displayText must reference both label and status"

def test_badge_does_not_hardcode_unknown():
    """C20A: Badge must not unconditionally render 'Unknown' — label renders its value."""
    # Old code: `{status || 'Unknown'}` — new code uses displayText
    idx = _SHARED.index("function Badge(")
    end = _SHARED.index("function Card(", idx)
    badge_src = _SHARED[idx:end]
    # The rendered text should be {displayText}, not {status || 'Unknown'}
    assert "{status || 'Unknown'}" not in badge_src, \
        "Badge must render displayText (label||status||Unknown), not {status || 'Unknown'}"
    assert "{displayText}" in badge_src, \
        "Badge must render {displayText}"

def test_badge_status_lookup_still_works():
    """C20A regression: Badge STATUS_MAP lookup must still work for status prop."""
    assert "STATUS_MAP[displayText]" in _SHARED or "STATUS_MAP[status]" in _SHARED, \
        "Badge must still use STATUS_MAP for color lookup"


# ── Bug 3: --surface-1 / --surface-2 tokens ──────────────────────────────────

def test_shipment_detail_has_surface_1_light():
    """C20A: shipment-detail.html :root must define --surface-1."""
    # Must appear BEFORE [data-theme="dark"]
    light_end = _DETAIL.index('[data-theme="dark"]')
    light_css = _DETAIL[:light_end]
    assert "--surface-1:" in light_css, \
        "shipment-detail.html :root must define --surface-1"

def test_shipment_detail_has_surface_2_light():
    """C20A: shipment-detail.html :root must define --surface-2."""
    light_end = _DETAIL.index('[data-theme="dark"]')
    light_css = _DETAIL[:light_end]
    assert "--surface-2:" in light_css, \
        "shipment-detail.html :root must define --surface-2"

def test_shipment_detail_has_surface_tokens_dark():
    """C20A: shipment-detail.html [data-theme=dark] must define surface tokens."""
    dark_start = _DETAIL.index('[data-theme="dark"]')
    # Dark block ends at </style> — search from dark_start to that marker
    style_end = _DETAIL.index("</style>", dark_start)
    dark_css = _DETAIL[dark_start: style_end]
    assert "--surface-1:" in dark_css, \
        "shipment-detail.html dark mode must define --surface-1"
    assert "--surface-2:" in dark_css, \
        "shipment-detail.html dark mode must define --surface-2"

def test_dashboard_has_surface_1_light():
    """C20A: dashboard.html :root must define --surface-1."""
    light_end = _DASH.index('[data-theme="dark"]')
    light_css = _DASH[:light_end]
    assert "--surface-1:" in light_css, \
        "dashboard.html :root must define --surface-1"

def test_dashboard_has_surface_2_light():
    """C20A: dashboard.html :root must define --surface-2."""
    light_end = _DASH.index('[data-theme="dark"]')
    light_css = _DASH[:light_end]
    assert "--surface-2:" in light_css, \
        "dashboard.html :root must define --surface-2"

def test_dashboard_has_surface_tokens_dark():
    """C20A: dashboard.html [data-theme=dark] must define surface tokens."""
    dark_start = _DASH.index('[data-theme="dark"]')
    dark_css = _DASH[dark_start: dark_start + 1500]
    assert "--surface-1:" in dark_css, \
        "dashboard.html dark mode must define --surface-1"
    assert "--surface-2:" in dark_css, \
        "dashboard.html dark mode must define --surface-2"

def test_surface_tokens_alias_bg_subtle():
    """C20A: surface tokens must alias --bg-subtle (not hardcode hex)."""
    assert "var(--bg-subtle)" in _DETAIL, \
        "--surface tokens must use var(--bg-subtle) alias, not hardcoded hex"
    assert "var(--bg-subtle)" in _DASH, \
        "--surface tokens must use var(--bg-subtle) alias in dashboard.html"


# ── Regression guards (C14A–C19A markers) ────────────────────────────────────

def test_btn_variants_still_include_outline():
    """C20A regression: outline variant must still be present."""
    assert "outline:" in _SHARED

def test_btn_variants_still_include_ghost():
    """C20A regression: ghost variant must still be present."""
    assert "ghost:" in _SHARED

def test_btn_variants_still_include_danger():
    """C20A regression: danger variant must still be present."""
    assert "danger:" in _SHARED

def test_shared_exports_badge_btn_card():
    """C20A regression: window.EstrellaShared must still export Badge, Btn, Card."""
    assert "Badge" in _SHARED
    assert "Btn" in _SHARED
    assert "Card" in _SHARED

def test_c19a_intelligence_panel_absent():
    """C20A regression: C19A deletion must still hold — no intelligence panel."""
    assert 'data-testid="draft-intelligence-panel"' not in _DETAIL

def test_c18a_ship_to_postal_code_present():
    """C20A regression: C18A postal_code fix must still hold."""
    assert "c.ship_to_postal_code" in _DETAIL

def test_c17a_workflow_cm_card_present():
    """C20A regression: C17A customer master cards must still be present."""
    assert "workflow-cm-card-" in _DETAIL

def test_c16a_is_transit_fix_present():
    """C20A regression: C16A isTransit fix must still be present."""
    assert "isTransit ? 'In transit' : (r.current_location" in _DETAIL

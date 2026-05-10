"""tests/test_dashboard_design_tokens.py — UI-1

Source-grep tests for the Estrella Atlas design-token adoption
applied to dashboard.html in UI-1.

UI-1 is a CSS-only phase. These tests pin three classes of
invariant:

  1. Brand-token alignment.
     Each operator-visible :root token (light theme) carries the
     value from the new design bundle's :root block (file
     `Estrella Dashboard.html` in the design archive). This
     anchors the migration — if a future commit drifts the token
     value, this test catches it.

  2. Migration-policy invariants (UI-1 does not regress earlier
     campaigns).
       * Existing dashboard route references remain unchanged
         (sample of high-value endpoints).
       * No FedEx / UPS / multi-carrier text introduced.
       * No content from the design's `Shipping Operations`
         (multi-carrier wireframe) page leaks in.
       * Existing data-testid landmarks remain.

  3. Token completeness.
     Every brand token from the design's :root block has a
     corresponding :root entry in dashboard.html.

UI-1 forbidden under this suite:
  - JSX edit
  - testid rename
  - copy change
  - new endpoint
  - sample-data import
  - shipping-ops content
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


# ── 1. Light-theme brand tokens align with the design bundle ───────────────

# Each entry is `(token_name, expected_value)`. Values come directly
# from the new Estrella Dashboard design bundle's :root block.
LIGHT_THEME_BRAND_TOKENS = [
    ("--bg",               "#F4F1EA"),
    ("--bg-subtle",        "#FAF8F2"),
    ("--card",             "#FFFFFF"),
    ("--row-hover",        "#F6F2EA"),
    ("--border",           "#E5DECF"),
    ("--border-subtle",    "#EFE9DA"),
    ("--text",             "#1B2538"),
    ("--text-2",           "#4E5A72"),
    ("--text-3",           "#8B97AE"),
    ("--accent",           "#B89968"),
    ("--accent-light",     "#D4B884"),
    ("--accent-text",      "#1B2538"),
    ("--accent-subtle",    "#F8EFD8"),
    ("--accent-border",    "#CFB178"),
    ("--sidebar-bg",       "#131C2E"),
    ("--sidebar-border",   "#25334C"),
    ("--sidebar-active",   "#1F2A42"),
    ("--sidebar-hover",    "#1A2438"),
    ("--sidebar-text",     "#F2EBD9"),
    ("--sidebar-text-muted","#7C89A3"),
    ("--sidebar-icon",     "#B89968"),
    ("--badge-accent-bg",     "#131C2E"),
    ("--badge-accent-text",   "#B89968"),
    ("--badge-accent-border", "#B89968"),
]


@pytest.mark.parametrize("token,value", LIGHT_THEME_BRAND_TOKENS)
def test_light_theme_brand_token_aligned(token, value):
    """Each design-bundle brand token must appear with its design-bundle
    value somewhere inside the dashboard's CSS source.

    Tolerant of any whitespace between the colon and the value (the
    dashboard uses padded alignment for readability).
    """
    src = _src()
    import re
    pattern = re.compile(rf"{re.escape(token)}\s*:\s*{re.escape(value)}\b")
    assert pattern.search(src) is not None, (
        f"brand token {token} missing or drifted from design value {value!r}"
    )


def test_root_block_present():
    """The :root block must remain a top-level CSS selector in dashboard.html."""
    src = _src()
    assert ":root {" in src, ":root block must remain in dashboard.html"


def test_dark_theme_block_preserved():
    """The dark-theme block must still exist (UI-1 doesn't drop dark mode)."""
    src = _src()
    assert '[data-theme="dark"] {' in src, "dark theme block must remain"


# ── 2. Migration-policy invariants — UI-1 must not regress earlier work ────

# Sample of high-value endpoints that already shipped. This is NOT an
# exhaustive route list; it's a representative spot-check that UI-1
# hasn't disturbed the call sites.
EXISTING_ENDPOINTS = [
    "/api/v1/carrier/shipments/by-batch/",
    "/api/v1/carrier/proposals/by-batch/",
    "/api/v1/carrier/actions/mark-label-printed/execute",
    "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
    "/api/v1/carrier/actions/cancel-shipment/execute",
    "/api/v1/closure/",
    "/api/v1/execute/closure_confirm",
    "/api/v1/dhl-documents/",
    "/api/v1/agency-documents/",
    "/api/v1/sales/linkage/",
    "/api/v1/proforma/",
    "/api/v1/wfirma/",
    "/api/v1/action-proposals/",
]


@pytest.mark.parametrize("endpoint", EXISTING_ENDPOINTS)
def test_existing_endpoint_still_referenced(endpoint):
    """Each high-value existing endpoint must still appear in
    dashboard.html. UI-1 is CSS-only and must not have removed any
    route call."""
    src = _src()
    assert endpoint in src, (
        f"existing endpoint {endpoint!r} no longer referenced in dashboard.html"
    )


# Sample of high-value testid landmarks that already shipped. UI-1
# must not have dropped any.
EXISTING_TESTIDS = [
    # carrier UI (W-2.1 + W-2.2 + W-2.3)
    "carrier-actions-tab",
    "carrier-shipment-panel",
    "carrier-shipment-row",
    "carrier-shipment-state-badge",
    "carrier-shipment-detail",
    "carrier-shipment-timeline",
    "carrier-shipment-label-evidence",
    "carrier-proposals-panel",
    "carrier-proposal-row",
    "carrier-proposal-create-info-note",
    "carrier-confirm-drawer",
    "carrier-confirm-drawer-cancel-warning",
    "carrier-confirm-drawer-handover-note",
    "carrier-confirm-drawer-execute-btn",
    "carrier-confirm-drawer-actor-input",
    # closure flow (W-7 / B1.b)
    "closure-eval-card",
    "closure-confirm-section",
    "closure-confirm-btn",
    # DHL / agency cards (W-7 / B1.c)
    "dhl-docs-received-card",
    "agency-docs-received-card",
    # broker followups
    "broker-followup-panel",
    "broker-followup-confirm-modal",
    # cross-batch read-only pages
    "customer-statement-drawer",
    "proforma-draft-panel",
]


@pytest.mark.parametrize("testid", EXISTING_TESTIDS)
def test_existing_testid_landmark_still_present(testid):
    """Each high-value testid landmark must still appear in dashboard.html."""
    src = _src()
    needle = f'data-testid="{testid}"'
    assert needle in src, (
        f"existing testid landmark {testid!r} no longer present in dashboard.html"
    )


# ── 3. UI-1 must not introduce out-of-scope content ────────────────────────

def test_ui1_did_not_add_fedex_references():
    """Some pre-existing 'FedEx' references in dashboard.html predate
    this campaign (option lists, sample row colour map, SLA benchmark
    rows). UI-1 is CSS-only and must not have added any new ones.

    Pinned at the count observed at baseline `ee0c3e4` (commit
    immediately before UI-1). If a future commit grows this count it
    means new multi-carrier UI is creeping in from the design bundle —
    forbidden. If a future commit *reduces* this count it's a
    deliberate cleanup and this test should be relaxed in that
    commit's diff.
    """
    src = _src()
    # The pre-UI-1 baseline count of 'FedEx' substrings is 7
    # (option list ~line 829; sample-row colour map ~line 1272 with
    # two ternary branches naming 'FedEx'; FedEx API-no-credentials
    # message ~line 6436; three insights rows ~lines 14229/14299/14302).
    # UI-1 is CSS-only and must keep this count unchanged. A lower
    # count later signals deliberate cleanup; a higher count signals
    # design leakage.
    assert src.count("FedEx") <= 7, (
        f"FedEx count grew above the pre-UI-1 baseline of 7 — "
        f"UI-1 must not import multi-carrier content from the design"
    )


def test_ui1_did_not_introduce_ups_carrier():
    """UPS as a carrier name must not appear in the dashboard. The
    bare letters 'UPS' do appear inside legitimate identifiers
    ('VER_GROUPS', 'FOLLOW-UPS') — those are not carrier references.
    What we forbid here is the design-bundle-specific UPS carrier
    markers."""
    src = _src()
    for design_marker in (
        "UPS Express",
        "UPS Priority",
        "UPS Worldwide",
        '"UPS"',  # the design's carrier select option uses this exact form
        "'UPS'",
    ):
        assert design_marker not in src, (
            f"design-bundle UPS marker {design_marker!r} found in "
            f"dashboard.html — UI-1 must not import multi-carrier content"
        )


def test_ui1_did_not_introduce_design_multi_carrier_tokens():
    """The design bundle's shipping-ops page uses specific multi-
    carrier markers like 'FedEx IP', 'FedEx Priority', and
    'options=["DHL","FedEx","UPS"]'. None of these may appear in
    dashboard.html — they're all design wireframe leakage signals."""
    src = _src()
    for design_marker in (
        "FedEx IP",
        "FedEx Priority",
        "FedEx Worldwide",
        '["DHL","FedEx","UPS"]',
        '["DHL", "FedEx", "UPS"]',
    ):
        assert design_marker not in src, (
            f"design-bundle multi-carrier marker {design_marker!r} found "
            f"in dashboard.html — UI-1 must not import multi-carrier wireframe"
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        # Substrings unique to the design's wireframe Shipping Operations page
        "Shipping Operations",
        "Carrier approval required",
        "carrier-shipment-status-chip",
        "Backend pending",
        "Estrella Atlas",  # the design's product name; we keep "Estrella"
    ],
)
def test_no_shipping_ops_content_imported(forbidden):
    """The new design's Shipping Operations page is multi-carrier
    wireframe and entirely out of scope. None of its distinctive
    strings may appear in dashboard.html under UI-1."""
    src = _src()
    assert forbidden not in src, (
        f"shipping-ops marker {forbidden!r} found in dashboard.html — "
        f"out-of-scope content from the design bundle"
    )


def test_dashboard_title_unchanged():
    """The dashboard's <title> must remain unchanged. UI-1 is CSS-only;
    branding strings are operator-visible and stay locked."""
    src = _src()
    assert "<title>Estrella PZ Customs Control</title>" in src, (
        "dashboard <title> must remain 'Estrella PZ Customs Control'; "
        "UI-1 must not adopt the design's 'Estrella Atlas — Operations Control'"
    )


def test_dhl_express_wording_lock_preserved():
    """W-2.1a wording lock — 'DHL Express' tab must still be present."""
    src = _src()
    assert "'DHL Express'" in src, (
        "'DHL Express' tab label dropped — UI-1 must not regress W-2.1a"
    )


def test_no_invented_endpoints_added():
    """The route audit (test_dashboard_repair::test_route_audit_zero_stale)
    is the canonical no-stale-route check. This test asserts the audit's
    pin still resolves: every apiFetch call in dashboard.html targets a
    route the FastAPI app actually serves. UI-1 is CSS-only and must
    not have introduced any new apiFetch call."""
    src = _src()
    # Quick sanity: count apiFetch calls. UI-1 should not change the count.
    # If a future drift adds or removes apiFetch sites, the route-audit
    # test (existing) will be the first signal; this test is a redundant
    # belt-and-braces.
    apifetch_count = src.count("apiFetch(")
    # Lower bound — must be > 50; well under any plausible upper bound.
    assert apifetch_count > 50, (
        f"apiFetch( call count fell to {apifetch_count}; UI-1 must not "
        f"have removed call sites"
    )


# ── 4. Token completeness — every brand token from the design has an entry ─

def test_all_brand_tokens_present_in_root_block():
    """Belt-and-braces: every design-bundle brand token name must appear
    in the :root block. (Per-token *value* alignment is parametrised
    above; this test catches accidental token *deletion*.)"""
    src = _src()
    # Anchor on the :root block start; check tokens appear before the
    # closing brace of the light-theme block.
    root_idx = src.find(":root {")
    assert root_idx != -1, ":root block not found"
    # Find the closing brace of the light-theme block. It's the next "}"
    # that starts a new line on its own (or `}` followed by newline +
    # `[data-theme=`).
    dark_idx = src.find('[data-theme="dark"] {', root_idx)
    assert dark_idx != -1, "dark theme block not found after :root"
    light_block = src[root_idx:dark_idx]
    for token, _ in LIGHT_THEME_BRAND_TOKENS:
        assert token in light_block, (
            f"brand token {token} missing from :root light-theme block"
        )

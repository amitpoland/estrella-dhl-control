"""tests/test_dashboard_pz_chrome.py — UI-2a

Source-grep tests for the narrow PZ / wFirma chrome restyle
applied to dashboard.html in UI-2a.

UI-2a is style-values-only. These tests pin three classes of
invariant:

  1. Chrome alignment.
     The four hoisted style consts in B-2 (the legacy reservation
     preview block) and the customer/product search rows in B-4
     carry the Estrella-design-aligned spacing / typography
     values.

  2. Forbidden-touch invariants (UI-2a does not regress earlier
     campaigns).
       * Logic variable names (canRunPZ, runPzDisabled,
         sadDecisionPresent, safe_to_run_pz, reservationPreview)
         remain.
       * Endpoint strings remain.
       * data-testid landmarks remain.
       * Operator-visible copy remains.
       * Forbidden markers (customers/add, goods/add, method:'PUT')
         remain absent.

  3. No new components / no JSX restructure.
       * No StatTile component appears in dashboard.html.
       * The block fences (`activeTab === 'PZ / wFirma'`,
         `wfirma-confirm-modal`, etc.) are unchanged.
       * Brace balance unchanged in B-2.

The tests are scoped to the two B-2 / B-4 surfaces UI-2a actually
touched, plus a cross-cutting forbidden-touch sweep over the
whole dashboard source.
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


# ── 1. B-2 hoisted style consts carry the design-aligned values ────────────

def test_section_style_aligned():
    """sectionStyle in B-2 must use design's padding 14px 18px and
    marginBottom 14."""
    src = _src()
    assert (
        "const sectionStyle = { padding: '14px 18px', marginBottom: 14 };" in src
    ), "sectionStyle in B-2 must be { padding: '14px 18px', marginBottom: 14 }"


def test_tbl_style_unchanged():
    """tblStyle stays as the design-canonical table chrome."""
    src = _src()
    assert (
        "const tblStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 11 };" in src
    ), "tblStyle must remain { width: '100%', borderCollapse: 'collapse', fontSize: 11 }"


def test_th_style_aligned():
    """thStyle: padding 8px 12px and letterSpacing 0.06em (design
    typography conventions)."""
    src = _src()
    # The exact form preserves all logic-bearing fields untouched.
    th_expected = (
        "const thStyle  = { textAlign: 'left', padding: '8px 12px', "
        "borderBottom: '1px solid var(--border)', fontWeight: 700, "
        "color: 'var(--text-3)', textTransform: 'uppercase', "
        "fontSize: 10, letterSpacing: '0.06em' };"
    )
    assert th_expected in src, (
        "thStyle in B-2 must use padding '8px 12px' + letterSpacing '0.06em'"
    )


def test_td_style_aligned():
    """tdStyle: padding 8px 12px (design-aligned)."""
    src = _src()
    td_expected = (
        "const tdStyle  = { padding: '8px 12px', "
        "borderBottom: '1px solid var(--border-subtle)', "
        "color: 'var(--text-2)' };"
    )
    assert td_expected in src, (
        "tdStyle in B-2 must use padding '8px 12px'"
    )


# ── 2. B-4 search-row chrome alignment ─────────────────────────────────────

def test_customer_search_row_chrome_aligned():
    src = _src()
    expected = (
        '<div data-testid="customer-search-row" style={{ display: \'flex\', '
        "gap: 10, alignItems: 'center', marginBottom: 14 }}>"
    )
    assert expected in src, (
        "customer-search-row chrome must be gap:10, marginBottom:14"
    )


def test_product_search_row_chrome_aligned():
    src = _src()
    expected = (
        '<div data-testid="product-search-row" style={{ display: \'flex\', '
        "gap: 10, alignItems: 'center', marginBottom: 14 }}>"
    )
    assert expected in src, (
        "product-search-row chrome must be gap:10, marginBottom:14"
    )


# ── 3. Forbidden-touch — logic vars MUST remain ────────────────────────────

@pytest.mark.parametrize(
    "logic_var",
    [
        "canRunPZ",
        "runPzDisabled",
        "sadDecisionPresent",
        "safe_to_run_pz",
        "reservationPreview",
        "loadReservationPreview",
        "loadCarrierShipments",      # adjacent — must not regress
        "pz_preview",
        "pz_create",
        "pz_adopt",
        "pz_lock_status",
    ],
)
def test_logic_variable_preserved(logic_var):
    src = _src()
    assert logic_var in src, (
        f"required logic variable {logic_var!r} no longer present in dashboard.html"
    )


# ── 4. Forbidden-touch — endpoint strings MUST remain ──────────────────────

@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/upload/shipment/",                 # PZ process + wFirma sub-routes
        "/process",                                  # PZ run trigger
        "/api/v1/wfirma/reservation-preview/",       # B-2 reservation preview
        "/wfirma/pz_preview",                        # PZ preview
        "/wfirma/pz_create",                         # PZ create
        "/wfirma/pz_adopt",                          # PZ adopt
        "/wfirma/pz_document",                       # PZ document
        "/wfirma/products/resolve",                  # product resolve
        "/wfirma/pz/refresh-mapping",                # mapping refresh
        "/api/v1/wfirma/contractors",                # customer search
        "/api/v1/wfirma/goods",                      # product search
    ],
)
def test_endpoint_string_preserved(endpoint):
    src = _src()
    assert endpoint in src, (
        f"endpoint {endpoint!r} no longer present in dashboard.html"
    )


# ── 5. Forbidden-touch — testid landmarks MUST remain ──────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        # PZ B-1
        "pz-already-created-banner",
        "pz-document-panel",
        "pz-lock-status-banner",
        "pz-lock-doc-id",
        "pz-lock-source",
        "pz-lock-event",
        # wFirma create B-2 / B-3
        "wfirma-create-btn",
        "wfirma-create-disabled-reason",
        "wfirma-skip-msg",
        "wfirma-log-warn",
        "wfirma-confirm-modal",
        "wfirma-confirm-submit-btn",
        # wFirma search B-4
        "customer-search-row",
        "customer-search-btn",
        "product-search-row",
        "product-search-btn",
    ],
)
def test_testid_landmark_preserved(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src, (
        f"testid landmark {testid!r} no longer present in dashboard.html"
    )


# ── 6. Forbidden-touch — operator-visible copy MUST remain ─────────────────

@pytest.mark.parametrize(
    "copy",
    [
        "Run PZ",
        "SAD validation failed",
        "Already created",
        "Create Reservation",
        "Search wFirma",
        "Looks up the contractor",
        "Looks up the good",
    ],
)
def test_operator_copy_preserved(copy):
    src = _src()
    assert copy in src, f"operator-visible copy {copy!r} no longer in dashboard.html"


# ── 7. Forbidden markers — must stay absent ────────────────────────────────

@pytest.mark.parametrize("forbidden", ["customers/add", "goods/add"])
def test_forbidden_create_markers_absent(forbidden):
    src = _src()
    assert forbidden not in src, (
        f"forbidden auto-create marker {forbidden!r} found in dashboard.html"
    )


def test_search_handlers_do_not_use_method_put():
    """Pin from test_dashboard_wfirma_search.py — wFirma search must
    not be a PUT. UI-2a must not have introduced one."""
    src = _src()
    # Belt-and-braces: this is also the existing wfirma_search test.
    # Here we sweep around the customer-search-btn and product-search-btn
    # blocks specifically for `method: 'PUT'` near them.
    for landmark in ("customer-search-btn", "product-search-btn"):
        idx = src.find(f'data-testid="{landmark}"')
        assert idx != -1
        snippet = src[max(0, idx - 200): idx + 1500]
        assert "method: 'PUT'" not in snippet
        assert 'method: "PUT"' not in snippet


# ── 8. No new component (no StatTile, no JSX restructure) ──────────────────

def test_no_stat_tile_component_introduced():
    """The migration design defines a StatTile component. UI-2a does
    NOT adopt it. The dashboard.html must remain free of StatTile
    JSX usage."""
    src = _src()
    assert "<StatTile" not in src, (
        "<StatTile component appears in dashboard.html — UI-2a must not "
        "adopt new components from the design (matrix §8 verdict: "
        "PZ partial migrate STYLE-ONLY)"
    )
    assert "function StatTile" not in src, (
        "function StatTile defined in dashboard.html — UI-2a must not "
        "introduce new components"
    )


def test_block_fences_unchanged():
    """The four PZ / wFirma block fences are anchors for tests and must
    remain at their canonical strings."""
    src = _src()
    assert "activeTab === 'PZ / wFirma' && (" in src, (
        "B-1 fence missing"
    )
    assert "activeTab === 'PZ / wFirma' && (() => {" in src, (
        "B-2 fence missing"
    )
    assert 'data-testid="wfirma-confirm-modal"' in src, "B-3 fence missing"
    assert 'data-testid="customer-search-row"' in src, "B-4 customer fence missing"
    assert 'data-testid="product-search-row"' in src, "B-4 product fence missing"


def test_dashboard_html_braces_balanced():
    """Whole-file `{` / `}` count must match. Catches truncation /
    accidental brace deletion. Mirrors the existing balance-check
    used in test_dashboard_wfirma_reservation_preview_panel.py.

    A local-block paren count would catch regex literals and string
    contents as imbalanced even when JS-parses cleanly — so the
    coarse whole-file brace check is the right invariant for UI-2a.
    """
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, (
        f"unbalanced braces in dashboard.html: {{={opens} }}={closes}"
    )


# ── 9. Chrome tokens use existing CSS variables (no new hex hardcodes) ─────

def test_chrome_uses_css_variables_not_hex():
    """The four restyled style consts must reference CSS variables for
    colours (not hardcoded hex), so UI-1's brand palette flows
    through unchanged. Padding/spacing values may be numeric."""
    src = _src()
    # Locate the B-2 sectionStyle const and walk forward through the
    # four consts.
    start = src.find("const sectionStyle = { padding: '14px 18px'")
    assert start != -1
    region = src[start: start + 800]
    # Each colour reference in this region must be a var(--…) token,
    # not a #xxxxxx hex literal. Walk every '#' followed by 6 hex
    # chars; assert none in the region.
    import re
    hex_hits = re.findall(r"#[0-9A-Fa-f]{6}", region)
    assert hex_hits == [], (
        f"hardcoded hex colour in restyled chrome: {hex_hits!r} — UI-2a "
        f"must use CSS variables only"
    )


# ── 10. UI-1 brand-token alignment carries through (sanity) ────────────────

def test_ui1_palette_still_present():
    """UI-1 brand tokens must still be in :root — UI-2a must not have
    accidentally edited the brand palette."""
    src = _src()
    for token_value in (
        "--accent: #B89968",       # UI-1 design accent
        "--bg: #F4F1EA",            # UI-1 design background
        "--text: #1B2538",          # UI-1 design text
        "--sidebar-bg: #131C2E",    # UI-1 design sidebar
    ):
        # tolerate the whitespace patterns dashboard.html actually uses
        import re
        token, value = token_value.split(": ")
        pattern = re.compile(rf"{re.escape(token)}\s*:\s*{re.escape(value)}\b")
        assert pattern.search(src) is not None, (
            f"UI-1 brand token {token_value!r} no longer present"
        )


# ── 11. Out-of-scope content stays out (cross-cutting from migration matrix) ─

@pytest.mark.parametrize("forbidden", ["FedEx IP", "FedEx Priority", "Estrella Atlas"])
def test_out_of_scope_design_content_absent(forbidden):
    """The design bundle's multi-carrier markers + alternate product
    name must remain absent."""
    src = _src()
    assert forbidden not in src, (
        f"out-of-scope design content {forbidden!r} found in dashboard.html"
    )

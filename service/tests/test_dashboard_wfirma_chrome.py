"""tests/test_dashboard_wfirma_chrome.py — UI-2b

Source-grep tests for the narrow wFirma chrome restyle applied
to dashboard.html in UI-2b.

UI-2b is style-values-only across three sub-surfaces:
  W-α  B-2 reservation-preview footer row
  W-β  B-3 reservation confirm modal chrome
  W-γ  B-4 customer/product search-result pills

These tests pin three classes of invariant:

  1. Chrome alignment (positive).
     Each of the seven W-α/W-β/W-γ value changes is present
     verbatim.

  2. Forbidden-touch invariants.
     Logic variable names, endpoint strings, data-testid
     landmarks, operator-visible copy strings, and forbidden
     create / alert / multi-carrier markers remain unchanged.

  3. No new component / no JSX restructure / no design-bundle
     unsafe simplifications adopted.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


# ── 1. Chrome alignment — positive value pins ──────────────────────────────

def test_w_alpha_footer_row_aligned():
    """W-α — B-2 reservation-preview footer row carries the new
    spacing values."""
    src = _src()
    expected = (
        "marginTop: 14, paddingTop: 12, "
        "borderTop: '1px solid var(--border-subtle)', "
        "display: 'flex', alignItems: 'center', "
        "justifyContent: 'space-between', gap: 14, flexWrap: 'wrap'"
    )
    assert expected in src, (
        "W-α footer row chrome not aligned: must use marginTop:14, "
        "paddingTop:12, gap:14"
    )


def test_w_beta_modal_description_aligned():
    """W-β — modal description marginBottom 12 → 14."""
    src = _src()
    expected = (
        "<div style={{ fontSize: 12, color: 'var(--text-2)', "
        "marginBottom: 14, lineHeight: 1.5 }}>"
    )
    assert expected in src, "W-β modal description marginBottom must be 14"


def test_w_beta_modal_summary_box_aligned():
    """W-β — summary box: padding '10px 12px' → '12px 14px';
    borderRadius 6 → 8."""
    src = _src()
    expected = (
        "background: 'var(--bg-subtle)', border: '1px solid var(--border)', "
        "borderRadius: 8, padding: '12px 14px', marginBottom: 14, "
        "fontSize: 12, lineHeight: 1.6"
    )
    assert expected in src, (
        "W-β modal summary box must use borderRadius:8 + padding:'12px 14px'"
    )


def test_w_beta_modal_fineprint_aligned():
    """W-β — fineprint marginBottom 12 → 14."""
    src = _src()
    expected = (
        "<div style={{ fontSize: 11, color: 'var(--text-3)', "
        "marginBottom: 14 }}>"
    )
    assert expected in src, "W-β modal fineprint marginBottom must be 14"


def test_w_beta_modal_button_row_aligned():
    """W-β — button row gap 8 → 10."""
    src = _src()
    expected = (
        "<div style={{ display: 'flex', gap: 10, "
        "justifyContent: 'flex-end' }}>"
    )
    assert expected in src, "W-β modal button row gap must be 10"


def test_w_gamma_customer_pill_aligned():
    """W-γ — customer search-result pill: padding + marginBottom."""
    src = _src()
    cust_idx = src.find("data-testid={`customer-search-${searchInfo.kind}`}")
    assert cust_idx != -1, "customer-search-${kind} testid not found"
    snippet = src[cust_idx : cust_idx + 800]
    assert (
        "fontSize: 11, padding: '8px 12px', borderRadius: 6, marginBottom: 14"
        in snippet
    ), (
        "W-γ customer search-result pill must use padding:'8px 12px' + "
        "marginBottom:14"
    )


def test_w_gamma_product_pill_aligned():
    """W-γ — product search-result pill: padding + marginBottom."""
    src = _src()
    prod_idx = src.find("data-testid={`product-search-${searchInfo.kind}`}")
    assert prod_idx != -1, "product-search-${kind} testid not found"
    snippet = src[prod_idx : prod_idx + 800]
    assert (
        "fontSize: 11, padding: '8px 12px', borderRadius: 6, marginBottom: 14"
        in snippet
    ), (
        "W-γ product search-result pill must use padding:'8px 12px' + "
        "marginBottom:14"
    )


# ── 2. Logic variables MUST remain ─────────────────────────────────────────

@pytest.mark.parametrize(
    "logic_var",
    [
        "reservationPreview",
        "loadReservationPreview",
        "createConfirm",
        "createBusy",
        "createResults",
        "submitReservation",
        "alreadyCreated",
        "canCreate",
        "batchWfirmaBlocked",
        "isDisabled",
        "disabledReason",
        "wfirmaPrimary",
        "searchInfo",
        "searchBusy",
        "editingCustomer",
        "editingProduct",
        "searchWfirmaCustomer",
        "searchWfirmaProduct",
        "wfirma_reservation_id",
        "log_write_failed",
        "milestone_skip",
    ],
)
def test_logic_variable_preserved(logic_var):
    src = _src()
    assert logic_var in src, (
        f"required logic variable {logic_var!r} no longer in dashboard.html"
    )


# ── 3. Endpoint strings MUST remain ────────────────────────────────────────

@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/wfirma/reservation-preview/",
        "/api/v1/wfirma/contractors",
        "/api/v1/wfirma/goods",
    ],
)
def test_wfirma_endpoint_preserved(endpoint):
    src = _src()
    assert endpoint in src, (
        f"endpoint {endpoint!r} no longer in dashboard.html"
    )


# ── 4. Testid landmarks MUST remain ────────────────────────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        "wfirma-create-btn",
        "wfirma-create-disabled-reason",
        "wfirma-skip-msg",
        "wfirma-log-warn",
        "wfirma-confirm-modal",
        "wfirma-confirm-submit-btn",
        "customer-search-row",
        "customer-search-btn",
        "product-search-row",
        "product-search-btn",
    ],
)
def test_testid_landmark_preserved(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src, (
        f"testid landmark {testid!r} no longer in dashboard.html"
    )


def test_template_testids_preserved():
    """The customer-search-${kind} and product-search-${kind} template
    testids must remain wired to searchInfo.kind."""
    src = _src()
    assert "data-testid={`customer-search-${searchInfo.kind}`}" in src, (
        "customer-search-${kind} template testid missing"
    )
    assert "data-testid={`product-search-${searchInfo.kind}`}" in src, (
        "product-search-${kind} template testid missing"
    )


# ── 5. Operator-visible copy MUST remain ───────────────────────────────────

@pytest.mark.parametrize(
    "copy",
    [
        "Confirm wFirma Reservation",
        "Already created",
        "Create Reservation",
        "Cancel",
        "Confirm & Create",
        "Submitting…",
        "Disabled —",
        "Ready to submit to wFirma",
        "Skipped: already progressed (SAD/PZ/Completed)",
        "✓ Created — wFirma ID:",
        "⚠ Action completed but log write failed",
        "Search wFirma",
        "Looks up the contractor in wFirma",
        "Looks up the good in wFirma",
        "read-only, does not save.",
        "Client:",
        "Document:",
        "Total value:",
    ],
)
def test_operator_copy_preserved(copy):
    src = _src()
    assert copy in src, f"operator copy {copy!r} no longer in dashboard.html"


def test_modal_diagnostic_re_run_fineprint_preserved():
    """The fineprint that documents 'live wFirma diagnostic before
    submission' must remain. Critical operator-safety text."""
    src = _src()
    assert (
        "The system will re-run the live wFirma diagnostic before submission."
        in src
    )
    assert (
        "If anything has changed since the preview, the request will be blocked."
        in src
    )


# ── 6. Forbidden markers — must stay absent ────────────────────────────────

@pytest.mark.parametrize(
    "forbidden",
    ["customers/add", "goods/add"],
)
def test_no_auto_create_endpoints(forbidden):
    src = _src()
    assert forbidden not in src, (
        f"forbidden auto-create endpoint {forbidden!r} found in dashboard.html"
    )


def test_no_alert_in_wfirma_surfaces():
    """The design's 'alert(\"Exported to wFirma!\")' pattern is the
    canonical unsafe simplification (matrix US-2). Sweep the wFirma
    surfaces for any alert(…) call."""
    src = _src()
    # Locate the wFirma confirm modal block + the reservation
    # preview footer row block. Both must be alert-free.
    modal_idx = src.find('data-testid="wfirma-confirm-modal"')
    footer_idx = src.find('data-testid="wfirma-create-btn"')
    assert modal_idx != -1
    assert footer_idx != -1
    for idx in (modal_idx, footer_idx):
        # Inspect 1500-char window around each anchor.
        snippet = src[max(0, idx - 800) : idx + 1500]
        assert "alert(" not in snippet, (
            f"alert( found near wFirma surface at byte {idx} — UI-2b must "
            f"reject US-2 unsafe simplification"
        )


def test_no_bare_export_button():
    """The design's 'Export to wFirma!' single-button pattern is the
    canonical bare-write surface. Must not appear."""
    src = _src()
    for marker in (
        "Exported to wFirma!",      # the design's alert text
        "Export to wFirma!",         # the design's button label
    ):
        assert marker not in src, (
            f"design's bare-export marker {marker!r} found in dashboard.html"
        )


def test_search_handlers_do_not_use_method_put():
    """wFirma search remains GET — never PUT. Pinned by an existing
    test in test_dashboard_wfirma_search.py; redundant belt-and-braces
    here ensures UI-2b did not introduce a PUT."""
    src = _src()
    for landmark in ("customer-search-btn", "product-search-btn"):
        idx = src.find(f'data-testid="{landmark}"')
        assert idx != -1
        snippet = src[max(0, idx - 200) : idx + 1500]
        assert "method: 'PUT'" not in snippet
        assert 'method: "PUT"' not in snippet


# ── 7. No new component / no JSX restructure ───────────────────────────────

def test_no_stat_tile_introduced():
    src = _src()
    assert "<StatTile" not in src
    assert "function StatTile" not in src


def test_no_accounting_page_paradigm_shift():
    """The design's AccountingPage merges PZ + Sales + wFirma + Master
    + Audit into a single page (matrix US-3). UI-2b must not introduce
    that paradigm shift.

    Note: the existing dashboard.html already defines its OWN
    WfirmaExportPage at line ~8515 (different from the design's bare-
    export version). The design's bare-export shape is caught by
    test_no_bare_export_button and test_no_alert_in_wfirma_surfaces;
    the WfirmaExportPage component name itself is not a design-
    specific marker and is left alone here.
    """
    src = _src()
    assert "<AccountingPage" not in src, (
        "design's <AccountingPage> component appears in dashboard.html — "
        "UI-2b must not adopt the merged accounting paradigm (matrix US-3)"
    )
    assert "function AccountingPage" not in src, (
        "design's AccountingPage function defined in dashboard.html — "
        "UI-2b must not adopt the merged accounting paradigm"
    )


def test_block_fences_preserved():
    """The wFirma block fences UI-2b touched must still anchor."""
    src = _src()
    assert "activeTab === 'PZ / wFirma' && (() => {" in src, "B-2 fence missing"
    assert 'data-testid="wfirma-confirm-modal"' in src, "B-3 fence missing"
    assert 'data-testid="customer-search-row"' in src, "B-4 customer fence missing"
    assert 'data-testid="product-search-row"' in src, "B-4 product fence missing"


def test_dashboard_html_braces_balanced():
    """Whole-file `{` / `}` balance — coarse compile sanity check."""
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, (
        f"unbalanced braces in dashboard.html: {{={opens} }}={closes}"
    )


# ── 8. No hardcoded hex in restyled chrome ─────────────────────────────────

def test_no_hex_in_w_alpha_chrome():
    """Restyled W-α footer row uses CSS variables, not hex."""
    src = _src()
    # Re-pick the line we restyled.
    needle = (
        "marginTop: 14, paddingTop: 12, "
        "borderTop: '1px solid var(--border-subtle)', "
        "display: 'flex', alignItems: 'center', "
        "justifyContent: 'space-between', gap: 14, flexWrap: 'wrap'"
    )
    idx = src.find(needle)
    assert idx != -1
    region = src[idx : idx + len(needle) + 50]
    hex_hits = re.findall(r"#[0-9A-Fa-f]{6}", region)
    assert hex_hits == [], (
        f"hardcoded hex in W-α chrome: {hex_hits!r}"
    )


def test_no_hex_in_w_beta_modal_chrome():
    """Restyled W-β modal chrome uses CSS variables, not hex."""
    src = _src()
    modal_idx = src.find('<div data-testid="wfirma-confirm-modal">')
    assert modal_idx != -1
    region = src[modal_idx : modal_idx + 2500]
    hex_hits = re.findall(r"#[0-9A-Fa-f]{6}", region)
    assert hex_hits == [], (
        f"hardcoded hex in W-β modal chrome: {hex_hits!r}"
    )


# ── 9. UI-1 + UI-2a values still flow through (sanity) ────────────────────

def test_ui1_palette_persists():
    """UI-1 brand tokens still in :root."""
    src = _src()
    for token, value in [
        ("--accent",     "#B89968"),
        ("--bg",         "#F4F1EA"),
        ("--text",       "#1B2538"),
        ("--sidebar-bg", "#131C2E"),
    ]:
        pattern = re.compile(rf"{re.escape(token)}\s*:\s*{re.escape(value)}\b")
        assert pattern.search(src) is not None, (
            f"UI-1 brand token {token}:{value} no longer present"
        )


def test_ui2a_pz_chrome_persists():
    """UI-2a hoisted style consts in B-2 still carry the design values."""
    src = _src()
    assert (
        "const sectionStyle = { padding: '14px 18px', marginBottom: 14 };" in src
    ), "UI-2a sectionStyle alignment regressed"
    assert (
        "padding: '8px 12px'" in src
        and "letterSpacing: '0.06em'" in src
    ), "UI-2a thStyle alignment regressed"


def test_ui2a_search_row_chrome_persists():
    """UI-2a customer/product search row chrome still aligned."""
    src = _src()
    assert (
        "data-testid=\"customer-search-row\" "
        "style={{ display: 'flex', gap: 10, alignItems: 'center', "
        "marginBottom: 14 }}" in src
    )
    assert (
        "data-testid=\"product-search-row\" "
        "style={{ display: 'flex', gap: 10, alignItems: 'center', "
        "marginBottom: 14 }}" in src
    )


# ── 10. Out-of-scope design content stays out ─────────────────────────────

@pytest.mark.parametrize(
    "forbidden",
    ["FedEx IP", "FedEx Priority", "Estrella Atlas", "Shipping Operations"],
)
def test_out_of_scope_design_content_absent(forbidden):
    src = _src()
    assert forbidden not in src, (
        f"out-of-scope design content {forbidden!r} found in dashboard.html"
    )

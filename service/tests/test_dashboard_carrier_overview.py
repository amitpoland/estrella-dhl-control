"""tests/test_dashboard_carrier_overview.py — W-2.1

Source-grep tests for the read-only carrier overview UI added to
dashboard.html in W-2.1.

The W-2.1 panel is read-only by design. These tests pin:
  * the new data-testids exist,
  * the only carrier endpoint referenced is the read-only
    GET /api/v1/carrier/shipments/by-batch/{batch_id},
  * NO write verbs (POST / PUT / PATCH / DELETE) appear inside
    the new carrier-actions-tab block,
  * NO action buttons (create / cancel / print / handover) appear
    inside the new block,
  * no invented carrier endpoints leak in.

The pattern follows the existing dashboard source-grep test suite
(e.g. test_dashboard_agency_docs_card.py): read dashboard.html as
text, find the relevant block by its data-testid landmark, assert
substring constraints over a bounded snippet.
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


def _carrier_tab_snippet(src: str, size: int = 6000) -> str:
    """The carrier-actions-tab block, bounded.

    Returns the substring starting at the carrier-actions-tab
    data-testid declaration. 6000 chars is generous — the W-2.1
    panel (read-only) is roughly 4500 chars including the table
    rendering. Tests on this snippet must NOT find write verbs or
    action buttons.
    """
    idx = src.find('data-testid="carrier-actions-tab"')
    assert idx != -1, "carrier-actions-tab testid not found in dashboard.html"
    return src[idx : idx + size]


# ── 1. Required data-testids exist ──────────────────────────────────────────

def test_carrier_actions_tab_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-actions-tab"' in src
    ), "carrier-actions-tab testid not found"


def test_carrier_shipment_panel_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipment-panel"' in src
    ), "carrier-shipment-panel testid not found"


def test_carrier_shipments_refresh_btn_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipments-refresh-btn"' in src
    ), "carrier-shipments-refresh-btn testid not found"


def test_carrier_shipments_empty_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipments-empty"' in src
    ), "carrier-shipments-empty testid not found"


def test_carrier_shipments_loading_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipments-loading"' in src
    ), "carrier-shipments-loading testid not found"


def test_carrier_shipments_error_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipments-error"' in src
    ), "carrier-shipments-error testid not found"


def test_carrier_shipment_row_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipment-row"' in src
    ), "carrier-shipment-row testid not found"


def test_carrier_shipment_state_badge_testid_present():
    src = _src()
    assert (
        'data-testid="carrier-shipment-state-badge"' in src
    ), "carrier-shipment-state-badge testid not found"


# ── 2. Carrier read endpoint is wired ───────────────────────────────────────

def test_carrier_shipments_endpoint_referenced():
    """The dashboard must call the read-only by-batch endpoint."""
    src = _src()
    snippet = _carrier_tab_snippet(src, size=8000)
    assert (
        "/api/v1/carrier/shipments/by-batch/" in src
    ), "carrier by-batch endpoint not referenced in dashboard"


def test_carrier_shipments_endpoint_uses_encode_uri_component():
    """The batch_id must be URL-encoded in the GET call.

    Looks for the apiFetch call site specifically (a backtick
    template literal that contains the path), not any random string
    occurrence — the comment block above the loader also mentions
    the path.
    """
    src = _src()
    needle = "apiFetch(`/api/v1/carrier/shipments/by-batch/"
    idx = src.find(needle)
    assert idx != -1, (
        "apiFetch call to /api/v1/carrier/shipments/by-batch/ not found "
        "(template-literal form expected)"
    )
    after = src[idx : idx + 200]
    assert "encodeURIComponent(batchId)" in after, (
        "batchId must be passed through encodeURIComponent in the apiFetch call"
    )


# ── 3. No write paths anywhere in the carrier-actions-tab block ─────────────

def test_carrier_overview_has_no_post_verb():
    snippet = _carrier_tab_snippet(_src(), size=8000)
    assert "method: 'POST'" not in snippet, (
        "method: 'POST' found inside carrier-actions-tab — W-2.1 is read-only"
    )
    assert 'method: "POST"' not in snippet, (
        'method: "POST" found inside carrier-actions-tab — W-2.1 is read-only'
    )


@pytest.mark.parametrize("verb", ["PUT", "PATCH", "DELETE"])
def test_carrier_overview_has_no_other_write_verbs(verb):
    snippet = _carrier_tab_snippet(_src(), size=8000)
    assert f"method: '{verb}'" not in snippet, (
        f"method: '{verb}' found inside carrier-actions-tab — W-2.1 is read-only"
    )
    assert f'method: "{verb}"' not in snippet, (
        f'method: "{verb}" found inside carrier-actions-tab — W-2.1 is read-only'
    )


def test_carrier_overview_does_not_call_actions_endpoint():
    """The W-2.1 panel must NOT reference any carrier-actions execute
    endpoint. Action paths land in W-2.3 / W-2.4."""
    snippet = _carrier_tab_snippet(_src(), size=8000)
    assert "/api/v1/carrier/actions/" not in snippet, (
        "carrier action execute endpoint referenced in W-2.1 panel — "
        "write paths belong to later W-2.x phases"
    )


def test_carrier_overview_does_not_call_execute_wrapper():
    """The W-2.1 panel must NOT reference the /api/v1/execute/ wrapper.
    Carrier writes use /api/v1/carrier/actions/, which W-2.1 also avoids."""
    snippet = _carrier_tab_snippet(_src(), size=8000)
    assert "/api/v1/execute/" not in snippet, (
        "/api/v1/execute/ wrapper referenced in W-2.1 panel — out of scope"
    )


# ── 4. No action buttons (create / cancel / print / handover) ───────────────

@pytest.mark.parametrize(
    "forbidden_marker",
    [
        "carrier-create-btn",
        "carrier-cancel-btn",
        "carrier-print-btn",
        "carrier-handed-btn",
        "carrier-mark-printed-btn",
        "carrier-mark-handed-btn",
        "create-shipment",
        "mark-label-printed",
        "mark-handed-to-carrier",
        "cancel-shipment",
    ],
)
def test_carrier_overview_has_no_action_button_markers(forbidden_marker):
    snippet = _carrier_tab_snippet(_src(), size=8000)
    assert forbidden_marker not in snippet, (
        f"forbidden action marker {forbidden_marker!r} found inside "
        f"carrier-actions-tab — W-2.1 is read-only; action UIs land in W-2.3+"
    )


# ── 5. UI elements: empty state + state badge + refresh + read-only note ────

def test_carrier_overview_empty_state_text_present():
    snippet = _carrier_tab_snippet(_src())
    assert (
        "No carrier shipments yet" in snippet
    ), "carrier overview empty-state copy not found"


def test_carrier_overview_state_badge_renders_via_color_map():
    """The state badge must map at least the four common state names
    issued by carrier_state_engine."""
    snippet = _carrier_tab_snippet(_src(), size=8000)
    for state in ("created", "label_created", "label_printed", "handed_to_carrier", "voided"):
        assert state in snippet, (
            f"state {state!r} not found in carrier overview state-badge map"
        )


def test_carrier_overview_refresh_button_exists():
    snippet = _carrier_tab_snippet(_src())
    # The refresh button is a Btn with the testid + onClick=loadCarrierShipments.
    assert "loadCarrierShipments" in snippet, (
        "loadCarrierShipments handler not wired into the refresh button"
    )
    assert "↺ Refresh" in snippet, "refresh button glyph not found"


def test_carrier_overview_read_only_mode_note_present():
    snippet = _carrier_tab_snippet(_src())
    assert "data-testid=\"carrier-overview-mode-note\"" in snippet
    # Must explicitly tell the operator that actions aren't here yet.
    assert "Read-only" in snippet or "read-only" in snippet


# ── 6. No invented carrier endpoints ────────────────────────────────────────

def test_carrier_overview_does_not_invent_endpoints():
    """The only carrier endpoint the W-2.1 block may reference is the
    read-only by-batch list. Any /api/v1/carrier/* path appearing in
    the block must start with the allowed prefix."""
    snippet = _carrier_tab_snippet(_src(), size=8000)
    import re
    paths = re.findall(r"/api/v1/carrier/[A-Za-z0-9_/-]*", snippet)
    allowed_prefix = "/api/v1/carrier/shipments/by-batch/"
    for p in paths:
        assert p.startswith(allowed_prefix), (
            f"carrier endpoint {p!r} appears in carrier-actions-tab "
            f"but only {allowed_prefix!r} is allowed in W-2.1"
        )


# ── 7. Tab registration ─────────────────────────────────────────────────────

def test_carrier_tab_registered_in_detail_tabs():
    src = _src()
    # The tab list defines DETAIL_TABS = [..., 'Carrier'].
    assert (
        "'Carrier'" in src and "DETAIL_TABS" in src
    ), "Carrier tab not registered in DETAIL_TABS"


def test_carrier_tab_renders_under_carrier_active_tab():
    src = _src()
    assert (
        "activeTab === 'Carrier'" in src
    ), "carrier-actions-tab not gated by activeTab === 'Carrier'"


def test_carrier_tab_use_effect_triggers_load():
    src = _src()
    # The useEffect that fires loadCarrierShipments when the Carrier
    # tab activates must be present.
    assert (
        "activeTab === 'Carrier'" in src
        and "loadCarrierShipments" in src
    ), "carrier-tab useEffect or loader missing"

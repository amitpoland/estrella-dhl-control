"""tests/test_dashboard_carrier_timeline.py — W-2.2

Source-grep tests for the DHL Express shipment timeline + label
evidence view added inside the existing carrier-actions-tab in
dashboard.html in W-2.2.

The W-2.2 surface is read-only by design. These tests pin:
  * the new data-testids exist (timeline + label evidence card +
    sub-states),
  * exactly two read-only carrier endpoints are referenced from
    inside the new block:
        GET /api/v1/carrier/shipments/{id}/transitions
        GET /api/v1/carrier/labels/{sha256}
  * NO write verbs (POST / PUT / PATCH / DELETE),
  * NO action buttons (create / cancel / print / handover),
  * Operator-visible labels say "DHL Express",
  * No FedEx / UPS / multi-carrier wording (Estrella scope is
    Polish DHL Express / MyDHL API only).

Pattern follows test_dashboard_carrier_overview.py: read
dashboard.html as text, anchor on a data-testid landmark, assert
substring constraints over a bounded snippet.
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


def _detail_snippet(src: str, size: int = 8000) -> str:
    """The carrier-shipment-detail block, bounded.

    The W-2.2 surface lives under data-testid="carrier-shipment-detail",
    inside the existing carrier-actions-tab from W-2.1 / W-2.1a.
    """
    idx = src.find('data-testid="carrier-shipment-detail"')
    assert idx != -1, (
        "carrier-shipment-detail testid not found in dashboard.html"
    )
    return src[idx : idx + size]


def _carrier_tab_snippet(src: str, size: int = 12000) -> str:
    """Wider snippet that includes the W-2.1 panel + W-2.2 detail.

    Used for tests that assert across both surfaces (e.g.,
    no-write-verb invariants, no-FedEx wording).
    """
    idx = src.find('data-testid="carrier-actions-tab"')
    assert idx != -1, "carrier-actions-tab testid not found"
    return src[idx : idx + size]


# ── 1. Required new data-testids exist ─────────────────────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        "carrier-shipment-detail",
        "carrier-shipment-detail-header",
        "carrier-shipment-detail-clear-btn",
        "carrier-shipment-timeline",
        "carrier-transitions-refresh-btn",
        "carrier-transitions-loading",
        "carrier-transitions-error",
        "carrier-transitions-empty",
        "carrier-transitions-list",
        "carrier-transition-row",
        "carrier-shipment-label-evidence",
        "carrier-shipment-label-evidence-missing",
        "carrier-label-sha256",
        "carrier-label-download-link",
    ],
)
def test_w2_2_testid_present(testid):
    src = _src()
    needle = f'data-testid="{testid}"'
    assert needle in src, f"{testid} testid not found in dashboard.html"


# ── 2. Allowed read-only endpoints are referenced ──────────────────────────

def test_transitions_endpoint_referenced_in_detail_block():
    """The W-2.2 detail block must call the read-only transitions
    endpoint via apiFetch with encodeURIComponent on the shipment id."""
    src = _src()
    needle = "apiFetch(`/api/v1/carrier/shipments/${encodeURIComponent("
    idx = src.find(needle)
    assert idx != -1, (
        "apiFetch call to /api/v1/carrier/shipments/{id}/transitions not "
        "found (template-literal form expected)"
    )
    after = src[idx : idx + 200]
    assert "/transitions" in after, (
        "apiFetch URL must end with /transitions"
    )


def test_label_endpoint_referenced_in_detail_block():
    snippet = _detail_snippet(_src(), size=10000)
    # The download is a plain <a href> — GET-only by definition.
    assert "/api/v1/carrier/labels/${encodeURIComponent(labelSha)}" in snippet, (
        "label download href must use /api/v1/carrier/labels/${sha} with "
        "encodeURIComponent"
    )


def test_label_link_is_get_only_anchor():
    snippet = _detail_snippet(_src(), size=10000)
    # The download link must be an <a href> tag, not a form-POST,
    # not a fetch with method:'POST'. This pins the anchor element.
    assert 'href={`/api/v1/carrier/labels/' in snippet, (
        "label download must use href={`...`} (anchor tag), not fetch()"
    )
    # Belt-and-braces: the link must explicitly use rel="noopener" for
    # target=_blank safety.
    assert 'target="_blank"' in snippet
    assert 'rel="noopener noreferrer"' in snippet


# ── 3. No write verbs anywhere in the carrier-actions-tab block ────────────

def test_carrier_tab_has_no_post_verb():
    """Combined W-2.1 + W-2.1a + W-2.2 surface must remain POST-free."""
    snippet = _carrier_tab_snippet(_src(), size=14000)
    assert "method: 'POST'" not in snippet, (
        "method: 'POST' found in carrier-actions-tab — W-2.2 must stay read-only"
    )
    assert 'method: "POST"' not in snippet


@pytest.mark.parametrize("verb", ["PUT", "PATCH", "DELETE"])
def test_carrier_tab_has_no_other_write_verbs(verb):
    snippet = _carrier_tab_snippet(_src(), size=14000)
    assert f"method: '{verb}'" not in snippet
    assert f'method: "{verb}"' not in snippet


def test_detail_block_does_not_call_actions_endpoint():
    snippet = _detail_snippet(_src(), size=10000)
    assert "/api/v1/carrier/actions/" not in snippet, (
        "/api/v1/carrier/actions/ referenced in detail block — W-2.2 "
        "must not introduce write paths"
    )


def test_detail_block_does_not_call_execute_wrapper():
    snippet = _detail_snippet(_src(), size=10000)
    assert "/api/v1/execute/" not in snippet, (
        "/api/v1/execute/ wrapper referenced in detail block"
    )


# ── 4. No action buttons (create / cancel / print / handover) ──────────────

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
        "Print label",
        "Hand to carrier",
        "Cancel shipment",
        "Create shipment",
    ],
)
def test_detail_block_has_no_action_button_markers(forbidden_marker):
    snippet = _detail_snippet(_src(), size=10000)
    assert forbidden_marker not in snippet, (
        f"forbidden action marker {forbidden_marker!r} found in W-2.2 "
        f"detail block — read-only only; action UIs land in W-2.3+"
    )


# ── 5. Endpoint allowlist sweep across the detail block ────────────────────

def test_detail_block_endpoint_allowlist():
    """Every /api/v1/carrier/* path appearing inside the W-2.2 detail
    block must match one of the two allowed read-only endpoints."""
    snippet = _detail_snippet(_src(), size=10000)
    # Capture path stems up to the first interpolation / quote / backtick.
    paths = re.findall(r"/api/v1/carrier/[A-Za-z0-9_/\-{}\\$]*", snippet)
    allowed_prefixes = (
        "/api/v1/carrier/shipments/${encodeURIComponent",
        "/api/v1/carrier/labels/${encodeURIComponent",
    )
    for p in paths:
        # Trim trailing punctuation or template artifacts that survived
        # the regex (e.g., the closing brace or a quote glued onto the
        # last interpolation token).
        stem = p
        assert any(stem.startswith(prefix) for prefix in allowed_prefixes), (
            f"endpoint {p!r} appears in W-2.2 detail block but is not in "
            f"the allowlist {allowed_prefixes!r}"
        )


# ── 6. Empty / loading / error states present ──────────────────────────────

def test_transitions_empty_state_text_present():
    snippet = _detail_snippet(_src())
    assert "No transitions yet" in snippet


def test_transitions_loading_text_present():
    snippet = _detail_snippet(_src())
    assert "Loading DHL Express transitions" in snippet


def test_transitions_error_text_present():
    snippet = _detail_snippet(_src())
    assert "Failed to load DHL Express transitions" in snippet


# ── 7. Refresh + clear-selection wiring ────────────────────────────────────

def test_transitions_refresh_button_wired():
    snippet = _detail_snippet(_src())
    assert "loadCarrierTransitions(selectedShipmentId)" in snippet, (
        "refresh button must call loadCarrierTransitions(selectedShipmentId)"
    )


def test_clear_selection_button_clears_state():
    snippet = _detail_snippet(_src())
    # Clear button must call setSelectedShipmentId(null).
    assert "setSelectedShipmentId(null)" in snippet


def test_row_click_toggles_selection():
    """Clicking a shipment row should toggle selectedShipmentId. This
    is a UI-state change; no API call from the click itself."""
    src = _src()
    # The row's onClick handler must call setSelectedShipmentId(...).
    assert "setSelectedShipmentId(isSelected ? null : (s.id || null))" in src, (
        "row click must toggle selectedShipmentId"
    )


# ── 8. DHL Express wording inherited from W-2.1a ───────────────────────────

def test_detail_block_uses_dhl_express_wording():
    snippet = _detail_snippet(_src(), size=10000)
    # At least three independent operator-visible "DHL Express" mentions
    # in the W-2.2 surface (header, transitions card title, label card).
    occurrences = snippet.count("DHL Express")
    assert occurrences >= 3, (
        f"expected ≥3 'DHL Express' mentions in detail block; found {occurrences}"
    )


def test_detail_block_does_not_use_generic_carrier_phrases():
    """Operator-visible generic 'carrier' phrases that previously
    existed in W-2.1 (now fixed in W-2.1a) must not creep back via
    W-2.2."""
    snippet = _detail_snippet(_src(), size=10000)
    for forbidden in (
        "carrier transitions",
        "Carrier Transitions",
        "carrier label",
        "Carrier Label",
        "carrier timeline",
        "Carrier Timeline",
    ):
        assert forbidden not in snippet, (
            f"generic operator copy {forbidden!r} found in W-2.2 detail block"
        )


@pytest.mark.parametrize("forbidden", ["FedEx", "UPS", "fedex"])
def test_detail_block_does_not_mention_other_carriers(forbidden):
    snippet = _detail_snippet(_src(), size=10000)
    assert forbidden not in snippet, (
        f"out-of-scope carrier {forbidden!r} found in detail block"
    )


# ── 9. State + loader wiring ──────────────────────────────────────────────

def test_state_variables_declared():
    src = _src()
    for needle in (
        "selectedShipmentId",
        "carrierTransitions",
        "carrierTransitionsLoading",
        "carrierTransitionsError",
    ):
        assert f"const [{needle}" in src or needle in src, (
            f"state variable {needle} not declared"
        )


def test_loader_callback_declared():
    src = _src()
    assert "const loadCarrierTransitions = React.useCallback(async (shipmentId) =>" in src, (
        "loadCarrierTransitions callback signature not found"
    )


def test_use_effect_loads_on_selection_change():
    src = _src()
    assert (
        "loadCarrierTransitions(selectedShipmentId)" in src
        and "[selectedShipmentId, loadCarrierTransitions]" in src
    ), (
        "useEffect must call loadCarrierTransitions when "
        "selectedShipmentId changes"
    )


# ── 10. Detail block is gated on a selected shipment ──────────────────────

def test_detail_block_only_renders_when_selected():
    src = _src()
    # The detail block lives inside `selectedShipmentId && (() => { ... })()`.
    # We verify the gating expression appears in the source.
    assert "{selectedShipmentId && (() => {" in src, (
        "detail block must be gated by selectedShipmentId truthiness"
    )

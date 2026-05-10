"""tests/test_dashboard_carrier_shadow_panel.py — UI-GAP-1.3

Source-grep tests for the DHL Express shadow log review panel
added to dashboard.html in UI-GAP-1.3.

The panel is READ-ONLY by design. These tests pin three classes
of invariant:

  1. Surface presence.
     The new data-testids exist; the summary + recent endpoints
     are wired; refresh button is present; empty / loading /
     error states exist.

  2. Write-safety invariants.
     No POST / PUT / PATCH / DELETE in the shadow-panel block.
     No /api/v1/carrier/actions/* or /api/v1/execute/* anywhere
     in the block. No action buttons (create / cancel / print /
     handover).

  3. Privacy invariants.
     The backend's _ROW_KEY_ALLOWLIST already strips raw DHL
     bytes, credentials, label_bytes, and documentImages from the
     rows the dashboard receives. These tests pin that the
     dashboard ALSO does not render or reference any such fields
     locally (defence-in-depth source-grep).

  4. Carrier scope.
     Operator-visible copy says "DHL Express"; FedEx / UPS /
     multi-carrier markers stay absent; nothing in the block
     implies live production is approved.

Pattern follows the existing carrier-UI test suite
(test_dashboard_carrier_overview.py / _timeline.py /
_proposals.py): scope assertions to the shadow-panel block via
its data-testid landmark, plus a global JS-handler sweep for
write-side invariants.
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


def _shadow_panel_snippet(src: str, size: int = 9000) -> str:
    """The carrier-shadow-panel block, bounded."""
    idx = src.find('data-testid="carrier-shadow-panel"')
    assert idx != -1, "carrier-shadow-panel testid not found"
    return src[idx : idx + size]


def _shadow_loader_snippet(src: str, size: int = 1800) -> str:
    """The loadCarrierShadow callback body — single read site."""
    idx = src.find("const loadCarrierShadow = React.useCallback")
    assert idx != -1, "loadCarrierShadow callback not found"
    return src[idx : idx + size]


# ── 1. Required testids ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        "carrier-shadow-panel",
        "carrier-shadow-explanation",
        "carrier-shadow-refresh-btn",
        "carrier-shadow-loading",
        "carrier-shadow-error",
        "carrier-shadow-summary-card",
        "carrier-shadow-summary-window",
        "carrier-shadow-summary-lifetime",
        "carrier-shadow-summary-empty",
        "carrier-shadow-summary-table",
        "carrier-shadow-summary-bucket",
        "carrier-shadow-recent-card",
        "carrier-shadow-recent-empty",
        "carrier-shadow-recent-table",
        "carrier-shadow-recent-row",
        "carrier-shadow-diff-badge",
    ],
)
def test_shadow_panel_testid_present(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src, (
        f"{testid} testid not found in dashboard.html"
    )


# ── 2. Endpoints — exact references ────────────────────────────────────────

def test_summary_endpoint_referenced_exactly():
    """The shadow-summary endpoint must be the *exact* URL the loader
    calls — `/api/v1/carrier/shadow/summary` (no query params, no
    trailing slash variant)."""
    src = _src()
    loader = _shadow_loader_snippet(src)
    assert "apiFetch('/api/v1/carrier/shadow/summary')" in loader, (
        "loader must call apiFetch('/api/v1/carrier/shadow/summary')"
    )


def test_recent_endpoint_referenced_exactly():
    src = _src()
    loader = _shadow_loader_snippet(src)
    assert "apiFetch('/api/v1/carrier/shadow/recent')" in loader, (
        "loader must call apiFetch('/api/v1/carrier/shadow/recent')"
    )


def test_loader_uses_promise_all():
    """Both endpoints must fire in parallel (Promise.all). UX latency
    matters on the stabilization-window operator dashboard."""
    loader = _shadow_loader_snippet(_src())
    assert "Promise.all" in loader, (
        "loadCarrierShadow must use Promise.all for the parallel reads"
    )


# ── 3. Write-safety — no method:'POST' / PUT / PATCH / DELETE ──────────────

def test_shadow_panel_has_no_post_verb():
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert "method: 'POST'" not in panel, (
        "method: 'POST' found inside shadow panel — UI-GAP-1.3 is read-only"
    )
    assert 'method: "POST"' not in panel


@pytest.mark.parametrize("verb", ["PUT", "PATCH", "DELETE"])
def test_shadow_panel_has_no_other_write_verbs(verb):
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert f"method: '{verb}'" not in panel
    assert f'method: "{verb}"' not in panel


def test_shadow_panel_does_not_call_actions_endpoint():
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert "/api/v1/carrier/actions/" not in panel, (
        "/api/v1/carrier/actions/ referenced in shadow panel — read-only"
    )


def test_shadow_panel_does_not_call_execute_wrapper():
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert "/api/v1/execute/" not in panel


# ── 4. Endpoint allowlist sweep ────────────────────────────────────────────

def test_shadow_panel_endpoint_allowlist():
    """Every /api/v1/carrier/* path in the shadow panel must match
    exactly one of the two allowed read-only endpoints."""
    panel = _shadow_panel_snippet(_src(), size=12000)
    paths = re.findall(r"/api/v1/carrier/[A-Za-z0-9_/\-{}\\$]*", panel)
    allowed = (
        "/api/v1/carrier/shadow/summary",
        "/api/v1/carrier/shadow/recent",
    )
    for p in paths:
        assert any(p.startswith(a) for a in allowed), (
            f"endpoint {p!r} in shadow panel; allowlist is {allowed!r}"
        )


# ── 5. No action buttons ───────────────────────────────────────────────────

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
        "Approve cutover",
    ],
)
def test_shadow_panel_has_no_action_button_markers(forbidden_marker):
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert forbidden_marker not in panel, (
        f"forbidden action marker {forbidden_marker!r} in shadow panel"
    )


# ── 6. Privacy — never expose raw DHL bytes, credentials, label data ──────

@pytest.mark.parametrize(
    "forbidden_field",
    [
        "raw_json",
        "raw_response",
        "Authorization",
        "password",
        "secret",
        "accountNumber",
        "account_number",
        "label_bytes",
        "labelContent",
        "documentImages",
        "signature_name",
        "signatureName",
        "X-API-Key",
        "X-DHL-API-Key",
    ],
)
def test_shadow_panel_does_not_reference_sensitive_fields(forbidden_field):
    """The backend's _ROW_KEY_ALLOWLIST already strips these from the
    rows the dashboard receives. The dashboard must ALSO not reference
    them locally (defence-in-depth source-grep)."""
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert forbidden_field not in panel, (
        f"sensitive field {forbidden_field!r} referenced in shadow panel"
    )


# ── 7. Required rendering surfaces ────────────────────────────────────────

def test_shadow_summary_renders_method_and_diff_columns():
    panel = _shadow_panel_snippet(_src())
    assert "'Method'" in panel
    assert "'Diff outcome'" in panel
    assert "'Count'" in panel


@pytest.mark.parametrize(
    "field",
    [
        "'Created'",
        "'Method'",
        "'Diff'",
        "'Live status'",
        "'Stub status'",
        "'Live error class'",
        "'Live ms'",
    ],
)
def test_shadow_recent_renders_required_columns(field):
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert field in panel, (
        f"recent-rows table header {field!r} missing"
    )


def test_shadow_recent_row_renders_data_fields():
    """Each row must read from the operator-safe projection's
    documented field names (created_at, method, diff_outcome,
    live_status, stub_status, live_error_class, live_duration_ms)."""
    panel = _shadow_panel_snippet(_src(), size=12000)
    for field in (
        "r.created_at",
        "r.method",
        "r.diff_outcome",
        "r.live_status",
        "r.stub_status",
        "r.live_error_class",
        "r.live_duration_ms",
    ):
        assert field in panel, f"row render must read {field!r}"


def test_shadow_summary_bucket_renders_required_fields():
    panel = _shadow_panel_snippet(_src())
    for field in ("b.method", "b.diff_outcome", "b.count"):
        assert field in panel, (
            f"summary bucket render must read {field!r}"
        )


# ── 8. UX states ──────────────────────────────────────────────────────────

def test_shadow_empty_states_exist():
    panel = _shadow_panel_snippet(_src())
    assert 'data-testid="carrier-shadow-summary-empty"' in panel
    assert 'data-testid="carrier-shadow-recent-empty"' in panel
    assert "No DHL Express shadow events recorded yet" in panel
    assert "No DHL Express shadow events yet" in panel


def test_shadow_loading_state_exists():
    panel = _shadow_panel_snippet(_src())
    assert 'data-testid="carrier-shadow-loading"' in panel
    assert "Loading DHL Express shadow log" in panel


def test_shadow_error_state_exists():
    panel = _shadow_panel_snippet(_src())
    assert 'data-testid="carrier-shadow-error"' in panel
    assert "Failed to load DHL Express shadow log" in panel


def test_shadow_refresh_button_wired():
    panel = _shadow_panel_snippet(_src())
    assert 'data-testid="carrier-shadow-refresh-btn"' in panel
    assert "onClick={loadCarrierShadow}" in panel
    assert "↺ Refresh" in panel


def test_shadow_explanation_text_present():
    """The /context requires this exact operator-facing explanation:
    'Shadow mode compares DHL Express live responses against the
    stub while preserving the stub as the operator-facing result.'
    """
    panel = _shadow_panel_snippet(_src())
    needle = (
        "Shadow mode compares DHL Express live responses against the "
        "stub while preserving the stub as the operator-facing result."
    )
    assert needle in panel, (
        "required shadow explanation copy not present verbatim"
    )


def test_shadow_explanation_does_not_imply_live_approved():
    """The explanation must not contain language suggesting live
    production is approved or active."""
    panel = _shadow_panel_snippet(_src())
    for forbidden in (
        "live production approved",
        "Live mode active",
        "Production cutover complete",
        "Live DHL traffic",
    ):
        assert forbidden not in panel, (
            f"phrase {forbidden!r} implies live production approved"
        )


# ── 9. Carrier scope — DHL Express only ───────────────────────────────────

def test_shadow_panel_uses_dhl_express_wording():
    panel = _shadow_panel_snippet(_src())
    occurrences = panel.count("DHL Express")
    assert occurrences >= 3, (
        f"expected >=3 'DHL Express' mentions in shadow panel; "
        f"got {occurrences}"
    )


@pytest.mark.parametrize("forbidden", ["FedEx", "UPS", "fedex"])
def test_shadow_panel_no_other_carriers(forbidden):
    panel = _shadow_panel_snippet(_src(), size=12000)
    assert forbidden not in panel, (
        f"out-of-scope carrier {forbidden!r} in shadow panel"
    )


# ── 10. State + loader wiring ─────────────────────────────────────────────

def test_state_variables_declared():
    src = _src()
    for needle in (
        "carrierShadowSummary",
        "carrierShadowRecent",
        "carrierShadowLoading",
        "carrierShadowError",
    ):
        assert needle in src, f"state variable {needle} not declared"


def test_loader_callback_signature():
    src = _src()
    assert "const loadCarrierShadow = React.useCallback(async () =>" in src


def test_use_effect_loads_on_tab_activation():
    src = _src()
    assert (
        "if (activeTab === 'DHL Express') loadCarrierShadow()" in src
    ), "useEffect must load shadow when DHL Express tab activates"


# ── 11. Existing W-2 surfaces preserved (sanity) ──────────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        "carrier-actions-tab",
        "carrier-shipment-panel",
        "carrier-shipment-timeline",
        "carrier-shipment-label-evidence",
        "carrier-proposals-panel",
        "carrier-confirm-drawer",
        "carrier-confirm-drawer-cancel-warning",
        "carrier-confirm-drawer-handover-note",
    ],
)
def test_existing_w2_testid_preserved(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src, (
        f"W-2 testid {testid!r} no longer present in dashboard.html"
    )


def test_dhl_express_tab_registered():
    src = _src()
    assert "'DHL Express'" in src and "DETAIL_TABS" in src


def test_dashboard_html_braces_balanced():
    """Whole-file `{` / `}` balance — coarse compile sanity check."""
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, (
        f"unbalanced braces in dashboard.html: {{={opens} }}={closes}"
    )

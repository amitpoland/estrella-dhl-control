"""tests/test_dashboard_carrier_copy.py — UI-2c-copy

Source-grep tests for the DHL Express operator-copy correction
pass applied to dashboard.html in UI-2c-copy.

Three fixes from the 2026-05-10 DHL Express operator review:

  F-1  carrier-overview-mode-note was stale (claimed actions
       weren't available; W-2.3 had shipped them).
  F-3  proposal-create info-note + disabled-badge exposed internal
       phase code "W-2.3b" to operators.
  F-4  shadow log diff badge rendered raw technical values
       (shape_mismatch / live_only_error / etc.) without
       human-readable labels.

These tests pin the corrected copy positively, pin absence of the
old stale strings, and confirm no logic / endpoint / testid /
flag changed.
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


# ── F-1: carrier-overview-mode-note reflects current reality ───────────────

def test_overview_mode_note_mentions_actions_live_in_proposals_panel():
    """The corrected mode-note explicitly tells the operator that
    print / hand-over / cancel actions DO exist below."""
    src = _src()
    idx = src.find('data-testid="carrier-overview-mode-note"')
    assert idx != -1
    snippet = src[idx : idx + 800]
    assert (
        "Mark label printed, mark handed to carrier, and cancel actions live in the Proposals panel below."
        in snippet
    ), "mode-note must point operators at the Proposals panel for the three available actions"


def test_overview_mode_note_creates_remains_deferred():
    """The note must still tell operators that creating a new
    shipment is NOT yet available — W-2.3b correctly deferred."""
    src = _src()
    idx = src.find('data-testid="carrier-overview-mode-note"')
    snippet = src[idx : idx + 800]
    assert "Creating a new shipment is not yet available" in snippet


def test_overview_mode_note_no_longer_says_actions_unavailable():
    """The stale wording must be gone."""
    src = _src()
    idx = src.find('data-testid="carrier-overview-mode-note"')
    snippet = src[idx : idx + 800]
    assert (
        "Operator actions (create, print, hand over, cancel) are not available here yet."
        not in snippet
    ), "stale mode-note copy still present"


# ── F-3: no internal phase-code "W-2.3b" in operator-visible copy ──────────

def test_create_info_note_replaced_with_operator_copy():
    """The create-shipment info-note must not reference internal
    phase code; it should use operator-language."""
    src = _src()
    idx = src.find('data-testid="carrier-proposal-create-info-note"')
    assert idx != -1
    snippet = src[idx : idx + 600]
    assert (
        "Creating a new DHL Express shipment requires shipper, recipient, package, value, and service data."
        in snippet
    )
    assert (
        "A dedicated form is planned; until then this proposal is informational only."
        in snippet
    )
    # "W-2.3b" must be gone from this snippet.
    assert "W-2.3b" not in snippet


def test_create_disabled_badge_uses_operator_copy():
    """The disabled-badge must read 'Form pending', not 'Awaiting
    W-2.3b'."""
    src = _src()
    idx = src.find('data-testid="carrier-proposal-create-disabled-badge"')
    assert idx != -1
    # 400-char window covers the open <span> + style props + child content
    # + closing </span>.
    snippet = src[idx : idx + 400]
    assert "Form pending" in snippet, "disabled-badge must read 'Form pending'"
    assert "W-2.3b" not in snippet
    assert "Awaiting W-2.3b" not in snippet


def test_no_operator_visible_w2_3b_anywhere_in_proposal_create_block():
    """Sweep around the entire create_shipment proposal-row JSX
    to confirm the phase code is gone from any operator-visible
    rendered text."""
    src = _src()
    idx = src.find("const isCreate     = p.action === 'create_shipment';")
    assert idx != -1, "create_shipment branch anchor not found"
    snippet = src[idx : idx + 2500]
    assert "W-2.3b" not in snippet, (
        "internal phase code 'W-2.3b' still present in create_shipment "
        "proposal branch"
    )


# ── F-4: shadow log diff outcomes have operator-readable labels ───────────

def test_diff_label_map_exists_with_operator_strings():
    """A diffLabel map renders human-readable strings per outcome.
    Technical value stays on data-row-diff / data-diff-value for
    test infrastructure and filters."""
    src = _src()
    # The map is declared next to diffColor inside the shadow recent
    # rows render.
    needle = "const diffLabel = {"
    idx = src.find(needle)
    assert idx != -1, "diffLabel map not declared"
    snippet = src[idx : idx + 600]
    # Operator-readable labels per outcome:
    for value, label in [
        ("match",           "'Match'"),
        ("shape_mismatch",  "'Shape mismatch'"),
        ("live_only_error", "'Live response error'"),
        ("stub_only_error", "'Stub response error'"),
        ("both_error",      "'Both responses errored'"),
    ]:
        assert f"{value}:" in snippet, f"diffLabel entry {value!r} missing"
        assert label in snippet, f"diffLabel label {label!r} missing"


def test_diff_badge_renders_diff_label_not_raw_value():
    """The badge renders {diffLabel}, not the raw r.diff_outcome."""
    src = _src()
    idx = src.find('data-testid="carrier-shadow-diff-badge"')
    assert idx != -1
    snippet = src[idx : idx + 600]
    # Inside the badge content, we expect {diffLabel}. The raw
    # r.diff_outcome should NOT be the rendered child (it remains
    # exposed via data-row-diff / data-diff-value attributes for
    # tests and filters).
    assert "{diffLabel}" in snippet, (
        "diff badge must render {diffLabel} (operator-readable)"
    )


def test_diff_badge_exposes_technical_value_on_data_attribute():
    """The technical diff_outcome value stays available to tests +
    filters via data-diff-value attribute on the badge."""
    src = _src()
    idx = src.find('data-testid="carrier-shadow-diff-badge"')
    snippet = src[idx : idx + 400]
    assert "data-diff-value={r.diff_outcome || ''}" in snippet, (
        "diff badge must carry data-diff-value with the raw outcome"
    )


def test_recent_row_still_exposes_diff_on_data_row_diff():
    """The row's data-row-diff attribute (set in UI-GAP-1.3) must
    remain — test infrastructure depends on it."""
    src = _src()
    idx = src.find('data-testid="carrier-shadow-recent-row"')
    snippet = src[idx : idx + 400]
    assert "data-row-diff={r.diff_outcome || ''}" in snippet


# ── Hard preservation invariants — UI-2c-copy must NOT change ──────────────

@pytest.mark.parametrize(
    "logic_var",
    [
        "carrierShipments",
        "carrierProposals",
        "carrierConfirmDrawer",
        "carrierShadowSummary",
        "carrierShadowRecent",
        "carrierExecuteEndpointFor",
        "openCarrierConfirmDrawer",
        "executeCarrierProposal",
        "loadCarrierShipments",
        "loadCarrierProposals",
        "loadCarrierShadow",
    ],
)
def test_logic_variable_preserved(logic_var):
    src = _src()
    assert logic_var in src, (
        f"logic variable {logic_var!r} no longer present in dashboard.html"
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/carrier/shipments/by-batch/",
        "/api/v1/carrier/proposals/by-batch/",
        "/api/v1/carrier/actions/mark-label-printed/execute",
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        "/api/v1/carrier/actions/cancel-shipment/execute",
        "/api/v1/carrier/shadow/summary",
        "/api/v1/carrier/shadow/recent",
    ],
)
def test_endpoint_preserved(endpoint):
    src = _src()
    assert endpoint in src, (
        f"endpoint {endpoint!r} no longer in dashboard.html"
    )


@pytest.mark.parametrize(
    "testid",
    [
        "carrier-actions-tab",
        "carrier-overview-mode-note",
        "carrier-shipment-panel",
        "carrier-shipment-detail",
        "carrier-shipment-timeline",
        "carrier-shipment-label-evidence",
        "carrier-proposals-panel",
        "carrier-proposal-row",
        "carrier-proposal-create-info-note",
        "carrier-proposal-create-disabled-badge",
        "carrier-proposal-review-btn",
        "carrier-confirm-drawer",
        "carrier-confirm-drawer-cancel-warning",
        "carrier-confirm-drawer-handover-note",
        "carrier-confirm-drawer-execute-btn",
        "carrier-confirm-drawer-actor-input",
        "carrier-shadow-panel",
        "carrier-shadow-explanation",
        "carrier-shadow-summary-card",
        "carrier-shadow-recent-card",
        "carrier-shadow-recent-row",
        "carrier-shadow-diff-badge",
    ],
)
def test_testid_preserved(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src


# ── No write-surface change ───────────────────────────────────────────────

def test_create_shipment_remains_deferred():
    """The carrier-actions create-shipment endpoint must NOT be a
    target of any apiFetch / fetch / mapping return in the source.
    UI-2c-copy is copy-only; it does not enable any new write."""
    src = _src()
    forbidden = "/api/v1/carrier/actions/create-shipment/execute"
    for pattern in (
        f"apiFetch(`{forbidden}`",
        f"apiFetch(\"{forbidden}\"",
        f"apiFetch('{forbidden}'",
        f"fetch(`{forbidden}`",
        f"return '{forbidden}'",
        f'return "{forbidden}"',
    ):
        assert pattern not in src, (
            f"create-shipment execute endpoint reached via {pattern!r}"
        )


def test_carrier_execute_endpoint_for_still_omits_create_shipment():
    """The action→endpoint map body must still NOT map create_shipment."""
    src = _src()
    sig = "const carrierExecuteEndpointFor = React.useCallback((action) => {"
    idx = src.find(sig)
    assert idx != -1
    body_end = src.find("}, []);", idx)
    body = src[idx + len(sig) : body_end]
    assert "create_shipment" not in body


# ── Carrier scope discipline ──────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", ["FedEx IP", "FedEx Priority", "Estrella Atlas", "Shipping Operations"])
def test_out_of_scope_design_content_absent(forbidden):
    src = _src()
    assert forbidden not in src


def test_dhl_express_wording_lock_preserved():
    src = _src()
    assert "'DHL Express'" in src, "DHL Express tab label must remain"


def test_w2_1a_no_generic_carrier_phrases_anywhere_in_overview_block():
    """Mode-note is the only spot that previously used 'carrier'
    operator-visibly. After UI-2c-copy it uses 'DHL Express'."""
    src = _src()
    idx = src.find('data-testid="carrier-overview-mode-note"')
    snippet = src[idx : idx + 800]
    assert "DHL Express shipments" in snippet
    # Forbidden generic phrases the operator UI used to carry:
    assert "carrier shipments" not in snippet
    assert "Carrier Shipments" not in snippet


# ── Brace balance / file sanity ───────────────────────────────────────────

def test_dashboard_html_braces_balanced():
    src = _src()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"

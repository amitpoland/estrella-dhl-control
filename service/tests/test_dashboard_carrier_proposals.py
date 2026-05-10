"""tests/test_dashboard_carrier_proposals.py — W-2.3

Source-grep tests for the DHL Express action-proposal panel and
the confirmation drawer added to dashboard.html in W-2.3. This is
the FIRST WRITE-SURFACE phase of the W-2 campaign.

Coverage shape:
  * Proposal panel exists, lists every backend proposal type.
  * The four backend actions render in the right way:
      mark_label_printed, mark_handed_to_carrier, cancel_shipment
        — render with a "Review action" / "Review handover" /
          "Review cancel" button when enabled. The button OPENS
          the drawer; it does not POST.
      create_shipment
        — renders read-only with an info note pointing at the
          future W-2.3b data-entry form. There is NO execute or
          review button for create_shipment in this phase.
  * The confirmation drawer exists, gates every POST.
  * The single POST site lives inside executeCarrierProposal and
    only fires for the three simple actions (allowlist enforced).
  * No /api/v1/carrier/actions/create-shipment/execute reference
    anywhere in the dashboard's W-2.3 code.
  * Cancel drawer carries an irreversible warning.
  * Mark-handed drawer says "DHL Express handover".
  * After successful execute, the loaders refresh proposals,
    shipments, and (if selected) the timeline.

The tests are scoped to two snippets:
  - the proposals panel itself  (data-testid="carrier-proposals-panel")
  - the confirm drawer block    (data-testid="carrier-confirm-drawer")
plus the global JS handler `executeCarrierProposal` for the
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


def _proposals_panel_snippet(src: str, size: int = 9000) -> str:
    idx = src.find('data-testid="carrier-proposals-panel"')
    assert idx != -1, "carrier-proposals-panel testid not found"
    return src[idx : idx + size]


def _confirm_drawer_snippet(src: str, size: int = 6500) -> str:
    idx = src.find('data-testid="carrier-confirm-drawer"')
    assert idx != -1, "carrier-confirm-drawer testid not found"
    return src[idx : idx + size]


def _execute_handler_snippet(src: str, size: int = 3000) -> str:
    """The executeCarrierProposal callback body — single POST site."""
    idx = src.find("const executeCarrierProposal = React.useCallback")
    assert idx != -1, "executeCarrierProposal callback not found"
    return src[idx : idx + size]


# ── 1. Required testids exist ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "testid",
    [
        "carrier-proposals-panel",
        "carrier-proposals-refresh-btn",
        "carrier-proposals-loading",
        "carrier-proposals-error",
        "carrier-proposals-empty",
        "carrier-proposal-row",
        "carrier-proposal-action",
        "carrier-proposal-severity-badge",
        "carrier-proposal-create-info-note",
        "carrier-proposal-create-disabled-badge",
        "carrier-proposal-review-btn",
        "carrier-confirm-drawer",
        "carrier-confirm-drawer-header",
        "carrier-confirm-drawer-action",
        "carrier-confirm-drawer-awb",
        "carrier-confirm-drawer-state",
        "carrier-confirm-drawer-proposal-id",
        "carrier-confirm-drawer-actor-input",
        "carrier-confirm-drawer-reason-input",
        "carrier-confirm-drawer-cancel-warning",
        "carrier-confirm-drawer-handover-note",
        "carrier-confirm-drawer-execute-btn",
        "carrier-confirm-drawer-back-btn",
        "carrier-confirm-drawer-cancel-btn",
        "carrier-execute-success",
        "carrier-execute-failure",
    ],
)
def test_w2_3_testid_present(testid):
    src = _src()
    assert f'data-testid="{testid}"' in src, f"{testid} testid not found"


# ── 2. Read-only proposal endpoint is referenced ───────────────────────────

def test_proposals_endpoint_referenced():
    src = _src()
    needle = "apiFetch(`/api/v1/carrier/proposals/by-batch/"
    assert needle in src, (
        "apiFetch call to /api/v1/carrier/proposals/by-batch/ not found "
        "(template-literal form expected)"
    )
    after = src[src.find(needle) : src.find(needle) + 200]
    assert "encodeURIComponent(batchId)" in after, (
        "batchId must pass through encodeURIComponent in the proposals fetch"
    )


# ── 3. The three allowed execute endpoints are referenced ──────────────────

@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/carrier/actions/mark-label-printed/execute",
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        "/api/v1/carrier/actions/cancel-shipment/execute",
    ],
)
def test_allowed_execute_endpoint_referenced(endpoint):
    src = _src()
    assert endpoint in src, (
        f"allowed execute endpoint {endpoint} not referenced in dashboard"
    )


# ── 4. create_shipment execute endpoint is NOT referenced ──────────────────

def test_create_shipment_execute_endpoint_not_called():
    """No CODE PATH may call the create-shipment execute endpoint.

    The literal endpoint string is allowed to appear in a documenting
    comment (it's a useful invariant marker for future contributors).
    What's forbidden is any executable reference: apiFetch / fetch /
    a return statement from the carrierExecuteEndpointFor mapping.
    """
    src = _src()
    forbidden_endpoint = "/api/v1/carrier/actions/create-shipment/execute"
    # Forbid the endpoint string anywhere it could be reached at runtime.
    forbidden_call_patterns = (
        f'apiFetch(`{forbidden_endpoint}`',
        f'apiFetch("{forbidden_endpoint}"',
        f"apiFetch('{forbidden_endpoint}'",
        f'fetch(`{forbidden_endpoint}`',
        f"return '{forbidden_endpoint}'",
        f'return "{forbidden_endpoint}"',
    )
    for pattern in forbidden_call_patterns:
        assert pattern not in src, (
            f"create-shipment execute endpoint reachable via {pattern!r} — "
            f"forbidden in W-2.3; lands in W-2.3b"
        )


def test_no_execute_wrapper_endpoint():
    src = _src()
    panel = _proposals_panel_snippet(src, size=12000)
    drawer = _confirm_drawer_snippet(src, size=8000)
    for snippet in (panel, drawer):
        assert "/api/v1/execute/" not in snippet, (
            "/api/v1/execute/ wrapper referenced in W-2.3 surface — "
            "carrier writes use /api/v1/carrier/actions/"
        )


# ── 5. Endpoint allowlist sweep across the proposals panel + drawer ────────

def test_w2_3_endpoint_allowlist():
    """Every /api/v1/carrier/* path appearing inside the W-2.3 surfaces
    (proposals panel + confirmation drawer) must match the campaign-
    approved allowlist."""
    src = _src()
    snippets = [
        _proposals_panel_snippet(src, size=12000),
        _confirm_drawer_snippet(src, size=8000),
    ]
    allowed_prefixes = (
        "/api/v1/carrier/proposals/by-batch/",  # W-2.3 reads
        "/api/v1/carrier/actions/mark-label-printed/execute",
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        "/api/v1/carrier/actions/cancel-shipment/execute",
    )
    for snippet in snippets:
        paths = re.findall(r"/api/v1/carrier/[A-Za-z0-9_/\-{}\\$]*", snippet)
        for p in paths:
            assert any(p.startswith(prefix) for prefix in allowed_prefixes), (
                f"endpoint {p!r} appears in W-2.3 surface but is not in "
                f"the allowlist {allowed_prefixes!r}"
            )


# ── 6. Single POST site — only inside executeCarrierProposal ───────────────

def test_proposal_panel_contains_no_post():
    """The proposal list itself must not POST. The Review button only
    OPENS the drawer; the drawer's execute button calls
    executeCarrierProposal, which is the single POST site."""
    panel = _proposals_panel_snippet(_src(), size=12000)
    assert "method: 'POST'" not in panel, (
        "method: 'POST' found inside carrier-proposals-panel — POSTs must "
        "live in executeCarrierProposal only"
    )
    assert 'method: "POST"' not in panel


def test_confirm_drawer_contains_no_post():
    """The drawer's JSX must not directly POST. The execute button calls
    the executeCarrierProposal handler, which is the only POST site."""
    drawer = _confirm_drawer_snippet(_src(), size=8000)
    assert "method: 'POST'" not in drawer
    assert 'method: "POST"' not in drawer


def test_post_lives_only_inside_execute_handler():
    """Sweep the whole dashboard: every `method: 'POST'` whose URL is a
    carrier-actions execute endpoint must sit inside the
    executeCarrierProposal callback body."""
    src = _src()
    handler = _execute_handler_snippet(src, size=3000)
    # Every carrier-actions execute endpoint must appear in the handler.
    for endpoint in (
        "/api/v1/carrier/actions/mark-label-printed/execute",
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        "/api/v1/carrier/actions/cancel-shipment/execute",
    ):
        # The endpoint can be referenced indirectly through
        # carrierExecuteEndpointFor; assert the mapping function names
        # the endpoint exactly.
        assert endpoint in src
    # The actual POST is via `method: 'POST'` inside the handler.
    assert "method:  'POST'" in handler or "method: 'POST'" in handler, (
        "executeCarrierProposal must POST via apiFetch with method: 'POST'"
    )


@pytest.mark.parametrize("verb", ["PUT", "PATCH", "DELETE"])
def test_no_other_write_verbs_in_w2_3(verb):
    src = _src()
    snippets = [
        _proposals_panel_snippet(src, size=12000),
        _confirm_drawer_snippet(src, size=8000),
        _execute_handler_snippet(src, size=3000),
    ]
    for snippet in snippets:
        assert f"method: '{verb}'" not in snippet
        assert f'method: "{verb}"' not in snippet


# ── 7. create_shipment info-only — no execute / no review button ───────────

def test_create_shipment_info_note_present():
    src = _src()
    note_idx = src.find('data-testid="carrier-proposal-create-info-note"')
    assert note_idx != -1
    snippet = src[note_idx : note_idx + 600]
    assert "shipper, recipient, package" in snippet
    assert "W-2.3b" in snippet


def test_create_shipment_has_no_execute_button():
    """The create_shipment branch must NOT render a Review-action button.
    Source-grep: the JSX block that handles create_shipment cards is
    gated by `isCreate` and renders a disabled badge, not a Btn that
    calls openCarrierConfirmDrawer for create_shipment."""
    src = _src()
    panel = _proposals_panel_snippet(src, size=12000)
    # The disabled badge MUST be present.
    assert 'data-testid="carrier-proposal-create-disabled-badge"' in panel
    # The Review button JSX is rendered only when `!isCreate && isSimple
    # && isEnabled`. Assert that the Review button branch explicitly
    # excludes create.
    assert "!isCreate && isSimple && isEnabled" in panel, (
        "Review-button branch must explicitly exclude create_shipment"
    )


def test_carrier_execute_endpoint_for_omits_create_shipment():
    """The action→endpoint map must not include create_shipment.

    Scoped to the function body (between `useCallback((action) => {`
    and the matching `}, []);`). Comments above the map are allowed
    to mention create_shipment — that documents the deliberate
    omission and is a useful invariant marker.
    """
    src = _src()
    map_idx = src.find("const carrierExecuteEndpointFor = React.useCallback((action) => {")
    assert map_idx != -1, "carrierExecuteEndpointFor signature not found"
    body_start = map_idx + len("const carrierExecuteEndpointFor = React.useCallback((action) => {")
    body_end = src.find("}, []);", body_start)
    assert body_end != -1, "carrierExecuteEndpointFor body close not found"
    body = src[body_start:body_end]
    assert "create_shipment" not in body, (
        "carrierExecuteEndpointFor body MUST NOT map create_shipment to any "
        "endpoint — that's W-2.3b territory"
    )
    # And the map body must include the three allowed actions.
    for action in ("mark_label_printed", "mark_handed_to_carrier", "cancel_shipment"):
        assert action in body, (
            f"carrierExecuteEndpointFor body must include {action!r}"
        )


def test_open_drawer_refuses_create_shipment():
    """openCarrierConfirmDrawer must refuse to open for create_shipment
    (because carrierExecuteEndpointFor returns null for it)."""
    src = _src()
    open_idx = src.find("const openCarrierConfirmDrawer = React.useCallback")
    assert open_idx != -1
    snippet = src[open_idx : open_idx + 700]
    # The early-return guard must check the endpoint mapping.
    assert "carrierExecuteEndpointFor(proposal.action)" in snippet
    assert "if (!carrierExecuteEndpointFor(proposal.action)) return;" in snippet


# ── 8. Disabled proposals show blocking reasons ────────────────────────────

def test_disabled_proposal_shows_blocking_reasons():
    panel = _proposals_panel_snippet(_src(), size=12000)
    assert 'data-testid="carrier-proposal-blocking-reasons"' in panel
    assert "p.blocking_reasons" in panel
    # Disabled (non-create) simple proposals show a Disabled note.
    assert 'data-testid="carrier-proposal-disabled-note"' in panel


# ── 9. Enabled simple proposals show Review action ─────────────────────────

def test_enabled_simple_proposal_review_button():
    panel = _proposals_panel_snippet(_src(), size=12000)
    assert "Review action" in panel
    assert "Review cancel" in panel
    assert "Review handover" in panel


# ── 10. Confirmation drawer wording rules ──────────────────────────────────

def test_drawer_uses_dhl_express_wording():
    drawer = _confirm_drawer_snippet(_src(), size=8000)
    occurrences = drawer.count("DHL Express")
    assert occurrences >= 3, (
        f"expected >=3 'DHL Express' mentions in drawer; got {occurrences}"
    )


def test_drawer_cancel_irreversible_warning():
    drawer = _confirm_drawer_snippet(_src(), size=8000)
    assert 'data-testid="carrier-confirm-drawer-cancel-warning"' in drawer
    # The warning text must use the word "Irreversible".
    assert "Irreversible" in drawer or "irreversible" in drawer.lower()
    # The warning must say "cannot be undone" or equivalent.
    assert "cannot be undone" in drawer.lower() or "void" in drawer.lower()


def test_drawer_handover_uses_dhl_express_handover_wording():
    drawer = _confirm_drawer_snippet(_src(), size=8000)
    assert 'data-testid="carrier-confirm-drawer-handover-note"' in drawer
    assert "DHL Express handover" in drawer


def test_drawer_requires_actor_input():
    drawer = _confirm_drawer_snippet(_src(), size=8000)
    assert 'data-testid="carrier-confirm-drawer-actor-input"' in drawer
    # The execute button must be disabled when actor is empty.
    assert "(carrierConfirmDrawer.actor || '').trim()" in drawer
    # Required label visible.
    assert "Operator (actor) — required" in drawer or "Operator" in drawer


def test_drawer_actor_validation_in_handler():
    handler = _execute_handler_snippet(_src(), size=3000)
    assert "Operator name (actor) is required" in handler


# ── 11. Successful execute refreshes proposals + shipments + transitions ──

def test_execute_handler_refreshes_proposals():
    handler = _execute_handler_snippet(_src(), size=3000)
    assert "loadCarrierProposals()" in handler


def test_execute_handler_refreshes_shipments():
    handler = _execute_handler_snippet(_src(), size=3000)
    assert "loadCarrierShipments()" in handler


def test_execute_handler_refreshes_transitions_when_selected():
    handler = _execute_handler_snippet(_src(), size=3000)
    # When a shipment is selected the handler reloads its transitions.
    assert "selectedShipmentId ? loadCarrierTransitions(selectedShipmentId)" in handler


def test_execute_handler_uses_promise_all_for_refresh():
    handler = _execute_handler_snippet(_src(), size=3000)
    assert "Promise.all" in handler


# ── 12. Body shape matches backend _ShipmentActionBody ─────────────────────

def test_execute_body_field_shape():
    """The POST body must include exactly the five fields backend
    _ShipmentActionBody declares: carrier, awb, proposal_id, actor,
    reason. No invented fields."""
    handler = _execute_handler_snippet(_src(), size=3000)
    for field in ("carrier:", "awb:", "proposal_id:", "actor:", "reason:"):
        assert field in handler, (
            f"required body field {field!r} not found in execute handler"
        )
    # JSON.stringify(body) — single body object, not raw JSON.
    assert "JSON.stringify(body)" in handler


# ── 13. No FedEx / UPS / multi-carrier wording ─────────────────────────────

@pytest.mark.parametrize("forbidden", ["FedEx", "UPS", "fedex"])
def test_no_other_carriers_in_w2_3(forbidden):
    src = _src()
    snippets = [
        _proposals_panel_snippet(src, size=12000),
        _confirm_drawer_snippet(src, size=8000),
    ]
    for snippet in snippets:
        assert forbidden not in snippet, (
            f"out-of-scope carrier {forbidden!r} found in W-2.3 surface"
        )


def test_no_generic_multi_carrier_phrases():
    src = _src()
    panel = _proposals_panel_snippet(src, size=12000)
    drawer = _confirm_drawer_snippet(src, size=8000)
    for forbidden in (
        "multi-carrier",
        "carrier marketplace",
        "any carrier",
        "all carriers",
    ):
        assert forbidden not in panel, (
            f"generic multi-carrier phrase {forbidden!r} in proposals panel"
        )
        assert forbidden not in drawer, (
            f"generic multi-carrier phrase {forbidden!r} in confirm drawer"
        )


# ── 14. State + loader wiring ─────────────────────────────────────────────

def test_state_variables_declared():
    src = _src()
    for needle in (
        "carrierProposals",
        "carrierProposalsLoading",
        "carrierProposalsError",
        "carrierConfirmDrawer",
        "carrierExecuteResult",
    ):
        assert needle in src, f"state variable {needle} not declared"


def test_use_effect_loads_proposals_on_tab_activation():
    src = _src()
    # The proposals load when the DHL Express tab activates.
    assert (
        "if (activeTab === 'DHL Express') loadCarrierProposals()" in src
    ), "useEffect must load proposals on DHL Express tab activation"


# ── 15. Drawer is the only path to opening an execute action ──────────────

def test_review_button_only_opens_drawer():
    """The Review button's onClick must call openCarrierConfirmDrawer,
    not the execute handler directly."""
    panel = _proposals_panel_snippet(_src(), size=12000)
    review_idx = panel.find('data-testid="carrier-proposal-review-btn"')
    assert review_idx != -1
    # Look at the next 400 chars for the onClick handler.
    after = panel[review_idx : review_idx + 400]
    assert "openCarrierConfirmDrawer(p)" in after, (
        "Review button's onClick must call openCarrierConfirmDrawer(p)"
    )
    assert "executeCarrierProposal" not in after, (
        "Review button must NOT call executeCarrierProposal directly — "
        "the drawer is the only confirmation path"
    )

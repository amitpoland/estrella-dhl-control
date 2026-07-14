"""
test_v2_dhl_parity_slice2b.py — Slice 2B contract fence.

Pins the V2 Shipment Detail DHL parity work: the live tracking card, the nine
pz-api DHL wrappers, the state-aware wired action controls, and the safety
invariants (send confirmation-gated, no duplicate DHL engine, no wFirma/PZ/
accounting/inventory write as a DHL side effect). Static source-grep only — no
server, no JSX execution (mirrors test_c03_shipment_detail_v2_ux.py).
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "shipment-detail-page.jsx"
_PZAPI = _V2 / "pz-api.js"


def _detail() -> str:
    return _DETAIL.read_text(encoding="utf-8")


def _api() -> str:
    return _PZAPI.read_text(encoding="utf-8")


# ── pz-api wrappers exist and target the canonical routes ─────────────────────

def test_pz_api_has_all_dhl_wrappers():
    src = _api()
    for name in (
        "getDhlTracking:", "refreshDhlTracking:", "scanDhlInbox:",
        "markDhlEmailReceived:", "generatePolishDescription:", "generateDsk:",
        "buildDhlReplyPackage:", "sendDhlReply:", "getDhlActionState:",
    ):
        assert name in src, f"pz-api.js missing DHL wrapper {name!r}"


def test_tracking_wrapper_targets_canonical_route():
    """The tracking card is a CLIENT of the backend tracking authority — the
    browser never calls DHL directly."""
    src = _api()
    assert "${BASE}/tracking/" in src, "getDhlTracking must call /api/v1/tracking/{awb}"
    # no direct carrier calls from the transport layer
    assert "dhl.com" not in src, "pz-api must not call DHL carrier hosts directly"


def test_dsk_routes_corrected_not_misrouted():
    """Regression pin: Generate-DSK → /api/v1/dsk/generate and Build-Package →
    /api/v1/dsk/email-package (previously both mis-routed to the DHL
    generate-customs-package endpoint)."""
    src = _api()
    assert "${BASE}/dsk/generate" in src
    assert "${BASE}/dsk/email-package" in src


def test_send_reply_uses_standard_dhl_route():
    """Send wires to the standard admin/logistics /api/v1/dhl/send-reply/{id}
    route (not the privileged execute path the browser session cannot present)."""
    src = _api()
    assert "${BASE}/dhl/send-reply/" in src


def test_dhl_wrappers_touch_no_financial_authority():
    """Authority separation: no DHL wrapper may target a wFirma / PZ / proforma /
    invoice / inventory write route."""
    src = _api()
    # isolate the DHL/tracking wrapper block
    start = src.index("getDhlTracking:")
    end = src.index("getDhlActionState:")
    block = src[start:end]
    for forbidden in ("/wfirma/", "/pz/process", "/proforma/post", "/proforma/create",
                      "/inventory/", "/invoice"):
        assert forbidden not in block, (
            f"DHL wrapper block must not target a financial/inventory route ({forbidden})"
        )


# ── V2 DhlTab: tracking card + wired actions ─────────────────────────────────

def test_tracking_card_present_and_wired():
    src = _detail()
    assert 'data-testid="dhl-tracking-card"' in src
    assert 'data-testid="dhl-tracking-refresh"' in src
    assert "window.PzApi.getDhlTracking" in src
    assert "window.PzApi.refreshDhlTracking" in src
    # unavailable state must be honest, with a reason
    assert 'data-testid="dhl-tracking-unavailable"' in src


def test_actions_call_existing_backend_wrappers():
    src = _detail()
    for call in (
        "window.PzApi.scanDhlInbox", "window.PzApi.markDhlEmailReceived",
        "window.PzApi.generatePolishDescription", "window.PzApi.generateDsk",
        "window.PzApi.buildDhlReplyPackage", "window.PzApi.sendDhlReply",
    ):
        assert call in src, f"DhlTab must call {call}"


def test_action_buttons_are_state_aware():
    """Each control renders a single truthful backend-derived state."""
    src = _detail()
    assert "function DhlActionButton(" in src
    assert "data-action-state={state}" in src
    # the five-state vocabulary is present in the derivation
    for token in ("'available'", "'completed'", "'blocked'", "'running'"):
        assert token in src, f"state token {token} missing from DhlActionButton wiring"


def test_send_reply_is_confirmation_gated():
    """Send opens an explicit confirmation and is never auto-fired."""
    src = _detail()
    assert 'data-testid="send-reply-confirm"' in src
    assert 'data-testid="send-reply-confirm-yes"' in src
    # the send button opens the confirm dialog, it does not call sendDhlReply directly
    assert "onClick={() => setConfirmSend(true)}" in src


def test_all_six_dhl_action_testids_preserved():
    """Lesson M: every capability stays visible — the six DHL testids survive the
    read-only → wired conversion."""
    src = _detail()
    for tid in ("scan-dhl-inbox", "mark-email-received", "generate-polish-desc",
                "generate-dsk", "build-reply-package", "send-reply"):
        assert f'testid="{tid}"' in src, f"DHL action testid '{tid}' lost"


def test_no_duplicate_dhl_engine_in_frontend():
    """The page reuses window.PzApi (transport authority) — it does not open its
    own raw fetch to a DHL route or a carrier host (no second engine). Note: the
    recipient email 'odprawacelna@dhl.com' in the send confirmation is fine — the
    check targets carrier-HOST URLs and raw DHL-route fetches only."""
    src = _detail()
    assert "//dhl.com" not in src and "dhl.com/" not in src, "no direct DHL carrier-host URL"
    assert "fetch('/api/v1/dhl" not in src and 'fetch("/api/v1/dhl' not in src


def test_command_success_refreshes_detail():
    """A successful command reloads the batch detail (readiness + timeline +
    documents refresh from truth) rather than optimistic-only local state."""
    src = _detail()
    # DhlActionsPanel.run calls onReload after a successful command
    assert "if (onReload) onReload();" in src


# ── TimelineTab consumes the 7-state read-model ──────────────────────────────

def test_timeline_consumes_state_field():
    src = _detail()
    assert "data-state={m.state}" in src, "timeline must render the per-milestone state"
    # completed counter counts ONLY completed
    assert "m.state === 'completed'" in src
    # the not_applicable + blocked states are surfaced
    assert "not_applicable" in src and "blocked" in src

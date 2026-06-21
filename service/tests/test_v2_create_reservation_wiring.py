"""
test_v2_create_reservation_wiring.py — Create Reservation button (Lesson M).

The V2 Reservation tab's "Create Reservation" button must EITHER execute a real
backend action OR be disabled with the exact canonical backend reason — it must
not be a visible no-op.

Operator decision (this task): wire it to the LIVE wFirma reservation endpoint
behind an explicit confirm, gated on the CANONICAL reservation readiness
(GET /wfirma/reservation-preview — distinct from the proforma post readiness):
  - reservation readiness BLOCKED → button disabled, exact backend blocker shown,
    NO request fired.
  - reservation readiness CLEAR → click → confirm → POST /wfirma/reservations/create.
  - success → refresh reservation preview + proforma readiness + draft.
  - failure (409 gate / 502 wFirma) → show the backend error/code.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"
_PZAPI = _V2 / "pz-api.js"


@pytest.fixture(scope="module")
def detail():
    return _DETAIL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pzapi():
    return _PZAPI.read_text(encoding="utf-8")


# ── pz-api transport ─────────────────────────────────────────────────────────

def test_pzapi_has_reservation_methods(pzapi):
    assert "getReservationPreview:" in pzapi
    assert "createReservation:" in pzapi
    assert "/wfirma/reservation-preview/" in pzapi
    assert "/wfirma/reservations/create" in pzapi
    # createReservation posts batch_id + client_name
    assert "batch_id: batchId, client_name: clientName" in pzapi


# ── the button is wired (Lesson M): onClick when enabled, gated when blocked ──

def test_create_reservation_button_has_onclick_and_testid(detail):
    # find the Create Reservation button block
    idx = detail.index('data-testid="reservation-create-btn"')
    blk = detail[idx - 400:idx + 200]
    assert "onClick=" in blk                       # not a no-op anymore
    assert "onCreateReservation" in blk
    assert 'data-testid="reservation-create-btn"' in detail


def test_button_gated_on_reservation_readiness_not_post(detail):
    # the button's enabled state is the reservation gate (resvCanCreate),
    # NOT the proforma post readiness (isBlocked).
    assert "const resvCanCreate = !!reservationReady && !reservationExists && !reservationBusy;" in detail
    idx = detail.index('data-testid="reservation-create-btn"')
    blk = detail[idx - 400:idx + 100]
    assert "disabled={!resvCanCreate}" in blk
    # disabled-state title is the exact backend reservation reason
    assert "resvDisabledReason" in blk


def test_disabled_reason_is_canonical_backend_blocker(detail):
    # the reason comes from the reservation-preview blocking_reasons (batch + client)
    assert "reservation-blocked-reason" in detail
    assert "const reservationReasons = [" in detail
    assert "reservationPreview && reservationPreview.blocking_reasons" in detail
    assert "reservationDoc && reservationDoc.blocking_reasons" in detail
    # readiness derives from ready_to_create AND the draft's client doc.ready
    assert "reservationPreview.ready_to_create && reservationDoc && reservationDoc.ready" in detail


def test_no_request_when_blocked(detail):
    # clicking while blocked is a no-op (guarded by resvCanCreate)
    idx = detail.index('data-testid="reservation-create-btn"')
    blk = detail[idx - 400:idx + 100]
    assert "resvCanCreate && onCreateReservation" in blk
    # the confirm modal's create button is also disabled unless reservationReady
    midx = detail.index('data-testid="reservation-confirm-create"')
    mblk = detail[midx - 300:midx + 100]
    assert "!reservationReady" in mblk


# ── confirm → live write → backend error / refresh ───────────────────────────

def test_confirm_modal_calls_create_reservation(detail):
    assert "reservation-confirm-modal" in detail
    assert "onClick={doCreateReservation}" in detail
    assert "window.PzApi.createReservation(batchId, clientName)" in detail


def test_success_refreshes_all_three(detail):
    # on success: refresh reservation preview + proforma readiness + draft
    i = detail.index("const doCreateReservation")
    blk = detail[i:i + 1400]
    assert "loadReservationPreview();" in blk
    assert "reloadReadiness();" in blk
    assert "draftHook && draftHook.refresh && draftHook.refresh();" in blk


def test_failure_shows_backend_error(detail):
    i = detail.index("const doCreateReservation")
    blk = detail[i:i + 1400]
    # parses the backend {code,error} out of the "HTTP <status>: <body>" message
    assert "setReservationResult({ ok: false" in blk
    assert "b.code" in blk and "b.error" in blk
    assert "reservation-inline-error" in detail or "reservation-error" in detail


def test_preview_fetch_is_operator_action_not_mount(detail):
    # the reservation preview loads when the Reservation tab is opened (operator
    # action), not auto on page mount (Lesson F).
    assert "if (activeTab === 'reservation') loadReservationPreview();" in detail


# ── incorporates the #700 frontend-design nits (token + testid) ──────────────

def test_convert_button_has_disabled_reason_title(detail):
    # the Convert button in the reservation tab footer must show why it is
    # disabled (frontend-design §5.2/§6.1) — convertDisabledReason is passed through.
    assert "convertDisabledReason={convertDisabledReason}" in detail
    idx = detail.index('data-testid="reservation-convert-btn"')
    blk = detail[idx - 260:idx]
    assert "title=" in blk and "convertDisabledReason" in blk


def test_includes_700_nits(detail):
    assert "'#F44'" not in detail                  # the hardcoded red is gone
    # approveError span now uses the token
    aidx = detail.index("{approveError}")
    assert "var(--badge-red-text)" in detail[aidx - 120:aidx]
    assert 'data-testid="reservation-create-btn"' in detail


# ── V1 untouched (Lesson F) ──────────────────────────────────────────────────

def test_v1_not_touched():
    for v1 in ("dashboard.html", "shipment-detail.html"):
        p = _V2.parent / v1
        if p.is_file():
            assert "createReservation" not in p.read_text(encoding="utf-8", errors="ignore")


# ── hardening salvaged from the superseded #703 guard (architecture-neutral) ──
# These pin contracts the #702 guard did not yet assert. They do NOT change the
# #702 architecture (reservation-preview gate); they only strengthen the wire.

def test_create_reservation_is_mutation_postm(pzapi):
    """The live wFirma write must ride the mutation path (_postM → X-Operator
    audit identity), never a read-like _post / _get."""
    i = pzapi.index("createReservation:")
    body = pzapi[i:i + 200]
    assert "_postM(" in body, (
        "createReservation is a live wFirma write — must use _postM (X-Operator audit)"
    )


def test_no_raw_fetch_to_reservation_endpoint_in_jsx(detail):
    """The reservation write must only ever leave through PzApi.createReservation —
    never a raw fetch/apiFetch in the page component."""
    for bad in (
        "apiFetch('/api/v1/wfirma/reservations/create'",
        'apiFetch("/api/v1/wfirma/reservations/create"',
        "fetch('/api/v1/wfirma/reservations/create'",
        'fetch("/api/v1/wfirma/reservations/create"',
    ):
        assert bad not in detail, f"page must not call the reservation endpoint directly: {bad!r}"


def test_backend_reservation_create_route_exists():
    """The wired path must target a real, registered backend route (no dangling
    wire)."""
    routes = (_V2.parent.parent / "api" / "routes_wfirma_reservation.py").read_text(
        encoding="utf-8", errors="replace")
    assert 'prefix="/api/v1/wfirma"' in routes, "router prefix must be /api/v1/wfirma"
    assert '@router.post("/reservations/create"' in routes, (
        "POST /api/v1/wfirma/reservations/create must exist (the button's target)"
    )


def test_old_inert_button_form_is_gone(detail):
    """Regression: the pre-existing enabled-and-inert Create Reservation button
    (no onClick) must never reappear."""
    assert '<Btn variant="outline" disabled={isBlocked}>Create Reservation</Btn>' not in detail, (
        "the enabled-and-inert Create Reservation button must not return (Lesson M)"
    )

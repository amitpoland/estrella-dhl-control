"""
test_v2_reservation_create_wiring.py — static-contract guard for the Atlas-V2
"Create Reservation" button wiring (Lesson M five-state truth model).

Background
----------
On origin/main the Reservation tab's "Create Reservation" <Btn> in
`v2/proforma-detail.jsx` had NO onClick handler. Once `!isBlocked` it rendered
as an ENABLED button that did nothing when clicked — an "enabled-and-inert"
control that violates the Lesson M five-state UI truth model (a control must be
either `available` = wired, or disabled with an explicit reason).

A real reservation-create backend exists and is the SOLE authority:
  POST /api/v1/wfirma/reservations/create  body: { batch_id, client_name }
  → wfirma_reservation_create.create_one_reservation (10 gates, atomic
    pending|failed → submitting transition; idempotent; never raises).

Disposition: WIRE the button through PzApi (transport-only) with an operator
confirmation modal. This guard pins the wiring so it cannot silently regress to
enabled-and-inert, and proves the transport/authority/V1-freeze contracts.

Static source-grep only — no server, no browser. V2-only; V1 pages must stay
frozen (Lesson F).
"""
from __future__ import annotations

import pathlib

_ROOT   = pathlib.Path(__file__).resolve().parents[1]          # service/
_V2     = _ROOT / "app" / "static" / "v2"
_STATIC = _ROOT / "app" / "static"
_DETAIL = _V2 / "proforma-detail.jsx"
_PZAPI  = _V2 / "pz-api.js"
_ROUTES = _ROOT / "app" / "api" / "routes_wfirma_reservation.py"


def _detail() -> str:
    return _DETAIL.read_text(encoding="utf-8", errors="replace")


def _pzapi() -> str:
    return _PZAPI.read_text(encoding="utf-8", errors="replace")


# ── Transport layer (pz-api.js) ───────────────────────────────────────────────

def test_pzapi_exposes_create_reservation_mutation():
    """PzApi must expose createWfirmaReservation as a mutation (_postM) to the
    exact backend path, sending only the backend contract fields."""
    src = _pzapi()
    assert "createWfirmaReservation:" in src, "PzApi must expose createWfirmaReservation"
    i = src.index("createWfirmaReservation:")
    body = src[i:i + 400]
    assert "_postM(" in body, (
        "reservation create is a live wFirma write — must use _postM (X-Operator "
        "audit identity), not _get/_post"
    )
    assert "/wfirma/reservations/create" in body, "must POST to /wfirma/reservations/create"
    assert "batch_id:" in body and "client_name:" in body, (
        "must send the backend CreateReservationRequest fields (batch_id, client_name)"
    )


def test_pzapi_create_reservation_is_transport_only():
    """Layer rule (Lesson F): the transport method carries no business logic —
    no local readiness/legality decisions live in pz-api.js."""
    src = _pzapi()
    i = src.index("createWfirmaReservation:")
    body = src[i:i + 400]
    for forbidden in ("if (", "ready", ".filter(", "blocking_reasons"):
        assert forbidden not in body, (
            f"pz-api.js createWfirmaReservation must be transport-only — found {forbidden!r}"
        )


# ── Button wiring (proforma-detail.jsx) ───────────────────────────────────────

def test_create_reservation_button_is_wired_not_inert():
    """The Create Reservation <Btn> must carry the testid AND an onClick handler
    — never enabled-and-inert (Lesson M)."""
    src = _detail()
    assert 'data-testid="reservation-create-btn"' in src, (
        "Create Reservation button must have data-testid='reservation-create-btn'"
    )
    i = src.index('data-testid="reservation-create-btn"')
    block = src[i - 320:i + 60]
    assert "onClick={canCreate ? onCreateReservation : undefined}" in block, (
        "Create Reservation button must be wired (onClick) — enabled-and-inert is a "
        "Lesson M violation"
    )
    assert "disabled={!canCreate}" in block, (
        "Create Reservation button must be gated on backend readiness (disabled={!canCreate})"
    )


def test_old_inert_button_form_is_gone():
    """Regression: the pre-existing enabled-and-inert form must not return."""
    src = _detail()
    assert '<Btn variant="outline" disabled={isBlocked}>Create Reservation</Btn>' not in src, (
        "the enabled-and-inert Create Reservation button must not reappear"
    )


def test_five_state_gating_and_explicit_reason():
    """Lesson M: when unavailable the control stays visible+disabled with an
    explicit reason; readiness is reflected from backend authority, not derived
    locally (Lesson F rule 5)."""
    src = _detail()
    assert "const canCreate" in src, "ProformaReservationTab must compute canCreate"
    # Gate on the canonical readiness authority (LOADED + clean), with the
    # handler-present check — NOT the preview-loaded sentinel, which would
    # false-enable in the window where readinessPost is still null.
    assert "!!reservationReady && !isBlocked && !!onCreateReservation" in src, (
        "canCreate must gate on reservationReady (canonical readiness) + not blocked + handler"
    )
    assert "readinessPost && readinessPost.ready === true" in src, (
        "reservationReady must derive from the canonical readinessPost authority "
        "(loaded + ready), never the preview-loaded sentinel alone (Lesson F rule 5)"
    )
    assert "disabledReason" in src, "must surface an explicit disabled reason (Lesson M)"
    assert "readiness has not loaded" in src, (
        "must explain the not-yet-ready state to the operator"
    )


# ── Confirmation modal ────────────────────────────────────────────────────────

def test_create_reservation_modal_defined_and_registered():
    src = _detail()
    assert "function CreateReservationModal(" in src, "CreateReservationModal must be defined"
    oa_start = src.index("Object.assign(window, {")
    oa = src[oa_start:oa_start + 400]
    assert "CreateReservationModal" in oa, "CreateReservationModal must be registered on window"


def test_modal_has_confirmation_idempotency_and_calls_pzapi():
    """Write-action rules: explicit confirmation, idempotency disclosure, and the
    write goes through PzApi transport (no raw fetch)."""
    src = _detail()
    m = src.index("function CreateReservationModal(")
    modal = src[m:src.index("Object.assign(window, {", m)]
    assert 'data-testid="reservation-create-modal-confirm"' in modal, (
        "modal must require an explicit operator confirmation checkbox"
    )
    assert 'data-testid="reservation-create-modal-submit"' in modal, (
        "modal submit button must carry a testid for E2E targeting"
    )
    assert "window.PzApi.createWfirmaReservation(" in modal, (
        "modal must submit through PzApi.createWfirmaReservation (transport layer)"
    )
    assert "idempotent" in modal.lower(), (
        "modal must disclose the backend idempotency guarantee to the operator"
    )
    assert "!confirmed || loading" in modal, (
        "handleCreate must guard against double-submit (re-entrancy) before the live write"
    )


def test_parent_wires_tab_and_renders_modal():
    src = _detail()
    assert "onCreateReservation={() => setShowReservationModal(true)}" in src, (
        "ProformaDetailPage must pass onCreateReservation to the Reservation tab"
    )
    assert "showReservationModal" in src and "setShowReservationModal" in src, (
        "ProformaDetailPage must own the reservation modal open/close state"
    )
    assert "<CreateReservationModal" in src, "ProformaDetailPage must render CreateReservationModal"


def test_no_raw_fetch_to_reservation_endpoint_in_jsx():
    """The reservation write must only ever leave through PzApi — never a raw
    fetch/apiFetch in the page component."""
    src = _detail()
    for bad in (
        "apiFetch('/api/v1/wfirma/reservations/create'",
        'apiFetch("/api/v1/wfirma/reservations/create"',
        "fetch('/api/v1/wfirma/reservations/create'",
        'fetch("/api/v1/wfirma/reservations/create"',
    ):
        assert bad not in src, f"page must not call the reservation endpoint directly: {bad!r}"


# ── Backend contract (end-to-end path pin) ────────────────────────────────────

def test_backend_reservation_create_endpoint_exists():
    """The wired path must target a real registered backend route."""
    routes = _ROUTES.read_text(encoding="utf-8", errors="replace")
    assert 'prefix="/api/v1/wfirma"' in routes, "router prefix must be /api/v1/wfirma"
    assert '@router.post("/reservations/create"' in routes, (
        "POST /api/v1/wfirma/reservations/create must exist (the button's target)"
    )


# ── V1 freeze (Lesson F) ──────────────────────────────────────────────────────

def test_v1_pages_did_not_gain_reservation_create_wiring():
    """Lesson F: frozen V1 pages must not gain the V2 reservation-create wiring."""
    for name in ("shipment-detail.html", "dashboard.html"):
        p = _STATIC / name
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        assert "createWfirmaReservation" not in t, (
            f"{name} (frozen V1) must not wire createWfirmaReservation"
        )
        assert "reservation-create-modal" not in t, (
            f"{name} (frozen V1) must not contain the V2 reservation modal"
        )

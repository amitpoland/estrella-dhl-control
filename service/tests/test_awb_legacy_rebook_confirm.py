"""AWB modal → legacy-rebook confirmation gate (ADR-proforma-cmr-short-number
§Known limitation, 2026-07-16).

compute_idempotency_key includes client_ref when present. A batch booked
BEFORE that change carries a legacy row (client_ref NULL) keyed WITHOUT
client_ref; a post-deploy re-book through the V2 flow (which now sends
client_ref) computes a NEW key → coordinator cache miss → a NEW shipment
record (and, in live mode, a NEW DHL booking) alongside the legacy row.
The mitigation pinned here: the AWB modal probes for a legacy row before
booking and HOLDS for explicit operator confirmation.

Pins:
  - get_legacy_shipment: newest non-failed NULL-client_ref row only; scoped
    rows never match; 'failed' rows never match (retry path is not a
    "prior booking")
  - GET /{batch_id}/shipment/legacy-probe: read-only, honest legacy_exists,
    NOT behind the carrier-config gate (works even when carrier would 503)
  - the modal gate lives inside doBooking() so EVERY path into booking
    (direct submit, save-then-book, keep-once, continue-without-saving) is
    covered; createCarrierShipment lives only inside executeBooking()
  - exact operator-facing warning text; explicit Continue/Cancel buttons;
    Cancel books nothing
  - FAIL VISIBLE: probe failure or missing wrapper arms the panel — never a
    silent pass-through (mirrors the 2026-07-06 baseline-gate incident fix)
  - no silent auto-cancel and no DHL void anywhere in the gate
  - no-client_ref bookings skip the gate (same legacy key → safe replay)

All backend tests use tmp_path. No production paths. No live calls.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence.shipment_db import (
    get_legacy_shipment,
    init_db,
    insert_shipment,
    update_state,
)

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
JSX = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
API = (_V2 / "pz-api.js").read_text(encoding="utf-8")
ROUTES = (
    Path(__file__).resolve().parents[1] / "app" / "api" / "routes_carrier_actions.py"
).read_text(encoding="utf-8")

LEGACY_TEXT = (
    "continuing will create a NEW shipment record — it will not replay the old one."
)
UNVERIFIED_TEXT = (
    "Could not verify whether a prior booking exists for this batch."
)


def _modal_src() -> str:
    """The AwbGenerateModal function body."""
    start = JSX.index("function AwbGenerateModal")
    end = JSX.index("function ProformaActionBar")
    return JSX[start:end]


# ── shipment_db.get_legacy_shipment ────────────────────────────────────────────


def _db(tmp_path):
    path = tmp_path / "carrier_shipments.db"
    init_db(path)
    return path


def _pending(key: str) -> ShipmentResult:
    return ShipmentResult(
        idempotency_key=key,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING,
        simulated=True,
    )


def _book(db, key, batch, client_ref, awb=None, state=ShipmentState.COMPLETE):
    insert_shipment(db, _pending(key), batch, client_ref)
    update_state(db, key, state, tracking_ref=awb)


class TestGetLegacyShipment:
    def test_legacy_complete_row_found_with_awb(self, tmp_path):
        db = _db(tmp_path)
        _book(db, "kLegacy", "B1", None, "AWB-LEGACY")
        row = get_legacy_shipment(db, "B1")
        assert row is not None
        assert row["client_ref"] is None
        assert row["tracking_ref"] == "AWB-LEGACY"

    def test_scoped_rows_are_not_legacy(self, tmp_path):
        """Client-scoped rows are the INTENDED per-client outcome — a sibling
        client's row must never trigger the legacy warning."""
        db = _db(tmp_path)
        _book(db, "kA", "B1", "Client A", "AWB-A")
        _book(db, "kB", "B1", "Client B", "AWB-B")
        assert get_legacy_shipment(db, "B1") is None

    def test_empty_batch_is_none(self, tmp_path):
        assert get_legacy_shipment(_db(tmp_path), "B1") is None

    def test_failed_legacy_row_is_not_a_prior_booking(self, tmp_path):
        """Re-booking over a FAILED attempt is the normal retry path — no
        warning noise."""
        db = _db(tmp_path)
        _book(db, "kFail", "B1", None, None, state=ShipmentState.FAILED)
        assert get_legacy_shipment(db, "B1") is None

    def test_pending_legacy_row_counts(self, tmp_path):
        """An in-flight (pending) legacy booking is still a prior booking."""
        db = _db(tmp_path)
        insert_shipment(db, _pending("kPend"), "B1", None)
        row = get_legacy_shipment(db, "B1")
        assert row is not None and row["state"] == "pending"

    def test_newest_legacy_row_wins(self, tmp_path):
        import sqlite3
        db = _db(tmp_path)
        _book(db, "kOld", "B1", None, "AWB-OLD")
        _book(db, "kNew", "B1", None, "AWB-NEW")
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "UPDATE carrier_shipments SET created_at='2026-01-01T00:00:00.000Z' "
                "WHERE idempotency_key='kOld'"
            )
            conn.execute(
                "UPDATE carrier_shipments SET created_at='2026-06-01T00:00:00.000Z' "
                "WHERE idempotency_key='kNew'"
            )
        assert get_legacy_shipment(db, "B1")["tracking_ref"] == "AWB-NEW"

    def test_other_batch_never_matches(self, tmp_path):
        db = _db(tmp_path)
        _book(db, "kLegacy", "B1", None, "AWB-LEGACY")
        assert get_legacy_shipment(db, "B2") is None


# ── GET /{batch_id}/shipment/legacy-probe ──────────────────────────────────────


def _probe_client(db_path):
    """TestClient where the carrier-config dependency BLOWS UP — pins that the
    probe is deliberately not behind the carrier gate (local-DB read only)."""
    from app.api import routes_carrier_actions as rca
    from app.api.routes_carrier_actions import router
    from app.core.security import require_api_key

    def _carrier_gate_503():
        raise HTTPException(status_code=503, detail="carrier pending")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[rca._get_carrier_config] = _carrier_gate_503
    app.dependency_overrides[rca._get_shipment_db_path] = lambda: db_path
    return TestClient(app)


class TestLegacyProbeRoute:
    # NB: route-level batch ids must satisfy _SAFE_BATCH ([A-Za-z0-9_-]{4,128});
    # short ids like "B1" are answered honestly-false by the guard.
    def test_probe_reports_legacy_row(self, tmp_path):
        db = _db(tmp_path)
        _book(db, "kLegacy", "BATCH1", None, "AWB-LEGACY")
        r = _probe_client(db).get("/api/v1/carrier/BATCH1/shipment/legacy-probe")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["legacy_exists"] is True
        assert body["tracking_ref"] == "AWB-LEGACY"
        assert body["batch_id"] == "BATCH1"

    def test_probe_false_for_scoped_only_batch(self, tmp_path):
        db = _db(tmp_path)
        _book(db, "kA", "BATCH1", "Client A", "AWB-A")
        r = _probe_client(db).get("/api/v1/carrier/BATCH1/shipment/legacy-probe")
        assert r.status_code == 200
        assert r.json()["legacy_exists"] is False

    def test_probe_false_for_unknown_batch(self, tmp_path):
        r = _probe_client(_db(tmp_path)).get(
            "/api/v1/carrier/NOPE/shipment/legacy-probe"
        )
        assert r.status_code == 200
        assert r.json()["legacy_exists"] is False

    def test_probe_malformed_batch_id_is_honest_false(self, tmp_path):
        """_SAFE_BATCH consistency guard: a malformed batch_id cannot name a
        real batch — answer honestly-false, never 500."""
        r = _probe_client(_db(tmp_path)).get(
            "/api/v1/carrier/x%00y/shipment/legacy-probe"
        )
        assert r.status_code == 200
        assert r.json()["legacy_exists"] is False

    def test_probe_not_behind_carrier_gate(self, tmp_path):
        """_get_carrier_config raises 503 in this fixture; the probe answers
        200 anyway — a pending/unconfigured carrier never hides the warning."""
        r = _probe_client(_db(tmp_path)).get(
            "/api/v1/carrier/BATCH1/shipment/legacy-probe"
        )
        assert r.status_code == 200

    def test_probe_is_read_only(self, tmp_path):
        import sqlite3
        db = _db(tmp_path)
        _book(db, "kLegacy", "BATCH1", None, "AWB-LEGACY")
        _probe_client(db).get("/api/v1/carrier/BATCH1/shipment/legacy-probe")
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT idempotency_key, state, tracking_ref FROM carrier_shipments"
            ).fetchall()
        assert rows == [("kLegacy", "complete", "AWB-LEGACY")]

    def test_route_declared_in_source(self):
        assert '"/{batch_id}/shipment/legacy-probe"' in ROUTES


# ── Modal gate: every booking path held until explicit confirmation ────────────


class TestModalGate:
    def test_gate_lives_inside_dobooking(self):
        """doBooking() is the shared entry for ALL booking paths (direct
        submit, save-then-book, keep-once, continue-without-saving); the gate
        must sit there, before executeBooking()."""
        src = _modal_src()
        gate = src[src.index("const doBooking"):src.index("const executeBooking")]
        assert "legacyProbe !== 'clear' && legacyProbe !== 'skip' && !legacyApproved" in gate
        assert "setLegacyConfirm(true)" in gate
        assert gate.index("setLegacyConfirm(true)") < gate.index("executeBooking()")
        assert "createCarrierShipment" not in gate   # gate never books

    def test_create_shipment_only_inside_executebooking(self):
        src = _modal_src()
        booking = src[src.index("const executeBooking"):]
        assert "createCarrierShipment" in booking
        before = src[:src.index("const executeBooking")]
        assert "createCarrierShipment" not in before

    def test_master_panel_buttons_still_route_through_gate(self):
        """The Customer-Master panel buttons call doBooking() (the gated
        wrapper) — never executeBooking() directly."""
        src = _modal_src()
        assert "onClick={() => { setSaveConfirm(null); doBooking(); }}" in src
        # the ONLY direct executeBooking() call from a click handler is the
        # legacy panel's explicit confirm button
        clicks = re.findall(r"onClick=\{[^}]*executeBooking\(\)[^}]*\}\}", src)
        assert len(clicks) == 1, clicks
        assert "setLegacyApproved(true)" in clicks[0]

    def test_confirm_button_approves_then_books(self):
        src = _modal_src()
        assert ("onClick={() => { setLegacyApproved(true); "
                "setLegacyConfirm(false); executeBooking(); }}") in src

    def test_cancel_books_nothing(self):
        src = _modal_src()
        m = re.search(
            r"onClick=\{\(\) => \{ setLegacyConfirm\(false\); \}\}", src)
        assert m, "Cancel must only dismiss the panel"
        assert "executeBooking" not in m.group(0)
        assert "doBooking" not in m.group(0)

    def test_submit_button_disabled_while_panel_open(self):
        assert "disabled={loading || isPending || !!saveConfirm || legacyConfirm}" in JSX


# ── Probe wiring, skip semantics, fail-visible ─────────────────────────────────


class TestProbeWiring:
    def test_api_wrapper_is_read_only_get(self):
        assert "probeCarrierLegacyShipment" in API
        m = re.search(
            r"probeCarrierLegacyShipment: \(batchId\) =>\s*\n\s*_get\(", API)
        assert m, "probe wrapper must be a plain _get (read-only, no mutation)"
        assert "/shipment/legacy-probe" in API

    def test_no_client_ref_booking_skips_gate(self):
        """No client_ref sent ⇒ same legacy idempotency key ⇒ the coordinator
        replays the legacy row safely — the gate must not fire."""
        src = _modal_src()
        assert "if (!prefill.client_name) {" in src
        skip = src[src.index("if (!prefill.client_name) {"):]
        assert skip.index("setLegacyProbe('skip')") < skip.index("probeCarrierLegacyShipment")

    def test_probe_failure_is_fail_visible(self):
        """Probe error or missing wrapper arms the panel via 'failed' — never
        a silent pass-through (2026-07-06 baseline-gate incident model)."""
        src = _modal_src()
        assert ".catch(() => setLegacyProbe('failed'))" in src
        assert "!window.PzApi.probeCarrierLegacyShipment" in src
        # 'failed' is NOT in the proceed set of the gate condition
        assert "legacyProbe !== 'clear' && legacyProbe !== 'skip'" in src

    def test_legacy_row_arms_legacy_state(self):
        src = _modal_src()
        assert "r.data.legacy_exists" in src
        assert "setLegacyProbe('legacy')" in src
        assert "setLegacyRow(r.data)" in src

    def test_late_clear_auto_dismisses_panel(self):
        """Race guard: submit while the probe is in flight opens the
        unverified panel; a late 'clear' resolution auto-dismisses it so the
        operator is never held by a false-positive. (A hung probe keeps the
        panel WITH its explicit continue — never a bricked modal, so the
        submit button is deliberately NOT disabled during 'loading'.)"""
        src = _modal_src()
        assert ("if (legacyConfirm && legacyProbe === 'clear') "
                "setLegacyConfirm(false);") in src


# ── Operator-facing panel text + safety ────────────────────────────────────────


class TestPanelUxAndSafety:
    def test_exact_legacy_warning_text(self):
        assert "A prior booking exists for this batch (AWB ${" in JSX
        assert LEGACY_TEXT in JSX

    def test_unverified_variant_text(self):
        assert UNVERIFIED_TEXT in JSX

    def test_no_void_no_cancel_reassurance_text(self):
        assert ("Nothing is cancelled or voided at DHL — the prior AWB (if any) "
                "stays exactly as it is.") in JSX

    def test_panel_testids(self):
        for tid in ("awb-legacy-rebook-panel", "awb-legacy-rebook-continue",
                    "awb-legacy-rebook-cancel"):
            assert tid in JSX, tid

    def test_button_labels_state_what_they_do(self):
        src = _modal_src()
        assert "Book NEW shipment" in src
        assert "Cancel — do not book" in src

    def test_gate_never_voids_or_cancels_anything(self):
        """The legacy gate is a confirmation only: no do-not-use flagging, no
        DHL void, no shipment mutation anywhere in the panel or gate."""
        src = _modal_src()
        panel = src[src.index('data-testid="awb-legacy-rebook-panel"'):
                    src.index('data-testid="awb-legacy-rebook-cancel"')]
        assert "markCarrierShipmentDoNotUse" not in panel
        gate = src[src.index("const doBooking"):src.index("const executeBooking")]
        assert "markCarrierShipmentDoNotUse" not in gate
        # backend probe: read-only handler, no update/insert calls
        probe_src = ROUTES[ROUTES.index("def probe_legacy_shipment"):
                           ROUTES.index("class DoNotUseBody")]
        for forbidden in ("update_state", "insert_shipment", "do_not_use",
                          "requests.", "httpx"):
            assert forbidden not in probe_src, forbidden

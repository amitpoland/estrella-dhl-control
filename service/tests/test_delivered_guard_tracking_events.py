"""test_delivered_guard_tracking_events.py — anomaly A1 fix coverage.

Verifies that is_audit_delivered() now treats tracking_events as a
fourth detection surface alongside the existing 3:
  - tracking.status == 'delivered'
  - delivered_at non-empty
  - proactive_dispatch_delivered_at non-empty
  - NEW: tracking_events[*].normalized_stage hits DELIVERED/CLOSED and
    no reactive stage appears after it.

Covers the 5 historical AWBs identified during the 2026-05-19 shadow
observation campaign (Phase 2 telemetry).
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ── New helper unit tests ────────────────────────────────────────────────────

def test_helper_returns_false_when_no_tracking_events():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    assert _is_delivered_by_tracking_events({}) is False
    assert _is_delivered_by_tracking_events({"tracking_events": []}) is False
    assert _is_delivered_by_tracking_events({"tracking_events": None}) is False


def test_helper_returns_false_on_malformed_audit():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    assert _is_delivered_by_tracking_events(None) is False
    assert _is_delivered_by_tracking_events("not a dict") is False


def test_helper_true_when_delivered_is_last_event():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "IN_TRANSIT"},
        {"normalized_stage": "DELIVERED"},
    ]}
    assert _is_delivered_by_tracking_events(a) is True


def test_helper_true_when_delivered_followed_only_by_exception():
    """The canonical DHL closure pattern: DELIVERED → EXCEPTION
    (shipment closed event).  Must be treated as terminal."""
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "IN_TRANSIT"},
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "EXCEPTION"},
    ]}
    assert _is_delivered_by_tracking_events(a) is True


def test_helper_true_for_closed_event():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "CLOSED"},
    ]}
    assert _is_delivered_by_tracking_events(a) is True


def test_helper_false_when_reactive_stage_after_delivered():
    """Real reactivation: shipment came back, must NOT be marked delivered."""
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "IN_TRANSIT"},
    ]}
    assert _is_delivered_by_tracking_events(a) is False


def test_helper_false_when_customs_pending_after_delivered():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "CUSTOMS_PENDING"},
    ]}
    assert _is_delivered_by_tracking_events(a) is False


def test_helper_false_when_out_for_delivery_after_delivered():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "OUT_FOR_DELIVERY"},
    ]}
    assert _is_delivered_by_tracking_events(a) is False


def test_helper_picks_last_delivered_when_multiple():
    """Multiple DELIVERED events: only the LAST one matters for
    reactivation analysis."""
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "IN_TRANSIT"},   # reactivation after 1st
        {"normalized_stage": "DELIVERED"},    # final delivery
        {"normalized_stage": "EXCEPTION"},    # closure
    ]}
    assert _is_delivered_by_tracking_events(a) is True


def test_helper_ignores_unknown_normalized_stage_after_delivered():
    """An unrecognised stage after DELIVERED is neither reactive nor
    terminal — treat as ambiguous and preserve delivered classification."""
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "SOMETHING_NEW_FROM_DHL"},
    ]}
    assert _is_delivered_by_tracking_events(a) is True


def test_helper_ignores_non_dict_events():
    from app.services.shipment_delivered_guard import _is_delivered_by_tracking_events
    a = {"tracking_events": [
        "not a dict",
        {"normalized_stage": "DELIVERED"},
        None,
    ]}
    assert _is_delivered_by_tracking_events(a) is True


# ── is_audit_delivered integration ───────────────────────────────────────────

def test_is_audit_delivered_falls_back_to_tracking_events(fresh):
    """An audit that has the 5-AWB shape (top-level fields empty but
    tracking_events end at DELIVERED/EXCEPTION) MUST be classified
    delivered."""
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {
        "tracking": {"status": None},
        "delivered_at": None,
        "proactive_dispatch_delivered_at": None,
        "tracking_events": [
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "CUSTOMS_CLEARED"},
            {"normalized_stage": "DELIVERED"},
            {"normalized_stage": "EXCEPTION"},  # DHL closure marker
        ],
    }
    assert is_audit_delivered(a) is True


def test_is_audit_delivered_top_level_still_wins(fresh):
    """Existing top-level surfaces still short-circuit before
    walking tracking_events."""
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {"tracking": {"status": "delivered"}}
    assert is_audit_delivered(a) is True
    a = {"delivered_at": "2026-05-18T10:00:00Z"}
    assert is_audit_delivered(a) is True
    a = {"proactive_dispatch_delivered_at": "2026-05-18T10:00:00Z"}
    assert is_audit_delivered(a) is True


def test_is_audit_delivered_false_for_in_transit_shipment(fresh):
    """AWB 4218922912 shape: must remain NOT delivered."""
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {
        "tracking": {"status": "on_hold"},
        "delivered_at": None,
        "tracking_events": [
            {"normalized_stage": "PICKED_UP"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "EXCEPTION"},  # transit hold, NOT closure
        ],
    }
    assert is_audit_delivered(a) is False


def test_is_audit_delivered_false_when_only_exception(fresh):
    """Exception without preceding DELIVERED is NOT closure."""
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {"tracking_events": [
        {"normalized_stage": "IN_TRANSIT"},
        {"normalized_stage": "EXCEPTION"},
    ]}
    assert is_audit_delivered(a) is False


def test_is_audit_delivered_false_when_reactivation(fresh):
    """Delivered then reactivated (out for delivery again) → active."""
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {"tracking_events": [
        {"normalized_stage": "DELIVERED"},
        {"normalized_stage": "IN_TRANSIT"},
        {"normalized_stage": "OUT_FOR_DELIVERY"},
    ]}
    assert is_audit_delivered(a) is False


# ── 5 anomaly AWBs — replicates the exact production shape ───────────────────

ANOMALY_AWB_SHAPES = {
    "2519243856": [
        "CUSTOMS_PENDING", "EXCEPTION", "EXCEPTION", "ARRIVED_ORIGIN_HUB",
        "IN_TRANSIT", "CUSTOMS_CLEARED", "DELIVERED", "EXCEPTION",
    ],
    "3483447564": [
        "DEPARTED_ORIGIN", "CUSTOMS_PENDING", "CUSTOMS_PENDING", "ARRIVED_ORIGIN_HUB",
        "IN_TRANSIT", "CUSTOMS_CLEARED", "DELIVERED", "EXCEPTION",
    ],
    "6049349806": [
        "CUSTOMS_PENDING", "CUSTOMS_PENDING", "CUSTOMS_PENDING", "CUSTOMS_PENDING",
        "EXCEPTION", "CUSTOMS_CLEARED", "EXCEPTION", "DELIVERED",
    ],
    "8523214840": [
        "EXCEPTION", "CUSTOMS_PENDING", "CUSTOMS_PENDING", "CUSTOMS_PENDING",
        "CUSTOMS_CLEARED", "IN_TRANSIT", "DELIVERED", "EXCEPTION",
    ],
    "8580992114": [
        "ARRIVED_ORIGIN_HUB", "EXCEPTION", "CUSTOMS_PENDING", "CUSTOMS_PENDING",
        "CUSTOMS_PENDING", "CUSTOMS_CLEARED", "EXCEPTION", "DELIVERED",
    ],
}


@pytest.mark.parametrize("awb,stages", list(ANOMALY_AWB_SHAPES.items()))
def test_anomaly_awbs_now_classify_delivered(fresh, awb, stages):
    from app.services.shipment_delivered_guard import is_audit_delivered
    a = {
        "awb": awb,
        "tracking": {"status": None},
        "delivered_at": None,
        "proactive_dispatch_delivered_at": None,
        "tracking_events": [{"normalized_stage": s} for s in stages],
    }
    assert is_audit_delivered(a) is True, (
        f"AWB {awb} should be classified delivered after fix"
    )


# ── Orchestrator decision replay ─────────────────────────────────────────────

def test_orchestrator_delivered_decision_for_anomaly_awbs(fresh):
    """After the fix, the orchestrator must classify these as delivered
    and emit suppress_pending_after_delivery (not customs_awaiting +
    dhl_followup_proposal_ready)."""
    from app.services.dhl_orchestrator import resolve_state, decide_for_audit, reset_cooldowns_for_tests
    reset_cooldowns_for_tests()
    a = {
        "batch_id": "SHIPMENT_2519243856_2026-05_40fb8002",
        "awb": "2519243856",
        "tracking_no": "2519243856",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "clearance_status": "dsk_generated",
        "tracking": {"status": None},
        "tracking_events": [
            {"normalized_stage": s}
            for s in ANOMALY_AWB_SHAPES["2519243856"]
        ],
    }
    assert resolve_state(a) == "delivered"
    d = decide_for_audit(a)
    assert d.lifecycle_state == "delivered"
    assert d.action == "suppress_pending_after_delivery"


def test_orchestrator_still_in_transit_for_awb_4218922912(fresh):
    """The live shipment must remain in_transit and produce
    agency_advance_pack_ready (NOT delivered)."""
    from app.services.dhl_orchestrator import resolve_state, decide_for_audit, reset_cooldowns_for_tests
    reset_cooldowns_for_tests()
    a = {
        "batch_id": "SHIPMENT_4218922912_2026-05_9040dd39",
        "awb": "4218922912",
        "tracking_no": "4218922912",
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "agency_email": "biuro@acspedycja.pl",
        },
        "clearance_status": "dsk_generated",
        "dsk_path": "x.pdf",
        "polish_desc_path": "y.pdf",
        "sad_ready_path": "z.json",
        "inputs": {"invoices": [{"path": "a.pdf"}]},
        "tracking": {"status": "on_hold"},
        "tracking_events": [
            {"normalized_stage": "PICKED_UP"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "EXCEPTION"},
            {"normalized_stage": "IN_TRANSIT"},
            {"normalized_stage": "DEPARTED_ORIGIN"},
        ],
    }
    assert resolve_state(a) == "in_transit"
    d = decide_for_audit(a)
    assert d.action == "agency_advance_pack_ready"


# ── Email-pipeline guard still respects the new surface ──────────────────────

def test_check_send_allowed_blocks_via_tracking_events(fresh, monkeypatch):
    """check_send_allowed must refuse to send when the new surface
    classifies the shipment delivered."""
    from app.services.shipment_delivered_guard import check_send_allowed
    bid = "SHIPMENT_TRACK_EV_DEL"
    d = fresh / "outputs" / bid
    d.mkdir(parents=True, exist_ok=True)
    a = {
        "batch_id": bid, "awb": "X1",
        "tracking_events": [{"normalized_stage": "DELIVERED"},
                            {"normalized_stage": "EXCEPTION"}],
    }
    (d / "audit.json").write_text(json.dumps(a), encoding="utf-8")
    g = check_send_allowed(bid)
    assert g["allowed"] is False
    assert g["delivered"] is True
    assert g["reason"] == "shipment_delivered"


def test_queue_email_refuses_via_tracking_events(fresh, monkeypatch):
    """queue_email's enqueue-time delivered guard must now refuse
    on the tracking_events surface alone."""
    from app.services import email_service as esvc
    import app.services.email_sender as snd
    monkeypatch.setattr(snd, "_smtp_configured", lambda: False)

    bid = "SHIPMENT_DEL_TEV"
    d = fresh / "outputs" / bid
    d.mkdir(parents=True, exist_ok=True)
    a = {
        "batch_id": bid, "awb": "X2",
        "tracking_events": [{"normalized_stage": "DELIVERED"}],
    }
    (d / "audit.json").write_text(json.dumps(a), encoding="utf-8")
    with pytest.raises(esvc.FollowupSuppressedError) as exc_info:
        esvc.queue_email(
            to="dhl@example.com",
            subject="x", body_html="<p>x</p>", body_text="x",
            batch_id=bid, email_type="dhl_followup",
        )
    assert exc_info.value.reason == "shipment_delivered"
    # Queue file should remain unchanged (no entry written)
    qp = fresh / "email_queue.json"
    assert not qp.exists() or qp.read_text(encoding="utf-8") in ("[]", "")

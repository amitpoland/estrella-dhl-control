"""test_dhl_orchestrator_state_machine.py — pure state-machine unit tests.

Verifies that resolve_state() returns the correct lifecycle state for
every shape of audit.json the orchestrator may encounter.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def base_audit():
    """Minimal active-shipment audit shell.

    Tests mutate copies of this fixture to exercise each branch of the
    state resolver.
    """
    return {
        "batch_id": "SHIPMENT_TEST_X",
        "awb": "TEST123",
        "tracking_no": "TEST123",
        "clearance_decision": {
            "clearance_path": "agency_clearance",
            "total_value_usd": 10000,
            "agency_email": "biuro@example.com",
        },
        "clearance_status": "",
        "tracking": {"status": "in_transit"},
        "tracking_events": [],
    }


def test_state_uploaded_when_no_clearance_decision(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["clearance_decision"] = None
    assert resolve_state(base_audit) == "uploaded"


def test_state_classified_when_decision_but_no_docs(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    # No dsk/polish/sad paths and no tracking events
    assert resolve_state(base_audit) == "classified"


def test_state_docs_ready_when_two_docs_present(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["dsk_path"] = "x.pdf"
    base_audit["polish_desc_path"] = "y.pdf"
    assert resolve_state(base_audit) == "docs_ready"


def test_state_in_transit_when_docs_and_tracking_events(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["dsk_path"] = "x.pdf"
    base_audit["polish_desc_path"] = "y.pdf"
    base_audit["sad_ready_path"] = "z.json"
    base_audit["tracking_events"] = [
        {"normalized_stage": "DEPARTED_ORIGIN"},
    ]
    assert resolve_state(base_audit) == "in_transit"


def test_state_customs_awaiting_when_at_destination_no_dhl_email(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["tracking_events"] = [
        {"normalized_stage": "ARRIVED_DESTINATION_COUNTRY"},
    ]
    assert resolve_state(base_audit) == "customs_awaiting"


def test_state_customs_received_when_dhl_email_no_package(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["dhl_email"] = {"received": True, "ticket": "T123"}
    assert resolve_state(base_audit) == "customs_received"


def test_state_reply_built_when_package_built_no_proposals(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["dhl_email"] = {"received": True}
    base_audit["agency_reply_package"] = {"status": "built"}
    assert resolve_state(base_audit) == "reply_built"


def test_state_operator_review_when_package_and_proposals(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["dhl_email"] = {"received": True}
    base_audit["agency_reply_package"] = {"status": "built"}
    base_audit["action_proposals"] = [{"id": "p1"}]
    assert resolve_state(base_audit) == "operator_review_required"


def test_state_reply_queued_when_clearance_status_advanced(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["clearance_status"] = "agency_email_queued"
    assert resolve_state(base_audit) == "reply_queued"


def test_state_agency_sent_terminal(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["clearance_status"] = "agency_email_sent"
    assert resolve_state(base_audit) == "agency_sent"


def test_state_delivered_via_tracking_status(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["tracking"] = {"status": "delivered"}
    assert resolve_state(base_audit) == "delivered"


def test_state_delivered_via_delivered_at(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["delivered_at"] = "2026-05-18T10:00:00Z"
    assert resolve_state(base_audit) == "delivered"


def test_state_delivered_via_proactive_dispatch(base_audit):
    from app.services.dhl_orchestrator import resolve_state
    base_audit["proactive_dispatch_delivered_at"] = "2026-05-18T10:00:00Z"
    assert resolve_state(base_audit) == "delivered"


def test_state_resolver_ignores_carrier_arrived_at_poland_at(base_audit):
    """Critical safety: this field has unreliable provenance; orchestrator
    must NOT use it to short-circuit to at_destination/customs_awaiting."""
    from app.services.dhl_orchestrator import resolve_state
    base_audit["carrier_arrived_at_poland_at"] = "2026-05-16T17:00:00+02:00"
    base_audit["tracking_events"] = [{"normalized_stage": "DEPARTED_ORIGIN"}]
    base_audit["dsk_path"] = "x.pdf"
    base_audit["polish_desc_path"] = "y.pdf"
    # Should stay in_transit, NOT advance to customs_awaiting.
    assert resolve_state(base_audit) == "in_transit"


def test_state_dsk_generated_status_does_not_regress(base_audit):
    """clearance_status='dsk_generated' must not block lifecycle advance
    to customs_awaiting once shipment arrives."""
    from app.services.dhl_orchestrator import resolve_state
    base_audit["clearance_status"] = "dsk_generated"
    base_audit["tracking_events"] = [{"normalized_stage": "ARRIVED_DESTINATION_COUNTRY"}]
    assert resolve_state(base_audit) == "customs_awaiting"


def test_all_state_constants_defined():
    """Smoke test: every documented state appears in the module's exported set."""
    from app.services import dhl_orchestrator as orch
    expected = {
        "uploaded", "classified", "docs_ready", "in_transit", "at_destination",
        "customs_awaiting", "customs_received", "reply_built",
        "operator_review_required", "reply_queued", "agency_sent",
        "delivered", "closed", "suppressed_after_delivery",
    }
    assert expected.issubset(set(orch.ALL_STATES))

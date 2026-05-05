"""
test_tracking_event_normalizer.py — Tests for the tracking event normalization layer.

Covers:
  - DHL raw event mapping to normalized stages
  - Manual event creation with explicit stage
  - Deduplication logic
  - Customs stage detection (workflow flags)
  - Delivered stage detection
  - Unknown event → requires_manual_review=True
  - stage_ge ordering helper
  - normalize_dhl_events_batch bulk normalization
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.tracking_normalizer import (
    STAGE_ORDER,
    VALID_STAGES,
    CUSTOMS_WORKFLOW_STAGES,
    append_tracking_events,
    apply_workflow_progression,
    normalize_dhl_events_batch,
    normalize_tracking_event,
    stage_ge,
    stage_rank,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw(description: str, status: str = "", timestamp: str = "2026-05-01T10:00:00Z",
         location: str = "WARSAW - PL") -> dict:
    return {
        "description": description,
        "status": status,
        "timestamp": timestamp,
        "location": location,
    }


# ── DHL raw event mapping ─────────────────────────────────────────────────────

class TestDHLRawEventMapping:
    def test_label_created(self):
        ev = normalize_tracking_event(_raw("Shipment information received"), awb="1234")
        assert ev["normalized_stage"] == "LABEL_CREATED"
        assert ev["confidence"] >= 0.9

    def test_picked_up(self):
        ev = normalize_tracking_event(_raw("Shipment picked up"), awb="1234")
        assert ev["normalized_stage"] == "PICKED_UP"
        assert ev["confidence"] == 1.0

    def test_in_transit_processed_at(self):
        ev = normalize_tracking_event(_raw("Processed at facility"), awb="1234")
        assert ev["normalized_stage"] == "IN_TRANSIT"

    def test_arrived_destination_country(self):
        ev = normalize_tracking_event(_raw("Arrived at destination country"), awb="1234")
        assert ev["normalized_stage"] == "ARRIVED_DESTINATION_COUNTRY"
        assert ev["confidence"] == 1.0

    def test_customs_pending_clearance_event(self):
        ev = normalize_tracking_event(_raw("Clearance event"), awb="1234")
        assert ev["normalized_stage"] == "CUSTOMS_PENDING"

    def test_customs_documents_requested(self):
        ev = normalize_tracking_event(
            _raw("Further clearance processing is required"), awb="1234"
        )
        assert ev["normalized_stage"] == "CUSTOMS_DOCUMENTS_REQUESTED"
        assert ev["confidence"] == 1.0

    def test_customs_under_review(self):
        ev = normalize_tracking_event(_raw("Customs status updated"), awb="1234")
        assert ev["normalized_stage"] == "CUSTOMS_UNDER_REVIEW"

    def test_customs_cleared(self):
        ev = normalize_tracking_event(_raw("Clearance processing complete"), awb="1234")
        assert ev["normalized_stage"] == "CUSTOMS_CLEARED"
        assert ev["confidence"] == 1.0

    def test_out_for_delivery_courier(self):
        ev = normalize_tracking_event(_raw("With delivery courier"), awb="1234")
        assert ev["normalized_stage"] == "OUT_FOR_DELIVERY"
        assert ev["confidence"] == 1.0

    def test_out_for_delivery_label(self):
        ev = normalize_tracking_event(_raw("Out for delivery"), awb="1234")
        assert ev["normalized_stage"] == "OUT_FOR_DELIVERY"

    def test_delivered(self):
        ev = normalize_tracking_event(_raw("Delivered - Signed by KOWALSKI"), awb="1234")
        assert ev["normalized_stage"] == "DELIVERED"
        assert ev["confidence"] == 1.0

    def test_unknown_event_requires_review(self):
        ev = normalize_tracking_event(_raw("Zbiorcza operacja magazynowa"), awb="1234")
        assert ev["normalized_stage"] == "EXCEPTION"
        assert ev["confidence"] == 0.0
        assert ev["requires_manual_review"] is True

    def test_event_fields_present(self):
        ev = normalize_tracking_event(
            _raw("Delivered", timestamp="2026-04-30T14:00:00Z", location="WARSAW - PL"),
            awb="9876543210",
            batch_id="SHIPMENT_TEST",
        )
        required = ["event_id", "batch_id", "awb", "source", "raw_status",
                    "raw_description", "normalized_stage", "location",
                    "event_time", "captured_at", "confidence", "requires_manual_review"]
        for f in required:
            assert f in ev, f"Missing field: {f}"
        assert ev["awb"] == "9876543210"
        assert ev["batch_id"] == "SHIPMENT_TEST"
        assert ev["source"] == "dhl_api"


# ── Manual event creation ─────────────────────────────────────────────────────

class TestManualEventCreation:
    def test_manual_with_valid_stage(self):
        raw = {
            "raw_description": "Shipment received at Warsaw customs",
            "normalized_stage": "CUSTOMS_PENDING",
            "event_time": "2026-05-01T09:00:00Z",
            "location": "WARSAW - PL",
        }
        ev = normalize_tracking_event(raw, source="manual", awb="111", batch_id="B1")
        assert ev["normalized_stage"] == "CUSTOMS_PENDING"
        assert ev["confidence"] == 1.0
        assert ev["requires_manual_review"] is False
        assert ev["source"] == "manual"

    def test_manual_with_delivered_stage(self):
        raw = {
            "raw_description": "Delivered — confirmed by warehouse",
            "normalized_stage": "DELIVERED",
            "event_time": "2026-05-02T12:00:00Z",
        }
        ev = normalize_tracking_event(raw, source="manual", awb="222")
        assert ev["normalized_stage"] == "DELIVERED"
        assert ev["confidence"] == 1.0

    def test_manual_invalid_stage_falls_back_to_normalizer(self):
        raw = {
            "raw_description": "Customs status updated",
            "normalized_stage": "NOT_A_REAL_STAGE",
            "event_time": "2026-05-01T08:00:00Z",
        }
        ev = normalize_tracking_event(raw, source="manual", awb="333")
        # Falls back to description-based normalization
        assert ev["normalized_stage"] == "CUSTOMS_UNDER_REVIEW"

    def test_manual_source_normalised_for_unknown_source(self):
        ev = normalize_tracking_event(
            {"raw_description": "test"}, source="operator_panel"
        )
        assert ev["source"] == "manual"


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication:
    def _make_event(self, desc: str, ts: str = "2026-05-01T10:00:00Z",
                    source: str = "dhl_api") -> dict:
        return normalize_tracking_event(
            {"description": desc, "timestamp": ts},
            source=source, awb="99999",
        )

    def test_no_duplicate_added(self):
        ev = self._make_event("Delivered")
        audit: dict = {}
        audit, added1 = append_tracking_events(audit, [ev])
        audit, added2 = append_tracking_events(audit, [ev])
        assert added1 == 1
        assert added2 == 0
        assert len(audit["tracking_events"]) == 1

    def test_different_description_not_deduped(self):
        ev1 = self._make_event("Delivered", ts="2026-05-01T10:00:00Z")
        ev2 = self._make_event("Picked up", ts="2026-05-01T08:00:00Z")
        audit: dict = {}
        audit, added = append_tracking_events(audit, [ev1, ev2])
        assert added == 2

    def test_same_description_different_source_not_deduped(self):
        ev_api = self._make_event("In transit", source="dhl_api")
        ev_pub = self._make_event("In transit", source="public_tracking")
        audit: dict = {}
        audit, added = append_tracking_events(audit, [ev_api, ev_pub])
        assert added == 2

    def test_events_sorted_chronologically(self):
        ev_late  = self._make_event("Delivered", ts="2026-05-02T12:00:00Z")
        ev_early = self._make_event("Picked up", ts="2026-04-28T09:00:00Z")
        audit: dict = {}
        audit, _ = append_tracking_events(audit, [ev_late, ev_early])
        times = [e["event_time"] for e in audit["tracking_events"]]
        assert times == sorted(times)

    def test_existing_events_preserved(self):
        ev1 = self._make_event("Picked up", ts="2026-04-28T09:00:00Z")
        ev2 = self._make_event("In transit", ts="2026-04-29T10:00:00Z")
        audit: dict = {}
        audit, _ = append_tracking_events(audit, [ev1])
        audit, added = append_tracking_events(audit, [ev2])
        assert added == 1
        assert len(audit["tracking_events"]) == 2


# ── Customs stage detection ───────────────────────────────────────────────────

class TestCustomsStageDetection:
    def _audit_with_stage(self, stage: str) -> dict:
        ev = normalize_tracking_event(
            {"description": "test", "normalized_stage": stage},
            source="manual", awb="111",
        )
        # Ensure stage is set (manual path respects it)
        ev["normalized_stage"] = stage
        audit: dict = {}
        audit, _ = append_tracking_events(audit, [ev])
        return audit

    def test_customs_docs_requested_sets_eligible(self):
        audit = self._audit_with_stage("CUSTOMS_DOCUMENTS_REQUESTED")
        result = apply_workflow_progression(audit)
        assert result.get("customs_workflow_eligible") is True

    def test_customs_cleared_sets_clearance_complete(self):
        audit = self._audit_with_stage("CUSTOMS_CLEARED")
        result = apply_workflow_progression(audit)
        assert result.get("clearance_complete") is True
        assert result.get("customs_workflow_eligible") is True

    def test_in_transit_does_not_set_customs_eligible(self):
        audit = self._audit_with_stage("IN_TRANSIT")
        result = apply_workflow_progression(audit)
        assert not result.get("customs_workflow_eligible")
        assert not result.get("clearance_complete")

    def test_flags_are_forward_only(self):
        audit = {"clearance_complete": True}
        result = apply_workflow_progression(audit, events=[])
        # Already set — must remain True even with no events
        assert result["clearance_complete"] is True


# ── Delivered stage detection ─────────────────────────────────────────────────

class TestDeliveredStageDetection:
    def test_delivered_sets_shipment_delivered(self):
        ev = normalize_tracking_event(
            {"description": "Delivered", "timestamp": "2026-05-01T14:00:00Z"},
            source="dhl_api", awb="555",
        )
        assert ev["normalized_stage"] == "DELIVERED"
        audit: dict = {}
        audit, _ = append_tracking_events(audit, [ev])
        result = apply_workflow_progression(audit)
        assert result.get("shipment_delivered") is True

    def test_out_for_delivery_does_not_set_delivered(self):
        ev = normalize_tracking_event(
            {"description": "With delivery courier"},
            source="dhl_api", awb="666",
        )
        audit: dict = {}
        audit, _ = append_tracking_events(audit, [ev])
        result = apply_workflow_progression(audit)
        assert not result.get("shipment_delivered")


# ── stage_ge ordering ─────────────────────────────────────────────────────────

class TestStageOrdering:
    def test_delivered_after_in_transit(self):
        assert stage_ge("DELIVERED", "IN_TRANSIT")

    def test_in_transit_not_after_delivered(self):
        assert not stage_ge("IN_TRANSIT", "DELIVERED")

    def test_customs_cleared_after_customs_pending(self):
        assert stage_ge("CUSTOMS_CLEARED", "CUSTOMS_PENDING")

    def test_same_stage_is_ge(self):
        assert stage_ge("PICKED_UP", "PICKED_UP")

    def test_unknown_stage_rank_is_minus_one(self):
        assert stage_rank("MADE_UP_STAGE") == -1

    def test_all_stages_have_increasing_rank(self):
        ranks = [stage_rank(s) for s in STAGE_ORDER if s not in ("EXCEPTION", "CLOSED")]
        for i in range(len(ranks) - 1):
            assert ranks[i] < ranks[i + 1]


# ── Bulk normalization ────────────────────────────────────────────────────────

class TestBulkNormalization:
    def test_normalize_dhl_events_batch(self):
        raw = [
            {"description": "Shipment picked up",       "timestamp": "2026-04-20T08:00:00Z", "location": "MUMBAI - IN"},
            {"description": "Processed at facility",    "timestamp": "2026-04-21T12:00:00Z", "location": "FRANKFURT - DE"},
            {"description": "Clearance event",          "timestamp": "2026-04-24T09:00:00Z", "location": "WARSAW - PL"},
            {"description": "Clearance processing complete", "timestamp": "2026-04-25T14:00:00Z", "location": "WARSAW - PL"},
            {"description": "With delivery courier",    "timestamp": "2026-04-26T08:00:00Z", "location": "WARSAW - PL"},
            {"description": "Delivered",                "timestamp": "2026-04-26T14:30:00Z", "location": "WARSAW - PL"},
        ]
        result = normalize_dhl_events_batch(raw, awb="1012178215", batch_id="BATCH_TEST")
        assert len(result) == 6
        stages = [e["normalized_stage"] for e in result]
        assert stages[0] == "PICKED_UP"
        assert stages[1] == "IN_TRANSIT"
        assert stages[2] == "CUSTOMS_PENDING"
        assert stages[3] == "CUSTOMS_CLEARED"
        assert stages[4] == "OUT_FOR_DELIVERY"
        assert stages[5] == "DELIVERED"

    def test_full_pipeline(self):
        raw = [
            {"description": "Further clearance processing is required",
             "timestamp": "2026-04-24T10:00:00Z", "location": "WARSAW - PL"},
            {"description": "Delivered", "timestamp": "2026-04-26T15:00:00Z", "location": "WARSAW - PL"},
        ]
        events = normalize_dhl_events_batch(raw, awb="AWB1", batch_id="B1")
        audit: dict = {}
        audit, added = append_tracking_events(audit, events)
        assert added == 2
        audit = apply_workflow_progression(audit)
        assert audit.get("customs_workflow_eligible") is True
        assert audit.get("shipment_delivered") is True

    def test_empty_batch(self):
        result = normalize_dhl_events_batch([], awb="X", batch_id="Y")
        assert result == []

"""
test_email_timeline_integration.py — End-to-end email→timeline integration tests.

Tests the 5 required scenarios from the architecture spec:
  1. email → timeline event added
  2. duplicate email → no duplicate event (protection rule)
  3. duty delay → trigger fires (timeline-based T2 detection)
  4. timeline overrides clearance decision
  5. no audit corruption

Plus coverage for singleton suppression, FedEx path, and unknown actor detection.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")
# NOTE: no STORAGE_ROOT setdefault — tests use tmp_path for isolation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(hours_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _make_audit(path: Path, extra: Dict[str, Any] | None = None) -> Path:
    """Create a minimal audit.json in `path` and return its Path."""
    path.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "awb": "1234567890",
        "carrier": "DHL",
        "status": "processing",
        "timeline": [],
    }
    if extra:
        audit.update(extra)
    ap = path / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return ap


def _read_timeline(audit_path: Path) -> List[Dict[str, Any]]:
    return json.loads(audit_path.read_text(encoding="utf-8")).get("timeline", [])


def _read_audit(audit_path: Path) -> Dict[str, Any]:
    return json.loads(audit_path.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Email → timeline event added
# ══════════════════════════════════════════════════════════════════════════════

class TestEmailToTimelineAdded:
    """Email ingestion writes the correct event to the timeline."""

    def test_dhl_arrival_appends_carrier_arrived(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":  "odprawacelna@dhl.com",
            "subject": "Przesyłka 1234567890 — odprawa celna",
            "body":    "AWB: 1234567890",
            "email_id": "msg-001",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev == "carrier_arrived", f"Expected carrier_arrived, got {ev!r}"
        tl = _read_timeline(ap)
        assert len(tl) == 1
        entry = tl[0]
        assert entry["event"] == "carrier_arrived"
        assert entry["trigger_source"] == "email_classifier"
        assert entry["actor"] == "odprawacelna@dhl.com"
        assert entry["detail"]["email_id"] == "msg-001"
        assert entry["detail"]["email_type"] == "dhl_arrival"

    def test_ganther_duty_appends_duty_note_received(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "ciagarlak@ganther.com.pl",
            "subject":  "Należności celne AWB 1234567890",
            "body":     "Kwota należności: 1 181,00 PLN",
            "email_id": "msg-002",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev == "duty_note_received"
        tl = _read_timeline(ap)
        assert any(e["event"] == "duty_note_received" for e in tl)
        duty_ev = next(e for e in tl if e["event"] == "duty_note_received")
        assert duty_ev["detail"]["pln_amount"] == 1181.0

    def test_zc429_appends_zc429_received(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":      "no-reply@acspedycja.pl",
            "subject":     "ZC429 — MRN 26PL44302D005LJ4R0",
            "attachments": ["ZC429_26PL44302D005LJ4R0_1_PL.pdf"],
            "email_id":    "msg-003",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev == "zc429_received"
        tl = _read_timeline(ap)
        zc = next(e for e in tl if e["event"] == "zc429_received")
        assert zc["detail"]["mrn"] == "26PL44302D005LJ4R0"

    def test_fedex_arrival_appends_carrier_arrived(self, tmp_path):
        ap = _make_audit(tmp_path, {"carrier": "FEDEX"})
        from app.services.email_classifier import process_incoming_email

        # Note: body must NOT contain "cesja"/"cession"/"dsk" — those keywords
        # match _DSK_KEYWORDS and classify the email as fedex_dsk before the
        # arrival/cesja-attachment check is reached (see email_classifier.py §5).
        email_obj = {
            "sender":   "pl-import@fedex.com",
            "subject":  "FedEx shipment 882994160903 arrived",
            "body":     "AWB 882994160903. Please submit the attached form to customs.",
            "attachments": ["authorization_form.pdf"],
            "email_id": "msg-fedex-01",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev == "carrier_arrived"
        tl = _read_timeline(ap)
        assert any(e["event"] == "carrier_arrived" for e in tl)

    def test_ganther_payment_appends_payment_confirmed(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "ciagarlak@ganther.com.pl",
            "subject":  "Płatność",
            "body":     "Dzieki, płaci się",
            "email_id": "msg-pay-01",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev == "payment_confirmed"
        tl = _read_timeline(ap)
        assert any(e["event"] == "payment_confirmed" for e in tl)

    def test_do_not_trigger_produces_no_event(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "biuro@acspedycja.pl",
            "subject":  "Zestawienie VAT",
            "body":     "Monthly VAT statement",
            "email_id": "msg-vat-01",
        }
        cls, ev = process_incoming_email(email_obj, ap)

        assert ev is None, f"Expected no event for do_not_trigger, got {ev!r}"
        assert _read_timeline(ap) == []

    def test_event_detail_contains_sender(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "piotr@acspedycja.pl",
            "subject":  "PZC — odprawa zakończona",
            "body":     "Potwierdzenie zgłoszenia celnego. 500 PLN",
            "email_id": "msg-pzc-01",
        }
        _, ev = process_incoming_email(email_obj, ap)
        assert ev is not None
        tl = _read_timeline(ap)
        entry = next(e for e in tl if e["event"] == ev)
        assert entry["detail"]["sender"] == "piotr@acspedycja.pl"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Duplicate email → no duplicate event (protection rules)
# ══════════════════════════════════════════════════════════════════════════════

class TestNoDuplicateTimelineEvent:
    """Protection rule: same email processed twice must not add a second event."""

    def test_same_email_id_not_duplicated(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "ciagarlak@ganther.com.pl",
            "subject":  "Należności celne",
            "body":     "1 000,00 PLN",
            "email_id": "msg-dedup-001",
        }
        _, ev1 = process_incoming_email(email_obj, ap)
        _, ev2 = process_incoming_email(email_obj, ap)

        assert ev1 == "duty_note_received"
        assert ev2 is None, "Second identical email_id should be suppressed"
        tl = _read_timeline(ap)
        duty_events = [e for e in tl if e["event"] == "duty_note_received"]
        assert len(duty_events) == 1, f"Expected 1 duty event, got {len(duty_events)}"

    def test_singleton_event_not_duplicated(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email1 = {
            "sender":   "odprawacelna@dhl.com",
            "subject":  "AWB 1234567890",
            "body":     "AWB: 1234567890",
            "email_id": "msg-arr-001",
        }
        email2 = {
            "sender":   "odprawacelna@dhl.com",
            "subject":  "AWB 1234567890 — followup",
            "body":     "AWB: 1234567890",
            "email_id": "msg-arr-002",    # different email_id
        }
        _, ev1 = process_incoming_email(email1, ap)
        _, ev2 = process_incoming_email(email2, ap)

        # carrier_arrived is a SINGLETON — second must be suppressed
        assert ev1 == "carrier_arrived"
        assert ev2 is None, "Singleton carrier_arrived must not fire twice"
        arrived = [e for e in _read_timeline(ap) if e["event"] == "carrier_arrived"]
        assert len(arrived) == 1

    def test_repeatable_event_different_email_id_allowed(self, tmp_path):
        """Duty notices CAN repeat (different invoices), but only if email_id differs."""
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email1 = {
            "sender":   "ciagarlak@ganther.com.pl",
            "subject":  "Należności celne AWB 111",
            "body":     "500,00 PLN",
            "email_id": "msg-duty-001",
        }
        email2 = {
            "sender":   "ciagarlak@ganther.com.pl",
            "subject":  "Należności celne AWB 222",
            "body":     "750,00 PLN",
            "email_id": "msg-duty-002",   # different email_id
        }
        _, ev1 = process_incoming_email(email1, ap)
        _, ev2 = process_incoming_email(email2, ap)

        assert ev1 == "duty_note_received"
        assert ev2 == "duty_note_received"
        duty_events = [e for e in _read_timeline(ap) if e["event"] == "duty_note_received"]
        assert len(duty_events) == 2

    def test_no_event_for_missing_audit(self, tmp_path):
        """If audit.json does not exist, return (cls, None) without crashing."""
        missing = tmp_path / "nonexistent" / "audit.json"
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "odprawacelna@dhl.com",
            "subject":  "AWB 1234567890",
            "body":     "AWB: 1234567890",
        }
        cls, ev = process_incoming_email(email_obj, missing)
        assert ev is None
        assert cls["type"] == "dhl_arrival"   # classification still works


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Duty delay → trigger fires (timeline-based T2 detection)
# ══════════════════════════════════════════════════════════════════════════════

class TestDutyDelayTriggerFromTimeline:
    """T2 trigger must fire when duty_note_received is on timeline, even without timestamp field."""

    def test_duty_trigger_from_timeline_event(self, tmp_path):
        """detect_triggers fires DUTY_PAYMENT_PENDING from timeline when duty_notice_received_at is absent."""
        from app.agents.cowork_coordinator import detect_triggers

        duty_ts = _ts(hours_ago=80)    # 80 hours ago — above 72h warning threshold
        audit = {
            "awb":     "1234567890",
            "carrier": "DHL",
            "status":  "processing",
            # NO duty_notice_received_at — relies on timeline fallback
            "timeline": [
                {"event": "carrier_arrived",    "ts": _ts(150), "detail": {}},
                {"event": "duty_note_received", "ts": duty_ts,  "detail": {"pln_amount": 981.0}},
            ],
        }
        triggers = detect_triggers(audit, "batch-001")
        codes = [t["trigger"] for t in triggers]
        assert "DUTY_PAYMENT_PENDING" in codes, (
            f"Expected DUTY_PAYMENT_PENDING from timeline fallback. Got: {codes}"
        )

    def test_duty_trigger_confidence_high_after_72h(self, tmp_path):
        from app.agents.cowork_coordinator import detect_triggers

        audit = {
            "awb": "1234567890",
            "carrier": "DHL",
            "timeline": [
                {"event": "duty_note_received", "ts": _ts(80), "detail": {}},
            ],
        }
        triggers = detect_triggers(audit, "batch-duty-conf")
        duty_t = next((t for t in triggers if t["trigger"] == "DUTY_PAYMENT_PENDING"), None)
        assert duty_t is not None
        assert duty_t["confidence"] == "high"

    def test_duty_trigger_not_fired_if_payment_confirmed(self, tmp_path):
        """T2 must not fire if payment_confirmed is also present."""
        from app.agents.cowork_coordinator import detect_triggers

        audit = {
            "awb": "1234567890",
            "carrier": "DHL",
            "duty_paid_signal_at": _ts(2),    # paid 2h ago
            "timeline": [
                {"event": "duty_note_received", "ts": _ts(80), "detail": {}},
                {"event": "payment_confirmed",  "ts": _ts(2),  "detail": {}},
            ],
        }
        triggers = detect_triggers(audit, "batch-paid")
        codes = [t["trigger"] for t in triggers]
        assert "DUTY_PAYMENT_PENDING" not in codes, (
            "DUTY_PAYMENT_PENDING must not fire when duty_paid_signal_at is set"
        )

    def test_duty_trigger_from_direct_field_still_works(self, tmp_path):
        """T2 must also fire when duty_notice_received_at is the direct field (backward compat)."""
        from app.agents.cowork_coordinator import detect_triggers

        audit = {
            "awb":                    "1234567890",
            "carrier":                "DHL",
            "duty_notice_received_at": _ts(80),
            "timeline":               [],
        }
        triggers = detect_triggers(audit, "batch-field")
        codes = [t["trigger"] for t in triggers]
        assert "DUTY_PAYMENT_PENDING" in codes


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Timeline overrides clearance decision
# ══════════════════════════════════════════════════════════════════════════════

class TestTimelineClearanceOverride:
    """Timeline signals must override the value-computed clearance path."""

    def test_agency_email_sent_forces_external_agency(self):
        from app.services.clearance_decision import apply_timeline_overrides

        decision = {
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
            "carrier_handles": True,
            "total_value_usd": 1200.0,
            "threshold_usd":   2500.0,
        }
        timeline = [
            {"event": "carrier_arrived",   "ts": _ts(120), "detail": {}},
            {"event": "agency_email_sent", "ts": _ts(72),  "detail": {}},
        ]
        result = apply_timeline_overrides(decision, timeline)

        assert result["clearance_path"]  == "agency_clearance"
        assert result["require_dsk"]     is True
        assert result["carrier_handles"] is False
        assert "timeline_override" in result["decision_reason"]
        assert "overridden_at" in result

    def test_dhl_reply_sent_low_value_forces_carrier(self):
        from app.services.clearance_decision import apply_timeline_overrides

        decision = {
            "clearance_path":  "routing_pending",
            "require_dsk":     None,
            "carrier_handles": None,
            "total_value_usd": 800.0,
            "threshold_usd":   2500.0,
        }
        timeline = [
            {"event": "carrier_arrived",  "ts": _ts(100), "detail": {}},
            {"event": "dhl_reply_sent",   "ts": _ts(50),  "detail": {}},
        ]
        result = apply_timeline_overrides(decision, timeline)

        assert result["clearance_path"]  == "dhl_self_clearance"
        assert result["require_dsk"]     is False
        assert result["carrier_handles"] is True
        assert "timeline_override" in result["decision_reason"]

    def test_high_value_agency_override_takes_priority_over_dhl_reply(self):
        """agency_email_sent takes priority over dhl_reply_sent."""
        from app.services.clearance_decision import apply_timeline_overrides

        decision = {
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
            "carrier_handles": True,
            "total_value_usd": 3200.0,
            "threshold_usd":   2500.0,
        }
        timeline = [
            {"event": "dhl_reply_sent",   "ts": _ts(80), "detail": {}},
            {"event": "agency_email_sent","ts": _ts(40), "detail": {}},
        ]
        result = apply_timeline_overrides(decision, timeline)

        # agency_email_sent wins (checked first)
        assert result["clearance_path"] == "agency_clearance"

    def test_no_override_when_timeline_empty(self):
        from app.services.clearance_decision import apply_timeline_overrides

        decision = {
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
            "carrier_handles": True,
        }
        result = apply_timeline_overrides(decision, [])
        assert result == decision    # unchanged

    def test_no_override_when_already_correct_path(self):
        """No overridden_at when path already matches override target."""
        from app.services.clearance_decision import apply_timeline_overrides

        decision = {
            "clearance_path":  "agency_clearance",
            "require_dsk":     True,
            "carrier_handles": False,
        }
        timeline = [{"event": "agency_email_sent", "ts": _ts(50), "detail": {}}]
        result = apply_timeline_overrides(decision, timeline)
        assert "overridden_at" not in result    # no override needed

    def test_decision_dict_not_mutated(self):
        """Original decision dict must not be mutated."""
        from app.services.clearance_decision import apply_timeline_overrides

        original = {
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
            "carrier_handles": True,
            "total_value_usd": 1200.0,
            "threshold_usd":   2500.0,
        }
        original_copy = dict(original)
        timeline = [{"event": "agency_email_sent", "ts": _ts(50), "detail": {}}]
        apply_timeline_overrides(original, timeline)
        assert original == original_copy, "Input decision dict was mutated"

    def test_build_decision_for_carrier_applies_overrides(self):
        """build_clearance_decision_for_carrier integrates timeline overrides end-to-end."""
        from app.services.clearance_decision import build_clearance_decision_for_carrier

        audit = {
            "carrier": "DHL",
            "invoice_totals": {"total_cif_usd": 1200.0},    # below threshold
            "timeline": [
                {"event": "agency_email_sent", "ts": _ts(50), "detail": {}},
            ],
        }
        dec = build_clearance_decision_for_carrier(audit)
        # Value says carrier_self_clearance; timeline says external_agency_clearance
        assert dec["clearance_path"] == "agency_clearance"
        assert "timeline_override" in dec["decision_reason"]


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — No audit corruption
# ══════════════════════════════════════════════════════════════════════════════

class TestNoAuditCorruption:
    """Protection: process_incoming_email must not corrupt audit.json."""

    def test_only_timeline_field_modified(self, tmp_path):
        """All fields except timeline must be identical before and after ingestion."""
        ap = _make_audit(tmp_path, {
            "awb": "9876543210",
            "carrier": "DHL",
            "status": "processing",
            "doc_no": "PZ 10/2026",
            "invoice_totals": {"total_cif_usd": 2800.0},
            "clearance_decision": {"clearance_path": "agency_clearance"},
        })
        before = _read_audit(ap)
        del before["timeline"]    # exclude timeline from comparison

        from app.services.email_classifier import process_incoming_email
        process_incoming_email(
            {"sender": "odprawacelna@dhl.com", "subject": "AWB 9876543210", "body": "",
             "email_id": "test-msg"},
            ap,
        )
        after = _read_audit(ap)
        after_no_tl = {k: v for k, v in after.items() if k != "timeline"}
        assert before == after_no_tl, "Fields other than 'timeline' were modified"

    def test_timeline_events_are_appended_not_replaced(self, tmp_path):
        """Existing timeline events must not be removed when a new event is appended."""
        existing_event = {
            "ts":             _ts(200),
            "event":          "batch_created",
            "trigger_source": "api",
            "actor":          "system",
            "detail":         None,
        }
        ap = _make_audit(tmp_path, {"timeline": [existing_event]})

        from app.services.email_classifier import process_incoming_email
        process_incoming_email(
            {"sender": "odprawacelna@dhl.com", "subject": "AWB 1234567890", "body": "",
             "email_id": "msg-append-test"},
            ap,
        )
        tl = _read_timeline(ap)
        assert len(tl) == 2
        assert tl[0]["event"] == "batch_created"    # original preserved
        assert tl[1]["event"] == "carrier_arrived"  # new appended

    def test_valid_json_after_ingestion(self, tmp_path):
        """audit.json must be valid JSON after process_incoming_email."""
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email
        process_incoming_email(
            {"sender": "no-reply@acspedycja.pl", "subject": "ZC429",
             "attachments": ["ZC429_26PL44302D005LJ4R0_1_PL.pdf"],
             "email_id": "msg-json-test"},
            ap,
        )
        # Must not raise
        content = json.loads(ap.read_text(encoding="utf-8"))
        assert isinstance(content, dict)
        assert "timeline" in content

    def test_event_has_required_timeline_fields(self, tmp_path):
        """Every ingested event must have ts, event, trigger_source, actor, detail."""
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email
        process_incoming_email(
            {"sender": "ciagarlak@ganther.com.pl", "subject": "PZC", "body": "pzc",
             "email_id": "msg-fields-test"},
            ap,
        )
        tl = _read_timeline(ap)
        assert len(tl) == 1
        entry = tl[0]
        for field in ("ts", "event", "trigger_source", "actor", "detail"):
            assert field in entry, f"Missing required field: {field}"
        assert isinstance(entry["ts"], str) and entry["ts"]
        assert isinstance(entry["detail"], dict)

    def test_no_modification_on_suppressed_event(self, tmp_path):
        """When event is suppressed (duplicate), audit.json mtime must not change."""
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email

        email_obj = {
            "sender":   "odprawacelna@dhl.com",
            "subject":  "AWB 1234567890",
            "body":     "",
            "email_id": "msg-mtime-001",
        }
        process_incoming_email(email_obj, ap)
        mtime_after_first = ap.stat().st_mtime

        # Second call — singleton suppressed
        process_incoming_email(email_obj, ap)
        mtime_after_second = ap.stat().st_mtime

        assert mtime_after_first == mtime_after_second, (
            "audit.json was modified even though the event was suppressed"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Additional: scan_recent_emails_hook and email type map coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestScanEmailsHookAndMapping:
    """Verify hook stub and mapping completeness."""

    def test_scan_hook_returns_empty_list(self):
        """Placeholder hook must return [] without errors."""
        from app.agents.cowork_coordinator import _scan_recent_emails_hook
        result = _scan_recent_emails_hook("batch-123", {"awb": "1234567890"})
        assert result == []

    def test_email_type_map_covers_key_types(self):
        from app.services.email_classifier import _EMAIL_TYPE_TO_EVENT
        required = {
            "dhl_arrival", "zc429_notification", "ganther_duty",
            "ganther_payment", "fedex_arrival", "acs_pzc",
        }
        assert required.issubset(_EMAIL_TYPE_TO_EVENT.keys()), (
            f"Missing types: {required - _EMAIL_TYPE_TO_EVENT.keys()}"
        )

    def test_singleton_events_are_subset_of_mapped_events(self):
        from app.services.email_classifier import _EMAIL_TYPE_TO_EVENT, _SINGLETON_EVENTS
        all_events = set(_EMAIL_TYPE_TO_EVENT.values())
        assert _SINGLETON_EVENTS.issubset(all_events), (
            f"Singleton events not in mapped values: {_SINGLETON_EVENTS - all_events}"
        )

    def test_process_email_returns_tuple(self, tmp_path):
        ap = _make_audit(tmp_path)
        from app.services.email_classifier import process_incoming_email
        result = process_incoming_email(
            {"sender": "odprawacelna@dhl.com", "subject": "", "body": ""},
            ap,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        cls, ev = result
        assert isinstance(cls, dict)
        assert ev is None or isinstance(ev, str)

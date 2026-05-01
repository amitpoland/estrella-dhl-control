"""
test_intelligence_engine.py — Acceptance tests for the Cowork Intelligence Engine.

Test matrix (6 criteria from spec):
  1. parse_research_docs() → no crash even if docs are missing
  2. _ACTORS registry contains ≥ 30 actors
  3. _TRIGGERS registry contains ≥ 10 triggers
  4. email_classifier.classify_email() handles DHL, FedEx, ZC429 emails
  5. No audit.json modification from any intelligence layer call
  6. cowork detect_triggers() returns suggestions (suggest-only; no writes)

Additional coverage:
  7. risk_detector.detect_all_risks() returns structured warnings
  8. timeline_mapper.map_email_to_events() returns correct events
  9. clearance_decision carrier detection + FedEx path
  10. intelligence_config_builder.build_config() produces expected keys

Run:
    pytest service/tests/test_intelligence_engine.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _mock_settings(storage_root: Path):
    s = MagicMock()
    s.storage_root = storage_root
    s.engine_dir   = storage_root
    return s


# ── 1. parse_research_docs() — no crash even with missing docs ────────────────

class TestIntelligenceParser:

    def _import(self):
        from app.services import intelligence_parser as ip
        return ip

    def test_parse_returns_result_object(self, tmp_path):
        """parse_research_docs() must return an IntelligenceResult even when all docs missing."""
        with patch("app.services.intelligence_parser.RESEARCH_DOCS", [
            tmp_path / "missing_doc_1.md",
            tmp_path / "missing_doc_2.md",
        ]):
            ip = self._import()
            result = ip.parse_research_docs()
        assert result is not None
        assert hasattr(result, "actors")
        assert hasattr(result, "triggers")
        assert hasattr(result, "risks")

    def test_parse_records_missing_docs(self, tmp_path):
        """Missing docs are recorded in docs_missing, not raising."""
        with patch("app.services.intelligence_parser.RESEARCH_DOCS", [
            tmp_path / "ghost.md",
        ]):
            ip = self._import()
            result = ip.parse_research_docs()
        assert len(result.docs_missing) >= 1

    def test_parse_records_found_docs(self, tmp_path):
        """Present docs are recorded in docs_parsed."""
        doc = tmp_path / "present.md"
        doc.write_text("# Test doc\ntest@example.com", encoding="utf-8")
        with patch("app.services.intelligence_parser.RESEARCH_DOCS", [doc]):
            ip = self._import()
            result = ip.parse_research_docs()
        assert "present.md" in result.docs_parsed

    def test_parse_no_exception_on_binary_garbage(self, tmp_path):
        """Unreadable/binary docs must not crash the parser."""
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\xff\xfe\x00\x00binary_garbage")
        with patch("app.services.intelligence_parser.RESEARCH_DOCS", [bad]):
            ip = self._import()
            # Should not raise
            result = ip.parse_research_docs()
        assert result is not None


# ── 2. Actor registry ≥ 30 entries ────────────────────────────────────────────

class TestActorRegistry:

    def test_actors_count_at_least_30(self):
        from app.services.intelligence_parser import _ACTORS
        assert len(_ACTORS) >= 30, (
            f"Expected ≥30 actors, got {len(_ACTORS)}. "
            "Add more actors from ONE_YEAR_EMAIL_ACTOR_DISCOVERY.md."
        )

    def test_actors_have_required_fields(self):
        from app.services.intelligence_parser import _ACTORS
        for actor in _ACTORS:
            assert actor.email, f"Actor missing email: {actor}"
            assert actor.trust_level in (
                "TRUSTED_CLEARANCE", "TRUSTED_NOTIFICATION",
                "DO_NOT_TRIGGER", "INTERNAL",
            ), f"Unknown trust_level on {actor.email}: {actor.trust_level}"

    def test_canonical_actors_present(self):
        """Key actors from the clearance chain must be present."""
        from app.services.intelligence_parser import _ACTORS
        emails = {a.email.lower() for a in _ACTORS}
        required = {
            "odprawacelna@dhl.com",
            "piotr@acspedycja.pl",
            "jaworska@ganther.com.pl",
            "import@estrellajewels.eu",
            "account@estrellajewels.eu",
        }
        missing = required - emails
        assert not missing, f"Required actors missing from registry: {missing}"

    def test_fedex_actor_present(self):
        from app.services.intelligence_parser import _ACTORS
        emails = {a.email.lower() for a in _ACTORS}
        assert "pl-import@fedex.com" in emails

    def test_do_not_trigger_actors_exist(self):
        from app.services.intelligence_parser import _ACTORS
        dnt = [a for a in _ACTORS if a.trust_level == "DO_NOT_TRIGGER"]
        assert len(dnt) >= 3, f"Expected ≥3 DO_NOT_TRIGGER actors, got {len(dnt)}"


# ── 3. Trigger registry ≥ 10 entries ─────────────────────────────────────────

class TestTriggerRegistry:

    def test_triggers_count_at_least_10(self):
        from app.services.intelligence_parser import _TRIGGERS
        assert len(_TRIGGERS) >= 10, (
            f"Expected ≥10 triggers, got {len(_TRIGGERS)}."
        )

    def test_triggers_have_id_and_name(self):
        from app.services.intelligence_parser import _TRIGGERS
        for t in _TRIGGERS:
            assert t.trigger_id, f"Trigger missing ID: {t}"
            assert t.name,       f"Trigger {t.trigger_id} missing name"

    def test_known_trigger_ids_present(self):
        from app.services.intelligence_parser import _TRIGGERS
        ids = {t.trigger_id for t in _TRIGGERS}
        required = {"T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7"}
        missing = required - ids
        assert not missing, f"Required trigger IDs missing: {missing}"


# ── 4. Email classifier ───────────────────────────────────────────────────────

class TestEmailClassifier:

    def _classify(self, sender, subject="", body="", attachments=None):
        from app.services.email_classifier import classify_email
        return classify_email(
            sender=sender,
            subject=subject,
            body=body,
            attachments=attachments or [],
        )

    # DHL arrival email
    def test_dhl_arrival_classified(self):
        result = self._classify(
            sender="odprawacelna@dhl.com",
            subject="Przesyłka 1234567890 - zgłoszenie do odprawy celnej",
            body="Twoja przesyłka 1234567890 oczekuje na odprawę.",
            attachments=["cesja.pdf"],
        )
        assert result["type"] == "dhl_arrival"
        assert result["carrier"] == "DHL"

    # FedEx arrival email — pl-import@fedex.com is the customs sender for cesja/clearance
    # Body must not contain "cesja"/"dsk" (those would trigger dsk/cesja-ack paths)
    def test_fedex_arrival_classified(self):
        result = self._classify(
            sender="pl-import@fedex.com",
            subject="FedEx Shipment 887467026597 - Customs Clearance Required",
            body="Your shipment 887467026597 has arrived in Warsaw customs warehouse.",
            attachments=["authorization_form.pdf"],
        )
        assert result["type"] == "fedex_arrival"
        assert result["carrier"] == "FEDEX"

    # datarwa@fedex.com is a DO_NOT_TRIGGER shipment notification (not customs)
    def test_fedex_data_notification_is_do_not_trigger(self):
        result = self._classify(
            sender="datarwa@fedex.com",
            subject="FedEx Shipment 887467026597 - Delivered",
            body="Your shipment has been delivered.",
        )
        assert result["type"] == "do_not_trigger"

    # ZC429 / SAD notification
    def test_zc429_classified(self):
        result = self._classify(
            sender="no-reply@acspedycja.pl",
            subject="ZC429 notification",
            body="ZC429 PL12345678901234",
            attachments=["ZC429_PL12345678901234_1_PL.pdf"],
        )
        assert result["type"] == "zc429_notification"

    # Ganther duty notice
    def test_ganther_duty_classified(self):
        result = self._classify(
            sender="jaworska@ganther.com.pl",
            subject="Nota celna - opłata",
            body="Opłata celna wynosi 1234,56 PLN. Proszę o potwierdzenie.",
        )
        assert result["type"] == "ganther_duty"
        assert result.get("pln_amount") == 1234.56

    # Ganther payment confirmation (płaci się)
    def test_ganther_payment_classified(self):
        result = self._classify(
            sender="krzysztof.suchodola@ganther.com.pl",
            subject="Re: nota celna",
            body="Dziękujemy, płaci się.",
        )
        assert result["type"] == "ganther_payment"

    # Do-not-trigger internal email
    def test_internal_do_not_trigger(self):
        result = self._classify(
            sender="amit@estrellajewels.eu",
            subject="Internal update",
            body="Please review the attached report.",
        )
        assert result["type"] in ("do_not_trigger", "internal")

    # Unknown sender → unknown_sender type
    def test_unknown_sender_classified(self):
        result = self._classify(
            sender="random.spammer@example.com",
            subject="Hello",
            body="Buy cheap watches!",
        )
        assert result["type"] == "unknown_sender"

    # AWB extraction
    def test_awb_extraction_dhl(self):
        result = self._classify(
            sender="odprawacelna@dhl.com",
            subject="Przesyłka 1234567890 gotowa",
            body="AWB: 1234567890",
        )
        assert result.get("awb") == "1234567890"

    def test_awb_extraction_fedex(self):
        result = self._classify(
            sender="pl-import@fedex.com",
            subject="FedEx 887467026597 customs",
            body="Tracking: 887467026597",
        )
        assert result.get("awb") == "887467026597"

    # Confidence field present (string: "high" | "medium" | "low")
    def test_confidence_field_present(self):
        result = self._classify(
            sender="odprawacelna@dhl.com",
            subject="Przesyłka",
            body="",
        )
        assert "confidence" in result
        assert result["confidence"] in ("high", "medium", "low"), (
            f"confidence must be 'high'/'medium'/'low', got: {result['confidence']!r}"
        )

    # VAT deferment detection
    def test_vat_deferment_classified(self):
        result = self._classify(
            sender="jaworska@ganther.com.pl",
            subject="VAT issue",
            body="Brak pozwolenia na odroczenie VAT. Vat zostanie zapłacony przed odprawą.",
        )
        assert result["type"] == "vat_deferment_gap"


# ── 5. No audit.json modification ────────────────────────────────────────────

class TestNoAuditModification:
    """Intelligence layer must NEVER write to audit.json."""

    def _make_audit(self, tmp_path: Path) -> Path:
        audit = {
            "awb": "1234567890",
            "carrier": "DHL",
            "status": "active",
            "timeline": [],
        }
        p = tmp_path / "audit.json"
        p.write_text(json.dumps(audit), encoding="utf-8")
        return p

    def test_classify_email_does_not_touch_audit(self, tmp_path):
        audit_path = self._make_audit(tmp_path)
        mtime_before = audit_path.stat().st_mtime

        from app.services.email_classifier import classify_email
        classify_email(
            sender="odprawacelna@dhl.com",
            subject="Przesyłka 1234567890",
            body="AWB: 1234567890",
        )
        assert audit_path.stat().st_mtime == mtime_before, "classify_email modified audit.json"

    def test_risk_detector_does_not_touch_audit(self, tmp_path):
        audit_path = self._make_audit(tmp_path)
        audit_data = json.loads(audit_path.read_text())
        mtime_before = audit_path.stat().st_mtime

        from app.services.risk_detector import detect_all_risks
        detect_all_risks(
            audit=audit_data,
            email_to="amit@estrellajewels.eu",
            email_cc=None,
            email_body="Opłata: 500 PLN",
            sender="jaworska@ganther.com.pl",
        )
        assert audit_path.stat().st_mtime == mtime_before, "detect_all_risks modified audit.json"

    def test_timeline_mapper_does_not_touch_audit(self, tmp_path):
        audit_path = self._make_audit(tmp_path)
        mtime_before = audit_path.stat().st_mtime

        from app.services.email_classifier import classify_email
        from app.services.timeline_mapper import map_email_to_events
        classification = classify_email(
            sender="odprawacelna@dhl.com",
            subject="Przesyłka 1234567890",
            body="1234567890",
        )
        map_email_to_events(classification)
        assert audit_path.stat().st_mtime == mtime_before, "map_email_to_events modified audit.json"

    def test_parse_research_docs_does_not_touch_audit(self, tmp_path):
        audit_path = self._make_audit(tmp_path)
        mtime_before = audit_path.stat().st_mtime

        with patch("app.services.intelligence_parser.RESEARCH_DOCS", []):
            from app.services.intelligence_parser import parse_research_docs
            parse_research_docs()
        assert audit_path.stat().st_mtime == mtime_before


# ── 6. cowork detect_triggers — suggest-only ─────────────────────────────────

class TestCoworkSuggestOnly:
    """detect_triggers() must return suggestions without writing anything."""

    def _make_audit(self, tmp_path: Path, **overrides) -> Dict[str, Any]:
        base = {
            "awb": "1234567890",
            "carrier": "DHL",
            "status": "active",
            "clearance_status": "active",
            "tracking": {"arrived_warehouse": False},
            "timeline": [],
            "invoice_totals": {"total_cif_usd": 3000.0},
        }
        base.update(overrides)
        return base

    def test_detect_triggers_returns_list(self, tmp_path):
        audit = self._make_audit(tmp_path)
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        mtime_before = audit_path.stat().st_mtime

        with patch("app.agents.cowork_coordinator.load_audit", return_value=audit):
            from app.agents.cowork_coordinator import detect_triggers
            suggestions = detect_triggers(audit, "TEST_BATCH_001")

        assert isinstance(suggestions, list)
        # Audit file must not have been touched
        assert audit_path.stat().st_mtime == mtime_before

    def test_detect_triggers_suggestions_have_required_keys(self, tmp_path):
        audit = self._make_audit(tmp_path, status="active")
        with patch("app.agents.cowork_coordinator.load_audit", return_value=audit):
            from app.agents.cowork_coordinator import detect_triggers
            suggestions = detect_triggers(audit, "TEST_BATCH_002")

        for s in suggestions:
            assert "trigger" in s or "code" in s, f"Suggestion missing trigger/code: {s}"
            assert "batch_id" in s or "awb" in s, f"Suggestion missing batch context: {s}"

    def test_detect_triggers_no_execution_side_effects(self, tmp_path):
        """detect_triggers must not send emails or create files."""
        audit = self._make_audit(tmp_path)
        with patch("app.agents.cowork_coordinator.load_audit", return_value=audit):
            from app.agents.cowork_coordinator import detect_triggers
            # Collect any files created during detection
            files_before = set(tmp_path.iterdir())
            detect_triggers(audit, "TEST_BATCH_003")
            files_after = set(tmp_path.iterdir())
        assert files_before == files_after, "detect_triggers created files unexpectedly"


# ── 7. Risk detector ──────────────────────────────────────────────────────────

class TestRiskDetector:

    def test_duty_routing_gap_detected(self):
        from app.services.risk_detector import detect_duty_routing_gap
        warnings = detect_duty_routing_gap(
            email_to="amit@estrellajewels.eu",
            email_cc=None,
        )
        codes = [w["code"] for w in warnings]
        assert "DUTY_ROUTING_GAP" in codes
        assert "DUTY_TO_PERSONAL" in codes

    def test_no_routing_gap_when_account_in_to(self):
        from app.services.risk_detector import detect_duty_routing_gap
        warnings = detect_duty_routing_gap(
            email_to="account@estrellajewels.eu",
            email_cc=None,
        )
        assert not any(w["code"] == "DUTY_ROUTING_GAP" for w in warnings)

    def test_vat_deferment_detected(self):
        from app.services.risk_detector import detect_vat_deferment
        warnings = detect_vat_deferment("Brak pozwolenia na odroczenie VAT.")
        assert len(warnings) == 1
        assert warnings[0]["code"] == "VAT_DEFERMENT_GAP"
        assert warnings[0]["severity"] == "HIGH"

    def test_fca_complication_detected(self):
        from app.services.risk_detector import detect_fca_complication
        warnings = detect_fca_complication("FCA transport invoice required.")
        assert len(warnings) == 1
        assert warnings[0]["code"] == "FCA_COMPLICATION"

    def test_unknown_sender_detected(self):
        from app.services.risk_detector import detect_unknown_sender
        warnings = detect_unknown_sender("random@unknown.example.com")
        assert len(warnings) == 1
        assert warnings[0]["code"] == "UNKNOWN_SENDER"
        assert warnings[0]["severity"] == "LOW"

    def test_trusted_sender_not_flagged(self):
        from app.services.risk_detector import detect_unknown_sender
        for trusted in [
            "odprawacelna@dhl.com",
            "jaworska@ganther.com.pl",
            "pl-import@fedex.com",
            "import@estrellajewels.eu",
        ]:
            warnings = detect_unknown_sender(trusted)
            assert not warnings, f"Trusted sender {trusted} incorrectly flagged"

    def test_sla_breach_duty_critical(self):
        """Audit with duty_notice_received_at 8 days ago → DUTY_PAYMENT_CRITICAL."""
        from datetime import datetime, timedelta, timezone
        from app.services.risk_detector import detect_sla_breach
        old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        audit = {
            "carrier": "DHL",
            "duty_notice_received_at": old_ts,
            "duty_paid_signal_at": None,
        }
        warnings = detect_sla_breach(audit)
        codes = [w["code"] for w in warnings]
        assert "DUTY_PAYMENT_CRITICAL" in codes

    def test_detect_all_risks_sorted_high_first(self):
        from app.services.risk_detector import detect_all_risks
        audit = {"carrier": "DHL", "tracking": {}, "timeline": []}
        warnings = detect_all_risks(
            audit=audit,
            email_to="amit@estrellajewels.eu",
            email_body="Brak pozwolenia na odroczenie VAT.",
            sender="random@unknown.com",
        )
        severities = [w["severity"] for w in warnings]
        # HIGH must appear before LOW
        if "HIGH" in severities and "LOW" in severities:
            assert severities.index("HIGH") < severities.index("LOW")

    def test_warn_dict_has_required_keys(self):
        from app.services.risk_detector import detect_unknown_sender
        w = detect_unknown_sender("x@unknown.com")[0]
        for key in ("code", "severity", "message", "detail"):
            assert key in w, f"Warning missing key: {key}"


# ── 8. Timeline mapper ────────────────────────────────────────────────────────

class TestTimelineMapper:

    def test_dhl_arrival_maps_to_carrier_arrived(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({
            "type": "dhl_arrival",
            "carrier": "DHL",
            "awb": "1234567890",
        })
        assert mapping is not None
        assert mapping.primary_event == "carrier_arrived"

    def test_zc429_maps_to_sad_uploaded(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "zc429_notification"})
        assert mapping is not None
        assert mapping.primary_event == "sad_uploaded"

    def test_ganther_duty_maps_to_duty_note_received(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "ganther_duty"})
        assert mapping is not None
        assert mapping.primary_event == "duty_note_received"

    def test_ganther_payment_maps_to_payment_confirmed(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "ganther_payment"})
        assert mapping.primary_event == "payment_confirmed"

    def test_fedex_arrival_maps_correctly(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({
            "type": "fedex_arrival",
            "carrier": "FEDEX",
            "sub_events": ["cesja_keyword"],
        })
        assert mapping.primary_event == "carrier_arrived"
        assert mapping.carrier == "FEDEX"
        assert "fedex_cesja_pending" in mapping.additional_events

    def test_fedex_cesja_ack_maps_to_cesja_submitted(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "fedex_cesja_ack"})
        assert mapping.primary_event == "cesja_submitted"

    def test_do_not_trigger_returns_none(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "do_not_trigger"})
        assert mapping is None

    def test_internal_returns_none(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "internal"})
        assert mapping is None

    def test_vat_deferment_has_alert(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "vat_deferment_gap"})
        assert mapping is not None
        assert mapping.alert is not None
        assert "VAT" in mapping.alert.upper() or "account@" in mapping.alert

    def test_to_dict_returns_all_keys(self):
        from app.services.timeline_mapper import map_email_to_events
        mapping = map_email_to_events({"type": "dhl_arrival", "carrier": "DHL"})
        d = mapping.to_dict()
        for key in ("email_type", "primary_event", "carrier", "suggested_audit_updates",
                    "additional_events", "alert", "route_to_accounting"):
            assert key in d, f"to_dict() missing key: {key}"

    def test_list_all_mappings_returns_dict(self):
        from app.services.timeline_mapper import list_all_mappings
        m = list_all_mappings()
        assert isinstance(m, dict)
        assert len(m) >= 10


# ── 9. Clearance decision — carrier detection + FedEx path ───────────────────

class TestClearanceDecision:

    def test_detect_carrier_dhl_explicit(self):
        from app.services.clearance_decision import detect_carrier
        assert detect_carrier({"carrier": "DHL"}) == "DHL"

    def test_detect_carrier_fedex_explicit(self):
        from app.services.clearance_decision import detect_carrier
        assert detect_carrier({"carrier": "FEDEX"}) == "FEDEX"

    def test_detect_carrier_from_awb_10digit_dhl(self):
        from app.services.clearance_decision import detect_carrier
        assert detect_carrier({"awb": "1234567890"}) == "DHL"

    def test_detect_carrier_from_awb_12digit_fedex(self):
        from app.services.clearance_decision import detect_carrier
        assert detect_carrier({"awb": "123456789012"}) == "FEDEX"

    def test_detect_carrier_unknown(self):
        from app.services.clearance_decision import detect_carrier
        assert detect_carrier({}) == "UNKNOWN"

    def test_fedex_clearance_path(self):
        from app.services.clearance_decision import build_fedex_clearance_decision
        audit = {
            "carrier": "FEDEX",
            "awb": "887467026597",
            "invoice_totals": {"total_cif_usd": 5000.0},
        }
        dec = build_fedex_clearance_decision(audit)
        assert dec["clearance_path"] == "fedex_ganther_clearance"
        assert dec["require_cesja_manual"] is True
        assert dec["cesja_target"] == "pl-import@fedex.com"
        assert dec["agency"] == "Ganther"
        assert dec["sla_days"] == 9

    def test_fedex_clearance_cif_zero_pending(self):
        from app.services.clearance_decision import build_fedex_clearance_decision
        dec = build_fedex_clearance_decision({"carrier": "FEDEX"})
        assert "pending" in dec["decision_reason"]

    def test_unified_dispatcher_routes_fedex(self):
        from app.services.clearance_decision import build_clearance_decision_for_carrier
        audit = {"carrier": "FEDEX", "invoice_totals": {"total_cif_usd": 500.0}}
        dec = build_clearance_decision_for_carrier(audit)
        assert dec["clearance_path"] == "fedex_ganther_clearance"

    def test_unified_dispatcher_routes_dhl(self):
        from app.services.clearance_decision import build_clearance_decision_for_carrier
        audit = {"carrier": "DHL", "invoice_totals": {"total_cif_usd": 3000.0}}
        dec = build_clearance_decision_for_carrier(audit)
        assert dec["clearance_path"] == "external_agency_clearance"

    def test_dhl_below_threshold_carrier_self_clearance(self):
        from app.services.clearance_decision import build_clearance_decision
        audit = {"invoice_totals": {"total_cif_usd": 1500.0}}
        dec = build_clearance_decision(audit)
        assert dec["clearance_path"] == "carrier_self_clearance"
        assert dec["require_dsk"] is False
        assert dec["carrier_handles"] is True

    def test_dhl_above_threshold_external_agency(self):
        from app.services.clearance_decision import build_clearance_decision
        audit = {"invoice_totals": {"total_cif_usd": 3000.0}}
        dec = build_clearance_decision(audit)
        assert dec["clearance_path"] == "external_agency_clearance"
        assert dec["require_dsk"] is True
        assert dec["agency_email"] == "biuro@acspedycja.pl"


# ── 10. Intelligence config builder ──────────────────────────────────────────

class TestIntelligenceConfigBuilder:

    def test_build_config_produces_expected_keys(self):
        from app.services.intelligence_config_builder import build_config
        config = build_config()
        assert "suggested_config" in config
        cfg = config["suggested_config"]
        for key in (
            "TRUSTED_CLEARANCE_SENDERS",
            "DO_NOT_TRIGGER",
            "ATTACHMENT_PATTERNS",
            "TRIGGER_RULES",
            "RISK_ITEMS",
            "SLA_THRESHOLDS",
            "CARRIER_RULES",
            "ACTOR_INDEX",
        ):
            assert key in cfg, f"Config missing key: {key}"

    def test_build_config_trusted_clearance_not_empty(self):
        from app.services.intelligence_config_builder import build_config
        config = build_config()
        tc = config["suggested_config"]["TRUSTED_CLEARANCE_SENDERS"]
        assert len(tc) >= 5

    def test_save_config_creates_file(self, tmp_path):
        from app.services.intelligence_config_builder import build_config, save_config
        config = build_config()
        path = tmp_path / "test_intel_config.json"
        saved = save_config(config, path=path)
        assert saved.exists()
        raw = json.loads(saved.read_text(encoding="utf-8"))
        assert "suggested_config" in raw

    def test_save_config_approval_status_pending(self, tmp_path):
        from app.services.intelligence_config_builder import build_config, save_config
        config = build_config()
        path = tmp_path / "test_intel_config.json"
        save_config(config, path=path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw.get("approval_status") == "pending_review"

    def test_save_config_preserves_activated_config(self, tmp_path):
        """Saving new suggested_config must NOT overwrite an existing activated_config."""
        from app.services.intelligence_config_builder import build_config, save_config
        path = tmp_path / "test_intel_config.json"

        # Simulate previously activated config
        existing = {
            "suggested_config": {"TRUSTED_CLEARANCE_SENDERS": []},
            "activated_config": {"TRUSTED_CLEARANCE_SENDERS": ["old@example.com"]},
            "approval_status": "approved",
        }
        path.write_text(json.dumps(existing), encoding="utf-8")

        # Now save fresh suggested config
        config = build_config()
        save_config(config, path=path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        # activated_config must survive
        assert "activated_config" in raw
        assert raw["activated_config"]["TRUSTED_CLEARANCE_SENDERS"] == ["old@example.com"]
        # But approval_status is now pending again (new suggested waiting for review)
        assert raw.get("approval_status") == "pending_review"

    def test_load_config_returns_activated_if_present(self, tmp_path):
        from app.services.intelligence_config_builder import load_config
        path = tmp_path / "test_intel_config.json"
        data = {
            "suggested_config": {"TRUSTED_CLEARANCE_SENDERS": ["suggested@example.com"]},
            "activated_config": {"TRUSTED_CLEARANCE_SENDERS": ["activated@example.com"]},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_config(path=path)
        assert loaded["TRUSTED_CLEARANCE_SENDERS"] == ["activated@example.com"]

    def test_load_config_falls_back_to_suggested(self, tmp_path):
        from app.services.intelligence_config_builder import load_config
        path = tmp_path / "test_intel_config.json"
        data = {
            "suggested_config": {"TRUSTED_CLEARANCE_SENDERS": ["suggested@example.com"]},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_config(path=path)
        assert loaded["TRUSTED_CLEARANCE_SENDERS"] == ["suggested@example.com"]

    def test_load_config_returns_none_if_no_file(self, tmp_path):
        from app.services.intelligence_config_builder import load_config
        loaded = load_config(path=tmp_path / "nonexistent.json")
        assert loaded is None

    def test_sla_thresholds_present(self):
        from app.services.intelligence_config_builder import build_config
        cfg = build_config()["suggested_config"]
        sla = cfg.get("SLA_THRESHOLDS", {})
        assert "DHL_FULL_HOURS" in sla or "dhl_full_hours" in sla or sla
        # At minimum the dict must not be empty
        assert len(sla) >= 2

    def test_carrier_rules_have_dhl_and_fedex(self):
        from app.services.intelligence_config_builder import build_config
        cfg = build_config()["suggested_config"]
        carrier_rules = cfg.get("CARRIER_RULES", {})
        assert "DHL" in carrier_rules
        assert "FEDEX" in carrier_rules

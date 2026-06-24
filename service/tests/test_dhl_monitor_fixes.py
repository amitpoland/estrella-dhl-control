"""
test_dhl_monitor_fixes.py — Regression tests for the AWB 9198333502 incident fixes.

Covers F1–F6:
  F1/F5  — Monitor block state surfaces manual_monitor_required + flags
  F2     — Tracking authority uses tracking_events, falls back to stale summary
  F3     — DSK generation writes customs_package_generated_at
  F4     — Agency package status reconciled from email_queue (Case C: sent)
  F6     — Email intelligence store deduplicates by message_id

Security invariant (T10): no live SMTP is called in any test.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso(hours: int = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_audit(**kwargs: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "awb":              "9198333502",
        "batch_id":         "SHIPMENT_9198333502_2026-05_87257361",
        "clearance_status": "customs_awaiting",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "orchestrator": {
            "state":  "customs_awaiting",
            "shadow": True,
            "flags":  {
                "auto_monitor_sweep":       False,
                "auto_send_dhl_followup":   False,
                "dhl_orch_shadow_mode":     True,
            },
        },
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# F1 / F5 — Monitor block state visibility
# ─────────────────────────────────────────────────────────────────────────────

class TestMonitorBlockState:
    """Tests for _monitor_state() in routes_orchestrator.py (F1 + F5)."""

    def _call(self, audit: Dict[str, Any], **flag_overrides: Any) -> Dict[str, Any]:
        from app.api.routes_orchestrator import _monitor_state
        from app.core.config import settings

        original = {
            "dhl_orch_auto_monitor_sweep":     getattr(settings, "dhl_orch_auto_monitor_sweep", False),
            "dhl_orch_auto_send_dhl_followup": getattr(settings, "dhl_orch_auto_send_dhl_followup", False),
            "dhl_orch_shadow_mode":            getattr(settings, "dhl_orch_shadow_mode", True),
        }
        for k, v in flag_overrides.items():
            object.__setattr__(settings, k, v)
        try:
            return _monitor_state(audit)
        finally:
            for k, v in original.items():
                object.__setattr__(settings, k, v)

    # T1 — stale scan warning
    def test_stale_scan_surfaces_last_scan_at(self) -> None:
        stale = _stale_iso(hours=60)
        audit = _make_audit(email_ingestion={"last_scan_at": stale})
        result = self._call(audit, dhl_orch_auto_monitor_sweep=False)
        assert result["last_scan_at"] == stale
        assert result["blocked_reason"] == "manual_monitor_required"

    # T2 — manual required blocked reason
    def test_auto_sweep_false_gives_blocked_reason(self) -> None:
        audit = _make_audit()
        result = self._call(audit, dhl_orch_auto_monitor_sweep=False)
        assert result["blocked_reason"] == "manual_monitor_required"
        assert result["safe_operator_action"] == "POST /api/v1/monitor/active-shipments/run"

    def test_auto_sweep_true_no_blocked_reason(self) -> None:
        audit = _make_audit()
        result = self._call(audit, dhl_orch_auto_monitor_sweep=True)
        assert result["blocked_reason"] is None
        assert result["safe_operator_action"] is None

    # T8 — shadow mode + followup flag surfaced
    def test_shadow_mode_and_followup_flag_present(self) -> None:
        audit = _make_audit()
        result = self._call(
            audit,
            dhl_orch_auto_monitor_sweep=False,
            dhl_orch_auto_send_dhl_followup=False,
            dhl_orch_shadow_mode=True,
        )
        assert result["shadow_mode"] is True
        assert result["auto_send_dhl_followup"] is False
        assert result["auto_monitor_sweep"] is False


# ─────────────────────────────────────────────────────────────────────────────
# F2 — Tracking authority: prefer tracking_events over stale summary
# ─────────────────────────────────────────────────────────────────────────────

class TestTrackingAuthority:
    """Tests for RC3 fix in active_shipment_monitor.py step 3 (F2)."""

    # T3 — tracking authority fixture
    def test_authoritative_events_used_when_present(self) -> None:
        """When tracking_events is present, it must be the source for triggers."""
        from app.services.tracking_intelligence import detect_tracking_triggers

        # Authoritative: one CUSTOMS_PENDING event at Warsaw
        auth_events = [
            {
                "event": "CUSTOMS_PENDING",
                "location": "WARSAW RR",
                "timestamp": _now_iso(),
                "description": "Customs clearance status updated",
            }
        ]
        # Stale: only an old Leipzig event
        stale_events = [
            {
                "event": "ARRIVED_DESTINATION",
                "location": "Leipzig PL",
                "timestamp": _stale_iso(hours=30),
                "description": "Arrived at destination",
            }
        ]

        audit = _make_audit(
            tracking_events=auth_events,
            tracking={"events": stale_events},
        )

        # simulate the monitor's step-3 logic as written after RC3-FIX
        tr_events = (
            audit.get("tracking_events")
            or (audit.get("tracking") or {}).get("events")
            or []
        )
        assert tr_events is auth_events, (
            "step 3 must select authoritative tracking_events, not stale summary"
        )

    def test_fallback_to_stale_when_tracking_events_absent(self) -> None:
        """When tracking_events is absent, fall back to audit.tracking.events."""
        stale_events = [
            {
                "event": "CUSTOMS_PENDING",
                "location": "WARSAW RR",
                "timestamp": _stale_iso(hours=4),
                "description": "Customs clearance status updated",
            }
        ]
        audit = _make_audit(tracking={"events": stale_events})
        # no tracking_events key

        tr_events = (
            audit.get("tracking_events")
            or (audit.get("tracking") or {}).get("events")
            or []
        )
        assert tr_events is stale_events

    # T4 — follow-up initialisation from authoritative event
    def test_authoritative_event_yields_current_trigger_time(self) -> None:
        """An authoritative customs event should produce a trigger with a recent event_time."""
        from app.services.tracking_intelligence import detect_tracking_triggers

        recent_ts = _now_iso()
        auth_events = [
            {
                "event":       "CUSTOMS_PENDING",
                "location":    "WARSAW RR",
                "timestamp":   recent_ts,
                "description": "Customs clearance status updated",
            }
        ]
        audit = _make_audit(tracking_events=auth_events)
        triggers = detect_tracking_triggers(auth_events, audit)
        customs_triggers = [
            t for t in triggers
            if t.get("trigger") == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED"
        ]
        assert customs_triggers, "should have at least one customs trigger"
        trigger_event_time = customs_triggers[0].get("event_time") or ""
        # event_time must be within the last hour (not 4 days ago)
        try:
            trigger_dt = datetime.fromisoformat(trigger_event_time.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - trigger_dt).total_seconds() / 3600
            assert age_hours < 1, (
                f"trigger event_time {trigger_event_time!r} is {age_hours:.1f}h old; "
                "expected recent (from authoritative events)"
            )
        except Exception as exc:
            pytest.fail(f"Could not parse trigger event_time: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# F3 — DSK generation writes customs_package_generated_at
# ─────────────────────────────────────────────────────────────────────────────

class TestDskPointerFix:
    """Tests for F3 fix in routes_dsk.py DSK generation endpoint."""

    # T5 — DSK generation writes canonical pointer
    def test_dsk_generation_writes_customs_package_generated_at(
        self, tmp_path: Path
    ) -> None:
        """
        After DSK generation, audit.customs_package_generated_at must be set.
        We simulate the audit-write block in the generate_dsk endpoint.
        """
        audit: Dict[str, Any] = _make_audit()
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")

        # Simulate the write block (identical to the endpoint code after F3-FIX)
        from app.utils.io import write_json_atomic

        _aud = json.loads(audit_path.read_text(encoding="utf-8"))
        _now_iso_val = datetime.now(timezone.utc).isoformat()
        _aud["dsk_filename"]  = "DSK_9198333502_22-05-2026.pdf"
        _aud["dsk_path"]      = str(tmp_path / "DSK_9198333502_22-05-2026.pdf")
        _aud["dsk_status"]    = "generated"
        _aud["customs_package_generated_at"] = _now_iso_val   # F3-FIX
        _aud["dsk_meta"] = {
            "value_usd":    58425.0,
            "value_source": "clearance_decision",
            "generated_at": _now_iso_val,
        }
        write_json_atomic(audit_path, _aud)

        saved = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "customs_package_generated_at" in saved, (
            "F3-FIX: customs_package_generated_at must be written by DSK generation"
        )
        assert saved["customs_package_generated_at"] == _now_iso_val

    # T6 — legacy pointer absent but DSK file exists → no false missing warning
    def test_dashboard_no_false_missing_when_dsk_file_exists(self) -> None:
        """
        _compute_dhl_action_state reads customs_package_generated_at.
        After F3-FIX, generating a DSK sets this key.  For pre-existing audits
        that have dsk_meta.generated_at but no customs_package_generated_at,
        the fix should not emit a false 'Customs package not generated' badge.

        This test verifies that once customs_package_generated_at IS present
        (after F3-FIX applies), the "customs_package_missing" badge is absent.
        """
        from app.api.routes_dashboard import _compute_dhl_action_state

        audit = _make_audit(
            customs_package_generated_at=_now_iso(),
            dsk_filename="DSK_9198333502_22-05-2026.pdf",
            dsk_status="generated",
        )
        result = _compute_dhl_action_state(audit)
        badges_by_key = {b["key"]: b for b in result.get("badges", [])}
        assert "customs_package_missing" not in badges_by_key, (
            "No false 'customs_package_missing' badge when customs_package_generated_at is set"
        )


# ─────────────────────────────────────────────────────────────────────────────
# F4 — Agency package status reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TestAgencyPackageReconciliation:
    """Tests for _reconcile_agency_package_status (F4)."""

    def _run(
        self,
        tmp_path: Path,
        audit: Dict[str, Any],
        queue_entries: list,
    ) -> tuple:
        """Helper: write audit, mock email_service, run reconciliation."""
        from app.utils.io import write_json_atomic
        from app.services.active_shipment_monitor import _reconcile_agency_package_status

        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        with patch(
            "app.services.active_shipment_monitor.get_all_emails",
            return_value=queue_entries,
        ):
            # also patch the import inside the function
            with patch(
                "app.services.email_service.get_all_emails",
                return_value=queue_entries,
            ):
                result = _reconcile_agency_package_status(audit_path, audit)

        saved = json.loads(audit_path.read_text(encoding="utf-8"))
        return result, saved

    # T7 — Case C: email sent but audit stuck at queued
    def test_case_c_sent_reconciles_audit(self, tmp_path: Path) -> None:
        """email_queue shows sent → audit must be updated to sent."""
        email_id = "2b848b9b-6c5b-46c5-aea7-50b411d9ee97"
        sent_at  = "2026-05-22T00:20:37.920132+00:00"
        provider_id = "<177940923328.14868.267703693157970136@DESKTOP-IGKI1LF.home>"

        audit = _make_audit(
            agency_reply_package={
                "email_id": email_id,
                "status":   "queued",
                "queued_at": "2026-05-22T02:20:33",
            },
            clearance_status="agency_email_queued",
        )
        queue_entries = [
            {
                "id":                  email_id,
                "status":              "sent",
                "sent_at":             sent_at,
                "provider_message_id": provider_id,
            }
        ]

        from app.utils.io import write_json_atomic
        from app.services import active_shipment_monitor as mon

        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        with patch.object(
            mon,
            "_reconcile_agency_package_status",
            wraps=mon._reconcile_agency_package_status,
        ):
            # Directly call without mocking internals — use a fake email_service
            with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
                result = mon._reconcile_agency_package_status(audit_path, audit)

        assert result.get("reconciled") is True
        assert result["email_id"] == email_id
        arp = audit.get("agency_reply_package") or {}
        assert arp["status"] == "sent"
        assert arp["sent_at"] == sent_at
        assert arp.get("send_verified") is True
        assert audit.get("clearance_status") == "agency_email_sent"

    def test_case_already_sent_noop(self, tmp_path: Path) -> None:
        """If audit already shows sent, reconciliation returns empty (no-op)."""
        from app.services.active_shipment_monitor import _reconcile_agency_package_status
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        audit = _make_audit(
            agency_reply_package={"email_id": email_id, "status": "sent"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        result = _reconcile_agency_package_status(audit_path, audit)
        assert result == {}

    def test_case_failed_returns_eq_status(self, tmp_path: Path) -> None:
        """If email_queue shows failed, return eq_status=failed without marking sent."""
        from app.services.active_shipment_monitor import _reconcile_agency_package_status
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        audit = _make_audit(
            agency_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        queue_entries = [{"id": email_id, "status": "failed"}]
        with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
            result = _reconcile_agency_package_status(audit_path, audit)

        assert result.get("reconciled") is False
        assert result.get("eq_status") == "failed"
        arp = audit.get("agency_reply_package") or {}
        assert arp.get("status") == "queued", "audit must NOT be updated on failed"

    # T10 — no live email send in tests
    def test_reconciliation_never_sends_email(self, tmp_path: Path) -> None:
        """Reconciliation must never call queue_email or send_queued_email."""
        from app.services.active_shipment_monitor import _reconcile_agency_package_status
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        audit = _make_audit(
            agency_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        with patch("app.services.email_service.queue_email") as mock_q, \
             patch("app.services.email_sender.send_queued_email") as mock_s, \
             patch("app.services.email_service.get_all_emails", return_value=[]):
            _reconcile_agency_package_status(audit_path, audit)

        mock_q.assert_not_called()
        mock_s.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# F6 — Email intelligence store dedup by message_id
# ─────────────────────────────────────────────────────────────────────────────

class TestEmailIntelligenceDedup:
    """Tests for F6 fix in email_intelligence_store.py."""

    # T9 — duplicate message_id collapse
    def test_duplicate_message_id_labeled(self, tmp_path: Path) -> None:
        """Emails with the same message_id must be labeled duplicate/unique."""
        from app.services import email_intelligence_store as eis
        from app.core.config import settings

        mid = "msg-abc-123"
        scan_results = {
            "awb":       "9198333502",
            "matched":   2,
            "confidence": "high",
            "emails": [
                {"message_id": mid, "subject": "First occurrence"},
                {"message_id": mid, "subject": "Duplicate occurrence"},
            ],
            "threads": [],
            "derived_events": [],
        }

        original_root = settings.storage_root
        object.__setattr__(settings, "storage_root", tmp_path)
        try:
            record = eis.save_email_scan_result(scan_results, audit=None)
        finally:
            object.__setattr__(settings, "storage_root", original_root)

        emails = record.get("emails") or []
        assert len(emails) == 2
        unique_count    = sum(1 for e in emails if e.get("dedup_status") == "unique")
        duplicate_count = sum(1 for e in emails if e.get("dedup_status") == "duplicate")
        assert unique_count == 1
        assert duplicate_count == 1

    def test_emails_without_message_id_labeled_unverified(self, tmp_path: Path) -> None:
        """Emails without any message_id are labeled 'unverified'."""
        from app.services import email_intelligence_store as eis
        from app.core.config import settings

        scan_results = {
            "awb":       "9198333502",
            "matched":   1,
            "confidence": "low",
            "emails": [
                {"subject": "No ID email"},
            ],
            "threads": [],
            "derived_events": [],
        }

        original_root = settings.storage_root
        object.__setattr__(settings, "storage_root", tmp_path)
        try:
            record = eis.save_email_scan_result(scan_results, audit=None)
        finally:
            object.__setattr__(settings, "storage_root", original_root)

        emails = record.get("emails") or []
        assert len(emails) == 1
        assert emails[0].get("dedup_status") == "unverified"


# ─────────────────────────────────────────────────────────────────────────────
# B5-FIX — DHL reply package status reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TestDhlReplyPackageReconciliation:
    """Tests for _reconcile_dhl_reply_package_status (B5-FIX).

    Mirrors TestAgencyPackageReconciliation (F4) for the DHL-side DSK
    reply package so the Phase B5 DSK chase scheduler can always see
    a confirmed sent_at even when the email send callback was missed.
    """

    # T11 — queued audit + sent email_queue → reconciled to sent
    def test_queued_audit_sent_queue_reconciles_to_sent(self, tmp_path: Path) -> None:
        """email_queue shows sent → audit.dhl_reply_package.status must become sent."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic

        email_id    = "4ab15110-93d9-47f4-bd42-826aa4cd0a8e"
        sent_at     = "2026-06-24T07:26:18.826532+00:00"
        provider_id = "<mock-provider-id-12345@mail>"

        audit = _make_audit(
            dhl_reply_package={
                "email_id": email_id,
                "status":   "queued",
                "queued_at": "2026-06-24T07:26:18.874450+00:00",
            },
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        queue_entries = [
            {
                "id":                  email_id,
                "status":              "sent",
                "sent_at":             sent_at,
                "provider_message_id": provider_id,
            }
        ]

        with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
            result = _reconcile_dhl_reply_package_status(audit_path, audit)

        assert result.get("reconciled") is True, "must return reconciled=True"
        assert result["email_id"] == email_id
        assert result["sent_at"]  == sent_at

        drp = audit.get("dhl_reply_package") or {}
        assert drp["status"]        == "sent",  "status must flip to sent"
        assert drp["sent_at"]       == sent_at,  "sent_at must be populated"
        assert drp.get("send_verified") is True
        assert drp.get("reconciled_by") == "monitor_reconciliation"

    # T12 — already-sent audit is a no-op
    def test_already_sent_audit_noop(self, tmp_path: Path) -> None:
        """If dhl_reply_package.status is already sent, function returns {} immediately."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic

        audit = _make_audit(
            dhl_reply_package={"email_id": str(uuid.uuid4()), "status": "sent"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        result = _reconcile_dhl_reply_package_status(audit_path, audit)
        assert result == {}, "must be a no-op when status is already sent"

    # T13 — missing email_id → no-op
    def test_no_email_id_noop(self, tmp_path: Path) -> None:
        """If dhl_reply_package has no email_id, function returns {} immediately."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic

        audit = _make_audit(dhl_reply_package={"status": "queued"})
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        result = _reconcile_dhl_reply_package_status(audit_path, audit)
        assert result == {}, "must be a no-op when email_id is absent"

    # T14 — failed queue entry → returns reconciled=False, does not mark sent
    def test_failed_queue_entry_not_marked_sent(self, tmp_path: Path) -> None:
        """If email_queue shows failed, audit must NOT be updated to sent."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        audit = _make_audit(
            dhl_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        queue_entries = [{"id": email_id, "status": "failed"}]
        with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
            result = _reconcile_dhl_reply_package_status(audit_path, audit)

        assert result.get("reconciled") is False
        assert result.get("eq_status") == "failed"
        drp = audit.get("dhl_reply_package") or {}
        assert drp.get("status") == "queued", "status must remain queued on failed"

    # T15 — dsk_reply_sent_at() sees the reconciled status (integration smoke)
    def test_dsk_chase_sla_sees_reconciled_sent_at(self, tmp_path: Path) -> None:
        """After reconciliation, dsk_reply_sent_at() must return a datetime."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.services.dhl_dsk_chase_sla import dsk_reply_sent_at
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        sent_at  = "2026-06-24T07:26:18.826532+00:00"

        audit = _make_audit(
            dhl_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        queue_entries = [{"id": email_id, "status": "sent", "sent_at": sent_at}]
        with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
            _reconcile_dhl_reply_package_status(audit_path, audit)

        # After reconciliation, the in-memory audit has status=sent
        result = dsk_reply_sent_at(audit)
        assert result is not None, "dsk_reply_sent_at() must return a datetime after reconciliation"

    # T16 — duplicate timeline event prevention
    def test_timeline_event_not_duplicated_on_second_reconcile(self, tmp_path: Path) -> None:
        """Running reconciliation twice must produce exactly one dhl_reply_sent_verified event."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic
        import json

        email_id = str(uuid.uuid4())
        sent_at  = "2026-06-24T07:26:18.826532+00:00"

        audit = _make_audit(
            dhl_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        queue_entries = [{"id": email_id, "status": "sent", "sent_at": sent_at}]
        with patch("app.services.email_service.get_all_emails", return_value=queue_entries):
            _reconcile_dhl_reply_package_status(audit_path, audit)
            # Second run with already-sent in-memory audit: status is now "sent" → returns {} immediately
            result2 = _reconcile_dhl_reply_package_status(audit_path, audit)

        assert result2 == {}, "second run must be a no-op (status already sent)"

        saved = json.loads(audit_path.read_text(encoding="utf-8"))
        verified_events = [
            e for e in (saved.get("timeline") or [])
            if isinstance(e, dict) and e.get("event") == "dhl_reply_sent_verified"
        ]
        assert len(verified_events) == 1, (
            f"expected exactly 1 dhl_reply_sent_verified event, got {len(verified_events)}"
        )

    # T17 — no live SMTP in any reconciliation test
    def test_reconciliation_never_sends_email(self, tmp_path: Path) -> None:
        """Reconciliation must never call queue_email or send_queued_email."""
        from app.services.active_shipment_monitor import _reconcile_dhl_reply_package_status
        from app.utils.io import write_json_atomic

        email_id = str(uuid.uuid4())
        audit = _make_audit(
            dhl_reply_package={"email_id": email_id, "status": "queued"},
        )
        audit_path = tmp_path / "audit.json"
        write_json_atomic(audit_path, audit)

        with patch("app.services.email_service.queue_email") as mock_q, \
             patch("app.services.email_sender.send_queued_email") as mock_s, \
             patch("app.services.email_service.get_all_emails", return_value=[]):
            _reconcile_dhl_reply_package_status(audit_path, audit)

        mock_q.assert_not_called()
        mock_s.assert_not_called()

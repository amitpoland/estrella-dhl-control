"""
test_email_evidence_ingestor.py

Tests for email_evidence_ingestor.py:
  1. needs_gap_scan returns False when evidence is complete
  2. needs_gap_scan returns True when dhl_request missing but shipment progressed
  3. needs_gap_scan respects 48h recency window
  4. needs_gap_scan returns True for zero messages when shipment progressed
  5. needs_gap_scan returns False for brand-new batch (no clearance, no flags)
  6. scan_and_ingest returns ok=False when no Zoho credentials
  7. scan_and_ingest stores new emails and returns correct ingested count
  8. scan_and_ingest is idempotent (duplicate message_ids not re-inserted)
  9. scan_and_ingest persists newly discovered dhl_ticket to audit.json
  10. scan_and_ingest returns ok=True with ingested=0 when scan finds nothing
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY",      "test-key")
os.environ.setdefault("STORAGE_ROOT", "/tmp/test_ingestor")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _summary(dhl_req=False, dhl_docs=False, agency_fwd_queued=False,
             our_reply_sent=False, agency_sad=False):
    return {
        "dhl_request_received":    dhl_req,
        "our_dhl_reply_sent":      our_reply_sent,
        "our_dhl_reply_queued":    False,
        "dhl_documents_received":  dhl_docs,
        "agency_forward_sent":     False,
        "agency_forward_queued":   agency_fwd_queued,
        "agency_sad_received":     agency_sad,
        "dhl_invoice_received":    False,
        "agency_invoice_received": False,
    }


def _ev_doc(threads=None, last_scan_at=None, summary=None):
    return {
        "awb":             "9999999999",
        "batch_ids":       ["BATCH_TEST"],
        "threads":         threads or [],
        "last_scan_at":    last_scan_at,
        "last_message_at": None,
        "summary":         summary or _summary(),
    }


def _make_email(mid, ticket=None, sender="odprawacelna@dhl.com",
                subj="T#1WA - DHL - przesyłka numer: 9999999999"):
    return {
        "message_id":  mid,
        "subject":     subj,
        "from":        sender,
        "received_at": "2026-04-29T02:46:18+00:00",
        "dhl_ticket":  ticket,
        "body_snippet": "test body",
        "attachments": [],
    }


def _fake_audit_path(tmp_path, ticket=None):
    data = {"batch_id": "BATCH_TEST", "awb": "9999999999", "dhl_ticket": ticket}
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(data))
    return p, data


# ─────────────────────────────────────────────────────────────────────────────
# needs_gap_scan
# ─────────────────────────────────────────────────────────────────────────────

class TestNeedsGapScan:

    def _call(self, ev_doc_val, audit):
        from app.services.email_evidence_ingestor import needs_gap_scan
        with patch("app.services.email_evidence_store.get_by_awb",
                   return_value=ev_doc_val):
            return needs_gap_scan("9999999999", audit)

    def test_no_gap_when_complete(self):
        ev = _ev_doc(summary=_summary(dhl_req=True, dhl_docs=True))
        assert self._call(ev, {"clearance_status": "dsk_generated"}) is False

    def test_gap_when_progressed_and_no_dhl_request(self):
        """Batch progressed to dsk_generated but dhl_request not recorded."""
        ev = _ev_doc(
            threads=[{"thread_id": "t", "messages": [
                {"event_type": "agency_forward", "direction": "outgoing",
                 "delivery_status": "queued"}
            ]}],
            summary=_summary(agency_fwd_queued=True),
        )
        assert self._call(ev, {"clearance_status": "dsk_generated"}) is True

    def test_respects_recency_window(self):
        """Scanned within 48h — skip rescan."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        ev = _ev_doc(
            summary=_summary(agency_fwd_queued=True),
            last_scan_at=recent,
        )
        assert self._call(ev, {"clearance_status": "dsk_generated"}) is False

    def test_triggers_after_window_expires(self):
        """Last scan > 48h ago — rescan warranted."""
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        ev = _ev_doc(
            summary=_summary(agency_fwd_queued=True),
            last_scan_at=old,
        )
        assert self._call(ev, {"clearance_status": "dsk_generated"}) is True

    def test_gap_zero_messages_with_progression(self):
        """0 messages stored + batch progressed → gap scan needed."""
        ev = _ev_doc(threads=[], summary=_summary())
        assert self._call(ev, {"clearance_status": "polish_description_generated"}) is True

    def test_no_gap_new_batch_no_clearance(self):
        """Brand-new batch: empty clearance, no evidence flags → no scan."""
        ev = _ev_doc(threads=[], summary=_summary())
        assert self._call(ev, {"clearance_status": ""}) is False

    def test_gap_via_evidence_flag_without_clearance_status(self):
        """agency_forward_queued alone is enough to indicate progression."""
        ev = _ev_doc(threads=[], summary=_summary(agency_fwd_queued=True))
        assert self._call(ev, {"clearance_status": ""}) is True


# ─────────────────────────────────────────────────────────────────────────────
# scan_and_ingest  (uses scan_fn= injection to avoid real Zoho calls)
# ─────────────────────────────────────────────────────────────────────────────

class TestScanAndIngest:

    def _ingest(self, tmp_path, emails, ticket=None, known_ticket=None):
        """Run scan_and_ingest with a mock scan_fn and real evidence store ops."""
        from app.services.email_evidence_ingestor import scan_and_ingest
        ap, audit = _fake_audit_path(tmp_path, ticket=known_ticket)
        scan_result = {
            "emails":      emails,
            "scanned":     len(emails),
            "query_used":  f"searchKey=9999999999",
            "scan_method": "rest_api_search",
        }
        fake_scan = MagicMock(return_value=scan_result)

        saved_msgs = {}

        def fake_save(awb, msg, *, source="zoho_rest"):
            mid = msg.get("message_id")
            if mid and mid in saved_msgs:
                return {"action": "duplicate", "message_id": mid}
            saved_msgs[mid] = msg
            return {"action": "inserted", "message_id": mid}

        with patch("app.services.email_evidence_store.get_by_awb",
                   return_value={"threads": [], "summary": {}}), \
             patch("app.services.email_evidence_store.link_batch"), \
             patch("app.services.email_evidence_store.save_message",
                   side_effect=fake_save), \
             patch("app.services.email_evidence_store.update_scan_cursor"):
            result = scan_and_ingest(
                "9999999999", "BATCH_TEST", ap, audit,
                limit=50,
                token_provider=lambda: "tok",
                scan_fn=fake_scan,
            )

        return result, ap

    def test_no_credentials_returns_error(self, tmp_path):
        from app.services.email_evidence_ingestor import scan_and_ingest
        ap, audit = _fake_audit_path(tmp_path)
        result = scan_and_ingest(
            "9999999999", "BATCH_TEST", ap, audit,
            token_provider=None,
            scan_fn=None,
        )
        # With no creds and no scan_fn, it hits the auth check first
        assert result["ok"] is False
        assert result["ingested"] == 0

    def test_stores_new_emails(self, tmp_path):
        emails = [_make_email("msg001"), _make_email("msg002")]
        result, _ = self._ingest(tmp_path, emails)
        assert result["ok"] is True
        assert result["ingested"] == 2
        assert result["total_scanned"] == 2

    def test_idempotent_skips_existing(self, tmp_path):
        """Running twice with same emails: second run inserts 0."""
        from app.services.email_evidence_ingestor import scan_and_ingest
        ap, audit = _fake_audit_path(tmp_path)
        emails = [_make_email("msg001")]
        scan_result = {"emails": emails, "scanned": 1, "query_used": "q",
                       "scan_method": "rest_api_search"}
        fake_scan = MagicMock(return_value=scan_result)

        existing_thread = {"thread_id": "t1",
                           "messages": [{"message_id": "msg001"}]}

        with patch("app.services.email_evidence_store.get_by_awb",
                   return_value={"threads": [existing_thread], "summary": {}}), \
             patch("app.services.email_evidence_store.link_batch"), \
             patch("app.services.email_evidence_store.save_message") as mock_save, \
             patch("app.services.email_evidence_store.update_scan_cursor"):
            result = scan_and_ingest(
                "9999999999", "BATCH_TEST", ap, audit,
                token_provider=lambda: "tok",
                scan_fn=fake_scan,
            )

        # msg001 already in _existing_ids → short-circuited before save_message
        assert result["ok"] is True
        assert result["already_stored"] == 1
        assert result["ingested"] == 0
        mock_save.assert_not_called()

    def test_persists_new_ticket_to_audit(self, tmp_path):
        emails = [_make_email("msg001", ticket="T#1WA2604290000099")]
        result, ap = self._ingest(tmp_path, emails, known_ticket=None)
        assert result["ok"] is True
        saved = json.loads(ap.read_text())
        assert saved.get("dhl_ticket") == "T#1WA2604290000099"

    def test_does_not_overwrite_existing_ticket(self, tmp_path):
        """If audit already has a ticket, don't replace it."""
        emails = [_make_email("msg001", ticket="T#DIFFERENT9999")]
        result, ap = self._ingest(tmp_path, emails, known_ticket="T#1WA2604290000028")
        saved = json.loads(ap.read_text())
        assert saved.get("dhl_ticket") == "T#1WA2604290000028"

    def test_zero_results_no_error(self, tmp_path):
        result, _ = self._ingest(tmp_path, [])
        assert result["ok"] is True
        assert result["ingested"] == 0
        assert result.get("error") is None

    def test_scan_fn_called_with_ticket(self, tmp_path):
        """Known dhl_ticket is passed to scan_fn as dhl_ticket=."""
        from app.services.email_evidence_ingestor import scan_and_ingest
        ap, audit = _fake_audit_path(tmp_path, ticket="T#1WA2604290000028")
        fake_scan = MagicMock(return_value={"emails": [], "scanned": 0,
                                             "query_used": "q", "scan_method": "s"})
        with patch("app.services.email_evidence_store.get_by_awb",
                   return_value={"threads": [], "summary": {}}), \
             patch("app.services.email_evidence_store.link_batch"), \
             patch("app.services.email_evidence_store.update_scan_cursor"):
            scan_and_ingest(
                "9999999999", "BATCH_TEST", ap, audit,
                token_provider=lambda: "tok",
                scan_fn=fake_scan,
            )
        assert fake_scan.called
        # First call must be the targeted AWB search with the known ticket
        first_kwargs = fake_scan.call_args_list[0][1]
        assert first_kwargs.get("dhl_ticket") == "T#1WA2604290000028"
        assert first_kwargs.get("target_awb") == "9999999999"


# ─────────────────────────────────────────────────────────────────────────────
# backfill_from_audit
# ─────────────────────────────────────────────────────────────────────────────

class TestBackfillFromAudit:
    """Tests for email_evidence_backfill.backfill_from_audit."""

    def _audit_with_dhl_email(self, awb: str = "9999999999") -> dict:
        return {
            "awb":            awb,
            "batch_id":       "BATCH_TEST",
            "dhl_ticket":     "T#1WA2604290000099",
            "dhl_email":      {
                "from":       "odprawacelna@dhl.com",
                "subject":    f"T#1WA2604290000099 - Agencja Celna DHL - przesyłka numer: {awb}",
                "received_at": "2026-04-29T02:46:18+00:00",
            },
        }

    def _audit_with_sent_agency_forward(self, awb: str = "9999999999") -> dict:
        return {
            "awb":      awb,
            "batch_id": "BATCH_TEST",
            "agency_reply_package": {
                "email_id":    "abc123",
                "queued_at":   "2026-04-29T18:00:00+00:00",
                "sent_at":     "2026-04-29T18:30:00+00:00",
                "status":      "sent",
                "send_verified": True,
                "to_list":     ["biuro@acspedycja.pl"],
                "subject":     f"Zgłoszenie celne – AWB {awb}",
                "attachments": [],
            },
            "timeline": [
                {"ts": "2026-04-29T18:30:00+00:00", "event": "agency_email_sent_verified"},
            ],
        }

    def _audit_with_queued_agency_forward(self, awb: str = "9999999999") -> dict:
        return {
            "awb":      awb,
            "batch_id": "BATCH_TEST",
            "agency_reply_package": {
                "email_id":  "abc456",
                "queued_at": "2026-04-29T18:00:00+00:00",
                # No sent_at, no send_verified → queued only
                "to_list":   ["biuro@acspedycja.pl"],
                "subject":   f"Zgłoszenie celne – AWB {awb}",
                "attachments": [],
            },
            "timeline": [],
        }

    def _run_backfill(self, tmp_path, awb, audit, existing_messages=None):
        """Run backfill_from_audit with patched store."""
        from app.services.email_evidence_backfill import backfill_from_audit

        stored: list = list(existing_messages or [])

        def fake_get_by_awb(a):
            return {"threads": [{"thread_id": "t", "messages": list(stored)}],
                    "summary": {}}

        def fake_save(a, msg, *, source="audit_backfill"):
            stored.append(dict(msg))
            return {"action": "inserted", "message_id": None}

        audit_path = tmp_path / "audit.json"
        audit_path.write_text(__import__("json").dumps(audit))

        with __import__("unittest.mock", fromlist=["patch"]).patch(
                "app.services.email_evidence_backfill._get_existing_messages",
                return_value=list(existing_messages or [])), \
             __import__("unittest.mock", fromlist=["patch"]).patch(
                "app.services.email_evidence_backfill._save",
                side_effect=lambda awb, msg: (stored.append(msg), "inserted")[1]), \
             __import__("unittest.mock", fromlist=["patch"]).patch(
                "app.services.email_evidence_backfill.link_batch",
                return_value=None) if False else __import__("contextlib").nullcontext():
            # Patch link_batch at the correct path
            from unittest.mock import patch as mpatch
            with mpatch("app.services.email_evidence_backfill._save",
                        side_effect=lambda awb, msg: (stored.append(msg), "inserted")[1]), \
                 mpatch("app.services.email_evidence_backfill._get_existing_messages",
                        return_value=list(existing_messages or [])):
                result = backfill_from_audit(awb, "BATCH_TEST", audit_path, audit)

        return result, stored

    def test_creates_dhl_request_from_audit(self, tmp_path):
        """Audit has dhl_email + ticket; evidence missing → backfill creates dhl_request."""
        awb   = "9999999999"
        audit = self._audit_with_dhl_email(awb)
        result, stored = self._run_backfill(tmp_path, awb, audit, existing_messages=[])

        added_events = [a["event_type"] for a in result["added"]]
        assert "dhl_request" in added_events, f"Expected dhl_request in {added_events}"
        assert result["total_added"] >= 1

        dhl_req = next((m for m in stored if m.get("event_type") == "dhl_request"), None)
        assert dhl_req is not None
        assert dhl_req["direction"] == "incoming"

    def test_marks_sent_when_audit_confirms_sent_at(self, tmp_path):
        """Audit has agency_reply_package.sent_at → evidence entry gets delivery_status=sent."""
        awb   = "9999999999"
        audit = self._audit_with_sent_agency_forward(awb)
        result, stored = self._run_backfill(tmp_path, awb, audit, existing_messages=[])

        agency_fwd = next((m for m in stored if m.get("event_type") == "agency_forward"), None)
        assert agency_fwd is not None, f"Expected agency_forward in stored: {stored}"
        assert agency_fwd["delivery_status"] == "sent", (
            f"Expected sent, got {agency_fwd.get('delivery_status')}")
        assert agency_fwd["sent_at"] is not None

    def test_marks_queued_when_no_sent_at(self, tmp_path):
        """Audit has agency_reply_package with queued_at only → delivery_status=queued."""
        awb   = "9999999999"
        audit = self._audit_with_queued_agency_forward(awb)
        result, stored = self._run_backfill(tmp_path, awb, audit, existing_messages=[])

        agency_fwd = next((m for m in stored if m.get("event_type") == "agency_forward"), None)
        assert agency_fwd is not None, f"Expected agency_forward in stored: {stored}"
        assert agency_fwd["delivery_status"] == "queued"
        assert agency_fwd.get("sent_at") is None

    def test_backfill_idempotent(self, tmp_path):
        """Running backfill twice does not create duplicate entries."""
        from unittest.mock import patch as mpatch
        from app.services.email_evidence_backfill import backfill_from_audit

        awb   = "9999999999"
        audit = self._audit_with_sent_agency_forward(awb)
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(__import__("json").dumps(audit))

        # Simulate an already-stored agency_forward entry (from first run)
        existing_agency_fwd = {
            "event_type":      "agency_forward",
            "direction":       "outgoing",
            "timestamp":       "2026-04-29T18:30:00+00:00",
            "delivery_status": "sent",
            "message_id":      None,
        }
        saved_calls = []

        with mpatch("app.services.email_evidence_backfill._save",
                    side_effect=lambda awb, msg: (saved_calls.append(msg), "inserted")[1]), \
             mpatch("app.services.email_evidence_backfill._get_existing_messages",
                    return_value=[existing_agency_fwd]):
            result = backfill_from_audit(awb, "BATCH_TEST", audit_path, audit)

        # agency_forward already present → should be skipped (not in added)
        added_events = [a["event_type"] for a in result["added"]]
        assert "agency_forward" not in added_events, (
            f"agency_forward should be skipped (already exists) but was in: {added_events}")
        # No save call for agency_forward
        saved_event_types = [m.get("event_type") for m in saved_calls]
        assert "agency_forward" not in saved_event_types


# ─────────────────────────────────────────────────────────────────────────────
# scan_and_ingest — new fields (broad_fallback_used, message_ids)
# ─────────────────────────────────────────────────────────────────────────────

class TestScanAndIngestNewFields:
    """Verify the new broad_fallback_used and message_ids fields in the response."""

    def _run_ingest(self, tmp_path, emails, scan_method="rest_api_search"):
        from app.services.email_evidence_ingestor import scan_and_ingest

        audit_data = {"batch_id": "BATCH_TEST", "awb": "9999999999"}
        ap = tmp_path / "audit.json"
        ap.write_text(__import__("json").dumps(audit_data))

        scan_result = {
            "emails":      emails,
            "scanned":     len(emails),
            "query_used":  "searchKey=9999999999",
            "scan_method": scan_method,
        }
        fake_scan = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(
            return_value=scan_result)

        from unittest.mock import patch as mpatch
        with mpatch("app.services.email_evidence_store.get_by_awb",
                    return_value={"threads": [], "summary": {}}), \
             mpatch("app.services.email_evidence_store.link_batch"), \
             mpatch("app.services.email_evidence_store.save_message",
                    return_value={"action": "inserted", "message_id": "msg001"}), \
             mpatch("app.services.email_evidence_store.update_scan_cursor"):
            result = scan_and_ingest(
                "9999999999", "BATCH_TEST", ap, audit_data,
                limit=50,
                token_provider=lambda: "tok",
                scan_fn=fake_scan,
            )
        return result

    def test_rescan_response_includes_message_ids(self, tmp_path):
        """scan_and_ingest returns a message_ids list."""
        emails = [
            {"message_id": "msg001", "subject": "DHL", "from": "odprawacelna@dhl.com",
             "received_at": "2026-04-29T02:00:00+00:00", "body_snippet": "9999999999"},
        ]
        result = self._run_ingest(tmp_path, emails)
        assert "message_ids" in result, f"message_ids missing from result: {list(result)}"
        assert isinstance(result["message_ids"], list)

    def test_rescan_response_includes_broad_fallback_used(self, tmp_path):
        """scan_and_ingest response always includes broad_fallback_used bool."""
        result = self._run_ingest(tmp_path, [])
        assert "broad_fallback_used" in result, f"broad_fallback_used missing: {list(result)}"
        assert isinstance(result["broad_fallback_used"], bool)

    def test_broad_fallback_used_false_for_direct_search(self, tmp_path):
        """Direct search (no fallback) returns broad_fallback_used=False."""
        emails = [
            {"message_id": "msg001", "subject": "DHL", "from": "odprawacelna@dhl.com",
             "received_at": "2026-04-29T02:00:00+00:00", "body_snippet": "9999999999"},
        ]
        result = self._run_ingest(tmp_path, emails, scan_method="rest_api_search")
        assert result["broad_fallback_used"] is False

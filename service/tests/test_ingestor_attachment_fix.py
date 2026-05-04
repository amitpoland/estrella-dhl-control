"""
test_ingestor_attachment_fix.py — Verify that attachment metadata from the
Zoho scanner is forwarded into classify_event_type and saved to the evidence
store, fixing Gap 1 (automated dhl_documents detection).

Coverage
--------
  1.  DHL email with "dsk.pdf" attachment → event_type = dhl_documents
  2.  DHL email with no attachments       → event_type = dhl_request (unchanged)
  3.  DHL email with "sad.pdf" attachment → event_type = dhl_documents
  4.  Agency email with "PZC.pdf"         → event_type = agency_sad_reply
  5.  Evidence store summary flips dhl_documents_received=True when doc email ingested
  6.  No-attachment path doesn't flip dhl_documents_received
  7.  Attachment key normalisation: scanner "type" key → evidence "document_type"
  8.  Attachments persisted on the stored message object
  9.  Re-scan (same message_id) is idempotent — evidence_type unchanged
 10.  Mixed batch: doc message + request message → only doc triggers received=True
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_audit(tmp_path: Path, awb: str = "9765416334") -> tuple[Path, dict]:
    d = tmp_path / "outputs" / "BATCH_TEST"
    d.mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": "BATCH_TEST", "awb": awb, "carrier": "DHL", "status": "blocked"}
    p = d / "audit.json"
    p.write_text(json.dumps(audit))
    return p, audit


def _email(mid: str, sender: str, attachments: list) -> dict:
    return {
        "message_id": mid,
        "from":       sender,
        "subject":    f"RE: AWB 9765416334",
        "body_text":  "Please find attached documentation.",
        "received_at": "2026-05-04T10:00:00+00:00",
        "to":         [],
        "cc":         [],
        "attachments": attachments,
    }


def _dhl_email(mid: str, attachments: list) -> dict:
    return _email(mid, "dhl.customs@dhl.com", attachments)


def _agency_email(mid: str, attachments: list) -> dict:
    return _email(mid, "info@acspedycja.pl", attachments)


def _run_ingest(tmp_path, emails, awb="9765416334"):
    """
    Run scan_and_ingest with a mock scan_fn and real evidence store ops
    against a temporary store.
    """
    from app.services.email_evidence_ingestor import scan_and_ingest
    import app.services.email_evidence_store as evs

    ap, audit = _fake_audit(tmp_path, awb=awb)

    scan_result = {
        "emails": emails,
        "scanned": len(emails),
        "query_used": "searchKey=9765416334",
        "scan_method": "rest_api_search",
    }
    fake_scan = MagicMock(return_value=scan_result)

    # Use real evidence store but redirected to tmp_path
    stored: dict[str, dict] = {}       # message_id → message dict
    thread_store: dict = {"threads": []}

    def fake_save(awb_key, msg, *, source="zoho_rest"):
        mid = msg.get("message_id")
        if mid and mid in stored:
            return {"action": "duplicate", "message_id": mid}
        stored[mid] = msg
        # Mirror into thread_store so get_by_awb returns them
        thread_store["threads"].append({"thread_id": msg.get("thread_id", "t"),
                                        "messages": [msg]})
        # Recompute summary after each insert
        from app.services.email_evidence_store import _summarise
        thread_store["summary"] = _summarise(thread_store["threads"])
        return {"action": "inserted", "message_id": mid}

    def fake_get_by_awb(_awb):
        return dict(thread_store)

    with patch("app.services.email_evidence_store.get_by_awb",
               side_effect=fake_get_by_awb), \
         patch("app.services.email_evidence_store.link_batch"), \
         patch("app.services.email_evidence_store.save_message",
               side_effect=fake_save), \
         patch("app.services.email_evidence_store.update_scan_cursor"):
        result = scan_and_ingest(
            awb, "BATCH_TEST", ap, audit,
            limit=50,
            token_provider=lambda: "tok",
            scan_fn=fake_scan,
        )

    return result, stored, thread_store


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_dhl_email_with_dsk_attachment_classified_as_dhl_documents(tmp_path):
    emails = [_dhl_email("msg001", [{"filename": "dsk.pdf", "type": "dsk"}])]
    result, stored, _ = _run_ingest(tmp_path, emails)
    assert result["ok"] is True
    assert result["ingested"] == 1
    msg = stored["msg001"]
    assert msg["event_type"] == "dhl_documents", (
        f"Expected dhl_documents, got {msg['event_type']}"
    )


def test_dhl_email_no_attachments_classified_as_dhl_request(tmp_path):
    emails = [_dhl_email("msg002", [])]
    result, stored, _ = _run_ingest(tmp_path, emails)
    assert result["ok"] is True
    msg = stored["msg002"]
    assert msg["event_type"] == "dhl_request"


def test_dhl_email_with_sad_attachment_classified_as_dhl_documents(tmp_path):
    emails = [_dhl_email("msg003", [{"filename": "SAD_document.pdf", "type": "sad"}])]
    _, stored, _ = _run_ingest(tmp_path, emails)
    assert stored["msg003"]["event_type"] == "dhl_documents"


def test_agency_email_with_pzc_classified_as_agency_sad_reply(tmp_path):
    emails = [_agency_email("msg004", [{"filename": "PZC_2026.pdf", "type": "pzc"}])]
    _, stored, _ = _run_ingest(tmp_path, emails)
    assert stored["msg004"]["event_type"] == "agency_sad_reply"


def test_evidence_summary_flips_when_doc_email_ingested(tmp_path):
    emails = [_dhl_email("msg005", [{"filename": "ZC429.pdf", "type": "dsk"}])]
    _, _, thread_store = _run_ingest(tmp_path, emails)
    summary = thread_store.get("summary", {})
    assert summary.get("dhl_documents_received") is True, (
        f"summary={summary}"
    )


def test_evidence_summary_not_flipped_for_request_only(tmp_path):
    emails = [_dhl_email("msg006", [])]
    _, _, thread_store = _run_ingest(tmp_path, emails)
    summary = thread_store.get("summary", {})
    assert summary.get("dhl_documents_received") is False


def test_attachment_key_normalised_scanner_type_to_document_type(tmp_path):
    """Scanner returns 'type'; stored message must have 'document_type'."""
    emails = [_dhl_email("msg007", [{"filename": "dsk_file.pdf", "type": "dsk"}])]
    _, stored, _ = _run_ingest(tmp_path, emails)
    attachments = stored["msg007"].get("attachments", [])
    assert attachments, "attachments list must not be empty"
    assert attachments[0].get("document_type") == "dsk", (
        f"Expected document_type=dsk, got {attachments[0]}"
    )
    assert attachments[0].get("filename") == "dsk_file.pdf"


def test_attachments_persisted_on_stored_message(tmp_path):
    emails = [_dhl_email("msg008", [
        {"filename": "ZC429.pdf",  "type": "dsk"},
        {"filename": "invoice.pdf","type": "invoice"},
    ])]
    _, stored, _ = _run_ingest(tmp_path, emails)
    attachments = stored["msg008"].get("attachments", [])
    assert len(attachments) == 2
    filenames = {a["filename"] for a in attachments}
    assert "ZC429.pdf" in filenames
    assert "invoice.pdf" in filenames


def test_idempotent_rescan_no_duplicate(tmp_path):
    emails = [_dhl_email("msg009", [{"filename": "dsk.pdf", "type": "dsk"}])]

    from app.services.email_evidence_ingestor import scan_and_ingest
    ap, audit = _fake_audit(tmp_path)

    call_count = {"n": 0}
    stored = {}

    def fake_save(awb_key, msg, *, source="zoho_rest"):
        mid = msg.get("message_id")
        if mid and mid in stored:
            return {"action": "duplicate", "message_id": mid}
        call_count["n"] += 1
        stored[mid] = msg
        return {"action": "inserted", "message_id": mid}

    existing_msgs: list = []

    def fake_get(awb):
        threads = [{"thread_id": "t1", "messages": list(existing_msgs)}]
        return {"threads": threads, "summary": {}}

    for _ in range(2):
        scan_result = {"emails": emails, "scanned": 1, "query_used": "q",
                       "scan_method": "rest"}
        fake_scan = MagicMock(return_value=scan_result)
        with patch("app.services.email_evidence_store.get_by_awb", side_effect=fake_get), \
             patch("app.services.email_evidence_store.link_batch"), \
             patch("app.services.email_evidence_store.save_message", side_effect=fake_save), \
             patch("app.services.email_evidence_store.update_scan_cursor"):
            scan_and_ingest("9765416334", "BATCH_TEST", ap, audit,
                            token_provider=lambda: "tok", scan_fn=fake_scan)
        # After first run, simulate the message is already in store
        if existing_msgs == []:
            existing_msgs.append({"message_id": "msg009"})

    assert call_count["n"] == 1, f"save_message called {call_count['n']} times, want 1"


def test_mixed_batch_only_doc_message_triggers_received(tmp_path):
    emails = [
        _dhl_email("msg010_req", []),                                          # request
        _dhl_email("msg010_doc", [{"filename": "DSK_customs.pdf", "type": "dsk"}]),  # documents
    ]
    _, stored, thread_store = _run_ingest(tmp_path, emails)
    assert stored["msg010_req"]["event_type"] == "dhl_request"
    assert stored["msg010_doc"]["event_type"] == "dhl_documents"
    assert thread_store["summary"].get("dhl_documents_received") is True

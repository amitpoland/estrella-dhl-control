"""
test_attachment_integrity.py — Regression tests for the attachment integrity
hotfix that prevents outbound customs emails from sending when required
attachments are missing or invalid.

Production incident covered:
    AWB 1196338404 — agency clearance email sent to biuro@acspedycja.pl,
    piotr@acspedycja.pl, ciagarlak@ganther.com.pl with subject
    "Zgłoszenie celne – AWB 1196338404" WITHOUT attachments.

Root cause:
    queue_email() triggers send_queued_email() synchronously before the caller
    writes audit["agency_reply_package"] to disk.  _attachments_for_queue()
    could not find the attachment list → returned ([], []) → both existing
    guards (attachments_missing, attachments_unresolved) saw 0 declared and
    0 found, so they let the send through.

Fixes verified by this suite:
    1. attachments= parameter added to queue_email() — stored in queue entry,
       bypasses the audit.json timing race.
    2. _attachments_for_queue() reads queue entry["attachments"] as priority 0.
    3. _validate_attachment_integrity() blocks on:
         a. Zero-byte attachment files
         b. Email type requiring ≥ 1 attachment (agency, dhl_reply, etc.)
         c. Body referencing attachments but list is empty
         d. MIME packaging failure
    4. Status set to FAILED_ATTACHMENT_VALIDATION (terminal — not 'pending').
    5. Timeline event written to audit.json on failure.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entry(
    email_type: str = "agency",
    body_text: str = "",
    body_html: str = "",
    attachments: list | None = None,
    batch_id: str = "",
) -> dict:
    """Minimal queue entry for testing."""
    return {
        "id":          str(uuid.uuid4()),
        "status":      "pending",
        "to":          "biuro@acspedycja.pl",
        "cc":          "",
        "subject":     "Zgłoszenie celne – AWB 1196338404",
        "body_text":   body_text,
        "body_html":   body_html,
        "from_address": "import@estrellajewels.eu",
        "email_type":  email_type,
        "batch_id":    batch_id,
        "attachments": attachments if attachments is not None else [],
    }


# ── 1. Zero-byte file is blocked ──────────────────────────────────────────────

def test_zero_byte_file_blocked(tmp_path):
    """
    A zero-size attachment file must be rejected with error_code='attachment_zero_bytes'.
    An empty PDF is never a valid customs document.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    zero_file = tmp_path / "polish_desc_AWB1196338404.pdf"
    zero_file.write_bytes(b"")  # 0 bytes

    entry = _make_entry(email_type="agency")
    ok, code, detail = _validate_attachment_integrity(entry, [zero_file])

    assert ok is False
    assert code == "attachment_zero_bytes"
    assert "0 bytes" in detail
    assert "Outbound customs email blocked" in detail


# ── 2. Body keyword + empty attachment list is blocked ───────────────────────

def test_body_keyword_no_attachments_blocked():
    """
    Body text containing 'w załączeniu' (Polish: 'attached') but zero resolved
    attachment files must be blocked.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    entry = _make_entry(
        email_type="",   # no special type — keyword check is type-agnostic
        body_text="Szanowni Państwo,\n\nW załączeniu przesyłamy opis celny.\n\nPozdrawienia",
    )
    ok, code, detail = _validate_attachment_integrity(entry, [])

    assert ok is False
    assert code == "body_references_missing_attachments"
    assert "attachment keyword" in detail.lower() or "keywords" in detail.lower() or "w załączeniu" in detail.lower() or "references" in detail.lower()
    assert "Outbound customs email blocked" in detail


def test_body_keyword_english_no_attachments_blocked():
    """'please find attached' in body with no files also triggers the guard."""
    from service.app.services.email_sender import _validate_attachment_integrity

    entry = _make_entry(email_type="", body_text="Dear DHL, please find attached the customs description.")
    ok, code, detail = _validate_attachment_integrity(entry, [])

    assert ok is False
    assert code == "body_references_missing_attachments"


# ── 3. Agency email type requires ≥ 1 attachment ─────────────────────────────

def test_agency_type_no_attachments_blocked():
    """
    email_type='agency' with zero resolved attachments must block even if the
    body text has no attachment keywords.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    entry = _make_entry(email_type="agency", body_text="Przesyłamy dokumenty.")
    ok, code, detail = _validate_attachment_integrity(entry, [])

    assert ok is False
    assert code == "attachment_required_for_type"
    assert "agency" in detail
    assert "Outbound customs email blocked" in detail


def test_dhl_reply_type_no_attachments_blocked():
    """email_type='dhl_reply' with zero attachments is also blocked."""
    from service.app.services.email_sender import _validate_attachment_integrity

    entry = _make_entry(email_type="dhl_reply", body_text="")
    ok, code, detail = _validate_attachment_integrity(entry, [])

    assert ok is False
    assert code == "attachment_required_for_type"
    assert "dhl_reply" in detail


# ── 4. Valid attachment passes ─────────────────────────────────────────────────

def test_valid_attachment_passes(tmp_path):
    """
    A non-zero PDF file, correct email_type, and a clean body passes all checks.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    pdf = tmp_path / "polish_desc_AWB1196338404.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake pdf content of sufficient length for testing")

    entry = _make_entry(email_type="agency", body_text="W załączeniu opis celny.")
    ok, code, detail = _validate_attachment_integrity(entry, [pdf])

    assert ok is True, f"Expected pass, got code={code!r} detail={detail!r}"
    assert code == ""
    assert detail == ""


def test_non_customs_email_without_attachments_passes():
    """
    An email with no email_type and no attachment keywords passes — it is a
    plain notification (e.g. account approval) and attachments are optional.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    entry = _make_entry(email_type="", body_text="Your account has been approved.")
    ok, code, detail = _validate_attachment_integrity(entry, [])

    assert ok is True, f"Expected pass for plain notification, got code={code!r}"


# ── 5. MIME packaging failure is blocked ─────────────────────────────────────

def test_mime_packaging_failure_blocked(tmp_path):
    """
    If _build_mime raises (e.g. IOError reading attachment), the guard must
    catch it and return error_code='mime_packaging_failed'.
    """
    from service.app.services.email_sender import _validate_attachment_integrity

    # Create a real file then mock _build_mime to raise
    pdf = tmp_path / "desc.pdf"
    pdf.write_bytes(b"%PDF-1.4 valid")

    entry = _make_entry(email_type="agency")

    with patch("service.app.services.email_sender._build_mime", side_effect=OSError("disk read error")):
        ok, code, detail = _validate_attachment_integrity(entry, [pdf])

    assert ok is False
    assert code == "mime_packaging_failed"
    assert "disk read error" in detail
    assert "Outbound customs email blocked" in detail


# ── 6. Terminal status FAILED_ATTACHMENT_VALIDATION is set ───────────────────

def test_terminal_status_set_on_failure(tmp_path):
    """
    When the attachment guard fires, queue entry status must be set to
    FAILED_ATTACHMENT_VALIDATION — not 'pending'. This prevents accidental
    retry before the root cause is fixed.
    """
    from service.app.services.email_sender import (
        _set_terminal_failure,
        _STATUS_ATTACHMENT_VALIDATION_FAILED,
    )

    queue_id = str(uuid.uuid4())
    queue_file = tmp_path / "email_queue.json"
    queue_file.write_text(json.dumps([{
        "id": queue_id,
        "status": "pending",
        "to": "agency@test.com",
        "subject": "Test",
    }]), encoding="utf-8")

    with patch("service.app.services.email_sender.settings") as mock_settings:
        mock_settings.storage_root = tmp_path

        # Patch _load_queue and _save_queue to use our temp file
        def _load():
            return json.loads(queue_file.read_text(encoding="utf-8"))

        def _save(q):
            queue_file.write_text(json.dumps(q), encoding="utf-8")

        with patch("service.app.services.email_sender._load_queue", side_effect=_load), \
             patch("service.app.services.email_sender._save_queue", side_effect=_save):

            _set_terminal_failure(queue_id, "attachment_zero_bytes", "Test detail")

    updated = json.loads(queue_file.read_text(encoding="utf-8"))
    entry = next(e for e in updated if e["id"] == queue_id)

    assert entry["status"] == _STATUS_ATTACHMENT_VALIDATION_FAILED, (
        f"Expected {_STATUS_ATTACHMENT_VALIDATION_FAILED!r}, got {entry['status']!r}"
    )
    assert entry["error"] == "attachment_zero_bytes"
    assert entry.get("attachment_guard_fired") is True


# ── 7. Audit timeline event is logged on failure ─────────────────────────────

def test_audit_timeline_event_logged_on_failure(tmp_path):
    """
    _log_attachment_failure_to_audit must write an 'attachment_validation_failed'
    event to the batch audit.json timeline when the guard fires.
    """
    from service.app.services.email_sender import _log_attachment_failure_to_audit

    # Set up a minimal audit.json
    batch_id = "BATCH_TEST_001"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(json.dumps({"batch_id": batch_id, "timeline": []}), encoding="utf-8")

    entry = _make_entry(email_type="agency", batch_id=batch_id)

    # Capture what tl.log_event is called with
    logged_events = []

    def fake_log_event(path, event, trigger_source="", actor="", detail=None):
        logged_events.append({
            "path":   str(path),
            "event":  event,
            "detail": detail or {},
        })

    with patch("service.app.services.email_sender.settings") as mock_settings, \
         patch("service.app.services.email_sender.tl") as mock_tl:

        mock_settings.storage_root = tmp_path
        mock_tl.log_event.side_effect = fake_log_event

        _log_attachment_failure_to_audit(
            queue_id   = entry["id"],
            entry      = entry,
            error_code  = "attachment_required_for_type",
            error_detail= "Outbound customs email blocked: required attachments missing.",
        )

    assert len(logged_events) == 1, (
        f"Expected 1 timeline event, got {len(logged_events)}: {logged_events}"
    )
    ev = logged_events[0]
    assert ev["event"] == "attachment_validation_failed"
    assert ev["detail"]["error_code"] == "attachment_required_for_type"
    assert ev["detail"]["email_type"] == "agency"


# ── 8. Queue entry attachments bypass audit.json timing race ─────────────────

def test_queue_entry_attachments_bypass_audit_timing_race(tmp_path):
    """
    When queue_entry["attachments"] is populated (the post-fix path),
    _attachments_for_queue must return paths from there WITHOUT reading
    audit.json — preventing the timing race where audit isn't written yet.
    """
    from service.app.services.email_sender import _attachments_for_queue

    pdf = tmp_path / "desc.pdf"
    pdf.write_bytes(b"%PDF-1.4 real content")

    # Queue entry has attachments directly; batch_id points to non-existent audit
    entry = _make_entry(
        batch_id="BATCH_NO_AUDIT_YET",
        attachments=[{"label": "Polish Description", "path": str(pdf)}],
    )

    with patch("service.app.services.email_sender.settings") as mock_settings:
        mock_settings.storage_root = tmp_path  # no audit.json exists here

        found, missing = _attachments_for_queue(entry)

    assert found == [pdf], f"Expected [{pdf}], got {found}"
    assert missing == []


def test_empty_queue_attachments_is_authoritative(tmp_path):
    """
    When queue_entry["attachments"] == [] (explicitly empty), the resolver
    returns ([], []) WITHOUT falling back to audit.json — so the type/keyword
    guards can fire correctly on the immediate SMTP attempt.
    """
    from service.app.services.email_sender import _attachments_for_queue

    # Set up an audit with a populated agency_reply_package — but the queue
    # entry itself says attachments=[] (empty list), which is authoritative.
    batch_id  = "BATCH_RACE_TEST"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    fake_pdf  = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 content")
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(json.dumps({
        "agency_reply_package": {
            "email_id":   "some-other-id",
            "attachments": [{"label": "Fake", "path": str(fake_pdf)}],
        },
    }), encoding="utf-8")

    entry = {
        "id":          "some-other-id",
        "batch_id":    batch_id,
        "email_type":  "agency",
        "attachments": [],   # explicitly empty — declared by caller
    }

    with patch("service.app.services.email_sender.settings") as mock_settings:
        mock_settings.storage_root = tmp_path

        found, missing = _attachments_for_queue(entry)

    # Should return empty (from queue entry) — NOT the audit fallback
    assert found == []
    assert missing == []

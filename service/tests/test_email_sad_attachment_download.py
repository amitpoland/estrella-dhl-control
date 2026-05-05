"""
test_email_sad_attachment_download.py — SAD attachment download to disk during ingestion.

Tests:
  1. test_valid_sad_attachment_downloaded        — file lands in source/sad/
  2. test_file_exists_on_disk_after_download     — dest file has expected content
  3. test_path_stored_in_audit                   — audit.agency_documents_received_state updated
  4. test_duplicate_email_does_not_redownload    — idempotent: same file skipped on second call
  5. test_non_sad_attachment_not_downloaded      — invoice/other types skipped
  6. test_no_attachment_id_skips_download        — missing attachmentId is non-fatal
  7. test_download_failure_is_non_fatal          — HTTP failure leaves audit unchanged

already_stored catch-up path (via scan_and_ingest):
  8. test_already_stored_triggers_sad_download   — missing file downloaded on rescan
  9. test_already_stored_no_duplicate_download   — file on disk skips download
 10. test_already_stored_no_overwrite            — existing file bytes unchanged
 11. test_already_stored_audit_updated           — audit.agency_documents_received_state populated
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.email_evidence_ingestor import (
    _is_valid_agency_sad_attachment,
    _safe_sad_name,
    _ingest_sad_attachments,
    _write_agency_receipt_to_audit,
)

TOKEN      = "test_token"
ACCOUNT_ID = "acct123"
MSG_ID     = "msg_abc"
API_BASE   = "https://mail.zoho.eu/api"

SAD_ATT = {"filename": "ZC429_TEST.pdf", "document_type": "sad"}
INV_ATT = {"filename": "invoice_EJL.pdf", "document_type": "invoice"}


def _write_audit(audit_path: Path, data: dict) -> None:
    audit_path.write_text(json.dumps(data), encoding="utf-8")


def _read_audit(audit_path: Path) -> dict:
    return json.loads(audit_path.read_text(encoding="utf-8"))


# ── 1. Valid SAD attachment lands in source/sad/ ──────────────────────────────

def test_valid_sad_attachment_downloaded(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "ZC429_TEST.pdf", "attachmentId": "att1"}],
    )

    def _fake_download(token, account_id, message_id, att_id, dest, api_base):
        dest.write_bytes(b"%PDF-1.4 ZC429 stub content")
        return True

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        _fake_download,
    )

    paths = _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    assert len(paths) == 1
    dest = tmp_path / "source" / "sad" / "ZC429_TEST.pdf"
    assert dest.exists(), "File must be written to source/sad/"


# ── 2. File has expected content on disk ──────────────────────────────────────

def test_file_exists_on_disk_after_download(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "ZC429_TEST.pdf", "attachmentId": "att1"}],
    )

    expected_bytes = b"%PDF-1.4 real content"

    def _fake_download(token, account_id, message_id, att_id, dest, api_base):
        dest.write_bytes(expected_bytes)
        return True

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        _fake_download,
    )

    _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    dest = tmp_path / "source" / "sad" / "ZC429_TEST.pdf"
    assert dest.read_bytes() == expected_bytes


# ── 3. Absolute path stored in audit ─────────────────────────────────────────

def test_path_stored_in_audit(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "ZC429_TEST.pdf", "attachmentId": "att1"}],
    )

    def _fake_download(token, account_id, message_id, att_id, dest, api_base):
        dest.write_bytes(b"content")
        return True

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        _fake_download,
    )

    _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    audit = _read_audit(audit_path)
    state = audit.get("agency_documents_received_state") or {}
    assert state.get("received") is True
    assert state.get("source") == "email_ingestor"

    files = state.get("files") or []
    assert len(files) == 1
    entry = files[0]
    assert entry["name"] == "ZC429_TEST.pdf"

    expected_path = str((tmp_path / "source" / "sad" / "ZC429_TEST.pdf").resolve())
    assert entry["path"] == expected_path, f"Expected {expected_path!r}, got {entry['path']!r}"

    recv = audit.get("agency_documents_received") or {}
    assert recv.get("received") is True
    assert recv.get("files_count") == 1


# ── 4. Duplicate call does not re-download ────────────────────────────────────

def test_duplicate_email_does_not_redownload(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "ZC429_TEST.pdf", "attachmentId": "att1"}],
    )

    call_count = []

    def _fake_download(token, account_id, message_id, att_id, dest, api_base):
        call_count.append(1)
        dest.write_bytes(b"content")
        return True

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        _fake_download,
    )

    # First call — downloads
    _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )
    # Second call — must skip (file already on disk)
    _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    assert len(call_count) == 1, "Download must only happen once"

    audit = _read_audit(audit_path)
    files = (audit.get("agency_documents_received_state") or {}).get("files") or []
    assert len(files) == 1, "Audit must not contain duplicate file entries"


# ── 5. Non-SAD attachments are not downloaded ─────────────────────────────────

def test_non_sad_attachment_not_downloaded(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    downloaded = []

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "invoice.pdf", "attachmentId": "att2"}],
    )

    def _fake_download(token, account_id, message_id, att_id, dest, api_base):
        downloaded.append(att_id)
        dest.write_bytes(b"x")
        return True

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        _fake_download,
    )

    paths = _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [INV_ATT], audit_path, "B1", API_BASE,
    )

    assert paths == [], "Invoice attachment must not be downloaded"
    assert downloaded == [], "_download_one_attachment must not be called for non-SAD types"


# ── 6. Missing attachmentId is non-fatal ──────────────────────────────────────

def test_no_attachment_id_skips_download(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    # Zoho returns empty list — no IDs available
    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [],
    )

    paths = _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    assert paths == [], "Must return empty list when no attachment IDs available"
    audit = _read_audit(audit_path)
    assert "agency_documents_received_state" not in audit, "Audit must not be modified"


# ── 7. HTTP download failure is non-fatal ─────────────────────────────────────

def test_download_failure_is_non_fatal(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "B1"})

    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._fetch_message_attachment_ids",
        lambda *_a, **_k: [{"attachmentName": "ZC429_TEST.pdf", "attachmentId": "att1"}],
    )
    monkeypatch.setattr(
        "app.services.email_evidence_ingestor._download_one_attachment",
        lambda *_a, **_k: False,  # simulate HTTP failure
    )

    paths = _ingest_sad_attachments(
        TOKEN, ACCOUNT_ID, MSG_ID, [SAD_ATT], audit_path, "B1", API_BASE,
    )

    assert paths == [], "Failed download must not appear in results"
    audit = _read_audit(audit_path)
    assert "agency_documents_received_state" not in audit, "Audit must not be modified on failure"


# ── is_valid helpers ──────────────────────────────────────────────────────────

def test_is_valid_by_document_type():
    assert _is_valid_agency_sad_attachment({"document_type": "customs_pdf"})
    assert _is_valid_agency_sad_attachment({"document_type": "customs_xml"})
    assert _is_valid_agency_sad_attachment({"document_type": "sad"})
    assert not _is_valid_agency_sad_attachment({"document_type": "invoice"})
    assert not _is_valid_agency_sad_attachment({"document_type": "other"})


def test_is_valid_by_filename_keyword():
    assert _is_valid_agency_sad_attachment({"filename": "ZC429_shipment.pdf", "document_type": "other"})
    assert _is_valid_agency_sad_attachment({"filename": "PZC_document.pdf", "document_type": "other"})
    assert not _is_valid_agency_sad_attachment({"filename": "invoice.pdf", "document_type": "other"})


def test_safe_sad_name_strips_unsafe_chars():
    assert _safe_sad_name("ZC 429 test.pdf") == "ZC_429_test.pdf"
    assert _safe_sad_name("") == "attachment.bin"
    assert _safe_sad_name("normal.pdf") == "normal.pdf"


# ── already_stored catch-up path (tests 8–11) ────────────────────────────────
#
# These tests exercise the new branch in scan_and_ingest that runs
# _ingest_sad_attachments even when save_message returns "already_stored".
# They use scan_fn injection and patch save_message to return that action.

def _make_scan_ingest_env(tmp_path, monkeypatch):
    """
    Return (audit_path, run_scan) where run_scan(download_fn) calls
    scan_and_ingest with one already_stored email carrying a SAD attachment,
    using the supplied fake download function.
    """
    from unittest.mock import MagicMock, patch

    from app.services.email_evidence_ingestor import scan_and_ingest

    # AWB must be all-digits — scan_and_ingest strips non-digits and returns
    # no_awb if the result is empty.
    _AWB = "9999000001"
    _BATCH = "BATCH_AS_001"

    # audit.json must live at outputs/<batch_id>/audit.json so that
    # _ingest_sad_attachments can locate source/sad/ relative to audit_path.parent.
    batch_dir  = tmp_path / "outputs" / _BATCH
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(
        json.dumps({"batch_id": _BATCH, "awb": _AWB}), encoding="utf-8"
    )

    sad_email = {
        "message_id":  "msg_already_001",
        "subject":     "ZC429 customs doc",
        "from":        "agency@acspedycja.pl",
        "to":          [],
        "cc":          [],
        "received_at": "2026-05-01T10:00:00Z",
        "body_snippet": f"AWB {_AWB} customs",
        "body_text":    f"AWB {_AWB}",
        "attachments": [{"filename": "ZC429_TEST_AS.pdf", "document_type": "sad"}],
    }

    scan_result = {
        "emails":      [sad_email],
        "scanned":     1,
        "query_used":  f"searchKey={_AWB}",
        "scan_method": "rest_api_search",
    }
    fake_scan = MagicMock(return_value=scan_result)

    # Build a minimal settings stand-in so account_id is non-empty.
    # scan_and_ingest does `from ..core.config import settings` at call time,
    # so patching the module-level name is the correct interception point.
    mock_settings = MagicMock()
    mock_settings.zoho_mail_account_id = "test_acct_123"
    mock_settings.zoho_mail_api_base   = "https://mail.zoho.eu/api"
    mock_settings.email_evidence_v2    = True

    def run_scan(download_fn):
        with patch("app.core.config.settings", mock_settings), \
             patch("app.services.email_evidence_store.get_by_awb",
                   return_value={"threads": [], "summary": {}}), \
             patch("app.services.email_evidence_store.link_batch"), \
             patch("app.services.email_evidence_store.save_message",
                   return_value={"action": "already_stored", "message_id": "msg_already_001"}), \
             patch("app.services.email_evidence_store.update_scan_cursor"), \
             patch("app.services.email_evidence_ingestor._fetch_message_attachment_ids",
                   return_value=[{"attachmentName": "ZC429_TEST_AS.pdf", "attachmentId": "att_as1"}]), \
             patch("app.services.email_evidence_ingestor._download_one_attachment",
                   side_effect=download_fn):
            return scan_and_ingest(
                _AWB, _BATCH, audit_path, json.loads(audit_path.read_text()),
                limit=10,
                token_provider=lambda: "tok_test",
                scan_fn=fake_scan,
            )

    return audit_path, run_scan


def test_already_stored_triggers_sad_download(tmp_path, monkeypatch):
    """already_stored email with SAD attachment → file must be downloaded."""
    audit_path, run_scan = _make_scan_ingest_env(tmp_path, monkeypatch)

    call_log = []

    def _fake_dl(token, account_id, message_id, att_id, dest, api_base):
        call_log.append(att_id)
        dest.write_bytes(b"%PDF-1.4 already_stored_test")
        return True

    run_scan(_fake_dl)

    assert call_log == ["att_as1"], "download must fire once for the already_stored SAD attachment"
    dest = audit_path.parent / "source" / "sad" / "ZC429_TEST_AS.pdf"
    assert dest.exists(), "file must be written to source/sad/"


def test_already_stored_no_duplicate_download(tmp_path, monkeypatch):
    """already_stored + file already on disk → download must NOT fire."""
    audit_path, run_scan = _make_scan_ingest_env(tmp_path, monkeypatch)

    # Pre-create the file so the idempotency check triggers
    sad_dir = audit_path.parent / "source" / "sad"
    sad_dir.mkdir(parents=True, exist_ok=True)
    (sad_dir / "ZC429_TEST_AS.pdf").write_bytes(b"%PDF-1.4 already_exists")

    call_log = []

    def _fake_dl(token, account_id, message_id, att_id, dest, api_base):
        call_log.append(att_id)
        dest.write_bytes(b"OVERWRITE")
        return True

    run_scan(_fake_dl)

    assert call_log == [], "_download_one_attachment must not be called when file exists"


def test_already_stored_no_overwrite(tmp_path, monkeypatch):
    """already_stored + file already on disk → original bytes must be preserved."""
    audit_path, run_scan = _make_scan_ingest_env(tmp_path, monkeypatch)

    sad_dir = audit_path.parent / "source" / "sad"
    sad_dir.mkdir(parents=True, exist_ok=True)
    original_bytes = b"%PDF-1.4 original_content_must_survive"
    (sad_dir / "ZC429_TEST_AS.pdf").write_bytes(original_bytes)

    run_scan(lambda *a, **k: True)

    assert (sad_dir / "ZC429_TEST_AS.pdf").read_bytes() == original_bytes, (
        "file bytes must be unchanged when file already exists on disk"
    )


def test_already_stored_audit_updated(tmp_path, monkeypatch):
    """already_stored download → audit.agency_documents_received_state must be written."""
    audit_path, run_scan = _make_scan_ingest_env(tmp_path, monkeypatch)

    def _fake_dl(token, account_id, message_id, att_id, dest, api_base):
        dest.write_bytes(b"%PDF-1.4 content")
        return True

    run_scan(_fake_dl)

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    state = audit.get("agency_documents_received_state") or {}
    assert state.get("received") is True, "received must be True after catch-up download"
    assert state.get("source") == "email_ingestor"
    files = state.get("files") or []
    assert len(files) == 1
    assert files[0]["name"] == "ZC429_TEST_AS.pdf"

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

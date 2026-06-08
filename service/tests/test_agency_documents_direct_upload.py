"""
test_agency_documents_direct_upload.py — Direct-upload path marks agency receipt.

Tests:
  1. test_direct_sad_upload_writes_agency_documents_received
     — _mark_agency_documents_received writes a dict with received=True
  2. test_direct_sad_upload_writes_received_state_with_path
     — agency_documents_received_state.files[0] contains the absolute path
  3. test_email_ingestor_receipt_not_overwritten
     — existing email_ingestor source blocks any overwrite
  4. test_operator_receipt_not_overwritten
     — existing operator source blocks any overwrite
  5. test_duplicate_call_does_not_duplicate_file_entry
     — idempotent: calling twice with same path produces one file entry
  6. test_xml_sad_classified_as_customs_xml
     — .xml extension → type == "customs_xml"
  7. test_parser_guard_passes_after_direct_upload
     — written audit satisfies parser G4a condition:
       (audit.get("agency_documents_received") or {}).get("received") is True
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.api.routes_upload import _mark_agency_documents_received, _save


def _write_audit(audit_path: Path, data: dict) -> None:
    audit_path.write_text(json.dumps(data), encoding="utf-8")


def _read_audit(audit_path: Path) -> dict:
    return json.loads(audit_path.read_text(encoding="utf-8"))


# ── 1. Receipt dict written correctly ────────────────────────────────────────

def test_direct_sad_upload_writes_agency_documents_received(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "TEST", "status": "draft"})

    sad_path = tmp_path / "ZC429_TEST.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    recv = audit["agency_documents_received"]

    assert isinstance(recv, dict), "agency_documents_received must be a dict"
    assert recv["received"] is True
    assert recv["source"] == "direct_upload"
    assert sad_path.name in recv["files"]
    assert recv["files_count"] == 1
    assert recv["received_at"]


# ── 2. State dict contains absolute path ─────────────────────────────────────

def test_direct_sad_upload_writes_received_state_with_path(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "TEST", "status": "draft"})

    sad_path = tmp_path / "ZC429_TEST.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    state = audit["agency_documents_received_state"]

    assert state["received"] is True
    assert state["source"] == "direct_upload"
    assert len(state["files"]) == 1

    entry = state["files"][0]
    assert entry["name"] == sad_path.name
    assert entry["path"] == str(sad_path.resolve())
    assert entry["type"] == "customs_pdf"


# ── 3. Email-ingestor source not overwritten ──────────────────────────────────

def test_email_ingestor_receipt_not_overwritten(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {
        "batch_id": "TEST",
        "agency_documents_received": {
            "received": True,
            "source": "email_ingestor",
            "files": ["from_email.pdf"],
            "files_count": 1,
            "received_at": "2026-01-01T00:00:00+00:00",
        },
        "agency_documents_received_state": {
            "received": True,
            "source": "email_ingestor",
            "files": [{"name": "from_email.pdf", "path": "/some/path.pdf", "type": "customs_pdf"}],
            "received_at": "2026-01-01T00:00:00+00:00",
        },
    })

    sad_path = tmp_path / "ZC429_DIRECT.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    assert audit["agency_documents_received"]["source"] == "email_ingestor"
    assert "from_email.pdf" in audit["agency_documents_received"]["files"]
    assert sad_path.name not in audit["agency_documents_received"]["files"]


# ── 4. Operator source not overwritten ───────────────────────────────────────

def test_operator_receipt_not_overwritten(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {
        "batch_id": "TEST",
        "agency_documents_received_state": {
            "received": True,
            "source": "operator",
            "files": [{"name": "op.pdf", "path": "/op/op.pdf", "type": "customs_pdf"}],
            "received_at": "2026-02-01T00:00:00+00:00",
        },
    })

    sad_path = tmp_path / "ZC429_DIRECT.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    state = audit.get("agency_documents_received_state", {})
    assert state.get("source") == "operator", "operator source must not be overwritten"
    assert sad_path.name not in [f.get("name") for f in state.get("files", [])]


# ── 5. Idempotent — no duplicate file entries ─────────────────────────────────

def test_duplicate_call_does_not_duplicate_file_entry(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "TEST", "status": "draft"})

    sad_path = tmp_path / "ZC429_TEST.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)
    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    state = audit["agency_documents_received_state"]
    assert len(state["files"]) == 1, "Duplicate call must not add a second file entry"
    assert audit["agency_documents_received"]["files_count"] == 1


# ── 6. XML SAD classified as customs_xml ─────────────────────────────────────

def test_xml_sad_classified_as_customs_xml(tmp_path):
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "TEST", "status": "draft"})

    sad_path = tmp_path / "ZC429_TEST.xml"
    sad_path.write_bytes(b"<root/>")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)
    state = audit["agency_documents_received_state"]
    assert state["files"][0]["type"] == "customs_xml"


# ── 7. Parser G4a condition is satisfied ─────────────────────────────────────

def test_parser_guard_passes_after_direct_upload(tmp_path):
    """
    Parser G4a (agency_sad_parser.py:47-50):
      docs = audit.get("agency_documents_received") or {}
      if not docs.get("received"):
          return {"skipped": True}
    Written audit must satisfy this: dict, received=True.
    """
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, {"batch_id": "TEST", "status": "draft"})

    sad_path = tmp_path / "ZC429_TEST.pdf"
    sad_path.write_bytes(b"%PDF-1.4")

    _mark_agency_documents_received(audit_path, "TEST", sad_path.name, sad_path)

    audit = _read_audit(audit_path)

    # Replicate parser G4a guard exactly
    docs = audit.get("agency_documents_received") or {}
    assert isinstance(docs, dict), "Parser expects dict, not bool — .get() would fail on True"
    assert docs.get("received") is True, "Parser G4a guard must pass"


# ── 8. H-R2 (PR #488): PDF magic-byte validation in _save ────────────────────
# A `.pdf` destination must reject content that does not begin with `%PDF`.
# Scoped strictly to the PR #488 magic-byte fix — no broadening of upload
# behaviour.

class _FakeUpload:
    """Minimal UploadFile stand-in. `_save` only uses `.filename` and
    `await .read()`, so a tiny async shim is sufficient (no Starlette
    SpooledTemporaryFile needed)."""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def test_pdf_upload_rejects_non_pdf_magic_bytes(tmp_path):
    """A .pdf upload whose bytes do not start with %PDF is rejected (400)
    and is NOT written to disk."""
    dest = tmp_path / "fake.pdf"
    upload = _FakeUpload("fake.pdf", b"NOT-A-PDF-payload-bytes-1234")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_save(upload, dest))
    assert exc.value.status_code == 400
    assert "valid PDF" in str(exc.value.detail)
    assert not dest.exists(), "rejected upload must not be written to disk"


def test_pdf_upload_accepts_valid_pdf_magic_bytes(tmp_path):
    """A .pdf upload that begins with %PDF passes the magic-byte check and is
    written (confirms the H-R2 guard does not false-reject real PDFs)."""
    dest = tmp_path / "real.pdf"
    upload = _FakeUpload("real.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n")
    asyncio.run(_save(upload, dest))
    assert dest.exists()
    assert dest.read_bytes().startswith(b"%PDF")

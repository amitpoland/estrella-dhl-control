"""
test_agency_sad_parser.py — Agency SAD parser agent coverage.

Tests:
  1. test_parse_skipped_if_no_docs          — guard: no agency_documents_received
  2. test_parse_skipped_if_already_parsed   — idempotency: status=="parsed" skips
  3. test_parse_awaiting_file               — docs received but no on-disk path
  4. test_parse_awaiting_file_path_missing  — path in state but file absent on disk
  5. test_parse_success_minimal             — PDF present, mrn returned → status parsed
  6. test_parse_does_not_write_customs_declaration — G1: customs_declaration untouched
  7. test_parse_partial_when_no_mrn         — orchestrator returns no mrn → partial
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.agency_sad_parser import parse_agency_sad


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_audit(batch_dir: Path, data: dict) -> Path:
    ap = batch_dir / "audit.json"
    batch_dir.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(data), encoding="utf-8")
    return ap


def _read_audit(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "audit.json").read_text(encoding="utf-8"))


def _make_pdf(tmp_path: Path, name: str = "SAD_test.pdf") -> Path:
    p = tmp_path / "source" / "sad" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 fake")
    return p


# ── Test 1: no docs received → skip ─────────────────────────────────────────

def test_parse_skipped_if_no_docs(tmp_path):
    batch_dir = tmp_path / "outputs" / "B1"
    audit = {"batch_id": "B1", "awb": "111"}
    ap = _write_audit(batch_dir, audit)

    result = parse_agency_sad("B1", ap, audit)

    assert result == {"skipped": True}
    assert _read_audit(batch_dir).get("agency_sad_parse") is None


# ── Test 2: idempotency — already parsed → skip ──────────────────────────────

def test_parse_skipped_if_already_parsed(tmp_path):
    batch_dir = tmp_path / "outputs" / "B2"
    existing_parse = {"status": "parsed", "mrn": "26PL001", "parse_version": 1}
    audit = {
        "batch_id": "B2",
        "agency_documents_received": {"received": True},
        "agency_sad_parse": existing_parse,
    }
    ap = _write_audit(batch_dir, audit)

    result = parse_agency_sad("B2", ap, audit)

    assert result == {"skipped": True}
    # Must not overwrite the existing parse record
    assert _read_audit(batch_dir)["agency_sad_parse"] == existing_parse


# ── Test 3: docs received but no state files → awaiting_file ─────────────────

def test_parse_awaiting_file_no_state(tmp_path):
    batch_dir = tmp_path / "outputs" / "B3"
    audit = {
        "batch_id": "B3",
        "agency_documents_received": {
            "received": True,
            "files": ["SAD_test.pdf"],   # filename-only, from ingestor
            "source": "email_ingestor",
        },
        # agency_documents_received_state absent → no paths
    }
    ap = _write_audit(batch_dir, audit)

    result = parse_agency_sad("B3", ap, audit)

    assert result == {"awaiting_file": True}
    written = _read_audit(batch_dir)["agency_sad_parse"]
    assert written["status"] == "awaiting_file"
    assert written["reason"] == "file_bytes_not_on_disk"


# ── Test 4: state has path but file missing on disk → awaiting_file ──────────

def test_parse_awaiting_file_path_missing_on_disk(tmp_path):
    batch_dir = tmp_path / "outputs" / "B4"
    ghost_path = str(tmp_path / "source" / "sad" / "SAD_ghost.pdf")  # does not exist
    audit = {
        "batch_id": "B4",
        "agency_documents_received": {"received": True},
        "agency_documents_received_state": {
            "files": [{"name": "SAD_ghost.pdf", "path": ghost_path, "type": "customs_pdf"}]
        },
    }
    ap = _write_audit(batch_dir, audit)

    result = parse_agency_sad("B4", ap, audit)

    assert result == {"awaiting_file": True}
    assert _read_audit(batch_dir)["agency_sad_parse"]["status"] == "awaiting_file"


# ── Test 5: success — orchestrator returns mrn ───────────────────────────────

def test_parse_success_minimal(tmp_path):
    batch_dir = tmp_path / "outputs" / "B5"
    pdf = _make_pdf(tmp_path)

    audit = {
        "batch_id": "B5",
        "awb": "999",
        "agency_documents_received": {"received": True},
        "agency_documents_received_state": {
            "files": [{"name": pdf.name, "path": str(pdf), "type": "customs_pdf"}]
        },
    }
    ap = _write_audit(batch_dir, audit)

    mock_result = {
        "mapped": {"mrn": "26PL001TEST", "duty_a00_pln": 500.0},
        "source": "pdf",
        "confidence": "high",
        "corrections": [],
        "ai_supplemented_fields": [],
    }

    with patch(
        "app.services.customs_parser_orchestrator.parse_customs_document",
        return_value=mock_result,
    ):
        result = parse_agency_sad("B5", ap, audit)

    assert result == {"parsed": True}
    written = _read_audit(batch_dir)["agency_sad_parse"]
    assert written["status"] == "parsed"
    assert written["mrn"] == "26PL001TEST"
    assert written["source"] == "pdf"
    assert written["confidence"] == "high"
    assert written["parse_version"] == 1
    assert str(pdf) in written["files_parsed"]


# ── Test 6: G1 — customs_declaration must not be written ─────────────────────

def test_parse_does_not_write_customs_declaration(tmp_path):
    batch_dir = tmp_path / "outputs" / "B6"
    pdf = _make_pdf(tmp_path, "ZC429_26PL.pdf")

    original_cd = {"mrn": "ORIGINAL_MRN", "duty_a00_pln": 9999.0}
    audit = {
        "batch_id": "B6",
        "customs_declaration": original_cd,
        "agency_documents_received": {"received": True},
        "agency_documents_received_state": {
            "files": [{"name": pdf.name, "path": str(pdf), "type": "customs_pdf"}]
        },
    }
    ap = _write_audit(batch_dir, audit)

    mock_result = {
        "mapped": {"mrn": "NEW_MRN_FROM_AGENCY", "duty_a00_pln": 1234.0},
        "source": "pdf",
        "confidence": "high",
        "corrections": [],
        "ai_supplemented_fields": [],
    }

    with patch(
        "app.services.customs_parser_orchestrator.parse_customs_document",
        return_value=mock_result,
    ):
        parse_agency_sad("B6", ap, audit)

    final = _read_audit(batch_dir)
    # customs_declaration must be unchanged
    assert final["customs_declaration"] == original_cd
    # mrn lives only in agency_sad_parse
    assert final["agency_sad_parse"]["mrn"] == "NEW_MRN_FROM_AGENCY"


# ── Test 7: partial when no mrn returned ─────────────────────────────────────

def test_parse_partial_when_no_mrn(tmp_path):
    batch_dir = tmp_path / "outputs" / "B7"
    pdf = _make_pdf(tmp_path)

    audit = {
        "batch_id": "B7",
        "agency_documents_received": {"received": True},
        "agency_documents_received_state": {
            "files": [{"name": pdf.name, "path": str(pdf), "type": "customs_pdf"}]
        },
    }
    ap = _write_audit(batch_dir, audit)

    mock_result = {
        "mapped": {},          # no mrn
        "source": "pdf",
        "confidence": "medium",
        "corrections": ["MRN not found in document"],
        "ai_supplemented_fields": [],
    }

    with patch(
        "app.services.customs_parser_orchestrator.parse_customs_document",
        return_value=mock_result,
    ):
        result = parse_agency_sad("B7", ap, audit)

    assert result == {"parsed": True}
    written = _read_audit(batch_dir)["agency_sad_parse"]
    assert written["status"] == "partial"
    assert written["mrn"] is None
    assert "MRN not found in document" in written["corrections"]

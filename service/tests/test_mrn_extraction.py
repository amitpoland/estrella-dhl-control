"""
test_mrn_extraction.py — MRN regex fallback helpers and orchestrator integration.

Tests:
  1. test_mrn_extracted_from_pdf_text       — valid MRN found via bare regex
  2. test_mrn_with_spaces_normalized        — spaced MRN stripped and uppercased
  3. test_mrn_not_extracted_when_invalid    — short/bad candidates rejected
  4. test_xml_path_unchanged_priority       — XML-derived MRN never overwritten
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.customs_parser_orchestrator import (
    _extract_mrn_from_text,
    _norm_mrn,
    _valid_mrn,
)


# ── 1. Valid MRN extracted from free text ─────────────────────────────────────

def test_mrn_extracted_from_pdf_text():
    # Bare pattern — no "MRN:" prefix, as agency docs often omit it
    text = "Numer dokumentu celnego 26PL123456789012345 Data odprawy 15.04.2026"
    result = _extract_mrn_from_text(text)
    assert result == "26PL123456789012345", f"Expected MRN, got {result!r}"


# ── 2. Spaces in MRN normalized ───────────────────────────────────────────────

def test_mrn_with_spaces_normalized():
    # Labeled form with internal spaces — common in scanned/HTML agency docs
    text = "MRN: 26 PL 1234 5678 90123 45"
    result = _extract_mrn_from_text(text)
    assert result is not None, "MRN with spaces should be extracted"
    # Must be space-free and uppercase after normalization
    assert " " not in result, "Normalized MRN must not contain spaces"
    assert result == result.upper(), "Normalized MRN must be uppercase"
    assert _valid_mrn(result), f"Normalized MRN {result!r} must pass validator"


# ── 3. Invalid candidates rejected ────────────────────────────────────────────

def test_mrn_not_extracted_when_invalid():
    # Too short (only 4 chars after country code)
    assert _extract_mrn_from_text("MRN: 26PL1234") is None

    # Wrong structure — starts with letters, not digits
    assert _extract_mrn_from_text("PL26ABCDEFGHIJKLMNO") is None

    # Random long string that looks alphanumeric but fails format
    assert _extract_mrn_from_text("ABCDEFGHIJKLMNOPQRSTU") is None

    # Empty text
    assert _extract_mrn_from_text("") is None

    # Ensure the validator itself gates correctly
    assert not _valid_mrn("26PL001")            # too short
    assert not _valid_mrn("26pl123456789012345") # not uppercased (validator expects upper)
    assert _valid_mrn("26PL123456789012345")     # correct


# ── 3b. Labeled regex: newline after MRN must not be consumed ────────────────

def test_mrn_labeled_regex_stops_at_newline():
    # Real-world PDF layout: "MRN: <mrn>\nData przyjęcia..."
    # Bug: [A-Za-z0-9\s] with \s matched \n + next word → corrupted MRN
    # Fix: [A-Za-z0-9 ] (space only) stops at the newline
    text = "MRN: 26PL44302D005LJ4R0\nData przyjecia zgłoszenia: 2026"
    result = _extract_mrn_from_text(text)
    assert result == "26PL44302D005LJ4R0", (
        f"Newline after MRN must not be consumed into capture. Got {result!r}"
    )


# ── 4. XML-path MRN not overwritten by fallback ───────────────────────────────

def test_xml_path_unchanged_priority(tmp_path, monkeypatch):
    """When audit.zc429 already provides an MRN, Priority 2b must never fire."""
    from app.services import customs_parser_orchestrator as orch

    fallback_called = []

    def _fake_fallback(sad_dir):
        fallback_called.append(str(sad_dir))
        return "26PL_FALLBACK_99999"

    monkeypatch.setattr(orch, "_extract_mrn_from_pdf_or_html", _fake_fallback)

    # Provide xml_dict via audit.zc429 with a real MRN
    from app.services.customs_xml_parser import parse_zc429_xml_from_dict
    monkeypatch.setattr(
        orch, "_extract_mrn_from_pdf_or_html", _fake_fallback,
    )

    # Mock parse_zc429_xml_from_dict to return controlled data with MRN
    monkeypatch.setattr(
        "app.services.customs_parser_orchestrator.parse_zc429_xml_from_dict"
        if hasattr(orch, "parse_zc429_xml_from_dict") else
        "app.services.customs_xml_parser.parse_zc429_xml_from_dict",
        lambda d: {"mrn": "26PL_XML_ORIGINAL", "duty_pln": 1000.0},
        raising=False,
    )

    sad_dir = tmp_path / "sad"
    sad_dir.mkdir()

    audit = {"zc429": {"mrn": "26PL_XML_ORIGINAL", "duty_pln": 1000.0}}
    result = orch.parse_customs_document("TEST", sad_dir, audit)

    assert result["mapped"].get("mrn") == "26PL_XML_ORIGINAL", (
        "XML-derived MRN must not be overwritten by fallback"
    )
    assert fallback_called == [], (
        "_extract_mrn_from_pdf_or_html must not be called when XML provides MRN"
    )

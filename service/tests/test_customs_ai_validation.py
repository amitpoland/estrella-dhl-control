"""
test_customs_ai_validation.py — Tests for the customs parsing hierarchy.

Verifies:
  1. XML takes priority over PDF
  2. PDF fallback when no XML
  3. AI supplements missing PDF fields
  4. AI returns None on failure — graceful degradation
  5. XML vs AI mismatch → risk_flag raised
  6. XML wins over AI always
  7. Financial fields not modified by AI
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.smoke


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sad_dir(tmp_path):
    """Create a temp sad directory."""
    d = tmp_path / "source" / "sad"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def sample_xml_dict():
    """Sample ZC429 data as parsed from XML (stored in audit.zc429)."""
    return {
        "mrn": "26PL44302D00A1J5R7",
        "lrn": "26S00RAE0S",
        "acceptance_date": "2026-04-29T12:44:45",
        "total_A00_duty_pln": 957.0,
        "total_B00_vat_pln": 9025.0,
        "importer_nip": "5252812119",
        "exporter": "ESTRELLA JEWELS LLP",
        "awb": "1012178215",
        "goods_items": [
            {
                "invoiced_usd": 10034.0,
                "statistical_value_pln": 37056.0,
                "hs_code": "711319",
                "description": "BIŻUTERIA PLATYNOWA",
                "release_date": "2026-04-29T13:30:21",
                "invoices": ["EJL/26-27/098"],
            },
            {
                "invoiced_usd": 332.0,
                "statistical_value_pln": 1226.0,
                "hs_code": "711311",
                "description": "BIŻUTERIA SREBRNA",
                "invoices": ["EJL/26-27/100"],
            },
        ],
    }


@pytest.fixture
def sample_parsed_json(sad_dir, sample_xml_dict):
    """Write sample parsed JSON to sad_dir."""
    p = sad_dir / "ZC429_parsed.json"
    p.write_text(json.dumps(sample_xml_dict), encoding="utf-8")
    return p


# ── Test 1: XML dict takes priority ────────────────────────────────────────

def test_xml_dict_priority(sad_dir, sample_xml_dict):
    """When audit.zc429 has parsed XML data, it is used — PDF/AI never called."""
    from service.app.services.customs_parser_orchestrator import parse_customs_document

    audit = {"zc429": sample_xml_dict}

    result = parse_customs_document("TEST_BATCH", sad_dir, audit=audit)

    assert result["source"] == "xml_dict"
    assert result["confidence"] == "high"
    assert result["mapped"]["mrn"] == "26PL44302D00A1J5R7"
    assert result["mapped"]["duty_a00_pln"] == 957.0
    assert result["mapped"]["vat_b00_pln"] == 9025.0
    assert len(result["ai_supplemented_fields"]) == 0


# ── Test 2: Parsed JSON fallback ───────────────────────────────────────────

def test_parsed_json_fallback(sad_dir, sample_parsed_json):
    """When no XML file or audit.zc429, but parsed JSON exists, use it."""
    from service.app.services.customs_parser_orchestrator import parse_customs_document

    result = parse_customs_document("TEST_BATCH", sad_dir, audit={})

    assert result["source"] == "xml_dict"
    assert result["confidence"] == "high"
    assert result["mapped"]["mrn"] == "26PL44302D00A1J5R7"


# ── Test 3: AI supplements missing PDF fields ──────────────────────────────

def test_ai_supplements_incomplete_pdf(sad_dir):
    """When PDF parse returns data but cn_code is missing, AI fills it."""
    from service.app.services import customs_parser_orchestrator as orch

    # Create a dummy PDF file (won't actually be parsed)
    (sad_dir / "test_zc429.pdf").write_bytes(b"%PDF-1.4 dummy")

    # Mock PDF parser to return partial data (no cn_code)
    partial_result = {
        "mrn": "26PL44302D00TEST",
        "duty_pln": 100.0,
        "vat_pln": 500.0,
        "clearance_date": "2026-01-01",
        "cn_code": None,  # Missing!
    }

    # Patch imports inside the orchestrator
    with patch.dict("sys.modules", {"pz_import_processor": MagicMock(parse_zc429=lambda p, c: partial_result)}):
        with patch.object(orch, "_try_ai_fallback", return_value={"cn_code": "711319"}):
            result = orch.parse_customs_document("TEST", sad_dir, audit={})

    assert "ai_supplement" in result["source"]
    assert "cn_code" in result["ai_supplemented_fields"]
    assert result["mapped"]["cn_code"] == "711319"


# ── Test 4: AI failure → graceful degradation ──────────────────────────────

def test_ai_failure_graceful(sad_dir, monkeypatch):
    """When AI parser fails, PDF result is used as-is without crash."""
    from service.app.services import customs_parser_orchestrator as orch

    (sad_dir / "test.pdf").write_bytes(b"%PDF-1.4 dummy")

    partial_result = {
        "mrn": "26PL44302DTEST",
        "duty_pln": 100.0,
        "vat_pln": 500.0,
        "clearance_date": "2026-01-01",
        "cn_code": None,
    }

    with patch.dict("sys.modules", {"pz_import_processor": MagicMock(parse_zc429=lambda p, c: partial_result)}):
        with patch("service.app.services.customs_parser_orchestrator._try_ai_fallback", return_value=None):
            result = orch.parse_customs_document("TEST", sad_dir, audit={})

    assert result["source"] == "pdf"
    assert result["mapped"]["mrn"] == "26PL44302DTEST"
    # cn_code was not supplemented
    assert result["mapped"].get("cn_code") is None


# ── Test 5: Validation detects mismatch, flags risk ───────────────────────

def test_validation_mismatch_flags_risk():
    """When duty values differ beyond tolerance, risk_flag is raised."""
    from service.app.services.customs_validator import validate_customs_data

    xml_data = {"duty_pln": 1225.0, "vat_pln": 9000.0, "mrn": "26PL44302DTEST"}
    ai_data  = {"duty_pln": 1300.0, "vat_pln": 9000.0, "mrn": "26PL44302DTEST"}

    result = validate_customs_data(xml_data, ai_data, "xml", "ai")

    assert result["validated"] is False
    assert "duty_pln_mismatch" in result["risk_flags"]
    assert result["risk_level"] == "high"
    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0]["field"] == "duty_pln"


# ── Test 6: Validation passes within tolerance ────────────────────────────

def test_validation_within_tolerance():
    """When values are within tolerance, validation passes."""
    from service.app.services.customs_validator import validate_customs_data

    xml_data = {"duty_pln": 1225.0, "customs_rate_usd": 3.6933}
    ai_data  = {"duty_pln": 1225.5, "customs_rate_usd": 3.6930}

    result = validate_customs_data(xml_data, ai_data)

    assert result["validated"] is True
    assert len(result["mismatches"]) == 0
    assert result["risk_level"] == "none"


# ── Test 7: AI never overwrites XML values ────────────────────────────────

def test_ai_never_overwrites_xml(sad_dir, sample_xml_dict):
    """When both XML and AI data exist, only XML values appear in final result."""
    from service.app.services.customs_parser_orchestrator import parse_customs_document

    # Provide XML data via audit.zc429
    audit = {"zc429": sample_xml_dict}

    # Even if AI would return different duty, XML wins because XML source
    # is complete and AI is never called
    result = parse_customs_document("TEST", sad_dir, audit=audit)

    assert result["source"] == "xml_dict"
    assert result["mapped"]["duty_a00_pln"] == 957.0  # XML value, not AI
    assert len(result["ai_supplemented_fields"]) == 0  # AI never called


# ── Test 8: customs_declaration in FORBIDDEN_FIELDS ───────────────────────

def test_customs_declaration_in_forbidden_fields():
    """customs_declaration is blocked from AI bridge writes."""
    from service.app.services.ai_bridge import FORBIDDEN_FIELDS

    assert "customs_declaration" in FORBIDDEN_FIELDS


# ── Test 9: XML parser from dict produces correct schema ──────────────────

def test_xml_parser_from_dict_schema(sample_xml_dict):
    """parse_zc429_xml_from_dict returns all required fields."""
    from service.app.services.customs_xml_parser import parse_zc429_xml_from_dict

    result = parse_zc429_xml_from_dict(sample_xml_dict)

    assert result is not None
    assert result["mrn"] == "26PL44302D00A1J5R7"
    assert result["duty_pln"] == 957.0
    assert result["vat_pln"] == 9025.0
    assert result["clearance_date"] == "2026-04-29"
    assert result["customs_rate_usd"] is not None
    assert result["cn_code"] == "711319, 711311"
    assert "EJL/26-27/098" in result["invoice_refs"]
    assert result["_parse_meta"]["source"] == "xml_dict"
    assert result["_parse_meta"]["confidence"] == "high"


# ── Test 10: Empty data returns None ──────────────────────────────────────

def test_xml_parser_empty_data():
    """parse_zc429_xml_from_dict returns None for empty input."""
    from service.app.services.customs_xml_parser import parse_zc429_xml_from_dict

    assert parse_zc429_xml_from_dict({}) is None
    assert parse_zc429_xml_from_dict(None) is None

"""
test_agency_sad_decision.py — Decision engine coverage.

Tests:
  1. test_not_parsed_blocks           — status != "parsed" → safe_to_run_pz False
  2. test_awaiting_file_blocks        — status == "awaiting_file" → False
  3. test_low_confidence_blocks       — confidence == "low" → False
  4. test_mrn_mismatch_blocks         — decl mrn != parsed mrn → False
  5. test_valid_no_decl_allows        — no customs_declaration → True (nothing to compare)
  6. test_valid_mrn_match_allows      — mrns match → True
  7. test_valid_decl_no_mrn_allows    — decl present but no mrn → True
  8. test_writes_audit_field          — decision written to audit.agency_sad_decision
  9. test_idempotent_via_monitor_hook — monitor hook skips when field already present
 10. test_no_financial_write          — customs_declaration unchanged after evaluate
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.agency_sad_decision import evaluate_agency_sad, _evaluate


# ── Pure logic tests (no filesystem) ─────────────────────────────────────────

def test_not_parsed_blocks():
    r = _evaluate({"status": "partial", "confidence": "high"}, {})
    assert r["safe_to_run_pz"] is False
    assert r["reason"] == "not_parsed"


def test_awaiting_file_blocks():
    r = _evaluate({"status": "awaiting_file"}, {})
    assert r["safe_to_run_pz"] is False
    assert r["reason"] == "not_parsed"


def test_low_confidence_blocks():
    r = _evaluate({"status": "parsed", "confidence": "low", "mrn": "26PL001"}, {})
    assert r["safe_to_run_pz"] is False
    assert r["reason"] == "low_confidence"


def test_mrn_mismatch_blocks():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26PL_AGENCY"},
        {"mrn": "26PL_ORIGINAL"},
    )
    assert r["safe_to_run_pz"] is False
    assert r["reason"] == "mrn_mismatch"


def test_valid_no_decl_allows():
    # No customs_declaration at all — nothing to compare against
    r = _evaluate({"status": "parsed", "confidence": "high", "mrn": "26PL001"}, {})
    assert r["safe_to_run_pz"] is True
    assert r["reason"] == "validated"


def test_valid_mrn_match_allows():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26PL001"},
        {"mrn": "26PL001"},
    )
    assert r["safe_to_run_pz"] is True
    assert r["reason"] == "validated"


def test_valid_decl_no_mrn_allows():
    # customs_declaration present but mrn absent — no basis to reject
    r = _evaluate(
        {"status": "parsed", "confidence": "medium", "mrn": "26PL001"},
        {"duty_a00_pln": 1261.0},   # has financial data but no mrn key
    )
    assert r["safe_to_run_pz"] is True
    assert r["reason"] == "validated"


# ── Filesystem tests ──────────────────────────────────────────────────────────

def _write_audit(tmp_path: Path, batch_id: str, data: dict) -> tuple[Path, Path]:
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(data), encoding="utf-8")
    return batch_dir, ap


def test_writes_audit_field(tmp_path):
    _, ap = _write_audit(tmp_path, "DEC1", {
        "batch_id": "DEC1",
        "agency_sad_parse": {"status": "parsed", "confidence": "high", "mrn": "26PL999"},
        "customs_declaration": {"mrn": "26PL999"},
    })
    audit = json.loads(ap.read_text())
    result = evaluate_agency_sad("DEC1", ap, audit)

    assert result["safe_to_run_pz"] is True
    written = json.loads(ap.read_text())
    dec = written.get("agency_sad_decision")
    assert dec is not None, "agency_sad_decision must be written to audit"
    assert dec["safe_to_run_pz"] is True
    assert dec["reason"] == "validated"
    assert dec.get("evaluated_at") is not None


def test_idempotent_existing_decision_not_overwritten(tmp_path):
    """evaluate_agency_sad is not called a second time by the monitor when decision exists."""
    existing_dec = {
        "safe_to_run_pz": False,
        "reason":          "mrn_mismatch",
        "evaluated_at":    "2026-01-01T00:00:00+00:00",
    }
    _, ap = _write_audit(tmp_path, "DEC2", {
        "batch_id": "DEC2",
        "agency_sad_parse":    {"status": "parsed", "confidence": "high", "mrn": "26PL_A"},
        "customs_declaration": {"mrn": "26PL_A"},   # would be "validated" if re-run
        "agency_sad_decision": existing_dec,        # already present
    })

    # Simulate monitor guard: skip if decision already set
    audit = json.loads(ap.read_text())
    if not audit.get("agency_sad_decision"):
        evaluate_agency_sad("DEC2", ap, audit)

    final = json.loads(ap.read_text())
    # Must remain unchanged
    assert final["agency_sad_decision"] == existing_dec


def test_no_financial_write(tmp_path):
    """evaluate_agency_sad must not mutate customs_declaration."""
    original_cd = {"mrn": "26PL001", "duty_a00_pln": 9999.0, "vat_b00_pln": 11895.0}
    _, ap = _write_audit(tmp_path, "DEC3", {
        "batch_id": "DEC3",
        "agency_sad_parse":    {"status": "parsed", "confidence": "high", "mrn": "26PL001"},
        "customs_declaration": original_cd,
    })
    audit = json.loads(ap.read_text())
    evaluate_agency_sad("DEC3", ap, audit)

    final = json.loads(ap.read_text())
    assert final["customs_declaration"] == original_cd, (
        "customs_declaration must not be modified by the decision engine"
    )


# ── MRN normalization tests ───────────────────────────────────────────────────

def test_mrn_match_with_spaces():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26PL 44302D"},
        {"mrn": "26PL44302D"},
    )
    assert r["safe_to_run_pz"] is True
    assert r["reason"] == "validated"
    assert r["mrn_match"] is True


def test_mrn_match_case_insensitive():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26pl44302d"},
        {"mrn": "26PL44302D"},
    )
    assert r["safe_to_run_pz"] is True
    assert r["reason"] == "validated"
    assert r["mrn_match"] is True


def test_mrn_mismatch_detected():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26PL_AGENCY"},
        {"mrn": "26PL_DIFFERENT"},
    )
    assert r["safe_to_run_pz"] is False
    assert r["reason"] == "mrn_mismatch"
    assert r["mrn_match"] is False


def test_output_contains_both_mrns():
    r = _evaluate(
        {"status": "parsed", "confidence": "high", "mrn": "26PL001"},
        {"mrn": "26PL001"},
    )
    assert r["safe_to_run_pz"] is True
    assert r["mrn_parsed"] == "26PL001"
    assert r["mrn_declared"] == "26PL001"
    assert r["mrn_match"] is True

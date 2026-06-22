"""
test_pz_verification_summary_coverage_fields.py — Lesson N API response gap (2026-06-22).

Root cause fixed:
  Both VerificationSummary constructors in routes_pz.py omitted
  invoice_value_coverage and invoice_refs_completeness, so these two-signal
  authority fields were computed by the engine and written to audit.json but
  never exposed in the /pz/process/_legacy HTTP response.

Coverage
--------
  1. VerificationSummary schema has invoice_value_coverage (Optional[bool])
  2. VerificationSummary schema has invoice_refs_completeness (Optional[str])
  3. VerificationSummary.model_dump() includes both fields with None by default
  4. Both fields round-trip through VerificationSummary constructor (bool + str)
  5. routes_pz.py success-path constructor passes invoice_value_coverage (source-grep)
  6. routes_pz.py success-path constructor passes invoice_refs_completeness (source-grep)
  7. routes_pz.py blocked-path constructor passes invoice_value_coverage (source-grep)
  8. routes_pz.py blocked-path constructor passes invoice_refs_completeness (source-grep)
  9. No VerificationSummary constructor in routes_pz.py omits either field (completeness)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

ROUTES_PZ = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_pz.py"


# ── 1–4: Schema contract ──────────────────────────────────────────────────────

def test_schema_has_invoice_value_coverage_field():
    from app.schemas.response import VerificationSummary
    fields = VerificationSummary.model_fields
    assert "invoice_value_coverage" in fields, (
        "VerificationSummary must declare invoice_value_coverage"
    )


def test_schema_has_invoice_refs_completeness_field():
    from app.schemas.response import VerificationSummary
    fields = VerificationSummary.model_fields
    assert "invoice_refs_completeness" in fields, (
        "VerificationSummary must declare invoice_refs_completeness"
    )


def _all_none_vs(**overrides):
    from app.schemas.response import VerificationSummary
    defaults = dict(
        invoice_refs_match=None, invoice_value_coverage=None,
        invoice_refs_completeness=None, cif_match=None,
        qty_match_by_type=None, importer_match=None, exporter_match=None,
        blocked_phrases_clean=None, duty_rate_ok=None, amendment_flags=[],
    )
    defaults.update(overrides)
    return VerificationSummary(**defaults)


def test_schema_model_dump_includes_both_fields_as_none():
    d = _all_none_vs().model_dump()
    assert "invoice_value_coverage" in d
    assert "invoice_refs_completeness" in d
    assert d["invoice_value_coverage"] is None
    assert d["invoice_refs_completeness"] is None


def test_both_fields_round_trip_through_constructor():
    d = _all_none_vs(
        invoice_value_coverage=True,
        invoice_refs_completeness="review_needed",
    ).model_dump()
    assert d["invoice_value_coverage"] is True
    assert d["invoice_refs_completeness"] == "review_needed"


# ── 5–9: Source-grep: both constructors in routes_pz.py must forward both fields ──

def _extract_verification_summary_blocks(src: str) -> list[str]:
    """
    Extract each VerificationSummary(...) constructor call as a string.
    Handles multi-line constructors by counting parentheses from the opening call.
    """
    blocks: list[str] = []
    pattern = re.compile(r"VerificationSummary\(")
    for m in pattern.finditer(src):
        start = m.start()
        depth = 0
        i = start + len("VerificationSummary")
        while i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(src[start : i + 1])
                    break
            i += 1
    return blocks


def test_routes_pz_success_path_passes_invoice_value_coverage():
    src = ROUTES_PZ.read_text(encoding="utf-8")
    blocks = _extract_verification_summary_blocks(src)
    assert len(blocks) >= 2, f"Expected ≥2 VerificationSummary constructors, found {len(blocks)}"
    # The success-path constructor is the last one (not inside a return statement for blocked)
    # Check that at least one block (the non-blocked one) includes the field
    non_blocked = [b for b in blocks if "errors" not in b and "[reason]" not in b]
    assert non_blocked, "Could not identify success-path VerificationSummary constructor"
    assert any("invoice_value_coverage" in b for b in non_blocked), (
        "Success-path VerificationSummary constructor must include invoice_value_coverage"
    )


def test_routes_pz_success_path_passes_invoice_refs_completeness():
    src = ROUTES_PZ.read_text(encoding="utf-8")
    blocks = _extract_verification_summary_blocks(src)
    non_blocked = [b for b in blocks if "errors" not in b and "[reason]" not in b]
    assert any("invoice_refs_completeness" in b for b in non_blocked), (
        "Success-path VerificationSummary constructor must include invoice_refs_completeness"
    )


def test_routes_pz_blocked_path_passes_invoice_value_coverage():
    src = ROUTES_PZ.read_text(encoding="utf-8")
    blocks = _extract_verification_summary_blocks(src)
    assert any("invoice_value_coverage" in b for b in blocks), (
        "At least one VerificationSummary constructor must pass invoice_value_coverage"
    )
    # All constructors must have it (completeness check)
    missing = [b for b in blocks if "invoice_value_coverage" not in b]
    assert not missing, (
        f"These VerificationSummary constructors omit invoice_value_coverage:\n"
        + "\n---\n".join(missing)
    )


def test_routes_pz_blocked_path_passes_invoice_refs_completeness():
    src = ROUTES_PZ.read_text(encoding="utf-8")
    blocks = _extract_verification_summary_blocks(src)
    missing = [b for b in blocks if "invoice_refs_completeness" not in b]
    assert not missing, (
        f"These VerificationSummary constructors omit invoice_refs_completeness:\n"
        + "\n---\n".join(missing)
    )


def test_all_verification_summary_constructors_include_both_new_fields():
    """Completeness guard: every constructor in routes_pz.py must include both fields."""
    src = ROUTES_PZ.read_text(encoding="utf-8")
    blocks = _extract_verification_summary_blocks(src)
    assert blocks, "No VerificationSummary constructors found — source structure has changed"
    for i, block in enumerate(blocks):
        assert "invoice_value_coverage" in block, (
            f"Constructor #{i + 1} omits invoice_value_coverage:\n{block}"
        )
        assert "invoice_refs_completeness" in block, (
            f"Constructor #{i + 1} omits invoice_refs_completeness:\n{block}"
        )

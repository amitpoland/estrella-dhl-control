"""test_excel_column_mapper.py — Regression tests for the three-tier column mapper.

Tests are grouped by concern:

    TestAlias          — Tier-1 exact alias paths
    TestFuzzy          — Tier-2 rapidfuzz accept / warning / unresolved paths
    TestBuildColMap    — build_col_map filtering contract
    TestLLMFallback    — LLM tier invocation contract (mocked — no real API calls)
    TestDataContract   — ColumnMapping dataclass fields, CANONICAL_FIELDS set
    TestExtractorAudit — _map_headers_with_audit() integration in extractor
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from dataclasses import dataclass

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.excel_column_mapper import (
    CANONICAL_FIELDS,
    ColumnMapping,
    build_col_map,
    map_all_headers,
)
from app.services.invoice_packing_extractor import (
    _FIELD_ALIASES,
    _map_headers,
    _map_headers_with_audit,
)


# ── TestAlias ─────────────────────────────────────────────────────────────────

class TestAlias:
    def test_known_header_maps_as_alias(self):
        mappings = map_all_headers(["Qty"], _FIELD_ALIASES)
        assert mappings[0].method == "alias"
        assert mappings[0].canonical_field == "quantity"
        assert mappings[0].confidence == 1.0

    def test_all_field_aliases_resolve_via_tier1(self):
        for alias_key, expected_field in _FIELD_ALIASES.items():
            mappings = map_all_headers([alias_key], _FIELD_ALIASES)
            m = mappings[0]
            assert m.method == "alias", (
                f"alias_key={alias_key!r} expected method='alias', got {m.method!r}"
            )
            assert m.canonical_field == expected_field, (
                f"alias_key={alias_key!r}: expected '{expected_field}', got '{m.canonical_field}'"
            )

    def test_currency_paren_stripped_before_alias(self):
        mappings = map_all_headers(["Value (EUR)"], _FIELD_ALIASES)
        m = mappings[0]
        assert m.method == "alias"
        assert m.canonical_field == "unit_price"

    def test_trailing_currency_stripped_before_alias(self):
        mappings = map_all_headers(["Value USD"], _FIELD_ALIASES)
        m = mappings[0]
        assert m.method == "alias"
        assert m.canonical_field == "unit_price"

    def test_col_index_preserved_for_alias(self):
        mappings = map_all_headers(["Junk", "Qty", "Gross Wt"], _FIELD_ALIASES)
        qty_m = next(m for m in mappings if m.canonical_field == "quantity")
        assert qty_m.col_index == 1

    def test_multiple_known_headers_all_alias(self):
        headers = ["Qty", "Value", "Net Wt"]
        mappings = map_all_headers(headers, _FIELD_ALIASES)
        assert all(m.method == "alias" for m in mappings)

    def test_original_header_preserved(self):
        mappings = map_all_headers(["Total Value"], _FIELD_ALIASES)
        assert mappings[0].original_header == "Total Value"

    def test_normalised_field_populated(self):
        mappings = map_all_headers(["Net Wt"], _FIELD_ALIASES)
        assert mappings[0].normalised == "net_wt"


# ── TestFuzzy ─────────────────────────────────────────────────────────────────

class TestFuzzy:
    def test_near_miss_typo_resolves(self):
        # "Quanity" (missing 't') is close enough to "quantity" alias key
        mappings = map_all_headers(["Quanity"], _FIELD_ALIASES)
        m = mappings[0]
        assert m.method in ("alias", "fuzzy"), (
            f"Expected alias or fuzzy, got {m.method!r} (normalised={m.normalised!r})"
        )
        assert m.canonical_field == "quantity"

    def test_completely_unrelated_header_is_unresolved(self):
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES)
        m = mappings[0]
        assert m.canonical_field is None
        assert m.method == "unresolved"

    def test_empty_header_is_unresolved(self):
        mappings = map_all_headers([""], _FIELD_ALIASES)
        m = mappings[0]
        assert m.method == "unresolved"
        assert m.canonical_field is None

    def test_whitespace_only_header_is_unresolved(self):
        mappings = map_all_headers(["   "], _FIELD_ALIASES)
        m = mappings[0]
        assert m.method == "unresolved"

    def test_fuzzy_confidence_is_fraction(self):
        # Find a header that maps via fuzzy (not exact alias) if any
        # We inject a synthetic variant that is close but not an exact key
        # This test is permissive: just checks that confidence is 0-1 for fuzzy
        mappings = map_all_headers(["Quanity"], _FIELD_ALIASES)
        m = mappings[0]
        if m.method == "fuzzy":
            assert 0.0 < m.confidence <= 1.0

    def test_unresolved_confidence_is_zero(self):
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES)
        m = mappings[0]
        assert m.confidence == 0.0

    def test_multiple_headers_mixed_resolution(self):
        headers = ["Qty", "ZZZZALPHABETAXYZ999", "Value"]
        mappings = map_all_headers(headers, _FIELD_ALIASES)
        methods = [m.method for m in mappings]
        assert methods[0] == "alias"    # Qty → alias
        assert methods[2] == "alias"    # Value → alias
        assert mappings[1].method == "unresolved"  # gibberish


# ── TestBuildColMap ───────────────────────────────────────────────────────────

class TestBuildColMap:
    def test_alias_mappings_included(self):
        mappings = map_all_headers(["Qty", "Value"], _FIELD_ALIASES)
        col_map = build_col_map(mappings)
        assert col_map.get(0) == "quantity"
        assert col_map.get(1) == "unit_price"

    def test_unresolved_excluded(self):
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999", "Qty"], _FIELD_ALIASES)
        col_map = build_col_map(mappings)
        assert 0 not in col_map
        assert 1 in col_map

    def test_fuzzy_warning_excluded(self):
        fake = ColumnMapping(
            col_index=0, original_header="Hmm", normalised="hmm",
            canonical_field="quantity", method="fuzzy_warning",
            confidence=0.85, reason="synthetic",
        )
        assert build_col_map([fake]) == {}

    def test_llm_advisory_excluded(self):
        fake = ColumnMapping(
            col_index=0, original_header="X", normalised="x",
            canonical_field="quantity", method="llm",
            confidence=0.75, reason="synthetic",
        )
        assert build_col_map([fake]) == {}

    def test_fuzzy_accepted_included(self):
        fake = ColumnMapping(
            col_index=0, original_header="Quanity", normalised="quanity",
            canonical_field="quantity", method="fuzzy",
            confidence=0.93, reason="synthetic",
        )
        col_map = build_col_map([fake])
        assert col_map == {0: "quantity"}

    def test_empty_mappings_returns_empty_dict(self):
        assert build_col_map([]) == {}

    def test_none_canonical_excluded(self):
        fake = ColumnMapping(
            col_index=0, original_header="X", normalised="x",
            canonical_field=None, method="alias",   # alias + None canonical (shouldn't happen normally)
            confidence=1.0, reason="synthetic",
        )
        assert build_col_map([fake]) == {}


# ── TestLLMFallback ───────────────────────────────────────────────────────────

class TestLLMFallback:
    def test_llm_not_called_when_disabled(self, monkeypatch):
        called: List[str] = []

        def mock_llm(header, candidates):
            called.append(header)
            return {"suggested_field": None, "confidence": 0.0, "reason": "mock"}

        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header", mock_llm
        )
        map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=False)
        assert called == [], "LLM must NOT be called when llm_fallback=False"

    def test_llm_called_for_unresolved_when_enabled(self, monkeypatch):
        called: List[str] = []

        def mock_llm(header, candidates):
            called.append(header)
            return {"suggested_field": None, "confidence": 0.0, "reason": "mock"}

        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header", mock_llm
        )
        map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=True)
        assert called, "LLM SHOULD be called when llm_fallback=True and header is unresolved"

    def test_llm_not_called_for_already_resolved_header(self, monkeypatch):
        called: List[str] = []

        def mock_llm(header, candidates):
            called.append(header)
            return {"suggested_field": "quantity", "confidence": 0.9, "reason": "mock"}

        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header", mock_llm
        )
        map_all_headers(["Qty"], _FIELD_ALIASES, llm_fallback=True)
        assert called == [], "LLM must NOT be called for headers already resolved via alias"

    def test_llm_suggestion_has_method_llm(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header",
            lambda h, c: {"suggested_field": "quantity", "confidence": 0.8, "reason": "mock match"},
        )
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=True)
        assert mappings[0].method == "llm"
        assert mappings[0].canonical_field == "quantity"

    def test_llm_advisory_not_in_build_col_map(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header",
            lambda h, c: {"suggested_field": "quantity", "confidence": 0.8, "reason": "mock"},
        )
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=True)
        col_map = build_col_map(mappings)
        assert 0 not in col_map, "LLM advisory must NEVER be included in build_col_map"

    def test_llm_no_suggestion_becomes_unresolved(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header",
            lambda h, c: {"suggested_field": None, "confidence": 0.0, "reason": "no match"},
        )
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=True)
        m = mappings[0]
        assert m.method == "unresolved"
        assert m.canonical_field is None

    def test_llm_hallucinated_field_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.excel_column_mapper._llm_suggest_header",
            lambda h, c: {"suggested_field": "non_existent_field_xyz", "confidence": 0.9, "reason": "hallucination"},
        )
        mappings = map_all_headers(["ZZZZALPHABETAXYZ999"], _FIELD_ALIASES, llm_fallback=True)
        m = mappings[0]
        # A hallucinated field not in canonical_candidates must be rejected
        # → either unresolved or llm with None canonical_field
        assert m.canonical_field != "non_existent_field_xyz", (
            "Hallucinated LLM field names must be rejected"
        )


# ── TestDataContract ──────────────────────────────────────────────────────────

class TestDataContract:
    def test_column_mapping_fields(self):
        m = ColumnMapping(
            col_index=3, original_header="Gross Wt", normalised="gross_wt",
            canonical_field="gross_weight", method="alias",
            confidence=1.0, reason="test",
        )
        assert m.col_index == 3
        assert m.original_header == "Gross Wt"
        assert m.normalised == "gross_wt"
        assert m.canonical_field == "gross_weight"
        assert m.method == "alias"
        assert m.confidence == 1.0
        assert m.reason == "test"

    def test_canonical_fields_is_frozenset(self):
        assert isinstance(CANONICAL_FIELDS, frozenset)

    def test_required_canonical_fields_present(self):
        required = {
            "quantity", "unit_price", "total_value",
            "gross_weight", "net_weight",
            "design_no", "item_type", "invoice_no",
        }
        assert required <= CANONICAL_FIELDS

    def test_all_alias_targets_in_canonical_fields(self):
        for alias_key, canonical in _FIELD_ALIASES.items():
            assert canonical in CANONICAL_FIELDS, (
                f"Alias target '{canonical}' (from key '{alias_key}') "
                f"is not in CANONICAL_FIELDS"
            )

    def test_map_all_headers_returns_one_entry_per_header(self):
        headers = ["Qty", "Value", "Junk", "", "Net Wt"]
        mappings = map_all_headers(headers, _FIELD_ALIASES)
        assert len(mappings) == len(headers)

    def test_col_index_matches_position(self):
        headers = ["Qty", "Junk", "Value"]
        mappings = map_all_headers(headers, _FIELD_ALIASES)
        for i, m in enumerate(mappings):
            assert m.col_index == i


# ── TestExtractorAudit ────────────────────────────────────────────────────────

class TestExtractorAudit:
    """Verify _map_headers_with_audit() contract in invoice_packing_extractor."""

    def test_returns_two_tuple(self):
        col_map, audit = _map_headers_with_audit(["Qty", "Value"])
        assert isinstance(col_map, dict)
        assert isinstance(audit, list)

    def test_col_map_matches_map_headers_for_known_aliases(self):
        headers = ["Qty", "Value", "Net Wt"]
        old_col_map = _map_headers(headers)
        new_col_map, _ = _map_headers_with_audit(headers)
        assert new_col_map == old_col_map

    def test_audit_length_equals_header_count(self):
        headers = ["Qty", "Value", "Junk", "Net Wt"]
        _, audit = _map_headers_with_audit(headers)
        assert len(audit) == len(headers)

    def test_known_aliases_are_method_alias_in_audit(self):
        _, audit = _map_headers_with_audit(["Qty", "Value"])
        for m in audit:
            assert m.method == "alias"
            assert m.canonical_field is not None

    def test_col_map_excludes_unresolved(self):
        col_map, audit = _map_headers_with_audit(["Qty", "ZZZZALPHABETAXYZ999", "Value"])
        assert 0 in col_map
        assert 1 not in col_map
        assert 2 in col_map

    def test_audit_has_col_index(self):
        _, audit = _map_headers_with_audit(["Qty", "Value", "Net Wt"])
        for i, m in enumerate(audit):
            assert m.col_index == i

    def test_extract_packing_diagnostic_has_audit_key(self, tmp_path):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        # EJL-style preamble
        for _ in range(8):
            ws.append([])
        # Header row
        ws.append(["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
                   "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"])
        # Data row
        ws.append([1, "BR", "D12345", "14W", "VS", 0.25, 0.0, 1, 150.00, 150.00, ""])
        p = tmp_path / "ejl_test.xlsx"
        wb.save(str(p))

        from app.services.invoice_packing_extractor import extract_packing
        rows, _, _, diag = extract_packing(p)
        assert "column_mapping_audit" in diag, (
            "column_mapping_audit key must be present in diagnostic dict for xlsx files"
        )

    def test_audit_in_diagnostic_is_list_of_dicts(self, tmp_path):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        for _ in range(8):
            ws.append([])
        ws.append(["PkSr", "Ctg", "DesignNo", "Kt/Color", "Quality",
                   "Dia Wt", "Col Wt", "Qty", "Value", "Total Value", "Size"])
        ws.append([1, "BR", "D12345", "14W", "VS", 0.25, 0.0, 1, 150.00, 150.00, ""])
        p = tmp_path / "ejl_diag.xlsx"
        wb.save(str(p))

        from app.services.invoice_packing_extractor import extract_packing
        _, _, _, diag = extract_packing(p)
        audit = diag.get("column_mapping_audit", [])
        assert isinstance(audit, list)
        if audit:
            entry = audit[0]
            assert isinstance(entry, dict)
            for field in ("col_index", "original_header", "normalised",
                          "canonical_field", "method", "confidence", "reason"):
                assert field in entry, f"Audit entry missing key '{field}'"

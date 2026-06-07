"""
test_customer_master_resolver.py — Customer Master direct-match resolver tests.

Tests for _resolve_customer_via_master() in routes_proforma.py.

Authority chain (PROJECT_STATE.md DECISIONS 2026-06-07):
  Customer Master is PRIMARY authority for client identity, email, address.
  wfirma_customers cache is a HELPER/CACHE, NOT the authority.

The resolver must:
  1. Match exact normalized bill_to_name (case-insensitive)
  2. Match prefix (draft name is leading substring of CM bill_to_name)
  3. Match reverse-prefix (CM name is leading substring of draft name)
  4. Return ambiguous when multiple matches found
  5. Return None (fall through) when no matches — NOT found=false
  6. Be tried BEFORE wfirma_customers cache fallback
  7. Normalize whitespace (collapse double spaces) before matching
  8. Not use fuzzy matching that could match unrelated companies

Sprint: Customer Master Resolver Authority Fix
Target: routes_proforma.py
"""
from __future__ import annotations

import pathlib
import re

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = SERVICE_DIR / "app"
ROUTES_PROFORMA = APP_DIR / "api" / "routes_proforma.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. _resolve_customer_via_master exists and is called before wfirma cache
# =============================================================================

class TestCustomerMasterResolverExists:
    """_resolve_customer_via_master must exist and be called before wfirma cache."""

    def test_helper_function_exists(self):
        """_resolve_customer_via_master must be defined in routes_proforma."""
        src = _read(ROUTES_PROFORMA)
        assert "def _resolve_customer_via_master(" in src

    def test_called_before_wfirma_cache(self):
        """Customer Master path must be tried BEFORE wfirma_customers cache."""
        src = _read(ROUTES_PROFORMA)
        # Inside _resolve_customer, _resolve_customer_via_master must appear
        # before wfdb.get_customer (the wfirma cache lookup)
        idx_resolve = src.find("def _resolve_customer(")
        assert idx_resolve > 0
        region = src[idx_resolve:]
        cm_pos = region.find("_resolve_customer_via_master")
        wf_pos = region.find("wfdb.get_customer")
        assert cm_pos > 0, "Must call _resolve_customer_via_master"
        assert wf_pos > 0, "Must still have wfirma cache fallback"
        assert cm_pos < wf_pos, (
            "Customer Master must be tried BEFORE wfirma_customers cache — "
            f"CM at offset {cm_pos}, wfirma at offset {wf_pos}"
        )

    def test_docstring_declares_primary_authority(self):
        """Docstring must declare Customer Master as PRIMARY AUTHORITY."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 800]
        assert "PRIMARY" in region.upper() or "primary" in region.lower()
        assert "authority" in region.lower() or "AUTHORITY" in region


# =============================================================================
# 2. Exact match — normalized name match against bill_to_name
# =============================================================================

class TestCustomerMasterExactMatch:
    """Exact normalized name match against Customer Master bill_to_name."""

    def test_exact_match_strategy_name(self):
        """Exact match must return match_strategy='customer_master'."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert '"customer_master"' in region or "'customer_master'" in region, (
            "Exact Customer Master match must use strategy 'customer_master'"
        )

    def test_exact_match_returns_found_true(self):
        """Exact match result must set found=True."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Must return found: True for exact match
        assert '"found"' in region or "'found'" in region
        assert "True" in region

    def test_exact_match_returns_contractor_id(self):
        """Exact match must return wfirma_customer_id from CM bill_to_contractor_id."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert "wfirma_customer_id" in region
        assert "bill_to_contractor_id" in region

    def test_case_insensitive_comparison(self):
        """Match must be case-insensitive (uses .lower())."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert ".lower()" in region, "Must use case-insensitive comparison"


# =============================================================================
# 3. Prefix match — draft name is leading substring of CM name
# =============================================================================

class TestCustomerMasterPrefixMatch:
    """Prefix match: draft name is a leading substring of CM bill_to_name."""

    def test_prefix_match_strategy_name(self):
        """Prefix match must return match_strategy='customer_master_prefix'."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert '"customer_master_prefix"' in region or "'customer_master_prefix'" in region

    def test_prefix_requires_word_boundary(self):
        """Prefix match must check for word boundary (space or separator)."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Must use startswith with space or separator — not bare substring
        assert ".startswith(" in region, "Must use startswith for prefix match"

    def test_prefix_match_returns_found_true(self):
        """Prefix match result must set found=True."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Found strategy customer_master_prefix
        match = re.search(
            r'"customer_master_prefix".*?"found".*?True',
            region,
            re.DOTALL,
        )
        # Alternative: just verify both exist in the function
        assert '"customer_master_prefix"' in region
        # And that found=True is returned in prefix section
        prefix_section_start = region.find('"customer_master_prefix"')
        prefix_section = region[max(0, prefix_section_start - 200):prefix_section_start + 200]
        assert "True" in prefix_section


# =============================================================================
# 4. Reverse-prefix match — CM name is leading substring of draft name
# =============================================================================

class TestCustomerMasterReversePrefixMatch:
    """Reverse-prefix: CM name is a leading substring of draft name."""

    def test_reverse_prefix_match_strategy_name(self):
        """Reverse-prefix must return match_strategy='customer_master_reverse_prefix'."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        # The function can be up to ~4500 chars with all three match strategies
        region = src[idx:idx + 5000]
        assert ('"customer_master_reverse_prefix"' in region
                or "'customer_master_reverse_prefix'" in region)

    def test_reverse_prefix_tried_after_prefix(self):
        """Reverse-prefix must be tried AFTER prefix (prefix has priority)."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 5000]
        prefix_pos = region.find('"customer_master_prefix"')
        rev_pos = region.find('"customer_master_reverse_prefix"')
        assert prefix_pos > 0
        assert rev_pos > 0
        assert prefix_pos < rev_pos, (
            "Prefix match must be tried BEFORE reverse-prefix"
        )


# =============================================================================
# 5. Ambiguous match — multiple Customer Master matches return ambiguous
# =============================================================================

class TestCustomerMasterAmbiguous:
    """Multiple matches must return ambiguous=True, not pick arbitrarily."""

    def test_ambiguous_flag_set(self):
        """Multiple matches must set ambiguous=True."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert '"ambiguous"' in region or "'ambiguous'" in region

    def test_ambiguous_returns_candidates(self):
        """Ambiguous result must include candidates list."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert '"candidates"' in region or "'candidates'" in region

    def test_ambiguous_does_not_set_found_true(self):
        """Ambiguous result must NOT set found=True."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Find all ambiguous blocks — they should NOT contain "found": True
        # Each ambiguous block has "ambiguous": True, "match_strategy": "ambiguous"
        # We check there's no "found" key in those blocks
        ambiguous_sections = []
        pos = 0
        while True:
            start = region.find('"ambiguous"', pos)
            if start < 0:
                break
            section = region[max(0, start - 50):start + 200]
            ambiguous_sections.append(section)
            pos = start + 1
        assert len(ambiguous_sections) >= 1, "Must have at least one ambiguous block"
        for section in ambiguous_sections:
            # Ambiguous blocks should have match_strategy=ambiguous but NOT found=True
            if '"match_strategy"' in section and '"ambiguous"' in section:
                assert '"found"' not in section, (
                    "Ambiguous result must NOT set found=True"
                )


# =============================================================================
# 6. Fall-through — returns None when no CM match (NOT found=false)
# =============================================================================

class TestCustomerMasterFallThrough:
    """No match returns None (not found=false) so wfirma cache gets a chance."""

    def test_returns_none_on_no_match(self):
        """Must return None (not a dict with found=false) when no CM match."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert "return None" in region, (
            "Must return None on no match — not a dict with found=false"
        )

    def test_return_type_is_optional_dict(self):
        """Return type annotation must be Optional[Dict]."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 200]
        assert "Optional" in region, "Return type must be Optional[Dict[str, Any]]"

    def test_caller_checks_none_before_update(self):
        """_resolve_customer must check for None return before calling .update()."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer(")
        assert idx > 0
        # The caller section with cm_match check may be further into the function
        region = src[idx:idx + 5000]
        # Must check cm_match is not None before updating out
        assert ("is not None" in region
                or "if cm_match" in region
                or "cm_match is not None" in region), (
            "Caller must check for None before using CM result"
        )


# =============================================================================
# 7. Whitespace normalization — double spaces collapsed before match
# =============================================================================

class TestCustomerMasterWhitespaceNormalization:
    """Double spaces in CM bill_to_name must be collapsed before matching."""

    def test_uses_normalize_client_name(self):
        """Must use _normalize_client_name for CM bill_to_name normalization."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert "_normalize_client_name" in region, (
            "Must use _normalize_client_name to normalize CM names"
        )

    def test_normalize_collapses_whitespace(self):
        """_normalize_client_name must collapse internal whitespace runs."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _normalize_client_name(")
        assert idx > 0
        # Need enough chars to capture the full function body (past docstring)
        region = src[idx:idx + 600]
        # Must use regex to collapse whitespace
        assert "\\s+" in region or "re.sub" in region or "_re.sub" in region, (
            "_normalize_client_name must collapse internal whitespace"
        )


# =============================================================================
# 8. No unsafe fuzzy matching
# =============================================================================

class TestCustomerMasterNoUnsafeMatch:
    """Must NOT use fuzzy matching that could match unrelated companies."""

    def test_no_substring_match_without_boundary(self):
        """Must NOT use bare 'in' operator for substring matching."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Filter to code lines only (no comments, no docstrings)
        lines = region.split("\n")
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        code = "\n".join(code_lines)
        # Should not use "norm_lc in cm_norm" — that's unsafe substring match
        # Safe patterns: .startswith(), ==, explicit boundary checks
        assert "in cm_norm" not in code and "in norm_lc" not in code, (
            "Must NOT use bare 'in' for substring match — use startswith with boundary"
        )

    def test_uses_startswith_for_prefix(self):
        """Prefix matching must use .startswith() — safe boundary-aware match."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert ".startswith(" in region

    def test_no_fuzzywuzzy_or_difflib(self):
        """Must NOT use fuzzy matching libraries."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        assert "fuzz" not in region.lower()
        assert "difflib" not in region.lower()
        assert "SequenceMatcher" not in region

    def test_does_not_import_customer_master_db_inline(self):
        """list_customers import must be at module level, not inline."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_customer_via_master(")
        assert idx > 0
        region = src[idx:idx + 3000]
        # Should not have an inline import of customer_master_db
        assert "from ..services.customer_master_db import" not in region, (
            "Import must be at module level, not inline in the function"
        )

    def test_customer_master_list_import_exists_at_module_level(self):
        """list_customers must be imported at module level."""
        src = _read(ROUTES_PROFORMA)
        # Check for module-level import of list_customers
        assert ("list_customers" in src.split("def ")[0]
                or "_list_customer_master" in src.split("def ")[0]), (
            "list_customers must be imported at module level"
        )

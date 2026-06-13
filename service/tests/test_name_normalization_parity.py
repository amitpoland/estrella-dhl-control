"""
Test parity between original name normalization implementations and the new consolidated module.

Ensures that moving functions to the new module preserves exact behavior.
Tests both the new module functions and the delegate functions.
"""
import re
import unicodedata
from typing import Optional

import pytest

from app.services import name_normalization
from app.services.customer_resolution_authority import _normalize_name as cra_normalize
from app.api.routes_proforma import _normalize_client_name as proforma_normalize
from app.services.suppliers_db import _normalize_name as suppliers_normalize
from app.services.wfirma_customer_auto_resolve import _normalize_name as wfirma_auto_normalize
from app.services.master_data_intelligence import _norm as master_data_norm_delegate
from app.services.packing_contractor_resolver import normalise_name as packing_normalize
from app.services.wfirma_customer_sync import normalise_client_name as wfirma_sync_normalize


# ── Frozen original implementations (mechanically captured from git show 62810c2:...) ──


def _frozen_customer_resolution_normalize_name(s: Optional[str]) -> str:
    """Frozen original from customer_resolution_authority.py:60"""
    if not s:
        return ""
    return " ".join(s.strip().split()).lower()


def _frozen_proforma_normalize_client_name(raw: str) -> str:
    """Frozen original from routes_proforma.py:263"""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def _frozen_suppliers_db_normalize_name(name: str) -> str:
    """Frozen original from suppliers_db.py:429"""
    # Constants from suppliers_db.py:29-30
    _PUNCT_RE = re.compile(r"[^\w\s]")
    _MULTI_SPACE_RE = re.compile(r"\s+")

    if not name:
        return ""
    s = name.lower().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def _frozen_wfirma_auto_resolve_normalize_name(raw: str) -> str:
    """Frozen original from wfirma_customer_auto_resolve.py:87"""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def _frozen_master_data_norm(s: Optional[str]) -> str:
    """Frozen original from master_data_intelligence.py:135"""
    if not s:
        return ""
    t = unicodedata.normalize("NFD", s.lower().strip())
    # strip common legal entity suffixes for name-based dedup
    for suffix in (" sp z o.o.", " sp. z o.o.", " s.a.", " gmbh", " ltd", " llp",
                   " b.v.", " s.r.o.", " s.r.l.", " inc.", " inc", " corp."):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return re.sub(r"\s+", " ", t)


def _frozen_packing_contractor_normalise_name(name: Optional[str]) -> str:
    """Frozen original from packing_contractor_resolver.py:112"""
    # ASCII fallback table and constants from packing_contractor_resolver.py
    _ASCII_FALLBACK = str.maketrans({
        "ł": "l",  "Ł": "L",
        "ø": "o",  "Ø": "O",
        "æ": "ae", "Æ": "AE",
        "å": "a",  "Å": "A",
        "ß": "ss",
        "œ": "oe", "Œ": "OE",
        "ð": "d",  "Ð": "D",
    })

    _LEGAL_SUFFIXES = (
        r"spółka z ograniczoną odpowiedzialnością",
        r"sp\.?\s*z\s*o\.?\s*o\.?",
        r"pvt\.?\s*ltd\.?",
        r"private\s+limited",
        r"s\.r\.o\.?",
        r"co\.?\s*,?\s*ltd\.?",
        r"co\.?\s*ltd\.?",
        r"limited",
        r"llp\.?",
        r"ltd\.?",
        r"gmbh",
        r"a\.?g\.?",
        r"s\.?a\.?s\.?",
        r"s\.?a\.?",
        r"b\.?v\.?",
        r"oy",
        r"ab",
        r"inc\.?",
        r"llc",
        r"eood",
        r"corp\.?",
    )
    _LEGAL_SUFFIXES_RE = re.compile(
        r"\b(?:" + "|".join(_LEGAL_SUFFIXES) + r")\b\s*\.?\s*$",
        re.IGNORECASE,
    )

    def _strip_accents(s: str) -> str:
        """Strip combining accents AND apply manual ASCII fallback for letters
        NFKD does not decompose (Polish ł, Nordic ø/æ/å, German ß, etc.)."""
        nfkd = unicodedata.normalize("NFKD", s)
        base = "".join(c for c in nfkd if not unicodedata.combining(c))
        return base.translate(_ASCII_FALLBACK)

    if not name:
        return ""
    s = _strip_accents(str(name)).lower().strip()
    # Drop trailing non-word punctuation BEFORE suffix detection so that
    # "beta, GMBH!" reaches the suffix regex as "beta, gmbh".
    s = re.sub(r"[^\w\s,.\-]+$", "", s).strip()
    # Drop trailing legal suffix once or twice (handles "Co., Ltd." → "" path).
    for _ in range(2):
        before = s
        s = _LEGAL_SUFFIXES_RE.sub("", s).strip(" ,.;:-")
        if s == before:
            break
    # Drop punctuation except spaces.
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _frozen_wfirma_sync_normalise_client_name(name: str) -> str:
    """Frozen original from wfirma_customer_sync.py:60"""
    # Constants from wfirma_customer_sync.py:56-57
    _WHITESPACE = re.compile(r"\s+")
    _TRAILING_PUNCT = re.compile(r"[\.,;:!\?]+$")

    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = _WHITESPACE.sub(" ", s)
    s = _TRAILING_PUNCT.sub("", s)
    return s.casefold()


# ── Test corpus ──


TEST_CORPUS = [
    # Basic cases
    "",
    "   ",
    "Simple Name",
    "UPPER CASE",
    "lower case",
    "Mixed Case Name",

    # Polish diacritics
    "ŁÓDŹ Sp. z o.o.",
    "Żółć S.A.",
    "Kraków Główny",
    "Wrocław Śródmieście",
    "Gdańsk Przysądź",

    # German and other European
    "Münster GmbH",
    "Straße Test",
    "Größe",
    "WEISS",

    # Legal suffixes
    "Diamond Group Sp. z o.o.",
    "Clear-Diamonds Ltd.",
    "Gold Trading LLC",
    "Silver Corp.",
    "Bronze Inc.",
    "Platinum GmbH",
    "Metal Works Limited",
    "Jewels & Co., Ltd.",
    "Precious Stones LLP",
    "Gem Trading S.A.",
    "Crystal Import B.V.",
    "Stone Export s.r.o.",

    # Whitespace variations
    "  Leading Spaces",
    "Trailing Spaces  ",
    "  Both Ends  ",
    "Multiple    Internal     Spaces",
    "Tab\tSeparated",
    "Newline\nSeparated",
    "Mixed\t\n  Whitespace",

    # Punctuation
    "Name, with comma",
    "Name. with period",
    "Name; with semicolon",
    "Name: with colon",
    "Name! with exclamation",
    "Name? with question",
    "Name-with-dash",
    "Name_with_underscore",
    "Name (with parentheses)",
    "Name [with brackets]",
    "Name {with braces}",
    "Name/with/slash",
    "Name\\with\\backslash",
    "Name@with@at",
    "Name#with#hash",
    "Name$with$dollar",
    "Name%with%percent",
    "Name^with^caret",
    "Name&with&ampersand",
    "Name*with*asterisk",
    "Name+with+plus",
    "Name=with=equals",

    # Full-width and compatibility characters (NFKC territory)
    "Ｆｕｌｌｗｉｄｔｈ",  # Full-width Latin
    "＋－×÷",  # Full-width operators
    "ﬁﬂ",  # Ligatures

    # Non-ASCII punctuation
    "Name — with em-dash",
    "Name – with en-dash",
    '"Smart quotes"',
    "'Single smart quotes'",
    "Name…with ellipsis",
    "Name • with bullet",
    "Name ‰ with per-mille",

    # Edge cases for casefold vs lower
    "ß",  # German sharp s
    "İ",  # Turkish capital i with dot
    "ı",  # Turkish dotless i

    # Complex combinations
    "Łódź Trading Sp. z o.o. — Premium Goods!",
    "  WEISS & SÖHNE GMBH  ",
    "Crystal…Import ＆ Export Ltd.",
]

# Add None for functions that accept Optional[str]
OPTIONAL_TEST_CORPUS = TEST_CORPUS + [None]


# ── Parity tests ──


class TestNameNormalizationParity:
    """Test that new module functions match frozen originals exactly."""

    def test_customer_resolution_parity(self):
        """Test customer_resolution_normalize_name parity."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = _frozen_customer_resolution_normalize_name(input_val)
            actual = name_normalization.customer_resolution_normalize_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_proforma_parity(self):
        """Test proforma_normalize_client_name parity."""
        for input_val in TEST_CORPUS:  # This function doesn't accept None
            expected = _frozen_proforma_normalize_client_name(input_val)
            actual = name_normalization.proforma_normalize_client_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_suppliers_db_parity(self):
        """Test suppliers_db_normalize_name parity."""
        for input_val in TEST_CORPUS:  # This function doesn't accept None
            expected = _frozen_suppliers_db_normalize_name(input_val)
            actual = name_normalization.suppliers_db_normalize_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_wfirma_auto_resolve_parity(self):
        """Test wfirma_auto_resolve_normalize_name parity."""
        for input_val in TEST_CORPUS:  # This function doesn't accept None
            expected = _frozen_wfirma_auto_resolve_normalize_name(input_val)
            actual = name_normalization.wfirma_auto_resolve_normalize_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_master_data_norm_parity(self):
        """Test master_data_norm parity."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = _frozen_master_data_norm(input_val)
            actual = name_normalization.master_data_norm(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_packing_contractor_parity(self):
        """Test packing_contractor_normalise_name parity."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = _frozen_packing_contractor_normalise_name(input_val)
            actual = name_normalization.packing_contractor_normalise_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_wfirma_sync_parity(self):
        """Test wfirma_sync_normalise_client_name parity."""
        for input_val in TEST_CORPUS:  # This function doesn't accept None
            expected = _frozen_wfirma_sync_normalise_client_name(input_val)
            actual = name_normalization.wfirma_sync_normalise_client_name(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"


class TestDelegateParity:
    """Test that delegate functions match new module functions."""

    def test_customer_resolution_delegate(self):
        """Test customer resolution delegate matches new module."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = name_normalization.customer_resolution_normalize_name(input_val)
            actual = cra_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_proforma_delegate(self):
        """Test proforma delegate matches new module."""
        for input_val in TEST_CORPUS:
            expected = name_normalization.proforma_normalize_client_name(input_val)
            actual = proforma_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_suppliers_db_delegate(self):
        """Test suppliers_db delegate matches new module."""
        for input_val in TEST_CORPUS:
            expected = name_normalization.suppliers_db_normalize_name(input_val)
            actual = suppliers_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_wfirma_auto_resolve_delegate(self):
        """Test wfirma_auto_resolve delegate matches new module."""
        for input_val in TEST_CORPUS:
            expected = name_normalization.wfirma_auto_resolve_normalize_name(input_val)
            actual = wfirma_auto_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_master_data_delegate(self):
        """Test master_data delegate matches new module."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = name_normalization.master_data_norm(input_val)
            actual = master_data_norm_delegate(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_packing_contractor_delegate(self):
        """Test packing_contractor delegate matches new module."""
        for input_val in OPTIONAL_TEST_CORPUS:
            expected = name_normalization.packing_contractor_normalise_name(input_val)
            actual = packing_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"

    def test_wfirma_sync_delegate(self):
        """Test wfirma_sync delegate matches new module."""
        for input_val in TEST_CORPUS:
            expected = name_normalization.wfirma_sync_normalise_client_name(input_val)
            actual = wfirma_sync_normalize(input_val)
            assert actual == expected, f"Input: {input_val!r}, Expected: {expected!r}, Got: {actual!r}"


class TestLeafRule:
    """Test that name_normalization.py imports only stdlib modules."""

    def test_leaf_rule_source_grep(self):
        """Verify name_normalization.py contains no app imports."""
        import inspect
        import_lines = []

        # Read the source file to check imports
        name_norm_file = inspect.getfile(name_normalization)
        with open(name_norm_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line.startswith('from app') or line.startswith('from .') or line.startswith('from ..'):
                    if 'app' in line:  # Only flag app imports
                        import_lines.append(f"Line {line_num}: {line}")

        assert not import_lines, f"Found forbidden app imports in name_normalization.py: {import_lines}"


class TestImportCycle:
    """Test that importing name_normalization from each host module works."""

    def test_import_from_all_hosts(self):
        """Test that name_normalization can be imported from all host module contexts."""
        # This test simply imports each module and verifies name_normalization is available
        from app.services.customer_resolution_authority import name_normalization as nn1
        from app.api.routes_proforma import name_normalization as nn2
        from app.services.suppliers_db import name_normalization as nn3
        from app.services.wfirma_customer_auto_resolve import name_normalization as nn4
        from app.services.master_data_intelligence import name_normalization as nn5
        from app.services.packing_contractor_resolver import name_normalization as nn6
        from app.services.wfirma_customer_sync import name_normalization as nn7

        # Verify they're all the same module
        assert nn1 is nn2 is nn3 is nn4 is nn5 is nn6 is nn7

        # Verify all seven functions are available
        assert hasattr(nn1, 'customer_resolution_normalize_name')
        assert hasattr(nn1, 'proforma_normalize_client_name')
        assert hasattr(nn1, 'suppliers_db_normalize_name')
        assert hasattr(nn1, 'wfirma_auto_resolve_normalize_name')
        assert hasattr(nn1, 'master_data_norm')
        assert hasattr(nn1, 'packing_contractor_normalise_name')
        assert hasattr(nn1, 'wfirma_sync_normalise_client_name')


class TestRouteDashboardCrossModuleImport:
    """Test that routes_dashboard.py cross-module import still works."""

    def test_routes_dashboard_import_works(self):
        """Verify routes_dashboard.py can still import _normalize_name from wfirma_customer_auto_resolve."""
        # This import must work unchanged per verdict condition 4
        from app.services.wfirma_customer_auto_resolve import _normalize_name

        # Test that it works
        result = _normalize_name("Test   Name")
        assert result == "Test Name"

        # Verify it's the delegate function
        expected = name_normalization.wfirma_auto_resolve_normalize_name("Test   Name")
        assert result == expected
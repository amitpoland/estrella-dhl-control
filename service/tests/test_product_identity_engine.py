"""
test_product_identity_engine.py — Unit tests for product_identity_engine.py

Covers:
  1.  CUFFLINK translation — customs_description_engine produces Polish
  2.  EJL product_code parsing — prefix, invoice_no, line_position, globally_unique
  3.  EJL short code (no line suffix) — still EJL, line_position=0
  4.  417 Global non-global-uniqueness flag
  5.  Unknown product_code format
  6.  Generic fallback blocked — is_generic_description returns True
  7.  Non-generic description passes — is_generic_description returns False
  8.  description_bilingual format — Polish first, slash, English
  9.  description_bilingual Polish-only fallback (empty English)
  10. customs_description_pl Polish-only — no English words
  11. confidence HIGH — all components present
  12. confidence MEDIUM — item_type + karat + description_pl but no color/stone
  13. confidence LOW — missing item_type
  14. confidence LOW — generic description_pl
  15. 417G code → always LOW confidence / not wfirma_eligible
  16. Forbidden product_code keys (RING, PENDANT, etc.) not allowed as product rows
  17. CUFFLINK normalised to CUFFLINKS in identity
  18. quality_string parsed — lab-grown compound
  19. quality_string parsed — named stone
  20. stone_type derived from quality_string when not supplied
  21. dry-run backfill: scan_outputs reports counts, writes nothing
  22. wfirma_eligible True for HIGH EJL
  23. wfirma_eligible False for LOW
  24. wfirma_eligible False for 417G even when description is specific
  25. missing_fields list correctly populated
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# Tests live at service/tests/; engine at service/app/services/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Engine-root (project root) — needed for customs_description_engine import
_ENGINE_ROOT = Path(__file__).resolve().parents[3]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from app.services.product_identity_engine import (
    CANONICAL_ITEM_TYPES,
    FORBIDDEN_PRODUCT_CODE_KEYS,
    GENERIC_FALLBACK_DESCRIPTIONS,
    KNOWN_KARAT_VALUES,
    KNOWN_METAL_COLORS,
    QualityComponents,
    assign_confidence,
    compose_bilingual,
    is_generic_description,
    parse_product_code,
    parse_quality_string,
    resolve_product_identity,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CUFFLINK translation — customs_description_engine path
# ══════════════════════════════════════════════════════════════════════════════

class TestCufflinkTranslation:
    """
    CUFFLINK item_type must produce "Spinki do mankietów" in Polish,
    never the raw English word "cufflink".

    The bug in pz_rows.json (pl_desc='cufflink ze złota...') was produced by
    an older processor path. The current customs_description_engine already
    normalises CUFFLINK → CUFFLINKS for the ITEM_TYPE_PL lookup and produces
    the correct Polish. These tests confirm the current behavior.
    """

    def test_cufflink_singular_in_item_type_pl(self):
        """customs_description_engine ITEM_TYPE_PL[CUFFLINK] → Polish, not English."""
        import customs_description_engine as cde
        # Both singular and plural must map to Polish
        assert cde.ITEM_TYPE_PL.get("CUFFLINK") == "Spinki do mankietów"
        assert cde.ITEM_TYPE_PL.get("CUFFLINKS") == "Spinki do mankietów"

    def test_normalize_cufflink_produces_polish(self):
        """normalize_item_description with CUFFLINK item_type returns Polish item_type_pl."""
        import customs_description_engine as cde
        result = cde.normalize_item_description(
            "14KT Gold Stud Jewel CUFFLINK",
            item_type="CUFFLINK",
            hsn_from_invoice="",
        )
        item_type_pl = result["item_type_pl"]
        # Must be Polish — not the English word
        assert item_type_pl == "Spinki do mankietów", (
            f"Expected 'Spinki do mankietów', got {item_type_pl!r}"
        )
        assert "cufflink" not in item_type_pl.lower(), (
            f"English 'cufflink' must not appear in item_type_pl: {item_type_pl!r}"
        )

    def test_normalize_cufflinks_plural_produces_polish(self):
        """normalize_item_description with CUFFLINKS plural also returns Polish."""
        import customs_description_engine as cde
        result = cde.normalize_item_description(
            "14KT Gold Jewel CUFFLINKS",
            item_type="CUFFLINKS",
            hsn_from_invoice="",
        )
        assert result["item_type_pl"] == "Spinki do mankietów"

    def test_cufflink_confidence_via_engine(self):
        """CUFFLINK identity resolves to CUFFLINKS in item_type (normalised)."""
        identity = resolve_product_identity(
            "EJL/26-27/200-13",
            item_type="CUFFLINK",
            karat="14KT",
            description_pl="Spinki do mankietów ze złota próby 585",
            description_en="14KT Gold Jewel CUFFLINKS",
        )
        assert identity.item_type == "CUFFLINKS"
        assert "RING" not in identity.item_type


# ══════════════════════════════════════════════════════════════════════════════
# 2 + 3. EJL product_code parsing
# ══════════════════════════════════════════════════════════════════════════════

class TestEJLProductCodeParsing:

    def test_full_ejl_code(self):
        """EJL/26-27/148-1 parses to all expected fields."""
        parsed = parse_product_code("EJL/26-27/148-1")
        assert parsed.supplier_prefix == "EJL"
        assert parsed.invoice_no == "EJL/26-27/148"
        assert parsed.line_position == 1
        assert parsed.is_globally_unique is True
        assert parsed.requires_manual_code is False

    def test_ejl_line_position_4(self):
        """High line_position parses correctly."""
        parsed = parse_product_code("EJL/26-27/149-4")
        assert parsed.line_position == 4
        assert parsed.invoice_no == "EJL/26-27/149"

    def test_ejl_fiscal_year_25_26(self):
        """Previous fiscal year parses correctly."""
        parsed = parse_product_code("EJL/25-26/1196-1")
        assert parsed.supplier_prefix == "EJL"
        assert parsed.invoice_no == "EJL/25-26/1196"
        assert parsed.line_position == 1

    def test_ejl_short_code_no_line_suffix(self):
        """EJL/26-27/100 (no -N) parses with line_position=0."""
        parsed = parse_product_code("EJL/26-27/100")
        assert parsed.supplier_prefix == "EJL"
        assert parsed.invoice_no == "EJL/26-27/100"
        assert parsed.line_position == 0
        assert parsed.is_globally_unique is True

    def test_ejl_globally_unique(self):
        """All EJL codes are globally unique."""
        for pc in ("EJL/26-27/148-1", "EJL/25-26/999-10", "EJL/26-27/100"):
            assert parse_product_code(pc).is_globally_unique is True

    def test_ejl_space_variant_before_dash(self):
        """EJL/26-27/100 -1 (space before dash) parses as EJL, not UNKNOWN."""
        parsed = parse_product_code("EJL/26-27/100 -1")
        assert parsed.supplier_prefix == "EJL"
        assert parsed.is_globally_unique is True
        assert parsed.line_position == 1
        assert parsed.invoice_no == "EJL/26-27/100"


# ══════════════════════════════════════════════════════════════════════════════
# 4. 417 Global non-global-uniqueness
# ══════════════════════════════════════════════════════════════════════════════

class Test417GlobalParsing:

    def test_417_global_not_unique(self):
        """417 Global Invoice-1 is not globally unique."""
        parsed = parse_product_code("417 Global Invoice-1")
        assert parsed.supplier_prefix == "417G"
        assert parsed.is_globally_unique is False
        assert parsed.requires_manual_code is True

    def test_417_global_line_position(self):
        """417 Global Invoice-13 extracts line_position=13."""
        parsed = parse_product_code("417 Global Invoice-13")
        assert parsed.line_position == 13

    def test_417_global_invoice_no(self):
        """invoice_no for 417G is the generic sentinel."""
        parsed = parse_product_code("417 Global Invoice-5")
        assert parsed.invoice_no == "417 Global Invoice"

    def test_417g_identity_always_low(self):
        """417G identity is LOW confidence regardless of other fields."""
        identity = resolve_product_identity(
            "417 Global Invoice-1",
            item_type="PENDANT",
            karat="14KT",
            metal_color="Y",
            quality_string="G-VS LAB",
            description_pl="Wisiorek ze złota próby 585 z diamentami laboratoryjnymi",
            description_en="14KT Gold LGD Pendant",
        )
        assert identity.confidence == "LOW"
        assert identity.wfirma_eligible is False
        assert identity.requires_manual_code is True

    def test_417g_identity_not_wfirma_eligible(self):
        """417G is never wFirma eligible even with perfect descriptions."""
        identity = resolve_product_identity(
            "417 Global Invoice-3",
            item_type="RING",
            karat="18KT",
            metal_color="W",
            stone_type="DIAMOND",
            description_pl="Pierścionek ze złota próby 750 z diamentami",
        )
        assert identity.wfirma_eligible is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. Unknown product_code format
# ══════════════════════════════════════════════════════════════════════════════

def test_unknown_format_flagged():
    """Unrecognised product_code gets UNKNOWN prefix and requires_manual_code."""
    parsed = parse_product_code("SOME-RANDOM-CODE")
    assert parsed.supplier_prefix == "UNKNOWN"
    assert parsed.is_globally_unique is False
    assert parsed.requires_manual_code is True


# ══════════════════════════════════════════════════════════════════════════════
# 6 + 7. Generic description guard
# ══════════════════════════════════════════════════════════════════════════════

class TestGenericDescriptionGuard:

    @pytest.mark.parametrize("desc", [
        "Biżuteria złota",
        "Biżuteria srebrna",
        "Biżuteria",
        "Wyrób jubilerski",
        "Wyrób",
        "Towar",
        "",
        "   ",
        # Case-insensitive check
        "BIŻUTERIA ZŁOTA",
        "biżuteria",
    ])
    def test_generic_descriptions_blocked(self, desc):
        """Known generic fallbacks are detected."""
        assert is_generic_description(desc) is True, (
            f"Expected is_generic_description({desc!r}) == True"
        )

    @pytest.mark.parametrize("desc", [
        "Pierścionek ze złota próby 585 z diamentami",
        "Bransoletka z brylantem laboratoryjnym ze złota próby 585",
        "Kolczyki ze srebra próby 925",
        "Wisiorek ze złota próby 750 z szafirami",
        "Spinki do mankietów ze złota próby 585",
    ])
    def test_specific_descriptions_pass(self, desc):
        """Specific Polish descriptions are not flagged as generic."""
        assert is_generic_description(desc) is False, (
            f"Expected is_generic_description({desc!r}) == False"
        )

    def test_forbidden_product_code_keys_not_in_generic_set(self):
        """FORBIDDEN_PRODUCT_CODE_KEYS covers at least the known 4 stubs."""
        for key in ("RING", "PENDANT", "BRACELET", "EARRINGS"):
            assert key in FORBIDDEN_PRODUCT_CODE_KEYS


# ══════════════════════════════════════════════════════════════════════════════
# 8 + 9. description_bilingual format
# ══════════════════════════════════════════════════════════════════════════════

class TestDescriptionBilingual:

    def test_polish_first_slash_english(self):
        """Bilingual is always Polish / English, never reversed."""
        result = compose_bilingual(
            "Pierścionek ze złota próby 585",
            "14KT Gold Diamond RING",
        )
        assert result == "Pierścionek ze złota próby 585 / 14KT Gold Diamond RING"
        # Polish must come before slash
        slash_pos = result.index(" / ")
        polish_end = slash_pos
        # First word is Polish
        assert result[:6] == "Pierśc"

    def test_no_reversed_bilingual(self):
        """English-first composition must never be produced."""
        result = compose_bilingual("Polish text", "English text")
        assert result.startswith("Polish text"), (
            f"Polish must be first in bilingual: {result!r}"
        )
        assert "English text / Polish text" not in result

    def test_polish_only_when_english_empty(self):
        """Empty English side returns Polish-only (no trailing slash)."""
        result = compose_bilingual("Pierścionek ze złota", "")
        assert result == "Pierścionek ze złota"
        assert "/" not in result

    def test_english_only_when_polish_empty(self):
        """Empty Polish side returns English-only (no leading slash)."""
        result = compose_bilingual("", "14KT Gold RING")
        assert result == "14KT Gold RING"

    def test_both_empty_returns_empty(self):
        assert compose_bilingual("", "") == ""

    def test_resolve_produces_bilingual(self):
        """resolve_product_identity populates description_bilingual correctly."""
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            description_pl="Bransoletka ze złota próby 375",
            description_en="9KT Gold BRACELET",
        )
        assert identity.description_bilingual == (
            "Bransoletka ze złota próby 375 / 9KT Gold BRACELET"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. customs_description_pl Polish-only
# ══════════════════════════════════════════════════════════════════════════════

def test_customs_description_pl_polish_only():
    """
    customs_description_pl must be Polish only — no English words like
    'bracelet', 'ring', 'gold', 'diamond'.

    We verify via customs_description_engine.normalize_item_description
    that the polish_customs_description output contains no English item words.
    """
    import customs_description_engine as cde

    for desc_en, item_type in (
        ("14KT Gold Diamond BRACELET", "BRACELET"),
        ("18KT Gold LGD RING",          "RING"),
        ("14KT Gold EARRINGS",           "EARRINGS"),
    ):
        result = cde.normalize_item_description(desc_en, item_type=item_type)
        pl_customs = result["polish_customs_description"]

        # Must not contain English item-type words (the raw English nouns)
        for forbidden in ("bracelet", "ring", "earring", "pendant", "necklace"):
            assert forbidden not in pl_customs.lower(), (
                f"English word '{forbidden}' found in polish_customs_description: "
                f"{pl_customs!r} (from desc_en={desc_en!r})"
            )
        # Must contain Polish
        polish_keywords = [
            "bransoletka", "pierścionek", "kolczyki", "wisiorek",
            "naszyjnik", "złota", "próby", "srebra",
        ]
        found_polish = any(kw in pl_customs.lower() for kw in polish_keywords)
        assert found_polish, (
            f"No Polish keywords found in polish_customs_description: {pl_customs!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 11–14. Confidence model
# ══════════════════════════════════════════════════════════════════════════════

class TestConfidenceModel:

    def test_high_confidence_all_components(self):
        """HIGH: item_type + karat + metal_color + stone_type + specific desc."""
        c = assign_confidence(
            item_type="BRACELET",
            karat="14KT",
            metal_color="W",
            stone_type="LAB_DIAMOND",
            description_pl="Bransoletka ze złota próby 585 z diamentami laboratoryjnymi",
        )
        assert c == "HIGH"

    def test_medium_confidence_no_color_or_stone(self):
        """MEDIUM: item_type + karat + specific desc, but no color/stone."""
        c = assign_confidence(
            item_type="BRACELET",
            karat="14KT",
            metal_color="",
            stone_type="",
            description_pl="Bransoletka ze złota próby 585",
        )
        assert c == "MEDIUM"

    def test_low_confidence_missing_item_type(self):
        """LOW: item_type is absent."""
        c = assign_confidence(
            item_type="",
            karat="14KT",
            description_pl="Pierścionek ze złota",
        )
        assert c == "LOW"

    def test_low_confidence_unknown_item_type(self):
        """LOW: item_type 'ITEM' is not in CANONICAL_ITEM_TYPES."""
        c = assign_confidence(
            item_type="ITEM",
            karat="14KT",
            description_pl="Pierścionek ze złota",
        )
        assert c == "LOW"

    def test_low_confidence_generic_description(self):
        """LOW: description_pl is a known generic fallback."""
        c = assign_confidence(
            item_type="RING",
            karat="14KT",
            metal_color="Y",
            stone_type="DIAMOND",
            description_pl="Biżuteria złota",
        )
        assert c == "LOW"

    def test_low_confidence_missing_karat(self):
        """LOW: karat is absent."""
        c = assign_confidence(
            item_type="RING",
            karat="",
            description_pl="Pierścionek ze złota próby 585",
        )
        assert c == "LOW"

    def test_high_with_ejl_identity(self):
        """Full resolve on EJL code with all fields → HIGH + wfirma_eligible."""
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="BRACELET",
            karat="09KT",
            metal_color="W",
            quality_string="F-VS LAB",
            description_pl="Bransoletka ze złota próby 375 z diamentami laboratoryjnymi",
            description_en="09KT White Gold Lab Diamond BRACELET",
            hs_code="71131911",
        )
        assert identity.confidence == "HIGH"
        assert identity.wfirma_eligible is True

    def test_medium_with_ejl_identity(self):
        """EJL code with item_type + karat + desc but no color → MEDIUM."""
        identity = resolve_product_identity(
            "EJL/26-27/149-2",
            item_type="RING",
            karat="14KT",
            description_pl="Pierścionek ze złota próby 585 z diamentami",
            description_en="14KT Gold Diamond RING",
        )
        assert identity.confidence == "MEDIUM"
        assert identity.wfirma_eligible is True


# ══════════════════════════════════════════════════════════════════════════════
# 16. Forbidden product_code keys
# ══════════════════════════════════════════════════════════════════════════════

class TestForbiddenProductCodeKeys:

    def test_ring_forbidden(self):
        assert "RING" in FORBIDDEN_PRODUCT_CODE_KEYS

    def test_pendant_forbidden(self):
        assert "PENDANT" in FORBIDDEN_PRODUCT_CODE_KEYS

    def test_bracelet_forbidden(self):
        assert "BRACELET" in FORBIDDEN_PRODUCT_CODE_KEYS

    def test_earrings_forbidden(self):
        assert "EARRINGS" in FORBIDDEN_PRODUCT_CODE_KEYS

    def test_ejl_code_not_forbidden(self):
        """Real EJL codes must not appear in the forbidden set."""
        assert "EJL/26-27/148-1" not in FORBIDDEN_PRODUCT_CODE_KEYS

    def test_forbidden_keys_are_item_type_names(self):
        """Forbidden keys are all uppercase item type strings."""
        for key in FORBIDDEN_PRODUCT_CODE_KEYS:
            assert key == key.upper(), f"Key not uppercase: {key!r}"
            assert "/" not in key, f"Key contains slash (should not be a product code): {key!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 17. CUFFLINK normalised to CUFFLINKS in identity
# ══════════════════════════════════════════════════════════════════════════════

def test_cufflink_normalised_in_resolve():
    """resolve_product_identity normalises CUFFLINK → CUFFLINKS in item_type."""
    identity = resolve_product_identity(
        "EJL/26-27/200-13",
        item_type="CUFFLINK",
        karat="14KT",
        description_pl="Spinki do mankietów ze złota próby 585",
        description_en="14KT Gold Jewel CUFFLINKS",
    )
    assert identity.item_type == "CUFFLINKS"


# ══════════════════════════════════════════════════════════════════════════════
# 18 + 19 + 20. Quality string parser
# ══════════════════════════════════════════════════════════════════════════════

class TestQualityStringParser:

    def test_simple_lab_grade(self):
        """'F-VS LAB' → lab_grown=True, primary='F-VS'."""
        qc = parse_quality_string("F-VS LAB")
        assert qc.lab_grown is True
        assert qc.diamond_primary == "F-VS"
        assert qc.diamond_secondary == ""
        assert qc.named_stones == []
        assert qc.is_compound is False

    def test_natural_grade(self):
        """'GH-SI' → natural diamond, primary='GH-SI'."""
        qc = parse_quality_string("GH-SI")
        assert qc.lab_grown is False
        assert qc.diamond_primary == "GH-SI"

    def test_compound_two_lab_grades(self):
        """'G-VS LAB,E-VVS LAB' → compound, two diamond segs."""
        qc = parse_quality_string("G-VS LAB,E-VVS LAB")
        assert qc.is_compound is True
        assert qc.lab_grown is True
        assert qc.diamond_primary == "G-VS"
        assert qc.diamond_secondary == "E-VVS"

    def test_lab_diamond_plus_named_stone(self):
        """'F-VS LAB,EMERALD' → lab=True, named_stone=Emerald."""
        qc = parse_quality_string("F-VS LAB,EMERALD")
        assert qc.lab_grown is True
        assert "Emerald" in qc.named_stones

    def test_natural_diamond_plus_multiple_stones(self):
        """'G-VS,Blue Sapphire,Amethyst' → diamond + 2 named stones."""
        qc = parse_quality_string("G-VS,Blue Sapphire,Amethyst")
        assert qc.diamond_primary == "G-VS"
        assert "Blue Sapphire" in qc.named_stones
        assert "Amethyst" in qc.named_stones
        assert qc.lab_grown is False

    def test_empty_string(self):
        """Empty string → all defaults."""
        qc = parse_quality_string("")
        assert qc.diamond_primary == ""
        assert qc.lab_grown is False
        assert qc.named_stones == []
        assert qc.is_compound is False

    def test_stone_derived_from_quality_string(self):
        """resolve_product_identity derives stone_type from quality_string."""
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="BRACELET",
            karat="14KT",
            quality_string="F-VS LAB",
            description_pl="Bransoletka ze złota próby 585 z diamentami laboratoryjnymi",
        )
        assert identity.stone_type == "LAB_DIAMOND"

    def test_named_stone_derived_from_quality_string(self):
        """Named stone in quality_string populates stone_type."""
        identity = resolve_product_identity(
            "EJL/26-27/149-1",
            item_type="RING",
            karat="18KT",
            quality_string="G-VS,Blue Sapphire",
            description_pl="Pierścionek ze złota próby 750 z szafirami",
        )
        assert identity.stone_type == "BLUE SAPPHIRE"


# ══════════════════════════════════════════════════════════════════════════════
# 21. Dry-run backfill
# ══════════════════════════════════════════════════════════════════════════════

class TestDryRunBackfill:
    """
    Tests the scan_outputs function from backfill_product_identity_dryrun.py.
    Uses a temporary directory with synthetic pz_rows.json files.
    No writes to any real DB.
    """

    def _write_batch(self, tmp: Path, batch_name: str, rows: list) -> Path:
        d = tmp / batch_name
        d.mkdir()
        (d / "pz_rows.json").write_text(
            __import__("json").dumps(rows), encoding="utf-8"
        )
        return d

    def test_scan_counts_ejl_and_417g(self, tmp_path):
        """scan_outputs counts EJL and 417G codes correctly."""
        from scripts.backfill_product_identity_dryrun import scan_outputs

        self._write_batch(tmp_path, "SHIPMENT_AAA", [
            {"product_code": "EJL/26-27/148-1", "item_type": "BRACELET",
             "description_en": "14KT Gold BRACELET",
             "pl_desc": "Bransoletka ze złota próby 585"},
            {"product_code": "EJL/26-27/148-2", "item_type": "RING",
             "description_en": "14KT Gold RING",
             "pl_desc": "Pierścionek ze złota próby 585"},
        ])
        self._write_batch(tmp_path, "SHIPMENT_BBB", [
            {"product_code": "417 Global Invoice-1", "item_type": "PENDANT",
             "description_en": "9KT Gold PENDANT",
             "pl_desc": "Wisiorek ze złota próby 375"},
        ])

        summary, rows = scan_outputs(tmp_path, verbose=False)

        assert summary["batches_with_pz_rows"] == 2
        assert summary["total_rows"] == 3
        assert summary["ejl_codes"] == 2
        assert summary["g417_codes"] == 1
        assert summary["dry_run"] is True

    def test_scan_generic_blocked(self, tmp_path):
        """scan_outputs detects generic descriptions."""
        from scripts.backfill_product_identity_dryrun import scan_outputs

        self._write_batch(tmp_path, "SHIPMENT_CCC", [
            {"product_code": "417 Global Invoice-2", "item_type": "ITEM",
             "description_en": "Gold Jewellery",
             "pl_desc": "Biżuteria złota"},
        ])

        summary, _ = scan_outputs(tmp_path, verbose=False)
        assert summary["generic_blocked"] == 1

    def test_scan_no_writes_to_real_db(self, tmp_path):
        """scan_outputs must not create any DB files."""
        from scripts.backfill_product_identity_dryrun import scan_outputs

        self._write_batch(tmp_path, "SHIPMENT_DDD", [
            {"product_code": "EJL/26-27/999-1", "item_type": "RING",
             "description_en": "14KT Gold RING",
             "pl_desc": "Pierścionek ze złota próby 585"},
        ])

        db_files_before = list(tmp_path.glob("**/*.db"))
        scan_outputs(tmp_path, verbose=False)
        db_files_after = list(tmp_path.glob("**/*.db"))

        assert db_files_before == db_files_after, (
            "scan_outputs must not create any .db files (dry-run)"
        )

    def test_scan_empty_batch_skipped(self, tmp_path):
        """Batch folder without pz_rows.json is skipped gracefully."""
        from scripts.backfill_product_identity_dryrun import scan_outputs

        (tmp_path / "SHIPMENT_EMPTY").mkdir()  # no pz_rows.json

        summary, _ = scan_outputs(tmp_path, verbose=False)
        assert summary["batches_scanned"] == 1
        assert summary["batches_with_pz_rows"] == 0
        assert summary["total_rows"] == 0

    def test_scan_high_medium_low_counts(self, tmp_path):
        """
        scan_outputs distributes HIGH/MEDIUM/LOW counts.

        pz_rows.json fields: product_code, item_type, description_en, pl_desc.
        Karat is NOT in pz_rows — it comes from packing_lines.  Without karat,
        assign_confidence returns LOW for all rows at this scanning stage.
        All rows are therefore expected to be LOW from a pz_rows-only scan.
        """
        from scripts.backfill_product_identity_dryrun import scan_outputs

        self._write_batch(tmp_path, "SHIPMENT_MIX", [
            # EJL with specific desc but no karat → LOW (karat missing)
            {"product_code": "EJL/26-27/100-1", "item_type": "RING",
             "description_en": "14KT Gold Diamond RING",
             "pl_desc": "Pierścionek ze złota próby 585 z diamentami"},
            # 417G with generic desc → LOW (417G + generic)
            {"product_code": "417 Global Invoice-5", "item_type": "ITEM",
             "description_en": "Gold Jewellery",
             "pl_desc": "Biżuteria złota"},
        ])

        summary, _ = scan_outputs(tmp_path, verbose=False)

        # Both rows are LOW at pz_rows-only scan stage (karat absent)
        assert summary["confidence_low"] == 2
        assert summary["confidence_high"] + summary["confidence_medium"] == 0

        # Generic block only applies to the 417G row with "Biżuteria złota"
        assert summary["generic_blocked"] == 1

        # Counts add up
        assert summary["total_rows"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# 22–24. wfirma_eligible logic
# ══════════════════════════════════════════════════════════════════════════════

class TestWfirmaEligibility:

    def test_high_ejl_eligible(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="BRACELET",
            karat="09KT",
            metal_color="W",
            quality_string="F-VS LAB",
            description_pl="Bransoletka ze złota próby 375 z diamentami lab",
            description_en="09KT Gold Lab Diamond BRACELET",
        )
        assert identity.wfirma_eligible is True

    def test_low_not_eligible(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="ITEM",    # unknown type → LOW
            karat="",
            description_pl="Biżuteria złota",
        )
        assert identity.wfirma_eligible is False

    def test_417g_not_eligible_even_with_perfect_data(self):
        identity = resolve_product_identity(
            "417 Global Invoice-1",
            item_type="RING",
            karat="14KT",
            metal_color="Y",
            stone_type="DIAMOND",
            description_pl="Pierścionek ze złota próby 585 z diamentami",
            description_en="14KT Gold Diamond RING",
        )
        assert identity.wfirma_eligible is False

    def test_generic_description_not_eligible(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="RING",
            karat="14KT",
            metal_color="Y",
            description_pl="Biżuteria złota",   # generic
        )
        assert identity.wfirma_eligible is False


# ══════════════════════════════════════════════════════════════════════════════
# 25. missing_fields list
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingFields:

    def test_all_fields_present_minimal_missing(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="BRACELET",
            karat="14KT",
            metal_color="W",
            quality_string="F-VS LAB",
            description_pl="Bransoletka ze złota próby 585 z diamentami",
            description_en="14KT Gold BRACELET",
            hs_code="71131911",
        )
        # metal_color and quality_string are provided, so those shouldn't be missing
        assert "item_type" not in identity.missing_fields
        assert "karat" not in identity.missing_fields
        assert "description_pl" not in identity.missing_fields

    def test_missing_karat_flagged(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="RING",
            karat="",
        )
        assert "karat" in identity.missing_fields

    def test_missing_item_type_flagged(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="",
            karat="14KT",
        )
        assert "item_type" in identity.missing_fields

    def test_generic_description_flagged_as_missing(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            item_type="RING",
            karat="14KT",
            description_pl="Biżuteria złota",
        )
        assert "description_pl" in identity.missing_fields

    def test_specific_description_not_missing(self):
        identity = resolve_product_identity(
            "EJL/26-27/148-1",
            description_pl="Bransoletka ze złota próby 585",
        )
        assert "description_pl" not in identity.missing_fields

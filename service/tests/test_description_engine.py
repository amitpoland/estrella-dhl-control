"""
test_description_engine.py — Single-source-of-truth product description.

Required coverage:
  1. creates description block for new product_code
  2. second call returns persisted block (byte-identical, no regen)
  3. same item_type but different product_code creates separate rows
  4. unknown item_type falls back to default translation, not error
  5. description_block contains all 3 bilingual sections
  6. no duplicate rows for repeated calls
  7. persisted manual override is not overwritten by default generator
"""
from __future__ import annotations

import sqlite3

import pytest

from app.services import document_db as ddb
from app.services import description_engine as deng


@pytest.fixture()
def db(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


# ── 1. First call generates + persists ──────────────────────────────────────

def test_creates_block_for_new_product_code(db):
    row = deng.get_description_block("EJL/26-27/100-1", "RING")
    assert row["product_code"]    == "EJL/26-27/100-1"
    assert row["item_type"]       == "RING"
    assert row["source"]          == "auto"
    assert row["name_pl"]         == "Pierścionek"
    assert "pierścionek" in row["description_pl"].lower()
    assert row["description_block"]
    assert row["created_at"]
    assert row["updated_at"]


# ── 2. Second call returns persisted block, no regeneration ─────────────────

def test_second_call_returns_persisted_block(db):
    first  = deng.get_description_block("EJL/26-27/100-2", "RING")
    second = deng.get_description_block("EJL/26-27/100-2", "RING")
    # Byte-identical (timestamps included): proves no overwrite.
    assert first == second


def test_second_call_with_different_item_type_does_not_overwrite(db):
    """
    Once a code is locked, even calling with a different item_type does
    not change the persisted block — the rule is one_code = one_block.
    """
    first  = deng.get_description_block("EJL/26-27/100-3", "RING")
    second = deng.get_description_block("EJL/26-27/100-3", "EARRINGS")
    assert second["item_type"] == "RING"  # original wins
    assert second["name_pl"]   == first["name_pl"]
    assert second["description_block"] == first["description_block"]


# ── 3. Same item_type, different product_code → separate rows ───────────────

def test_same_item_type_different_codes_separate_rows(db):
    a = deng.get_description_block("EJL/26-27/100-4", "RING")
    b = deng.get_description_block("EJL/26-27/100-5", "RING")
    assert a["product_code"] != b["product_code"]
    # Default translation is per-type, so the body is identical for two
    # rings — that's documented behaviour. The store is per-code, though.
    assert a["description_pl"] == b["description_pl"]
    assert a["item_type"]      == b["item_type"]


# ── 4. Unknown item_type falls back to DEFAULT_TRANSLATION ──────────────────

def test_unknown_item_type_uses_default(db):
    row = deng.get_description_block("EJL/26-27/200-1", "BOGUS_TYPE")
    # Resolves through DEFAULT_TRANSLATION → name_pl = "Biżuteria"
    assert row["name_pl"] == "Biżuteria"
    # Stored item_type carries the normalised input — clear breadcrumb
    assert row["item_type"] == "BOGUS_TYPE"


def test_empty_item_type_uses_default(db):
    row = deng.get_description_block("EJL/26-27/200-2", "")
    assert row["name_pl"] == "Biżuteria"


# ── 5. description_block contains all 3 bilingual sections ──────────────────

def test_description_block_has_three_bilingual_sections(db):
    row = deng.get_description_block("EJL/26-27/300-1", "PENDANT")
    body = row["description_block"]
    # Polish + English labels per locked format
    assert "Co to za towar"      in body
    assert "What is this"        in body
    assert "Z jakiego materiału" in body
    assert "Material"            in body
    assert "Do czego służy"      in body
    assert "Purpose"             in body
    # Body content present
    assert row["description_pl"] in body
    assert row["material_pl"]    in body
    assert row["purpose_pl"]     in body


# ── 6. No duplicate rows for repeated calls ─────────────────────────────────

def test_no_duplicate_rows_for_repeated_calls(db):
    for _ in range(5):
        deng.get_description_block("EJL/26-27/400-1", "BRACELET")
    with sqlite3.connect(str(db / "documents.db")) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM product_descriptions WHERE product_code=?",
            ("EJL/26-27/400-1",),
        ).fetchone()[0]
    assert n == 1


# ── 7. Manual override is not overwritten by auto generator ─────────────────

def test_manual_override_protected_from_auto_overwrite(db):
    pc = "EJL/26-27/500-1"
    manual = deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "Custom Pierścionek złoty",
        description_pl = "Custom: pierścionek 18kt z brylantem",
        material_pl    = "Złoto 18kt + brylant 0.5ct",
        purpose_pl     = "Ozdoba — pierścionek zaręczynowy",
    )
    assert manual["source"] == "manual"

    # Default generator must NOT clobber the manual block
    after_auto_call = deng.get_description_block(pc, "RING")
    assert after_auto_call["source"]            == "manual"
    assert after_auto_call["name_pl"]           == "Custom Pierścionek złoty"
    assert after_auto_call["description_pl"]    == manual["description_pl"]
    assert after_auto_call["description_block"] == manual["description_block"]


def test_manual_override_can_be_updated_again(db):
    pc = "EJL/26-27/500-2"
    deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "First override",
        description_pl = "first",
        material_pl    = "first",
        purpose_pl     = "first",
    )
    second = deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "Second override",
        description_pl = "second",
        material_pl    = "second",
        purpose_pl     = "second",
    )
    assert second["name_pl"]        == "Second override"
    assert second["description_pl"] == "second"
    assert second["source"]         == "manual"


# ── 8. Empty product_code raises ────────────────────────────────────────────

def test_empty_product_code_raises(db):
    with pytest.raises(ValueError, match="product_code is required"):
        deng.get_description_block("", "RING")
    with pytest.raises(ValueError, match="product_code is required"):
        deng.set_manual_block(
            product_code="", item_type="RING",
            name_pl="x", description_pl="x", material_pl="x", purpose_pl="x",
        )


# ── Polish-first / English-after-slash composed line ────────────────────────

def test_description_line_polish_first_english_after_slash(db):
    row = deng.get_description_block(
        "EJL/26-27/600-1", "RING",
        description_en="Diamond & Colour Stone PT950 Platinum Jewellery RING",
    )
    # Customs-grade Polish derived from the English seed (PT950 platinum
    # jewellery → "Pierścionek z platyny próby 950 z diamentami i kamieniami...")
    assert row["description_pl"].startswith("Pierścionek")
    assert row["description_en"] == \
        "Diamond & Colour Stone PT950 Platinum Jewellery RING"
    # description_line composition: customs Polish / English
    assert row["description_line"].startswith(row["description_pl"])
    assert row["description_line"].endswith(row["description_en"])
    assert " / " in row["description_line"]
    # Generic ITEM_TRANSLATIONS Polish must NOT lead the line
    assert not row["description_line"].startswith("Biżuteria —")
    # And the bilingual block contains the slash-composed line on the
    # "Co to za towar" row, not the Polish-only text.
    assert row["description_line"] in row["description_block"]


def test_description_line_no_english_no_slash(db):
    row = deng.get_description_block("EJL/26-27/600-2", "RING")
    assert row["description_en"]    == ""
    assert row["description_line"]  == row["description_pl"]
    assert " / " not in row["description_line"]


def test_description_en_locked_after_first_write(db):
    """Once written, a later call cannot replace description_en."""
    first  = deng.get_description_block(
        "EJL/26-27/600-3", "RING",
        description_en="ORIGINAL ENGLISH",
    )
    second = deng.get_description_block(
        "EJL/26-27/600-3", "RING",
        description_en="ATTEMPTED OVERWRITE",
    )
    assert second["description_en"] == "ORIGINAL ENGLISH"
    assert second["description_line"].endswith("/ ORIGINAL ENGLISH")


# ── Customs-grade Polish takes priority over ITEM_TRANSLATIONS ─────────────

def test_description_pl_uses_customs_grade_when_english_provided(db):
    """
    When caller supplies description_en, the engine routes the English
    text through customs_description_engine.normalize_item_description
    to derive a customs-grade Polish phrase — not the generic
    'Biżuteria — pierścionek' ITEM_TRANSLATIONS default.
    """
    row = deng.get_description_block(
        "EJL/26-27/CG-1", "RING",
        description_en="Lab Grown Diamond Studded 14KT Gold Jewellery RING",
    )
    # Customs phrase should mention metal+purity+stones
    assert "Pierścionek" in row["description_pl"]
    assert "ze złota" in row["description_pl"]
    assert "próby 585" in row["description_pl"]
    # Must NOT be the generic ITEM_TRANSLATIONS text
    assert "Biżuteria — pierścionek" not in row["description_pl"]
    # And must NOT lead the description_line either
    assert not row["description_line"].startswith("Biżuteria —")


def test_description_line_starts_with_customs_polish(db):
    """description_line = <customs Polish> / <English>"""
    row = deng.get_description_block(
        "EJL/26-27/CG-2", "EARRINGS",
        description_en="Diamond Studded 18KT Gold Jewellery EARRINGS",
    )
    line = row["description_line"]
    # Polish first
    assert line.startswith(row["description_pl"])
    # Slash separator
    assert " / " in line
    # English second
    assert line.endswith(row["description_en"])
    # Specifically: not generic
    assert not line.startswith("Biżuteria")


def test_no_english_falls_back_to_item_translations(db):
    """When description_en is empty, normalise_item_description has no
    seed; engine falls back to ITEM_TRANSLATIONS generic text."""
    row = deng.get_description_block("EJL/26-27/CG-3", "RING")
    # Generic ITEM_TRANSLATIONS Polish — no rich material phrase
    assert row["description_pl"] == "Biżuteria — pierścionek"


def test_caller_supplied_description_pl_overrides_customs_engine(db):
    """If caller passes description_pl explicitly, engine respects it
    and does NOT call the customs normaliser."""
    row = deng.get_description_block(
        "EJL/26-27/CG-4", "RING",
        description_en="Lab Grown Diamond Ring",
        description_pl="CALLER-SUPPLIED POLISH",
    )
    assert row["description_pl"] == "CALLER-SUPPLIED POLISH"


def test_locked_block_protects_customs_grade_too(db):
    """Once written with customs-grade text, subsequent calls return the
    stored row — no regeneration even with a different English seed."""
    first = deng.get_description_block(
        "EJL/26-27/CG-5", "RING",
        description_en="Lab Grown Diamond Studded 14KT Gold Jewellery RING",
    )
    second = deng.get_description_block(
        "EJL/26-27/CG-5", "RING",
        description_en="Different English Description",
    )
    assert second["description_pl"] == first["description_pl"]
    assert second["description_en"] == first["description_en"]


def test_manual_override_still_wins(db):
    """Manual override is never replaced by customs-grade auto."""
    pc = "EJL/26-27/CG-6"
    deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "Manual Pierścionek",
        description_pl = "MANUAL_POLISH_OVERRIDE",
        material_pl    = "manual material",
        purpose_pl     = "manual purpose",
        description_en = "MANUAL_ENGLISH_OVERRIDE",
    )
    after = deng.get_description_block(
        pc, "RING",
        description_en="Lab Grown Diamond Ring",  # would normally trigger customs
    )
    assert after["source"]         == "manual"
    assert after["description_pl"] == "MANUAL_POLISH_OVERRIDE"
    assert after["description_en"] == "MANUAL_ENGLISH_OVERRIDE"


def test_manual_override_carries_english(db):
    pc = "EJL/26-27/600-4"
    row = deng.set_manual_block(
        product_code   = pc,
        item_type      = "RING",
        name_pl        = "Pierścionek z brylantem",
        description_pl = "pierścionek z platyny próby 950 z diamentami i kamieniami",
        material_pl    = "Platyna 950 + diament + kamienie kolorowe",
        purpose_pl     = "Ozdoba — pierścionek",
        description_en = "Diamond & Colour Stone PT950 Platinum Jewellery RING",
    )
    assert row["source"] == "manual"
    assert row["description_line"] == (
        "pierścionek z platyny próby 950 z diamentami i kamieniami / "
        "Diamond & Colour Stone PT950 Platinum Jewellery RING"
    )

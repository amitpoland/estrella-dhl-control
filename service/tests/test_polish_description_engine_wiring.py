"""
test_polish_description_engine_wiring.py — PZ description PDF reads from
the description_engine source of truth.

Asserts:
  1. Generated PDF still contains the bilingual three-section block.
  2. The "Co to za towar" content line is Polish-first / English-after-slash
     when an English description has been written.
  3. A manual override for the item_type is reflected in the PDF text.
  4. Generating the PDF twice does not duplicate product_descriptions rows.
  5. Unknown item_type uses the safe default fallback (no crash).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Project root holds polish_description_generator.py — make it importable.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services import document_db as ddb
from app.services import description_engine as deng


@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _make_batch(item_type: str, qty: int = 1) -> dict:
    return {
        "rows": [
            {"item_type": item_type, "qty": qty},
        ],
    }


def _generate(batch: dict, output_dir: Path) -> dict:
    import polish_description_generator as pdg
    return pdg.generate_polish_description(batch, awb="TEST-AWB",
                                            output_dir=str(output_dir))


def _read_pdf_text(pdf_path: str) -> str:
    """Cheap text scrape — pdftotext-equivalent without an extra dep."""
    try:
        from pypdf import PdfReader  # modern
        reader = PdfReader(pdf_path)
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        try:
            from PyPDF2 import PdfReader  # legacy fallback
            reader = PdfReader(pdf_path)
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            # Fallback: return the raw bytes; assertions just check substrings.
            return Path(pdf_path).read_bytes().decode("latin-1", errors="ignore")


# ── 1. PDF still has the three bilingual sections ──────────────────────────

def test_pdf_contains_three_bilingual_sections(storage):
    res = _generate(_make_batch("RING"), storage)
    assert res["generated"] is True
    text = _read_pdf_text(res["output_path"])
    # Section labels (the generator prints these regardless of engine wiring)
    assert "Co to za towar" in text
    assert "Z jakiego materia" in text
    assert "Do czego s" in text


# ── 2. Polish-first / English-after-slash composed content ──────────────────

def test_description_content_uses_polish_then_slash_then_english(storage):
    # Pre-seed an English description for RING via the engine.
    deng.get_description_block(
        "RING", "RING",
        description_en="Diamond & Colour Stone PT950 Platinum Jewellery RING",
    )
    res = _generate(_make_batch("RING"), storage)
    text = _read_pdf_text(res["output_path"])
    # Polish-first half (name_pl="Pierścionek", description_pl uses Polish noun
    # phrase). Look for the canonical Polish lemma rather than a 2-char prefix:
    # the engine produces "Pierścionek z platyny próby 950 wysadzany diamentami
    # i kamieniami szlachetnymi. Biżuteria do noszenia." which the generator
    # surfaces in the "Pozycja" heading and in the "Co to za towar" content line.
    assert "Pierścionek" in text
    assert "biżuteria" in text  # appears in description body
    # English half
    assert "Diamond & Colour Stone" in text
    # Slash separator between Polish and English on the composed line
    assert "/" in text
    # Same row in DB carries the composed line in Polish-first / slash /
    # English-after-slash form. The Polish half is the engine's full
    # description_pl phrase, not a compact "Biżuteria — pierścionek" form.
    # Grammar upgrade (Phase 1): karat-expanded genitive, setting verb,
    # sentence break. PT950 is not karat-based so genitive stays as-is,
    # but setting verb (wysadzany) and sentence break now apply.
    row = ddb.get_product_description("RING")
    assert row["description_line"] == (
        "Pierścionek z platyny próby 950 wysadzany diamentami i kamieniami szlachetnymi. "
        "Biżuteria do noszenia. / "
        "Diamond & Colour Stone PT950 Platinum Jewellery RING"
    )


# ── 3. Manual override is reflected in the PDF ──────────────────────────────

def test_manual_override_reflected_in_pdf(storage):
    deng.set_manual_block(
        product_code   = "RING",
        item_type      = "RING",
        name_pl        = "Pierścionek z brylantem",
        description_pl = "pierścionek z platyny próby 950 z diamentami",
        material_pl    = "Platyna 950 + diament",
        purpose_pl     = "Ozdoba — pierścionek zaręczynowy",
        description_en = "PT950 Diamond Engagement Ring",
    )
    res = _generate(_make_batch("RING"), storage)
    text = _read_pdf_text(res["output_path"])
    assert "PT950 Diamond Engagement Ring" in text
    assert "platyny" in text
    # Type-default text must NOT appear (override fully replaced it)
    assert "Biżuteria — pierścionek" not in text


# ── 4. No duplicate product_descriptions rows on repeated generation ────────

def test_repeated_generation_no_duplicate_rows(storage):
    for _ in range(3):
        _generate(_make_batch("RING"), storage)
    with sqlite3.connect(str(storage / "documents.db")) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM product_descriptions WHERE product_code=?",
            ("RING",),
        ).fetchone()[0]
    assert n == 1


# ── 5. Unknown item_type → safe fallback (no crash) ─────────────────────────

def test_unknown_item_type_uses_safe_fallback(storage):
    res = _generate(_make_batch("BOGUS_TYPE"), storage)
    assert res["generated"] is True
    text = _read_pdf_text(res["output_path"])
    # Safe-fallback path: when the generator encounters an unknown item_type
    # it persists a Polish-noun fallback ("Wyrób jubilerski" — Polish for
    # "jewellery item") rather than crashing. The fallback shows up both in
    # the rendered PDF and in the persisted product_descriptions row.
    assert "Wyrób jubilerski" in text
    # Persisted under the bogus key. The generator-path fallback writes
    # "Wyrób jubilerski" as name_pl (note: deng.get_description_block called
    # directly returns "Biżuteria"; the generator chooses the descriptive
    # noun for the persisted record).
    row = ddb.get_product_description("BOGUS_TYPE")
    assert row is not None
    assert row["name_pl"] == "Wyrób jubilerski"
    # Sanity: the description_line stays Polish-first / slash / English-after
    assert " / " in row["description_line"]
    assert row["description_line"].startswith("Wyrób jubilerski")


# ── 6. Polish diacritics render correctly — no black-square corruption ──────


def test_no_black_square_in_generated_pdf(storage):
    """Polish diacritics (ś, ż, ą, ę, ł, ć, ń, ó, ź) must render correctly.

    When the PDF generator falls back to Helvetica (e.g. when none of the
    OS-specific font paths in ``polish_description_generator._FONT_PATHS``
    resolve), Polish characters are emitted as ``■`` (U+25A0 BLACK SQUARE).
    This test catches the regression where the font search list was missing
    paths for the current OS — production runs on Windows, so the original
    list (macOS + Linux only) caused every generated polish-description PDF
    to ship with ``■`` instead of ``ś``/``ż``/``ł``/``ć``/``ń``/``ó``/``ź``.

    The fix adds ``C:/Windows/Fonts/arial.ttf`` (and three other Windows
    Unicode fonts) to ``_FONT_PATHS``. This test pins that the rendered PDF
    never contains the U+25A0 fallback glyph and that representative Polish
    words come through intact.
    """
    deng.get_description_block(
        "RING", "RING",
        description_en="Diamond & Colour Stone PT950 Platinum Jewellery RING",
    )
    res = _generate(_make_batch("RING"), storage)
    text = _read_pdf_text(res["output_path"])

    # Hard invariant: U+25A0 must not appear anywhere in the rendered text.
    assert "■" not in text, (
        "Generated PDF contains ■ (U+25A0 BLACK SQUARE) — font fallback "
        "corrupted Polish diacritics. Check polish_description_generator."
        "_FONT_PATHS for the current OS. First 300 chars: "
        + repr(text[:300])
    )

    # Representative Polish diacritic-bearing words must render intact.
    for word in ("Pierścionek", "biżuteria", "materiału", "służy", "Ilość"):
        assert word in text, (
            f"Polish word {word!r} missing from generated PDF — likely "
            f"corrupted by font fallback. Inspect _FONT_PATHS resolution. "
            f"First 300 chars: {text[:300]!r}"
        )


# ── 7. pypdf is declared as a real dependency, not just a soft import ──────


def test_pypdf_importable_as_declared_dependency():
    """pypdf is required by this test module (and by the polish-description
    PDF validator path). It MUST be declared in service/requirements.txt so
    that fresh installs and CI environments do not silently degrade tests
    to the latin-1 byte-scrape fallback.
    """
    import importlib
    try:
        pypdf = importlib.import_module("pypdf")
    except ImportError as exc:  # pragma: no cover — guarded by requirements.txt
        pytest.fail(
            "pypdf import failed — must be declared in "
            "service/requirements.txt: " + str(exc)
        )
    assert hasattr(pypdf, "PdfReader"), "pypdf.PdfReader API not available"

    # Source-grep: requirements.txt must declare pypdf so future
    # environments do not silently fall back to the latin-1 byte scrape.
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "pypdf" in req, (
        "pypdf must be declared in service/requirements.txt — present in "
        "site-packages now but the requirement file says otherwise"
    )

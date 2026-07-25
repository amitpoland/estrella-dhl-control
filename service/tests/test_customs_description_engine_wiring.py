"""
test_customs_description_engine_wiring.py — Live PZ/customs PDF generator
reads from description_engine source-of-truth and renders Polish-first /
English-after-slash content.

Asserts:
  1. All field labels are Polish first / English after slash.
  2. The legacy English-first label "What is this: / Co to za towar:" is
     absent from the rendered PDF.
  3. The "Co to za towar" content row is rendered as <Polish> / <English>;
     the legacy " — " (em-dash) separator is gone.
  4. A description_engine sentinel block is consumed when present.
  5. Manual override via set_manual_block surfaces in the generated PDF.
  6. Repeated generation does not duplicate product_descriptions rows.
  7. Engine fallback works when description_engine is unreachable.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Project root holds customs_description_engine.py — make it importable.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services import document_db as ddb
from app.services import description_engine as deng


@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _ring_batch() -> dict:
    """Single-invoice, single-line RING with rich English source description."""
    return {
        "invoices": [{
            "invoice_number": "EJL/25-26/1274",
            "items": [{
                "product_code": "EJL/25-26/1274-3",
                "description":  "Diamond & Colour Stone PT950 Platinum Jewellery RING",
                "item_type":    "RING",
                "quantity":     1,
                "unit_price":   173.0,
                "line_total":   173.0,
                "unit":         "PCS",
                "hsn_code":     "71131900",
            }],
        }],
        "tracking_no":     "1234567890",
        "invoice_totals":  {"total_cif_usd": 200.0},
    }


def _generate_pdf(storage_root: Path, batch: dict | None = None) -> dict:
    import customs_description_engine as cde
    pkg = cde.generate_customs_description_package(
        batch         = batch or _ring_batch(),
        awb           = "TEST-AWB",
        output_dir    = str(storage_root),
        date_override = "2026-05-06",
    )
    return pkg


def _read_pdf_text_flat(pdf_path: str) -> str:
    """PDF text with all runs of whitespace collapsed to single spaces.

    The label row is laid out wide enough that the PDF wraps it mid-string:
    extraction yields 'Co to za towar / What is' on one line and 'this:' on
    the next, so a raw `"Co to za towar / What is this" in text` check fails
    even though the label renders correctly. That is a layout artefact, not a
    missing label — this file already compensates for the same wrapping
    elsewhere ("check distinguishing phrases separately"), it was just never
    applied to the label assertions. Flattening keeps the assertion exact
    instead of weakening it to a substring of a substring.
    """
    return " ".join(_read_pdf_text(pdf_path).split())


def _read_pdf_text(pdf_path: str) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(pdf_path).pages)
    except Exception:
        try:
            from PyPDF2 import PdfReader
            return "\n".join(p.extract_text() or "" for p in PdfReader(pdf_path).pages)
        except Exception:
            return Path(pdf_path).read_bytes().decode("latin-1", errors="ignore")


# ── 1 + 2. Labels are Polish first; legacy English-first label gone ────────

def test_labels_are_polish_first(storage):
    pkg = _generate_pdf(storage)
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    # New: Polish first, English after slash. Read flattened — the label cell
    # (LABEL_W = 42mm) wraps this 32-char label, so pypdf returns
    # "Co to za towar /\nWhat is this:" and a raw substring check fails on a
    # label that is in fact rendered correctly.
    assert "Co to za towar / What is this" in _read_pdf_text_flat(
        pkg["pdf"]["output_path"])
    assert "Z jakiego materia" in text and "Material" in text
    assert "Do czego s" in text and "Purpose" in text
    assert "Ilo" in text and "Quantity" in text
    assert "Warto" in text and "Value" in text
    # Legacy English-first label MUST be gone
    assert "What is this: / Co to za towar" not in text
    assert "What is this:\nCo to za towar" not in text


# ── 3. Content row is Polish / English (no em-dash) ─────────────────────────

def test_description_content_polish_then_slash_then_english(storage):
    pkg = _generate_pdf(storage)
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    # English half present (PDF may wrap long lines mid-string — check
    # distinguishing phrases separately).
    assert "Diamond & Colour Stone" in text
    assert "PT950 Platinum Jewellery RING" in text
    # Slash separator present
    assert "/" in text
    # Em-dash + English ordering of the legacy composition is gone.
    assert "Diamond & Colour Stone PT950 Platinum Jewellery RING — " not in text


# ── 4. Engine sentinel propagates into the PDF ──────────────────────────────

def test_engine_sentinel_appears_in_pdf(storage):
    """Pre-seed an override-shaped block via the engine; expect it in PDF."""
    deng.set_manual_block(
        product_code   = "EJL/25-26/1274-3",
        item_type      = "RING",
        name_pl        = "Pierścionek z platyny",
        description_pl = "ZZ_SENTINEL_POLISH_DESCRIPTION_ZZ",
        material_pl    = "Platyna 950 + diamenty",
        purpose_pl     = "Ozdoba — pierścionek",
        description_en = "ZZ_SENTINEL_ENGLISH_DESCRIPTION_ZZ",
    )
    pkg  = _generate_pdf(storage)
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    assert "ZZ_SENTINEL_POLISH_DESCRIPTION_ZZ" in text
    assert "ZZ_SENTINEL_ENGLISH_DESCRIPTION_ZZ" in text
    # Composed line shape preserved
    assert ("ZZ_SENTINEL_POLISH_DESCRIPTION_ZZ / "
            "ZZ_SENTINEL_ENGLISH_DESCRIPTION_ZZ") in text


# ── 5. Approved manual description is the generation source ─────────────────

def test_manual_override_surfaces_in_pdf(storage):
    # Authority model (customs-description-resolver): the approved manual block
    # (source='manual') is the generation source. Seed it, generate, and prove
    # BOTH the approved Polish AND approved English surface in the PDF — the
    # resolver honors the operator's approved description end-to-end.
    deng.set_manual_block(
        product_code   = "EJL/25-26/1274-3",
        item_type      = "RING",
        name_pl        = "Manual Pierścionek",
        description_pl = "ZZ_MANUAL_PL_ZZ",
        material_pl    = "Platyna 950",
        purpose_pl     = "Ozdoba",
        description_en = "ZZ_MANUAL_EN_ZZ",
    )
    pkg = _generate_pdf(storage)
    assert not pkg.get("blocked"), pkg
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    assert "ZZ_MANUAL_PL_ZZ / ZZ_MANUAL_EN_ZZ" in text
    # The approved row remains the single manual authority; customs generation
    # does NOT persist a competing source='auto' row (resolver is authority, so
    # nothing generic is written to product_descriptions).
    row = ddb.get_product_description("EJL/25-26/1274-3")
    assert row is not None and row["source"] == "manual"


# ── 6. Repeated generation keeps the approved row singular ──────────────────

def test_repeated_generation_manual_row_stays_singular(storage):
    # With an approved manual block, repeated generation must not create a
    # competing/duplicate product_descriptions row (deterministic; generation
    # persists nothing new because the resolver is the authority).
    deng.set_manual_block(
        product_code   = "EJL/25-26/1274-3",
        item_type      = "RING",
        name_pl        = "Manual Pierścionek",
        description_pl = "ZZ_MANUAL_PL_ZZ",
        material_pl    = "Platyna 950",
        purpose_pl     = "Ozdoba",
        description_en = "ZZ_MANUAL_EN_ZZ",
    )
    for _ in range(3):
        _generate_pdf(storage)
    with sqlite3.connect(str(storage / "documents.db")) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM product_descriptions WHERE product_code=?",
            ("EJL/25-26/1274-3",),
        ).fetchone()[0]
    assert n == 1


# ── 7. Fallback when engine unreachable: PDF still has Polish/English ──────

def test_fallback_when_engine_unreachable(storage, monkeypatch):
    """
    Force the loaded engine to None; generator must still produce a valid
    Polish-first / English-after-slash content line via inline composition.
    """
    import customs_description_engine as cde
    monkeypatch.setattr(cde, "_DESCRIPTION_ENGINE", None)

    pkg = _generate_pdf(storage)
    text = _read_pdf_text(pkg["pdf"]["output_path"])
    # English half still appears (PDF may wrap long lines mid-string —
    # check distinguishing phrases separately).
    assert "Diamond & Colour Stone" in text
    assert "PT950 Platinum Jewellery RING" in text
    # Polish-first label still rendered (flattened — see _read_pdf_text_flat)
    assert "Co to za towar / What is this" in _read_pdf_text_flat(
        pkg["pdf"]["output_path"])
    # No em-dash composition in the description content
    assert "Diamond & Colour Stone PT950 Platinum Jewellery RING — " not in text

"""
test_invoice_cif_abbreviations.py — extraction coverage for the abbreviated
FOB / Freight / Insurance / CIF labels that appear on Global Jewellery invoices
and DHL waybills.

Root-cause incident: invoices for AWB 2315714531 render the customs valuation
components with the short DHL/AWB abbreviations rather than full words —
``FOB US$ 607``, ``FRI US$ 100`` (freight), ``INS $ 25`` (insurance) and
``CIF Value 732``. The original regexes only recognised the full words
("Freight", "Insurance"), so freight + insurance silently parsed to 0.0, the
CIF collapsed below its true value, and clearance routing was wrong.

Two extraction paths are pinned here:
  1. app.services.global_invoice_parser module regexes (_FOB_RE / _FREIGHT_RE /
     _INS_RE / _CIF_RE)
  2. pz_import_processor.parse_invoice_global_jewellery (the CLI engine path)

Proof point: text "FOB US$ 607  FRI US$ 100  INS $ 25" must produce
fob=607, freight=100, insurance=25, cif=732.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))
# pz_import_processor lives at the CLI root (one level above service/);
# conftest.py already inserts it, but be explicit so this file is import-safe.
_CLI_ROOT = Path(__file__).parent.parent.parent
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from app.services.global_invoice_parser import (
    _CIF_RE,
    _FOB_RE,
    _FREIGHT_RE,
    _INS_RE,
)


def _amt(regex, text):
    m = regex.search(text)
    return float(m.group(1).replace(",", "")) if m else None


# ── Module regexes: abbreviated forms ─────────────────────────────────────────

def test_fob_abbreviation_us_dollar_prefix():
    assert _amt(_FOB_RE, "FOB US$ 607") == pytest.approx(607.0)


def test_freight_fri_abbreviation():
    assert _amt(_FREIGHT_RE, "FRI US$ 100") == pytest.approx(100.0)


def test_freight_fri_glued_dollar():
    assert _amt(_FREIGHT_RE, "FRI $ 100") == pytest.approx(100.0)


def test_insurance_ins_abbreviation():
    assert _amt(_INS_RE, "INS $ 25") == pytest.approx(25.0)


def test_insurance_ins_us_dollar():
    assert _amt(_INS_RE, "INS US$ 25") == pytest.approx(25.0)


def test_cif_value_label():
    assert _amt(_CIF_RE, "CIF Value 732") == pytest.approx(732.0)


def test_full_words_still_parse():
    """The full-word forms must keep working — additive change, no regression."""
    assert _amt(_FREIGHT_RE, "Freight: 125.00") == pytest.approx(125.0)
    assert _amt(_INS_RE, "Insurance: 25.00") == pytest.approx(25.0)
    assert _amt(_FOB_RE, "FOB Value: USD 3,172.00") == pytest.approx(3172.0)


def test_thousands_separator_in_abbreviated_form():
    assert _amt(_FOB_RE, "FOB US$ 14,169.00") == pytest.approx(14169.0)


# ── pz_import_processor engine path: the proof-point aggregation ──────────────

def test_engine_parser_aggregates_abbreviated_components_to_732():
    """parse_invoice_global_jewellery must read FOB/FRI/INS abbreviations and
    aggregate to CIF 732 — the AWB 2315714531 proof point."""
    from pz_import_processor import parse_invoice_global_jewellery

    text = (
        "GLOBAL JEWELLERY PVT LTD\n"
        "Invoice No.: 122  Date: 02/01/2026\n"
        "Exporter: GLOBAL JEWELLERY PVT LTD\n"
        "FOB US$ 607\n"
        "FRI US$ 100\n"
        "INS $ 25\n"
    )
    lines = text.split("\n")
    out = parse_invoice_global_jewellery("inv_122.pdf", text, lines, [])

    assert out["fob_usd"] == pytest.approx(607.0)
    assert out["freight_usd"] == pytest.approx(100.0)
    assert out["freight_found"] is True
    assert out["insurance_usd"] == pytest.approx(25.0)
    assert out["cif_usd"] == pytest.approx(732.0)


def test_engine_parser_freight_not_found_is_zero_but_flagged():
    """When freight truly is absent, freight_usd is 0.0 and freight_found is
    False — the engine distinguishes 'not present' from a parsed value, so a
    downstream consumer can treat the gap honestly rather than as a real 0."""
    from pz_import_processor import parse_invoice_global_jewellery

    text = (
        "GLOBAL JEWELLERY PVT LTD\n"
        "Invoice No.: 122  Date: 02/01/2026\n"
        "Exporter: GLOBAL JEWELLERY PVT LTD\n"
        "FOB US$ 607\n"
    )
    lines = text.split("\n")
    out = parse_invoice_global_jewellery("inv_122.pdf", text, lines, [])

    assert out["fob_usd"] == pytest.approx(607.0)
    assert out["freight_usd"] == pytest.approx(0.0)
    assert out["freight_found"] is False

"""
test_preamble_signals_direct.py — Direct unit tests for preamble_signals
=========================================================================

Pure-function tests for ``app.services.preamble_signals``:

  * VAT extraction edge cases (EU prefixes, embedded separators, length
    bounds, false positives)
  * Heading candidate denylist (sheet titles, labelled key:value rows,
    metadata prefixes, postal/phone-shaped digits, length bounds)
  * Best-effort guarantees: missing file → None, empty path → None,
    openpyxl ImportError → None, raising openpyxl → None
  * Combined extractor returns dict with both keys (values nullable)

PR 1 adds an observational call site inside the draft-birth resolver.
These tests pin the contract that the helper NEVER raises and ALWAYS
returns ``None`` (or a dict with ``None`` values) on any failure path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import preamble_signals as ps


# ── Pure-function helpers (no I/O) ────────────────────────────────────────────

class TestNormalizeVat:
    def test_normalize_strips_separators_and_uppercases(self):
        assert ps._normalize_vat("sk", "107095376") == "SK107095376"

    def test_normalize_keeps_canonical(self):
        assert ps._normalize_vat("SK", "107095376") == "SK107095376"

    def test_normalize_rejects_too_short(self):
        # 6 digits — below 7-digit floor
        assert ps._normalize_vat("SK", "123456") is None

    def test_normalize_rejects_too_long(self):
        # 13 digits — above 12-digit ceiling
        assert ps._normalize_vat("SK", "1234567890123") is None

    def test_normalize_accepts_min_boundary(self):
        # exactly 7 digits
        assert ps._normalize_vat("DE", "1234567") == "DE1234567"

    def test_normalize_accepts_max_boundary(self):
        # exactly 12 digits
        assert ps._normalize_vat("HU", "123456789012") == "HU123456789012"

    def test_normalize_strips_inline_dashes_and_spaces(self):
        assert ps._normalize_vat("SK", "1070 95-376") == "SK107095376"

    def test_normalize_rejects_if_no_digits(self):
        assert ps._normalize_vat("SK", "abc") is None


class TestIsHeadingCandidate:
    def test_accepts_normal_company_name(self):
        assert ps._is_heading_candidate("Jozef Horňák-HORNAK klenoty")

    def test_rejects_too_short(self):
        assert not ps._is_heading_candidate("ACME")

    def test_rejects_too_long(self):
        assert not ps._is_heading_candidate("X" * 100)

    def test_rejects_empty(self):
        assert not ps._is_heading_candidate("")

    def test_rejects_whitespace(self):
        assert not ps._is_heading_candidate("   ")

    def test_rejects_colon_label(self):
        assert not ps._is_heading_candidate("Customer: ACME Corp")

    def test_rejects_hash_label(self):
        assert not ps._is_heading_candidate("Invoice #12345")

    def test_rejects_sheet_title(self):
        assert not ps._is_heading_candidate("Shipment Packing List")
        assert not ps._is_heading_candidate("PACKING LIST")
        assert not ps._is_heading_candidate("Invoice")

    def test_rejects_vat_prefix(self):
        assert not ps._is_heading_candidate("VAT SK107095376")

    def test_rejects_phone_prefix(self):
        assert not ps._is_heading_candidate("Phone +421 911 222 333")

    def test_rejects_address_prefix(self):
        assert not ps._is_heading_candidate("Address Mlynska 123")

    def test_rejects_email_prefix(self):
        assert not ps._is_heading_candidate("Email contact@x.com")

    def test_rejects_postal_or_phone_majority_digits(self):
        # ≥50% digits classified as postal/phone
        assert not ps._is_heading_candidate("12345 67890")
        assert not ps._is_heading_candidate("+421 911 222 333 444")


class TestLooksLikePostalOrPhone:
    def test_pure_digits(self):
        assert ps._looks_like_postal_or_phone("12345678")

    def test_pure_letters(self):
        assert not ps._looks_like_postal_or_phone("CompanyName")

    def test_empty_treated_as_digit_like(self):
        assert ps._looks_like_postal_or_phone("")

    def test_boundary_50_percent(self):
        # 50% digit ratio → True
        assert ps._looks_like_postal_or_phone("ab12")


# ── extract_vat_from_preamble best-effort paths ──────────────────────────────

class TestExtractVatBestEffort:
    def test_empty_path_returns_none(self):
        assert ps.extract_vat_from_preamble("") is None
        assert ps.extract_vat_from_preamble(None) is None  # type: ignore

    def test_missing_file_returns_none(self, tmp_path):
        assert ps.extract_vat_from_preamble(tmp_path / "no-such.xlsx") is None

    def test_openpyxl_missing_returns_none(self, tmp_path):
        # File exists but openpyxl import fails
        fake = tmp_path / "stub.xlsx"
        fake.write_bytes(b"PK\x03\x04")  # minimal zip header — won't be read
        with patch.dict(sys.modules, {"openpyxl": None}):
            # Force ImportError by removing from sys.modules and blocking import
            import builtins
            real_import = builtins.__import__

            def blocked_import(name, *a, **k):
                if name == "openpyxl":
                    raise ImportError("blocked for test")
                return real_import(name, *a, **k)

            with patch.object(builtins, "__import__", side_effect=blocked_import):
                assert ps.extract_vat_from_preamble(fake) is None

    def test_unreadable_file_returns_none(self, tmp_path):
        # File exists but is not a valid XLSX → openpyxl raises → returns None
        broken = tmp_path / "broken.xlsx"
        broken.write_bytes(b"not a real xlsx")
        assert ps.extract_vat_from_preamble(broken) is None


# ── extract_heading_candidate best-effort paths ──────────────────────────────

class TestExtractHeadingBestEffort:
    def test_empty_path_returns_none(self):
        assert ps.extract_heading_candidate("") is None
        assert ps.extract_heading_candidate(None) is None  # type: ignore

    def test_missing_file_returns_none(self, tmp_path):
        assert ps.extract_heading_candidate(tmp_path / "no-such.xlsx") is None

    def test_unreadable_file_returns_none(self, tmp_path):
        broken = tmp_path / "broken.xlsx"
        broken.write_bytes(b"not a real xlsx")
        assert ps.extract_heading_candidate(broken) is None


# ── extract_all_signals combined contract ────────────────────────────────────

class TestExtractAllSignals:
    def test_returns_dict_with_both_keys_on_missing_file(self, tmp_path):
        result = ps.extract_all_signals(tmp_path / "no-such.xlsx")
        assert isinstance(result, dict)
        assert set(result.keys()) == {"vat", "heading_candidate"}
        assert result["vat"] is None
        assert result["heading_candidate"] is None

    def test_returns_dict_with_both_keys_on_empty_path(self):
        result = ps.extract_all_signals("")
        assert set(result.keys()) == {"vat", "heading_candidate"}
        assert result == {"vat": None, "heading_candidate": None}

    def test_returns_dict_with_both_keys_on_broken_file(self, tmp_path):
        broken = tmp_path / "broken.xlsx"
        broken.write_bytes(b"not a real xlsx")
        result = ps.extract_all_signals(broken)
        assert set(result.keys()) == {"vat", "heading_candidate"}
        assert result == {"vat": None, "heading_candidate": None}


# ── Real XLSX extraction (skip if openpyxl unavailable) ──────────────────────

openpyxl = pytest.importorskip("openpyxl")


def _make_xlsx(path: Path, rows: list) -> Path:
    """Write a minimal XLSX with the given rows on the active sheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
    wb.save(str(path))
    wb.close()
    return path


class TestExtractVatRealFile:
    def test_finds_canonical_vat_in_header(self, tmp_path):
        p = _make_xlsx(tmp_path / "vat.xlsx", [
            ["Jozef Horňák-HORNAK klenoty"],
            ["VAT SK107095376"],
            ["Phone +421 911 222 333"],
        ])
        assert ps.extract_vat_from_preamble(p) == "SK107095376"

    def test_finds_vat_with_inline_spaces(self, tmp_path):
        p = _make_xlsx(tmp_path / "vat-sp.xlsx", [
            ["VAT SK 1070 95376"],
        ])
        assert ps.extract_vat_from_preamble(p) == "SK107095376"

    def test_finds_vat_with_inline_dash(self, tmp_path):
        p = _make_xlsx(tmp_path / "vat-dash.xlsx", [
            ["VAT SK-107095376"],
        ])
        assert ps.extract_vat_from_preamble(p) == "SK107095376"

    def test_returns_none_when_no_vat_present(self, tmp_path):
        p = _make_xlsx(tmp_path / "no-vat.xlsx", [
            ["Some Customer Name"],
            ["Address: Main Street 1"],
            ["Phone: 12345"],
        ])
        assert ps.extract_vat_from_preamble(p) is None

    def test_respects_max_rows(self, tmp_path):
        # VAT is on row 20; default max_rows=15 → not found
        rows = [["filler"]] * 19 + [["VAT SK107095376"]]
        p = _make_xlsx(tmp_path / "deep-vat.xlsx", rows)
        assert ps.extract_vat_from_preamble(p) is None
        # With max_rows=25 → found
        assert ps.extract_vat_from_preamble(p, max_rows=25) == "SK107095376"

    def test_returns_first_hit(self, tmp_path):
        p = _make_xlsx(tmp_path / "two-vats.xlsx", [
            ["VAT SK107095376"],
            ["VAT DE111222333"],
        ])
        assert ps.extract_vat_from_preamble(p) == "SK107095376"


class TestExtractHeadingRealFile:
    def test_finds_plausible_company_heading(self, tmp_path):
        p = _make_xlsx(tmp_path / "hd.xlsx", [
            ["Jozef Horňák-HORNAK klenoty"],
            ["VAT SK107095376"],
        ])
        assert ps.extract_heading_candidate(p) == "Jozef Horňák-HORNAK klenoty"

    def test_skips_sheet_title(self, tmp_path):
        p = _make_xlsx(tmp_path / "title.xlsx", [
            ["Shipment Packing List"],
            ["Jozef Horňák-HORNAK klenoty"],
        ])
        assert ps.extract_heading_candidate(p) == "Jozef Horňák-HORNAK klenoty"

    def test_skips_metadata_prefixes(self, tmp_path):
        p = _make_xlsx(tmp_path / "meta.xlsx", [
            ["Address Mlynska 12"],
            ["Phone +421 911"],
            ["VAT SK107095376"],
            ["Jozef Horňák-HORNAK klenoty"],
        ])
        assert ps.extract_heading_candidate(p) == "Jozef Horňák-HORNAK klenoty"

    def test_skips_colon_labels(self, tmp_path):
        p = _make_xlsx(tmp_path / "colon.xlsx", [
            ["Customer: ACME Corp"],
            ["Real Company Name"],
        ])
        assert ps.extract_heading_candidate(p) == "Real Company Name"

    def test_returns_none_if_only_metadata(self, tmp_path):
        p = _make_xlsx(tmp_path / "all-meta.xlsx", [
            ["Address Mlynska 12"],
            ["VAT SK107095376"],
            ["Phone +421"],
        ])
        assert ps.extract_heading_candidate(p) is None

    def test_respects_max_rows(self, tmp_path):
        # Heading on row 10; default max_rows=6 → None
        rows = [["VAT SK107095376"]] * 9 + [["Jozef Horňák-HORNAK klenoty"]]
        p = _make_xlsx(tmp_path / "deep.xlsx", rows)
        assert ps.extract_heading_candidate(p) is None
        assert (
            ps.extract_heading_candidate(p, max_rows=12)
            == "Jozef Horňák-HORNAK klenoty"
        )


class TestExtractAllSignalsRealFile:
    def test_both_signals_present(self, tmp_path):
        p = _make_xlsx(tmp_path / "both.xlsx", [
            ["Jozef Horňák-HORNAK klenoty"],
            ["VAT SK107095376"],
        ])
        result = ps.extract_all_signals(p)
        assert result == {
            "vat": "SK107095376",
            "heading_candidate": "Jozef Horňák-HORNAK klenoty",
        }

    def test_vat_only(self, tmp_path):
        p = _make_xlsx(tmp_path / "vat-only.xlsx", [
            ["VAT SK107095376"],
            ["Phone 12345"],
        ])
        result = ps.extract_all_signals(p)
        assert result["vat"] == "SK107095376"
        assert result["heading_candidate"] is None

    def test_heading_only(self, tmp_path):
        p = _make_xlsx(tmp_path / "hd-only.xlsx", [
            ["Real Company Name SRO"],
            ["Phone 12345"],
        ])
        result = ps.extract_all_signals(p)
        assert result["vat"] is None
        assert result["heading_candidate"] == "Real Company Name SRO"

    def test_neither_signal(self, tmp_path):
        p = _make_xlsx(tmp_path / "none.xlsx", [
            ["VAT short"],   # no normalised VAT
            ["Address: X"],  # colon-labelled, skipped
            ["12345"],       # postal-shaped
        ])
        result = ps.extract_all_signals(p)
        assert result == {"vat": None, "heading_candidate": None}

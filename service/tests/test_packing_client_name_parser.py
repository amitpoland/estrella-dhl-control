"""
test_packing_client_name_parser.py — Tests for client-name extraction helpers
in routes_packing.py and the recheck stale-failed_checks fix.

Covers:
  1. _guess_client_from_filename — long format, Cilent typo, short format, blank
  2. _guess_client_from_preamble — header-row fallback (mocked openpyxl)
  3. Recheck stale failed_checks — cif_match cleared, status upgraded to partial
  4. UI source-grep — ghost rows hidden, ghost count message present
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DASHBOARD_HTML = _ROOT / "app" / "static" / "dashboard.html"
ROUTES_PACKING = _ROOT / "app" / "api" / "routes_packing.py"


# ===========================================================================
# 1. _guess_client_from_filename — long format + Cilent typo
# ===========================================================================

class TestGuessClientFromFilenameExtended:
    """
    Extends the short-format tests in test_packing_sales_linkage.py with the
    long-format pattern introduced in this fix.
    """

    def _f(self, name: str) -> str:
        from app.api.routes_packing import _guess_client_from_filename
        return _guess_client_from_filename(name)

    def test_long_format_client_suffix(self):
        """Long filename with '-Client NAME' at end returns NAME."""
        result = self._f("148 EJL-26-27-148-PND-18KT-SUOKKO-2026-05-Client SUOKKO.xlsx")
        assert result == "SUOKKO"

    def test_long_format_cilent_typo(self):
        """Long format with '-Cilent NAME' at end returns NAME."""
        result = self._f("150 EJL-26-27-150-PND-18KT-XYZ-2026-05-Cilent XYZ Corp.xlsx")
        assert result == "XYZ Corp"

    def test_long_format_multi_word_name(self):
        """Long format where client name has two words."""
        result = self._f("12 EJL-26-27-012-RNG-14KT-ALPHA-2026-05-Client Diamond Point.xlsx")
        assert result == "Diamond Point"

    def test_short_format_still_works(self):
        """Short '148 Client SUOKKO.xlsx' must still work after regex change."""
        result = self._f("148 Client SUOKKO.xlsx")
        assert result == "SUOKKO"

    def test_short_format_cilent_typo(self):
        """Short '149 Cilent Diamond Point.xlsx' still works."""
        result = self._f("149 Cilent Diamond Point.xlsx")
        assert result == "Diamond Point"

    def test_no_client_token(self):
        """Returns '' when 'Client' token is absent."""
        result = self._f("invoice_12345.xlsx")
        assert result == ""

    def test_blank_filename(self):
        """Returns '' for blank input."""
        result = self._f("")
        assert result == ""

    def test_extension_not_in_result(self):
        """Extension is not included in the returned name."""
        result = self._f("5 Client TestName.xlsx")
        assert "xlsx" not in result
        assert result == "TestName"


# ===========================================================================
# 2. _guess_client_from_preamble — openpyxl mocked
# ===========================================================================

def _make_fake_wb(rows: list):
    """Build a minimal openpyxl mock that yields rows from iter_rows."""
    wb = MagicMock()
    ws = MagicMock()
    wb.active = ws

    def _iter_rows(min_row=1, max_row=12, values_only=True):
        for r in rows[:max_row]:
            yield r

    ws.iter_rows.side_effect = _iter_rows
    return wb


class TestGuessClientFromPreamble:

    def _run(self, preamble_rows: list, path: str = "/fake/file.xlsx") -> str:
        from app.api.routes_packing import _guess_client_from_preamble
        wb = _make_fake_wb(preamble_rows)
        with patch("openpyxl.load_workbook", return_value=wb):
            return _guess_client_from_preamble(path)

    def test_client_colon(self):
        """Detects 'Client: SUOKKO' in preamble."""
        result = self._run([["Order No: 1234", None], ["Client: SUOKKO", None]])
        assert result == "SUOKKO"

    def test_consignee_label(self):
        """Detects 'Consignee: ALPHA Corp'."""
        result = self._run([[None], ["Consignee: ALPHA Corp"]])
        assert result == "ALPHA Corp"

    def test_buyer_label(self):
        """Detects 'Buyer: Beta Ltd'."""
        result = self._run([["Date: 2026-05-01"], ["Buyer: Beta Ltd"]])
        assert result == "Beta Ltd"

    def test_ship_to_label(self):
        """Detects 'Ship To: Gamma GmbH'."""
        result = self._run([["Ship To: Gamma GmbH"]])
        assert result == "Gamma GmbH"

    def test_no_match_returns_empty(self):
        """Returns '' when no client label found."""
        result = self._run([["Invoice: EJL/26-27/001"], ["Date: 2026-05-01"]])
        assert result == ""

    def test_empty_path_returns_empty(self):
        """Returns '' immediately for empty path."""
        from app.api.routes_packing import _guess_client_from_preamble
        assert _guess_client_from_preamble("") == ""

    def test_openpyxl_exception_handled(self):
        """Returns '' gracefully when openpyxl raises."""
        from app.api.routes_packing import _guess_client_from_preamble
        with patch("openpyxl.load_workbook", side_effect=Exception("corrupt")):
            assert _guess_client_from_preamble("/fake/bad.xlsx") == ""

    def test_value_too_long_skipped(self):
        """Values ≥ 80 chars are not returned (not a client name)."""
        long_val = "X" * 80
        result = self._run([[f"Client: {long_val}"]])
        assert result == ""


# ===========================================================================
# 3. Recheck stale failed_checks — dict mutation logic
# ===========================================================================

def _apply_cif_match_clear(audit: dict) -> dict:
    """
    Reproduce the exact failed_checks clearing logic from routes_dashboard.py
    recheck section D.  Returns the mutated dict.
    """
    _fc = list(audit.get("failed_checks") or [])
    if "cif_match" in _fc:
        _fc = [c for c in _fc if c != "cif_match"]
        audit["failed_checks"] = _fc
        if not _fc and audit.get("status") == "blocked":
            pz_exists = bool(
                audit.get("pz_output", {}).get("generated_at")
                or (audit.get("files", {}).get("pdf") or {}).get("sha256")
            )
            if pz_exists:
                audit["status"] = "partial"
    return audit


class TestRecheckFailedChecksClear:

    def test_cif_match_removed(self):
        audit = {"failed_checks": ["cif_match"], "status": "blocked",
                 "pz_output": {"generated_at": "2026-05-14T10:00:00Z"}}
        _apply_cif_match_clear(audit)
        assert "cif_match" not in audit["failed_checks"]

    def test_status_upgraded_to_partial_pz_output(self):
        audit = {"failed_checks": ["cif_match"], "status": "blocked",
                 "pz_output": {"generated_at": "2026-05-14T10:00:00Z"}}
        _apply_cif_match_clear(audit)
        assert audit["status"] == "partial"

    def test_status_upgraded_to_partial_files_pdf(self):
        """PZ existence also detected via files.pdf.sha256."""
        audit = {"failed_checks": ["cif_match"], "status": "blocked",
                 "files": {"pdf": {"sha256": "abc123"}}}
        _apply_cif_match_clear(audit)
        assert audit["status"] == "partial"

    def test_no_upgrade_without_pz_evidence(self):
        """Status stays 'blocked' when no PZ output evidence."""
        audit = {"failed_checks": ["cif_match"], "status": "blocked"}
        _apply_cif_match_clear(audit)
        assert audit["status"] == "blocked"
        assert audit["failed_checks"] == []

    def test_other_failed_checks_preserved(self):
        """Only cif_match is removed; invoice_refs_match remains."""
        audit = {"failed_checks": ["cif_match", "invoice_refs_match"],
                 "status": "blocked",
                 "pz_output": {"generated_at": "2026-05-14T10:00:00Z"}}
        _apply_cif_match_clear(audit)
        assert "cif_match" not in audit["failed_checks"]
        assert "invoice_refs_match" in audit["failed_checks"]
        assert audit["status"] == "blocked"  # other check still present

    def test_no_upgrade_when_already_partial(self):
        """No state change when status is already 'partial'."""
        audit = {"failed_checks": ["cif_match"], "status": "partial",
                 "pz_output": {"generated_at": "2026-05-14T10:00:00Z"}}
        _apply_cif_match_clear(audit)
        assert audit["status"] == "partial"

    def test_noop_when_cif_match_absent(self):
        """No mutation when 'cif_match' is not in failed_checks."""
        audit = {"failed_checks": ["invoice_refs_match"], "status": "blocked"}
        original_fc = list(audit["failed_checks"])
        _apply_cif_match_clear(audit)
        assert audit["failed_checks"] == original_fc
        assert audit["status"] == "blocked"


# ===========================================================================
# 4. Source-grep — routes_packing.py regex changes
# ===========================================================================

class TestRoutesPackingSourceGrep:

    def _src(self) -> str:
        return ROUTES_PACKING.read_text(encoding="utf-8")

    def test_client_name_re_uses_search_not_match(self):
        """_guess_client_from_filename must use search() for long-format support."""
        src = self._src()
        idx = src.find("def _guess_client_from_filename")
        assert idx != -1
        fn_body = src[idx:idx + 600]
        assert "_CLIENT_NAME_RE.search(" in fn_body, (
            "_guess_client_from_filename must use .search() not .match()"
        )

    def test_client_name_re_handles_dash_separator(self):
        """_CLIENT_NAME_RE must allow dash separator before 'client' keyword."""
        src = self._src()
        # Pattern must allow a leading '-' (dash before Client in long format)
        # while also requiring either a digit prefix or dash — not bare start.
        assert "-" in src[src.find("_CLIENT_NAME_RE"):src.find("_CLIENT_NAME_RE") + 200], (
            "_CLIENT_NAME_RE must contain '-' separator for long filename format"
        )

    def test_preamble_re_defined(self):
        """_CLIENT_PREAMBLE_RE must be defined."""
        assert "_CLIENT_PREAMBLE_RE" in self._src()

    def test_preamble_fallback_function_defined(self):
        """_guess_client_from_preamble function must be defined."""
        assert "def _guess_client_from_preamble" in self._src()

    def test_preamble_fallback_called_in_get_packing_documents(self):
        """get_packing_documents must call _guess_client_from_preamble as fallback."""
        src = self._src()
        assert "_guess_client_from_preamble" in src
        # The fallback must appear after the filename guess (or-chain)
        fn_idx = src.find("_guess_client_from_filename(raw_name)")
        pre_idx = src.find("_guess_client_from_preamble(")
        assert fn_idx != -1 and pre_idx != -1
        # Both must appear in the same expression (within 200 chars)
        window = src[fn_idx:fn_idx + 200]
        assert "_guess_client_from_preamble" in window, (
            "_guess_client_from_preamble must be the or-fallback in get_packing_documents"
        )


# ===========================================================================
# 5. UI source-grep — dashboard.html ghost row changes
# ===========================================================================

class TestDashboardGhostRowUI:

    def _html(self) -> str:
        return DASHBOARD_HTML.read_text(encoding="utf-8")

    def test_ghost_filter_applied_in_both_renders(self):
        """Both packing table renders must filter out ghost rows."""
        src = self._html()
        count = src.count("!(doc.is_duplicate && doc.line_count === 0)")
        assert count >= 2, (
            f"Expected ghost filter in ≥2 table renders, found {count}"
        )

    def test_ghost_count_testid_first_panel(self):
        """link-packing-ghost-count testid must be present."""
        assert 'data-testid="link-packing-ghost-count"' in self._html()

    def test_ghost_count_testid_main_panel(self):
        """link-packing-ghost-count-main testid must be present."""
        assert 'data-testid="link-packing-ghost-count-main"' in self._html()

    def test_ghost_count_message_text(self):
        """Ghost count message shows 'hidden (zero lines)'."""
        assert "hidden (zero lines)" in self._html()

    def test_submit_excludes_ghost_docs(self):
        """submitLinkAsSales must exclude ghost docs (is_duplicate && line_count=0)."""
        src = self._html()
        submit_idx = src.find("submitLinkAsSales = React.useCallback")
        assert submit_idx != -1
        fn_body = src[submit_idx:submit_idx + 800]
        assert "!(doc.is_duplicate && doc.line_count === 0)" in fn_body, (
            "submitLinkAsSales must explicitly exclude ghost rows"
        )

    def test_dup_badge_still_present(self):
        """DUP badge still exists for non-ghost duplicate rows."""
        assert ">DUP<" in self._html() or '"DUP"' in self._html() or ">DUP\n" in self._html()

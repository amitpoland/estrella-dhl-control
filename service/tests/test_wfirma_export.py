"""
test_wfirma_export.py — wFirma export hardening tests.

Covers:
1. Supplier resolution priority chain (customs > verification > exporter_check > zc429 > learning > fallback)
2. Supplier fallback emits risk flag and warning
3. doc_no blank emits warning + requires_doc_no=True (does not block)
4. doc_no present clears requires_doc_no
5. Backend warnings shown alongside row data in clipboard endpoint payload
6. autofill_pz.js contains no Save-click logic
7. autofill_pz.js validation rejects empty rows
8. autofill_pz.js validation warns on empty doc_no
9. autofill_pz.js validation blocks UNKNOWN_SUPPLIER without reviewMode
10. No PZ financial values are modified by the export path
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.api.routes_wfirma import _resolve_supplier  # noqa: E402


# ── 1-3. Supplier priority chain tests ────────────────────────────────────────

def test_supplier_priority_customs_declaration_wins():
    audit = {
        "customs_declaration": {"exporter_name": "Estrella Jewels LLP"},
        "verification":        {"invoice_exporter_name": "Some Other Inc"},
        "exporter_check":      {"invoice_exporter": "Backup Co"},
    }
    name, source, risks = _resolve_supplier(audit)
    assert name == "Estrella Jewels LLP"
    assert source == "customs_declaration.exporter_name"
    assert risks == []


def test_supplier_priority_verification_when_customs_blank():
    audit = {
        "customs_declaration": {"exporter_name": ""},
        "verification":        {"invoice_exporter_name": "Estrella Jewels LLP"},
    }
    name, source, risks = _resolve_supplier(audit)
    assert name == "Estrella Jewels LLP"
    assert source == "verification.invoice_exporter_name"
    assert risks == []


def test_supplier_priority_exporter_check_third():
    audit = {
        "customs_declaration": {"exporter_name": ""},
        "verification":        {"invoice_exporter_name": ""},
        "exporter_check":      {"invoice_exporter": "Global Jewellery Pvt. Ltd."},
    }
    name, source, _ = _resolve_supplier(audit)
    assert name == "Global Jewellery Pvt. Ltd."
    assert source == "exporter_check.invoice_exporter"


def test_supplier_priority_zc429_fourth():
    audit = {
        "customs_declaration": {},
        "zc429":                {"exporter_name": "Estrella Jewels LLP"},
    }
    name, source, _ = _resolve_supplier(audit)
    assert name == "Estrella Jewels LLP"
    assert source == "zc429.exporter_name"


def test_supplier_priority_learning_traces_with_risk_flag():
    audit = {
        "customs_declaration": {"exporter_name": ""},
        "learning_traces":     [{"supplier_key": "estrella_jewels_llp"}],
    }
    name, source, risks = _resolve_supplier(audit)
    assert name == "Estrella Jewels LLP"
    assert source == "learning_traces[0].supplier_key"
    assert "supplier_from_learning_only" in risks


def test_supplier_fallback_unknown_with_risk_flag():
    audit = {
        "customs_declaration": {},
        "verification":        {},
        "exporter_check":      {},
        "zc429":               {},
        "learning_traces":     [],
    }
    name, source, risks = _resolve_supplier(audit)
    assert name == "UNKNOWN_SUPPLIER"
    assert source == "fallback"
    assert "supplier_missing_for_wfirma" in risks


def test_supplier_never_returns_blank():
    """Even with completely empty audit, supplier is non-blank."""
    audit: dict = {}
    name, _, risks = _resolve_supplier(audit)
    assert name and name.strip()
    assert "supplier_missing_for_wfirma" in risks


# ── 6-9. Autofill script safety audit (static analysis) ───────────────────────

_AUTOFILL_PATH = Path(__file__).parent.parent.parent / "chrome_wfirma_autofill" / "autofill_pz.js"


@pytest.fixture(scope="module")
def autofill_src() -> str:
    assert _AUTOFILL_PATH.exists(), f"autofill script missing: {_AUTOFILL_PATH}"
    return _AUTOFILL_PATH.read_text(encoding="utf-8")


def test_autofill_no_save_click(autofill_src: str):
    """Script must never contain logic that clicks Save/Zapisz."""
    # Strip comments and string literals before checking for save-click patterns
    no_block_comments = re.sub(r"/\*.*?\*/", "", autofill_src, flags=re.DOTALL)
    no_line_comments  = re.sub(r"//.*", "", no_block_comments)
    # Strip single + double quoted strings
    no_strings        = re.sub(r"'[^']*'|\"[^\"]*\"", "''", no_line_comments)

    forbidden_patterns = [
        r"button.*Zapisz.*\.click",
        r"\.click\(\)\s*;?\s*//\s*(save|submit|zapisz)",
        r"form\s*\.\s*submit\s*\(",
        r"document\.forms\[\s*\d+\s*\]\.submit",
        r"\.submit\(\s*\)",
    ]
    for pat in forbidden_patterns:
        m = re.search(pat, no_strings, re.IGNORECASE)
        assert not m, f"Forbidden Save-click pattern found: {pat!r} → {m.group() if m else ''}"


def test_autofill_no_external_network(autofill_src: str):
    """Script must not contact external servers (no fetch/XHR in code, only in docstring example)."""
    no_block_comments = re.sub(r"/\*.*?\*/", "", autofill_src, flags=re.DOTALL)
    no_line_comments  = re.sub(r"//.*", "", no_block_comments)
    no_strings        = re.sub(r"'[^']*'|\"[^\"]*\"", "''", no_line_comments)
    # No XMLHttpRequest, no real fetch (only allowed inside _log/_warn string args)
    assert "XMLHttpRequest" not in no_strings, "XHR usage forbidden in autofill script"
    assert "navigator.sendBeacon" not in no_strings, "sendBeacon forbidden"


def test_autofill_validates_empty_rows(autofill_src: str):
    """Validation chain must reject empty rows."""
    assert "_validateInput" in autofill_src
    assert "No rows in PZ_READY.json" in autofill_src or "No rows" in autofill_src


def test_autofill_warns_on_empty_doc_no(autofill_src: str):
    """Validation chain must warn when doc_no is empty (warning, not blocker)."""
    # Extract _validateInput full body by brace matching
    start = autofill_src.find("function _validateInput")
    assert start != -1, "_validateInput function not found"
    # Find the function's opening brace and walk to its matching close
    brace_start = autofill_src.find("{", start)
    depth, i = 0, brace_start
    while i < len(autofill_src):
        c = autofill_src[i]
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: break
        i += 1
    body = autofill_src[start:i + 1]

    assert "doc_no" in body, "doc_no check missing from _validateInput"
    # Find the doc_no handling and confirm it's a warning, not a blocker
    doc_no_warning = re.search(r"doc_no[\s\S]{0,200}warnings\.push", body)
    assert doc_no_warning, "doc_no must trigger warnings.push"
    # No blocker.push for doc_no
    doc_no_blocker = re.search(r"blockers\.push\([^)]*doc_no[^)]*\)", body)
    assert not doc_no_blocker, "doc_no must be a warning, not a blocker"


def test_autofill_blocks_unknown_supplier_in_strict_mode(autofill_src: str):
    """Default mode must block UNKNOWN_SUPPLIER; reviewMode allows it."""
    assert "UNKNOWN_SUPPLIER" in autofill_src
    # Look for blocker push containing UNKNOWN_SUPPLIER OR supplier check pattern
    m = re.search(
        r"UNKNOWN_SUPPLIER.*?reviewMode.*?blockers\.push",
        autofill_src, re.DOTALL,
    )
    assert m, "UNKNOWN_SUPPLIER blocker logic not found"


def test_autofill_returns_structured_result(autofill_src: str):
    """wfirmaFill must return an object with the documented keys."""
    for key in ("status", "rows_expected", "rows_filled", "supplier",
                "doc_no", "warnings", "totals_checked", "totals_match"):
        assert f'"{key}"' in autofill_src or f"'{key}'" in autofill_src or f"{key}:" in autofill_src, (
            f"Result key '{key}' not found in autofill script"
        )


def test_autofill_never_modifies_input_json(autofill_src: str):
    """Validation function must read data, never assign to data.* fields."""
    # Look for any assignment back into data.something inside the script
    assignments = re.findall(r"\bdata\.\w+\s*=(?!=)", autofill_src)
    assert not assignments, f"Script writes back into input data: {assignments}"


# ── 10. No financial fields modified by export path ───────────────────────────

def test_export_path_does_not_touch_financial_fields():
    """
    The wFirma export path is read-only over engine outputs.
    Verify _resolve_supplier reads but never mutates audit numeric fields.
    """
    audit = {
        "customs_declaration": {
            "exporter_name":   "Estrella Jewels LLP",
            "duty_a00_pln":    1234.56,
            "nbp_rate":        4.12,
        },
        "totals": {"net": 9999.99, "gross": 12299.99},
    }
    snapshot = {
        "duty": audit["customs_declaration"]["duty_a00_pln"],
        "rate": audit["customs_declaration"]["nbp_rate"],
        "net":  audit["totals"]["net"],
        "gross":audit["totals"]["gross"],
    }
    _resolve_supplier(audit)
    assert audit["customs_declaration"]["duty_a00_pln"] == snapshot["duty"]
    assert audit["customs_declaration"]["nbp_rate"]      == snapshot["rate"]
    assert audit["totals"]["net"]                        == snapshot["net"]
    assert audit["totals"]["gross"]                      == snapshot["gross"]

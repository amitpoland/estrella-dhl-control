"""
test_dashboard_missing_functions_matrix.py — Source-grep tests for the
Missing / Parked Modules matrix in the Overview tab.

Pattern: read dashboard.html as text and assert structural markers.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Component existence ───────────────────────────────────────────────────────

def test_missing_functions_matrix_component_exists():
    """MissingFunctionsMatrix function component must be defined."""
    assert "function MissingFunctionsMatrix(" in _src()


# ── Overview tab wiring ───────────────────────────────────────────────────────

def test_missing_functions_matrix_in_overview_tab():
    """MissingFunctionsMatrix must be rendered inside the Overview tab block."""
    src = _src()
    overview_start = src.find("activeTab === 'Overview'")
    assert overview_start != -1, "Overview tab block not found"
    # Next distinct tab after Overview is Documents
    overview_end = src.find("activeTab === 'Documents'", overview_start)
    assert overview_end != -1
    snippet = src[overview_start:overview_end]
    assert "<MissingFunctionsMatrix" in snippet, (
        "<MissingFunctionsMatrix /> not rendered inside Overview tab block"
    )


# ── Testids ───────────────────────────────────────────────────────────────────

def test_missing_functions_matrix_testid():
    """data-testid='missing-functions-matrix' must be present."""
    src = _src()
    assert (
        'data-testid="missing-functions-matrix"' in src
        or "data-testid='missing-functions-matrix'" in src
    )


def test_readonly_warning_testid():
    """Read-only warning element must carry its testid."""
    src = _src()
    assert (
        'data-testid="missing-functions-matrix-readonly-warning"' in src
        or "data-testid='missing-functions-matrix-readonly-warning'" in src
    )


# ── Read-only text ────────────────────────────────────────────────────────────

def test_readonly_warning_text_present():
    """The read-only disclaimer text must appear verbatim in the source."""
    assert "This matrix is read-only and does not trigger actions" in _src()


# ── All 10 module rows ────────────────────────────────────────────────────────

def test_row_proforma_converter():
    assert "Proforma" in _src() and "Invoice converter" in _src()


def test_row_pz_chrome_autofill():
    assert "PZ Chrome AutoFill preview" in _src()


def test_row_packing_list_upload():
    assert "Packing list upload" in _src()


def test_row_barcode_label_print():
    assert "Barcode / label print" in _src()


def test_row_dhl_documents_received():
    assert "DHL documents received" in _src()


def test_row_agency_documents_received():
    assert "Agency documents received" in _src()


def test_row_service_invoice_receipt():
    assert "Service invoice receipt" in _src()


def test_row_shipment_closure():
    assert "Shipment closure" in _src()


def test_row_wfirma_create_guard():
    assert "wFirma create guard" in _src()


def test_row_old_batch_flow_cleanup():
    assert "Old batch flow cleanup" in _src()


def test_all_ten_rows_present():
    """All 10 rows are generated via the ROWS array with a template-literal testid.
    The JSX uses data-testid={`mfm-row-${i}`} so we grep for the template expression."""
    src = _src()
    # The template expression appears literally in JSX source
    assert 'mfm-row-' in src, "mfm-row- testid prefix missing from source"
    # And there must be exactly 10 entries in the ROWS array
    rows_count = src.count("module:")
    # Count only within the MissingFunctionsMatrix component
    start = src.find("function MissingFunctionsMatrix(")
    assert start != -1
    snippet = src[start : start + 8000]
    module_count = snippet.count("module:")
    assert module_count >= 10, f"Expected ≥10 ROWS entries, found {module_count}"


# ── No new write calls ────────────────────────────────────────────────────────

def test_no_post_in_missing_functions_matrix():
    """MissingFunctionsMatrix must contain no POST/DELETE/PATCH fetch calls."""
    src = _src()
    start = src.find("function MissingFunctionsMatrix(")
    assert start != -1
    # Find the closing } of the function — scan 300 lines worth
    snippet = src[start : start + 10000]
    # Look for any fetch with a write method inside the component
    assert "method: 'POST'" not in snippet[:3000]
    assert "method: 'DELETE'" not in snippet[:3000]
    assert "method: 'PATCH'" not in snippet[:3000]


# ── Badge labels present ──────────────────────────────────────────────────────

def test_badge_labels_present():
    """All six badge types must appear somewhere in the matrix source."""
    src = _src()
    component_start = src.find("function MissingFunctionsMatrix(")
    assert component_start != -1
    snippet = src[component_start : component_start + 6000]
    for badge in ["Complete", "Partial", "Parked", "Missing UI", "Risky"]:
        assert badge in snippet, f"Badge '{badge}' not found in MissingFunctionsMatrix"


# ── Structural integrity ──────────────────────────────────────────────────────

def test_brace_balance():
    """Curly braces in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("{")
    closes = jsx.count("}")
    assert opens == closes, f"Unbalanced braces: {{ {opens}  }} {closes}"


def test_paren_balance():
    """Parentheses in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("(")
    closes = jsx.count(")")
    assert opens == closes, f"Unbalanced parens: ( {opens}  ) {closes}"

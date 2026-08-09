"""Source-grep: Management Analysis wiring under Ledgers."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_management_analysis_route_registered():
    src = (ROOT / "app" / "api" / "routes_ledgers.py").read_text(encoding="utf-8")
    assert "/management-analysis.json" in src
    assert "build_management_analysis" in src
    assert "/payables-analysis.json" in src
    assert "build_payables_analysis" in src
    assert "/suppliers/{contractor_id}/statement.json" in src


def test_ledgers_page_has_management_analysis_tab():
    src = (ROOT / "app" / "static" / "v2" / "ledgers-page.jsx").read_text(encoding="utf-8")
    assert "Management Analysis" in src
    assert "ManagementAnalysisView" in src
    assert "ldg-ma-table" in src
    assert "ldg-ma-ap-table" in src
    assert "Open Ledger" in src
    assert "Open Supplier Ledger" in src
    assert "Payables" in src
    api = (ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
    assert "getManagementAnalysis" in api
    assert "getPayablesAnalysis" in api
    assert "getSupplierStatement" in api


def test_no_client_side_remaining_formula_in_ma_view():
    src = (ROOT / "app" / "static" / "v2" / "ledgers-page.jsx").read_text(encoding="utf-8")
    # UI must display backend fields, not recompute gross - payments.
    assert "gross -" not in src.lower()
    assert "remaining =" not in src
    assert "currency_label" not in src

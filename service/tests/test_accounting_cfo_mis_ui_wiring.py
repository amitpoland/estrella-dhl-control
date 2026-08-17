"""Accounting + CFO MIS campaign — focused V2 UI wiring pins (PRIORITY 3/4).

Static source-grep only; no browser/server required.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"


def _read(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


# ── Shared register filter (Insurance Export pattern) ─────────────────────

def test_accounting_register_filter_exports_window():
    src = _read("accounting-register-filter.jsx")
    assert "window.AccountingRegisterFilter = AccountingRegisterFilter" in src
    assert "window.arfMonthlyPeriod" in src


def test_index_loads_register_filter_before_hub():
    idx = _read("index.html")
    arf_pos = idx.index("accounting-register-filter.jsx")
    hub_pos = idx.index("accounting-hub.jsx")
    assert arf_pos < hub_pos, "register filter must load before accounting-hub.jsx"


def test_register_filter_testids():
    src = _read("accounting-register-filter.jsx")
    for suffix in (
        "-period-mode",
        "-year",
        "-month",
        "-from",
        "-to",
        "-search",
        "-currency",
        "-status",
        "-page-prev",
    ):
        assert f"`${{tid}}{suffix}`" in src or f'${{tid}}{suffix}' in src, (
            f"missing testId suffix {suffix} in accounting-register-filter.jsx"
        )


# ── Accounting Hub document grids + AWB projection ───────────────────────

def test_acc_doc_grid_uses_shared_filter():
    hub = _read("accounting-hub.jsx")
    assert "window.AccountingRegisterFilter" in hub
    assert "_ACC_PAGE_LIMIT = 20" in hub
    assert "function AccDocGrid" in hub


def test_wz_pz_awb_cell_no_accounting_editor():
    hub = _read("accounting-hub.jsx")
    assert "function AccAwbCell" in hub
    assert "getAccountingDocAwbs" in _read("pz-api.js")
    assert "#logistics/" in hub, "Logistics hash navigation for AWB actions"
    assert "AccAwbEditor" not in hub and "awb editor" not in hub.lower()


def test_mm_honest_unsupported_state():
    hub = _read("accounting-hub.jsx")
    assert "acc-grid-mm-unsupported" in hub or "mm-unsupported" in hub


def test_document_sections_wired():
    hub = _read("accounting-hub.jsx")
    for sec in ("inv", "cn", "wz", "pz", "pw", "rw", "mm"):
        assert f"'{sec}'" in hub or f'"{sec}"' in hub


# ── Client balance sort (backend) ─────────────────────────────────────────

def test_sort_client_balance_rows_exists():
    routes = (
        Path(__file__).resolve().parent.parent / "app" / "api" / "routes_ledgers.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert "def _sort_client_balance_rows" in routes
    assert '"total":        total' in routes or '"total": total' in routes


def test_sort_client_balance_overdue_before_clear():
    from app.api.routes_ledgers import _sort_client_balance_rows

    rows = [
        {"contractor_id": "clear", "name": "Clear Co", "balance_available": True,
         "state": "clear", "open": "0", "overdue_invoice_age": "0"},
        {"contractor_id": "ovd", "name": "Overdue Co", "balance_available": True,
         "state": "overdue", "open": "100", "overdue_invoice_age": "50"},
        {"contractor_id": "open", "name": "Open Co", "balance_available": True,
         "state": "open", "open": "200", "overdue_invoice_age": "0"},
    ]
    ordered = [r["contractor_id"] for r in _sort_client_balance_rows(rows)]
    assert ordered[0] == "ovd"
    assert ordered[1] == "open"
    assert ordered[2] == "clear"

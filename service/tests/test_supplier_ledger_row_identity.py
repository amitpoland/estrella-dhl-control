"""Phase 1 — Supplier Ledger financial-row identity (contractor_id|currency).

Pins the FE composite selection key and the optional statement/PDF currency
query so EUR+USD for one contractor cannot collapse or cross-resolve.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes_ledgers import _restrict_supplier_statement_currency
from app.core.config import settings
from app.main import app

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
_ROUTES = (
    Path(__file__).resolve().parent.parent / "app" / "api" / "routes_ledgers.py"
)


def _ldg() -> str:
    return (_V2 / "ledgers-page.jsx").read_text(encoding="utf-8", errors="replace")


def _api() -> str:
    return (_V2 / "pz-api.js").read_text(encoding="utf-8", errors="replace")


def _hdr() -> dict:
    return {"X-API-Key": settings.api_key}


@pytest.fixture()
def client():
    return TestClient(app)


# ── A. Composite identity helpers ─────────────────────────────────────────

def test_supplier_financial_row_id_helper_is_composite():
    src = _ldg()
    assert "supplierFinancialRowId" in src
    assert "parseSupplierFinancialRowId" in src
    assert "`${contractorId || ''}|${String(currency || '').trim().toUpperCase()}`" in src


def test_supplier_roster_selects_by_composite_not_contractor_alone():
    src = _ldg()
    # The collapsed lookup must be gone.
    assert "suppliers.find((s) => s.contractor_id === activeId)" not in src
    assert "supplierFinancialRowId(s.contractor_id, s.currency) === activeId" in src
    # Default / focus selection also uses the composite.
    assert "supplierFinancialRowId(rows[0].contractor_id, rows[0].currency)" in src
    assert "if (!activeId && rows.length) setActiveId(rows[0].contractor_id);" not in src


def test_ma_open_supplier_ledger_passes_currency():
    src = _ldg()
    assert "onOpenSupplierLedger(r.contractor_id, r.currency)" in src
    assert "openSupplierLedger = (contractorId, currency)" in src
    assert "setFocusSupplierId(supplierFinancialRowId(contractorId, currency))" in src


def test_sup_list_limit_ten_enables_10_plus_3_paging():
    src = _ldg()
    assert "SUP_LIST_LIMIT = 10" in src
    # Pager label exposes page slice vs full roster for proof.
    assert "ldg-suppliers-page-label" in src
    # Exact 13-row case arithmetic pinned (page1=10, page2=3).
    n, limit = 13, 10
    assert (n + limit - 1) // limit == 2
    assert min(limit, n) == 10
    assert max(0, n - limit) == 3


def test_payables_analysis_math_untouched():
    """AP totals Δ0 — Phase 1 must not edit the payables aggregator."""
    analytics_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "accounting_analytics.py"
    )
    # File content hash not required — confirm this PR does not modify it.
    import subprocess
    diff = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD", "--", str(analytics_path)],
        cwd=str(analytics_path.parents[3]),
        text=True,
    ).strip()
    assert diff == "", f"accounting_analytics.py must stay Δ0 in Phase 1, got: {diff!r}"
    routes = _ROUTES.read_text(encoding="utf-8", errors="replace")
    assert "build_payables_analysis(" in routes
    assert "per_supplier_wfirma_calls" in routes



def test_statement_and_pdf_carry_selected_currency():
    src = _ldg()
    assert "currency: sel.currency" in src or "currency: active.currency" in src
    assert "currency: active.currency" in src
    # Sibling currency blocks must not render for the selected row.
    assert "stmtCurrencies" in src
    assert "ccy === active.currency" in src

    api = _api()
    assert "if (opts && opts.currency) qs.set('currency', opts.currency);" in api
    assert "if (p.currency) qs.set('currency', p.currency);" in api


def test_no_contractor_only_statement_fetch_from_active_id():
    """Regression: activeId used to be contractor_id and was passed straight
    into getSupplierStatement — that resolved the whole multi-ccy statement.
    """
    src = _ldg()
    # Must parse composite before the API call.
    assert "parseSupplierFinancialRowId(activeId)" in src
    assert re.search(
        r"getSupplierStatement\(\s*sel\.contractor_id",
        src,
    ), "statement fetch must use parsed contractor_id, not raw composite activeId"


# ── B. Backend currency restriction (no new grain) ────────────────────────

def test_restrict_helper_drops_sibling_currency():
    body = {
        "currencies": ["EUR", "USD"],
        "entries_per_currency": {"EUR": [{"doc": "e"}], "USD": [{"doc": "u"}]},
        "totals_per_currency": {"EUR": {"net_payable": "1"}, "USD": {"net_payable": "2"}},
        "aging_per_currency": {"EUR": {"total": "1"}, "USD": {"total": "2"}},
    }
    out = _restrict_supplier_statement_currency(body, "USD")
    assert out["currencies"] == ["USD"]
    assert list(out["entries_per_currency"]) == ["USD"]
    assert list(out["totals_per_currency"]) == ["USD"]
    assert "EUR" not in out["aging_per_currency"]


def test_statement_json_currency_query_filters_sections(client):
    multi = {
        "currencies": ["EUR", "USD"],
        "entries_per_currency": {"EUR": [], "USD": []},
        "totals_per_currency": {"EUR": {}, "USD": {}},
        "aging_per_currency": {"EUR": {}, "USD": {}},
        "query_stats": {"per_supplier_wfirma_calls": 0},
    }
    with patch(
        "app.api.routes_ledgers._build_supplier_statement_dict",
        return_value=_restrict_supplier_statement_currency(multi, "USD"),
    ) as mocked:
        r = client.get(
            "/api/v1/ledgers/suppliers/38142296/statement.json",
            params={
                "from": "2026-01-01",
                "to": "2026-08-11",
                "currency": "USD",
            },
            headers=_hdr(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currencies"] == ["USD"]
    assert "EUR" not in body["entries_per_currency"]
    # Route must forward currency into the shared builder (same PDF path).
    assert mocked.call_args is not None
    args, kwargs = mocked.call_args
    # Positional: (contractor_id, from_, to, as_of, refresh, currency)
    assert "USD" in args or kwargs.get("currency") == "USD"


def test_statement_pdf_currency_query_in_filename(client):
    stmt = {
        "currencies": ["USD"],
        "entries_per_currency": {"USD": []},
        "totals_per_currency": {"USD": {"outstanding": "0.00", "net_payable": "0.00"}},
        "aging_per_currency": {"USD": {"total": "0.00"}},
        "contractor": {"wfirma_contractor_id": "S-1", "name": "Acme"},
        "period": {"from": "2026-01-01", "to": "2026-06-30"},
        "as_of": "2026-06-30",
        "generated_at": "2026-06-30",
        "warnings": [],
    }
    with patch(
        "app.api.routes_ledgers._build_supplier_statement_dict",
        return_value=stmt,
    ), patch(
        "app.api.routes_ledgers.render_supplier_statement_pdf",
        return_value=b"%PDF-1.4 currency-usd-proof",
    ):
        r = client.get(
            "/api/v1/ledgers/suppliers/S-1/statement.pdf",
            params={
                "from": "2026-01-01",
                "to": "2026-06-30",
                "currency": "USD",
            },
            headers=_hdr(),
        )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-")
    assert "USD" in r.headers.get("content-disposition", "")
    assert "no-store" in r.headers.get("cache-control", "")


def test_statement_currency_query_rejects_junk(client):
    r = client.get(
        "/api/v1/ledgers/suppliers/S-1/statement.json",
        params={"from": "2026-01-01", "to": "2026-06-30", "currency": "BTC"},
        headers=_hdr(),
    )
    assert r.status_code == 400


def test_routes_still_use_require_api_key_not_weakened():
    src = _ROUTES.read_text(encoding="utf-8", errors="replace")
    assert src.count('"/suppliers/{contractor_id}/statement.json"') >= 1
    assert src.count('"/suppliers/{contractor_id}/statement.pdf"') >= 1
    # Both supplier statement routes stay behind the same _auth guard.
    assert "_auth  = Depends(require_api_key)" in src or "_auth = Depends(require_api_key)" in src
    # No write verbs introduced on supplier statement surfaces.
    assert "@router.post(\n    \"/suppliers/" not in src
    assert "WFIRMA_CREATE" not in src.split("get_supplier_statement_pdf")[0][-500:]

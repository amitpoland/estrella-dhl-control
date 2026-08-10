"""
test_ledger_period_authority_ui.py — one period authority for the ledgers UI.

Source-grep pins (repo house style for the bundler-free V2 layer: the .jsx is
served verbatim to the browser, so grepping the served file IS testing what
ships). These encode PR-005 — single authority ownership per domain — for the
accounting period window, which used to be re-derived in six places.

Coverage:
   1. exactly one calendar formula, and it lives in components.jsx
   2. accounting-hub.jsx owns no period state at all
   3. LedgersPage default mode is this_month
   4. Custom prefills both dates (the silent half-filled fallback cannot recur)
   5. resolvePeriod returns null rather than falling back to a preset
   6. all three page limits are 10
   7. exactly one AR Status and one AP Status control
   8. exactly one <LedgersPage mount in the hub
   9. all four pagers reset on period change, supplier pager included
  10. Management Analysis defaults to scope=all_outstanding
  11. pz-api.js stays transport-only for the two new PDF routes
"""
from __future__ import annotations

import re
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent / "app/static/v2"


def _read(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


# ── 1. One formula ────────────────────────────────────────────────────────

def test_quarter_math_exists_exactly_once_in_v2():
    """The literal quarter expression may appear in resolvePeriod and nowhere else."""
    hits = {
        p.name: p.read_text(encoding="utf-8", errors="replace").count("Math.floor(m / 3) * 3")
        for p in _V2.glob("*.jsx")
    }
    assert hits.get("components.jsx") == 1, hits
    assert sum(hits.values()) == 1, f"quarter math duplicated outside resolvePeriod: {hits}"


def test_resolve_period_is_exported_on_window():
    src = _read("components.jsx")
    assert "function resolvePeriod(" in src
    assert re.search(r"Object\.assign\(window,[\s\S]{0,600}resolvePeriod", src), (
        "resolvePeriod must be exported on window — ledgers-page.jsx and "
        "accounting-hub.jsx are separate <script> tags, not modules"
    )


# ── 2-3. Ownership and default ────────────────────────────────────────────

def test_accounting_hub_owns_no_period_state():
    hub = _read("accounting-hub.jsx")
    assert "useState('quarter')" not in hub
    assert "setPreset" not in hub, "the hub must not render a second preset bar"
    assert "periodFrom=" not in hub, "the hub must not push a period into LedgersPage"


def test_ledgers_page_default_mode_is_this_month():
    ldg = _read("ledgers-page.jsx")
    assert "mode: 'this_month'" in ldg
    assert "LDG_WINDOW" not in ldg, "the old fallback window must be deleted, not shadowed"


def test_supplier_ledger_shares_the_same_period_object():
    """Supplier view reads the same filters prop — no second period state."""
    ldg = _read("ledgers-page.jsx")
    assert re.search(r"function SupplierLedgerView\(\s*\{[^}]*filters", ldg), (
        "SupplierLedgerView must take the shared filters object"
    )


# ── 4-5. Custom cannot silently fall back ─────────────────────────────────

def test_custom_prefills_both_dates():
    ldg = _read("ledgers-page.jsx")
    assert "onMode" in ldg and "custom" in ldg
    # Switching to custom seeds from AND to from the currently resolved window.
    assert re.search(r"setCustom\(\s*\{\s*from:\s*filters\.from,\s*to:\s*filters\.to\s*\}\s*\)", ldg), (
        "switching to Custom must prefill both inputs from the resolved period"
    )
    assert "Both dates are required" in ldg, "an incomplete custom range must say so"
    assert "From date must be on or before To date" in ldg, "inverted range must be surfaced"


def test_resolve_period_returns_null_for_incomplete_custom():
    src = _read("components.jsx")
    m = re.search(r"if \(mode === 'custom'\) \{(.+?)\n  \}", src, re.S)
    assert m, "custom branch not found"
    body = m.group(1)
    assert "null" in body, "an incomplete custom range must yield null, never a preset"
    assert "c.from <= c.to" in body, "inverted ranges must be rejected, not swapped"


# ── 6. Page size ──────────────────────────────────────────────────────────

def test_all_list_limits_are_ten():
    ldg = _read("ledgers-page.jsx")
    for name in ("LDG_LIST_LIMIT", "SUP_LIST_LIMIT", "MA_TABLE_LIMIT"):
        assert f"{name} = 10" in ldg, f"{name} must be 10"


# ── 7. No duplicate status filters ────────────────────────────────────────

def test_exactly_one_ar_and_one_ap_status_control():
    joined = "".join(p.read_text(encoding="utf-8", errors="replace") for p in _V2.glob("*.jsx"))
    assert joined.count("ldg-ma-ap-status") == 1, "AP Status must exist exactly once"
    assert joined.count("ldg-ma-status") == 1, "AR Status must exist exactly once"


# ── 8. One mount ──────────────────────────────────────────────────────────

def test_ledgers_page_mounted_exactly_once():
    hub = _read("accounting-hub.jsx")
    assert hub.count("<LedgersPage") == 1
    assert "function AccSupplierLedger" not in hub


# ── 9. Pager resets ───────────────────────────────────────────────────────

def test_all_four_pagers_reset_on_period_change():
    ldg = _read("ledgers-page.jsx")
    for setter in ("setListPage(1)", "setArTablePage(1)", "setApTablePage(1)", "setSupListPage(1)"):
        assert setter in ldg, f"{setter} missing — a stale page survives a period change"
    # Every reset must depend on the period, not only on its own filter inputs.
    for setter in ("setListPage(1)", "setArTablePage(1)", "setApTablePage(1)", "setSupListPage(1)"):
        eff = re.search(
            r"React\.useEffect\(\(\) => \{ " + re.escape(setter) + r";? \}, \[([^\]]*)\]\)", ldg
        )
        assert eff, f"{setter} has no period-scoped reset effect"
        assert "period.from" in eff.group(1) and "period.to" in eff.group(1), (
            f"{setter} must reset when the period changes (deps: {eff.group(1)})"
        )


# ── 10. Management Analysis scope ─────────────────────────────────────────

def test_management_analysis_defaults_to_all_outstanding():
    ldg = _read("ledgers-page.jsx")
    assert "scope: 'all_outstanding'" in ldg, (
        "Management outstanding is a current exposure, not documents issued "
        "this month — the default scope must be all_outstanding"
    )
    assert "ldg-ma-scope" in ldg, "the Scope control must be on screen"


# ── 11. Transport stays transport ─────────────────────────────────────────

def test_pz_api_pdf_builders_are_url_only():
    # v2/pz-api.js — the transport the V2 index.html loads, not the legacy
    # static/pz-api.js used by the pre-V2 pages.
    api = _read("pz-api.js")
    assert "supplierStatementPdfUrl" in api
    assert "managementAnalysisPdfUrl" in api
    for banned in ("Decimal", "toFixed", "parseFloat", "reduce("):
        assert banned not in api.split("supplierStatementPdfUrl")[1][:1200], (
            f"pz-api.js must stay transport-only — found {banned!r} near the PDF builders"
        )

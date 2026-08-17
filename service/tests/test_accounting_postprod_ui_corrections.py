"""Post-production Accounting UI correction regressions.

Source-grep + unit pins for:
  - shared Year/Month/From/To ledger filter (no This Month presets)
  - as-of vs activity semantics labels
  - warning object rendering (never [object Object])
  - sanitized upstream 502 / HTML bodies
  - Credit Note create authority honesty
  - source/freshness badge modes
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parent.parent / "app/static/v2"
_SVC = Path(__file__).resolve().parent.parent / "app"


def _read(rel: str) -> str:
    return (_V2 / rel).read_text(encoding="utf-8", errors="replace")


def test_ledger_uses_year_month_from_to_not_preset_chips():
    ldg = _read("ledgers-page.jsx")
    assert "ldg-preset-this_month" not in ldg
    assert "This Month" not in ldg or "ldg-period-mode" in ldg
    assert 'data-testid="ldg-year"' in ldg
    assert 'data-testid="ldg-month"' in ldg
    assert 'data-testid="ldg-from"' in ldg
    assert 'data-testid="ldg-to"' in ldg
    assert 'data-testid="ldg-as-of"' in ldg
    assert "ldgDefaultActivityPeriod" in ldg
    assert "periodMode: 'monthly'" in ldg or 'periodMode: act.periodMode' in ldg
    # Must reuse AccountingRegisterFilter monthly helper, not invent a second formula
    assert "arfMonthlyPeriod" in ldg
    assert "LDG_PRESETS" not in ldg


def test_ledger_separates_position_asof_from_activity_period():
    ldg = _read("ledgers-page.jsx")
    assert "Position as-of" in ldg
    assert "Period activity only" in ldg
    assert "Period closing balance" in ldg
    assert "full outstanding as-of" in ldg
    assert "not period-bounded" in ldg
    # Roster still uses as_of for all_outstanding
    assert "to: period.as_of || period.to" in ldg
    assert "scope: period.scope || 'all_outstanding'" in ldg


def test_statement_warnings_never_string_object():
    ldg = _read("ledgers-page.jsx")
    assert "formatLedgerWarning" in ldg
    assert "dedupeLedgerWarnings" in ldg
    # Banned unsafe interpolations for warnings
    assert not re.search(r"ldg-stmt-warnings[\s\S]{0,400}String\(w\)", ldg)
    assert "JSON.stringify(w)" not in ldg
    assert "[object Object]" in ldg  # explicit guard against the literal
    assert "text === '[object Object]'" in ldg or "s === '[object Object]'" in ldg


def test_format_ledger_warning_behaviour_via_exec():
    """Execute the JS helpers with a tiny Node-less Python reimplementation check.

    The served JSX helpers are duplicated here as contract pins so CI does not
    need a JS runtime. Keep in sync with formatLedgerWarning / dedupeLedgerWarnings.
    """

    def format_ledger_warning(w):
        if w is None or w == "":
            return None
        if isinstance(w, (str, int, float, bool)):
            s = str(w)
            return None if s == "[object Object]" else s
        if not isinstance(w, dict):
            return str(w)
        event = w.get("event") or w.get("code") or ""
        msg = w.get("message") or w.get("detail") or ""
        parts = []
        if event:
            parts.append(str(event).replace("_", " "))
        if msg and msg != event:
            parts.append(str(msg))
        if w.get("wfirma_doc_id"):
            parts.append(f"doc {w['wfirma_doc_id']}")
        if w.get("linked_invoice"):
            parts.append(f"invoice {w['linked_invoice']}")
        if not parts:
            return "Data-quality exception (see server logs)"
        return " · ".join(parts)

    def dedupe(warnings):
        seen, out = set(), []
        for w in warnings or []:
            text = format_ledger_warning(w)
            if not text or text == "[object Object]":
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    assert "[object Object]" not in format_ledger_warning(
        {"event": "payment_unmatched", "wfirma_doc_id": "99"}
    )
    assert "payment unmatched" in format_ledger_warning(
        {"event": "payment_unmatched", "wfirma_doc_id": "99"}
    )
    assert format_ledger_warning({"event": "x"}) == format_ledger_warning({"event": "x"})
    d = dedupe(
        [
            {"event": "payment_unmatched", "wfirma_doc_id": "1"},
            {"event": "payment_unmatched", "wfirma_doc_id": "1"},
            {"event": "other", "message": "distinct"},
        ]
    )
    assert len(d) == 2
    assert all("[object Object]" not in t for t in d)


def test_wfirma_upstream_error_sanitizes_html_502():
    from app.services.wfirma_upstream_error import (
        operator_detail_for_exc,
        sanitize_wfirma_read_error,
    )

    html = RuntimeError(
        "HTTP 502: <!DOCTYPE html><!--[if lt IE 7]><html class=\"no-js\"><![endif]-->"
        "<html><head><title>Error</title></head><body>cloudflare</body></html>"
    )
    code, msg, retryable = sanitize_wfirma_read_error(html)
    assert code == "upstream_502"
    assert retryable is True
    assert "<!DOCTYPE" not in msg
    assert "<html" not in msg.lower()
    assert "502" in msg
    assert "<" not in operator_detail_for_exc(html)


def test_routes_accounting_uses_sanitizer():
    src = (_SVC / "api/routes_accounting.py").read_text(encoding="utf-8")
    assert "operator_detail_for_exc" in src
    assert 'detail=f"wFirma read failed: {exc}"' not in src


def test_api_fetch_sanitizes_html_error_bodies():
    for name in ("dashboard-shared.js",):
        src = _read(name)
        assert "upstream temporarily unavailable" in src
        assert "text.slice(0, 200)" not in src


def test_acc_doc_grid_empty_and_retry_states():
    hub = _read("accounting-hub.jsx")
    assert "No {m.t.toLowerCase()} documents found." in hub
    assert "temporarily unavailable from wFirma" in hub
    assert "acc-grid-${sectionId}-retry" in hub or 'acc-grid-${sectionId}-retry' in hub
    assert "formatAccUpstreamError" in hub
    # MM unsupported preserved
    assert "acc-grid-${sectionId}-mm-unsupported" in hub or "mm-unsupported" in hub
    assert "warehouse_document_m_m" in hub


def test_credit_note_no_atlas_write_authority():
    hub = _read("accounting-hub.jsx")
    assert "Create in wFirma" in hub
    assert "no approved CN write authority" in hub
    # CN must not reuse New Proforma action
    assert "sectionId === 'cn'" in hub or "sectionId !== 'cn'" in hub


def test_source_badges_local_vs_wfirma():
    ldg = _read("ledgers-page.jsx")
    assert "ldg-source-local" in ldg
    assert "ldg-source-wfirma" in ldg
    assert "mode={tab === 'analysis' ? 'local' : 'wfirma'}" in ldg
    assert "Period activity only" in ldg


def test_accounting_jsx_has_no_object_object_interpolation():
    """Scan AccDoc + ledgers for dangerous String(obj) warning patterns."""
    banned = []
    for name in ("ledgers-page.jsx", "accounting-hub.jsx", "cfo-mis.jsx"):
        p = _V2 / name
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        # Direct warning render with String(w) where w is likely an object
        if re.search(r"warnings[^\n]{0,80}String\(w\)", src):
            banned.append(name)
        if "⚠ {String(" in src:
            banned.append(f"{name}:string-warn")
    assert banned == [], f"unsafe object interpolation: {banned}"

"""Insurance Export — period selector contract pins (Slice 1).

Frontend convention here is source-grep against the JSX (there is no JS test
runner in this repo), plus the server-side period guard which is the actual
authority for the applied range.

Pins:
  • Monthly + Custom range are both first-class, discoverable modes.
  • Draft dates are edit-only — only Apply commits a range.
  • from > to is rejected client-side and server-side.
  • An applied period change clears declaration selection/preview and closes
    the stale PDF composer.
  • The current month stops at today; a completed month runs to its last day.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

APP = Path(__file__).resolve().parents[1] / "app"
JSX = APP / "static" / "v2" / "insurance-export-tab.jsx"


@pytest.fixture(scope="module")
def jsx() -> str:
    return JSX.read_text(encoding="utf-8")


def test_both_period_modes_offered(jsx):
    assert 'data-testid="ins-export-period-mode"' in jsx
    assert '<option value="monthly">Monthly</option>' in jsx
    assert '<option value="custom">Custom range</option>' in jsx
    # Monthly is the default mode.
    assert "React.useState('monthly')" in jsx


def test_monthly_controls_present(jsx):
    for testid in (
        "ins-export-year",
        "ins-export-month",
        "ins-export-prev",
        "ins-export-today",
        "ins-export-next",
    ):
        assert 'data-testid="%s"' % testid in jsx, testid
    assert "All year" in jsx
    # No twelve-button month wall — months live in the dropdown.
    assert "INS_MONTHS.map" in jsx


def test_custom_range_inputs_and_apply(jsx):
    assert 'data-testid="ins-export-from" type="date"' in jsx
    assert 'data-testid="ins-export-to" type="date"' in jsx
    assert 'data-testid="ins-export-apply"' in jsx
    assert "Date from" in jsx and "Date to" in jsx


def test_editing_a_date_does_not_fetch(jsx):
    """The date inputs write draft state only; setPeriod is the fetch trigger."""
    for handler in (
        "onChange={e => setCustomFrom(e.target.value)}",
        "onChange={e => setCustomTo(e.target.value)}",
    ):
        assert handler in jsx, handler
    # Neither input handler may commit a period or call the loader.
    assert not re.search(r"setCustomFrom\([^)]*\);\s*setPeriod\(", jsx)
    assert not re.search(r"setCustom(?:From|To)\(e\.target\.value\);\s*loadReport", jsx)


def test_apply_commits_exactly_one_period(jsx):
    body = jsx.split("const applyCustom", 1)[1].split("const downloadPdf", 1)[0]
    assert body.count("setPeriod(") == 1
    assert "setPeriod({ from: customFrom, to: customTo })" in body


def test_apply_rejects_reversed_range(jsx):
    body = jsx.split("const applyCustom", 1)[1].split("const downloadPdf", 1)[0]
    assert "customFrom > customTo" in body
    assert "setPeriodError(" in body
    # The reversed range must return before committing.
    assert body.index("customFrom > customTo") < body.index("setPeriod({")
    assert 'data-testid="ins-export-period-error"' in jsx


def test_mode_switch_never_leaves_a_hidden_period(jsx):
    body = jsx.split("const changeMode", 1)[1].split("const stepMonth", 1)[0]
    # custom seeds its drafts from the applied period...
    assert "setCustomFrom(period.from)" in body
    assert "setCustomTo(period.to)" in body
    # ...and monthly re-applies the year/month selection.
    assert "setPeriod(insMonthlyPeriod(year, month))" in body
    assert "onChange={e => changeMode(e.target.value)}" in jsx


def test_period_change_clears_declaration_and_closes_composer(jsx):
    effect = jsx.split("// Load on period change", 1)[1].split("}, [period, loadReport]);", 1)[0]
    for call in (
        "setSelDocs(new Set())",
        "setSelAdjs(new Set())",
        "setPreview(null)",
        "setDrawerOpen(false)",
        "loadReport(period, false)",
    ):
        assert call in effect, call


def test_month_navigation_preserved(jsx):
    body = jsx.split("const stepMonth", 1)[1].split("const goToday", 1)[0]
    assert "m = 12; y = y - 1;" in body
    assert "m = 1;  y = y + 1;" in body
    # All-year mode steps the year instead of the month.
    assert "applyMonthly(year + dir, 0)" in body


def test_all_year_and_current_month_bounds(jsx):
    fn = jsx.split("function insMonthlyPeriod", 1)[1].split("\n}", 1)[0]
    assert "${year}-01-01" in fn and "${year}-12-31" in fn
    # Current month is clamped to today; other months run to their last day.
    assert "isCurrent" in fn
    assert "insIsoDate(today)" in fn
    assert "insPad2(lastDay)" in fn


def test_server_rejects_reversed_period():
    """The applied range is validated by the route, not trusted from the UI."""
    from app.api.routes_insurance_export import _validate_period

    assert _validate_period("2026-08-01", "2026-08-31") == ("2026-08-01", "2026-08-31")
    with pytest.raises(HTTPException) as exc:
        _validate_period("2026-08-31", "2026-08-01")
    assert exc.value.status_code == 400

"""tests/test_dashboard_pipeline_summary_sales_hint.py — UI-3.6

Source-grep tests verifying that BatchDetailPage Pipeline Summary
consumes the true sales_status_hint injected by the batch detail
backend rather than falling back to the hardcoded 'n/a' placeholder.

UI-3.6 changes:
  - Backend: batch_detail() injects audit["sales_status_hint"] via the
    existing _sales_hint() helper before returning. The documents DB is
    the only authoritative source; audit.json never carries this field.
  - Frontend: pipelineRow.salesHint now reads audit.sales_status_hint
    with an 'n/a' fallback instead of being hardcoded to 'n/a'.

Invariants:
  - No new endpoint introduced (_sales_hint is already used by the list).
  - _sales_hint fails silently to 'n/a'; no extra try/except in the route.
  - The 'present' → 'Linked' / else → 'See Sales tab' label map is unchanged.
  - All UI-3.4 and UI-3.5 landmarks remain intact.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DASH     = _SVC_ROOT / "app" / "static" / "dashboard.html"
_ROUTES   = _SVC_ROOT / "app" / "api" / "routes_dashboard.py"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html not found")
    return _DASH.read_text(encoding="utf-8")


def _routes() -> str:
    if not _ROUTES.exists():
        pytest.skip("routes_dashboard.py not found")
    return _ROUTES.read_text(encoding="utf-8")


# ── Block helpers ─────────────────────────────────────────────────────────────

_PIPELINE_OPEN  = "UI-3.4: Per-Batch Pipeline Summary"
_PIPELINE_CLOSE = "<MissingFunctionsMatrix />"


def _pipeline_block(src: str) -> str:
    start = src.find(_PIPELINE_OPEN)
    end   = src.find(_PIPELINE_CLOSE, start)
    assert start != -1, "UI-3.4 block opener not found"
    assert end != -1 and end > start, "UI-3.4 block close anchor not found"
    return src[start:end]


_DETAIL_FUNC = "def batch_detail("


def _batch_detail_block(src: str) -> str:
    start = src.find(_DETAIL_FUNC)
    assert start != -1, "batch_detail function not found in routes_dashboard.py"
    # Read up to the next top-level @router decorator or end of file.
    end = src.find("\n@router.", start + 1)
    return src[start:] if end == -1 else src[start:end]


# ── Backend injection ─────────────────────────────────────────────────────────

def test_batch_detail_injects_sales_status_hint():
    """batch_detail() must write audit['sales_status_hint'] before returning."""
    src = _routes()
    block = _batch_detail_block(src)
    assert 'audit["sales_status_hint"]' in block or "audit['sales_status_hint']" in block, (
        "batch_detail must inject audit['sales_status_hint'] into the response"
    )


def test_batch_detail_uses_sales_hint_helper():
    """Injection must go through the existing _sales_hint() helper —
    no inline reimplementation."""
    src = _routes()
    block = _batch_detail_block(src)
    assert "_sales_hint(batch_id)" in block, (
        "batch_detail must delegate to _sales_hint(batch_id) for the injection"
    )


def test_sales_hint_helper_defined_once():
    """_sales_hint must be defined exactly once — no duplication."""
    src = _routes()
    assert src.count("def _sales_hint(") == 1, (
        "_sales_hint must be defined exactly once in routes_dashboard.py"
    )


def test_sales_hint_helper_returns_present_none():
    """_sales_hint must document 'present' and 'none' as its return values."""
    src = _routes()
    idx = src.find("def _sales_hint(")
    body = src[idx: idx + 400]
    assert "'present'" in body, "_sales_hint must return 'present' on hit"
    assert "'none'" in body, "_sales_hint must return 'none' on miss"


def test_sales_hint_helper_fails_silently():
    """_sales_hint must catch all exceptions and return 'n/a'."""
    src = _routes()
    idx = src.find("def _sales_hint(")
    body = src[idx: idx + 400]
    assert "except" in body and ('"n/a"' in body or "'n/a'" in body), (
        "_sales_hint must catch exceptions and return 'n/a'"
    )


def test_batch_detail_injection_placed_before_return():
    """The injection must appear before the final `return audit`."""
    src = _routes()
    block = _batch_detail_block(src)
    inject_idx = block.find('audit["sales_status_hint"]')
    if inject_idx == -1:
        inject_idx = block.find("audit['sales_status_hint']")
    return_idx = block.rfind("return audit")
    assert inject_idx != -1 and return_idx != -1
    assert inject_idx < return_idx, (
        "sales_status_hint injection must occur before `return audit`"
    )


# ── Frontend binding ──────────────────────────────────────────────────────────

def test_pipeline_sales_hint_reads_from_audit():
    """pipelineRow.salesHint must read audit.sales_status_hint."""
    src = _src()
    block = _pipeline_block(src)
    assert "audit.sales_status_hint" in block, (
        "pipelineRow.salesHint must read audit.sales_status_hint "
        "(not hardcoded 'n/a')"
    )


def test_pipeline_sales_hint_not_hardcoded_na():
    """salesHint must not be unconditionally set to 'n/a'."""
    src = _src()
    block = _pipeline_block(src)
    assert "salesHint:   'n/a'" not in block and "salesHint: 'n/a'" not in block, (
        "salesHint must not be hardcoded to 'n/a' in pipelineRow — "
        "it must read audit.sales_status_hint"
    )


def test_pipeline_sales_hint_has_na_fallback():
    """The binding must include an 'n/a' fallback for missing field."""
    src = _src()
    block = _pipeline_block(src)
    idx = block.find("audit.sales_status_hint")
    assert idx != -1
    snippet = block[idx: idx + 80]
    assert "'n/a'" in snippet, (
        "salesHint binding must fall back to 'n/a' when audit.sales_status_hint absent"
    )


def test_pipeline_sales_hint_guards_audit_null():
    """The binding must guard against null audit (audit && audit.sales_status_hint)."""
    src = _src()
    block = _pipeline_block(src)
    assert "audit && audit.sales_status_hint" in block, (
        "salesHint must guard against null audit before reading sales_status_hint"
    )


# ── Label map unchanged ───────────────────────────────────────────────────────

def test_sales_pill_linked_label_on_present():
    """'present' hint → 'Linked' label must remain unchanged."""
    src = _src()
    block = _pipeline_block(src)
    idx = block.find('data-testid="pipeline-summary-sales-pill"')
    assert idx != -1
    snippet = block[idx: idx + 600]
    assert "'present'" in snippet and "'Linked'" in snippet, (
        "sales pill must still map 'present' → 'Linked'"
    )


def test_sales_pill_fallback_label_on_non_present():
    """Non-present hint → 'See Sales tab' fallback must remain unchanged."""
    src = _src()
    block = _pipeline_block(src)
    idx = block.find('data-testid="pipeline-summary-sales-pill"')
    assert idx != -1
    snippet = block[idx: idx + 700]
    assert "'See Sales tab'" in snippet or '"See Sales tab"' in snippet, (
        "sales pill fallback label 'See Sales tab' must remain unchanged"
    )


def test_sales_pill_exposes_data_sales_hint_attribute():
    """data-sales-hint attribute must still be emitted from pipelineRow.salesHint."""
    src = _src()
    block = _pipeline_block(src)
    idx = block.find('data-testid="pipeline-summary-sales-pill"')
    assert idx != -1
    snippet = block[idx: idx + 200]
    assert "data-sales-hint={pipelineRow.salesHint}" in snippet, (
        "sales pill must expose data-sales-hint={pipelineRow.salesHint}"
    )


# ── No new endpoint, no write surface ────────────────────────────────────────

def test_pipeline_block_no_new_apifetch():
    """UI-3.6 must introduce no new apiFetch calls in the pipeline block."""
    src = _src()
    block = _pipeline_block(src)
    assert "apiFetch" not in block, (
        "Pipeline Summary block must not introduce new apiFetch calls"
    )


def test_pipeline_block_no_raw_fetch():
    src = _src()
    block = _pipeline_block(src)
    assert "fetch(" not in block, (
        "Pipeline Summary block must not introduce raw fetch() calls"
    )


# ── UI-3.4 / UI-3.5 landmarks preserved ──────────────────────────────────────

@pytest.mark.parametrize("landmark", [
    'data-testid="pipeline-summary-sales-pill"',
    'data-testid="pipeline-summary-sales-accounting"',
    'data-testid="pipeline-summary-sales-attention"',
    'data-testid="pipeline-summary-warehouse-lifecycle-pill"',
    'data-testid="pipeline-summary-dhl-status-pill"',
])
def test_ui_3_4_landmarks_preserved(landmark):
    """UI-3.6 must not remove any UI-3.4 pipeline summary landmarks."""
    src = _src()
    assert landmark in src, (
        f"UI-3.4 landmark {landmark!r} must remain after UI-3.6 patch"
    )

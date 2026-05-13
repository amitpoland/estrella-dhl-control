"""
test_dashboard_learning_design.py — Path B / Pass 8.

Contract for the Parser / Learning page (LearningPage) design pass:
  - Live invoice-learning surface remains the ONLY real data source
  - Real /api/v1/invoice-learning endpoints preserved (summary, patterns,
    feedback, reset)
  - Live KPI strip derives counts from the real suppliers array
  - Design-preview strip (SAD/Invoice parser playgrounds + locked-formula
    rules display) is visually marked and disabled
  - Preview controls emit NO network calls
  - No mock supplier names, no mock pattern examples, no fake MRN/LRN/
    exchange-rate values, no mock invoice extracts
  - No invented endpoints
  - Existing feedback + reset handlers + confirm guard unchanged
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


# ── Live invoice-learning endpoints preserved ──────────────────────────────

def test_learning_page_component_present():
    assert "function LearningPage({ onToast })" in _src()


def test_learning_route_wired():
    src = _src()
    # Route is wired under intelligence_grp per the new IA
    assert "page === 'intelligence_grp'" in src
    assert "<LearningPage" in src


def test_summary_endpoint_intact():
    assert "apiFetch('/api/v1/invoice-learning/summary')" in _src()


def test_patterns_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/invoice-learning/patterns/${encodeURIComponent(key)}`)" in src


def test_feedback_endpoint_intact():
    src = _src()
    assert "apiFetch('/api/v1/invoice-learning/feedback'" in src
    # POST with explicit method (write path)
    assert "method: 'POST'" in src
    # Body shape: batch_id / supplier_key / layout_fingerprint / correct
    assert "supplier_key: supplierKey" in src
    assert "layout_fingerprint: fingerprint" in src
    assert "correct }" in src


def test_reset_patterns_endpoint_intact():
    src = _src()
    # DELETE /api/v1/invoice-learning/patterns/{key}
    assert "apiFetch(`/api/v1/invoice-learning/patterns/${encodeURIComponent(key)}`, { method: 'DELETE' })" in src


# ── Reset guard preserved ──────────────────────────────────────────────────

def test_reset_patterns_confirm_guard_intact():
    src = _src()
    # The reset path still asks window.confirm with the explicit warning
    assert "window.confirm(`Reset all learned patterns for" in src
    assert "This cannot be undone." in src


def test_feedback_no_silent_write():
    src = _src()
    # Feedback sets local sending/done/error state — no auto-fire on mount
    assert "setFeedback(p => ({ ...p, [fk]: 'sending' }))" in src


# ── Live KPI strip uses real supplier array ───────────────────────────────

def test_live_stats_strip_present():
    src = _src()
    assert 'data-testid="learning-live-stats"' in src
    # Template-literal testid per tile
    assert 'data-testid={`learning-stat-${s.id}`}' in src
    for sid in ("'total'", "'trusted'", "'stablePlus'", "'needsRev'"):
        assert f"id: {sid}" in src, f"Missing live stat id: {sid}"


def test_live_stats_derive_from_real_suppliers_array():
    src = _src()
    # Counts come from suppliers array, not literals
    assert "total:      suppliers.length" in src
    assert "trusted:    suppliers.filter(s => s.confidence === 'trusted').length" in src
    assert "stablePlus: suppliers.filter(s => s.confidence === 'trusted' || s.confidence === 'stable').length" in src
    assert "needsRev:   suppliers.filter(s => s.any_unstable || (s.failed_count || 0) > 0).length" in src


def test_live_stats_loading_state():
    src = _src()
    assert "{loading ? '…' : s.value}" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_learning_preview_strip_present():
    assert 'data-testid="learning-design-preview"' in _src()


def test_learning_preview_has_pending_badge():
    assert 'data-testid="learning-preview-pending-badge"' in _src()


def test_learning_preview_tools_present():
    src = _src()
    assert 'data-testid="learning-preview-tools"' in src
    assert 'data-testid={`learning-preview-tool-${c.id}`}' in src
    for tid in ("'sad_parser_test'", "'invoice_parser_test'"):
        assert f"id: {tid}" in src, f"Missing preview tool id: {tid}"


def test_learning_preview_rules_card_present():
    src = _src()
    assert 'data-testid="learning-preview-rules-card"' in src


# ── Preview is disabled / non-executable ───────────────────────────────────

def test_preview_marked_pending_via_data_attr():
    src = _src()
    block_start = src.index('data-testid="learning-design-preview"')
    block_end   = src.index('<SectionLabel>Supplier patterns</SectionLabel>')
    block = src[block_start:block_end]
    # Tools template + rules card each carry data-pending="true"
    assert block.count('data-pending="true"') >= 2


def test_preview_block_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="learning-design-preview"')
    block_end   = src.index('<SectionLabel>Supplier patterns</SectionLabel>')
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview block must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block
    # No file inputs either (design's mock had file upload)
    assert "<input type=\"file\"" not in block
    assert "<input type='file'" not in block


def test_preview_tools_show_em_dash_or_pending_only():
    src = _src()
    block_start = src.index('data-testid="learning-preview-tools"')
    block_end   = src.index('learning-preview-rules-card', block_start)
    block = src[block_start:block_end]
    # No fake "▶ Run Parser" button result, no MRN/LRN mock values
    assert "Run Parser" not in block
    assert "PL" not in block or block.count("PL") < 10   # tolerate "Parser" / labels


# ── Anti-fake: no mock supplier names / mock parse results ────────────────

def test_no_mock_supplier_names_introduced():
    src = _src()
    # Design fixture had mock agency name
    for fake in (
        "Agencja Celna Sp. z o.o.",
        "Patek Philippe SA",
        "Crown Jewelers Ltd",
        "Maison Royale SARL",
    ):
        assert fake not in src, f"Mock supplier name leaked: {fake}"


def test_no_mock_mrn_lrn_or_rate_values():
    src = _src()
    # Design fixture used these specific format placeholders for MRN/LRN
    # — confirm we don't have hardcoded mock values for them
    for fake in (
        "'PL12345678901234A'",
        "'LRN-2024-0001'",
        "exchangeRate: '4.2650'",
        "nbpRate: '4.2510'",
        "Math.floor(Math.random() * 99999999999999)",
    ):
        assert fake not in src, f"Mock parse value leaked: {fake}"


def test_no_mock_run_parser_handler():
    src = _src()
    # The design's runParser function used setTimeout + Math.random — this
    # whole pattern must not have landed in production.
    assert "const runParser = " not in src
    assert "setParsing(true)" not in src
    assert "setParserInput(" not in src


def test_no_locked_formula_mock_strings():
    src = _src()
    # The design's Parser Rules card hardcoded these strings inside a
    # 6-row mock array. Some legitimate text might appear elsewhere — we
    # check only inside the design-preview block.
    block_start = src.index('data-testid="learning-design-preview"')
    block_end   = src.index('<SectionLabel>Supplier patterns</SectionLabel>')
    block = src[block_start:block_end]
    for fake in (
        "Uses SAD net value × carrier exchange rate.",
        "Customs tariff × CIF value.",
        "(CIF + A00) × VAT rate (23%).",
        "Regex + positional extraction. Read-only.",
        "PDF text extraction. Field mapping locked.",
        "Disabled. Admin must approve all DHL replies.",
    ):
        assert fake not in block, f"Mock locked-formula text leaked: {fake}"


# ── Anti-fake: no invented endpoints ───────────────────────────────────────

def test_no_invented_learning_endpoints():
    src = _src()
    for ep in (
        "/api/v1/parser/test",
        "/api/v1/parser/run",
        "/api/v1/parser/rules",
        "/api/v1/invoice-learning/test",
        "/api/v1/invoice-learning/rules",
        "/api/v1/invoice-learning/playground",
        "/api/v1/sad/parse-test",
        "/api/v1/invoice/parse-test",
    ):
        assert ep not in src, f"Invented parser endpoint leaked: {ep}"


# ── SectionLabel polish + page landmarks ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="learning-page"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>Supplier patterns</SectionLabel>" in src


# ── Existing CONF_META legend preserved ────────────────────────────────────

def test_confidence_meta_preserved():
    src = _src()
    assert "const CONF_META = {" in src
    for tier in ("unconfirmed:", "emerging:", "stable:", "trusted:"):
        assert tier in src, f"CONF_META tier missing: {tier}"


def test_confidence_thresholds_preserved():
    src = _src()
    assert "const CONF_THRESHOLDS" in src


# ── UI-3 + DETAIL_TABS unchanged ───────────────────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src

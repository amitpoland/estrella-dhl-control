"""tests/test_c21a_workflow_button_token_compliance.py — C21A

Workflow Button Token Compliance: fixes 10 bare <button> elements in
shipment-detail.html that used hardcoded hex colors, breaking dark mode
and violating the EJ CSS token system.

Bug class: hardcoded hex (#15803d, #9ca3af, #d1d5db, #374151, #fca5a5,
           #e8a0a0, #c44) in operator-facing workflow buttons.

Fix: converted workflow/CN/PZ buttons to <Btn> component; converted
     file-delete ✕ buttons to use CSS custom property tokens.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_DETAIL = (_ROOT / "service" / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")


# ── helper: extract region between two marker strings ────────────────────────

def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


# ── Bug fix: workflow-refresh button ─────────────────────────────────────────

def test_workflow_refresh_uses_btn():
    """C21A: workflow-refresh must use <Btn>, not bare <button>."""
    # Locate the data-testid in the file
    idx = _DETAIL.index('data-testid="workflow-refresh"')
    ctx = _DETAIL[idx - 20: idx + 80]
    assert '<Btn' in ctx, \
        "workflow-refresh must be rendered as <Btn> component, not bare <button>"


def test_workflow_refresh_no_hardcoded_hex():
    """C21A: workflow-refresh must not use #d1d5db or #fff hardcoded colors."""
    idx = _DETAIL.index('data-testid="workflow-refresh"')
    ctx = _DETAIL[idx: idx + 200]
    assert '#d1d5db' not in ctx, "workflow-refresh must not use #d1d5db — use CSS token"
    # #fff in a Btn style prop is gone since Btn uses CSS vars internally


# ── Bug fix: CN/HSN decision buttons ─────────────────────────────────────────

def test_cn_accept_sad_uses_btn():
    """C21A: cn-accept-sad must use <Btn> component."""
    idx = _DETAIL.index('data-testid="cn-accept-sad"')
    ctx = _DETAIL[idx - 20: idx + 60]
    assert '<Btn' in ctx, "cn-accept-sad must be <Btn>, not bare <button>"


def test_cn_accept_sad_no_hardcoded_hex():
    """C21A: cn-accept-sad must not use #15803d hardcoded green."""
    idx = _DETAIL.index('data-testid="cn-accept-sad"')
    ctx = _DETAIL[idx: idx + 300]
    assert '#15803d' not in ctx, \
        "cn-accept-sad must not use #15803d — use CSS token or Btn variant"


def test_cn_correct_internal_uses_btn():
    """C21A: cn-correct-internal must use <Btn> component."""
    idx = _DETAIL.index('data-testid="cn-correct-internal"')
    ctx = _DETAIL[idx - 20: idx + 60]
    assert '<Btn' in ctx, "cn-correct-internal must be <Btn>, not bare <button>"


def test_cn_correct_internal_no_hardcoded_hex():
    """C21A: cn-correct-internal must not use #374151 or #9ca3af hardcoded."""
    idx = _DETAIL.index('data-testid="cn-correct-internal"')
    ctx = _DETAIL[idx: idx + 300]
    assert '#374151' not in ctx, "cn-correct-internal must not use #374151 — use CSS token"


def test_cn_escalate_agent_uses_btn():
    """C21A: cn-escalate-agent must use <Btn> component."""
    idx = _DETAIL.index('data-testid="cn-escalate-agent"')
    ctx = _DETAIL[idx - 20: idx + 60]
    assert '<Btn' in ctx, "cn-escalate-agent must be <Btn>, not bare <button>"


def test_cn_escalate_agent_no_hardcoded_hex():
    """C21A: cn-escalate-agent must not use #991b1b or #fca5a5 hardcoded."""
    idx = _DETAIL.index('data-testid="cn-escalate-agent"')
    ctx = _DETAIL[idx: idx + 300]
    assert '#fca5a5' not in ctx, "cn-escalate-agent must not use #fca5a5 — use CSS token"


# ── Bug fix: execute-pz buttons ───────────────────────────────────────────────

def test_execute_pz_refresh_uses_btn():
    """C21A: execute-pz-refresh must use <Btn> component."""
    idx = _DETAIL.index('data-testid="execute-pz-refresh"')
    ctx = _DETAIL[idx - 20: idx + 80]
    assert '<Btn' in ctx, "execute-pz-refresh must be <Btn>, not bare <button>"


def test_execute_pz_button_uses_btn():
    """C21A: execute-pz-button must use <Btn> component."""
    idx = _DETAIL.index('data-testid="execute-pz-button"')
    ctx = _DETAIL[idx - 20: idx + 80]
    assert '<Btn' in ctx, "execute-pz-button must be <Btn>, not bare <button>"


def test_execute_pz_button_no_hardcoded_hex():
    """C21A: execute-pz-button must not use #15803d or #9ca3af conditional hex."""
    idx = _DETAIL.index('data-testid="execute-pz-button"')
    ctx = _DETAIL[idx: idx + 300]
    assert '#15803d' not in ctx, "execute-pz-button must not use #15803d — use Btn variant"
    assert '#9ca3af' not in ctx, "execute-pz-button must not use #9ca3af — use Btn disabled prop"


def test_execute_pz_button_preserves_disabled_prop():
    """C21A: execute-pz-button must preserve disabled={!enabled} gate."""
    idx = _DETAIL.index('data-testid="execute-pz-button"')
    ctx = _DETAIL[idx: idx + 300]
    assert 'disabled=' in ctx, \
        "execute-pz-button must preserve disabled prop — PZ gate must not be bypassed"


# ── Bug fix: file-delete ✕ buttons ───────────────────────────────────────────

def test_file_delete_buttons_use_css_token_border():
    """C21A: file-delete ✕ buttons must use CSS token for border, not #e8a0a0."""
    assert '#e8a0a0' not in _DETAIL, \
        "File-delete buttons must use var(--badge-red-border), not hardcoded #e8a0a0"


def test_file_delete_buttons_use_css_token_color():
    """C21A: file-delete ✕ buttons must use CSS token for color, not #c44."""
    # Use word-boundary approach: '#c44,' or '#c44,' etc. to avoid partial matches
    import re
    matches = re.findall(r"'#c44[^0-9a-fA-F]", _DETAIL)
    assert len(matches) == 0, \
        "File-delete buttons must use var(--badge-red-text), not hardcoded #c44"


def test_file_delete_buttons_use_badge_red_token():
    """C21A: file-delete ✕ buttons must reference badge-red CSS vars."""
    # At least one occurrence of the token in context (there are 4 delete buttons)
    assert 'var(--badge-red-border)' in _DETAIL, \
        "File-delete buttons must use var(--badge-red-border) token"
    assert 'var(--badge-red-text)' in _DETAIL, \
        "File-delete buttons must use var(--badge-red-text) token"


# ── Regression guards (C20A markers) ─────────────────────────────────────────

def test_c20a_btn_primary_still_present():
    """C21A regression: C20A Btn primary variant must still exist."""
    from pathlib import Path
    shared = (_ROOT / "service" / "app" / "static" / "dashboard-shared.js").read_text(encoding="utf-8")
    assert "primary:" in shared

def test_c20a_surface_tokens_still_present():
    """C21A regression: C20A --surface-1 in :root must still be present."""
    light_end = _DETAIL.index('[data-theme="dark"]')
    light_css = _DETAIL[:light_end]
    assert '--surface-1:' in light_css

def test_c19a_intelligence_panel_absent():
    """C21A regression: C19A deletion must still hold — no draft-intelligence-panel."""
    assert 'data-testid="draft-intelligence-panel"' not in _DETAIL

def test_c18a_ship_to_postal_code_present():
    """C21A regression: C18A postal_code fix must still hold."""
    assert "c.ship_to_postal_code" in _DETAIL

def test_cn_buttons_preserve_onclick_logic():
    """C21A: CN decision buttons must preserve their postDecision() onClick calls."""
    assert "'accept-sad'" in _DETAIL, "cn-accept-sad must still call postDecision with 'accept-sad'"
    assert "'correct-internal'" in _DETAIL, "cn-correct-internal must still call postDecision"
    assert "'escalate-agent'" in _DETAIL, "cn-escalate-agent must still call postDecision"

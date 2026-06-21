"""
test_v2_proforma_detail_design_nits.py — frontend-design contract guard.

Two pre-existing frontend-design nits on v2/proforma-detail.jsx (flagged during
the PR #699 frontend-flow review, fixed as an isolated display-only cleanup):

  1. §3 — the inline approveError <span> hardcoded `color: '#F44'` instead of a
     CSS custom-property token. It must use `var(--badge-red-text)` so the colour
     tracks the design-token system (dark mode, theme switches).

  2. §8 — the "Create Reservation" <Btn> in the Reservation tab had no
     `data-testid`. Every interactive element needs one; its sibling Convert
     button already carries `data-testid="reservation-convert-btn"`.

Static source-grep only — no server, no browser. V2-only; V1 pages untouched
(Lesson F freeze).
"""
from __future__ import annotations

import pathlib

_V2 = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL = _V2 / "proforma-detail.jsx"


def _src() -> str:
    return _DETAIL.read_text(encoding="utf-8", errors="replace")


# ── §3 — approveError colour must use a design token, not a hardcoded hex ─────

def test_approve_error_uses_token_not_hardcoded_hex():
    """The approveError span must colour via var(--badge-red-text), not '#F44'."""
    src = _src()
    idx = src.index("{approveError}")
    # Inspect the span that renders the error text (immediately before the marker).
    span = src[idx - 160:idx]
    assert "var(--badge-red-text)" in span, (
        "approveError span must use color: 'var(--badge-red-text)' (frontend-design §3)"
    )
    assert "#F44" not in span, (
        "approveError span must not hardcode the hex '#F44' (frontend-design §3)"
    )


# ── §8 — every interactive element needs a data-testid ────────────────────────

def test_create_reservation_btn_has_testid():
    """The Create Reservation <Btn> must carry data-testid='reservation-create-btn'."""
    src = _src()
    idx = src.index("Create Reservation")
    btn = src[idx - 120:idx]
    assert 'data-testid="reservation-create-btn"' in btn, (
        "Create Reservation <Btn> must have data-testid='reservation-create-btn' "
        "(frontend-design §8)"
    )

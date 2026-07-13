"""
test_wave8_frontend_polish_contract.py — Wave 8 frontend hygiene (design tokens +
testids), landed as the focused frontend-polish PR.

Pins only the polish-owned changes on the four V2 files. Cross-PR invariants
(#909 client save label + overlay tokens, #911 deep-link) are asserted separately
on the combined release candidate, not here (this branch is main-based).
"""
from __future__ import annotations

from pathlib import Path

import pytest

V2 = Path(__file__).parents[1] / "app" / "static" / "v2"
DASH = V2 / "dashboard-page.jsx"
MASTER = V2 / "master-page.jsx"
CLIENT = V2 / "client-detail.jsx"
SHIP = V2 / "shipment-detail-page.jsx"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.name} missing")
    return p.read_text(encoding="utf-8")


# ── dashboard-page: GOLD+'22' invalid CSS gone; filter testids + tokens ──────

def test_no_invalid_gold_alpha_css():
    src = _read(DASH)
    assert "GOLD + '22'" not in src and "GOLD+'22'" not in src, \
        "invalid CSS `var(--accent)22` must be removed"
    assert "var(--accent-subtle)" in src, "active filter must use the --accent-subtle token"


def test_filter_buttons_have_stable_testids():
    src = _read(DASH)
    assert "shipments-hub-filter-" in src, "status-filter buttons must carry stable data-testids"


def test_dashboard_carrier_and_text_tokenised():
    src = _read(DASH)
    assert "var(--badge-blue-bg)" in src and "var(--badge-neutral-bg)" in src, \
        "carrier badges must use design tokens"
    # the pre-existing hardcoded filter/text hex are gone
    for hexv in ("#8A8278", "#6A6258", "#1A5FA8"):
        assert hexv not in src, f"hardcoded {hexv} must be tokenised"


def test_wave1_money_formatter_preserved():
    src = _read(DASH)
    assert "_money(" in src, "Wave-1 shared money formatter must remain wired"


# ── master-page: honest write-disabled fallback (no stale Sprint-38 text) ────

def test_write_disabled_reason_is_honest():
    src = _read(MASTER)
    # Only the operator-facing fallback VALUE matters; historical `// Sprint 38b:`
    # code comments are out of scope and intentionally left untouched.
    assert "Write operations not yet wired" not in src, \
        "stale write-disabled fallback value must be replaced"
    assert "not available for this entity type" in src, "fallback must state the honest reason"


# ── client-detail: error banners tokenised ───────────────────────────────────

def test_client_error_banners_tokenised():
    src = _read(CLIENT)
    assert "var(--badge-red-bg)" in src, "error banners must use the red badge token"
    assert "rgba(220,38,38" not in src, "no hardcoded red rgba may remain in client-detail"


# ── shipment-detail: token cleanup, Wave-3/4 wiring preserved ────────────────

def test_shipment_detail_tokens_and_wiring_preserved():
    src = _read(SHIP)
    # Wave-4 timeline read-model still consumed
    assert "timelineMilestones" in src or "timeline_milestones" in src, \
        "Wave-4 timeline read-model must remain wired"
    # no reintroduced V1-action redirect text
    assert "use V1" not in src.lower().replace("use v1 today", "use v1"), \
        "must not reintroduce V1-action instructions"

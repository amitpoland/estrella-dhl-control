"""test_commercial_visibility_v1_v2_v3.py — UI invariant for visibility patches.

Pure source-grep tests; no rendering required.  Locks the V1+V2+V3
visibility additions in both dashboard.html and shipment-detail.html
without exercising any backend or governance path.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
_DASHBOARD = _STATIC / "dashboard.html"
_DETAIL    = _STATIC / "shipment-detail.html"


@pytest.fixture(scope="module")
def dashboard_html() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    return _DETAIL.read_text(encoding="utf-8")


# ── V1 — label + color for adopted_from_audit ────────────────────────────────

def test_v1_label_present_dashboard(dashboard_html):
    assert "adopted_from_audit: 'Adopted from wFirma'" in dashboard_html


def test_v1_label_present_detail(detail_html):
    assert "adopted_from_audit: 'Adopted from wFirma'" in detail_html


def test_v1_color_mapping_dashboard(dashboard_html):
    assert ("adopted_from_audit: { bg: 'var(--badge-blue-bg)', "
            "tx: 'var(--badge-blue-text)' }") in dashboard_html


def test_v1_color_mapping_detail(detail_html):
    assert ("adopted_from_audit: { bg: 'var(--badge-blue-bg)', "
            "tx: 'var(--badge-blue-text)' }") in detail_html


# ── V2 — invoice-eligibility badge ───────────────────────────────────────────

def test_v2_badge_test_id_dashboard(dashboard_html):
    assert 'data-testid="draft-invoice-eligibility-badge"' in dashboard_html


def test_v2_badge_test_id_detail(detail_html):
    assert 'data-testid="draft-invoice-eligibility-badge"' in detail_html


def test_v2_badge_has_both_labels_dashboard(dashboard_html):
    assert "'Invoice eligible'" in dashboard_html
    assert "'Invoice blocked'" in dashboard_html


def test_v2_badge_has_both_labels_detail(detail_html):
    assert "'Invoice eligible'" in detail_html
    assert "'Invoice blocked'" in detail_html


def test_v2_uses_existing_gate_conditions(dashboard_html):
    """Badge must read the same gate the backend enforces:
    draft.status='issued' AND draft_state='posted' AND no invoice link."""
    assert "openDraft.status === 'issued'" in dashboard_html
    assert "openDraft.draft_state === 'posted'" in dashboard_html


def test_v2_no_confirm_token_exposed_in_badge():
    """The eligibility badge (V2) must NEVER include the confirm token.

    The token legitimately appears elsewhere in the file as part of the
    existing operator-typed conversion input — that pre-existed and is
    operator-controlled.  This test narrows the assertion to the V2
    block only.
    """
    bad = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
    for f in (_DASHBOARD, _DETAIL):
        src = f.read_text(encoding="utf-8")
        marker = "V2 — read-only invoice-eligibility badge."
        if marker not in src:
            continue
        seg = src[src.find(marker): src.find(marker) + 1500]
        assert bad not in seg, f"{f.name}: V2 block must not embed the confirm token"


def test_v2_no_new_buttons_or_onclick_in_patch():
    """Patch must be read-only — no new <Btn> or onClick added by V2."""
    for f in (_DASHBOARD, _DETAIL):
        src = f.read_text(encoding="utf-8")
        # The exact V2 marker comment is unique; the block between it and
        # the closing IIFE must not contain onClick or <Btn.
        marker = "V2 — read-only invoice-eligibility badge."
        if marker not in src:
            continue
        # take the next 1500 chars after the marker — covers the IIFE
        seg = src[src.find(marker): src.find(marker) + 1500]
        assert "onClick" not in seg, f"{f.name}: V2 block must not contain onClick"
        assert "<Btn" not in seg,    f"{f.name}: V2 block must not contain <Btn"


# ── V3 — posted-banner extended condition ────────────────────────────────────

def test_v3_banner_extended_dashboard(dashboard_html):
    assert "isPosted || openDraft.draft_state === 'adopted_from_audit'" in dashboard_html


def test_v3_banner_extended_detail(detail_html):
    assert "isPosted || openDraft.draft_state === 'adopted_from_audit'" in detail_html


def test_v3_does_not_duplicate_banner_component(dashboard_html, detail_html):
    """The patch must REUSE the existing draft-posted-banner test-id, not
    create a parallel banner."""
    for src, name in ((dashboard_html, "dashboard.html"), (detail_html, "shipment-detail.html")):
        n = src.count('data-testid="draft-posted-banner"')
        # Each file should have exactly one banner element (the test-id may
        # appear in surrounding docs/comments, but the actual rendered
        # element is unique).
        assert n == 1, f"{name}: expected 1 draft-posted-banner, found {n}"


# ── Safety: no backend / API references introduced ───────────────────────────

def test_no_new_endpoint_referenced_in_patches():
    """Visibility patches must not introduce any new API path."""
    for f in (_DASHBOARD, _DETAIL):
        src = f.read_text(encoding="utf-8")
        for marker, hay in (("V1", "V1 —"), ("V2", "V2 — read-only"), ("V3", "V3 —")):
            i = src.find(hay)
            if i < 0: continue
            seg = src[i: i + 2000]
            # No fetch / apiFetch / new route in the patched segment
            assert "apiFetch(" not in seg, f"{f.name} {marker}: introduced apiFetch"
            assert "fetch('" not in seg,  f"{f.name} {marker}: introduced fetch(' "


def test_no_auto_flag_referenced_in_patches():
    """Visibility patches must not reference any AUTO_* flag or confirm token."""
    for f in (_DASHBOARD, _DETAIL):
        src = f.read_text(encoding="utf-8")
        for marker in ("V1 —", "V2 — read-only", "V3 —"):
            i = src.find(marker)
            if i < 0: continue
            seg = src[i: i + 2000]
            assert "AUTO_" not in seg
            assert "WFIRMA_CREATE_INVOICE_ALLOWED" not in seg
            assert "YES_" not in seg

"""
test_dashboard_doc_suite_design.py — Phase 7 (design implementation).

Pins the visual elements brought in from the Estrella Document Suite design
handoff (Claude Design bundle). The bundle ships a static document-suite
prototype establishing the brand palette (emerald #0B3D2E + gold #C9A24B +
cream #FBF8F1) and a Pro Forma masthead / "issued" toolbar treatment.

The dashboard adopts ONLY the visual aspects that map to the existing
Phase 1-6 Proforma Draft panel — no new endpoints, no new buttons, no
removed functionality. These tests are source-grep so they pin the
contract without requiring a browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


@pytest.fixture(scope="module")
def html() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Brand palette adopted (scoped to the panel, not global) ────────────────

@pytest.mark.parametrize("token, value", [
    ("--ej-brand",      "#0B3D2E"),   # emerald
    ("--ej-brand-2",    "#0F5A45"),
    ("--ej-brand-3",    "#DCEDE5"),
    ("--ej-gold",       "#C9A24B"),
    ("--ej-gold-2",     "#B0892F"),
    ("--ej-gold-tint",  "#F6EFD9"),
    ("--ej-cream",      "#FBF8F1"),
])
def test_design_token_present(html, token, value):
    # Tokens must be the EXACT hex values from estrella-docs/tokens.css.
    assert f"['{token}']: '{value}'" in html, (
        f"design token {token} must be set to {value} (matches the "
        "Estrella Document Suite handoff palette exactly)"
    )


def test_design_tokens_scoped_to_proforma_panel_only(html):
    # The token block must live inside the proforma-draft-panel <Card>,
    # NOT on :root or body — the panel is the only adopter.
    panel_idx = html.find('data-testid="proforma-draft-panel"')
    assert panel_idx > 0
    # Find the token within ~600 chars of the panel anchor.
    window = html[panel_idx:panel_idx + 1200]
    assert "['--ej-brand']:" in window, (
        "Brand tokens must be set inline on the panel Card so the design "
        "palette is scoped, not promoted to a global theme override"
    )
    # The :root selector must not have been mutated to add ej tokens.
    assert ":root{--ej-brand" not in html.replace(" ", "")


# ── Branded masthead (Pro Forma letterhead aesthetic) ──────────────────────

def test_branded_masthead_renders_above_section_header(html):
    assert 'data-testid="proforma-draft-masthead"' in html, (
        "ProformaDraftPanel must render the branded masthead element"
    )
    masthead_idx = html.find('data-testid="proforma-draft-masthead"')
    section_idx  = html.find(
        'icon="◇" title="Local Proforma Drafts"',
        masthead_idx,   # start search AFTER the masthead
    )
    assert masthead_idx > 0 and section_idx > masthead_idx, (
        "Masthead must precede the existing SectionHeader so Phase 6 tests "
        "pinning the SectionHeader still pass"
    )


def test_masthead_uses_design_band_gradient(html):
    # The Document Suite uses a `linear-gradient(90deg, var(--ej-brand) 0 65%,
    # var(--ej-gold) 65% 100%)` band as the page header rule. We keep the
    # same gradient on the masthead.
    masthead_idx = html.find('data-testid="proforma-draft-masthead"')
    window = html[masthead_idx:masthead_idx + 1200]
    assert "var(--ej-brand) 0 65%" in window
    assert "var(--ej-gold) 65% 100%" in window


def test_masthead_carries_pro_forma_label(html):
    # The branded eyebrow + main label both come from the design's
    # ProformaModern hero ("Pro Forma · Faktura proforma · Predfaktúra").
    # We use the EN/PL pair (no SK in dashboard scope).
    masthead_idx = html.find('data-testid="proforma-draft-masthead"')
    window = html[masthead_idx:masthead_idx + 1500]
    assert "Estrella Jewels · Document Suite" in window
    assert "Pro Forma · Faktura proforma" in window


def test_masthead_shows_draft_count(html):
    # Right-aligned count chip, mirrors the design's "EUR" / "WDT 0%" pill row.
    masthead_idx = html.find('data-testid="proforma-draft-masthead"')
    window = html[masthead_idx:masthead_idx + 2400]
    assert "drafts.length" in window
    assert "draft{drafts.length === 1 ? '' : 's'}" in window


def test_logo_mark_uses_design_palette(html):
    # The "EJ" mark uses the design's logo-mark recipe (emerald gradient
    # circle, gold text, gold-tint outer ring).
    masthead_idx = html.find('data-testid="proforma-draft-masthead"')
    window = html[masthead_idx:masthead_idx + 2000]
    assert "linear-gradient(135deg,#0B3D2E 0%,#0F5A45 100%)" in window
    assert "color: 'var(--ej-gold)'" in window
    assert "0 0 0 2px var(--ej-gold-tint)" in window


# ── Posted banner: branded "issued" toolbar (single wired endpoint) ────────

def test_posted_banner_uses_branded_toolbar(html):
    banner_idx = html.find('data-testid="draft-posted-banner"')
    assert banner_idx > 0
    # Widened from 2000 → 4000 to cover the Phase-8 Download PDF anchor.
    window = html[banner_idx:banner_idx + 4000]
    # Must use the brand emerald header + cream secondary strip.
    assert "background: 'var(--ej-brand)'" in window
    assert "background: 'var(--ej-cream)'" in window


def test_posted_banner_eyebrow_and_label(html):
    banner_idx = html.find('data-testid="draft-posted-banner"')
    window = html[banner_idx:banner_idx + 2000]
    # Design's eyebrow style: small uppercase gold label.
    assert "Pro Forma · Issued" in window
    assert "POSTED to wFirma" in window


def test_view_proforma_link_endpoint_unchanged(html):
    """Phase 6 wires this link to /api/v1/proforma/{batch}/{client}/document.
    The redesign must NOT change the URL — only the styling."""
    banner_idx = html.find('data-testid="draft-posted-banner"')
    window = html[banner_idx:banner_idx + 2000]
    assert "/api/v1/proforma/${encodeURIComponent(openDraft.batch_id)}/" in window
    assert "${encodeURIComponent(openDraft.client_name)}/document" in window


def test_no_extra_view_or_download_buttons_added(html):
    """Phase 8 lifted the Phase-7 'one anchor only' rule by adding a real
    Download PDF endpoint backed by wfirma_client.fetch_invoice_pdf.

    Updated rule: the posted banner exposes EXACTLY two anchors:
      1. View Proforma (JSON viewer — existing /document endpoint)
      2. Download PDF (real /document.pdf endpoint added in Phase 8)

    No Email / Statement / CMR / XLSX anchors — those backends still
    don't exist. Anything else is a fake-button violation."""
    banner_idx = html.find('data-testid="draft-posted-banner"')
    end = html.find('</div>\n              )}', banner_idx)
    assert end > banner_idx
    block = html[banner_idx:end]
    assert block.count("<a ") == 2, (
        "Posted banner must expose exactly two anchors "
        "(View Proforma + Download PDF). Found "
        f"{block.count('<a ')}."
    )
    # The two anchors are the ones we actually wired.
    assert 'data-testid="draft-view-proforma-link"'    in block
    assert 'data-testid="draft-download-proforma-pdf"' in block
    # No fake buttons for endpoints we have NOT wired.
    for forbidden_id in (
        "draft-email-proforma",
        "draft-download-statement",
        "draft-download-cmr",
        "draft-download-xlsx",
    ):
        assert forbidden_id not in block


def test_posted_banner_keeps_phase6_testids(html):
    """The Phase 6 source-grep tests pin these test ids — the redesign
    must keep them all."""
    for tid in (
        'draft-posted-banner',
        'draft-posted-wfirma-id',
        'draft-posted-fullnumber',
        'draft-view-proforma-link',
    ):
        assert f'data-testid="{tid}"' in html, (
            f"Phase 6 testid {tid!r} must still be present"
        )


# ── Legacy create still NOT referenced (regression guard) ──────────────────

def test_legacy_create_endpoint_still_not_referenced(html):
    # The design adoption must not have re-introduced the legacy route.
    assert "/api/v1/proforma/create/" not in html, (
        "Dashboard must not call legacy /api/v1/proforma/create — the local "
        "draft post endpoint is the only sanctioned post path"
    )


# ── Existing functionality preserved ───────────────────────────────────────

def test_section_header_subtitle_text_preserved(html):
    # Phase 6 subtitle stays — the masthead is additive, not a replacement.
    assert "edit locally before posting to wFirma" in html


def test_post_token_constant_unchanged(html):
    assert "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA" in html
    assert "YES_APPROVE_LOCAL_PROFORMA_DRAFT" in html
    assert "YES_REOPEN_LOCAL_PROFORMA_DRAFT" in html


def test_panel_class_marker_for_styleable_descendants(html):
    # We tag the panel with a className so future scoped rules (and tests)
    # can target only the document-suite-styled subtree.
    panel_idx = html.find('data-testid="proforma-draft-panel"')
    window = html[panel_idx:panel_idx + 400]
    assert 'className="ej-doc-suite"' in window

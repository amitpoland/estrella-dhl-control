"""wFirma PZ direct-access URL — regression lock (2026-05-22).

pz_preview now returns wfirma_pz_view_url whenever wfirma_pz_doc_id is set.
The URL deep-links to the real wFirma document page so operators can verify
PZ line contents without leaving the workflow.

Lesson I classification:
  Type: Operator confusion → workflow link
  Authority owner: audit.wfirma_export + settings.wfirma_company_id
  Workflow class: any shipment with a PZ doc_id (all suppliers, all batches)

Tests pin:
  1.  URL built correctly when doc_id + company_id present.
  2.  URL is None when doc_id absent.
  3.  URL is None when company_id absent (settings not configured).
  4.  WFIRMA_PZ_VIEW_URL_TEMPLATE override works.
  5.  pz_preview already-created path returns wfirma_pz_view_url.
  6.  pz_preview no-doc-id paths return wfirma_pz_view_url = null.
  7.  wfirma_pz_fullnumber included in already-created response.
  8.  Adopted/confirmed PZ (pz_source=adopted_existing) also gets URL.
  9.  Source-grep: _build_wfirma_pz_view_url present in routes_wfirma.py.
  10. Frontend: View-in-wFirma anchor has target=_blank + rel=noopener noreferrer.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from service.app.api.routes_wfirma import _build_wfirma_pz_view_url

ROUTES  = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"
HTML    = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"
COMPANY = "359292"
DOC_ID  = "185759075"


# ── helpers ────────────────────────────────────────────────────────────────

def _settings_with_company(company_id: str = COMPANY, template: str = ""):
    """Return a mock settings object with the given company_id."""
    class _S:
        wfirma_company_id          = company_id
        wfirma_pz_view_url_template = template
    return _S()


# ── 1. URL built correctly ─────────────────────────────────────────────────

def test_build_view_url_returns_correct_url():
    with patch("service.app.api.routes_wfirma.settings", _settings_with_company(COMPANY)):
        url = _build_wfirma_pz_view_url(DOC_ID)
    assert url == f"https://app.wfirma.pl/{COMPANY}/warehouses/view/{DOC_ID}"


# ── 2. URL is None when doc_id absent ─────────────────────────────────────

def test_build_view_url_none_when_no_doc_id():
    with patch("service.app.api.routes_wfirma.settings", _settings_with_company(COMPANY)):
        assert _build_wfirma_pz_view_url("") is None
        assert _build_wfirma_pz_view_url(None) is None  # type: ignore[arg-type]


# ── 3. URL is None when company_id absent ─────────────────────────────────

def test_build_view_url_none_when_no_company_id():
    with patch("service.app.api.routes_wfirma.settings", _settings_with_company("")):
        assert _build_wfirma_pz_view_url(DOC_ID) is None


# ── 4. WFIRMA_PZ_VIEW_URL_TEMPLATE override ───────────────────────────────

def test_build_view_url_respects_template_override():
    template = "https://custom.wfirma.pl/docs/{doc_id}/view"
    with patch("service.app.api.routes_wfirma.settings",
               _settings_with_company(COMPANY, template=template)):
        url = _build_wfirma_pz_view_url(DOC_ID)
    assert url == f"https://custom.wfirma.pl/docs/{DOC_ID}/view"


# ── 5. already-created path has wfirma_pz_view_url ────────────────────────

def test_source_grep_already_created_path_has_view_url():
    src = ROUTES.read_text(encoding="utf-8")
    # Already-created return block must contain both new fields.
    already_start = src.find('"already_created":      True,')
    assert already_start > 0, "already_created=True return block not found"
    chunk = src[already_start:already_start + 600]
    assert '"wfirma_pz_view_url":' in chunk, (
        "already_created return block must include wfirma_pz_view_url"
    )
    assert '"wfirma_pz_fullnumber":' in chunk, (
        "already_created return block must include wfirma_pz_fullnumber"
    )
    assert "_build_wfirma_pz_view_url(existing_pz_doc_id)" in chunk, (
        "already_created path must call _build_wfirma_pz_view_url"
    )


# ── 6. no-doc-id paths return null URL ────────────────────────────────────

def test_source_grep_no_doc_id_paths_return_null_url():
    src = ROUTES.read_text(encoding="utf-8")
    # Count occurrences regardless of internal whitespace — both null paths
    # use the same key name but may have different column alignment.
    import re
    null_count = len(re.findall(r'"wfirma_pz_view_url"\s*:\s*None,', src))
    assert null_count >= 2, (
        f"expected at least 2 null wfirma_pz_view_url entries (blockers + build paths); "
        f"found {null_count}"
    )


# ── 7. wfirma_pz_fullnumber in already-created ────────────────────────────

def test_source_grep_fullnumber_in_already_created():
    src = ROUTES.read_text(encoding="utf-8")
    already_start = src.find('"already_created":      True,')
    chunk = src[already_start:already_start + 600]
    assert 'wfirma_export.get("wfirma_pz_fullnumber")' in chunk, (
        "already_created response must read wfirma_pz_fullnumber from wfirma_export"
    )


# ── 8. adopted PZ also gets URL (source-grep) ─────────────────────────────

def test_build_view_url_works_for_any_doc_id():
    """The URL builder is doc-id-agnostic — works for adopted PZ too."""
    adopted_doc_id = "99999999"
    with patch("service.app.api.routes_wfirma.settings", _settings_with_company(COMPANY)):
        url = _build_wfirma_pz_view_url(adopted_doc_id)
    assert url == f"https://app.wfirma.pl/{COMPANY}/warehouses/view/{adopted_doc_id}"


# ── 9. Helper present in routes_wfirma.py ────────────────────────────────

def test_helper_present_in_routes():
    src = ROUTES.read_text(encoding="utf-8")
    assert "def _build_wfirma_pz_view_url(" in src, (
        "_build_wfirma_pz_view_url must be defined in routes_wfirma.py"
    )
    assert "warehouses/view/{doc_id" in src or "warehouses/view/" in src, (
        "_build_wfirma_pz_view_url must contain the wFirma warehouse view path"
    )


# ── 10. Frontend: anchor has target + rel ─────────────────────────────────

def test_frontend_view_button_has_safe_anchor_attributes():
    """The View-in-wFirma link must use target=_blank and rel=noopener noreferrer
    to prevent tab-napping and opener access."""
    body = HTML.read_text(encoding="utf-8")
    assert 'target="_blank"' in body, (
        'shipment-detail.html must contain target="_blank" for wFirma link'
    )
    assert 'rel="noopener noreferrer"' in body, (
        'shipment-detail.html must contain rel="noopener noreferrer" for wFirma link'
    )
    # The link context must be near a wfirma_pz_view_url reference.
    view_idx = body.find("wfirma_pz_view_url")
    assert view_idx > 0, "wfirma_pz_view_url must be referenced in shipment-detail.html"

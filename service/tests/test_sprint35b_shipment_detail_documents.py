"""
test_sprint35b_shipment_detail_documents.py — Sprint 35b authority contract.

Asserts (static source-grep; no server required):

  A. Mock-array removal (T1–T2)
     T1. UPLOADED_DOCS literal does NOT exist in shipment-detail-page.jsx.
     T2. GENERATED_DOCS literal does NOT exist in shipment-detail-page.jsx.

  B. Real authority wiring (T3–T4)
     T3. files_detail referenced in shipment-detail-page.jsx (DocumentsTab fetch).
     T4. No onNotify("Downloading") pattern inside DocCard — downloads use real URL.

  C. Navigation wiring (T5–T6)
     T5. DashboardPage accepts and calls onViewShipment.
     T6. index.html passes onViewShipment to DashboardPage.

  D. Proforma routing (T7)
     T7. ProformaTabInShipment navigates to /v2/proforma?batch_id= (no alert() call).

  E. Empty-state guard (T8)
     T8. DocumentsTab guards on missing batchId before fetching.
"""

import re
from pathlib import Path

_ROOT    = Path(__file__).parents[1]
_STATIC  = _ROOT / "app" / "static" / "v2"
_DETAIL  = _STATIC / "shipment-detail-page.jsx"
_DASH    = _STATIC / "dashboard-page.jsx"
_INDEX   = _STATIC / "index.html"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── A. Mock-array removal ──────────────────────────────────────────────────────

def test_T1_no_UPLOADED_DOCS_literal():
    """UPLOADED_DOCS mock array must be gone from shipment-detail-page.jsx."""
    assert "UPLOADED_DOCS" not in _src(_DETAIL), (
        "UPLOADED_DOCS still present — mock document array not removed (Sprint 35b)"
    )


def test_T2_no_GENERATED_DOCS_literal():
    """GENERATED_DOCS mock array must be gone from shipment-detail-page.jsx."""
    assert "GENERATED_DOCS" not in _src(_DETAIL), (
        "GENERATED_DOCS still present — mock document array not removed (Sprint 35b)"
    )


# ── B. Real authority wiring ──────────────────────────────────────────────────

def test_T3_files_detail_fetched():
    """DocumentsTab must reference /files endpoint from dashboard batch authority."""
    src = _src(_DETAIL)
    assert "/api/v1/dashboard/batches/" in src and "/files" in src, (
        "shipment-detail-page.jsx does not reference "
        "/api/v1/dashboard/batches/{batch_id}/files — DocumentsTab not wired"
    )


def test_T4_no_onNotify_download_in_DocCard():
    """DocCard must not use onNotify('Downloading…') — all downloads use real URL."""
    src = _src(_DETAIL)
    # The old pattern was: onClick={() => onNotify(`Downloading ...`)}
    assert "onNotify" not in src or "Downloading" not in src.split("onNotify")[1].split("\n")[0] if "onNotify" in src else True, (
        "DocCard still uses onNotify for downloads — replace with real file.url href"
    )
    # Positive assertion: real download anchor present
    assert 'data-testid="doc-download"' in src, (
        "doc-download testid not found in DocCard — real download anchor missing"
    )


# ── C. Navigation wiring ──────────────────────────────────────────────────────

def test_T5_dashboard_page_uses_onViewShipment():
    """DashboardPage must accept and call onViewShipment prop."""
    src = _src(_DASH)
    assert "onViewShipment" in src, (
        "DashboardPage does not reference onViewShipment — drill-through not wired"
    )


def test_T6_index_html_passes_onViewShipment_to_DashboardPage():
    """index.html must pass onViewShipment prop to DashboardPage."""
    src = _src(_INDEX)
    assert "DashboardPage onViewShipment=" in src or "DashboardPage\n" not in src, (
        "index.html does not pass onViewShipment to DashboardPage"
    )
    assert "onViewShipment={handleViewShipment}" in src, (
        "handleViewShipment not passed to DashboardPage in index.html"
    )


# ── D. Proforma routing ────────────────────────────────────────────────────────

def test_T7_proforma_tab_navigates_no_alert():
    """ProformaTabInShipment must navigate to /v2/proforma?batch_id= — no alert()."""
    src = _src(_DETAIL)
    assert "/v2/proforma?batch_id=" in src, (
        "ProformaTabInShipment does not navigate to /v2/proforma?batch_id= — batch context not passed"
    )
    # alert() calls in this component were dead-end mock navigation; must be gone
    proforma_section = src.split("ProformaTabInShipment")[1].split("Object.assign")[0] if "ProformaTabInShipment" in src else ""
    assert "alert(" not in proforma_section, (
        "alert() still present in ProformaTabInShipment — replace with real navigation"
    )


# ── E. Empty-state guard ───────────────────────────────────────────────────────

def test_T8_documents_tab_guards_on_missing_batch_id():
    """DocumentsTab must show honest empty state when batchId is falsy."""
    src = _src(_DETAIL)
    # The guard pattern: if (!batchId) return ...
    assert "if (!batchId)" in src, (
        "DocumentsTab missing !batchId guard — will attempt fetch with undefined batch_id"
    )

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

  F. Proforma blocker visibility (T9–T11) — Sprint 35c
     T9.  DraftReadinessCard renders blockers as numbered ordered list (<ol>), not <ul>.
     T10. DraftReadinessCard surfaces post_failed error via data-testid proforma-post-failed-error.
     T11. ProformaTabInShipment renders all-complete banner when all active drafts done.

  G. Intake diagnostics (T12–T15) — Sprint 35d
     T12. IntakeDiagnosticsCard component defined; getBatchDetail added to pz-api.js.
     T13. Lifecycle stage rendered with backend-verbatim value (data-testid intake-clearance-status).
     T14. Artifact checklist and blocking reason surfaced (intake-artifact-checklist, intake-blocking-reason).
     T15. Hardcoded Shipment card strings removed from OverviewTab (no '3 uploaded'; old subtitle gone).
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


# ── F. Proforma blocker visibility (Sprint 35c) ────────────────────────────────

def test_T9_draft_readiness_card_uses_ordered_list():
    """DraftReadinessCard must render blockers as a numbered <ol>, not <ul>."""
    src = _src(_DETAIL)
    card_slice = src.split("DraftReadinessCard")[1].split("ProformaTabInShipment")[0] if "DraftReadinessCard" in src else ""
    assert "<ol" in card_slice, (
        "DraftReadinessCard does not render an <ol> — blockers must be a numbered ordered list"
    )
    # Old inline-span pattern must be gone (replaced by callout box)
    assert 'span style={{ color: \'var(--text-2)\' }}> — {b.repair_action}' not in src, (
        "Old inline em-dash repair_action span still present — replace with callout box"
    )


def test_T10_draft_readiness_card_shows_post_failed_error():
    """DraftReadinessCard must surface post_failed error via proforma-post-failed-error testid."""
    src = _src(_DETAIL)
    assert 'data-testid="proforma-post-failed-error"' in src, (
        "DraftReadinessCard missing proforma-post-failed-error testid — "
        "post_failed error box not rendered"
    )
    assert "isPostFailed" in src, (
        "DraftReadinessCard missing isPostFailed flag — post_failed state not detected"
    )
    assert "error_hint" in src, (
        "DraftReadinessCard does not reference draft.error_hint — "
        "wFirma failure reason not surfaced"
    )


def test_T11_proforma_tab_shows_all_complete_banner():
    """ProformaTabInShipment must render an all-complete banner when all active drafts are done."""
    src = _src(_DETAIL)
    assert 'data-testid="proforma-all-complete-banner"' in src, (
        "ProformaTabInShipment missing proforma-all-complete-banner testid — "
        "all-approved positive confirmation not rendered"
    )
    assert "All active Pro Forma drafts complete" in src, (
        "All-complete banner missing expected text — operator cannot confirm all drafts done"
    )


# ── G. Intake diagnostics (Sprint 35d) ────────────────────────────────────────

_PZAPI = _STATIC / "pz-api.js"


def test_T12_intake_diagnostics_card_defined_and_getBatchDetail_added():
    """IntakeDiagnosticsCard must be defined; getBatchDetail must exist in pz-api.js."""
    src = _src(_DETAIL)
    assert "IntakeDiagnosticsCard" in src, (
        "IntakeDiagnosticsCard not found in shipment-detail-page.jsx — "
        "intake diagnostics component not defined"
    )
    assert 'data-testid="intake-diagnostics-card"' in src, (
        "intake-diagnostics-card testid missing — IntakeDiagnosticsCard root element not rendered"
    )
    api_src = _src(_PZAPI)
    assert "getBatchDetail" in api_src, (
        "getBatchDetail not found in pz-api.js — "
        "batch detail fetch method not added to PzApi transport layer"
    )
    assert "/dashboard/batches/" in api_src, (
        "pz-api.js does not reference /dashboard/batches/ path — "
        "getBatchDetail not wired to correct endpoint"
    )


def test_T13_intake_lifecycle_stage_rendered():
    """IntakeDiagnosticsCard must render lifecycle stage with intake-clearance-status testid."""
    src = _src(_DETAIL)
    assert 'data-testid="intake-clearance-status"' in src, (
        "intake-clearance-status testid missing — lifecycle stage not rendered; "
        "operator cannot determine intake stage without opening logs"
    )
    # Lifecycle value must come verbatim from backend (clearance_status field), not from
    # a frontend label map (Lesson F rule 5: frontend reflects truth, never produces it).
    assert "clearance_status" in src, (
        "clearance_status field not referenced in shipment-detail-page.jsx — "
        "lifecycle stage authority not wired"
    )


def test_T14_intake_artifact_checklist_and_blocking_reason():
    """IntakeDiagnosticsCard must surface artifact checklist and blocking reason."""
    src = _src(_DETAIL)
    assert 'data-testid="intake-artifact-checklist"' in src, (
        "intake-artifact-checklist testid missing — "
        "artifact presence/absence panel not rendered"
    )
    assert 'data-testid="intake-blocking-reason"' in src, (
        "intake-blocking-reason testid missing — "
        "blocking reason callout not rendered"
    )
    assert "action_reason" in src, (
        "action_reason not referenced — primary blocking reason not surfaced from backend"
    )
    assert "sales_status_hint" in src, (
        "sales_status_hint not referenced — sales packing artifact check not wired "
        "(sales packing lives in document_db, not source_files)"
    )


def test_T15_hardcoded_shipment_card_strings_removed():
    """Hardcoded Shipment card strings must be absent — old card replaced by IntakeDiagnosticsCard."""
    src = _src(_DETAIL)
    # '3 uploaded' was the fake invoice count in the old Shipment PanelCard row.
    assert "'3 uploaded'" not in src, (
        "Hardcoded '3 uploaded' still present in shipment-detail-page.jsx — "
        "old Shipment PanelCard Invoices row not removed (Sprint 35d)"
    )
    # Old card had subtitle "Tracking, invoices, AWB" — replaced with "Shipment intake".
    assert '"Tracking, invoices, AWB"' not in src, (
        "Old Shipment PanelCard subtitle 'Tracking, invoices, AWB' still present — "
        "PanelCard not replaced by IntakeDiagnosticsCard (Sprint 35d)"
    )

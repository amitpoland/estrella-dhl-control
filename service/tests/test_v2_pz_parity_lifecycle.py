"""
test_v2_pz_parity_lifecycle.py — V2 Shipment Detail PZ lifecycle wiring.

Pins: PzApi wrappers for process/preview/create/adopt, state-aware action
controls, confirmation gates, no hardcoded pz.pdf/pz.xlsx downloads, and
removal of the obsolete "not wired into V2" banner. Source-grep only.
"""
from __future__ import annotations

from pathlib import Path

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_DETAIL = _V2 / "shipment-detail-page.jsx"
_PZAPI = _V2 / "pz-api.js"


def _detail() -> str:
    return _DETAIL.read_text(encoding="utf-8")


def _api() -> str:
    return _PZAPI.read_text(encoding="utf-8")


def test_pz_api_wrappers_exist():
    src = _api()
    for name in (
        "processShipment:",
        "wfirmaPzPreview:",
        "wfirmaPzCreate:",
        "wfirmaPzAdopt:",
        "wfirmaPzConfirm:",
        "downloadBatchFile:",
        "getBatchFiles:",
    ):
        assert name in src, f"pz-api.js missing PZ wrapper {name!r}"


def test_run_pz_targets_process_not_create():
    """Local generation is POST …/process — never collapsed onto pz_create."""
    api = _api()
    detail = _detail()
    assert "${BASE}/upload/shipment/${encodeURIComponent(batchId)}/process" in api
    assert "window.PzApi.processShipment" in detail
    # Run / Regenerate must name /process in data-backend-route
    assert "/process" in detail
    # The mis-route "Run PZ → pz_create" must be gone from PendingAction labels
    assert "PendingAction label=\"Run PZ\"" not in detail


def test_export_uses_wfirma_create():
    src = _detail()
    assert "window.PzApi.wfirmaPzCreate" in src
    assert "/wfirma/pz_create" in src


def test_adopt_and_confirm_require_body():
    src = _detail()
    assert "window.PzApi.wfirmaPzAdopt" in src
    assert "window.PzApi.wfirmaPzConfirm" in src
    assert "pz_doc_id" in src and "pz_number" in src
    assert 'data-testid="pz-number-input"' in src


def test_downloads_resolve_via_batch_files():
    """Downloads must not hardcode /pz.pdf or /pz.xlsx filenames."""
    src = _detail()
    assert "window.PzApi.getBatchFiles" in src
    assert "window.PzApi.downloadBatchFile" in src
    assert "/files/' + bid + '/pz.xlsx" not in src
    assert "/files/' + bid + '/pz.pdf" not in src
    assert "calc_xlsx" in src or "pz_pdf" in src


def test_write_actions_are_confirmation_gated():
    src = _detail()
    assert 'data-testid="export-wfirma-confirm"' in src
    assert 'data-testid="regenerate-pz-confirm"' in src
    assert "onClick={() => setConfirmExport(true)}" in src
    assert "onClick={() => setConfirmRegen(true)}" in src


def test_obsolete_not_wired_banner_removed():
    src = _detail()
    assert 'testid="pz-actions-pending-note"' not in src
    assert "not yet wired into this V2 page" not in src
    assert 'testid="pz-actions-authority-note"' in src
    assert "function PzActionsPanel(" in src


def test_six_plus_documents_testids_preserved():
    src = _detail()
    for tid in (
        "run-pz", "regenerate-pz", "confirm-pz", "download-xlsx", "download-pdf",
        "export-wfirma", "mark-exported", "pz-open-documents",
    ):
        assert f'testid="{tid}"' in src, f"PZ action testid '{tid}' lost"


def test_success_reloads_detail():
    src = _detail()
    assert "if (onReload) onReload();" in src
    # PzTab receives onReload from ShipmentDetailPage
    assert "onReload={reloadDetail}" in src

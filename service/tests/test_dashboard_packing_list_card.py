"""
test_dashboard_packing_list_card.py — Source-grep tests for the
Packing List card in the Documents tab.

Pattern: read dashboard.html as text and assert structural markers.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

# Repo-relative path so the suite runs on any developer machine and in CI.
# parents[2] == repo root (this file lives at service/tests/<name>.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
# Phase 2 — Packing List card lives in shipment-detail.html.
DASHBOARD = _REPO_ROOT / "service" / "app" / "static" / "shipment-detail.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Card presence in Documents tab ───────────────────────────────────────────

def test_packing_list_card_testid():
    """data-testid='packing-list-card' must be present."""
    src = _src()
    assert (
        'data-testid="packing-list-card"' in src
        or "data-testid='packing-list-card'" in src
    )


def test_packing_list_card_in_documents_tab():
    """Packing List card must be rendered inside the Documents tab block."""
    src = _src()
    docs_start = src.find("activeTab === 'Documents'")
    assert docs_start != -1, "Documents tab block not found"
    # Find the next tab after Documents (Timeline)
    docs_end = src.find("activeTab === 'Timeline'", docs_start)
    assert docs_end != -1, "Timeline tab block not found after Documents"
    snippet = src[docs_start:docs_end]
    assert 'packing-list-card' in snippet, (
        "packing-list-card testid not found inside Documents tab block"
    )


# ── Upload endpoint wired ────────────────────────────────────────────────────

def test_packing_upload_endpoint_wired():
    """POST /api/v1/packing/{batch_id}/upload must be called in the card."""
    src = _src()
    assert "/api/v1/packing/" in src
    assert "/upload" in src
    # The fetch must use POST method
    assert "method: 'POST'" in src or 'method:"POST"' in src


def test_packing_upload_form_field():
    """The upload must append 'file' field to FormData."""
    src = _src()
    assert "formData.append('file'" in src or 'formData.append("file"' in src


def test_packing_upload_input_testid():
    """File input must have data-testid='packing-list-upload-input'."""
    src = _src()
    assert (
        'data-testid="packing-list-upload-input"' in src
        or "data-testid='packing-list-upload-input'" in src
    )


def test_packing_upload_accepts_pdf_and_xlsx():
    """The file input must accept .pdf and .xlsx extensions."""
    src = _src()
    # Find the packing upload input — look at a wider window since accept= precedes data-testid
    idx = src.find('packing-list-upload-input')
    assert idx != -1
    snippet = src[max(0, idx - 500):idx + 300]
    assert ".pdf" in snippet or "pdf" in snippet.lower()
    assert ".xlsx" in snippet or "xlsx" in snippet.lower()


# ── GET endpoint for loading status ─────────────────────────────────────────

def test_load_packing_info_callback_present():
    """loadPackingInfo callback must be defined."""
    assert "loadPackingInfo" in _src()


def test_packing_info_state_hooks_present():
    """packingInfo / packingInfoLoading / packingUploading state hooks."""
    src = _src()
    assert "packingInfo" in src
    assert "packingInfoLoading" in src
    assert "packingUploading" in src
    assert "setPackingInfo" in src
    assert "setPackingInfoLoading" in src
    assert "setPackingUploading" in src


def test_packing_get_endpoint_wired():
    """GET /api/v1/packing/{batch_id} must be fetched by loadPackingInfo."""
    src = _src()
    start = src.find("loadPackingInfo")
    assert start != -1
    snippet = src[start:start + 400]
    assert "/api/v1/packing/" in snippet


# ── Auto-load effect ─────────────────────────────────────────────────────────

def test_packing_info_loaded_on_documents_tab():
    """packingInfo must be fetched when Documents tab is activated."""
    src = _src()
    # Look for the useEffect that triggers on Documents tab
    assert "activeTab === 'Documents' && !packingInfo" in src or (
        "activeTab === 'Documents'" in src and "loadPackingInfo" in src
    )


# ── Refresh after upload ────────────────────────────────────────────────────

def test_refresh_packing_info_after_upload():
    """loadPackingInfo must be called after a successful upload."""
    src = _src()
    upload_fn = src.find("handlePackingUpload")
    assert upload_fn != -1
    snippet = src[upload_fn:upload_fn + 800]
    assert "loadPackingInfo" in snippet


def test_refresh_batch_readiness_after_upload():
    """loadBatchReadiness must be called after a successful upload."""
    src = _src()
    upload_fn = src.find("handlePackingUpload")
    assert upload_fn != -1
    snippet = src[upload_fn:upload_fn + 800]
    assert "loadBatchReadiness" in snippet


# ── Empty state ──────────────────────────────────────────────────────────────

def test_packing_list_empty_state_testid():
    """data-testid='packing-list-empty-state' must be present."""
    src = _src()
    assert (
        'data-testid="packing-list-empty-state"' in src
        or "data-testid='packing-list-empty-state'" in src
    )


def test_packing_list_empty_state_text():
    """Empty state must contain a meaningful message."""
    src = _src()
    assert "No packing list uploaded yet" in src


# ── Informational label ──────────────────────────────────────────────────────

def test_packing_list_feeds_label():
    """Card must carry the required 'feeds Warehouse Audit and Sales Linkage' label."""
    assert "Packing list upload feeds Warehouse Audit and Sales Linkage." in _src()


# ── Status display ──────────────────────────────────────────────────────────

def test_packing_list_status_testid():
    """data-testid='packing-list-status' must be present for existing docs."""
    src = _src()
    assert (
        'data-testid="packing-list-status"' in src
        or "data-testid='packing-list-status'" in src
    )


def test_packing_list_row_count_displayed():
    """Row count (packing_lines.length) must be displayed when > 0."""
    src = _src()
    assert "lineCount" in src
    assert "rows extracted" in src


def test_packing_list_file_name_displayed():
    """File name from source_file_path must be surfaced."""
    src = _src()
    assert "source_file_path" in src


def test_packing_list_date_displayed():
    """Upload date from created_at must be surfaced."""
    src = _src()
    assert "created_at" in src


# ── No unrelated POST ────────────────────────────────────────────────────────

def test_only_packing_post_in_card():
    """The card must POST only to the packing upload endpoint."""
    src = _src()
    # Find the function definition (not a reference) so the snippet covers the body
    fn_def = src.find("const handlePackingUpload")
    assert fn_def != -1, "handlePackingUpload function not found"
    # Grab ~1200 chars covering the async function body
    snippet = src[fn_def:fn_def + 1200]
    assert "/api/v1/packing/" in snippet
    post_count = snippet.count("method: 'POST'") + snippet.count('method:"POST"')
    assert post_count >= 1, "No POST method found in handlePackingUpload"
    assert post_count <= 2, f"Unexpected extra POST calls in handlePackingUpload: {post_count}"


# ── Structural integrity ─────────────────────────────────────────────────────

def test_brace_balance():
    """Curly braces in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("{")
    closes = jsx.count("}")
    assert opens == closes, f"Unbalanced braces: {{ {opens}  }} {closes}"


def test_paren_balance():
    """Parentheses in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("(")
    closes = jsx.count(")")
    assert opens == closes, f"Unbalanced parens: ( {opens}  ) {closes}"

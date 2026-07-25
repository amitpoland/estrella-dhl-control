"""
test_dashboard_agency_docs_card.py — Source-grep tests for the
Agency Documents Received card in the DHL / Customs tab.

The card uses POST /api/v1/agency-documents/{batch_id}/upload with
multipart/FormData — the safe browser upload path added in the backend fix.

Pattern: read dashboard.html as text and assert structural markers.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Safety: no fake paths ────────────────────────────────────────────────────

def test_no_dev_null_in_agency_card():
    """/dev/null must not appear anywhere in dashboard.html."""
    assert "/dev/null" not in _src(), "/dev/null found — fake path present"


def test_no_fake_path_in_agency_card_snippet():
    """No fake/placeholder filesystem paths in the agency docs card block."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    assert idx != -1, "agency-docs-received-card testid not found"
    snippet = src[idx:idx + 5000]
    for bad in ("/dev/null", "fake_path", "placeholder_path", "manual_receipt"):
        assert bad not in snippet, f"Forbidden fake path '{bad}' in agency docs card"


# ── Card presence in DHL / Customs tab ──────────────────────────────────────

def test_agency_docs_card_testid():
    """data-testid='agency-docs-received-card' must be present."""
    src = _src()
    assert (
        'data-testid="agency-docs-received-card"' in src
        or "data-testid='agency-docs-received-card'" in src
    )


def test_agency_docs_card_in_dhl_tab():
    """Agency Documents Received card must be inside the DHL / Customs tab block."""
    src = _src()
    dhl_start = src.find("activeTab === 'DHL / Customs' && (() => {")
    assert dhl_start != -1, "DHL / Customs IIFE panel block not found"
    snippet = src[dhl_start:dhl_start + 20000]
    assert "agency-docs-received-card" in snippet, (
        "agency-docs-received-card not found inside DHL / Customs tab block"
    )


# ── Upload endpoint wiring ───────────────────────────────────────────────────

def test_agency_upload_endpoint_path():
    """Card must POST to /api/v1/agency-documents/{batchId}/upload."""
    src = _src()
    assert "/api/v1/agency-documents/" in src
    assert "/upload" in src
    # Verify the pattern is in the agency card block
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "/api/v1/agency-documents/" in snippet, (
        "Upload endpoint path not found in agency docs card"
    )
    assert "/upload" in snippet, "'/upload' not found in agency docs card"


def test_agency_upload_uses_formdata():
    """Card must use FormData for multipart upload (not JSON body)."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "FormData" in snippet, "FormData not found in agency docs card"
    assert "fd.append" in snippet or "append(" in snippet, (
        "FormData.append() call not found in agency docs card"
    )


def test_agency_upload_appends_files_field():
    """Card must append files under the 'files' field name."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "'files'" in snippet or '"files"' in snippet, (
        "files field name not found in agency docs FormData append"
    )


def test_agency_upload_method_post():
    """Fetch call in agency card must use method: 'POST'."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "method: 'POST'" in snippet or 'method: "POST"' in snippet, (
        "POST method not found in agency docs card fetch call"
    )


# ── Refresh after upload ─────────────────────────────────────────────────────

def test_refresh_dhl_readiness_after_upload():
    """Card must call loadDhlReadiness() after successful upload."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "loadDhlReadiness" in snippet, (
        "loadDhlReadiness() not called after agency docs upload"
    )


def test_refresh_batch_readiness_after_upload():
    """Card must call loadBatchReadiness() after successful upload."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    assert "loadBatchReadiness" in snippet, (
        "loadBatchReadiness() not called after agency docs upload"
    )


# ── Required UI elements ─────────────────────────────────────────────────────

def test_agency_docs_description_text():
    """Card must show the upload purpose description."""
    assert "Upload SAD/PZC or agency documents received from the customs agency." in _src()


def test_agency_docs_file_input_present():
    """data-testid='agency-docs-file-input' must be present."""
    src = _src()
    assert (
        'data-testid="agency-docs-file-input"' in src
        or "data-testid='agency-docs-file-input'" in src
    )


def test_agency_docs_accepted_extensions_shown():
    """Accepted extensions must be shown in the card."""
    src = _src()
    assert (
        'data-testid="agency-docs-accepted-extensions"' in src
        or "data-testid='agency-docs-accepted-extensions'" in src
    )
    assert ".pdf" in src and ".xml" in src and ".html" in src


def test_agency_docs_accept_attribute():
    """File input must declare accept attribute with agency-relevant types."""
    src = _src()
    idx = src.find("agency-docs-file-input")
    snippet = src[idx:idx + 300]
    assert "accept=" in snippet, "accept attribute missing on agency docs file input"
    assert ".pdf" in snippet


def test_agency_docs_multiple_attribute():
    """File input must accept multiple files."""
    src = _src()
    idx = src.find("agency-docs-file-input")
    snippet = src[idx:idx + 300]
    assert "multiple" in snippet, "multiple attribute missing on agency docs file input"


def test_agency_docs_success_testid():
    """data-testid='agency-docs-success' must be present for success state."""
    src = _src()
    assert (
        'data-testid="agency-docs-success"' in src
        or "data-testid='agency-docs-success'" in src
    )


def test_agency_docs_error_testid():
    """data-testid='agency-docs-error' must be present for error state."""
    src = _src()
    assert (
        'data-testid="agency-docs-error"' in src
        or "data-testid='agency-docs-error'" in src
    )


# ── No unrelated POST added ──────────────────────────────────────────────────

def test_no_unrelated_post_in_agency_card():
    """Agency card must not POST to unrelated endpoints (email, forward, import)."""
    src = _src()
    idx = src.find("agency-docs-received-card")
    snippet = src[idx:idx + 5000]
    for forbidden in ("/api/v1/email", "/api/v1/forward", "/api/v1/import", "/api/v1/sad"):
        assert forbidden not in snippet, (
            f"Unexpected endpoint '{forbidden}' found in agency docs card"
        )


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

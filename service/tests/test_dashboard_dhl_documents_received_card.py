"""
test_dashboard_dhl_documents_received_card.py — Source-grep tests for the
DHL Documents Received card in the DHL / Customs tab.

The card is read-only because the existing backend endpoint
(POST /api/v1/dhl-documents/{batch_id}/received) requires real server-side
file paths, not browser uploads.  Sending fake / placeholder paths such as
/dev/null would create false audit evidence.

The card therefore:
  - displays DSK/cesja receipt status from the existing dhlReadiness state
  - shows missing document types
  - shows last received timestamp
  - carries the explanation label
  - shows a note that manual receipt requires backend upload support
  - has no write button

Pattern: read dashboard.html as text and assert structural markers.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ── Safety: no fake paths ────────────────────────────────────────────────────

def test_no_dev_null_in_source():
    """/dev/null must not appear anywhere in dashboard.html."""
    assert "/dev/null" not in _src(), "/dev/null found — fake path present"


def test_no_placeholder_path_in_dhl_section():
    """No placeholder filesystem path should be POSTed from the DHL card."""
    src = _src()
    # Locate the DHL docs card block
    idx = src.find("dhl-docs-received-card")
    assert idx != -1
    snippet = src[idx:idx + 3000]
    # These are the specific fake-path patterns we forbid
    for bad in ("/dev/null", "/tmp/", "placeholder", "fake_path", "manual_receipt"):
        assert bad not in snippet, f"Forbidden placeholder '{bad}' found in DHL docs card"


# ── Card presence in DHL / Customs tab ──────────────────────────────────────

def test_dhl_docs_received_card_testid():
    """data-testid='dhl-docs-received-card' must be present."""
    src = _src()
    assert (
        'data-testid="dhl-docs-received-card"' in src
        or "data-testid='dhl-docs-received-card'" in src
    )


def test_dhl_docs_received_card_in_dhl_tab():
    """DHL Documents Received card must be rendered inside the DHL / Customs tab block."""
    src = _src()
    dhl_start = src.find("activeTab === 'DHL / Customs' && (() => {")
    assert dhl_start != -1, "DHL / Customs IIFE panel block not found"
    snippet = src[dhl_start:dhl_start + 12000]
    assert 'dhl-docs-received-card' in snippet, (
        "dhl-docs-received-card testid not found inside DHL / Customs tab block"
    )


# ── Read-only: button absent, note present ───────────────────────────────────

def test_record_button_absent():
    """The 'Record DHL documents received' write button must NOT be present
    because the backend requires real server-side file paths."""
    src = _src()
    idx = src.find("dhl-docs-received-card")
    assert idx != -1
    snippet = src[idx:idx + 3000]
    assert 'data-testid="dhl-docs-record-btn"' not in snippet
    assert "data-testid='dhl-docs-record-btn'" not in snippet


def test_backend_upload_support_note_present():
    """The card must show the read-only note explaining why the button is absent."""
    assert "Manual DHL document receipt requires backend upload support." in _src()


def test_backend_upload_note_testid():
    """data-testid='dhl-docs-manual-receipt-note' must be present."""
    src = _src()
    assert (
        'data-testid="dhl-docs-manual-receipt-note"' in src
        or "data-testid='dhl-docs-manual-receipt-note'" in src
    )


# ── No write calls in card ───────────────────────────────────────────────────

def test_no_post_to_dhl_documents_endpoint():
    """The DHL docs card must not POST to /api/v1/dhl-documents/ because
    there is no safe browser-driven upload path."""
    src = _src()
    idx = src.find("dhl-docs-received-card")
    assert idx != -1
    snippet = src[idx:idx + 3000]
    assert "/api/v1/dhl-documents/" not in snippet, (
        "Found POST call to dhl-documents endpoint — fake path must not be sent"
    )


# ── Status display testids (read-only, preserved) ───────────────────────────

def test_dhl_docs_received_status_testid():
    """data-testid='dhl-docs-received-status' must be present for received state."""
    src = _src()
    assert (
        'data-testid="dhl-docs-received-status"' in src
        or "data-testid='dhl-docs-received-status'" in src
    )


def test_dhl_docs_not_received_state_testid():
    """data-testid='dhl-docs-not-received-state' must be present for empty state."""
    src = _src()
    assert (
        'data-testid="dhl-docs-not-received-state"' in src
        or "data-testid='dhl-docs-not-received-state'" in src
    )


# ── Required UI text ─────────────────────────────────────────────────────────

def test_dhl_docs_explanation_label():
    """Card must carry the 'confirms documents received from DHL before agency forwarding' label."""
    assert "This confirms documents received from DHL before agency forwarding." in _src()


# ── DSK timestamp and missing docs surfaced ──────────────────────────────────

def test_dhl_docs_uses_dsk_docs_received():
    """Card must use dsk_docs_received from dhlReadiness state."""
    assert "dsk_docs_received" in _src()


def test_dhl_docs_shows_missing_documents():
    """Card must surface missing_documents from dhlReadiness state."""
    src = _src()
    assert "missing_documents" in src
    assert "missingDocs" in src


# ── Removed state hooks must not be present ─────────────────────────────────

def test_dhl_docs_busy_state_hook_absent():
    """dhlDocsBusy must be removed — it was only needed for the write button."""
    assert "dhlDocsBusy" not in _src()


def test_dhl_docs_confirm_state_hook_absent():
    """dhlDocsConfirm must be removed — it was only needed for the write button."""
    assert "dhlDocsConfirm" not in _src()


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


# ── Source-of-receipt badges ─────────────────────────────────────────────────

def test_dashboard_shows_auto_detected():
    """When source='email_ingestor', the card must render the auto-detected badge."""
    src = _src()
    idx = src.find("dhl-docs-received-card")
    assert idx != -1
    snippet = src[idx:idx + 4000]
    assert 'data-testid="dhl-docs-source-auto"' in snippet, (
        "dhl-docs-source-auto testid missing from DHL docs card"
    )
    assert "email_ingestor" in snippet, (
        "email_ingestor source value not referenced in DHL docs card"
    )
    assert "Auto-detected from email" in snippet, (
        "'Auto-detected from email' label missing from DHL docs card"
    )


def test_dashboard_shows_manual():
    """When source='operator', the card must render the manually-registered badge."""
    src = _src()
    idx = src.find("dhl-docs-received-card")
    assert idx != -1
    snippet = src[idx:idx + 4000]
    assert 'data-testid="dhl-docs-source-manual"' in snippet, (
        "dhl-docs-source-manual testid missing from DHL docs card"
    )
    assert "Manually registered" in snippet, (
        "'Manually registered' label missing from DHL docs card"
    )

"""Phase 2-A renderer source-grep tests.

These tests assert that the required HTML renderer sections are present
in the routes_proforma.py source file.  They are intentionally
source-grep style — they verify implementation coverage without
needing a running server or database.
"""
from __future__ import annotations

from pathlib import Path

# Absolute path — never depends on cwd
_ROUTES_SOURCE = (
    Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
)


def _src() -> str:
    return _ROUTES_SOURCE.read_text(encoding="utf-8")


# ── Import presence ────────────────────────────────────────────────────────────

def test_renderer_has_company_profile_import():
    """get_company_profile must be imported at module level."""
    assert "get_company_profile" in _src(), (
        "get_company_profile is not imported in routes_proforma.py"
    )


# ── Seller block ───────────────────────────────────────────────────────────────

def test_renderer_has_seller_block():
    """The 'company profile not configured' banner must be present in the
    renderer so the UI degrades gracefully when master_data.sqlite has no
    company profile row."""
    src = _src()
    assert "Company profile not configured" in src or \
           "company-profile not configured" in src, (
        "Seller 'not configured' banner text missing from renderer"
    )


# ── PLN reference total ────────────────────────────────────────────────────────

def test_renderer_has_pln_total():
    """grand_total × exchange_rate PLN calculation must appear in renderer."""
    src = _src()
    # The renderer computes _pln_total = grand_total * _exr
    assert "exchange_rate" in src, (
        "exchange_rate reference missing from renderer (PLN total section)"
    )
    assert "_pln_total" in src, (
        "_pln_total variable missing from renderer"
    )


# ── Audit.json read-through ────────────────────────────────────────────────────

def test_renderer_has_audit_read():
    """Renderer must read audit.json from batch storage path (read-only)."""
    src = _src()
    assert "audit.json" in src, (
        "audit.json read-through missing from renderer"
    )
    assert "_audit_awb" in src, (
        "_audit_awb extraction missing from renderer"
    )


# ── No wFirma client call inside the renderer ─────────────────────────────────

def test_renderer_no_wfirma_call():
    """The renderer function must not call wfirma_client for live API calls.
    decide_proforma_vat_context is a pure-data function (no API call) and is
    allowed; but wfirma_client.<live-call> imports are forbidden inside the
    renderer function body.

    Strategy: confirm 'wfirma_client' appears only in ways we permit
    (the module is imported at the top of the file; decide_proforma_vat_context
    is a pure function call).  We check that the forbidden pattern
    'wfirma_client.create' or 'wfirma_client.fetch' or
    'wfirma_client.get_invoice' do not appear inside the renderer function.
    """
    src = _src()
    # Locate the renderer function boundaries
    func_start = src.find("def get_proforma_draft_preview_html(")
    assert func_start != -1, "get_proforma_draft_preview_html not found"
    # Next top-level def after the renderer
    next_def = src.find("\n@router.", func_start + 1)
    if next_def == -1:
        next_def = len(src)
    func_body = src[func_start:next_def]

    forbidden = [
        "wfirma_client.create_",
        "wfirma_client.fetch_",
        "wfirma_client.get_invoice",
        "wfirma_client.get_pz",
        "wfirma_client.post_",
    ]
    for pattern in forbidden:
        assert pattern not in func_body, (
            f"Forbidden wFirma live-call pattern '{pattern}' found inside "
            f"get_proforma_draft_preview_html"
        )


# ── name_en column ─────────────────────────────────────────────────────────────

def test_renderer_has_name_en_col():
    """name_en must be read per line in the rows_html construction."""
    src = _src()
    # Locate the renderer function body
    func_start = src.find("def get_proforma_draft_preview_html(")
    assert func_start != -1
    next_def = src.find("\n@router.", func_start + 1)
    if next_def == -1:
        next_def = len(src)
    func_body = src[func_start:next_def]

    assert "name_en" in func_body, (
        "name_en column missing from rows_html construction in renderer"
    )


# ── hs_code column ─────────────────────────────────────────────────────────────

def test_renderer_has_hs_code_col():
    """hs_code must be read per line in the rows_html construction."""
    src = _src()
    func_start = src.find("def get_proforma_draft_preview_html(")
    assert func_start != -1
    next_def = src.find("\n@router.", func_start + 1)
    if next_def == -1:
        next_def = len(src)
    func_body = src[func_start:next_def]

    assert "hs_code" in func_body, (
        "hs_code column missing from rows_html construction in renderer"
    )


# ── Incoterm display ───────────────────────────────────────────────────────────

def test_renderer_has_incoterm_display():
    """d.incoterm must be referenced in the renderer for the Shipment terms
    section."""
    src = _src()
    func_start = src.find("def get_proforma_draft_preview_html(")
    assert func_start != -1
    next_def = src.find("\n@router.", func_start + 1)
    if next_def == -1:
        next_def = len(src)
    func_body = src[func_start:next_def]

    assert "d.incoterm" in func_body, (
        "d.incoterm not referenced in get_proforma_draft_preview_html"
    )

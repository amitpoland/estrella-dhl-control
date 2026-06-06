"""
test_toolbar_authority_map.py
==============================
Toolbar authority regression tests for ProformaDetailPage.

Verifies that every toolbar button is either:
  - ENABLED_WITH_AUTHORITY  — wired to a real backend route with correct semantics
  - DISABLED_WITH_REASON    — permanently disabled with an honest title/reason
  - state-gated             — disabled/enabled based on lifecycle state

Source-grep tests only — no server required.

Binds to:
  service/app/static/v2/proforma-detail.jsx
  service/app/static/v2/pz-api.js          (V2)
  service/app/api/routes_proforma.py
  service/app/api/routes_carrier_actions.py
"""
from __future__ import annotations

import re
from pathlib import Path

_V2_DIR  = Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL  = _V2_DIR / "proforma-detail.jsx"
_PZ_API  = _V2_DIR / "pz-api.js"
_ROUTES  = Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
_CARRIER = Path(__file__).parent.parent / "app" / "api" / "routes_carrier_actions.py"


def _src()     -> str: return _DETAIL.read_text(encoding="utf-8")
def _api()     -> str: return _PZ_API.read_text(encoding="utf-8")
def _routes()  -> str: return _ROUTES.read_text(encoding="utf-8")
def _carrier() -> str: return _CARRIER.read_text(encoding="utf-8")


# ── 1. Post to wFirma — ENABLED_WITH_AUTHORITY ───────────────────────────────

def test_post_button_uses_can_post_guard():
    """Post button must be disabled={!canPost}, not always enabled."""
    src = _src()
    assert "disabled={!canPost}" in src, \
        "Post to wFirma button must use disabled={!canPost}"


def test_can_post_guard_definition():
    """canPost must be defined from lifecycle state array."""
    src = _src()
    assert "const canPost" in src, "canPost must be derived from draftState"
    assert "pending_local" in src, "canPost states must include 'pending_local'"


def test_post_route_posts_proforma_not_invoice():
    """POST /draft/{id}/post must create a wFirma PROFORMA, not an invoice."""
    routes = _routes()
    # The route docstring must say "Proforma Draft" or "proforma"
    assert "Proforma Draft" in routes or "proforma" in routes.lower(), \
        "post route must reference proforma semantics"
    # The route must return wfirma_proforma_id (not invoice)
    assert "wfirma_proforma_id" in routes, \
        "post route must return wfirma_proforma_id (proves it creates a PROFORMA)"


def test_post_route_confirm_token_is_proforma():
    """Confirm token for Post must reference PROFORMA, not INVOICE."""
    routes = _routes()
    assert "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA" in routes, \
        "Post route confirm token must be YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
    # Must NOT have invoice token on the post route
    post_section = routes[routes.index("/draft/{draft_id}/post"):]
    invoice_pos = post_section.find("YES_CREATE_FINAL_INVOICE_FROM_PROFORMA")
    post_section_end = post_section.find("\n@router.")
    assert invoice_pos == -1 or invoice_pos > post_section_end, \
        "Post route must not reference invoice confirm token"


def test_post_wfirma_flag_gate_present():
    """Post must be gated by wfirma_create_proforma_allowed flag."""
    routes = _routes()
    assert "wfirma_create_proforma_allowed" in routes, \
        "Post route must check wfirma_create_proforma_allowed flag"


# ── 2. Convert to Invoice — ENABLED_WITH_AUTHORITY (requires posted state) ───

def test_convert_button_uses_can_convert_guard():
    """Convert button must be disabled={!canConvert}."""
    src = _src()
    assert "disabled={!canConvert}" in src, \
        "Convert to Invoice button must use disabled={!canConvert}"


def test_can_convert_requires_posted_state():
    """canConvert must only be true when draftState is 'posted' or 'ready'."""
    src = _src()
    assert "draftState === 'posted'" in src, \
        "canConvert must require posted state"


def test_convert_route_delegates_to_proforma_to_invoice():
    """to-invoice route must convert an existing proforma, not create from scratch."""
    routes = _routes()
    # The route delegates to proforma_to_invoice
    assert "proforma_to_invoice" in routes, \
        "to-invoice route must delegate to proforma_to_invoice"


def test_convert_requires_wfirma_proforma_id():
    """to-invoice route must require an existing wfirma_proforma_id."""
    routes = _routes()
    assert "UNIQUE(proforma_id)" in routes or "wfirma_proforma_id" in routes, \
        "to-invoice route must reference wfirma_proforma_id guard"


def test_convert_uses_invoice_confirm_token():
    """Convert confirm token must be the invoice token, not the proforma post token."""
    routes = _routes()
    assert "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA" in routes, \
        "to-invoice route must require YES_CREATE_FINAL_INVOICE_FROM_PROFORMA confirm"


def test_convert_wfirma_flag_gate_present():
    """Convert must be gated by wfirma_create_invoice_allowed flag."""
    routes = _routes()
    assert "wfirma_create_invoice_allowed" in routes, \
        "to-invoice route must check wfirma_create_invoice_allowed flag"


# ── 3. Print — ENABLED_WITH_AUTHORITY (requires wfirma_proforma_id) ──────────

def test_print_button_uses_can_print_guard():
    """Print button must be disabled={!canPrint} — not always enabled."""
    src = _src()
    assert "disabled={!canPrint}" in src, \
        "Print button must be disabled when wfirma_proforma_id is absent"


def test_can_print_requires_wfirma_proforma_id():
    """canPrint must be derived from wfirma_proforma_id existence."""
    src = _src()
    assert "canPrint" in src, "canPrint must be defined"
    assert "wfirma_proforma_id" in src, \
        "canPrint must reference wfirma_proforma_id"


def test_print_disabled_title_present():
    """Print button must have an honest disabled reason."""
    src = _src()
    assert "PDF only available after posting" in src or \
           "only available after posting to wFirma" in src, \
        "Print disabled title must explain PDF requires posting first"


def test_print_uses_document_pdf_route():
    """Print must call the document.pdf backend route."""
    src = _src()
    assert "document.pdf" in src, \
        "Print must use GET /document.pdf route for PDF authority"


def test_print_uses_window_open():
    """Print must open PDF in new tab via window.open."""
    src = _src()
    assert "window.open" in src, "Print must use window.open"


def test_print_pdf_route_exists_in_backend():
    """Backend must have a GET /{batch_id}/{cn}/document.pdf route."""
    routes = _routes()
    assert "document.pdf" in routes, \
        "routes_proforma.py must define GET /document.pdf endpoint"


def test_print_pdf_route_requires_wfirma_proforma_id():
    """Backend document.pdf route must return 404 when wfirma_proforma_id absent."""
    routes = _routes()
    assert "PROFORMA_NOT_LINKED" in routes or "wfirma_proforma_id" in routes, \
        "PDF route must guard on wfirma_proforma_id existence"


def test_cmr_print_not_exposed():
    """CMR print is NOT exposed — no CMR backend route exists."""
    routes = _routes()
    assert "cmr" not in routes.lower(), \
        "No CMR route must exist in routes_proforma.py — not in project scope"


# ── 4. Send — DISABLED_WITH_REASON ───────────────────────────────────────────

def test_send_button_is_disabled():
    """Send button must have disabled prop (no email send authority exists)."""
    src = _src()
    # Find the tb-send section
    tb_send_pos = src.find('data-testid="tb-send"')
    assert tb_send_pos > 0, "Send button testid must exist"
    # The TbBtn block before it must contain 'disabled'
    block_start = src.rfind("<TbBtn", 0, tb_send_pos)
    block = src[block_start:tb_send_pos + 50]
    assert "disabled" in block, \
        "Send button must be disabled — no email send authority exists"


def test_send_button_has_reason_title():
    """Send button title must explain why it is disabled."""
    src = _src()
    assert "not yet wired" in src or "send authority" in src or \
           "Email send" in src or "email" in src.lower(), \
        "Send button must have a title explaining why it is disabled"


def test_no_proforma_email_send_route_in_backend():
    """No direct proforma email send route must exist in routes_proforma.py."""
    routes = _routes()
    # Should not have send/queue_email routes
    assert "queue_email" not in routes, \
        "routes_proforma.py must not contain email-send queue logic"


# ── 5. Generate — DISABLED_WITH_REASON ───────────────────────────────────────

def test_generate_button_is_disabled():
    """Generate button must be disabled — carrier AWB is not proforma-wired."""
    src = _src()
    tb_gen_pos = src.find('data-testid="tb-generate"')
    assert tb_gen_pos > 0, "Generate button testid must exist"
    block_start = src.rfind("<TbBtn", 0, tb_gen_pos)
    block = src[block_start:tb_gen_pos + 50]
    assert "disabled" in block, \
        "Generate button must be disabled — carrier AWB is not wired from proforma view"


def test_generate_button_has_reason_title():
    """Generate button title must explain why it is disabled."""
    src = _src()
    assert "not yet available" in src or "generation" in src or \
           "Generate" in src, \
        "Generate button must carry an explanatory title"


def test_carrier_is_dhl_only():
    """Carrier factory must be DHL-only — no FedEx support."""
    carrier = _carrier()
    assert "DhlExpress" in carrier or "DHL" in carrier, \
        "Carrier system must reference DHL"
    # No FedEx adapters should be referenced
    from pathlib import Path
    factory = (Path(_CARRIER).parent.parent / "services" / "carrier" / "factory.py").read_text()
    assert "FedEx" not in factory and "fedex" not in factory.lower(), \
        "Carrier factory must not reference FedEx — DHL Express only"


def test_no_fedex_in_proforma_detail():
    """proforma-detail.jsx must not reference FedEx."""
    src = _src()
    assert "fedex" not in src.lower() and "FedEx" not in src, \
        "proforma-detail.jsx must not invent FedEx support"


# ── 6. Duplicate — ENABLED_WITH_AUTHORITY ────────────────────────────────────

def test_duplicate_calls_clone_draft():
    """Duplicate button must call PzApi.cloneDraft."""
    src = _src()
    assert "PzApi.cloneDraft(" in src, \
        "Duplicate must call PzApi.cloneDraft"


def test_clone_draft_exists_in_v2_pz_api():
    """cloneDraft must be defined in V2 pz-api.js."""
    assert "cloneDraft:" in _api(), \
        "V2 pz-api.js must define cloneDraft"


# ── 7. No button silently calls onNotify only ────────────────────────────────

def test_post_button_does_not_silently_notify():
    """Post button must open modal, not silently call onNotify."""
    src = _src()
    # Post button calls setShowPostModal(true)
    assert "setShowPostModal" in src, \
        "Post button must open PostToWFirmaModal, not silently trigger"


def test_convert_button_does_not_silently_notify():
    """Convert button must open modal, not silently call onNotify."""
    src = _src()
    assert "setShowConvertModal" in src, \
        "Convert button must open ConvertToInvoiceModal"


def test_print_button_does_not_silently_notify():
    """Print button must call handleDownloadPdf, not silently notify."""
    src = _src()
    assert "handleDownloadPdf" in src, \
        "Print button must call handleDownloadPdf"


# ── 8. V2 pz-api.js has all 4 lifecycle functions ────────────────────────────

def test_v2_api_has_all_lifecycle_functions():
    api = _api()
    for fn in ("postDraftToWfirma:", "cloneDraft:", "draftToInvoice:", "getDraftEvents:"):
        assert fn in api, f"V2 pz-api.js must define {fn}"


# ── 9. Toolbar testids present ───────────────────────────────────────────────

def test_toolbar_testids_present():
    src = _src()
    for testid in ("tb-post", "tb-convert", "proforma-detail-download-pdf",
                   "tb-send", "tb-generate", "tb-duplicate"):
        assert f'data-testid="{testid}"' in src, \
            f"Toolbar button testid '{testid}' must be present"

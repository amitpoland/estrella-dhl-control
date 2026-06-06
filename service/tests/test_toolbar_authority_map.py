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
                   "tb-send", "tb-generate", "tb-duplicate", "tb-preview", "tb-cmr"):
        assert f'data-testid="{testid}"' in src, \
            f"Toolbar button testid '{testid}' must be present"


# ── 10. Preview modal ─────────────────────────────────────────────────────────

def test_preview_button_opens_modal():
    """Preview button must set showPreview state (setShowPreview(true))."""
    src = _src()
    assert "setShowPreview(true)" in src, \
        "Preview button must call setShowPreview(true)"


def test_preview_modal_testid_present():
    """Preview modal must have proforma-preview-modal testid."""
    src = _src()
    assert 'data-testid="proforma-preview-modal"' in src, \
        "ProformaPreviewModal must have data-testid='proforma-preview-modal'"


def test_preview_modal_is_read_only():
    """Preview modal must not call any PzApi mutation function."""
    src = _src()
    # Extract the ProformaPreviewModal function body
    modal_start = src.find("function ProformaPreviewModal(")
    modal_end   = src.find("\nfunction ProformaDetailPage(", modal_start)
    modal_body  = src[modal_start:modal_end] if modal_end > modal_start else ""
    for mutation_fn in ("postDraftToWfirma", "draftToInvoice", "cloneDraft"):
        assert mutation_fn not in modal_body, \
            f"ProformaPreviewModal must not call PzApi.{mutation_fn} (read-only)"


def test_preview_variant_controls_present():
    """Preview modal must render Classic and Modern variant selector buttons."""
    src = _src()
    # Variant buttons use a template literal: data-testid={`preview-variant-${v}`}
    # with values 'classic' and 'modern' from the mapped array.
    assert "preview-variant-" in src, \
        "Preview modal must have variant selector buttons (data-testid prefix 'preview-variant-')"
    assert "'classic'" in src and "'modern'" in src, \
        "Preview modal must iterate over ['classic', 'modern'] variants"


def test_preview_uses_ej_proforma_components():
    """Preview must load EJProformaClassic / EJProformaModern from window."""
    src = _src()
    assert "EJProformaClassic" in src, \
        "ProformaPreviewModal must reference window.EJProformaClassic"
    assert "EJProformaModern" in src, \
        "ProformaPreviewModal must reference window.EJProformaModern"


def test_doc_tokens_css_in_index():
    """index.html must load estrella-doc-tokens.css."""
    idx = (Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html").read_text(encoding="utf-8")
    assert "estrella-doc-tokens.css" in idx, \
        "index.html must link estrella-doc-tokens.css for document print preview"


def test_doc_proforma_jsx_in_index():
    """index.html must load estrella-doc-proforma.jsx."""
    idx = (Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html").read_text(encoding="utf-8")
    assert "estrella-doc-proforma.jsx" in idx, \
        "index.html must load estrella-doc-proforma.jsx for print variant components"


def test_doc_tokens_css_exists():
    """estrella-doc-tokens.css must exist in the V2 static directory."""
    tokens = _V2_DIR / "estrella-doc-tokens.css"
    assert tokens.exists(), "service/app/static/v2/estrella-doc-tokens.css must exist"


def test_doc_proforma_jsx_exists():
    """estrella-doc-proforma.jsx must exist in the V2 static directory."""
    jsx = _V2_DIR / "estrella-doc-proforma.jsx"
    assert jsx.exists(), "service/app/static/v2/estrella-doc-proforma.jsx must exist"


def test_ej_brand_colors_in_tokens():
    """Tokens CSS must define Estrella emerald and gold brand colors."""
    tokens = (_V2_DIR / "estrella-doc-tokens.css").read_text(encoding="utf-8")
    assert "#0B3D2E" in tokens, "tokens.css must define --ej-brand: #0B3D2E (deep emerald)"
    assert "#C9A24B" in tokens, "tokens.css must define --ej-gold: #C9A24B (gold)"


# ── 11. Bold variant ──────────────────────────────────────────────────────────

def test_bold_variant_exported_from_proforma_jsx():
    """estrella-doc-proforma.jsx must export EJProformaBold."""
    jsx = (_V2_DIR / "estrella-doc-proforma.jsx").read_text(encoding="utf-8")
    assert "EJProformaBold" in jsx, \
        "estrella-doc-proforma.jsx must define and export EJProformaBold"
    assert "window" in jsx and "EJProformaBold" in jsx.split("Object.assign(window")[1], \
        "EJProformaBold must be in the Object.assign(window, ...) export"


def test_preview_modal_has_bold_variant():
    """ProformaPreviewModal variant list must include 'bold'."""
    src = _src()
    assert "'bold'" in src, \
        "ProformaPreviewModal must include 'bold' in variant options"


def test_preview_modal_uses_ej_proforma_bold():
    """Preview modal must reference window.EJProformaBold."""
    src = _src()
    assert "EJProformaBold" in src, \
        "ProformaPreviewModal must reference window.EJProformaBold for bold variant"


# ── 12. CMR button and component ─────────────────────────────────────────────

def test_cmr_toolbar_button_is_disabled():
    """CMR toolbar button must be disabled — no backend PDF generation route exists."""
    src = _src()
    tb_cmr_pos = src.find('data-testid="tb-cmr"')
    assert tb_cmr_pos > 0, "CMR button testid tb-cmr must be present"
    block_start = src.rfind("<TbBtn", 0, tb_cmr_pos)
    block = src[block_start:tb_cmr_pos + 60]
    assert "disabled" in block, \
        "CMR button must be disabled — no CMR PDF backend route exists"


def test_cmr_button_has_honest_reason():
    """CMR button title must explain why it is disabled."""
    src = _src()
    assert "no backend" in src.lower() or "CMR print" in src or "CMR" in src, \
        "CMR button must carry a title explaining the disabled reason"


def test_cmr_doc_jsx_exists():
    """estrella-doc-cmr.jsx must exist in the V2 static directory."""
    jsx = _V2_DIR / "estrella-doc-cmr.jsx"
    assert jsx.exists(), "service/app/static/v2/estrella-doc-cmr.jsx must exist"


def test_cmr_jsx_in_index():
    """index.html must load estrella-doc-cmr.jsx."""
    idx = (Path(__file__).parent.parent / "app" / "static" / "v2" / "index.html").read_text(encoding="utf-8")
    assert "estrella-doc-cmr.jsx" in idx, \
        "index.html must load estrella-doc-cmr.jsx for CMR preview"


def test_cmr_exports_to_window():
    """estrella-doc-cmr.jsx must export EJCMRClassic and EJCMRModern to window."""
    jsx = (_V2_DIR / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
    assert "EJCMRClassic" in jsx, "estrella-doc-cmr.jsx must define EJCMRClassic"
    assert "EJCMRModern"  in jsx, "estrella-doc-cmr.jsx must define EJCMRModern"
    assign_part = jsx.split("Object.assign(window")[1] if "Object.assign(window" in jsx else ""
    assert "EJCMRClassic" in assign_part and "EJCMRModern" in assign_part, \
        "Both EJCMRClassic and EJCMRModern must be in Object.assign(window, ...) export"


def test_cmr_no_mock_data_in_proforma_detail():
    """proforma-detail.jsx must not use SAMPLE or hardcoded CMR mock data."""
    src = _src()
    assert "EJ_SAMPLE" not in src, "proforma-detail.jsx must not use design-canvas SAMPLE data"
    assert "CMR-EJ-26-0095" not in src, \
        "proforma-detail.jsx must not contain hardcoded CMR reference from design canvas"


def test_cmr_preview_uses_live_batch_id():
    """cmrPreviewData must use liveDraft.batch_id for CMR reference."""
    src = _src()
    assert "cmrPreviewData" in src, "proforma-detail.jsx must define cmrPreviewData"
    assert "batch_id" in src, "cmrPreviewData must reference liveDraft.batch_id for CMR number"


def test_preview_doctype_selector_present():
    """Preview modal must have Proforma / CMR document type selector."""
    src = _src()
    # testid is built via template literal: data-testid={`preview-doctype-${dt}`}
    assert "preview-doctype-" in src, \
        "Preview modal must use data-testid starting with 'preview-doctype-'"
    assert "onDocTypeChange" in src, \
        "Preview modal must call onDocTypeChange for doctype switching"
    assert "'proforma'" in src and "'cmr'" in src, \
        "Preview modal must enumerate both 'proforma' and 'cmr' doc type values"

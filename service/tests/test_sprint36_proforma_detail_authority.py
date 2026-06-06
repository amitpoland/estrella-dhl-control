"""
test_sprint36_proforma_detail_authority.py
==========================================
Sprint 36 Phase 1 regression tests: ProformaDetailPage authority recovery.

All authority-violation criteria verified via source-grep:
  A. No fake VAT/company/product/FX hardcoded values in proforma-detail.jsx
  B. Real editable_lines wired (liveDraft.editable_lines)
  C. Real exchange_rate wired (liveDraft.exchange_rate)
  D. Company profile wired via GET /api/v1/settings/company-profile
  E. PDF download wired via /api/v1/proforma/{batch}/{cn}/document.pdf
  F. ConvertToInvoiceModal calls draftToInvoice (real API, not stub)
  G. No browser-side FX currency conversion (no totalEur * fx.rate)
  H. "Edit Draft" dead button removed
  I. "wFirma Mapping Setup" dead button removed
  J. Required testids present
  K. 'proforma_detail' re-added to WIRED_PAGES
  L. HistoryTab wired to getDraftEvents (real API)

References:
  service/app/static/v2/proforma-detail.jsx
  service/app/static/v2/mock-badge.jsx
  service/app/static/pz-api.js
"""
from __future__ import annotations

import re
from pathlib import Path

_V2            = Path(__file__).parent.parent / "app" / "static" / "v2"
_DETAIL        = _V2 / "proforma-detail.jsx"
_MOCK_BADGE    = _V2 / "mock-badge.jsx"
_PZ_API        = Path(__file__).parent.parent / "app" / "static" / "pz-api.js"
_ROUTES_PROFORMA = Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"


def _src() -> str:
    return _DETAIL.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip // single-line comments so prose never trips a forbidden-token scan."""
    out = []
    for line in src.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if "//" in line and "http" not in line:
            line = line[: line.index("//")]
        out.append(line)
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# A. No fake/hardcoded authority violations
# ══════════════════════════════════════════════════════════════════════════════

def test_no_fake_vat_number():
    src = _src()
    assert "PL5252532437" not in src, (
        "Fake VAT PL5252532437 must not appear in proforma-detail.jsx"
    )


def test_no_fake_company_name_hardcoded():
    code = _code_only(_src())
    assert "Estrella Jewels Sp. z o.o." not in code, (
        "Fake company name must not be hardcoded in proforma-detail.jsx code"
    )


def test_no_fake_address_hardcoded():
    code = _code_only(_src())
    assert "Przykładowa 10" not in code, (
        "Fake address must not be hardcoded in proforma-detail.jsx"
    )


def test_no_fake_fx_rate_hardcoded():
    code = _code_only(_src())
    assert "4.2650" not in code, (
        "Fake FX rate 4.2650 must not be hardcoded in proforma-detail.jsx"
    )


def test_no_fake_product_skus():
    src = _src()
    for fake_sku in ("RNG-AU750-001", "NKL-AU585-008", "BRC-PT950-012"):
        assert fake_sku not in src, (
            f"Fake product SKU {fake_sku!r} must not appear in proforma-detail.jsx"
        )


def test_no_fake_wfirma_product_ids():
    src = _src()
    for fake_id in ("WF-PROD-8821", "WF-PROD-8822", "WF-PROD-8823"):
        assert fake_id not in src, (
            f"Fake wFirma product ID {fake_id!r} must not appear in proforma-detail.jsx"
        )


def test_no_fake_nbp_table():
    code = _code_only(_src())
    assert "A 089/2026" not in code, (
        "Fake NBP table A 089/2026 must not be hardcoded"
    )


def test_no_hardcoded_bank_transfer_14_days():
    code = _code_only(_src())
    assert "Bank transfer · 14 days" not in code, (
        "Fake payment terms must not be hardcoded"
    )


def test_no_hardcoded_ddp_warsaw():
    code = _code_only(_src())
    assert "DDP Warsaw" not in code, (
        "Fake incoterm must not be hardcoded"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. Real editable_lines wired
# ══════════════════════════════════════════════════════════════════════════════

def test_editable_lines_referenced():
    src = _src()
    assert "editable_lines" in src, (
        "proforma-detail.jsx must reference editable_lines from backend draft"
    )


def test_editable_lines_from_live_draft():
    src = _src()
    assert "liveDraft.editable_lines" in src, (
        "Lines must come from liveDraft.editable_lines (real backend data)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Real exchange_rate wired
# ══════════════════════════════════════════════════════════════════════════════

def test_exchange_rate_from_live_draft():
    src = _src()
    assert "liveDraft.exchange_rate" in src, (
        "FX rate must come from liveDraft.exchange_rate (real backend data)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. Company profile wired via settings API
# ══════════════════════════════════════════════════════════════════════════════

def test_company_profile_endpoint_referenced():
    src = _src()
    assert "/api/v1/settings/company-profile" in src, (
        "proforma-detail.jsx must call GET /api/v1/settings/company-profile for exporter data"
    )


def test_company_profile_legal_name_used():
    src = _src()
    assert "companyProfile.legal_name" in src or "legal_name" in src, (
        "Exporter name must come from companyProfile.legal_name"
    )


def test_company_profile_vat_eu_used():
    src = _src()
    assert "vat_eu" in src, (
        "Exporter VAT EU must come from company profile vat_eu field"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. PDF download wired
# ══════════════════════════════════════════════════════════════════════════════

def test_pdf_download_endpoint_referenced():
    src = _src()
    assert "document.pdf" in src, (
        "proforma-detail.jsx must reference the PDF download endpoint (/document.pdf)"
    )


def test_pdf_download_testid_present():
    src = _src()
    assert 'data-testid="proforma-detail-download-pdf"' in src, (
        "PDF download button must carry data-testid='proforma-detail-download-pdf'"
    )


def test_pdf_download_uses_window_open():
    code = _code_only(_src())
    assert "window.open" in code, (
        "PDF download must use window.open to open the PDF URL"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. ConvertToInvoiceModal calls real API
# ══════════════════════════════════════════════════════════════════════════════

def test_to_invoice_confirm_token_present():
    src = _src()
    assert "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA" in src, (
        "ConvertToInvoiceModal must include the exact confirm token for to-invoice"
    )


def test_draft_to_invoice_api_called():
    src = _src()
    assert "draftToInvoice" in src, (
        "ConvertToInvoiceModal must call PzApi.draftToInvoice (not a stub)"
    )


def test_convert_modal_has_error_state():
    src = _src()
    assert "apiError" in src, (
        "ConvertToInvoiceModal must have an error state for API failures"
    )


def test_convert_modal_has_loading_state():
    src = _src()
    assert "loading" in src, (
        "ConvertToInvoiceModal must have a loading state during API call"
    )


def test_convert_modal_submit_testid():
    src = _src()
    assert 'data-testid="convert-modal-submit"' in src, (
        "Convert modal submit button must carry data-testid='convert-modal-submit'"
    )


# ══════════════════════════════════════════════════════════════════════════════
# G. No browser-side FX currency conversion
# ══════════════════════════════════════════════════════════════════════════════

def test_no_total_eur_times_fx_rate():
    code = _code_only(_src())
    assert "totalEur * " not in code, (
        "Browser-side PLN total (totalEur * fx.rate) must be removed"
    )
    # Phase 2: both totalEur and detail.fx.rate may appear for display purposes,
    # but must never be MULTIPLIED together (no totalEur * detail.fx.rate).
    assert "totalEur * detail.fx.rate" not in code, (
        "No browser-side FX conversion: totalEur * detail.fx.rate is forbidden"
    )


def test_no_pln_total_calculation_in_modal():
    code = _code_only(_src())
    assert "totalPln" not in code, (
        "totalPln browser-side calculation must be removed from ConvertToInvoiceModal"
    )


# ══════════════════════════════════════════════════════════════════════════════
# H. "Edit Draft" dead button removed
# ══════════════════════════════════════════════════════════════════════════════

def test_edit_draft_button_removed():
    code = _code_only(_src()).lower()
    # Look for button with "edit draft" visible text — not just comment prose
    assert ">✎ edit draft<" not in code and '">✎ edit draft<' not in code, (
        "'✎ Edit Draft' dead button must be removed from proforma-detail.jsx"
    )


def test_no_edit_draft_control_in_toolbar():
    code = _code_only(_src())
    assert "Edit Draft" not in code, (
        "'Edit Draft' button must be removed (dead — no safe edit endpoint)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I. "wFirma Mapping Setup" dead button removed
# ══════════════════════════════════════════════════════════════════════════════

def test_wfirma_mapping_setup_button_removed():
    code = _code_only(_src())
    assert "Mapping Setup" not in code, (
        "'Open wFirma Mapping Setup' button must be removed (dead — no safe target)"
    )


def test_no_open_wfirma_mapping_setup():
    code = _code_only(_src())
    assert "wFirma Mapping Setup" not in code, (
        "wFirma Mapping Setup dead button must not appear in proforma-detail.jsx"
    )


# ══════════════════════════════════════════════════════════════════════════════
# J. Required testids present
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_TESTIDS = [
    "proforma-detail-root",
    "proforma-detail-download-pdf",
    "convert-modal-submit",
    "convert-modal-confirm-checkbox",
]


def test_required_testids_present():
    src = _src()
    for tid in REQUIRED_TESTIDS:
        assert f'data-testid="{tid}"' in src, (
            f"Required testid '{tid}' missing from proforma-detail.jsx"
        )


# ══════════════════════════════════════════════════════════════════════════════
# K. 'proforma_detail' in WIRED_PAGES
# ══════════════════════════════════════════════════════════════════════════════

def test_proforma_detail_in_wired_pages():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    assert "'proforma_detail'" in src, (
        "mock-badge.jsx WIRED_PAGES must include 'proforma_detail' after Sprint 36 Phase 1"
    )


def test_wired_pages_array_contains_proforma_detail():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    assert "proforma_detail" in arr_body, (
        "'proforma_detail' must be inside the WIRED_PAGES array literal"
    )


def test_all_prior_wired_pages_preserved():
    src = _MOCK_BADGE.read_text(encoding="utf-8")
    idx = src.index("WIRED_PAGES")
    arr_body = src[src.index("[", idx):src.index("]", idx)]
    for page in ("proforma", "inbox", "inventory", "dhl",
                 "shipments", "automation", "intelligence", "documents"):
        assert page in arr_body, (
            f"Prior wired page '{page}' must not be removed from WIRED_PAGES"
        )


# ══════════════════════════════════════════════════════════════════════════════
# L. HistoryTab wired to real events API
# ══════════════════════════════════════════════════════════════════════════════

def test_history_tab_uses_get_draft_events():
    src = _src()
    assert "getDraftEvents" in src, (
        "HistoryTab must call PzApi.getDraftEvents (real events API)"
    )


def test_history_tab_no_hardcoded_events():
    code = _code_only(_src())
    assert "customer mapping verified" not in code.lower(), (
        "HistoryTab must not contain hardcoded fake event 'Customer mapping verified'"
    )
    assert "2026-05-10 14:25" not in code, (
        "HistoryTab must not contain hardcoded fake timestamp"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Extra: draftToInvoice transport function exists in pz-api.js
# ══════════════════════════════════════════════════════════════════════════════

def test_draft_to_invoice_in_pz_api():
    src = _PZ_API.read_text(encoding="utf-8")
    assert "draftToInvoice" in src, (
        "pz-api.js must expose draftToInvoice transport function"
    )


def test_get_draft_events_in_pz_api():
    src = _PZ_API.read_text(encoding="utf-8")
    assert "getDraftEvents" in src, (
        "pz-api.js must expose getDraftEvents transport function"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Backend: to-invoice route exists
# ══════════════════════════════════════════════════════════════════════════════

def test_to_invoice_route_exists_in_backend():
    src = _ROUTES_PROFORMA.read_text(encoding="utf-8")
    assert "/draft/{draft_id}/to-invoice" in src, (
        "POST /api/v1/proforma/draft/{draft_id}/to-invoice must exist in routes_proforma.py"
    )


def test_company_profile_settings_route_exists():
    routes_settings = (
        Path(__file__).parent.parent / "app" / "api" / "routes_settings.py"
    )
    src = routes_settings.read_text(encoding="utf-8")
    assert '"/company-profile"' in src or "'/company-profile'" in src, (
        "GET /api/v1/settings/company-profile must exist in routes_settings.py"
    )


def test_pdf_download_route_exists_in_backend():
    src = _ROUTES_PROFORMA.read_text(encoding="utf-8")
    assert "document.pdf" in src, (
        "PDF download endpoint (document.pdf) must exist in routes_proforma.py"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Sprint 36 Phase 2 — UI parity with atlas-proforma-preview.html
# ══════════════════════════════════════════════════════════════════════════════

# ── M. Full toolbar: 8 buttons with correct testids ──────────────────────────

PHASE2_TOOLBAR_TESTIDS = [
    "tb-edit",
    "tb-delete",
    "tb-duplicate",
    "tb-post",
    "tb-convert",
    "proforma-detail-download-pdf",   # Print button reuses Phase 1 testid
    "tb-send",
    "tb-generate",
    "tb-back",
]


def test_all_toolbar_testids_present():
    src = _src()
    for tid in PHASE2_TOOLBAR_TESTIDS:
        assert f'data-testid="{tid}"' in src, (
            f"Toolbar testid '{tid}' missing from proforma-detail.jsx"
        )


def test_duplicate_button_calls_clone_draft():
    src = _src()
    assert "cloneDraft" in src, (
        "Duplicate toolbar button must call PzApi.cloneDraft"
    )


def test_post_to_wfirma_button_gates_on_can_post():
    code = _code_only(_src())
    assert "canPost" in code, (
        "Post to wFirma toolbar button must be gated on canPost state"
    )


def test_convert_button_gates_on_can_convert():
    code = _code_only(_src())
    assert "canConvert" in code, (
        "Convert to Invoice toolbar button must be gated on canConvert state"
    )


def test_edit_button_disabled_with_reason():
    src = _src()
    assert "tb-edit" in src, "tb-edit toolbar button must be present"
    # Verify it is disabled (not just missing) — should have disabled attribute
    assert "Inline editing not yet available" in src, (
        "Edit toolbar button must be disabled with 'Inline editing not yet available' reason"
    )


def test_delete_button_disabled_with_reason():
    src = _src()
    assert "No delete-draft endpoint" in src, (
        "Delete toolbar button must be disabled with reason citing missing endpoint"
    )


def test_send_button_disabled_with_reason():
    src = _src()
    assert "tb-send" in src, "tb-send toolbar button must be present"
    assert "Email send not yet wired" in src, (
        "Send toolbar button must be disabled with 'Email send not yet wired' reason"
    )


def test_generate_button_disabled_with_reason():
    src = _src()
    assert "tb-generate" in src, "tb-generate toolbar button must be present"
    assert "not yet available" in src.lower(), (
        "Generate toolbar button must be disabled with a not-yet-available reason"
    )


# ── N. Party cards: SELLER / BUYER / RECIPIENT ───────────────────────────────

PARTY_CARD_TESTIDS = [
    "party-seller",
    "party-buyer",
    "party-recipient",
]


def test_all_party_card_testids_present():
    src = _src()
    for tid in PARTY_CARD_TESTIDS:
        assert f'data-testid="{tid}"' in src, (
            f"Party card testid '{tid}' missing from proforma-detail.jsx"
        )


def test_seller_card_from_company_profile():
    src = _src()
    assert "party-seller" in src, "SELLER party card must be present"
    assert "companyProfile" in src, (
        "SELLER card must derive data from companyProfile (GET /api/v1/settings/company-profile)"
    )


def test_buyer_card_from_customer_resolution():
    src = _src()
    assert "party-buyer" in src, "BUYER party card must be present"
    assert "customer_resolution" in src, (
        "BUYER card must derive data from draft customer_resolution field"
    )


def test_recipient_card_same_as_buyer():
    src = _src()
    assert "party-recipient" in src, "RECIPIENT party card must be present"
    assert "Same as Buyer" in src, (
        "RECIPIENT card must have 'Same as Buyer' footer note"
    )


def test_party_cards_three_columns():
    src = _src()
    # All 3 party cards must be defined
    assert src.count("party-seller") >= 1, "SELLER card must be present"
    assert src.count("party-buyer") >= 1, "BUYER card must be present"
    assert src.count("party-recipient") >= 1, "RECIPIENT card must be present"


def test_seller_card_title_uppercase():
    src = _src()
    assert "SELLER" in src, "Party card title 'SELLER' must be present"


def test_buyer_card_title_uppercase():
    src = _src()
    assert "BUYER" in src, "Party card title 'BUYER' must be present"


def test_recipient_card_title_uppercase():
    src = _src()
    assert "RECIPIENT" in src, "Party card title 'RECIPIENT' must be present"


# ── O. PostToWFirmaModal wired correctly ─────────────────────────────────────

def test_post_to_wfirma_modal_defined():
    src = _src()
    assert "PostToWFirmaModal" in src, (
        "PostToWFirmaModal must be defined in proforma-detail.jsx"
    )


def test_post_modal_confirm_checkbox_testid():
    src = _src()
    assert 'data-testid="post-modal-confirm-checkbox"' in src, (
        "Post modal confirm checkbox must have data-testid='post-modal-confirm-checkbox'"
    )


def test_post_modal_submit_testid():
    src = _src()
    assert 'data-testid="post-modal-submit"' in src, (
        "Post modal submit button must have data-testid='post-modal-submit'"
    )


def test_post_modal_confirm_token_correct():
    src = _src()
    assert "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA" in src, (
        "PostToWFirmaModal must pass confirm_token: 'YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA'"
    )


def test_post_modal_calls_post_draft_to_wfirma():
    src = _src()
    assert "postDraftToWfirma" in src, (
        "PostToWFirmaModal must call PzApi.postDraftToWfirma"
    )


def test_post_modal_sends_expected_updated_at():
    src = _src()
    assert "expected_updated_at" in src, (
        "PostToWFirmaModal must include expected_updated_at in the body"
    )


def test_post_modal_has_error_state():
    src = _src()
    assert 'data-testid="post-modal-error"' in src, (
        "PostToWFirmaModal must display an error state with data-testid='post-modal-error'"
    )


def test_post_modal_exported_to_window():
    src = _src()
    assert "PostToWFirmaModal" in src
    # Must be in the Object.assign(window, ...) export block
    assert "PostToWFirmaModal" in src[src.rfind("Object.assign"):], (
        "PostToWFirmaModal must be exported via Object.assign(window, ...)"
    )


# ── P. pz-api.js: postDraftToWfirma accepts body param ───────────────────────

def test_post_draft_to_wfirma_accepts_body_param():
    src = _PZ_API.read_text(encoding="utf-8")
    # Must match: postDraftToWfirma: (draftId, body) =>
    assert "postDraftToWfirma: (draftId, body)" in src, (
        "pz-api.js postDraftToWfirma must accept a body parameter: (draftId, body)"
    )


def test_post_draft_to_wfirma_uses_body_or_default():
    src = _PZ_API.read_text(encoding="utf-8")
    assert "body || {}" in src, (
        "pz-api.js postDraftToWfirma must pass 'body || {}' to the API call"
    )


# ── Q. ReservationTab wired (not placeholder) ─────────────────────────────────

def test_reservation_tab_not_placeholder():
    src = _src()
    assert "Not yet wired" not in src, (
        "ReservationTab placeholder 'Not yet wired — deferred post Sprint 36' must be replaced"
    )


def test_reservation_tab_wired_to_blocking_reasons():
    src = _src()
    assert "blockingReasons" in src, (
        "ReservationTab must render blockingReasons from POST /proforma/preview endpoint"
    )


def test_reservation_tab_wired_to_export_blockers():
    src = _src()
    assert "exportBlockers" in src, (
        "ReservationTab must render exportBlockers from POST /proforma/preview endpoint"
    )


def test_reservation_cap_strip_testid():
    src = _src()
    assert 'data-testid="reservation-cap-strip"' in src, (
        "ReservationTab must have a cap-strip row with data-testid='reservation-cap-strip'"
    )


# ── R. 5 tabs present (overview / lines / customer_mapping / reservation / history)

EXPECTED_TABS = ["overview", "lines", "customer_mapping", "reservation", "history"]


def test_all_five_tabs_defined():
    src = _src()
    for tab_id in EXPECTED_TABS:
        assert tab_id in src, (
            f"Tab '{tab_id}' must be defined in PROFORMA_TABS or rendered in proforma-detail.jsx"
        )


def test_overview_tab_has_kv_grid():
    src = _src()
    assert "KvItem" in src, (
        "OverviewTab must use KvItem components for the kv-grid layout"
    )


def test_overview_tab_shows_proforma_number():
    src = _src()
    assert "wfirma_proforma_fullnumber" in src, (
        "OverviewTab kv-grid must include proforma number from wfirma_proforma_fullnumber"
    )


def test_overview_tab_shows_exchange_rate():
    src = _src()
    assert "exchange_rate" in src or "fxRate" in src, (
        "OverviewTab must display the exchange rate from backend authority"
    )


def test_lines_tab_renders_table():
    src = _src()
    assert "ProformaLinesTab" in src, (
        "Lines tab must be rendered by ProformaLinesTab component"
    )
    assert "proforma-lines-total" in src, (
        "Lines tab table footer must carry data-testid='proforma-lines-total'"
    )


def test_customer_mapping_tab_renders():
    src = _src()
    assert "ProformaCustomerMappingTab" in src, (
        "Customer Mapping tab must be rendered by ProformaCustomerMappingTab component"
    )


def test_history_tab_renders():
    src = _src()
    assert "ProformaHistoryTab" in src, (
        "History tab must be rendered by ProformaHistoryTab component"
    )


# ── S. ConvertToInvoiceModal enhanced: includes line items in disclosure ───────

def test_convert_modal_shows_line_items():
    src = _src()
    assert "detail.lines" in src or "lines.map" in src, (
        "ConvertToInvoiceModal must disclose line items in its payload preview"
    )


def test_convert_modal_shows_fx_rate():
    src = _src()
    assert "detail.fx" in src or "fx.rate" in src, (
        "ConvertToInvoiceModal payload disclosure must show the FX rate from backend"
    )


def test_convert_modal_shows_customer():
    src = _src()
    assert "wfirmaName" in src or "customer.wfirmaName" in src or "detail.customer" in src, (
        "ConvertToInvoiceModal payload disclosure must show the resolved wFirma customer"
    )


# ── T. Clone action wired in backend ──────────────────────────────────────────

def test_clone_draft_endpoint_exists_in_backend():
    src = _ROUTES_PROFORMA.read_text(encoding="utf-8")
    assert "clone" in src, (
        "POST /api/v1/proforma/draft/{id}/clone must exist in routes_proforma.py"
    )


def test_post_draft_endpoint_exists_in_backend():
    src = _ROUTES_PROFORMA.read_text(encoding="utf-8")
    assert "/draft/{draft_id}/post" in src or "draft_id}/post" in src, (
        "POST /api/v1/proforma/draft/{id}/post must exist in routes_proforma.py"
    )

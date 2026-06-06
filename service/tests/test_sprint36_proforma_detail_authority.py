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
    assert "detail.fx.rate" not in code or "totalEur" not in code, (
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

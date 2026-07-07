"""
Proforma-v2 PDF-defect salvage contract (2026-07-07)

Source-grep regression contract locking the two bug-fix commits that were
salvaged after local `main` was reset to origin/main on 2026-07-07:

  a0a36a6  fix(proforma-v2): patch 13 PDF print defects found in PROF 151/2026
  476b7fa  fix(proforma): expose missing draft fields for document preview

Both fixes had already been lost once (the reset dropped them from the tree).
These assertions read source directly (no server) so a future upstream rewrite
of proforma-detail.jsx / routes_proforma.py cannot silently drop them again.
"""
from pathlib import Path

_ROOT = Path(__file__).parent.parent
PROFORMA_DETAIL = _ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"
ROUTES_PROFORMA = _ROOT / "app" / "api" / "routes_proforma.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── 476b7fa: _draft_to_full must expose the document display fields ───────────

def test_draft_to_full_exposes_document_display_fields():
    src = _src(ROUTES_PROFORMA)
    for key in (
        '"invoice_date"',
        '"wfirma_payment_due"',
        '"exchange_rate_date"',
        '"nbp_table"',
        '"incoterm"',
    ):
        assert key in src, f"_draft_to_full must expose {key} (salvage 476b7fa)"


def test_get_draft_enriches_description_and_origin():
    src = _src(ROUTES_PROFORMA)
    assert 'ln["description_pl"]' in src, "read-time description_pl enrichment (476b7fa)"
    assert 'ln["description_en"]' in src, "read-time description_en enrichment (476b7fa)"
    # origin enrichment from product_local authority
    assert "_pl_origin_index" in src, "product_local origin index enrichment (476b7fa)"


# ── a0a36a6: proforma-detail.jsx data-builder fixes ──────────────────────────

def test_origin_fallback_excludes_seller_country():
    """PL (seller) must not leak into goods origin — companyProfile.country
    removed from the origin fallback chain."""
    src = _src(PROFORMA_DETAIL)
    assert "origin:   ln.origin || liveDraft.origin_country || '—'" in src, \
        "origin fallback must not include companyProfile.country (a0a36a6)"


def test_awb_not_set_from_batch_id():
    """batch_id is a system reference, never a DHL AWB — carrier.awb stays null,
    batch_ref carries the reference."""
    src = _src(PROFORMA_DETAIL)
    assert "awb: liveDraft.batch_id" not in src, \
        "batch_id must not be rendered as AWB (a0a36a6)"
    assert "batch_ref: liveDraft.batch_id" in src, \
        "batch_id must pass through as batch_ref (a0a36a6)"


def test_qa_warnings_builder_present():
    src = _src(PROFORMA_DETAIL)
    for code in ("NO_FX_RATE", "NO_ISSUE_DATE", "MISSING_ORIGIN"):
        assert code in src, f"QA warnings builder must emit {code} (a0a36a6)"


def test_bank_name_currency_suffix_stripped():
    src = _src(PROFORMA_DETAIL)
    assert "_cleanBankName" in src, \
        "bank_name (EURO)/(EUR) suffix strip must be present (a0a36a6)"

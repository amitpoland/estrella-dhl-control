"""
test_proforma_readiness_draft_scope.py — Draft #38 class.

A proforma draft's readiness must be scoped to the product_codes IT bills
(editable_lines authority), NOT the client's whole sales packing list for the
batch. The preview reports wfirma_products / stock-state blockers at design-line
granularity over the entire client sales packing (e.g. "61 product(s) still in
PURCHASE_TRANSIT" for only 2 distinct billed product_codes). Surfacing those
verbatim mis-attributes other drafts'/clients' pieces to this draft.

Fix (_derive_draft_readiness): skip the client-wide wfirma_products + per-state
stock blockers from the preview and RE-DERIVE them draft-scoped — wfirma in
section 3, stock in section 3b — deduped to the draft's DISTINCT billed codes.
The wFirma PZ / export prerequisite (batch-level, real) is preserved.
"""
from __future__ import annotations

import json

import pytest

from app.api import routes_proforma as rp


PC1, PC2 = "EJL/26-27/292-1", "EJL/26-27/292-2"


class _FakeDraft:
    def __init__(self, lines, **kw):
        self.id = 1
        self.batch_id = "BATCH_SCOPE"
        self.client_name = "ClientA"
        self.client_contractor_id = ""
        self.draft_state = "editing"
        self.status = "editing"
        self.editable_lines_json = json.dumps(lines)
        for k, v in kw.items():
            setattr(self, k, v)


def _two_line_draft():
    return _FakeDraft([
        {"product_code": PC1, "design_no": "D1", "qty": 1, "unit_price": 100},
        {"product_code": PC2, "design_no": "D2", "qty": 1, "unit_price": 100},
    ])


def _patch_common(monkeypatch, preview):
    """Neutralise the gate's other sections so the test isolates the scope fix."""
    monkeypatch.setattr(rp, "_build_preview", lambda *a, **k: preview)
    monkeypatch.setattr(rp, "_preflight_approve", lambda *a, **k: None)
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda *a, **k: {"wfirma_customer_id": ""})
    # over-bill / fail-closed guard: authority available, ample stock so no
    # over-bill blocker and no packing-authority-unavailable blocker.
    import app.services.product_authority_resolver as par
    monkeypatch.setattr(par, "resolve_batch_product_authority", lambda *a, **k: {
        "authority_available": True, "authority_error": "",
        "available_by_product_code": {PC1: 999, PC2: 999},
        "invoice_by_product_code": {PC1: "INV", PC2: "INV"},
        "design_to_product_codes": {}, "product_codes": {PC1, PC2},
        "rows_scanned": 0, "rows_skipped": 0,
    })
    # design bridge summary (advisory) — keep quiet
    import app.services.design_product_bridge as dpb
    monkeypatch.setattr(dpb, "populate_from_packing",
                        lambda *a, **k: {"resolved_design_codes": {}})


def _reasons(monkeypatch, preview, intent="post", get_product=lambda pc: None):
    _patch_common(monkeypatch, preview)
    monkeypatch.setattr(rp.wfdb, "_db_path", "x")
    monkeypatch.setattr(rp.wfdb, "get_product", get_product)
    res = rp._derive_draft_readiness(_two_line_draft(), intent=intent)
    return [b["reason"] for b in res["blockers"]], res


# ── the client-wide inflated counts are dropped; the draft-scoped ones appear ──

def test_inflated_client_wide_blockers_are_scoped_to_billed_codes(monkeypatch):
    preview = {
        "blocking_reasons": [
            "61 product(s) not matched in wfirma_products",
            "61 product(s) still in PURCHASE_TRANSIT (not yet received in warehouse)",
        ],
        "export_blockers": [],
        "ambiguous_design_codes": {},
        "lines": [
            {"product_code": PC1, "stock_ok": False, "stock_status": "purchase_transit"},
            {"product_code": PC2, "stock_ok": False, "stock_status": "purchase_transit"},
            # other drafts'/clients' codes on the same batch — must NOT block this draft
            {"product_code": "OTHER/1", "stock_ok": False, "stock_status": "purchase_transit"},
            {"product_code": "OTHER/2", "stock_ok": False, "stock_status": "purchase_transit"},
        ],
    }
    reasons, _ = _reasons(monkeypatch, preview)
    # the inflated client-wide line-counts are gone
    assert not any("61 product" in r for r in reasons), reasons
    # other clients' codes never block this draft
    assert not any("OTHER" in r for r in reasons), reasons
    # draft-scoped transit blocker for the 2 DISTINCT billed codes (both in transit)
    assert any("2 product(s) still in PURCHASE_TRANSIT" in r for r in reasons), reasons
    # draft-scoped wfirma blocker (section 3) for the same 2 billed codes
    assert any("not matched in wfirma_products (missing wfirma_product_id)" in r
               for r in reasons), reasons
    assert any(PC1 in r and PC2 in r for r in reasons), reasons


def test_draft_with_received_codes_has_no_transit_blocker(monkeypatch):
    # this draft's 2 billed codes ARE received (stock_ok); other clients' codes
    # are still in transit. The draft must NOT inherit the transit blocker.
    preview = {
        "blocking_reasons": [
            "61 product(s) still in PURCHASE_TRANSIT (not yet received in warehouse)",
        ],
        "export_blockers": [],
        "ambiguous_design_codes": {},
        "lines": [
            {"product_code": PC1, "stock_ok": True, "stock_status": "warehouse_stock"},
            {"product_code": PC2, "stock_ok": True, "stock_status": "warehouse_stock"},
            {"product_code": "OTHER/1", "stock_ok": False, "stock_status": "purchase_transit"},
        ],
    }
    reasons, _ = _reasons(monkeypatch, preview)
    assert not any("PURCHASE_TRANSIT" in r for r in reasons), reasons


def test_pz_export_prerequisite_preserved_for_post(monkeypatch):
    # the wFirma PZ / export blocker is batch-level + REAL — it must survive.
    preview = {
        "blocking_reasons": [],
        "export_blockers": [
            "proforma export requires wFirma PZ — run wFirma PZ create before issuing a proforma"
        ],
        "ambiguous_design_codes": {},
        "lines": [
            {"product_code": PC1, "stock_ok": True, "stock_status": "warehouse_stock"},
            {"product_code": PC2, "stock_ok": True, "stock_status": "warehouse_stock"},
        ],
    }
    # codes ARE wfirma-mapped here so section 3 stays quiet — isolate the PZ gate
    reasons, res = _reasons(
        monkeypatch, preview, intent="post",
        get_product=lambda pc: {"wfirma_product_id": "999"})
    assert any("requires wFirma PZ" in r for r in reasons), reasons
    assert res["ready"] is False


def test_non_stock_non_wfirma_preview_blockers_still_surface(monkeypatch):
    # a generic preview blocker (e.g. missing sales price) is NOT a stock/wfirma
    # scope class — it must still surface verbatim.
    preview = {
        "blocking_reasons": [
            "3 line(s) missing sales unit_price or currency on the customer packing list",
        ],
        "export_blockers": [],
        "ambiguous_design_codes": {},
        "lines": [
            {"product_code": PC1, "stock_ok": True, "stock_status": "warehouse_stock"},
            {"product_code": PC2, "stock_ok": True, "stock_status": "warehouse_stock"},
        ],
    }
    reasons, _ = _reasons(monkeypatch, preview,
                          get_product=lambda pc: {"wfirma_product_id": "999"})
    assert any("missing sales unit_price" in r for r in reasons), reasons

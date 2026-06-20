"""test_document_readiness.py — pure-function review-state authority.

Pins ``app.services.document_readiness.derive_document_review`` — the single
backend authority for the Document Registry "Review" column. Pure: no DB/IO.

Invariants:
  - purchase_packing_list complete in packing.db (proven by effective status OR
    a positive line count) but 'pending' on shipment_documents → ready, NOT
    pending/blank (RC-1).
  - sales_packing_list complete + resolved client → ready; + unresolved client
    → blocked with reason; no contractor_context → never a false block.
  - failed/empty extraction → blocked with reason.
  - non-line document types → not_applicable.
  - EVERY combination returns a non-empty state/reason/code (never blank).

Run: python -m pytest tests/test_document_readiness.py -q
"""
from __future__ import annotations

import itertools

import pytest

from app.services import document_readiness as dr
from app.services.document_readiness import (
    REVIEW_READY, REVIEW_NEEDS_REVIEW, REVIEW_BLOCKED, REVIEW_NOT_APPLICABLE,
    derive_document_review,
)

_STATES = {REVIEW_READY, REVIEW_NEEDS_REVIEW, REVIEW_BLOCKED, REVIEW_NOT_APPLICABLE}


def _row(dt, ext="pending", parser="pending", rmr=False, cid="", sid=""):
    return {
        "document_type": dt,
        "extraction_status": ext,
        "parser_status": parser,
        "requires_manual_review": 1 if rmr else 0,
        "client_contractor_id": cid,
        "supplier_contractor_id": sid,
    }


# ── RC-1: purchase packing complete-but-stale-pending ───────────────────────

def test_purchase_packing_pending_row_with_complete_packing_status_is_ready():
    r = _row("purchase_packing_list", ext="pending")  # stale shipment_documents value
    out = derive_document_review(r, line_count=84, effective_extraction_status="complete")
    assert out.state == REVIEW_READY
    assert out.code == "ok"


def test_purchase_packing_pending_row_with_lines_is_ready_even_without_effective_status():
    """A positive line count alone proves completion — the registry must not show
    'pending' when 84 lines exist."""
    r = _row("purchase_packing_list", ext="pending")
    out = derive_document_review(r, line_count=84, effective_extraction_status=None)
    assert out.state == REVIEW_READY


def test_purchase_packing_genuinely_pending_no_lines_is_needs_review_not_blank():
    r = _row("purchase_packing_list", ext="pending")
    out = derive_document_review(r, line_count=0, effective_extraction_status="")
    assert out.state == REVIEW_NEEDS_REVIEW
    assert out.code == "awaiting_extraction"
    assert out.state and out.reason and out.code  # never blank


# ── failed / empty extraction → blocked ─────────────────────────────────────

@pytest.mark.parametrize("ext", ["extraction_failed", "failed", "empty", "error"])
def test_failed_or_empty_extraction_is_blocked(ext):
    r = _row("purchase_packing_list", ext=ext)
    out = derive_document_review(r, line_count=0)
    assert out.state == REVIEW_BLOCKED
    assert out.code == "extraction_failed"
    assert out.reason


def test_failed_status_but_lines_present_is_not_blocked():
    """If lines exist, a stale 'failed' must not override real data."""
    r = _row("sales_packing_list", ext="extraction_failed")
    out = derive_document_review(r, line_count=5,
                                contractor_context={"client_name": "C"})
    assert out.state == REVIEW_READY


# ── sales packing + contractor gate ─────────────────────────────────────────

def test_sales_complete_resolved_client_is_ready():
    r = _row("sales_packing_list", ext="extracted")
    out = derive_document_review(r, line_count=10,
                                contractor_context={"client_name": "Clear-Diamonds Ltd."})
    assert out.state == REVIEW_READY


def test_sales_complete_resolved_by_contractor_id_is_ready():
    r = _row("sales_packing_list", ext="extracted", cid="182241571")
    out = derive_document_review(r, line_count=10,
                                contractor_context={"client_contractor_id": "182241571",
                                                    "client_name": ""})
    assert out.state == REVIEW_READY


def test_sales_complete_unresolved_client_is_blocked():
    r = _row("sales_packing_list", ext="extracted")
    out = derive_document_review(r, line_count=10,
                                contractor_context={"client_contractor_id": "", "client_name": ""})
    assert out.state == REVIEW_BLOCKED
    assert out.code == "client_unresolved"
    assert "draft" in out.reason.lower()


def test_sales_complete_without_contractor_context_does_not_false_block():
    """Conservative: when no contractor context is supplied, the contractor gate
    is skipped (never a false block)."""
    r = _row("sales_packing_list", ext="extracted")
    out = derive_document_review(r, line_count=10, contractor_context=None)
    assert out.state == REVIEW_READY


# ── invoices ────────────────────────────────────────────────────────────────

def test_purchase_invoice_extracted_is_ready():
    r = _row("purchase_invoice", ext="extracted", parser="complete")
    out = derive_document_review(r, line_count=31)
    assert out.state == REVIEW_READY


def test_purchase_invoice_extracted_with_pending_parser_is_still_ready():
    """The legacy state: extraction_status='extracted' but parser_status='pending'
    must still resolve to ready, not pending."""
    r = _row("purchase_invoice", ext="extracted", parser="pending")
    out = derive_document_review(r, line_count=31)
    assert out.state == REVIEW_READY


def test_sales_invoice_extracted_is_ready():
    r = _row("sales_invoice", ext="extracted", parser="complete")
    out = derive_document_review(r, line_count=4)
    assert out.state == REVIEW_READY


def test_sales_invoice_failed_is_blocked():
    r = _row("sales_invoice", ext="extraction_failed")
    out = derive_document_review(r, line_count=0)
    assert out.state == REVIEW_BLOCKED
    assert out.code == "extraction_failed"


def test_sales_invoice_pending_no_lines_is_needs_review():
    r = _row("sales_invoice", ext="pending")
    out = derive_document_review(r, line_count=0)
    assert out.state == REVIEW_NEEDS_REVIEW
    assert out.code == "awaiting_extraction"


def test_placeholder_extraction_is_needs_review():
    r = _row("purchase_invoice", ext="placeholder")
    out = derive_document_review(r, line_count=0)
    assert out.state == REVIEW_NEEDS_REVIEW
    assert out.code == "placeholder_extraction"


def test_manual_review_flag_on_complete_is_needs_review():
    r = _row("purchase_invoice", ext="extracted", rmr=True)
    out = derive_document_review(r, line_count=5)
    assert out.state == REVIEW_NEEDS_REVIEW
    assert out.code == "manual_review_flagged"


# ── non-line documents ──────────────────────────────────────────────────────

@pytest.mark.parametrize("dt", ["awb", "service_invoice", "carnet", "packing", "", "unknown_type"])
def test_non_line_documents_are_not_applicable(dt):
    out = derive_document_review(_row(dt, ext="pending"), line_count=None)
    assert out.state == REVIEW_NOT_APPLICABLE
    assert out.code == "non_line_document"


# ── never-blank invariant + payload shape ───────────────────────────────────

def test_every_combination_yields_a_concrete_state():
    dts = ["purchase_packing_list", "sales_packing_list", "purchase_invoice",
           "sales_invoice", "awb", "service_invoice", ""]
    exts = ["pending", "extracted", "complete", "placeholder", "extraction_failed",
            "empty", "failed", ""]
    parsers = ["pending", "complete", "failed", ""]
    lcs = [None, 0, 7]
    ctxs = [None, {"client_name": ""}, {"client_name": "X"}]
    for dt, ext, parser, lc, ctx in itertools.product(dts, exts, parsers, lcs, ctxs):
        out = derive_document_review(_row(dt, ext=ext, parser=parser),
                                     line_count=lc, contractor_context=ctx)
        assert out.state in _STATES, (dt, ext, parser, lc, ctx, out.state)
        assert out.reason and isinstance(out.reason, str)
        assert out.code and isinstance(out.code, str)


def test_as_dict_keys():
    out = derive_document_review(_row("purchase_invoice", ext="extracted"), line_count=1)
    d = out.as_dict()
    assert set(d.keys()) == {"review_state", "review_reason", "review_code"}
    assert d["review_state"] == REVIEW_READY

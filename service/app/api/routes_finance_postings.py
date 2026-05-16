"""
routes_finance_postings.py — Phase 6F.3 — Read-only breakdown endpoint.

> **READ-ONLY. ONE ENDPOINT. NO WRITES. NO INTEGRATION.**

Single endpoint:

    GET /api/v1/finance/postings/{posting_id}/breakdown

Returns the full breakdown for one posting:
    - posting record
    - charges attached to the posting
    - payments attached to the posting
    - allocations linking those payments to charges
    - settlement (if recorded) else null
    - totals: charge_total_minor, payment_total_minor, balance_minor, is_fully_paid
    - schema_version

If the posting does not exist → HTTP 404.
All endpoints require X-API-Key authentication via the standard
``require_api_key`` dependency (mirrors every other Master Data route).

This module is INTENTIONALLY ISOLATED from posting/settlement/FX/PZ/wFirma/
proforma engines. The 6F.1.5 contract test suite enforces this; any future
batch that wires this module to those engines must update the contract
tests in the same diff.

DB initialisation:
    ``init_db`` is called inside the request handler (lazily). Main.py
    lifespan does NOT initialise this DB — that is a deliberate decision
    documented in ``tasks/phase-6f-3-implementation-plan.md``. The
    rationale: 6F.3 is the first runtime touch; init-on-first-request
    keeps the cost zero for installations that never call the endpoint.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.finance_postings_db import (
    SCHEMA_VERSION,
    Charge, Posting, Payment, PaymentAllocation, Settlement,
    init_db,
    get_posting,
    list_charges,
    list_payments,
    list_allocations,
    get_settlement_for_posting,
    compute_sum_charges_minor,
    compute_sum_payments_minor,
    is_fully_paid,
)


log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/finance/postings", tags=["finance-postings"])
_auth  = Depends(require_api_key)

_DB_PATH = settings.storage_root / "finance_postings.sqlite"


# ── Serialisation helpers (pure dict mappers; no I/O) ────────────────────────

def _posting_dict(p: Posting) -> Dict[str, Any]:
    return {
        "id": p.id, "batch_id": p.batch_id, "client_name": p.client_name,
        "wfirma_invoice_id": p.wfirma_invoice_id,
        "wfirma_doc_number": p.wfirma_doc_number,
        "posting_kind": p.posting_kind, "posted_at": p.posted_at,
        "issued_total_minor": p.issued_total_minor, "currency": p.currency,
        "fx_rate_at_issue": p.fx_rate_at_issue,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _charge_dict(c: Charge) -> Dict[str, Any]:
    return {
        "id": c.id, "batch_id": c.batch_id, "client_name": c.client_name,
        "charge_type": c.charge_type, "amount_minor": c.amount_minor,
        "currency": c.currency, "source": c.source,
        "posting_id": c.posting_id, "notes": c.notes,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def _payment_dict(p: Payment) -> Dict[str, Any]:
    return {
        "id": p.id, "posting_id": p.posting_id,
        "paid_at": p.paid_at, "amount_minor": p.amount_minor,
        "currency": p.currency,
        "fx_rate_at_payment": p.fx_rate_at_payment,
        "wfirma_payment_id": p.wfirma_payment_id, "source": p.source,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _alloc_dict(a: PaymentAllocation) -> Dict[str, Any]:
    return {
        "id": a.id, "payment_id": a.payment_id, "charge_id": a.charge_id,
        "applied_minor": a.applied_minor,
        "fx_delta_minor": a.fx_delta_minor,
        "allocation_method": a.allocation_method,
        "created_at": a.created_at,
    }


def _settlement_dict(s: Settlement) -> Dict[str, Any]:
    return {
        "id": s.id, "posting_id": s.posting_id,
        "settled_at": s.settled_at,
        "fx_delta_total_minor": s.fx_delta_total_minor,
        "rounding_diff_minor": s.rounding_diff_minor,
        "created_at": s.created_at,
    }


# ── The single endpoint ──────────────────────────────────────────────────────

@router.get(
    "/{posting_id}/breakdown",
    dependencies=[_auth],
    summary="Read-only breakdown for one posting",
)
def get_breakdown_endpoint(posting_id: int) -> JSONResponse:
    """Read-only assembly of posting + charges + payments + allocations +
    settlement + totals for a single posting id.

    Lazy init: ``init_db`` runs on every call (idempotent). This keeps the
    DB-file creation cost off the PZService startup path and confines the
    finance_postings.sqlite file's existence to installations that actually
    hit this endpoint at least once.

    404 if posting not found; the rest of the structure is always populated
    (empty arrays for charges/payments/allocations, null for settlement).
    """
    init_db(_DB_PATH)
    posting = get_posting(_DB_PATH, posting_id)
    if posting is None:
        raise HTTPException(
            status_code=404,
            detail=f"Posting not found: id={posting_id}",
        )

    charges     = list_charges(_DB_PATH,     posting_id=posting_id)
    payments    = list_payments(_DB_PATH,    posting_id=posting_id)

    # Allocations are joined by payment_id; only return allocations whose
    # payment is attached to THIS posting.
    payment_ids = {p.id for p in payments if p.id is not None}
    allocations: List[PaymentAllocation] = []
    for pid in payment_ids:
        allocations.extend(list_allocations(_DB_PATH, payment_id=pid))

    settlement = get_settlement_for_posting(_DB_PATH, posting_id)

    charge_total_minor  = compute_sum_charges_minor(_DB_PATH, posting_id)
    payment_total_minor = compute_sum_payments_minor(_DB_PATH, posting_id)
    balance_minor       = charge_total_minor - payment_total_minor
    paid                = is_fully_paid(_DB_PATH, posting_id)

    body: Dict[str, Any] = {
        "ok":             True,
        "posting_id":     posting_id,
        "schema_version": SCHEMA_VERSION,
        "posting":        _posting_dict(posting),
        "charges":        [_charge_dict(c) for c in charges],
        "payments":       [_payment_dict(p) for p in payments],
        "allocations":    [_alloc_dict(a) for a in allocations],
        "settlement":     _settlement_dict(settlement) if settlement else None,
        "totals": {
            "charge_total_minor":  charge_total_minor,
            "payment_total_minor": payment_total_minor,
            "balance_minor":       balance_minor,
            "is_fully_paid":       paid,
        },
    }
    log.info("finance_postings_breakdown posting_id=%s charges=%d payments=%d "
             "balance_minor=%d", posting_id, len(charges), len(payments),
             balance_minor)
    return JSONResponse(body)

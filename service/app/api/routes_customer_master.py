"""
routes_customer_master.py — Customer Master REST API (Layer 1 CRUD).

  GET  /api/v1/customer-master/
       List customers. Optional QS: country, risk_status, limit (default 200).

  GET  /api/v1/customer-master/{contractor_id}
       Read one customer by wFirma contractor id.  404 if absent.

  PUT  /api/v1/customer-master/{contractor_id}
       Create or update a customer record (upsert by contractor_id).
       Body is a JSON object with any subset of CustomerMaster fields.
       Returns the stored record.

All endpoints are X-API-Key authenticated.
DB path: settings.storage_root / "customer_master.sqlite"
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.customer_master_db import (
    CustomerMaster,
    validate,
    init_db,
    upsert_customer,
    get_customer,
    list_customers,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/customer-master", tags=["customer-master"])
_auth  = Depends(require_api_key)

_DB_PATH = settings.storage_root / "customer_master.sqlite"


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _dec_or_none(v) -> Optional[str]:
    """Serialise Decimal → string for JSON; None stays None."""
    if v is None:
        return None
    return str(Decimal(v))


def _customer_to_dict(c: CustomerMaster) -> Dict[str, Any]:
    return {
        "id":                            c.id,
        "bill_to_contractor_id":         c.bill_to_contractor_id,
        "bill_to_name":                  c.bill_to_name,
        "country":                       c.country,
        "nip":                           c.nip,
        "vat_eu_number":                 c.vat_eu_number,
        "vat_eu_valid":                  c.vat_eu_valid,
        "vat_eu_validated_at":           c.vat_eu_validated_at,
        "ship_to_use_alternate":         c.ship_to_use_alternate,
        "ship_to_name":                  c.ship_to_name,
        "ship_to_person":                c.ship_to_person,
        "ship_to_street":                c.ship_to_street,
        "ship_to_city":                  c.ship_to_city,
        "ship_to_zip":                   c.ship_to_zip,
        "ship_to_country":               c.ship_to_country,
        "ship_to_phone":                 c.ship_to_phone,
        "ship_to_email":                 c.ship_to_email,
        "ship_to_contractor_id":         c.ship_to_contractor_id,
        "default_currency":              c.default_currency,
        "default_language_id":           c.default_language_id,
        "preferred_proforma_series_id":  c.preferred_proforma_series_id,
        "preferred_invoice_series_id":   c.preferred_invoice_series_id,
        "vat_mode":                      c.vat_mode,
        # Freight
        "freight_service_id":            c.freight_service_id,
        "freight_last_amount":           _dec_or_none(c.freight_last_amount),
        "freight_avg_amount":            _dec_or_none(c.freight_avg_amount),
        "freight_currency":              c.freight_currency,
        "freight_mode":                  c.freight_mode,
        "freight_fixed_amount_eur":      _dec_or_none(c.freight_fixed_amount_eur),
        "freight_fixed_amount_usd":      _dec_or_none(c.freight_fixed_amount_usd),
        "freight_label_pl":              c.freight_label_pl,
        "freight_label_en":              c.freight_label_en,
        # Insurance
        "insurance_service_id":          c.insurance_service_id,
        "insurance_min_amount":          _dec_or_none(c.insurance_min_amount),
        "insurance_min_override":        _dec_or_none(c.insurance_min_override),
        "insurance_rate":                _dec_or_none(c.insurance_rate),
        "insurance_mode":                c.insurance_mode,
        "insurance_fixed_amount_eur":    _dec_or_none(c.insurance_fixed_amount_eur),
        "insurance_fixed_amount_usd":    _dec_or_none(c.insurance_fixed_amount_usd),
        "insurance_min_eur":             _dec_or_none(c.insurance_min_eur),
        "insurance_min_usd":             _dec_or_none(c.insurance_min_usd),
        "insurance_label_pl":            c.insurance_label_pl,
        "insurance_label_en":            c.insurance_label_en,
        "insurance_enabled":             c.insurance_enabled,
        # Credit / Kuke
        "credit_limit":                  _dec_or_none(c.credit_limit),
        "credit_currency":               c.credit_currency,
        "kuke_approved":                 c.kuke_approved,
        "kuke_limit":                    _dec_or_none(c.kuke_limit),
        "kuke_currency":                 c.kuke_currency,
        "kuke_expiry_date":              c.kuke_expiry_date,
        "risk_status":                   c.risk_status,
        "notes":                         c.notes,
        "created_at":                    c.created_at,
        "updated_at":                    c.updated_at,
    }


# ── Deserialisation helpers ───────────────────────────────────────────────────

_DECIMAL_FIELDS = frozenset({
    "freight_last_amount", "freight_avg_amount",
    "freight_fixed_amount_eur", "freight_fixed_amount_usd",
    "insurance_min_amount", "insurance_min_override", "insurance_rate",
    "insurance_fixed_amount_eur", "insurance_fixed_amount_usd",
    "insurance_min_eur", "insurance_min_usd",
    "credit_limit", "kuke_limit",
})

_BOOL_FIELDS = frozenset({
    "ship_to_use_alternate", "vat_eu_valid", "kuke_approved", "insurance_enabled",
})

_INT_FIELDS = frozenset({"vat_mode"})


def _parse_body(contractor_id: str, body: Dict[str, Any]) -> CustomerMaster:
    """Coerce raw JSON body → CustomerMaster dataclass.

    - bill_to_contractor_id is always injected from the URL path (body value ignored).
    - audit fields (id, created_at, updated_at) are stripped.
    - insurance_enabled defaults to True if absent.
    Raises HTTPException 422 on type conversion failures.
    """
    body = dict(body)
    body["bill_to_contractor_id"] = contractor_id

    # Decimal coercions
    for fname in _DECIMAL_FIELDS:
        if fname in body and body[fname] is not None:
            try:
                body[fname] = Decimal(str(body[fname]))
            except InvalidOperation:
                raise HTTPException(
                    status_code=422,
                    detail=f"{fname}: cannot parse {body[fname]!r} as Decimal",
                )

    # Bool coercions
    for fname in _BOOL_FIELDS:
        if fname in body and body[fname] is not None:
            body[fname] = bool(body[fname])

    # Int coercions
    for fname in _INT_FIELDS:
        if fname in body and body[fname] is not None:
            try:
                body[fname] = int(body[fname])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"{fname}: cannot parse {body[fname]!r} as int",
                )

    # Default insurance_enabled to True
    body.setdefault("insurance_enabled", True)

    # Strip server-managed audit fields
    for key in ("id", "created_at", "updated_at"):
        body.pop(key, None)

    try:
        return CustomerMaster(**body)
    except TypeError as exc:
        raise HTTPException(status_code=422, detail=f"CustomerMaster field error: {exc}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", dependencies=[_auth], summary="List customers")
def list_customers_endpoint(
    country:     Optional[str] = Query(None, description="ISO-3166 alpha-2 country filter"),
    risk_status: Optional[str] = Query(None, description="Filter by risk_status"),
    limit:       int           = Query(200, ge=1, le=1000, description="Max rows returned"),
) -> JSONResponse:
    """List customers with optional filters. Returns up to `limit` records,
    ordered by most-recently-updated first."""
    try:
        records = list_customers(_DB_PATH, country=country,
                                 risk_status=risk_status, limit=limit)
    except Exception as exc:
        log.error("list_customers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    return JSONResponse({
        "count": len(records),
        "customers": [_customer_to_dict(c) for c in records],
    })


@router.get("/{contractor_id}", dependencies=[_auth], summary="Get one customer")
def get_customer_endpoint(contractor_id: str) -> JSONResponse:
    """Read a customer by wFirma contractor id.  404 if not found."""
    try:
        record = get_customer(_DB_PATH, contractor_id)
    except Exception as exc:
        log.error("get_customer failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Customer not found: contractor_id={contractor_id!r}",
        )
    return JSONResponse(_customer_to_dict(record))


@router.put("/{contractor_id}", dependencies=[_auth], summary="Create or update customer")
async def upsert_customer_endpoint(contractor_id: str, request: Request) -> JSONResponse:
    """Upsert a customer record by wFirma contractor id.

    Body must be a JSON object. Required on first create: bill_to_name, country.
    Returns the stored record (including server-assigned id, created_at, updated_at).
    """
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    customer = _parse_body(contractor_id, body)

    errs = validate(customer)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": errs})

    try:
        init_db(_DB_PATH)
        row_id = upsert_customer(_DB_PATH, customer)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("upsert_customer failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    stored = get_customer(_DB_PATH, contractor_id)
    if stored is None:
        raise HTTPException(status_code=500,
                            detail="upsert succeeded but record not found on re-read")

    log.info("customer_master_upsert contractor_id=%s row_id=%d", contractor_id, row_id)
    return JSONResponse(status_code=200, content=_customer_to_dict(stored))

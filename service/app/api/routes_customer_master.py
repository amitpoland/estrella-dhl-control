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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..auth.dependencies import require_admin
from ..core.audit import audit_safe
from ..core.role_gate import require_role_or_apikey, MASTER_ADMIN, MASTER_EDITOR
from ..services.customer_master_db import (
    CustomerMaster,
    validate,
    init_db,
    upsert_customer,
    upsert_identity_only,
    get_customer,
    list_customers,
    soft_delete_customer,
    restore_customer,
    hard_delete_customer,
    find_customers_by_nip,
)
from ..services.customer_intelligence import (
    validate_customer_vat,
    kuke_is_currently_active,
    get_kuke_risk,
    HttpViesConnector,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/customer-master", tags=["customer-master"])
_auth       = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
_admin_auth = Depends(require_admin)

_DB_PATH = settings.storage_root / "customer_master.sqlite"


import hmac as _hmac


def _parse_active_query(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):  return True
    if s in ("false", "0", "no"):  return False
    raise HTTPException(status_code=422, detail=f"active must be true/false, got {v!r}")


def _resolve_list_active(v: Optional[str]) -> Optional[bool]:
    """Phase 4B Wave 3b-2 — default customer list to active-only when the
    ``active`` query param is omitted."""
    parsed = _parse_active_query(v)
    return True if parsed is None else parsed


def _hard_delete_guard(request: Request) -> None:
    """Phase 4B Wave 3b-2 — gate for DELETE ...?hard=true. Flag must be on
    AND caller must hold master_admin (or admin X-API-Key). Same contract as
    the suppliers / master-data guards."""
    if not settings.master_hard_delete_enabled:
        raise HTTPException(
            status_code=409,
            detail=("Hard delete is disabled. Set master_hard_delete_enabled "
                    "to true (admin) to permit permanent removal."),
        )
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if settings.api_key and key and _hmac.compare_digest(key.encode("utf-8"), settings.api_key.encode("utf-8")):
        return
    cookie = request.cookies.get("pz_session")
    if cookie:
        try:
            from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
            user = get_current_user_optional(pz_session=cookie)
        except Exception:
            user = None
        if user and (user.get("role") or "") == MASTER_ADMIN:
            return
    raise HTTPException(status_code=403,
                        detail="Hard delete requires master_admin role.")


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
        "preferred_proforma_series_id":         c.preferred_proforma_series_id,
        "preferred_invoice_series_id":          c.preferred_invoice_series_id,
        "preferred_wdt_invoice_series_id":      c.preferred_wdt_invoice_series_id,
        "preferred_export_invoice_series_id":   c.preferred_export_invoice_series_id,
        "preferred_payment_method":             c.preferred_payment_method,
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
        "kuke_policy_number":            c.kuke_policy_number,
        "kuke_self_retention_pct":       _dec_or_none(c.kuke_self_retention_pct),
        "payment_terms_days":            c.payment_terms_days,
        # KYC / Compliance
        "kyc_status":                    c.kyc_status,
        "kyc_approved_on":               c.kyc_approved_on,
        "kyc_expiry":                    c.kyc_expiry,
        "beneficial_owner":              c.beneficial_owner,
        "owner_id_type":                 c.owner_id_type,
        "owner_id_number":               c.owner_id_number,
        "aml_risk_rating":               c.aml_risk_rating,
        "pep_check_result":              c.pep_check_result,
        "compliance_notes":              c.compliance_notes,
        "notes":                         c.notes,
        "created_at":                    c.created_at,
        "updated_at":                    c.updated_at,
        # B0 enrichment fields
        "bill_to_email":                 c.bill_to_email,
        "bill_to_phone":                 c.bill_to_phone,
        "bill_to_mobile":                c.bill_to_mobile,
        "bank_account":                  c.bank_account,
        "last_wfirma_sync_at":           c.last_wfirma_sync_at,
        "wfirma_sync_source":            c.wfirma_sync_source,
        # B0 deep-enrichment 2026-05-17
        "bill_to_street":                c.bill_to_street,
        "bill_to_city":                  c.bill_to_city,
        "bill_to_postal_code":           c.bill_to_postal_code,
        # Backward-compat alias: the V1 Customer Master form reads `bill_to_country`
        # from the response.  The dataclass field is `country` (billing country).
        # Return both so that legacy UIs that read `bill_to_country` continue to work
        # without a frontend change.
        "bill_to_country":               c.country,
        "regon":                         c.regon,
        "short_code":                    c.short_code,
        "client_type":                   c.client_type,
        "industry":                      c.industry,
        "eori":                          c.eori,
        # Phase 4B Wave 3b-2 — soft-delete lifecycle.
        "active":                        c.active,
        "deleted_at":                    c.deleted_at,
    }


# ── Deserialisation helpers ───────────────────────────────────────────────────

_DECIMAL_FIELDS = frozenset({
    "freight_last_amount", "freight_avg_amount",
    "freight_fixed_amount_eur", "freight_fixed_amount_usd",
    "insurance_min_amount", "insurance_min_override", "insurance_rate",
    "insurance_fixed_amount_eur", "insurance_fixed_amount_usd",
    "insurance_min_eur", "insurance_min_usd",
    "credit_limit", "kuke_limit",
    "kuke_self_retention_pct",
})

_BOOL_FIELDS = frozenset({
    "ship_to_use_alternate", "vat_eu_valid", "kuke_approved", "insurance_enabled",
})

_INT_FIELDS = frozenset({"vat_mode", "payment_terms_days"})

# Allowed values for preferred_payment_method.  Any other non-empty value is
# rejected with 422 at the route layer before it reaches the DB.
# Empty string and None are normalised to NULL (wFirma default).
_ALLOWED_PAYMENT_METHODS: frozenset[str] = frozenset({
    "transfer", "cash", "card", "compensation",
})

# Optional string fields where an empty string from the UI must become None.
# These fields are nullable in the DB; "" is never a valid stored value.
_OPTIONAL_STR_FIELDS = frozenset({
    "freight_service_id", "insurance_service_id",
    "freight_mode", "freight_currency", "freight_label_pl", "freight_label_en",
    "insurance_mode", "insurance_label_pl", "insurance_label_en",
    "credit_currency",
    "kuke_currency", "kuke_expiry_date", "kuke_policy_number", "risk_status",
    "kyc_status", "kyc_approved_on", "kyc_expiry",
    "beneficial_owner", "owner_id_type", "owner_id_number",
    "aml_risk_rating", "pep_check_result", "compliance_notes",
    "notes",
    # B2 (MasterData-2.2): wFirma invoice/proforma defaults bound on Invoices tab
    "preferred_proforma_series_id", "preferred_invoice_series_id",
    "default_language_id",
    # B0 deep-enrichment 2026-05-17 — bill-to address + contact + operator
    # profile fields. Generic across every country / VAT regime / currency.
    "bill_to_street", "bill_to_city", "bill_to_postal_code",
    "bill_to_email", "bill_to_phone", "bill_to_mobile",
    "bank_account",
    # UI aliases — frontend form sends bill_to_nip and bill_to_country;
    # blank→None before alias pass (bill_to_nip → nip, bill_to_country → country)
    "bill_to_nip",
    "bill_to_country",
    # Ship-to alternate-address fields — must be '' → None coerced so that
    # clearing a previously-set alternate address persists as NULL rather
    # than empty string (operator complaint 2026-05-19: ship-to clears
    # round-trip as ""). ship_to_use_alternate is boolean (covered in
    # _BOOL_FIELDS). ship_to_contractor_id is the wFirma receiver id and
    # is allowed to be cleared by the operator.
    "ship_to_name", "ship_to_person", "ship_to_street",
    "ship_to_city", "ship_to_zip", "ship_to_country",
    "ship_to_phone", "ship_to_email", "ship_to_contractor_id",
    "regon", "short_code", "client_type", "industry", "eori",
    # default_currency was already accepted via the dataclass field but had
    # no '' → None coercion; route it through here so an operator clearing
    # the field saves NULL rather than the empty string.
    "default_currency",
    # Invoice/payment defaults (Campaign 9)
    "preferred_payment_method",
})


def _parse_body(
    contractor_id: str,
    body: Dict[str, Any],
    existing: Optional[CustomerMaster] = None,
) -> CustomerMaster:
    """Coerce raw JSON body → CustomerMaster dataclass.

    - bill_to_contractor_id is always injected from the URL path (body value ignored).
    - audit fields (id, created_at, updated_at) are stripped.
    - insurance_enabled defaults to True if absent.
    - Backward-compatibility hydration: when `existing` is supplied (partial
      update of an already-stored customer), required identity fields
      (bill_to_name, country) and any other field absent from the body are
      hydrated from the existing record before construction.  This restores
      legacy partial-PUT behaviour (e.g. the dashboard "Edit freight &
      insurance" modal which only sends freight/insurance keys) without
      relaxing the dataclass contract introduced by Campaign 5/6.
    Raises HTTPException 422 on type conversion failures.
    """
    body = dict(body)
    body["bill_to_contractor_id"] = contractor_id

    # ── Compatibility hydration ──────────────────────────────────────────────
    # If the customer already exists, fill in any field the caller did not
    # send from the stored record.  This makes PUT behave as PATCH for
    # already-known customers, which is what every legacy edit modal expects.
    if existing is not None:
        from dataclasses import fields as _dc_fields
        for f in _dc_fields(CustomerMaster):
            if f.name in ("id",):
                continue
            if f.name not in body or body[f.name] is None:
                # Only hydrate when caller omitted the key or sent null.
                # Never overwrite an explicit value the caller supplied.
                if f.name not in body:
                    body[f.name] = getattr(existing, f.name)
                else:
                    # body[f.name] is None — keep caller's intent for
                    # optional fields, but for the two REQUIRED identity
                    # fields fall back to existing so construction succeeds.
                    if f.name in ("bill_to_name", "country"):
                        body[f.name] = getattr(existing, f.name)

    # Decimal coercions — empty string is treated as None (not set) before parsing.
    for fname in _DECIMAL_FIELDS:
        if fname in body and body[fname] is not None:
            if body[fname] == "":
                body[fname] = None
                continue
            try:
                body[fname] = Decimal(str(body[fname]))
            except InvalidOperation:
                raise HTTPException(
                    status_code=422,
                    detail=f"{fname}: cannot parse {body[fname]!r} as Decimal",
                )

    # Bool coercions — explicit check against string "false"/"0" avoids
    # bool("false") == True trap when the UI serialises booleans as strings.
    for fname in _BOOL_FIELDS:
        if fname in body and body[fname] is not None:
            v = body[fname]
            if isinstance(v, str):
                body[fname] = v.strip().lower() not in ("false", "0", "")
            else:
                body[fname] = bool(v)

    # Int coercions — empty string becomes None first
    for fname in _INT_FIELDS:
        if fname in body:
            if body[fname] == "" or body[fname] is None:
                body[fname] = None
                continue
            try:
                body[fname] = int(body[fname])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"{fname}: cannot parse {body[fname]!r} as int",
                )

    # Blank-string → None normalisation for optional string fields.
    # The UI sends "" for every unset text input; "" must not reach validate()
    # as a whitespace-only invalid value, and must not be stored in the DB.
    for fname in _OPTIONAL_STR_FIELDS:
        if fname in body and body[fname] == "":
            body[fname] = None

    # Enum validation for preferred_payment_method.
    # After the blank→None pass above, None means "not set" (OK).
    # Any other value must be in the whitelist; unknown values are rejected
    # to keep the wFirma XML mapping deterministic.
    pm = body.get("preferred_payment_method")
    if pm is not None and pm not in _ALLOWED_PAYMENT_METHODS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"preferred_payment_method {pm!r} is not allowed. "
                f"Allowed values: {sorted(_ALLOWED_PAYMENT_METHODS)}"
            ),
        )

    # Default insurance_enabled to True
    body.setdefault("insurance_enabled", True)

    # Alias: UI form sends bill_to_nip; CustomerMaster dataclass field is nip.
    # After the blank→None pass above, bill_to_nip may be None (cleared) or a
    # VAT string. Map to nip if nip was not explicitly provided.
    if "bill_to_nip" in body:
        alias_val = body.pop("bill_to_nip")
        if "nip" not in body:
            body["nip"] = alias_val

    # Alias: UI form sends bill_to_country; CustomerMaster dataclass field is
    # `country` (the billing country — there is no separate bill_to_country field;
    # see resolve_billing_address() comment).  Map to `country` if country was
    # not explicitly provided.
    if "bill_to_country" in body:
        alias_val = body.pop("bill_to_country")
        if "country" not in body:
            body["country"] = alias_val

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
    active:      Optional[str] = Query(None,
        description="omit = active-only (default); 'false' = inactive only; 'true' = active only"),
    limit:       int           = Query(200, ge=1, le=1000, description="Max rows returned"),
    q:           Optional[str] = Query(None, description="Case-insensitive name search (substring)"),
) -> JSONResponse:
    """List customers with optional filters. Returns up to `limit` records,
    ordered by most-recently-updated first.

    Phase 4B Wave 3b-2: defaults to active-only when ``active`` is omitted.
    ``q`` filters by case-insensitive substring match on bill_to_name.
    """
    try:
        records = list_customers(_DB_PATH, country=country,
                                 risk_status=risk_status, limit=limit, q=q,
                                 active=_resolve_list_active(active))
    except Exception as exc:
        log.error("list_customers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    return JSONResponse({
        "count": len(records),
        "customers": [_customer_to_dict(c) for c in records],
    })


# ── B0 (MDOC-cache) — wFirma identity review-and-assign for Customer Master ──
#
# Reads wFirma contractors and proposes per-row actions the operator drives.
# Writes only when per-row target = customer_master AND flag
# WFIRMA_SYNC_CUSTOMERS_ALLOWED is on. Identity-only: name + country + nip;
# existing freight / insurance / KYC / shipping / invoice columns are NEVER
# overwritten (see upsert_identity_only in customer_master_db).

_CM_EXPENSE_HINTS = (
    "dhl", "fedex", " ups ", "tnt", "courier", "kurier", "hotel",
    "airline", "ryanair", "lufthansa", "lot polish", "uber",
    "tax office", "urzad skarbowy", "izba", "skarbowy",
    "bank ", "orlen ", "lotos ", "shell", "paypal", "stripe",
    "google ", "microsoft ", "amazon web", "facebook", "linkedin",
)
_CM_EXPORTER_HINTS = (
    "estrella", " llp", " llp.", "pvt ltd", "pvt. ltd", "exporter",
    "exports", "manufacturing", " factory", "industries", "jewels pvt",
    "gems & jewel",
)
_CM_EU_COUNTRIES = frozenset({
    "AT","BE","BG","CY","CZ","DE","DK","EE","ES","FI","FR","GR","HR","HU",
    "IE","IT","LT","LU","LV","MT","NL","PL","PT","RO","SE","SI","SK",
})


def _cm_suggest_target(name: str, vat_id: str, country: str) -> Dict[str, str]:
    """Pure deterministic suggestion. No AI. Operator can override."""
    nm = (name or "").lower().strip()
    cty = (country or "").upper().strip()
    vat = (vat_id or "").strip()
    if not nm:
        return {"suggested_target": "needs_operator_review", "reason": "missing_name"}
    if any(h in nm for h in _CM_EXPENSE_HINTS):
        return {"suggested_target": "ignore", "reason": "expense_or_carrier_keyword"}
    if any(h in nm for h in _CM_EXPORTER_HINTS):
        return {"suggested_target": "supplier_master", "reason": "exporter_keyword"}
    if vat and cty and cty in _CM_EU_COUNTRIES:
        return {"suggested_target": "client_master", "reason": "eu_vat_and_country_present"}
    if vat and cty:
        return {"suggested_target": "client_master", "reason": "vat_and_country_present"}
    return {"suggested_target": "needs_operator_review",
            "reason": ("missing_country" if not cty else "missing_vat")}


def _cm_wfirma_proposals() -> List[Dict[str, Any]]:
    """Per-row proposals comparing wFirma contractors against customer_master."""
    from ..services import wfirma_client as wfc
    contractors: List[Any] = []
    page = 1
    while True:
        batch = wfc.list_contractors_page(page=page, limit=100)
        if not batch:
            break
        contractors.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 200:
            break

    init_db(_DB_PATH)
    existing = list_customers(_DB_PATH, limit=10000)
    by_contractor: Dict[str, CustomerMaster] = {
        c.bill_to_contractor_id: c for c in existing if c.bill_to_contractor_id
    }

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for c in contractors:
        wfid = (c.wfirma_id or "").strip()
        name = (c.name or "").strip()
        nip  = (c.nip or "").strip()
        cty  = (c.country or "").strip().upper()
        # B0 enrichment — opportunistic from wFirma XML
        email  = (getattr(c, "email", "") or "").strip()
        phone  = (getattr(c, "phone", "") or "").strip()
        mobile = (getattr(c, "mobile", "") or "").strip()
        bank   = (getattr(c, "account_payments", "") or "").strip()
        pterm  = (getattr(c, "payment_term", "") or "").strip()

        if not wfid:
            out.append({
                "wfirma_id": "", "name": name, "vat_id": nip, "country": cty,
                "email": email or None, "phone": phone or None,
                "mobile": mobile or None, "bank_account": bank or None,
                "payment_term": pterm or None,
                "status": "skipped_invalid", "reason": "missing_wfirma_id",
                "suggested_target": "ignore",
                "local_match": None, "mismatches": [],
            })
            continue
        if wfid in seen:
            continue
        seen.add(wfid)

        match = by_contractor.get(wfid)
        status = "matched_existing" if match is not None else "new_candidate"
        if not name or not cty:
            status = "needs_operator_review"
            reason_target = {"suggested_target": "needs_operator_review",
                             "reason": ("missing_name" if not name else "missing_country")}
        else:
            reason_target = _cm_suggest_target(name, nip, cty)

        # Mismatch detection — for matched_existing rows where wFirma value
        # differs from a non-empty local value, surface a per-field flag so
        # the operator can decide. Apply still NEVER overwrites a non-empty
        # local value via upsert_identity_only's COALESCE semantics.
        mismatches: List[Dict[str, str]] = []
        if match is not None:
            checks = [
                ("name",          name,  match.bill_to_name),
                ("country",       cty,   match.country),
                ("vat_id",        nip,   (match.nip or "")),
                ("email",         email, (match.bill_to_email or "")),
                ("phone",         phone, (match.bill_to_phone or "")),
            ]
            for field, remote_val, local_val in checks:
                remote_s = (remote_val or "").strip()
                local_s  = (local_val  or "").strip()
                if remote_s and local_s and remote_s.lower() != local_s.lower():
                    mismatches.append({"field": field,
                                       "remote": remote_s, "local": local_s})

        out.append({
            "wfirma_id":         wfid,
            "name":              name,
            "vat_id":            nip,
            "country":           cty,
            "email":             email or None,
            "phone":             phone or None,
            "mobile":            mobile or None,
            "bank_account":      bank or None,
            "payment_term":      pterm or None,
            "status":            status,
            "reason":            reason_target["reason"],
            "suggested_target":  reason_target["suggested_target"],
            "mismatches":        mismatches,
            "local_match": None if match is None else {
                "id":                       match.id,
                "bill_to_contractor_id":    match.bill_to_contractor_id,
                "bill_to_name":             match.bill_to_name,
                "country":                  match.country,
                "bill_to_email":            match.bill_to_email,
                "bill_to_phone":            match.bill_to_phone,
                "default_currency":         match.default_currency,
                "payment_terms_days":       match.payment_terms_days,
                "freight_service_id":       match.freight_service_id,
                "insurance_service_id":     match.insurance_service_id,
                "kyc_status":               match.kyc_status,
                "last_wfirma_sync_at":      match.last_wfirma_sync_at,
            },
        })
    return out


@router.get("/sync-from-wfirma/preview", dependencies=[_auth],
            summary="Per-row review proposals for wFirma -> Customer Master (no write)")
def cm_wfirma_sync_preview() -> JSONResponse:
    try:
        proposals = _cm_wfirma_proposals()
    except Exception as exc:
        log.error("cm wf preview failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )
    return JSONResponse({
        "ok":        True,
        "mode":      "preview",
        "fetched":   len(proposals),
        "proposals": proposals,
    })


@router.post("/sync-from-wfirma/apply", dependencies=[_admin_auth],
             summary="Apply only the wFirma rows the operator targeted at Customer Master")
async def cm_wfirma_sync_apply(request: Request) -> JSONResponse:
    """Body: {"wfirma_ids": ["123", ...]}.

    Identity-only write via upsert_identity_only(). Preserves all existing
    freight / insurance / KYC / shipping / invoice fields. Rows missing
    required fields are returned in the ``rejected`` list (no DB write).
    Flag-gated by WFIRMA_SYNC_CUSTOMERS_ALLOWED.
    """
    try:
        body: Any = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    wfirma_ids = body.get("wfirma_ids")
    if not isinstance(wfirma_ids, list) or not wfirma_ids:
        raise HTTPException(status_code=422,
                            detail="wfirma_ids must be a non-empty list of strings")
    if not all(isinstance(x, str) for x in wfirma_ids):
        raise HTTPException(status_code=422, detail="wfirma_ids must be a list of strings")

    # B0 semantic fix (2026-05-16): Save/Assign writes to the LOCAL
    # customer_master master only. No wFirma write occurs here. The legacy
    # WFIRMA_SYNC_CUSTOMERS_ALLOWED flag protected an outbound wFirma
    # contractor sync that this endpoint does NOT perform, so its gate is
    # not relevant — the operator's authenticated click + this route's
    # X-API-Key are sufficient. The flag remains in place for the original
    # /api/v1/wfirma/customers/sync (wfirma_customers mapping) endpoint.

    try:
        proposals = _cm_wfirma_proposals()
    except Exception as exc:
        log.error("cm wf apply preview failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"ok": False, "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}"},
        )

    requested = set(wfirma_ids)
    inserted = 0
    updated  = 0
    rejected: List[Dict[str, Any]] = []
    applied:  List[Dict[str, Any]] = []

    for p in proposals:
        if p["wfirma_id"] not in requested:
            continue
        if p["status"] in ("skipped_invalid", "needs_operator_review"):
            rejected.append({"wfirma_id": p["wfirma_id"], "reason": p["reason"],
                             "status": p["status"]})
            continue
        # B0 deep-enrichment 2026-05-16: per-row, look up the contractor's
        # full record via fetch_contractor_by_id to surface payment_term,
        # default_currency, language, invoice/proforma series, bank account.
        # The list-page response we already have in `p` rarely carries
        # these. Read-only against wFirma; never raises if the contractor
        # is unknown — we just fall back to the list-page values.
        deep_email   = p.get("email")
        deep_phone   = p.get("phone")
        deep_mobile  = p.get("mobile")
        deep_bank    = p.get("bank_account")
        deep_curr    = None       # not in wFirma contractor detail; baseline only
        deep_pterm   = None
        deep_lang    = None
        deep_pro_id  = None       # wFirma contractor detail does not expose
        deep_inv_id  = None       # series IDs at the contractor level
        deep_street  = None
        deep_city    = None
        deep_zip     = None
        deep_regon   = None
        try:
            from ..services import wfirma_client as wfc
            cd = wfc.fetch_contractor_by_id(p["wfirma_id"])
            if cd.ok:
                # XML keys verified live against a real contractor response (2026-05-17).
                deep_email  = deep_email  or (cd.email  or None)
                deep_phone  = deep_phone  or (cd.phone  or None)
                deep_mobile = deep_mobile or (cd.mobile or None)
                deep_bank   = deep_bank   or (cd.account_number or None)
                # payment_days is the real wFirma key (not payment_term).
                # "0" sentinel means "no preference"; treat as None.
                pd = (cd.payment_days or "").strip()
                if pd.isdigit() and int(pd) > 0:
                    deep_pterm = int(pd)
                deep_lang   = (cd.translation_language_id or "").strip() or None
                deep_street = (cd.street or "").strip() or None
                deep_city   = (cd.city or "").strip() or None
                deep_zip    = (cd.zip or "").strip() or None
                deep_regon  = (cd.regon or "").strip() or None
        except Exception as exc:
            # Deep-fetch failure is non-fatal — we still write identity.
            log.warning("deep-fetch failed for wfid=%s: %s", p["wfirma_id"], exc)

        try:
            res = upsert_identity_only(
                _DB_PATH,
                bill_to_contractor_id=p["wfirma_id"],
                bill_to_name=p["name"],
                country=p["country"],
                nip=p["vat_id"] or None,
                bill_to_email=deep_email,
                bill_to_phone=deep_phone,
                bill_to_mobile=deep_mobile,
                bank_account=deep_bank,
                default_currency=deep_curr,
                payment_terms_days=deep_pterm,
                default_language_id=deep_lang,
                preferred_proforma_series_id=deep_pro_id,
                preferred_invoice_series_id=deep_inv_id,
                bill_to_street=deep_street,
                bill_to_city=deep_city,
                bill_to_postal_code=deep_zip,
                regon=deep_regon,
            )
            if res["action"] == "inserted":
                inserted += 1
            else:
                updated += 1
            applied.append({"wfirma_id": p["wfirma_id"], "action": res["action"]})
        except ValueError as ve:
            rejected.append({"wfirma_id": p["wfirma_id"], "reason": str(ve),
                             "status": "validation_failed"})
        except Exception as exc:
            log.error("cm wf apply row failed wfid=%s: %s", p["wfirma_id"], exc, exc_info=True)
            rejected.append({"wfirma_id": p["wfirma_id"],
                             "reason": f"{type(exc).__name__}: {exc}",
                             "status": "internal_error"})

    body_out = {
        "ok":             True,
        "mode":           "write",
        "fetched":        len(proposals),
        "requested":      len(requested),
        "inserted":       inserted,
        "updated":        updated,
        "applied_count":  inserted + updated,
        "rejected":       rejected,
        "applied":        applied,
    }
    log.info("client_master_wf_apply requested=%d inserted=%d updated=%d rejected=%d",
             len(requested), inserted, updated, len(rejected))
    return JSONResponse(body_out)


# ── B0 deep-enrichment 2026-05-16 — dictionaries for the operator UI ─────────
# (Declared BEFORE /{contractor_id} so FastAPI does not route 'dictionaries'
# as a contractor id.)

@router.get("/dictionaries", dependencies=[_auth],
            summary="Operator-facing dictionaries (VAT modes, currencies, languages, series)")
def client_master_dictionaries() -> JSONResponse:
    """Read-only dictionary catalog the dashboard uses to render label
    dropdowns in place of raw wFirma IDs.

    Returns merged payload: hardcoded baseline overlaid by any live entries
    cached from a prior ``POST /dictionaries/refresh`` call in this process.
    ``source_state`` carries per-dictionary status (live / baseline /
    unavailable / error).
    """
    from ..services import wfirma_dictionary_cache as wdc
    return JSONResponse(wdc.get_dictionaries())


@router.post("/dictionaries/refresh", dependencies=[_admin_auth],
             summary="Operator-triggered refresh of live wFirma dictionaries")
def client_master_dictionaries_refresh() -> JSONResponse:
    """Read-only refresh of the live wFirma dictionaries (series/find).

    Hard rules:
    - **Read-only against wFirma.** Only `series/find` is called today.
      languages/find, currencies/find, invoiceseries/find, proformaseries/find
      were probed and return CONTROLLER NOT FOUND — they will never be
      called.
    - **Never raises.** Per-dictionary failures are isolated; the call
      returns the merged dictionary payload regardless.
    - **No contractor rows mutated.** No wFirma write.
    - Result is cached in-process. Survives until next process restart;
      operator re-triggers as needed.
    """
    from ..services import wfirma_dictionary_cache as wdc
    try:
        body = wdc.refresh_from_wfirma()
    except Exception as exc:
        log.error("dictionaries refresh failed: %s", exc, exc_info=True)
        # Still return whatever we have (baseline) so the UI never breaks.
        body = wdc.get_dictionaries()
        body["refresh_error"] = f"{type(exc).__name__}: {exc}"
    log.info(
        "dictionaries_refresh source_state=%s fetched_at=%s "
        "invoice_count=%d proforma_count=%d",
        body.get("source_state", {}),
        body.get("fetched_at"),
        len(body.get("invoice_series", [])),
        len(body.get("proforma_series", [])),
    )
    return JSONResponse(body)


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


@router.put("/{contractor_id}", dependencies=[_write_auth], summary="Create or update customer")
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

    # Fetch existing record (if any) so partial PUT payloads can be hydrated
    # from stored state for required identity fields (bill_to_name, country).
    # On first-create the lookup returns None and the dataclass contract is
    # enforced unchanged — caller MUST supply bill_to_name + country.
    try:
        init_db(_DB_PATH)
        existing = get_customer(_DB_PATH, contractor_id)
    except Exception as exc:
        log.error("get_customer pre-upsert failed contractor_id=%s: %s",
                  contractor_id, exc, exc_info=True)
        existing = None

    customer = _parse_body(contractor_id, body, existing=existing)

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
    audit_safe("customers", "create" if existing is None else "update", contractor_id,
               request=request, before=existing, after=stored)
    return JSONResponse(status_code=200, content=_customer_to_dict(stored))


@router.delete("/{contractor_id}", dependencies=[_write_auth],
               summary="Delete customer (soft-delete by default; ?hard=true for permanent)",
               status_code=204)
def delete_customer_endpoint(
    contractor_id: str, request: Request,
    hard: bool = Query(False, description="Permanent removal; requires master_admin + flag"),
):
    init_db(_DB_PATH)
    before = get_customer(_DB_PATH, contractor_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Customer not found: {contractor_id}")
    if hard:
        _hard_delete_guard(request)
        if not hard_delete_customer(_DB_PATH, contractor_id):
            raise HTTPException(status_code=404, detail=f"Customer not found: {contractor_id}")
        log.info("customer_master_hard_delete contractor_id=%s", contractor_id)
        audit_safe("customers", "hard_delete", contractor_id,
                   request=request, before=before, after=None)
        return Response(status_code=204)
    if not soft_delete_customer(_DB_PATH, contractor_id):
        raise HTTPException(status_code=404, detail=f"Customer not found: {contractor_id}")
    log.info("customer_master_soft_delete contractor_id=%s", contractor_id)
    audit_safe("customers", "delete", contractor_id,
               request=request, before=before, after=None)
    return Response(status_code=204)


@router.post("/{contractor_id}/restore", dependencies=[_write_auth],
             summary="Restore a soft-deleted customer")
def restore_customer_endpoint(contractor_id: str, request: Request) -> JSONResponse:
    init_db(_DB_PATH)
    before = get_customer(_DB_PATH, contractor_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Customer not found: {contractor_id}")
    if not restore_customer(_DB_PATH, contractor_id):
        raise HTTPException(status_code=404, detail=f"Customer not found: {contractor_id}")
    after = get_customer(_DB_PATH, contractor_id)
    log.info("customer_master_restore contractor_id=%s", contractor_id)
    audit_safe("customers", "restore", contractor_id,
               request=request, before=before, after=after)
    return JSONResponse(_customer_to_dict(after))


# ── CSV import / export (Wave 5) ──────────────────────────────────────────────
@router.get("/export/csv", dependencies=[_auth],
            summary="Export customers as CSV (injection-safe, UTF-8 BOM)")
def customers_export_csv(
    active: Optional[bool] = Query(None, description="Filter; omit = active only"),
    country: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
) -> Response:
    from ..services import master_csv
    init_db(_DB_PATH)
    eff_active = True if active is None else active
    rows = [_customer_to_dict(c) for c in
            list_customers(_DB_PATH, country=country, limit=limit, active=eff_active)]
    body = master_csv.rows_to_csv(rows, master_csv.customer_columns())
    from datetime import datetime, timezone
    fname = f"customer_master_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=body, media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache", "Expires": "0",
        },
    )


@router.post("/import/csv", dependencies=[_write_auth],
             summary="Import customers from CSV (dry-run by default; ?commit=true to apply)")
async def customers_import_csv(
    request: Request,
    file: UploadFile = File(...),
    commit: bool = Query(False, description="false = preview only; true = apply upserts"),
) -> JSONResponse:
    """Upsert customers by ``bill_to_contractor_id`` via the existing
    upsert_customer writer. Preview (default) reports what WOULD happen; commit
    applies. Each row is validated with the same ``validate`` used by PUT;
    system columns are ignored; empty cells never blank stored values.

    Duplicate-VAT is surfaced as an ADVISORY (per Lesson N) — it never blocks a
    row; the operator sees which existing customers share the NIP.
    """
    fname = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()
    if not (fname.endswith(".csv") or "csv" in ctype or ctype in
            ("application/vnd.ms-excel", "application/octet-stream", "text/plain")):
        raise HTTPException(status_code=422, detail="Upload must be a .csv file")

    from ..services import master_csv
    raw = await master_csv.read_capped(file, master_csv.MAX_IMPORT_BYTES)
    if raw is None:
        raise HTTPException(status_code=413, detail="CSV exceeds 5 MB limit")

    init_db(_DB_PATH)
    writable = master_csv.customer_import_writable()
    try:
        parsed = master_csv.parse_csv(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {exc}")
    if len(parsed) > master_csv.MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413,
                            detail=f"CSV exceeds {master_csv.MAX_IMPORT_ROWS} rows")

    created = updated = 0
    rejected: list = []
    dup_vat: list = []
    touched: list = []
    for line, row in parsed:
        data = master_csv.project_writable(row, writable)
        cid = data.pop("bill_to_contractor_id", None)
        if not cid:
            rejected.append({"row": line, "reason": "missing bill_to_contractor_id"})
            continue
        existing = get_customer(_DB_PATH, cid)
        try:
            customer = _parse_body(cid, data, existing=existing)
        except Exception as exc:
            rejected.append({"row": line, "reason": f"row error: {exc}"})
            continue
        errs = validate(customer)
        if errs:
            rejected.append({"row": line, "reason": "; ".join(errs)})
            continue
        # Advisory only — never blocks (Lesson N).
        nip = (data.get("nip") or "").strip()
        if nip and existing is None:
            others = [c.bill_to_contractor_id for c in find_customers_by_nip(_DB_PATH, nip)
                      if c.bill_to_contractor_id != cid]
            if others:
                dup_vat.append({"row": line, "nip": nip, "existing_contractor_ids": others})
        if not commit:
            if existing:
                updated += 1
            else:
                created += 1
            continue
        try:
            upsert_customer(_DB_PATH, customer)
            if existing:
                updated += 1
            else:
                created += 1
            touched.append(cid)
        except ValueError as exc:
            # Our own validation-class message — safe to reflect.
            rejected.append({"row": line, "reason": str(exc)})
        except Exception as exc:
            # Never reflect raw DB text (may leak schema); full detail to the log.
            log.error("customer csv import row=%d failed: %s", line, exc, exc_info=True)
            rejected.append({"row": line, "reason": "database error"})

    result = {
        "mode": "commit" if commit else "preview",
        "committed": bool(commit),
        "total_rows": len(parsed),
        "created": created, "updated": updated, "skipped": len(rejected),
        "rejected": rejected,
        "duplicate_vat_advisories": dup_vat,
    }
    if commit:
        audit_safe("customers", "csv_import", "-", request=request, before=None,
                   after={"total_rows": len(parsed), "created": created,
                          "updated": updated, "skipped": len(rejected),
                          "contractor_ids": touched[:500]})
    return JSONResponse(result)


@router.post(
    "/{contractor_id}/validate-vat",
    dependencies=[_write_auth],  # writes vat_eu_valid to Customer Master → master-write guard (RBAC)
    summary="Run VIES validation and update Customer Master vat_eu_valid field",
)
def validate_vat_endpoint(contractor_id: str, request: Request) -> JSONResponse:
    """Validate the customer's EU VAT number via the EC VIES REST API.

    WHAT THIS DOES
    - Reads the customer's vat_eu_number from Customer Master.
    - Calls the EC VIES REST API.
    - If valid or invalid: updates vat_eu_valid + vat_eu_validated_at in Customer Master.
    - If unavailable: leaves Customer Master unchanged.
    - Writes an audit log entry recording the before/after state.
    - Returns the validation result and current KUKE risk advisory.

    WHEN TO CALL
    - Manually, by operator, when onboarding a new EU customer.
    - After updating vat_eu_number.
    - On periodic compliance review (not on every page load).

    GOVERNANCE
    - Does NOT change vat_mode, kuke_approved, kyc_status, or fiscal fields.
    - VIES unavailable is advisory only — never a hard block.
    - Requires API key. No admin role needed (read + targeted write).
    """
    cm_before = get_customer(_DB_PATH, contractor_id)
    if cm_before is None:
        raise HTTPException(
            status_code=404,
            detail=f"Customer not found: contractor_id={contractor_id!r}",
        )

    try:
        action = validate_customer_vat(
            _DB_PATH,
            contractor_id,
            vies_connector=HttpViesConnector(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("validate_vat failed contractor_id=%s: %s", contractor_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"VIES validation error: {exc}")

    cm_after = get_customer(_DB_PATH, contractor_id)

    audit_safe(
        "customers", "update", contractor_id,
        request=request,
        before={
            "vat_eu_valid":        cm_before.vat_eu_valid,
            "vat_eu_validated_at": cm_before.vat_eu_validated_at,
        },
        after={
            "vat_eu_valid":        action.vat_eu_valid,
            "vat_eu_validated_at": action.validated_at,
            "vies_status":         action.vies_status,
            "source":              action.source,
        },
    )

    log.info(
        "validate_vat contractor_id=%s vies_status=%s cm_updated=%s",
        contractor_id, action.vies_status, action.cm_updated,
    )

    kuke_risk = get_kuke_risk(cm_after) if cm_after else None

    return JSONResponse({
        "contractor_id":     action.contractor_id,
        "vat_number":        action.vat_number,
        "vies_status":       action.vies_status,
        "vat_eu_valid":      action.vat_eu_valid,
        "cm_updated":        action.cm_updated,
        "validated_at":      action.validated_at,
        "source":            action.source,
        "raw_name":          action.raw_name,
        "raw_address":       action.raw_address,
        "advisory":          action.advisory,
        "d3_cleared":        action.d3_cleared,
        "d3_blocked":        action.d3_blocked,
        "kuke_risk": {
            "code":               kuke_risk.code,
            "level":              kuke_risk.level,
            "description":        kuke_risk.description,
            "recommended_action": kuke_risk.recommended_action,
        } if kuke_risk else None,
    })

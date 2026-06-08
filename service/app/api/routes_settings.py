"""routes_settings.py — Operator-facing settings endpoints.

Phase 7: company profile (seller identity + bank details).
Auth: require_api_key (same pattern as routes_proforma.py).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.config import settings
from ..core.security import require_api_key
from ..auth.dependencies import require_admin
from ..services.master_data_db import CompanyProfile, get_company_profile, upsert_company_profile

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_auth       = Depends(require_api_key)
_admin_auth = Depends(require_admin)

# Field names that callers may supply (excludes id and updated_at)
_ALLOWED_FIELDS = frozenset({
    "legal_name", "short_name", "street", "postal_city", "country",
    "nip", "vat_eu", "regon", "email", "phone",
    "iban_eur", "iban_usd", "iban_pln", "swift", "bank_name",
    "place_of_issue", "signatory_name", "signatory_title",
    "returns_policy_pl", "gdpr_text_pl",
})


@router.get("/company-profile", dependencies=[_auth])
async def get_company_profile_endpoint() -> Dict[str, Any]:
    db_path = settings.storage_root / "master_data.sqlite"
    profile = get_company_profile(db_path)
    if profile is None:
        # Return empty profile — never 404
        profile = CompanyProfile(legal_name="")
    return {"ok": True, "profile": dataclasses.asdict(profile)}


@router.patch("/company-profile", dependencies=[_admin_auth])
async def patch_company_profile_endpoint(request: Request) -> Dict[str, Any]:
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    filtered = {k: v for k, v in body.items() if k in _ALLOWED_FIELDS}
    db_path = settings.storage_root / "master_data.sqlite"
    profile = upsert_company_profile(db_path, **filtered)
    return {"ok": True, "profile": dataclasses.asdict(profile)}

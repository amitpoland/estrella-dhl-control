"""Carrier Master credential API — masked reads + admin-only writes.

Authority: Carrier Master (operator-facing). Persistence: DPAPI store via
CarrierCredentialService. No Reveal Secret. No vendor-specific route families.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import (
    require_carrier_credentials_admin,
    require_carrier_credentials_view,
)
from app.core.audit import audit_safe
from app.services.carrier.credentials.exceptions import (
    CarrierCredentialError,
    CarrierCredentialNotConfigured,
)
from app.services.carrier.credentials.credential_service import (
    CarrierCredentialService,
    audit_credential_event,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/carrier-credentials",
    tags=["carrier-credentials"],
)

_svc = CarrierCredentialService()


class CandidateBody(BaseModel):
    fields: dict[str, str] = Field(..., min_length=1)


class ActivateBody(BaseModel):
    slot: str = Field(..., pattern="^[ABab]$")


def _http_from_cred_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CarrierCredentialNotConfigured):
        return HTTPException(status_code=404, detail="credential not configured")
    if isinstance(exc, CarrierCredentialError):
        # Never include exception args that might echo vendor detail
        msg = str(exc)
        if "previous credential preserved" in msg:
            return HTTPException(status_code=422, detail=msg)
        if "unvalidated" in msg:
            return HTTPException(status_code=422, detail=msg)
        return HTTPException(status_code=422, detail="credential operation failed")
    return HTTPException(status_code=500, detail="credential operation failed")


@router.get(
    "/",
    dependencies=[Depends(require_carrier_credentials_view)],
    summary="List masked carrier credential status",
)
def list_credentials() -> JSONResponse:
    try:
        items = _svc.list_status()
    except CarrierCredentialNotConfigured:
        items = []
    except Exception:
        log.exception("list_credentials failed")
        raise HTTPException(status_code=500, detail="credential list failed")
    return JSONResponse({"count": len(items), "credentials": items})


@router.get(
    "/{carrier}/{environment}/{capability}",
    dependencies=[Depends(require_carrier_credentials_view)],
    summary="Get masked credential status",
)
def get_credential_status(
    carrier: str, environment: str, capability: str
) -> JSONResponse:
    try:
        return JSONResponse(_svc.status(carrier, capability, environment))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        log.exception("get_credential_status failed")
        raise HTTPException(status_code=500, detail="credential status failed")


@router.post(
    "/{carrier}/{environment}/{capability}/candidate",
    dependencies=[Depends(require_carrier_credentials_admin)],
    summary="Store candidate credential (does not activate)",
)
async def store_candidate(
    carrier: str,
    environment: str,
    capability: str,
    body: CandidateBody,
    request: Request,
    user: dict = Depends(require_carrier_credentials_admin),
) -> JSONResponse:
    try:
        public = _svc.store_candidate(
            carrier, capability, environment, body.fields, user=user
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CarrierCredentialError as exc:
        raise _http_from_cred_error(exc)
    except Exception:
        log.exception("store_candidate failed")
        raise HTTPException(status_code=500, detail="credential store failed")

    from app.services.carrier.credentials.models import (
        CapabilityState,
        CredentialIdentity,
        CredentialMeta,
    )

    meta = CredentialMeta(
        identity=CredentialIdentity(carrier, environment, capability),
        configured=public.get("configured", False),
        active=public.get("active", False),
        fingerprint=public.get("fingerprint"),
        masked_suffix=public.get("masked_identifier"),
        last_validated_at=public.get("last_validated_at"),
        last_rotated_at=public.get("last_rotated_at"),
        updated_by=public.get("updated_by"),
        state=CapabilityState(public.get("state", "stored_unvalidated")),
    )
    audit_safe(
        "carrier_credentials",
        "candidate",
        public["credential_reference"],
        request=request,
        after=audit_credential_event("candidate", meta, actor=str(user.get("email") or "admin")),
    )
    return JSONResponse(public)


@router.post(
    "/{carrier}/{environment}/{capability}/rotate",
    dependencies=[Depends(require_carrier_credentials_admin)],
    summary="Rotate credentials (validate optional; unvalidated keeps A active)",
)
async def rotate_credential(
    carrier: str,
    environment: str,
    capability: str,
    body: CandidateBody,
    request: Request,
    user: dict = Depends(require_carrier_credentials_admin),
    validate: bool = False,
) -> JSONResponse:
    """
    validate=false (default): store candidate only → stored_unvalidated; A stays.
    validate=true: requires a registered non-chargeable probe (not yet for DHL Phase 0).
    """
    validator = None
    if validate:
        # Honest: no probe wired yet — do not pretend success.
        raise HTTPException(
            status_code=422,
            detail=(
                "external validation probe not available for this capability; "
                "store candidate without validate, or wait for probe wiring"
            ),
        )
    try:
        public = _svc.rotate(
            carrier,
            capability,
            environment,
            body.fields,
            user=user,
            validate=validator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CarrierCredentialError as exc:
        raise _http_from_cred_error(exc)
    except Exception:
        log.exception("rotate_credential failed")
        raise HTTPException(status_code=500, detail="credential rotate failed")

    from app.services.carrier.credentials.models import (
        CapabilityState,
        CredentialIdentity,
        CredentialMeta,
    )

    meta = CredentialMeta(
        identity=CredentialIdentity(carrier, environment, capability),
        configured=public.get("configured", False),
        active=public.get("active", False),
        fingerprint=public.get("fingerprint"),
        masked_suffix=public.get("masked_identifier"),
        last_validated_at=public.get("last_validated_at"),
        last_rotated_at=public.get("last_rotated_at"),
        updated_by=public.get("updated_by"),
        state=CapabilityState(public.get("state", "stored_unvalidated")),
    )
    audit_safe(
        "carrier_credentials",
        "rotate",
        public["credential_reference"],
        request=request,
        after=audit_credential_event(
            "rotate",
            meta,
            actor=str(user.get("email") or "admin"),
            validation_result=public.get("state"),
        ),
    )
    return JSONResponse(public)


@router.post(
    "/{carrier}/{environment}/{capability}/disable",
    dependencies=[Depends(require_carrier_credentials_admin)],
    summary="Disable active credential for identity",
)
def disable_credential(
    carrier: str,
    environment: str,
    capability: str,
    request: Request,
    user: dict = Depends(require_carrier_credentials_admin),
) -> JSONResponse:
    try:
        public = _svc.disable(carrier, capability, environment, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CarrierCredentialError as exc:
        raise _http_from_cred_error(exc)
    except Exception:
        log.exception("disable_credential failed")
        raise HTTPException(status_code=500, detail="credential disable failed")
    audit_safe(
        "carrier_credentials",
        "disable",
        public["credential_reference"],
        request=request,
        after={"action": "disable", "credential_reference": public["credential_reference"]},
    )
    return JSONResponse(public)

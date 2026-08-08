"""
MyDHL electronic proof of delivery (ePOD) persistence.

Authority: DHL Express MyDHL REST
  GET /mydhlapi[/test]/shipments/{awb}/proof-of-delivery

This is the CARRIER proof document. It is completely separate from the
customer delivery-confirmation receipt (application evidence). Never
substitute one for the other.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SAFE_REF = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_SAFE_BATCH = re.compile(r"^[A-Za-z0-9_-]{4,128}$")


@dataclass(frozen=True)
class EpodResult:
    status: str  # present | persisted | not_eligible | error | skipped
    path: Optional[Path] = None
    detail: Optional[str] = None


def _carrier_root() -> Path:
    from ...core.config import settings
    return Path(settings.carrier_storage_root or (settings.storage_root / "carrier"))


def epod_file_path(batch_id: str, tracking_ref: str) -> Optional[Path]:
    """Return the persisted ePOD path if it exists (path-confined), else None."""
    if not (isinstance(batch_id, str) and isinstance(tracking_ref, str)):
        return None
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return None
    doc_dir = (_carrier_root() / "epods").resolve()
    candidate = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
    if candidate.parent != doc_dir or not candidate.is_file():
        return None
    return candidate


def ensure_epod_persisted(batch_id: str, tracking_ref: str) -> Optional[Path]:
    """Fetch and persist MyDHL ePOD for (batch, AWB) if missing.

    Thin wrapper over :func:`ensure_epod_result` for call sites that only
    need the path (outbound hook).
    """
    result = ensure_epod_result(batch_id, tracking_ref)
    return result.path if result.status in ("present", "persisted") else None


def ensure_epod_result(batch_id: str, tracking_ref: str) -> EpodResult:
    """Fetch/persist ePOD with an explicit outcome for manifest messaging."""
    batch_id = (batch_id or "").strip()
    tracking_ref = (tracking_ref or "").strip()
    if not batch_id or not tracking_ref:
        return EpodResult("skipped", detail="missing_ids")
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return EpodResult("skipped", detail="invalid_ids")

    existing = epod_file_path(batch_id, tracking_ref)
    if existing is not None:
        return EpodResult("present", path=existing)

    try:
        from ...core.config import settings
        from .factory import CarrierConfig, get_adapter
    except Exception as exc:  # pragma: no cover
        return EpodResult("error", detail=str(exc))

    if (settings.carrier_api_status or "").strip().lower() != "live":
        return EpodResult(
            "skipped",
            detail=f"carrier_api_status={settings.carrier_api_status!r}",
        )

    try:
        cfg = CarrierConfig(
            status=settings.carrier_api_status,
            api_key=settings.dhl_express_api_key,
            api_secret=settings.dhl_express_api_secret,
            api_url=settings.dhl_express_api_url,
            use_sandbox=settings.dhl_express_use_sandbox,
            account_number=settings.dhl_express_account_number,
            live_allowlist=settings.carrier_live_allowlist or "*",
        )
        adapter = get_adapter(cfg)
    except Exception as exc:
        return EpodResult("error", detail=f"adapter:{exc}")

    outcome_fn = getattr(adapter, "fetch_electronic_pod_outcome", None)
    if callable(outcome_fn):
        try:
            outcome = outcome_fn(tracking_ref)
        except Exception as exc:
            return EpodResult("error", detail=str(exc))
    else:
        fetch = getattr(adapter, "fetch_electronic_pod", None)
        if not callable(fetch):
            return EpodResult("skipped", detail="no_fetch")
        try:
            pdf = fetch(tracking_ref)
        except Exception as exc:
            return EpodResult("error", detail=str(exc))
        outcome = (
            {"status": "ok", "pdf": pdf}
            if pdf and pdf[:4] == b"%PDF"
            else {"status": "not_eligible", "detail": "empty"}
        )

    status = (outcome or {}).get("status")
    if status == "not_eligible":
        return EpodResult("not_eligible", detail=outcome.get("detail"))
    if status != "ok":
        return EpodResult("error", detail=(outcome or {}).get("detail") or status)

    pdf = outcome.get("pdf")
    if not pdf or bytes(pdf)[:4] != b"%PDF":
        return EpodResult("not_eligible", detail="non_pdf")

    try:
        doc_dir = (_carrier_root() / "epods").resolve()
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
        if path.parent != doc_dir:
            return EpodResult("error", detail="path_escape")
        path.write_bytes(bytes(pdf))
        log.info("ePOD saved: %s", path)
        return EpodResult("persisted", path=path)
    except Exception as exc:
        return EpodResult("error", detail=f"persist:{exc}")

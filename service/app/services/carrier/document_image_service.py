"""
MyDHL Document Image Request — post-booking recovery for waybill (and kin).

Official REST (this stack):
  GET /mydhlapi[/test]/shipments/{awb}/get-image
      ?shipperAccountNumber=&typeCode=waybill&pickupYearAndMonth=YYYY-MM

Distinct from create-shipment documents[] (saved at booking) and from ePOD
(proof-of-delivery). Account entitlement varies — 403 means the account is
not authorized for Get Image (honest Not provided / not retrievable).
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
class DocumentImageResult:
    """Outcome of a best-effort Get Image attempt."""
    status: str  # present | persisted | not_found | not_authorized | skipped | error
    path: Optional[Path] = None
    detail: Optional[str] = None


def _carrier_root() -> Path:
    from ...core.config import settings
    return Path(settings.carrier_storage_root or (settings.storage_root / "carrier"))


def waybill_file_path(batch_id: str, tracking_ref: str) -> Optional[Path]:
    if not (isinstance(batch_id, str) and isinstance(tracking_ref, str)):
        return None
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return None
    doc_dir = (_carrier_root() / "waybill_docs").resolve()
    candidate = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
    if candidate.parent != doc_dir or not candidate.is_file():
        return None
    return candidate


def ensure_waybill_persisted(
    batch_id: str,
    tracking_ref: str,
    *,
    pickup_year_month: Optional[str] = None,
) -> DocumentImageResult:
    """Fetch MyDHL waybill image and persist under waybill_docs/ when missing.

    Idempotent when the file already exists. Best-effort — never raises.
    """
    batch_id = (batch_id or "").strip()
    tracking_ref = (tracking_ref or "").strip()
    if not batch_id or not tracking_ref:
        return DocumentImageResult("skipped", detail="missing_ids")
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return DocumentImageResult("skipped", detail="invalid_ids")

    existing = waybill_file_path(batch_id, tracking_ref)
    if existing is not None:
        return DocumentImageResult("present", path=existing)

    try:
        from ...core.config import settings
        from .factory import CarrierConfig, get_adapter
    except Exception as exc:  # pragma: no cover
        return DocumentImageResult("error", detail=str(exc))

    if (settings.carrier_api_status or "").strip().lower() != "live":
        return DocumentImageResult(
            "skipped",
            detail=f"carrier_api_status={settings.carrier_api_status!r}",
        )

    try:
        from .credentials.consumer_bridge import express_carrier_config_kwargs

        kwargs = express_carrier_config_kwargs("documents")
        if not (kwargs.get("live_allowlist") or "").strip():
            kwargs["live_allowlist"] = "*"
        cfg = CarrierConfig(**kwargs)
        adapter = get_adapter(cfg)
    except Exception as exc:
        return DocumentImageResult("error", detail=f"adapter:{exc}")

    fetch = getattr(adapter, "fetch_document_image", None)
    if not callable(fetch):
        return DocumentImageResult("skipped", detail="adapter_has_no_get_image")

    # pickupYearAndMonth: prefer caller; else YYYY-MM from tracking_ref booking row
    # is left to the caller. Default: current UTC month is wrong for historical —
    # require explicit or derive below.
    ym = (pickup_year_month or "").strip()
    if not ym:
        ym = _pickup_year_month_for(batch_id, tracking_ref) or ""
    if not ym:
        return DocumentImageResult("skipped", detail="missing_pickup_year_month")

    try:
        outcome = fetch(tracking_ref, type_code="waybill", pickup_year_month=ym)
    except Exception as exc:
        log.warning("get-image raised for awb=%s: %s", tracking_ref, exc)
        return DocumentImageResult("error", detail=str(exc))

    if not isinstance(outcome, dict):
        return DocumentImageResult("error", detail="bad_adapter_outcome")
    code = outcome.get("status")
    if code == "not_authorized":
        return DocumentImageResult("not_authorized", detail=outcome.get("detail"))
    if code == "not_found":
        return DocumentImageResult("not_found", detail=outcome.get("detail"))
    if code != "ok":
        return DocumentImageResult("error", detail=outcome.get("detail") or code)

    pdf = outcome.get("pdf")
    if not pdf or not isinstance(pdf, (bytes, bytearray)) or bytes(pdf)[:4] != b"%PDF":
        return DocumentImageResult("not_found", detail="empty_or_non_pdf")

    try:
        doc_dir = (_carrier_root() / "waybill_docs").resolve()
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
        if path.parent != doc_dir:
            return DocumentImageResult("error", detail="path_escape")
        path.write_bytes(bytes(pdf))
        log.info("waybill saved via get-image: %s", path)
        return DocumentImageResult("persisted", path=path)
    except Exception as exc:
        return DocumentImageResult("error", detail=f"persist:{exc}")


def _pickup_year_month_for(batch_id: str, tracking_ref: str) -> Optional[str]:
    """YYYY-MM from carrier_shipments.created_at when available."""
    try:
        from ...core.config import settings
        from .persistence import shipment_db
        root = settings.carrier_storage_root or (settings.storage_root / "carrier")
        db = Path(root) / "carrier_shipments.db"
        if not db.exists():
            return None
        row = shipment_db.get_shipment_by_tracking_ref(db, tracking_ref)
        if not row:
            return None
        created = (row.get("created_at") or "").strip()
        if len(created) >= 7 and created[4] == "-":
            return created[:7]
    except Exception as exc:
        log.debug("pickup_year_month lookup failed: %s", exc)
    return None

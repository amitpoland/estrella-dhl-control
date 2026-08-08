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
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SAFE_REF = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_SAFE_BATCH = re.compile(r"^[A-Za-z0-9_-]{4,128}$")


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

    Idempotent: returns the existing file without calling DHL when present.
    Best-effort: returns None (never raises) when carrier is not live, the
    account has no ePOD for this AWB, or the fetch fails.
    """
    batch_id = (batch_id or "").strip()
    tracking_ref = (tracking_ref or "").strip()
    if not batch_id or not tracking_ref:
        return None
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return None

    existing = epod_file_path(batch_id, tracking_ref)
    if existing is not None:
        return existing

    try:
        from ...core.config import settings
        from .factory import CarrierConfig, get_adapter
    except Exception as exc:  # pragma: no cover
        log.debug("ePOD imports failed: %s", exc)
        return None

    if (settings.carrier_api_status or "").strip().lower() != "live":
        log.info(
            "ePOD skip — carrier_api_status=%r (need live)",
            settings.carrier_api_status,
        )
        return None

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
        log.warning("ePOD adapter unavailable: %s", exc)
        return None

    fetch = getattr(adapter, "fetch_electronic_pod", None)
    if not callable(fetch):
        return None

    try:
        pdf = fetch(tracking_ref)
    except Exception as exc:
        log.warning("ePOD fetch raised for awb=%s: %s", tracking_ref, exc)
        return None
    if not pdf or pdf[:4] != b"%PDF":
        return None

    try:
        doc_dir = (_carrier_root() / "epods").resolve()
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
        if path.parent != doc_dir:
            return None
        path.write_bytes(pdf)
        log.info("ePOD saved: %s", path)
        return path
    except Exception as exc:
        log.warning("ePOD persist failed for awb=%s: %s", tracking_ref, exc)
        return None

"""
Outbound-delivery hook.

``tracking_service`` calls :func:`on_outbound_tracking_update` whenever it
resolves a tracking status for an AWB. When (and only when) the status is
``delivered`` for an OUTBOUND shipment, this hook resolves the AWB back to its
owning proforma draft and asks the delivery-confirmation service to (maybe)
queue the one customer "confirm receipt" email.

Design constraints:
  * BEST-EFFORT — every failure is swallowed and logged. Tracking must never
    break because a downstream confirmation email could not be queued.
  * NON-RECURSIVE — the hook passes ``delivered=True`` + ``carrier_delivered_at``
    to ``maybe_notify_outbound_delivered`` so that service never re-queries
    tracking (which would recurse, since this hook fires from inside
    ``get_tracking_status``).
  * The outbound AWB (tracking_ref) is the delivery authority here — NOT the
    inbound-customs ``audit.json``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _carrier_db_path() -> Optional[Path]:
    try:
        from ..core.config import settings
        root = settings.carrier_storage_root or (settings.storage_root / "carrier")
        return Path(root) / "carrier_shipments.db"
    except Exception:
        return None


def _delivered_at_from_events(events: Optional[List[dict]]) -> Optional[str]:
    """Best-effort delivered timestamp from the tracking event stream."""
    if not events:
        return None
    for ev in events:
        blob = " ".join(
            str(ev.get(k, "")) for k in ("description", "status", "statusCode")
        ).lower()
        if "delivered" in blob:
            ts = ev.get("timestamp") or ev.get("time") or ev.get("date")
            if ts:
                return str(ts)
    return None


def on_outbound_tracking_update(
    awb: str,
    status: str,
    events: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Fire the customer delivery-confirmation flow for a delivered outbound AWB.

    Returns the notify result dict (or a ``{"notified": False, "reason": ...}``
    when nothing was done). Never raises.
    """
    try:
        awb = (awb or "").strip()
        if not awb:
            return {"notified": False, "reason": "no_awb"}
        if (status or "").strip().lower() != "delivered":
            return {"notified": False, "reason": "not_delivered_status"}

        # Feature flag short-circuit — avoid any DB work when disabled.
        from ..core.config import settings
        if not settings.customer_delivery_confirmation_enabled:
            return {"notified": False, "reason": "feature_disabled"}

        carrier_db = _carrier_db_path()
        row: Optional[dict] = None
        if carrier_db and Path(carrier_db).exists():
            try:
                from .carrier.persistence import shipment_db
                row = shipment_db.get_shipment_by_tracking_ref(carrier_db, awb)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("outbound hook shipment lookup failed: %s", exc)
                row = None
        if row is None:
            # Outbound AWB is not one of ours (e.g. an inbound-only tracking
            # number). Do nothing — never notify for an unknown shipment.
            return {"notified": False, "reason": "awb_not_recognised", "awb": awb}

        batch_id = row.get("batch_id")
        client_ref = (row.get("client_ref") or "").strip() or None
        booking_created_at = row.get("created_at")

        # Best-effort MyDHL ePOD persist — never blocks customer notify.
        try:
            from .carrier.epod_service import ensure_epod_persisted
            if batch_id:
                ensure_epod_persisted(str(batch_id), awb)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("outbound hook ePOD persist failed: %s", exc)

        # Resolve the draft for this (batch, client) — needed for the customer
        # email + draft-scoped notification record.
        draft_id = None
        client_name = client_ref
        try:
            from . import proforma_invoice_link_db as pildb
            pf_db = Path(settings.storage_root) / "proforma_links.db"
            if client_ref and pf_db.exists():
                draft = pildb.get_draft(pf_db, batch_id, client_ref)
                if draft is not None:
                    draft_id = draft.id
                    client_name = draft.client_name
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("outbound hook draft lookup failed: %s", exc)

        from . import delivery_confirmation_service as dcs
        return dcs.maybe_notify_outbound_delivered(
            awb,
            draft_id=draft_id,
            batch_id=batch_id,
            client_name=client_name,
            delivered=True,
            carrier_delivered_at=_delivered_at_from_events(events),
            booking_created_at=booking_created_at,
        )
    except Exception as exc:  # pragma: no cover - hook must never raise
        log.warning("on_outbound_tracking_update failed for awb=%s: %s", awb, exc)
        return {"notified": False, "reason": "hook_error"}

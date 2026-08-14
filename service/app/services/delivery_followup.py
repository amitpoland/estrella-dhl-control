"""
delivery_followup.py — ONE read-side composition of tracking + confirmation.

Does NOT invent delivery. Does NOT replace delivery_confirmation_db.
tracking_service owns physical delivered state; delivery_confirmation owns
Estrella→customer confirmation lifecycle.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def compose_delivery_followup(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Dict[str, Any]:
    """Return carrier + confirmation projection for Send UI (backend-only)."""
    from . import delivery_confirmation_db as dcdb
    from . import delivery_confirmation_service as dcs
    from . import proforma_invoice_link_db as pildb
    from .carrier.persistence import shipment_db
    from .shipment_document_manifest import _batch_client_count

    storage_root = Path(storage_root)
    proforma_db = Path(proforma_db)
    carrier_db = Path(carrier_db)
    db = storage_root / "delivery_confirmations.db"

    summary = dcdb.get_delivery_summary_for_draft(db, int(draft_id))
    draft = pildb.get_draft_by_id(proforma_db, int(draft_id))

    awb = ((summary or {}).get("awb") or "").strip()
    shipment_row = None
    if draft is not None:
        batch_id = (draft.batch_id or "").strip()
        client_name = (draft.client_name or "").strip() or None
        single_client = _batch_client_count(proforma_db, batch_id) <= 1
        try:
            shipment_row = shipment_db.get_shipment_for_draft(
                carrier_db,
                batch_id,
                client_name,
                allow_single_client_fallback=single_client,
            )
        except Exception as exc:
            log.debug("followup shipment resolve failed: %s", exc)
        if not awb and shipment_row:
            awb = (shipment_row.get("tracking_ref") or "").strip()

    proof: Dict[str, Any] = {"ok": False}
    if awb:
        try:
            proof = dcs._prove_outbound_delivered(awb)
        except Exception as exc:
            log.debug("followup delivered proof failed: %s", exc)
            proof = {"ok": False, "reason": "proof_error"}

    delivered = bool(proof.get("ok"))
    delivered_at = proof.get("carrier_delivered_at")
    location = None
    # Prefer tracking cache location when delivered.
    if delivered and awb and draft is not None:
        try:
            from . import tracking_service as ts
            batch_id = (draft.batch_id or "").strip()
            cache_dir = storage_root / "outputs" / batch_id
            if cache_dir.is_dir():
                hit = ts.select_cached_tracking_record(ts._load_cache(cache_dir), awb) or {}
                delivered_at = delivered_at or hit.get("last_update")
                location = (hit.get("last_location") or "").strip() or None
                if (hit.get("status") or "").strip().lower() == "delivered":
                    delivered = True
        except Exception as exc:
            log.debug("followup tracking enrich failed: %s", exc)

    provider = None
    if shipment_row:
        provider = (shipment_row.get("provider") or "").strip() or "DHL"

    carrier_status = "unknown"
    if delivered:
        carrier_status = "delivered"
    elif awb:
        carrier_status = "in_transit"

    op = (summary or {}).get("operator_status") if summary else None
    notif = (summary or {}).get("notification_status") if summary else None

    conf_state = "not_sent"
    can_send = False
    can_remind = False
    conf_reason = None

    if op in ("confirmed_good", "issue_reported"):
        conf_state = op
        conf_reason = f"Customer already responded ({op})."
    elif op == "awaiting_customer" or (
        summary is not None and op in (None, "token_issued") and notif in ("queued", "sent")
    ):
        conf_state = "awaiting_customer"
        can_remind = True
        conf_reason = "Already awaiting customer — use reminder."
    elif notif == "failed":
        conf_state = "failed"
        can_send = True
    elif delivered and summary is None:
        conf_state = "not_sent"
        can_send = True
    elif delivered:
        conf_state = "not_sent"
        can_send = True
    elif not awb:
        conf_state = "unavailable"
        conf_reason = "No outbound AWB linked to this draft."
    else:
        conf_state = "unavailable"
        conf_reason = "Delivery Confirmation becomes available after the shipment is delivered."

    return {
        "carrier": {
            "status": carrier_status,
            "delivered": delivered,
            "delivered_at": delivered_at,
            "location": location,
            "awb": awb or None,
            "provider": provider,
            "service_product": (shipment_row or {}).get("service_product") if shipment_row else None,
        },
        "confirmation": {
            "state": conf_state,
            "can_send": can_send,
            "can_remind": can_remind,
            "operator_status": op,
            "notification_status": notif,
            "reason": conf_reason,
            "customer_name": (summary or {}).get("customer_name") if summary else None,
        },
    }

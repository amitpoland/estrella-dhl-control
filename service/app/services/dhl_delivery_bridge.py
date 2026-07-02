"""
dhl_delivery_bridge.py — Phase 7: DHL delivered→received bridge (§1B / WF4).

When DHL reports a shipment as "delivered", this module raises a
"confirm received" inbox proposal. The proposal asks the operator to
confirm: person / date / location of physical receipt.

On operator confirmation, the shared stock-promotion authority
(stock_promotion.run_stock_promotion) moves scan_codes from
PURCHASE_TRANSIT → WAREHOUSE_STOCK and writes the Stock Promotion Note
(BE-2b — every stock movement produces a document).

Architecture:
- This module is READ-ONLY w.r.t. DHL — it reads tracking status from audit.
- It EMITS a proposal (write to audit["action_proposals"]).
- The operator APPROVES the proposal via the Inbox.
- The POST /confirm-received endpoint performs the actual state transition.

"Received" is SOFT — it is a signal that goods arrived, but it is not
a posting precondition (no gate blocks proforma creation on un-received goods).

Boundaries (HARD):
- Never calls DHL API
- Never auto-transitions inventory state
- Never writes wFirma
- The state transition (PURCHASE_TRANSIT → WAREHOUSE_STOCK) happens ONLY
  on explicit operator confirmation, not automatically.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Proposal type for the "confirm received" inbox item
PROP_DHL_DELIVERED_NOT_RECEIVED = "dhl_delivered_not_received"
DELIVERY_BRIDGE_CHANNEL         = "dhl_delivery_bridge"

# DHL tracking statuses that indicate physical delivery
_DELIVERED_STATUSES = frozenset({
    "delivered",
    "DELIVERED",
    "Delivered",
    "transit_delivered",
})


# ── Detection ─────────────────────────────────────────────────────────────────

def is_dhl_delivered(audit: Dict[str, Any]) -> bool:
    """Return True when DHL tracking indicates the shipment is physically delivered."""
    # Check audit.tracking events
    tracking_events = audit.get("tracking") or []
    if isinstance(tracking_events, list):
        for ev in tracking_events:
            status = (ev.get("status") or ev.get("description") or "").lower()
            if "delivered" in status and "attempted" not in status:
                return True

    # Check clearance_status
    cs = (audit.get("clearance_status") or "").lower()
    if "delivered" in cs:
        return True

    # Check carrier_status / dhl_status
    for key in ("carrier_status", "dhl_status", "shipment_status"):
        v = (audit.get(key) or "").lower()
        if v in {s.lower() for s in _DELIVERED_STATUSES}:
            return True

    return False


def is_received_confirmed(audit: Dict[str, Any]) -> bool:
    """Return True when the operator has already confirmed physical receipt."""
    # Check for an existing resolved 'confirm received' proposal
    for p in (audit.get("action_proposals") or []):
        if (p.get("type") == PROP_DHL_DELIVERED_NOT_RECEIVED
                and p.get("channel") == DELIVERY_BRIDGE_CHANNEL
                and p.get("status") in ("approved", "resolved")):
            return True
    # Check explicit received flag
    return bool(audit.get("goods_received_confirmed"))


# ── Proposal creation ─────────────────────────────────────────────────────────

def create_delivery_confirmation_proposal(
    audit:    Dict[str, Any],
    batch_id: str,
) -> Optional[Dict[str, Any]]:
    """Create a 'confirm received' inbox proposal when DHL shows delivered.

    Returns the new proposal dict, or None if:
      - DHL does not yet show delivered
      - Goods already confirmed received
      - An active proposal already exists (dedup)

    The proposal is appended to audit["action_proposals"] and returned.
    Caller owns the audit lifecycle (must write audit.json after calling this).
    """
    if not is_dhl_delivered(audit):
        return None
    if is_received_confirmed(audit):
        return None

    # Dedup: one active proposal per type per channel
    for p in (audit.get("action_proposals") or []):
        if (p.get("type") == PROP_DHL_DELIVERED_NOT_RECEIVED
                and p.get("channel") == DELIVERY_BRIDGE_CHANNEL
                and p.get("status") == "pending_review"):
            return p  # already pending

    proposal: Dict[str, Any] = {
        "proposal_id":    str(uuid.uuid4()),
        "type":           PROP_DHL_DELIVERED_NOT_RECEIVED,
        "channel":        DELIVERY_BRIDGE_CHANNEL,
        "batch_id":       batch_id,
        "status":         "pending_review",
        "reason":         "DHL tracking shows shipment delivered — confirm physical receipt",
        "confidence":     "high",
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "approved_by":    None,
        "approved_at":    None,
        "rejected_by":    None,
        "rejected_at":    None,
        "reject_reason":  None,
        # Operator fills in these fields on confirm:
        "resolution_data": {
            "received_by":    "",    # person who received goods
            "received_at":    "",    # ISO date of physical receipt
            "location":       "",    # warehouse location / dock
        },
        "draft":    {},
        "email_id": None,
        "queued_at": None,
        # Instruction for the operator UI
        "action_required": (
            "Confirm that the goods arrived physically at the warehouse. "
            "Supply: received_by (name), received_at (date), location. "
            "This triggers PURCHASE_TRANSIT → WAREHOUSE_STOCK for all scan_codes."
        ),
    }
    audit.setdefault("action_proposals", []).append(proposal)
    log.info("[%s] DHL delivery confirmation proposal created: %s",
             batch_id, proposal["proposal_id"])
    return proposal


# ── State transition (called ONLY on operator confirmation) ───────────────────

def execute_goods_received(
    batch_id:      str,
    proposal:      Dict[str, Any],
    resolution:    Dict[str, Any],
    operator:      str,
    storage_root:  Path,
) -> Dict[str, Any]:
    """Execute the PURCHASE_TRANSIT → WAREHOUSE_STOCK transition.

    Called ONLY when the operator approves the delivery proposal via Inbox.
    Never called automatically.

    resolution must contain:
      - received_by: str
      - received_at: str (ISO date)
      - location: str

    Returns a result dict with:
      - transitioned: int (count of scan_codes moved)
      - errors: List[str]
      - note_no: str — the Stock Promotion Note documenting this receipt
        ('' when nothing moved; BE-2b)
    """
    received_by  = (resolution.get("received_by") or "").strip()
    received_at  = (resolution.get("received_at") or "").strip()
    location     = (resolution.get("location") or "").strip()

    if not received_by or not received_at:
        raise ValueError(
            "received_by and received_at are required to confirm goods receipt"
        )

    result: Dict[str, Any] = {"transitioned": 0, "errors": [], "note_no": ""}

    try:
        from . import warehouse_db as wdb
        from .stock_promotion import run_stock_promotion

        warehouse_db_path = storage_root / "warehouse.db"
        if not warehouse_db_path.exists():
            result["errors"].append("warehouse.db not found — state transition skipped")
            return result

        wdb.init_warehouse_db(warehouse_db_path)

        note = (
            f"goods_received: by={received_by!r} at={received_at!r} "
            f"location={location!r} operator={operator!r}"
        )
        # BE-2b (PROJECT_STATE DECISIONS 2026-07-03): the receipt path was
        # the LAST PURCHASE_TRANSIT → WAREHOUSE_STOCK writer outside the
        # shared authority — its direct per-row transition loop is replaced
        # by run_stock_promotion(), so operator-confirmed receipts gain the
        # same idempotent skip, audit mirrors, and Stock Promotion Note as
        # the PZ-created / generation paths ("every stock movement must
        # produce a document"). Dependency: the shared function derives the
        # piece set from packing lines — packing_db must be initialised
        # (service startup does this; tests init it in fixtures).
        promo = run_stock_promotion(
            batch_id,
            trigger  = "warehouse_receive",
            source   = "dhl_delivery_bridge",
            operator = operator,
            note     = note,
        )
        result["transitioned"] = int(promo.get("promoted", 0))
        # skipped surfaced so a caller can distinguish a REPLAY (already
        # promoted: transitioned=0, skipped>0) from an empty batch
        # (transitioned=0, skipped=0) — verify-pass hardening for the
        # future Inbox dispatcher.
        result["skipped"]      = int(promo.get("skipped", 0))
        result["note_no"]      = str(promo.get("note_no", "") or "")
        if promo.get("errors"):
            result["errors"].append(
                f"{promo['errors']} line(s) failed to promote "
                "(see audit timeline inventory_transition_failed events)"
            )
        if promo.get("note_failed"):
            result["errors"].append(
                "stock promotion note write FAILED — pieces were promoted "
                "without a document; reconcile from inventory_state_events"
            )

    except Exception as exc:
        result["errors"].append(f"execute_goods_received failed: {exc}")

    return result

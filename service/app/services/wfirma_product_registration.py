"""
wfirma_product_registration.py — Phase 6: wFirma product registration via Inbox.

After parse + product master population, an inbox proposal is created asking
the operator to approve wFirma product registration for unsynced product codes.

On approval:
  - Flag WFIRMA_CREATE_PRODUCT_ALLOWED must be ON
  - Dev uses mock wFirma client (NEVER the live API during the build campaign)
  - Route calls existing POST /shipment/{batch_id}/wfirma/products/resolve

BOUNDARIES (HARD):
  - Never calls wFirma API directly from this module
  - Never auto-approves
  - Write only occurs when WFIRMA_CREATE_PRODUCT_ALLOWED=True AND operator approves
  - Flag stays OFF during the entire campaign build; this module only creates proposals

Proposal type: product_not_synced_to_wfirma (§7)
Channel: wfirma_product_registration
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PROP_PRODUCT_NOT_SYNCED  = "product_not_synced_to_wfirma"
REGISTRATION_CHANNEL     = "wfirma_product_registration"


def find_unsynced_product_codes(
    batch_id:     str,
    storage_root,
) -> List[str]:
    """Return product codes for this batch that have no wfirma_product_id.

    Read-only — queries wfirma.db and cross-references with invoice_lines.
    """
    unsynced: List[str] = []
    try:
        import sqlite3
        from pathlib import Path
        storage_root = Path(storage_root)

        docs_db = storage_root / "documents.db"
        wfirma_db = storage_root / "wfirma.db"
        if not docs_db.exists() or not wfirma_db.exists():
            return []

        # Collect product codes for this batch
        conn = sqlite3.connect(str(docs_db))
        conn.row_factory = sqlite3.Row
        pc_rows = conn.execute(
            "SELECT DISTINCT product_code FROM invoice_lines WHERE batch_id=?",
            (batch_id,)
        ).fetchall()
        conn.close()
        batch_codes = {(r["product_code"] or "").strip() for r in pc_rows
                       if (r["product_code"] or "").strip()}

        if not batch_codes:
            return []

        # Check which ones are synced
        wconn = sqlite3.connect(str(wfirma_db))
        wconn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in batch_codes)
        synced_rows = wconn.execute(
            f"SELECT product_code, sync_status FROM wfirma_products "
            f"WHERE product_code IN ({placeholders})",
            list(batch_codes),
        ).fetchall()
        wconn.close()
        synced = {r["product_code"] for r in synced_rows
                  if (r["sync_status"] or "") in ("matched", "created", "ready")}
        unsynced = sorted(batch_codes - synced)
    except Exception as exc:
        log.warning("[%s] find_unsynced_product_codes failed: %s", batch_id, exc)

    return unsynced


def create_registration_proposal(
    audit:           Dict[str, Any],
    batch_id:        str,
    unsynced_codes:  List[str],
) -> Optional[Dict[str, Any]]:
    """Create a 'register products to wFirma' inbox proposal.

    Returns None if:
      - No unsynced codes
      - Active proposal already exists (dedup)

    Caller owns the audit lifecycle (must write audit.json after calling this).
    Write flag status is NOT checked here — flag check happens at execution time
    in the /products/resolve endpoint.
    """
    if not unsynced_codes:
        return None

    # Dedup
    for p in (audit.get("action_proposals") or []):
        if (p.get("type") == PROP_PRODUCT_NOT_SYNCED
                and p.get("channel") == REGISTRATION_CHANNEL
                and p.get("status") == "pending_review"):
            return p

    proposal: Dict[str, Any] = {
        "proposal_id":      str(uuid.uuid4()),
        "type":             PROP_PRODUCT_NOT_SYNCED,
        "channel":          REGISTRATION_CHANNEL,
        "batch_id":         batch_id,
        "status":           "pending_review",
        "reason":           (
            f"{len(unsynced_codes)} product code(s) not yet registered in wFirma. "
            "Approve to trigger registration (requires WFIRMA_CREATE_PRODUCT_ALLOWED=true)."
        ),
        "confidence":       "high",
        "created_at":       datetime.now(timezone.utc).isoformat(),
        "approved_by":      None,
        "approved_at":      None,
        "rejected_by":      None,
        "rejected_at":      None,
        "reject_reason":    None,
        "draft":            {},
        "email_id":         None,
        "queued_at":        None,
        "context": {
            "unsynced_product_codes": unsynced_codes[:20],
            "unsynced_count":         len(unsynced_codes),
            "action":                 "POST /api/v1/shipment/{batch_id}/wfirma/products/resolve",
            "flag_required":          "WFIRMA_CREATE_PRODUCT_ALLOWED",
        },
    }
    audit.setdefault("action_proposals", []).append(proposal)
    log.info("[%s] wFirma product registration proposal created: %s codes",
             batch_id, len(unsynced_codes))
    return proposal


def dispatch_registration(
    batch_id:  str,
    proposal:  Dict[str, Any],
    operator:  str,
) -> Dict[str, Any]:
    """Execute product registration via the existing /products/resolve endpoint.

    Called ONLY when the operator approves the proposal via Inbox.
    Flag WFIRMA_CREATE_PRODUCT_ALLOWED must be True — the endpoint enforces it.

    Returns: {ok: bool, result: dict, error: str}
    """
    try:
        from ..core.config import settings
        if not settings.wfirma_create_product_allowed:
            return {
                "ok": False,
                "error": (
                    "WFIRMA_CREATE_PRODUCT_ALLOWED=false — flag must be enabled "
                    "by the operator before product registration can proceed. "
                    "This is a live wFirma write; enable the flag deliberately."
                ),
            }

        # Delegate to the existing products/resolve service logic
        # (the full HTTP call chain with flag enforcement lives there)
        from ..api.routes_wfirma import _resolve_products_for_batch  # type: ignore
        result = _resolve_products_for_batch(batch_id, operator=operator)
        return {"ok": True, "result": result}

    except ImportError:
        # _resolve_products_for_batch may not be importable in all test contexts
        return {
            "ok": False,
            "error": "routes_wfirma._resolve_products_for_batch not available in this context",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

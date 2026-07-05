"""
Pull-only wFirma sync triggers (Wave 4 Item 7 — PULL-ONLY SLICE).

READ-ONLY against live wFirma. Endpoints here trigger existing READ/PULL
processors and update LOCAL state only. There is NO push, NO create, NO edit,
NO ``goods/edit``, and NO ``wfirma_create_*`` flag anywhere in this file — every
PUSH sync (customer→wFirma, product→wFirma, invoice/proforma create, goods/edit)
remains CP4-gated and lives elsewhere. It CANNOT route through this router:
there is no ``{type}`` dispatcher — only fixed, explicitly-named pull paths.

Served here (net-new, no existing trigger):
  POST /api/v1/wfirma/sync/payments-pull   {contractor_id}
      → wfirma_payment_sync_processor.sync_payments_for_contractor
        (READ-ONLY wFirma GET payments/find → local payment_state.db snapshot).

Reused elsewhere (NOT duplicated here — Item 8 anti-duplication rule):
  customer ← wFirma pull : GET  /api/v1/customer-master/sync-from-wfirma/preview
                           POST /api/v1/customer-master/sync-from-wfirma/apply (admin,
                                                              writes LOCAL customer_master only)
  webhook status         : GET  /api/v1/webhooks/wfirma/status
  invoice read/status    : GET  /api/v1/accounting/documents/{invoice|credit_note}

Intentionally NOT served — stock-pull: ``wfirma_client.get_stock`` is read-only
(GET goods/find), but ``wfirma_stock_sync_processor`` is a no-op stub with no
persistence target (OI-10). There is no safe pull path to reuse, so stock-pull
stays Backend Pending rather than shipping a route that does nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key

# ONLY a read/pull processor is imported here. No push/create/edit service.
from ..services.wfirma_payment_sync_processor import sync_payments_for_contractor

router = APIRouter(prefix="/api/v1/wfirma/sync", tags=["wfirma-sync-pull"])
_auth = Depends(require_api_key)


class PaymentsPullRequest(BaseModel):
    contractor_id: str


@router.post("/payments-pull", dependencies=[_auth])
def payments_pull(body: PaymentsPullRequest) -> dict:
    """PULL payments for ONE contractor from wFirma into the local
    payment_state.db snapshot store.

    Direction: PULL. wFirma side is READ-ONLY (payments/find GET); the only
    write is a local, append-only snapshot insert. No wFirma mutation.

    Bounded to a single contractor_id (no unbounded fan-out).

    Outcomes: 200 pulled · 400 missing contractor_id · 502 wFirma read failed.
    """
    cid = (body.contractor_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="contractor_id is required")

    from ..services.wfirma_payment_db import init_payment_db

    db_path = settings.storage_root / "payment_state.db"
    init_payment_db(db_path)
    now = datetime.now(timezone.utc).isoformat()

    new_count, existing_count, err = sync_payments_for_contractor(
        contractor_id=cid,
        payment_db=db_path,
        now=now,
    )
    if err:
        raise HTTPException(status_code=502, detail=f"wFirma payments read failed: {err}")
    return {
        "ok": True,
        "type": "payments-pull",
        "direction": "PULL",
        "contractor_id": cid,
        "new": new_count,
        "existing": existing_count,
    }

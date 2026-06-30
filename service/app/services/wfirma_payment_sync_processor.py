"""
Phase 4A — contractor payment snapshot processor.

For each contractor_id provided:
  1. Call fetch_payments_for_contractor() — READ-ONLY wFirma GET.
  2. For each <payment> node returned, insert an idempotent snapshot into
     payment_state.db (INSERT OR IGNORE on payment_id UNIQUE).

Called exclusively from wfirma_webhook_scheduler._run_payment_sync_tick().
Never raises. Never writes to customer_master, proforma_drafts, or any
business table. No Track B stage modifications.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    v = (el.text or "").strip()
    return v if v else None


def sync_payments_for_contractor(
    *,
    contractor_id: str,
    payment_db: Path,
    now: str,
) -> Tuple[int, int, Optional[str]]:
    """
    Fetch all wFirma payments for one contractor and store immutable snapshots.

    Returns (new_count, existing_count, error_or_None).
    Never raises.
    """
    from .wfirma_client import fetch_payments_for_contractor
    from .wfirma_payment_db import insert_payment_snapshot

    try:
        # Empty date strings → no date filter → fetch all payments
        payment_nodes = fetch_payments_for_contractor(contractor_id, "", "")
    except Exception as exc:
        msg = str(exc)[:300]
        log.warning(
            "payment_sync: fetch failed contractor_id=%s: %s",
            contractor_id, msg,
        )
        return 0, 0, msg

    new_count = 0
    existing_count = 0

    for payment in payment_nodes:
        payment_id = _text(payment.find("id"))
        if not payment_id:
            log.debug(
                "payment_sync: skipping payment node with no id contractor_id=%s",
                contractor_id,
            )
            continue

        invoice_node = payment.find("invoice")
        invoice_id = _text(invoice_node.find("id")) if invoice_node is not None else None

        fields: dict = {
            "payment_id":     payment_id,
            "contractor_id":  contractor_id,
            "invoice_id":     invoice_id,
            "payment_date":   _text(payment.find("date")),
            "value":          _text(payment.find("value")),
            "value_pln":      _text(payment.find("value_pln")),
            "currency_label": _text(payment.find("currency_label")),
            "payment_method": _text(payment.find("payment_method")),
            "payment_type":   _text(payment.find("payment_type")),
            "type":           _text(payment.find("type")),
            "notes":          _text(payment.find("notes")),
        }

        try:
            inserted = insert_payment_snapshot(
                payment_db,
                payment_id=payment_id,
                contractor_id=contractor_id,
                invoice_id=invoice_id,
                payment_date=fields["payment_date"],
                value=fields["value"],
                value_pln=fields["value_pln"],
                currency_label=fields["currency_label"],
                payment_method=fields["payment_method"],
                payment_type=fields["payment_type"],
                type_=fields["type"],
                notes=fields["notes"],
                fetched_at=now,
                raw_json=json.dumps(fields, ensure_ascii=False),
            )
            if inserted:
                new_count += 1
            else:
                existing_count += 1
        except Exception as exc:
            log.warning(
                "payment_sync: insert error payment_id=%s contractor_id=%s: %s",
                payment_id, contractor_id, exc,
            )

    log.info(
        "payment_sync: contractor_id=%s total=%d new=%d existing=%d",
        contractor_id, new_count + existing_count, new_count, existing_count,
    )
    return new_count, existing_count, None

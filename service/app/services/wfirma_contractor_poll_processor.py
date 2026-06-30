"""
Phase 3B -- wFirma contractor master sync processor.

Paginates through the full wFirma contractor list using list_contractors_page()
and calls upsert_identity_only() for every contractor found.

Design rules:
- Fill-when-empty semantics (upsert_identity_only COALESCE logic):
    * Operators and Phase 3 (webhook-driven) always win if field already set.
    * Only empty local columns are populated from wFirma list data.
- Skip contractors with empty name or invalid/missing country (same guard
  as Phase 3's sync_customer_from_snapshot).
- sync_source="wfirma_poll" distinguishes poll inserts from webhook inserts.
- Never raises -- all exceptions caught; returns partial counts + error.
- No writes to wfirma_processing.db, wfirma_webhook_events.db,
  payment_state.db, or wfirma_customer_snapshots.

Called exclusively from wfirma_webhook_scheduler._run_contractor_poll_tick().
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

_MAX_PAGES = 200   # hard safety cap (200 pages x 50 = 10 000 contractors)


def scan_contractors_into_master(
    cm_db: Path,
    now: str,
) -> Tuple[int, int, int, Optional[str]]:
    """
    Full contractor scan: paginate wFirma -> upsert customer_master.

    Returns (total_seen, new_count, updated_count, error_or_None).
    Never raises.
    """
    from .wfirma_client import list_contractors_page
    from .customer_master_db import upsert_identity_only
    from .wfirma_contractor_poll_db import PAGE_SIZE

    total_seen   = 0
    new_count    = 0
    updated_count = 0

    for page_num in range(1, _MAX_PAGES + 1):
        try:
            contractors = list_contractors_page(page_num, PAGE_SIZE)
        except Exception as exc:
            msg = str(exc)[:300]
            log.warning(
                "contractor_poll: list_contractors_page page=%d failed: %s",
                page_num, msg,
            )
            return total_seen, new_count, updated_count, msg

        if not contractors:
            # Empty page = past the end
            break

        for c in contractors:
            total_seen += 1

            name    = (c.name or "").strip()
            country = (c.country or "").strip().upper()

            if not name or len(country) != 2:
                log.debug(
                    "contractor_poll: skip contractor id=%s name=%r country=%r",
                    c.wfirma_id, name, country,
                )
                continue

            payment_terms_days: Optional[int] = None
            if c.payment_term:
                try:
                    payment_terms_days = int(c.payment_term)
                except (TypeError, ValueError):
                    pass

            try:
                result = upsert_identity_only(
                    cm_db,
                    bill_to_contractor_id = c.wfirma_id,
                    bill_to_name          = name,
                    country               = country,
                    nip                   = c.nip or None,
                    bill_to_email         = c.email or None,
                    bill_to_phone         = c.phone or None,
                    bill_to_mobile        = c.mobile or None,
                    bank_account          = c.account_payments or None,
                    payment_terms_days    = payment_terms_days,
                    bill_to_street        = c.street or None,
                    bill_to_city          = c.city or None,
                    bill_to_postal_code   = c.zip or None,
                    sync_source           = "wfirma_poll",
                )
                if result.get("action") == "inserted":
                    new_count += 1
                else:
                    updated_count += 1
            except Exception as exc:
                log.warning(
                    "contractor_poll: upsert error contractor_id=%s name=%r: %s",
                    c.wfirma_id, name, exc,
                )

        log.debug(
            "contractor_poll: page=%d contractors=%d cumulative_seen=%d",
            page_num, len(contractors), total_seen,
        )

    log.info(
        "contractor_poll: scan complete total=%d new=%d updated=%d",
        total_seen, new_count, updated_count,
    )
    return total_seen, new_count, updated_count, None

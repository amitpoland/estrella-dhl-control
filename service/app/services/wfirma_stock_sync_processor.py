"""
C-8a — wFirma goods stock-change webhook processor (Wave 4).

Consumes the "Produkty » Zmiana ilości na magazynie" (Products » Stock quantity
change) webhook and refreshes the affected good's stock from the authoritative
source via ``wfirma_client.get_stock`` (C-9a).

STATUS: deterministic plumbing only. Three steps are intentionally NOT
implemented because their inputs are not yet known — each is marked
``BLOCKED BY OI-10`` below:
  1. payload parsing     — the wire payload shape is undocumented in the
                           wfirma-api-integration skill (help center gives only
                           the UI label, not the JSON field carrying the good id).
  2. event field mapping — the good-id field name is undocumented.
  3. stock update logic  — there is no persistence target for refreshed stock
                           (Product Master is identity-only, Constitution §6;
                           C-9a is uncached), so where the refreshed count lands
                           is an operator decision.

Until a live payload sample from OI-10 (wFirma-UI registration) resolves the
event-type string + field names, this processor recognizes no stock-change
event and performs no reads or writes — it is a safe no-op wired into the
existing scheduler so that only the three blocked sections need filling later.

Called exclusively from ``wfirma_webhook_scheduler._run_stock_sync_tick()``.
No wFirma writes. No business-table writes. No schema changes.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# The exact wire ``event_type`` string wFirma sends for a stock-quantity-change
# webhook. UNDOCUMENTED in the skill (only the UI label "Produkty » Zmiana
# ilości na magazynie" is known). Left None so the matcher deterministically
# matches nothing — no guessing (no assumptions). Set this once OI-10 supplies
# a live sample.
STOCK_CHANGE_EVENT_TYPE: Optional[str] = None  # BLOCKED BY OI-10


def is_stock_change_event(event_type: Optional[str]) -> bool:
    """
    Deterministic predicate — True iff ``event_type`` is a goods stock-change.

    While ``STOCK_CHANGE_EVENT_TYPE`` is None (BLOCKED BY OI-10) this returns
    False for every event, keeping the processor inert. It does NOT guess the
    string from partial labels.
    """
    if STOCK_CHANGE_EVENT_TYPE is None:
        return False
    return event_type == STOCK_CHANGE_EVENT_TYPE


def sync_stock_from_event(
    *,
    event_id: str,
    event_type: Optional[str],
    payload_json: str,
    now: str,
) -> str:
    """
    Route one stored webhook event as a potential stock-change refresh.

    Deterministic plumbing (implemented): event-type routing, structured
    logging, and the result contract. Non-stock events are skipped safely.

    Returns one of:
      - "skipped_not_stock_change" — event is not a stock-change event
      - "blocked_oi10"             — recognized as stock-change but deferred
                                     (only reachable once OI-10 sets the
                                     event-type string; still a no-op until the
                                     three blocked steps below are implemented)

    Idempotency: storage-level de-duplication is already guaranteed upstream by
    ``wfirma_webhook_events.event_id`` PRIMARY KEY + INSERT OR IGNORE
    (wfirma_webhook_db). Processing-level de-duplication (a processed marker) is
    BLOCKED BY OI-10 because it belongs with the persistence target.
    """
    if not is_stock_change_event(event_type):
        return "skipped_not_stock_change"

    # --- BLOCKED BY OI-10: payload parsing ----------------------------------
    #   good_id = _extract_good_id(payload_json)
    #   (the field carrying the wFirma good id is undocumented in the skill)
    #
    # --- BLOCKED BY OI-10: event field mapping ------------------------------
    #   target = _resolve_stock_target(good_id)
    #   (maps the wFirma good id to the persistence target)
    #
    # --- BLOCKED BY OI-10: stock update logic -------------------------------
    #   from .wfirma_client import get_stock
    #   stock = get_stock(good_id)          # C-9a — authoritative re-read
    #   _persist_stock(target, stock)       # target undecided (Constitution §6)
    # ------------------------------------------------------------------------
    log.info(
        "wfirma_stock_sync: stock-change event_id=%s recognized but DEFERRED "
        "(BLOCKED BY OI-10: payload contract + persistence target)",
        event_id,
    )
    return "blocked_oi10"

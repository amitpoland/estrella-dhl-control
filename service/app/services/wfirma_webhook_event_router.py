"""
WH-001 / WH-005 — wFirma webhook event domain routing (foundation).

Classifies stored ``event_type`` strings into processing domains so the main
scheduler tick (``_run_processing_tick`` Step 2) only hands **invoice** events to
``InvoiceSnapshotProcessor``. Stock and contractor events are terminal-routed
without an invoice fetch; unknown types are quarantined.

Routing table (prefix match, case-sensitive — wFirma wire strings)
------------------------------------------------------------------
| Domain     | event_type match                         | Main tick action              |
|------------|------------------------------------------|-------------------------------|
| INVOICE    | ``Faktury.*``, ``invoice.*``             | InvoiceSnapshotProcessor      |
| STOCK      | ``Towary.*``, ``Produkty.*``, stock predicate | ROUTED_STOCK (stock tick)    |
| CONTRACTOR | ``Kontrahenci.*``                        | ROUTED_CONTRACTOR (3B poll)   |
| UNKNOWN    | everything else (incl. NULL/empty)       | QUARANTINED — no fetch        |

Stock-change exact-type matching delegates to ``wfirma_stock_sync_processor``
(``is_stock_change_event``) so OI-10 can arm the wire string without changing
this table. ``Towary.*`` / ``Produkty.*`` cover goods prefixes before OI-10;
inventory mutation stays blocked until a live payload is proven.

No wFirma API calls. No webhook registration. No secret handling.
"""
from __future__ import annotations

from typing import Optional

DOMAIN_INVOICE = "INVOICE"
DOMAIN_STOCK = "STOCK"
DOMAIN_CONTRACTOR = "CONTRACTOR"
DOMAIN_UNKNOWN = "UNKNOWN"

_TERMINAL_SKIP_STATES = {
    DOMAIN_STOCK: "ROUTED_STOCK",
    DOMAIN_CONTRACTOR: "ROUTED_CONTRACTOR",
    DOMAIN_UNKNOWN: "QUARANTINED",
}


def _prefix_domain(event_type: str) -> Optional[str]:
    if event_type.startswith("Faktury.") or event_type.startswith("invoice."):
        return DOMAIN_INVOICE
    if event_type.startswith("Towary.") or event_type.startswith("Produkty."):
        return DOMAIN_STOCK
    if event_type.startswith("Kontrahenci."):
        return DOMAIN_CONTRACTOR
    return None


def classify_event_domain(event_type: Optional[str]) -> str:
    """
    Return the processing domain for one stored webhook ``event_type``.

    Never raises. NULL/blank → UNKNOWN.
    """
    if not event_type or not str(event_type).strip():
        return DOMAIN_UNKNOWN

    et = str(event_type).strip()
    by_prefix = _prefix_domain(et)
    if by_prefix is not None:
        return by_prefix

    from .wfirma_stock_sync_processor import is_stock_change_event

    if is_stock_change_event(et):
        return DOMAIN_STOCK

    return DOMAIN_UNKNOWN


def terminal_state_for_domain(domain: str) -> Optional[str]:
    """Processing-state name for non-invoice domains, or None for INVOICE."""
    return _TERMINAL_SKIP_STATES.get(domain)


def skip_reason_for_domain(domain: str, event_type: Optional[str]) -> str:
    """Human-readable ``last_error`` marker for terminal skip / quarantine."""
    et = event_type or "(null)"
    if domain == DOMAIN_STOCK:
        return f"routed_stock:event_type={et}"
    if domain == DOMAIN_CONTRACTOR:
        return f"routed_contractor:event_type={et}"
    return f"quarantined_unknown_event_type:{et}"

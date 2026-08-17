"""
WH-001 / WH-005 — wFirma webhook event domain routing (foundation).

Classifies stored ``event_type`` strings into processing domains so the main
scheduler tick (``_run_processing_tick`` Step 2) only hands **invoice add/edit**
events to ``InvoiceSnapshotProcessor``. Stock, contractor, payment, and invoice-
delete events are terminal-routed without an invoice fetch; unknown types are
quarantined.

Routing table (prefix match, case-sensitive — wFirma wire strings)
------------------------------------------------------------------
| Domain         | event_type match                              | Main tick action           |
|----------------|-----------------------------------------------|----------------------------|
| INVOICE        | ``Faktury.*``, ``invoice.*`` (non-delete)     | InvoiceSnapshotProcessor   |
| INVOICE_DELETE | Faktury/invoice + Usunięcie/delete           | ROUTED_INVOICE_DELETE      |
| PAYMENT        | ``Płatności.*``, ``payment.*``                | ROUTED_PAYMENT             |
| STOCK          | ``Towary.*``, ``Produkty.*``, stock predicate | ROUTED_STOCK (stock tick)  |
| CONTRACTOR     | ``Kontrahenci.*``                             | ROUTED_CONTRACTOR (3B poll)|
| UNKNOWN        | everything else (incl. NULL/empty)            | QUARANTINED — no fetch     |

WH-002 (delete tombstone) and WH-003 (payment consumer) remain PENDING for
genuine payload proof — routing only prevents unsafe fetch / wrong-family
processing. Payment poll sync remains financial correctness authority.
WH-004 inventory mutation stays blocked (OI-10).

No wFirma API calls. No webhook registration. No secret handling.
"""
from __future__ import annotations

from typing import Optional

DOMAIN_INVOICE = "INVOICE"
DOMAIN_INVOICE_DELETE = "INVOICE_DELETE"  # WH-002 — tombstone pending genuine payload
DOMAIN_STOCK = "STOCK"
DOMAIN_CONTRACTOR = "CONTRACTOR"
DOMAIN_PAYMENT = "PAYMENT"  # WH-003 — event latency; poll remains correctness authority
DOMAIN_UNKNOWN = "UNKNOWN"

_TERMINAL_SKIP_STATES = {
    DOMAIN_STOCK: "ROUTED_STOCK",
    DOMAIN_CONTRACTOR: "ROUTED_CONTRACTOR",
    DOMAIN_PAYMENT: "ROUTED_PAYMENT",
    DOMAIN_INVOICE_DELETE: "ROUTED_INVOICE_DELETE",
    DOMAIN_UNKNOWN: "QUARANTINED",
}


def _is_invoice_delete_event(event_type: str) -> bool:
    """True for Faktury delete-class wire strings (WH-002).

    Does NOT fetch or tombstone finance rows — only keeps the invoice snapshot
    processor from attempting a live fetch that cannot succeed after delete.
    Full tombstone consumer stays PENDING until a genuine payload is proven.
    """
    et = event_type.lower()
    if "usuni" in et:  # Usunięcie / usunięte (Polish delete wording)
        return True
    if ".delete" in et or et.endswith(".deleted") or "delete" in et.split("."):
        return True
    return False


def _prefix_domain(event_type: str) -> Optional[str]:
    if event_type.startswith("Faktury.") or event_type.startswith("invoice."):
        if _is_invoice_delete_event(event_type):
            return DOMAIN_INVOICE_DELETE
        return DOMAIN_INVOICE
    if event_type.startswith("Płatności.") or event_type.startswith("Platnosci."):
        return DOMAIN_PAYMENT
    if event_type.startswith("payment.") or event_type.startswith("payments."):
        return DOMAIN_PAYMENT
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
    if domain == DOMAIN_PAYMENT:
        return (
            f"routed_payment_pending_consumer:event_type={et};"
            "correctness=payment_poll_sync"
        )
    if domain == DOMAIN_INVOICE_DELETE:
        return (
            f"routed_invoice_delete_tombstone_pending:event_type={et};"
            "no_fetch_no_hard_delete"
        )
    return f"quarantined_unknown_event_type:{et}"

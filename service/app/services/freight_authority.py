"""freight_authority.py — derive freight parse-status from audit fields.

Single authority for classifying freight state. Consumed by the batch
detail API to expose a stable, frontend-readable ``freight_authority``
dict — the frontend must render from this, never guess from loose fields.

freight_status values
---------------------
parsed_positive    freight regex matched and returned > 0 on at least one
                   invoice. freight_pln computed if exchange rate available.
confidently_absent parser ran on all invoices and found no freight row
                   (freight_found_count == 0). Supplier declared no freight.
unparsed           invoice_totals present but no freight_found_count
                   annotation (old audit.json pre-annotation). Conservative:
                   show ⚠ Needs review rather than 0.00 PLN.
missing_invoice    invoice_totals absent — invoices not yet processed.

Never returns "No freight on invoices" or any internal field name.
"""
from __future__ import annotations


def derive_freight_authority(audit: dict) -> dict:
    """Derive freight authority from a loaded audit dict.

    Pure function — no I/O, no side effects. Caller is responsible for
    exception handling so a derivation failure does not break the batch
    detail response.

    Args:
        audit: The full audit.json content (may include derived enrichments).

    Returns:
        Dict with keys: freight_status, freight_pln, freight_usd,
        freight_source, freight_review_reason.
    """
    it = audit.get("invoice_totals") or {}
    if not it:
        return {
            "freight_status":        "missing_invoice",
            "freight_pln":           None,
            "freight_usd":           None,
            "freight_source":        None,
            "freight_review_reason": (
                "Invoice totals not computed — process invoices first."
            ),
        }

    fusd        = it.get("total_freight_usd") or 0.0
    found_count = it.get("freight_found_count", None)   # None = old audit.json

    # Exchange rate for PLN conversion (from customs declaration or SAD)
    cd   = (audit.get("customs_declaration") or
            audit.get("clearance_decision") or {})
    exch = cd.get("exchange_rate") or cd.get("sad_customs_rate")

    if fusd > 0:
        fpln = round(fusd * exch, 2) if exch else None
        return {
            "freight_status":        "parsed_positive",
            "freight_pln":           fpln,
            "freight_usd":           fusd,
            "freight_source":        "invoice_totals",
            "freight_review_reason": None,
        }

    if found_count is not None:
        if found_count == 0:
            # All parsers ran; no invoice had a freight row → supplier
            # did not declare freight (e.g. consolidated shipment billed
            # separately).
            return {
                "freight_status":        "confidently_absent",
                "freight_pln":           None,
                "freight_usd":           0.0,
                "freight_source":        "invoice_totals",
                "freight_review_reason": None,
            }
        # found_count > 0 but total is still 0 → freight row parsed as
        # explicit zero (rare; treated as declared-zero, not a gap).
        return {
            "freight_status":        "parsed_positive",
            "freight_pln":           0.0,
            "freight_usd":           0.0,
            "freight_source":        "invoice_totals",
            "freight_review_reason": None,
        }

    # No annotation (old audit.json) and zero freight → conservative
    # unparsed: we cannot distinguish "absent" from "not found by parser".
    return {
        "freight_status":        "unparsed",
        "freight_pln":           None,
        "freight_usd":           0.0,
        "freight_source":        "invoice_totals",
        "freight_review_reason": (
            "Freight is zero but parser annotation is absent. "
            "Re-process invoices to classify: 0.00 PLN or review."
        ),
    }

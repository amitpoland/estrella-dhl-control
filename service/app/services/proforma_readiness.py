# service/app/services/proforma_readiness.py
"""
Proforma readiness helpers.

Determines what actions are available on a draft based on its state.
"""
from typing import Any, Dict


def compute_convert_readiness(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return whether Convert to Invoice is available.

    convert_available is False when:
    - draft already has wfirma_invoice_id (already converted)
    - draft_state is 'converted'

    Returns the wfirma_invoice_id so the UI can display it.
    """
    already_converted = bool(
        draft.get("wfirma_invoice_id")
        or draft.get("draft_state") == "converted"
    )
    return {
        "convert_available": not already_converted,
        "wfirma_invoice_id": draft.get("wfirma_invoice_id") or "",
        "wfirma_invoice_number": draft.get("wfirma_invoice_number") or "",
        "draft_state": draft.get("draft_state") or "draft",
    }

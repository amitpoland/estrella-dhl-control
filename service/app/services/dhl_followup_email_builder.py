"""
dhl_followup_email_builder.py — Lightweight follow-up email for DHL.

Sent when DHL hasn't responded within the SLA window. Stays light: AWB PDF
only (if available) — does not re-attach heavy invoice/Polish-desc PDFs.
DHL already received those in the original DHL reply package.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..config.email_routing import DHL_TO

log = logging.getLogger(__name__)


def _invoice_dir() -> Path: return settings.storage_root / "outputs"


def build_dhl_followup_email(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """Build the standard follow-up package."""
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    ticket = (audit.get("dhl_email") or {}).get("ticket") or audit.get("dhl_ticket") or ""
    dec    = audit.get("clearance_decision") or {}
    cif    = dec.get("total_value_usd", 0)
    state  = audit.get("dhl_followup") or {}
    count  = int(state.get("followup_count", 0)) + 1   # this send

    # Recipients — keep follow-up to DHL only with internal CC (no broker spam)
    to_list = list(DHL_TO)                  # odprawacelna@dhl.com
    cc_list = [
        "import@estrellajewels.eu",
        "info@estrellajewels.eu",
        "account@estrellajewels.eu",
    ]

    # Invoice references (lightweight — names only, no PDFs)
    inv_dir = _invoice_dir() / batch_id / "source" / "invoices"
    invoice_names: List[str] = []
    if inv_dir.is_dir():
        invoice_names = [pdf.name for pdf in sorted(inv_dir.glob("*.pdf"))]

    # AWB attachment (the only file we ship — small + always relevant)
    attachments: List[Dict[str, str]] = []
    awb_attached = False
    awb_filename = (audit.get("inputs") or {}).get("awb")
    if awb_filename:
        awb_dir  = _invoice_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True

    subject = f"URGENT follow-up #{count} – DSK / customs documents required – AWB {awb}"
    if ticket:
        subject = f"Re: {ticket} – {subject}"

    body_text = _render_body_text(awb, ticket, cif, count, invoice_names)
    body_html = _render_body_html(body_text)

    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_followup",
        "to":           ", ".join(to_list),
        "to_list":      to_list,
        "cc":           ", ".join(cc_list),
        "cc_list":      cc_list,
        "subject":      subject,
        "body_text":    body_text,
        "body_html":    body_html,
        "attachments":  attachments,
        "awb_attached": awb_attached,
        "ticket":       ticket,
        "followup_seq": count,
        # Headers — request receipts where supported
        "extra_headers": {
            "Disposition-Notification-To": "import@estrellajewels.eu",
            "Return-Receipt-To":           "import@estrellajewels.eu",
            "X-Priority":                  "1",
            "Importance":                  "High",
        },
    }


def _render_body_text(
    awb:           str,
    ticket:        str,
    cif:           float,
    count:         int,
    invoice_names: List[str],
) -> str:
    invoices_block = ""
    if invoice_names:
        joined = "\n  ".join(invoice_names[:10])
        more   = f"\n  +{len(invoice_names)-10} more" if len(invoice_names) > 10 else ""
        invoices_block = f"\nInvoice references:\n  {joined}{more}\n"

    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(count, f"{count}th")

    return (
        f"Dear DHL Poland team,\n\n"
        f"This is our {ordinal} follow-up regarding AWB {awb}"
        f"{f' (ticket {ticket})' if ticket else ''}.\n"
        f"CIF value: USD {cif:,.2f}\n"
        f"{invoices_block}\n"
        f"The shipment is in customs / Warsaw and we still have not received "
        f"the DSK code / customs documents required for clearance.\n\n"
        f"Our broker (Ganther Sp. z o.o. — Mr. Grzegorz Ciagarlak) and the "
        f"customs agency (Agencja Celna Spedycja — Mr. Roman Kałużny) are "
        f"unable to proceed without these documents.\n\n"
        f"Please send the DSK / customs documents immediately, or confirm the "
        f"current status if there is any blocker on your side.\n\n"
        f"AWB document is attached for reference. Polish description and "
        f"invoices were already provided in our previous reply.\n\n"
        f"Thank you for your urgent attention.\n\n"
        f"Best regards,\n"
        f"Import Department\n"
        f"Estrella Jewels Sp. z o.o. Sp. k.\n"
        f"import@estrellajewels.eu\n"
    )


def _render_body_html(body_text: str) -> str:
    return (
        "<div style='font-family:sans-serif'>"
        "<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>"
        + body_text +
        "</pre></div>"
    )

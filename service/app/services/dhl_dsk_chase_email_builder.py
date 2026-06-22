"""
dhl_dsk_chase_email_builder.py — Post-DSK-reply chase email to DHL.

Sent when DHL has NOT issued the DSK number / cesja documents within the SLA
window AFTER Estrella already sent the signed DSK broker-notification reply.
Distinct from dhl_followup_email_builder (pre-T# chase): the framing here is
"we already authorized — please issue the DSK", and the count is read from
``audit["dhl_dsk_chase"]`` (not dhl_followup).

Lightweight: AWB PDF only (DHL already holds the DSK authorization + invoices +
Polish description from the original reply). Recipients: DHL on TO, Estrella
internal on CC only — NO broker (governance: broker is never CC'd on the DHL
DSK reply/chase; DHL routes the DSK to the broker directly).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..config.email_routing import DHL_TO, INTERNAL_CC

log = logging.getLogger(__name__)


def _invoice_dir() -> Path:
    return settings.storage_root / "outputs"


def build_dsk_chase_email(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """Build the post-reply DSK/cesja chase package (standard dict shape)."""
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    ticket = (audit.get("dhl_email") or {}).get("ticket") or audit.get("dhl_ticket") or ""
    dec    = audit.get("clearance_decision") or {}
    cif    = dec.get("total_value_usd", 0)
    state  = audit.get("dhl_dsk_chase") or {}
    count  = int(state.get("followup_count", 0)) + 1   # this send

    # Recipients — DHL on TO, Estrella internal on CC only (no broker).
    to_list = list(DHL_TO)                  # odprawacelna@dhl.com
    cc_list = list(INTERNAL_CC)             # info / import / account @estrellajewels.eu

    # AWB attachment (the only file we ship — small + always relevant).
    attachments: List[Dict[str, str]] = []
    awb_attached = False
    awb_filename = (audit.get("inputs") or {}).get("awb")
    if awb_filename:
        awb_dir  = _invoice_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True

    subject = f"DSK issuance reminder #{count} – AWB {awb}"
    if ticket:
        subject = f"Re: {ticket} – {subject}"

    body_text = _render_body_text(awb, ticket, cif, count)
    body_html = _render_body_html(body_text)

    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_dsk_chase",
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
        "extra_headers": {
            "Disposition-Notification-To": "import@estrellajewels.eu",
            "Return-Receipt-To":           "import@estrellajewels.eu",
            "X-Priority":                  "1",
            "Importance":                  "High",
        },
    }


def _render_body_text(awb: str, ticket: str, cif: float, count: int) -> str:
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(count, f"{count}th")
    return (
        f"Dear DHL Poland team,\n\n"
        f"This is our {ordinal} reminder regarding AWB {awb}"
        f"{f' (ticket {ticket})' if ticket else ''}.\n"
        f"CIF value: USD {cif:,.2f}\n\n"
        f"We have already sent you the signed broker-notification order (DSK) "
        f"authorizing our customs agency (Agencja Celna Spedycja — "
        f"Mr. Roman Kałużny) to handle clearance.\n\n"
        f"We have NOT yet received the DSK number / cesja documents from your "
        f"side. Our broker cannot file the customs declaration until DHL issues "
        f"them.\n\n"
        f"Please issue the DSK number / cesja documents to our agency "
        f"immediately, or confirm the current status if there is any blocker on "
        f"your side.\n\n"
        f"AWB document is attached for reference; the DSK authorization, Polish "
        f"description and invoices were already provided in our previous reply.\n\n"
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

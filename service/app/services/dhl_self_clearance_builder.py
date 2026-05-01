"""
dhl_self_clearance_builder.py — Low-value (CIF ≤ $2,500) DHL self-clearance reply.

When DHL customs email arrives for a low-value shipment, reply in the SAME
thread to odprawacelna@dhl.com with:
  - All invoice PDFs
  - AWB PDF
  - Polish description PDF

No agency / Ganther / ACS routing. No DSK transfer request.

Triggered when:
  audit.clearance_decision.clearance_path == "carrier_self_clearance"
  AND audit.dhl_email.received is True
  AND audit.dhl_self_clearance_reply_package not yet sent

Returns the same dict shape as the other builders so email_sender path is
identical.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..config.email_routing import DHL_TO, INTERNAL_CC

log = logging.getLogger(__name__)


def _invoice_dir() -> Path: return settings.storage_root / "outputs"
def _polish_dir()  -> Path: return settings.storage_root / "polish_descriptions"


def build_dhl_self_clearance_reply(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """
    Assemble the DHL reply for a low-value (carrier_self_clearance) shipment.

    Returns the standard package dict.
    """
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    dhl_email = audit.get("dhl_email") or {}
    ticket    = dhl_email.get("ticket") or audit.get("dhl_ticket") or ""
    cif       = (audit.get("clearance_decision") or {}).get("total_value_usd", 0)

    # Recipients: reply to DHL only (+ internal CC for visibility)
    to_list = list(DHL_TO)
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in INTERNAL_CC if a.lower() not in to_norm]

    # Attachments — invoices + AWB + Polish description (all mandatory)
    attachments: List[Dict[str, str]] = []
    missing:     List[str] = []
    awb_attached = False

    polish_fn = audit.get("polish_desc_filename") or ""
    if polish_fn:
        polish_path = _polish_dir() / polish_fn
        if polish_path.is_file():
            attachments.append({"label": "Polish Customs Description", "path": str(polish_path)})
        else:
            missing.append(f"Polish desc PDF not on disk: {polish_fn}")
    else:
        missing.append("Polish description not generated")

    inv_dir = _invoice_dir() / batch_id / "source" / "invoices"
    if inv_dir.is_dir():
        for pdf in sorted(inv_dir.glob("*.pdf")):
            attachments.append({"label": f"Invoice: {pdf.name}", "path": str(pdf)})
    else:
        missing.append("Invoice source directory not found")

    awb_filename = (audit.get("inputs") or {}).get("awb")
    if awb_filename:
        awb_dir  = _invoice_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True
        else:
            missing.append(f"AWB file not found: {awb_filename}")
            log.error("[dhl_self_clear] AWB attachment missing: file=%s batch=%s",
                      awb_filename, batch_id)
    elif awb:
        log.error("[dhl_self_clear] AWB attachment missing: no PDF uploaded for AWB %s",
                  awb)
        missing.append("AWB PDF: no file uploaded")

    subject = f"Re: {ticket} – AWB {awb} customs clearance documents" if ticket \
              else f"AWB {awb} customs clearance documents"

    body_text = _render_body_text(awb, ticket, cif, len(attachments))
    body_html = _render_body_html(body_text)

    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_self_clearance_reply",
        "to":           ", ".join(to_list),
        "to_list":      to_list,
        "cc":           ", ".join(cc_list),
        "cc_list":      cc_list,
        "subject":      subject,
        "body_text":    body_text,
        "body_html":    body_html,
        "attachments":  attachments,
        "missing":      missing,
        "awb_attached": awb_attached,
        "ticket":       ticket,
    }


def _render_body_text(awb: str, ticket: str, cif: float, attach_count: int) -> str:
    return (
        f"Dear DHL Poland team,\n\n"
        f"Reference: AWB {awb}{f' (ticket {ticket})' if ticket else ''}\n"
        f"CIF value: USD {cif:,.2f}\n\n"
        f"In response to your customs clearance request, please find attached "
        f"all the documents required for self-clearance:\n"
        f"  - Commercial invoice(s)\n"
        f"  - AWB document\n"
        f"  - Polish description of goods\n\n"
        f"This shipment is below the broker-clearance threshold and may be "
        f"cleared directly. Please proceed with customs processing and notify "
        f"us of the duty/tax breakdown for payment.\n\n"
        f"Total attachments: {attach_count}.\n\n"
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

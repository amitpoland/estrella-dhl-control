"""
dhl_reply_builder.py — Build the DHL customs reply package.

Triggered when DHL customs email is received (T#... ticket from
odprawacelna@dhl.com) and CIF > $2,500 — i.e. external_agency_clearance
path. Reply confirms broker (Ganther + ACS) and requests DSK code.

Standard template (Estrella ↔ DHL Poland):
    From:    Import Department <import@estrellajewels.eu>
    To:      odprawacelna@dhl.com (+ administracja_centralna@dhl.com)
    CC:      Ganther + ACS + Estrella internal
    Subject: Request for custom clearance – AWB {awb}
    Body:    English standard text (see template)
    Attach:  Polish description PDF + invoice PDFs + AWB PDF

Returns the same dict shape as agency_email_builder.build_agency_package
so email_sender / email queue path is identical.
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

# DHL DSK source receives carbon copy so it can attach the broker assignment
_DHL_DSK_NOTIFY = ["administracja_centralna@dhl.com"]

# Broker / agency CC list — kept in the loop on the reply
_BROKER_CC = [
    "ciagarlak@ganther.com.pl",
    "piotr@acspedycja.pl",
    "biuro@acspedycja.pl",
    "roman@acspedycja.pl",
]


def build_dhl_reply_package(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """
    Assemble the DHL customs reply for a high-value (agency-path) shipment.

    Returns
    -------
    {
        from_address, email_type:"dhl_reply",
        to, to_list, cc, cc_list,
        subject, body_text, body_html,
        attachments: [{label, path}],
        missing:     [str],
        awb_attached: bool,
    }
    """
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    dhl_email = audit.get("dhl_email") or {}
    ticket    = dhl_email.get("ticket") or audit.get("dhl_ticket") or ""
    dec       = audit.get("clearance_decision") or {}
    cif       = dec.get("total_value_usd", 0)

    # Recipients ---------------------------------------------------------------
    to_list = list(DHL_TO) + _DHL_DSK_NOTIFY  # DHL + DSK source
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in (_BROKER_CC + list(INTERNAL_CC)) if a.lower() not in to_norm]

    # Attachments --------------------------------------------------------------
    attachments: List[Dict[str, str]] = []
    missing:     List[str] = []
    awb_attached = False

    # Polish description (mandatory)
    polish_fn = audit.get("polish_desc_filename") or ""
    if polish_fn:
        polish_path = _polish_dir() / polish_fn
        if polish_path.is_file():
            attachments.append({"label": "Polish Customs Description", "path": str(polish_path)})
        else:
            missing.append(f"Polish desc PDF not on disk: {polish_fn}")
    else:
        missing.append("Polish description not generated")

    # Invoice PDFs
    inv_dir = _invoice_dir() / batch_id / "source" / "invoices"
    if inv_dir.is_dir():
        for pdf in sorted(inv_dir.glob("*.pdf")):
            attachments.append({"label": f"Invoice: {pdf.name}", "path": str(pdf)})
    else:
        missing.append("Invoice source directory not found")

    # AWB PDF (mandatory when known)
    awb_filename = (audit.get("inputs") or {}).get("awb")
    if awb_filename:
        awb_dir  = _invoice_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True
        else:
            missing.append(f"AWB file not found: {awb_filename}")
            log.error("[dhl_reply_pkg] AWB attachment missing: file=%s batch=%s",
                      awb_filename, batch_id)
    elif awb:
        log.error("[dhl_reply_pkg] AWB attachment missing: no PDF uploaded for AWB %s",
                  awb)
        missing.append("AWB PDF: no file uploaded")

    # Subject + body -----------------------------------------------------------
    subject = f"Request for custom clearance – AWB {awb}" if awb else "Request for custom clearance"
    if ticket:
        subject = f"Re: {ticket} – {subject}"

    body_text = _render_body_text(awb, ticket, cif)
    body_html = _render_body_html(awb, ticket, cif)

    return {
        "from_address": "import@estrellajewels.eu",   # Poland Import identity
        "email_type":   "dhl_reply",
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


# ── Standard template ────────────────────────────────────────────────────────

def _render_body_text(awb: str, ticket: str, cif: float) -> str:
    return (
        f"Dear DHL Poland team,\n\n"
        f"Reference: AWB {awb}{f' (ticket {ticket})' if ticket else ''}\n"
        f"CIF value: USD {cif:,.2f}\n\n"
        f"We confirm that we have appointed our customs broker:\n"
        f"  Ganther Sp. z o.o.\n"
        f"  Contact: Mr. Grzegorz Ciagarlak (ciagarlak@ganther.com.pl)\n\n"
        f"Additionally, Agencja Celna Spedycja\n"
        f"  Contact: Mr. Roman Kałużny (roman@acspedycja.pl)\n"
        f"is included for full clearance handling.\n\n"
        f"We kindly request:\n"
        f"  1. DSK code for the shipment\n"
        f"  2. Confirmation of broker assignment\n"
        f"  3. Required next steps for clearance\n\n"
        f"Attached:\n"
        f"  - Polish customs description\n"
        f"  - Invoice set\n"
        f"  - AWB document\n\n"
        f"Please proceed with coordination with our broker.\n\n"
        f"Best regards,\n"
        f"Import Department\n"
        f"Estrella Jewels Sp. z o.o. Sp. k.\n"
        f"import@estrellajewels.eu\n"
    )


def _render_body_html(awb: str, ticket: str, cif: float) -> str:
    text = _render_body_text(awb, ticket, cif)
    # Minimal HTML — preserve formatting via <pre>; avoids template-injection risk
    return (
        "<div style='font-family:sans-serif'>"
        "<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>"
        + text +
        "</pre></div>"
    )

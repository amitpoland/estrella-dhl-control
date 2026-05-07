"""
agency_forward_after_dhl_builder.py — Post-DSK-receipt agency forward.

Triggered after DHL has sent back the customs documents (DSK / PZC / SAD /
ZC429). Forwards everything to the broker (Piotr @ Agencja Celna Spedycja)
+ CC Ganther + ACS team + Estrella internal, in the SAME DHL ticket thread,
with a short professional "please proceed" instruction.

Sender: import@estrellajewels.eu
Mode:   reply (same thread — Subject prefixed Re: T#... so threading clients
        group it with the DHL ticket conversation)

Builds the standard package dict shape; email_sender handles delivery.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..config.email_routing import AGENCY_TO, AGENCY_CC, INTERNAL_CC

log = logging.getLogger(__name__)


def _invoice_dir() -> Path: return settings.storage_root / "outputs"


def build_agency_forward_after_dhl(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """
    Assemble the post-DHL agency forward package.

    Returns standard dict (or one with `error` if AWB PDF missing — caller
    must NOT send when error is set).
    """
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    ticket = (audit.get("dhl_email") or {}).get("ticket") or audit.get("dhl_ticket") or ""

    # Recipients — spec v3 hard rule 7: agency recipient layout is identical
    # for B1 and B4. Read from the centralized email_routing constants so
    # any future spec amendment lands once and applies to both stages.
    to_list = list(AGENCY_TO)
    cc_list = list(AGENCY_CC) + list(INTERNAL_CC)
    # Dedupe (defensive — in case any address appears in both)
    to_norm = {a.lower() for a in to_list}
    cc_list = [a for a in cc_list if a.lower() not in to_norm]

    # Attachments — full document set (same as received from DHL):
    #   DS/cesja document + invoices + AWB + Polish description
    attachments: List[Dict[str, str]] = []
    missing:     List[str] = []
    awb_attached = False

    # 1) DHL-received customs documents (DS/cesja, PZC, SAD, ZC429, etc.)
    docs_state = audit.get("dhl_documents_received") or {}
    docs_files = docs_state.get("files") or []
    for doc in docs_files:
        path_str = doc.get("path") if isinstance(doc, dict) else ""
        if not path_str:
            continue
        p = Path(path_str)
        if p.is_file():
            doc_type = (doc.get("type") if isinstance(doc, dict) else "") or "DHL document"
            attachments.append({
                "label": f"{doc_type}: {p.name}",
                "path":  str(p),
            })
        else:
            missing.append(f"DHL doc not on disk: {p.name}")

    # 2) Invoice PDFs (all invoices from source)
    inv_dir = _invoice_dir() / batch_id / "source" / "invoices"
    if inv_dir.is_dir():
        for pdf in sorted(inv_dir.glob("*.pdf")):
            attachments.append({"label": f"Invoice: {pdf.name}", "path": str(pdf)})
    else:
        missing.append("Invoice source directory not found")

    # 3) AWB PDF (mandatory)
    awb_filename = (audit.get("inputs") or {}).get("awb")
    if awb_filename:
        awb_dir  = _invoice_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True
        else:
            missing.append(f"AWB file not found: {awb_filename}")
            log.error("[agency_forward] AWB attachment missing: file=%s batch=%s",
                      awb_filename, batch_id)
    elif awb:
        log.error("[agency_forward] AWB attachment missing: no PDF for AWB %s", awb)
        missing.append("AWB PDF: no file uploaded")

    # 4) Polish customs description
    polish_fn = audit.get("polish_desc_filename") or ""
    if polish_fn:
        polish_dir = settings.storage_root / "polish_descriptions"
        polish_path = polish_dir / polish_fn
        if polish_path.is_file():
            attachments.append({"label": "Polish Customs Description", "path": str(polish_path)})
        else:
            missing.append(f"Polish desc PDF not on disk: {polish_fn}")

    # AWB-required block — caller must check `error` field
    if not awb_attached:
        return {
            "error":         "awb_pdf_missing",
            "error_detail":  "AWB PDF missing — agency forward blocked",
            "missing":       missing,
        }

    # Subject — Re: prefix + ticket so it threads with the DHL conversation
    if ticket:
        subject = f"Re: {ticket} – AWB {awb} – Customs clearance documents"
    else:
        subject = f"Re: AWB {awb} – Customs clearance documents"

    body_text = _render_body_text(awb, ticket, len(attachments))
    body_html = _render_body_html(body_text)

    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "agency_forward_after_dhl",
        "to":           ", ".join(to_list),
        "to_list":      to_list,
        "cc":           ", ".join(cc_list),
        "cc_list":      cc_list,
        "subject":      subject,
        "body_text":    body_text,
        "body_html":    body_html,
        "attachments":  attachments,
        "missing":      missing,
        "awb_attached": True,
        "ticket":       ticket,
    }


def _render_body_text(awb: str, ticket: str, attach_count: int) -> str:
    return (
        f"Dear Sir,\n\n"
        f"We confirm that all required customs documents for the shipment "
        f"under AWB {awb}{f' (DHL ticket {ticket})' if ticket else ''} are "
        f"now available.\n\n"
        f"Please find them attached and proceed with the customs clearance "
        f"process on an urgent basis.\n\n"
        f"Our designated broker, Ganther Sp. z o.o. (Mr. Grzegorz Ciagarlak), "
        f"is authorized to handle the clearance and is in copy on this email.\n\n"
        f"Kindly proceed without delay and keep us informed on the status.\n\n"
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

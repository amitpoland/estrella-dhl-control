"""
agency_email_builder.py — Build the email package for external customs agency.

Used when clearance_decision.clearance_path == "external_agency_clearance"
(shipment value > 2 500 USD).

The package contains:
  - Invoice PDF(s)
  - AWB / tracking document (if uploaded)
  - Polish customs description PDF (must be generated first)
  - Bilingual email body (PL + EN)

Does NOT send — returns a structured dict that routes_agency queues and persists.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..config.email_routing import (
    AGENCY_TO,
    AGENCY_CC,
    INTERNAL_CC,
    format_to,
    format_cc,
    primary,
)

log = logging.getLogger(__name__)

_INVOICE_DIR  = settings.storage_root / "outputs"   # batch-scoped: outputs/<batch_id>/source/invoices/
_POLISH_DIR   = settings.storage_root / "polish_descriptions"


def build_agency_package(audit: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    """
    Assemble an agency email package from audit data.

    Parameters
    ----------
    audit    : full audit dict for the batch
    batch_id : batch identifier (used to locate source files)

    Returns
    -------
    {
        "to":          str          — primary agency recipient (comma-separated if multiple)
        "to_list":     list[str]    — full TO list
        "cc":          str          — all CC recipients comma-separated
        "cc_list":     list[str]    — full CC list (agency CC + internal CC)
        "subject":     str
        "body_pl":     str          — Polish body
        "body_en":     str          — English body
        "attachments": list[dict]   — [{label, path}]
        "missing":     list[str]    — attachments that could not be resolved
    }

    Raises
    ------
    ValueError  if Polish description has not been generated yet
    """
    dec    = audit.get("clearance_decision") or {}
    awb    = audit.get("tracking_no") or audit.get("awb") or ""
    doc_no = audit.get("doc_no") or batch_id

    # ── Recipient resolution ──────────────────────────────────────────────────
    # Allow clearance_decision to override agency TO (e.g. per-shipment agency)
    _agency_override = dec.get("agency_email")
    if _agency_override and _agency_override not in AGENCY_TO:
        to_list: List[str] = [_agency_override] + AGENCY_TO
    else:
        to_list = list(AGENCY_TO)

    cc_list: List[str] = list(AGENCY_CC) + list(INTERNAL_CC)

    # ── Resolve attachments ───────────────────────────────────────────────────
    attachments: List[Dict[str, str]] = []
    missing:     List[str]            = []

    # 1. Polish description (mandatory for agency path)
    polish_filename = audit.get("polish_desc_filename")
    if polish_filename:
        polish_path = _POLISH_DIR / polish_filename
        if polish_path.is_file():
            attachments.append({"label": "Polish Customs Description", "path": str(polish_path)})
        else:
            missing.append(f"Polish description file not found: {polish_filename}")
    else:
        raise ValueError(
            "Polish customs description has not been generated. "
            "Generate it first before building the agency package."
        )

    # 2. Invoice PDFs
    inv_dir = _INVOICE_DIR / batch_id / "source" / "invoices"
    if inv_dir.is_dir():
        for pdf in sorted(inv_dir.glob("*.pdf")):
            attachments.append({"label": f"Invoice: {pdf.name}", "path": str(pdf)})
    else:
        missing.append("Invoice source directory not found")

    # 3. AWB / tracking document — MANDATORY when AWB is on file
    awb_filename = (audit.get("inputs") or {}).get("awb")
    awb_attached = False
    if awb_filename:
        awb_dir = _INVOICE_DIR / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename if awb_dir.is_dir() else None
        if awb_path and awb_path.is_file():
            attachments.append({"label": "AWB Document", "path": str(awb_path)})
            awb_attached = True
        else:
            missing.append(f"AWB file not found: {awb_filename}")
            log.error("[agency_pkg] AWB attachment missing: file=%s batch=%s",
                      awb_filename, batch_id)
    elif audit.get("awb") or audit.get("tracking_no"):
        # AWB number known but no file uploaded — surface as critical
        log.error("[agency_pkg] AWB attachment missing: no PDF uploaded for AWB %s, batch=%s",
                  audit.get("awb") or audit.get("tracking_no"), batch_id)
        missing.append("AWB PDF: no file uploaded")

    # ── Email bodies ──────────────────────────────────────────────────────────
    body_pl = _render_body_pl(audit, awb, doc_no, dec)
    body_en = _render_body_en(audit, awb, doc_no, dec)

    subject = f"Zgłoszenie celne – AWB {awb}" if awb else f"Zgłoszenie celne – {doc_no}"

    return {
        "from_address": "import@estrellajewels.eu",   # Poland Import identity
        "email_type":   "agency",
        "to":          format_to(to_list),
        "to_list":     to_list,
        "cc":          format_cc(cc_list),
        "cc_list":     cc_list,
        "subject":     subject,
        "body_pl":     body_pl,
        "body_en":     body_en,
        "attachments": attachments,
        "missing":     missing,
        "awb_attached": awb_attached,
    }


def _render_body_pl(
    audit: Dict[str, Any],
    awb: str,
    doc_no: str,
    dec: Dict[str, Any],
) -> str:
    cif = dec.get("total_value_usd", 0)
    lines = [
        "Szanowni Państwo,",
        "",
        f"Przesyłamy dokumenty do odprawy celnej dla przesyłki numer AWB: {awb}",
        "",
        f"Wartość CIF: USD {cif:,.2f}" if cif else "",
        "",
        "W załączeniu:",
        "- Opis towarów do odprawy (opis celny)",
        "- Faktury handlowe",
        "- Dokument AWB (jeśli dostępny)",
        "",
        "Prosimy o potwierdzenie odbioru i informację o dalszych krokach.",
        "",
        "Z poważaniem,",
        "Estrella Jewels",
        "info@estrellajewels.eu",
    ]
    return "\n".join(l for l in lines if l is not None)


def _render_body_en(
    audit: Dict[str, Any],
    awb: str,
    doc_no: str,
    dec: Dict[str, Any],
) -> str:
    cif = dec.get("total_value_usd", 0)
    lines = [
        "Dear Agency,",
        "",
        f"Please find attached the customs clearance documents for shipment AWB: {awb}",
        "",
        f"CIF Value: USD {cif:,.2f}" if cif else "",
        "",
        "Attachments:",
        "- Polish customs description",
        "- Commercial invoice(s)",
        "- AWB document (if available)",
        "",
        "Please confirm receipt and advise on next steps.",
        "",
        "Best regards,",
        "Estrella Jewels",
        "info@estrellajewels.eu",
    ]
    return "\n".join(l for l in lines if l is not None)

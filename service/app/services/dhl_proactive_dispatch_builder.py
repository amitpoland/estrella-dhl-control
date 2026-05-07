"""
dhl_proactive_dispatch_builder.py — first-contact body builder for proactive
DHL customs dispatch (P2 Slice A).

Distinct from :mod:`app.services.dhl_self_clearance_builder` which is reply-
thread-coupled and embeds CIF in the body. This builder is intentionally
first-contact-only:

  * subject does NOT start with "Re:" — D4 locked format
  * NEVER reads ``audit["dhl_email"]["ticket"]``
  * NEVER reads any monetary or customs-value field
  * goods description is delivered ONLY as the attached Polish description PDF
  * recipient/CC values in the returned dict are an OPERATOR PREVIEW; the
    queue-time path (:func:`queue_proposal`) re-resolves them from
    ``email_routing.DHL_TO`` / ``email_routing.INTERNAL_CC`` (canonical),
    falling back to ``settings.dhl_customs_email`` / ``settings.dhl_customs_cc``
    only when the centralized constants are empty, before invoking
    ``email_service.queue_email``

Allowed audit reads (FROZEN):
  * ``audit["dhl_awb"]`` / ``audit["awb"]`` / ``audit["batch_meta"]["awb"]``
    / ``audit["tracking_no"]``
  * ``audit["polish_desc_filename"]``
  * ``audit["inputs"]["invoices"]``
  * ``audit["inputs"]["awb"]``

Forbidden audit reads:
  * ``audit["clearance_decision"]`` (no CIF, no duty, no path)
  * ``audit["customs_declaration"]``
  * ``audit["invoice_totals"]``
  * ``audit["wfirma_export"]``
  * any monetary / customs-value field
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings
from ..config.email_routing import resolve_dhl_to, resolve_dhl_cc

log = logging.getLogger(__name__)


def _outputs_dir() -> Path:
    return settings.storage_root / "outputs"


def _polish_desc_dir() -> Path:
    return settings.storage_root / "polish_descriptions"


def _resolve_awb(audit: Dict[str, Any]) -> str:
    """Multi-source AWB resolution matching the existing convention."""
    return (
        audit.get("dhl_awb")
        or audit.get("awb")
        or (audit.get("batch_meta") or {}).get("awb")
        or audit.get("tracking_no")
        or ""
    )


def build_dhl_proactive_dispatch(
    audit: Dict[str, Any],
    batch_id: str,
) -> Dict[str, Any]:
    """
    Build the proactive customs-dispatch email package.

    Returned dict shape::

      {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_proactive_dispatch",
        "to":           <preview from DHL_TO; fallback settings.dhl_customs_email>,
        "cc":           <preview from INTERNAL_CC; fallback settings.dhl_customs_cc>,
        "subject":      "AWB {awb} — Zgłoszenie celne / Customs Declaration",
        "body_text":    <Polish-first bilingual first-contact body>,
        "body_html":    <pre-wrapped body_text>,
        "attachments":  [{"label": str, "path": str}, ...],
        "missing":      [<filenames missing from disk; non-empty → caller aborts>],
      }

    The ``to`` and ``cc`` fields in the returned dict are PREVIEW only — they
    populate the operator-visible draft. The queue-time code path
    re-resolves them authoritatively from current settings before sending.

    The body is a first-contact note in Polish then English. It mentions
    only the AWB and the attachment list. It contains NO monetary or
    customs-value text.
    """
    awb = _resolve_awb(audit)

    attachments: List[Dict[str, str]] = []
    missing: List[str] = []

    # ── Polish description PDF — the goods description payload ─────────────
    polish_fn = audit.get("polish_desc_filename") or ""
    if polish_fn:
        polish_path = _polish_desc_dir() / polish_fn
        if polish_path.is_file():
            attachments.append({
                "label": "Polish Customs Description",
                "path":  str(polish_path),
            })
        else:
            missing.append(f"polish description: {polish_fn}")
    else:
        missing.append("polish description: not generated")

    # ── Commercial invoices ────────────────────────────────────────────────
    inv_dir = _outputs_dir() / batch_id / "source" / "invoices"
    if inv_dir.is_dir():
        invoice_files = sorted(inv_dir.glob("*.pdf"))
        if not invoice_files:
            missing.append("invoices: no PDFs found in source/invoices/")
        for pdf in invoice_files:
            attachments.append({
                "label": f"Invoice: {pdf.name}",
                "path":  str(pdf),
            })
    else:
        missing.append("invoices: source directory not found")

    # ── AWB document ───────────────────────────────────────────────────────
    awb_filename = (audit.get("inputs") or {}).get("awb") or ""
    if awb_filename:
        awb_dir = _outputs_dir() / batch_id / "source" / "awb"
        awb_path = awb_dir / awb_filename
        if awb_path.is_file():
            attachments.append({
                "label": "AWB Document",
                "path":  str(awb_path),
            })
        else:
            missing.append(f"awb: {awb_filename}")
    else:
        missing.append("awb: no PDF uploaded")

    # ── Subject (D4 locked format — first-contact, AWB-first, Polish-first)
    subject = f"AWB {awb} — Zgłoszenie celne / Customs Declaration"

    body_text = _render_body_text(awb, len(attachments))
    body_html = _render_body_html(body_text)

    # Recipient/CC preview — DHL_TO + INTERNAL_CC (canonical) with env-var
    # fallback only when the centralized constants are empty. Queue-time
    # re-resolution overrides these values.
    to_preview = resolve_dhl_to()
    cc_preview = resolve_dhl_cc()

    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_proactive_dispatch",
        "to":           to_preview,
        "cc":           cc_preview,
        "subject":      subject,
        "body_text":    body_text,
        "body_html":    body_html,
        "attachments":  attachments,
        "missing":      missing,
    }


def _render_body_text(awb: str, attach_count: int) -> str:
    """First-contact body. Polish first, then English. No CIF, no ticket, no Re."""
    return (
        "Szanowni Państwo,\n\n"
        f"Niniejszym przesyłamy proaktywnie dokumenty celne dla przesyłki "
        f"AWB {awb} zmierzającej do Polski.\n\n"
        "W załączeniu:\n"
        "  - Faktura(y) handlowa(e)\n"
        "  - List przewozowy (AWB)\n"
        "  - Opis towarów w języku polskim\n\n"
        "Prosimy o uwzględnienie tych dokumentów w procesie odprawy "
        "celnej po przybyciu przesyłki do Polski.\n\n"
        "---\n\n"
        "Dear DHL Customs Team,\n\n"
        f"We are proactively sending customs documents for the shipment "
        f"AWB {awb} inbound to Poland.\n\n"
        "Attached:\n"
        "  - Commercial invoice(s)\n"
        "  - AWB document\n"
        "  - Polish description of goods\n\n"
        f"Total attachments: {attach_count}.\n\n"
        "Please use these documents during customs clearance once the "
        "shipment arrives in Poland.\n\n"
        "Best regards,\n"
        "Import Department\n"
        "Estrella Jewels Sp. z o.o. Sp. k.\n"
        "import@estrellajewels.eu\n"
    )


def _render_body_html(body_text: str) -> str:
    return (
        "<div style='font-family:sans-serif'>"
        "<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>"
        + body_text +
        "</pre></div>"
    )

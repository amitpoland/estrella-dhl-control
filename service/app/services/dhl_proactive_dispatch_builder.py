"""
dhl_proactive_dispatch_builder.py — body builder for proactive DHL customs
dispatch.

Subject policy (revised):
  * If ``audit["dhl_ticket"]`` (or ``audit["dhl_email"]["ticket"]``) is set,
    the subject joins the existing DHL thread:
        ``Re:T#... - Agencja Celna DHL - przesyłka numer: <AWB>``
  * Otherwise, fall back to a standalone subject:
        ``AWB <AWB> — Dokumenty celne / Customs documents``

Body policy:
  * Mobile-safe: short paragraphs, numbered list, no wide tables, no
    leading-indent bullets that wrap badly on narrow screens.
  * Polish first, English second, both reading the same meaning.
  * Attachment count in the body is derived from the actual attachments
    list — never inflated or hardcoded.
  * Optional one-paragraph correction note when ``correction=True``.

Forbidden audit reads (FROZEN):
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


def _resolve_dhl_ticket(audit: Dict[str, Any]) -> str:
    """Pull the DHL customs ticket from any known location in the audit.
    Returns empty string when no ticket has been recorded."""
    t = (audit.get("dhl_ticket") or "").strip()
    if t:
        return t
    de = audit.get("dhl_email") or {}
    if isinstance(de, dict):
        t = (de.get("ticket") or "").strip()
        if t:
            return t
    return ""


def _build_subject(awb: str, ticket: str) -> str:
    """Subject precedence: DHL thread (when ticket present) > standalone."""
    if ticket:
        return f"Re:{ticket} - Agencja Celna DHL - przesyłka numer: {awb}"
    return f"AWB {awb} — Dokumenty celne / Customs documents"


def build_dhl_proactive_dispatch(
    audit: Dict[str, Any],
    batch_id: str,
    *,
    correction: bool = False,
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

    # ── Subject (thread-aware) ──────────────────────────────────────────────
    ticket  = _resolve_dhl_ticket(audit)
    subject = _build_subject(awb, ticket)

    body_text = _render_body_text(awb, correction=correction)
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


def _render_body_text(awb: str, *, correction: bool = False) -> str:
    """Mobile-safe bilingual body. Polish first, then English. Numbered list,
    no leading-space bullets, no wide tables. The attachment count is NOT
    injected here — the recipient sees the actual MIME parts attached."""
    correction_pl = (
        "Niniejsza wiadomość jest korektą wcześniejszej wysyłki, "
        "która została dostarczona bez załączników. Przesyłamy komplet "
        "dokumentów.\n\n"
    ) if correction else ""

    correction_en = (
        "This is a correction of an earlier message that was delivered "
        "without attachments. The full document set is attached.\n\n"
    ) if correction else ""

    return (
        "Szanowni Państwo,\n\n"
        + correction_pl
        + f"W załączeniu przesyłamy dokumenty do odprawy celnej dla "
          f"przesyłki DHL AWB {awb}.\n\n"
        + "Załączniki:\n"
        + "1. Faktury handlowe\n"
        + "2. List przewozowy AWB\n"
        + "3. Opis towarów w języku polskim\n\n"
        + "Prosimy o wykorzystanie dokumentów do odprawy celnej przesyłki.\n\n"
        + "---\n\n"
        + "Dear DHL Customs Team,\n\n"
        + correction_en
        + f"Please find attached the customs documents for DHL shipment "
          f"AWB {awb}.\n\n"
        + "Attachments:\n"
        + "1. Commercial invoices\n"
        + "2. AWB document\n"
        + "3. Polish goods description\n\n"
        + "Please use these documents for customs clearance.\n\n"
        + "Best regards,\n"
        + "Import Department\n"
        + "Estrella Jewels Sp. z o.o. Sp. k.\n"
        + "import@estrellajewels.eu\n"
    )


def _render_body_html(body_text: str) -> str:
    """HTML wrapper that preserves text layout exactly. Mobile-safe: no
    tables, no fixed widths, no inline alignment that breaks on narrow
    viewports. white-space:pre-wrap keeps newlines while allowing word-wrap."""
    return (
        "<div style='font-family:Arial,sans-serif;font-size:14px;"
        "line-height:1.5;color:#1e293b;max-width:640px;'>"
        "<pre style='white-space:pre-wrap;word-wrap:break-word;"
        "font-family:Arial,sans-serif;font-size:14px;margin:0;'>"
        + body_text +
        "</pre></div>"
    )

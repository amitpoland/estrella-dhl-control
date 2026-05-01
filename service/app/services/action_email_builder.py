"""
action_email_builder.py — Build email draft dicts for action proposals.

Each draft is a pure dict — it is never sent here.
Callers (routes_action_proposals.py) call queue_email() only after admin approval.

Supported proposal types:
  dhl_followup              DHL follow-up asking for DSK/customs status
  agency_followup           ACS Spedycja follow-up asking for SAD/ZC429 status
  dhl_dsk_transfer          Send DSK broker notification to DHL customs
  carrier_description_reply Send Polish product description to DHL/FedEx customs
  agency_clearance_email    Send full clearance package to ACS Spedycja
  duty_payment_followup     Internal reminder to confirm duty payment
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..config.email_routing import (
    AGENCY_TO, AGENCY_CC, DHL_TO, INTERNAL_CC,
    format_to, format_cc, primary,
)

_OUTPUTS = settings.storage_root / "outputs"

# ── Public API ────────────────────────────────────────────────────────────────

def build_email_draft(proposal_type: str, audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build an email draft dict for the given proposal type and audit state.

    Returns
    -------
    dict with keys:
        to          str   primary recipient(s), comma-separated
        cc          str   CC list, comma-separated (may be empty)
        subject     str
        body_text   str   plain-text body
        body_html   str   HTML body (wraps body_text in <pre> if not supplied)
        attachments list  [{label, path}] — paths relative to batch output dir
        draft_built_at str ISO timestamp
    """
    builders = {
        "dhl_followup":              _build_dhl_followup,
        "agency_followup":           _build_agency_followup,
        "dhl_dsk_transfer":          _build_dhl_dsk_transfer,
        "carrier_description_reply": _build_carrier_description_reply,
        "agency_clearance_email":    _build_agency_clearance_email,
        "duty_payment_followup":     _build_duty_payment_followup,
        "tracking_lookup":           _build_tracking_lookup,
    }
    builder = builders.get(proposal_type)
    if builder is None:
        raise ValueError(f"Unknown proposal type: {proposal_type!r}")
    draft = builder(audit)
    draft["draft_built_at"] = datetime.now(timezone.utc).isoformat()
    return draft


# ── Helpers ───────────────────────────────────────────────────────────────────

def _awb(audit: Dict[str, Any]) -> str:
    return audit.get("awb") or audit.get("tracking_no") or audit.get("dhl_awb") or ""


def _doc_no(audit: Dict[str, Any]) -> str:
    return audit.get("doc_no") or audit.get("batch_id") or ""


def _batch_output_path(audit: Dict[str, Any], filename: str) -> Optional[str]:
    """Return full path string if the file exists, else None."""
    batch_id = audit.get("batch_id") or ""
    if not batch_id or not filename:
        return None
    p = _OUTPUTS / batch_id / filename
    return str(p) if p.exists() else None


def _attachment_if_exists(
    audit: Dict[str, Any],
    field: str,
    label: str,
) -> Optional[Dict[str, str]]:
    """
    Return {"label": label, "path": str} if the file named in audit[field] exists.
    Returns None if field is missing or file does not exist.
    """
    filename = audit.get(field) or ""
    path = _batch_output_path(audit, filename)
    if path:
        return {"label": label, "path": path}
    return None


def _wrap_html(body_text: str) -> str:
    return f"<pre style='font-family:sans-serif'>{body_text}</pre>"


# ── Draft builders ────────────────────────────────────────────────────────────

def _build_dhl_followup(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    subject = f"Re: DSK — AWB {awb}" if awb else "Re: DSK broker notification status"
    body = (
        "Szanowni Państwo,\n\n"
        f"Uprzejmie prosimy o potwierdzenie statusu powiadomienia brokera (DSK) "
        f"dla przesyłki AWB: {awb}.\n\n"
        "Prosimy o niezwłoczną odpowiedź.\n\n"
        "Z poważaniem,\nEstrella Jewels\nimport@estrellajewels.eu"
    )
    return {
        "to":          format_to(DHL_TO),
        "cc":          format_cc(INTERNAL_CC),
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": [],
    }


def _build_agency_followup(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    dec = audit.get("clearance_decision") or {}
    agency_primary = dec.get("agency_email") or primary(AGENCY_TO)
    subject = f"SAD/ZC429 — AWB {awb}" if awb else "SAD — prośba o aktualizację statusu"
    body = (
        "Szanowni Państwo,\n\n"
        f"Uprzejmie prosimy o potwierdzenie statusu odprawy celnej "
        f"dla przesyłki AWB: {awb}.\n\n"
        "Czy SAD/ZC429 został już wystawiony? Prosimy o przesłanie kopii.\n\n"
        "Z poważaniem,\nEstrella Jewels\nimport@estrellajewels.eu"
    )
    return {
        "to":          agency_primary,
        "cc":          format_cc(AGENCY_CC + INTERNAL_CC),
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": [],
    }


def _build_dhl_dsk_transfer(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    subject = f"DSK — AWB {awb}" if awb else "DSK broker notification"
    body = (
        "Szanowni Państwo,\n\n"
        f"W załączeniu przesyłamy dokument DSK (powiadomienie brokera celnego) "
        f"dla przesyłki AWB: {awb}.\n\n"
        "Prosimy o potwierdzenie odbioru.\n\n"
        "Z poważaniem,\nEstrella Jewels\nimport@estrellajewels.eu"
    )
    attachments: List[Dict[str, str]] = []
    dsk_att = _attachment_if_exists(audit, "dsk_filename", "DSK")
    if dsk_att:
        attachments.append(dsk_att)
    return {
        "to":          format_to(DHL_TO),
        "cc":          format_cc(INTERNAL_CC),
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": attachments,
    }


def _build_carrier_description_reply(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    carrier = (audit.get("carrier") or "DHL").upper()
    if carrier == "FEDEX":
        to_addr = "pl-import@fedex.com"
    else:
        to_addr = format_to(DHL_TO)
    subject = f"Opis towarów — AWB {awb}" if awb else "Opis towarów do odprawy celnej"
    body = (
        "Szanowni Państwo,\n\n"
        f"W odpowiedzi na Państwa zapytanie dotyczące przesyłki AWB: {awb}, "
        "w załączeniu przesyłamy szczegółowy opis towarów w języku polskim "
        "wraz z dokumentami handlowymi.\n\n"
        "Z poważaniem,\nEstrella Jewels\nimport@estrellajewels.eu"
    )
    attachments: List[Dict[str, str]] = []
    desc_att = _attachment_if_exists(audit, "polish_desc_filename", "Polish description")
    if desc_att:
        attachments.append(desc_att)
    for inv_field in ("invoice_filename", "invoice_pdf"):
        inv_att = _attachment_if_exists(audit, inv_field, "Invoice")
        if inv_att:
            attachments.append(inv_att)
            break
    return {
        "to":          to_addr,
        "cc":          format_cc(INTERNAL_CC),
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": attachments,
    }


def _build_agency_clearance_email(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    dec = audit.get("clearance_decision") or {}
    agency_primary = dec.get("agency_email") or primary(AGENCY_TO)
    subject = f"Odprawa celna — AWB {awb}" if awb else "Zlecenie odprawy celnej"
    body = (
        "Szanowni Państwo,\n\n"
        f"Zlecamy odprawę celną przesyłki AWB: {awb}.\n\n"
        "W załączeniu:\n"
        "- Faktura handlowa (Commercial Invoice)\n"
        "- List przewozowy (AWB)\n"
        "- Opis towarów w języku polskim\n"
        "- Dokument DSK (powiadomienie brokera celnego)\n\n"
        "Prosimy o potwierdzenie przyjęcia zlecenia.\n\n"
        "Z poważaniem,\nEstrella Jewels\nimport@estrellajewels.eu"
    )
    attachments: List[Dict[str, str]] = []
    for field, label in [
        ("invoice_filename", "Invoice"),
        ("invoice_pdf", "Invoice"),
        ("awb_filename", "AWB"),
        ("polish_desc_filename", "Polish description"),
        ("dsk_filename", "DSK"),
    ]:
        att = _attachment_if_exists(audit, field, label)
        if att:
            attachments.append(att)
    # Combine: agency primary TO, agency CC + Ganther + internal CC
    ganther_cc = ["ciagarlak@ganther.com.pl"]
    cc_list = AGENCY_CC + ganther_cc + INTERNAL_CC
    return {
        "to":          agency_primary,
        "cc":          format_cc(cc_list),
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": attachments,
    }


def _build_tracking_lookup(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tracking lookup task — NOT an email.

    channel=cowork means this is a Cowork/manual task, not an outbound message.
    to/cc are intentionally empty — queue_email must never be called for this type.
    The draft contains the lookup instruction so the dashboard can render it clearly.
    """
    awb     = _awb(audit)
    carrier = (audit.get("carrier") or "DHL").upper()
    tr      = audit.get("tracking") or {}
    tracking_url = tr.get("tracking_url", "")
    if not tracking_url:
        from ..services.tracking_service import _dhl_tracking_url, _fedex_tracking_url
        tracking_url = (
            _fedex_tracking_url(awb) if carrier == "FEDEX"
            else _dhl_tracking_url(awb)
        )
    return {
        "to":          "",         # intentionally empty — this is NOT an email
        "cc":          "",
        "subject":     f"Tracking lookup: {carrier} AWB {awb}",
        "body_text":   (
            f"Fetch latest status from public {carrier} tracking page.\n\n"
            f"AWB: {awb}\n"
            f"Tracking URL: {tracking_url}\n\n"
            "Report result via POST /api/v1/tracking/{batch_id}/update"
        ),
        "body_html":   "",
        "attachments": [],
        # Cowork-specific fields (not used by email sender)
        "channel":     "cowork",
        "awb":         awb,
        "carrier":     carrier,
        "tracking_url": tracking_url,
        "instruction": f"Fetch latest status from public {carrier} tracking page",
    }


def _build_duty_payment_followup(audit: Dict[str, Any]) -> Dict[str, Any]:
    awb = _awb(audit)
    pln = audit.get("duty_amount_pln")
    pln_str = f"{pln} PLN" if pln else "kwota nieznana"
    subject = (
        f"Potwierdzenie płatności cła — AWB {awb}" if awb
        else "Potwierdzenie płatności cła"
    )
    body = (
        "Prośba o potwierdzenie płatności cła.\n\n"
        f"Przesyłka AWB: {awb}\n"
        f"Kwota do opłacenia: {pln_str}\n\n"
        "Czy płatność została dokonana? Prosimy o potwierdzenie.\n\n"
        "Pozdrawiam,\nimport@estrellajewels.eu"
    )
    return {
        "to":          "account@estrellajewels.eu",
        "cc":          "import@estrellajewels.eu",
        "subject":     subject,
        "body_text":   body,
        "body_html":   _wrap_html(body),
        "attachments": [],
    }

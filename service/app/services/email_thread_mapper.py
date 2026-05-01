"""
Email Evidence V2 — thread mapper.

Pure helpers:
  - normalise_subject(s): strip Re:/Fwd:/[ticket] wrappers
  - extract_awb(subject, body, attachments): find AWB via regex + master index
  - classify_direction(from_addr): incoming|outgoing
  - classify_event_type(message): one of dhl_request | our_dhl_reply | dhl_documents
                                       | agency_forward | agency_sad_reply
                                       | dhl_invoice | agency_invoice | other

Reuses TRUSTED_SENDERS and _ATTACH_TYPE_HINTS from dhl_email_monitor (single
source of truth for sender identity and attachment classification).

Read-only. Does not mutate any input.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Reuse the canonical sender registry + attachment hints
try:
    from dhl_email_monitor import TRUSTED_SENDERS, _classify_attachment  # type: ignore
except Exception:
    TRUSTED_SENDERS = {"dhl": [], "agency": [], "ganther": [], "internal": [], "fedex": []}
    def _classify_attachment(filename: str) -> str:  # type: ignore
        return "other"


# ── Subject normalisation ───────────────────────────────────────────────────

_RE_PREFIX = re.compile(r"^\s*(?:re|fwd|fw|odp|tr|pd)\s*:\s*", re.IGNORECASE)
_RE_TICKET = re.compile(r"\[(?:ticket|case|ref|tkt)[^\]]*\]\s*", re.IGNORECASE)
_RE_BRACKET_TAGS = re.compile(r"^\[[^\]]{1,40}\]\s*")


def normalise_subject(subject: str) -> str:
    """Strip Re:/Fwd:/ticket wrappers; collapse whitespace; lowercase."""
    if not subject:
        return ""
    s = subject.strip()
    # Strip repeated Re:/Fwd: prefixes
    for _ in range(8):
        s2 = _RE_PREFIX.sub("", s)
        if s2 == s:
            break
        s = s2
    # Strip [Ticket #1234] wrappers
    s = _RE_TICKET.sub("", s)
    s = _RE_BRACKET_TAGS.sub("", s)
    return re.sub(r"\s+", " ", s).strip().lower()


# ── AWB extraction ──────────────────────────────────────────────────────────

# DHL/UPS/FedEx-style AWB: 10-12 digits possibly with spaces every 4 chars
_RE_AWB = re.compile(r"\b(\d{10,12})\b")
# Estrella invoice number patterns (EJL/26-27/100 or EJL-26-27-100)
_RE_INVOICE = re.compile(r"\b(EJL[/\-]\d{2}[/\-]\d{2}[/\-]\d{2,4})\b", re.IGNORECASE)
# MRN (Polish customs movement reference number) — 18 chars, e.g. 26PL44302D00A1J5R7
_RE_MRN = re.compile(r"\b(\d{2}PL\d{4,12}[A-Z0-9]{6,12})\b")
# DHL ticket reference
_RE_TICKET_NO = re.compile(r"\b(?:ticket|case|tkt)[^\w]?(\d{5,12})\b", re.IGNORECASE)


def extract_identifiers(subject: str, body: str) -> Dict[str, Any]:
    """Pull every identifier we can find. Used to map an email to an AWB."""
    text = f"{subject or ''}\n{body or ''}"
    out: Dict[str, Any] = {
        "awb_candidates":   sorted({m for m in _RE_AWB.findall(text)}),
        "invoice_numbers":  sorted({m for m in _RE_INVOICE.findall(text)}),
        "mrn":              (_RE_MRN.search(text).group(1) if _RE_MRN.search(text) else None),
        "dhl_ticket":       (_RE_TICKET_NO.search(text).group(1) if _RE_TICKET_NO.search(text) else None),
    }
    return out


def extract_awb(
    subject: str,
    body: str,
    attachments: Iterable[Any] = (),
    *,
    candidate_awbs: Iterable[str] = (),
    invoice_to_awb: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Resolve an AWB from any combination of subject/body/attachments.

    `candidate_awbs` constrains matching to active shipments (the worker passes
    its set so spurious 10-digit numbers don't false-match).
    `invoice_to_awb` maps EJL/.../... → awb (from master index by_invoice_no).
    """
    ids = extract_identifiers(subject, body)
    candidates = set(map(str, candidate_awbs or []))

    # Direct AWB match — preferred
    for awb in ids["awb_candidates"]:
        if not candidates or awb in candidates:
            return awb

    # Attachment filenames
    for att in attachments or []:
        name = att.get("filename") if isinstance(att, dict) else getattr(att, "filename", "")
        for awb in _RE_AWB.findall(name or ""):
            if not candidates or awb in candidates:
                return awb

    # Invoice → AWB via master index
    if invoice_to_awb:
        for inv in ids["invoice_numbers"]:
            awb = invoice_to_awb.get(inv) or invoice_to_awb.get(inv.upper())
            if awb:
                return awb

    return None


# ── Direction ──────────────────────────────────────────────────────────────

INTERNAL_EMAIL_HINTS = (
    "import@estrellajewels.eu",
    "info@estrellajewels.eu",
    "account@estrellajewels.eu",
    "amit@estrellajewels.eu",
    "@estrellajewels.eu",
    "@estrellajewels.com",
)


def classify_direction(from_addr: str) -> str:
    if not from_addr:
        return "incoming"
    a = from_addr.lower()
    return "outgoing" if any(h in a for h in INTERNAL_EMAIL_HINTS) else "incoming"


# ── Sender role ────────────────────────────────────────────────────────────

def classify_sender_role(from_addr: str) -> str:
    """Return dhl|agency|ganther|internal|fedex|external."""
    a = (from_addr or "").lower()
    for role, patterns in (TRUSTED_SENDERS or {}).items():
        for p in patterns:
            if p.lower() in a:
                return role
    return "external"


# ── Event type ─────────────────────────────────────────────────────────────

_INVOICE_KEYWORDS = ("invoice", "faktur", "rachunek", "service invoice", "vat invoice")
_DSK_DOCUMENT_TYPES = {"dsk", "sad", "pzc", "duty"}
_DHL_REQUEST_TOKENS = ("cesja", "request", "podstawienie", "dokumentacj", "tłumaczeni", "opis tow", "broker", "agencj")


def _has_attachment_of_types(attachments: Iterable[Any], types: set[str]) -> bool:
    for att in attachments or []:
        t = att.get("document_type") if isinstance(att, dict) else getattr(att, "document_type", "")
        name = att.get("filename") if isinstance(att, dict) else getattr(att, "filename", "")
        if not t and name:
            t = _classify_attachment(name)
        if t and t in types:
            return True
    return False


def _has_invoice_attachment(attachments: Iterable[Any]) -> bool:
    return _has_attachment_of_types(attachments, {"invoice"})


def classify_event_type(
    *,
    direction: str,
    sender_role: str,
    subject: str,
    body: str,
    attachments: Iterable[Any] = (),
    to_addresses: Iterable[str] = (),
) -> str:
    """
    Returns one of: dhl_request | our_dhl_reply | dhl_documents | agency_forward
                   | agency_sad_reply | dhl_invoice | agency_invoice | other
    """
    s = (subject or "").lower()
    b = (body or "").lower()
    text = s + "\n" + b

    has_dsk_docs   = _has_attachment_of_types(attachments, _DSK_DOCUMENT_TYPES)
    has_invoice    = _has_invoice_attachment(attachments)
    has_invoice_kw = any(k in text for k in _INVOICE_KEYWORDS)
    is_invoice     = has_invoice or has_invoice_kw

    # Outgoing
    if direction == "outgoing":
        recipients = " ".join((a or "").lower() for a in (to_addresses or []))
        if "dhl.com" in recipients:
            return "our_dhl_reply"
        if "acspedycja.pl" in recipients or "ganther.com.pl" in recipients:
            return "agency_forward"
        return "other"

    # Incoming
    if sender_role == "dhl":
        if is_invoice and not has_dsk_docs:
            return "dhl_invoice"
        if has_dsk_docs:
            return "dhl_documents"
        if any(t in text for t in _DHL_REQUEST_TOKENS):
            return "dhl_request"
        # Default DHL incoming with no attachments → request
        return "dhl_request"

    if sender_role in ("agency", "ganther"):
        if is_invoice and not has_dsk_docs:
            return "agency_invoice"
        if has_dsk_docs:
            return "agency_sad_reply"
        return "agency_sad_reply"   # agency response with no attachments still informational

    return "other"

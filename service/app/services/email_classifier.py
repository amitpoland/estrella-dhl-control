"""
email_classifier.py — Email Classification Engine
===================================================
Classifies inbound emails into customs clearance event types based on:
  - sender address
  - subject line
  - body keywords
  - attachment filenames

Output schema:
{
  "type":         str,   # email type (see EMAIL_TYPES below)
  "carrier":      str,   # DHL | FEDEX | BOTH | UNKNOWN
  "awb":          str | None,
  "mrn":          str | None,
  "pln_amount":   float | None,
  "confidence":   str,   # high | medium | low
  "matched_rule": str,
  "sub_events":   list,  # additional signals detected
  "warnings":     list,  # routing gaps, unknown senders, etc.
}

EMAIL_TYPES:
  dhl_arrival        — DHL shipment arrived at customs warehouse
  dhl_cesja_fwd      — DHL forwarded cesja form to ACS
  zc429_notification — ACS WinSADMS ZC429 automated notification (MRN in attachment)
  acs_pzc            — ACS issued PZC + duty notice to Estrella
  ganther_duty       — Ganther duty payment request (PLN amount)
  ganther_payment    — Ganther payment confirmation ("płaci się")
  ganther_pzc        — Ganther clearance notification / PZC relay
  ganther_invoice    — Ganther service invoice (FV / Faktura VAT)
  fedex_arrival      — FedEx shipment arrival + cesja form
  fedex_cesja_ack    — FedEx auto-acknowledgment of cesja submission
  fedex_dsk          — FedEx DSK issued to Ganther
  acs_vat_statement  — ACS monthly VAT statement (billing — not clearance)
  vat_deferment_gap  — Ganther VAT deferment warning
  fca_complication   — FCA incoterms complication flag
  unknown_clearance  — Trusted sender but type unclassified
  do_not_trigger     — Known non-clearance sender (ignore)
  unknown_sender     — Sender not in trusted list (flag for review)
"""
from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Sender classification (from intelligence_parser) ──────────────────────────

_TRUSTED_CLEARANCE = {
    "piotr@acspedycja.pl",
    "logistyka@acspedycja.pl",
    "roman@acspedycja.pl",
    "adrian@acspedycja.pl",
    "michal@acspedycja.pl",
    "odprawacelna@dhl.com",
    "administracja_centralna@dhl.com",
    "ganther.com.pl",
    "jaworska@ganther.com.pl",
    "krzysztof.suchodola@ganther.com.pl",
    "pl-import@fedex.com",
}

_TRUSTED_NOTIFICATION = {
    "no-reply@acspedycja.pl",
}

_DO_NOT_TRIGGER = {
    "biuro@acspedycja.pl",
    "accounts@gjlindia.com",
    "dataRWA@fedex.com",
    "datarwa@fedex.com",
    "poland@fedex.com",
    "zaneta.nagat@fedex.com",
    "dyszynska@abf-biurorachunkowe.pl",
    "kaushal@estrellajewelsllp.com",
    "jigar.p@simplex-hurtownia.pl",
    "iza@simplex-hurtownia.pl",
}

_INTERNAL = {
    "import@estrellajewels.eu",
    "tejal@estrellajewels.com",
    "account@estrellajewels.eu",
    "amit@estrellajewels.eu",
    "jyoti@estrellajewels.com",
    "info@estrellajewels.eu",
}

_DHL_SENDERS   = {"odprawacelna@dhl.com", "administracja_centralna@dhl.com"}

# DHL Warsaw customs agency notification mailbox. Distinct from the
# per-shipment customs agent (odprawacelna@dhl.com) because plwawecs is
# a one-way notification address (ZC429 completion). It is added to
# trusted senders below; classification routes it through the
# zc429_completion branch only.
_DHL_AGENCY_NOTIFICATION = {"plwawecs@dhl.com"}
_TRUSTED_CLEARANCE = _TRUSTED_CLEARANCE | _DHL_AGENCY_NOTIFICATION
_FEDEX_SENDERS = {"pl-import@fedex.com"}
_ACS_SENDERS   = {"piotr@acspedycja.pl", "logistyka@acspedycja.pl", "roman@acspedycja.pl",
                  "adrian@acspedycja.pl", "michal@acspedycja.pl", "no-reply@acspedycja.pl"}
_GANTHER_DOMAINS = {"ganther.com.pl"}

# ── Regex patterns ─────────────────────────────────────────────────────────────

_AWB_DHL_RE    = re.compile(r'\b(\d{10})\b')
_AWB_FEDEX_RE  = re.compile(r'\b(\d{12})\b')
# Matches T# tickets with OR without surrounding brackets.
# DHL's original notification arrives WITHOUT brackets (e.g. "T#1WA2605130000195 - ...").
# Reply threads and internal forwards may add brackets (e.g. "[T#1WA2605130000195]").
# Both forms must be accepted to avoid silent ticket extraction failure.
_DHL_TICKET_RE = re.compile(r'\[?T#([A-Z0-9]+)\]?')
_MRN_RE        = re.compile(r'(?:ZC429_)?([A-Z0-9]{18,20})(?:_\d+_PL)?', re.IGNORECASE)
_PLN_RE        = re.compile(r'(\d[\d\s,.]+)\s*PLN', re.IGNORECASE)
_ZC429_FILE_RE = re.compile(r'ZC429_([A-Z0-9]+)_\d+_PL\.pdf', re.IGNORECASE)
_GANTHER_INV_RE= re.compile(r'(?:FV|faktura)[_\s-]*(\d+)[_/](\d+)', re.IGNORECASE)

# ── Keyword sets ───────────────────────────────────────────────────────────────

_PAYMENT_KEYWORDS = frozenset([
    "płaci się", "placi sie", "dzieki, płaci się", "dzięki płaci się",
    "zapłata odebrana", "płatność odebrana",
])
_VAT_DEFERMENT_KEYWORDS = frozenset([
    "vat deferment", "odroczenie vat", "brak pozwolenia",
    "pozwolenie wygasło", "no permission for vat",
    "vat zostanie zapłacony przed",
])
_CLEARANCE_IN_PROGRESS = frozenset([
    "przesyłka w odprawie", "in clearance", "w odprawie celnej",
])
_FCA_KEYWORDS = frozenset(["fca", "free carrier"])
_PZC_KEYWORDS = frozenset(["pzc", "potwierdzenie zgłoszenia"])
_DSK_KEYWORDS = frozenset(["dsk", "cession", "cesja"])
_CESJA_ACK_KEYWORDS = frozenset(["potwierdzenie cesji", "cesja potwierdzona", "auto-ack", "confirmation of cession"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _norm_sender(sender: str) -> str:
    return sender.strip().lower()


def _is_ganther(sender: str) -> bool:
    s = _norm_sender(sender)
    return s in _GANTHER_DOMAINS or s.endswith("@ganther.com.pl")


def _extract_awb(text: str, carrier: str) -> Optional[str]:
    if carrier == "FEDEX":
        m = _AWB_FEDEX_RE.search(text)
        if m:
            return m.group(1)
    m = _AWB_DHL_RE.search(text)
    return m.group(1) if m else None


def _extract_mrn_from_attachments(attachments: List[str]) -> Optional[str]:
    for fname in attachments:
        m = _ZC429_FILE_RE.match(fname)
        if m:
            return m.group(1)
    return None


def _extract_pln(text: str) -> Optional[float]:
    matches = _PLN_RE.findall(text)
    if not matches:
        return None
    try:
        raw = matches[0].replace(" ", "").replace(",", ".")
        return float(raw)
    except (ValueError, IndexError):
        return None


def _text_contains_any(text_lower: str, keywords: frozenset) -> bool:
    return any(kw in text_lower for kw in keywords)


# ── Core classifier ────────────────────────────────────────────────────────────

def classify_email(
    sender: str,
    subject: str = "",
    body: str = "",
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Classify an inbound email and return structured classification.

    Args:
        sender:      FROM address (e.g. "odprawacelna@dhl.com")
        subject:     Email subject line
        body:        Email body text (plain text preferred)
        attachments: List of attachment filenames

    Returns:
        Classification dict. See module docstring for schema.
    """
    if attachments is None:
        attachments = []

    s_norm   = _norm_sender(sender)
    sub_low  = subject.lower()
    body_low = body.lower()
    combined = f"{sub_low} {body_low}"

    result: Dict[str, Any] = {
        "type":         "unknown_sender",
        "carrier":      "UNKNOWN",
        "awb":          None,
        "mrn":          None,
        "pln_amount":   None,
        "dhl_ticket":   None,
        "confidence":   "low",
        "matched_rule": "no_match",
        "sub_events":   [],
        "warnings":     [],
    }

    # ── 0. Sender classification ───────────────────────────────────────────────
    if s_norm in _DO_NOT_TRIGGER:
        result["type"]         = "do_not_trigger"
        result["confidence"]   = "high"
        result["matched_rule"] = "do_not_trigger_list"
        # ACS VAT statement — distinguish for routing
        if s_norm == "biuro@acspedycja.pl":
            result["type"]    = "acs_vat_statement"
            result["carrier"] = "DHL"
        return result

    if s_norm in _INTERNAL:
        result["type"]         = "internal"
        result["confidence"]   = "high"
        result["matched_rule"] = "internal_sender"
        return result

    # ── 0a. DHL WAW agency ZC429 completion notification ─────────────────────
    # This branch fires BEFORE the generic carrier classification so the
    # plwawecs notification never gets misrouted as a normal DHL customs
    # request. The detector lives in dhl_zc429_intake (single source of
    # truth) — we only ask "does this match?" here.
    if s_norm in _DHL_AGENCY_NOTIFICATION:
        try:
            from .dhl_zc429_intake import is_dhl_zc429_email
            is_zc429 = is_dhl_zc429_email(
                sender=sender, subject=subject, body=body)
        except Exception:
            is_zc429 = False
        result["carrier"] = "DHL"
        if is_zc429:
            result["type"]         = "zc429_completion"
            result["sender_role"]  = "dhl_agency_notification"
            result["matched_rule"] = "dhl_waw_zc429_completion"
            result["confidence"]   = "high"
            awb = _extract_awb(f"{subject} {body}", "DHL")
            result["awb"]          = awb
        else:
            # plwawecs@dhl.com sent something that isn't a ZC429 — flag
            # for review without triggering any side effects.
            result["type"]         = "dhl_agency_other"
            result["sender_role"]  = "dhl_agency_notification"
            result["matched_rule"] = "dhl_waw_unknown_template"
            result["confidence"]   = "low"
        return result

    # Determine carrier from sender
    if s_norm in _DHL_SENDERS:
        result["carrier"] = "DHL"
    elif s_norm in _FEDEX_SENDERS:
        result["carrier"] = "FEDEX"
    elif s_norm in _ACS_SENDERS:
        result["carrier"] = "DHL"  # ACS only handles DHL
    elif _is_ganther(s_norm):
        result["carrier"] = "BOTH"
    elif s_norm not in _TRUSTED_CLEARANCE and s_norm not in _TRUSTED_NOTIFICATION:
        result["warnings"].append(f"unknown_sender:{sender}")

    # ── 1. DHL senders ────────────────────────────────────────────────────────
    if s_norm == "odprawacelna@dhl.com":
        awb = _extract_awb(f"{subject} {body}", "DHL")
        ticket_m = _DHL_TICKET_RE.search(subject)
        result["awb"]        = awb
        result["dhl_ticket"] = f"T#{ticket_m.group(1)}" if ticket_m else None
        result["confidence"] = "high"

        body_kw = combined
        if "cesja" in body_kw or "fwd" in sub_low or "forward" in sub_low:
            result["type"]         = "dhl_cesja_fwd"
            result["matched_rule"] = "dhl_cesja_forward_detected"
        else:
            result["type"]         = "dhl_arrival"
            result["matched_rule"] = "dhl_odprawacelna_arrival"
        return result

    # ── 2. ZC429 AIS notification ─────────────────────────────────────────────
    if s_norm == "no-reply@acspedycja.pl":
        mrn = _extract_mrn_from_attachments(attachments)
        if not mrn:
            # Try to extract from subject
            m = _MRN_RE.search(subject)
            mrn = m.group(1) if m else None
        awb = _extract_awb(f"{subject} {body}", "DHL")
        result.update({
            "type":         "zc429_notification",
            "carrier":      "DHL",
            "mrn":          mrn,
            "awb":          awb,
            "confidence":   "high" if mrn else "medium",
            "matched_rule": "acs_ais_automated",
        })
        return result

    # ── 3. ACS clearance agents ───────────────────────────────────────────────
    if s_norm in _ACS_SENDERS:
        awb = _extract_awb(f"{subject} {body}", "DHL")
        pln = _extract_pln(body)
        result["awb"]        = awb
        result["pln_amount"] = pln
        result["confidence"] = "high"

        if "pzc" in combined or "potwierdzenie zgłoszenia" in combined:
            result["type"]         = "acs_pzc"
            result["matched_rule"] = "acs_pzc_keyword"
        elif "zestawienie" in combined or "vat statement" in combined:
            result["type"]         = "acs_vat_statement"
            result["matched_rule"] = "acs_vat_statement"
        elif pln:
            result["type"]         = "acs_pzc"
            result["matched_rule"] = "acs_pln_amount"
            result["sub_events"].append("duty_amount_detected")
        else:
            result["type"]         = "unknown_clearance"
            result["matched_rule"] = "acs_trusted_unclassified"
        return result

    # ── 4. Ganther emails ──────────────────────────────────────────────────────
    if _is_ganther(s_norm):
        awb = _extract_awb(f"{subject} {body}", "DHL")
        pln = _extract_pln(body)
        result["awb"]        = awb
        result["pln_amount"] = pln
        result["carrier"]    = "BOTH"
        result["confidence"] = "high"

        # Check VAT deferment (highest priority — must alert immediately)
        if _text_contains_any(body_low, _VAT_DEFERMENT_KEYWORDS):
            result["type"]         = "vat_deferment_gap"
            result["matched_rule"] = "ganther_vat_deferment"
            result["confidence"]   = "high"
            result["warnings"].append("vat_deferment_issue_detected")
            return result

        # Payment confirmation
        if _text_contains_any(combined, _PAYMENT_KEYWORDS):
            result["type"]         = "ganther_payment"
            result["matched_rule"] = "ganther_payment_phrase"
            return result

        # FCA complication
        if _text_contains_any(combined, _FCA_KEYWORDS) and "transport" in combined:
            result["type"]         = "fca_complication"
            result["matched_rule"] = "ganther_fca_keyword"
            result["sub_events"].append("transport_invoice_required")
            return result

        # PZC relay
        if _text_contains_any(combined, _PZC_KEYWORDS):
            result["type"]         = "ganther_pzc"
            result["matched_rule"] = "ganther_pzc_keyword"
            return result

        # Clearance in progress
        if _text_contains_any(combined, _CLEARANCE_IN_PROGRESS):
            result["type"]         = "ganther_pzc"
            result["matched_rule"] = "ganther_clearance_in_progress"
            result["sub_events"].append("clearance_started")
            return result

        # Ganther invoice (FV / Faktura VAT)
        inv_m = _GANTHER_INV_RE.search(combined)
        if inv_m:
            result["type"]         = "ganther_invoice"
            result["matched_rule"] = "ganther_invoice_number"
            result["sub_events"].append(f"invoice:{inv_m.group(0)}")
            return result

        # Duty notice (has PLN amount)
        if pln:
            result["type"]         = "ganther_duty"
            result["matched_rule"] = "ganther_pln_amount"

            # Routing gap check: if not "ganther duty to account@"
            # NOTE: This check is indicative only — actual routing validation
            # requires email header parsing (not just body)
            if "account@estrellajewels.eu" not in body_low:
                result["sub_events"].append("routing_check_required")
                result["warnings"].append("account_not_mentioned_in_body")
            return result

        result["type"]         = "unknown_clearance"
        result["matched_rule"] = "ganther_trusted_unclassified"
        return result

    # ── 5. FedEx emails ───────────────────────────────────────────────────────
    if s_norm in _FEDEX_SENDERS:
        awb = _extract_awb(f"{subject} {body}", "FEDEX")
        result["awb"]        = awb
        result["carrier"]    = "FEDEX"
        result["confidence"] = "high"

        # Cesja auto-acknowledgment
        if _text_contains_any(combined, _CESJA_ACK_KEYWORDS):
            result["type"]         = "fedex_cesja_ack"
            result["matched_rule"] = "fedex_cesja_ack_keyword"
            return result

        # DSK issued
        if _text_contains_any(combined, _DSK_KEYWORDS):
            result["type"]         = "fedex_dsk"
            result["matched_rule"] = "fedex_dsk_keyword"
            return result

        # Cesja form (has cesja attachment or cesja keyword)
        cesja_attach = any("cesja" in f.lower() or "cession" in f.lower() or "authorization" in f.lower()
                           for f in attachments)
        if "cesja" in combined or cesja_attach:
            result["type"]         = "fedex_arrival"
            result["matched_rule"] = "fedex_cesja_form"
            result["sub_events"].append("cesja_form_attached" if cesja_attach else "cesja_keyword")
            return result

        # General FedEx arrival
        if awb:
            result["type"]         = "fedex_arrival"
            result["matched_rule"] = "fedex_awb_detected"
        else:
            result["type"]         = "unknown_clearance"
            result["matched_rule"] = "fedex_trusted_unclassified"
        return result

    # ── 6. Unknown trusted / untrusted ────────────────────────────────────────
    if s_norm in _TRUSTED_CLEARANCE:
        awb = _extract_awb(f"{subject} {body}", "BOTH")
        result.update({
            "type":         "unknown_clearance",
            "awb":          awb,
            "confidence":   "medium",
            "matched_rule": "trusted_sender_unclassified",
        })
    else:
        result["warnings"].append(f"unknown_sender:{sender}")
        result["type"]         = "unknown_sender"
        result["matched_rule"] = "not_in_trusted_list"

    return result


# ── Email type → timeline event mapping ──────────────────────────────────────

# Singleton events: once present in the timeline for a batch, never add again.
# These represent one-time state transitions per clearance lifecycle.
_SINGLETON_EVENTS: frozenset = frozenset({
    "carrier_arrived",
    "cesja_received",
    "zc429_received",
    "payment_confirmed",
})

# Maps classify_email() type → canonical timeline event name.
# Types absent from this map produce no timeline event.
_EMAIL_TYPE_TO_EVENT: Dict[str, str] = {
    "dhl_arrival":         "carrier_arrived",
    "dhl_cesja_fwd":       "cesja_received",
    "zc429_notification":  "zc429_received",
    "acs_pzc":             "pzc_received",
    "ganther_duty":        "duty_note_received",
    "ganther_payment":     "payment_confirmed",
    "ganther_pzc":         "ganther_pzc_sent",
    "ganther_invoice":     "ganther_invoice_received",
    "fedex_arrival":       "carrier_arrived",
    "fedex_cesja_ack":     "cesja_submitted",
    "fedex_dsk":           "dsk_received",
    "vat_deferment_gap":   "vat_deferment_flagged",
    "fca_complication":    "fca_complication_flagged",
    # Intentionally absent (no timeline mapping):
    #   do_not_trigger, internal, acs_vat_statement,
    #   unknown_sender, unknown_clearance
}


def process_incoming_email(
    email_obj: Dict[str, Any],
    audit_path: "Any",                  # Path — avoid circular import at module level
) -> "tuple":
    """
    Classify an inbound email and—if it maps to a clearance event—append it
    safely to the audit timeline.

    This is the main ingestion entry point for the email → timeline bridge.
    Safe to call repeatedly; duplicate events are suppressed:
      - Singleton events (carrier_arrived, zc429_received, etc.) are never
        added a second time regardless of email_id.
      - Repeatable events are deduplicated by email_id if one is provided.

    Args:
        email_obj:  Dict with keys:
                      sender      (str, required)
                      subject     (str, optional)
                      body        (str, optional)
                      attachments (list[str], optional)
                      email_id    (str, optional — unique message ID)
                      received_at (str, optional — ISO timestamp)
        audit_path: Path to the batch's audit.json (Path or str).

    Returns:
        (classification: dict, timeline_event_name: str | None)
        timeline_event_name is None when:
          - email type has no timeline mapping
          - event was suppressed (singleton already present, or duplicate email_id)
          - audit file not found
    """
    import json as _json
    from pathlib import Path as _Path
    from ..core import timeline as tl

    cls = classify_email(
        sender=email_obj.get("sender", ""),
        subject=email_obj.get("subject", ""),
        body=email_obj.get("body", ""),
        attachments=email_obj.get("attachments") or [],
    )

    email_type = cls.get("type", "")
    event_name = _EMAIL_TYPE_TO_EVENT.get(email_type)
    if not event_name:
        return cls, None

    email_id   = email_obj.get("email_id") or ""
    audit_path = _Path(audit_path)

    if not audit_path.exists():
        log.warning("[email_classifier] process_incoming_email: audit not found at %s", audit_path)
        return cls, None

    # ── Deduplication check ───────────────────────────────────────────────────
    try:
        existing        = _json.loads(audit_path.read_text(encoding="utf-8"))
        existing_tl: list = existing.get("timeline") or []
    except Exception as exc:
        log.warning("[email_classifier] Could not read audit for dedup check: %s", exc)
        return cls, None

    for entry in existing_tl:
        if entry.get("event") == event_name:
            if event_name in _SINGLETON_EVENTS:
                log.debug(
                    "[email_classifier] Singleton %r already on timeline — suppressed",
                    event_name,
                )
                return cls, None
            if email_id and (entry.get("detail") or {}).get("email_id") == email_id:
                log.debug(
                    "[email_classifier] email_id %r already on timeline — suppressed",
                    email_id,
                )
                return cls, None

    # ── Build event detail ────────────────────────────────────────────────────
    detail: Dict[str, Any] = {
        "email_type":   email_type,
        "sender":       email_obj.get("sender", ""),
        "confidence":   cls.get("confidence", ""),
        "matched_rule": cls.get("matched_rule", ""),
    }
    if email_id:
        detail["email_id"] = email_id
    if cls.get("awb"):
        detail["awb"] = cls["awb"]
    if cls.get("mrn"):
        detail["mrn"] = cls["mrn"]
    if cls.get("pln_amount"):
        detail["pln_amount"] = cls["pln_amount"]
    if email_obj.get("received_at"):
        detail["received_at"] = email_obj["received_at"]
    if cls.get("warnings"):
        detail["email_warnings"] = cls["warnings"]

    # ── Append to timeline (atomic, non-fatal) ────────────────────────────────
    try:
        tl.log_event(
            audit_path=audit_path,
            event=event_name,
            trigger_source="email_classifier",
            actor=email_obj.get("sender", "unknown"),
            detail=detail,
        )
        log.info(
            "[email_classifier] Ingested: type=%s → event=%s batch=%s",
            email_type, event_name, audit_path.parent.name,
        )
    except Exception as exc:
        log.error("[email_classifier] Failed to log timeline event: %s", exc)
        return cls, None

    return cls, event_name


# ── Batch classification (for testing / admin review) ─────────────────────────

def classify_batch(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Classify a list of email dicts.

    Each input dict should have keys: sender, subject, body, attachments (optional).
    Returns list of classification results with input echo.
    """
    results = []
    for email in emails:
        cls = classify_email(
            sender=email.get("sender", ""),
            subject=email.get("subject", ""),
            body=email.get("body", ""),
            attachments=email.get("attachments", []),
        )
        results.append({
            "input":  {k: v for k, v in email.items() if k != "body"},
            "result": cls,
        })
    return results

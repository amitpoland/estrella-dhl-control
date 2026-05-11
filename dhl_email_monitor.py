"""
dhl_email_monitor.py — DHL Customs Email Monitor for Estrella PZ system.

Scans Zoho Mail inbox for incoming DHL Agencja Celna emails and extracts
the DHL ticket number and AWB (air waybill number) from the subject line.

This module is designed to be called from the FastAPI service via
/api/v1/dhl/scan-inbox — it does NOT send any email replies.

Detection rules:
    DHL_SENDER          : odprawacelna@dhl.com
    DHL_SUBJECT_KEYWORDS: "Agencja Celna DHL", "przesyłka numer:"
    DHL_BODY_KEYWORDS   : "Tłumaczenie zawartości przesyłki",
                          "Określenie rodzaju odprawy celnej"

Subject format (example):
    [T#1WA2604140000123] - Agencja Celna DHL - przesyłka numer: 3283625844
"""
from __future__ import annotations

import json
import sys
if sys.platform != "win32":
    import fcntl as _fcntl
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Intent detection keyword lists ───────────────────────────────────────────

BROKER_KEYWORDS_PL: list[str] = [
    "powiadomienie brokera",
    "pełnomocnictwo",
    "agencja celna zewnętrzna",
    "broker celny",
    "zlecenie odprawy",
    "odprawa przez agencję",
    "DSK",
    "zlecenie realizacji usługi",
]

TRANSLATION_KEYWORDS_PL: list[str] = [
    "tłumaczenie zawartości",
    "opis towaru",
    "określenie rodzaju",
    "co to za towar",
    "z jakiego materiału",
    "do czego służy",
    "proszę o opis",
    "wymagany opis",
    "zawartość przesyłki",
]

# Max expected keyword matches used for confidence normalization
_BROKER_MAX_EXPECTED      = 3
_TRANSLATION_MAX_EXPECTED = 3

# ── Detection constants ───────────────────────────────────────────────────────

DHL_SENDER = "odprawacelna@dhl.com"

DHL_SUBJECT_KEYWORDS: list[str] = [
    "Agencja Celna DHL",
    "przesyłka numer:",
]

DHL_BODY_KEYWORDS: list[str] = [
    "Tłumaczenie zawartości przesyłki",
    "Określenie rodzaju odprawy celnej",
]

# ── Regex patterns ────────────────────────────────────────────────────────────

# Match T# ticket with OR without surrounding brackets: [T#1WA...] or T#1WA...
# DHL's original notification uses no brackets; reply/forward threads add them.
_TICKET_RE = re.compile(r'(?:\[)?T#([A-Z0-9]+)(?:\])?')
_AWB_RE    = re.compile(r'przesyłka numer:\s*(\d+)', re.IGNORECASE)

# Broader AWB patterns — used when scanning subject + body + attachments + forwarded mail.
# Order matters: more specific patterns first so we capture the strongest signal.
_AWB_PATTERNS = [
    re.compile(r'przesyłka\s+numer[:\s]+(\d{8,12})', re.IGNORECASE),
    re.compile(r'\bAWB[:\s#-]+(\d{8,12})\b',         re.IGNORECASE),
    re.compile(r'\b(?:tracking|nr|no\.?)[:\s#-]+(\d{10,12})\b', re.IGNORECASE),
    re.compile(r'\b(\d{10})\b'),                     # bare 10-digit (DHL)
    re.compile(r'\b(\d{12})\b'),                     # bare 12-digit (FedEx)
]


# ── Trusted sender registry ───────────────────────────────────────────────────
# Substring match on sender address (case-insensitive). Each role has multiple
# candidates so forwarded mail and aliases all classify correctly.

TRUSTED_SENDERS: dict[str, list[str]] = {
    "dhl": [
        "odprawacelna@dhl.com",
        "administracja_centralna@dhl.com",
        "plwawecs@dhl.com",
        "@dhl.com",                 # any other DHL alias
    ],
    "agency": [
        "piotr@acspedycja.pl",
        "biuro@acspedycja.pl",
        "roman@acspedycja.pl",
        "logistyka@acspedycja.pl",
        "no-reply@acspedycja.pl",
        "@acspedycja.pl",           # any acspedycja alias
    ],
    "ganther": [
        "ciagarlak@ganther.com.pl",
        "@ganther.com.pl",
    ],
    "internal": [
        "@estrellajewels.eu",
        "@estrellajewels.com",
    ],
    "fedex": [
        "pl-import@fedex.com",
        "@fedex.com",
    ],
}

# Subject/body keyword hints — case-insensitive substring matches.
# Used as supplementary signal; AWB match alone is sufficient.
# Stems are used (e.g. "odpraw" matches odprawa/odprawy/odprawę) to handle
# Polish noun/verb inflection in forwards and replies.
_DHL_KEYWORDS = [
    "agencja celna",
    "przesyłk",          # przesyłka / przesyłki / przesyłce
    "odpraw",            # odprawa / odprawy / odprawie / odprawę
    "celn",              # celna / celnej / celne (covers "odprawy celnej")
    "tłumaczeni",        # tłumaczenie / tłumaczenia
    "określeni",         # określenie / określenia
    "opis tow",          # opis towaru / opis towarów
    "dsk",
    "broker",
    "agencja",
]


# Attachment classifier hints — used for `attachments[].type` in scan results.
_ATTACH_TYPE_HINTS = [
    ("invoice",       ["invoice", "faktur", "ejl-"]),
    ("awb",           ["awb"]),
    ("dsk",           ["dsk_", "dsk-", "dsk."]),
    ("sad",           ["sad", "zc429", "zc-429", "pzc"]),
    ("duty",          ["nota", "duty", "cło"]),
    ("payment",       ["payment", "wpłat", "potwierdz"]),
    ("description",   ["polish_desc", "opis", "translation"]),
]


def _classify_attachment(filename: str) -> str:
    """Return one of: invoice / awb / dsk / sad / duty / payment / description / other."""
    if not filename:
        return "other"
    fn = filename.lower()
    for type_name, keywords in _ATTACH_TYPE_HINTS:
        if any(k in fn for k in keywords):
            return type_name
    return "other"


def _classify_sender(sender: str) -> str:
    """Return role: dhl / agency / ganther / internal / fedex / unknown."""
    if not sender:
        return "unknown"
    s = sender.lower()
    for role, patterns in TRUSTED_SENDERS.items():
        if any(p.lower() in s for p in patterns):
            return role
    return "unknown"


def _extract_awbs_from_text(text: str) -> list[str]:
    """Return list of AWB-like digit sequences found anywhere in `text`."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _AWB_PATTERNS:
        for m in pattern.finditer(text):
            awb = m.group(1) if m.groups() else m.group(0)
            awb = re.sub(r"\D", "", awb)
            if awb and awb not in seen and 8 <= len(awb) <= 12:
                seen.add(awb)
                found.append(awb)
    return found


def match_email_to_shipment(
    email: dict,
    target_awb: Optional[str] = None,
) -> dict:
    """
    Decide whether an email relates to a customs/shipment workflow.

    Matches on ANY of:
      - sender role is in TRUSTED_SENDERS (dhl/agency/ganther/internal/fedex)
      - subject contains AWB or DHL/customs keyword
      - body contains AWB
      - any attachment filename contains AWB
      - forwarded body contains AWB (quoted-reply / Fwd:)

    Args:
        email:      Dict with keys subject, from, body, attachments, received_at.
        target_awb: If provided, ONLY match this specific AWB. Otherwise match
                    any AWB-shaped digit sequence.

    Returns:
        dict with:
            matched          : bool
            matched_fields   : list[str]   ("sender", "subject", "body",
                                            "attachment", "forwarded_body")
            matched_reason   : str         (human-readable summary)
            awb              : str | None  (best-confidence AWB)
            ticket           : str | None  (T# token if present)
            detected_type    : str         (broker_notification / translation /
                                            agency_reply / internal_forward /
                                            carrier_status / unknown)
            sender_role      : str         (dhl / agency / ganther / internal /
                                            fedex / unknown)
            confidence       : float       (0.0–1.0)
            attachments      : list[dict]  (filename + classified type)
    """
    subject = (email.get("subject") or "").strip()
    body    = (email.get("body")    or email.get("body_snippet") or "").strip()
    sender  = (email.get("from")    or email.get("fromAddress")  or "").strip()
    attachments_in = email.get("attachments") or []

    sender_role = _classify_sender(sender)

    # AWB candidates from each surface, deduped.
    subj_awbs    = _extract_awbs_from_text(subject)
    body_awbs    = _extract_awbs_from_text(body)
    attach_awbs: list[str] = []
    attach_out: list[dict] = []
    for a in attachments_in:
        fn = a.get("filename") or a.get("name") or ""
        attach_awbs.extend(_extract_awbs_from_text(fn))
        attach_out.append({"filename": fn, "type": _classify_attachment(fn)})

    # Forwarded-body AWBs: lines that look like quoted-reply headers
    fwd_awbs: list[str] = []
    if body:
        # Common forwarded-message markers
        if re.search(r"-{2,}\s*Forwarded message|^From:|^Wiadomość przekazana", body, re.MULTILINE):
            fwd_awbs = body_awbs  # already covered, but flag the source

    matched_fields: list[str] = []
    if sender_role != "unknown":
        matched_fields.append("sender")

    # Determine if this email matches based on AWB or keyword presence
    if target_awb:
        target_clean = re.sub(r"\D", "", str(target_awb))
        in_subj   = target_clean in re.sub(r"\D", "", subject)
        in_body   = target_clean in re.sub(r"\D", "", body)
        in_attach = any(target_clean in re.sub(r"\D", "", (a.get("filename") or "")) for a in attachments_in)
        if in_subj:   matched_fields.append("subject")
        if in_body:   matched_fields.append("body")
        if in_attach: matched_fields.append("attachment")
        if fwd_awbs and target_clean in fwd_awbs:
            matched_fields.append("forwarded_body")
        is_match = bool(in_subj or in_body or in_attach)
        awb_out  = target_clean if is_match else None
    else:
        # No specific AWB — match if AWB-like digits are anywhere OR
        # if sender is trusted AND subject/body contains a customs keyword
        if subj_awbs:    matched_fields.append("subject")
        if body_awbs:    matched_fields.append("body")
        if attach_awbs:  matched_fields.append("attachment")
        any_awb = subj_awbs + body_awbs + attach_awbs
        keyword_hit = any(
            kw.lower() in (subject + " " + body).lower() for kw in _DHL_KEYWORDS
        )
        is_match = bool(any_awb) or (sender_role != "unknown" and keyword_hit)
        awb_out  = any_awb[0] if any_awb else None

    ticket = _extract_ticket(subject) or _extract_ticket(body)

    # Detected type (best-effort routing hint)
    intent = detect_request_intent(subject, body)
    detected_type = intent.get("request_type", "unknown")
    if detected_type == "unknown":
        if sender_role == "agency":
            detected_type = "agency_reply"
        elif sender_role == "internal":
            detected_type = "internal_forward"
        elif sender_role in ("dhl", "fedex", "ganther"):
            detected_type = "carrier_status"

    confidence = 0.0
    if is_match:
        # Higher confidence with more match surfaces and a known sender role
        confidence = min(1.0, 0.3 + 0.2 * len([f for f in matched_fields if f != "sender"])
                              + (0.2 if sender_role != "unknown" else 0.0))

    reason_parts: list[str] = []
    if "subject"        in matched_fields: reason_parts.append("AWB in subject")
    if "body"           in matched_fields: reason_parts.append("AWB in body")
    if "attachment"     in matched_fields: reason_parts.append("AWB in attachment filename")
    if "forwarded_body" in matched_fields: reason_parts.append("AWB in forwarded body")
    if "sender" in matched_fields and not (set(matched_fields) - {"sender"}):
        reason_parts.append(f"sender is trusted ({sender_role})")
    matched_reason = "; ".join(reason_parts) or "no match"

    return {
        "matched":        is_match,
        "matched_fields": matched_fields,
        "matched_reason": matched_reason,
        "awb":            awb_out,
        "ticket":         ticket,
        "detected_type":  detected_type,
        "sender_role":    sender_role,
        "confidence":     round(confidence, 2),
        "attachments":    attach_out,
    }


# ── Zoho Mail constants (from email_service.py / service .env) ────────────────

ZOHO_ACCOUNT_ID = "2261204000000002002"
ZOHO_INBOX_FOLDER_ID = "2261204000000002014"   # Inbox folder ID for info@estrellajewels.eu

# Default API base — Zoho mailbox lives in the India data centre. The .eu and
# .com regions both reject this account's tokens with 401 INVALID_OAUTHTOKEN.
# Empirically verified against the live mailbox account 2261204000000002002.
ZOHO_MAIL_API_BASE_DEFAULT = "https://zmail.zoho.in/api"


# ── Search-key helpers ────────────────────────────────────────────────────────
#
# Zoho's .in region rejects bare-keyword searchKey values with HTTP 400
# "Invalid Input / Index 1 out of bounds for length 1". The .in region requires
# the field-prefixed form (e.g. ``entire:1012178215``). The .eu region accepts
# both, so the prefixed form is safe across regions.
#
# These helpers exist to (a) prevent accidental reintroduction of the bare
# form and (b) give tests an importable target.

def _build_search_key(term: Any) -> str:
    """
    Wrap *term* in the ``entire:`` prefix that Zoho's .in region requires.

    Raises ValueError if *term* is empty/None or non-string.
    """
    if term is None:
        raise ValueError("search term must not be None")
    s = str(term).strip()
    if not s:
        raise ValueError("search term must not be empty")
    return f"entire:{s}"


def _assert_search_key_valid(key: str, context: str = "") -> None:
    """
    Guard against bare-keyword search keys.

    Zoho's .in region returns HTTP 400 on bare keywords. A valid key must
    contain a ``:`` separating field and value (e.g. ``entire:1234567890``,
    ``subject:foo``).
    """
    if not key or ":" not in str(key):
        log.warning(
            "INVALID searchKey detected (bare keyword) context=%s key=%r",
            context, key,
        )
        raise ValueError(
            f"INVALID searchKey {key!r} — must be field:value form "
            f"(context={context!r})"
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_ticket(subject: str) -> Optional[str]:
    """Extract DHL ticket token from subject, e.g. 'T#1WA2604140000123'."""
    m = _TICKET_RE.search(subject)
    return f"T#{m.group(1)}" if m else None


def _extract_awb(subject: str) -> Optional[str]:
    """Extract AWB number from subject line."""
    m = _AWB_RE.search(subject)
    return m.group(1) if m else None


def _subject_matches(subject: str) -> bool:
    """Return True if the subject line looks like a DHL customs notification."""
    s_lower = subject.lower()
    return all(kw.lower() in s_lower for kw in DHL_SUBJECT_KEYWORDS)


def _body_matches(body: str) -> bool:
    """Return True if body contains at least one DHL body keyword."""
    b_lower = body.lower()
    return any(kw.lower() in b_lower for kw in DHL_BODY_KEYWORDS)


def _routing_hint(subject: str, body: str) -> str:
    """
    Cheap heuristic to pre-classify clearance type from the email content.
    The authoritative routing is done in dhl_clearance_handler.py using the
    actual invoice CIF value — this is just a UI hint.
    """
    combined = (subject + " " + body).lower()
    if "tłumaczenie" in combined or "opis towarów" in combined:
        return "dhl_clearance"
    if "broker" in combined or "agencja" in combined:
        return "broker_clearance"
    return "unknown"


def detect_request_intent(subject: str, body: str) -> dict:
    """
    Detect the DHL email's actual request type from content keywords.

    This is the PRIMARY routing signal. Value-based routing is a fallback only.

    Returns
    -------
    dict with keys:
        request_type            : "broker_notification" | "translation" | "clarification" | "unknown"
        broker_keywords_found   : list of matched broker keywords
        translation_keywords_found : list of matched translation keywords
        confidence              : float 0.0–1.0
        routing_decision        : "generate_dsk" | "generate_description" | "manual_review"
        routing_basis           : "email_content" (always; value is never the basis here)
    """
    combined = (subject + " " + body).lower()

    broker_found: list[str] = []
    for kw in BROKER_KEYWORDS_PL:
        if kw.lower() in combined:
            broker_found.append(kw)

    translation_found: list[str] = []
    for kw in TRANSLATION_KEYWORDS_PL:
        if kw.lower() in combined:
            translation_found.append(kw)

    has_broker      = len(broker_found) > 0
    has_translation = len(translation_found) > 0

    if has_broker and not has_translation:
        request_type     = "broker_notification"
        routing_decision = "generate_dsk"
        raw_confidence   = len(broker_found) / _BROKER_MAX_EXPECTED
    elif has_translation and not has_broker:
        request_type     = "translation"
        routing_decision = "generate_description"
        raw_confidence   = len(translation_found) / _TRANSLATION_MAX_EXPECTED
    elif has_broker and has_translation:
        # Both present — ambiguous, lean on whichever has more matches
        if len(broker_found) >= len(translation_found):
            request_type     = "broker_notification"
            routing_decision = "generate_dsk"
        else:
            request_type     = "translation"
            routing_decision = "generate_description"
        raw_confidence = 0.4   # ambiguous signal
    else:
        request_type     = "unknown"
        routing_decision = "manual_review"
        raw_confidence   = 0.0

    confidence = min(1.0, raw_confidence)

    return {
        "request_type":               request_type,
        "broker_keywords_found":      broker_found,
        "translation_keywords_found": translation_found,
        "confidence":                 round(confidence, 3),
        "routing_decision":           routing_decision,
        "routing_basis":              "email_content",
    }


# ── Public API ────────────────────────────────────────────────────────────────

def scan_for_dhl_customs_emails(
    zoho_account_id: str = ZOHO_ACCOUNT_ID,
    zoho_folder_id: str = ZOHO_INBOX_FOLDER_ID,
    limit: int = 50,
    zoho_api_token: Optional[str] = None,
    target_awb: Optional[str] = None,
    api_base: str = "https://mail.zoho.eu/api",
    token_provider: Optional[Any] = None,
    dhl_ticket: Optional[str] = None,
) -> dict:
    """
    Scan Zoho Mail inbox for shipment-related correspondence.

    Modes:
      - "awb_targeted"  : when target_awb is given, search Zoho mail for that
                          AWB across subject/body and apply the permissive
                          matcher to each result.
      - "broad_recent"  : when no AWB is given, fetch the most recent N messages
                          and apply the matcher.

    Returns
    -------
    dict with:
        scanned       : int   — number of messages actually inspected
        matched       : int   — number of messages that matched
        emails        : list  — matched email records
        scan_method   : str   — "rest_api_search" | "rest_api_recent" |
                                "no_credentials"
        search_mode   : str   — "awb_targeted" | "broad_recent"
        query_used    : str   — exact search query / endpoint used
        awb_used      : str | None
    """
    awb_clean = re.sub(r"\D", "", str(target_awb)) if target_awb else None
    search_mode = "awb_targeted" if awb_clean else "broad_recent"

    # Resolve a usable token. Caller may supply:
    #   - token_provider() -> str (for refresh-token flow; preferred)
    #   - zoho_api_token   (static; bootstrap-only)
    # else env fallback (legacy CLI use).
    def _get_token() -> str:
        if token_provider is not None:
            return token_provider()
        return zoho_api_token or os.environ.get("ZOHO_MAIL_API_TOKEN", "")

    try:
        token = _get_token()
    except Exception as exc:  # pragma: no cover — provider raises ZohoAuthError
        return {
            "scanned":     0,
            "matched":     0,
            "emails":      [],
            "scan_method": "auth_error",
            "search_mode": search_mode,
            "query_used":  "",
            "awb_used":    awb_clean,
            "error":       str(exc),
        }

    if not token:
        return {
            "scanned":     0,
            "matched":     0,
            "emails":      [],
            "scan_method": "no_credentials",
            "search_mode": search_mode,
            "query_used":  "",
            "awb_used":    awb_clean,
        }

    raw, scanned, query_used, scan_method = _fetch_messages(
        account_id=zoho_account_id,
        folder_id=zoho_folder_id,
        limit=limit,
        token=token,
        target_awb=awb_clean,
        api_base=api_base,
        dhl_ticket=dhl_ticket,
    )

    # NOTE: the historical Sent-folder fallback is intentionally GONE.
    # The ``entire:`` searchKey form spans Inbox, Sent, Archive, and any
    # custom folders in a single Zoho call, so the dedicated Sent scan is
    # both redundant and (on the .in region) impossible — the
    # /folders/{id}/messages endpoint that the old fallback used returns
    # HTTP 404 INVALID_METHOD on .in.

    matched: list[dict] = []
    for msg in raw:
        # Hydrate body for matching (REST list endpoint usually omits body)
        body = msg.get("body") or _fetch_body_snippet(
            zoho_account_id, str(msg.get("messageId", "")), token, max_chars=8000,
            api_base=api_base,
        )
        sender = msg.get("fromAddress", "") or msg.get("from", "")
        subject = msg.get("subject", "")
        attachments = msg.get("attachments") or []

        decision = match_email_to_shipment(
            email={
                "subject":     subject,
                "body":        body,
                "from":        sender,
                "attachments": attachments,
            },
            target_awb=awb_clean,
        )
        if not decision["matched"]:
            continue

        matched.append({
            "message_id":           str(msg.get("messageId", "")),
            "thread_id":            str(msg.get("threadId", "")),
            "subject":              subject,
            "from":                 sender,
            "received_at":          _ms_to_iso(msg.get("receivedTime")),
            "dhl_ticket":           decision["ticket"],
            "awb":                  decision["awb"],
            "raw_subject":          subject,
            "body_snippet":         body[:500] if body else "",
            "requires_translation": "tłumaczenie zawartości" in (body or "").lower(),
            "routing_hint":         _routing_hint(subject, body),
            "intent":               detect_request_intent(subject, body),
            "matched_fields":       decision["matched_fields"],
            "matched_reason":       decision["matched_reason"],
            "detected_type":        decision["detected_type"],
            "sender_role":          decision["sender_role"],
            "confidence":           decision["confidence"],
            "attachments":          decision["attachments"],
        })

    return {
        "scanned":     scanned,
        "matched":     len(matched),
        "emails":      matched,
        "scan_method": scan_method,
        "search_mode": search_mode,
        "query_used":  query_used,
        "awb_used":    awb_clean,
    }


def _fetch_messages(
    account_id: str,
    folder_id: str,
    limit: int,
    token: str,
    target_awb: Optional[str],
    api_base: str = "https://mail.zoho.eu/api",
    dhl_ticket: Optional[str] = None,
) -> tuple[list[dict], int, str, str]:
    """
    Fetch raw messages from Zoho Mail.

    When target_awb is provided, searches Zoho for that AWB.
    Uses Zoho's ``entire:<term>`` searchKey — the bare term (no prefix) is
    rejected by the Zoho .in region with HTTP 400 "Invalid Input / Index 1
    out of bounds for length 1". The ``entire:`` form searches across all
    indexed fields (subject + body + headers) and is the documented
    cross-region syntax. The legacy ``newentire::`` prefix from earlier code
    is also rejected by the .in region — do not reintroduce it.

    Falls back to a ticket search (T#...) if the AWB search returns nothing
    and a dhl_ticket is known.

    Returns: (messages, scanned_count, query_used, scan_method)
    """
    try:
        import requests as _req
    except ImportError:
        return [], 0, "", "no_credentials"

    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Accept": "application/json",
    }
    base = api_base.rstrip("/")

    def _do_search(search_key: str) -> list[dict]:
        """Issue a single Zoho search; return [] on failure (warn on 400/INVALID)."""
        try:
            _assert_search_key_valid(search_key, context="_fetch_messages")
        except ValueError:
            return []
        url = f"{base}/accounts/{account_id}/messages/search"
        params = {
            "searchKey": search_key,
            "start":     1,
            "limit":     min(limit, 200),
        }
        try:
            resp = _req.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 400 or "INVALID_METHOD" in (resp.text or ""):
                log.warning(
                    "[zoho] HTTP %s on searchKey=%r body=%r",
                    resp.status_code, search_key, (resp.text or "")[:300],
                )
            resp.raise_for_status()
            return resp.json().get("data", []) or []
        except Exception as exc:
            log.debug("[zoho] search failed key=%r: %s", search_key, exc)
            return []

    if target_awb:
        # 1. Primary search — entire:<awb>
        primary_key = _build_search_key(target_awb)
        messages = _do_search(primary_key)
        scan_method = "rest_api_search"
        query_used  = f"searchKey={primary_key}"

        # 2. Spaced-AWB secondary search — Zoho indexes some AWBs split into
        #    two 4+6 digit chunks, especially when the original mail rendered
        #    them with a thin space. Try once if the primary returned 0.
        if not messages and len(target_awb) >= 10 and target_awb.isdigit():
            spaced = f"{target_awb[:4]} {target_awb[4:]}"
            spaced_key = _build_search_key(spaced)
            spaced_messages = _do_search(spaced_key)
            if spaced_messages:
                messages = spaced_messages
                scan_method = "rest_api_search_spaced"
                query_used  = f"searchKey={spaced_key} (spaced)"

        # 3. Ticket fallback — entire:<ticket_core> after stripping T#/# prefix.
        if not messages and dhl_ticket:
            ticket_clean = dhl_ticket.lstrip("T#").lstrip("#").strip()
            if ticket_clean:
                ticket_key = _build_search_key(ticket_clean)
                ticket_messages = _do_search(ticket_key)
                if ticket_messages:
                    messages    = ticket_messages
                    scan_method = "rest_api_search_ticket"
                    query_used  = f"searchKey={ticket_key} (ticket fallback)"

        return messages, len(messages), query_used, scan_method
    else:
        # Broad scan — list recent messages from a folder.
        # Zoho's .in region requires the /messages endpoint (NOT
        # /folders/{id}/messages — that path returns HTTP 404 INVALID_METHOD)
        # and a `fields` query parameter listing the columns to return.
        url = f"{base}/accounts/{account_id}/messages"
        params = {
            "folderId":  folder_id,
            "limit":     min(limit, 200),
            "start":     1,
            "sortorder": "false",
            # Zoho rejects /messages without `fields`. Request the columns
            # the matcher needs downstream.
            "fields":    "messageId,subject,fromAddress,toAddress,"
                         "receivedTime,summary,folderId,threadId,"
                         "hasAttachment",
        }
        scan_method = "rest_api_recent"
        query_used  = f"folderId={folder_id} limit={params['limit']}"

        try:
            resp = _req.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 400 or "INVALID_METHOD" in (resp.text or ""):
                log.warning(
                    "[zoho] broad scan HTTP %s body=%r",
                    resp.status_code, (resp.text or "")[:300],
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[zoho] broad scan failed: %s", exc)
            return [], 0, query_used, scan_method

        messages = data.get("data", []) or []
        return messages, len(messages), query_used, scan_method


def _get_sent_folder_id(
    account_id: str,
    token: str,
    api_base: str = "https://mail.zoho.eu/api",
) -> Optional[str]:
    """
    Fetch the list of folders for account_id and return the folder ID whose
    name is 'Sent' or 'Sent Items'.  Returns None if not found or on error.
    """
    try:
        import requests as _req
    except ImportError:
        return None

    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Accept": "application/json",
    }
    base = api_base.rstrip("/")
    url  = f"{base}/accounts/{account_id}/folders"
    try:
        resp = _req.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        folders = resp.json().get("data", []) or []
    except Exception:
        return None

    for f in folders:
        name = (f.get("folderName") or f.get("name") or "").strip()
        if name.lower() in ("sent", "sent items", "sent mail", "nadane", "wysłane"):
            fid = f.get("folderId") or f.get("id") or ""
            return str(fid) if fid else None
    return None


def _fetch_body_snippet(
    account_id: str,
    message_id: str,
    token: str,
    max_chars: int = 8000,
    api_base: str = "https://mail.zoho.eu/api",
) -> str:
    """Fetch plain-text body of a message (first `max_chars` chars)."""
    try:
        import requests as _req

        url = (
            f"{api_base.rstrip('/')}/accounts/{account_id}"
            f"/messages/{message_id}/content"
        )
        resp = _req.get(
            url,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"mimeType": "text/plain"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        body = data.get("data", {}).get("content", "")
        return body[:max_chars] if body else ""
    except Exception:
        return ""


def _ms_to_iso(ms_timestamp: Any) -> str:
    """Convert Zoho epoch-ms timestamp to ISO8601 string."""
    if not ms_timestamp:
        return datetime.now(timezone.utc).isoformat()
    try:
        ts = int(ms_timestamp) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _scan_via_mock_or_queue(
    account_id: str,
    folder_id: str,
    limit: int,
) -> list[dict]:
    """Deprecated; preserved for backwards compatibility with older imports."""
    return []


# ── AWB matcher ───────────────────────────────────────────────────────────────

def match_awb_to_batch(
    awb: str,
    storage_root: str,
) -> Optional[dict]:
    """
    Search all batch audit.json files for a matching AWB number.

    Searches:
        result["awb"]
        batch_meta["awb"]
        Any top-level string field containing the AWB digits

    Parameters
    ----------
    awb          : AWB number to search for (digits only, e.g. "3283625844")
    storage_root : Root storage directory (contains outputs/ and working/)

    Returns
    -------
    Batch audit dict if found, or None.
    """
    import glob
    import json

    awb_clean = re.sub(r"\s+", "", awb)

    search_patterns = [
        os.path.join(storage_root, "outputs", "*", "audit.json"),
        os.path.join(storage_root, "working", "*", "audit.json"),
    ]

    candidates: list[str] = []
    for pat in search_patterns:
        candidates.extend(glob.glob(pat))

    # Sort newest first (by mtime)
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    for audit_path in candidates:
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                audit = json.load(f)
        except Exception:
            continue

        if _audit_contains_awb(audit, awb_clean):
            audit["_audit_path"] = audit_path
            return audit

    return None


def _audit_contains_awb(audit: dict, awb_clean: str) -> bool:
    """Return True if the audit dict contains awb_clean in any relevant field."""
    def _normalize(v: str) -> str:
        return re.sub(r"\s+", "", str(v))

    # Direct fields
    for key in ("awb", "batch_awb"):
        v = audit.get(key)
        if v and _normalize(v) == awb_clean:
            return True

    # Nested in result / batch_meta
    for section_key in ("result", "batch_meta"):
        section = audit.get(section_key, {}) or {}
        if isinstance(section, dict):
            for key in ("awb",):
                v = section.get(key)
                if v and _normalize(v) == awb_clean:
                    return True

    # Scan all top-level string values
    for v in audit.values():
        if isinstance(v, str) and _normalize(v) == awb_clean:
            return True

    return False


# ── Conversation log (DHL ticket as key) ─────────────────────────────────────

_CONV_LOG_FILENAME = "dhl_conversation_log.json"
_CONV_LOG_LOCK_SUFFIX = ".lock"


def load_conversation_log(storage_root: str) -> dict:
    """
    Load dhl_conversation_log.json keyed by DHL ticket.

    Returns empty dict if file does not exist or is corrupt.
    Thread-safe: uses a file lock.
    """
    log_path = Path(storage_root) / _CONV_LOG_FILENAME
    if not log_path.exists():
        return {}
    lock_path = log_path.with_suffix(_CONV_LOG_LOCK_SUFFIX)
    try:
        with open(lock_path, "w") as lock_f:
            if sys.platform != "win32":
                _fcntl.flock(lock_f, _fcntl.LOCK_SH)
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
            finally:
                if sys.platform != "win32":
                    _fcntl.flock(lock_f, _fcntl.LOCK_UN)
    except Exception:
        return {}


def record_email_in_conversation(
    dhl_ticket: str,
    email: dict,
    action_taken: dict,
    storage_root: str,
) -> None:
    """
    Append this email + action to the conversation log for dhl_ticket.

    Creates a new entry if this is the first email for the ticket.
    Thread-safe: uses an exclusive file lock for the write.

    Conversation log structure per ticket::

        {
            "dhl_ticket":     "T#1WA2604140000123",
            "awb":            "3283625844",
            "batch_id":       "...",
            "first_received": "ISO8601",
            "last_received":  "ISO8601",
            "email_count":    2,
            "emails": [
                {"message_id": ..., "received_at": ...,
                 "intent": {...}, "response_version": 1},
                ...
            ],
            "responses": [
                {"version": 1, "generated_at": ...,
                 "files": [...], "sent": false},
                ...
            ]
        }
    """
    if not dhl_ticket:
        return

    storage = Path(storage_root)
    storage.mkdir(parents=True, exist_ok=True)

    log_path  = storage / _CONV_LOG_FILENAME
    lock_path = log_path.with_suffix(_CONV_LOG_LOCK_SUFFIX)

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with open(lock_path, "w") as lock_f:
            if sys.platform != "win32":
                _fcntl.flock(lock_f, _fcntl.LOCK_EX)
            try:
                # Load existing log
                if log_path.exists():
                    try:
                        log_data = json.loads(log_path.read_text(encoding="utf-8"))
                        if not isinstance(log_data, dict):
                            log_data = {}
                    except Exception:
                        log_data = {}
                else:
                    log_data = {}

                entry = log_data.get(dhl_ticket)
                if entry is None:
                    entry = {
                        "dhl_ticket":     dhl_ticket,
                        "awb":            email.get("awb", ""),
                        "batch_id":       action_taken.get("batch_id", ""),
                        "first_received": email.get("received_at", now_iso),
                        "last_received":  email.get("received_at", now_iso),
                        "email_count":    0,
                        "emails":         [],
                        "responses":      [],
                    }

                # Version = next response number
                version = len(entry["responses"]) + 1

                # Append the email record
                email_record = {
                    "message_id":       email.get("message_id", ""),
                    "received_at":      email.get("received_at", now_iso),
                    "intent":           email.get("intent", {}),
                    "response_version": version,
                }
                entry["emails"].append(email_record)

                # Collect files from action_taken
                files = []
                if action_taken.get("dsk") and action_taken["dsk"].get("output_path"):
                    files.append(action_taken["dsk"]["output_path"])
                if action_taken.get("polish_description") and action_taken["polish_description"].get("output_path"):
                    files.append(action_taken["polish_description"]["output_path"])

                # Append the response record
                response_record = {
                    "version":      version,
                    "generated_at": now_iso,
                    "action":       action_taken.get("action", ""),
                    "files":        files,
                    "sent":         False,
                }
                entry["responses"].append(response_record)

                # Update metadata
                entry["email_count"]   = len(entry["emails"])
                entry["last_received"] = email.get("received_at", now_iso)

                log_data[dhl_ticket] = entry

                # Atomic write
                tmp = log_path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(log_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(log_path)

            finally:
                if sys.platform != "win32":
                    _fcntl.flock(lock_f, _fcntl.LOCK_UN)
    except Exception:
        pass   # non-fatal — conversation log must never crash the handler


# ── Quick smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== DHL Email Monitor — self-test ===\n")

    # Test subject parsing
    test_subjects = [
        "[T#1WA2604140000123] - Agencja Celna DHL - przesyłka numer: 3283625844",
        "[T#2EU2604150000456] - Agencja Celna DHL - przesyłka numer: 1234567890",
        "Normal email — not DHL",
    ]

    for s in test_subjects:
        ticket  = _extract_ticket(s)
        awb     = _extract_awb(s)
        matches = _subject_matches(s)
        print(f"Subject : {s[:70]}")
        print(f"  match={matches}  ticket={ticket}  awb={awb}")
        print()

    # Test AWB normalization
    awb_variants = ["3283625844", "32 8362 5844", " 3283625844 "]
    for v in awb_variants:
        print(f"AWB '{v}' → clean='{re.sub(chr(32), '', v.strip())}'")

    print("\n=== Done ===")

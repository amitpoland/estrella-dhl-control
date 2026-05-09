"""
email_search_context.py — Multi-key identifier extraction for email discovery.

Builds the search context that the AI Bridge `email_scan` task uses. The
discovery engine MUST search across AWB + invoice numbers + DHL ticket +
sender domains, not AWB alone — that was an architectural bug surfaced when
real DHL/agency emails sometimes carry only an invoice reference in the body
or attachment filename.

Public API:
    build_email_search_context(audit: dict) -> dict
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── Canonical Estrella mailbox identity ──────────────────────────────────────
# ONE Zoho mailbox (account_id 2261204000000002002, login amit@estrellajewels.eu)
# with multiple sender identities / group + alias addresses routing to it.
# These are NOT separate accounts — search must treat To/Cc on any of these
# as matching this single mailbox context.

ESTRELLA_ACCOUNT_ID = "2261204000000002002"
ESTRELLA_LOGIN      = "amit@estrellajewels.eu"

ESTRELLA_RELATED_IDENTITIES: List[str] = [
    "amit@estrellajewels.eu",       # primary login
    "info@estrellajewels.eu",       # group alias
    "account@estrellajewels.eu",    # group alias
    "import@estrellajewels.eu",     # group alias
    "amit@estrellajewels.com",      # cross-domain alias
]


# ── Canonical sender / domain registry ────────────────────────────────────────
# Sourced from email_routing.py constants. Duplicated here intentionally to
# keep this module self-contained for the Cowork task payload.

_KNOWN_SENDERS: List[str] = [
    "odprawacelna@dhl.com",
    "administracja_centralna@dhl.com",
    "plwawecs@dhl.com",                      # DHL WAW ZC429 completion
    "no-reply@acspedycja.pl",
    "piotr@acspedycja.pl",
    "biuro@acspedycja.pl",
    "roman@acspedycja.pl",
    "ciagarlak@ganther.com.pl",
    "pl-import@fedex.com",
]

_KNOWN_DOMAINS: List[str] = [
    "dhl.com",
    "acspedycja.pl",
    "ganther.com.pl",
    "estrellajewels.eu",
    "estrellajewels.com",
    "fedex.com",
]

# Recurring Polish/English subject phrases worth folding into the search
# query as quoted strings. The matcher already handles substrings; these are
# extra signals for full-text search engines (Zoho `searchKey`, etc.).
_FIXED_SUBJECT_TERMS: List[str] = [
    "Agencja Celna DHL",
    "przesyłka numer",
    "odprawa celna",
    "DSK",
    "ZC429",
    "Powiadomienie o odebranym komunikacie",   # DHL WAW ZC429 subject
]


# ── Invoice-number extraction ─────────────────────────────────────────────────

_INVOICE_RE = re.compile(r"\bEJL[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{3,4}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{2}\b", re.IGNORECASE)
_INVOICE_RE_SHORT = re.compile(r"\bEJL[-/\s]\S+\b", re.IGNORECASE)
_NUMERIC_INVOICE_PREFIX = re.compile(r"^\s*(\d{2,4})\s+Invoice\s+", re.IGNORECASE)


def _extract_invoice_numbers(audit: Dict[str, Any]) -> List[str]:
    """
    Pull invoice references from every plausible audit location.

    Looks at:
      - audit['invoices']                  (list of metadata dicts or filename strings)
      - audit['invoice_files']             (legacy)
      - audit['inputs']['invoices']        (canonical upload list)
      - audit['dhl_precheck']['invoices']  (sometimes carries refs)
      - audit['invoice_totals']            (some structured totals carry invoice_no)
      - any filename string containing 'EJL-' / 'Invoice' / etc.
    Deduplicates case-insensitively, preserves first-seen order.
    """
    seen_lower: set[str] = set()
    out: List[str] = []

    def _add(s: Any) -> None:
        if not s:
            return
        v = str(s).strip()
        if not v:
            return
        key = v.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            out.append(v)

    def _scan_str(s: str) -> None:
        # Strict EJL pattern
        for m in _INVOICE_RE.finditer(s):
            _add(m.group(0))
        # Looser EJL- pattern (catches truncated forms in filenames)
        for m in _INVOICE_RE_SHORT.finditer(s):
            _add(m.group(0))
        # Numeric prefix like "1247 Invoice EJL-..."
        m = _NUMERIC_INVOICE_PREFIX.match(s)
        if m:
            _add(f"INV-{m.group(1)}")

    def _scan_any(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            _scan_str(value)
        elif isinstance(value, dict):
            # Look at common keys for an invoice number directly
            for k in ("invoice_no", "invoice_number", "filename", "name", "file"):
                if k in value:
                    _scan_any(value[k])
        elif isinstance(value, (list, tuple)):
            for item in value:
                _scan_any(item)

    # Scan known fields
    for key in ("invoices", "invoice_files"):
        _scan_any(audit.get(key))

    inputs = audit.get("inputs") or {}
    _scan_any(inputs.get("invoices"))

    precheck = audit.get("dhl_precheck") or {}
    _scan_any(precheck.get("invoices"))

    # invoice_totals sometimes has per-invoice rows
    it = audit.get("invoice_totals") or {}
    _scan_any(it.get("invoices"))
    _scan_any(it.get("by_invoice"))

    # PZ rows often have invoice_no
    for row in (audit.get("pz_rows") or []):
        _scan_any(row.get("invoice_no") if isinstance(row, dict) else None)

    # Agency package attachments are filenames (extras safety net)
    arp = audit.get("agency_reply_package") or {}
    _scan_any(arp.get("attachments"))

    return out


# ── DHL ticket / MRN ─────────────────────────────────────────────────────────

_TICKET_RE = re.compile(r"T#[A-Z0-9]+", re.IGNORECASE)


def _extract_dhl_ticket(audit: Dict[str, Any]) -> Optional[str]:
    """Find a DHL ticket string T#... anywhere in audit if present."""
    direct = audit.get("dhl_ticket") or (audit.get("dhl_email") or {}).get("ticket")
    if direct:
        return str(direct)
    # Fallback: scan strings
    for v in audit.values():
        if isinstance(v, str):
            m = _TICKET_RE.search(v)
            if m:
                return m.group(0)
    return None


def _extract_mrn(audit: Dict[str, Any]) -> Optional[str]:
    """Find a customs MRN if the audit has it."""
    cd = audit.get("customs_declaration") or {}
    return cd.get("mrn") or audit.get("mrn") or None


# ── Public builder ───────────────────────────────────────────────────────────

def build_email_search_context(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a multi-key search context for the AI Bridge `email_scan` task.

    Returns a dict with:
      awb              : str | None
      invoice_numbers  : list[str]
      dhl_ticket       : str | None
      mrn              : str | None
      known_senders    : list[str]
      known_domains    : list[str]
      search_terms     : list[str]   (all unique non-empty searchable identifiers)
    """
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
    )
    if awb:
        awb = str(awb).strip()

    invoices    = _extract_invoice_numbers(audit)
    dhl_ticket  = _extract_dhl_ticket(audit)
    mrn         = _extract_mrn(audit)

    # Build the unified search-terms list (dedup, preserve order)
    search_terms: List[str] = []
    seen: set[str] = set()
    def _push(v: Optional[str]) -> None:
        if not v:
            return
        s = str(v).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            search_terms.append(s)

    _push(awb)
    if awb and len(awb) >= 8:
        _push(awb[-8:])             # partial AWB for truncated subjects
    for inv in invoices:
        _push(inv)
    _push(dhl_ticket)
    _push(mrn)
    for term in _FIXED_SUBJECT_TERMS:
        _push(term)

    return {
        "awb":                awb,
        "invoice_numbers":    invoices,
        "dhl_ticket":         dhl_ticket,
        "mrn":                mrn,
        "known_senders":      list(_KNOWN_SENDERS),
        "known_domains":      list(_KNOWN_DOMAINS),
        "search_terms":       search_terms,
        "related_identities": list(ESTRELLA_RELATED_IDENTITIES),
        "target_account_id":  ESTRELLA_ACCOUNT_ID,
        "target_mailbox":     ESTRELLA_LOGIN,
    }

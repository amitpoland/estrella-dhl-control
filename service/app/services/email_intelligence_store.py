"""
email_intelligence_store.py — persistent email-scan intelligence layer.

Verified Cowork email scan results are stored once and reused by AWB,
invoice number, MRN, and DHL ticket so the system never has to re-scan
the same shipment.

Storage layout:
    storage/email_intelligence/
        master_email_map.json       — flat map record_id → record
        by_awb/<awb>.json           — one record per AWB (latest verified)
        by_invoice/<inv>.json       — index: list of awbs that mention this invoice
        by_mrn/<mrn>.json           — index: list of awbs that mention this MRN
        by_ticket/<ticket>.json     — index: list of awbs that mention this ticket

Each record:
    {
      awb, invoice_numbers, mrn, dhl_ticket,
      matched, confidence,
      threads, emails, derived_events,
      recommended_next_action, search_unreliable, manual_review_required,
      source, connector_used, account_id, mailbox,
      last_scanned_at, linked_batches
    }

Public API:
    save_email_scan_result(scan_results: dict, audit: dict) -> dict
    get_by_awb(awb)        -> record | None
    get_by_invoice(inv_no) -> list[record]
    get_by_mrn(mrn)        -> list[record]
    get_by_ticket(ticket)  -> list[record]
    find_existing_email_context(audit) -> record | None
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..utils.io import write_json_atomic


def _root() -> Path:
    r = settings.storage_root / "email_intelligence"
    for sub in ("by_awb", "by_invoice", "by_mrn", "by_ticket"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    return r


def _master_path() -> Path:
    return _root() / "master_email_map.json"


def _safe_key(s: str) -> str:
    """Make a string filesystem-safe for use as a filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s).strip())


def _load_master() -> Dict[str, Any]:
    p = _master_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_master(d: Dict[str, Any]) -> None:
    write_json_atomic(_master_path(), d)


def _read_index(sub: str, key: str) -> List[str]:
    p = _root() / sub / f"{_safe_key(key)}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("awbs", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _write_index(sub: str, key: str, awbs: List[str]) -> None:
    p = _root() / sub / f"{_safe_key(key)}.json"
    write_json_atomic(p, {"key": key, "awbs": sorted(set(awbs))})


# ── Public API ────────────────────────────────────────────────────────────────

def save_email_scan_result(
    scan_results: Dict[str, Any],
    audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Persist a normalized record from an email_scan result and update all
    indices. Returns the stored record.

    Indexed by AWB primarily. Invoice/MRN/ticket are secondary indexes
    pointing back to AWBs.
    """
    awb = (scan_results.get("awb") or "").strip()
    if not awb:
        # Nothing to index without an AWB
        return {}

    now_iso = datetime.now(timezone.utc).isoformat()
    by_awb_path = _root() / "by_awb" / f"{_safe_key(awb)}.json"

    # Merge with existing record if present (preserves linked_batches across scans)
    existing: Dict[str, Any] = {}
    if by_awb_path.exists():
        try:
            existing = json.loads(by_awb_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Pull every plausible identifier from the scan result
    invoice_numbers: List[str] = list(dict.fromkeys(
        (existing.get("invoice_numbers") or []) +
        ((scan_results.get("searched") or {}).get("invoice_numbers") or [])
    ))
    mrn        = scan_results.get("mrn_discovered") or scan_results.get("mrn") or existing.get("mrn")
    dhl_ticket = scan_results.get("dhl_ticket")    or existing.get("dhl_ticket")

    linked_batches = list(dict.fromkeys(
        (existing.get("linked_batches") or []) +
        ([audit.get("batch_id")] if (audit and audit.get("batch_id")) else [])
    ))

    # F6-FIX: deduplicate emails by stable message_id before storing.
    # Emails without a message_id are labeled "unverified" — they may be
    # duplicate representations of the same message from different search passes.
    _seen_msg_ids: set = set()
    _emails_deduped: List[Dict[str, Any]] = []
    for _em in (scan_results.get("emails", []) or []):
        _mid = (
            _em.get("message_id")
            or _em.get("messageId")
            or _em.get("id")
        )
        if _mid:
            if _mid in _seen_msg_ids:
                _em = {**_em, "dedup_status": "duplicate", "dedup_key": _mid}
            else:
                _seen_msg_ids.add(_mid)
                _em = {**_em, "dedup_status": "unique", "dedup_key": _mid}
        else:
            _em = {**_em, "dedup_status": "unverified"}
        _emails_deduped.append(_em)

    record: Dict[str, Any] = {
        "awb":                     awb,
        "invoice_numbers":         invoice_numbers,
        "mrn":                     mrn,
        "dhl_ticket":              dhl_ticket,
        "matched":                 int(scan_results.get("matched", 0) or 0),
        "confidence":              scan_results.get("confidence", ""),
        "threads":                 scan_results.get("threads", []) or [],
        "emails":                  _emails_deduped,
        "derived_events":          scan_results.get("derived_events", []) or [],
        "recommended_next_action": scan_results.get("recommended_next_action", ""),
        "search_unreliable":       bool(scan_results.get("search_unreliable", False)),
        "manual_review_required":  bool(scan_results.get("manual_review_required", False)),
        "connector_mismatch":      bool(scan_results.get("connector_mismatch", False)),
        "source":                  scan_results.get("source", "unknown"),
        "connector_used":          scan_results.get("connector_used", ""),
        "account_id":              scan_results.get("account_id", ""),
        "mailbox":                 scan_results.get("mailbox", ""),
        "last_scanned_at":         now_iso,
        "linked_batches":          linked_batches,
    }

    # Persist primary index
    write_json_atomic(by_awb_path, record)

    # Update master map (record_id = awb)
    master = _load_master()
    master[awb] = {
        "awb":              awb,
        "matched":          record["matched"],
        "confidence":       record["confidence"],
        "search_unreliable": record["search_unreliable"],
        "last_scanned_at":  now_iso,
        "source":           record["source"],
    }
    _save_master(master)

    # Update secondary indices: by_invoice / by_mrn / by_ticket
    for inv in invoice_numbers:
        if inv:
            existing_awbs = _read_index("by_invoice", inv)
            _write_index("by_invoice", inv, existing_awbs + [awb])

    if mrn:
        existing_awbs = _read_index("by_mrn", mrn)
        _write_index("by_mrn", mrn, existing_awbs + [awb])

    if dhl_ticket:
        existing_awbs = _read_index("by_ticket", dhl_ticket)
        _write_index("by_ticket", dhl_ticket, existing_awbs + [awb])

    return record


def get_by_awb(awb: str) -> Optional[Dict[str, Any]]:
    """Return the stored record for this AWB, or None if not found."""
    if not awb:
        return None
    p = _root() / "by_awb" / f"{_safe_key(awb)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _get_records_via_index(sub: str, key: str) -> List[Dict[str, Any]]:
    """Read AWB list from a secondary index, then dereference each AWB record."""
    awbs = _read_index(sub, key)
    out: List[Dict[str, Any]] = []
    for awb in awbs:
        rec = get_by_awb(awb)
        if rec:
            out.append(rec)
    return out


def get_by_invoice(invoice_no: str) -> List[Dict[str, Any]]:
    return _get_records_via_index("by_invoice", invoice_no)


def get_by_mrn(mrn: str) -> List[Dict[str, Any]]:
    return _get_records_via_index("by_mrn", mrn)


def get_by_ticket(ticket: str) -> List[Dict[str, Any]]:
    return _get_records_via_index("by_ticket", ticket)


def find_existing_email_context(audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Look up a stored email intelligence record for this audit's shipment.

    Tries (in order):
      1. By AWB / tracking_no
      2. By DHL ticket if known
      3. By MRN if known
      4. By invoice numbers (returns first hit)
    Returns the most-relevant record or None.
    """
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
    )
    if awb:
        rec = get_by_awb(str(awb))
        if rec:
            return rec

    dhl_ticket = (
        audit.get("dhl_ticket")
        or (audit.get("dhl_email") or {}).get("ticket")
    )
    if dhl_ticket:
        recs = get_by_ticket(dhl_ticket)
        if recs:
            return recs[0]

    mrn = (audit.get("customs_declaration") or {}).get("mrn") or audit.get("mrn")
    if mrn:
        recs = get_by_mrn(mrn)
        if recs:
            return recs[0]

    # Invoice fallback (best-effort: scan known fields for invoice strings)
    from .email_search_context import _extract_invoice_numbers
    for inv in _extract_invoice_numbers(audit):
        recs = get_by_invoice(inv)
        if recs:
            return recs[0]

    return None

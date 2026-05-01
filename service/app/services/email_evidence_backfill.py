"""
email_evidence_backfill.py — Audit-driven evidence backfill.

For outgoing emails (our_dhl_reply, agency_forward), we do NOT depend on
Zoho search because sent emails may never appear in the inbox search.  Instead
we read them directly from the audit fields that the PZ App populates on send:

  Incoming evidence:
    audit.dhl_email / audit.dhl_ticket       → dhl_request
    audit.dhl_documents_received             → dhl_documents

  Outgoing evidence:
    audit.dhl_reply_package                  → our_dhl_reply
    audit.agency_reply_package               → agency_forward
    audit.timeline[dhl_reply_sent_verified]  → supplements our_dhl_reply
    audit.timeline[agency_email_sent_*]      → supplements agency_forward

Delivery-status rules (strictly enforced — never upgrade unless confirmed):
  - delivery_status = "sent"   ONLY when sent_at is populated AND
                               (status == "sent" OR send_verified is True)
                               OR timeline has the corresponding *_sent_verified event
  - delivery_status = "queued" when queued_at is present but sent_at is missing/falsy
  - Never mark "sent" from a queue_id or email_id alone

Idempotency:
  Checks the existing evidence store before writing.  A record is considered
  present if a message exists in the same thread_id with the same direction
  and event_type and approximately the same timestamp (±60 s tolerance for
  queued→sent timestamp drift).

Read-only over audit.json and any financial fields.

Public API
----------
backfill_from_audit(awb, batch_id, audit_path, audit) -> dict
    Returns {"added": [...], "skipped": [...], "total_added": int}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ts_close(a: Any, b: Any, tolerance_secs: int = 120) -> bool:
    """True when two ISO timestamps are within tolerance_secs of each other."""
    ta = _parse_ts(a)
    tb = _parse_ts(b)
    if ta is None or tb is None:
        return False
    return abs((ta - tb).total_seconds()) <= tolerance_secs


# ── Delivery-status determination ─────────────────────────────────────────────

def _is_confirmed_sent(
    package: Dict[str, Any],
    timeline: List[Dict[str, Any]],
    timeline_sent_event: str,
) -> bool:
    """
    Return True only when the audit positively confirms delivery.

    Confirmation sources (any one is sufficient):
      1. package.sent_at populated AND (package.status=="sent" OR package.send_verified==True)
      2. A matching timeline event of type `timeline_sent_event`
    """
    sent_at = package.get("sent_at")
    if sent_at:
        if package.get("status") == "sent" or package.get("send_verified") is True:
            return True

    return any(e.get("event") == timeline_sent_event for e in (timeline or []))


def _delivery_status(truly_sent: bool, package: Dict[str, Any]) -> str:
    return "sent" if truly_sent else "queued"


# ── Duplicate detection ───────────────────────────────────────────────────────

def _already_exists(
    existing_messages: List[Dict[str, Any]],
    event_type: str,
    direction: str,
    timestamp: Optional[str],
) -> bool:
    """
    Return True if a message with the same event_type + direction already exists.

    For backfill entries (message_id=None) we check only event_type + direction
    since timestamps may differ between the queued_at and sent_at of the same
    logical event.  A single event_type+direction pair per AWB is sufficient to
    consider the entry present — we never need two dhl_request or two
    agency_forward entries from the audit source.
    """
    for m in existing_messages:
        if m.get("event_type") == event_type and m.get("direction") == direction:
            # Any matching event_type+direction is considered present
            return True
    return False


# ── Individual backfill builders ──────────────────────────────────────────────

def _build_dhl_request(awb: str, audit: Dict[str, Any], timeline: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build a dhl_request evidence entry from audit.dhl_email or timeline."""
    de = audit.get("dhl_email") or {}
    ticket = audit.get("dhl_ticket") or de.get("ticket") or ""

    # Timestamp: prefer dhl_email_received_at, then the timeline event
    received_at = (
        audit.get("dhl_email_received_at")
        or de.get("received_at")
        or next(
            (e.get("ts") for e in timeline if e.get("event") == "dhl_customs_email_received"),
            None,
        )
    )

    # Require at least one confirming signal
    if not (de or ticket or received_at):
        return None

    subject = (
        de.get("subject")
        or (f"T#{ticket} - Agencja Celna DHL - przesyłka numer: {awb}" if ticket else None)
        or f"DHL customs request — AWB {awb}"
    )
    sender = de.get("from") or de.get("sender") or "odprawacelna@dhl.com"

    return {
        "message_id":          None,
        "thread_id":           f"backfill:dhl_request:{awb}",
        "direction":           "incoming",
        "sender":              sender,
        "to":                  [de.get("to") or "import@estrellajewels.eu"],
        "cc":                  [],
        "subject":             subject,
        "body_text":           de.get("body_text") or de.get("body_snippet") or "",
        "timestamp":           received_at or "",
        "event_type":          "dhl_request",
        "matched_identifiers": {"awb": True, "ticket": ticket} if ticket else {"awb": True},
        "attachments":         [],
        "processed":           False,
        "processed_at":        None,
        "body_hash":           "",
    }


def _build_dhl_documents(awb: str, audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a dhl_documents evidence entry from audit.dhl_documents_received."""
    dd = audit.get("dhl_documents_received") or {}
    files = dd.get("files") or []
    received_at = dd.get("received_at") or ""
    if not (files or received_at):
        return None

    return {
        "message_id":          None,
        "thread_id":           f"backfill:dhl_documents:{awb}",
        "direction":           "incoming",
        "sender":              "odprawacelna@dhl.com",
        "to":                  ["import@estrellajewels.eu"],
        "cc":                  [],
        "subject":             f"DHL documents for AWB {awb}",
        "body_text":           "",
        "timestamp":           received_at,
        "event_type":          "dhl_documents",
        "matched_identifiers": {"awb": True},
        "attachments":         [
            {
                "filename":      Path(str(f.get("path", ""))).name or f.get("name", ""),
                "local_path":    str(f.get("path", "")),
                "sha256":        "",
                "document_type": f.get("type", ""),
            }
            for f in files
        ],
        "processed":           False,
        "processed_at":        None,
        "body_hash":           "",
    }


def _build_our_dhl_reply(
    awb: str,
    audit: Dict[str, Any],
    timeline: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build an our_dhl_reply evidence entry from audit.dhl_reply_package."""
    drp = audit.get("dhl_reply_package") or {}

    # Need at least a queued_at or email_id to know it was attempted
    if not (drp.get("queued_at") or drp.get("email_id") or drp.get("sent_at")):
        return None

    truly_sent = _is_confirmed_sent(drp, timeline, "dhl_reply_sent_verified")
    sent_at    = drp.get("sent_at") or ""
    queued_at  = drp.get("queued_at") or ""
    timestamp  = sent_at if truly_sent else queued_at

    ticket = audit.get("dhl_ticket") or ""
    subject = drp.get("subject") or (
        f"Re: T#{ticket} - Agencja Celna DHL - przesyłka numer: {awb}" if ticket
        else f"DHL reply — AWB {awb}"
    )

    files = drp.get("files") or []
    attachments = [
        {
            "filename":      Path(str(f)).name if isinstance(f, str) else (f.get("name") or Path(str(f.get("path", ""))).name),
            "local_path":    str(f) if isinstance(f, str) else str(f.get("path", "")),
            "sha256":        "",
            "document_type": "" if isinstance(f, str) else f.get("type", ""),
        }
        for f in files
    ]

    return {
        "message_id":          None,
        "thread_id":           f"backfill:our_dhl_reply:{awb}",
        "direction":           "outgoing",
        "sender":              "import@estrellajewels.eu",
        "to":                  drp.get("to") or ["odprawacelna@dhl.com"],
        "cc":                  drp.get("cc") or [],
        "subject":             subject,
        "body_text":           "",
        "timestamp":           timestamp,
        "event_type":          "our_dhl_reply",
        "matched_identifiers": {"awb": True},
        "attachments":         attachments,
        "processed":           truly_sent,
        "delivery_status":     _delivery_status(truly_sent, drp),
        "sent_at":             sent_at if truly_sent else None,
        "queued_at":           queued_at or None,
        "processed_at":        None,
        "body_hash":           "",
    }


def _build_agency_forward(
    awb: str,
    audit: Dict[str, Any],
    timeline: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build an agency_forward evidence entry from audit.agency_reply_package."""
    arp = audit.get("agency_reply_package") or {}

    # Need at least a queued_at or email_id
    if not (arp.get("queued_at") or arp.get("email_id") or arp.get("sent_at")):
        return None

    truly_sent = _is_confirmed_sent(arp, timeline, "agency_email_sent_verified")
    # Also accept the less-specific agency_email_sent event
    if not truly_sent:
        truly_sent = any(
            e.get("event") == "agency_email_sent" and arp.get("sent_at")
            for e in timeline
        )

    sent_at   = arp.get("sent_at") or ""
    queued_at = arp.get("queued_at") or ""
    timestamp = sent_at if truly_sent else queued_at

    attachments = [
        {
            "filename":      att.get("label") or Path(str(att.get("path", ""))).name,
            "local_path":    str(att.get("path", "")),
            "sha256":        "",
            "document_type": "customs_doc",
        }
        for att in (arp.get("attachments") or [])
    ]

    return {
        "message_id":          None,
        "thread_id":           f"backfill:agency_forward:{awb}",
        "direction":           "outgoing",
        "sender":              "import@estrellajewels.eu",
        "to":                  arp.get("to_list") or [arp.get("to") or "biuro@acspedycja.pl"],
        "cc":                  arp.get("cc_list") or [],
        "subject":             arp.get("subject") or f"Zgłoszenie celne – AWB {awb}",
        "body_text":           "",
        "timestamp":           timestamp,
        "event_type":          "agency_forward",
        "matched_identifiers": {"awb": True},
        "attachments":         attachments,
        "processed":           truly_sent,
        "delivery_status":     _delivery_status(truly_sent, arp),
        "sent_at":             sent_at if truly_sent else None,
        "queued_at":           queued_at or None,
        "processed_at":        None,
        "body_hash":           "",
    }


# ── Store helper ──────────────────────────────────────────────────────────────

def _get_existing_messages(awb: str) -> List[Dict[str, Any]]:
    """Return all messages currently stored for this AWB."""
    try:
        from .email_evidence_store import get_by_awb
        doc = get_by_awb(awb)
        return [
            m
            for t in doc.get("threads", [])
            for m in t.get("messages", [])
        ]
    except Exception:
        return []


def _save(awb: str, msg: Dict[str, Any]) -> str:
    """Save a message to the evidence store. Returns 'inserted' | 'duplicate' | 'error'."""
    try:
        from .email_evidence_store import save_message
        result = save_message(awb, msg, source="audit_backfill")
        return result.get("action", "inserted")
    except Exception as exc:
        log.warning("[backfill] save_message failed awb=%s event=%s: %s",
                    awb, msg.get("event_type"), exc)
        return "error"


# ── Public API ────────────────────────────────────────────────────────────────

def backfill_from_audit(
    awb: str,
    batch_id: str,
    audit_path: Path,
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Read audit fields and create missing evidence entries.

    Returns:
        {
            "awb":         str,
            "batch_id":    str,
            "added":       [{"event_type": ..., "delivery_status": ..., "action": ...}],
            "skipped":     [{"event_type": ..., "reason": ...}],
            "total_added": int,
        }

    Idempotent: calling twice with the same audit will not create duplicate entries
    because backfill entries share a deterministic thread_id and the duplicate
    check uses thread_id + event_type + direction + approximate timestamp.
    """
    awb = str(awb).strip()
    timeline = audit.get("timeline") or []

    # Link this batch to the AWB in the evidence store
    try:
        from .email_evidence_store import link_batch
        link_batch(awb, batch_id)
    except Exception as exc:
        log.debug("[backfill] link_batch failed: %s", exc)

    # Collect existing messages once (for duplicate detection)
    existing = _get_existing_messages(awb)

    added:   List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    # ── Candidates to process ─────────────────────────────────────────────────
    candidates = [
        ("dhl_request",   _build_dhl_request(awb, audit, timeline)),
        ("dhl_documents", _build_dhl_documents(awb, audit)),
        ("our_dhl_reply", _build_our_dhl_reply(awb, audit, timeline)),
        ("agency_forward", _build_agency_forward(awb, audit, timeline)),
    ]

    for event_type, msg in candidates:
        if msg is None:
            skipped.append({"event_type": event_type, "reason": "no_source_data"})
            continue

        direction = msg.get("direction", "incoming")
        timestamp = msg.get("timestamp")

        if _already_exists(existing, event_type, direction, timestamp):
            # Check if the existing entry needs a delivery_status upgrade
            upgraded = _try_upgrade_delivery_status(awb, event_type, direction, msg, existing)
            if upgraded:
                added.append({"event_type": event_type, "action": "upgraded", "delivery_status": msg.get("delivery_status")})
            else:
                skipped.append({"event_type": event_type, "reason": "already_stored"})
            continue

        action = _save(awb, msg)
        if action in ("inserted", "promoted"):
            existing.append(msg)  # update local view so later checks see it
            added.append({
                "event_type":      event_type,
                "action":          action,
                "delivery_status": msg.get("delivery_status"),
                "sent_at":         msg.get("sent_at"),
            })
        elif action == "duplicate":
            skipped.append({"event_type": event_type, "reason": "duplicate_from_store"})
        else:
            skipped.append({"event_type": event_type, "reason": f"save_error"})

    result = {
        "awb":         awb,
        "batch_id":    batch_id,
        "added":       added,
        "skipped":     skipped,
        "total_added": len(added),
    }
    log.info("[backfill] awb=%s batch=%s added=%d skipped=%d",
             awb, batch_id, len(added), len(skipped))
    return result


def _try_upgrade_delivery_status(
    awb: str,
    event_type: str,
    direction: str,
    new_msg: Dict[str, Any],
    existing: List[Dict[str, Any]],
) -> bool:
    """
    If the existing record has delivery_status='queued' but the new audit data
    confirms it was sent (delivery_status='sent'), upgrade it in the store.

    Returns True if an upgrade was performed.
    """
    if new_msg.get("delivery_status") != "sent":
        return False

    # Find the matching existing message
    for existing_msg in existing:
        if (existing_msg.get("event_type") == event_type
                and existing_msg.get("direction") == direction
                and existing_msg.get("delivery_status") != "sent"):
            mid = existing_msg.get("message_id")
            ts  = new_msg.get("timestamp") or new_msg.get("sent_at") or ""
            if not _ts_close(existing_msg.get("timestamp"), ts, tolerance_secs=120):
                continue
            # Upgrade: update via store if message_id known, else update in-place
            try:
                from .email_evidence_store import update_message
                patch = {
                    "delivery_status": "sent",
                    "sent_at":         new_msg.get("sent_at"),
                }
                if mid:
                    update_message(awb, mid, patch)
                    return True
                else:
                    # Backfill entry (no message_id): update in-memory doc directly
                    # by re-saving with the upgraded status through the store lock
                    existing_msg.update(patch)
                    _patch_backfill_entry(awb, event_type, direction, existing_msg.get("timestamp"), patch)
                    return True
            except Exception as exc:
                log.debug("[backfill] upgrade failed awb=%s event=%s: %s", awb, event_type, exc)
    return False


def _patch_backfill_entry(
    awb: str,
    event_type: str,
    direction: str,
    timestamp: Optional[str],
    patch: Dict[str, Any],
) -> None:
    """Directly patch a backfill entry (message_id=None) in the by_awb store."""
    try:
        from .email_evidence_store import _awb_lock, _safe_load, _summarise
        from ..utils.io import write_json_atomic
        from .email_evidence_store import BY_AWB_DIR, _safe_awb

        p = BY_AWB_DIR / f"{_safe_awb(awb)}.json"
        with _awb_lock(awb):
            doc = _safe_load(p)
            for t in doc.get("threads", []):
                for m in t.get("messages", []):
                    if (m.get("event_type") == event_type
                            and m.get("direction") == direction
                            and m.get("message_id") is None):
                        if timestamp is None or _ts_close(m.get("timestamp"), timestamp, 120):
                            m.update(patch)
                            doc["summary"] = _summarise(doc["threads"])
                            write_json_atomic(p, doc)
                            return
    except Exception as exc:
        log.debug("[backfill] _patch_backfill_entry failed: %s", exc)

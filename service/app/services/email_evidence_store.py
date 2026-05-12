"""
Email Evidence V2 — local on-disk store.

Permanent mailbox memory keyed by AWB and thread. Lives at:
  storage/email_evidence/
    by_awb/{awb}.json                    one file per AWB (locked per write)
    by_thread/{thread_id}.json           cross-AWB thread index
    attachments/{sha256[:2]}/{sha256}    sha256-of-content de-dup
    master_email_index.json              {awb -> [message_ids], message_id -> awb}

Idempotent:
  - same message_id saved twice → second is a no-op (returns "duplicate")
  - same attachment sha256 saved twice → file exists check, single copy on disk
  - audit-backfill entries can have message_id=None and are promoted later when
    the real Zoho fetch lands a matching (received_at + from + subject) message

Concurrency: fcntl.flock per by_awb/{awb}.json (matches the dhl_email_monitor pattern).

This module is read-only over audit.json. It NEVER touches:
  - financial fields (CIF, duty, totals, customs values)
  - existing sent records
  - PZ outputs
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

if sys.platform == "win32":
    import threading as _threading
    _awb_locks: dict = {}
    _awb_locks_guard = _threading.Lock()
else:
    import fcntl as _fcntl

from ..core.config import settings
from ..core.logging import get_logger
from ..utils.io import write_json_atomic

log = get_logger(__name__)

def _evidence_root() -> Path:
    return settings.storage_root / "email_evidence"

def _by_awb_dir() -> Path:
    return _evidence_root() / "by_awb"

def _by_thread_dir() -> Path:
    return _evidence_root() / "by_thread"

def _attach_dir() -> Path:
    return _evidence_root() / "attachments"

def _master_index() -> Path:
    return _evidence_root() / "master_email_index.json"


# ── Filesystem setup ────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    for d in (_by_awb_dir(), _by_thread_dir(), _attach_dir()):
        d.mkdir(parents=True, exist_ok=True)


# ── Locking ─────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _awb_lock(awb: str):
    """Per-AWB exclusive lock. POSIX: fcntl.flock. Windows: threading.Lock."""
    _ensure_dirs()
    p = _by_awb_dir() / f"{_safe_awb(awb)}.json"
    if not p.exists():
        p.write_text("{}", encoding="utf-8")
    if sys.platform == "win32":
        with _awb_locks_guard:
            if awb not in _awb_locks:
                _awb_locks[awb] = _threading.Lock()
            lock = _awb_locks[awb]
        lock.acquire()
        try:
            yield p
        finally:
            lock.release()
    else:
        f = open(p, "r+")
        try:
            _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
            yield p
        finally:
            try: _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
            except Exception: pass
            f.close()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_awb(awb: str) -> str:
    return "".join(c for c in str(awb) if c.isalnum() or c in "-_")[:64] or "unknown"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _attach_path_for(sha: str) -> Path:
    return _attach_dir() / sha[:2] / sha


def _safe_load(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else {}
    except Exception:
        return {}


def _empty_awb_doc(awb: str) -> Dict[str, Any]:
    return {
        "awb":              awb,
        "batch_ids":        [],
        "threads":          [],
        "last_scan_at":     None,
        "last_message_at":  None,
        "summary":          {
            "dhl_request_received":   False,
            "our_dhl_reply_sent":     False,
            "our_dhl_reply_queued":   False,
            "dhl_documents_received": False,
            "agency_forward_sent":    False,
            "agency_forward_queued":  False,
            "agency_sad_received":    False,
            "dhl_invoice_received":   False,
            "agency_invoice_received": False,
        },
    }


_OUTGOING_EVENTS = {"our_dhl_reply", "agency_forward"}


def _is_truly_sent(msg: Dict[str, Any]) -> bool:
    """Outgoing message counts as 'sent' only if delivery_status confirms it.
    queued / failed / unknown explicitly DO NOT count.
    """
    return (msg.get("delivery_status") == "sent") or bool(msg.get("sent_at"))


def _summarise(threads: List[Dict[str, Any]]) -> Dict[str, bool]:
    incoming_seen = set()
    sent_outgoing = set()
    queued_outgoing = set()
    for t in threads:
        for m in t.get("messages", []):
            ev = m.get("event_type")
            if not ev:
                continue
            if ev in _OUTGOING_EVENTS:
                if _is_truly_sent(m):
                    sent_outgoing.add(ev)
                else:
                    queued_outgoing.add(ev)
            else:
                incoming_seen.add(ev)
    return {
        "dhl_request_received":    "dhl_request" in incoming_seen,
        "our_dhl_reply_sent":      "our_dhl_reply" in sent_outgoing,
        "our_dhl_reply_queued":    "our_dhl_reply" in queued_outgoing and "our_dhl_reply" not in sent_outgoing,
        "dhl_documents_received":  "dhl_documents" in incoming_seen,
        "agency_forward_sent":     "agency_forward" in sent_outgoing,
        "agency_forward_queued":   "agency_forward" in queued_outgoing and "agency_forward" not in sent_outgoing,
        "agency_sad_received":     "agency_sad_reply" in incoming_seen,
        "dhl_invoice_received":    "dhl_invoice" in incoming_seen,
        "agency_invoice_received": "agency_invoice" in incoming_seen,
    }


# ── Master index ────────────────────────────────────────────────────────────

def _load_index() -> Dict[str, Any]:
    return _safe_load(_master_index()) or {"awb_to_messages": {}, "message_to_awb": {}, "by_invoice_no": {}}


def _save_index(idx: Dict[str, Any]) -> None:
    write_json_atomic(_master_index(), idx)


# ── Attachment storage ──────────────────────────────────────────────────────

def save_attachment(content: bytes, filename: str = "") -> Dict[str, Any]:
    """Save bytes to attachments/{sha[:2]}/{sha} (de-dup'd). Returns metadata."""
    _ensure_dirs()
    sha = _sha256(content)
    dest = _attach_path_for(sha)
    if dest.exists():
        return {"sha256": sha, "size": len(content), "local_path": str(dest), "stored": False}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return {"sha256": sha, "size": len(content), "local_path": str(dest), "stored": True}


def attachment_path(sha: str) -> Optional[Path]:
    """Resolve sha256 → local file path if present, else None."""
    p = _attach_path_for(sha)
    return p if p.is_file() else None


# ── Message storage ─────────────────────────────────────────────────────────

def save_message(
    awb: str,
    message: Dict[str, Any],
    *,
    source: str = "zoho_rest",
) -> Dict[str, Any]:
    """
    Idempotent save. `message` shape (all optional unless noted):
      message_id (str|None)   — None permitted only when source='audit_backfill'
      thread_id  (str)        — required (synthesise from subject_root if missing)
      direction  (str)        — 'incoming' | 'outgoing'
      sender, to, cc, subject, body_text, timestamp
      event_type, matched_identifiers, attachments=[{filename,sha256,size,document_type}]

    Returns: {"action": "inserted" | "duplicate" | "promoted", "message_id": str|None}
    """
    awb = _safe_awb(awb)
    msg = dict(message)
    msg.setdefault("source", source)
    msg.setdefault("processed", False)
    msg.setdefault("processed_at", None)
    msg.setdefault("attachments", [])
    msg.setdefault("matched_identifiers", {})
    msg.setdefault("body_hash", "")
    if not msg.get("thread_id"):
        # W-5 / P0: DHL self-clearance emails use RFC822 References-based threading
        # (per dhl_thread_tracker). Non-DHL traffic retains the existing
        # subject-keyed logic for backwards compatibility.
        if _is_dhl_selfclearance_message(msg):
            derived = _derive_dhl_thread_id(msg, awb)
            if derived:
                msg["thread_id"] = derived
        if not msg.get("thread_id"):
            # synthesise a thread id from normalised subject root for backfill records
            from .email_thread_mapper import normalise_subject
            msg["thread_id"] = "sub:" + (normalise_subject(msg.get("subject", "")) or "unknown")[:80]

    with _awb_lock(awb) as p:
        doc = _safe_load(p) or _empty_awb_doc(awb)
        if "awb" not in doc:
            doc.update(_empty_awb_doc(awb))

        # Find or create thread
        thread = None
        for t in doc["threads"]:
            if t.get("thread_id") == msg["thread_id"]:
                thread = t; break
        if thread is None:
            thread = {
                "thread_id":     msg["thread_id"],
                "subject_root":  msg.get("subject", ""),
                "messages":      [],
            }
            doc["threads"].append(thread)

        # Idempotency check
        action = "inserted"
        mid = msg.get("message_id")
        if mid:
            for existing in thread["messages"]:
                if existing.get("message_id") == mid:
                    return {"action": "duplicate", "message_id": mid}
            # Promote a backfilled (message_id=None) entry that matches by (received_at + from + subject)
            for existing in thread["messages"]:
                if existing.get("message_id") is None and \
                   existing.get("timestamp") == msg.get("timestamp") and \
                   existing.get("sender") == msg.get("sender") and \
                   existing.get("subject") == msg.get("subject"):
                    existing["message_id"] = mid
                    existing["source"] = source
                    existing.setdefault("attachments", []).extend(msg.get("attachments", []))
                    doc["last_message_at"] = msg.get("timestamp") or _now_iso()
                    doc["summary"] = _summarise(doc["threads"])
                    write_json_atomic(p, doc)
                    _index_message(awb, mid, msg)
                    return {"action": "promoted", "message_id": mid}

        thread["messages"].append(msg)
        doc["last_message_at"] = msg.get("timestamp") or _now_iso()
        doc["summary"] = _summarise(doc["threads"])
        write_json_atomic(p, doc)

    if mid:
        _index_message(awb, mid, msg)
    _index_thread(msg["thread_id"], awb, msg.get("message_id"))
    return {"action": action, "message_id": mid}


def _is_dhl_selfclearance_message(msg: Dict[str, Any]) -> bool:
    """
    True iff this message is on the DHL self-clearance email path.

    Gated by sender/recipient match against email_routing.DHL_TO. Other email
    types (agency forwards, invoice forwards, etc.) keep the existing
    subject-keyed thread_id logic — only DHL customs threads switch to
    RFC822 References-based threading at P0.
    """
    try:
        from ..config.email_routing import DHL_TO
    except Exception:
        return False
    dhl_addrs = {a.lower() for a in (DHL_TO or [])}
    if not dhl_addrs:
        return False

    def _collect(value: Any) -> set:
        if value is None:
            return set()
        if isinstance(value, str):
            return {value.lower()}
        if isinstance(value, (list, tuple, set)):
            return {str(v).lower() for v in value}
        return {str(value).lower()}

    candidates = (
        _collect(msg.get("sender"))
        | _collect(msg.get("from"))
        | _collect(msg.get("to"))
        | _collect(msg.get("cc"))
    )
    # Substring match handles formatted "Name <addr@example>" envelopes.
    for cand in candidates:
        for dhl in dhl_addrs:
            if dhl and dhl in cand:
                return True
    return False


def _derive_dhl_thread_id(msg: Dict[str, Any], awb: str) -> Optional[str]:
    """
    Resolve a thread_id for a DHL self-clearance message via RFC822 References.

    Returns None when neither headers nor an AWB fallback resolve a thread.
    The caller falls back to the legacy subject-keyed path on None.
    """
    headers = msg.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    # Inline References / In-Reply-To / Message-ID can also live at the top
    # level of the message dict — accept either.
    for k in ("References", "references", "In-Reply-To", "in_reply_to",
              "Message-ID", "message_id"):
        if k not in headers and k in msg:
            headers[k] = msg[k]
    try:
        from .dhl_thread_tracker import resolve_thread_id
    except Exception:
        return None
    thread_id, _source = resolve_thread_id(headers, awb)
    return thread_id or None


def _index_message(awb: str, message_id: str, msg: Dict[str, Any]) -> None:
    idx = _load_index()
    idx.setdefault("awb_to_messages", {}).setdefault(awb, [])
    if message_id not in idx["awb_to_messages"][awb]:
        idx["awb_to_messages"][awb].append(message_id)
    idx.setdefault("message_to_awb", {})[message_id] = awb
    # Invoice-number cross-index
    invs = (msg.get("matched_identifiers") or {}).get("invoice_numbers", []) or []
    for inv in invs:
        idx.setdefault("by_invoice_no", {}).setdefault(str(inv), [])
        if awb not in idx["by_invoice_no"][str(inv)]:
            idx["by_invoice_no"][str(inv)].append(awb)
    _save_index(idx)


def _index_thread(thread_id: str, awb: str, message_id: Optional[str]) -> None:
    _by_thread_dir().mkdir(parents=True, exist_ok=True)
    p = _by_thread_dir() / f"{_safe_awb(thread_id)}.json"
    doc = _safe_load(p) or {"thread_id": thread_id, "awbs": [], "message_ids": []}
    if awb not in doc["awbs"]: doc["awbs"].append(awb)
    if message_id and message_id not in doc["message_ids"]:
        doc["message_ids"].append(message_id)
    write_json_atomic(p, doc)


# ── Read API ────────────────────────────────────────────────────────────────

def get_by_awb(awb: str) -> Dict[str, Any]:
    p = _by_awb_dir() / f"{_safe_awb(awb)}.json"
    return _safe_load(p) or _empty_awb_doc(awb)


def get_by_thread(thread_id: str) -> Dict[str, Any]:
    p = _by_thread_dir() / f"{_safe_awb(thread_id)}.json"
    return _safe_load(p) or {"thread_id": thread_id, "awbs": [], "message_ids": []}


def get_summary(awb: str) -> Dict[str, Any]:
    doc = get_by_awb(awb)
    return doc.get("summary") or _empty_awb_doc(awb)["summary"]


def iter_messages(awb: str) -> Iterable[Dict[str, Any]]:
    for t in get_by_awb(awb).get("threads", []):
        for m in t.get("messages", []):
            yield m


def get_latest_event(awb: str, event_types: Tuple[str, ...] = (), after: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the latest message (by timestamp) matching event_types, optionally after iso timestamp."""
    candidates = [m for m in iter_messages(awb)
                  if (not event_types or m.get("event_type") in event_types)
                  and (not after or (m.get("timestamp") or "") > after)]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.get("timestamp", ""))


# ── Cursor / scan bookmark ──────────────────────────────────────────────────

def update_scan_cursor(awb: str, last_scan_at: str) -> None:
    with _awb_lock(awb) as p:
        doc = _safe_load(p) or _empty_awb_doc(awb)
        doc["last_scan_at"] = last_scan_at
        write_json_atomic(p, doc)


def get_scan_cursor(awb: str) -> Optional[str]:
    return get_by_awb(awb).get("last_scan_at")


def link_batch(awb: str, batch_id: str) -> None:
    with _awb_lock(awb) as p:
        doc = _safe_load(p) or _empty_awb_doc(awb)
        if batch_id not in doc.get("batch_ids", []):
            doc.setdefault("batch_ids", []).append(batch_id)
            write_json_atomic(p, doc)


# ── Mark message processed ──────────────────────────────────────────────────

def update_message(awb: str, message_id: str, patch: Dict[str, Any]) -> bool:
    """
    Apply a patch to a stored message identified by message_id.
    Re-summarises after writing. Returns True if a message was found.

    Used by email_service.mark_sent to flip queued → sent when SMTP confirms.
    """
    if not message_id or not patch:
        return False
    with _awb_lock(awb) as p:
        doc = _safe_load(p) or _empty_awb_doc(awb)
        for t in doc.get("threads", []):
            for m in t.get("messages", []):
                if m.get("message_id") == message_id:
                    m.update(patch)
                    doc["summary"] = _summarise(doc["threads"])
                    write_json_atomic(p, doc)
                    return True
        return False


def mark_processed(awb: str, message_id_or_idx: Any) -> bool:
    """Mark a message processed=True, processed_at=now. Returns True if found."""
    with _awb_lock(awb) as p:
        doc = _safe_load(p) or {}
        for t in doc.get("threads", []):
            for m in t.get("messages", []):
                if m.get("message_id") == message_id_or_idx:
                    m["processed"] = True
                    m["processed_at"] = _now_iso()
                    write_json_atomic(p, doc)
                    return True
        return False

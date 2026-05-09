"""
zc429_email_dispatcher.py — Bridge from the mailbox watcher to
``dhl_zc429_intake.ingest_zc429_email``.

Purpose
-------
The mailbox watcher (``email_ingestion_worker``) downloads attachments to
disk and emits an email_record. This dispatcher:

  1. Re-uses ``dhl_zc429_intake.is_dhl_zc429_email`` so the detector
     stays the single source of truth.
  2. Reads each already-downloaded attachment from disk into bytes.
  3. Builds the {filename, content, size} payload accepted by
     ``ingest_zc429_email`` and calls it.
  4. Returns the intake result, or ``None`` when the email is not a
     ZC429 completion notification.

Hard rules
----------
- NEVER calls wFirma, SMTP, PZ create, observers, or any side-effect
  outside ``ingest_zc429_email``.
- NEVER raises on missing attachments — surfaces a warning entry in
  the result instead.
- Idempotency is delegated to ``dhl_zc429_intake`` /
  ``intake_lineage`` (UNIQUE on source_kind+message_id, UNIQUE on
  event+sha+filename).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from . import dhl_zc429_intake as _zc

log = get_logger(__name__)


def maybe_dispatch_zc429(
    audit_path: Path,
    email_record: Dict[str, Any],
    attachment_paths: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """If the email looks like a DHL WAW ZC429 completion notice, run
    intake. Otherwise return ``None``.

    ``email_record`` is the output of the mailbox classifier. The keys
    we read are:
      from / sender, subject, body / body_text, message_id,
      received_at / timestamp.

    ``attachment_paths`` are filesystem paths to already-downloaded
    attachments. Missing files are tolerated — they show up as
    zero-byte payloads with a warning, and the lineage row is written
    without a stored copy. The next mailbox cycle can re-deliver and
    will dedupe by SHA.
    """
    sender  = (email_record.get("from")
               or email_record.get("sender") or "")
    subject = (email_record.get("subject") or "")
    body    = (email_record.get("body")
               or email_record.get("body_text") or "")
    received_at = (email_record.get("received_at")
                   or email_record.get("timestamp") or "")
    message_id  = str(email_record.get("message_id") or "")

    if not _zc.is_dhl_zc429_email(sender=sender, subject=subject, body=body):
        return None

    payload: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for ap in (attachment_paths or []):
        p = Path(ap)
        try:
            content = p.read_bytes() if p.exists() else b""
            if not content:
                warnings.append(f"attachment_missing_or_empty: {p.name}")
        except Exception as exc:
            warnings.append(
                f"attachment_read_failed: {p.name}: {type(exc).__name__}: {exc}")
            content = b""
        payload.append({
            "filename": p.name,
            "content":  content,
            "size":     len(content),
        })

    # Resolve batch_id from audit path (outputs/<batch_id>/audit.json).
    batch_id = ""
    try:
        ap_path = Path(audit_path)
        if ap_path.name == "audit.json":
            batch_id = ap_path.parent.name
    except Exception:
        batch_id = ""

    result = _zc.ingest_zc429_email(
        sender       = sender,
        subject      = subject,
        body         = body,
        received_at  = received_at,
        message_id   = message_id,
        attachments  = payload,
        batch_id     = batch_id or None,
    )
    if warnings:
        result.setdefault("dispatcher_warnings", []).extend(warnings)
    log.info(
        "[zc429-dispatcher] sender=%s message_id=%s ok=%s duplicate=%s "
        "intake_event_id=%s attachments=%d",
        sender, message_id,
        result.get("ok"), result.get("duplicate"),
        result.get("intake_event_id"), result.get("attachment_count"),
    )
    return result

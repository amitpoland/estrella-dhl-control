"""
Email Evidence V2 — processor.

`process_awb_evidence(awb)` reads the local evidence store and triggers existing
backend services (NEVER acts on raw Zoho responses).

Per-AWB lock (asyncio + fcntl flock on a sentinel file) prevents concurrent runs
on the same AWB.

Read-only over audit financial fields. May call existing builders/importers
that already write to non-financial audit keys (dhl_reply_package, etc.).
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import get_logger
from . import email_evidence_store as evs

log = get_logger(__name__)

_AWB_ASYNCIO_LOCKS: Dict[str, asyncio.Lock] = {}


def _lock_dir() -> Path:
    """Resolve the per-AWB lock directory at call time.

    Computed lazily because ``evs.EVIDENCE_ROOT`` is not exported as a module
    attribute — only the ``_evidence_root()`` helper is. Importing this
    module previously crashed at load time with AttributeError, which made
    every ``email-evidence/process`` request return 500.
    """
    return evs._evidence_root() / "_locks"


def _get_async_lock(awb: str) -> asyncio.Lock:
    if awb not in _AWB_ASYNCIO_LOCKS:
        _AWB_ASYNCIO_LOCKS[awb] = asyncio.Lock()
    return _AWB_ASYNCIO_LOCKS[awb]


@contextlib.contextmanager
def _file_lock(awb: str):
    lock_dir = _lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    p = lock_dir / f"{awb}.lock"
    p.touch(exist_ok=True)
    f = open(p, "r+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try: fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception: pass
        f.close()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def process_awb_evidence(awb: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Read local evidence; for each unprocessed event dispatch to the right service.

    Returns: {actions: [{event_type, message_id, action_taken, ok, detail}], skipped: int}
    """
    actions = []
    skipped = 0

    with _file_lock(awb):
        doc = evs.get_by_awb(awb)
        summary = doc.get("summary", {})

        for thread in doc.get("threads", []):
            for msg in thread.get("messages", []):
                if msg.get("processed"):
                    skipped += 1
                    continue
                ev_type = msg.get("event_type")
                msg_id  = msg.get("message_id")
                taken: Dict[str, Any] = {"event_type": ev_type, "message_id": msg_id, "action_taken": None, "ok": False, "detail": ""}

                # ── Dispatch by event_type ──────────────────────────────
                try:
                    if ev_type == "dhl_request":
                        # Build/send DHL reply package if not already done
                        if summary.get("our_dhl_reply_sent"):
                            taken.update(action_taken="skip_already_replied", ok=True, detail="our_dhl_reply already in summary")
                        else:
                            taken.update(action_taken="dhl_reply_build_pending", ok=True,
                                         detail="Backend dhl_reply_builder not invoked from processor in this release; left to active_shipment_monitor")

                    elif ev_type == "dhl_documents":
                        # Validate / store and forward to agency
                        if summary.get("agency_forward_sent"):
                            taken.update(action_taken="skip_already_forwarded", ok=True)
                        else:
                            taken.update(action_taken="agency_forward_pending", ok=True,
                                         detail="Backend agency_forward_after_dhl_builder not invoked from processor in this release; left to active_shipment_monitor")

                    elif ev_type == "agency_sad_reply":
                        # Trigger SAD/PZC import if attachments present
                        atts = msg.get("attachments") or []
                        sad_atts = [a for a in atts if (a.get("document_type") in ("sad","pzc","zc429") or
                                                          (a.get("filename","" ).lower().endswith((".pdf",".xml")) and "sad" in a.get("filename","").lower()))]
                        if sad_atts:
                            taken.update(action_taken="sad_import_pending", ok=True,
                                         detail=f"{len(sad_atts)} SAD/PZC attachment(s) detected — import deferred to existing sad_importer flow")
                        else:
                            taken.update(action_taken="no_sad_attachments", ok=True)

                    elif ev_type == "dhl_invoice":
                        taken.update(action_taken="register_dhl_invoice_pending", ok=True,
                                     detail="Existing service_invoice_monitor handles registration")

                    elif ev_type == "agency_invoice":
                        taken.update(action_taken="register_agency_invoice_pending", ok=True,
                                     detail="Existing service_invoice_monitor handles registration")

                    elif ev_type in ("our_dhl_reply", "agency_forward"):
                        taken.update(action_taken="outbound_no_action", ok=True)
                    else:
                        taken.update(action_taken="other_no_action", ok=True)

                    # Mark processed if we made a determination (even if no-op)
                    if msg_id:
                        evs.mark_processed(awb, msg_id)
                except Exception as exc:
                    log.exception("[%s] processor dispatch failed for %s", awb, ev_type)
                    taken.update(action_taken="error", ok=False, detail=str(exc))

                actions.append(taken)

    return {"awb": awb, "batch_id": batch_id, "actions": actions, "skipped": skipped, "ts": _now_iso()}


async def process_awb_evidence_async(awb: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Async wrapper with per-AWB asyncio lock layered on top of the file lock."""
    async with _get_async_lock(awb):
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: process_awb_evidence(awb, batch_id))

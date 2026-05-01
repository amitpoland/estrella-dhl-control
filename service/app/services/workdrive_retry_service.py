"""
workdrive_retry_service.py — WorkDrive upload retry queue.

Manages a persistent JSON queue at storage/system/workdrive_upload_queue.json.
Each item tracks one file upload that failed and should be retried.

Queue item schema:
{
    "batch_id":      str,          # SHIPMENT_... batch identifier
    "file_type":     "pdf"|"xlsx", # which output file
    "file_path":     str,          # absolute local path
    "target_folder": str,          # PZ/YYYY/MM/{batch_id}/ logical path
    "attempts":      int,          # number of attempts made so far
    "status":        "pending"|"success"|"failed",
    "last_error":    str|None,
    "queued_at":     str,          # ISO-8601 UTC
    "last_attempt":  str|None,     # ISO-8601 UTC of last try
}

Max attempts before marking "failed" (permanent): MAX_ATTEMPTS = 5
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_QUEUE_LOCK  = threading.Lock()


def _queue_path() -> Path:
    """Return path to the upload queue file, creating parent dirs if needed."""
    from .workdrive_uploader import _mime  # noqa: F401 — just to confirm import works
    from ..core.config import settings
    p = settings.storage_root / "system" / "workdrive_upload_queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Queue read/write helpers ──────────────────────────────────────────────────

def _read_queue() -> List[Dict[str, Any]]:
    p = _queue_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[workdrive_retry] queue read error: %s", exc)
        return []


def _write_queue(items: List[Dict[str, Any]]) -> None:
    p = _queue_path()
    try:
        p.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.error("[workdrive_retry] queue write error: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def enqueue(batch_id: str, file_type: str, file_path: Path, target_folder: str) -> None:
    """Add a failed upload to the retry queue."""
    with _QUEUE_LOCK:
        items = _read_queue()
        # De-duplicate: if same batch_id + file_type already pending, update path only
        for item in items:
            if item["batch_id"] == batch_id and item["file_type"] == file_type:
                if item["status"] in ("pending",):
                    item["file_path"]     = str(file_path)
                    item["target_folder"] = target_folder
                    item["last_error"]    = None
                    log.info(
                        "[workdrive_retry] re-queued existing item batch=%s type=%s",
                        batch_id, file_type,
                    )
                    _write_queue(items)
                    return

        items.append({
            "batch_id":      batch_id,
            "file_type":     file_type,
            "file_path":     str(file_path),
            "target_folder": target_folder,
            "attempts":      0,
            "status":        "pending",
            "last_error":    None,
            "queued_at":     _now_iso(),
            "last_attempt":  None,
        })
        _write_queue(items)
    log.info(
        "[workdrive_retry] enqueued batch=%s type=%s path=%s",
        batch_id, file_type, file_path,
    )


def pending_count() -> int:
    """Return number of items with status=='pending'."""
    return sum(1 for i in _read_queue() if i["status"] == "pending")


def get_queue() -> List[Dict[str, Any]]:
    """Return the full queue (all statuses)."""
    return _read_queue()


def run_pending(token: Optional[str] = None) -> Dict[str, int]:
    """
    Process all pending queue items.

    Uses the WorkDrive uploader to upload each pending file.
    Updates the queue file with results.

    Returns: {"processed": n, "succeeded": n, "failed": n}
    """
    from . import workdrive_uploader as _wdu
    _get_access_token    = _wdu._get_access_token
    _resolve_batch_folder = _wdu._resolve_batch_folder
    upload_file           = _wdu.upload_file

    stats = {"processed": 0, "succeeded": 0, "failed": 0}

    with _QUEUE_LOCK:
        items = _read_queue()
        changed = False

        # Resolve token once
        _token = token or _get_access_token()
        if not _token:
            log.warning("[workdrive_retry] cannot get access token — skipping run")
            return stats

        for item in items:
            if item["status"] != "pending":
                continue

            stats["processed"] += 1
            item["attempts"]    += 1
            item["last_attempt"] = _now_iso()
            changed = True

            file_path = Path(item["file_path"])
            if not file_path.exists():
                item["status"]     = "failed"
                item["last_error"] = f"local file missing: {file_path}"
                stats["failed"]   += 1
                log.error(
                    "[workdrive_retry] batch=%s type=%s — file missing, marking failed",
                    item["batch_id"], item["file_type"],
                )
                continue

            try:
                folder_id = _resolve_batch_folder(item["batch_id"], _token)
                if not folder_id:
                    raise RuntimeError("could not resolve/create batch folder")

                resource_id = upload_file(file_path, folder_id, _token)
                if resource_id:
                    item["status"]       = "success"
                    item["last_error"]   = None
                    item["resource_id"]  = resource_id
                    item["folder_id"]    = folder_id
                    stats["succeeded"]  += 1
                    log.info(
                        "[workdrive_retry] ✅ batch=%s type=%s resource=%s",
                        item["batch_id"], item["file_type"], resource_id,
                    )
                    # Patch the batch audit.json with the recovered resource ID
                    _patch_audit(item["batch_id"], item["file_type"], resource_id, folder_id)
                else:
                    raise RuntimeError("upload returned no resource_id")

            except Exception as exc:
                item["last_error"] = str(exc)
                if item["attempts"] >= MAX_ATTEMPTS:
                    item["status"]  = "failed"
                    stats["failed"] += 1
                    log.error(
                        "[workdrive_retry] ❌ batch=%s type=%s — max attempts reached: %s",
                        item["batch_id"], item["file_type"], exc,
                    )
                else:
                    stats["failed"] += 1   # still pending, counts as failed attempt
                    log.warning(
                        "[workdrive_retry] attempt %d/%d failed batch=%s type=%s: %s",
                        item["attempts"], MAX_ATTEMPTS,
                        item["batch_id"], item["file_type"], exc,
                    )

        if changed:
            _write_queue(items)

    return stats


# ── Audit patch helper ────────────────────────────────────────────────────────

def _patch_audit(batch_id: str, file_type: str, resource_id: str, folder_id: str) -> None:
    """Write recovered WorkDrive resource ID back into the batch audit.json."""
    from ..core.config import settings
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        return
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        key = f"workdrive_{file_type}_resource_id"
        audit[key]                     = resource_id
        audit["workdrive_batch_folder_id"] = folder_id
        audit["workdrive_direct_upload"]   = True
        # Refresh the upload section if present
        _upd = audit.setdefault("workdrive_upload", {})
        _upd["status"]        = "success"
        _upd["retry_required"] = False
        audit_path.write_text(
            json.dumps(audit, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        log.info("[workdrive_retry] audit patched batch=%s type=%s", batch_id, file_type)
    except Exception as exc:
        log.warning("[workdrive_retry] audit patch failed: %s", exc)

"""
workdrive_sync.py — Mirror per-shipment files into Zoho WorkDrive via TrueSync.

Uses the existing TrueSync model (no API integration): files copied into the
local TrueSync folder (`WORKDRIVE_SYNC_ROOT` env var) are auto-uploaded by
the Zoho WorkDrive desktop app.

Public API:
    sync_to_workdrive(batch_id, src_path) -> dict
    is_configured() -> bool
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from ..core.config import settings

log = logging.getLogger(__name__)


def is_configured() -> bool:
    val = getattr(settings, "workdrive_sync_root", "") or ""
    return bool(str(val).strip())


def _shipment_root(batch_id: str) -> Path:
    base = Path(getattr(settings, "workdrive_sync_root", "") or "")
    return base / "Shipments" / batch_id


def sync_to_workdrive(batch_id: str, src_path: Path) -> Dict[str, Any]:
    """
    Copy a file into the TrueSync folder for this batch, preserving the
    01_invoices / 02_awb / ... layout.

    Idempotent: skips if dest already exists with same size.
    Returns:
      {synced: bool, dest: str | None, reason: str | None}
    """
    if not is_configured():
        return {"synced": False, "reason": "workdrive_not_configured"}

    src = Path(src_path)
    if not src.is_file():
        return {"synced": False, "reason": f"src not found: {src}"}

    # Preserve subfolder name from local layout (parent dir name)
    folder = src.parent.name
    dest_dir = _shipment_root(batch_id) / folder
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.warning("[workdrive] mkdir failed: %s", exc)
        return {"synced": False, "reason": f"mkdir_failed: {exc}"}

    dest = dest_dir / src.name
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return {"synced": True, "dest": str(dest), "reason": "already_present"}

    try:
        shutil.copy2(src, dest)
    except Exception as exc:
        log.warning("[workdrive] copy failed src=%s dest=%s err=%s", src, dest, exc)
        return {"synced": False, "reason": f"copy_failed: {exc}"}

    return {"synced": True, "dest": str(dest)}

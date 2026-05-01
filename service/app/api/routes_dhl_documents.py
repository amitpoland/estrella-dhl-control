"""
routes_dhl_documents.py — Record DHL-received customs documents per batch.

Once the operator (or downstream extractor) has the DHL-returned customs
docs (DSK / PZC / SAD / ZC429 / etc.) on disk, this endpoint registers them
into audit. The active monitor then auto-builds + sends the post-DHL agency
forward in its next sweep (or immediately on demand via the helper).

Endpoints:
  POST /api/v1/dhl-documents/{batch_id}/received
        Body: {"files": [{"name":"...", "path":"...", "type":"DSK|PZC|SAD|ZC429|other"}]}
        Records the files into audit.dhl_documents_received.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl-documents", tags=["dhl-documents"])
_auth  = Depends(require_api_key)


def _audit_path(batch_id: str) -> Path:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")


class _DocFile(BaseModel):
    name: str
    path: str
    type: Optional[str] = "other"   # DSK | PZC | SAD | ZC429 | other


class ReceivedReq(BaseModel):
    files:     List[_DocFile]
    source:    Optional[str] = "operator"   # operator | mcp_extract | manual_upload
    note:      Optional[str] = None


@router.post("/{batch_id}/received", dependencies=[_auth])
def record_received_documents(batch_id: str, body: ReceivedReq) -> Dict[str, Any]:
    """
    Register DHL-received customs documents on the batch audit.

    Files must already exist on disk. Each file's `path` is checked; missing
    files are reported but do not block — the agency forward step has its own
    AWB-required guard.
    """
    if not body.files:
        raise HTTPException(status_code=422, detail="files list is empty")

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = audit.get("dhl_documents_received") or {}
    existing_paths = {f.get("path") for f in (existing.get("files") or []) if isinstance(f, dict)}

    new_files: List[Dict[str, Any]] = list(existing.get("files") or [])
    missing: List[str] = []
    for f in body.files:
        fp = Path(f.path)
        if not fp.is_file():
            missing.append(f.path)
            continue
        if f.path in existing_paths:
            continue   # idempotent — skip duplicates
        new_files.append({
            "name":     f.name or fp.name,
            "path":     f.path,
            "type":     (f.type or "other").upper(),
            "size":     fp.stat().st_size,
            "added_at": now_iso,
        })

    audit["dhl_documents_received"] = {
        "received":    True,
        "files":       new_files,
        "received_at": existing.get("received_at") or now_iso,
        "source":      body.source or "operator",
        "note":        body.note or "",
        "files_count": len(new_files),
    }
    write_json_atomic(p, audit)

    try:
        tl.log_event(p, "dhl_documents_received", "operator", body.source or "operator",
                     detail={"files_count":  len(new_files),
                             "added_files":  [f.name for f in body.files],
                             "missing_paths": missing})
    except Exception:
        pass

    return {
        "ok":             True,
        "batch_id":       batch_id,
        "files_count":    len(new_files),
        "missing_paths":  missing,
        "next_step":      "Active monitor will build + send agency forward on next sweep "
                          "(or hit /api/v1/monitor/active-shipments/run to fire immediately).",
    }

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

  POST /api/v1/dhl-documents/{batch_id}/upload
        Multipart file upload (.pdf/.xml/.html/.htm/.jpg/.jpeg/.png).
        Browser-safe fallback when email auto-detection does not capture docs.
        Saves files to batch source/dhl_documents/, then updates audit.
        Does NOT send email, does NOT affect closure hard blockers.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key
from ..auth.dependencies import require_role
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log      = logging.getLogger(__name__)
router   = APIRouter(prefix="/api/v1/dhl-documents", tags=["dhl-documents"])
_auth    = Depends(require_api_key)
_op_auth = Depends(require_role("admin", "logistics"))

_ALLOWED_EXTENSIONS = {".pdf", ".xml", ".html", ".htm", ".jpg", ".jpeg", ".png"}
_MAX_UPLOAD_BYTES   = 50 * 1024 * 1024   # 50 MB per file


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


def _write_dhl_docs_to_audit(
    p: Path,
    audit: dict,
    batch_id: str,
    ready_files: List[Dict[str, Any]],
    source: str,
    note: str,
) -> List[Dict[str, Any]]:
    """
    Write ready_files into audit.dhl_documents_received (idempotent by path),
    persist to disk, fire timeline event, and mirror into the evidence store.

    ready_files: each dict must have {name, path, type, size}.
    Returns the updated new_files list.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = audit.get("dhl_documents_received") or {}
    existing_paths = {f.get("path") for f in (existing.get("files") or []) if isinstance(f, dict)}

    new_files: List[Dict[str, Any]] = list(existing.get("files") or [])
    for f in ready_files:
        if f["path"] in existing_paths:
            continue
        new_files.append({**f, "added_at": now_iso})

    audit["dhl_documents_received"] = {
        "received":    True,
        "files":       new_files,
        "received_at": existing.get("received_at") or now_iso,
        "source":      source,
        "note":        note or "",
        "files_count": len(new_files),
    }
    write_json_atomic(p, audit)

    try:
        tl.log_event(p, "dhl_documents_received", "operator", source,
                     detail={"files_count":  len(new_files),
                             "added_files":  [f["name"] for f in ready_files]})
    except Exception:
        pass

    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if awb:
        try:
            from ..services import email_evidence_store as evs
            evs.link_batch(awb, batch_id)
            evs.save_message(awb, {
                "message_id":  f"op_dhl_recv:{batch_id}",
                "thread_id":   f"op_dhl_recv:{batch_id}",
                "direction":   "incoming",
                "sender":      "dhl@operator-receipt",
                "to":          [],
                "cc":          [],
                "subject":     "Manual DHL documents received",
                "body_text":   f"Operator registered {len(new_files)} DHL document(s) for batch {batch_id}.",
                "timestamp":   now_iso,
                "event_type":  "dhl_documents",
                "matched_identifiers": {"awb": True},
                "attachments": [
                    {
                        "filename":      f.get("name", ""),
                        "document_type": (f.get("type") or "other").lower(),
                        "size":          f.get("size"),
                        "sha256":        None,
                    }
                    for f in new_files
                ],
                "source": "operator_receipt",
            }, source="operator_receipt")
        except Exception as _exc:
            log.warning("[dhl_documents] evidence store write failed (non-fatal): %s", _exc)

    return new_files


@router.post("/{batch_id}/received", dependencies=[_auth, _op_auth])
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

    ready_files: List[Dict[str, Any]] = []
    missing: List[str] = []
    for f in body.files:
        fp = Path(f.path)
        if not fp.is_file():
            missing.append(f.path)
            continue
        ready_files.append({
            "name": f.name or fp.name,
            "path": f.path,
            "type": (f.type or "other").upper(),
            "size": fp.stat().st_size,
        })

    new_files = _write_dhl_docs_to_audit(
        p, audit, batch_id, ready_files,
        source=body.source or "operator",
        note=body.note or "",
    )

    return {
        "ok":             True,
        "batch_id":       batch_id,
        "files_count":    len(new_files),
        "missing_paths":  missing,
        "next_step":      "Active monitor will build + send agency forward on next sweep "
                          "(or hit /api/v1/monitor/active-shipments/run to fire immediately).",
    }


@router.post("/{batch_id}/upload", dependencies=[_auth, _op_auth])
async def upload_dhl_documents(
    batch_id: str,
    files:  List[UploadFile],
    source: str = Form(default="operator"),
) -> Dict[str, Any]:
    """
    Browser-safe multipart upload for DHL-returned customs documents.

    Operator fallback for when email auto-detection does not capture the docs.
    Files are saved to batch source/dhl_documents/ and registered in audit.

    Does NOT send email. Does NOT affect closure hard blockers (customs_docs,
    pz_generated). Does NOT mark customs_docs.received — DHL docs are a
    separate milestone from the SAD/PZC customs clearance documents.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files provided.")

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if not suffix or suffix not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type {suffix!r}. Allowed: "
                       + ", ".join(sorted(_ALLOWED_EXTENSIONS)),
            )

    p = _audit_path(batch_id)
    audit = json.loads(p.read_text(encoding="utf-8"))

    dest_dir = p.parent / "source" / "dhl_documents"
    dest_dir.mkdir(parents=True, exist_ok=True)

    ready_files: List[Dict[str, Any]] = []
    for f in files:
        content = await f.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail=f"File '{f.filename}' is empty.")
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{f.filename}' exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        safe_name = "".join(
            c if c.isalnum() or c in "._- " else "_"
            for c in Path(f.filename or "document").name
        )
        dest = dest_dir / safe_name
        if not dest.exists():
            dest.write_bytes(content)
        ready_files.append({
            "name": safe_name,
            "path": str(dest),
            "type": "other",
            "size": len(content),
        })

    new_files = _write_dhl_docs_to_audit(
        p, audit, batch_id, ready_files,
        source=source or "operator",
        note="",
    )

    return {
        "ok":          True,
        "received":    True,
        "batch_id":    batch_id,
        "files_count": len(new_files),
        "files":       [f["name"] for f in ready_files],
    }

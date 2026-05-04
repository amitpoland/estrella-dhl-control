"""
agency_sad_monitor.py — Detect / register agency SAD/PZC documents.

Two ingestion paths:

  1. PUSH (operator / extractor / Cowork):
       Use POST /api/v1/agency-documents/{batch_id}/received with the file
       paths. This module is the underlying handler.

  2. MCP scan (future):
       Reserved interface — `scan_agency_inbox(audit, since)` returns
       discovered files. Backend can't invoke MCP directly; the
       Cowork orchestrator runs the scan and POSTs results.

Output (audit fields):
  audit.agency_documents_received: bool
  audit.agency_documents:          list of {name, path, type, ...}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

from .customs_doc_classifier  import classify
from .shipment_folder_manager import save_file
from .workdrive_sync          import sync_to_workdrive

log = logging.getLogger(__name__)


def register_agency_documents(
    batch_id:     str,
    file_paths:   List[str],
    source:       str = "operator",
    note:         str = "",
) -> Dict[str, Any]:
    """
    Save received agency documents into the structured shipment folder
    and update audit.agency_documents.

    Each file is classified, copied (idempotent), and mirrored to WorkDrive
    via TrueSync if configured.

    Returns operation summary.
    """
    audit_path = _audit_path(batch_id)
    if not audit_path:
        return {"ok": False, "error": f"batch {batch_id} not found"}

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    now_iso = datetime.now(timezone.utc).isoformat()

    state = audit.get("agency_documents_received_state") or {
        "received":    False,
        "files":       [],
        "received_at": None,
        "source":      source,
        "note":        note,
    }
    existing_paths = {f.get("path") for f in state["files"]}

    imported: List[Dict[str, Any]] = []
    skipped:  List[Dict[str, Any]] = []
    for src in file_paths:
        try:
            cls = classify(Path(src).name)
            saved = save_file(batch_id, src, cls["type"])
            if str(saved) in existing_paths:
                continue
            wd = sync_to_workdrive(batch_id, saved)
            entry = {
                "name":         saved.name,
                "path":         str(saved),
                "type":         cls["type"],
                "confidence":   cls["confidence"],
                "size":         saved.stat().st_size,
                "imported_at":  now_iso,
                "source":       source,
                "workdrive":    wd,
            }
            state["files"].append(entry)
            imported.append(entry)
        except FileNotFoundError as exc:
            skipped.append({"file": src, "error": str(exc)})
        except Exception as exc:
            skipped.append({"file": src, "error": f"{type(exc).__name__}: {exc}"})

    # Only mark received when at least one file was actually imported.
    # A call where every provided path fails is_file() must not create a
    # false audit record (received=True with zero files).
    if len(state["files"]) == 0:
        return {
            "ok":        False,
            "error":     "no_files_imported",
            "batch_id":  batch_id,
            "imported":  [],
            "skipped":   skipped,
            "files_total": 0,
        }

    state["received"]    = True
    state["received_at"] = state.get("received_at") or now_iso
    state["files_count"] = len(state["files"])
    audit["agency_documents_received_state"] = state
    audit["agency_documents_received"]       = True
    audit["agency_documents"]                = state["files"]
    write_json_atomic(audit_path, audit)

    # ── Mirror into email evidence store ─────────────────────────────────────
    _awb_sad = str(audit.get("awb") or audit.get("tracking_no") or "")
    if _awb_sad:
        try:
            from .email_evidence_store import link_batch as _evs_link, save_message as _evs_save
            _evs_link(_awb_sad, batch_id)
            _evs_save(_awb_sad, {
                "message_id":  f"op_agency_docs:{batch_id}",
                "thread_id":   f"op_agency_docs:{batch_id}",
                "direction":   "incoming",
                "sender":      f"agency@{source}",
                "to":          [],
                "cc":          [],
                "subject":     f"Agency documents registered for batch {batch_id}",
                "body_text":   f"{source} registered {len(imported)} agency document(s) for batch {batch_id}.",
                "timestamp":   now_iso,
                "event_type":  "agency_sad_reply",
                "matched_identifiers": {"awb": True},
                "attachments": [
                    {
                        "filename":      e.get("name", ""),
                        "document_type": (e.get("type") or "other").lower(),
                        "size":          e.get("size"),
                        "sha256":        None,
                    }
                    for e in imported
                ],
                "source":      source,
            }, source=source)
        except Exception as _evs_exc:
            log.warning("[register_agency_documents] evidence store write failed (non-fatal): %s", _evs_exc)

    try:
        tl.log_event(audit_path, "agency_documents_registered",
                     "operator" if source == "operator" else "system", source,
                     detail={"imported": len(imported), "skipped": len(skipped)})
    except Exception:
        pass

    return {
        "ok":       True,
        "batch_id": batch_id,
        "imported": imported,
        "skipped":  skipped,
        "files_total": state["files_count"],
    }


def scan_agency_inbox(audit: Dict[str, Any], since: Optional[str] = None) -> Dict[str, Any]:
    """
    Reserved interface for future MCP-driven scan.

    Returns: {"available": False, "reason": "mcp_orchestrator_required"}.
    The orchestrator (Claude Cowork) is expected to run the actual MCP
    search by AWB/MRN/invoice numbers and POST results back via the
    register_agency_documents endpoint.
    """
    return {
        "available": False,
        "reason":   "mcp_orchestrator_required",
        "hint":     "Cowork session must run Zoho Mail MCP search and POST "
                    "to /api/v1/agency-documents/{batch_id}/received.",
    }


def _audit_path(batch_id: str) -> Optional[Path]:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    return None

"""
sad_importer.py — Register agency-returned customs documents into a batch.

Routes incoming files into the structured shipment folder, classifies them,
and updates audit.customs_docs. Optionally triggers the existing PZ engine
when a SAD/ZC429 PDF arrives.

Public API:
    import_customs_docs(batch_id, file_paths, source) -> dict
    list_customs_docs(batch_id) -> dict
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
from .customs_doc_classifier   import classify
from .shipment_folder_manager  import save_file
from .workdrive_sync           import sync_to_workdrive

log = logging.getLogger(__name__)


def import_customs_docs(
    batch_id:     str,
    file_paths:   List[str],
    source:       str = "operator",
    auto_trigger_pz: bool = False,
) -> Dict[str, Any]:
    """
    Move + classify customs documents for a batch.

    Returns:
      {
        ok, batch_id, imported: [...], skipped: [...], audit_after, pz_triggered
      }
    """
    audit_path = _resolve_audit_path(batch_id)
    if not audit_path:
        return {"ok": False, "error": f"Batch {batch_id} not found"}

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    now_iso = datetime.now(timezone.utc).isoformat()

    customs_docs = audit.get("customs_docs") or {
        "files": [], "by_type": {},
    }

    imported: List[Dict[str, Any]] = []
    skipped:  List[Dict[str, Any]] = []
    triggers_pz = False

    for src in file_paths:
        try:
            cls = classify(Path(src).name)
            doc_type = cls["type"]
            saved_path = save_file(batch_id, src, doc_type)
            sync_result = sync_to_workdrive(batch_id, saved_path)
            entry = {
                "name":            saved_path.name,
                "path":            str(saved_path),
                "type":            doc_type,
                "confidence":      cls["confidence"],
                "size":            saved_path.stat().st_size,
                "imported_at":     now_iso,
                "source":          source,
                "workdrive":       sync_result,
            }
            customs_docs["files"].append(entry)
            customs_docs["by_type"].setdefault(doc_type, []).append(saved_path.name)
            imported.append(entry)
            if doc_type in ("customs_pdf", "customs_xml"):
                triggers_pz = True
        except FileNotFoundError as exc:
            skipped.append({"file": src, "error": str(exc)})
        except Exception as exc:
            skipped.append({"file": src, "error": f"{type(exc).__name__}: {exc}"})

    customs_docs["received"]    = True
    customs_docs["received_at"] = customs_docs.get("received_at") or now_iso
    customs_docs["files_count"] = len(customs_docs["files"])
    audit["customs_docs"]       = customs_docs

    write_json_atomic(audit_path, audit)

    try:
        tl.log_event(audit_path, "customs_docs_imported",
                     "operator" if source == "operator" else "system", source,
                     detail={"imported": len(imported), "skipped": len(skipped)})
    except Exception:
        pass

    pz_triggered = False
    if auto_trigger_pz and triggers_pz:
        pz_triggered = _try_trigger_pz(batch_id, audit_path)

    return {
        "ok":            True,
        "batch_id":      batch_id,
        "imported":      imported,
        "skipped":       skipped,
        "pz_triggered":  pz_triggered,
        "files_total":   customs_docs["files_count"],
    }


def list_customs_docs(batch_id: str) -> Dict[str, Any]:
    audit_path = _resolve_audit_path(batch_id)
    if not audit_path:
        return {"ok": False, "error": "batch not found"}
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    return {"ok": True, "batch_id": batch_id, "customs_docs": audit.get("customs_docs") or {}}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_audit_path(batch_id: str) -> Optional[Path]:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    return None


def _try_trigger_pz(batch_id: str, audit_path: Path) -> bool:
    """
    Best-effort PZ pipeline trigger. Calls the existing pz pipeline if
    available; logs and returns False on any failure (never raises).
    """
    try:
        from ..pipelines import pz as pz_pipeline
        # Existing pipeline expects audit + audit_path + trigger_source + actor
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        # The pipeline function name varies; guard with hasattr
        for fn_name in ("start_pz", "run_pz", "process_pz"):
            fn = getattr(pz_pipeline, fn_name, None)
            if callable(fn):
                fn(audit=audit, audit_path=audit_path,
                   trigger_source="sad_importer", actor="auto")
                return True
        log.info("[sad_importer] no PZ trigger function found in pz_pipeline")
        return False
    except Exception as exc:
        log.warning("[sad_importer] PZ auto-trigger failed: %s", exc)
        return False

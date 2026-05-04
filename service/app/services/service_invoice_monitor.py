"""
service_invoice_monitor.py — Track DHL + agency service invoices.

Push-based interface (operator/extractor POSTs the file paths). Files land
in `08_service_invoices/` and audit.service_invoices accumulates entries
with vendor classification (DHL / Ganther / ACS / unknown).

Used by the closure engine to know whether all expected invoices have arrived.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

from .shipment_folder_manager import save_file
from .workdrive_sync          import sync_to_workdrive

log = logging.getLogger(__name__)


_VENDOR_PATTERNS = [
    (re.compile(r"(?<![a-z])dhl(?![a-z])", re.IGNORECASE), "DHL"),
    (re.compile(r"ganther",            re.IGNORECASE), "Ganther"),
    (re.compile(r"acs[-_ ]?pedycja|acspedycja", re.IGNORECASE), "ACS"),
    (re.compile(r"agencja[-_ ]?celna", re.IGNORECASE), "ACS"),
]


def classify_vendor(filename: str) -> str:
    if not filename:
        return "unknown"
    for pat, vendor in _VENDOR_PATTERNS:
        if pat.search(filename):
            return vendor
    return "unknown"


def register_service_invoices(
    batch_id:   str,
    file_paths: List[str],
    source:     str = "operator",
) -> Dict[str, Any]:
    audit_path = _audit_path(batch_id)
    if not audit_path:
        return {"ok": False, "error": f"batch {batch_id} not found"}

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    now_iso = datetime.now(timezone.utc).isoformat()
    invoices = audit.get("service_invoices") or []
    existing_paths = {x.get("path") for x in invoices}

    imported: List[Dict[str, Any]] = []
    skipped:  List[Dict[str, Any]] = []
    for src in file_paths:
        try:
            saved = save_file(batch_id, src, "service_invoice")
            if str(saved) in existing_paths:
                continue
            wd = sync_to_workdrive(batch_id, saved)
            entry = {
                "name":         saved.name,
                "path":         str(saved),
                "vendor":       classify_vendor(saved.name),
                "size":         saved.stat().st_size,
                "imported_at":  now_iso,
                "source":       source,
                "workdrive":    wd,
            }
            invoices.append(entry)
            imported.append(entry)
        except FileNotFoundError as exc:
            skipped.append({"file": src, "error": str(exc)})
        except Exception as exc:
            skipped.append({"file": src, "error": f"{type(exc).__name__}: {exc}"})

    # If every supplied path failed, return an explicit error.
    # Do NOT touch audit flags — nothing was stored.
    if not imported and skipped:
        return {
            "ok":       False,
            "error":    "no_files_imported",
            "batch_id": batch_id,
            "imported": imported,
            "skipped":  skipped,
        }

    # Vendor presence flags — used by the closure engine
    vendors_present = {x["vendor"] for x in invoices}
    audit["service_invoices"]              = invoices
    audit["service_invoices_count"]        = len(invoices)
    audit["dhl_invoice_received"]          = "DHL"     in vendors_present
    audit["agency_invoice_received"]       = ("Ganther" in vendors_present
                                              or "ACS"   in vendors_present)
    write_json_atomic(audit_path, audit)

    try:
        tl.log_event(audit_path, "service_invoices_registered",
                     "operator" if source == "operator" else "system", source,
                     detail={"imported": len(imported), "skipped": len(skipped),
                             "vendors":  sorted(vendors_present)})
    except Exception:
        pass

    return {
        "ok":                      True,
        "batch_id":                batch_id,
        "imported":                imported,
        "skipped":                 skipped,
        "dhl_invoice_received":    audit["dhl_invoice_received"],
        "agency_invoice_received": audit["agency_invoice_received"],
        "total":                   len(invoices),
    }


def _audit_path(batch_id: str) -> Optional[Path]:
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return p
    return None

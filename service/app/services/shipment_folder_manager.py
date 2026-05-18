"""
shipment_folder_manager.py — Structured per-shipment storage.

Layout (under settings.storage_root / "shipments" / <batch_id>):
    01_invoices/
    02_awb/
    03_description/
    04_dhl_docs/
    05_agency_emails/
    06_customs_docs/
    07_pz_output/
    08_service_invoices/
    09_audit/

Public API:
    ensure_layout(batch_id) -> dict            (creates directories, returns map)
    folder_for(batch_id, doc_type) -> Path     (route a document type → folder)
    save_file(batch_id, src_path, doc_type) -> Path  (copy src → routed folder)
    list_layout(batch_id) -> dict              (file inventory by folder)
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List

from ..core.config import settings

log = logging.getLogger(__name__)


_FOLDERS: Dict[str, str] = {
    "01_invoices":         "invoice",
    "02_awb":              "awb",
    "03_description":      "polish_desc",
    "04_dhl_docs":         "dhl_doc",
    "05_agency_emails":    "agency_email",
    "06_customs_docs":     "customs_pdf",       # also accepts customs_xml/html
    "07_pz_output":        "pz_output",
    "08_service_invoices": "service_invoice",
    "09_audit":            "audit",
}

# doc_type → folder name
_TYPE_TO_FOLDER: Dict[str, str] = {
    "invoice":         "01_invoices",
    "awb":             "02_awb",
    "polish_desc":     "03_description",
    "dhl_doc":         "04_dhl_docs",
    "dhl_pdf":         "04_dhl_docs",
    "agency_email":    "05_agency_emails",
    "customs_pdf":     "06_customs_docs",
    "customs_xml":     "06_customs_docs",
    "customs_html":    "06_customs_docs",
    "duty_note":       "06_customs_docs",
    "payment":         "06_customs_docs",
    "pz_output":       "07_pz_output",
    "service_invoice": "08_service_invoices",
    "audit":           "09_audit",
    "other":           "06_customs_docs",
}


def _root(batch_id: str) -> Path:
    return settings.storage_root / "shipments" / batch_id


def ensure_layout(batch_id: str) -> Dict[str, Path]:
    """Create all 9 subfolders for a batch. Idempotent."""
    base = _root(batch_id)
    out: Dict[str, Path] = {}
    for folder in _FOLDERS:
        p = base / folder
        p.mkdir(parents=True, exist_ok=True)
        out[folder] = p
    return out


def folder_for(batch_id: str, doc_type: str) -> Path:
    """Resolve the folder for a given doc_type. Auto-creates layout."""
    layout = ensure_layout(batch_id)
    folder_name = _TYPE_TO_FOLDER.get(doc_type, "06_customs_docs")
    return layout[folder_name]


def save_file(batch_id: str, src_path: str, doc_type: str,
              dest_filename: str = "") -> Path:
    """
    Copy `src_path` into the routed folder for this batch + doc_type.

    Idempotent: if dest already exists with same size, returns existing path
    (no overwrite). If size differs, writes alongside as `<stem>_v2.<ext>`,
    `_v3`, etc. — never silently clobbers.
    """
    src = Path(src_path).resolve()
    # Issue #224: path traversal guard — source must reside under storage_root.
    # This prevents an authenticated operator from supplying arbitrary server-side
    # paths (e.g. /etc/passwd) and having them copied into the batch folder.
    allowed_root = settings.storage_root.resolve()
    try:
        src.relative_to(allowed_root)
    except ValueError:
        raise PermissionError(
            f"save_file: source path {src_path!r} is outside allowed storage root "
            f"({allowed_root}). Operator-supplied file paths must be under storage_root."
        )
    if not src.is_file():
        raise FileNotFoundError(f"Source file not found: {src_path}")
    dest_dir = folder_for(batch_id, doc_type)
    name = dest_filename or src.name
    dest = dest_dir / name

    if dest.exists():
        if dest.stat().st_size == src.stat().st_size:
            return dest   # same content (size match) — assume identical
        # Conflict: version suffix
        stem  = dest.stem
        ext   = dest.suffix
        v = 2
        while True:
            candidate = dest_dir / f"{stem}_v{v}{ext}"
            if not candidate.exists():
                dest = candidate
                break
            v += 1

    shutil.copy2(src, dest)
    log.info("[folder] copied %s → %s", src.name, dest)
    return dest


def list_layout(batch_id: str) -> Dict[str, List[str]]:
    """Return {folder_name: [filename, ...]} for the batch (filenames only)."""
    out: Dict[str, List[str]] = {}
    base = _root(batch_id)
    if not base.exists():
        return out
    for folder in _FOLDERS:
        p = base / folder
        if p.is_dir():
            out[folder] = sorted([f.name for f in p.iterdir() if f.is_file()])
        else:
            out[folder] = []
    return out

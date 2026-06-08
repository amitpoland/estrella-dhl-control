"""parser_diagnostic_writer.py — fingerprint capture for failed packing parses.

Writes a JSON artifact under
  <storage_root>/parser_diagnostics/<batch_id>/packing_diag_<ts>_<safe_filename>.json

containing the raw header rows + parser diagnostic so a future alias-expansion
pass can learn from real vendor formats.

Hard rule: every operation is non-fatal. On any exception this module logs a
WARNING and returns None — never propagates an error to the caller (intake
must not fail because of diagnostic write).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    """Sanitise a filename for inclusion in the artifact filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", (name or "anon"))[:120]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _collect_raw_header_rows(path: Path, file_type: str) -> List[Dict[str, Any]]:
    """Best-effort capture of the first 5 non-empty rows per sheet (Excel)
    or first table (PDF). Returns empty list on failure."""
    out: List[Dict[str, Any]] = []
    try:
        if file_type in (".xlsx", ".xls"):
            from .excel_reader import read_excel_rows as _read_excel_rows
            engine = "openpyxl" if file_type == ".xlsx" else "xlrd"
            try:
                import openpyxl as _opx
                wb = _opx.load_workbook(str(path), data_only=True, read_only=True) if engine == "openpyxl" else None
                sheet_name = wb.active.title if wb is not None else "<sheet>"
            except Exception:
                sheet_name = "<sheet>"
            rows = _read_excel_rows(path, engine)
            kept = 0
            for idx, row in enumerate(rows[:25]):
                cells = [str(c) if c is not None else "" for c in row]
                if not any(c.strip() for c in cells):
                    continue
                out.append({"sheet": sheet_name, "row_index": idx, "cells": cells[:40]})
                kept += 1
                if kept >= 5:
                    break
        elif file_type == ".pdf":
            import pdfplumber as _pp
            with _pp.open(str(path)) as pdf:
                for pi, page in enumerate(pdf.pages[:2]):
                    tables = page.extract_tables() or []
                    if not tables:
                        continue
                    for ri, row in enumerate(tables[0][:5]):
                        out.append({
                            "sheet":     f"page_{pi+1}",
                            "row_index": ri,
                            "cells":     [str(c) if c is not None else "" for c in row][:40],
                        })
                    if out:
                        break
    except Exception as exc:
        log.debug("packing diagnostic raw-header capture failed: %s", exc)
    return out


def _collect_preview(path: Path, file_type: str) -> List[Dict[str, Any]]:
    """First 20 rows (any content) for the artifact's first_20_rows_preview."""
    out: List[Dict[str, Any]] = []
    try:
        if file_type in (".xlsx", ".xls"):
            from .excel_reader import read_excel_rows as _read_excel_rows
            engine = "openpyxl" if file_type == ".xlsx" else "xlrd"
            try:
                import openpyxl as _opx
                wb = _opx.load_workbook(str(path), data_only=True, read_only=True) if engine == "openpyxl" else None
                sheet_name = wb.active.title if wb is not None else "<sheet>"
            except Exception:
                sheet_name = "<sheet>"
            rows = _read_excel_rows(path, engine)
            for idx, row in enumerate(rows[:20]):
                cells = [str(c) if c is not None else "" for c in row]
                out.append({"sheet": sheet_name, "row_index": idx, "cells": cells[:40]})
        elif file_type == ".pdf":
            import pdfplumber as _pp
            with _pp.open(str(path)) as pdf:
                page = pdf.pages[0] if pdf.pages else None
                tables = (page.extract_tables() or []) if page else []
                if tables:
                    for ri, row in enumerate(tables[0][:20]):
                        out.append({
                            "sheet":     "page_1",
                            "row_index": ri,
                            "cells":     [str(c) if c is not None else "" for c in row][:40],
                        })
    except Exception as exc:
        log.debug("packing diagnostic preview capture failed: %s", exc)
    return out


def write_packing_diagnostic_artifact(
    storage_root:      Path,
    batch_id:          str,
    document_id:       str,
    filename:          str,
    document_type:     str,
    source_path:       Path,
    parser_diagnostic: Dict[str, Any],
) -> Optional[Path]:
    """Write the artifact JSON. Returns the written path on success, None on
    failure. NEVER raises.

    Triggered by the parser-observability layer when a packing extraction
    yields zero rows OR raises an exception. Body is intentionally
    forgiving — every step is wrapped so disk full / permission denied /
    bad path will produce a log line but not break intake.
    """
    try:
        if not (storage_root and batch_id and filename):
            log.warning("packing diagnostic artifact: missing required args")
            return None
        dest_dir = Path(storage_root) / "parser_diagnostics" / batch_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        ts = _now_iso().replace(":", "-")
        artifact_name = f"packing_diag_{ts}_{_safe_name(filename)}.json"
        dest_path = dest_dir / artifact_name

        file_type = (parser_diagnostic or {}).get("file_type") or Path(filename).suffix.lower()
        raw_header_rows = _collect_raw_header_rows(source_path, file_type)
        preview         = _collect_preview(source_path, file_type)

        artifact: Dict[str, Any] = {
            "schema_version":        "1",
            "batch_id":              batch_id,
            "document_id":           document_id or "",
            "filename":              filename,
            "document_type":         document_type,
            "upload_timestamp":      _now_iso(),
            "workbook_sheet_names":  (parser_diagnostic or {}).get("workbook_sheet_names", []),
            "raw_header_rows":       raw_header_rows,
            "first_20_rows_preview": preview,
            "parser_diagnostic":     parser_diagnostic or {},
        }
        dest_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("packing diagnostic artifact written: %s", dest_path)
        return dest_path
    except Exception as exc:
        log.warning("packing diagnostic artifact write failed (non-fatal): %s", exc)
        return None


__all__ = ["write_packing_diagnostic_artifact"]

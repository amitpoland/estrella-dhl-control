"""
agency_sad_parser.py — Read-only SAD/PZC data extraction from agency documents.

Reads files already stored on disk (from agency_sad_monitor / operator upload),
runs them through the existing customs parser orchestrator, and writes a preview
dict to audit.agency_sad_parse.

Safety contract:
  - Never writes to audit.customs_declaration
  - Never triggers PZ processing
  - Never mutates clearance_status, status, or blocked
  - Idempotent: skips if status == "parsed" already
  - Fail-safe: wraps entire body in try/except; never crashes the caller
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..utils.io import write_json_atomic
from ..core import timeline as tl

log = logging.getLogger(__name__)


def parse_agency_sad(
    batch_id: str,
    audit_path: Path,
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract structured customs data from agency SAD/PZC documents.

    Returns:
      {"skipped": True}           — guard tripped, nothing written
      {"awaiting_file": True}     — docs registered by name only, bytes not on disk
      {"parsed": True}            — result written to audit.agency_sad_parse
      {"error": str}              — exception caught; audit untouched
    """
    try:
        # ── G3: Idempotency ────────────────────────────────────────────────────
        if (audit.get("agency_sad_parse") or {}).get("status") == "parsed":
            return {"skipped": True}

        # ── G4a: docs must be received ─────────────────────────────────────────
        docs = audit.get("agency_documents_received") or {}
        if not docs.get("received"):
            return {"skipped": True}

        # ── G4b: file bytes must exist on disk ─────────────────────────────────
        state_files = (audit.get("agency_documents_received_state") or {}).get("files") or []
        _PARSEABLE_TYPES = {"customs_pdf", "customs_xml", "customs_html"}
        valid_paths = [
            f["path"] for f in state_files
            if f.get("path") and f.get("type") in _PARSEABLE_TYPES and Path(f["path"]).exists()
        ]

        if not valid_paths:
            # Ingestor wrote only filename strings — bytes not yet on disk
            _write_atomic_safe(audit_path, audit, {
                "status":      "awaiting_file",
                "reason":      "file_bytes_not_on_disk",
                "parsed_at":   _now_iso(),
                "parse_version": 1,
            })
            return {"awaiting_file": True}

        # ── Parse via orchestrator ─────────────────────────────────────────────
        sad_dir = Path(valid_paths[0]).parent
        from .customs_parser_orchestrator import parse_customs_document
        result = parse_customs_document(batch_id, sad_dir, audit)

        mapped = result.get("mapped") or {}
        status = "parsed" if mapped.get("mrn") else "partial"

        parse_record: Dict[str, Any] = {
            "status":                status,
            "source":                result.get("source"),
            "confidence":            result.get("confidence"),
            "mrn":                   mapped.get("mrn"),
            "clearance_date":        mapped.get("clearance_date"),
            "duty_a00_pln":          mapped.get("duty_a00_pln"),
            "cn_code":               mapped.get("cn_code"),
            "customs_agent":         mapped.get("customs_agent"),
            "importer_name":         mapped.get("importer_name"),
            "goods_description":     mapped.get("goods_description"),
            "art33a":                mapped.get("art33a"),
            "corrections":           result.get("corrections") or [],
            "ai_supplemented_fields": result.get("ai_supplemented_fields") or [],
            "parsed_at":             _now_iso(),
            "parse_version":         1,
            "files_parsed":          valid_paths,
        }

        _write_atomic_safe(audit_path, audit, parse_record)

        try:
            tl.log_event(
                audit_path, "agency_sad_parsed", "monitor", "system",
                detail={
                    "mrn":        parse_record.get("mrn"),
                    "confidence": parse_record.get("confidence"),
                    "source":     parse_record.get("source"),
                    "files":      valid_paths,
                },
            )
        except Exception:
            pass

        log.info(
            "[agency_sad_parser] %s: %s mrn=%s source=%s confidence=%s",
            batch_id, status, parse_record.get("mrn"),
            parse_record.get("source"), parse_record.get("confidence"),
        )
        return {"parsed": True}

    except Exception as exc:
        log.warning("[agency_sad_parser] %s: unhandled error (non-fatal): %s", batch_id, exc)
        return {"error": str(exc)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic_safe(audit_path: Path, audit: Dict[str, Any], parse_record: Dict[str, Any]) -> None:
    """Re-read audit to pick up concurrent writes, then write agency_sad_parse."""
    import json
    live = json.loads(audit_path.read_text(encoding="utf-8"))
    live["agency_sad_parse"] = parse_record
    write_json_atomic(audit_path, live)

"""
cache_freshness.py — Detect stale audit.json / pz_rows.json caches.

The PZ row schema gained new required fields in 2026-05:
  - product_code        (invoice_no + "-" + line_position, 1-indexed)
  - line_position
  - nazwa_pl, nazwa_en  (bilingual product names)
  - nazwa               (canonical "PL / EN" form used by PDF/XLSX/clipboard)

Existing audit.json files written by older engine versions DO NOT carry these
fields. Consumers (dashboard, regeneration scripts, normalizer) MUST treat
those caches as stale and force a full regenerate from source documents
rather than re-rendering cached rows.

Truth source for the current schema version:
    service.app.services.export_service.ROW_SCHEMA_VERSION
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

CURRENT_ROW_SCHEMA_VERSION = "v2"

# Required fields a single row dict must carry when row_schema_version == "v2".
# Missing any of these → cache is stale, must regenerate from source.
_REQUIRED_ROW_FIELDS_V2 = ("product_code", "nazwa_pl", "nazwa_en", "nazwa")


def is_audit_stale(audit: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Return (is_stale, reason) for the given audit.json dict.

    A cache is stale when any of the following is true:
      1. row_schema_version is missing or older than CURRENT_ROW_SCHEMA_VERSION.
      2. Any row in audit['rows'] is missing a required v2 field.

    Atlas-style intake-draft audits have NEITHER ``rows`` nor a
    ``row_schema_version`` stamp — the engine simply has not been run
    on them yet. Those are not stale, just not-yet-generated; return
    (False, "") so the dashboard does not surface the misleading
    "schema (missing) → v2" banner on fresh drafts.

    The dashboard / regeneration entrypoints should call this BEFORE rendering
    the audit and force a full regenerate when stale=True.
    """
    if not isinstance(audit, dict):
        return True, "audit is not a dict"

    stamped = audit.get("row_schema_version", "")
    rows    = audit.get("rows")

    # Not-yet-engine-generated draft audit: no rows AND no stamp.
    # Treat as not stale — no cached rows to be stale against.
    if not stamped and (rows is None or rows == []):
        return False, ""

    if stamped != CURRENT_ROW_SCHEMA_VERSION:
        return True, (
            f"row_schema_version={stamped!r} (expected {CURRENT_ROW_SCHEMA_VERSION!r})"
        )

    rows = audit.get("rows") or []
    if not isinstance(rows, list):
        return True, "rows is not a list"

    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            return True, f"row[{i}] is not a dict"
        missing = [f for f in _REQUIRED_ROW_FIELDS_V2 if not r.get(f)]
        if missing:
            return True, f"row[{i}] missing fields: {missing}"

    return False, ""


def stale_field_summary(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Return a structured summary suitable for surfacing in API responses."""
    stale, reason = is_audit_stale(audit)
    rows = audit.get("rows") or []
    missing_per_row: List[Dict[str, Any]] = []
    if isinstance(rows, list):
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                continue
            miss = [f for f in _REQUIRED_ROW_FIELDS_V2 if not r.get(f)]
            if miss:
                missing_per_row.append({"row_index": i, "missing": miss})
    return {
        "stale":                       stale,
        "reason":                      reason,
        "row_schema_version":          audit.get("row_schema_version", ""),
        "current_row_schema_version":  CURRENT_ROW_SCHEMA_VERSION,
        "row_count":                   len(rows) if isinstance(rows, list) else 0,
        "rows_missing_fields":         missing_per_row,
        "regenerate_required":         stale,
    }

"""
agency_sad_decision.py — Evaluate whether agency SAD parse is safe for PZ.

Pure read-only evaluation. Never writes financial fields, never triggers PZ.

Reads:
  audit.agency_sad_parse     — from agency_sad_parser
  audit.customs_declaration  — from prior operator SAD upload / XML parse

Writes:
  audit.agency_sad_decision  — structured recommendation only

Safe-to-run conditions (all must pass):
  1. agency_sad_parse.status == "parsed"
  2. confidence != "low"
  3. If customs_declaration.mrn is set: must match agency_sad_parse.mrn
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..utils.io import write_json_atomic
from ..core import timeline as tl

log = logging.getLogger(__name__)


def evaluate_agency_sad(
    batch_id: str,
    audit_path: Path,
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluate parsed agency SAD against existing customs declaration.

    Returns the decision dict (also written to audit.agency_sad_decision).
    Never raises — wraps body in try/except, returns error dict on failure.
    """
    try:
        parsed = audit.get("agency_sad_parse") or {}
        decl   = audit.get("customs_declaration") or {}

        decision = _evaluate(parsed, decl)
        decision["evaluated_at"] = _now_iso()

        # Re-read to pick up concurrent writes before writing decision
        live = json.loads(audit_path.read_text(encoding="utf-8"))
        live["agency_sad_decision"] = decision
        write_json_atomic(audit_path, live)

        try:
            tl.log_event(
                audit_path, "agency_sad_decision", "monitor", "system",
                detail={
                    "safe_to_run_pz": decision["safe_to_run_pz"],
                    "reason":         decision["reason"],
                },
            )
        except Exception:
            pass

        log.info(
            "[agency_sad_decision] %s: safe=%s reason=%s",
            batch_id, decision["safe_to_run_pz"], decision["reason"],
        )
        return decision

    except Exception as exc:
        log.warning("[agency_sad_decision] %s: unhandled error (non-fatal): %s", batch_id, exc)
        return {"safe_to_run_pz": False, "reason": "engine_error", "error": str(exc)}


# ── Pure evaluation (no I/O) ──────────────────────────────────────────────────

def _norm(x: Any) -> str:
    """Normalize MRN for comparison: strip spaces, uppercase."""
    return (x or "").replace(" ", "").upper()


def _evaluate(parsed: Dict[str, Any], decl: Dict[str, Any]) -> Dict[str, Any]:
    """Stateless evaluation — testable without filesystem."""

    if parsed.get("status") != "parsed":
        return {"safe_to_run_pz": False, "reason": "not_parsed"}

    if parsed.get("confidence") == "low":
        return {"safe_to_run_pz": False, "reason": "low_confidence"}

    parsed_mrn = parsed.get("mrn")
    decl_mrn   = decl.get("mrn")
    mrn_match  = None

    if decl_mrn and parsed_mrn:
        mrn_match = _norm(decl_mrn) == _norm(parsed_mrn)
        if not mrn_match:
            return {
                "safe_to_run_pz": False,
                "reason":         "mrn_mismatch",
                "mrn_parsed":     parsed_mrn,
                "mrn_declared":   decl_mrn,
                "mrn_match":      False,
            }

    return {
        "safe_to_run_pz": True,
        "reason":         "validated",
        "mrn_parsed":     parsed_mrn,
        "mrn_declared":   decl_mrn,
        "mrn_match":      mrn_match,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

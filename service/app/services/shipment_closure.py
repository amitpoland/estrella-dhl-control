"""
shipment_closure.py — Final shipment-closure state machine.

A shipment becomes 'completed' (and audit.ready_for_accounting=true) when ALL
of these are true:

  1. customs_docs_received          (audit.customs_docs.received == True)
  2. PZ generated                   (audit.pz_generated == True OR pz file exists)
  3. agency invoice received        (audit.agency_invoice_received == True)
  4. DHL invoice received           (audit.dhl_invoice_received == True)

Public API:
    evaluate_closure(audit) -> dict        (read-only — returns checklist + ready)
    apply_closure(audit_path) -> dict      (writes audit.status=completed if ready)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)


def evaluate_closure(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Pure check — compute closure flags + readiness without mutating audit."""
    customs_docs_received = bool((audit.get("customs_docs") or {}).get("received"))
    pz_generated = (
        bool(audit.get("pz_generated"))
        or bool(audit.get("pz_filename"))
        or bool(audit.get("polish_desc_filename"))   # Polish desc counts as PZ-equivalent
    )
    agency_invoice = bool(audit.get("agency_invoice_received"))
    dhl_invoice    = bool(audit.get("dhl_invoice_received"))

    checks = {
        "customs_docs_received":  customs_docs_received,
        "pz_generated":           pz_generated,
        "agency_invoice_received": agency_invoice,
        "dhl_invoice_received":    dhl_invoice,
    }
    ready = all(checks.values())
    return {
        "ready":  ready,
        "checks": checks,
        "missing": [k for k, v in checks.items() if not v],
    }


def apply_closure(audit_path: Path, approved_by: str = "operator") -> Dict[str, Any]:
    """
    Read audit, evaluate closure, and if ready, mark completed.
    Idempotent — once status=completed, no further writes.
    """
    if not audit_path.is_file():
        return {"ok": False, "error": f"audit not found: {audit_path}"}

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") == "completed":
        return {"ok": True, "already_completed": True, "checks": evaluate_closure(audit)["checks"]}

    decision = evaluate_closure(audit)
    if not decision["ready"]:
        return {"ok": True, "ready": False, "missing": decision["missing"]}

    now_iso = datetime.now(timezone.utc).isoformat()
    audit["status"]                = "completed"
    audit["closed_at"]             = now_iso
    audit["ready_for_accounting"]  = True
    audit["closure_checks"]        = decision["checks"]
    audit["closure_approved_by"]   = approved_by
    write_json_atomic(audit_path, audit)

    try:
        tl.log_event(audit_path, "shipment_closed", "system", "closure_engine",
                     detail={"checks": decision["checks"], "closed_at": now_iso})
    except Exception:
        pass

    return {
        "ok":                   True,
        "ready":                True,
        "status":               "completed",
        "closed_at":            now_iso,
        "ready_for_accounting": True,
        "checks":               decision["checks"],
    }


def closure_for_batch(batch_id: str, approved_by: str = "operator") -> Dict[str, Any]:
    """Convenience wrapper: locate batch audit + apply_closure."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return apply_closure(p, approved_by=approved_by)
    return {"ok": False, "error": f"batch {batch_id} not found"}

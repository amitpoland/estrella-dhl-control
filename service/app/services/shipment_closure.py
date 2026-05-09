"""
shipment_closure.py — Final shipment-closure state machine.

A shipment becomes 'completed' (and audit.ready_for_accounting=true) when ALL
of these are true:

  1. customs_docs_received          (audit.customs_docs.received == True)
  2. PZ generated                   (audit.pz_generated == True OR pz file exists)

Service invoices (agency_invoice_received, dhl_invoice_received) are accounting
signals only.  Missing invoices do NOT block closure — they set
accounting_followup_required=True in the result and in the audit.

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
    # ── Hard blockers ──────────────────────────────────────────────────────────
    customs_docs_received = bool((audit.get("customs_docs") or {}).get("received"))
    pz_generated = (
        bool(audit.get("pz_generated"))
        or bool(audit.get("pz_filename"))
        or bool(audit.get("polish_desc_filename"))   # Polish desc counts as PZ-equivalent
    )

    checks = {
        "customs_docs_received": customs_docs_received,
        "pz_generated":          pz_generated,
    }
    ready = all(checks.values())

    # ── Accounting signals (non-blocking) ──────────────────────────────────────
    agency_invoice = bool(audit.get("agency_invoice_received"))
    dhl_invoice    = bool(audit.get("dhl_invoice_received"))

    accounting_checks = {
        "agency_invoice_received": agency_invoice,
        "dhl_invoice_received":    dhl_invoice,
    }
    invoice_status = "received" if (agency_invoice and dhl_invoice) else "pending_accounting"
    accounting_followup_required = invoice_status == "pending_accounting"

    return {
        "ready":                      ready,
        "checks":                     checks,
        "missing":                    [k for k, v in checks.items() if not v],
        "accounting_checks":          accounting_checks,
        "invoice_status":             invoice_status,
        "accounting_followup_required": accounting_followup_required,
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
    audit["status"]                       = "completed"
    audit["closed_at"]                    = now_iso
    audit["ready_for_accounting"]         = True
    audit["closure_checks"]               = decision["checks"]
    audit["closure_approved_by"]          = approved_by
    audit["accounting_checks"]            = decision["accounting_checks"]
    audit["invoice_status"]               = decision["invoice_status"]
    audit["accounting_followup_required"] = decision["accounting_followup_required"]
    write_json_atomic(audit_path, audit)

    try:
        tl.log_event(audit_path, "shipment_closed", "system", "closure_engine",
                     detail={"checks": decision["checks"], "closed_at": now_iso,
                             "accounting_followup_required": decision["accounting_followup_required"]})
    except Exception:
        pass

    return {
        "ok":                         True,
        "ready":                      True,
        "status":                     "completed",
        "closed_at":                  now_iso,
        "ready_for_accounting":       True,
        "checks":                     decision["checks"],
        "accounting_checks":          decision["accounting_checks"],
        "invoice_status":             decision["invoice_status"],
        "accounting_followup_required": decision["accounting_followup_required"],
    }


def closure_for_batch(batch_id: str, approved_by: str = "operator") -> Dict[str, Any]:
    """Convenience wrapper: locate batch audit + apply_closure."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            return apply_closure(p, approved_by=approved_by)
    return {"ok": False, "error": f"batch {batch_id} not found"}

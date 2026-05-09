"""
batch_readiness.py — Read-only aggregated batch readiness across all domains.

Aggregates four domain readiness signals into a single response:
  warehouse — packing completion vs warehouse scan coverage
  sales     — invoice linkage quality and missing scans
  wfirma    — reservation state (configured / created / ready / blocked)
  dhl       — customs clearance pipeline state

Rules:
  - NEVER writes to any DB
  - NEVER calls get_reservation_preview() (it has write side effects)
  - NEVER sends email or triggers side effects
  - All domain reads are wrapped in try/except for safe fallback

Overall priority order for next_step (highest urgency first):
  1. DHL SLA breach
  2. wFirma not configured
  3. warehouse not clean
  4. sales warnings / missing scans
  5. wFirma blocked
  6. DHL waiting (non-breach)
  7. ready for closure
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import warehouse_audit as waudit
from . import sales_linkage as sl
from . import wfirma_db as wfdb
from . import wfirma_capabilities as wfc
from .dhl_readiness import get_dhl_readiness


# ── Domain helpers ─────────────────────────────────────────────────────────────

def _warehouse_domain(batch_id: str) -> Dict[str, Any]:
    """
    Compute warehouse domain status.

    Status: 'clean' | 'partial' | 'empty' | 'n/a'
      clean   — all packing lines scanned, no invalid flows, no orphans
      partial — some scanned but gaps remain (missing | invalid_flow | orphan)
      empty   — packing lines exist but nothing scanned yet
      n/a     — no packing lines (batch not yet loaded)
    """
    try:
        completion  = waudit.get_batch_completion(batch_id)
        total       = completion.get("total_items") or 0
        scanned     = completion.get("scanned_items") or 0
        missing_cnt = completion.get("missing_items") or 0

        if total == 0:
            return {
                "status":  "n/a",
                "ready":   False,
                "message": "No packing lines found for this batch",
            }

        missing_scans  = waudit.get_missing_scans(batch_id)
        invalid_flows  = waudit.get_invalid_flows(batch_id)
        orphan_inv     = waudit.get_orphan_inventory(batch_id)

        n_missing = len(missing_scans)
        n_invalid = len(invalid_flows)
        n_orphan  = len(orphan_inv)

        if scanned == 0:
            return {
                "status":  "empty",
                "ready":   False,
                "message": f"{total} packing line(s) not yet scanned into warehouse",
            }

        if n_missing == 0 and n_invalid == 0 and n_orphan == 0:
            return {
                "status":  "clean",
                "ready":   True,
                "message": f"All {total} item(s) scanned and accounted for",
            }

        parts: List[str] = []
        if n_missing:
            parts.append(f"{n_missing} missing scan(s)")
        if n_invalid:
            parts.append(f"{n_invalid} invalid flow(s)")
        if n_orphan:
            parts.append(f"{n_orphan} orphan record(s)")
        return {
            "status":  "partial",
            "ready":   False,
            "message": "; ".join(parts),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "n/a", "ready": False, "message": f"Warehouse data unavailable: {exc}"}


def _sales_domain(batch_id: str) -> Dict[str, Any]:
    """
    Compute sales domain status.

    Status: 'ready' | 'warnings' | 'missing' | 'none'
      none     — no sales packing lines
      ready    — all items linked and invoice-ready
      warnings — audit warnings present but not fully blocking
      missing  — missing warehouse scans for linked items
    """
    try:
        result  = sl.get_sales_linkage(batch_id)
        items   = result.get("items") or []
        summary = result.get("summary") or {}

        if not items:
            return {
                "status":  "none",
                "ready":   False,
                "message": "No sales packing lines linked",
            }

        missing_scan    = summary.get("missing_scan") or 0
        audit_warnings  = result.get("audit_warnings") or []
        ready_for_inv   = result.get("ready_for_invoice", False)
        total_items     = summary.get("total") or len(items)

        if missing_scan > 0:
            return {
                "status":  "missing",
                "ready":   False,
                "message": f"{missing_scan}/{total_items} item(s) not yet scanned",
            }

        if audit_warnings:
            msg = audit_warnings[0] if len(audit_warnings) == 1 else (
                f"{len(audit_warnings)} audit warning(s): {audit_warnings[0]}"
            )
            return {
                "status":  "warnings",
                "ready":   False,
                "message": msg,
            }

        return {
            "status":  "ready",
            "ready":   True,
            "message": f"All {total_items} item(s) linked and invoice-ready",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "none", "ready": False, "message": f"Sales data unavailable: {exc}"}


def _wfirma_domain(batch_id: str) -> Dict[str, Any]:
    """
    Compute wFirma domain status.

    Reads capabilities and existing drafts ONLY — never calls get_reservation_preview()
    (which has write side effects).

    Status: 'ready' | 'blocked' | 'not_configured' | 'created' | 'none'
      not_configured — wFirma API credentials not set
      created        — at least one reservation already submitted successfully
      ready          — draft exists with ready_to_create=True
      blocked        — draft(s) exist but none are ready
      none           — no drafts for this batch
    """
    try:
        caps = wfc.get_capabilities()
        if not caps.get("api_configured"):
            return {
                "status":  "not_configured",
                "ready":   False,
                "message": "wFirma API credentials not configured",
            }

        if wfdb._db_path is None:
            return {
                "status":  "n/a",
                "ready":   False,
                "message": "wFirma database not initialised",
            }

        drafts = wfdb.list_reservation_drafts(batch_id)
        if not drafts:
            return {
                "status":  "none",
                "ready":   False,
                "message": "No wFirma reservation preview built yet",
            }

        # Check for already-created reservations
        created = [d for d in drafts if d.get("status") == "created" and d.get("wfirma_reservation_id")]
        if created:
            ids = ", ".join(d["wfirma_reservation_id"] for d in created)
            return {
                "status":  "created",
                "ready":   True,
                "message": f"Reservation already created: {ids}",
            }

        # Check for drafts ready to create
        ready_drafts = [d for d in drafts if d.get("ready_to_create")]
        if ready_drafts:
            n = len(ready_drafts)
            return {
                "status":  "ready",
                "ready":   True,
                "message": f"{n} draft(s) ready to submit to wFirma",
            }

        # Drafts exist but blocked
        return {
            "status":  "blocked",
            "ready":   False,
            "message": f"{len(drafts)} draft(s) not yet ready — check blocking reasons",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "n/a", "ready": False, "message": f"wFirma data unavailable: {exc}"}


def _dhl_domain(batch_id: str) -> Dict[str, Any]:
    """
    Compute DHL domain status from the audit-trail readiness helper.

    Status: the dhl_status string from get_dhl_readiness (7-state pipeline value).
    ready  = dhl_status == 'customs_cleared'
    """
    try:
        r          = get_dhl_readiness(batch_id)
        dhl_status   = r.get("dhl_status", "awaiting_start")
        sla_breach   = r.get("sla_breach", False)
        nra          = r.get("next_required_action") or ""
        days_out     = r.get("days_since_last_outbound")
        pz_generated = bool(r.get("pz_generated"))

        # `ready` is satisfied when customs is fully cleared OR the wFirma
        # PZ has already been generated. A PZ-generated batch has finished
        # the operator-actionable DHL work; later customs_cleared confirmation
        # is informational, not a blocker for downstream Proforma/closure.
        ready = (dhl_status == "customs_cleared") or pz_generated

        if sla_breach and days_out is not None:
            msg = f"SLA breach: no DHL response after {days_out:.1f} day(s) — {nra}"
        elif ready and pz_generated and dhl_status != "customs_cleared":
            msg = "wFirma PZ generated — customs clearance confirmation pending"
        elif ready:
            msg = "Customs clearance confirmed"
        elif dhl_status == "awaiting_start":
            msg = nra or "No DHL contact initiated"
        else:
            msg = nra or f"Pipeline at stage: {dhl_status}"

        return {
            "status":       dhl_status,
            "ready":        ready,
            "sla_breach":   sla_breach,
            "pz_generated": pz_generated,
            "message":      msg,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "n/a", "ready": False,
            "sla_breach": False,
            "message": f"DHL data unavailable: {exc}",
        }


# ── Overall next_step priority ─────────────────────────────────────────────────

def _next_step(
    wh: Dict[str, Any],
    sa: Dict[str, Any],
    wf: Dict[str, Any],
    dh: Dict[str, Any],
) -> str:
    """
    Return the most urgent next action across all domains.

    Priority (highest first):
      1. DHL SLA breach
      2. wFirma not configured
      3. warehouse not clean
      4. sales warnings / missing scans
      5. wFirma blocked
      6. DHL waiting (non-breach)
      7. ready for closure
    """
    # 1. DHL SLA breach
    if dh.get("sla_breach"):
        return f"Urgent: {dh['message']}"

    # 2. wFirma not configured
    if wf.get("status") == "not_configured":
        return "Configure wFirma API credentials before proceeding"

    # 3. Warehouse not clean
    if not wh.get("ready") and wh.get("status") not in ("n/a",):
        return f"Resolve warehouse issues: {wh['message']}"

    # 4. Sales warnings / missing scans
    if not sa.get("ready") and sa.get("status") not in ("none", "n/a"):
        return f"Resolve sales linkage: {sa['message']}"

    # 5. wFirma blocked
    if wf.get("status") == "blocked":
        return f"Resolve wFirma blocking: {wf['message']}"

    # 6. DHL waiting (non-cleared, non-breach)
    if not dh.get("ready"):
        dhl_msg = dh.get("message") or "DHL customs clearance pending"
        return f"DHL: {dhl_msg}"

    # 7. All good
    return "Batch is ready for closure"


# ── Public API ─────────────────────────────────────────────────────────────────

def get_batch_readiness(batch_id: str) -> Dict[str, Any]:
    """
    Return aggregated readiness across warehouse, sales, wFirma, and DHL domains.

    Pure read-only: no writes, no email sends, no side effects.

    Returns
    -------
    {
        "batch_id": str,
        "warehouse": {"status": str, "ready": bool, "message": str},
        "sales":     {"status": str, "ready": bool, "message": str},
        "wfirma":    {"status": str, "ready": bool, "message": str},
        "dhl":       {"status": str, "ready": bool, "sla_breach": bool, "message": str},
        "overall": {
            "ready_for_closure": bool,
            "blocked_domains":   list[str],
            "next_step":         str,
        }
    }
    """
    wh = _warehouse_domain(batch_id)
    sa = _sales_domain(batch_id)
    wf = _wfirma_domain(batch_id)
    dh = _dhl_domain(batch_id)

    blocked_domains: List[str] = []
    for name, domain in (("warehouse", wh), ("sales", sa), ("wfirma", wf), ("dhl", dh)):
        if not domain.get("ready", False):
            blocked_domains.append(name)

    ready_for_closure = len(blocked_domains) == 0

    return {
        "batch_id":  batch_id,
        "warehouse": wh,
        "sales":     sa,
        "wfirma":    wf,
        "dhl":       dh,
        "overall": {
            "ready_for_closure": ready_for_closure,
            "blocked_domains":   blocked_domains,
            "next_step":         _next_step(wh, sa, wf, dh),
        },
    }

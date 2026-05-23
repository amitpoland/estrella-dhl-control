"""
ai_advisory.py — Read-only AI advisory service (Phase 1 skeleton).

Class: R (read-only AI). See docs/ai-governance/ai-capability-map.md §1.

This module is deliberately deterministic in Phase 1. It computes a
plain-English "why is this workflow blocked?" explanation by reading
`batch_readiness.get_batch_readiness()` — which is already a pure
read-only authority — and re-shaping its output for an operator-facing
surface.

Phase 2 may add an LLM call inside `synthesise_explanation()` as a
strictly additive enhancement. The contract enforced here (no writes,
no `/execute` calls, no authority redefinition) carries forward
unchanged.

Forbidden by capability map §6 — do not add any of these:
  * imports of wfirma_writer / wfirma_create_*
  * imports of email_service.queue_email / send
  * direct calls to execute_action(...)
  * database writes
  * mutation of audit.json / timeline.json
  * HTTP calls to wFirma / DHL / carrier endpoints
  * re-derivation of financial truth or readiness
"""
from __future__ import annotations

from typing import Any, Dict, List

from .batch_readiness import get_batch_readiness


# ── Public contract ───────────────────────────────────────────────────────────

class AdvisoryError(Exception):
    """Raised when readiness cannot be loaded. The route maps this to 503."""


def explain_workflow_blockers(batch_id: str) -> Dict[str, Any]:
    """
    Return a read-only, operator-facing explanation of why a batch's
    workflow is currently blocked (or, if not blocked, why it is ready).

    Pure read-only: no writes, no email sends, no side effects.

    Returns
    -------
    {
        "batch_id":          str,
        "ready_for_closure": bool,
        "blocked_domains":   list[str],          # subset of warehouse/sales/wfirma/dhl
        "next_step":         str,                # mirrored from batch_readiness
        "blockers":          list[Blocker],      # one entry per blocked domain
        "summary":           str,                # plain-English synthesis
        "advisory_class":    "R",                # read-only by contract
        "source":            "batch_readiness",  # authority chain
        "llm_used":          False,              # Phase 1 contract
    }

    Blocker
    -------
    {
        "domain":  str,                # warehouse | sales | wfirma | dhl
        "status":  str,                # domain-specific status enum
        "message": str,                # message from batch_readiness
        "why":     str,                # plain-English expansion (deterministic)
        "what_unblocks_it": str,       # next-action hint (deterministic)
    }
    """
    if not batch_id or not isinstance(batch_id, str):
        raise AdvisoryError("batch_id must be a non-empty string")

    try:
        readiness = get_batch_readiness(batch_id)
    except Exception as exc:  # pragma: no cover — defensive
        raise AdvisoryError(f"readiness_load_failed: {exc!s}") from exc

    overall = readiness.get("overall") or {}
    blocked_domains: List[str] = list(overall.get("blocked_domains") or [])
    ready_for_closure: bool = bool(overall.get("ready_for_closure"))
    next_step: str = str(overall.get("next_step") or "")

    blockers: List[Dict[str, Any]] = []
    for domain in blocked_domains:
        d = readiness.get(domain) or {}
        blockers.append({
            "domain":           domain,
            "status":           str(d.get("status") or "unknown"),
            "message":          str(d.get("message") or ""),
            "why":              _why_for(domain, d),
            "what_unblocks_it": _unblock_hint_for(domain, d),
        })

    summary = synthesise_explanation(
        batch_id=batch_id,
        ready_for_closure=ready_for_closure,
        blockers=blockers,
        next_step=next_step,
    )

    return {
        "batch_id":          batch_id,
        "ready_for_closure": ready_for_closure,
        "blocked_domains":   blocked_domains,
        "next_step":         next_step,
        "blockers":          blockers,
        "summary":           summary,
        "advisory_class":    "R",
        "source":            "batch_readiness",
        "llm_used":          False,
    }


def synthesise_explanation(
    *,
    batch_id: str,
    ready_for_closure: bool,
    blockers: List[Dict[str, Any]],
    next_step: str,
) -> str:
    """
    Phase 1: deterministic plain-English synthesis.

    Phase 2 extension point: this is where an LLM call may be added,
    behind a feature flag, with prompt-injection mitigations. The
    function signature is stable: the caller passes only structured
    fields produced from authority output (never raw untrusted text
    from emails or documents).
    """
    if ready_for_closure:
        return (
            f"Batch {batch_id} is ready for closure. "
            "All four readiness domains (warehouse, sales, wFirma, DHL) report ready."
        )

    if not blockers:
        # Defensive: should not happen given the contract, but keep the surface honest.
        return (
            f"Batch {batch_id} reports not-ready but no blocked domains were identified. "
            "Refresh readiness and re-check."
        )

    parts: List[str] = [
        f"Batch {batch_id} is blocked in {len(blockers)} domain(s): "
        + ", ".join(b["domain"] for b in blockers)
        + "."
    ]
    for b in blockers:
        parts.append(
            f"- {b['domain']}: {b['message'] or b['status']} "
            f"→ {b['what_unblocks_it']}"
        )
    if next_step:
        parts.append(f"Next step: {next_step}")
    return "\n".join(parts)


# ── Deterministic per-domain explanations ─────────────────────────────────────

def _why_for(domain: str, d: Dict[str, Any]) -> str:
    """Plain-English expansion of *why* this domain is not ready."""
    status = str(d.get("status") or "unknown")
    if domain == "warehouse":
        return {
            "n/a":     "No packing lines have been loaded for this batch yet.",
            "empty":   "Packing lines exist but nothing has been scanned into the warehouse.",
            "partial": "Some items scanned, but missing scans, invalid flows, or orphan inventory remain.",
        }.get(status, "Warehouse domain reports a non-ready state.")
    if domain == "sales":
        return {
            "n/a":     "Sales linkage has not been built yet.",
            "partial": "Some sales lines are linked, but invoice gaps or missing scans remain.",
        }.get(status, "Sales domain reports a non-ready state.")
    if domain == "wfirma":
        return {
            "not_configured": "wFirma reservation has not been configured for this batch.",
            "blocked":        "wFirma reports a hard blocker (customer/product authority gap or fiscal guard).",
            "created":        "wFirma reservation created but not yet ready for adoption.",
        }.get(status, "wFirma domain reports a non-ready state.")
    if domain == "dhl":
        if d.get("sla_breach"):
            return "DHL clearance pipeline has breached its SLA — operator attention required."
        return "DHL clearance pipeline is waiting on an external event (SAD, agency reply, or carrier response)."
    return "Domain reports a non-ready state."


def _unblock_hint_for(domain: str, d: Dict[str, Any]) -> str:
    """Plain-English next-action hint for the operator (advisory only)."""
    status = str(d.get("status") or "unknown")
    if domain == "warehouse":
        if status == "n/a":
            return "Load the packing list for this batch."
        if status == "empty":
            return "Scan items into the warehouse."
        if status == "partial":
            return "Resolve missing scans, invalid flows, and orphans in the warehouse panel."
        return "Open the warehouse panel for this batch."
    if domain == "sales":
        return "Open the sales panel and complete invoice linkage / missing-scan resolution."
    if domain == "wfirma":
        if status == "not_configured":
            return "Open the wFirma panel and configure the reservation."
        if status == "blocked":
            return "Resolve customer/product authority gaps in the Customer Master / Product Master panels."
        return "Open the wFirma panel for next-step guidance."
    if domain == "dhl":
        if d.get("sla_breach"):
            return "Open the DHL clearance panel — SLA breached, escalation may be required."
        return "Open the DHL clearance panel; the next external event is awaited."
    return "Open the domain panel for next-step guidance."

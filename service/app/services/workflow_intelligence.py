"""Workflow Intelligence service -- Phase 9.

Aggregates batch-level workflow signals into a unified operator-facing
status report.  Consumers: batch_readiness, intelligence_graph,
master_data_intelligence (graph + document scores).

Hard invariants:
  - llm_used = False (structural, never changes)
  - PRAGMA query_only = ON on every direct DB connection
  - No INSERT / UPDATE / DELETE
  - No ai_gateway, no Anthropic, no LLM of any kind
  - No wFirma / DHL / customs / accounting / PZ write mutations
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── DB path (used only for AWB -> batch_id resolution) ───────────────────────

_DOC_DB: Path = settings.storage_root / "documents.db"

# ── Severity constants ────────────────────────────────────────────────────────

_HIGH   = "HIGH"
_MEDIUM = "MEDIUM"
_LOW    = "LOW"


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class WorkflowBlocker:
    """A hard blocker preventing closure in a specific domain."""
    domain:   str
    reason:   str
    severity: str   # HIGH | MEDIUM | LOW


@dataclass
class WorkflowWarning:
    """A soft warning that does not block closure but warrants attention."""
    domain: str
    reason: str


@dataclass
class WorkflowIntelligenceResult:
    """
    Unified workflow status for a single batch.

    workflow_status values:
      BLOCKED    -- at least one HIGH-severity blocker present
      INCOMPLETE -- no HIGH blockers; MEDIUM blockers or missing links present
      READY      -- no blockers, no missing critical links
      UNKNOWN    -- data fetch failed; cannot determine status
    """
    batch_id:                         str
    workflow_status:                  str        # BLOCKED | INCOMPLETE | READY | UNKNOWN
    blockers:                         List[WorkflowBlocker]
    warnings:                         List[WorkflowWarning]
    missing_links:                    List[str]
    readiness_impact:                 Dict[str, Any]
    recommended_next_operator_review: str
    llm_used:                         bool       # always False
    generated_at:                     str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":          self.batch_id,
            "workflow_status":   self.workflow_status,
            "blockers": [
                {"domain": b.domain, "reason": b.reason, "severity": b.severity}
                for b in self.blockers
            ],
            "warnings": [
                {"domain": w.domain, "reason": w.reason}
                for w in self.warnings
            ],
            "missing_links":   self.missing_links,
            "readiness_impact": self.readiness_impact,
            "recommended_next_operator_review": self.recommended_next_operator_review,
            "llm_used":         self.llm_used,
            "generated_at":     self.generated_at,
        }


# ── Private helpers ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ro_conn(db_path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection with PRAGMA query_only = ON."""
    con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def _resolve_batch_id_by_awb(
    awb: str,
    doc_db: Optional[Path] = None,
) -> Optional[str]:
    """
    Resolve an AWB to a batch_id via documents.db.
    Returns None when the DB is absent or no matching record exists.
    """
    db_path = doc_db or _DOC_DB
    if not db_path.exists():
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            "SELECT batch_id FROM shipment_documents"
            " WHERE awb = ? AND batch_id != '' LIMIT 1",
            (awb,),
        ).fetchone()
        con.close()
        if row:
            return row["batch_id"]
    except Exception as exc:  # noqa: BLE001
        log.debug("[workflow] _resolve_batch_id_by_awb(%s): %s", awb, exc)
    return None


def _classify_readiness_blockers(readiness: Dict[str, Any]) -> List[WorkflowBlocker]:
    """
    Convert batch_readiness domain statuses into WorkflowBlocker entries.

    Severity mapping:
      wfirma  not ready -> HIGH  (accounting record missing -- hard close blocker)
      sales   not ready -> HIGH  (no proforma/invoice -- hard close blocker)
      warehouse not ready -> MEDIUM (physical evidence incomplete)
      dhl     not ready + sla_breach -> HIGH ; not ready + no breach -> LOW
    """
    blockers: List[WorkflowBlocker] = []

    def _add(name: str, domain: Dict[str, Any], high_sev: str, low_sev: str) -> None:
        if not domain.get("ready", True):
            msg  = domain.get("message", f"{name} domain not ready")
            blockers.append(WorkflowBlocker(domain=name, reason=msg, severity=high_sev))

    wf_domain  = readiness.get("wfirma",    {})
    sa_domain  = readiness.get("sales",     {})
    wh_domain  = readiness.get("warehouse", {})
    dhl_domain = readiness.get("dhl",       {})

    _add("wfirma",    wf_domain,  _HIGH,   _HIGH)
    _add("sales",     sa_domain,  _HIGH,   _HIGH)
    _add("warehouse", wh_domain,  _MEDIUM, _MEDIUM)

    if not dhl_domain.get("ready", True):
        dhl_sev = _HIGH if dhl_domain.get("sla_breach", False) else _LOW
        blockers.append(WorkflowBlocker(
            domain="dhl",
            reason=dhl_domain.get("message", "DHL domain not ready"),
            severity=dhl_sev,
        ))

    return blockers


def _classify_graph_signals(
    graph_result: Any,
) -> tuple[List[WorkflowBlocker], List[WorkflowWarning], List[str]]:
    """
    Convert GraphResult (from intelligence_graph.build_batch_graph) into
    blockers, warnings, and missing_links.

    Returns (blockers, warnings, missing_links).
    """
    blockers: List[WorkflowBlocker] = []
    warnings: List[WorkflowWarning] = []
    missing:  List[str]             = []

    if graph_result is None:
        return blockers, warnings, missing

    # Missing links from link_completeness
    lc = graph_result.link_completeness
    if lc:
        missing_list = lc.missing if hasattr(lc, "missing") else []
        for link in missing_list:
            missing.append(link)
            if link in ("awb", "customs", "mrn"):
                warnings.append(WorkflowWarning(
                    domain="graph",
                    reason=f"Missing {link} link in intelligence graph",
                ))
            else:
                warnings.append(WorkflowWarning(
                    domain="graph",
                    reason=f"Missing {link} link in intelligence graph",
                ))

    # Conflicts escalate to HIGH blockers (two authoritative sources disagree)
    conflict_keys = getattr(graph_result, "conflict_keys", []) or []
    for ck in conflict_keys:
        blockers.append(WorkflowBlocker(
            domain="graph",
            reason=f"Authority conflict on '{ck}' — two sources disagree; operator review required",
            severity=_HIGH,
        ))

    return blockers, warnings, missing


def _derive_status(
    blockers: List[WorkflowBlocker],
    missing_links: List[str],
) -> str:
    """Derive workflow_status from blockers + missing links."""
    if any(b.severity == _HIGH for b in blockers):
        return "BLOCKED"
    if blockers or missing_links:
        return "INCOMPLETE"
    return "READY"


def _recommend_next_review(
    workflow_status: str,
    blockers: List[WorkflowBlocker],
    missing_links: List[str],
    readiness_next_step: str,
) -> str:
    """
    Produce a one-sentence operator recommendation.
    Deterministic priority: BLOCKED domains first, then missing links.
    """
    if workflow_status == "READY":
        return "No immediate action required. Batch is ready for closure."

    if workflow_status == "UNKNOWN":
        return "Workflow status could not be determined. Check service logs."

    # Priority: HIGH blockers first, domain order: wfirma > sales > warehouse > dhl > graph
    domain_priority = ["wfirma", "sales", "warehouse", "dhl", "graph"]

    for domain in domain_priority:
        for b in blockers:
            if b.domain == domain and b.severity == _HIGH:
                if domain == "wfirma":
                    return "Review wFirma PZ document status and confirm accounting record created."
                if domain == "sales":
                    return "Review proforma/invoice issuance — sales domain is blocking closure."
                if domain == "graph":
                    return (
                        f"Resolve authority conflict ({b.reason}) before closing this batch."
                    )

    # MEDIUM blockers
    for domain in domain_priority:
        for b in blockers:
            if b.domain == domain and b.severity == _MEDIUM:
                if domain == "warehouse":
                    return "Verify warehouse scan-in completion and packing list confirmation."

    # LOW blockers
    for b in blockers:
        if b.domain == "dhl" and b.severity == _LOW:
            return "Confirm DHL clearance status — shipment may still be in transit."

    # Missing links
    if "awb" in missing_links:
        return "Confirm DHL AWB with logistics team — AWB not linked in intelligence graph."
    if "customs" in missing_links or "mrn" in missing_links:
        return "Await customs MRN confirmation — customs declaration not yet linked."
    if missing_links:
        return (
            f"Resolve missing intelligence links ({', '.join(missing_links[:3])}) "
            "to improve batch coverage."
        )

    # Fall back to batch_readiness next_step
    if readiness_next_step:
        return readiness_next_step

    return "Review outstanding workflow signals before closing this batch."


# ── Public API ────────────────────────────────────────────────────────────────


def get_workflow_intelligence(
    batch_id: str,
    domain:   Optional[str] = None,
    *,
    doc_db: Optional[Path] = None,
) -> WorkflowIntelligenceResult:
    """
    Aggregate workflow signals for a single batch.

    Parameters
    ----------
    batch_id : str
        The batch identifier to analyse.
    domain : str, optional
        If given, filter blockers and warnings to this domain only.
        Valid: "warehouse" | "sales" | "wfirma" | "dhl" | "graph"
    doc_db : Path, optional
        Override documents.db path (test injection).

    Returns
    -------
    WorkflowIntelligenceResult
        Unified workflow status. llm_used is always False.
        Never raises -- returns UNKNOWN status on error.
    """
    llm_used = False  # structural invariant -- never changes

    blockers:      List[WorkflowBlocker] = []
    warnings:      List[WorkflowWarning] = []
    missing_links: List[str]             = []
    readiness_impact: Dict[str, Any]     = {}
    readiness_next_step: str             = ""

    # ── Signal 1: batch_readiness ─────────────────────────────────────────────
    try:
        from .batch_readiness import get_batch_readiness
        readiness = get_batch_readiness(batch_id)

        readiness_impact = {
            "warehouse":         readiness.get("warehouse", {}).get("ready", False),
            "sales":             readiness.get("sales",     {}).get("ready", False),
            "wfirma":            readiness.get("wfirma",    {}).get("ready", False),
            "dhl":               readiness.get("dhl",       {}).get("ready", False),
            "ready_for_closure": readiness.get("overall",   {}).get("ready_for_closure", False),
        }
        readiness_next_step = readiness.get("overall", {}).get("next_step", "")

        readiness_blockers = _classify_readiness_blockers(readiness)
        blockers.extend(readiness_blockers)

    except Exception as exc:  # noqa: BLE001
        log.warning("[workflow] batch_readiness failed for %s: %s", batch_id, exc)
        warnings.append(WorkflowWarning(
            domain="readiness",
            reason=f"Could not fetch readiness signals: {exc}",
        ))

    # ── Signal 2: intelligence_graph ─────────────────────────────────────────
    try:
        from .intelligence_graph import build_batch_graph
        graph_result = build_batch_graph(batch_id)

        g_blockers, g_warnings, g_missing = _classify_graph_signals(graph_result)
        blockers.extend(g_blockers)
        warnings.extend(g_warnings)
        missing_links.extend(g_missing)

    except Exception as exc:  # noqa: BLE001
        log.warning("[workflow] intelligence_graph failed for %s: %s", batch_id, exc)
        warnings.append(WorkflowWarning(
            domain="graph",
            reason=f"Could not fetch intelligence graph signals: {exc}",
        ))

    # ── Domain filter ────────────────────────────────────────────────────────
    if domain:
        blockers = [b for b in blockers if b.domain == domain]
        warnings = [w for w in warnings if w.domain == domain]
        # missing_links are graph-level, only filter if domain != "graph"
        if domain != "graph":
            missing_links = []

    # ── Derive status + recommendation ───────────────────────────────────────
    workflow_status = _derive_status(blockers, missing_links)
    recommendation  = _recommend_next_review(
        workflow_status, blockers, missing_links, readiness_next_step,
    )

    return WorkflowIntelligenceResult(
        batch_id=batch_id,
        workflow_status=workflow_status,
        blockers=blockers,
        warnings=warnings,
        missing_links=missing_links,
        readiness_impact=readiness_impact,
        recommended_next_operator_review=recommendation,
        llm_used=llm_used,
        generated_at=_now_iso(),
    )


def resolve_batch_id_from_awb(
    awb: str,
    doc_db: Optional[Path] = None,
) -> Optional[str]:
    """
    Public resolver: AWB -> batch_id via documents.db.
    Returns None when not found.
    Used by the route layer to convert awb query param to batch_id.
    """
    return _resolve_batch_id_by_awb(awb, doc_db=doc_db)

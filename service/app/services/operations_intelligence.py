"""Operations Intelligence service -- Phase 10.

Aggregates cross-batch operational metrics into a platform-level operations
health report.  Consumers: dashboard, periodic reporting, operator alerts.

Key metrics:
  total_batches          -- distinct batch_ids active in the period
  blocked_batches        -- batches with >= 1 HIGH-severity readiness blocker
  incomplete_batches     -- batches with MEDIUM/LOW issues but no HIGH blocker
  ready_batches          -- batches with no blockers
  document_coverage_score -- platform-wide from MDI document domain (0.0-1.0)
  master_data_score       -- MDI platform_score (0.0-1.0)
  graph_completeness_score -- MDI graph domain completeness (0.0-1.0)
  workflow_risk_summary   -- {"HIGH": n, "MEDIUM": n, "LOW": n} aggregate
  top_missing_evidence    -- most common absent document/evidence types
  top_master_data_gaps    -- from MDI top_recommendations (top 3)

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── DB path (batch enumeration from documents.db) ─────────────────────────────

_DOC_DB: Path = settings.storage_root / "documents.db"

# ── Period constants ──────────────────────────────────────────────────────────

_VALID_PERIODS = {"today", "7d", "30d"}
_DEFAULT_PERIOD = "7d"

# ── Default batch limit ───────────────────────────────────────────────────────

_DEFAULT_BATCH_LIMIT = 200


# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class OperationsIntelligenceResult:
    """
    Platform-level operations health report for a time period.

    workflow_risk_summary counts aggregate severity across all batches:
      HIGH   -- total HIGH-severity blocker instances across all batches
      MEDIUM -- total MEDIUM-severity blocker instances
      LOW    -- total LOW-severity blocker instances
    """
    period:                   str                  # today | 7d | 30d
    total_batches:            int
    blocked_batches:          int                  # >= 1 HIGH blocker
    incomplete_batches:       int                  # MEDIUM/LOW only; no HIGH
    ready_batches:            int                  # no blockers
    document_coverage_score:  float                # MDI document domain (0.0-1.0)
    master_data_score:        float                # MDI platform_score (0.0-1.0)
    graph_completeness_score: float                # MDI graph domain (0.0-1.0)
    workflow_risk_summary:    Dict[str, int]       # {"HIGH": n, "MEDIUM": n, "LOW": n}
    top_missing_evidence:     List[str]            # most common absent evidence types
    top_master_data_gaps:     List[str]            # MDI top_recommendations (top 3)
    llm_used:                 bool                 # always False
    generated_at:             str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period":                   self.period,
            "total_batches":            self.total_batches,
            "blocked_batches":          self.blocked_batches,
            "incomplete_batches":       self.incomplete_batches,
            "ready_batches":            self.ready_batches,
            "document_coverage_score":  round(self.document_coverage_score, 3),
            "master_data_score":        round(self.master_data_score, 3),
            "graph_completeness_score": round(self.graph_completeness_score, 3),
            "workflow_risk_summary":    self.workflow_risk_summary,
            "top_missing_evidence":     self.top_missing_evidence,
            "top_master_data_gaps":     self.top_master_data_gaps,
            "llm_used":                 self.llm_used,
            "generated_at":             self.generated_at,
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


def _period_cutoff(period: str) -> str:
    """Return ISO-8601 UTC cutoff string for the given period."""
    now = datetime.now(timezone.utc)
    if period == "today":
        cutoff = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
    else:  # 30d
        cutoff = now - timedelta(days=30)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _enumerate_batch_ids(
    period: str,
    limit: int,
    doc_db: Optional[Path] = None,
) -> List[str]:
    """
    Return a list of distinct batch_ids from documents.db created on or after
    the period cutoff.  Returns [] when DB is absent or period yields no data.
    """
    db_path = doc_db or _DOC_DB
    if not db_path.exists():
        log.debug("[ops-intel] documents.db not found at %s -- returning empty batch list", db_path)
        return []
    try:
        cutoff = _period_cutoff(period)
        con = _ro_conn(db_path)
        rows = con.execute(
            "SELECT DISTINCT batch_id FROM shipment_documents"
            " WHERE batch_id != '' AND created_at >= ?"
            " ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        con.close()
        return [r["batch_id"] for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("[ops-intel] _enumerate_batch_ids(%s): %s", period, exc)
        return []


def _classify_readiness_severity(readiness: Dict[str, Any]) -> str:
    """
    Return 'BLOCKED' | 'INCOMPLETE' | 'READY' based on readiness domain data.
    Uses the same severity mapping as workflow_intelligence.
    """
    wf_ready  = readiness.get("wfirma",    {}).get("ready", True)
    sa_ready  = readiness.get("sales",     {}).get("ready", True)
    wh_ready  = readiness.get("warehouse", {}).get("ready", True)
    dhl       = readiness.get("dhl",       {})
    dhl_ready = dhl.get("ready", True)
    dhl_breach = dhl.get("sla_breach", False)

    # HIGH blockers: wfirma/sales not ready, or dhl not ready + sla_breach
    has_high = (
        not wf_ready
        or not sa_ready
        or (not dhl_ready and dhl_breach)
    )
    if has_high:
        return "BLOCKED"

    # MEDIUM/LOW blockers: warehouse not ready, or dhl not ready (no breach)
    has_medium_low = not wh_ready or not dhl_ready
    if has_medium_low:
        return "INCOMPLETE"

    return "READY"


def _collect_missing_evidence(readiness: Dict[str, Any]) -> List[str]:
    """
    Return list of domain names that are not ready (evidence absent).
    Used to count which evidence types are most often missing.
    """
    missing = []
    for domain in ("warehouse", "sales", "wfirma", "dhl"):
        if not readiness.get(domain, {}).get("ready", True):
            missing.append(domain)
    return missing


def _get_platform_mdi_scores(
    domain: Optional[str] = None,
) -> Dict[str, float]:
    """
    Pull document_coverage_score, master_data_score, graph_completeness_score
    from master_data_intelligence.generate_report().
    Returns {"document": 0.0, "master_data": 0.0, "graph": 0.0} on failure.
    """
    defaults = {"document": 0.0, "master_data": 0.0, "graph": 0.0}
    try:
        from .master_data_intelligence import generate_report
        report = generate_report()
        return {
            "document":    getattr(report.document,  "completeness_score", 0.0),
            "master_data": getattr(report,            "platform_score",    0.0),
            "graph":       getattr(report.graph,     "completeness_score", 0.0),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("[ops-intel] _get_platform_mdi_scores: %s", exc)
        return defaults


def _aggregate_missing_evidence(counter: Dict[str, int], top_n: int = 5) -> List[str]:
    """Sort missing evidence types by frequency, return top N."""
    if not counter:
        return []
    return [k for k, _ in sorted(counter.items(), key=lambda x: -x[1])][:top_n]


# ── Public API ────────────────────────────────────────────────────────────────


def get_operations_intelligence(
    period: str = _DEFAULT_PERIOD,
    domain: Optional[str] = None,
    *,
    doc_db: Optional[Path] = None,
    batch_limit: int = _DEFAULT_BATCH_LIMIT,
) -> OperationsIntelligenceResult:
    """
    Aggregate cross-batch operational metrics for the given time period.

    Parameters
    ----------
    period : str
        Time window: "today" | "7d" | "30d". Filters batches by created_at
        in documents.db.
    domain : str, optional
        If given, restrict risk_summary and missing_evidence to one domain.
        Valid: "warehouse" | "sales" | "wfirma" | "dhl" | "graph" | "readiness"
    doc_db : Path, optional
        Override documents.db path (test injection).
    batch_limit : int
        Maximum batches to scan. Default 200. Prevents unbounded DB scans.

    Returns
    -------
    OperationsIntelligenceResult
        Platform-level operations report. llm_used is always False.
        Never raises -- returns zero-count result on error.
    """
    llm_used = False  # structural invariant -- never changes

    total_batches    = 0
    blocked_batches  = 0
    incomplete_batches = 0
    ready_batches    = 0
    workflow_risk_summary: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    missing_evidence_counter: Dict[str, int] = {}
    mdi_scores: Dict[str, float] = {"document": 0.0, "master_data": 0.0, "graph": 0.0}
    top_master_data_gaps: List[str] = []

    # ── Enumerate batch_ids from documents.db ─────────────────────────────────
    batch_ids = _enumerate_batch_ids(period, batch_limit, doc_db=doc_db)
    total_batches = len(batch_ids)

    # ── Per-batch readiness aggregation ───────────────────────────────────────
    if batch_ids:
        try:
            from .batch_readiness import get_batch_readiness
        except Exception as exc:  # noqa: BLE001
            log.warning("[ops-intel] could not import batch_readiness: %s", exc)
            get_batch_readiness = None  # type: ignore[assignment]

        for batch_id in batch_ids:
            if get_batch_readiness is None:
                break
            try:
                readiness = get_batch_readiness(batch_id)

                # Status classification
                status = _classify_readiness_severity(readiness)
                if status == "BLOCKED":
                    blocked_batches += 1
                    # Count HIGH-severity domains
                    if not readiness.get("wfirma", {}).get("ready", True):
                        workflow_risk_summary["HIGH"] += 1
                    if not readiness.get("sales", {}).get("ready", True):
                        workflow_risk_summary["HIGH"] += 1
                    dhl = readiness.get("dhl", {})
                    if not dhl.get("ready", True) and dhl.get("sla_breach", False):
                        workflow_risk_summary["HIGH"] += 1
                    # Warehouse is MEDIUM even in BLOCKED batches
                    if not readiness.get("warehouse", {}).get("ready", True):
                        workflow_risk_summary["MEDIUM"] += 1
                    # DHL no-breach LOW even in BLOCKED batches
                    if not readiness.get("dhl", {}).get("ready", True) and not readiness.get("dhl", {}).get("sla_breach", False):
                        workflow_risk_summary["LOW"] += 1

                elif status == "INCOMPLETE":
                    incomplete_batches += 1
                    if not readiness.get("warehouse", {}).get("ready", True):
                        workflow_risk_summary["MEDIUM"] += 1
                    dhl = readiness.get("dhl", {})
                    if not dhl.get("ready", True) and not dhl.get("sla_breach", False):
                        workflow_risk_summary["LOW"] += 1
                else:
                    ready_batches += 1

                # Track missing evidence types
                for ev_type in _collect_missing_evidence(readiness):
                    if domain is None or ev_type == domain:
                        missing_evidence_counter[ev_type] = (
                            missing_evidence_counter.get(ev_type, 0) + 1
                        )

            except Exception as exc:  # noqa: BLE001
                log.debug("[ops-intel] batch %s readiness failed: %s", batch_id, exc)

    # ── Platform MDI scores ───────────────────────────────────────────────────
    try:
        mdi_scores = _get_platform_mdi_scores(domain=domain)
    except Exception as exc:  # noqa: BLE001
        log.warning("[ops-intel] MDI scores failed: %s", exc)

    # ── MDI top recommendations (master data gaps) ────────────────────────────
    try:
        from .master_data_intelligence import generate_report
        report = generate_report()
        recs = getattr(report, "top_recommendations", []) or []
        top_master_data_gaps = recs[:3]
    except Exception as exc:  # noqa: BLE001
        log.warning("[ops-intel] MDI top_recommendations failed: %s", exc)

    # ── Top missing evidence types ────────────────────────────────────────────
    top_missing_evidence = _aggregate_missing_evidence(missing_evidence_counter, top_n=5)

    return OperationsIntelligenceResult(
        period=period,
        total_batches=total_batches,
        blocked_batches=blocked_batches,
        incomplete_batches=incomplete_batches,
        ready_batches=ready_batches,
        document_coverage_score=mdi_scores.get("document", 0.0),
        master_data_score=mdi_scores.get("master_data", 0.0),
        graph_completeness_score=mdi_scores.get("graph", 0.0),
        workflow_risk_summary=workflow_risk_summary,
        top_missing_evidence=top_missing_evidence,
        top_master_data_gaps=top_master_data_gaps,
        llm_used=llm_used,
        generated_at=_now_iso(),
    )

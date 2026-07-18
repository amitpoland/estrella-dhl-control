"""document_reconciler.py — Campaign-2 · Phase A2 (service-first).

READ-ONLY reconciliation authority for a proforma-derived invoice. Thin
orchestration over EXISTING authorities — it owns NO comparison logic and NO
persistence:

  local draft aggregate (proforma_invoice_link_db.get_draft_by_id)
        │  rebuild EXPECTED plan via the single conversion authority
        │  (routes_proforma._build_convert_candidate → FinalInvoicePlan)
        ▼
  ACTUAL wFirma invoice XML (wfirma_client.fetch_invoice_xml — read-only)
        ▼
  document_comparator.compare_invoice_plan   ← the ONLY comparison authority (A1)
        ▼
  stable backend view-model (classified gaps + comparison metadata)

Hard invariants (A2 Step 1):
  * NO route / feature flag / frontend / schema / persistence here.
  * NO DB write, NO wFirma write, NO audit-on-read.
  * Comparison is delegated EXCLUSIVELY to compare_invoice_plan — this module
    never re-implements the matrix (no second comparison authority).
  * When the draft has no linked wfirma_invoice_id there is no local expected
    projection → return no_local_authority; NEVER fabricate gaps.

The draft-load / expected-plan / actual-fetch steps are module-level
indirections so callers and tests can inject them; the production defaults reuse
the canonical authorities named above.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .document_comparator import compare_invoice_plan, Gap

COMPARISON_VERSION = "a2-1"

STATUS_NO_LOCAL_AUTHORITY = "no_local_authority"
STATUS_RECONCILED = "reconciled"


# ── canonical-authority indirections (production defaults; test-injectable) ───

def _default_db_path():
    from ..core.config import settings
    return settings.storage_root / "proforma_links.db"


def _load_draft(db_path, draft_id: int):
    """Existing draft authority — read-only."""
    from . import proforma_invoice_link_db as plink
    return plink.get_draft_by_id(db_path, draft_id)


def _build_expected_plan(draft):
    """Rebuild the EXPECTED FinalInvoicePlan via the single conversion authority.

    Re-fetches the source proforma read-only, parses it, and feeds it to
    routes_proforma._build_convert_candidate (the one conversion-resolution
    authority shared by disclose/execute/reconcile). Returns (plan, source_hash).
    Lazy import avoids an import-time service→route cycle.
    """
    from . import wfirma_client as wc
    from . import proforma_to_invoice as p2i
    from ..api.routes_proforma import _build_convert_candidate

    source_xml = wc.fetch_invoice_xml(draft.wfirma_proforma_id)
    snap = p2i.parse_proforma_xml(source_xml)
    candidate = _build_convert_candidate(draft, snap)
    return candidate["plan"], candidate.get("core_hash", "")


def _fetch_actual_xml(invoice_id: str) -> str:
    """Read-only fetch of the linked wFirma invoice."""
    from . import wfirma_client as wc
    return wc.fetch_invoice_xml(invoice_id)


# ── view-model helpers ────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _gap_to_dict(g: Gap) -> Dict[str, Any]:
    return {
        "field":             g.field,
        "expected":          _scalar(g.expected),
        "actual":            _scalar(g.actual),
        "authority":         g.authority,
        "severity":          g.severity,
        "resolution_policy": g.resolution_policy,
        "evidence_quality":  g.evidence_quality,
        "message":           g.message,
    }


def _scalar(v: Any) -> Any:
    """JSON-safe, deterministic representation of expected/actual values."""
    if isinstance(v, dict):
        return {k: str(v[k]) for k in sorted(v)}
    return str(v)


def _summarise(gaps: List[Gap]) -> Dict[str, Any]:
    by_sev: Dict[str, int] = {}
    by_pol: Dict[str, int] = {}
    for g in gaps:
        by_sev[g.severity] = by_sev.get(g.severity, 0) + 1
        by_pol[g.resolution_policy] = by_pol.get(g.resolution_policy, 0) + 1
    return {
        "total":        len(gaps),
        "by_severity":  by_sev,
        "by_policy":    by_pol,
        "has_blocking": any(g.blocking for g in gaps),
    }


def _no_local_authority(draft_id: int) -> Dict[str, Any]:
    return {
        "status":                  STATUS_NO_LOCAL_AUTHORITY,
        "reconciliation_available": False,
        "draft_id":                draft_id,
        "comparison_version":      COMPARISON_VERSION,
        "gaps":                    [],
        "gap_summary":             _summarise([]),
    }


# ── public authority ──────────────────────────────────────────────────────────

def build_reconciliation(
    draft_id: int,
    *,
    db_path=None,
    load_draft: Optional[Callable] = None,
    build_expected_plan: Optional[Callable] = None,
    fetch_actual_xml: Optional[Callable] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> Dict[str, Any]:
    """Produce the read-only reconciliation view-model for one draft.

    Returns ``no_local_authority`` (reconciliation_available=False) when the
    draft is absent or has no linked wfirma_invoice_id — never a fabricated gap
    report. Otherwise rebuilds the expected plan, fetches the actual invoice
    read-only, and delegates comparison to compare_invoice_plan.

    Pure orchestration: no DB write, no wFirma write, no audit. All I/O flows
    through the injectable indirections (defaults reuse the canonical authorities).
    """
    _load = load_draft or _load_draft
    _plan = build_expected_plan or _build_expected_plan
    _actual = fetch_actual_xml or _fetch_actual_xml
    _now = now or (lambda: datetime.now(timezone.utc))
    db = db_path or _default_db_path()

    draft = _load(db, draft_id)
    if draft is None or not getattr(draft, "wfirma_invoice_id", None):
        return _no_local_authority(draft_id)

    resolved_at = _now().isoformat()
    plan, source_hash = _plan(draft)
    actual_xml = _actual(draft.wfirma_invoice_id)
    result = compare_invoice_plan(plan, actual_xml)   # sole comparison authority
    compared_at = _now().isoformat()

    gaps = list(result.gaps)
    return {
        "status":                   STATUS_RECONCILED,
        "reconciliation_available": True,
        "draft_id":                 draft_id,
        "clean":                    not gaps,
        "comparison_version":       COMPARISON_VERSION,
        "local_source_hash":        source_hash or _sha256(repr(plan)),
        "remote_document_id":       str(draft.wfirma_invoice_id),
        "remote_snapshot_hash":     _sha256(actual_xml),
        "resolved_at":              resolved_at,
        "compared_at":              compared_at,
        "gaps":                     [_gap_to_dict(g) for g in gaps],
        "gap_summary":              _summarise(gaps),
    }

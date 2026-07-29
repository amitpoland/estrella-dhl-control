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
COMPARISON_VERSION_2B = "2b-1"

STATUS_NO_LOCAL_AUTHORITY = "no_local_authority"
STATUS_RECONCILED = "reconciled"
STATUS_PREVIEW_AVAILABLE = "preview_available"


# ── canonical-authority indirections (production defaults; test-injectable) ───

def _default_db_path():
    from ..core.config import settings
    return settings.storage_root / "proforma_links.db"


def _load_draft(db_path, draft_id: int):
    """Existing draft authority — read-only."""
    from . import proforma_invoice_link_db as plink
    return plink.get_draft_by_id(db_path, draft_id)


def _build_expected_plan(draft):
    """Default is a LOUD FAILURE, not an implementation.

    The EXPECTED-plan builder is INJECTED by the caller (the route), which owns the
    conversion authority (``_build_convert_candidate``). This service must NEVER
    import the route layer — that would invert the established service←route
    dependency (backend/reviewer finding). Production always injects
    ``build_expected_plan``; tests inject their own. This default only fires if a
    caller forgets, and it fails clearly rather than reaching into the api layer.
    """
    raise RuntimeError(
        "build_reconciliation requires build_expected_plan to be injected by the "
        "caller (the route owns the conversion authority; the service does not "
        "import the api layer)"
    )


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
    # Both remote ids are required to reconcile: wfirma_invoice_id names the ACTUAL
    # document, wfirma_proforma_id is the source the EXPECTED plan is rebuilt from.
    # A draft missing either has no reconcilable local authority — never a fabricated
    # gap, and never a raw fetch of a missing id (which would 500 in the route).
    if (draft is None
            or not getattr(draft, "wfirma_invoice_id", None)
            or not getattr(draft, "wfirma_proforma_id", None)):
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


# ── 2B: manual document-link preview (sibling; explicit remote id) ─────────────

def _serialize_plan_for_hash(plan) -> str:
    """Deterministic, order-stable serialization of the ENTIRE expected plan.

    Covers every fiscally-meaningful field so ANY change to the local expected
    plan between resolve and confirm changes the preview_hash (drift → 409).
    Security review W-5: the drift token must cover the whole plan, not just a
    description-covering subset.
    """
    def _line(li):
        return "/".join(str(getattr(li, a, "") or "") for a in
                        ("name", "good_id", "unit", "unit_count", "price", "vat_code_id"))
    head = "|".join(str(getattr(plan, a, "") or "") for a in
                    ("type", "contractor_id", "currency", "series_id",
                     "company_account_id", "contractor_receiver_id", "expected_total"))
    lines = ";".join(_line(li) for li in (getattr(plan, "contents", None) or []))
    return head + "||" + lines


def _preview_hash(plan, remote_id: str, remote_xml_hash: str,
                  document_type: str) -> str:
    """Opaque drift token binding the expected plan + remote snapshot + type +
    version. Never displayed; echoed only for the confirm round-trip."""
    parts = [
        COMPARISON_VERSION_2B,
        (document_type or ""),
        str(remote_id or ""),
        remote_xml_hash or "",
        _sha256(_serialize_plan_for_hash(plan)),
    ]
    return _sha256("|".join(parts))


def _candidate_summary(plan) -> Dict[str, Any]:
    """Operator-visible, ID-free summary of the expected plan. Security review
    W-3: NO series_id / company_account_id / contractor_id / good_id / raw XML."""
    return {
        "currency":       str(getattr(plan, "currency", "") or ""),
        "expected_total": str(getattr(plan, "expected_total", "") or ""),
        "line_count":     len(getattr(plan, "contents", None) or []),
    }


# Human labels for gap fields — the field NAME is a schema identifier (safe); the
# raw expected/actual VALUES and the comparator message (which embed wFirma entity
# ids) are NOT surfaced by the 2B preview. Security review W-6.
_GAP_FIELD_LABELS = {
    "contractor_id":          "Contractor",
    "contractor_receiver_id": "Ship-to contractor",
    "currency":               "Currency",
    "total":                  "Total",
    "series_id":              "Invoice series",
    "company_account_id":     "Bank account",
}


def _public_gap(g: Gap) -> Dict[str, Any]:
    """ID-free public view of one gap for the 2B preview: field/severity/policy/
    evidence_quality + a human label. Deliberately omits expected/actual/message
    because those carry raw wFirma entity ids (W-6)."""
    field = g.field
    label = _GAP_FIELD_LABELS.get(field, str(field).replace("_", " ").title())
    return {
        "field":             field,
        "severity":          g.severity,
        "resolution_policy": g.resolution_policy,
        "evidence_quality":  g.evidence_quality,
        "label":             f"{label} differs from the expected invoice",
    }


def _preview_no_local_authority(draft_id: int, document_type: str) -> Dict[str, Any]:
    base = _no_local_authority(draft_id)
    base["status"] = STATUS_NO_LOCAL_AUTHORITY
    base["document_type"] = document_type
    base["comparison_version"] = COMPARISON_VERSION_2B
    return base


def build_manual_link_preview(
    draft_id: int,
    *,
    remote_document_id: str,
    document_type: str,
    db_path=None,
    load_draft: Optional[Callable] = None,
    build_expected_plan: Optional[Callable] = None,
    fetch_actual_xml: Optional[Callable] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> Dict[str, Any]:
    """READ-ONLY preview for manually linking an OPERATOR-SPECIFIED remote wFirma
    document to a proforma-derived draft. Sibling of build_reconciliation.

    Unlike build_reconciliation (which reconciles the ALREADY-linked
    wfirma_invoice_id), this targets an explicit ``remote_document_id`` supplied
    by the operator — the pre-link preview. It requires only wfirma_proforma_id
    (the source the EXPECTED plan is rebuilt from); it does NOT read
    wfirma_invoice_id.

    Hard invariants (identical to A2): NO route/flag/frontend/schema here; NO DB
    write, NO wFirma write, NO audit-on-read. Comparison is delegated EXCLUSIVELY
    to compare_invoice_plan (A1 — the sole comparison authority); this function
    never re-implements the matrix. build_expected_plan MUST be injected by the
    route (the service never imports the api layer).

    Returns no_local_authority when the draft is absent or has no
    wfirma_proforma_id. Otherwise returns preview_available with an opaque
    preview_hash, an ID-free candidate summary, and the classified gaps.
    """
    _load = load_draft or _load_draft
    _plan = build_expected_plan or _build_expected_plan
    _actual = fetch_actual_xml or _fetch_actual_xml
    _now = now or (lambda: datetime.now(timezone.utc))
    db = db_path or _default_db_path()

    remote_id = (remote_document_id or "").strip()
    if not remote_id:
        raise ValueError("remote_document_id is required")

    draft = _load(db, draft_id)
    if draft is None or not getattr(draft, "wfirma_proforma_id", None):
        return _preview_no_local_authority(draft_id, document_type)

    resolved_at = _now().isoformat()
    plan, source_hash = _plan(draft)              # route-injected; re-fetches source proforma
    actual_xml = _actual(remote_id)               # read-only fetch of the SPECIFIED remote doc
    result = compare_invoice_plan(plan, actual_xml)   # A1 — sole comparison authority
    compared_at = _now().isoformat()

    remote_xml_hash = _sha256(actual_xml)
    gaps = list(result.gaps)
    return {
        "status":                   STATUS_PREVIEW_AVAILABLE,
        "reconciliation_available": True,
        "draft_id":                 draft_id,
        "document_type":            document_type,
        "clean":                    not gaps,
        "comparison_version":       COMPARISON_VERSION_2B,
        "local_source_hash":        source_hash or _sha256(_serialize_plan_for_hash(plan)),
        "remote_snapshot_hash":     remote_xml_hash,
        "preview_hash":             _preview_hash(plan, remote_id, remote_xml_hash, document_type),
        "resolved_at":              resolved_at,
        "compared_at":              compared_at,
        "candidate_summary":        _candidate_summary(plan),
        # ID-free public gaps (W-6): no raw expected/actual/message values.
        "gaps":                     [_public_gap(g) for g in gaps],
        "gap_summary":              _summarise(gaps),
    }

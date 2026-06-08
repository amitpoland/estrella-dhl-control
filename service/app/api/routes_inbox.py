"""
routes_inbox.py — Global action-queue aggregator for the /v2/ Inbox surface.

GET /api/v1/inbox
  Aggregates four read-only sources:
    A) Pending action proposals (all batches, require_api_key)
    B) Email queue pending items (require_admin — included ONLY when caller is admin)
    C) DHL evidence store — AWBs with unresolved customs actions (require_api_key)
    D) Proforma drafts needing attention — cross-batch draft queue (require_api_key)

HARD CONSTRAINTS (enforced by design, not just convention):
  - ZERO SIDE EFFECTS on GET.  Never calls scan_for_dhl_customs_emails.
    Never sends email.  Never mutates any lifecycle state.
  - Source C reads email_evidence_store.list_actionable_awbs() — a pure file read
    over storage/email_evidence/by_awb/*.json.  scan-inbox is NOT called on this
    path.  A refresh must NOT fire a Zoho/Gmail scan.
  - GRACEFUL DEGRADATION: each source is wrapped independently. One dead source
    returns a per-source {"ok": false, "error": "..."} marker; the inbox returns
    200 with the other sources intact — never 500 on one dead source.
  - primary_action.endpoint is a URL string ONLY.  The aggregator never calls
    approve/reject itself and never bypasses their idempotency guards.

Design doc: docs/inbox/sprint-2b-design.md (72d3f4d)
OQ-1: require_api_key base + role-conditional email queue for admins.
OQ-2: all operators see all clients' proposals (no per-client ACL today).
OQ-3: snooze omitted from v1.
OQ-4: email-queue items are read-only in the inbox; Send stays on the admin queue page.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, Depends, Query
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])
_auth = Depends(require_api_key)

# ── Priority constants ────────────────────────────────────────────────────────

PRIORITY_ORDER: Dict[str, int] = {"urgent": 0, "high": 1, "normal": 2, "info": 3}

_PROPOSAL_PRIORITY: Dict[str, str] = {
    "dhl_proactive_dispatch":      "urgent",
    "dhl_clearance_inquiry":       "urgent",
    "customs_description_mismatch":"high",
    "dhl_proactive_post_customs":  "high",
    "dhl_reply":                   "high",
    "dhl_followup":                "high",
    "customs_docs_ready":          "high",
    "agency_forward":              "normal",
    "agency_package":              "normal",
}

_PROPOSAL_TITLE: Dict[str, str] = {
    "dhl_proactive_dispatch":      "DHL proactive dispatch — clearance ready",
    "dhl_clearance_inquiry":       "DHL clearance inquiry",
    "customs_description_mismatch":"Customs description correction",
    "dhl_proactive_post_customs":  "Post-customs DHL notification",
    "dhl_reply":                   "DHL reply",
    "dhl_followup":                "DHL follow-up",
    "customs_docs_ready":          "Customs documents ready",
    "agency_forward":              "Agency forward after DHL",
    "agency_package":              "Agency email package",
}


# ── Source A: pending proposals (cross-batch file scan) ──────────────────────

def _collect_pending_proposals(outputs_dir: Path) -> List[Dict[str, Any]]:
    """Scan all batch audits and collect pending proposals as inbox items.

    Delegates the cross-batch file scan to the shared proposals_reader scanner —
    the single traversal authority also used by
    routes_action_proposals._resolve_proposal.  Importing from the services layer
    (not the routes module) avoids the circular import that previously justified a
    duplicated inline loop here.  The path stays strictly read-only: the scanner
    silently skips missing/unparseable audits and never raises.

    The pending_review filter and the inbox item envelope are applied here.  Output
    is identical to the previous inline scan: batches with no proposals contribute
    no items either way, and the batch traversal order is unchanged.
    """
    from ..services.proposals_reader import _iter_batch_proposals  # noqa: PLC0415

    items: List[Dict[str, Any]] = []
    for batch_id, _audit, proposals in _iter_batch_proposals(outputs_dir):
        for prop in proposals:
            if prop.get("status") != "pending_review":
                continue
            pid  = prop.get("proposal_id", "")
            ptype = prop.get("type", "unknown")
            items.append({
                "id":             f"proposal-{pid}",
                "type":           "proposal",
                "priority":       _PROPOSAL_PRIORITY.get(ptype, "normal"),
                "title":          _PROPOSAL_TITLE.get(ptype, f"Proposal: {ptype}"),
                "detail":         f"{batch_id} · {(prop.get('reason') or '')[:80]}",
                "age":            prop.get("created_at", ""),
                "actor":          "AI Bridge",
                "primary_action": "Approve",
                "linked_batch_id":batch_id,
                "actionable":     True,
                # URL string only — aggregator never calls this endpoint.
                # Approve/reject idempotency guards (proposal_write_lock,
                # terminal-status 409) remain owned by the action-proposals routes.
                "endpoint":       f"/api/v1/action-proposals/{pid}/approve",
            })
    return items


# ── Source B: email queue pending items (admin-only) ─────────────────────────

def _collect_email_queue_items() -> List[Dict[str, Any]]:
    """Return pending email queue items as inbox items.

    Caller MUST verify the user is admin before calling this function.
    get_all_emails() reads the queue from file/DB — zero external calls.

    OQ-4: items render read-only in the inbox; the "Send" action stays on the
    admin email-queue page, not wired inline here.
    """
    from ..services.email_service import get_all_emails  # noqa: PLC0415
    emails = get_all_emails(limit=50)
    items: List[Dict[str, Any]] = []
    for e in emails:
        if e.get("status") != "pending":
            continue
        items.append({
            "id":             f"email-{e.get('id', '')}",
            "type":           "email",
            "priority":       "high",
            "title":          e.get("subject") or "Queued email",
            "detail":         f"to: {e.get('to', '')}",
            "age":            e.get("queued_at") or e.get("created_at") or "",
            "actor":          "Email queue",
            "primary_action": "Review",
            "linked_batch_id":e.get("batch_id"),
            "actionable":     True,
            # OQ-4: no inline Send. endpoint=None signals "open admin queue page".
            "endpoint":       None,
        })
    return items


# ── Source C: DHL evidence (pure read, never triggers scan) ───────────────────

def _collect_dhl_cache_items() -> List[Dict[str, Any]]:
    """Return DHL AWBs with unresolved customs actions from the evidence store.

    HARD CONSTRAINT: reads email_evidence_store.list_actionable_awbs() ONLY.
    scan_for_dhl_customs_emails is NEVER called on this path.
    list_actionable_awbs() is a pure file read over storage/email_evidence/by_awb/*.json.
    It NEVER triggers a Zoho/Gmail scan, NEVER mutates evidence files.
    """
    from ..services.email_evidence_store import list_actionable_awbs  # noqa: PLC0415
    records = list_actionable_awbs(limit=20)
    items: List[Dict[str, Any]] = []
    for rec in records:
        awb = rec.get("awb", "")
        batch_ids = rec.get("batch_ids") or []
        items.append({
            "id":             f"dhl-{awb}",
            "type":           "customs",
            "priority":       rec.get("priority", "normal"),
            "title":          rec.get("next_action", f"DHL: AWB {awb}"),
            "detail":         f"AWB {awb} · {rec.get('message_count', 0)} messages",
            "age":            rec.get("last_event_at", ""),
            "actor":          "DHL evidence",
            "primary_action": "Review",
            "linked_batch_id":batch_ids[0] if batch_ids else None,
            "actionable":     True,
            # Review is an explicit operator action; not wired inline.
            "endpoint":       None,
        })
    return items


# ── Source D: Proforma drafts needing attention (pure DB read) ───────────────

_PROFORMA_DRAFT_PRIORITY: Dict[str, str] = {
    "post_failed": "high",
    "posting":     "high",
    "approved":    "normal",
    "editing":     "normal",
    "draft":       "normal",
}

_PROFORMA_DRAFT_TITLE: Dict[str, str] = {
    "post_failed": "Proforma post failed — retry needed",
    "posting":     "Proforma posting in progress",
    "approved":    "Proforma approved — ready to post",
    "editing":     "Proforma draft being edited",
    "draft":       "Proforma draft — review needed",
}


def _collect_proforma_draft_items() -> List[Dict[str, Any]]:
    """Return proforma drafts needing operator attention as inbox items.

    HARD CONSTRAINT: reads proforma_invoice_link_db.list_attention_drafts() ONLY.
    This is a pure SQLite read over proforma_drafts table.
    NEVER calls approve, post, cancel, convert, or any write endpoint.
    NEVER mutates any proforma state.
    """
    from ..services import proforma_invoice_link_db as pildb  # noqa: PLC0415

    db_path = settings.storage_root / "proforma_links.db"
    records = pildb.list_attention_drafts(db_path, limit=30)
    items: List[Dict[str, Any]] = []
    for rec in records:
        draft_id   = rec.get("id", "")
        batch_id   = rec.get("batch_id", "")
        client     = rec.get("client_name", "")
        state      = rec.get("draft_state", "draft")
        fullnumber = rec.get("fullnumber", "")

        title = _PROFORMA_DRAFT_TITLE.get(state, f"Proforma: {state}")
        detail_parts = [batch_id]
        if client:
            detail_parts.append(client)
        if fullnumber:
            detail_parts.append(fullnumber)

        items.append({
            "id":             f"proforma-draft-{draft_id}",
            "type":           "proforma_draft",
            "priority":       _PROFORMA_DRAFT_PRIORITY.get(state, "normal"),
            "title":          title,
            "detail":         " · ".join(detail_parts),
            "age":            rec.get("updated_at", ""),
            "actor":          "Proforma",
            "primary_action": "Review",
            "linked_batch_id":batch_id or None,
            "actionable":     True,
            # Inbox links to the proforma page; no inline action.
            "endpoint":       None,
        })
    return items


# ── GET /api/v1/inbox ─────────────────────────────────────────────────────────

@router.get("", dependencies=[_auth])
def get_inbox(
    priority:   Optional[str] = None,
    item_type:  Optional[str] = Query(default=None, alias="type"),
    limit:      int = 50,
    pz_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """
    Global action-queue inbox.

    Returns a merged, priority-sorted list of items from all four sources.
    Email queue items are included ONLY when the caller is an admin (OQ-1).
    GET is read-only — no Zoho scan, no email send, no lifecycle mutation,
    no proforma approve/post/cancel.

    Response shape:
      { ok, count, items: [{id,type,priority,title,detail,age,actor,
                             primary_action,linked_batch_id,actionable,endpoint}],
        sources: { proposals:{ok,count}, email_queue:{ok,count,note?},
                   dhl_cache:{ok,count}, proforma_drafts:{ok,count} } }
    """
    # Derive admin status from session for role-conditional email queue (OQ-1).
    # Uses get_current_user_optional (does not raise) — non-session callers are non-admin.
    is_admin = False
    if pz_session:
        try:
            from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
            user = get_current_user_optional(pz_session=pz_session)
            is_admin = bool(user and user.get("role") == "admin")
        except Exception:
            is_admin = False

    all_items: List[Dict[str, Any]] = []
    sources:   Dict[str, Any]       = {}
    outputs_dir = settings.storage_root / "outputs"

    # ── Source A: pending proposals (all batches) ─────────────────────────────
    try:
        a_items = _collect_pending_proposals(outputs_dir)
        all_items.extend(a_items)
        sources["proposals"] = {"ok": True, "count": len(a_items)}
    except Exception as exc:
        log.warning("[inbox] proposals source failed: %s", exc)
        sources["proposals"] = {"ok": False, "error": str(exc)[:200]}

    # ── Source B: email queue (admin-only — OQ-1) ─────────────────────────────
    if is_admin:
        try:
            b_items = _collect_email_queue_items()
            all_items.extend(b_items)
            sources["email_queue"] = {"ok": True, "count": len(b_items)}
        except Exception as exc:
            log.warning("[inbox] email_queue source failed: %s", exc)
            sources["email_queue"] = {"ok": False, "error": str(exc)[:200]}
    else:
        # Non-admin: source B entirely omitted. No partial data, no leakage.
        sources["email_queue"] = {"ok": True, "count": 0, "note": "not_admin"}

    # ── Source C: DHL evidence store (pure file read, NO scan triggered) ──────
    try:
        c_items = _collect_dhl_cache_items()
        all_items.extend(c_items)
        sources["dhl_cache"] = {"ok": True, "count": len(c_items)}
    except Exception as exc:
        log.warning("[inbox] dhl_cache source failed: %s", exc)
        sources["dhl_cache"] = {"ok": False, "error": str(exc)[:200]}

    # ── Source D: proforma drafts needing attention (pure DB read) ────────────
    try:
        d_items = _collect_proforma_draft_items()
        all_items.extend(d_items)
        sources["proforma_drafts"] = {"ok": True, "count": len(d_items)}
    except Exception as exc:
        log.warning("[inbox] proforma_drafts source failed: %s", exc)
        sources["proforma_drafts"] = {"ok": False, "error": str(exc)[:200]}

    # ── Sort: priority asc (urgent first), then age asc (oldest first) ────────
    all_items.sort(key=lambda it: (
        PRIORITY_ORDER.get(it.get("priority", "info"), 99),
        it.get("age", ""),
    ))

    # ── Filters ───────────────────────────────────────────────────────────────
    if priority and priority != "all":
        all_items = [i for i in all_items if i.get("priority") == priority]
    if item_type and item_type != "all":
        all_items = [i for i in all_items if i.get("type") == item_type]

    # ── Limit ─────────────────────────────────────────────────────────────────
    capped = max(1, min(limit, 100))
    all_items = all_items[:capped]

    return JSONResponse({
        "ok":      True,
        "count":   len(all_items),
        "items":   all_items,
        "sources": sources,
    })

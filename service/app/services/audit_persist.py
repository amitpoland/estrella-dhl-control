"""
audit_persist.py — Append-only audit hardening helpers.

Why
---
The read-time ``audit_evidence`` shim copes with stale audit.json shapes,
but it's a fallback. The on-disk file should reflect reality so that:

  • Operators reading audit.json see the truth without running the service.
  • Restart-safe recovery does not depend on the shim.
  • Downstream tools (timeline analytics, exports) see consistent state.

This module is the *write* counterpart: every successful operation that
generates new evidence appends to audit.json idempotently, using existing
timeline event infrastructure (``app.core.timeline.log_event``) and the
existing atomic file writer.

Rules
-----
- Append-only: never deletes timeline entries or rewrites historical
  structure. The only field this module *replaces* is ``audit.status``,
  and only when the canonical
  ``operational_authority.compute_effective_pz_status`` says the operator-
  effective state has changed.
- Idempotent: re-running every helper for the same input produces the
  same final audit.json (sets are de-duped on natural keys).
- Best-effort wiring: callers wrap with try/except — these helpers must
  never break a primary write path. Each helper logs failures and
  returns a structured result.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.io import write_json_atomic, read_json
from ..core import timeline as tl


log = logging.getLogger(__name__)


# Timeline event names emitted by this module. Centralised so tests/grep
# remain in lock-step with reality.
EV_PROFORMA_ISSUED                  = "proforma_issued"
EV_PROFORMA_CANCELLED               = "proforma_cancelled"
EV_PROFORMA_CONVERTED_TO_INVOICE    = "proforma_converted_to_invoice"
EV_INVOICE_APPROVAL_ATTEMPT         = "invoice_approval_attempt"
EV_INVENTORY_DIRECT_DISPATCH_MARKED = "inventory_direct_dispatch_marked"
EV_WFIRMA_PZ_MAPPING_REFRESHED      = "wfirma_pz_mapping_refreshed"


# ── Internal I/O ─────────────────────────────────────────────────────────────

def _load(audit_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read and return audit.json as a dict, or None on any failure.

    Uses ``read_json`` (utf-8-sig) so a UTF-8 BOM introduced by PowerShell
    or another non-Python tool is silently stripped and a WARNING is logged
    directing the operator to re-save the file with ``write_json_atomic``.
    """
    if not audit_path.exists():
        return None
    try:
        return read_json(audit_path)
    except Exception as exc:
        log.warning("audit_persist._load failed for %s: %s", audit_path, exc)
        return None


# ── Status normalisation (idempotent restamp) ────────────────────────────────

def restamp_pz_status_if_done(audit_path: Path) -> Dict[str, Any]:
    """
    If the operator-effective PZ state is done (``"success"``/``"partial"``)
    but the stored ``audit.status`` lags behind, persist the effective value.

    Uses the SAME canonical normalisation the wFirma export guard uses
    (``operational_authority.compute_effective_pz_status``) so on-disk and read-
    time gates stay aligned.

    Returns ``{"changed": bool, "stored_before": str, "stored_after": str,
                "effective": str, "reason": str}``.

    Never raises. Idempotent: a second call on a fresh-stamped audit
    short-circuits with ``changed=False``.
    """
    audit = _load(audit_path)
    if audit is None:
        return {"changed": False, "stored_before": "", "stored_after": "",
                "effective": "", "reason": "audit.json missing or unreadable"}

    stored = (audit.get("status") or "").strip()

    try:
        # A1 Stage 2: import the single canonical authority from the leaf
        # operational_authority (no route → helper → route cycle).
        from .operational_authority import (
            compute_effective_pz_status as _compute_effective_pz_status,
            PZ_DONE as _PZ_DONE,
        )
    except Exception as exc:
        return {"changed": False, "stored_before": stored, "stored_after": stored,
                "effective": "", "reason": f"normalisation helper unavailable: {exc}"}

    try:
        effective, _normalized = _compute_effective_pz_status(audit)
    except Exception as exc:
        return {"changed": False, "stored_before": stored, "stored_after": stored,
                "effective": "", "reason": f"normalisation failed: {exc}"}

    if effective not in _PZ_DONE:
        return {"changed": False, "stored_before": stored, "stored_after": stored,
                "effective": effective, "reason": "effective status not done"}
    if stored == effective:
        return {"changed": False, "stored_before": stored, "stored_after": stored,
                "effective": effective, "reason": "already aligned"}

    audit["status"] = effective
    try:
        write_json_atomic(audit_path, audit)
    except Exception as exc:
        log.error("audit_persist.restamp_pz_status_if_done write failed: %s", exc)
        return {"changed": False, "stored_before": stored, "stored_after": stored,
                "effective": effective, "reason": f"write failed: {exc}"}

    log.info("audit_persist: %s status %r → %r (effective normalisation)",
             audit_path.name, stored, effective)
    return {"changed": True, "stored_before": stored, "stored_after": effective,
            "effective": effective, "reason": "restamped"}


# ── Proforma issued ──────────────────────────────────────────────────────────

def record_proforma_issued(
    audit_path: Path,
    *,
    batch_id:                   str,
    client_name:                str,
    wfirma_proforma_id:         str,
    line_count:                 int,
    currency:                   str,
    operator:                   str,
    wfirma_proforma_fullnumber: str = "",
) -> Dict[str, Any]:
    """
    Append a ``proforma_issued`` entry to ``audit.proforma_issued[]`` and
    emit a timeline event of the same name. Idempotent on
    ``wfirma_proforma_id`` — a re-call with the same id is a no-op.

    Phase 9: ``wfirma_proforma_fullnumber`` is the canonical
    operator-readable number (e.g. ``"PROF 92/2026"``). Optional with an
    empty-string default so legacy callers continue to work; threaded
    into both the persisted entry and the timeline event detail.

    Returns ``{"appended": bool, "wfirma_proforma_id": str,
                "total_issued": int, "reason": str}``.
    """
    if not (wfirma_proforma_id or "").strip():
        return {"appended": False, "wfirma_proforma_id": "",
                "total_issued": 0, "reason": "wfirma_proforma_id is empty"}

    audit = _load(audit_path)
    if audit is None:
        return {"appended": False, "wfirma_proforma_id": wfirma_proforma_id,
                "total_issued": 0, "reason": "audit.json missing or unreadable"}

    issued: List[Dict[str, Any]] = audit.setdefault("proforma_issued", [])
    if any((row.get("wfirma_proforma_id") or "") == wfirma_proforma_id
           for row in issued):
        return {"appended": False, "wfirma_proforma_id": wfirma_proforma_id,
                "total_issued": len(issued), "reason": "already recorded"}

    issued.append({
        "client_name":                client_name,
        "wfirma_proforma_id":         wfirma_proforma_id,
        "wfirma_proforma_fullnumber": (wfirma_proforma_fullnumber or "").strip(),
        "line_count":                 int(line_count or 0),
        "currency":                   currency or "",
        "operator":                   operator or "",
    })

    try:
        write_json_atomic(audit_path, audit)
    except Exception as exc:
        log.error("audit_persist.record_proforma_issued write failed: %s", exc)
        return {"appended": False, "wfirma_proforma_id": wfirma_proforma_id,
                "total_issued": len(issued) - 1,
                "reason": f"write failed: {exc}"}

    # Append timeline event AFTER the list write succeeded so timeline +
    # canonical list stay in agreement.
    try:
        tl.log_event(
            audit_path, EV_PROFORMA_ISSUED, "system", "proforma",
            detail={
                "batch_id":                   batch_id,
                "client_name":                client_name,
                "wfirma_proforma_id":         wfirma_proforma_id,
                "wfirma_proforma_fullnumber": (wfirma_proforma_fullnumber or "").strip(),
                "line_count":                 int(line_count or 0),
                "currency":                   currency or "",
                "operator":                   operator or "",
            },
        )
    except Exception as exc:
        log.warning("audit_persist: timeline emit failed (non-fatal): %s", exc)

    return {"appended": True, "wfirma_proforma_id": wfirma_proforma_id,
            "total_issued": len(issued), "reason": "appended"}


# ── Proforma cancelled ───────────────────────────────────────────────────────

def record_proforma_cancelled(
    audit_path: Path,
    *,
    batch_id:                       str,
    client_name:                    str,
    deleted_wfirma_proforma_id:     str,
    replaced_by_wfirma_proforma_id: str = "",
    reason:                         str = "",
    operator:                       str = "",
    source:                         str = "cancel_for_reissue",
) -> Dict[str, Any]:
    """
    Append a ``proforma_cancelled`` timeline event recording that a
    wFirma Proforma was deleted (and optionally which active Proforma
    replaced it).

    Idempotent on ``(batch_id, deleted_wfirma_proforma_id)`` — a second
    call with the same pair is a no-op write-wise but reports
    ``appended=False``.

    Append-only contract:
      * Never modifies an existing timeline entry.
      * Never adds the cancelled id to ``audit.proforma_issued[]`` (that
        list is the source-of-truth for currently-active Proformas).

    Returns ``{"appended": bool, "deleted_wfirma_proforma_id": str,
                "reason": str}``.
    """
    if not (deleted_wfirma_proforma_id or "").strip():
        return {"appended": False,
                "deleted_wfirma_proforma_id": "",
                "reason": "deleted_wfirma_proforma_id is empty"}

    audit = _load(audit_path)
    if audit is None:
        return {"appended": False,
                "deleted_wfirma_proforma_id": deleted_wfirma_proforma_id,
                "reason": "audit.json missing or unreadable"}

    timeline = audit.get("timeline") or []
    if isinstance(timeline, list):
        for entry in timeline:
            if not isinstance(entry, dict):
                continue
            if entry.get("event") != EV_PROFORMA_CANCELLED:
                continue
            d = entry.get("detail") or {}
            if (d.get("batch_id") == batch_id
                    and (d.get("deleted_wfirma_proforma_id") or "")
                        == deleted_wfirma_proforma_id):
                return {
                    "appended": False,
                    "deleted_wfirma_proforma_id": deleted_wfirma_proforma_id,
                    "reason": "already recorded",
                }

    try:
        tl.log_event(
            audit_path, EV_PROFORMA_CANCELLED, "system",
            operator or "proforma",
            detail={
                "batch_id":                       batch_id,
                "client_name":                    client_name,
                "deleted_wfirma_proforma_id":     deleted_wfirma_proforma_id,
                "replaced_by_wfirma_proforma_id": (
                    replaced_by_wfirma_proforma_id or ""
                ),
                "reason":                         reason or "",
                "operator":                       operator or "",
                "source":                         source or "cancel_for_reissue",
            },
        )
    except Exception as exc:
        log.warning(
            "audit_persist.record_proforma_cancelled timeline emit "
            "failed (non-fatal): %s", exc,
        )
        return {"appended": False,
                "deleted_wfirma_proforma_id": deleted_wfirma_proforma_id,
                "reason": f"timeline emit failed: {exc}"}

    return {"appended": True,
            "deleted_wfirma_proforma_id": deleted_wfirma_proforma_id,
            "reason": "appended"}


# ── Proforma → Invoice conversion ───────────────────────────────────────────

def record_proforma_converted_to_invoice(
    audit_path: Path,
    *,
    batch_id:           str,
    client_name:        str,
    wfirma_proforma_id: str,
    wfirma_invoice_id:  str,
    invoice_number:     str,
    operator:           str = "",
    source:             str = "manual_convert_button",
) -> Dict[str, Any]:
    """
    Append a ``proforma_converted_to_invoice`` timeline event recording
    that an issued wFirma Proforma was converted into a final invoice.

    Idempotent on ``(batch_id, wfirma_proforma_id, wfirma_invoice_id)`` —
    a second call with the same triple is a no-op write-wise but reports
    ``appended=False, reason="already recorded"``.

    Append-only:
      * Never modifies an existing timeline entry.
      * Never touches ``audit.proforma_issued[]`` or
        ``audit.proforma_cancelled[]`` arrays — those are owned by their
        respective recorders.

    Returns ``{"appended": bool, "wfirma_proforma_id": str,
                "wfirma_invoice_id": str, "reason": str}``.
    """
    pid = (wfirma_proforma_id or "").strip()
    iid = (wfirma_invoice_id  or "").strip()
    if not pid:
        return {"appended": False,
                "wfirma_proforma_id": "",
                "wfirma_invoice_id":  iid,
                "reason": "wfirma_proforma_id is empty"}
    if not iid:
        return {"appended": False,
                "wfirma_proforma_id": pid,
                "wfirma_invoice_id":  "",
                "reason": "wfirma_invoice_id is empty"}

    audit = _load(audit_path)
    if audit is None:
        return {"appended": False,
                "wfirma_proforma_id": pid,
                "wfirma_invoice_id":  iid,
                "reason": "audit.json missing or unreadable"}

    timeline = audit.get("timeline") or []
    if isinstance(timeline, list):
        for entry in timeline:
            if not isinstance(entry, dict):
                continue
            if entry.get("event") != EV_PROFORMA_CONVERTED_TO_INVOICE:
                continue
            d = entry.get("detail") or {}
            if (d.get("batch_id") == batch_id
                    and (d.get("wfirma_proforma_id") or "") == pid
                    and (d.get("wfirma_invoice_id")  or "") == iid):
                return {
                    "appended": False,
                    "wfirma_proforma_id": pid,
                    "wfirma_invoice_id":  iid,
                    "reason": "already recorded",
                }

    try:
        tl.log_event(
            audit_path, EV_PROFORMA_CONVERTED_TO_INVOICE, "system",
            operator or "proforma",
            detail={
                "batch_id":           batch_id,
                "client_name":        client_name,
                "wfirma_proforma_id": pid,
                "wfirma_invoice_id":  iid,
                "invoice_number":     invoice_number or "",
                "operator":           operator or "",
                "source":             source or "manual_convert_button",
            },
        )
    except Exception as exc:
        log.warning(
            "audit_persist.record_proforma_converted_to_invoice timeline "
            "emit failed (non-fatal): %s", exc,
        )
        return {"appended": False,
                "wfirma_proforma_id": pid,
                "wfirma_invoice_id":  iid,
                "reason": f"timeline emit failed: {exc}"}

    return {"appended": True,
            "wfirma_proforma_id": pid,
            "wfirma_invoice_id":  iid,
            "reason": "appended"}


# ── Human invoice approval boundary ──────────────────────────────────────────

def record_invoice_approval_attempt(
    audit_path: Path,
    *,
    batch_id:           str,
    client_name:        str,
    wfirma_proforma_id: str,
    operator:           str,
    outcome:            str,   # "approved" | "blocked" | "failed"
    blocking_reason:    str = "",
) -> Dict[str, Any]:
    """
    Append an ``invoice_approval_attempt`` timeline event capturing every
    human attempt to convert a proforma to a final invoice.

    Records both successful approvals and blocked/failed attempts so the
    audit trail is complete regardless of outcome.

    Append-only (never modifies existing entries). Best-effort — callers
    must wrap with try/except.

    Returns ``{"appended": bool, "reason": str}``.
    """
    pid = (wfirma_proforma_id or "").strip()
    op  = (operator or "").strip()
    out = (outcome or "").strip()
    # pid is required for "approved" (we have a real proforma id at that point)
    # but may be empty for "blocked" / "failed" (blocked before draft lookup).
    if not pid and out == "approved":
        return {"appended": False, "reason": "wfirma_proforma_id is empty for approved outcome"}
    if out not in ("approved", "blocked", "failed"):
        out = "unknown"

    audit = _load(audit_path)
    if audit is None:
        # audit.json absent is normal for new batches — still try to write.
        audit = {}

    try:
        tl.log_event(
            audit_path, EV_INVOICE_APPROVAL_ATTEMPT, "system",
            op or "operator",
            detail={
                "batch_id":           batch_id,
                "client_name":        client_name,
                "wfirma_proforma_id": pid,
                "operator":           op,
                "outcome":            out,
                "blocking_reason":    blocking_reason or "",
                "human_approval_required": True,
            },
        )
    except Exception as exc:
        log.warning(
            "audit_persist.record_invoice_approval_attempt timeline "
            "emit failed (non-fatal): %s", exc,
        )
        return {"appended": False, "reason": f"timeline emit failed: {exc}"}

    return {"appended": True, "reason": "appended"}


# ── Direct-dispatch transition ───────────────────────────────────────────────

def record_inventory_direct_dispatch(
    audit_path: Path,
    *,
    batch_id:            str,
    scan_codes:          List[str],
    transitioned:        int,
    already_ready:       int,
    operator:            str,
    customer_allocation: str,
    customs_signals:     List[str],
    evidence_note:       str,
) -> Dict[str, Any]:
    """
    Emit a timeline event capturing a direct-dispatch promotion call.

    Append-only. Does NOT write any other audit field — the lifecycle
    state itself lives in ``warehouse.db.inventory_state``; this is a
    cross-reference proof in audit.json.

    Returns ``{"appended": bool, "reason": str}``.
    """
    if _load(audit_path) is None:
        return {"appended": False,
                "reason": "audit.json missing or unreadable"}
    if transitioned <= 0 and already_ready <= 0:
        return {"appended": False,
                "reason": "no transitioned or already_ready scan_codes"}
    try:
        tl.log_event(
            audit_path, EV_INVENTORY_DIRECT_DISPATCH_MARKED, "operator",
            operator or "operator",
            detail={
                "batch_id":            batch_id,
                "scan_codes":          list(scan_codes or []),
                "transitioned":        int(transitioned or 0),
                "already_ready":       int(already_ready or 0),
                "operator":            operator or "",
                "customer_allocation": customer_allocation or "",
                "customs_signals":     list(customs_signals or []),
                "evidence_note":       (evidence_note or "")[:500],
            },
        )
    except Exception as exc:
        log.warning("audit_persist.record_inventory_direct_dispatch failed: %s", exc)
        return {"appended": False, "reason": f"timeline emit failed: {exc}"}
    return {"appended": True, "reason": "appended"}


# ── wFirma PZ canonical mapping ──────────────────────────────────────────────

def record_wfirma_pz_mapping(
    audit_path: Path,
    *,
    wfirma_pz_doc_id:     str,
    wfirma_pz_fullnumber: str,
    source:               str = "created_via_app",
    operator:             str = "",
) -> Dict[str, Any]:
    """
    Stamp the canonical wFirma PZ mapping fields under
    ``audit.wfirma_export``: ``wfirma_pz_doc_id``,
    ``wfirma_pz_fullnumber``, and ``pz_mapped_at`` (UTC ISO timestamp).
    Preserves any pre-existing ``pz_source`` and ``pz_created_at`` —
    those are stamped by ``_patch_pz_doc_id`` at create time and must
    not be overwritten by a later refresh.

    Idempotent: a second call with identical (doc_id, fullnumber) is a
    no-op write-wise but always emits a timeline event so the operator
    can see when a refresh was last attempted. Returns ``{"changed":
    bool, "before": dict, "after": dict, "reason": str}``.

    Why a dedicated helper
    ----------------------
    The dashboard and downstream tooling want a single canonical source
    for both the numeric id and the human-readable PZ number. Splitting
    them across audit fields and timeline events meant the operator
    sometimes saw "PZ 12/3/2026" from one read path and a numeric id
    from another. This helper enforces one place for both, so the
    "Confirm PZ Number" manual fallback can hide cleanly.
    """
    audit = _load(audit_path)
    if audit is None:
        return {"changed": False, "before": {}, "after": {},
                "reason": "audit.json missing or unreadable"}

    doc_id   = (wfirma_pz_doc_id or "").strip()
    fullnum  = (wfirma_pz_fullnumber or "").strip()
    if not doc_id and not fullnum:
        return {"changed": False, "before": {}, "after": {},
                "reason": "doc_id and fullnumber both empty"}

    before = dict(audit.get("wfirma_export") or {})
    after  = dict(before)
    if doc_id:
        after["wfirma_pz_doc_id"] = doc_id
    if fullnum:
        after["wfirma_pz_fullnumber"] = fullnum
    # Preserve any pre-existing source / create timestamp; only set
    # source / mapped_at when missing.
    if not (after.get("pz_source") or "").strip():
        after["pz_source"] = source or "refresh_mapping"
    after["pz_mapped_at"] = _now_iso()

    changed = (
        before.get("wfirma_pz_doc_id")     != after.get("wfirma_pz_doc_id") or
        before.get("wfirma_pz_fullnumber") != after.get("wfirma_pz_fullnumber")
    )
    if changed:
        audit["wfirma_export"] = after
        try:
            write_json_atomic(audit_path, audit)
        except Exception as exc:
            return {"changed": False, "before": before, "after": after,
                    "reason": f"write failed: {exc}"}

    # Always emit a timeline event so the operator has an audit trail of
    # mapping refreshes (especially for historical batches).
    try:
        tl.log_event(
            audit_path, EV_WFIRMA_PZ_MAPPING_REFRESHED, "system",
            operator or "wfirma",
            detail={
                "wfirma_pz_doc_id":     doc_id,
                "wfirma_pz_fullnumber": fullnum,
                "source":               source,
                "operator":             operator or "",
                "changed":              bool(changed),
            },
        )
    except Exception as exc:
        log.warning("audit_persist.record_wfirma_pz_mapping timeline "
                    "emit failed (non-fatal): %s", exc)

    return {"changed": bool(changed), "before": before, "after": after,
            "reason": "stamped" if changed else "already aligned"}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── One-shot reconciliation (for stale audits) ───────────────────────────────

def reconcile_from_timeline(audit_path: Path) -> Dict[str, Any]:
    """
    Idempotent reconciliation pass: walk the timeline and refresh
    canonical fields from event evidence WITHOUT mutating the timeline
    itself. Specifically:

      - If ``wfirma_export.wfirma_pz_doc_id`` is empty but a
        ``wfirma_pz_created`` timeline event carries one, copy it across
        (and stamp ``pz_source="created_via_app"`` if missing).
      - Then call ``restamp_pz_status_if_done`` so a stale
        ``status="failed"`` flips to ``"partial"`` once evidence
        supports it.

    Safe to call repeatedly. Designed for one-shot recovery on legacy
    batches whose audit lagged behind real wFirma state.
    """
    audit = _load(audit_path)
    if audit is None:
        return {"changed": False, "reason": "audit.json missing or unreadable"}

    actions: List[str] = []
    wfirma_export = dict(audit.get("wfirma_export") or {})
    if not (wfirma_export.get("wfirma_pz_doc_id") or "").strip():
        timeline = audit.get("timeline") or []
        for entry in timeline:
            if not isinstance(entry, dict): continue
            if entry.get("event") != "wfirma_pz_created": continue
            doc_id = ((entry.get("detail") or {}).get("wfirma_pz_doc_id") or "").strip()
            if doc_id:
                wfirma_export["wfirma_pz_doc_id"] = doc_id
                wfirma_export.setdefault("pz_source",     "created_via_app")
                wfirma_export.setdefault("pz_created_at", entry.get("ts") or "")
                audit["wfirma_export"] = wfirma_export
                actions.append("copied_wfirma_pz_doc_id_from_timeline")
                break

    if actions:
        try:
            write_json_atomic(audit_path, audit)
        except Exception as exc:
            return {"changed": False, "reason": f"write failed: {exc}",
                    "actions": actions}

    status_result = restamp_pz_status_if_done(audit_path)
    if status_result.get("changed"):
        actions.append(f"status_restamped:{status_result.get('stored_after')}")

    return {"changed": bool(actions), "actions": actions, "reason": "ok"}

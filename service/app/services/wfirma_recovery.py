"""
wfirma_recovery.py — Infrastructure for wFirma action-proposal recovery.

Creates proposals stored in audit.json["action_proposals"] with the
wfirma_action channel. These are distinct from email proposals: they
carry a `context` block (data for the operator card) and a
`resolution_data` block (data collected at resolve time). Resolving
them executes a backend action (retry / PATCH master / adopt) rather
than queuing an email.

CREATION GATE: settings.wfirma_recovery_enabled_types is a comma-separated
set of allowed type strings. If a type is not in that set the dead-end
returns its existing bare error UNCHANGED — this file is not called.
Production default is "" (empty = no proposals created).

All functions are pure-Python helpers; HTTP handling lives in
routes_action_proposals.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set


# ── Channel constant ──────────────────────────────────────────────────────────

WFIRMA_CHANNEL = "wfirma_action"

# Statuses added by this system (extend the existing proposal lifecycle)
STATUS_RESOLVING = "resolving"   # resolve in progress (set before action executes)
STATUS_RESOLVED  = "resolved"    # action completed successfully


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def recovery_enabled_types() -> Set[str]:
    """Return the set of wFirma action proposal types currently permitted.

    Reads settings.wfirma_recovery_enabled_types (comma-separated).
    Empty string → empty set → no proposals created anywhere.
    """
    from ..core.config import settings  # lazy to avoid startup circular dep
    raw = (settings.wfirma_recovery_enabled_types or "").strip()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def create_wfirma_proposal(
    audit:            Dict[str, Any],
    batch_id:         str,
    proposal_type:    str,
    context:          Dict[str, Any],
    resolution_data:  Dict[str, Any],
    reason:           str = "",
) -> Dict[str, Any]:
    """
    Insert a wfirma_action proposal into audit["action_proposals"].

    Deduplication: if an active proposal of the same type already exists
    (status in {pending_review, resolving}) return it unchanged — one
    active proposal per type per batch.

    The proposal carries:
      - channel: "wfirma_action"  ← discriminator from email proposals
      - context: operator-facing display data (proforma#, customer, etc.)
      - resolution_data: mutable slot filled in by /resolve body

    Does NOT write audit to disk — caller owns the audit lifecycle.
    """
    proposals: list = audit.setdefault("action_proposals", [])

    _active = {"pending_review", STATUS_RESOLVING}
    for existing in proposals:
        if (existing.get("type") == proposal_type
                and existing.get("channel") == WFIRMA_CHANNEL
                and existing.get("status") in _active):
            return existing

    proposal: Dict[str, Any] = {
        "proposal_id":        str(uuid.uuid4()),
        "type":               proposal_type,
        "channel":            WFIRMA_CHANNEL,
        "batch_id":           batch_id,
        "status":             "pending_review",
        "reason":             reason or f"wFirma recovery needed: {proposal_type}",
        "confidence":         "high",
        "context":            context,
        "resolution_data":    resolution_data,
        "created_at":         _now_iso(),
        "resolved_at":        None,
        "resolved_by":        None,
        "resolution_result":  None,
        # Fields kept compatible with existing email proposal schema so
        # the inbox list endpoint returns them uniformly.
        "draft":              {},       # no email draft for wfirma_action
        "approved_by":        None,
        "approved_at":        None,
        "rejected_by":        None,
        "rejected_at":        None,
        "reject_reason":      None,
        "email_id":           None,
        "queued_at":          None,
        "override_value_check": False,
        "validation_failure_reason": None,
    }
    proposals.append(proposal)
    return proposal


# ── Type-specific resolve handlers ────────────────────────────────────────────

def resolve_wfirma_series_missing(
    proposal:    Dict[str, Any],
    body:        Dict[str, Any],
    operator:    str,
) -> Dict[str, Any]:
    """
    Execute the wfirma_series_missing resolution.

    body must contain:
      - selected_series_id: str  (must be non-null, non-empty, and present
                                  in proposal["context"]["available_series"])
      - save_to_customer_master: bool  (optional, default False)

    Guard: selected_series_id == null or not in available_series → 400.
    Never rubber-stamps; operator MUST supply a valid series from the list.

    On success:
      1. If save_to_customer_master, PATCH customer master.
      2. Re-invoke conversion using stored idempotency_key + selected_series_id.
      3. Return the conversion result.
    """
    from fastapi import HTTPException
    from ..api.routes_proforma import (
        _FinalInvoiceConfirmReq,
        proforma_to_invoice,
        _FINAL_INVOICE_CONFIRM_TOKEN,
    )
    from ..services.customer_master_db import (
        get_customer, upsert_customer, init_db,
    )
    from ..core.config import settings
    from fastapi.responses import JSONResponse
    import json as _json
    import dataclasses as _dc

    ctx = proposal.get("context", {})
    available = [s["id"] for s in ctx.get("available_series", [])]
    selected = (body.get("selected_series_id") or "").strip()

    # ── Guard: selected_series_id must be non-null and in available_series ──
    if not selected:
        raise HTTPException(
            status_code=400,
            detail="selected_series_id is required and must not be null or empty",
        )
    if available and selected not in available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"selected_series_id {selected!r} is not in the proposal's "
                f"available_series {available!r} — supply a series from the list"
            ),
        )

    save_to_master = bool(body.get("save_to_customer_master", False))
    contractor_id  = (ctx.get("customer_contractor_id") or "").strip()

    # ── Step 1: optionally PATCH customer master ──────────────────────────────
    customer_master_updated = False
    if save_to_master and contractor_id:
        try:
            import sqlite3 as _sqlite3
            db_path = settings.storage_root / "customer_master.sqlite"
            init_db(db_path)
            existing = get_customer(db_path, contractor_id)
            if existing is None:
                raise ValueError(
                    f"contractor_id {contractor_id!r} not found in customer master"
                )
            # Direct SQL update for preferred_invoice_series_id only.
            # Uses the same ISO-8601 UTC timestamp format as _now_iso() in
            # customer_master_db so updated_at is consistent across all write paths.
            _now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            with _sqlite3.connect(str(db_path)) as _conn:
                _conn.execute(
                    "UPDATE customer_master SET preferred_invoice_series_id=?, "
                    "updated_at=? WHERE bill_to_contractor_id=?",
                    (selected, _now, contractor_id),
                )
                _conn.commit()
            customer_master_updated = True
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"customer master PATCH failed: {type(exc).__name__}: {exc}",
            ) from exc

    # ── Step 2: re-invoke conversion with injected series ────────────────────
    batch_id    = ctx.get("batch_id") or proposal.get("batch_id", "")
    client_name = ctx.get("client_name", "")
    idempotency_key = (
        (proposal.get("resolution_data") or {}).get("idempotency_key") or ""
    )

    confirm_body = _FinalInvoiceConfirmReq(
        confirm              = _FINAL_INVOICE_CONFIRM_TOKEN,
        operator_description = f"Series resolved via recovery proposal (key={idempotency_key})",
        final_series_id      = selected,
    )
    # Call the existing proforma_to_invoice function directly.
    # This re-runs ALL existing guards (flag, duplicate-conversion, etc.).
    result: JSONResponse = proforma_to_invoice(
        batch_id    = batch_id,
        client_name = client_name,
        body        = confirm_body,
        x_operator  = operator,
    )

    result_body = _json.loads(result.body)
    return {
        "conversion_result":       result_body,
        "selected_series_id":      selected,
        "customer_master_updated": customer_master_updated,
        "operator":                operator,
    }


# ── Dispatch table — add new types here as the 8-type set grows ───────────────

_RESOLVE_HANDLERS = {
    "wfirma_series_missing": resolve_wfirma_series_missing,
}


def dispatch_resolve(
    proposal: Dict[str, Any],
    body:     Dict[str, Any],
    operator: str,
) -> Dict[str, Any]:
    """Route to the correct resolve handler based on proposal type.
    Raises HTTPException(400) for unknown types.
    """
    from fastapi import HTTPException

    prop_type = proposal.get("type", "")
    handler = _RESOLVE_HANDLERS.get(prop_type)
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"proposal type {prop_type!r} has no resolve handler — "
                f"known wfirma_action types: {sorted(_RESOLVE_HANDLERS)}"
            ),
        )
    return handler(proposal, body, operator)

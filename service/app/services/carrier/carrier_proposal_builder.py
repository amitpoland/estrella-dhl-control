"""
carrier_proposal_builder.py — DL-D2 read-only proposal generation.

Consumes the carrier registry (read-only) and emits structured action
proposals describing what an operator could do next on a given batch
or shipment. Mirrors the discipline of the cowork action-proposal
pipeline: the builder NEVER mutates state, NEVER calls the
coordinator, NEVER queues anything. Execution is a separate phase
(DL-D3 will add the gated POST endpoints).

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* No web-framework imports.
* No coordinator-layer import (DL-D3 boundary).
* No carrier-adapter import (live or stub).
* No outbound HTTP client import.
* No DB write functions are referenced.
* The module reads from the shipment DB only via the existing
  read-only helpers.

Proposal shape
--------------
Every builder returns a dict with this exact set of keys::

    {
      "proposal_id":      str,
      "action":           str,             # one of ACTIONS
      "carrier":          str,
      "batch_id":         str | None,
      "awb":              str | None,
      "state":            str | None,
      "title":            str,
      "reason":           str,
      "severity":         "info" | "warning" | "blocked",
      "enabled":          bool,
      "blocking_reasons": list[str],
      "metadata":         dict,
    }

``proposal_id`` is deterministic and stable: same (action, batch_id /
carrier+awb, state) seed always produces the same id, so a downstream
execute layer (DL-D3) can use it as an idempotency key.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from pathlib import Path

from . import carrier_shipment_db as csdb
from . import carrier_state_engine as cse
from .base import CARRIER_DHL


# ── Action ids and severity labels ──────────────────────────────────────────

ACTION_CREATE_SHIPMENT:        str = "create_shipment"
ACTION_MARK_LABEL_PRINTED:     str = "mark_label_printed"
ACTION_MARK_HANDED_TO_CARRIER: str = "mark_handed_to_carrier"
ACTION_CANCEL_SHIPMENT:        str = "cancel_shipment"

ACTIONS = frozenset({
    ACTION_CREATE_SHIPMENT,
    ACTION_MARK_LABEL_PRINTED,
    ACTION_MARK_HANDED_TO_CARRIER,
    ACTION_CANCEL_SHIPMENT,
})

SEVERITY_INFO:    str = "info"
SEVERITY_WARNING: str = "warning"
SEVERITY_BLOCKED: str = "blocked"

VALID_SEVERITIES = frozenset({
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_BLOCKED,
})

#: Default severity is info; downgrade rules below upgrade to warning
#: when an SLA threshold is crossed and to blocked when the action is
#: structurally unavailable.

PRE_HANDOVER_CANCELLABLE = frozenset({
    cse.AWB_ISSUED,
    cse.LABEL_CREATED,
    cse.LABEL_PRINTED,
})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _proposal_id(action: str, *parts: Any) -> str:
    """Deterministic 16-hex proposal id keyed on action + identity.

    Same inputs always produce the same id; different inputs always
    produce different ids (sha256 over a delimited seed). The result
    is prefixed with the action so logs and dashboards can read it
    without unpacking.
    """
    seed = action + "|" + "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"carrier-{action}-{digest}"


def _is_terminal(state: Optional[str]) -> bool:
    """Treat unknown / missing state as non-terminal so the builder
    is conservative — proposals do not silently disappear because a
    row ended up in a state the engine does not yet know."""
    if not state:
        return False
    return state in cse.TERMINAL_STATES


def _hours_since(iso_ts: str) -> Optional[float]:
    """Hours elapsed since *iso_ts* (UTC). Returns None on parse fail."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600.0


def _empty_proposal(
    *,
    proposal_id:      str,
    action:           str,
    carrier:          str,
    batch_id:         Optional[str],
    awb:              Optional[str],
    state:            Optional[str],
    title:            str,
    reason:           str,
    severity:         str,
    enabled:          bool,
    blocking_reasons: Iterable[str],
    metadata:         Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Internal factory that pins the proposal shape exactly once."""
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"invalid proposal severity {severity!r}; "
            f"must be one of {sorted(VALID_SEVERITIES)}"
        )
    if action not in ACTIONS:
        raise ValueError(
            f"invalid proposal action {action!r}; "
            f"must be one of {sorted(ACTIONS)}"
        )
    return {
        "proposal_id":      proposal_id,
        "action":           action,
        "carrier":          carrier,
        "batch_id":         batch_id,
        "awb":              awb,
        "state":            state,
        "title":            title,
        "reason":           reason,
        "severity":         severity,
        "enabled":          bool(enabled),
        "blocking_reasons": list(blocking_reasons),
        "metadata":         dict(metadata or {}),
    }


# ── Per-action builders ─────────────────────────────────────────────────────

def build_create_shipment_proposal(
    batch_id: str,
    *,
    reason:              Optional[str] = None,
    metadata:            Optional[Dict[str, Any]] = None,
    existing_shipments:  Optional[List[Dict[str, Any]]] = None,
    carrier:             str = CARRIER_DHL,
) -> Dict[str, Any]:
    """Propose creating a new outbound shipment for *batch_id*.

    Enabled rules:
      * If *existing_shipments* is None / empty → enabled=True, severity=info.
      * If *existing_shipments* contains any non-terminal row → enabled=False,
        severity=blocked, with one blocking reason per active shipment.
      * If *existing_shipments* are all terminal (delivered / returned /
        voided) → enabled=True, severity=info, with a metadata.hint
        explaining the prior shipment is closed and a new one is allowed.

    The builder NEVER inspects customs / inventory / closure state. That
    coupling is DL-D3+.
    """
    if not (batch_id or "").strip():
        raise ValueError("batch_id is required for create-shipment proposal")

    active = [
        s for s in (existing_shipments or [])
        if not _is_terminal(s.get("state"))
    ]
    terminal = [
        s for s in (existing_shipments or [])
        if _is_terminal(s.get("state"))
    ]

    pid = _proposal_id(ACTION_CREATE_SHIPMENT, batch_id, "none")

    if active:
        active_awbs = [s.get("awb", "") for s in active]
        return _empty_proposal(
            proposal_id      = pid,
            action           = ACTION_CREATE_SHIPMENT,
            carrier          = carrier,
            batch_id         = batch_id,
            awb              = None,
            state            = None,
            title            = f"Create {carrier.upper()} shipment for batch {batch_id}",
            reason           = reason or
                f"Batch {batch_id} already has {len(active)} active shipment(s).",
            severity         = SEVERITY_BLOCKED,
            enabled          = False,
            blocking_reasons = [
                f"shipment already active: {awb}" for awb in active_awbs
            ],
            metadata         = {
                **(metadata or {}),
                "active_shipments":   active_awbs,
                "terminal_shipments": [s.get("awb", "") for s in terminal],
            },
        )

    hint = (
        "All prior shipments for this batch are terminal; new shipment is allowed."
        if terminal else "Batch has no carrier shipment yet."
    )
    return _empty_proposal(
        proposal_id      = pid,
        action           = ACTION_CREATE_SHIPMENT,
        carrier          = carrier,
        batch_id         = batch_id,
        awb              = None,
        state            = None,
        title            = f"Create {carrier.upper()} shipment for batch {batch_id}",
        reason           = reason or hint,
        severity         = SEVERITY_INFO,
        enabled          = True,
        blocking_reasons = [],
        metadata         = {
            **(metadata or {}),
            "hint":               hint,
            "terminal_shipments": [s.get("awb", "") for s in terminal],
        },
    )


def build_mark_label_printed_proposal(
    shipment_row: Dict[str, Any],
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Propose marking the label printed for *shipment_row*.

    Enabled only when the row's state is exactly ``label_created``.
    Other states return a disabled / blocked proposal with a clear
    reason so the dashboard can show why the action is unavailable.
    """
    carrier = shipment_row.get("carrier", "")
    awb     = shipment_row.get("awb", "")
    state   = shipment_row.get("state")
    pid     = _proposal_id(ACTION_MARK_LABEL_PRINTED, carrier, awb, state)

    title = f"Mark label printed for {awb}"

    if state == cse.LABEL_CREATED:
        return _empty_proposal(
            proposal_id      = pid,
            action           = ACTION_MARK_LABEL_PRINTED,
            carrier          = carrier,
            batch_id         = shipment_row.get("batch_id") or None,
            awb              = awb,
            state            = state,
            title            = title,
            reason           = reason or
                "Label is generated and ready for the operator to print.",
            severity         = SEVERITY_INFO,
            enabled          = True,
            blocking_reasons = [],
            metadata         = {
                "shipment_id":   shipment_row.get("id"),
                "label_sha256":  shipment_row.get("label_sha256", ""),
                "manifest_path": shipment_row.get("manifest_path", ""),
            },
        )

    return _empty_proposal(
        proposal_id      = pid,
        action           = ACTION_MARK_LABEL_PRINTED,
        carrier          = carrier,
        batch_id         = shipment_row.get("batch_id") or None,
        awb              = awb,
        state            = state,
        title            = title,
        reason           = reason or
            f"Mark-label-printed requires state {cse.LABEL_CREATED!r}, "
            f"current state is {state!r}.",
        severity         = SEVERITY_BLOCKED,
        enabled          = False,
        blocking_reasons = [
            f"requires state {cse.LABEL_CREATED!r}; current state is {state!r}",
        ],
        metadata         = {
            "shipment_id": shipment_row.get("id"),
        },
    )


def build_mark_handed_to_carrier_proposal(
    shipment_row: Dict[str, Any],
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Propose marking the package handed-to-carrier.

    Enabled only when the row's state is exactly ``label_printed``.
    """
    carrier = shipment_row.get("carrier", "")
    awb     = shipment_row.get("awb", "")
    state   = shipment_row.get("state")
    pid     = _proposal_id(ACTION_MARK_HANDED_TO_CARRIER, carrier, awb, state)

    title = f"Mark handed to carrier for {awb}"

    if state == cse.LABEL_PRINTED:
        return _empty_proposal(
            proposal_id      = pid,
            action           = ACTION_MARK_HANDED_TO_CARRIER,
            carrier          = carrier,
            batch_id         = shipment_row.get("batch_id") or None,
            awb              = awb,
            state            = state,
            title            = title,
            reason           = reason or
                "Operator has printed the label; package is ready for carrier pickup.",
            severity         = SEVERITY_INFO,
            enabled          = True,
            blocking_reasons = [],
            metadata         = {
                "shipment_id":   shipment_row.get("id"),
                "label_sha256":  shipment_row.get("label_sha256", ""),
                "manifest_path": shipment_row.get("manifest_path", ""),
            },
        )

    return _empty_proposal(
        proposal_id      = pid,
        action           = ACTION_MARK_HANDED_TO_CARRIER,
        carrier          = carrier,
        batch_id         = shipment_row.get("batch_id") or None,
        awb              = awb,
        state            = state,
        title            = title,
        reason           = reason or
            f"Mark-handed-to-carrier requires state {cse.LABEL_PRINTED!r}, "
            f"current state is {state!r}.",
        severity         = SEVERITY_BLOCKED,
        enabled          = False,
        blocking_reasons = [
            f"requires state {cse.LABEL_PRINTED!r}; current state is {state!r}",
        ],
        metadata         = {
            "shipment_id": shipment_row.get("id"),
        },
    )


def build_cancel_shipment_proposal(
    shipment_row: Dict[str, Any],
    *,
    reason:      Optional[str] = None,
    stale_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Propose voiding a pre-handover shipment.

    Enabled rules:
      * State in ``{awb_issued, label_created, label_printed}``
        → enabled=True. If *stale_hours* is provided and the shipment's
        ``updated_at`` is older than that many hours, severity is
        ``warning`` instead of the default ``info``.
      * State in ``{handed_to_carrier, in_transit, delivered, returned}``
        → enabled=False, severity=blocked, blocking_reasons cite the
        named "void after handover" rule.
      * State == ``voided`` → enabled=False, severity=blocked,
        blocking_reasons cite "already voided" (so the dashboard can
        show why this action is grayed out without surfacing the
        engine's terminal-state error).
    """
    carrier = shipment_row.get("carrier", "")
    awb     = shipment_row.get("awb", "")
    state   = shipment_row.get("state")
    pid     = _proposal_id(ACTION_CANCEL_SHIPMENT, carrier, awb, state)

    title = f"Cancel shipment {awb}"

    if state == cse.VOIDED:
        return _empty_proposal(
            proposal_id      = pid,
            action           = ACTION_CANCEL_SHIPMENT,
            carrier          = carrier,
            batch_id         = shipment_row.get("batch_id") or None,
            awb              = awb,
            state            = state,
            title            = title,
            reason           = reason or "Shipment is already voided.",
            severity         = SEVERITY_BLOCKED,
            enabled          = False,
            blocking_reasons = ["shipment is already voided"],
            metadata         = {"shipment_id": shipment_row.get("id")},
        )

    if state in PRE_HANDOVER_CANCELLABLE:
        elapsed = _hours_since(shipment_row.get("updated_at", ""))
        is_stale = (
            stale_hours is not None
            and elapsed is not None
            and elapsed >= float(stale_hours)
        )
        return _empty_proposal(
            proposal_id      = pid,
            action           = ACTION_CANCEL_SHIPMENT,
            carrier          = carrier,
            batch_id         = shipment_row.get("batch_id") or None,
            awb              = awb,
            state            = state,
            title            = title,
            reason           = reason or (
                "Shipment is past the staleness threshold; consider voiding."
                if is_stale else
                "Shipment is pre-handover and may be voided without penalty."
            ),
            severity         = SEVERITY_WARNING if is_stale else SEVERITY_INFO,
            enabled          = True,
            blocking_reasons = [],
            metadata         = {
                "shipment_id":          shipment_row.get("id"),
                "hours_since_update":   elapsed,
                "stale_hours_threshold": stale_hours,
                "is_stale":             bool(is_stale),
            },
        )

    # Post-handover, terminal-non-voided: structurally blocked.
    return _empty_proposal(
        proposal_id      = pid,
        action           = ACTION_CANCEL_SHIPMENT,
        carrier          = carrier,
        batch_id         = shipment_row.get("batch_id") or None,
        awb              = awb,
        state            = state,
        title            = title,
        reason           = reason or
            "Voiding is only permitted before handover to the carrier.",
        severity         = SEVERITY_BLOCKED,
        enabled          = False,
        blocking_reasons = [
            f"voiding not permitted from state {state!r}; "
            f"package has been handed to the carrier",
        ],
        metadata         = {"shipment_id": shipment_row.get("id")},
    )


# ── Orchestrators ───────────────────────────────────────────────────────────

def build_proposals_for_batch(
    db_path: Path,
    batch_id: str,
) -> List[Dict[str, Any]]:
    """All open proposals for a single PZ batch.

    Reads the registry through ``get_by_batch`` (no writes). Always
    emits a ``create_shipment`` proposal so the operator UI shows the
    action explicitly (enabled when no active shipment exists,
    blocked otherwise). Per-shipment proposals are only emitted for
    actions actually available in the shipment's current state.
    """
    # The DB module is a singleton. Initialise it idempotently if the
    # caller has not already done so. This module never writes; init
    # only attaches the SQLite connection.
    csdb.init_db(db_path)

    rows = csdb.get_by_batch(batch_id)
    proposals: List[Dict[str, Any]] = [
        build_create_shipment_proposal(
            batch_id, existing_shipments=rows,
        )
    ]
    for row in rows:
        proposals.extend(_proposals_for_row(row))
    return proposals


def build_all_open_proposals(db_path: Path) -> List[Dict[str, Any]]:
    """All per-shipment proposals across the whole registry.

    Does not emit ``create_shipment`` proposals — that question
    requires a batch context which lives outside the carrier registry.
    Reads via ``list_all`` (no writes).
    """
    csdb.init_db(db_path)

    rows = csdb.list_all()
    proposals: List[Dict[str, Any]] = []
    for row in rows:
        proposals.extend(_proposals_for_row(row))
    return proposals


def _proposals_for_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-shipment fan-out: emit only proposals relevant to the row's state."""
    out: List[Dict[str, Any]] = []
    state = row.get("state")

    if state == cse.LABEL_CREATED:
        out.append(build_mark_label_printed_proposal(row))
    elif state == cse.LABEL_PRINTED:
        out.append(build_mark_handed_to_carrier_proposal(row))

    # Cancel proposal is meaningful for any pre-handover state. After
    # handover it is structurally blocked and noisy; for terminal
    # states (delivered / returned / voided) we omit it entirely.
    if state in PRE_HANDOVER_CANCELLABLE:
        out.append(build_cancel_shipment_proposal(row))

    return out

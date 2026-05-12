"""
dhl_clearance_manifest.py — Writer helpers for audit.dhl_clearance.* namespace.

Sub-schemas are FROZEN at P0; phases (P2-P5) must NOT add fields without an
ADR amendment. Adding a field outside the schema raises ManifestSchemaError.

Hash-only audit per ADR-006 — never store raw PDF bytes in the manifest;
only sha256 references that point at the on-disk attachment store.

Schema overview (frozen):
    audit["dhl_clearance"] = {
        "state":              <one of ALL_STATES>,
        "state_history":      [<append-only transition records>],
        "thread_id":           <string>,
        "thread_id_aliases":   [<string>...],   # Risk-R1: fresh DHL threads
        "p2_dispatch": {
            "shadow":         <bool>,
            "message_id":     <string>,
            "recipient":      <string>,
            "sent_at":        <iso8601>,
            "content_sha256": <hex>,
        },
        "p3_tracking": {
            "last_signal_token": <string>,
            "last_signal_at":    <iso8601>,
            "tick_count":        <int>,
            "last_tick_at":      <iso8601>,
            "watcher_active":    <bool>,
        },
        "p4_followup": {
            "activated_at":           <iso8601>,
            "last_tick_at":           <iso8601>,
            "livelock_budget_until":  <iso8601>,
        },
        "p5_clarifications": [
            {
                "inbound_message_id": <string>,
                "intent":             <one of CLASSIFIER_INTENTS>,
                "confidence":         <float 0..1>,
                "reply_message_id":   <string>,
                "reply_sha256":       <hex>,
                "at":                 <iso8601>,
            },
            ...
        ],
        "p6_sad": {
            "doc_id":     <string>,
            "sha256":     <hex>,
            "type":       <"SAD"|"PZC">,
            "arrived_at": <iso8601>,
        },
        "p7_pz": {
            "triggered_at":   <iso8601>,
            "last_status":    <"unlocked"|"running"|"succeeded"|"failed">,
            "last_run_at":    <iso8601>,
            "failure_reason": <string|null>,
        },
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Set

from . import dhl_clearance_state_engine as _state_engine

# ── Namespace key on the audit dict ──────────────────────────────────────────

MANIFEST_KEY: str = "dhl_clearance"


# ── Schema enumerations (frozen at P0) ───────────────────────────────────────

_TOP_LEVEL_FIELDS: FrozenSet[str] = frozenset({
    "state",
    "state_history",
    "thread_id",
    "thread_id_aliases",
    "p2_dispatch",
    "p3_tracking",
    "p4_followup",
    "p5_clarifications",
    "p6_sad",
    "p7_pz",
})

_P2_DISPATCH_FIELDS: FrozenSet[str] = frozenset({
    "shadow", "message_id", "recipient", "sent_at", "content_sha256",
})

_P3_TRACKING_FIELDS: FrozenSet[str] = frozenset({
    "last_signal_token", "last_signal_at",
    "tick_count", "last_tick_at", "watcher_active",
})

_P4_FOLLOWUP_FIELDS: FrozenSet[str] = frozenset({
    "activated_at", "last_tick_at", "livelock_budget_until",
})

_P5_CLARIFICATION_FIELDS: FrozenSet[str] = frozenset({
    "inbound_message_id", "intent", "confidence",
    "reply_message_id", "reply_sha256", "at",
})

_P6_SAD_FIELDS: FrozenSet[str] = frozenset({
    "doc_id", "sha256", "type", "arrived_at",
})

_P7_PZ_FIELDS: FrozenSet[str] = frozenset({
    "triggered_at", "last_status", "last_run_at", "failure_reason",
})

_P7_PZ_STATUSES: FrozenSet[str] = frozenset({
    "unlocked", "running", "succeeded", "failed",
})

_P6_SAD_TYPES: FrozenSet[str] = frozenset({"SAD", "PZC"})

CLASSIFIER_INTENTS: FrozenSet[str] = frozenset({
    "goods_description", "invoice", "authorization", "sad_received", "unknown",
})


# ── Errors ───────────────────────────────────────────────────────────────────

class ManifestSchemaError(ValueError):
    """Raised when a writer is given a field outside the frozen schema."""


# ── Initialisation ───────────────────────────────────────────────────────────

def init_manifest(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialise audit[MANIFEST_KEY] with a default-shaped block if absent.

    Mutates *audit* in place and returns it for chaining.
    """
    if MANIFEST_KEY not in audit or not isinstance(audit[MANIFEST_KEY], dict):
        audit[MANIFEST_KEY] = {
            "state":              _state_engine.INITIAL_STATE,
            "state_history":      [],
            "thread_id":          "",
            "thread_id_aliases":  [],
            "p2_dispatch":        {},
            "p3_tracking":        {},
            "p4_followup":        {},
            "p5_clarifications":  [],
            "p6_sad":             {},
            "p7_pz":              {},
        }
    return audit


def _block(audit: Dict[str, Any]) -> Dict[str, Any]:
    init_manifest(audit)
    return audit[MANIFEST_KEY]


# ── State transitions ────────────────────────────────────────────────────────

def get_state(audit: Dict[str, Any]) -> str:
    return _block(audit).get("state", _state_engine.INITIAL_STATE)


def record_transition(
    audit:  Dict[str, Any],
    to_state: str,
    *,
    reason: str = "",
    actor:  str = "system",
    shadow: bool = False,
) -> Dict[str, Any]:
    """
    Validate the transition through the state engine, append to state_history,
    and update current state. Append-only.

    The optional `shadow` kwarg forwards to `state_engine.transition()`. When
    True, the state_history entry carries a `shadow: True` key per ADR-018
    Invariant 4 so audit consumers can filter cleanly between observation-
    mode and live-mode transitions.

    Raises:
        IllegalTransition / UnknownState — surfaces from state engine.
    """
    block = _block(audit)
    from_state = block.get("state", _state_engine.INITIAL_STATE)

    entry = _state_engine.transition(
        from_state, to_state,
        reason=reason, actor=actor, shadow=shadow,
    )
    block["state_history"] = _state_engine.append_state_history(
        block.get("state_history") or [], entry,
    )
    block["state"] = to_state
    return audit


# ── Thread tracking ──────────────────────────────────────────────────────────

def set_thread_id(audit: Dict[str, Any], thread_id: str) -> Dict[str, Any]:
    if not isinstance(thread_id, str) or not thread_id:
        raise ManifestSchemaError("thread_id must be a non-empty string")
    _block(audit)["thread_id"] = thread_id
    return audit


def add_thread_alias(audit: Dict[str, Any], alias: str) -> Dict[str, Any]:
    """Append *alias* to thread_id_aliases[] if not already present. Risk-R1."""
    if not isinstance(alias, str) or not alias:
        raise ManifestSchemaError("alias must be a non-empty string")
    block = _block(audit)
    aliases: List[str] = block.setdefault("thread_id_aliases", [])
    if alias not in aliases:
        aliases.append(alias)
    return audit


# ── Phase-block writers (frozen schemas) ─────────────────────────────────────

def write_p2_dispatch(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p2_dispatch", fields, _P2_DISPATCH_FIELDS)
    if "content_sha256" in fields:
        _enforce_hex_sha256(fields["content_sha256"])
    _block(audit)["p2_dispatch"] = {**_block(audit).get("p2_dispatch", {}), **fields}
    return audit


def write_p3_tracking(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p3_tracking", fields, _P3_TRACKING_FIELDS)
    _block(audit)["p3_tracking"] = {**_block(audit).get("p3_tracking", {}), **fields}
    return audit


def write_p4_followup(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p4_followup", fields, _P4_FOLLOWUP_FIELDS)
    _block(audit)["p4_followup"] = {**_block(audit).get("p4_followup", {}), **fields}
    return audit


def append_p5_clarification(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p5_clarification", fields, _P5_CLARIFICATION_FIELDS)
    intent = fields.get("intent")
    if intent is not None and intent not in CLASSIFIER_INTENTS:
        raise ManifestSchemaError(
            f"intent must be one of {sorted(CLASSIFIER_INTENTS)}; got {intent!r}"
        )
    confidence = fields.get("confidence")
    if confidence is not None:
        try:
            c = float(confidence)
        except (TypeError, ValueError):
            raise ManifestSchemaError("confidence must be numeric")
        if not (0.0 <= c <= 1.0):
            raise ManifestSchemaError("confidence must be in [0.0, 1.0]")
    if "reply_sha256" in fields and fields["reply_sha256"]:
        _enforce_hex_sha256(fields["reply_sha256"])
    block = _block(audit)
    block.setdefault("p5_clarifications", []).append(dict(fields))
    return audit


def write_p6_sad(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p6_sad", fields, _P6_SAD_FIELDS)
    doc_type = fields.get("type")
    if doc_type is not None and doc_type not in _P6_SAD_TYPES:
        raise ManifestSchemaError(
            f"type must be one of {sorted(_P6_SAD_TYPES)}; got {doc_type!r}"
        )
    if "sha256" in fields and fields["sha256"]:
        _enforce_hex_sha256(fields["sha256"])
    _block(audit)["p6_sad"] = {**_block(audit).get("p6_sad", {}), **fields}
    return audit


def write_p7_pz(audit: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    _enforce_fields("p7_pz", fields, _P7_PZ_FIELDS)
    last_status = fields.get("last_status")
    if last_status is not None and last_status not in _P7_PZ_STATUSES:
        raise ManifestSchemaError(
            f"last_status must be one of {sorted(_P7_PZ_STATUSES)}; "
            f"got {last_status!r}"
        )
    _block(audit)["p7_pz"] = {**_block(audit).get("p7_pz", {}), **fields}
    return audit


# ── Schema enforcement ───────────────────────────────────────────────────────

def _enforce_fields(
    block_name: str,
    given: Dict[str, Any],
    allowed: FrozenSet[str],
) -> None:
    extra: Set[str] = set(given.keys()) - allowed
    if extra:
        raise ManifestSchemaError(
            f"{block_name} block does not permit fields {sorted(extra)}; "
            f"allowed fields are {sorted(allowed)}. "
            f"Adding new fields requires an ADR amendment."
        )


def _enforce_hex_sha256(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ManifestSchemaError(
            "sha256 must be a 64-char hex string (ADR-006 hash-only audit)"
        )
    try:
        int(value, 16)
    except ValueError:
        raise ManifestSchemaError("sha256 must be hex digits")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

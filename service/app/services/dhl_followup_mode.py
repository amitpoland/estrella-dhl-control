"""dhl_followup_mode.py — Shipment-level DHL follow-up mode authority.

Single source of truth for whether a shipment is enrolled in automatic
follow-up sending or kept under manual operator control. Persisted on
the shipment audit at ``audit.followup.mode``.

Architecture (operator directive 2026-05-26):

    Global emergency switch (env)  ←──  one switch, kill-all
        DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP=false|true

    Shipment-level mode (audit)    ←──  one decision per shipment
        audit.followup.mode = "manual" | "automatic"

Authorisation matrix for a follow-up auto-send:

    | global flag | shipment mode | sends? |
    | false       | manual        |  no    |
    | false       | automatic     |  no    |  ← emergency switch wins
    | true        | manual        |  no    |
    | true        | automatic     |  yes (subject to all other gates) |

The mode default is **manual** for every shipment that has not been
explicitly enrolled. Enrollment is operator-explicit (Inbox toggle,
audited timeline event). Disablement is one-click reversible.

This module is pure I/O on audit dicts + atomic JSON writes. It does
NOT send email, NOT call the carrier, NOT touch wFirma/PZ/customs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Literal, Optional

log = logging.getLogger(__name__)

ModeLiteral = Literal["manual", "automatic"]
VALID_MODES: frozenset = frozenset({"manual", "automatic"})
DEFAULT_MODE: ModeLiteral = "manual"


def get_mode(audit: Dict[str, Any]) -> ModeLiteral:
    """Return the shipment's current follow-up mode.

    Reads ``audit.followup.mode``. Defaults to ``"manual"`` when:
      - the key is absent (shipment never enrolled),
      - the value is missing / empty,
      - the value is not in VALID_MODES (defensive — never trust drift).
    """
    fu = (audit or {}).get("followup") or {}
    mode = str(fu.get("mode") or "").strip().lower()
    if mode in VALID_MODES:
        return mode  # type: ignore[return-value]
    return DEFAULT_MODE


def is_automatic(audit: Dict[str, Any]) -> bool:
    """True iff shipment is enrolled in automatic mode."""
    return get_mode(audit) == "automatic"


def is_mode_explicit(audit: Dict[str, Any]) -> bool:
    """Return True iff audit.followup.mode is explicitly set to a valid value.

    Distinguishes operator-set ``manual`` from default-fallback ``manual``.
    This is an introspection of the same authority field — NOT a second
    authority. UIs should use this to render "Manual" (operator-set) vs
    "Default" (no decision yet) without re-deriving mode independently.
    """
    fu = (audit or {}).get("followup") or {}
    mode = str(fu.get("mode") or "").strip().lower()
    return mode in VALID_MODES


def set_mode(
    audit_path: Path,
    audit: Dict[str, Any],
    mode: str,
    *,
    operator: str = "operator",
) -> Dict[str, Any]:
    """Persist a new follow-up mode on the shipment audit.

    Atomic write + timeline event. Returns the new ``followup`` block.

    Idempotent: setting the same mode that's already set returns the
    existing state without writing a timeline event (no churn).

    Raises ValueError on invalid mode strings — never silently coerces
    to a default mode; mistyped operator input must surface as an error.
    """
    norm = str(mode or "").strip().lower()
    if norm not in VALID_MODES:
        raise ValueError(
            f"Invalid followup mode: {mode!r}. Allowed: {sorted(VALID_MODES)}"
        )

    fu = audit.get("followup") or {}
    current = str(fu.get("mode") or DEFAULT_MODE).strip().lower()
    if current == norm:
        # No change → no write, no timeline event
        return {"mode": current, "changed": False, "operator": operator}

    fu["mode"] = norm
    audit["followup"] = fu

    # Atomic persist
    from ..utils.io import write_json_atomic
    write_json_atomic(audit_path, audit)

    # Timeline event for audit trail
    try:
        from ..core import timeline as tl
        tl.log_event(
            audit_path, "dhl_followup_mode_changed", "operator", operator,
            detail={"from": current, "to": norm},
        )
    except Exception as exc:
        log.warning("[dhl_followup_mode] timeline write failed: %s", exc)

    log.info(
        "[dhl_followup_mode] batch=%s mode=%s→%s by=%s",
        audit.get("batch_id") or audit_path.parent.name,
        current, norm, operator,
    )
    return {"mode": norm, "changed": True, "operator": operator, "previous": current}


def mode_telemetry(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Return the UI-facing telemetry for the mode card: current mode,
    last ingest scan, next follow-up due. Read-only."""
    state = (audit or {}).get("dhl_followup") or {}
    ingestion = (audit or {}).get("email_ingestion") or {}
    return {
        "mode":             get_mode(audit),
        "last_scan_at":     ingestion.get("last_scan_at"),
        "next_followup_at": state.get("next_followup_at"),
        "followup_count":   state.get("followup_count", 0),
        "last_followup_at": state.get("last_followup_at"),
        "active":           bool(state.get("active")),
    }

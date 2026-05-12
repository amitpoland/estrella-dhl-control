"""
dhl_clearance_coordinator.py — Path A self-clearance coordinator (P0 skeleton).

Single coordinator that drives the DHL self-clearance state machine through
P2 (proactive dispatch), P3 (tracking watcher), P4 (clarification reply), and
P5 (SAD unlock + PZ trigger).

At P0 this is a *scaffold only*: every on_* entrypoint is declared but raises
`NotImplementedYet`. P2-P5 each wires its own behaviour behind its own flag.

Path A scope gate
=================
Every entrypoint MUST short-circuit if the shipment is not on the Path A
self-clearance flow. The gate uses `is_dhl_self_clearance()` from
`clearance_path_alias`, which normalises legacy aliases.

AWB stability gate
==================
P2 dispatch requires `is_awb_stable()` from `carrier.coordinator` to return
True. The coordinator never reaches into the carrier persistence directly;
it consults the read-only predicate.

Predecessor-phase gate (Risk R7)
=================================
Each phase checks its predecessor's *live_enabled* flag before doing work.
If the predecessor is OFF, the phase logs `selfclearance_pX_blocked_predecessor_off`
and no-ops. P0 declares the gate; P2-P5 enforce it in their own wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import dhl_clearance_manifest as manifest
from . import dhl_clearance_state_engine as state_engine

log = get_logger(__name__)


class NotImplementedYet(NotImplementedError):
    """Coordinator entrypoint exists at P0 but its behaviour ships in P2-P5."""


# ── Inputs for each entrypoint (typed records) ───────────────────────────────

@dataclass(frozen=True)
class DispatchInput:
    batch_id: str
    awb:      str
    audit:    Dict[str, Any]


@dataclass(frozen=True)
class TrackingEventInput:
    batch_id:         str
    awb:              str
    signal_token:     str
    signal_at:        str
    audit:            Dict[str, Any]


@dataclass(frozen=True)
class FollowupTickInput:
    batch_id: str
    awb:      str
    now_iso:  str
    audit:    Dict[str, Any]


@dataclass(frozen=True)
class InboundClarificationInput:
    batch_id:        str
    awb:             str
    thread_id:       str
    message_id:      str
    inbound_body:    str
    audit:           Dict[str, Any]


@dataclass(frozen=True)
class SadInboundInput:
    batch_id:   str
    awb:        str
    doc_id:     str
    doc_sha256: str
    doc_type:   str
    audit:      Dict[str, Any]


# ── Coordinator ──────────────────────────────────────────────────────────────

class DhlClearanceCoordinator:
    """Path A coordinator. P0 ships scaffolds only."""

    # ── Scope gates (reusable; tested in P0) ─────────────────────────────────

    @staticmethod
    def is_in_scope(audit: Dict[str, Any]) -> bool:
        """True when this shipment is on the Path A self-clearance flow."""
        from .clearance_path_alias import is_dhl_self_clearance  # local — avoid import cycle
        decision = (audit.get("clearance_decision") or {})
        return bool(is_dhl_self_clearance(decision.get("clearance_path")))

    @staticmethod
    def is_awb_stable_for(awb: str) -> bool:
        """Read-only carrier predicate — see carrier/coordinator.is_awb_stable."""
        from .carrier.coordinator import is_awb_stable  # local — avoid eager import
        return bool(is_awb_stable(awb))

    # ── P2 — proactive dispatch ──────────────────────────────────────────────

    def dispatch_proactive(self, _inp: DispatchInput) -> None:
        """Wired in P2. Sends the proactive customs package to DHL."""
        raise NotImplementedYet("P2 wires dhl_proactive_dispatch_builder.py")

    # ── P3 — tracking watcher ────────────────────────────────────────────────

    def on_tracking_event(self, _inp: TrackingEventInput) -> None:
        """Wired in P3. Reacts to new tracking_normalizer signal tokens."""
        raise NotImplementedYet("P3 wires the tracking watcher")

    # ── P4 — follow-up scheduler ─────────────────────────────────────────────

    def tick_followup(self, _inp: FollowupTickInput) -> None:
        """Wired in P4. Executes one follow-up cadence tick (ADR-014)."""
        raise NotImplementedYet("P4 wires dhl_selfclearance_followup_v2.py")

    # ── P4/P5 — clarification reply ──────────────────────────────────────────

    def on_inbound_clarification(self, _inp: InboundClarificationInput) -> None:
        """Wired in P4. Routes DHL clarification through the classifier + reply lock."""
        raise NotImplementedYet("P4 wires the classifier + reply lock")

    # ── P5 — SAD / PZC arrival ───────────────────────────────────────────────

    def on_sad_inbound(self, _inp: SadInboundInput) -> None:
        """Wired in P5. Links SAD/PZC, transitions to pz_unlocked, triggers PZ."""
        raise NotImplementedYet("P5 wires SAD link + PZ trigger")

    # ── Predecessor-phase gate (Risk R7) — used by P2-P5 wiring ──────────────

    @staticmethod
    def predecessor_live_enabled(phase: str) -> bool:
        """
        Returns True if the predecessor phase's *_live_enabled flag is True.

        Phases:
            "p2" → no predecessor → always True
            "p3" → predecessor is p2
            "p4" → predecessor is p3
            "p5" → predecessor is p4
        """
        if phase == "p2":
            return True
        if phase == "p3":
            return bool(getattr(settings, "dhl_selfclearance_p2_live_enabled", False))
        if phase == "p4":
            return bool(getattr(settings, "dhl_selfclearance_p3_live_enabled", False))
        if phase == "p5":
            return bool(getattr(settings, "dhl_selfclearance_p4_live_enabled", False))
        return False

    @staticmethod
    def initial_manifest(audit: Dict[str, Any]) -> Dict[str, Any]:
        """Convenience — initialise the manifest block on a fresh audit."""
        return manifest.init_manifest(audit)


# Module-level singleton for callers that prefer a function-call shape.
coordinator = DhlClearanceCoordinator()

"""
dhl_clearance_coordinator.py — Path A self-clearance coordinator (P0 skeleton + P2 dispatch).

Single coordinator that drives the DHL self-clearance state machine through
P2 (proactive dispatch), P3 (tracking watcher), P4 (clarification reply), and
P5 (SAD unlock + PZ trigger).

At P0 every on_* entrypoint was a `NotImplementedYet` scaffold. P2 wires
`dispatch_proactive` behind the default-OFF `dhl_selfclearance_p2_live_enabled`
flag, with ADR-018 shadow-mode semantics (`shadow_mode=True` default → build
package + manifest + log, NO send; `live_enabled=True + shadow_mode=True` →
queue real email via `email_service.queue_email`; FORBIDDEN combination
`shadow_mode=False + live_enabled=True` is rejected by `_enforce_flag_combination`).

Path A scope gate
=================
Every entrypoint MUST short-circuit if the shipment is not on the Path A
self-clearance flow. The gate uses `is_dhl_self_clearance()` from
`clearance_path_alias`, which normalises legacy aliases. Non-Path-A shipments
raise `OutOfScopeError` (Path B falls through to the existing agency flow).

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

Idempotency
===========
Once `audit.dhl_clearance.p2_dispatch.message_id` is recorded, subsequent
`dispatch_proactive` calls for the same batch are no-ops. This holds across
both shadow and live modes — second call returns the same prior result
shape with `idempotent: True`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import dhl_clearance_manifest as manifest
from . import dhl_clearance_state_engine as state_engine

log = get_logger(__name__)


class NotImplementedYet(NotImplementedError):
    """Coordinator entrypoint exists at P0 but its behaviour ships in P2-P5."""


class OutOfScopeError(Exception):
    """Shipment is not on the Path A self-clearance flow. Caller must skip."""


class ForbiddenFlagCombination(Exception):
    """ADR-018 FORBIDDEN state: shadow_mode=False AND live_enabled=True.

    The combination is structurally invalid — `live_enabled=True` REQUIRES
    `shadow_mode=True` (Invariant 1 of ADR-018). The coordinator rejects
    the action; the admin endpoint should likewise refuse the flag-flip
    that would produce this state.
    """


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

    # ── P2 — proactive dispatch (WIRED) ──────────────────────────────────────

    def dispatch_proactive(self, inp: "DispatchInput") -> Dict[str, Any]:
        """
        Fire the proactive customs dispatch for a Path A shipment.

        Returns a result dict:
            {
              "status": "shadow" | "sent" | "skipped" | "blocked",
              "reason": <str>,
              "message_id": <str|None>,
              "content_sha256": <hex>,
              "idempotent": <bool>,
            }

        Behavior matrix (ADR-018):
          - shadow_mode=True,  live_enabled=False → SHADOW  (build + manifest, no send)
          - shadow_mode=True,  live_enabled=True  → LIVE    (queue email + manifest)
          - shadow_mode=False, live_enabled=False → DORMANT (no-op, status=skipped)
          - shadow_mode=False, live_enabled=True  → FORBIDDEN (raises)

        Raises:
            OutOfScopeError       — shipment is on Path B (agency_clearance)
            ForbiddenFlagCombination — `shadow_mode=False AND live_enabled=True`
        """
        # ── 1. Scope gate (Path A only) ──────────────────────────────────────
        if not self.is_in_scope(inp.audit):
            raise OutOfScopeError(
                f"batch_id={inp.batch_id!r} is not on Path A self-clearance; "
                f"refusing P2 dispatch"
            )

        # ── 2. Flag combination check (ADR-018) ──────────────────────────────
        shadow_mode = bool(getattr(settings, "dhl_selfclearance_p2_shadow_mode", True))
        live_enabled = bool(getattr(settings, "dhl_selfclearance_p2_live_enabled", False))
        _enforce_flag_combination("p2", shadow_mode, live_enabled)

        # ── 3. DORMANT: nothing to do ────────────────────────────────────────
        if not shadow_mode and not live_enabled:
            log.info("selfclearance_p2_dormant batch_id=%s", inp.batch_id)
            return {
                "status": "skipped",
                "reason": "dormant_state",
                "message_id": None,
                "content_sha256": "",
                "idempotent": False,
            }

        # ── 4. Idempotency — second call returns prior result ────────────────
        manifest.init_manifest(inp.audit)
        prior = inp.audit["dhl_clearance"].get("p2_dispatch") or {}
        if prior.get("message_id"):
            log.info(
                "selfclearance_p2_idempotent batch_id=%s message_id=%s",
                inp.batch_id, prior.get("message_id"),
            )
            return {
                "status": "shadow" if prior.get("shadow") else "sent",
                "reason": "already_dispatched",
                "message_id": prior.get("message_id"),
                "content_sha256": prior.get("content_sha256", ""),
                "idempotent": True,
            }

        # ── 5. AWB stability gate ────────────────────────────────────────────
        if not self.is_awb_stable_for(inp.awb):
            log.info(
                "selfclearance_p2_awb_unstable batch_id=%s awb=%s — staying at "
                "awaiting_preemptive_send",
                inp.batch_id, inp.awb,
            )
            return {
                "status": "skipped",
                "reason": "awb_unstable",
                "message_id": None,
                "content_sha256": "",
                "idempotent": False,
            }

        # ── 6. Build the dispatch package ────────────────────────────────────
        try:
            from .dhl_proactive_dispatch_builder import build_dhl_proactive_dispatch
            pkg = build_dhl_proactive_dispatch(inp.audit, inp.batch_id)
        except Exception as exc:
            log.error(
                "selfclearance_p2_build_failed batch_id=%s reason=%s",
                inp.batch_id, exc.__class__.__name__,
            )
            self._transition_to_dispatch_failed(inp.audit, str(exc))
            return {
                "status": "blocked",
                "reason": "build_failed",
                "message_id": None,
                "content_sha256": "",
                "idempotent": False,
            }

        if pkg.get("missing"):
            log.warning(
                "selfclearance_p2_missing_attachments batch_id=%s missing=%s",
                inp.batch_id, pkg.get("missing"),
            )
            return {
                "status": "blocked",
                "reason": "missing_attachments",
                "message_id": None,
                "content_sha256": "",
                "idempotent": False,
            }

        # Compute content SHA over a deterministic canonical projection of the
        # outbound payload (subject + body_text + recipient + attachment labels).
        # Bytes never live in the manifest — only the hash.
        content_sha256 = _compute_content_sha256(pkg)

        # ── 7. SHADOW or LIVE? ───────────────────────────────────────────────
        if shadow_mode and not live_enabled:
            # SHADOW state — build + manifest + log only.
            message_id = f"shadow:{inp.batch_id}:{content_sha256[:12]}"
            now = _now_iso()
            recipient = ",".join(pkg.get("to") or [])
            manifest.write_p2_dispatch(
                inp.audit,
                shadow=True,
                message_id=message_id,
                recipient=recipient,
                sent_at=now,
                content_sha256=content_sha256,
            )
            # State transition: awaiting_preemptive_send → awaiting_poland_arrival
            # (legal under shadow mode per ADR-018 — state_history append carries
            # shadow:True via reason field; downstream phases gated on
            # live_enabled=True will not act on shadow-tagged transitions).
            self._advance_to_awaiting_poland_arrival(inp.audit, shadow=True)
            log.info(
                "selfclearance_p2_shadow batch_id=%s message_id=%s sha=%s",
                inp.batch_id, message_id, content_sha256[:12],
            )
            return {
                "status": "shadow",
                "reason": "shadow_logged",
                "message_id": message_id,
                "content_sha256": content_sha256,
                "idempotent": False,
            }

        # LIVE state — actually queue the email.
        from .email_service import queue_email
        from ..config.email_routing import format_to, format_cc
        to_str = format_to(pkg.get("to") or [])
        cc_str = format_cc(pkg.get("cc") or [])
        try:
            message_id = queue_email(
                to=to_str,
                subject=pkg.get("subject", ""),
                body_html=pkg.get("body_html", ""),
                body_text=pkg.get("body_text", ""),
                batch_id=inp.batch_id,
                cc=cc_str,
                from_address=pkg.get("from_address", ""),
                email_type=pkg.get("email_type", "dhl_proactive_dispatch"),
            )
        except Exception as exc:
            log.error(
                "selfclearance_p2_queue_failed batch_id=%s reason=%s",
                inp.batch_id, exc.__class__.__name__,
            )
            self._transition_to_dispatch_failed(inp.audit, str(exc))
            return {
                "status": "blocked",
                "reason": "queue_failed",
                "message_id": None,
                "content_sha256": content_sha256,
                "idempotent": False,
            }

        now = _now_iso()
        manifest.write_p2_dispatch(
            inp.audit,
            shadow=False,
            message_id=message_id,
            recipient=to_str,
            sent_at=now,
            content_sha256=content_sha256,
        )
        self._advance_to_awaiting_poland_arrival(inp.audit, shadow=False)
        log.info(
            "selfclearance_p2_sent batch_id=%s message_id=%s recipient=%s",
            inp.batch_id, message_id, to_str,
        )
        return {
            "status": "sent",
            "reason": "queued",
            "message_id": message_id,
            "content_sha256": content_sha256,
            "idempotent": False,
        }

    # ── P2 state transition helpers ──────────────────────────────────────────

    @staticmethod
    def _advance_to_awaiting_poland_arrival(audit: Dict[str, Any], *, shadow: bool) -> None:
        """Advance state if currently awaiting_preemptive_send; otherwise no-op
        (caller may already be past this state, e.g. on idempotent retry)."""
        block = audit[manifest.MANIFEST_KEY]
        current = block.get("state", state_engine.INITIAL_STATE)
        if current != state_engine.STATE_AWAITING_PREEMPTIVE_SEND:
            return
        reason = "p2_dispatch_shadow" if shadow else "p2_dispatch_sent"
        manifest.record_transition(
            audit,
            state_engine.STATE_AWAITING_POLAND_ARRIVAL,
            reason=reason,
            actor="system",
        )

    @staticmethod
    def _transition_to_dispatch_failed(audit: Dict[str, Any], reason: str) -> None:
        """Transition to dispatch_failed if currently awaiting_preemptive_send."""
        manifest.init_manifest(audit)
        block = audit[manifest.MANIFEST_KEY]
        current = block.get("state", state_engine.INITIAL_STATE)
        if current != state_engine.STATE_AWAITING_PREEMPTIVE_SEND:
            return
        manifest.record_transition(
            audit,
            state_engine.STATE_DISPATCH_FAILED,
            reason=f"p2_dispatch_failed:{reason[:80]}",
            actor="system",
        )

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


# ── Module-level helpers (used by dispatch_proactive and exported for tests) ──

def _enforce_flag_combination(phase: str, shadow_mode: bool, live_enabled: bool) -> None:
    """ADR-018 Invariant 1: `live_enabled=True` REQUIRES `shadow_mode=True`.

    Raises ForbiddenFlagCombination on the (False, True) combination.
    All other combinations are valid (DORMANT / SHADOW / LIVE).
    """
    if live_enabled and not shadow_mode:
        raise ForbiddenFlagCombination(
            f"phase={phase!r}: shadow_mode=False AND live_enabled=True is "
            f"FORBIDDEN (ADR-018 Invariant 1: live_enabled=True requires "
            f"shadow_mode=True)"
        )


def _compute_content_sha256(pkg: Dict[str, Any]) -> str:
    """Deterministic SHA256 over the dispatch package's canonical projection.

    Hash inputs: subject, body_text (Polish-first bilingual), recipient list,
    attachment labels (NOT paths — paths are environment-specific).

    Bytes never live in the manifest (ADR-006). Only this hash does.
    """
    projection = {
        "subject": pkg.get("subject", ""),
        "body_text": pkg.get("body_text", ""),
        "to": pkg.get("to") or [],
        "attachment_labels": sorted(
            (a.get("label", "") for a in (pkg.get("attachments") or [])),
        ),
    }
    canonical = json.dumps(projection, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

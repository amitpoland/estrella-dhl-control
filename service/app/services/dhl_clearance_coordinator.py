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


class ForceRequiresActor(Exception):
    """ADR-019: `force=True` on dispatch_proactive requires a non-empty actor.

    Force bypasses idempotency and re-emits dispatch. Audit trail MUST
    identify the operator. Admin route enforces min-3-char actor before
    calling coordinator; this is the coordinator-level guard.
    """


class CallerRejectsForce(Exception):
    """ADR-019 Invariant 4: sweep caller must never set force=True.

    Sweep is the automatic primary path; force is reserved for the admin
    HTTP override route. Mixing these would mask sweep bugs as operator
    actions.
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
    def is_awb_stable_for(awb: str, batch_id: Optional[str] = None) -> bool:
        """Read-only carrier predicate — see carrier/coordinator.is_awb_stable.

        Resolves the carrier shipment DB path from settings and passes the
        caller-supplied batch_id as the lookup key (batch_id is the carrier
        DB's primary index; AWB→batch_id direct resolver is operator-
        deferred per P0 spec, with batch_id passed by P2/P3/P4/P5 callers
        from their DispatchInput / TrackingEventInput / etc.).

        If batch_id is not provided OR the carrier DB does not exist on
        disk, returns False (safe-default for a stability predicate).
        """
        from .carrier.coordinator import is_awb_stable  # local — avoid eager import
        if not batch_id:
            return False
        # The carrier shipment DB lives under storage_root. The path is
        # derived the same way the carrier subsystem itself derives it
        # (see CarrierCoordinator construction in routes_carrier_actions.py).
        db_path = settings.storage_root / "carrier_shipments.db"
        if not db_path.exists():
            return False
        return bool(is_awb_stable(batch_id, db_path=db_path))

    # ── P2 — proactive dispatch (WIRED) ──────────────────────────────────────

    def dispatch_proactive(
        self,
        inp: "DispatchInput",
        *,
        caller: str = "sweep",
        force: bool = False,
        actor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fire the proactive customs dispatch for a Path A shipment.

        Parameters:
            inp:    DispatchInput dataclass (batch_id, awb, audit)
            caller: "sweep" | "admin_route"  — Model C ignition source (ADR-019)
            force:  When True, bypass the per-batch idempotency check and emit
                    a new dispatch even if a prior `p2_dispatch.message_id`
                    exists. Requires `caller=="admin_route"` and a non-empty
                    `actor`. Always emits a WARNING-level audit entry.
                    Forbidden when `caller=="sweep"` — raises `ForceRequiresActor`.
            actor:  Operator identity (required when force=True). Persisted in
                    audit log for forensic reconstruction. Min 3 chars enforced
                    by the admin route layer; coordinator only checks non-empty.

        Returns a result dict (ADR-019 truth table for `triggered_by`):
            {
              "status":         "shadow" | "sent" | "skipped" | "blocked",
              "reason":         <str>,
              "message_id":     <str|None>,
              "content_sha256": <hex>,
              "idempotent":     <bool>,
              "triggered_by":   "sweep" | "admin_override_normal" | "admin_override_force",
            }

        Behavior matrix (ADR-018):
          - shadow_mode=True,  live_enabled=False → SHADOW  (build + manifest, no send)
          - shadow_mode=True,  live_enabled=True  → LIVE    (queue email + manifest)
          - shadow_mode=False, live_enabled=False → DORMANT (no-op, status=skipped)
          - shadow_mode=False, live_enabled=True  → FORBIDDEN (raises)

        Force semantics (ADR-019):
          - force=False (default): existing idempotency behavior; second call
            returns the prior result with idempotent=True
          - force=True: bypasses idempotency, re-dispatches, appends to
            `audit.dhl_clearance.p2_dispatch_history[]` (prior message_id
            preserved for audit), emits WARNING-level audit. Subject to ALL
            other gates: scope, ADR-018 truth table, AWB stability, build.

        Raises:
            OutOfScopeError          — shipment is on Path B (agency_clearance)
            ForbiddenFlagCombination — `shadow_mode=False AND live_enabled=True`
            ForceRequiresActor       — `force=True` without a non-empty `actor`
            CallerRejectsForce       — `caller=="sweep"` AND `force=True`
        """
        # ── 0. Caller / force contract (ADR-019) ─────────────────────────────
        if caller == "sweep" and force:
            raise CallerRejectsForce(
                "sweep caller must never set force=True; force is reserved for "
                "admin_route per ADR-019"
            )
        if force and not (actor or "").strip():
            raise ForceRequiresActor(
                f"force=True requires a non-empty actor for audit "
                f"(batch_id={inp.batch_id!r})"
            )
        # Resolve triggered_by per ADR-019 truth table.
        if caller == "admin_route":
            triggered_by = "admin_override_force" if force else "admin_override_normal"
        else:
            triggered_by = "sweep"


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
                "triggered_by": triggered_by,
            }

        # ── 4. Idempotency — second call returns prior result ────────────────
        # Force=True (ADR-019) bypasses this check — it MUST advance to
        # rebuild + re-dispatch + record a new history entry. Prior dispatch
        # is preserved in `p2_dispatch_history[]` for forensic audit.
        manifest.init_manifest(inp.audit)
        prior = inp.audit["dhl_clearance"].get("p2_dispatch") or {}
        if prior.get("message_id") and not force:
            log.info(
                "selfclearance_p2_idempotent batch_id=%s message_id=%s caller=%s",
                inp.batch_id, prior.get("message_id"), caller,
            )
            return {
                "status": "shadow" if prior.get("shadow") else "sent",
                "reason": "already_dispatched",
                "message_id": prior.get("message_id"),
                "content_sha256": prior.get("content_sha256", ""),
                "idempotent": True,
                "triggered_by": triggered_by,
            }

        if prior.get("message_id") and force:
            # Force-path: archive prior dispatch into history before overwrite.
            log.warning(
                "selfclearance_p2_force_redispatch batch_id=%s actor=%s "
                "prior_message_id=%s caller=%s",
                inp.batch_id, actor, prior.get("message_id"), caller,
            )
            history = inp.audit["dhl_clearance"].setdefault("p2_dispatch_history", [])
            history.append({
                **prior,
                "archived_at":   _now_iso(),
                "archived_by":   actor,
                "archive_reason": "force_redispatch",
            })
            # Clear the current p2_dispatch so the manifest write below produces
            # a fresh entry. The history array preserves the prior message_id
            # for forensic reconstruction.
            inp.audit["dhl_clearance"]["p2_dispatch"] = {}

        # ── 5. AWB stability gate ────────────────────────────────────────────
        # Pass batch_id explicitly — see is_awb_stable_for docstring + Issue #38 F8.
        if not self.is_awb_stable_for(inp.awb, batch_id=inp.batch_id):
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
                "triggered_by": triggered_by,
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
            self._transition_to_dispatch_failed(inp.audit, exc.__class__.__name__)
            return {
                "status": "blocked",
                "reason": "build_failed",
                "message_id": None,
                "content_sha256": "",
                "idempotent": False,
                "triggered_by": triggered_by,
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
                "triggered_by": triggered_by,
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
            recipient = _normalise_recipient(pkg.get("to"))
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
                "triggered_by": triggered_by,
            }

        # LIVE state — actually queue the email.
        from .email_service import queue_email
        from ..config.email_routing import format_to, format_cc
        # Builder returns to/cc as strings (resolve_dhl_to/cc return str);
        # if a list slips in for any reason, normalise it. queue_email
        # expects a comma-separated string.
        to_str = _normalise_recipient(pkg.get("to"))
        cc_str = _normalise_recipient(pkg.get("cc"))
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
            self._transition_to_dispatch_failed(inp.audit, exc.__class__.__name__)
            return {
                "status": "blocked",
                "reason": "queue_failed",
                "message_id": None,
                "content_sha256": content_sha256,
                "idempotent": False,
                "triggered_by": triggered_by,
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
            "selfclearance_p2_sent batch_id=%s message_id=%s recipient=%s caller=%s",
            inp.batch_id, message_id, to_str, caller,
        )
        return {
            "status": "sent",
            "reason": "queued",
            "message_id": message_id,
            "content_sha256": content_sha256,
            "idempotent": False,
            "triggered_by": triggered_by,
        }

    # ── P2 state transition helpers ──────────────────────────────────────────

    @staticmethod
    def _advance_to_awaiting_poland_arrival(audit: Dict[str, Any], *, shadow: bool) -> None:
        """Advance state if currently awaiting_preemptive_send; otherwise no-op
        (caller may already be past this state, e.g. on idempotent retry).

        Per ADR-018 Invariant 4, when transitioning under shadow_mode=True
        the state_history entry carries an explicit `shadow: True` field so
        audit consumers can filter cleanly between observation-mode and
        live-mode transitions. The boolean is forwarded through
        `manifest.record_transition(shadow=shadow)` → `state_engine.transition`.
        """
        block = audit[manifest.MANIFEST_KEY]
        current = block.get("state", state_engine.INITIAL_STATE)
        if current != state_engine.STATE_AWAITING_PREEMPTIVE_SEND:
            log.warning(
                "selfclearance_p2_state_skew current=%s expected=%s — "
                "skipping advance to awaiting_poland_arrival (see F5/F6)",
                current, state_engine.STATE_AWAITING_PREEMPTIVE_SEND,
            )
            return
        manifest.record_transition(
            audit,
            state_engine.STATE_AWAITING_POLAND_ARRIVAL,
            reason="p2_dispatch",
            actor="system",
            shadow=shadow,
        )

    @staticmethod
    def _transition_to_dispatch_failed(audit: Dict[str, Any], reason: str) -> None:
        """Transition to dispatch_failed if currently awaiting_preemptive_send.

        Note: `reason` is the original exception's class name (NOT str(exc))
        to avoid persisting raw exception args into the audit. The caller
        passes `exc.__class__.__name__` per backend-safety + security-write-
        action reviewer recommendations.
        """
        manifest.init_manifest(audit)
        block = audit[manifest.MANIFEST_KEY]
        current = block.get("state", state_engine.INITIAL_STATE)
        if current != state_engine.STATE_AWAITING_PREEMPTIVE_SEND:
            log.warning(
                "selfclearance_p2_state_skew current=%s expected=%s — "
                "skipping transition to dispatch_failed (see F5/F6); "
                "operator must clear via dispatch_failed→awaiting_preemptive_send "
                "recovery before retry",
                current, state_engine.STATE_AWAITING_PREEMPTIVE_SEND,
            )
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

    Hash inputs: subject, body_text (Polish-first bilingual), recipient
    (normalised — see _normalise_recipient), attachment labels
    (NOT paths — paths are environment-specific).

    Bytes never live in the manifest (ADR-006). Only this hash does.
    """
    projection = {
        "subject": pkg.get("subject", ""),
        "body_text": pkg.get("body_text", ""),
        "to": _normalise_recipient(pkg.get("to")),
        "attachment_labels": sorted(
            (a.get("label", "") for a in (pkg.get("attachments") or [])),
        ),
    }
    canonical = json.dumps(projection, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalise_recipient(value: Any) -> str:
    """Normalise a builder-returned recipient value into a comma-separated string.

    The canonical builder (`dhl_proactive_dispatch_builder.build_dhl_proactive_dispatch`)
    returns `to` / `cc` as **strings** (output of `resolve_dhl_to()` / `resolve_dhl_cc()`).
    Test stubs and historical callers may pass `List[str]`. This helper accepts
    either and returns a comma-separated string suitable for `queue_email(to=...)`.

    Per integration-boundary review of P2 — without this normalisation, the
    coordinator would iterate over string characters and produce a corrupt
    "o,d,p,r,a,..." recipient that fails at SMTP delivery time.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        # Filter empty entries; join with comma (matches format_to/format_cc
        # convention in email_routing).
        return ", ".join(s.strip() for s in (str(v) for v in value) if s.strip())
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

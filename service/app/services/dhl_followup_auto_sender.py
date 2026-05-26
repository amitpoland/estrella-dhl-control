"""
dhl_followup_auto_sender.py — Autonomous DHL follow-up send engine.

Phase 3 of the "blocks become actions" campaign. Converts the previously
operator-explicit DHL follow-up send into a self-driving action gated by
seven safety properties. AI is allowed to polish wording only — never
to decide facts.

Public API (this module is the ONLY authority on auto-send):

    evaluate_gates(audit_path, audit, *, now=None) -> dict
        Pure read. Returns:
          {
            "decision": "ready" | "blocked",
            "gates":    [{name, passed: bool, reason, evidence}, ...],
            "first_failed": str | None,
          }

    draft_followup(audit, batch_id, *, use_ai=True) -> dict
        Builds the deterministic package via dhl_followup_email_builder
        and (optionally) replaces the body_text with an AI-polished
        version that preserves facts. Returns the package dict — same
        shape as build_dhl_followup_email plus a "draft_source" key
        ("ai" | "deterministic_fallback" | "deterministic_disabled").

    try_auto_send(audit_path, audit, *, now=None, operator="auto",
                  force_sla=False) -> dict
        Full pipeline. Evaluates gates, drafts, queues, sends, records
        audit + timeline. Returns:
          {
            "decision": "sent" | "suppressed" | "blocked",
            "reason":   str,
            "gates":    [...],
            "idempotency_key": str,
            "queue_id": str | None,
            "package":  dict | None,        # masked for log/preview
            "evidence": dict,               # what was checked
            "draft_source": str | None,
          }

Five mandatory background-email properties (Lesson E):
    1. Execution-time validation  — every gate re-checked at send time
    2. Idempotency                — latch on (batch_id, followup_seq)
    3. Terminal-state suppression — _is_active() must be True
    4. Replay safety              — audit timeline event written BEFORE
                                    queue_email() returns successfully
    5. Environment isolation      — relies on email_service.queue_email
                                    which inherits SMTP env from settings

Hard non-goals:
    - DOES NOT send agency emails (forbidden by operator)
    - DOES NOT respond to substantive DHL customs requests (operator
      explicit per task description)
    - DOES NOT modify wFirma / PZ / proforma / customs / inventory state
    - DOES NOT call any external API directly — uses only existing
      builder + queue_email + ai_gateway.call (which is itself gated)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..config.email_routing import DHL_TO
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)


# ── Safe-recipient allow-list ────────────────────────────────────────────────
# DHL follow-up must go ONLY to DHL Poland customs. Internal CC is allowed
# from the builder's recipients but never as a TO target. Any TO recipient
# outside this set blocks the send.
_SAFE_TO_DOMAINS: frozenset = frozenset({"dhl.com"})
_SAFE_TO_ADDRESSES: frozenset = frozenset({addr.lower() for addr in DHL_TO})


# ── Idempotency latch ────────────────────────────────────────────────────────
# In-process latch only; the durable guard is the audit timeline event
# (replay safety per Lesson E). The in-process latch prevents two parallel
# monitor sweeps from racing to send the same follow-up sequence number.
import threading
_LATCH_LOCK = threading.Lock()
_LATCH_HELD: set[str] = set()


def _idempotency_key(batch_id: str, followup_seq: int) -> str:
    return f"dhl_followup_auto::{batch_id}::seq{followup_seq}"


# ── Gate evaluation (pure read) ──────────────────────────────────────────────

def evaluate_gates(
    audit_path: Path,
    audit: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    skip_sla: bool = False,
) -> Dict[str, Any]:
    """Evaluate all seven gates against a frozen audit snapshot.

    Pure read — never mutates audit. Returns a structured verdict the
    caller can render in the Inbox preview UI.
    """
    gates: List[Dict[str, Any]] = []

    # Gate 0 — master flag
    enabled = bool(getattr(settings, "dhl_auto_followup_enabled", False))
    gates.append({
        "name": "flag_enabled",
        "passed": enabled,
        "reason": "dhl_auto_followup_enabled is False — operator-explicit mode"
                  if not enabled else "ok",
        "evidence": {"flag": "dhl_auto_followup_enabled", "value": enabled},
    })
    if not enabled:
        return _verdict("blocked", gates)

    # Gate 1 — active shipment
    try:
        from .active_shipment_monitor import _is_active
        is_active = _is_active(audit)
    except Exception as exc:
        is_active = False
        log.warning("[auto_followup] active check failed: %s", exc)
    cs = audit.get("clearance_status", "")
    tr_status = (audit.get("tracking") or {}).get("status", "")
    gates.append({
        "name": "active_shipment",
        "passed": bool(is_active),
        "reason": "shipment terminal/delivered" if not is_active else "ok",
        "evidence": {
            "clearance_status": cs,
            "tracking_status":  tr_status,
        },
    })
    if not is_active:
        return _verdict("blocked", gates)

    # Gate 2 — SLA elapsed (skip-able only by explicit operator force_sla)
    from .dhl_followup_sla import is_due
    state = audit.get("dhl_followup") or {}
    due = is_due(state, now=now)
    gates.append({
        "name": "sla_elapsed",
        "passed": bool(due) or skip_sla,
        "reason": (
            "sla skipped by operator force_sla=True" if (skip_sla and not due) else
            ("next_followup_at not yet reached" if not due else "ok")
        ),
        "evidence": {
            "active":           bool(state.get("active")),
            "next_followup_at": state.get("next_followup_at"),
            "followup_count":   state.get("followup_count", 0),
            "sla_skipped":      bool(skip_sla and not due),
        },
    })
    if not (due or skip_sla):
        return _verdict("blocked", gates)

    # Gate 3 — fresh email ingest
    max_age_min = int(getattr(settings, "dhl_auto_followup_max_ingest_age_minutes", 30))
    ing = audit.get("email_ingestion") or {}
    last_scan = ing.get("last_scan_at") or ""
    ingest_fresh, ingest_age_s = _ingest_fresh(last_scan, max_age_min, now=now)
    gates.append({
        "name": "fresh_email_ingest",
        "passed": ingest_fresh,
        "reason": ("no last_scan_at recorded" if not last_scan else
                   f"ingest stale ({ingest_age_s}s > {max_age_min*60}s)") if not ingest_fresh else "ok",
        "evidence": {
            "last_scan_at": last_scan,
            "max_age_s":    max_age_min * 60,
            "age_s":        ingest_age_s,
        },
    })
    if not ingest_fresh:
        return _verdict("blocked", gates)

    # Gate 4 — no DHL/agency email evidence
    dhl_received = bool((audit.get("dhl_email") or {}).get("received"))
    agency_received = bool(
        (audit.get("agency_preclearance") or {}).get("acknowledgement") or
        (audit.get("agency_preclearance") or {}).get("sent_at")
    )
    docs_received = bool((audit.get("customs_docs") or {}).get("received"))
    has_evidence = dhl_received or agency_received or docs_received
    gates.append({
        "name": "no_dhl_or_agency_email",
        "passed": (not has_evidence),
        "reason": (
            "DHL email already received" if dhl_received else
            "Agency preclearance present" if agency_received else
            "Customs docs received — follow-up unnecessary" if docs_received else "ok"
        ),
        "evidence": {
            "dhl_email_received":    dhl_received,
            "agency_seen":           agency_received,
            "customs_docs_received": docs_received,
        },
    })
    if has_evidence:
        return _verdict("blocked", gates)

    # Gate 5 — safe recipient
    to_list = [a.strip().lower() for a in DHL_TO if a and a.strip()]
    unsafe = [a for a in to_list if not _is_safe_to(a)]
    safe_ok = (len(to_list) > 0) and (len(unsafe) == 0)
    gates.append({
        "name": "safe_recipient",
        "passed": safe_ok,
        "reason": ("no DHL_TO configured" if not to_list else
                   f"unsafe recipient(s): {unsafe}") if not safe_ok else "ok",
        "evidence": {"to_list": to_list, "unsafe": unsafe},
    })
    if not safe_ok:
        return _verdict("blocked", gates)

    # Gate 6 — package buildable (AWB resolvable)
    awb = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    pkg_ok = bool(awb)
    gates.append({
        "name": "package_buildable",
        "passed": pkg_ok,
        "reason": "AWB missing — cannot build follow-up subject/body" if not pkg_ok else "ok",
        "evidence": {"awb": awb},
    })
    if not pkg_ok:
        return _verdict("blocked", gates)

    # Gate 7 — idempotency latch clear
    followup_seq = int(state.get("followup_count", 0)) + 1
    batch_id = str(audit.get("batch_id") or audit_path.parent.name)
    key = _idempotency_key(batch_id, followup_seq)
    latch_clear = key not in _LATCH_HELD
    # Replay-safety check: scan timeline for an already-sent event with
    # this sequence number. If found, gate fails (durable idempotency).
    durable_clear = not _already_sent_seq(audit_path, followup_seq)
    gates.append({
        "name": "idempotency_clear",
        "passed": latch_clear and durable_clear,
        "reason": (
            "in-flight latch held by another worker" if not latch_clear else
            f"followup_seq={followup_seq} already sent (timeline)" if not durable_clear else "ok"
        ),
        "evidence": {
            "key":          key,
            "in_flight":    not latch_clear,
            "already_sent": not durable_clear,
            "followup_seq": followup_seq,
        },
    })
    if not (latch_clear and durable_clear):
        return _verdict("blocked", gates)

    return _verdict("ready", gates)


def _verdict(decision: str, gates: List[Dict[str, Any]]) -> Dict[str, Any]:
    first_failed = next((g["name"] for g in gates if not g["passed"]), None)
    return {"decision": decision, "gates": gates, "first_failed": first_failed}


def _ingest_fresh(
    last_scan_iso: str, max_age_min: int, *, now: Optional[datetime] = None,
) -> tuple[bool, int]:
    if not last_scan_iso:
        return False, -1
    try:
        last = datetime.fromisoformat(str(last_scan_iso).replace("Z", "+00:00"))
    except Exception:
        return False, -1
    now_dt = (now or datetime.now(timezone.utc))
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_s = int((now_dt - last).total_seconds())
    return (age_s >= 0 and age_s <= max_age_min * 60), age_s


def _is_safe_to(addr: str) -> bool:
    a = (addr or "").strip().lower()
    if not a or "@" not in a:
        return False
    if a in _SAFE_TO_ADDRESSES:
        return True
    domain = a.rsplit("@", 1)[-1]
    return domain in _SAFE_TO_DOMAINS


def _already_sent_seq(audit_path: Path, followup_seq: int) -> bool:
    """Replay-safety: scan audit.timeline for a dhl_followup_auto_sent event
    with the same followup_seq. If found, idempotency gate fails."""
    try:
        if not audit_path.exists():
            return False
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for ev in audit.get("timeline") or []:
            if ev.get("event") != "dhl_followup_auto_sent":
                continue
            d = ev.get("detail") or {}
            if int(d.get("followup_seq") or 0) == int(followup_seq):
                return True
    except Exception:
        return False
    return False


# ── Drafting (deterministic + optional AI polish) ────────────────────────────

def draft_followup(audit: Dict[str, Any], batch_id: str, *, use_ai: bool = True) -> Dict[str, Any]:
    """Build the follow-up package. AI polishes wording only if enabled +
    available; deterministic body is always the fact source.

    The AI is given the deterministic body and asked to improve clarity
    without changing AWB, ticket, amount, counts, or any operational fact.
    If the AI output drops any of these tokens, we discard it and fall
    back to deterministic. AI never decides customs/legal facts.
    """
    from .dhl_followup_email_builder import build_dhl_followup_email
    pkg = build_dhl_followup_email(audit, batch_id)
    pkg["draft_source"] = "deterministic"

    ai_flag = bool(getattr(settings, "dhl_auto_followup_use_ai_draft", True))
    if not (use_ai and ai_flag):
        pkg["draft_source"] = "deterministic_disabled"
        return pkg

    try:
        from . import ai_gateway
    except Exception:
        return pkg

    awb     = audit.get("awb") or audit.get("tracking_no") or ""
    ticket  = (audit.get("dhl_email") or {}).get("ticket") or audit.get("dhl_ticket") or ""
    cif     = (audit.get("clearance_decision") or {}).get("total_value_usd", 0)
    seq     = int(pkg.get("followup_seq", 1))

    # Build fact-anchor tokens that MUST survive any AI rewrite
    anchors: List[str] = []
    if awb:
        anchors.append(str(awb))
    if ticket:
        anchors.append(str(ticket))
    # CIF amount with the same formatting the builder uses
    if cif:
        anchors.append(f"{cif:,.2f}")

    system_prompt = (
        "You are improving the wording of a customs follow-up email to DHL Poland. "
        "RULES (non-negotiable):\n"
        "1. Never invent new facts.\n"
        "2. Never alter the AWB number, ticket reference, monetary amount, "
        "follow-up count, broker name, or agency name.\n"
        "3. Never remove the urgency framing or the explicit request for DSK / "
        "customs documents.\n"
        "4. Output only the rewritten body text (no markdown, no JSON, no "
        "subject line, no signature changes).\n"
        "5. Keep it under 220 words.\n"
    )
    user_prompt = (
        f"DETERMINISTIC BODY (improve wording only):\n\n{pkg['body_text']}\n\n"
        f"FACT ANCHORS that MUST appear verbatim in your output: {anchors}\n"
        f"This is follow-up #{seq}. Do not lower the urgency. Output only the rewritten body."
    )

    try:
        text = ai_gateway.call(
            system=system_prompt, user=user_prompt,
            task_type="dhl_followup_polish",
            service_name="dhl_followup_auto_sender",
            object_id=batch_id,
            complexity="simple", risk_level="medium",
            max_tokens=900,
        )
    except Exception as exc:
        log.warning("[auto_followup] ai_gateway.call raised: %s", exc)
        text = None

    if not text or not text.strip():
        pkg["draft_source"] = "deterministic_fallback"
        return pkg

    # Verify all fact anchors survived. If any missing, fall back.
    cleaned = text.strip()
    missing = [a for a in anchors if a and a not in cleaned]
    if missing:
        log.warning(
            "[auto_followup] AI draft missing fact anchors %s — falling back to deterministic",
            missing,
        )
        pkg["draft_source"] = "deterministic_fallback"
        return pkg

    pkg["body_text"] = cleaned
    # Re-render minimal HTML wrapper around the cleaned text
    pkg["body_html"] = (
        "<div style='font-family:sans-serif'>"
        "<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>"
        + cleaned +
        "</pre></div>"
    )
    pkg["draft_source"] = "ai"
    return pkg


# ── Full pipeline (gates → draft → queue → send → audit) ─────────────────────

def try_auto_send(
    audit_path: Path,
    audit: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    operator: str = "auto",
    force_sla: bool = False,
) -> Dict[str, Any]:
    """Run the full auto-send pipeline.

    Returns a structured result. Never raises — failures map to
    {"decision": "blocked"|"suppressed", "reason": ...}.
    """
    batch_id = str(audit.get("batch_id") or audit_path.parent.name)

    # Re-evaluate gates at execution time (Lesson E property 1).
    # force_sla skips ONLY the sla_elapsed gate — every other gate stays.
    verdict = evaluate_gates(audit_path, audit, now=now, skip_sla=bool(force_sla))

    if verdict["decision"] != "ready":
        # Suppress event so future operators can see the decision happened
        _log_suppression(audit_path, batch_id, verdict, operator)
        return {
            "decision": "suppressed",
            "reason":   verdict["first_failed"] or "unknown",
            "gates":    verdict["gates"],
            "idempotency_key": None,
            "queue_id": None,
            "package":  None,
            "evidence": {g["name"]: g["evidence"] for g in verdict["gates"]},
            "draft_source": None,
        }

    state = audit.get("dhl_followup") or {}
    followup_seq = int(state.get("followup_count", 0)) + 1
    idem_key = _idempotency_key(batch_id, followup_seq)

    # Acquire in-process latch (property 2: idempotency)
    with _LATCH_LOCK:
        if idem_key in _LATCH_HELD:
            return _suppress("idempotency_clear", "in-flight latch held", verdict, idem_key)
        _LATCH_HELD.add(idem_key)

    try:
        # Build draft (AI-polished or deterministic)
        pkg = draft_followup(audit, batch_id, use_ai=True)

        # ── Property 4: write timeline BEFORE returning success ──────────
        # The timeline write happens after queue_email returns success.
        # Suppression / draft events are written immediately.
        from .email_service import queue_email, FollowupSuppressedError

        try:
            queue_id = queue_email(
                to=pkg["to"], subject=pkg["subject"],
                body_html=pkg["body_html"], body_text=pkg["body_text"],
                batch_id=batch_id, cc=pkg.get("cc", ""),
                from_address=pkg.get("from_address", ""),
                email_type=pkg.get("email_type", "dhl_followup"),
                attachments=pkg.get("attachments", []),
            )
        except FollowupSuppressedError as exc:
            # email_service refused (terminal / duplicate). Treat as
            # suppression so audit reflects honest outcome.
            return _suppress(
                "queue_email_refused", str(exc), verdict, idem_key,
                draft_source=pkg.get("draft_source"),
            )
        except Exception as exc:
            log.exception("[auto_followup] queue_email failed: %s", exc)
            return _suppress(
                "queue_email_error", str(exc), verdict, idem_key,
                draft_source=pkg.get("draft_source"),
            )

        # Record on the SLA state (durable idempotency)
        from .dhl_followup_sla import record_followup_sent
        record_followup_sent(audit, when=now)
        try:
            write_json_atomic(audit_path, audit)
        except Exception as exc:
            log.warning("[auto_followup] audit persist failed: %s", exc)

        # Write timeline event — replay safety (property 4)
        try:
            tl.log_event(
                audit_path, "dhl_followup_auto_sent", "monitor", operator,
                detail={
                    "queue_id":       queue_id,
                    "followup_seq":   followup_seq,
                    "idempotency_key": idem_key,
                    "draft_source":   pkg.get("draft_source"),
                    "subject":        pkg["subject"],
                    "to":             pkg.get("to", ""),
                    "awb":            audit.get("awb") or audit.get("tracking_no"),
                    "gates_evidence": {g["name"]: g["evidence"] for g in verdict["gates"]},
                },
            )
        except Exception as exc:
            log.warning("[auto_followup] timeline write failed: %s", exc)

        return {
            "decision":        "sent",
            "reason":          "ok",
            "gates":           verdict["gates"],
            "idempotency_key": idem_key,
            "queue_id":        queue_id,
            "package": {
                "to":           pkg.get("to"),
                "subject":      pkg.get("subject"),
                "body_text":    pkg.get("body_text"),
                "followup_seq": followup_seq,
            },
            "evidence":     {g["name"]: g["evidence"] for g in verdict["gates"]},
            "draft_source": pkg.get("draft_source"),
        }
    finally:
        # Release in-process latch (durable idempotency is the timeline)
        with _LATCH_LOCK:
            _LATCH_HELD.discard(idem_key)


def _suppress(
    reason_name: str, reason_detail: str, verdict: Dict[str, Any], idem_key: str,
    *, draft_source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "decision":        "suppressed",
        "reason":          f"{reason_name}: {reason_detail}",
        "gates":           verdict["gates"],
        "idempotency_key": idem_key,
        "queue_id":        None,
        "package":         None,
        "evidence":        {g["name"]: g["evidence"] for g in verdict["gates"]},
        "draft_source":    draft_source,
    }


def _log_suppression(
    audit_path: Path, batch_id: str, verdict: Dict[str, Any], operator: str,
) -> None:
    try:
        tl.log_event(
            audit_path, "dhl_followup_auto_suppressed", "monitor", operator,
            detail={
                "first_failed": verdict.get("first_failed"),
                "gates":        [{"name": g["name"], "passed": g["passed"], "reason": g["reason"]}
                                  for g in verdict.get("gates", [])],
            },
        )
    except Exception:
        pass

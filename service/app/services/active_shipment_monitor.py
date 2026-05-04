"""
active_shipment_monitor.py — Periodic active-shipment sweeper.

Runs (via /api/v1/monitor/active-shipments/run or cron) over every
non-terminal batch and:
  1. Checks email intelligence cache for verified DHL/agency evidence
  2. Applies derived events (with rank-guard — never downgrades state)
  3. Dispatches a NEW AI Bridge email_scan task only when:
       - no verified cache
       - no pending task within COOLDOWN_MINUTES
  4. Surfaces SLA risks (DHL email overdue at Warsaw, etc.)
  5. Returns a structured action summary

Read-mostly: never modifies CIF/duty/invoice/PZ/financial fields.
Audit writes are limited to:
  - clearance_status (rank-guarded)
  - dhl_email, agency_preclearance
  - email_scan_results, email_search_risk*
  - timeline events
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic

log = logging.getLogger(__name__)

COOLDOWN_MINUTES = 10
WARSAW_DHL_EMAIL_SLA_HOURS = 6
DHL_REPLY_AFTER_EMAIL_SLA_MINUTES = 10
TRIGGER_RETRY_MINUTES = 10

# Statuses considered terminal — sweeper skips these unless force=True
_TERMINAL_CLEARANCE_STATUSES = frozenset({
    "delivered",
    "agency_email_sent",
    "reply_sent",
    "shipment_released",
})

# clearance_status rank table — duplicated from routes_ai_bridge for self-containment
_STATUS_ORDER = {
    "":                              0,
    "draft":                         0,
    "awaiting_dhl_customs_email":    1,
    "dhl_email_received":            2,
    "polish_description_generated":  3,
    "agency_email_queued":           4,
    "agency_email_sent":             4,
    "delivered":                     5,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _all_audit_paths() -> List[Path]:
    """Find every batch audit.json under storage/outputs/."""
    out: List[Path] = []
    base = settings.storage_root / "outputs"
    if not base.exists():
        return out
    for p in base.glob("*/audit.json"):
        out.append(p)
    return out


def _is_active(audit: Dict[str, Any]) -> bool:
    """A shipment is active if it hasn't reached a terminal clearance + tracking state."""
    clearance = audit.get("clearance_status", "")
    if clearance in _TERMINAL_CLEARANCE_STATUSES:
        # Even if clearance is sent, tracking-not-delivered still counts as active for monitoring
        # But the explicit operator-confirmed "agency_email_sent + verified" we treat as done
        if clearance == "agency_email_sent" and (audit.get("agency_reply_package") or {}).get("send_verified") is True:
            return False
    # Check tracking — if delivered AND clearance complete, terminal
    tr = audit.get("tracking") or {}
    if tr.get("status") == "delivered" and clearance in _TERMINAL_CLEARANCE_STATUSES:
        return False
    return True


def _recent_pending_task_for_awb(awb: str, cooldown_minutes: int = COOLDOWN_MINUTES) -> Optional[str]:
    """Return task_id of a pending email_scan task for this AWB created within cooldown window."""
    if not awb:
        return None
    tasks_dir = settings.storage_root / "ai_bridge" / "tasks"
    if not tasks_dir.exists():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    for tf in tasks_dir.glob("*.json"):
        try:
            t = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if t.get("task_type") != "email_scan":
            continue
        if (t.get("payload") or {}).get("awb") != awb:
            continue
        try:
            ct = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if ct >= cutoff:
            return t.get("task_id")
    return None


def _apply_cache_to_audit(audit_path: Path, audit: Dict[str, Any], cached: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply a cached email intelligence record to a batch audit.

    Rank-guarded: never downgrades clearance_status. Returns a result summary.
    """
    summary: Dict[str, Any] = {
        "applied":              False,
        "advanced_status":      None,
        "wrote_dhl_email":      False,
        "wrote_preclearance":   False,
        "timeline_events_added": [],
    }
    derived = cached.get("derived_events") or []
    if not derived:
        return summary

    now_iso = datetime.now(timezone.utc).isoformat()
    current_status = audit.get("clearance_status", "")
    current_rank   = _STATUS_ORDER.get(current_status, 0)

    # ── DHL customs email ────────────────────────────────────────────────────
    # Write dhl_email evidence ALWAYS when detected — it's informational metadata.
    # Only the clearance_status advance is rank-guarded (never go backwards).
    dhl_event = next((e for e in derived if e.get("event") == "dhl_customs_email_received"), None)
    # Idempotency: if the same DHL ticket has already been applied to this
    # audit (dhl_email.received + matching ticket), skip the rewrite AND
    # mark the timeline event as "duplicate" so we don't pollute the log
    # on every monitor sweep.
    dhl_dup = False
    if dhl_event:
        existing = audit.get("dhl_email") or {}
        ev_ticket  = (dhl_event.get("ticket")  or "").strip()
        cur_ticket = (existing.get("ticket")    or "").strip()
        if existing.get("received") and ev_ticket and ev_ticket == cur_ticket:
            dhl_dup = True
    if dhl_event and not dhl_dup:
        audit["dhl_email"] = {
            "received":     True,
            "source":       "active_shipment_monitor",
            "sender":       dhl_event.get("source_email_from", ""),
            "subject":      dhl_event.get("source_email_subject", ""),
            "ticket":       dhl_event.get("ticket", ""),
            "request_type": dhl_event.get("request_type", "unknown"),
            "received_at":  dhl_event.get("timestamp") or now_iso,
            "confidence":   dhl_event.get("confidence", ""),
            "applied_via":  "monitor",
        }
        if dhl_event.get("ticket"):
            audit["dhl_ticket"] = dhl_event["ticket"]
        summary["wrote_dhl_email"] = True
        # Status advance — rank-guarded
        if current_rank < _STATUS_ORDER["dhl_email_received"]:
            audit["clearance_status"]     = "dhl_email_received"
            audit["clearance_updated_at"] = now_iso
            summary["advanced_status"]    = "dhl_email_received"

    # ── Agency pre-clearance ─────────────────────────────────────────────────
    pre_sent = next((e for e in derived if e.get("event") == "agency_preclearance_sent"), None)
    pre_ack  = next((e for e in derived if e.get("event") == "agency_acknowledged"), None)
    if pre_sent or pre_ack:
        pre = audit.get("agency_preclearance") or {}
        if pre_sent:
            pre.update({
                "source":     "active_shipment_monitor",
                "sent_at":    pre_sent.get("timestamp") or now_iso,
                "subject":    pre_sent.get("source_email_subject", ""),
                "from":       pre_sent.get("source_email_from", ""),
                "confidence": pre_sent.get("confidence", ""),
            })
        if pre_ack:
            pre["acknowledgement"] = {
                "from":      pre_ack.get("source_email_from", ""),
                "subject":   pre_ack.get("source_email_subject", ""),
                "timestamp": pre_ack.get("timestamp") or now_iso,
            }
        audit["agency_preclearance"]  = pre
        summary["wrote_preclearance"] = True

    write_json_atomic(audit_path, audit)

    # ── Timeline events for everything new ───────────────────────────────────
    for ev in derived:
        et = ev.get("event")
        if not et:
            continue
        # Suppress duplicate dhl_customs_email_received for an already-applied ticket
        if et == "dhl_customs_email_received" and dhl_dup:
            continue
        try:
            tl.log_event(audit_path, et, "monitor", "active_shipment_monitor",
                         detail={"auto_applied":   True,
                                 "source_subject": ev.get("source_email_subject", ""),
                                 "source_from":    ev.get("source_email_from", ""),
                                 "ticket":         ev.get("ticket", ""),
                                 "via":            "active_shipment_monitor"})
            summary["timeline_events_added"].append(et)
        except Exception:
            pass

    summary["applied"]      = bool((dhl_event and not dhl_dup) or pre_sent or pre_ack)
    summary["dhl_duplicate"] = dhl_dup
    return summary


def _hours_since(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _evaluate_sla(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute SLA flags for a shipment. Read-only.

    Returns:
        {
          dhl_email_overdue:     bool,
          dhl_reply_overdue:     bool,
          required_actions:      list[str],
          high_value:            bool,
        }
    """
    out = {
        "dhl_email_overdue": False,
        "dhl_reply_overdue": False,
        "required_actions":  [],
        "high_value":        False,
    }
    cd = audit.get("clearance_decision") or {}
    cif = cd.get("total_value_usd") or 0
    out["high_value"] = (cif or 0) > 2500 or cd.get("clearance_path") == "external_agency_clearance"

    # SLA: Warsaw arrival → DHL email within 6h
    tr = audit.get("tracking") or {}
    if tr.get("last_location", "").upper().find("WARSAW") >= 0:
        elapsed = _hours_since(tr.get("last_update"))
        if elapsed and elapsed > WARSAW_DHL_EMAIL_SLA_HOURS:
            if not (audit.get("dhl_email") or {}).get("received"):
                out["dhl_email_overdue"] = True

    # SLA: DHL email received → reply queued within 10 min (high-value only)
    dhl = audit.get("dhl_email") or {}
    if dhl.get("received") and out["high_value"]:
        elapsed_min = (_hours_since(dhl.get("received_at")) or 0) * 60.0
        # The reply is "done" when ANY of these is true:
        #   1. dhl_reply_package.status == "sent" (set by send_queued_email)
        #   2. timeline contains dhl_reply_sent_verified
        #   3. legacy: audit.dhl_reply.queued (older audits)
        #   4. clearance_status has already advanced past the reply step
        reply_pkg_status = (audit.get("dhl_reply_package") or {}).get("status") or ""
        timeline_sent = any(
            (e or {}).get("event") == "dhl_reply_sent_verified"
            for e in (audit.get("timeline") or [])
        )
        reply_queued = (
            reply_pkg_status == "sent"
            or timeline_sent
            or (audit.get("dhl_reply") or {}).get("queued")
            or audit.get("clearance_status") in (
                "polish_description_generated", "agency_email_queued", "agency_email_sent"
            )
        )
        if elapsed_min > DHL_REPLY_AFTER_EMAIL_SLA_MINUTES and not reply_queued:
            out["dhl_reply_overdue"] = True

    # Required actions, path-aware
    if dhl.get("received"):
        if not audit.get("polish_desc_filename"):
            out["required_actions"].append("generate_polish_description")
        if out["high_value"]:
            if not (audit.get("agency_reply_package") or {}).get("status"):
                out["required_actions"].append("build_agency_package")
            if not (audit.get("dhl_reply_package") or {}).get("status"):
                out["required_actions"].append("build_dhl_dsk_reply")
        else:
            # Low-value DHL self-clearance path
            if not (audit.get("dhl_self_clearance_reply_package") or {}).get("status"):
                out["required_actions"].append("build_dhl_self_clearance_reply")

    return out


# ── DHL reply auto-build + auto-send ─────────────────────────────────────────

def _ensure_dhl_reply(audit_path: Path, audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Branch by clearance_path when DHL email is received:

      external_agency_clearance (CIF > $2,500)
          → build DHL DSK transfer reply (broker assignment)
          → audit.dhl_reply_package
      carrier_self_clearance (CIF ≤ $2,500)
          → build DHL self-clearance reply (full doc set, in-thread)
          → audit.dhl_self_clearance_reply_package

    Auto-sends via SMTP when configured. Idempotent — skips when package
    already queued/sent.
    """
    out: Dict[str, Any] = {"built": False, "sent": False, "error": None}
    cd   = audit.get("clearance_decision") or {}
    path = cd.get("clearance_path") or ""
    cif  = cd.get("total_value_usd") or 0
    dhl_received = bool((audit.get("dhl_email") or {}).get("received"))

    if not dhl_received:
        return out

    # Branch by clearance path
    is_high_value = path == "external_agency_clearance" or (cif or 0) > 2500
    is_low_value  = path == "carrier_self_clearance"     or (0 < (cif or 0) <= 2500)

    if is_high_value:
        return _ensure_dhl_dsk_transfer_reply(audit_path, audit)
    if is_low_value:
        return _ensure_dhl_self_clearance_reply(audit_path, audit)
    return out


def _ensure_dhl_dsk_transfer_reply(audit_path: Path, audit: Dict[str, Any]) -> Dict[str, Any]:
    """High-value: build DHL DSK transfer reply (existing builder)."""
    out: Dict[str, Any] = {"built": False, "sent": False, "error": None, "path": "external_agency_clearance"}
    drp = audit.get("dhl_reply_package") or {}
    if drp.get("status"):
        return out
    try:
        from .dhl_reply_builder import build_dhl_reply_package
        from .email_service     import queue_email
        pkg = build_dhl_reply_package(audit, audit_path.parent.name)

        # Validate attachments exist
        existing = [a for a in pkg.get("attachments", [])
                    if Path(a.get("path", "")).is_file()]
        if not existing:
            out["error"] = "no_attachments_on_disk"
            return out

        body_text = pkg["body_text"]
        body_html = pkg["body_html"]
        email_id = queue_email(
            to=pkg["to"], subject=pkg["subject"],
            body_html=body_html, body_text=body_text,
            batch_id=audit_path.parent.name,
            cc=pkg.get("cc", ""),
            from_address=pkg.get("from_address", ""),
            email_type=pkg.get("email_type", "dhl_reply"),
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        audit["dhl_reply_package"] = {
            "from_address": pkg.get("from_address", ""),
            "to":           pkg["to"],
            "to_list":      pkg.get("to_list", []),
            "cc":           pkg.get("cc", ""),
            "cc_list":      pkg.get("cc_list", []),
            "subject":      pkg["subject"],
            "body_text":    body_text,
            "body_html":    body_html,
            "attachments":  existing,
            "ticket":       pkg.get("ticket", ""),
            "email_id":     email_id,
            "status":       "queued",
            "queued_at":    now_iso,
            "source":       "monitor_auto_after_dhl_email",
            "awb_attached": pkg.get("awb_attached", False),
        }
        write_json_atomic(audit_path, audit)
        out["built"] = True
        out["email_id"] = email_id

        try:
            tl.log_event(audit_path, "dhl_reply_package_auto_built",
                         "monitor", "active_shipment_monitor",
                         detail={"email_id": email_id, "ticket": pkg.get("ticket", "")})
        except Exception:
            pass

        # Auto-send if SMTP is configured
        from .email_sender import send_queued_email, _smtp_configured
        if _smtp_configured():
            send_result = send_queued_email(email_id, method="smtp")
            if send_result.get("ok") and send_result.get("status") == "sent":
                out["sent"] = True
                out["provider_message_id"] = send_result.get("provider_message_id")
            else:
                out["error"] = f"send_failed: {send_result.get('error')}"
        else:
            out["error"] = "smtp_not_configured"

    except Exception as exc:
        out["error"] = f"build_failed: {exc}"

    return out


def _ensure_dhl_self_clearance_reply(audit_path: Path, audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Low-value (carrier_self_clearance): build DHL reply that includes the full
    document set so DHL can self-clear directly. No agency, no DSK transfer.
    """
    out: Dict[str, Any] = {"built": False, "sent": False, "error": None,
                            "path": "carrier_self_clearance"}
    pkg_existing = audit.get("dhl_self_clearance_reply_package") or {}
    if pkg_existing.get("status"):
        return out
    try:
        from .dhl_self_clearance_builder import build_dhl_self_clearance_reply
        from .email_service              import queue_email
        pkg = build_dhl_self_clearance_reply(audit, audit_path.parent.name)

        existing = [a for a in pkg.get("attachments", [])
                    if Path(a.get("path", "")).is_file()]
        if not existing:
            out["error"] = "no_attachments_on_disk"
            return out

        # AWB-required block: if AWB number exists but no PDF attached, refuse
        if (audit.get("awb") or audit.get("tracking_no")) and not pkg.get("awb_attached"):
            out["error"] = "awb_pdf_missing"
            out["error_detail"] = "AWB PDF missing from clearance package"
            return out

        body_text = pkg["body_text"]
        body_html = pkg["body_html"]
        email_id = queue_email(
            to=pkg["to"], subject=pkg["subject"],
            body_html=body_html, body_text=body_text,
            batch_id=audit_path.parent.name,
            cc=pkg.get("cc", ""),
            from_address=pkg.get("from_address", ""),
            email_type=pkg.get("email_type", "dhl_self_clearance_reply"),
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        audit["dhl_self_clearance_reply_package"] = {
            "from_address": pkg.get("from_address", ""),
            "to":           pkg["to"],
            "to_list":      pkg.get("to_list", []),
            "cc":           pkg.get("cc", ""),
            "cc_list":      pkg.get("cc_list", []),
            "subject":      pkg["subject"],
            "body_text":    body_text,
            "body_html":    body_html,
            "attachments":  existing,
            "ticket":       pkg.get("ticket", ""),
            "email_id":     email_id,
            "status":       "queued",
            "queued_at":    now_iso,
            "source":       "monitor_auto_after_dhl_email",
            "awb_attached": pkg.get("awb_attached", False),
        }
        write_json_atomic(audit_path, audit)
        out["built"] = True
        out["email_id"] = email_id

        try:
            tl.log_event(audit_path, "dhl_self_clearance_reply_auto_built",
                         "monitor", "active_shipment_monitor",
                         detail={"email_id": email_id, "ticket": pkg.get("ticket", "")})
        except Exception:
            pass

        # Auto-send if SMTP configured
        from .email_sender import send_queued_email, _smtp_configured
        if _smtp_configured():
            send_result = send_queued_email(email_id, method="smtp")
            if send_result.get("ok") and send_result.get("status") == "sent":
                out["sent"] = True
                out["provider_message_id"] = send_result.get("provider_message_id")
            else:
                out["error"] = f"send_failed: {send_result.get('error')}"
        else:
            out["error"] = "smtp_not_configured"

    except Exception as exc:
        out["error"] = f"build_failed: {exc}"

    return out


def _ensure_agency_forward_after_dhl(audit_path: Path, audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Auto-forward DHL-received customs documents to the agency (Piotr @ ACS,
    CC Ganther + ACS team + internal) once the docs are recorded.

    Conditions:
      - clearance_path == external_agency_clearance
      - dhl_email.received == true
      - dhl_documents_received.files non-empty
      - agency_forward_after_dhl.sent != true (idempotent)

    AWB PDF is mandatory — refuses to send if missing.
    """
    out: Dict[str, Any] = {"built": False, "sent": False, "error": None}

    cd       = audit.get("clearance_decision") or {}
    is_high  = cd.get("clearance_path") == "external_agency_clearance"
    dhl_recv = bool((audit.get("dhl_email") or {}).get("received"))
    docs     = audit.get("dhl_documents_received") or {}
    files    = docs.get("files") or []
    has_docs_fallback = False
    if not files:
        try:
            from .email_evidence_store import get_summary as _ev_sum
            _awb_fwd = audit.get("awb") or audit.get("tracking_no")
            _ev_summary = _ev_sum(_awb_fwd) if _awb_fwd else {}
            has_docs_fallback = bool((_ev_summary or {}).get("dhl_documents_received"))
        except Exception:
            pass
    has_docs = bool(files) or has_docs_fallback
    already  = bool((audit.get("agency_forward_after_dhl") or {}).get("sent"))

    if not (is_high and dhl_recv and has_docs and not already):
        return out

    # Hard-stop: block retries that slip past the outer `already` flag.
    # Covers two cases:
    #   1. sent=True + provider_message_id → confirmed delivered
    #   2. email_id present → queued (SMTP pending or already processed)
    _existing_fwd = audit.get("agency_forward_after_dhl") or {}
    if _existing_fwd.get("sent") and _existing_fwd.get("provider_message_id"):
        return out
    if _existing_fwd.get("email_id"):
        return out

    try:
        from .agency_forward_after_dhl_builder import build_agency_forward_after_dhl
        from .email_service                    import queue_email
        from .email_sender                     import send_queued_email, _smtp_configured

        pkg = build_agency_forward_after_dhl(audit, audit_path.parent.name)
        if pkg.get("error"):
            out["error"] = pkg["error"]
            out["error_detail"] = pkg.get("error_detail")
            return out

        existing_attach = [a for a in pkg.get("attachments", [])
                           if Path(a.get("path", "")).is_file()]
        if not existing_attach:
            out["error"] = "no_attachments_on_disk"
            return out

        email_id = queue_email(
            to=pkg["to"], subject=pkg["subject"],
            body_html=pkg["body_html"], body_text=pkg["body_text"],
            batch_id=audit_path.parent.name,
            cc=pkg.get("cc", ""),
            from_address=pkg.get("from_address", ""),
            email_type=pkg.get("email_type", "agency_forward_after_dhl"),
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        send_outcome = None
        if _smtp_configured():
            send_outcome = send_queued_email(email_id, method="smtp")

        # Persist forward state (sent only if SMTP success)
        sent_ok = bool(send_outcome and send_outcome.get("ok") and send_outcome.get("status") == "sent")
        audit["agency_forward_after_dhl"] = {
            "from_address":        pkg.get("from_address", ""),
            "to":                  pkg["to"],
            "to_list":             pkg.get("to_list", []),
            "cc":                  pkg.get("cc", ""),
            "cc_list":             pkg.get("cc_list", []),
            "subject":             pkg["subject"],
            "ticket":              pkg.get("ticket", ""),
            "attachments":         existing_attach,
            "attachments_count":   len(existing_attach),
            "email_id":            email_id,
            "status":              "sent" if sent_ok else "queued",
            "sent":                sent_ok,
            "sent_at":             now_iso if sent_ok else None,
            "provider_message_id": (send_outcome or {}).get("provider_message_id"),
            "queued_at":           now_iso,
            "source":              "monitor_auto_after_dhl_documents",
            "send_verified":       sent_ok,
        }
        write_json_atomic(audit_path, audit)

        # ── Mirror into email evidence store ─────────────────────────────────
        _awb_fwd = str(audit.get("awb") or audit.get("tracking_no") or "")
        _batch_id_fwd = audit_path.parent.name
        if _awb_fwd:
            try:
                from .email_evidence_store import link_batch as _evs_link, save_message as _evs_save
                _evs_link(_awb_fwd, _batch_id_fwd)
                _evs_save(_awb_fwd, {
                    "message_id":      f"op_agency_forward:{_batch_id_fwd}",
                    "thread_id":       f"op_agency_forward:{_batch_id_fwd}",
                    "direction":       "outgoing",
                    "sender":          pkg.get("from_address", "import@estrellajewels.eu"),
                    "to":              pkg.get("to_list") or ([pkg["to"]] if pkg.get("to") else []),
                    "cc":              pkg.get("cc_list") or ([pkg["cc"]] if pkg.get("cc") else []),
                    "subject":         pkg["subject"],
                    "body_text":       f"Agency forward sent for batch {_batch_id_fwd}.",
                    "timestamp":       now_iso,
                    "event_type":      "agency_forward",
                    "delivery_status": "sent" if sent_ok else "queued",
                    "matched_identifiers": {"awb": True},
                    "attachments":     [{"filename": a.get("name", Path(a.get("path","")).name),
                                         "document_type": "other", "size": None, "sha256": None}
                                        for a in existing_attach],
                    "source":          "monitor_auto",
                }, source="monitor_auto")
            except Exception as _evs_exc:
                log.warning("[agency_forward] evidence store write failed (non-fatal): %s", _evs_exc)

        out["built"]    = True
        out["email_id"] = email_id
        out["sent"]     = sent_ok
        if sent_ok:
            out["provider_message_id"] = send_outcome.get("provider_message_id")
            try:
                tl.log_event(audit_path, "agency_forward_after_dhl_sent",
                             "monitor", "active_shipment_monitor",
                             detail={"email_id":            email_id,
                                     "provider_message_id": send_outcome.get("provider_message_id"),
                                     "attachments_count":   len(existing_attach)})
            except Exception:
                pass
        else:
            out["error"] = (send_outcome or {}).get("error", "smtp_not_configured")
            try:
                tl.log_event(audit_path, "agency_forward_after_dhl_queued",
                             "monitor", "active_shipment_monitor",
                             detail={"email_id": email_id,
                                     "reason":   out["error"]})
            except Exception:
                pass

    except Exception as exc:
        out["error"] = f"forward_failed: {exc}"

    return out


def _process_agency_sla(audit_path: Path, audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agency SLA driver.
      Start: agency_forward_after_dhl.sent == True (or sent_at present), no SLA active
      Stop:  agency_documents_received == True OR shipment terminal
    """
    from datetime import datetime
    from .agency_sla_engine import (
        start_agency_sla, stop_agency_sla,
        record_agency_followup_sent, is_agency_followup_due,
    )
    out: Dict[str, Any] = {"started": False, "stopped": False}

    # ── Mark agency_sla.started immediately when forward was sent ──────────
    # This is a lightweight flag separate from the agency_sla_engine's audit["sla"]
    # key, written idempotently so the dashboard can detect SLA start without
    # waiting for the engine's first followup sweep.
    _fwd_check = audit.get("agency_forward_after_dhl") or {}
    if bool(_fwd_check.get("sent")) and not (audit.get("agency_sla") or {}).get("started"):
        audit["agency_sla"] = {
            "started":    True,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(audit_path, audit)
        out["started"] = True

    # ── Stop agency_sla when SAD is received ──────────────────────────────────
    _asla = audit.get("agency_sla") or {}
    if _asla.get("started") and not _asla.get("stopped"):
        _awb_sla = str(audit.get("awb") or audit.get("tracking_no") or "")
        _sad_received = False
        if _awb_sla:
            try:
                from .email_evidence_store import get_summary as _ev_sum
                _sad_received = bool((_ev_sum(_awb_sla) or {}).get("agency_sad_received"))
            except Exception:
                pass
        if _sad_received:
            audit["agency_sla"]["stopped"] = True
            audit["agency_sla"]["stopped_at"] = datetime.now(timezone.utc).isoformat()
            write_json_atomic(audit_path, audit)
            return {"started": False, "stopped": True}

    fwd = audit.get("agency_forward_after_dhl") or {}
    forward_sent = bool(fwd.get("sent")) or bool(fwd.get("sent_at"))
    sla = audit.get("sla") or {}

    # Stop conditions
    if sla.get("active"):
        if audit.get("agency_documents_received"):
            stop_agency_sla(audit, "agency_documents_received")
            write_json_atomic(audit_path, audit)
            try:
                tl.log_event(audit_path, "agency_sla_stopped", "monitor",
                             "active_shipment_monitor",
                             detail={"reason": "agency_documents_received"})
            except Exception:
                pass
            out["stopped"] = True
            return out
        cs = audit.get("clearance_status", "")
        tr = (audit.get("tracking") or {}).get("status", "")
        if cs == "delivered" or tr == "delivered":
            stop_agency_sla(audit, "shipment_terminal")
            write_json_atomic(audit_path, audit)
            out["stopped"] = True
            return out

    # Start condition — only when agency forward was sent and SLA not yet active
    if forward_sent and not sla.get("active"):
        sent_at_raw = fwd.get("sent_at") or datetime.now(timezone.utc).isoformat()
        try:
            sent_at = datetime.fromisoformat(str(sent_at_raw).replace("Z", "+00:00"))
        except Exception:
            sent_at = datetime.now(timezone.utc)
        start_agency_sla(audit, sent_at)
        write_json_atomic(audit_path, audit)
        try:
            tl.log_event(audit_path, "agency_sla_started", "monitor",
                         "active_shipment_monitor",
                         detail={"first_followup_at": audit["sla"]["first_followup_at"]})
        except Exception:
            pass
        out["started"] = True

    return out


def _process_dhl_followup(
    audit_path:      Path,
    audit:           Dict[str, Any],
    customs_trigger: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    DHL follow-up SLA driver.

    1. If customs trigger fired and no DHL email yet and no SLA active → start
       SLA with first_followup_at = trigger + 4h (clamped to working window).
    2. If DHL email arrived after SLA started → stop with reason
       'dhl_email_received'.
    3. If SLA active and now >= next_followup_at → build follow-up email,
       queue + auto-send via SMTP, increment counter, advance next_followup_at.
    4. Idempotent — never sends twice for the same scheduled slot.
    """
    from .dhl_followup_sla import (
        start_followup, stop_followup, record_followup_sent, is_due,
        STOP_DHL_EMAIL_RECEIVED, STOP_TERMINAL, _now_poland,
    )
    out: Dict[str, Any] = {
        "started":     False,
        "sent":        False,
        "stopped":     False,
        "error":       None,
        "state_after": None,
    }

    state = audit.get("dhl_followup") or {}
    dhl_received = bool((audit.get("dhl_email") or {}).get("received"))

    # ── Email Evidence V2 — local store overrides stale audit ────────────────
    # If local evidence already shows a DHL response (request, documents, or
    # invoice), skip the followup. Cheap, deterministic, file-grounded.
    if not dhl_received:
        try:
            from .email_evidence_store import get_summary as _ev_get_summary
            _awb = str(audit.get("awb") or audit.get("tracking_no") or "")
            if _awb:
                _summary = _ev_get_summary(_awb)
                if _summary.get("dhl_request_received") or _summary.get("dhl_documents_received") \
                   or _summary.get("dhl_invoice_received"):
                    dhl_received = True
        except Exception:
            pass

    # ── Stop conditions ──────────────────────────────────────────────────────
    if state.get("active"):
        if dhl_received:
            stop_followup(audit, STOP_DHL_EMAIL_RECEIVED)
            write_json_atomic(audit_path, audit)
            try:
                tl.log_event(audit_path, "dhl_followup_stopped", "monitor",
                             "active_shipment_monitor",
                             detail={"reason": STOP_DHL_EMAIL_RECEIVED})
            except Exception:
                pass
            out["stopped"]     = True
            out["state_after"] = audit["dhl_followup"]
            return out
        # Terminal status check
        cs = audit.get("clearance_status", "")
        tr = (audit.get("tracking") or {}).get("status", "")
        if cs in ("agency_email_sent", "delivered") or tr in ("delivered", "returned", "cancelled"):
            stop_followup(audit, STOP_TERMINAL)
            write_json_atomic(audit_path, audit)
            try:
                tl.log_event(audit_path, "dhl_followup_stopped", "monitor",
                             "active_shipment_monitor",
                             detail={"reason": STOP_TERMINAL})
            except Exception:
                pass
            out["stopped"]     = True
            out["state_after"] = audit["dhl_followup"]
            return out

    # ── Start conditions ─────────────────────────────────────────────────────
    if not state.get("active") and not dhl_received and customs_trigger:
        # parse trigger time, fall back to now if missing
        trig_time_raw = customs_trigger.get("event_time") or _now_poland().isoformat()
        try:
            trig_time = datetime.fromisoformat(str(trig_time_raw).replace("Z", "+00:00"))
        except Exception:
            trig_time = datetime.now(timezone.utc)
        new_state = start_followup(audit, trig_time, customs_trigger.get("reason", "customs_trigger"))
        write_json_atomic(audit_path, audit)
        try:
            tl.log_event(audit_path, "dhl_followup_started", "monitor",
                         "active_shipment_monitor",
                         detail={"trigger_reason":  new_state["trigger_reason"],
                                 "first_followup_at": new_state["first_followup_at"]})
        except Exception:
            pass
        out["started"]     = True
        out["state_after"] = new_state
        # Re-read state for the due-check below
        state = new_state

    # ── Send when due ────────────────────────────────────────────────────────
    if state.get("active") and is_due(state):
        try:
            from .dhl_followup_email_builder import build_dhl_followup_email
            from .email_service               import queue_email
            from .email_sender                import send_queued_email, _smtp_configured

            pkg = build_dhl_followup_email(audit, audit_path.parent.name)
            existing = [a for a in pkg.get("attachments", [])
                        if Path(a.get("path", "")).is_file()]
            email_id = queue_email(
                to=pkg["to"], subject=pkg["subject"],
                body_html=pkg["body_html"], body_text=pkg["body_text"],
                batch_id=audit_path.parent.name,
                cc=pkg.get("cc", ""),
                from_address=pkg.get("from_address", ""),
                email_type=pkg.get("email_type", "dhl_followup"),
            )
            send_method  = "smtp"
            send_outcome = None
            if _smtp_configured():
                send_outcome = send_queued_email(email_id, method="smtp")
            else:
                # Risk flag — we couldn't send the follow-up
                flags = audit.get("risk_flags") or []
                if "dhl_followup_send_failed" not in flags:
                    flags.append("dhl_followup_send_failed")
                    audit["risk_flags"] = flags

            if send_outcome and send_outcome.get("ok") and send_outcome.get("status") == "sent":
                # Advance SLA state
                record_followup_sent(audit)
                write_json_atomic(audit_path, audit)
                try:
                    tl.log_event(audit_path, "dhl_followup_sent", "monitor",
                                 "active_shipment_monitor",
                                 detail={"email_id":            email_id,
                                         "provider_message_id": send_outcome.get("provider_message_id"),
                                         "followup_count":      audit["dhl_followup"]["followup_count"],
                                         "next_followup_at":    audit["dhl_followup"]["next_followup_at"]})
                except Exception:
                    pass
                out["sent"]                = True
                out["email_id"]            = email_id
                out["provider_message_id"] = send_outcome.get("provider_message_id")
                out["state_after"]         = audit["dhl_followup"]
            else:
                out["error"] = (send_outcome or {}).get("error", "smtp_not_configured")
                # Don't advance next_followup_at — operator/SMTP fix needed first
        except Exception as exc:
            out["error"] = f"followup_send_failed: {exc}"

    return out


# ── Public API ───────────────────────────────────────────────────────────────

def scan_active_shipments(force: bool = False) -> Dict[str, Any]:
    """
    Sweep every active batch and return an action summary.

    Args:
        force: when True, includes terminal shipments (for testing/backfill).

    Returns:
        {
          scanned:             int,
          active:              int,
          actions: [
             {batch_id, awb, status, applied_cache?, sla, dispatched_task?, reused_task?, error?}
          ],
          ran_at:              ISO timestamp
        }
    """
    from . import email_intelligence_store as eis
    from . import email_evidence_store as ees
    from .email_intelligence_store import find_existing_email_context
    from .email_search_context     import build_email_search_context
    from .tracking_intelligence    import detect_tracking_triggers
    from .dhl_followup_sla         import (
        start_followup, stop_followup, record_followup_sent, is_due,
        STOP_DHL_EMAIL_RECEIVED, STOP_TERMINAL,
    )
    from . import ai_bridge as ab

    # Propagate settings to sub-modules so monkeypatched storage_root
    # is respected by dependent stores (email intelligence, evidence, search context).
    eis.settings = settings
    ees.settings = settings

    out: Dict[str, Any] = {
        "scanned": 0,
        "active":  0,
        "actions": [],
        "ran_at":  datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 0: autonomous email ingestion (best-effort, never blocks sweep) ─
    try:
        from .email_ingestion_worker import run_ingestion_cycle
        ing = run_ingestion_cycle()
        out["ingestion"] = {
            "ok":             ing.get("ok"),
            "active_batches": ing.get("active_batches"),
            "shipments":      len(ing.get("shipments") or []),
            "events":         sum((s.get("events") or 0)
                                   for s in (ing.get("shipments") or [])),
        }
    except Exception as exc:
        log.warning("[monitor] ingestion cycle failed (non-fatal): %s", exc)
        out["ingestion"] = {"ok": False, "error": str(exc)}

    for audit_path in _all_audit_paths():
        out["scanned"] += 1
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not force and not _is_active(audit):
            continue
        out["active"] += 1

        action: Dict[str, Any] = {
            "batch_id": audit.get("batch_id", audit_path.parent.name),
            "awb":      audit.get("awb") or audit.get("tracking_no") or "",
            "status":   audit.get("clearance_status", ""),
        }

        # 1. Try cache
        cached = find_existing_email_context(audit)
        if cached and cached.get("matched", 0) > 0 and not cached.get("search_unreliable"):
            applied = _apply_cache_to_audit(audit_path, audit, cached)
            action["applied_cache"] = applied
            # Re-read after potential changes
            audit = json.loads(audit_path.read_text(encoding="utf-8"))

        # 2. SLA
        action["sla"] = _evaluate_sla(audit)

        # 3. Tracking triggers (customs activity → email scan now)
        tr_events = (audit.get("tracking") or {}).get("events") or []
        triggers  = detect_tracking_triggers(tr_events, audit) if tr_events else []
        action["triggers"] = triggers

        # 4. Decide whether to dispatch (or reuse) an email_scan task
        #    Conditions:
        #      a) DHL email not yet detected, OR
        #      b) tracking trigger fired (customs activity since last scan)
        dhl_received = bool((audit.get("dhl_email") or {}).get("received"))
        customs_trigger = next(
            (t for t in triggers if t["trigger"] == "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED"),
            None,
        )
        should_dispatch = (not dhl_received) or bool(customs_trigger)

        if should_dispatch:
            awb = action["awb"]
            existing_task = _recent_pending_task_for_awb(awb)
            if existing_task:
                action["reused_task"] = existing_task
            elif awb:
                try:
                    ctx = build_email_search_context(audit)
                    task = ab.create_task(
                        batch_id=action["batch_id"],
                        task_type="email_scan",
                        payload={
                            "awb":             ctx["awb"] or awb,
                            "invoice_numbers": ctx["invoice_numbers"],
                            "dhl_ticket":      ctx["dhl_ticket"],
                            "mrn":             ctx["mrn"],
                            "search_terms":    ctx["search_terms"],
                            "known_senders":   ctx["known_senders"],
                            "known_domains":   ctx["known_domains"],
                            "target_account_id":            ctx["target_account_id"],
                            "target_mailbox":               ctx["target_mailbox"],
                            "related_identities":           ctx["related_identities"],
                            "preferred_mcp_connector_hint": "mcp__620999a3",
                            "trigger_reason": (customs_trigger or {}).get("reason", ""),
                        },
                        note=(
                            f"Monitor — AWB {awb}"
                            + (f" — tracking trigger: {customs_trigger['reason']}"
                               if customs_trigger else "")
                        ),
                    )
                    action["dispatched_task"] = task["task_id"]
                except Exception as exc:
                    action["error"] = f"dispatch_failed: {exc}"

        # 5. Pending-trigger bookkeeping: when a customs trigger fired but no
        #    DHL email is yet on file, set a retry stamp + risk flag if past it.
        if customs_trigger and not dhl_received:
            now = datetime.now(timezone.utc)
            pending = audit.get("pending_triggers") or {}
            existing = pending.get("dhl_email_check") or {}
            should_persist = False
            if not existing:
                pending["dhl_email_check"] = {
                    "active":            True,
                    "reason":            customs_trigger["reason"],
                    "first_seen_at":     now.isoformat(),
                    "next_retry_at":     (now + timedelta(minutes=TRIGGER_RETRY_MINUTES)).isoformat(),
                    "retries":           0,
                    "trigger_event_at":  customs_trigger.get("event_time"),
                }
                should_persist = True
                try:
                    tl.log_event(audit_path, "dhl_email_check_pending", "monitor",
                                 "active_shipment_monitor",
                                 detail={"reason": customs_trigger["reason"],
                                         "event_at": customs_trigger.get("event_time")})
                except Exception:
                    pass
            else:
                # Already pending — check retry window
                try:
                    next_retry = datetime.fromisoformat(
                        str(existing.get("next_retry_at", "")).replace("Z", "+00:00")
                    )
                except Exception:
                    next_retry = now
                if now >= next_retry:
                    existing["retries"]       = int(existing.get("retries", 0)) + 1
                    existing["next_retry_at"] = (now + timedelta(minutes=TRIGGER_RETRY_MINUTES)).isoformat()
                    if existing["retries"] >= 1:
                        # First retry already failed → raise risk flag
                        flags = audit.get("risk_flags") or []
                        flag = "dhl_email_missing_after_tracking_trigger"
                        if flag not in flags:
                            flags.append(flag)
                            audit["risk_flags"] = flags
                            try:
                                tl.log_event(audit_path, "dhl_email_missing_after_trigger",
                                             "monitor", "active_shipment_monitor",
                                             detail={"retries": existing["retries"]})
                            except Exception:
                                pass
                    pending["dhl_email_check"] = existing
                    should_persist = True
            if should_persist:
                audit["pending_triggers"] = pending
                write_json_atomic(audit_path, audit)
                action["pending_trigger"] = pending["dhl_email_check"]

        # 5b. Auto-build + send DHL reply for high-value shipments with email
        try:
            audit_for_reply = json.loads(audit_path.read_text(encoding="utf-8"))
            reply_result = _ensure_dhl_reply(audit_path, audit_for_reply)
            if reply_result["built"] or reply_result.get("error"):
                action["dhl_reply"] = reply_result
        except Exception as exc:
            action["dhl_reply_error"] = str(exc)

        # 5c. DHL follow-up SLA — start on customs trigger, fire when due, stop on resolve
        try:
            audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
            followup_result = _process_dhl_followup(audit_path, audit_now, customs_trigger)
            if followup_result.get("started") or followup_result.get("sent") or followup_result.get("stopped"):
                action["dhl_followup"] = followup_result
        except Exception as exc:
            action["dhl_followup_error"] = str(exc)

        # 5d. Post-DHL → agency forward (after DSK / customs docs received)
        try:
            audit_fwd = json.loads(audit_path.read_text(encoding="utf-8"))
            fwd_result = _ensure_agency_forward_after_dhl(audit_path, audit_fwd)
            if fwd_result.get("built") or fwd_result.get("error"):
                action["agency_forward_after_dhl"] = fwd_result
        except Exception as exc:
            action["agency_forward_after_dhl_error"] = str(exc)

        # 5e. Agency SLA — start 2h after agency forward sent; stop on docs received
        # Guard: skip entirely only when SLA is fully complete (started AND stopped).
        # Calling when started-but-not-stopped is required so the stop path can fire.
        try:
            audit_sla = json.loads(audit_path.read_text(encoding="utf-8"))
            _sla_state = audit_sla.get("agency_sla") or {}
            if not (_sla_state.get("started") and _sla_state.get("stopped")):
                sla_result = _process_agency_sla(audit_path, audit_sla)
                if sla_result.get("started") or sla_result.get("stopped"):
                    action["agency_sla"] = sla_result
        except Exception:
            pass

        # 5f. Agency SAD parse — read-only extraction after SLA stops
        # Never writes to customs_declaration, never triggers PZ.
        try:
            _audit_for_sad = json.loads(audit_path.read_text(encoding="utf-8"))
            if (_audit_for_sad.get("agency_sla") or {}).get("stopped"):
                _sad_parse = _audit_for_sad.get("agency_sad_parse") or {}
                if not _sad_parse or _sad_parse.get("status") != "parsed":
                    from .agency_sad_parser import parse_agency_sad
                    sad_result = parse_agency_sad(
                        action["batch_id"], audit_path, _audit_for_sad
                    )
                    if sad_result.get("parsed") or sad_result.get("awaiting_file"):
                        action["agency_sad_parse"] = sad_result
        except Exception:
            pass

        # 5f2. Agency SAD decision — evaluate parse result against customs_declaration
        # Pure evaluation; never writes financial fields, never triggers PZ.
        try:
            _audit_for_dec = json.loads(audit_path.read_text(encoding="utf-8"))
            if (_audit_for_dec.get("agency_sad_parse") or {}).get("status"):
                if not _audit_for_dec.get("agency_sad_decision"):
                    from .agency_sad_decision import evaluate_agency_sad
                    dec_result = evaluate_agency_sad(
                        action["batch_id"], audit_path, _audit_for_dec
                    )
                    action["agency_sad_decision"] = dec_result
        except Exception:
            pass

        # 5g. Closure check — write completed status when all conditions met
        try:
            from .shipment_closure import apply_closure
            cl = apply_closure(audit_path)
            if cl.get("ready"):
                action["closure"] = cl
        except Exception:
            pass

        # 5h. Action proposal refresh — detect triggers, upsert/resolve proposals.
        #     Best-effort: never blocks the sweep. Re-reads audit so 5b–5f writes
        #     are included before trigger detection runs.
        try:
            from ..api.routes_action_proposals import refresh_proposals as _refresh_proposals
            _audit_for_props = json.loads(audit_path.read_text(encoding="utf-8"))
            prop_result = _refresh_proposals(audit_path, _audit_for_props,
                                             action["batch_id"])
            if prop_result.get("created") or prop_result.get("resolved"):
                action["proposals"] = prop_result
        except Exception as _exc:
            log.debug("[monitor] proposal refresh failed (non-fatal) for %s: %s",
                      action["batch_id"], _exc)

        # 5i. Evidence gap-scan — if the email evidence timeline has gaps that
        #     Zoho Mail can fill (e.g. batch predates evidence store deployment,
        #     or previous scans ran before Zoho search was fixed), trigger a
        #     scan-and-ingest now. Respects a 48-hour recency window so it
        #     never hammers Zoho on every sweep. Best-effort; never blocks.
        _batch_awb = action.get("awb") or ""
        if _batch_awb:
            try:
                from .email_evidence_ingestor import needs_gap_scan, scan_and_ingest
                _audit_for_gap = json.loads(audit_path.read_text(encoding="utf-8"))
                if needs_gap_scan(_batch_awb, _audit_for_gap):
                    log.info("[monitor] evidence gap detected for awb=%s — triggering rescan",
                             _batch_awb)
                    _gap_result = scan_and_ingest(
                        _batch_awb, action["batch_id"], audit_path, _audit_for_gap,
                        limit=100,
                    )
                    if _gap_result.get("ingested", 0) > 0:
                        action["evidence_gap_scan"] = {
                            "ingested": _gap_result["ingested"],
                            "query":    _gap_result.get("query_used", ""),
                        }
                        log.info("[monitor] gap-scan ingested=%d for awb=%s",
                                 _gap_result["ingested"], _batch_awb)
            except Exception as _exc:
                log.debug("[monitor] evidence gap-scan failed (non-fatal) for %s: %s",
                          action["batch_id"], _exc)

        # 6. Trigger satisfied: clear pending state once DHL email confirmed
        # IMPORTANT: re-read from disk so steps 5b/5c writes (dhl_reply_package,
        # dhl_followup state changes) aren't clobbered by a stale local audit.
        if dhl_received and (audit.get("pending_triggers") or {}).get("dhl_email_check"):
            try:
                audit_fresh = json.loads(audit_path.read_text(encoding="utf-8"))
                pt = audit_fresh.setdefault("pending_triggers", {}).setdefault("dhl_email_check", {})
                pt["active"]       = False
                pt["satisfied_at"] = datetime.now(timezone.utc).isoformat()
                if "dhl_email_missing_after_tracking_trigger" in (audit_fresh.get("risk_flags") or []):
                    audit_fresh["risk_flags"].remove("dhl_email_missing_after_tracking_trigger")
                write_json_atomic(audit_path, audit_fresh)
                action["trigger_satisfied"] = True
            except Exception as exc:
                action["trigger_satisfied_error"] = str(exc)

        out["actions"].append(action)

    log.info("[monitor] scanned=%d active=%d actions=%d",
             out["scanned"], out["active"], len(out["actions"]))
    return out

"""
email_evidence_ingestor.py — Shared scan-and-store logic for email evidence.

Used by:
  - email_ingestion_worker.py  (continuous sweep, per-AWB)
  - routes_dashboard.py        (on-demand Rescan button)
  - active_shipment_monitor.py (gap-detection auto-scan)

Public API
----------
scan_and_ingest(awb, batch_id, audit_path, audit, *, limit=50) -> dict
    Scan Zoho Mail for the AWB, store all new messages in the evidence store,
    persist any newly-discovered dhl_ticket to audit.json.

    Returns:
        ok           : bool
        ingested     : int   (new messages added)
        already_stored: int  (duplicates skipped)
        total_scanned: int
        query_used   : str
        scan_method  : str
        error        : str | None

needs_gap_scan(awb, audit, max_age_hours=48) -> bool
    True when the evidence summary has gaps and a fresh scan is warranted.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def needs_gap_scan(awb: str, audit: Dict[str, Any], max_age_hours: float = 48) -> bool:
    """
    Return True when the evidence for this AWB has gaps that a Zoho scan
    might fill AND the evidence hasn't been refreshed too recently.

    Gaps that trigger a scan:
      - dhl_request_received is False but the shipment has progressed past
        the initial filing stage (has clearance_status or a PZ was generated)
      - dhl_documents_received is False but agency_forward exists
        (we forwarded something, so DHL docs were received first)
      - total messages stored == 0

    We also respect a recency window: if a scan ran within the last
    max_age_hours we do not rescan (avoids hammering Zoho on every sweep).
    """
    try:
        from .email_evidence_store import get_by_awb
        ev = get_by_awb(awb)
    except Exception:
        return False

    summary = ev.get("summary") or {}
    msg_count = sum(len(t.get("messages", [])) for t in ev.get("threads", []))

    # No gaps at all — skip
    if (summary.get("dhl_request_received") and
            summary.get("dhl_documents_received")):
        return False

    # Has the shipment progressed past the initial state?
    clearance = audit.get("clearance_status") or ""
    progressed = clearance not in ("", "new", "pending")

    # Additional signals that DHL interaction already happened
    evidence_flags = bool(
        summary.get("agency_forward_queued") or
        summary.get("agency_forward_sent") or
        summary.get("agency_sad_received") or
        summary.get("dhl_documents_received") or
        clearance in ("dsk_generated", "polish_description_generated",
                      "agency_notified", "sad_received", "pz_generated",
                      "completed")
    )

    # Only scan when we have reason to believe DHL interaction happened
    interaction_expected = progressed or evidence_flags
    if not interaction_expected:
        return False

    has_gap = msg_count == 0 or not summary.get("dhl_request_received")
    if not has_gap:
        return False

    # Respect recency window — avoid re-scanning within max_age_hours
    last_scan = ev.get("last_scan_at")
    if last_scan:
        try:
            last_dt = datetime.fromisoformat(last_scan)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if age < max_age_hours:
                return False
        except Exception:
            pass

    return True


def scan_and_ingest(
    awb: str,
    batch_id: str,
    audit_path: Path,
    audit: Dict[str, Any],
    *,
    limit: int = 100,
    token_provider: Optional[Any] = None,
    scan_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Scan Zoho Mail for `awb` and store any new messages in the evidence store.

    Steps:
      1. Obtain a Zoho access token (uses zoho_auth by default).
      2. Call scan_for_dhl_customs_emails with AWB + any known dhl_ticket.
      3. For each matched email, save it to the evidence store (idempotent).
      4. If a new dhl_ticket is discovered, persist it to audit.json.
      5. Update the scan cursor.

    Returns:
        ok, ingested, already_stored, total_scanned, query_used, scan_method,
        error (if any), summary (updated evidence summary)
    """
    awb = re.sub(r"\D", "", str(awb))
    if not awb:
        return {"ok": False, "error": "no_awb", "ingested": 0, "already_stored": 0, "total_scanned": 0}

    # ── 1. Token ──────────────────────────────────────────────────────────────
    if token_provider is None:
        try:
            from .zoho_auth import get_valid_access_token, has_zoho_credentials
            if not has_zoho_credentials():
                return {"ok": False, "error": "no_credentials", "ingested": 0,
                        "already_stored": 0, "total_scanned": 0}
            token_provider = get_valid_access_token
        except Exception as exc:
            return {"ok": False, "error": f"auth_unavailable: {exc}", "ingested": 0,
                    "already_stored": 0, "total_scanned": 0}

    try:
        token = token_provider()
    except Exception as exc:
        return {"ok": False, "error": f"token_error: {exc}", "ingested": 0,
                "already_stored": 0, "total_scanned": 0}

    # ── 2. Scan Zoho ─────────────────────────────────────────────────────────
    if scan_fn is None:
        try:
            # Engine root must be on the path for dhl_email_monitor
            _engine_root = str(Path(audit_path).parent.parent.parent.parent)
            if _engine_root not in sys.path:
                sys.path.insert(0, _engine_root)
            from dhl_email_monitor import scan_for_dhl_customs_emails  # type: ignore
            scan_fn = scan_for_dhl_customs_emails
        except Exception as exc:
            return {"ok": False, "error": f"scan_fn_unavailable: {exc}", "ingested": 0,
                    "already_stored": 0, "total_scanned": 0}

    known_ticket = audit.get("dhl_ticket") or None
    try:
        from ..core.config import settings
        api_base = getattr(settings, "zoho_mail_api_base", "https://mail.zoho.eu/api")
    except Exception:
        api_base = "https://mail.zoho.eu/api"

    try:
        result = scan_fn(
            target_awb=awb,
            limit=limit,
            api_base=api_base,
            token_provider=lambda _t=token: _t,
            dhl_ticket=known_ticket,
        )
    except Exception as exc:
        log.warning("[ingest] scan_for_dhl_customs_emails failed awb=%s: %s", awb, exc)
        return {"ok": False, "error": f"scan_error: {exc}", "ingested": 0,
                "already_stored": 0, "total_scanned": 0}

    emails: List[Dict[str, Any]] = result.get("emails") or []
    total_scanned = result.get("scanned", len(emails))
    query_used    = result.get("query_used", "")
    scan_method   = result.get("scan_method", "")

    # ── Broad-scan fallback: Zoho keyword search can miss when emails are old,
    #    the AWB appears after a colon that wasn't indexed, or the API token
    #    only has inbox scope. If targeted search returned nothing, also run a
    #    broad recent-inbox scan and match locally. The matcher in
    #    scan_for_dhl_customs_emails already filters by AWB, so no false positives.
    if not emails:
        log.info("[ingest] awb=%s — targeted search returned 0, trying broad fallback", awb)
        try:
            fallback = scan_fn(
                target_awb=None,        # broad mode: reads recent folder messages
                limit=min(limit * 2, 200),
                api_base=api_base,
                token_provider=lambda _t=token: _t,
            )
            # Filter fallback results to those that match this AWB
            awb_clean = awb
            matched_fallback = [
                e for e in (fallback.get("emails") or [])
                if awb_clean in re.sub(r"\D", "", e.get("subject", "") +
                                       e.get("body_snippet", "") +
                                       e.get("body_text", ""))
                   or e.get("awb") == awb_clean
            ]
            if matched_fallback:
                emails        = matched_fallback
                total_scanned += fallback.get("scanned", 0)
                query_used    = f"{query_used}+broad_fallback({len(matched_fallback)} matched)"
                scan_method   = "broad_fallback"
                log.info("[ingest] awb=%s — broad fallback matched %d emails",
                         awb, len(matched_fallback))
            else:
                total_scanned += fallback.get("scanned", 0)
        except Exception as _exc:
            log.debug("[ingest] broad fallback failed awb=%s: %s", awb, _exc)

    # ── 3. Store in evidence (idempotent) ────────────────────────────────────
    try:
        from .email_evidence_store import (
            save_message, link_batch, get_by_awb, update_scan_cursor,
        )
        from .email_thread_mapper import (
            normalise_subject as _ns,
            classify_direction as _cd,
            classify_sender_role as _csr,
            classify_event_type as _cet,
        )
    except Exception as exc:
        return {"ok": False, "error": f"store_unavailable: {exc}", "ingested": 0,
                "already_stored": 0, "total_scanned": total_scanned,
                "query_used": query_used, "scan_method": scan_method}

    link_batch(awb, batch_id)
    _existing_ids = {
        m.get("message_id")
        for t in get_by_awb(awb).get("threads", [])
        for m in t.get("messages", [])
        if m.get("message_id")
    }

    ingested = 0
    already_stored = 0
    new_ticket: Optional[str] = None
    ingested_message_ids: List[str] = []
    broad_fallback_used: bool = (scan_method == "broad_fallback")

    for e in emails:
        mid = e.get("message_id") or e.get("messageId") or e.get("id")

        # Track newly discovered ticket
        if not known_ticket and not new_ticket and e.get("dhl_ticket"):
            new_ticket = e["dhl_ticket"]

        if mid and mid in _existing_ids:
            already_stored += 1
            continue

        sender = e.get("from") or e.get("sender") or ""
        subj   = e.get("subject", "")
        body   = e.get("body_text") or e.get("body_snippet") or e.get("body", "") or ""

        direction = _cd(sender)
        role      = _csr(sender)
        ev_type   = _cet(
            direction=direction, sender_role=role,
            subject=subj, body=body, attachments=[],
            to_addresses=e.get("to") or [],
        )

        thread_id = "zoho:" + (_ns(subj) or "msg")[:80]

        try:
            action = save_message(awb, {
                "message_id":          mid,
                "thread_id":           thread_id,
                "direction":           direction,
                "sender":              sender,
                "to":                  e.get("to") or [],
                "cc":                  e.get("cc") or [],
                "subject":             subj,
                "body_text":           body,
                "timestamp":           e.get("received_at") or e.get("date") or "",
                "event_type":          ev_type,
                "matched_identifiers": {"awb": True},
                "attachments":         [],
            }, source="zoho_rest")
            if action.get("action") in ("inserted", "promoted"):
                ingested += 1
                if mid:
                    _existing_ids.add(mid)
                    ingested_message_ids.append(mid)
            else:
                already_stored += 1
        except Exception as exc:
            log.warning("[ingest] save_message failed mid=%s awb=%s: %s", mid, awb, exc)

    # ── 4. Persist newly discovered ticket ───────────────────────────────────
    if new_ticket and not known_ticket:
        try:
            from ..utils.io import write_json_atomic
            _live = json.loads(audit_path.read_text(encoding="utf-8"))
            if not _live.get("dhl_ticket"):
                _live["dhl_ticket"] = new_ticket
                write_json_atomic(audit_path, _live)
                log.info("[ingest] stored dhl_ticket=%s for awb=%s", new_ticket, awb)
        except Exception as exc:
            log.debug("[ingest] could not persist dhl_ticket: %s", exc)

    # ── 5. Update scan cursor ─────────────────────────────────────────────────
    now = _now_iso()
    try:
        update_scan_cursor(awb, now)
    except Exception:
        pass

    summary = get_by_awb(awb).get("summary", {})
    log.info("[ingest] awb=%s ingested=%d already_stored=%d scanned=%d query=%r",
             awb, ingested, already_stored, total_scanned, query_used)

    return {
        "ok":                  True,
        "awb":                 awb,
        "ingested":            ingested,
        "already_stored":      already_stored,
        "total_scanned":       total_scanned,
        "query_used":          query_used,
        "scan_method":         scan_method,
        "broad_fallback_used": broad_fallback_used or scan_method == "broad_fallback",
        "message_ids":         ingested_message_ids,
        "summary":             summary,
    }

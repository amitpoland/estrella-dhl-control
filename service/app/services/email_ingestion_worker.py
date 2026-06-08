"""
email_ingestion_worker.py — Continuous, autonomous mail-ingestion loop.

Runs every monitor sweep (and may be cron-scheduled standalone):
  1. Lists active shipment audits
  2. For each shipment, calls scan_for_dhl_customs_emails(target_awb=AWB)
     plus a single broad-recent scan to catch new senders/threads
  3. For each matched email not yet processed:
        a. Downloads attachments to a temp dir under storage_root
        b. Hands the (email_record, attachment_paths) tuple to
           event_trigger_engine.route_email
  4. Records audit.email_ingestion = {
        last_scan_at, emails_processed,
        attachments_extracted, events_detected,
        processed_message_ids
     }

Idempotent: a message-id already in `processed_message_ids` is skipped.
Network-quiet: when ZOHO creds are missing the worker logs a single warning
and returns ok=False without touching audits.

Public API:
    run_ingestion_cycle(limit_per_shipment: int = 30,
                        broad_limit: int = 50) -> dict
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import settings
from .event_trigger_engine import route_email

log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_active_audits() -> List[Path]:
    root = settings.storage_root / "outputs"
    if not root.is_dir():
        return []
    audits: List[Path] = []
    for d in root.iterdir():
        a = d / "audit.json"
        if not a.exists():
            continue
        try:
            obj = json.loads(a.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("status") in ("completed", "cancelled", "blocked"):
            continue
        audits.append(a)
    return audits


def _awb_for(audit: Dict[str, Any]) -> Optional[str]:
    for k in ("tracking_no", "awb", "tracking_number"):
        v = audit.get(k)
        if v:
            return re.sub(r"\D", "", str(v)) or None
    # Look in nested DHL state
    dhl = audit.get("dhl") or {}
    if isinstance(dhl, dict):
        for k in ("tracking_no", "awb"):
            v = dhl.get(k)
            if v:
                return re.sub(r"\D", "", str(v)) or None
    return None


def _attach_dir(batch_id: str) -> Path:
    p = settings.storage_root / "outputs" / batch_id / "_ingested_attachments"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "attachment.bin"


# ── Zoho attachment download (best-effort) ───────────────────────────────────

def _download_attachment(token: str, account_id: str, message_id: str,
                          attachment_id: str, dest: Path,
                          api_base: str) -> bool:
    """Download a single attachment via Zoho Mail REST. Returns True on success."""
    try:
        import requests
    except ImportError:
        return False
    import re as _re
    if not _re.match(r'^[A-Za-z0-9._\-]+$', str(attachment_id)):
        log.warning("[ingest] attachment_id contains unsafe chars — skipped: %r", attachment_id)
        return False
    url = f"{api_base.rstrip('/')}/accounts/{account_id}/messages/{message_id}/attachments/{attachment_id}"
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200 or not r.content:
            log.debug("[ingest] attachment %s status=%s len=%d",
                      attachment_id, r.status_code, len(r.content or b""))
            return False
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        log.warning("[ingest] download failed att=%s: %s", attachment_id, exc)
        return False


def _download_email_attachments(token: str, account_id: str,
                                 email_record: Dict[str, Any],
                                 batch_id: str, api_base: str) -> List[str]:
    """Return list of locally-saved attachment paths for this email."""
    msg_id = str(email_record.get("message_id") or "")
    if not msg_id:
        return []
    saved: List[str] = []
    out_dir = _attach_dir(batch_id) / _safe_name(msg_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in email_record.get("attachments") or []:
        att_id = a.get("attachmentId") or a.get("id")
        fn     = a.get("filename") or a.get("name") or "attachment.bin"
        if not att_id:
            continue
        dest = out_dir / _safe_name(fn)
        if dest.exists() and dest.stat().st_size > 0:
            saved.append(str(dest))
            continue
        if _download_attachment(token, account_id, msg_id, str(att_id),
                                  dest, api_base):
            saved.append(str(dest))
    return saved


# ── Main entry point ─────────────────────────────────────────────────────────

def run_ingestion_cycle(
    limit_per_shipment: int = 30,
    broad_limit: int = 50,
    scan_fn: Optional[Any] = None,
    token_provider: Optional[Any] = None,
    download_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Run one full ingestion sweep.

    Args (all optional, mostly for tests):
        scan_fn:        injectable scan function (defaults to
                        dhl_email_monitor.scan_for_dhl_customs_emails).
        token_provider: injectable token getter (defaults to
                        zoho_auth.get_valid_access_token).
        download_fn:    injectable attachment downloader (called with
                        (token, account_id, email_record, batch_id, api_base)
                        and must return list[str] of paths). Defaults to
                        the real Zoho REST downloader.
    """
    # Resolve dependencies lazily so tests can stub them.
    if scan_fn is None:
        # Prefer the in-tree scanner. The legacy ``dhl_email_monitor``
        # name is not present in the package; the canonical scanner
        # lives at ``email_evidence_ingestor.scan_and_ingest``. We
        # adapt its signature so the rest of this worker is unchanged.
        try:
            from .email_evidence_ingestor import scan_and_ingest as _evi_scan
            def scan_fn(target_awb=None, limit=50, api_base=None,
                         token_provider=None, dhl_ticket=None,
                         token=None, account_id=None, **_):  # type: ignore
                # Ingestor expects (awb, batch_id, audit_path, audit, *, limit,
                # token_provider, scan_fn). The token is threaded via
                # token_provider (a lambda returning the pre-refreshed token);
                # account_id is read by the underlying scanner from settings.
                # We don't have a batch_id at scan-fn level; the per-shipment
                # caller above already loops batches and calls scan_fn per AWB,
                # so an empty batch_id is acceptable for the broad scan path.
                return _evi_scan(
                    target_awb or "", "", None, {},
                    limit=limit,
                    token_provider=token_provider,
                )
        except Exception as exc:
            log.warning("[ingest] in-tree scanner unavailable: %s", exc)
            return {"ok": False, "error": "scan_fn_unavailable"}

    if token_provider is None:
        try:
            from .zoho_auth import get_valid_access_token, has_zoho_credentials
            if not has_zoho_credentials():
                log.info("[ingest] no Zoho creds — skipping cycle")
                return {"ok": False, "error": "no_credentials"}
            token_provider = get_valid_access_token
        except Exception as exc:
            log.warning("[ingest] zoho_auth unavailable: %s", exc)
            return {"ok": False, "error": "auth_unavailable"}

    if download_fn is None:
        download_fn = _download_email_attachments

    account_id = getattr(settings, "zoho_mail_account_id", "") or ""
    api_base   = getattr(settings, "zoho_mail_api_base", "https://mail.zoho.eu/api")

    audits = _list_active_audits()
    cycle_started = _now_iso()
    summary: Dict[str, Any] = {
        "ok":             True,
        "started_at":     cycle_started,
        "active_batches": len(audits),
        "shipments":      [],
    }

    if not audits:
        log.info("[ingest] no active shipments — cycle complete")
        return summary

    # One shared token per cycle (refresh handled internally).
    try:
        token = token_provider()
    except Exception as exc:
        log.warning("[ingest] token fetch failed: %s", exc)
        return {"ok": False, "error": f"token_error: {exc}"}

    for audit_path in audits:
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("[ingest] cannot read %s: %s", audit_path, exc)
            continue

        batch_id = str(audit.get("batch_id") or audit_path.parent.name)
        awb      = _awb_for(audit)
        emails_seen = 0
        atts_total  = 0
        events      = 0
        actions:    List[Dict[str, Any]] = []

        # ── Targeted scan (if AWB known) ─────────────────────────────────────
        if awb:
            _known_ticket = audit.get("dhl_ticket") or None
            try:
                res = scan_fn(
                    target_awb=awb,
                    limit=limit_per_shipment,
                    api_base=api_base,
                    token_provider=lambda t=token: t,
                    dhl_ticket=_known_ticket,
                )
            except Exception as exc:
                log.warning("[ingest] scan failed batch=%s awb=%s: %s",
                            batch_id, awb, exc)
                res = {"emails": []}
            # Persist any newly-discovered DHL ticket back to audit
            if not _known_ticket:
                for _e in res.get("emails") or []:
                    _t = _e.get("dhl_ticket")
                    if _t:
                        try:
                            _audit_live = json.loads(audit_path.read_text(encoding="utf-8"))
                            if not _audit_live.get("dhl_ticket"):
                                _audit_live["dhl_ticket"] = _t
                                from ..utils.io import write_json_atomic
                                write_json_atomic(audit_path, _audit_live)
                                log.info("[ingest] stored dhl_ticket=%s for batch=%s", _t, batch_id)
                        except Exception as _exc:
                            log.debug("[ingest] could not persist dhl_ticket: %s", _exc)
                        break
            # ── Email Evidence V2 dual-write (default ON; EMAIL_EVIDENCE_V2=0 disables) ──
            v2_on = bool(getattr(settings, "email_evidence_v2", True))
            if v2_on:
                try:
                    from .email_evidence_store import save_message, save_attachment, get_by_awb, link_batch
                    from .email_thread_mapper import (
                        normalise_subject as _ns, classify_direction as _cd,
                        classify_sender_role as _csr, classify_event_type as _cet,
                    )
                    link_batch(awb, batch_id)
                    _existing_ids = {m.get("message_id") for t in get_by_awb(awb).get("threads", [])
                                     for m in t.get("messages", []) if m.get("message_id")}
                except Exception as _exc:
                    log.warning("[ingest] evidence V2 init failed: %s", _exc)
                    v2_on = False
            for e in res.get("emails") or []:
                emails_seen += 1
                paths = []
                if e.get("attachments"):
                    paths = download_fn(token, account_id, e, batch_id, api_base)
                    atts_total += len(paths)
                # V2: store in evidence (idempotent by message_id)
                if v2_on:
                    try:
                        mid = e.get("message_id") or e.get("messageId") or e.get("id")
                        if mid and mid in _existing_ids:
                            pass   # dup — skip
                        else:
                            sender = e.get("from") or e.get("sender") or ""
                            subj   = e.get("subject", "")
                            body   = e.get("body_text") or e.get("body", "") or ""
                            atts_meta = []
                            for p in paths:
                                try:
                                    from pathlib import Path as _P
                                    pp = _P(p)
                                    if pp.is_file():
                                        m = save_attachment(pp.read_bytes(), pp.name)
                                        atts_meta.append({"filename": pp.name,
                                                          "local_path": m["local_path"],
                                                          "sha256": m["sha256"], "size": m["size"]})
                                except Exception: pass
                            direction = _cd(sender)
                            role      = _csr(sender)
                            ev_type   = _cet(direction=direction, sender_role=role,
                                             subject=subj, body=body, attachments=atts_meta,
                                             to_addresses=e.get("to") or [])
                            save_message(awb, {
                                "message_id":   mid,
                                "thread_id":    "zoho:" + (_ns(subj) or "msg")[:80],
                                "direction":    direction,
                                "sender":       sender,
                                "to":           e.get("to") or [],
                                "cc":           e.get("cc") or [],
                                "subject":      subj,
                                "body_text":    body,
                                "timestamp":    e.get("received_at") or e.get("date") or "",
                                "event_type":   ev_type,
                                "matched_identifiers": {"awb": True},
                                "attachments":  atts_meta,
                            }, source="zoho_rest")
                            if mid: _existing_ids.add(mid)
                    except Exception as _ex:
                        log.warning("[ingest] V2 store write failed: %s", _ex)
                r = route_email(audit_path, e, paths)
                if r.get("ok") and not r.get("skipped"):
                    events += len(r.get("actions") or [])
                    actions.append(r)
            # Update per-AWB scan cursor
            if v2_on:
                try:
                    from .email_evidence_store import update_scan_cursor
                    update_scan_cursor(awb, cycle_started)
                except Exception: pass

        # ── Update audit.email_ingestion timestamp regardless ────────────────
        try:
            audit_now = json.loads(audit_path.read_text(encoding="utf-8"))
            ing = audit_now.get("email_ingestion") or {}
            ing["last_scan_at"] = cycle_started
            audit_now["email_ingestion"] = ing
            from ..utils.io import write_json_atomic
            write_json_atomic(audit_path, audit_now)
        except Exception:
            pass

        summary["shipments"].append({
            "batch_id":     batch_id,
            "awb":          awb,
            "emails_seen":  emails_seen,
            "attachments":  atts_total,
            "events":       events,
        })

    summary["completed_at"] = _now_iso()
    log.info("[ingest] cycle done: batches=%d shipments_with_events=%d",
             len(audits),
             sum(1 for s in summary["shipments"] if s["events"] > 0))
    return summary

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


# ── SAD attachment download helpers ───────────────────────────────────────────

_VALID_SAD_DOC_TYPES = frozenset({"sad", "customs_pdf", "customs_xml", "customs_html"})
_SAD_FILENAME_KEYWORDS = ("zc429", "zc_429", "zc-429", "pzc", "sad")


def _is_valid_agency_sad_attachment(a: Dict[str, Any]) -> bool:
    """True when attachment looks like a SAD/customs document worth downloading."""
    doc_type = (a.get("document_type") or a.get("type") or "").lower()
    if doc_type in _VALID_SAD_DOC_TYPES:
        return True
    fn = (a.get("filename") or a.get("name") or "").lower()
    return any(kw in fn for kw in _SAD_FILENAME_KEYWORDS)


def _safe_sad_name(raw_name: str) -> str:
    """Return filesystem-safe version of an attachment filename."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)[:120] or "attachment.bin"


def _fetch_message_attachment_ids(
    token: str,
    account_id: str,
    message_id: str,
    api_base: str,
) -> List[Dict[str, Any]]:
    """
    Fetch full attachment list for a Zoho message (includes attachmentId).
    Returns [] on any failure — callers must handle the empty case.
    """
    try:
        import requests
        url = f"{api_base.rstrip('/')}/accounts/{account_id}/messages/{message_id}"
        r = requests.get(url,
                         headers={"Authorization": f"Zoho-oauthtoken {token}"},
                         timeout=15)
        if r.status_code != 200:
            log.debug("[ingest] fetch_attachment_ids msg=%s status=%s", message_id, r.status_code)
            return []
        return r.json().get("data", {}).get("attachments") or []
    except Exception as exc:
        log.debug("[ingest] fetch_attachment_ids msg=%s: %s", message_id, exc)
        return []


def _download_one_attachment(
    token: str,
    account_id: str,
    message_id: str,
    att_id: str,
    dest: Path,
    api_base: str,
) -> bool:
    """Download a single Zoho Mail attachment to dest. Returns True on success."""
    try:
        import requests
        url = (f"{api_base.rstrip('/')}/accounts/{account_id}"
               f"/messages/{message_id}/attachments/{att_id}")
        r = requests.get(url,
                         headers={"Authorization": f"Zoho-oauthtoken {token}"},
                         timeout=30)
        if r.status_code != 200 or not r.content:
            log.debug("[ingest] download att=%s status=%s", att_id, r.status_code)
            return False
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        log.warning("[ingest] download_one_attachment att=%s: %s", att_id, exc)
        return False


def _write_agency_receipt_to_audit(
    audit_path: Path,
    batch_id: str,
    file_name: str,
    file_path: Path,
    file_type: str,
) -> None:
    """
    Merge one downloaded SAD attachment into audit.agency_documents_received(_state).
    Source = "email_ingestor". Idempotent: skips if absolute path already recorded.
    """
    try:
        from ..utils.io import write_json_atomic
        live = json.loads(audit_path.read_text(encoding="utf-8"))
        now_iso = datetime.now(timezone.utc).isoformat()

        state: Dict[str, Any] = live.get("agency_documents_received_state") or {}
        existing_files: List[Dict[str, Any]] = list(state.get("files") or [])
        abs_path = str(file_path.resolve())

        if any(f.get("path") == abs_path for f in existing_files):
            return  # already recorded — idempotent

        existing_files.append({"name": file_name, "path": abs_path, "type": file_type})
        received_at = state.get("received_at") or now_iso

        live["agency_documents_received"] = {
            "received":    True,
            "source":      "email_ingestor",
            "files":       [f["name"] for f in existing_files],
            "files_count": len(existing_files),
            "received_at": received_at,
        }
        live["agency_documents_received_state"] = {
            "received":    True,
            "files":       existing_files,
            "source":      "email_ingestor",
            "received_at": received_at,
        }
        write_json_atomic(audit_path, live)
        log.info("[ingest] agency_documents_received updated (email_ingestor): %s in %s",
                 file_name, batch_id)
    except Exception as exc:
        log.warning("[ingest] could not update agency_documents_received: %s", exc)


def _ingest_sad_attachments(
    token: str,
    account_id: str,
    message_id: str,
    attachments: List[Dict[str, Any]],
    audit_path: Path,
    batch_id: str,
    api_base: str,
    *,
    fetch_from_zoho: bool = False,
) -> List[str]:
    """
    Download valid SAD/customs attachments to {batch_dir}/source/sad/.

    - Only downloads attachments that pass _is_valid_agency_sad_attachment.
    - Fetches Zoho attachmentId via a message-detail API call.
    - Skips files already present on disk (idempotent by filename).
    - Updates audit.agency_documents_received_state after each successful download.
    - Non-fatal: exceptions are caught per-file; returns list of downloaded paths.

    fetch_from_zoho=True: skip the client-supplied ``attachments`` list and
    instead discover all attachments directly from the Zoho message-detail API.
    Used by the catch-up path for messages stored before attachment metadata
    was tracked — the scanner list API does not return attachment details.
    """
    sad_dir = audit_path.parent / "source" / "sad"
    try:
        sad_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.warning("[ingest] could not create sad_dir %s: %s", sad_dir, exc)
        return []

    zoho_atts = _fetch_message_attachment_ids(token, account_id, message_id, api_base)
    # Build filename → attachmentId map from Zoho response
    id_map: Dict[str, str] = {}
    for za in zoho_atts:
        fn  = za.get("attachmentName") or za.get("filename") or za.get("name") or ""
        aid = str(za.get("attachmentId") or za.get("id") or "")
        if fn and aid:
            id_map[fn] = aid

    if fetch_from_zoho:
        # Build a synthetic attachment list from the Zoho API response so the
        # filter below can validate by filename/type.
        source_atts = [
            {"filename": fn, "document_type": "other"}
            for fn in id_map
        ]
    else:
        source_atts = attachments

    valid = [a for a in source_atts if _is_valid_agency_sad_attachment(a)]
    if not valid:
        return []

    downloaded: List[str] = []
    for a in valid:
        fn        = a.get("filename") or a.get("name") or "attachment.bin"
        safe_fn   = _safe_sad_name(fn)
        dest      = sad_dir / safe_fn
        file_type = "customs_xml" if fn.lower().endswith(".xml") else "customs_pdf"

        # Idempotency: skip if file already on disk and non-empty
        if dest.exists() and dest.stat().st_size > 0:
            log.debug("[ingest] SAD attachment already on disk: %s", dest)
            _write_agency_receipt_to_audit(audit_path, batch_id, fn, dest, file_type)
            downloaded.append(str(dest))
            continue

        att_id = id_map.get(fn)
        if not att_id:
            log.debug("[ingest] no attachmentId for %r in msg=%s", fn, message_id)
            continue

        if _download_one_attachment(token, account_id, message_id, att_id, dest, api_base):
            _write_agency_receipt_to_audit(audit_path, batch_id, fn, dest, file_type)
            downloaded.append(str(dest))
            log.info("[ingest] SAD attachment downloaded: %s → %s", fn, dest)

    return downloaded


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
    # Required Zoho Mail credentials (service/.env or OS environment):
    #   Refresh-token flow:  ZOHO_CLIENT_ID + ZOHO_CLIENT_SECRET + ZOHO_MAIL_REFRESH_TOKEN
    #   Static-token flow:   ZOHO_MAIL_API_TOKEN   (daily-refresh path)
    # Also set:              ZOHO_MAIL_ACCOUNT_ID = 2261204000000002002
    if token_provider is None:
        try:
            from .zoho_auth import get_valid_access_token, has_zoho_credentials
            if has_zoho_credentials():
                token_provider = get_valid_access_token
            else:
                # Daily token injection path: ZOHO_MAIL_API_TOKEN may be written
                # to the OS environment by an external refresh job even when it is
                # absent from service/.env (which is read only once at startup).
                # Reading os.environ directly here means every scan_and_ingest
                # call sees the freshest value without needing a service restart.
                import os as _os
                _env_token = _os.environ.get("ZOHO_MAIL_API_TOKEN", "").strip()
                if _env_token:
                    token_provider = lambda _t=_env_token: _t
                else:
                    return {"ok": False, "error": "no_credentials", "ingested": 0,
                            "already_stored": 0, "total_scanned": 0}
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
            # Resolve the CLI root where dhl_email_monitor.py lives.
            # Use settings.engine_dir (set via ENGINE_DIR in service/.env) so
            # the path is always correct regardless of where storage_root points.
            # Fallback: four parent-hops from audit_path — only reliable when
            # STORAGE_ROOT sits inside the repo tree, which is NOT the case in
            # production (STORAGE_ROOT = ~/Library/.../estrellajewels/storage).
            try:
                from ..core.config import settings as _cfg
                _engine_root = str(_cfg.engine_dir)
            except Exception:
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
        api_base   = getattr(settings, "zoho_mail_api_base",    "https://mail.zoho.eu/api")
        account_id = getattr(settings, "zoho_mail_account_id",  "") or ""
    except Exception:
        api_base   = "https://mail.zoho.eu/api"
        account_id = ""

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

    log.info("[ingest] awb=%s mode=awb results=%d", awb, len(emails))

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

    # ── Identity-based fallback: when AWB search + broad scan both return 0,
    #    use previously persisted sender addresses from audit.email_identities.
    #    Searches entire:{email} for each known address; results are locally
    #    filtered to keep only emails that contain this AWB in subject/body.
    #    This adds zero API calls if AWB search already found results.
    if not emails:
        _saved_idents = audit.get("email_identities") or {}
        _identity_emails: List[str] = []
        for _bucket in ("dhl", "agency", "internal"):
            _identity_emails.extend(_saved_idents.get(_bucket) or [])

        if _identity_emails:
            log.info(
                "[ingest] awb=%s mode=identity_fallback identities=%d",
                awb, len(_identity_emails),
            )
            for _addr in _identity_emails:
                try:
                    _id_result = scan_fn(
                        target_awb=None,
                        limit=min(limit, 200),
                        api_base=api_base,
                        token_provider=lambda _t=token: _t,
                        identity_emails=[_addr],
                    )
                    _id_candidates = _id_result.get("emails") or []
                    _id_matched = [
                        _e for _e in _id_candidates
                        if awb in re.sub(r"\D", "", _e.get("subject", "") +
                                         _e.get("body_snippet", "") +
                                         _e.get("body_text", ""))
                           or _e.get("awb") == awb
                    ]
                    if _id_matched:
                        emails        = _id_matched
                        total_scanned += _id_result.get("scanned", 0)
                        query_used    = f"identity_fallback:{_addr}"
                        scan_method   = "identity_fallback"
                        log.info(
                            "[ingest] awb=%s identity_fallback addr=%r matched=%d",
                            awb, _addr, len(_id_matched),
                        )
                        break
                    total_scanned += _id_result.get("scanned", 0)
                except Exception as _exc:
                    log.debug("[ingest] identity fallback failed addr=%r: %s", _addr, _exc)

        log.info("[ingest] awb=%s mode=%s results=%d",
                 awb, scan_method if emails else "identity_fallback", len(emails))

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

    # Accumulate identities to persist after the loop
    _new_identities: Dict[str, set] = {"dhl": set(), "agency": set(), "internal": set()}

    for e in emails:
        mid = e.get("message_id") or e.get("messageId") or e.get("id")

        # Track newly discovered ticket
        if not known_ticket and not new_ticket and e.get("dhl_ticket"):
            new_ticket = e["dhl_ticket"]

        # Extract sender now so already-stored emails still populate identity pool.
        sender = e.get("from") or e.get("sender") or ""

        if mid and mid in _existing_ids:
            already_stored += 1
            # Still classify and accumulate identity even if duplicate
            _s = sender.lower().strip()
            if _s:
                _r = _csr(_s)
                if _r == "dhl":
                    _new_identities["dhl"].add(_s)
                elif _r in ("agency", "ganther"):
                    _new_identities["agency"].add(_s)
                elif _r == "internal":
                    _new_identities["internal"].add(_s)
            continue

        subj   = e.get("subject", "")
        body   = e.get("body_text") or e.get("body_snippet") or e.get("body", "") or ""

        # Normalise attachment list from scanner shape {"filename","type"} to
        # evidence-store shape {"filename","document_type"}.  Backward-compatible:
        # if the key is already "document_type" it is preserved as-is.
        raw_attachments = e.get("attachments") or []
        attachments = [
            {
                "filename":      a.get("filename") or a.get("name") or "",
                "document_type": a.get("document_type") or a.get("type") or "other",
                "size":          a.get("size"),
                "sha256":        a.get("sha256"),
            }
            for a in raw_attachments
            if isinstance(a, dict)
        ]

        direction = _cd(sender)
        role      = _csr(sender)
        ev_type   = _cet(
            direction=direction, sender_role=role,
            subject=subj, body=body, attachments=attachments,
            to_addresses=e.get("to") or [],
        )

        thread_id = "zoho:" + (_ns(subj) or "msg")[:80]

        # Collect identity addresses for fallback search persistence
        sender_lower = sender.lower().strip()
        if sender_lower:
            if role == "dhl":
                _new_identities["dhl"].add(sender_lower)
            elif role in ("agency", "ganther"):
                _new_identities["agency"].add(sender_lower)
            elif role == "internal":
                _new_identities["internal"].add(sender_lower)

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
                "attachments":         attachments,
            }, source="zoho_rest")
            if action.get("action") in ("inserted", "promoted"):
                ingested += 1
                if mid:
                    _existing_ids.add(mid)
                    ingested_message_ids.append(mid)
                # ── Download SAD/customs attachments to {batch_dir}/source/sad/ ──
                if attachments and token and account_id:
                    try:
                        _ingest_sad_attachments(
                            token, account_id, str(mid or ""),
                            attachments, audit_path, batch_id, api_base,
                        )
                    except Exception as _dl_exc:
                        log.warning("[ingest] sad attachment download failed mid=%s: %s",
                                    mid, _dl_exc)
            else:
                already_stored += 1
                # ── Catch-up: download SAD attachments for messages that were
                #    stored before the download path was deployed.  Does NOT
                #    re-save the message or touch the evidence store — only
                #    downloads files that are missing from source/sad/.
                #
                # Two triggers:
                #  A) attachment metadata present in the scan result — use it
                #     directly (fast, no extra Zoho API call).
                #  B) no attachment metadata but ev_type signals an agency SAD
                #     email — ask Zoho for the attachment list (fetch_from_zoho).
                #     Covers messages stored before attachment tracking existed.
                _is_agency_sad_ev = ev_type in (
                    "agency_sad_reply", "agency_documents_received",
                )
                if token and account_id and mid and (
                    (attachments and any(
                        _is_valid_agency_sad_attachment(a) for a in attachments))
                    or (_is_agency_sad_ev and not attachments)
                ):
                    try:
                        _ingest_sad_attachments(
                            token, account_id, str(mid),
                            attachments, audit_path, batch_id, api_base,
                            fetch_from_zoho=(_is_agency_sad_ev and not attachments),
                        )
                    except Exception as _dl_exc:
                        log.warning("[ingest] sad catch-up download failed mid=%s: %s",
                                    mid, _dl_exc)
        except Exception as exc:
            log.warning("[ingest] save_message failed mid=%s awb=%s: %s", mid, awb, exc)

    # ── 3b. Persist email identities for future fallback searches ─────────────
    # Merges discovered sender addresses into audit.email_identities so that
    # future scans can use identity-based search as a fallback when AWB search
    # returns 0.  Only writes when new addresses were collected; merge-safe.
    if any(_new_identities[k] for k in _new_identities):
        try:
            from ..utils.io import write_json_atomic
            _live = json.loads(audit_path.read_text(encoding="utf-8"))
            _ident = _live.setdefault("email_identities", {"dhl": [], "agency": [], "internal": []})
            changed = False
            for bucket, addresses in _new_identities.items():
                existing_set = set(_ident.get(bucket) or [])
                new_addrs = addresses - existing_set
                if new_addrs:
                    _ident[bucket] = sorted(existing_set | new_addrs)
                    changed = True
            if changed:
                write_json_atomic(audit_path, _live)
                log.info(
                    "[ingest] persisted email_identities for awb=%s dhl=%d agency=%d internal=%d",
                    awb,
                    len(_ident.get("dhl", [])),
                    len(_ident.get("agency", [])),
                    len(_ident.get("internal", [])),
                )
        except Exception as exc:
            log.debug("[ingest] could not persist email_identities: %s", exc)

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

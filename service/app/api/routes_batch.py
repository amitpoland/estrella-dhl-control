"""
routes_batch.py — Cliq bot batch collection endpoints (production)
==================================================================
All requests carry chat_id + user_id for full per-user isolation.
user_id is optional (defaults to "" → falls back to chat_id-only key)
for single-user bot DMs where isolation is not needed.

Session key = user_id if available, else chat_id.  This ensures /start,
/add, /status, /submit, and /cancel all resolve to the same session
regardless of which chat context the command arrives from.

Endpoints:
    POST /api/v1/batch/start               — begin session (/start <doc_no>)
    POST /api/v1/batch/add                 — register a file
    GET  /api/v1/batch/status/{chat_id}    — session state (/status) [GET compat]
    POST /api/v1/batch/status              — session state (/status) [POST preferred]
    GET  /api/v1/batch/sessions            — all active sessions (dashboard)
    POST /api/v1/batch/submit              — manual trigger (/submit)
    POST /api/v1/batch/cancel              — discard session (/cancel)
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services.batch_manager import BatchSession, FileSlot, manager, _AUTO_SUBMIT_IF_READY
from ..services.batch_service import get_output_dir
from ..services.cliq_bot_service import download_file, find_files_in_chat, scan_chat_files
from ..services import cliq_service, export_service
from ..core.guards import (
    guard_pz_requires_sad, guard_trigger_declared,
    guard_status_transition, _guard_error,
)
from ..core import timeline as tl

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/batch", tags=["batch"])
_auth  = Depends(require_api_key)

_DEPRECATION_MESSAGE = {
    "error":       "Deprecated endpoint — old Cliq BatchManager flow is disabled.",
    "use_instead": "Use the Shipment Batch model via the dashboard or API:",
    "docs": (
        "Create shipment: POST /api/v1/upload/shipment\n"
        "Upload SAD:      POST /api/v1/upload/shipment/{id}/sad\n"
        "Run PZ:          POST /api/v1/upload/shipment/{id}/process\n"
        "Dashboard:       GET  /dashboard/batches\n"
        "Cancel shipment: DELETE /dashboard/batches/{id}"
    ),
    "re_enable":   "Set DEBUG_ALLOW_OLD_BATCH_FLOW=true in .env to re-enable (testing only).",
}


def _require_old_flow_enabled() -> None:
    """Gate: raise 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true."""
    if not settings.debug_allow_old_batch_flow:
        raise HTTPException(status_code=410, detail=_DEPRECATION_MESSAGE)


# ── Request models ────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    chat_id:     str
    user_id:     str = ""   # Zoho sender.get("id")    — primary isolation key
    user_email:  str = ""   # Zoho sender.get("email") — display / audit trail
    doc_no:      str
    tracking_no: str = ""   # AWB number (e.g. "68 7625 8325" → normalized "6876258325")


class StatusRequest(BaseModel):
    chat_id:  str
    user_id:  str = ""


class AddFileRequest(BaseModel):
    chat_id:    str
    user_id:    str = ""
    user_email: str = ""
    type:       Literal["invoice", "sad", "awb"]
    file_id:    str
    file_name:  str


class SubmitRequest(BaseModel):
    chat_id:         str
    user_id:         str = ""
    user_email:      str = ""
    settlement_mode: Literal["standard", "art33a"] = "standard"
    carrier:         str   = ""
    nbp_rate:        Optional[float] = None
    strict_match:    Optional[bool]  = None
    target_type:     Literal["bot", "chat", "user"] = "bot"
    target_id:       str = ""
    trigger_source:  str = "bot"


class CancelRequest(BaseModel):
    chat_id:    str
    user_id:    str = ""
    user_email: str = ""
    args:       str = ""   # command arguments — must equal "confirm" to execute


class ScanChatRequest(BaseModel):
    chat_id:    str
    user_id:    str = ""
    user_email: str = ""


# ── Shared processing entry point ─────────────────────────────────────────────
# Used by both /submit (manual) and auto-submit sweep

async def run_session(
    session:         BatchSession,
    settlement_mode: str          = "standard",
    carrier:         str          = "",
    nbp_rate:        Optional[float] = None,
    strict_match:    Optional[bool]  = None,
    target_id:       str          = "",
    triggered_by:    str          = "manual",   # "manual" | "auto_idle" | "auto_ready"
) -> None:
    """
    Full async processing pipeline.
    Called either from the /submit route background task
    or from the BatchManager auto-submit sweep.
    """
    batch_id = session.batch_id
    doc_no   = session.doc_no
    errors:  List[str] = []

    log.info("[%s] Pipeline start (triggered_by=%s, invoices=%d, sad=%s)",
             batch_id, triggered_by, len(session.invoices),
             session.sad.file_name if session.sad else "NONE")

    # ── Enforcement guards ──────────────────────────────────────────────────
    _audit_path_pre = get_output_dir(batch_id) / "audit.json"
    if _audit_path_pre.exists():
        try:
            import json as _json
            _guard_audit = _json.loads(_audit_path_pre.read_text())
            _sad_advisory = guard_pz_requires_sad(_guard_audit)
            # advisory mode: log and continue; hard mode: raises HTTPException
            if _sad_advisory:
                import logging as _log
                _log.getLogger(__name__).info(
                    "[%s] advisory gate bypass: %s", batch_id, _sad_advisory.get("code")
                )
            guard_status_transition(_guard_audit.get("status", ""), "processing")
        except HTTPException:
            raise
        except Exception:
            pass  # audit not readable — proceed
    guard_trigger_declared(triggered_by)

    # ── 1. Create folders ─────────────────────────────────────────────────────
    try:
        session.create_folders()
    except Exception as exc:
        await _post_failure(f"Folder creation failed: {exc}", doc_no, batch_id, target_id)
        return

    # Timeline: batch created
    output_dir = get_output_dir(batch_id)
    tl.log_event(output_dir / "audit.json", tl.EV_BATCH_CREATED, triggered_by,
                 session.user_email or "bot",
                 detail={"doc_no": doc_no, "invoices": len(session.invoices)})

    # ── 1.5. Resolve empty file_ids via Cliq API (slash-command uploads) ────
    unresolved_names = []
    for slot in session.invoices:
        if not slot.file_id:
            unresolved_names.append(slot.file_name)
    if session.sad and not session.sad.file_id:
        unresolved_names.append(session.sad.file_name)
    if session.awb and not session.awb.file_id:
        unresolved_names.append(session.awb.file_name)

    if unresolved_names:
        log.info("[%s] Resolving %d file(s) by name from chat %s",
                 batch_id, len(unresolved_names), session.chat_id)
        resolved = await find_files_in_chat(session.chat_id, unresolved_names)
        id_map = {m.file_name.lower(): m.file_id for m in resolved}
        for slot in session.invoices:
            if not slot.file_id:
                slot.file_id = id_map.get(slot.file_name.lower(), "")
                log.info("[%s] Invoice %r → file_id=%r", batch_id, slot.file_name, slot.file_id or "UNRESOLVED")
        if session.sad and not session.sad.file_id:
            session.sad.file_id = id_map.get(session.sad.file_name.lower(), "")
            log.info("[%s] SAD %r → file_id=%r", batch_id, session.sad.file_name, session.sad.file_id or "UNRESOLVED")
        if session.awb and not session.awb.file_id:
            session.awb.file_id = id_map.get(session.awb.file_name.lower(), "")

    # ── 1.6. Auto-scan chat for missed invoices (multi-attach Zoho workaround) ─
    # Zoho slash commands sometimes only surface 1 attachment even when the user
    # attached several. Scanning chat messages recovers the rest with real file_ids.
    try:
        scan_zc429, scan_invoices, scan_awbs = await scan_chat_files(session.chat_id)

        # Register any invoice found in chat that isn't already in the session
        existing_names = {s.file_name.lower() for s in session.invoices}
        for inv in scan_invoices:
            if inv.file_name.lower() not in existing_names:
                session.invoices.append(FileSlot(file_id=inv.file_id, file_name=inv.file_name))
                existing_names.add(inv.file_name.lower())
                log.info("[%s] Auto-scan added invoice %r (id=%s)", batch_id, inv.file_name, inv.file_id)

        # Fill in SAD file_id if we found one in chat and session has no file_id yet
        if scan_zc429 and session.sad and not session.sad.file_id:
            if session.sad.file_name.lower() == scan_zc429.file_name.lower():
                session.sad.file_id = scan_zc429.file_id
                log.info("[%s] Auto-scan resolved SAD %r (id=%s)", batch_id, scan_zc429.file_name, scan_zc429.file_id)

        # Fill in AWB file_id if missing
        if scan_awbs and session.awb and not session.awb.file_id:
            for awb in scan_awbs:
                if session.awb.file_name.lower() == awb.file_name.lower():
                    session.awb.file_id = awb.file_id
                    log.info("[%s] Auto-scan resolved AWB %r (id=%s)", batch_id, awb.file_name, awb.file_id)
                    break

        log.info("[%s] Post-scan: %d invoice(s) in session", batch_id, len(session.invoices))
    except Exception as exc:
        log.warning("[%s] Auto-scan failed (non-fatal): %s", batch_id, exc)

    # ── 2. Download files from Cliq ───────────────────────────────────────────
    downloaded_invoices: List[Path] = []
    for slot in session.invoices:
        dest = session.invoice_dir() / _safe_name(slot.file_name)
        ok   = await download_file(slot.file_id, dest)
        if ok:
            downloaded_invoices.append(dest)
        else:
            errors.append(f"Invoice download failed: {slot.file_name}")
            log.error("[%s] Download failed: %s (id=%s)", batch_id, slot.file_name, slot.file_id)

    if not downloaded_invoices:
        await _post_failure(
            "No invoices could be downloaded from Cliq. "
            "Check that the bot token has file access and the files were shared in this chat.",
            doc_no, batch_id, target_id,
        )
        return

    sad_slot = session.sad
    sad_path = session.sad_path(_safe_name(sad_slot.file_name))
    if not await download_file(sad_slot.file_id, sad_path):
        await _post_failure(
            f"SAD/ZC429 download failed: {sad_slot.file_name}",
            doc_no, batch_id, target_id,
        )
        return

    if session.awb:
        awb_dest = session.awb_path(_safe_name(session.awb.file_name))
        if not await download_file(session.awb.file_id, awb_dest):
            errors.append(f"AWB download failed (non-fatal): {session.awb.file_name}")

    # ── 2.5. Copy source files into output folder (for dashboard visibility) ──
    try:
        output_dir = get_output_dir(batch_id)
        src_base   = output_dir / "source"
        for sub in ("invoices", "sad", "awb"):
            (src_base / sub).mkdir(parents=True, exist_ok=True)
        for inv_path in downloaded_invoices:
            shutil.copy2(inv_path, src_base / "invoices" / inv_path.name)
        if sad_path.exists():
            shutil.copy2(sad_path, src_base / "sad" / sad_path.name)
        if session.awb:
            awb_dest = session.awb_path(_safe_name(session.awb.file_name))
            if awb_dest.exists():
                shutil.copy2(awb_dest, src_base / "awb" / awb_dest.name)
        log.info("[%s] Source files copied to output/source/", batch_id)
    except Exception as exc:
        log.warning("[%s] Source file copy failed (non-fatal): %s", batch_id, exc)

    # ── 3. Run engine ─────────────────────────────────────────────────────────
    output_dir = get_output_dir(batch_id)
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: export_service.process_shipment(
                invoice_dir     = session.invoice_dir(),
                zc429_path      = sad_path,
                output_dir      = output_dir,
                doc_no          = doc_no,
                settlement_mode = settlement_mode,
                carrier         = carrier,
                nbp_rate        = nbp_rate,
            ),
        )
    except Exception as exc:
        log.exception("[%s] Engine error", batch_id)
        await _post_failure(f"Engine error: {exc}", doc_no, batch_id, target_id)
        return

    # ── 4. Strict-match gate ──────────────────────────────────────────────────
    v               = result.get("verification", {})
    amendment_flags = v.get("amendment_flags", [])
    effective_strict = strict_match if strict_match is not None else settings.strict_match

    if effective_strict and (
        any(val is False for val in v.values() if not isinstance(val, list))
        or amendment_flags
    ):
        await _post_blocked(v, amendment_flags, doc_no, batch_id, target_id)
        return

    # ── 5. Post results ───────────────────────────────────────────────────────
    corrections_log = result.get("corrections_log", [])
    verify_gaps     = [c for c in corrections_log if c.startswith("[VERIFY-GAP]")]
    corr_report     = result.get("correction_report", {})

    # Timeline: record PZ result
    _result_status = result.get("status", "unknown")
    _ev = tl.EV_PZ_GENERATED if _result_status in ("success", "partial") else tl.EV_PZ_BLOCKED
    tl.log_event(
        output_dir / "audit.json", _ev, triggered_by,
        session.user_email or "bot",
        detail={"status": _result_status, "doc_no": doc_no},
    )

    await _post_success(
        result          = result,
        doc_no          = doc_no,
        batch_id        = batch_id,
        amendment_flags = amendment_flags,
        verify_gaps     = verify_gaps,
        corr_report     = corr_report,
        triggered_by    = triggered_by,
        errors          = errors,
    )
    log.info("[%s] Pipeline done.", batch_id)


# ── /start ────────────────────────────────────────────────────────────────────

@router.post("/start", dependencies=[_auth])
async def start_batch(req: StartRequest) -> dict:
    """
    Begin a new batch session.
    Replaces any existing session for this (chat, user) pair.
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    """
    _require_old_flow_enabled()
    if not req.doc_no.strip():
        raise HTTPException(status_code=422, detail="doc_no is required. Usage: /start PZ 12/3/2026")

    tracking_no = _normalize_tracking(req.tracking_no) if req.tracking_no else ""

    log.info(
        "[/start] chat_id=%r user_id=%r tracking_no=%r doc_no=%r",
        req.chat_id, req.user_id, tracking_no, req.doc_no,
    )

    try:
        session = manager.start_session(
            req.chat_id, req.user_id, req.doc_no.strip(), req.user_email, tracking_no
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log.info(
        "[/start] session_key=%r batch_id=%r active_keys=%s",
        session.session_key, session.batch_id, list(manager._sessions.keys()),
    )

    auto_note = (
        "\n⚡ Auto-submit ON — processing starts automatically once SAD + invoices are received."
        if _AUTO_SUBMIT_IF_READY else
        f"\n⏱ Auto-submits after {int(getattr(settings, 'batch_auto_submit_minutes', 20))} min "
        f"idle once ready. Or send /submit manually."
    )

    return {
        "status":      "ok",
        "batch_id":    session.batch_id,
        "doc_no":      session.doc_no,
        "tracking_no": session.tracking_no,
        "session_key": session.session_key,
        "message": (
            f"📦 Batch started: {session.doc_no}\n"
            f"ID: {session.batch_id}\n"
            + (f"Shipment: {session.tracking_no}\n" if session.tracking_no else "")
            + (f"Operator: {session.user_email}\n" if session.user_email else "")
            + f"\nCommands:\n"
            f"  /invoice  — attach invoice PDF(s)\n"
            f"  /sad      — attach ZC429 / SAD PDF\n"
            f"  /awb      — attach AWB (optional)\n"
            f"  /status   — check progress\n"
            f"  /submit   — process when ready\n"
            f"  /cancel   — discard batch"
            f"{auto_note}"
        ),
    }


# ── /add ─────────────────────────────────────────────────────────────────────

@router.post("/add", dependencies=[_auth])
async def add_file(req: AddFileRequest, background: BackgroundTasks) -> dict:
    """
    Register a file with the active session.
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    """
    _require_old_flow_enabled()
    log.info(
        "[/add] chat_id=%r user_id=%r type=%r file=%r active_keys=%s",
        req.chat_id, req.user_id, req.type, req.file_name,
        list(manager._sessions.keys()),
    )

    session, action = manager.add_file(
        chat_id   = req.chat_id,
        user_id   = req.user_id,
        file_type = req.type,
        file_id   = req.file_id,
        file_name = req.file_name,
    )

    if action == "no_session":
        raise HTTPException(
            status_code = 404,
            detail      = f"No active batch session (key tried: {req.user_id or req.chat_id!r}). Send /start <doc_no> first.",
        )

    if action == "locked":
        raise HTTPException(
            status_code = 409,
            detail      = f"Session status is '{session.status}' — cannot add files now.",
        )

    if action == "duplicate":
        return {
            "status":    "duplicate",
            "type":      req.type,
            "file_name": req.file_name,
            "message":   f"⚠️ Already registered: {req.file_name} — skipped.",
            "is_ready":  session.is_ready,
            "session_key": session.session_key,
        }

    # ── Build confirmation message ─────────────────────────────────────────────
    labels = {
        "invoice": f"📄 Invoice: {req.file_name}  ({len(session.invoices)} total)",
        "sad":     f"📋 SAD / ZC429: {req.file_name}",
        "awb":     f"✈️  AWB: {req.file_name}",
    }
    msg = labels.get(req.type, f"File registered: {req.file_name}")

    if session.is_ready:
        if _AUTO_SUBMIT_IF_READY:
            # Pop immediately and fire — no /submit needed
            popped = manager.pop_session(req.chat_id, req.user_id)
            if popped:
                popped.status = "downloading"
                background.add_task(run_session, popped, triggered_by="auto_ready")
                msg += (
                    f"\n\n✅ Batch ready — auto-submit triggered!\n"
                    f"Invoices: {len(popped.invoices)} | SAD: {popped.sad.file_name}\n"
                    f"⏳ Processing started. Results will appear in #PZ."
                )
                return {
                    "status":    "auto_submitted",
                    "type":      req.type,
                    "file_name": req.file_name,
                    "batch_id":  popped.batch_id,
                    "message":   msg,
                    "is_ready":  True,
                }
        else:
            auto_min = getattr(settings, "batch_auto_submit_minutes", 20)
            msg += f"\n\n✅ Batch ready — send /submit or auto-submits in ~{auto_min} min"
    else:
        msg += "\n⏳ Still needed: " + ", ".join(session.missing_required)

    return {
        "status":      "ok",
        "type":        req.type,
        "file_name":   req.file_name,
        "message":     msg,
        "is_ready":    session.is_ready,
        "missing":     session.missing_required,
        "session_key": session.session_key,
    }


# ── /status ───────────────────────────────────────────────────────────────────

@router.get("/status/{chat_id}", dependencies=[_auth])
async def session_status(
    chat_id: str,
    user_id: str = Query(default=""),
) -> dict:
    """DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true."""
    _require_old_flow_enabled()
    log.info(
        "[/status GET] chat_id=%r user_id=%r active_keys=%s",
        chat_id, user_id, list(manager._sessions.keys()),
    )
    session = manager.get_session(chat_id, user_id)
    if not session:
        return {
            "status":      "no_session",
            "message":     "No active batch. Send /start <doc_no> to begin.",
            "key_tried":   user_id or chat_id,
            "active_keys": list(manager._sessions.keys()),
        }
    session.touch()
    return {**session.summary(), "message": session.status_message()}


@router.post("/status", dependencies=[_auth])
async def session_status_post(req: StatusRequest) -> dict:
    """POST variant of /status. DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true."""
    _require_old_flow_enabled()
    log.info(
        "[/status POST] chat_id=%r user_id=%r active_keys=%s",
        req.chat_id, req.user_id, list(manager._sessions.keys()),
    )
    session = manager.get_session(req.chat_id, req.user_id)
    if not session:
        return {
            "status":      "no_session",
            "message":     "No active batch. Send /start <doc_no> to begin.",
            "key_tried":   req.user_id or req.chat_id,
            "active_keys": list(manager._sessions.keys()),
        }
    session.touch()
    return {**session.summary(), "message": session.status_message()}


# ── /scan-chat ───────────────────────────────────────────────────────────────

@router.post("/scan-chat", dependencies=[_auth])
async def scan_chat(req: ScanChatRequest) -> dict:
    """
    Scan recent chat messages for invoice/SAD/AWB file attachments.
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    """
    _require_old_flow_enabled()
    session = manager.get_session(req.chat_id, req.user_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="No active session. Send /start <doc_no> first.",
        )

    scan_zc429, scan_invoices, scan_awbs = await scan_chat_files(req.chat_id)

    registered:  dict = {"invoices": [], "sad": None, "awb": None}
    already_had: dict = {"invoices": [], "sad": None, "awb": None}

    for inv in scan_invoices:
        _, action = manager.add_file(req.chat_id, req.user_id, "invoice", inv.file_id, inv.file_name)
        if action == "added":
            registered["invoices"].append(inv.file_name)
            log.info("[scan-chat] registered invoice %r", inv.file_name)
        else:
            already_had["invoices"].append(inv.file_name)

    if scan_zc429:
        _, action = manager.add_file(req.chat_id, req.user_id, "sad", scan_zc429.file_id, scan_zc429.file_name)
        if action == "added":
            registered["sad"] = scan_zc429.file_name
        else:
            already_had["sad"] = scan_zc429.file_name

    for awb in scan_awbs:
        _, action = manager.add_file(req.chat_id, req.user_id, "awb", awb.file_id, awb.file_name)
        if action == "added":
            registered["awb"] = awb.file_name
            break
        else:
            already_had["awb"] = awb.file_name

    # Re-fetch session after updates
    session = manager.get_session(req.chat_id, req.user_id)

    new_inv  = len(registered["invoices"])
    had_inv  = len(already_had["invoices"])
    total_inv = new_inv + had_inv

    parts = []
    if new_inv:
        parts.append(f"➕ {new_inv} new invoice(s) registered")
    if registered["sad"]:
        parts.append(f"➕ SAD registered: {registered['sad']}")
    if registered["awb"]:
        parts.append(f"➕ AWB registered: {registered['awb']}")
    if had_inv:
        parts.append(f"✓ {had_inv} invoice(s) already in session")
    if already_had["sad"]:
        parts.append(f"✓ SAD already set")
    if not parts:
        parts.append("No new files found in recent chat messages.")

    summary = "\n".join(parts)
    if session:
        summary += f"\n\n{session.status_message()}"

    return {
        "status":       "ok",
        "registered":   registered,
        "already_had":  already_had,
        "total_invoices_found": total_inv,
        "session":      session.summary() if session else None,
        "message":      f"🔍 Scan complete\n{summary}",
    }


# ── /sessions — dashboard ─────────────────────────────────────────────────────

@router.get("/sessions", dependencies=[_auth])
async def all_sessions() -> dict:
    """
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    Use GET /dashboard/batches instead.
    """
    _require_old_flow_enabled()
    summaries = manager.all_summaries()
    return {
        "count":    len(summaries),
        "sessions": summaries,
    }


# ── /cancel ──────────────────────────────────────────────────────────────────

@router.post("/cancel", dependencies=[_auth])
async def cancel_batch(req: CancelRequest) -> dict:
    """
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    Use DELETE /dashboard/batches/{batch_id} instead.
    """
    _require_old_flow_enabled()
    args_clean = req.args.strip().lower()
    keys_before = list(manager._sessions.keys())
    session_key = req.user_id or req.chat_id

    log.info(
        "[/cancel] chat_id=%r user_id=%r args_raw=%r args_clean=%r session_key=%r active_keys=%s",
        req.chat_id, req.user_id, req.args, args_clean, session_key, keys_before,
    )

    # ── Hard safety gate: no session must ever be deleted without "confirm" ───
    if args_clean != "confirm":
        session = manager.get_session(req.chat_id, req.user_id)
        if not session:
            return {
                "status":        "no_session",
                "cancelled":     False,
                "message":       "No active session to cancel.",
                "args_received": req.args,
                "session_key":   session_key,
                "active_keys_before": keys_before,
                "active_keys_after":  keys_before,
            }
        log.info(
            "[/cancel] args_clean=%r != 'confirm' — returning confirm_required, NOT cancelling",
            args_clean,
        )
        return {
            "status":        "confirm_required",
            "cancelled":     False,
            "message":       "⚠️ To cancel this shipment, type /cancel confirm",
            "args_received": req.args,
            "session_key":   session.session_key,
            "active_keys_before": keys_before,
            "active_keys_after":  keys_before,
        }

    # ── Confirmed: args_clean == "confirm" — delete session ──────────────────
    log.info("[/cancel] confirmed — cancelling session for key=%r", session_key)
    batch_id = manager.cancel_session(req.chat_id, req.user_id)
    keys_after = list(manager._sessions.keys())

    if not batch_id:
        return {
            "status":        "no_session",
            "cancelled":     False,
            "message":       "No active session to cancel.",
            "args_received": req.args,
            "session_key":   session_key,
            "active_keys_before": keys_before,
            "active_keys_after":  keys_after,
        }

    log.info("[/cancel] cancelled batch_id=%r keys_before=%s keys_after=%s",
             batch_id, keys_before, keys_after)
    return {
        "status":        "cancelled",
        "cancelled":     True,
        "batch_id":      batch_id,
        "message":       f"❌ Shipment session cancelled.\nSend /start <doc_no> to begin a new one.",
        "args_received": req.args,
        "session_key":   session_key,
        "active_keys_before": keys_before,
        "active_keys_after":  keys_after,
    }


# ── /submit ───────────────────────────────────────────────────────────────────

@router.post("/submit", dependencies=[_auth])
async def submit_batch(req: SubmitRequest, background: BackgroundTasks) -> dict:
    """
    Manual submit. Validates readiness, pops session, fires background processing.
    DEPRECATED — returns 410 unless DEBUG_ALLOW_OLD_BATCH_FLOW=true.
    """
    _require_old_flow_enabled()
    log.info(
        "[/submit] chat_id=%r user_id=%r active_keys=%s",
        req.chat_id, req.user_id, list(manager._sessions.keys()),
    )
    session = manager.get_session(req.chat_id, req.user_id)
    if not session:
        raise HTTPException(
            status_code = 404,
            detail      = f"No active batch session (key tried: {req.user_id or req.chat_id!r}). Send /start <doc_no> first.",
        )

    validation_errors = session.validate()
    if validation_errors:
        # Return 422 with structured error list for the Deluge handler to show
        raise HTTPException(
            status_code = 422,
            detail      = {
                "message": "Cannot submit — batch is incomplete:",
                "errors":  validation_errors,
            },
        )

    if session.status not in ("collecting", "ready"):
        raise HTTPException(
            status_code = 409,
            detail      = f"Session is already in state '{session.status}'. Check #PZ for results.",
        )

    popped = manager.pop_session(req.chat_id, req.user_id)
    if not popped:
        raise HTTPException(status_code=409, detail="Session was already submitted.")

    popped.status = "downloading"

    # Build a clean confirmation message
    awb_line = f"AWB: ✓ {popped.awb.file_name}" if popped.awb else "AWB: – (not provided)"
    confirm_msg = (
        f"✅ Batch {popped.doc_no} — submitting\n"
        f"ID: {popped.batch_id}\n\n"
        f"Invoices: {len(popped.invoices)} file(s)\n"
        + "\n".join(f"  • {f.file_name}" for f in popped.invoices) + "\n"
        f"SAD: ✓ {popped.sad.file_name}\n"
        f"{awb_line}\n\n"
        f"⏳ Processing started. Results will appear in #PZ."
    )

    background.add_task(
        run_session,
        popped,
        settlement_mode = req.settlement_mode,
        carrier         = req.carrier,
        nbp_rate        = req.nbp_rate,
        strict_match    = req.strict_match,
        target_id       = req.target_id or req.chat_id,
        triggered_by    = "manual",
    )

    return {
        "status":   "accepted",
        "batch_id": popped.batch_id,
        "doc_no":   popped.doc_no,
        "message":  confirm_msg,
    }


# ── Cliq notification helpers ─────────────────────────────────────────────────

async def _post_failure(reason: str, doc_no: str, batch_id: str, target_id: str) -> None:
    msg = (
        f"❌ PZ processing failed\n"
        f"Document: {doc_no or '—'}\n"
        f"Batch: {batch_id}\n"
        f"Reason:\n  {reason}\n"
        f"No files posted."
    )
    log.error("[%s] %s", batch_id, reason)
    try:
        await cliq_service.post_to_channel(msg)
    except Exception as exc:
        log.error("[%s] Could not post failure to #PZ: %s", batch_id, exc)


async def _post_blocked(
    v: dict, amendment_flags: list, doc_no: str, batch_id: str, target_id: str
) -> None:
    failed_keys  = [k for k, val in v.items() if not isinstance(val, list) and val is False]
    check_lines  = "\n".join(f"  ✗ {k}" for k in failed_keys)
    flag_lines   = "\n".join(f"  ⚑ {f}" for f in amendment_flags)
    msg = (
        f"⚠️ PZ BLOCKED — verification mismatch\n"
        f"Document: {doc_no or '—'} | Batch: {batch_id}\n"
        f"Failed checks:\n{check_lines}"
        + (f"\nAmendment flags:\n{flag_lines}" if amendment_flags else "")
        + "\n\nAction required: verify SAD vs invoices.\nNo files posted."
    )
    try:
        await cliq_service.post_to_channel(msg)
    except Exception as exc:
        log.error("[%s] Could not post blocked notice to #PZ: %s", batch_id, exc)


async def _post_success(
    result:          dict,
    doc_no:          str,
    batch_id:        str,
    amendment_flags: list,
    verify_gaps:     list,
    corr_report:     dict,
    triggered_by:    str,
    errors:          List[str],
) -> None:
    trigger_note = {
        "auto_ready": "⚡ Auto-submitted (all files received)",
        "auto_idle":  "⏱ Auto-submitted (idle timeout)",
        "manual":     "",
    }.get(triggered_by, "")

    corrections_list   = corr_report.get("corrections", [])
    corrections_total  = corr_report.get("shown_count", len(corrections_list))
    corrections_crit   = sum(1 for c in corrections_list if c["severity"] == "CRITICAL")
    primary_action_txt = corr_report.get("primary_action_text", "")
    frozen             = corr_report.get("learning_frozen", False)

    msg = cliq_service.build_success_message(
        doc_no               = doc_no,
        lines                = result.get("line_count", 0),
        total_net            = result.get("total_net", 0.0),
        total_gross          = result.get("total_gross", 0.0),
        duty_pln             = result.get("duty_pln", 0.0),
        amendment_flags      = amendment_flags,
        verify_gaps          = verify_gaps,
        audit_score          = result.get("audit_score"),
        audit_risk_level     = result.get("audit_risk_level"),
        batch_id             = batch_id,
        primary_action_text  = primary_action_txt,
        corrections_critical = corrections_crit,
        corrections_total    = corrections_total,
        learning_frozen      = frozen,
    )
    if trigger_note:
        msg = f"{trigger_note}\n\n" + msg

    if errors:
        msg += "\n\n⚠️ Non-fatal errors during download:\n" + "\n".join(f"  - {e}" for e in errors)

    try:
        ok = await cliq_service.post_to_channel(msg)
        if not ok:
            log.error("[%s] post_to_channel returned False — result may not have reached #PZ", batch_id)
    except Exception as exc:
        log.error("[%s] Could not post result to #PZ: %s", batch_id, exc)


# ── Sweep callbacks (registered in main.py) ───────────────────────────────────

async def on_auto_submit(session: BatchSession) -> None:
    """Called by the sweep task when a ready session times out."""
    session.status = "downloading"
    await run_session(session, triggered_by="auto_idle")


async def on_session_expiry(chat_id: str, user_id: str, doc_no: str) -> None:
    """Called by the sweep task when an incomplete session expires."""
    msg = (
        f"⏰ Batch session expired\n"
        f"Document: {doc_no or '—'}\n"
        f"Your batch was incomplete and expired after "
        f"{int(getattr(settings, 'batch_session_timeout_minutes', 30))} minutes.\n"
        f"Send /start {doc_no} to begin again."
    )
    try:
        await cliq_service.post_to_channel(msg)
    except Exception as exc:
        log.error("Expiry notifier failed for chat=%s: %s", chat_id, exc)


# ── Utility ───────────────────────────────────────────────────────────────────

def _safe_name(filename: str) -> str:
    """Sanitise a filename for local storage — strips path traversal, normalises chars."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
    return safe if safe else "file.pdf"


def _normalize_tracking(raw: str) -> str:
    """Strip spaces and non-alphanumeric chars (except hyphen) from a tracking number.
    '68 7625 8325' → '6876258325'
    """
    return re.sub(r"[^a-zA-Z0-9-]", "", raw)

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import cliq_service
from ..services import cliq_bot_service
from ..services.batch_manager import manager as batch_manager
from ..services.export_service import process_shipment

router = APIRouter(prefix="/api/v1/cliq", tags=["cliq-bot"])
_auth  = Depends(require_api_key)
log    = get_logger(__name__)

# ── Bot pipeline timeout ──────────────────────────────────────────────────────
_BOT_PIPELINE_TIMEOUT_S = 300   # 5 minutes max for the full pipeline

# ── In-memory debounce accumulator ───────────────────────────────────────────
# Cliq fires the Message Handler once per attached file.
# After the debounce window the backend fetches ALL files from Cliq API directly.

_pending: Dict[str, dict] = {}
_pending_lock = asyncio.Lock()

# ── Ring buffers (debug visibility) ──────────────────────────────────────────
_RING_SIZE = 20

LAST_BOT_EVENTS:  Deque[dict] = deque(maxlen=_RING_SIZE)
LAST_STAGE_EVENTS: Deque[dict] = deque(maxlen=_RING_SIZE)
LAST_ERRORS:      Deque[dict] = deque(maxlen=_RING_SIZE)
LAST_PZ_POSTS:    Deque[dict] = deque(maxlen=_RING_SIZE)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


async def start_watcher() -> None:
    """Launch the background debounce watcher. Called from app lifespan."""
    asyncio.create_task(_batch_watcher())
    log.info("Bot batch watcher started (debounce=%ds)", settings.bot_debounce_seconds)


async def _batch_watcher() -> None:
    while True:
        await asyncio.sleep(2)
        now   = time.monotonic()
        ready: list[tuple[str, dict]] = []

        async with _pending_lock:
            for chat_id, batch in list(_pending.items()):
                if (now - batch["last_seen"] >= settings.bot_debounce_seconds
                        and not batch.get("processing")):
                    batch["processing"] = True
                    ready.append((chat_id, dict(batch)))
                    del _pending[chat_id]

        for chat_id, batch in ready:
            asyncio.create_task(
                _run_with_timeout(
                    chat_id      = chat_id,
                    message_text = batch["message_text"],
                    window_secs  = settings.bot_debounce_seconds + 20,
                )
            )


async def _run_with_timeout(chat_id: str, message_text: str, window_secs: int) -> None:
    """Wraps the pipeline in a timeout guard — marks failed + posts to #PZ on breach."""
    try:
        await asyncio.wait_for(
            _process_bot_batch(chat_id, message_text, window_secs),
            timeout=_BOT_PIPELINE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.error("Bot pipeline TIMED OUT after %ds for chat %s", _BOT_PIPELINE_TIMEOUT_S, chat_id)
        batch_manager.update_session(
            chat_id, user_id="bot",
            status="failed",
            error_message=f"Pipeline timed out after {_BOT_PIPELINE_TIMEOUT_S}s",
        )
        await cliq_service.post_to_channel(
            f"❌ PZ processing timed out\n"
            f"Chat: {chat_id}\n"
            f"The pipeline exceeded {_BOT_PIPELINE_TIMEOUT_S // 60} min — "
            f"check logs for where it stalled."
        )


# ── Bot event endpoint ────────────────────────────────────────────────────────

class BotEvent(BaseModel):
    attachments:  List[str] = []   # filenames — informational only
    chat_id:      str = ""
    message_text: str = ""


@router.post("/bot-event", dependencies=[_auth])
async def bot_event(event: BotEvent) -> Dict[str, Any]:
    """
    Called by the Zoho Cliq bot Deluge handler on each message/file event.
    Registers the chat_id in the debounce accumulator.
    After the debounce window the backend pulls files from Cliq API directly.
    """
    if not event.chat_id:
        return {"status": "ignored", "reason": "no chat_id"}

    is_new = False
    async with _pending_lock:
        if event.chat_id not in _pending:
            _pending[event.chat_id] = {
                "message_text": event.message_text,
                "last_seen":    time.monotonic(),
                "processing":   False,
            }
            is_new = True
        batch = _pending[event.chat_id]
        batch["last_seen"] = time.monotonic()
        if event.message_text:
            batch["message_text"] = event.message_text

    log.info("Bot event registered for chat %s (new=%s)", event.chat_id, is_new)

    # ── Ring buffer: record every bot event ───────────────────────────────────
    LAST_BOT_EVENTS.append({
        "ts":           _ts(),
        "chat_id":      event.chat_id,
        "attachments":  event.attachments,
        "message_text": event.message_text[:120] if event.message_text else "",
        "is_new":       is_new,
    })

    # ── Cliq BatchManager flow disabled (Fix 4 — stabilization) ──────────────
    # The old flow created ephemeral BatchManager sessions that were invisible to
    # the dashboard and bypassed the Shipment Batch audit/timeline model.
    # Until the Cliq bot is refactored to create proper Shipment Batch records,
    # we reject the upload and direct users to the dashboard.
    if is_new and not settings.debug_allow_old_batch_flow:
        await cliq_service.post_to_channel(
            "⚠️ Cliq file upload is temporarily disabled.\n"
            "Please use the dashboard to create and process shipments:\n"
            f"{settings.fastapi_public_url}/static/dashboard.html\n\n"
            "1. Click + New Shipment\n"
            "2. Upload invoices + AWB\n"
            "3. DHL pre-check runs automatically\n"
            "4. Upload SAD when received\n"
            "5. Click Process Shipment → PZ generated\n\n"
            "Set DEBUG_ALLOW_OLD_BATCH_FLOW=true in .env to re-enable the old Cliq flow."
        )
        return {"status": "disabled", "reason": "old_batch_flow_deprecated"}

    # ── Checkpoint 1: register with dashboard on first event ──────────────────
    if is_new:
        doc_no_hint = cliq_bot_service.parse_doc_no(event.message_text) or "AUTO"
        batch_manager.start_session(
            chat_id    = event.chat_id,
            user_id    = "bot",
            doc_no     = doc_no_hint,
            user_email = "",
        )
        batch_manager.update_session(
            event.chat_id, user_id="bot",
            status = "collecting",
            source = "bot",
        )
        await cliq_service.post_to_channel(
            f"🟡 PZ intake started\n"
            f"Chat: {event.chat_id}\n"
            f"Doc: {doc_no_hint}\n"
            f"Waiting for file upload debounce ({settings.bot_debounce_seconds}s)…"
        )

    return {"status": "accepted"}


# ── Stage helper ──────────────────────────────────────────────────────────────

async def _set_stage(
    chat_id:     str,
    stage:       str,
    channel_msg: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    Update dashboard session + write log line + optionally post to #PZ.
    All pipeline stage transitions go through here.
    """
    batch_manager.update_session(chat_id, user_id="bot", status=stage, **kwargs)
    log.info("PZ bot stage=%-20s chat=%s %s", stage, chat_id,
             {k: v for k, v in kwargs.items() if k != "error_message"} if kwargs else "")

    # Ring buffer: stage event
    ev: dict = {"ts": _ts(), "chat_id": chat_id, "stage": stage}
    if kwargs.get("error_message"):
        ev["error"] = kwargs["error_message"]
    LAST_STAGE_EVENTS.append(ev)
    if stage == "failed":
        LAST_ERRORS.append({**ev, "msg": kwargs.get("error_message", "")})

    if channel_msg:
        log.info("post_to_channel → stage=%s chat=%s preview=%r",
                 stage, chat_id, channel_msg[:80])
        ok = await cliq_service.post_to_channel(channel_msg)
        log.info("post_to_channel ← stage=%s chat=%s delivered=%s",
                 stage, chat_id, ok)
        LAST_PZ_POSTS.append({
            "ts":      _ts(),
            "chat_id": chat_id,
            "stage":   stage,
            "ok":      ok,
            "preview": channel_msg[:120],
        })


# ── Batch processor ───────────────────────────────────────────────────────────

async def _process_bot_batch(
    chat_id:      str,
    message_text: str,
    window_secs:  int = 45,
) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="cliq_bot_"))
    stage   = "resolving_files"   # track current stage for error reporting

    try:
        # ── Checkpoint 2: debounce done → resolving files ─────────────────────
        stage = "resolving_files"
        await _set_stage(
            chat_id, stage,
            f"🟠 Resolving files from Cliq…\n"
            f"Chat: {chat_id}",
        )

        file_list = await cliq_service.resolve_files_from_chat(chat_id, window_secs)
        log.info("Cliq API returned %d file(s): %s",
                 len(file_list), [f["file_name"] for f in file_list])

        if not file_list:
            await _set_stage(
                chat_id, "failed",
                f"❌ PZ processing failed\n"
                f"Stage: {stage}\n"
                f"Reason: Cliq API returned 0 files in the last {window_secs}s window.\n"
                f"Please re-upload your files and try again.",
                error_message="Cliq API returned 0 files",
                files_found=0,
            )
            return

        # ── Checkpoint 3: files resolved → list them ─────────────────────────
        stage = "downloading"
        file_names = "\n".join(f"  • {f['file_name']}" for f in file_list)
        await _set_stage(
            chat_id, stage,
            f"📂 Files found: {len(file_list)}\n{file_names}\nDownloading…",
            files_found=len(file_list),
        )

        # ── Download each file ────────────────────────────────────────────────
        metas: List[cliq_bot_service.AttachmentMeta] = []
        for f in file_list:
            try:
                content = await cliq_service.download_cliq_file(
                    f["file_id"], f.get("download_url", "")
                )
                dest    = tmp_dir / f["file_name"]
                dest.write_bytes(content)
                metas.append(
                    cliq_bot_service.AttachmentMeta("local", f["file_name"], len(content))
                )
                log.info("Downloaded %r (%d bytes)", f["file_name"], len(content))
            except Exception as exc:
                log.error("Failed to download %r: %s", f["file_name"], exc)

        batch_manager.update_session(chat_id, user_id="bot", files_downloaded=len(metas))

        if not metas:
            await _set_stage(
                chat_id, "failed",
                f"❌ PZ processing failed\n"
                f"Stage: {stage}\n"
                f"Reason: All file downloads failed (OAuth scope or network error).\n"
                f"Check that ZohoCliq.Attachments.READ is in the OAuth token.",
                error_message="All file downloads failed",
            )
            return

        # ── Classify ──────────────────────────────────────────────────────────
        zc429_meta, invoice_metas, awb_metas = cliq_bot_service.classify_files(metas)

        # ── Sync classified inventory → dashboard session ─────────────────────
        # Must happen before any early-return so dashboard shows correct slots
        # even on failure.
        batch_manager.set_file_inventory(
            chat_id  = chat_id,
            user_id  = "bot",
            invoices = [m.file_name for m in invoice_metas],
            sad      = zc429_meta.file_name if zc429_meta else None,
            awb      = awb_metas[0].file_name if awb_metas else None,
        )

        if not zc429_meta:
            file_list_str = "\n".join(f"  • {m.file_name}" for m in metas)
            awb_note = (
                f"\n⚠ AWB/tracking files were correctly excluded (not SAD): "
                + ", ".join(m.file_name for m in awb_metas)
                if awb_metas else ""
            )
            await _set_stage(
                chat_id, "failed",
                "❌ PZ processing failed\n"
                "Stage: classification\n"
                f"Reason: No ZC429/SAD file detected among {len(metas)} file(s).\n"
                f"{file_list_str}"
                f"{awb_note}\n\n"
                "Upload rule:\n"
                "• Name the ZC429/SAD file with 'zc429' or 'sad' (e.g. zc429_ABC.pdf)\n"
                "• Attach all invoice PDFs in the same message\n"
                "• Optional doc number: doc: PZ 12/3/2026",
                error_message="No ZC429/SAD file detected",
            )
            return

        if not invoice_metas:
            await _set_stage(
                chat_id, "failed",
                "❌ PZ processing failed\n"
                "Stage: classification\n"
                f"Reason: Only ZC429 received ({zc429_meta.file_name}) — need at least one invoice PDF.\n\n"
                "Upload rule:\n"
                "• Name the ZC429/SAD file with 'zc429' or 'sad' (e.g. zc429_ABC.pdf)\n"
                "• Attach all invoice PDFs in the same message",
                error_message="Only ZC429 received — no invoice PDFs detected",
            )
            return

        zc429_path  = tmp_dir / zc429_meta.file_name
        invoice_dir = tmp_dir / "invoices"
        invoice_dir.mkdir()
        for inv in invoice_metas:
            (tmp_dir / inv.file_name).rename(invoice_dir / inv.file_name)

        # ── Checkpoint 4: downloads done → engine starting ────────────────────
        stage = "processing"
        doc_no      = cliq_bot_service.parse_doc_no(message_text)

        # Extract tracking / AWB number (source priority: AWB filename → AUTO)
        tracking_no = ""
        if awb_metas:
            tracking_no = cliq_bot_service.extract_tracking_no(awb_metas[0].file_name)

        # Build batch_id:  SHIPMENT_<tracking>_<YYYY-MM>_<8hex>
        _month   = datetime.now(timezone.utc).strftime("%Y-%m")
        _uid     = uuid.uuid4().hex[:8]
        _safe_trk = (
            "".join(c if c.isalnum() else "_" for c in tracking_no)[:30]
            if tracking_no else "AUTO"
        )
        batch_id   = f"SHIPMENT_{_safe_trk}_{_month}_{_uid}"
        output_dir = settings.storage_root / "outputs" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)

        awb_line = f"AWB: {awb_metas[0].file_name}\n" if awb_metas else ""
        trk_line = f"Tracking: {tracking_no}\n" if tracking_no else ""
        log.info("Bot batch %s: zc429=%s  invoices=%d  awbs=%d  doc_no=%r  tracking=%r",
                 batch_id, zc429_meta.file_name, len(invoice_metas), len(awb_metas),
                 doc_no, tracking_no)

        await _set_stage(
            chat_id, stage,
            f"⬇️ Files downloaded: {len(metas)}/{len(file_list)}\n"
            f"ZC429: {zc429_meta.file_name}\n"
            f"{awb_line}"
            f"{trk_line}"
            f"Invoices: {len(invoice_metas)}\n"
            f"Running PZ engine…",
        )

        # ── Run engine ────────────────────────────────────────────────────────
        try:
            result = await asyncio.to_thread(
                process_shipment,
                invoice_dir = invoice_dir,
                zc429_path  = zc429_path,
                output_dir  = output_dir,
                doc_no      = doc_no,
            )
        except Exception as exc:
            log.error("Bot batch %s engine error: %s", batch_id, exc)
            await _set_stage(
                chat_id, "failed",
                f"❌ PZ processing failed\n"
                f"Stage: {stage}\n"
                f"Batch ID: {batch_id}\n"
                f"Reason: {exc}",
                error_message=str(exc),
            )
            return

        result["batch_id"] = batch_id

        # ── Checkpoint 5: engine done → posting result ────────────────────────
        stage = "posting"
        await _set_stage(
            chat_id, stage,
            f"✅ Engine completed\nPosting result to #PZ…",
        )

        # ── Build result message ──────────────────────────────────────────────
        v               = result.get("verification", {})
        amendment_flags = v.get("amendment_flags", [])
        failed_keys     = [
            k for k, val in v.items()
            if not isinstance(val, (list, dict)) and val is False
        ]
        corrections = result.get("corrections_log", [])
        verify_gaps = [
            c.removeprefix("[VERIFY-GAP]").strip()
            for c in corrections if c.startswith("[VERIFY-GAP]")
        ]

        base_url      = settings.fastapi_public_url.rstrip("/")
        pdf_url       = f"{base_url}/api/v1/files/{batch_id}/{result['pdf_path'].name}"
        xlsx_url      = f"{base_url}/api/v1/files/{batch_id}/{result['xlsx_path'].name}"

        def _file_url(key: str) -> Optional[str]:
            p = result.get(key)
            return f"{base_url}/api/v1/files/{batch_id}/{p.name}" if p else None

        audit_en_url     = _file_url("audit_en_path")
        audit_pl_url     = _file_url("audit_pl_path")
        audit_pdf_url    = _file_url("audit_pdf_path")
        audit_score      = result.get("audit_score")
        audit_risk_level = result.get("audit_risk_level", "")
        audit_failed     = result.get("audit_failed_checks", [])

        batch_status = "blocked" if (failed_keys or amendment_flags) else "success"

        trk_block = f"Shipment / AWB: {tracking_no}\n" if tracking_no else ""

        if failed_keys or amendment_flags:
            failed_lines = "\n".join(f"- {k} = FALSE" for k in failed_keys)
            flag_lines   = "\n".join(f"- {f}" for f in amendment_flags)
            score_line   = (f"\nRisk Score: {audit_score}/100 ({audit_risk_level})"
                            if audit_score is not None else "")
            text = (
                f"⚠️ PZ BLOCKED — verification mismatch\n"
                f"Document: {doc_no or '—'}\n"
                f"{trk_block}"
                f"Batch ID: {batch_id}"
                + score_line
                + f"\nFailed checks:\n{failed_lines}"
                + (f"\nAmendment flags:\n{flag_lines}" if amendment_flags else "")
                + f"\nAction required: verify SAD vs invoices\n"
                f"Review files:\nPDF: {pdf_url}\nXLSX: {xlsx_url}"
            )
            if audit_en_url:  text += f"\nAudit EN PDF: {audit_en_url}"
            if audit_pl_url:  text += f"\nAudit PL PDF: {audit_pl_url}"
            if audit_pdf_url: text += f"\nAudit Memo PDF: {audit_pdf_url}"
        else:
            text = cliq_service.build_success_message(
                doc_no           = doc_no or "—",
                tracking_no      = tracking_no,
                batch_id         = batch_id,
                lines            = result.get("line_count", 0),
                total_net        = result.get("total_net", 0),
                total_gross      = result.get("total_gross", 0),
                duty_pln         = result.get("duty_pln", 0),
                amendment_flags  = amendment_flags,
                verify_gaps      = verify_gaps,
                pdf_url          = pdf_url,
                xlsx_url         = xlsx_url,
                audit_en_url     = audit_en_url,
                audit_pl_url     = audit_pl_url,
                audit_pdf_url    = audit_pdf_url,
                audit_score      = audit_score,
                audit_risk_level = audit_risk_level,
            )

        if audit_score is not None:
            from escalation import should_escalate, build_escalation_block
            if should_escalate(audit_score, batch_status):
                text += build_escalation_block(
                    score         = audit_score,
                    risk_level    = audit_risk_level,
                    failed_checks = audit_failed,
                    batch_id      = batch_id,
                    doc_no        = doc_no or "",
                    audit_en_url  = audit_en_url,
                    audit_pl_url  = audit_pl_url,
                    audit_pdf_url = audit_pdf_url,
                )

        log.info("post_to_channel → final result stage=posting chat=%s preview=%r",
                 chat_id, text[:80])
        ok = await cliq_service.post_to_channel(text)
        log.info("post_to_channel ← final result delivered=%s", ok)
        LAST_PZ_POSTS.append({
            "ts":      _ts(),
            "chat_id": chat_id,
            "stage":   "posting_final",
            "ok":      ok,
            "preview": text[:120],
        })
        batch_manager.update_session(chat_id, user_id="bot", status="completed")
        log.info("Bot batch %s delivered to Cliq — stage=completed", batch_id)

    except Exception as exc:
        # Catch-all: unexpected error not caught above
        log.error("Bot pipeline unhandled error [stage=%s chat=%s]: %s", stage, chat_id, exc)
        LAST_ERRORS.append({
            "ts":      _ts(),
            "chat_id": chat_id,
            "stage":   stage,
            "error":   str(exc),
            "kind":    "unhandled",
        })
        await _set_stage(
            chat_id, "failed",
            f"❌ PZ processing failed\n"
            f"Stage: {stage}\n"
            f"Chat: {chat_id}\n"
            f"Reason: {exc}",
            error_message=str(exc),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

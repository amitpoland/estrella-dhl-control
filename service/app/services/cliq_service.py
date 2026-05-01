from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── Message builders ──────────────────────────────────────────────────────────

def _fmt_pln(value: float) -> str:
    return f"{value:,.2f} PLN".replace(",", "\u00a0")


def build_success_message(
    doc_no:               str,
    lines:                int,
    total_net:            float,
    total_gross:          float,
    duty_pln:             float,
    amendment_flags:      List[str],
    verify_gaps:          List[str],
    pdf_url:              str = "",
    xlsx_url:             str = "",
    audit_en_url:         Optional[str] = None,
    audit_pl_url:         Optional[str] = None,
    audit_pdf_url:        Optional[str] = None,
    audit_score:          Optional[int] = None,
    audit_risk_level:     Optional[str] = None,
    batch_id:             str = "",
    tracking_no:          str = "",   # AWB / shipment tracking number
    msg_id:               str = "",
    primary_action_text:  str = "",   # from correction_report.primary_action_text
    corrections_critical: int = 0,    # count of CRITICAL corrections
    corrections_total:    int = 0,    # total correction count
    learning_frozen:      bool = False,
) -> str:
    if verify_gaps:
        header = "PZ processed with verification gaps"
        gap_lines = "\n".join(f"- {g}" for g in verify_gaps)
        verify_block = f"Verification gaps:\n{gap_lines}"
    else:
        header = "PZ processed successfully"
        verify_block = "Verification: clean"

    flag_block = "Amendment flags: none" if not amendment_flags else (
        "Amendment flags:\n" + "\n".join(f"- {f}" for f in amendment_flags)
    )

    score_line = (
        f"Risk Score: {audit_score}/100 ({audit_risk_level})\n"
        if audit_score is not None else ""
    )

    links = []
    if pdf_url:       links.append(f"PDF: {pdf_url}")
    if xlsx_url:      links.append(f"XLSX: {xlsx_url}")
    if audit_en_url:  links.append(f"Audit EN PDF: {audit_en_url}")
    if audit_pl_url:  links.append(f"Audit PL PDF: {audit_pl_url}")
    if audit_pdf_url: links.append(f"Audit Memo PDF: {audit_pdf_url}")
    file_block = ("\nFiles:\n" + "\n".join(links)) if links else ""

    trk_line   = f"Shipment / AWB: {tracking_no}\n" if tracking_no else ""
    batch_line = f"Batch ID: {batch_id}\n" if batch_id else ""
    msg_line   = f"\n---\nmsg:{msg_id}" if msg_id else ""

    # Primary action line (concise — operators paste this into emails)
    action_line = ""
    if primary_action_text:
        action_line = f"Primary action:\n{primary_action_text}\n"

    # Corrections count line
    corr_line = ""
    if corrections_total > 0:
        crit_note = f" ({corrections_critical} critical)" if corrections_critical else ""
        corr_line = f"Corrections: {corrections_total}{crit_note}\n"

    freeze_line = "⚠️ Freeze mode active — learning adjustments disabled\n" if learning_frozen else ""

    return (
        f"{header}\n"
        f"Document: {doc_no or '—'}\n"
        f"{trk_line}"
        f"{batch_line}"
        f"{score_line}"
        f"Lines: {lines}\n"
        f"Netto: {_fmt_pln(total_net)}\n"
        f"Brutto: {_fmt_pln(total_gross)}\n"
        f"Duty A00: {_fmt_pln(duty_pln)}\n"
        f"{verify_block}\n"
        f"{flag_block}\n"
        f"{action_line}"
        f"{corr_line}"
        f"{freeze_line}"
        f"{file_block}"
        f"{msg_line}"
    )


def build_failure_message(doc_no: str, errors: List[str]) -> str:
    reason_lines = "\n".join(f"- {e}" for e in errors)
    return (
        f"PZ processing failed\n"
        f"Document: {doc_no or '—'}\n"
        f"Reason:\n{reason_lines}\n"
        f"No final files were posted."
    )


# ── Webhook delivery (bot chat acknowledgment) ────────────────────────────────

def _webhook_url() -> str:
    return settings.cliq_webhook_url


async def post_message(
    text:        str,
    target_type: Literal["bot", "chat", "user"] = "bot",
    target_id:   str = "",
) -> bool:
    """Post via incoming webhook — goes to the bot chat conversation."""
    url = _webhook_url()
    if not url:
        log.warning("CLIQ_WEBHOOK_URL not configured — skipping Cliq message.")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json={"text": text})
            r.raise_for_status()
            log.info("Cliq webhook message posted  status=%d", r.status_code)
            return True
    except Exception as exc:
        log.error("Cliq post_message failed: %s", exc)
        return False


# ── Channel delivery (production results → #PZ) ───────────────────────────────

_CLIQ_BASE = "https://cliq.zoho.in/api/v2"
_PZ_CHANNEL = "pz"

# In-memory token cache (refreshed on 401)
_access_token: str = ""
_token_lock = asyncio.Lock()


async def _get_access_token() -> str:
    """Return current token, refreshing from Zoho if empty or stale."""
    global _access_token
    async with _token_lock:
        if _access_token:
            return _access_token
        # Populate from settings on first call
        _access_token = settings.cliq_bot_token
        return _access_token


async def _refresh_access_token() -> str:
    """Exchange refresh token for a new access token via Zoho OAuth."""
    global _access_token
    refresh_token  = settings.cliq_refresh_token
    client_id      = settings.cliq_client_id
    client_secret  = settings.cliq_client_secret

    if not all([refresh_token, client_id, client_secret]):
        log.warning("OAuth refresh credentials not configured (CLIQ_REFRESH_TOKEN / CLIQ_CLIENT_ID / CLIQ_CLIENT_SECRET)")
        return ""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://accounts.zoho.in/oauth/v2/token",
                params={
                    "refresh_token": refresh_token,
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "grant_type":    "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
            new_token = data.get("access_token", "")
            if new_token:
                async with _token_lock:
                    _access_token = new_token
                log.info("Cliq OAuth token refreshed successfully")
                return new_token
            log.error("Token refresh response missing access_token: %s", data.get("error", "unknown"))
            return ""
    except Exception as exc:
        log.error("Cliq token refresh failed: %s", exc)
        return ""


async def post_to_channel(text: str, channel: str = _PZ_CHANNEL) -> bool:
    """
    Post to #PZ via the Zoho Cliq channel API using OAuth.

    Primary URL: settings.cliq_channel_api_url
      (https://cliq.zoho.in/company/60014108075/api/v2/channelsbyname/pz/message)
    Header: Authorization: Zoho-oauthtoken <access_token>

    Retries once on 401 by refreshing the token.
    Never falls back to the bot webhook — if the channel post fails, returns False.
    """
    url = settings.cliq_channel_api_url or settings.cliq_channel_webhook_url
    if not url:
        log.error("post_to_channel: neither CLIQ_CHANNEL_API_URL nor CLIQ_CHANNEL_WEBHOOK_URL "
                  "is configured — cannot post to #%s", channel)
        return False

    log.info("post_to_channel: target=#%s url=%s preview=%r", channel, url, text[:80])

    for attempt in range(2):
        token = await _get_access_token()
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json={"text": text}, headers=headers)
            log.info("post_to_channel: #%s attempt=%d → HTTP %d body=%r",
                     channel, attempt + 1, r.status_code, r.text[:120])
            if r.status_code == 401 and attempt == 0:
                log.info("post_to_channel: 401 — refreshing OAuth token and retrying")
                await _refresh_access_token()
                continue
            if r.status_code in (200, 201, 204):
                return True
            log.error("post_to_channel: #%s HTTP %d — %s", channel, r.status_code, r.text[:300])
            return False
        except Exception as exc:
            log.error("post_to_channel: #%s failed: %s", channel, exc)
            return False

    log.error("post_to_channel: #%s failed after token refresh", channel)
    return False


async def post_file(
    file_path:   Path,
    target_type: Literal["bot", "chat", "user"] = "bot",
    target_id:   str = "",
) -> bool:
    url = _webhook_url()
    if not url:
        log.warning("CLIQ_WEBHOOK_URL not configured — skipping Cliq file upload.")
        return False

    if not file_path.exists():
        log.error("File not found for Cliq upload: %s", file_path)
        return False

    mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with file_path.open("rb") as fh:
                r = await client.post(
                    url,
                    files={"file": (file_path.name, fh, mime)},
                )
            r.raise_for_status()
            log.info("Cliq webhook file posted %s  status=%d", file_path.name, r.status_code)
            return True
    except Exception as exc:
        log.error("Cliq post_file failed for %s: %s", file_path.name, exc)
        return False


# ── Cliq API: pull files from chat ───────────────────────────────────────────

async def _authed_get(url: str) -> dict:
    """GET with OAuth Bearer token, auto-refreshing on 401."""
    token = await _get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers)
        if r.status_code == 401:
            log.info("Cliq API 401 — refreshing token")
            token = await _refresh_access_token()
            if not token:
                log.error("Token refresh failed — cannot call Cliq API")
                return {}
            headers = {"Authorization": f"Zoho-oauthtoken {token}"}
            r = await client.get(url, headers=headers)
        if r.status_code not in (200, 201, 204):
            log.error("Cliq API GET %s → %d: %s", url, r.status_code, r.text[:300])
            return {}
        try:
            return r.json()
        except Exception:
            return {}


async def resolve_files_from_chat(
    chat_id:        str,
    window_seconds: int = 45,
) -> list[dict]:
    """
    Fetch all file messages posted in a bot chat within the last window_seconds.
    Tries the dedicated files endpoint first, falls back to messages scan.
    Returns list of {file_id, file_name, uploaded_at}.
    """
    cutoff_ms = int(time.time() * 1000) - (window_seconds * 1000)
    files:    list[dict] = []
    seen_ids: set[str]   = set()

    # ── Attempt 1: dedicated files endpoint ──────────────────────────────────
    files_url  = f"{_CLIQ_BASE}/chats/{chat_id}/files?limit=20"
    files_data = await _authed_get(files_url)

    if files_data:
        # Cliq returns the list under "list" key, not "data"
        for item in files_data.get("list", files_data.get("data", [])):
            item_time = int(item.get("time", item.get("created_time", 0)))
            file_id   = item.get("id") or item.get("file_id")
            file_name = item.get("name") or item.get("file_name", "attachment.pdf")
            if file_id and item_time >= cutoff_ms and file_id not in seen_ids:
                seen_ids.add(file_id)
                files.append({"file_id": file_id, "file_name": file_name, "uploaded_at": item_time,
                              "download_url": item.get("download_url") or ""})

    if files:
        log.info("resolve: found %d file(s) via /files endpoint", len(files))
        return files

    # ── Attempt 2: scan messages ──────────────────────────────────────────────
    log.info("resolve: /files returned nothing — scanning messages (chat %s)", chat_id)
    next_token: str | None = None
    pages = 0

    while pages < 10:
        url = f"{_CLIQ_BASE}/chats/{chat_id}/messages?limit=50"
        if next_token:
            url += f"&next={next_token}"

        data = await _authed_get(url)
        if not data:
            log.warning("resolve: empty messages response page %d", pages + 1)
            break

        messages  = data.get("data", [])
        pages    += 1
        log.info("resolve: page %d — %d messages", pages, len(messages))

        for msg in messages:
            msg_time = int(msg.get("time", 0))
            if msg_time < cutoff_ms:
                continue
            if msg.get("type") != "file":
                continue
            content  = msg.get("content", {})
            file_obj = content.get("file", {})
            file_id  = file_obj.get("id")
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            files.append({
                "file_id":      file_id,
                "file_name":    file_obj.get("name", "attachment.pdf"),
                "uploaded_at":  msg_time,
                "download_url": file_obj.get("download_url") or file_obj.get("url") or "",
            })
            log.info("resolve: found file %r id=%s", file_obj.get("name"), file_id)

        next_token = data.get("next_token")
        if not next_token:
            break

    return files


def _extract_zapikey() -> str:
    """Pull zapikey from the configured webhook URL."""
    wh = settings.cliq_webhook_url or ""
    if "zapikey=" in wh:
        return wh.split("zapikey=")[-1].split("&")[0]
    return ""


async def download_cliq_file(file_id: str, download_url: str = "") -> bytes:
    """
    Download a Cliq file by ID using OAuth Bearer token (ZohoCliq.Attachments.READ scope).
    If the message content includes a direct download URL, that is tried first.
    """
    url = f"{_CLIQ_BASE}/files/{file_id}"

    # ── Attempt 1: direct download URL from message content ───────────────────
    if download_url:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(download_url)
            if r.status_code == 200:
                log.info("File %s downloaded via direct URL (%d bytes)", file_id, len(r.content))
                return r.content
            log.warning("Direct URL download → %d, trying OAuth", r.status_code)

    # ── Attempt 2: OAuth Bearer token (ZohoCliq.Attachments.READ) ────────────
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        r = await client.get(url, headers=headers)
        if r.status_code == 401:
            token = await _refresh_access_token()
            if not token:
                raise RuntimeError("Cannot refresh Cliq OAuth token for file download")
            headers = {"Authorization": f"Zoho-oauthtoken {token}"}
            r = await client.get(url, headers=headers)
        r.raise_for_status()
        log.info("File %s downloaded via OAuth (%d bytes)", file_id, len(r.content))
        return r.content


async def deliver_batch_result(
    result:      Dict[str, Any],
    doc_no:      str,
    target_type: Literal["bot", "chat", "user"],
    target_id:   str,
    errors:      Optional[List[str]] = None,
) -> bool:
    """
    Post summary text + PDF + XLSX via webhook.
    target_type / target_id are accepted for API compatibility but unused in webhook mode.
    Returns True only if all three posts succeeded.
    """
    v               = result.get("verification", {})
    amendment_flags = v.get("amendment_flags", [])
    corrections     = result.get("corrections_log", [])
    verify_gaps     = [
        c.removeprefix("[VERIFY-GAP]").strip()
        for c in corrections if c.startswith("[VERIFY-GAP]")
    ]

    if errors:
        text = build_failure_message(doc_no, errors)
        return await post_to_channel(text)

    # Prefer WorkDrive share links; fall back to local service URLs
    pdf_path  = result.get("pdf_path")
    xlsx_path = result.get("xlsx_path")
    batch_id  = result.get("batch_id", "")
    pdf_url   = result.get("pdf_share_url") or (
        f"/api/v1/files/{batch_id}/{pdf_path.name}" if pdf_path else ""
    )
    xlsx_url  = result.get("xlsx_share_url") or (
        f"/api/v1/files/{batch_id}/{xlsx_path.name}" if xlsx_path else ""
    )

    text = build_success_message(
        doc_no          = doc_no,
        lines           = result.get("line_count", 0),
        total_net       = result.get("total_net", 0),
        total_gross     = result.get("total_gross", 0),
        duty_pln        = result.get("duty_pln", 0),
        amendment_flags = amendment_flags,
        verify_gaps     = verify_gaps,
        pdf_url         = pdf_url,
        xlsx_url        = xlsx_url,
    )

    return await post_to_channel(text)

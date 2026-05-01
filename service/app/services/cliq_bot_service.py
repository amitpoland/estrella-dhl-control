from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

_CLIQ_BASE = settings.cliq_base_url.rstrip("/")


# ── Token manager — auto-refresh on 401 ──────────────────────────────────────

class _TokenManager:
    """
    Thread-safe holder for the Cliq OAuth access token.

    On 401: calls accounts.zoho.in to get a new token from CLIQ_REFRESH_TOKEN,
    updates settings.cliq_bot_token in memory, and writes the new value back
    to service/.env so the token survives service restarts.
    Only one coroutine refreshes at a time (asyncio.Lock); others wait for it.
    """

    def __init__(self) -> None:
        self._token: str       = settings.cliq_bot_token
        self._lock:  asyncio.Lock = asyncio.Lock()

    def current(self) -> str:
        return self._token

    async def refresh(self) -> str:
        async with self._lock:
            log.info("TokenManager: refreshing Cliq access token …")
            refresh_token  = settings.cliq_refresh_token
            client_id      = settings.cliq_client_id
            client_secret  = settings.cliq_client_secret
            accounts_base  = settings.cliq_base_url.replace("cliq.", "accounts.").split("/api/")[0]
            token_url      = f"{accounts_base}/oauth/v2/token"

            if not all([refresh_token, client_id, client_secret]):
                log.error("TokenManager: CLIQ_REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET not set — cannot refresh")
                return self._token

            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.post(
                        token_url,
                        data={
                            "grant_type":    "refresh_token",
                            "refresh_token": refresh_token,
                            "client_id":     client_id,
                            "client_secret": client_secret,
                        },
                    )
                    r.raise_for_status()
                    new_token = r.json().get("access_token", "")
            except Exception as exc:
                log.error("TokenManager: refresh failed: %s", exc)
                return self._token

            if not new_token:
                log.error("TokenManager: refresh returned no access_token")
                return self._token

            self._token = new_token
            settings.cliq_bot_token = new_token   # update in-memory config

            log.info("TokenManager: token refreshed (in-memory only)")
            return self._token


_token_mgr = _TokenManager()

# ── Classification keyword sets ───────────────────────────────────────────────
# Priority order: ZC429/SAD → AWB/tracking → invoice → unknown
# A file matching AWB keywords must NEVER be used as ZC429 fallback.

_ZC429_KEYWORDS   = ("zc429", "zc-429", "sad", "zgłoszenie", "zgloszenie", "zgłosz")
_AWB_KEYWORDS     = ("tracking", "awb", "waybill", "airway", "courier", "shipment_track")
_INVOICE_KEYWORDS = ("invoice", "faktura", "inv-", "inv_", "ejl/")


# ── File classification ────────────────────────────────────────────────────────

class AttachmentMeta:
    def __init__(self, file_id: str, file_name: str, file_size: int = 0):
        self.file_id   = file_id
        self.file_name = file_name
        self.file_size = file_size


def _file_category(name: str) -> str:
    """
    Classify a filename into: 'zc429' | 'awb' | 'invoice' | 'unknown'.

    Priority:
      1. ZC429/SAD keywords   → 'zc429'
      2. AWB/tracking keywords → 'awb'    (never fallback to zc429)
      3. Invoice keywords      → 'invoice'
      4. Anything else         → 'unknown'
    """
    nl = name.lower()
    if any(k in nl for k in _ZC429_KEYWORDS):
        return "zc429"
    if any(k in nl for k in _AWB_KEYWORDS):
        return "awb"
    if any(k in nl for k in _INVOICE_KEYWORDS):
        return "invoice"
    return "unknown"


def classify_files(
    files: List[AttachmentMeta],
) -> Tuple[Optional[AttachmentMeta], List[AttachmentMeta], List[AttachmentMeta]]:
    """
    Classify uploaded files into three buckets.

    Returns: (zc429, invoices, awbs)

    Detection order (strict priority):
    1. Filename matches ZC429/SAD keywords  → zc429 slot
    2. Filename matches AWB/tracking        → awbs list  (never invoice, never zc429)
    3. Everything else                      → invoices list

    Fallback rule: if no ZC429 was found by name, we do NOT silently
    promote the first file. Callers must handle zc429=None explicitly.
    This prevents AWB/tracking files from being misclassified as ZC429.
    """
    zc429    : Optional[AttachmentMeta] = None
    invoices : List[AttachmentMeta]     = []
    awbs     : List[AttachmentMeta]     = []

    for f in files:
        cat = _file_category(f.file_name)
        if cat == "zc429":
            if zc429 is None:
                zc429 = f
            else:
                invoices.append(f)   # second SAD-named file → treat as invoice
        elif cat == "awb":
            log.info("classify_files: %r → AWB", f.file_name)
            awbs.append(f)
        else:
            # invoice or unknown → treat as invoice for engine to parse
            invoices.append(f)

    log.info(
        "classify_files result: zc429=%s invoices=%d awbs=%d",
        zc429.file_name if zc429 else "None",
        len(invoices),
        len(awbs),
    )
    return zc429, invoices, awbs


# ── Tracking number extraction ────────────────────────────────────────────────

def extract_tracking_no(filename: str) -> str:
    """
    Extract a shipment tracking / AWB number from a filename.

    Strategy: find the longest digit-run of ≥6 chars in the stem.
    This handles real-world names like:
        "6876258325 Tracking.pdf"   → "6876258325"
        "AWB_123456789.pdf"         → "123456789"
        "DHL-9876543210-001.pdf"    → "9876543210"
        "airwaybill.pdf"            → ""   (no long digit run)
    """
    stem = Path(filename).stem
    # Prefer 8+ digit runs (most carrier tracking numbers); fallback to 6+
    for min_len in (8, 6):
        matches = re.findall(rf'\d{{{min_len},}}', stem)
        if matches:
            return max(matches, key=len)
    return ""


# ── doc_no extraction ─────────────────────────────────────────────────────────

def parse_doc_no(text: str) -> str:
    """
    Pull a document number from bot message text.

    Preferred format:  doc: PZ 12/3/2026
    Also accepted:     doc-no PZ-12  |  document: PZ 12/3/2026

    Bare text is NOT used as a fallback — too easy to accidentally capture
    a greeting or other free-form text as a document number.
    """
    text = text.strip()
    m = re.search(
        r"doc(?:ument)?[\s:\-_]*no?[:\-_]\s*([\w][\w\s/\-]{0,58})",
        text, re.I,
    )
    if m:
        return m.group(1).strip()
    return ""


# ── Cliq chat message fetcher (shared) ───────────────────────────────────────

async def _fetch_chat_messages(chat_id: str) -> List[dict]:
    """
    Fetch recent messages from a Cliq chat (channel or DM).
    Retries once with a refreshed token on 401.
    Returns raw message list; empty list on any error.
    """
    url = f"{_CLIQ_BASE}/chats/{chat_id}/messages"

    for attempt in range(2):   # attempt 0 = current token, attempt 1 = refreshed
        token = _token_mgr.current()
        if not token:
            log.error("CLIQ_BOT_TOKEN not set — cannot read chat messages.")
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, headers={"Authorization": f"Zoho-oauthtoken {token}"})
            if r.status_code == 401 and attempt == 0:
                log.warning("_fetch_chat_messages: 401 — refreshing token and retrying")
                await _token_mgr.refresh()
                continue
            r.raise_for_status()
            data = r.json()
            messages = data if isinstance(data, list) else data.get("data", [])
            log.info("_fetch_chat_messages %s: %d message(s)", chat_id, len(messages))
            return messages
        except Exception as exc:
            log.error("_fetch_chat_messages %s: %s", chat_id, exc)
            return []
    return []


# ── Cliq file lookup (resolve filenames → file IDs) ───────────────────────────

async def find_files_in_chat(
    chat_id:   str,
    filenames: List[str],
) -> List[AttachmentMeta]:
    """
    Query Cliq API for files shared in a chat, match by exact filename.
    Returns AttachmentMeta list for each matched filename (first occurrence = most recent).
    """
    messages  = await _fetch_chat_messages(chat_id)
    name_set  = {n.lower() for n in filenames}
    matched:    List[AttachmentMeta] = []
    seen_names: set                  = set()

    for msg in messages:
        if msg.get("type") != "file":
            continue
        f    = msg.get("content", {}).get("file", {})
        name = f.get("name", "")
        fid  = f.get("id",   "")
        size = int(f.get("dimensions", {}).get("size", 0))
        if name.lower() in name_set and fid and name.lower() not in seen_names:
            matched.append(AttachmentMeta(fid, name, size))
            seen_names.add(name.lower())
            log.info("find_files_in_chat: matched %r → %s", name, fid)

    if len(matched) < len(filenames):
        missing = {n for n in filenames if n.lower() not in seen_names}
        log.warning("find_files_in_chat: unmatched: %s", missing)

    return matched


async def scan_chat_files(
    chat_id: str,
) -> Tuple[Optional[AttachmentMeta], List[AttachmentMeta], List[AttachmentMeta]]:
    """
    Scan ALL recent messages in a chat for file attachments.
    Classifies each file by filename and returns (zc429, invoices, awbs).
    Only files with a real file_id are returned (slash-command filename-only
    entries are skipped — those are resolved separately).
    """
    messages = await _fetch_chat_messages(chat_id)
    all_files: List[AttachmentMeta] = []
    seen_ids: set = set()

    for msg in messages:
        if msg.get("type") != "file":
            continue
        f    = msg.get("content", {}).get("file", {})
        name = f.get("name", "")
        fid  = f.get("id",   "")
        size = int(f.get("dimensions", {}).get("size", 0))
        if name and fid and fid not in seen_ids:
            all_files.append(AttachmentMeta(fid, name, size))
            seen_ids.add(fid)

    log.info("scan_chat_files %s: %d unique file(s) found in chat", chat_id, len(all_files))
    return classify_files(all_files)


# ── Cliq file download ─────────────────────────────────────────────────────────

async def download_file(file_id: str, dest: Path) -> bool:
    """Download a Cliq file by ID. Retries once with a refreshed token on 401."""
    if not file_id:
        log.error("download_file called with empty file_id — skipping")
        return False

    url = f"{_CLIQ_BASE}/files/{file_id}"

    for attempt in range(2):
        token = _token_mgr.current()
        if not token:
            log.error("CLIQ_BOT_TOKEN not configured — cannot download files from Cliq.")
            return False
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Zoho-oauthtoken {token}"},
                    follow_redirects=True,
                )
            if r.status_code == 401 and attempt == 0:
                log.warning("download_file: 401 on %s — refreshing token and retrying", file_id)
                await _token_mgr.refresh()
                continue
            r.raise_for_status()
            dest.write_bytes(r.content)
            log.info("Downloaded %s → %s (%d bytes)", file_id, dest.name, len(r.content))
            return True
        except Exception as exc:
            log.error("File download failed %s: %s", file_id, exc)
            return False
    return False

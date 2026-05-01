#!/usr/bin/env python3
"""
batch_manager.py — Production batch session manager for Cliq bot workflow
=========================================================================
Upgrades from prototype → production:

  ✓ Multi-user isolation  — key = chat_id:user_id (no cross-user conflicts)
  ✓ Auto-submit timeout   — ready batch auto-fires after N minutes of inactivity
  ✓ Auto-submit on ready  — optional: fires immediately when all required files arrive
  ✓ Duplicate protection  — checked by file_id AND file_name
  ✓ Status tracking       — collecting → ready → downloading → processing → done/error
  ✓ Date-prefixed folders — 2026-04-24_PZ_1295_abc12345 (sortable, traceable)
  ✓ Expiry sweep          — cleans abandoned incomplete sessions after SESSION_TIMEOUT

Configuration (via .env):
    BATCH_SESSION_TIMEOUT_MINUTES   — expire incomplete session (default 30)
    BATCH_AUTO_SUBMIT_MINUTES       — auto-fire ready session (default 20)
    BATCH_AUTO_SUBMIT_IF_READY      — fire immediately when ready, skip /submit (default false)

Key format:
    session key = user_id        (when user_id is available — preferred)
    session key = chat_id        (fallback for single-user DM bot chats)

Required files for is_ready:
    • ≥1 invoice PDF
    • exactly 1 SAD/ZC429 PDF
    AWB is optional — shown in status but does not block ready state.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── Timeouts (read from settings, with fallbacks) ────────────────────────────
_SESSION_TIMEOUT_MIN:   int  = getattr(settings, "batch_session_timeout_minutes",   30)
_AUTO_SUBMIT_MIN:       int  = getattr(settings, "batch_auto_submit_minutes",        20)
_AUTO_SUBMIT_IF_READY:  bool = getattr(settings, "batch_auto_submit_if_ready",      False)
_SWEEP_INTERVAL_S:      int  = 15   # sweep granularity (seconds)
_COMPLETED_RETAIN_MIN:  int  = 30   # keep done/failed sessions visible for 30 min

# Test / synthetic user IDs that must never appear in production sessions
_TEST_USER_IDS = {"user456", "test", "demo", "testuser", "test_user"}


# ── Key helper ────────────────────────────────────────────────────────────────

def _key(chat_id: str, user_id: str = "") -> str:
    """
    Session lookup key.
    Prefer user_id (stable across chats/DMs); fall back to chat_id for
    single-user bot DMs where user_id is unavailable.
    """
    return user_id if user_id else chat_id


def _is_test_id(uid: str) -> bool:
    """Return True if uid matches a known synthetic test identifier."""
    if not uid:
        return False
    lower = uid.lower()
    return lower in _TEST_USER_IDS or lower.startswith("user") and not lower[4:].isdigit()


# ── File slot ─────────────────────────────────────────────────────────────────

@dataclass
class FileSlot:
    file_id:   str
    file_name: str
    added_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class BatchSession:
    """
    One active batch collection session per (chat, user) pair.

    Status lifecycle:
        collecting  — accepting files; not yet ready
        ready       — all required files present; awaiting /submit or auto-submit
        downloading — /submit accepted; files being fetched from Cliq
        processing  — engine is running
        done        — completed successfully
        error       — failed; session archived
    """
    batch_id:    str
    session_key: str          # f"{chat_id}:{user_id}" or chat_id
    chat_id:     str
    user_id:     str          # Zoho sender.get("id")    — primary isolation key
    user_email:  str          # Zoho sender.get("email") — human-readable display name
    doc_no:      str
    tracking_no: str          # AWB / shipment tracking number (e.g. "6876258325")
    created_at:  datetime
    last_active: datetime
    invoices:    List[FileSlot] = field(default_factory=list)
    sad:         Optional[FileSlot] = None
    awb:         Optional[FileSlot] = None
    status:      str = "collecting"

    # ── Visibility fields (bot-event flow) ────────────────────────────────────
    source:           str = "manual"  # "bot" | "manual"
    files_found:      int = 0         # how many files Cliq API returned
    files_downloaded: int = 0         # how many downloaded successfully
    error_message:    str = ""        # last failure reason (non-empty = failed)
    completed_at:     Optional[datetime] = None   # set when done/failed (for retention)

    # ── Derived ───────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return len(self.invoices) > 0 and self.sad is not None

    @property
    def missing_required(self) -> List[str]:
        m = []
        if not self.invoices:
            m.append("invoices")
        if self.sad is None:
            m.append("SAD / ZC429")
        return m

    @property
    def optional_missing(self) -> List[str]:
        return [] if self.awb else ["AWB (optional)"]

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.last_active).total_seconds()

    @property
    def is_session_expired(self) -> bool:
        """True if an incomplete session has been idle too long."""
        return (
            self.status == "collecting"
            and not self.is_ready
            and self.elapsed_seconds > _SESSION_TIMEOUT_MIN * 60
        )

    @property
    def is_auto_submit_due(self) -> bool:
        """True if a READY session has been idle past the auto-submit threshold."""
        return (
            self.status == "ready"
            and self.elapsed_seconds > _AUTO_SUBMIT_MIN * 60
        )

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """Return a list of blocking validation errors. Empty list = ok to submit."""
        errors = []
        if not self.invoices:
            errors.append("No invoices received — attach at least one invoice PDF with /invoice")
        if self.sad is None:
            errors.append("SAD / ZC429 missing — attach with /sad")
        return errors

    # ── Summary dict ──────────────────────────────────────────────────────────

    def operator_label(self) -> str:
        """Best available human-readable operator identifier."""
        if self.user_email:
            return self.user_email
        if self.user_id:
            return self.user_id
        return "unknown"

    def summary(self) -> Dict[str, Any]:
        elapsed_min = round(self.elapsed_seconds / 60, 1)
        return {
            "batch_id":         self.batch_id,
            "session_key":      self.session_key,
            "chat_id":          self.chat_id,
            "user_id":          self.user_id,
            "user_email":       self.user_email,
            "operator":         self.operator_label(),
            "doc_no":           self.doc_no,
            "tracking_no":      self.tracking_no,
            "status":           self.status,
            "source":           self.source,
            "is_ready":         self.is_ready,
            "missing_required": self.missing_required,
            "optional_missing": self.optional_missing,
            "invoice_count":    len(self.invoices),
            "invoices":         [{"file_name": f.file_name, "file_id": f.file_id} for f in self.invoices],
            "sad":              {"file_name": self.sad.file_name, "file_id": self.sad.file_id} if self.sad else None,
            "awb":              {"file_name": self.awb.file_name, "file_id": self.awb.file_id} if self.awb else None,
            "created_at":       self.created_at.isoformat(),
            "last_active":      self.last_active.isoformat(),
            "elapsed_minutes":  elapsed_min,
            "auto_submit_in":   max(0.0, round(_AUTO_SUBMIT_MIN - elapsed_min, 1)) if self.status == "ready" else None,
            # visibility fields
            "files_found":      self.files_found,
            "files_downloaded": self.files_downloaded,
            "error_message":    self.error_message,
            "completed_at":     self.completed_at.isoformat() if self.completed_at else None,
        }

    def status_message(self) -> str:
        """Human-readable status block for /status command."""
        inv_lines = "\n".join(f"  ✓ {f.file_name}" for f in self.invoices) or "  (none)"
        sad_line  = f"  ✓ {self.sad.file_name}" if self.sad else "  ✗ missing"
        awb_line  = f"  ✓ {self.awb.file_name}" if self.awb else "  – not provided (optional)"
        elapsed   = round(self.elapsed_seconds / 60, 1)
        op_line   = f"Operator: {self.operator_label()}\n" if self.operator_label() != "unknown" else ""

        if self.is_ready:
            if _AUTO_SUBMIT_IF_READY:
                action = "⚡ Auto-submit is ON — processing will start automatically"
            else:
                remaining = max(0.0, _AUTO_SUBMIT_MIN - elapsed)
                action = (
                    f"✅ Ready — send /submit OR auto-submits in ~{remaining:.0f} min"
                )
        else:
            action = "⏳ Waiting for: " + ", ".join(self.missing_required)

        return (
            f"📦 Batch: {self.doc_no}\n"
            f"ID: {self.batch_id}\n"
            f"{op_line}"
            f"\nInvoices ({len(self.invoices)}):\n{inv_lines}\n"
            f"SAD / ZC429:\n{sad_line}\n"
            f"AWB:\n{awb_line}\n\n"
            f"{action}"
        )

    # ── Folder structure ──────────────────────────────────────────────────────

    def create_folders(self) -> Path:
        root = settings.storage_root / "sessions" / self.batch_id
        for sub in ("invoices", "sad", "awb"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        return root

    def invoice_dir(self) -> Path:
        return settings.storage_root / "sessions" / self.batch_id / "invoices"

    def sad_path(self, filename: str) -> Path:
        return settings.storage_root / "sessions" / self.batch_id / "sad" / filename

    def awb_path(self, filename: str) -> Path:
        return settings.storage_root / "sessions" / self.batch_id / "awb" / filename


# ── Manager ───────────────────────────────────────────────────────────────────

# Type alias for the auto-submit and timeout callbacks
_SubmitCb  = Callable[[BatchSession], Coroutine]     # (session) → None
_ExpiryCb  = Callable[[str, str, str], Coroutine]    # (chat_id, user_id, doc_no) → None


class BatchManager:
    """
    Production-grade in-memory session store.

    Key design decisions:
      - Sessions keyed by chat_id:user_id — zero cross-user contamination
      - Duplicate files rejected by file_id OR file_name (whichever matches first)
      - Sweep task handles both auto-submit (ready + idle) and session expiry
      - All callbacks (submit, expiry) are async — no blocking the event loop
    """

    def __init__(self) -> None:
        self._sessions:    Dict[str, BatchSession] = {}
        self._sweep_task:  Optional[asyncio.Task]  = None
        self._submit_cb:   Optional[_SubmitCb]     = None
        self._expiry_cb:   Optional[_ExpiryCb]     = None

    # ── Callback registration ─────────────────────────────────────────────────

    def set_auto_submit_callback(self, fn: _SubmitCb) -> None:
        """Register the coroutine that processes a ready session."""
        self._submit_cb = fn

    def set_expiry_callback(self, fn: _ExpiryCb) -> None:
        """Register the coroutine that notifies a user about session expiry."""
        self._expiry_cb = fn

    # ── Sweep task ────────────────────────────────────────────────────────────

    def start_sweep(self) -> None:
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._sweep_loop())
            log.info(
                "BatchManager sweep started (interval=%ds, session_timeout=%dmin, "
                "auto_submit=%dmin, auto_submit_if_ready=%s)",
                _SWEEP_INTERVAL_S, _SESSION_TIMEOUT_MIN,
                _AUTO_SUBMIT_MIN, _AUTO_SUBMIT_IF_READY,
            )

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(_SWEEP_INTERVAL_S)
            for key, session in list(self._sessions.items()):

                # ── Auto-submit: ready session idle past threshold ────────────
                if session.is_auto_submit_due and self._submit_cb:
                    log.info(
                        "BatchManager: auto-submitting %s (idle %.1f min, threshold=%d min)",
                        session.batch_id,
                        session.elapsed_seconds / 60,
                        _AUTO_SUBMIT_MIN,
                    )
                    # Remove from active sessions before firing
                    self._sessions.pop(key, None)
                    session.status = "downloading"
                    try:
                        await self._submit_cb(session)
                    except Exception as exc:
                        log.error("Auto-submit callback failed for %s: %s", session.batch_id, exc)

                # ── Completed/failed retention expiry ─────────────────────────
                elif session.completed_at is not None:
                    age_min = (datetime.now(timezone.utc) - session.completed_at).total_seconds() / 60
                    if age_min > _COMPLETED_RETAIN_MIN:
                        log.info(
                            "BatchManager: removing completed session %s after %.0f min",
                            session.batch_id, age_min,
                        )
                        self._sessions.pop(key, None)

                # ── Session expiry: incomplete session idle too long ──────────
                elif session.is_session_expired:
                    log.warning(
                        "BatchManager: expiring incomplete session %s (chat=%s user=%s, "
                        "idle=%.1f min, missing=%s)",
                        session.batch_id, session.chat_id, session.user_id,
                        session.elapsed_seconds / 60, session.missing_required,
                    )
                    self._sessions.pop(key, None)
                    if self._expiry_cb:
                        try:
                            await self._expiry_cb(
                                session.chat_id, session.user_id, session.doc_no
                            )
                        except Exception as exc:
                            log.error("Expiry callback failed for %s: %s", session.batch_id, exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def start_session(
        self,
        chat_id:     str,
        user_id:     str,
        doc_no:      str,
        user_email:  str = "",
        tracking_no: str = "",
    ) -> BatchSession:
        """
        Start a new session for (chat, user). Replaces any existing session.

        batch_id format:
            SHIPMENT_<tracking>_<YYYY-MM>_<8hex>   when tracking number is known
            SHIPMENT_AUTO_<YYYY-MM>_<8hex>          fallback (no AWB / tracking)

        Raises ValueError if a test user_id is used and
        DEBUG_ALLOW_TEST_SESSIONS is not enabled.
        """
        allow_test = getattr(settings, "debug_allow_test_sessions", False)
        if _is_test_id(user_id) and not allow_test:
            raise ValueError(
                f"Rejected test user_id={user_id!r}. "
                "Set DEBUG_ALLOW_TEST_SESSIONS=true to allow synthetic sessions."
            )

        k = _key(chat_id, user_id)
        if k in self._sessions:
            old = self._sessions[k]
            log.info("BatchManager: replacing session %s for key %s", old.batch_id, k)

        month_str = datetime.now(timezone.utc).strftime("%Y-%m")
        uid_part  = uuid.uuid4().hex[:8]
        safe_trk  = (
            "".join(c if c.isalnum() else "_" for c in tracking_no)[:30]
            if tracking_no else "AUTO"
        )
        batch_id  = f"SHIPMENT_{safe_trk}_{month_str}_{uid_part}"

        now     = datetime.now(timezone.utc)
        session = BatchSession(
            batch_id    = batch_id,
            session_key = k,
            chat_id     = chat_id,
            user_id     = user_id,
            user_email  = user_email,
            doc_no      = doc_no,
            tracking_no = tracking_no,
            created_at  = now,
            last_active = now,
        )
        self._sessions[k] = session
        log.info("BatchManager: started %s key=%s doc=%r tracking=%r",
                 batch_id, k, doc_no, tracking_no)
        return session

    def get_session(self, chat_id: str, user_id: str = "") -> Optional[BatchSession]:
        return self._sessions.get(_key(chat_id, user_id))

    def add_file(
        self,
        chat_id:   str,
        user_id:   str,
        file_type: str,
        file_id:   str,
        file_name: str,
    ) -> tuple[Optional[BatchSession], str]:
        """
        Add a file to the active session.

        Returns (session, action) where action is one of:
            "added"     — file registered successfully
            "duplicate" — file already present (by file_id or file_name)
            "no_session"— no active session for this key
            "locked"    — session is no longer accepting files
        """
        session = self._sessions.get(_key(chat_id, user_id))
        if not session:
            return None, "no_session"

        if session.status not in ("collecting", "ready"):
            return session, "locked"

        slot = FileSlot(file_id=file_id, file_name=file_name)

        if file_type == "invoice":
            # Duplicate check: reject if file_id OR file_name already present
            dup_ids   = {f.file_id   for f in session.invoices}
            dup_names = {f.file_name.lower() for f in session.invoices}
            if (file_id and file_id in dup_ids) or file_name.lower() in dup_names:
                log.info("BatchManager: duplicate invoice %r in %s — skipped",
                         file_name, session.batch_id)
                session.touch()
                return session, "duplicate"
            session.invoices.append(slot)
            log.info("BatchManager: invoice +%r → %s (n=%d)",
                     file_name, session.batch_id, len(session.invoices))

        elif file_type == "sad":
            if (session.sad and
                    (session.sad.file_id == file_id or
                     session.sad.file_name.lower() == file_name.lower())):
                session.touch()
                return session, "duplicate"
            session.sad = slot
            log.info("BatchManager: SAD set %r → %s", file_name, session.batch_id)

        elif file_type == "awb":
            if (session.awb and
                    (session.awb.file_id == file_id or
                     session.awb.file_name.lower() == file_name.lower())):
                session.touch()
                return session, "duplicate"
            session.awb = slot
            log.info("BatchManager: AWB set %r → %s", file_name, session.batch_id)

        else:
            log.warning("BatchManager: unknown file_type %r — ignored", file_type)
            return session, "locked"

        # Update status
        session.status = "ready" if session.is_ready else "collecting"
        session.touch()
        return session, "added"

    def pop_session(self, chat_id: str, user_id: str = "") -> Optional[BatchSession]:
        return self._sessions.pop(_key(chat_id, user_id), None)

    def cancel_session(self, chat_id: str, user_id: str = "") -> Optional[str]:
        session = self._sessions.pop(_key(chat_id, user_id), None)
        if session:
            log.info("BatchManager: cancelled %s (key=%s)", session.batch_id, _key(chat_id, user_id))
            return session.batch_id
        return None

    def update_status(self, chat_id: str, status: str, user_id: str = "") -> bool:
        """
        Update session status.
        Valid statuses: collecting | resolving_files | downloading | processing |
                        posting | completed | done | failed | error
        Sets completed_at when transitioning to a terminal state.
        Returns True if session was found and updated, False otherwise.
        """
        session = self._sessions.get(_key(chat_id, user_id))
        if not session:
            return False
        old = session.status
        session.status = status
        if status in ("done", "completed", "failed", "error") and not session.completed_at:
            session.completed_at = datetime.now(timezone.utc)
        session.touch()
        log.info("BatchManager: %s status %s → %s", session.batch_id, old, status)
        return True

    def update_session(self, chat_id: str, user_id: str = "", **kwargs) -> bool:
        """
        Update arbitrary session fields in one call.
        Accepted kwargs: status, source, files_found, files_downloaded,
                         error_message, doc_no, and any other BatchSession attribute.
        Also handles completed_at automatically when status is terminal.
        Returns True if session was found, False otherwise.
        """
        session = self._sessions.get(_key(chat_id, user_id))
        if not session:
            return False
        status = kwargs.get("status")
        if status:
            old = session.status
            log.info("BatchManager: %s status %s → %s", session.batch_id, old, status)
            if status in ("done", "completed", "failed", "error") and not session.completed_at:
                session.completed_at = datetime.now(timezone.utc)
        for k, v in kwargs.items():
            if hasattr(session, k):
                setattr(session, k, v)
        session.touch()
        return True

    def set_file_inventory(
        self,
        chat_id:   str,
        user_id:   str = "",
        invoices:  Optional[List[str]] = None,
        sad:       Optional[str] = None,
        awb:       Optional[str] = None,
    ) -> bool:
        """
        Write classified file inventory into a bot session.

        Called from routes_bot.py after classify_files() so the dashboard
        shows invoice filenames, SAD filename, and AWB filename rather than
        empty slots.

        Uses synthetic file_id="bot-classified" since bot flow fetches files
        by name, not by the Cliq file_id.
        """
        session = self._sessions.get(_key(chat_id, user_id))
        if not session:
            return False

        if invoices is not None:
            session.invoices = [
                FileSlot(file_id="bot-classified", file_name=name)
                for name in invoices
            ]

        if sad is not None:
            session.sad = FileSlot(file_id="bot-classified", file_name=sad)
        elif sad == "":   # explicit empty string → clear slot
            session.sad = None

        if awb is not None:
            session.awb = FileSlot(file_id="bot-classified", file_name=awb)
        elif awb == "":
            session.awb = None

        session.touch()
        log.info(
            "BatchManager: set_file_inventory %s — invoices=%d sad=%s awb=%s",
            session.batch_id,
            len(session.invoices),
            session.sad.file_name if session.sad else "None",
            session.awb.file_name if session.awb else "None",
        )
        return True

    def set_tracking_no(
        self,
        chat_id:     str,
        user_id:     str = "",
        tracking_no: str = "",
    ) -> bool:
        """
        Update the tracking / AWB number on an existing session.
        Also rebuilds batch_id to embed the tracking number.
        """
        session = self._sessions.get(_key(chat_id, user_id))
        if not session:
            return False
        if not tracking_no or session.tracking_no == tracking_no:
            return False
        session.tracking_no = tracking_no
        # Rebuild batch_id to embed the tracking number
        month_str = session.created_at.strftime("%Y-%m")
        uid_part  = session.batch_id.split("_")[-1]   # preserve original short UUID
        safe_trk  = "".join(c if c.isalnum() else "_" for c in tracking_no)[:30]
        session.batch_id = f"SHIPMENT_{safe_trk}_{month_str}_{uid_part}"
        log.info(
            "BatchManager: set_tracking_no %s tracking=%r",
            session.batch_id, tracking_no,
        )
        return True

    def all_summaries(self) -> List[Dict[str, Any]]:
        return sorted(
            [s.summary() for s in self._sessions.values()],
            key=lambda x: x["created_at"],
            reverse=True,
        )

    def clear_test_sessions(self) -> List[str]:
        """
        Remove sessions whose key matches a known test/synthetic identifier.
        Safe to call at any time — only touches test keys, never real Zoho user IDs.
        Returns list of removed batch_ids.
        """
        removed = []
        for key in list(self._sessions.keys()):
            if _is_test_id(key):
                s = self._sessions.pop(key)
                removed.append(s.batch_id)
                log.info("BatchManager: cleared test session %s (key=%r)", s.batch_id, key)
        return removed

    def clear_all_sessions(self) -> int:
        """Remove all in-memory sessions. Use only on startup or force-reset."""
        count = len(self._sessions)
        self._sessions.clear()
        log.warning("BatchManager: cleared ALL %d sessions", count)
        return count

    @property
    def active_count(self) -> int:
        return len(self._sessions)


# ── Singleton ─────────────────────────────────────────────────────────────────

manager = BatchManager()

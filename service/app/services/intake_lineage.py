"""
intake_lineage.py — Immutable intake-event lineage store.

Purpose
-------
DHL ZC429 (and any future customs email source) intake is a legally
relevant event. Once a ZC429 email is accepted into the system, every
downstream effect — attachment classification, audit mutation,
readiness transition, operator correction — must be traceable back
to one and only one ``intake_event_id``.

This module provides the persistent, append-only lineage store that
makes that chain unforgeable.

Storage
-------
  storage_root/intake_lineage.db   (SQLite, WAL)

Tables
------
  intake_events                — one row per accepted intake
                                 (UNIQUE on source_kind + source_message_id
                                 — duplicate ingest returns the existing row)
  intake_attachments           — one row per classified+persisted file
                                 (UNIQUE on event + sha256 + filename
                                 — duplicate content never duplicates rows)
  intake_processing_history    — append-only processing notes per event
                                 (every reprocess pushes one row; the
                                 intake_event_id stays the same)

Hard guarantees
---------------
1. **No update path.** No public function updates an `intake_events`
   or `intake_attachments` row. Reprocess writes a *processing note*
   to the history table; nothing else changes.
2. **Idempotent insert.** ``get_or_create_intake_event`` is the only
   write path for events. It returns ``(row, was_existing)``.
3. **Attachment dedupe.** ``record_attachment`` uses
   ``INSERT OR IGNORE`` over (event, sha256, filename), so duplicate
   intake of the same email yields zero new attachment rows.
4. **No automation.** This module never calls wFirma, SMTP, PZ,
   Proforma, observers, schedulers, or correction_registry. Other
   services consume it; it consumes nothing back.

Public API
----------
  init_intake_lineage(db_path)
  get_or_create_intake_event(...)        → (row, was_existing)
  record_attachment(...)                 → attachment_id (or "" on dedupe)
  record_processing_note(...)            → note_id
  get_intake_event(intake_event_id)      → row | None
  get_intake_event_by_message_id(kind, mid) → row | None
  list_attachments(intake_event_id)      → [row]
  list_processing_history(intake_event_id) → [row]
  list_intake_events_for_batch(batch_id) → [row]
  list_intake_events_for_awb(awb)        → [row]
  lineage_envelope(intake_event_id, audit_path=None) → dict
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.logging import get_logger

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None

PROCESSING_VERSION = "1.0"


# ── Init ──────────────────────────────────────────────────────────────────────

def init_intake_lineage(db_path: Path) -> None:
    """Idempotent schema setup."""
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS intake_events (
                intake_event_id     TEXT PRIMARY KEY,
                source_kind         TEXT NOT NULL,
                source_message_id   TEXT NOT NULL,
                source_sender       TEXT NOT NULL DEFAULT '',
                source_subject      TEXT NOT NULL DEFAULT '',
                awb                 TEXT NOT NULL DEFAULT '',
                zc_number           TEXT NOT NULL DEFAULT '',
                batch_id            TEXT NOT NULL DEFAULT '',
                received_at         TEXT NOT NULL DEFAULT '',
                processing_version  TEXT NOT NULL DEFAULT '1.0',
                created_at          TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_ie_kind_msg
                ON intake_events (source_kind, source_message_id);
            CREATE INDEX IF NOT EXISTS idx_ie_awb
                ON intake_events (awb);
            CREATE INDEX IF NOT EXISTS idx_ie_batch
                ON intake_events (batch_id);

            CREATE TABLE IF NOT EXISTS intake_attachments (
                id                   TEXT PRIMARY KEY,
                intake_event_id      TEXT NOT NULL,
                original_filename    TEXT NOT NULL,
                safe_filename        TEXT NOT NULL DEFAULT '',
                sha256               TEXT NOT NULL,
                size                 INTEGER NOT NULL DEFAULT 0,
                classified_type      TEXT NOT NULL DEFAULT '',
                bucket               TEXT NOT NULL DEFAULT '',
                confidence           TEXT NOT NULL DEFAULT '',
                stored_path          TEXT NOT NULL DEFAULT '',
                source_message_id    TEXT NOT NULL DEFAULT '',
                source_sender        TEXT NOT NULL DEFAULT '',
                received_at          TEXT NOT NULL DEFAULT '',
                created_at           TEXT NOT NULL,
                FOREIGN KEY (intake_event_id)
                    REFERENCES intake_events(intake_event_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_ia_uniq
                ON intake_attachments (intake_event_id, sha256, original_filename);
            CREATE INDEX IF NOT EXISTS idx_ia_event
                ON intake_attachments (intake_event_id);
            CREATE INDEX IF NOT EXISTS idx_ia_sha
                ON intake_attachments (sha256);

            CREATE TABLE IF NOT EXISTS intake_processing_history (
                id                  TEXT PRIMARY KEY,
                intake_event_id     TEXT NOT NULL,
                note                TEXT NOT NULL DEFAULT '',
                actor               TEXT NOT NULL DEFAULT 'system',
                processing_version  TEXT NOT NULL DEFAULT '1.0',
                created_at          TEXT NOT NULL,
                FOREIGN KEY (intake_event_id)
                    REFERENCES intake_events(intake_event_id)
            );

            CREATE INDEX IF NOT EXISTS idx_iph_event
                ON intake_processing_history (intake_event_id, created_at);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("intake_lineage not initialised")
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(r) if r else None


# ── Append-only writers ──────────────────────────────────────────────────────

def get_or_create_intake_event(
    *,
    source_kind:       str,
    source_message_id: str,
    source_sender:     str = "",
    source_subject:    str = "",
    awb:               str = "",
    zc_number:         str = "",
    batch_id:          str = "",
    received_at:       str = "",
) -> Tuple[Dict[str, Any], bool]:
    """Atomic find-or-create. The (source_kind, source_message_id)
    pair is the unique key — same DHL email reprocessed twice always
    returns the same intake_event_id.

    Returns
    -------
    (row, was_existing) where ``was_existing`` is True iff a row
    already lived in the DB before this call.
    """
    if _db_path is None or not source_kind or not source_message_id:
        raise ValueError("source_kind and source_message_id are required")
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT * FROM intake_events "
            "WHERE source_kind = ? AND source_message_id = ?",
            (source_kind, source_message_id),
        ).fetchone()
        if existing:
            return dict(existing), True

        new_id = str(uuid.uuid4())
        con.execute(
            """
            INSERT INTO intake_events
              (intake_event_id, source_kind, source_message_id,
               source_sender, source_subject, awb, zc_number, batch_id,
               received_at, processing_version, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id, source_kind, source_message_id,
             source_sender, source_subject, awb, zc_number, batch_id,
             received_at, PROCESSING_VERSION, _now()),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM intake_events WHERE intake_event_id = ?",
            (new_id,),
        ).fetchone()
    return dict(row), False


def record_attachment(
    *,
    intake_event_id:   str,
    original_filename: str,
    sha256:            str,
    size:              int = 0,
    classified_type:   str = "",
    bucket:            str = "",
    confidence:        str = "",
    stored_path:       str = "",
    safe_filename:     str = "",
    source_message_id: str = "",
    source_sender:     str = "",
    received_at:       str = "",
) -> str:
    """Append-only attachment lineage row.

    Idempotent over (intake_event_id, sha256, original_filename) —
    duplicate intake of the same email writes 0 new rows. Returns the
    new attachment id, or ``""`` when an identical row already exists.
    """
    if _db_path is None or not intake_event_id or not sha256:
        return ""
    rid = str(uuid.uuid4())
    with _lock, _connect() as con:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO intake_attachments
              (id, intake_event_id, original_filename, safe_filename,
               sha256, size, classified_type, bucket, confidence,
               stored_path, source_message_id, source_sender,
               received_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (rid, intake_event_id, original_filename, safe_filename,
             sha256, int(size or 0), classified_type, bucket, confidence,
             stored_path, source_message_id, source_sender,
             received_at, _now()),
        )
        con.commit()
        if cur.rowcount == 0:
            return ""
    return rid


def record_processing_note(
    *,
    intake_event_id: str,
    note:            str,
    actor:           str = "system",
) -> str:
    """Append a processing note to an existing intake event. The
    intake_events row is NEVER updated — only this audit-style trail
    grows over time. Use this to record reprocesses, classification
    revisions, etc."""
    if _db_path is None or not intake_event_id:
        return ""
    rid = str(uuid.uuid4())
    with _lock, _connect() as con:
        con.execute(
            """
            INSERT INTO intake_processing_history
              (id, intake_event_id, note, actor,
               processing_version, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (rid, intake_event_id, note, actor or "system",
             PROCESSING_VERSION, _now()),
        )
        con.commit()
    return rid


# ── Read-only API ────────────────────────────────────────────────────────────

def get_intake_event(intake_event_id: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not intake_event_id:
        return None
    with _connect() as con:
        return _row(con.execute(
            "SELECT * FROM intake_events WHERE intake_event_id = ?",
            (intake_event_id,),
        ).fetchone())


def get_intake_event_by_message_id(
    source_kind: str, source_message_id: str,
) -> Optional[Dict[str, Any]]:
    if _db_path is None or not source_kind or not source_message_id:
        return None
    with _connect() as con:
        return _row(con.execute(
            "SELECT * FROM intake_events "
            "WHERE source_kind = ? AND source_message_id = ?",
            (source_kind, source_message_id),
        ).fetchone())


def list_attachments(intake_event_id: str) -> List[Dict[str, Any]]:
    if _db_path is None or not intake_event_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM intake_attachments "
            "WHERE intake_event_id = ? ORDER BY created_at ASC",
            (intake_event_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_processing_history(intake_event_id: str) -> List[Dict[str, Any]]:
    if _db_path is None or not intake_event_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM intake_processing_history "
            "WHERE intake_event_id = ? ORDER BY created_at ASC",
            (intake_event_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_intake_events_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    if _db_path is None or not batch_id:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM intake_events WHERE batch_id = ? "
            "ORDER BY created_at ASC",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_intake_events_for_awb(awb: str) -> List[Dict[str, Any]]:
    if _db_path is None or not awb:
        return []
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM intake_events WHERE awb = ? "
            "ORDER BY created_at ASC",
            (awb,),
        ).fetchall()
    return [dict(r) for r in rows]


def _linked_timeline_events(
    audit_path: Optional[Path],
    intake_event_id: str,
) -> List[Dict[str, Any]]:
    """Pull every timeline entry whose ``detail.intake_event_id`` matches.
    Read-only over audit.json. Returns ``[]`` if audit missing/unreadable."""
    if not audit_path or not intake_event_id:
        return []
    try:
        if not audit_path.exists():
            return []
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for ev in (audit.get("timeline") or []):
        det = ev.get("detail") or {}
        if isinstance(det, dict) and det.get("intake_event_id") == intake_event_id:
            out.append(ev)
    return out


def lineage_envelope(
    intake_event_id: str,
    *,
    audit_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Single read for the explainability surface:

      "Which exact DHL email and attachment created this state?"

    Returns:
      {
        intake_event:           row | None,
        attachments:            [row],
        processing_history:     [row],
        linked_timeline_events: [event] (if audit_path supplied),
      }
    """
    return {
        "intake_event":           get_intake_event(intake_event_id),
        "attachments":            list_attachments(intake_event_id),
        "processing_history":     list_processing_history(intake_event_id),
        "linked_timeline_events": _linked_timeline_events(
                                      audit_path, intake_event_id),
    }

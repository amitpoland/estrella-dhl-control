"""supplier_invoice_db.py — Supplier invoice OCR drafts (operator-review store).

Storage: <storage_root>/supplier_invoice_ocr.sqlite (separate file per the
one-file-per-domain convention).

Authority: LOCAL review store only. Drafts hold the machine extraction plus
the operator's confirmed corrections; nothing here writes to wFirma — a human
books the actual expense manually using a confirmed draft as reference
(expenses/add is unverified, docs/WFIRMA_API_VALIDATED_MAP.md).

Lifecycle: pending_review → confirmed | rejected. ``machine_original_json``
freezes what the model said at extraction time so operator edits stay
distinguishable from machine output (same audit posture as vision_invoice).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STATUS_PENDING   = "pending_review"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED  = "rejected"
STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_REJECTED)


# ── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_invoice_drafts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_uuid            TEXT NOT NULL UNIQUE,
    source_filename       TEXT NOT NULL,
    source_file_path      TEXT NOT NULL,
    raw_extraction_json   TEXT,
    machine_original_json TEXT,
    supplier_name         TEXT,
    supplier_gstin        TEXT,
    invoice_number        TEXT,
    invoice_date          TEXT,
    currency              TEXT,
    total_amount          REAL,
    needs_review_json     TEXT,
    status                TEXT NOT NULL DEFAULT 'pending_review',
    confirmed_fields_json TEXT,
    extraction_method     TEXT,
    extraction_confidence REAL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    confirmed_at          TEXT,
    confirmed_by          TEXT
);
CREATE INDEX IF NOT EXISTS ix_sid_status  ON supplier_invoice_drafts (status);
CREATE INDEX IF NOT EXISTS ix_sid_created ON supplier_invoice_drafts (created_at);
CREATE INDEX IF NOT EXISTS ix_sid_gstin   ON supplier_invoice_drafts (supplier_gstin);
"""


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as cx:
        cx.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Read ────────────────────────────────────────────────────────────────────

def get_draft(path: Path, draft_id: int) -> Optional[sqlite3.Row]:
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        return cx.execute(
            "SELECT * FROM supplier_invoice_drafts WHERE id = ?", (draft_id,)
        ).fetchone()


def list_drafts(path: Path, *, status: Optional[str] = None,
                limit: int = 50, offset: int = 0) -> List[sqlite3.Row]:
    where = ""
    args: List[Any] = []
    if status:
        where = " WHERE status = ?"
        args.append(status)
    args.extend([limit, offset])
    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        return cx.execute(
            "SELECT * FROM supplier_invoice_drafts" + where +
            " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            args,
        ).fetchall()


def count_drafts(path: Path, *, status: Optional[str] = None) -> int:
    where = ""
    args: List[Any] = []
    if status:
        where = " WHERE status = ?"
        args.append(status)
    with sqlite3.connect(path) as cx:
        r = cx.execute(
            "SELECT COUNT(*) FROM supplier_invoice_drafts" + where, args
        ).fetchone()
    return int(r[0]) if r else 0


# ── Write ───────────────────────────────────────────────────────────────────

def create_draft(path: Path, data: Dict[str, Any]) -> sqlite3.Row:
    """Insert a new draft. ``data`` must include draft_uuid, source_filename,
    source_file_path; everything else is optional. Returns the stored row."""
    now = _now()
    status = data.get("status") or STATUS_PENDING
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}")
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            """INSERT INTO supplier_invoice_drafts
               (draft_uuid, source_filename, source_file_path,
                raw_extraction_json, machine_original_json,
                supplier_name, supplier_gstin, invoice_number, invoice_date,
                currency, total_amount, needs_review_json, status,
                extraction_method, extraction_confidence,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["draft_uuid"],
                data["source_filename"],
                data["source_file_path"],
                data.get("raw_extraction_json"),
                data.get("machine_original_json"),
                data.get("supplier_name"),
                data.get("supplier_gstin"),
                data.get("invoice_number"),
                data.get("invoice_date"),
                data.get("currency"),
                data.get("total_amount"),
                data.get("needs_review_json") or "[]",
                status,
                data.get("extraction_method"),
                data.get("extraction_confidence"),
                now, now,
            ),
        )
        cx.commit()
        draft_id = cur.lastrowid
    row = get_draft(path, int(draft_id))
    assert row is not None
    return row


def confirm_draft(path: Path, draft_id: int, *, confirmed_by: str,
                  confirmed_fields: Dict[str, Any]) -> bool:
    """Promote a pending draft to confirmed with the operator's final values.

    Only transitions from ``pending_review``; returns False when the draft is
    absent or already confirmed/rejected (caller maps that to 404/409)."""
    now = _now()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            """UPDATE supplier_invoice_drafts
               SET status = ?, confirmed_fields_json = ?,
                   confirmed_at = ?, confirmed_by = ?, updated_at = ?
               WHERE id = ? AND status = ?""",
            (STATUS_CONFIRMED, json.dumps(confirmed_fields, ensure_ascii=False),
             now, confirmed_by, now, draft_id, STATUS_PENDING),
        )
        cx.commit()
        return cur.rowcount > 0


def reject_draft(path: Path, draft_id: int, *, rejected_by: str) -> bool:
    """Mark a pending draft rejected. Only transitions from pending_review."""
    now = _now()
    with sqlite3.connect(path) as cx:
        cur = cx.execute(
            """UPDATE supplier_invoice_drafts
               SET status = ?, confirmed_at = ?, confirmed_by = ?, updated_at = ?
               WHERE id = ? AND status = ?""",
            (STATUS_REJECTED, now, rejected_by, now, draft_id, STATUS_PENDING),
        )
        cx.commit()
        return cur.rowcount > 0

"""
SQLite persistence for the customer delivery-confirmation flow.

One file per domain (``storage_root/delivery_confirmations.db``), owned entirely
by this module — direct ``sqlite3`` calls, no shared ORM (matches the repo's
one-DB-per-domain convention).

Three tables:
  * ``delivery_notifications`` — one row per OUTBOUND AWB we emailed the
    customer a "confirm receipt" link for. ``UNIQUE(awb)`` makes the outbound
    notification idempotent: a delivered event that fires twice never queues a
    second email.
  * ``delivery_receipts`` — one row per opaque public token minted for a
    notification. Stores only the SHA-256 hash of the token (never the token
    itself, never any internal id). Records the customer's response
    (good / issue) once used.
  * ``delivery_evidence`` — uploaded photos attached to a receipt (metadata
    only; bytes live on disk under the evidence root).

Nothing here mutates accounting / invoice / stock / product / DHL state — this
is a customer-facing acknowledgement store only.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS delivery_notifications (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id             INTEGER,
    batch_id             TEXT,
    client_name          TEXT,
    awb                  TEXT NOT NULL UNIQUE,
    email_to             TEXT,
    email_id             TEXT,
    queued_at            TEXT,
    sent_at              TEXT,
    status               TEXT NOT NULL DEFAULT 'queued',
    activation_cutoff_ok INTEGER NOT NULL DEFAULT 0 CHECK(activation_cutoff_ok IN (0, 1)),
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS delivery_receipts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash          TEXT NOT NULL UNIQUE,
    awb                 TEXT,
    draft_id            INTEGER,
    batch_id            TEXT,
    client_name         TEXT,
    customer_name       TEXT,
    expires_at          TEXT,
    used_at             TEXT,
    condition           TEXT,
    issue_categories    TEXT,
    comments            TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    carrier_delivered_at TEXT,
    response_ip         TEXT,
    audit_json          TEXT
);

CREATE TABLE IF NOT EXISTS delivery_evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id    INTEGER NOT NULL,
    stored_name   TEXT NOT NULL,
    original_name TEXT,
    mime          TEXT,
    size_bytes    INTEGER,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_dc_notif_awb ON delivery_notifications(awb);
CREATE INDEX IF NOT EXISTS idx_dc_receipt_awb ON delivery_receipts(awb);
CREATE INDEX IF NOT EXISTS idx_dc_receipt_draft ON delivery_receipts(draft_id);
CREATE INDEX IF NOT EXISTS idx_dc_evidence_receipt ON delivery_evidence(receipt_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the delivery-confirmation tables if absent. Idempotent."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


# ── Notifications ──────────────────────────────────────────────────────────────


def create_notification_if_absent(
    db_path: Path,
    *,
    awb: str,
    draft_id: Optional[int],
    batch_id: Optional[str],
    client_name: Optional[str],
    email_to: Optional[str],
    activation_cutoff_ok: bool,
    status: str = "queued",
) -> tuple[Optional[dict], bool]:
    """Insert a notification row for the AWB, or return the existing one.

    Returns ``(row, created)``. ``UNIQUE(awb)`` guarantees only the first caller
    for a given outbound AWB inserts — this is the idempotency anchor that stops
    a repeated delivered event from queuing a second customer email.
    """
    awb = (awb or "").strip()
    if not awb:
        return None, False
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO delivery_notifications
                (awb, draft_id, batch_id, client_name, email_to,
                 activation_cutoff_ok, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(awb) DO NOTHING
            """,
            (
                awb, draft_id, batch_id, client_name, email_to,
                int(bool(activation_cutoff_ok)), status,
            ),
        )
        created = bool(conn.execute("SELECT changes()").fetchone()[0])
        row = conn.execute(
            "SELECT * FROM delivery_notifications WHERE awb = ?", (awb,)
        ).fetchone()
    return (dict(row) if row else None), created


def mark_notification_queued(
    db_path: Path, awb: str, *, email_id: str, email_to: str, queued_at: str,
) -> None:
    """Record the queued email id/recipient on the notification row."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE delivery_notifications
               SET email_id = ?, email_to = ?, queued_at = ?, status = 'queued'
             WHERE awb = ?
            """,
            (email_id, email_to, queued_at, (awb or "").strip()),
        )


def mark_notification_sent(db_path: Path, awb: str, *, sent_at: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE delivery_notifications SET sent_at = ?, status = 'sent' WHERE awb = ?",
            (sent_at, (awb or "").strip()),
        )


def mark_notification_failed(db_path: Path, awb: str, *, reason: str = "") -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE delivery_notifications SET status = 'failed' WHERE awb = ?",
            ((awb or "").strip(),),
        )


def get_notification_by_awb(db_path: Path, awb: str) -> Optional[dict]:
    if not (awb or "").strip() or not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_notifications WHERE awb = ?", ((awb or "").strip(),)
        ).fetchone()
    return dict(row) if row else None


# ── Receipt tokens ─────────────────────────────────────────────────────────────


def create_receipt_token_row(
    db_path: Path,
    *,
    token_hash: str,
    awb: Optional[str],
    draft_id: Optional[int],
    batch_id: Optional[str],
    client_name: Optional[str],
    customer_name: Optional[str],
    expires_at: str,
    carrier_delivered_at: Optional[str] = None,
) -> dict:
    """Insert one public receipt token row. ``token_hash`` is the SHA-256 hex of
    the opaque token — the token itself is never stored."""
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO delivery_receipts
                (token_hash, awb, draft_id, batch_id, client_name, customer_name,
                 expires_at, carrier_delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token_hash, awb, draft_id, batch_id, client_name, customer_name,
                expires_at, carrier_delivered_at,
            ),
        )
        rid = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE id = ?", (rid,)
        ).fetchone()
    return dict(row)


def get_receipt_by_token_hash(db_path: Path, token_hash: str) -> Optional[dict]:
    if not (token_hash or "").strip() or not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE token_hash = ?",
            ((token_hash or "").strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_receipt_by_id(db_path: Path, receipt_id: int) -> Optional[dict]:
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE id = ?", (int(receipt_id),)
        ).fetchone()
    return dict(row) if row else None


def mark_receipt_used(
    db_path: Path,
    *,
    token_hash: str,
    condition: str,
    issue_categories: Optional[List[str]],
    comments: str,
    used_at: str,
    response_ip: Optional[str] = None,
    audit: Optional[Dict[str, Any]] = None,
) -> dict:
    """Record the customer's response on an unused, unexpired receipt.

    Raises ``KeyError`` when the token is unknown, and ``ValueError`` when the
    receipt was already used (replay) or has expired. The used-state flip is
    done inside a single transaction with a ``used_at IS NULL`` guard so two
    concurrent submissions cannot both win.
    """
    token_hash = (token_hash or "").strip()
    cats_json = json.dumps(list(issue_categories or []), ensure_ascii=False)
    audit_json = json.dumps(audit or {}, ensure_ascii=False)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if row is None:
            raise KeyError("unknown receipt token")
        if row["used_at"]:
            raise ValueError("receipt already used")
        exp = row["expires_at"]
        if exp and used_at > exp:
            raise ValueError("receipt expired")
        cur = conn.execute(
            """
            UPDATE delivery_receipts
               SET used_at = ?, condition = ?, issue_categories = ?,
                   comments = ?, response_ip = ?, audit_json = ?
             WHERE token_hash = ? AND used_at IS NULL
            """,
            (used_at, condition, cats_json, comments, response_ip, audit_json,
             token_hash),
        )
        if cur.rowcount == 0:
            # Lost the race to a concurrent submit.
            raise ValueError("receipt already used")
        updated = conn.execute(
            "SELECT * FROM delivery_receipts WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return dict(updated)


def get_receipt_for_draft(db_path: Path, draft_id: int) -> Optional[dict]:
    """Newest receipt row for a draft (operator view)."""
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE draft_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (int(draft_id),),
        ).fetchone()
    return dict(row) if row else None


def get_receipt_for_awb(db_path: Path, awb: str) -> Optional[dict]:
    if not (awb or "").strip() or not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_receipts WHERE awb = ? ORDER BY id DESC LIMIT 1",
            ((awb or "").strip(),),
        ).fetchone()
    return dict(row) if row else None


# ── Evidence ───────────────────────────────────────────────────────────────────


def add_evidence(
    db_path: Path,
    *,
    receipt_id: int,
    stored_name: str,
    original_name: Optional[str],
    mime: Optional[str],
    size_bytes: int,
) -> dict:
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO delivery_evidence
                (receipt_id, stored_name, original_name, mime, size_bytes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(receipt_id), stored_name, original_name, mime, int(size_bytes)),
        )
        rid = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM delivery_evidence WHERE id = ?", (rid,)
        ).fetchone()
    return dict(row)


def get_evidence(db_path: Path, evidence_id: int) -> Optional[dict]:
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_evidence WHERE id = ?", (int(evidence_id),)
        ).fetchone()
    return dict(row) if row else None


def list_evidence_for_receipt(db_path: Path, receipt_id: int) -> List[dict]:
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM delivery_evidence WHERE receipt_id = ? ORDER BY id ASC",
            (int(receipt_id),),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Manifest summary helper ────────────────────────────────────────────────────


def get_notification_for_draft(db_path: Path, draft_id: int) -> Optional[dict]:
    """Latest delivery-notification row for a draft, if any."""
    if not Path(db_path).exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_notifications WHERE draft_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (int(draft_id),),
        ).fetchone()
    return dict(row) if row else None


def get_delivery_summary_for_draft(db_path: Path, draft_id: int) -> Optional[dict]:
    """Compact summary for the document manifest / operator view, or None.

    Never exposes token hashes, IPs, or filesystem paths — only the customer's
    acknowledgement state, condition, categories and evidence count.

    ``operator_status`` vocabulary:
      - awaiting_customer — notification queued/sent, no response yet
      - confirmed_good    — customer confirmed good condition
      - issue_reported    — customer reported damage/loss/tampering
      - token_issued      — receipt token minted, waiting on customer
    """
    if not Path(db_path).exists():
        return None
    receipt = get_receipt_for_draft(db_path, draft_id)
    notification = get_notification_for_draft(db_path, draft_id)
    if receipt is None and notification is None:
        return None

    cats: list = []
    evidence: list = []
    responded = False
    condition = None
    comments = None
    responded_at = None
    expires_at = None
    customer_name = None
    evidence_ids: list = []

    if receipt is not None:
        try:
            cats = json.loads(receipt.get("issue_categories") or "[]")
        except Exception:
            cats = []
        evidence = list_evidence_for_receipt(db_path, receipt["id"])
        responded = bool(receipt.get("used_at"))
        condition = receipt.get("condition")
        comments = receipt.get("comments")
        responded_at = receipt.get("used_at")
        expires_at = receipt.get("expires_at")
        customer_name = receipt.get("customer_name")
        evidence_ids = [e["id"] for e in evidence]

    if responded and condition == "good":
        operator_status = "confirmed_good"
    elif responded and condition == "issue":
        operator_status = "issue_reported"
    elif notification is not None or (receipt is not None and not responded):
        operator_status = "awaiting_customer"
    else:
        operator_status = "token_issued"

    return {
        "operator_status": operator_status,
        "responded": responded,
        "condition": condition,
        "issue_categories": cats,
        "comments": comments,
        "responded_at": responded_at,
        "expires_at": expires_at,
        "evidence_count": len(evidence),
        "evidence_ids": evidence_ids,
        "customer_name": customer_name,
        "notification_status": (notification or {}).get("status"),
        "notification_queued_at": (notification or {}).get("queued_at"),
        "awb": (receipt or notification or {}).get("awb"),
    }

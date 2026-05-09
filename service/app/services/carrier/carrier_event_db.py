"""
carrier_event_db.py — SQLite store for inbound carrier-webhook events
and webhook subscriptions.

DL-E1 scope
-----------
Two tables:

  carrier_webhook_events
      One row per inbound event we have ever seen. Idempotency key is
      the synthetic event_id derived from
      ``sha256(carrier|awb|status_code|occurred_at)``. ``INSERT OR
      IGNORE`` makes duplicate inserts a no-op and lets the handler
      detect repeats by checking how many rows changed.
      The row carries:
        - identity: id, carrier, awb, status_code, occurred_at
        - lifecycle: applied_at, outcome
        - link to the registry: shipment_id (NULL for no_shipment)
        - full DHL status object as raw_json (audit trail)

  carrier_webhook_subscriptions
      One row per (subscription_id, secret_hash). DHL provides a
      "secret" string at subscription-confirmation time; we never
      persist the raw secret. Multiple rows may exist for one
      subscription_id during secret rotation — the activation
      endpoint accepts any matching hash.

Hard rules (mirror carrier_shipment_db / intake_lineage discipline)
------------------------------------------------------------------
* Module-level ``_db_path`` singleton; ``init_db`` is idempotent.
* No web framework imports. No coordinator import. No adapter import.
* No outbound HTTP. No env reads.
* All write functions use a single threading.Lock for cross-thread
  consistency (the handler is called from an async route worker;
  pytest concurrency tests need this).

Public API
----------
  init_db(db_path)
  insert_event_or_ignore(...)              -> bool        # True if inserted
  mark_outcome(event_id, outcome, *, shipment_id=None)
  get_event(event_id)                      -> dict | None
  list_events_for_awb(carrier, awb)        -> list[dict]
  upsert_subscription(...)                 -> bool        # True if new
  confirm_subscription(...)
  get_subscription(subscription_id)        -> list[dict]  # one per hash
  compute_event_id(carrier, awb, status_code, occurred_at) -> str
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_lock: threading.Lock = threading.Lock()
_db_path: Optional[Path] = None


# ── Init ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Idempotent schema setup."""
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS carrier_webhook_events (
                id            TEXT PRIMARY KEY,
                carrier       TEXT NOT NULL,
                awb           TEXT NOT NULL,
                status_code   TEXT NOT NULL,
                occurred_at   TEXT NOT NULL,
                received_at   TEXT NOT NULL,
                applied_at    TEXT NOT NULL DEFAULT '',
                shipment_id   TEXT NOT NULL DEFAULT '',
                outcome       TEXT NOT NULL DEFAULT 'pending',
                raw_json      TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_cwe_carrier_awb
                ON carrier_webhook_events (carrier, awb);
            CREATE INDEX IF NOT EXISTS idx_cwe_outcome
                ON carrier_webhook_events (outcome);

            CREATE TABLE IF NOT EXISTS carrier_webhook_subscriptions (
                subscription_id  TEXT NOT NULL,
                secret_hash      TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                confirmed_at     TEXT NOT NULL DEFAULT '',
                disabled_at      TEXT NOT NULL DEFAULT '',
                last_event_at    TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (subscription_id, secret_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_cws_sub
                ON carrier_webhook_subscriptions (subscription_id);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError(
            "carrier_event_db not initialised — call init_db() first"
        )
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(r) if r else None


# ── Idempotency key ─────────────────────────────────────────────────────────

def compute_event_id(
    *,
    carrier:     str,
    awb:         str,
    status_code: str,
    occurred_at: str,
) -> str:
    """Deterministic event id used for dedupe.

    Same inputs always produce the same id. The handler relies on
    this for the ``INSERT OR IGNORE`` no-op check — a duplicate
    insert means the same event has already been seen.
    """
    seed = (
        f"{(carrier or '').strip().lower()}|"
        f"{(awb or '').strip()}|"
        f"{(status_code or '').strip().lower()}|"
        f"{(occurred_at or '').strip()}"
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# ── Event writes ────────────────────────────────────────────────────────────

def insert_event_or_ignore(
    *,
    event_id:    str,
    carrier:     str,
    awb:         str,
    status_code: str,
    occurred_at: str,
    raw_json:    str = "",
) -> bool:
    """Insert a new event row. Returns True iff a row was inserted.

    Uses ``INSERT OR IGNORE``. The PRIMARY KEY on ``id`` makes this
    a no-op for duplicate ids. The caller checks the return to
    distinguish first-seen from replay.
    """
    if not event_id:
        raise ValueError("event_id is required")
    with _lock, _connect() as con:
        cur = con.execute(
            """INSERT OR IGNORE INTO carrier_webhook_events
                   (id, carrier, awb, status_code, occurred_at,
                    received_at, applied_at, shipment_id, outcome,
                    raw_json)
               VALUES (?,?,?,?,?,?, '', '', 'pending', ?)""",
            (event_id, carrier, awb, status_code, occurred_at,
             _now(), raw_json),
        )
        return cur.rowcount > 0


def mark_outcome(
    event_id:    str,
    outcome:     str,
    *,
    shipment_id: Optional[str] = None,
) -> None:
    """Update the outcome (and optionally shipment_id) of a stored event.

    Used by the handler after the dedupe + translation + coordinator
    flow lands. The set of outcomes is application-level; valid
    values today are: ``applied``, ``deduped``, ``ignored``,
    ``no_shipment``, ``ingest_failed``.
    """
    if not event_id or not outcome:
        raise ValueError("event_id and outcome are required")
    with _lock, _connect() as con:
        if shipment_id is None:
            con.execute(
                """UPDATE carrier_webhook_events
                       SET outcome=?, applied_at=?
                   WHERE id=?""",
                (outcome, _now(), event_id),
            )
        else:
            con.execute(
                """UPDATE carrier_webhook_events
                       SET outcome=?, applied_at=?, shipment_id=?
                   WHERE id=?""",
                (outcome, _now(), shipment_id, event_id),
            )


# ── Event reads ─────────────────────────────────────────────────────────────

def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    if not (event_id or "").strip():
        return None
    with _connect() as con:
        return _row(con.execute(
            "SELECT * FROM carrier_webhook_events WHERE id=?",
            (event_id,),
        ).fetchone())


def list_events_for_awb(carrier: str, awb: str) -> List[Dict[str, Any]]:
    if not (awb or "").strip():
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM carrier_webhook_events
                   WHERE carrier=? AND awb=?
                   ORDER BY received_at""",
            (carrier, awb),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Subscription writes ─────────────────────────────────────────────────────

def hash_secret(secret: str) -> str:
    """sha256 of a webhook secret. Used to avoid storing raw secrets."""
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def upsert_subscription(
    *,
    subscription_id: str,
    secret_hash:     str,
) -> bool:
    """Insert a (subscription_id, secret_hash) pair if absent.

    Returns True iff a new row was inserted. Multiple rows can exist
    for one subscription_id during secret rotation.
    """
    if not subscription_id or not secret_hash:
        raise ValueError("subscription_id and secret_hash are required")
    with _lock, _connect() as con:
        cur = con.execute(
            """INSERT OR IGNORE INTO carrier_webhook_subscriptions
                   (subscription_id, secret_hash, created_at)
               VALUES (?,?,?)""",
            (subscription_id, secret_hash, _now()),
        )
        return cur.rowcount > 0


def confirm_subscription(
    *,
    subscription_id: str,
    secret_hash:     str,
) -> None:
    """Stamp ``confirmed_at`` for the matching (sub_id, hash) pair."""
    if not subscription_id or not secret_hash:
        raise ValueError("subscription_id and secret_hash are required")
    with _lock, _connect() as con:
        con.execute(
            """UPDATE carrier_webhook_subscriptions
                   SET confirmed_at=?
               WHERE subscription_id=? AND secret_hash=?""",
            (_now(), subscription_id, secret_hash),
        )


def get_subscription(subscription_id: str) -> List[Dict[str, Any]]:
    """Return all (subscription_id, *) rows. May be empty."""
    if not (subscription_id or "").strip():
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM carrier_webhook_subscriptions
                   WHERE subscription_id=?
                   ORDER BY created_at""",
            (subscription_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def has_active_secret(subscription_id: str, secret_hash: str) -> bool:
    """True iff the (subscription_id, secret_hash) pair exists and is
    not disabled."""
    if not subscription_id or not secret_hash:
        return False
    with _connect() as con:
        row = con.execute(
            """SELECT disabled_at FROM carrier_webhook_subscriptions
                   WHERE subscription_id=? AND secret_hash=?""",
            (subscription_id, secret_hash),
        ).fetchone()
    if row is None:
        return False
    return not (row["disabled_at"] or "").strip()

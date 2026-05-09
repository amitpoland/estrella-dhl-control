"""
dhl_shadow_db.py — SQLite store for DHL shadow-mode call outcomes.

DL-F2 scope
-----------
One table: ``carrier_shadow_log``. Every shadow-mode call lands one
row capturing:

  * which method was called (create / cancel / fetch_label / pickup)
  * a deterministic ``request_hash`` of the canonical request seed
  * the stub outcome (status / awb / label_format / label_size /
    error_class / error_summary)
  * the live outcome (same shape, plus duration_ms)
  * a classification of the diff (match / shape_diff / live_only_error
    / stub_only_error / both_error / unknown)

Hard rules (also enforced by source-grep tests)
-----------------------------------------------
* No raw response bodies are persisted. The live response can carry
  PII (addresses, declared values) and credentials in error bodies;
  storing only metadata blocks an accidental second PII store.
* No raw label bytes are persisted; the schema captures only sizes.
* No credentials are persisted at any point.
* No web-framework imports, no coordinator import, no adapter imports
  from this module.
* No outbound HTTP. No env reads.

Public API
----------
  init_db(db_path)
  compute_request_hash(method, *parts)              -> str
  record_call_outcome(...)                          -> str   (row id)
  list_recent(*, method=None, diff_outcome=None,
              limit=200)                            -> list[dict]
  summarise_last_n_days(days=7)                     -> list[dict]
  truncate_summary(text, max_chars=200)             -> str
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
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

            CREATE TABLE IF NOT EXISTS carrier_shadow_log (
                id                  TEXT PRIMARY KEY,
                method              TEXT NOT NULL,
                request_hash        TEXT NOT NULL,
                actor               TEXT NOT NULL DEFAULT '',
                stub_status         TEXT NOT NULL DEFAULT 'ok',
                stub_awb            TEXT NOT NULL DEFAULT '',
                stub_label_format   TEXT NOT NULL DEFAULT '',
                stub_label_size     INTEGER NOT NULL DEFAULT 0,
                stub_error_class    TEXT NOT NULL DEFAULT '',
                stub_error_summary  TEXT NOT NULL DEFAULT '',
                live_status         TEXT NOT NULL DEFAULT 'pending',
                live_awb            TEXT NOT NULL DEFAULT '',
                live_label_format   TEXT NOT NULL DEFAULT '',
                live_label_size     INTEGER NOT NULL DEFAULT 0,
                live_http_status    INTEGER NOT NULL DEFAULT 0,
                live_error_class    TEXT NOT NULL DEFAULT '',
                live_error_summary  TEXT NOT NULL DEFAULT '',
                live_duration_ms    INTEGER NOT NULL DEFAULT 0,
                diff_outcome        TEXT NOT NULL DEFAULT 'unknown',
                diff_notes          TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_csl_method
                ON carrier_shadow_log (method);
            CREATE INDEX IF NOT EXISTS idx_csl_diff
                ON carrier_shadow_log (diff_outcome);
            CREATE INDEX IF NOT EXISTS idx_csl_created_at
                ON carrier_shadow_log (created_at);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError(
            "dhl_shadow_db not initialised — call init_db() first"
        )
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Helpers ─────────────────────────────────────────────────────────────────

def compute_request_hash(method: str, *parts: Any) -> str:
    """Deterministic sha256 over the (method, parts) seed.

    Same inputs always produce the same hex; different methods always
    produce different hashes even when the parts are identical (the
    method is part of the seed).
    """
    seed = (method or "").strip().lower() + "|" + "|".join(
        "" if p is None else str(p) for p in parts
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def truncate_summary(text: str, max_chars: int = 200) -> str:
    """Cap an error-summary string at *max_chars* with an ellipsis."""
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


# Recognised values (validated at write-time so a typo in a caller
# cannot poison the diff dashboard).
_VALID_DIFF_OUTCOMES = frozenset({
    "match",
    "live_only_error",
    "stub_only_error",
    "both_error",
    "shape_diff",
    "unknown",
})


# ── Writes ──────────────────────────────────────────────────────────────────

def record_call_outcome(
    *,
    method:              str,
    request_hash:        str,
    actor:               str = "",
    stub_status:         str = "ok",
    stub_awb:            str = "",
    stub_label_format:   str = "",
    stub_label_size:     int = 0,
    stub_error_class:    str = "",
    stub_error_summary:  str = "",
    live_status:         str = "pending",
    live_awb:            str = "",
    live_label_format:   str = "",
    live_label_size:     int = 0,
    live_http_status:    int = 0,
    live_error_class:    str = "",
    live_error_summary:  str = "",
    live_duration_ms:    int = 0,
    diff_outcome:        str = "unknown",
    diff_notes:          str = "",
) -> str:
    """Insert one shadow-log row and return its id.

    All inputs are passed through one truncation pass so a runaway
    error message cannot grow the row beyond ~1 KB. Diff outcomes
    outside the documented set fall back to "unknown" rather than
    raising — the shadow log must never crash the operator path.
    """
    if not (method or "").strip() or not (request_hash or "").strip():
        raise ValueError("method and request_hash are required")
    rid = str(uuid.uuid4())
    diff_outcome_clean = (
        diff_outcome if diff_outcome in _VALID_DIFF_OUTCOMES else "unknown"
    )
    with _lock, _connect() as con:
        con.execute(
            """INSERT INTO carrier_shadow_log
                   (id, method, request_hash, actor,
                    stub_status, stub_awb, stub_label_format,
                    stub_label_size, stub_error_class,
                    stub_error_summary,
                    live_status, live_awb, live_label_format,
                    live_label_size, live_http_status,
                    live_error_class, live_error_summary,
                    live_duration_ms, diff_outcome, diff_notes,
                    created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid, method, request_hash, actor or "",
                stub_status, stub_awb, stub_label_format,
                int(stub_label_size or 0),
                stub_error_class,
                truncate_summary(stub_error_summary),
                live_status, live_awb, live_label_format,
                int(live_label_size or 0),
                int(live_http_status or 0),
                live_error_class,
                truncate_summary(live_error_summary),
                int(live_duration_ms or 0),
                diff_outcome_clean,
                truncate_summary(diff_notes),
                _now_iso(),
            ),
        )
    return rid


# ── Reads ───────────────────────────────────────────────────────────────────

def get_row(row_id: str) -> Optional[Dict[str, Any]]:
    if not (row_id or "").strip():
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM carrier_shadow_log WHERE id=?", (row_id,),
        ).fetchone()
    return dict(row) if row else None


def list_recent(
    *,
    method:        Optional[str] = None,
    diff_outcome:  Optional[str] = None,
    limit:         int = 200,
) -> List[Dict[str, Any]]:
    """Most-recent rows first. Optional filters on method / diff_outcome."""
    where: List[str] = []
    params: List[Any] = []
    if method:
        where.append("method = ?")
        params.append(method)
    if diff_outcome:
        where.append("diff_outcome = ?")
        params.append(diff_outcome)
    sql = "SELECT * FROM carrier_shadow_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with _connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def summarise_last_n_days(days: int = 7) -> List[Dict[str, Any]]:
    """Counts grouped by ``(method, diff_outcome)`` for the last N days.

    Returns a list of dicts ``{method, diff_outcome, count}`` sorted
    by ``count`` descending. Useful for the future operator dashboard
    panel, which DL-F2 does NOT mount yet.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=int(days))
    ).isoformat()
    with _connect() as con:
        rows = con.execute(
            """SELECT method, diff_outcome, COUNT(*) AS n
                 FROM carrier_shadow_log
                WHERE created_at >= ?
             GROUP BY method, diff_outcome
             ORDER BY n DESC""",
            (cutoff,),
        ).fetchall()
    return [
        {"method": r["method"], "diff_outcome": r["diff_outcome"],
         "count":  r["n"]}
        for r in rows
    ]


def count_total() -> int:
    """Total number of shadow-log rows. Cheap; used by tests."""
    with _connect() as con:
        return int(con.execute(
            "SELECT COUNT(*) FROM carrier_shadow_log"
        ).fetchone()[0])

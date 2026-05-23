"""
ai_call_ledger.py — Append-only SQLite ledger for every external AI call.

Written by ai_gateway.py after every call attempt (success or failure).
No raw prompt text is stored — only prompt_hash (SHA-256 of redacted prompt).

Schema version: 1
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_LOCK = threading.Lock()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS ai_calls (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT    NOT NULL,
    service                 TEXT    NOT NULL,
    object_id               TEXT,
    task_type               TEXT    NOT NULL,
    requested_model         TEXT,
    selected_model          TEXT    NOT NULL,
    model_tier              TEXT    NOT NULL,
    selection_reason        TEXT,
    escalation_reason       TEXT,
    confidence_score        REAL,
    prompt_hash             TEXT    NOT NULL,
    estimated_input_tokens  INTEGER,
    estimated_output_tokens INTEGER,
    estimated_cost          REAL,
    actual_input_tokens     INTEGER,
    actual_output_tokens    INTEGER,
    actual_cost             REAL,
    latency_ms              INTEGER,
    success                 INTEGER NOT NULL,
    fallback_reason         TEXT,
    error_type              TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_calls_timestamp ON ai_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_ai_calls_service   ON ai_calls(service);
"""

# Approximate USD cost per 1k tokens (MTok pricing as of 2026-05-23)
# Used for pre-call estimates; actual cost recorded post-call when available.
_COST_PER_1K: Dict[str, Dict[str, float]] = {
    "claude-haiku-4-5-20251001":  {"in": 0.00025, "out": 0.00125},
    "claude-sonnet-4-6":          {"in": 0.003,   "out": 0.015},
    "claude-opus-4-7":            {"in": 0.015,   "out": 0.075},
}
_COST_FALLBACK = {"in": 0.003, "out": 0.015}  # sonnet-tier default


def _db_path() -> Path:
    try:
        from ..core.config import settings  # noqa: PLC0415
        return Path(settings.storage_root) / "ai_call_ledger.db"
    except Exception:
        return Path(__file__).parent.parent / "storage" / "ai_call_ledger.db"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_CREATE_SQL)
    conn.commit()


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return max(1, len(text) // 4)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_1K.get(model, _COST_FALLBACK)
    return round(
        rates["in"]  * input_tokens  / 1000
        + rates["out"] * output_tokens / 1000,
        6,
    )


def prompt_hash(system: str, user: str) -> str:
    """SHA-256 of the concatenated redacted prompts. Never stores raw text."""
    digest = hashlib.sha256((system + "\n\n" + user).encode("utf-8", errors="replace"))
    return digest.hexdigest()


def record(entry: Dict[str, Any]) -> None:
    """Append one ledger row. Never raises — failures are logged only."""
    try:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            conn = sqlite3.connect(str(path), timeout=5)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                _ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO ai_calls (
                        timestamp, service, object_id, task_type,
                        requested_model, selected_model, model_tier,
                        selection_reason, escalation_reason, confidence_score,
                        prompt_hash,
                        estimated_input_tokens, estimated_output_tokens, estimated_cost,
                        actual_input_tokens, actual_output_tokens, actual_cost,
                        latency_ms, success, fallback_reason, error_type
                    ) VALUES (
                        :timestamp, :service, :object_id, :task_type,
                        :requested_model, :selected_model, :model_tier,
                        :selection_reason, :escalation_reason, :confidence_score,
                        :prompt_hash,
                        :estimated_input_tokens, :estimated_output_tokens, :estimated_cost,
                        :actual_input_tokens, :actual_output_tokens, :actual_cost,
                        :latency_ms, :success, :fallback_reason, :error_type
                    )
                    """,
                    {
                        "timestamp":               entry.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                        "service":                 entry.get("service", "unknown"),
                        "object_id":               entry.get("object_id"),
                        "task_type":               entry.get("task_type", "unknown"),
                        "requested_model":         entry.get("requested_model"),
                        "selected_model":          entry.get("selected_model", "unknown"),
                        "model_tier":              entry.get("model_tier", "unknown"),
                        "selection_reason":        entry.get("selection_reason"),
                        "escalation_reason":       entry.get("escalation_reason"),
                        "confidence_score":        entry.get("confidence_score"),
                        "prompt_hash":             entry.get("prompt_hash", ""),
                        "estimated_input_tokens":  entry.get("estimated_input_tokens"),
                        "estimated_output_tokens": entry.get("estimated_output_tokens"),
                        "estimated_cost":          entry.get("estimated_cost"),
                        "actual_input_tokens":     entry.get("actual_input_tokens"),
                        "actual_output_tokens":    entry.get("actual_output_tokens"),
                        "actual_cost":             entry.get("actual_cost"),
                        "latency_ms":              entry.get("latency_ms"),
                        "success":                 1 if entry.get("success") else 0,
                        "fallback_reason":         entry.get("fallback_reason"),
                        "error_type":              entry.get("error_type"),
                    },
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:
        log.error("[ai_ledger] write failed: %s", exc)


def get_daily_cost_usd(date_prefix: Optional[str] = None) -> float:
    """Return total actual_cost (or estimated_cost as fallback) for a UTC date.

    date_prefix defaults to today UTC, e.g. '2026-05-23'.
    Returns 0.0 if ledger does not exist yet.
    """
    if date_prefix is None:
        date_prefix = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        path = _db_path()
        if not path.exists():
            return 0.0
        with _LOCK:
            conn = sqlite3.connect(str(path), timeout=5)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                _ensure_schema(conn)
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(actual_cost, estimated_cost, 0)), 0)
                    FROM ai_calls
                    WHERE timestamp LIKE ? AND success = 1
                    """,
                    (f"{date_prefix}%",),
                ).fetchone()
                return float(row[0]) if row else 0.0
            finally:
                conn.close()
    except Exception as exc:
        log.error("[ai_ledger] daily cost query failed: %s", exc)
        return 0.0

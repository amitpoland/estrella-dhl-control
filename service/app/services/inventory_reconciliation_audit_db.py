"""
inventory_reconciliation_audit_db.py — WF-2 reconciliation-run audit store.

This owns ``inventory_reconciliation.db`` (one file per domain). It records the
METADATA of every fiscal-reconciliation run — timestamp, warehouse filter,
duration, objects checked, and difference counts by type/severity — so an
operator can answer the four status questions (running? last run? what happened?
run now?) and see reconciliation history.

SCOPE / SAFETY: this is the ONLY table WF-2 writes to, and it stores run
metadata ONLY. It NEVER holds business data and NEVER writes to inventory_state,
wFirma goods, Product Master, Customer Master, accounting, invoices, or
reservations. Recording an audit run does not modify either reconciled system.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id                 TEXT PRIMARY KEY,
    run_at             TEXT NOT NULL,
    warehouse_filter   TEXT NOT NULL DEFAULT '',
    fiscal_source      TEXT NOT NULL DEFAULT '',
    duration_ms        INTEGER NOT NULL DEFAULT 0,
    objects_checked    INTEGER NOT NULL DEFAULT 0,
    matching           INTEGER NOT NULL DEFAULT 0,
    mismatched         INTEGER NOT NULL DEFAULT 0,
    missing_dashboard  INTEGER NOT NULL DEFAULT 0,
    missing_wfirma     INTEGER NOT NULL DEFAULT 0,
    unknown_mappings   INTEGER NOT NULL DEFAULT 0,
    differences_total  INTEGER NOT NULL DEFAULT 0,
    by_severity_json   TEXT NOT NULL DEFAULT '{}',
    by_type_json       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_recon_runs_at
    ON reconciliation_runs (run_at);
"""

_COLUMNS = (
    "id", "run_at", "warehouse_filter", "fiscal_source", "duration_ms",
    "objects_checked", "matching", "mismatched", "missing_dashboard",
    "missing_wfirma", "unknown_mappings", "differences_total",
    "by_severity_json", "by_type_json",
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_run(db_path: Path, run: Dict[str, Any]) -> str:
    """Insert one reconciliation-run record. Returns the generated run id.

    ``run`` may carry any subset of the metadata fields; missing fields default
    to 0 / '' / {}. ``by_severity``/``by_type`` dicts are JSON-serialised.
    """
    init_db(db_path)
    run_id = str(uuid.uuid4())
    row = {
        "id": run_id,
        "run_at": run.get("run_at") or _now_iso(),
        "warehouse_filter": str(run.get("warehouse_filter") or ""),
        "fiscal_source": str(run.get("fiscal_source") or ""),
        "duration_ms": int(run.get("duration_ms") or 0),
        "objects_checked": int(run.get("objects_checked") or 0),
        "matching": int(run.get("matching") or 0),
        "mismatched": int(run.get("mismatched") or 0),
        "missing_dashboard": int(run.get("missing_dashboard") or 0),
        "missing_wfirma": int(run.get("missing_wfirma") or 0),
        "unknown_mappings": int(run.get("unknown_mappings") or 0),
        "differences_total": int(run.get("differences_total") or 0),
        "by_severity_json": json.dumps(run.get("by_severity") or {}, ensure_ascii=False),
        "by_type_json": json.dumps(run.get("by_type") or {}, ensure_ascii=False),
    }
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO reconciliation_runs ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
            tuple(row[c] for c in _COLUMNS),
        )
    return run_id


def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    d["by_severity"] = json.loads(d.pop("by_severity_json", "{}") or "{}")
    d["by_type"] = json.loads(d.pop("by_type_json", "{}") or "{}")
    return d


def get_last_run(db_path: Path) -> Optional[Dict[str, Any]]:
    p = Path(db_path)
    if not p.exists():
        return None
    with _connect(p) as conn:
        try:
            r = conn.execute(
                "SELECT * FROM reconciliation_runs ORDER BY run_at DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_dict(r) if r else None


def list_runs(db_path: Path, limit: int = 50) -> List[Dict[str, Any]]:
    p = Path(db_path)
    if not p.exists():
        return []
    with _connect(p) as conn:
        try:
            rows = conn.execute(
                "SELECT * FROM reconciliation_runs ORDER BY run_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_row_to_dict(r) for r in rows]

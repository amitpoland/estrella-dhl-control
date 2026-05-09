"""
correction_registry.py — Operator-approved correction memory layer.

Purpose
-------
Persist every operator-driven correction or override so that downstream
recommendation / confidence / explainability layers can be added on top
WITHOUT introducing automation. This module is strictly an append-only
read/write registry. It NEVER:
  • mutates wFirma master data
  • mutates audit.json, packing, warehouse, document or reservation DBs
  • triggers SMTP / DHL / PZ / Proforma flows
  • runs observers, schedulers, or background tasks
  • overwrites or deletes prior history

The registry is consulted as a hint source. Any future "auto-suggest"
must still surface its provenance via `explain_for(...)` so an operator
can see exactly which historical decisions back the suggestion.

Storage
-------
  storage_root/correction_registry.db  (SQLite, WAL)

Tables
------
  corrections          append-only history of every operator action

Schema rationale
----------------
- No UNIQUE constraint over (correction_type, entity_key) — multiple
  rows per key are intentional (history).
- `approved=0` (rejected_match) rows are retained for confidence math.
- `evidence_refs` is a JSON array of {type,ref} pointers (audit, email,
  shipment, document) so explainability stays linkable without copying
  the underlying records.
- Every helper accepts a quiet path when `_db_path` is None so the
  caller never has to guard against missing init.

Supported correction_type values
--------------------------------
  customer_resolution_override   — operator chose customer X for client_name Y
  vat_override                   — operator set/changed VAT id for a customer
  product_mapping_override       — product_code → wFirma product_id assignment
  ambiguity_resolution           — operator picked one of several candidates
  unit_override                  — unit (szt./kpl./para) corrected
  wording_override               — Polish description / line wording change
  warehouse_override             — warehouse_id assignment correction
  contractor_alias               — alternate name → canonical customer
  rejected_match                 — operator rejected a system-suggested match
  accepted_match                 — operator confirmed a system-suggested match
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.logging import get_logger

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None


SUPPORTED_TYPES = frozenset({
    "customer_resolution_override",
    "vat_override",
    "product_mapping_override",
    "ambiguity_resolution",
    "unit_override",
    "wording_override",
    "warehouse_override",
    "contractor_alias",
    "rejected_match",
    "accepted_match",
})


# ── Init ──────────────────────────────────────────────────────────────────────

def init_correction_registry(db_path: Path) -> None:
    """
    Initialise the SQLite file (idempotent). Creates the append-only
    corrections table and supporting indexes.
    """
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS corrections (
                id                TEXT PRIMARY KEY,
                correction_type   TEXT NOT NULL,
                entity_type       TEXT NOT NULL DEFAULT '',
                entity_key        TEXT NOT NULL DEFAULT '',
                old_value         TEXT NOT NULL DEFAULT '',
                new_value         TEXT NOT NULL DEFAULT '',
                shipment_id       TEXT NOT NULL DEFAULT '',
                batch_id          TEXT NOT NULL DEFAULT '',
                operator          TEXT NOT NULL DEFAULT '',
                module_source     TEXT NOT NULL DEFAULT '',
                confidence        REAL NOT NULL DEFAULT 0.0,
                notes             TEXT NOT NULL DEFAULT '',
                approved          INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL,
                evidence_refs     TEXT NOT NULL DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS idx_corr_lookup
                ON corrections (correction_type, entity_key, created_at);
            CREATE INDEX IF NOT EXISTS idx_corr_shipment
                ON corrections (shipment_id);
            CREATE INDEX IF NOT EXISTS idx_corr_batch
                ON corrections (batch_id);
            CREATE INDEX IF NOT EXISTS idx_corr_approved
                ON corrections (correction_type, entity_key, approved);
            CREATE INDEX IF NOT EXISTS idx_corr_operator
                ON corrections (operator, created_at);
        """)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("correction_registry not initialised")
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Append-only writer ───────────────────────────────────────────────────────

def record_correction(
    *,
    correction_type: str,
    entity_type:     str = "",
    entity_key:      str = "",
    old_value:       Any = "",
    new_value:       Any = "",
    shipment_id:     str = "",
    batch_id:        str = "",
    operator:        str = "",
    module_source:   str = "",
    confidence:      float = 0.0,
    notes:           str = "",
    approved:        bool = True,
    evidence_refs:   Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Append one correction record. Returns the new row id.

    This is the ONLY write path. It is intentionally narrow and never
    updates or deletes prior rows. A "rejected match" or "operator
    changed their mind later" both produce *new* rows.

    `confidence` is the operator-stated confidence in the correction
    (0.0–1.0). The future confidence engine derives a separate score
    by aggregating over many rows — this column is the per-record
    confidence the operator chose to attach.
    """
    if _db_path is None:
        return ""
    if correction_type not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported correction_type: {correction_type!r}")
    if not isinstance(approved, bool):
        raise ValueError("approved must be bool")

    rid = str(uuid.uuid4())
    payload_old = old_value if isinstance(old_value, str) else json.dumps(old_value, default=str)
    payload_new = new_value if isinstance(new_value, str) else json.dumps(new_value, default=str)
    refs_json   = json.dumps(evidence_refs or [], default=str)
    try:
        c = max(0.0, min(1.0, float(confidence)))
    except Exception:
        c = 0.0

    with _lock, _connect() as con:
        con.execute(
            """
            INSERT INTO corrections
                (id, correction_type, entity_type, entity_key,
                 old_value, new_value, shipment_id, batch_id,
                 operator, module_source, confidence, notes,
                 approved, created_at, evidence_refs)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid, correction_type, entity_type, entity_key,
                payload_old, payload_new, shipment_id, batch_id,
                operator, module_source, c, notes,
                1 if approved else 0, _now(), refs_json,
            ),
        )
        con.commit()
    log.info(
        "correction_registry: appended %s entity_key=%s approved=%s by=%s",
        correction_type, entity_key, approved, operator or "?",
    )
    return rid


# ── Row helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    try:
        d["evidence_refs"] = json.loads(d.get("evidence_refs") or "[]")
    except Exception:
        d["evidence_refs"] = []
    d["approved"] = bool(d.get("approved", 0))
    return d


# ── Read-only retrieval API ──────────────────────────────────────────────────

def list_corrections(
    *,
    correction_type: Optional[str] = None,
    entity_key:      Optional[str] = None,
    shipment_id:     Optional[str] = None,
    batch_id:        Optional[str] = None,
    approved:        Optional[bool] = None,
    operator:        Optional[str] = None,
    limit:           int = 200,
) -> List[Dict[str, Any]]:
    """
    Return matching rows ordered most-recent-first. All filters are
    optional. Always returns a list.
    """
    if _db_path is None:
        return []
    where: List[str] = []
    args:  List[Any] = []
    if correction_type:
        where.append("correction_type = ?")
        args.append(correction_type)
    if entity_key:
        where.append("entity_key = ?")
        args.append(entity_key)
    if shipment_id:
        where.append("shipment_id = ?")
        args.append(shipment_id)
    if batch_id:
        where.append("batch_id = ?")
        args.append(batch_id)
    if approved is not None:
        where.append("approved = ?")
        args.append(1 if approved else 0)
    if operator:
        where.append("operator = ?")
        args.append(operator)
    sql = "SELECT * FROM corrections"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(max(1, min(limit, 5000))))
    with _connect() as con:
        rows = con.execute(sql, tuple(args)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_last_accepted(correction_type: str, entity_key: str) -> Optional[Dict[str, Any]]:
    """
    Most recent approved row for (correction_type, entity_key), or None.
    Suggestion engines should treat this as a *hint*, not a directive.
    """
    if _db_path is None or not correction_type or not entity_key:
        return None
    with _connect() as con:
        row = con.execute(
            """
            SELECT * FROM corrections
             WHERE correction_type = ?
               AND entity_key      = ?
               AND approved        = 1
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (correction_type, entity_key),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_rejected(correction_type: str, entity_key: str,
                 limit: int = 20) -> List[Dict[str, Any]]:
    """All rejected rows (approved=0) for the given key, newest first."""
    if _db_path is None or not correction_type or not entity_key:
        return []
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM corrections
             WHERE correction_type = ?
               AND entity_key      = ?
               AND approved        = 0
             ORDER BY created_at DESC
             LIMIT ?
            """,
            (correction_type, entity_key, int(max(1, min(limit, 200)))),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_frequency(correction_type: str, entity_key: str) -> Dict[str, Any]:
    """
    Aggregate counts for one key:
      { accepted, rejected, total, last_accepted_at, last_rejected_at,
        accept_ratio, distinct_new_values, top_new_value }
    """
    out = {
        "accepted":            0,
        "rejected":            0,
        "total":               0,
        "last_accepted_at":    None,
        "last_rejected_at":    None,
        "accept_ratio":        0.0,
        "distinct_new_values": 0,
        "top_new_value":       None,
        "top_new_value_count": 0,
    }
    if _db_path is None or not correction_type or not entity_key:
        return out
    with _connect() as con:
        rows = con.execute(
            "SELECT new_value, approved, created_at FROM corrections "
            "WHERE correction_type = ? AND entity_key = ?",
            (correction_type, entity_key),
        ).fetchall()
    if not rows:
        return out
    accepted_at: List[str] = []
    rejected_at: List[str] = []
    accepted_vals: Counter = Counter()
    for r in rows:
        if r["approved"]:
            out["accepted"] += 1
            accepted_at.append(r["created_at"])
            if r["new_value"]:
                accepted_vals[r["new_value"]] += 1
        else:
            out["rejected"] += 1
            rejected_at.append(r["created_at"])
    out["total"]               = out["accepted"] + out["rejected"]
    out["last_accepted_at"]    = max(accepted_at) if accepted_at else None
    out["last_rejected_at"]    = max(rejected_at) if rejected_at else None
    out["accept_ratio"]        = (out["accepted"] / out["total"]) if out["total"] else 0.0
    out["distinct_new_values"] = len(accepted_vals)
    if accepted_vals:
        top, cnt = accepted_vals.most_common(1)[0]
        out["top_new_value"]       = top
        out["top_new_value_count"] = cnt
    return out


def confidence_score(correction_type: str, entity_key: str) -> Dict[str, Any]:
    """
    Aggregate a single confidence number per key. Conservative formula:

        score = accept_ratio * stability * volume_factor

    where:
      • accept_ratio    = accepted / (accepted + rejected)
      • stability       = top_new_value_count / accepted   (1.0 if all
                          past accepted rows agree on the new value)
      • volume_factor   = min(1.0, accepted / 3)           (caps at 3)

    The score is intentionally bounded in [0,1]. This is a HINT for
    UI ranking only — the engine never auto-applies based on it.
    """
    f = get_frequency(correction_type, entity_key)
    accepted = f["accepted"]
    if accepted == 0:
        return {**f, "score": 0.0, "stability": 0.0, "volume_factor": 0.0}
    stability     = (f["top_new_value_count"] / accepted) if accepted else 0.0
    volume_factor = min(1.0, accepted / 3.0)
    score = f["accept_ratio"] * stability * volume_factor
    return {
        **f,
        "stability":     round(stability, 4),
        "volume_factor": round(volume_factor, 4),
        "score":         round(score, 4),
    }


def explain_for(correction_type: str, entity_key: str,
                limit: int = 25) -> Dict[str, Any]:
    """
    Return a structured explanation envelope for ONE (type, key) pair.
    A future suggestion surface MUST attach this envelope so the
    operator can see why a value was prefilled.

      {
        "correction_type":     str,
        "entity_key":          str,
        "last_accepted":       row or None,
        "rejected_examples":   [row, …],
        "frequency":           {…},
        "confidence":          {…},
        "history":             [row, …]   (chronological, newest first)
      }

    The envelope contains only registry rows — no inferences, no
    speculative content, no synthetic confidence boosts.
    """
    return {
        "correction_type":   correction_type,
        "entity_key":        entity_key,
        "last_accepted":     get_last_accepted(correction_type, entity_key),
        "rejected_examples": get_rejected(correction_type, entity_key, limit=10),
        "frequency":         get_frequency(correction_type, entity_key),
        "confidence":        confidence_score(correction_type, entity_key),
        "history":           list_corrections(
                                 correction_type=correction_type,
                                 entity_key=entity_key,
                                 limit=limit),
    }


def stats_overview() -> Dict[str, Any]:
    """
    Cheap rollup for dashboard/reporting:
      • total rows
      • per-correction_type counts (accepted vs rejected)
      • distinct operators
      • newest entry timestamp
    Read-only.
    """
    out = {
        "total":             0,
        "by_type":           {},
        "distinct_operators": 0,
        "last_recorded_at":  None,
    }
    if _db_path is None:
        return out
    with _connect() as con:
        out["total"] = con.execute(
            "SELECT COUNT(*) FROM corrections"
        ).fetchone()[0]
        for r in con.execute(
            "SELECT correction_type, approved, COUNT(*) AS c "
            "FROM corrections GROUP BY correction_type, approved"
        ).fetchall():
            t = r["correction_type"]
            d = out["by_type"].setdefault(t, {"accepted": 0, "rejected": 0})
            if r["approved"]:
                d["accepted"] += int(r["c"])
            else:
                d["rejected"] += int(r["c"])
        out["distinct_operators"] = con.execute(
            "SELECT COUNT(DISTINCT operator) FROM corrections "
            "WHERE operator <> ''"
        ).fetchone()[0]
        row = con.execute(
            "SELECT MAX(created_at) AS m FROM corrections"
        ).fetchone()
        out["last_recorded_at"] = row["m"] if row else None
    return out

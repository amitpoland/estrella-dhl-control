"""commercial_charge_record_db.py — durable charge record of ISSUED documents.

The CommercialChargeAuthority (``commercial_charge_authority``) is a pure
resolver: it interprets a list of charges, it does not store them. Until now
its only ingestion source was a proforma draft's ``service_charges_json`` —
which is **pre-issue intent**, written before the fiscal document exists.

Measured 2026-08-16 across all 764 issued wFirma sales documents
(``reports/inspection/2026-08-16-insurance-recovered-authority-census.md``):

  * 512 documents bill insurance and have no draft at all — the authority
    holds nothing for six years of history;
  * 2 of the 14 linked documents diverge from their draft snapshot, in both
    directions (WDT 146/2026 bills a premium the snapshot lacks; WDT 155/2026
    has a snapshot premium of 362.39 USD that the issued document never bills).

This module is the authority's durable record of what an issued fiscal
document **actually billed**. It is not a second authority: the rows it stores
are resolved by the same ``resolve_commercial_charges`` under the same
resolution vocabulary (``RESOLUTION_INVOICED``). Nothing here interprets,
recomputes, or sums an amount.

Write discipline (operator-ratified, 2026-08-16):
  * The issued fiscal document is never mutated. The draft snapshot is never
    mutated. This store is append/repair-only and local.
  * Re-capturing an identical amount + currency is a no-op — convergence is
    idempotent by construction.
  * A re-capture that CONTRADICTS a stored amount or currency never
    overwrites: the row keeps its stored value and is marked
    ``needs_manual_review`` with both values in the note.

Storage: ``<storage_root>/commercial_charges.db`` (this module owns the file).
"""
from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from .commercial_charge_authority import RESOLUTION_INVOICED

#: Charge types captured from an issued document. Same vocabulary as the
#: authority — nothing else is stored.
CHARGE_TYPES = ("freight", "insurance")

#: Set on a row whose stored value is contradicted by a later capture.
CONFLICT_NEEDS_REVIEW = "needs_manual_review"

_DDL = """
CREATE TABLE IF NOT EXISTS issued_document_charge (
    wfirma_invoice_id TEXT NOT NULL,
    charge_type       TEXT NOT NULL,
    amount            TEXT NOT NULL,
    currency          TEXT NOT NULL,
    resolution        TEXT NOT NULL,
    good_id           TEXT NOT NULL DEFAULT '',
    document_number   TEXT NOT NULL DEFAULT '',
    document_date     TEXT NOT NULL DEFAULT '',
    document_type     TEXT NOT NULL DEFAULT '',
    captured_at       TEXT NOT NULL,
    conflict_state    TEXT NOT NULL DEFAULT '',
    conflict_note     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (wfirma_invoice_id, charge_type)
)
"""

#: Single-row observability for the convergence capability (requirement 5 of the
#: Business Feature Completeness Standard). Only APPLY runs are recorded — a dry
#: run must not make the next scheduled run look satisfied.
_RUN_DDL = """
CREATE TABLE IF NOT EXISTS convergence_run (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    window_from       TEXT NOT NULL DEFAULT '',
    window_to         TEXT NOT NULL DEFAULT '',
    operator          TEXT NOT NULL DEFAULT '',
    last_started_at   TEXT NOT NULL DEFAULT '',
    last_completed_at TEXT NOT NULL DEFAULT '',
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    processed         INTEGER NOT NULL DEFAULT 0,
    created           INTEGER NOT NULL DEFAULT 0,
    updated           INTEGER NOT NULL DEFAULT 0,
    skipped           INTEGER NOT NULL DEFAULT 0,
    conflicts         INTEGER NOT NULL DEFAULT 0,
    unattributed      INTEGER NOT NULL DEFAULT 0,
    errors            INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT NOT NULL DEFAULT ''
)
"""


def db_path() -> Path:
    return Path(settings.storage_root) / "commercial_charges.db"


@contextlib.contextmanager
def _connect(path: Optional[Path] = None):
    p = Path(path) if path is not None else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(_DDL)
        conn.execute(_RUN_DDL)
        yield conn
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _same_amount(a: Any, b: Any) -> bool:
    da, db = _dec(a), _dec(b)
    return da is not None and db is not None and da == db


# ── Read ─────────────────────────────────────────────────────────────────────


def get_document_charges(
    invoice_id: str, path: Optional[Path] = None
) -> Optional[List[Dict[str, Any]]]:
    """Charges captured from the issued document, shaped for the authority.

    Returns ``None`` when the document has never been converged — which is a
    different fact from "the document billed no insurance" (an empty premium
    is stored as an explicit 0.00 row). Consumers must keep them distinct.
    """
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT charge_type, amount, currency, resolution, conflict_state "
            "FROM issued_document_charge WHERE wfirma_invoice_id = ?",
            (str(invoice_id),),
        ).fetchall()
    if not rows:
        return None
    return [
        {
            "charge_type": r["charge_type"],
            "amount": r["amount"],
            "currency": r["currency"],
            "resolution": r["resolution"],
            "conflict_state": r["conflict_state"],
        }
        for r in rows
    ]


def list_conflicts(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM issued_document_charge WHERE conflict_state <> '' "
            "ORDER BY document_date, document_number, charge_type"
        ).fetchall()
    return [dict(r) for r in rows]


def count_documents(path: Optional[Path] = None) -> int:
    with _connect(path) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(DISTINCT wfirma_invoice_id) FROM issued_document_charge"
            ).fetchone()[0]
        )


# ── Write (the ONE writer) ───────────────────────────────────────────────────


def capture_document(
    document: Dict[str, Any],
    charges: Dict[str, Dict[str, Any]],
    path: Optional[Path] = None,
    apply: bool = True,
) -> Dict[str, Any]:
    """Capture one issued document's freight + insurance as billed.

    ``document`` carries ``invoice_id``/``number``/``date``/``type``/``currency``.
    ``charges`` maps charge_type → ``{"amount", "good_id"}``. Only the charge
    types PRESENT in that mapping are recorded — a caller that cannot attribute
    a charge type with certainty must omit it rather than assert a zero.
    Within the types it does pass, a type the document does not bill MUST be
    passed with amount 0, so that "converged, nothing billed" is recorded as a
    fact rather than left as an absence.

    Returns ``{"invoice_id", "actions": {charge_type: action}, "conflicts": [...]}``
    where action ∈ inserted / unchanged / conflict. With ``apply=False`` the
    same decisions are computed and nothing is written (dry-run).
    """
    invoice_id = str(document.get("invoice_id") or "").strip()
    if not invoice_id:
        raise ValueError("capture_document requires an invoice_id")
    currency = str(document.get("currency") or "").strip().upper()
    now = _utcnow()

    actions: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []

    with _connect(path) as conn:
        for ctype in CHARGE_TYPES:
            if ctype not in charges:
                continue
            incoming = charges.get(ctype) or {}
            amount = _dec(incoming.get("amount"))
            if amount is None:
                amount = Decimal("0")
            good_id = str(incoming.get("good_id") or "")

            existing = conn.execute(
                "SELECT * FROM issued_document_charge "
                "WHERE wfirma_invoice_id = ? AND charge_type = ?",
                (invoice_id, ctype),
            ).fetchone()

            if existing is None:
                actions[ctype] = "inserted"
                if apply:
                    conn.execute(
                        "INSERT INTO issued_document_charge ("
                        "wfirma_invoice_id, charge_type, amount, currency, resolution,"
                        " good_id, document_number, document_date, document_type,"
                        " captured_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            invoice_id,
                            ctype,
                            str(amount),
                            currency,
                            RESOLUTION_INVOICED,
                            good_id,
                            str(document.get("number") or ""),
                            str(document.get("date") or ""),
                            str(document.get("type") or ""),
                            now,
                        ),
                    )
                continue

            if _same_amount(existing["amount"], amount) and existing["currency"] == currency:
                actions[ctype] = "unchanged"
                continue

            # Contradiction: keep the stored value, never overwrite.
            note = (
                "stored %s %s contradicted by issued document %s %s at %s"
                % (existing["amount"], existing["currency"], amount, currency, now)
            )
            actions[ctype] = "conflict"
            conflicts.append(
                {
                    "invoice_id": invoice_id,
                    "document_number": existing["document_number"],
                    "charge_type": ctype,
                    "stored_amount": existing["amount"],
                    "stored_currency": existing["currency"],
                    "issued_amount": str(amount),
                    "issued_currency": currency,
                }
            )
            if apply:
                conn.execute(
                    "UPDATE issued_document_charge SET conflict_state = ?, conflict_note = ? "
                    "WHERE wfirma_invoice_id = ? AND charge_type = ?",
                    (CONFLICT_NEEDS_REVIEW, note, invoice_id, ctype),
                )
        if apply:
            conn.commit()

    return {"invoice_id": invoice_id, "actions": actions, "conflicts": conflicts}


# ── Run status (observability) ───────────────────────────────────────────────

_RUN_FIELDS = ("processed", "created", "updated", "skipped", "conflicts",
               "unattributed", "errors")


def mark_run_started(window_from: str, window_to: str, operator: str,
                     path: Optional[Path] = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO convergence_run (id, window_from, window_to, operator,"
            " last_started_at) VALUES (1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
            " window_from=excluded.window_from, window_to=excluded.window_to,"
            " operator=excluded.operator, last_started_at=excluded.last_started_at",
            (window_from, window_to, operator, _utcnow()),
        )
        conn.commit()


def mark_run_completed(summary: Dict[str, Any], path: Optional[Path] = None) -> None:
    values = [int(summary.get(f) or 0) for f in _RUN_FIELDS]
    with _connect(path) as conn:
        conn.execute(
            "UPDATE convergence_run SET last_completed_at=?, duration_ms=?,"
            " processed=?, created=?, updated=?, skipped=?, conflicts=?,"
            " unattributed=?, errors=?, last_error=? WHERE id = 1",
            [_utcnow(), int(summary.get("duration_ms") or 0)] + values
            + [str(summary.get("last_error") or "")],
        )
        conn.commit()


def get_run_status(path: Optional[Path] = None) -> Dict[str, Any]:
    """Canonical status shape. A capability that has never run is not an error."""
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM convergence_run WHERE id = 1").fetchone()
    if row is None:
        return {"running": False, "last_started_at": None, "last_completed_at": None,
                "window": None, "operator": None, "duration_ms": 0, "last_error": "",
                **{f: 0 for f in _RUN_FIELDS}}
    started, completed = row["last_started_at"], row["last_completed_at"]
    return {
        "running": bool(started and started > (completed or "")),
        "last_started_at": started or None,
        "last_completed_at": completed or None,
        "window": {"from": row["window_from"], "to": row["window_to"]},
        "operator": row["operator"] or None,
        "duration_ms": int(row["duration_ms"] or 0),
        "last_error": row["last_error"] or "",
        **{f: int(row[f] or 0) for f in _RUN_FIELDS},
    }


def is_run_due(cooldown_seconds: int, now: Optional[float] = None,
               path: Optional[Path] = None) -> bool:
    """Has the cooldown elapsed since the last APPLY run STARTED?

    Measured from the start, not the completion, so a run that died without
    completing unblocks after one cooldown instead of wedging the schedule
    forever — and a run still in flight is not due again, because its own start
    stamp is by definition recent.
    """
    status = get_run_status(path)
    started = status["last_started_at"]
    if not started:
        return True
    try:
        last = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return True
    current = now if now is not None else datetime.now(timezone.utc).timestamp()
    return (current - last) >= cooldown_seconds


__all__ = [
    "CHARGE_TYPES",
    "CONFLICT_NEEDS_REVIEW",
    "capture_document",
    "count_documents",
    "db_path",
    "get_document_charges",
    "get_run_status",
    "is_run_due",
    "list_conflicts",
    "mark_run_completed",
    "mark_run_started",
]

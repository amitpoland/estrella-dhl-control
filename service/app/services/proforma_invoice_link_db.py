"""
proforma_invoice_link_db.py — local link table between an approved proforma
and the final wFirma invoice we issue from it.

wFirma exposes NO native conversion endpoint and stores no parent/child
relationship between a proforma and its final invoice (probe results dated
2026-05-03 — see app/tools/probe_proforma_to_invoice_api.py). This table
is the only audit trace that connects them.

Pure CRUD. Pure SQLite. No wFirma I/O lives here.

Schema (locked):
    proforma_invoice_links
        id                 INTEGER PRIMARY KEY AUTOINCREMENT
        proforma_id        TEXT    NOT NULL  UNIQUE   wFirma id
        proforma_number    TEXT    NOT NULL           e.g. "PROF 90/2026"
        invoice_id         TEXT                       wFirma id of final invoice
        invoice_number     TEXT                       e.g. "FV 12/2026"
        converted_at       TEXT    NOT NULL           UTC ISO timestamp
        operator           TEXT    NOT NULL           who confirmed the live write
        source_total       TEXT    NOT NULL           proforma total at conversion
        invoice_total      TEXT                       final invoice total (set on success)
        currency           TEXT    NOT NULL
        status             TEXT    NOT NULL           pending | issued | failed | rolled_back
        notes              TEXT

The UNIQUE on proforma_id is the duplicate-conversion guard. Trying to
re-convert the same proforma will raise sqlite3.IntegrityError, which the
caller turns into a ProformaAlreadyConverted exception.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional


# ── Public types ──────────────────────────────────────────────────────────────

VALID_STATUSES = ("pending", "issued", "failed", "rolled_back")


@dataclass(frozen=True)
class ProformaInvoiceLink:
    """One row in proforma_invoice_links."""
    proforma_id:      str
    proforma_number:  str
    converted_at:     str               # ISO 8601 UTC
    operator:         str
    source_total:     Decimal
    currency:         str
    status:           str               # one of VALID_STATUSES
    invoice_id:       Optional[str]     = None
    invoice_number:   Optional[str]     = None
    invoice_total:    Optional[Decimal] = None
    notes:            Optional[str]     = None
    id:               Optional[int]     = None


class ProformaAlreadyConverted(Exception):
    """Raised when a caller tries to insert a second link for the same
    proforma_id. Carries the existing row for the operator to inspect."""

    def __init__(self, message: str, existing: ProformaInvoiceLink) -> None:
        super().__init__(message)
        self.existing = existing


# ── Validation ────────────────────────────────────────────────────────────────

def validate(link: ProformaInvoiceLink) -> List[str]:
    """Return a list of human-readable blockers; empty if OK."""
    blockers: List[str] = []
    if not (link.proforma_id or "").strip():
        blockers.append("proforma_id is required")
    if not (link.proforma_number or "").strip():
        blockers.append("proforma_number is required")
    if not (link.operator or "").strip():
        blockers.append("operator is required")
    if not (link.currency or "").strip():
        blockers.append("currency is required")
    if link.currency and link.currency not in ("PLN", "USD", "EUR"):
        blockers.append(f"currency must be PLN/USD/EUR, got {link.currency!r}")
    if link.status not in VALID_STATUSES:
        blockers.append(f"status must be one of {VALID_STATUSES}, got {link.status!r}")
    try:
        if Decimal(link.source_total) <= 0:
            blockers.append(f"source_total must be > 0, got {link.source_total}")
    except Exception:  # noqa: BLE001
        blockers.append(f"source_total is not a valid decimal: {link.source_total!r}")
    if link.invoice_total is not None:
        try:
            if Decimal(link.invoice_total) <= 0:
                blockers.append(f"invoice_total must be > 0 when set, got {link.invoice_total}")
        except Exception:  # noqa: BLE001
            blockers.append(f"invoice_total is not a valid decimal: {link.invoice_total!r}")
    # status=issued requires invoice_id + invoice_number + invoice_total
    if link.status == "issued":
        if not (link.invoice_id or "").strip():
            blockers.append("status=issued requires invoice_id")
        if not (link.invoice_number or "").strip():
            blockers.append("status=issued requires invoice_number")
        if link.invoice_total is None:
            blockers.append("status=issued requires invoice_total")
    return blockers


# ── DB lifecycle ─────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create the table if missing. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proforma_invoice_links (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                proforma_id     TEXT NOT NULL UNIQUE,
                proforma_number TEXT NOT NULL,
                invoice_id      TEXT,
                invoice_number  TEXT,
                converted_at    TEXT NOT NULL,
                operator        TEXT NOT NULL,
                source_total    TEXT NOT NULL,
                invoice_total   TEXT,
                currency        TEXT NOT NULL,
                status          TEXT NOT NULL,
                notes           TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pil_status ON proforma_invoice_links(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pil_invoice_id ON proforma_invoice_links(invoice_id)")
        conn.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_link(row: sqlite3.Row) -> ProformaInvoiceLink:
    return ProformaInvoiceLink(
        id              = row["id"],
        proforma_id     = row["proforma_id"],
        proforma_number = row["proforma_number"],
        invoice_id      = row["invoice_id"],
        invoice_number  = row["invoice_number"],
        converted_at    = row["converted_at"],
        operator        = row["operator"],
        source_total    = Decimal(row["source_total"]),
        invoice_total   = Decimal(row["invoice_total"]) if row["invoice_total"] else None,
        currency        = row["currency"],
        status          = row["status"],
        notes           = row["notes"],
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_pending_link(db_path: Path, link: ProformaInvoiceLink) -> int:
    """Insert a NEW link in 'pending' state. Raises ProformaAlreadyConverted
    if a row already exists for this proforma_id.

    Returns the new row id.
    """
    init_db(db_path)
    blockers = validate(link)
    if blockers:
        raise ValueError(f"link validation failed: {'; '.join(blockers)}")

    if not link.converted_at:
        link = replace(link, converted_at=_now_utc_iso())

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                INSERT INTO proforma_invoice_links
                    (proforma_id, proforma_number, invoice_id, invoice_number,
                     converted_at, operator, source_total, invoice_total,
                     currency, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.proforma_id,
                    link.proforma_number,
                    link.invoice_id,
                    link.invoice_number,
                    link.converted_at,
                    link.operator,
                    str(link.source_total),
                    str(link.invoice_total) if link.invoice_total is not None else None,
                    link.currency,
                    link.status,
                    link.notes,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            existing = get_link_by_proforma(db_path, link.proforma_id)
            raise ProformaAlreadyConverted(
                f"proforma_id={link.proforma_id} already has a link "
                f"(status={existing.status if existing else 'unknown'})",
                existing=existing,
            ) from exc


def mark_issued(db_path: Path,
                proforma_id: str,
                *,
                invoice_id: str,
                invoice_number: str,
                invoice_total: Decimal,
                notes: Optional[str] = None) -> None:
    """Promote a pending link to issued, recording the wFirma final invoice id."""
    if not invoice_id or not invoice_number:
        raise ValueError("invoice_id and invoice_number are required to mark issued")
    if Decimal(invoice_total) <= 0:
        raise ValueError(f"invoice_total must be > 0, got {invoice_total}")
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """
            UPDATE proforma_invoice_links
               SET invoice_id    = ?,
                   invoice_number= ?,
                   invoice_total = ?,
                   status        = 'issued',
                   notes         = COALESCE(?, notes)
             WHERE proforma_id   = ?
            """,
            (str(invoice_id), str(invoice_number), str(invoice_total),
             notes, str(proforma_id)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no link row for proforma_id={proforma_id!r}")


def mark_failed(db_path: Path, proforma_id: str, *, notes: str) -> None:
    """Promote a pending link to failed (e.g. wFirma rejected the add)."""
    if not (notes or "").strip():
        raise ValueError("notes is required when marking failed")
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """
            UPDATE proforma_invoice_links
               SET status = 'failed',
                   notes  = ?
             WHERE proforma_id = ?
            """,
            (notes, str(proforma_id)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no link row for proforma_id={proforma_id!r}")


def get_link_by_proforma(db_path: Path, proforma_id: str) -> Optional[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM proforma_invoice_links WHERE proforma_id = ? LIMIT 1",
            (str(proforma_id),),
        )
        row = cur.fetchone()
        return _row_to_link(row) if row else None


def get_link_by_invoice(db_path: Path, invoice_id: str) -> Optional[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM proforma_invoice_links WHERE invoice_id = ? LIMIT 1",
            (str(invoice_id),),
        )
        row = cur.fetchone()
        return _row_to_link(row) if row else None


def list_links(db_path: Path,
               *,
               status: Optional[str] = None,
               limit:  int = 100) -> List[ProformaInvoiceLink]:
    if not Path(db_path).exists():
        return []
    where = ""
    args: List = []
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")
        where = "WHERE status = ?"
        args.append(status)
    args.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f"SELECT * FROM proforma_invoice_links {where} ORDER BY id DESC LIMIT ?",
            tuple(args),
        )
        return [_row_to_link(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Proforma drafts — pre-create staging keyed by (batch_id, client_name)
# ─────────────────────────────────────────────────────────────────────────────
# `proforma_invoice_links` (above) is keyed by the WFIRMA proforma_id and is
# only useful AFTER a proforma exists in wFirma. The drafts table below
# captures the BEFORE state: a local idempotency record built from the
# read-only preview, before any live wFirma call. Once a live call succeeds
# (in a future task) the matching drafts row is promoted to status='issued'
# with `wfirma_proforma_id` populated, and a parallel `proforma_invoice_links`
# row is created for the eventual final-invoice conversion.

DRAFT_STATUSES = ("pending_local", "issued", "failed")


@dataclass(frozen=True)
class ProformaDraft:
    """One row in proforma_drafts."""
    batch_id:           str
    client_name:        str
    status:             str            # one of DRAFT_STATUSES
    currency:           str            = ""
    exchange_rate:      Optional[float] = None
    source_lines_json:  str            = "[]"
    wfirma_proforma_id: Optional[str]  = None
    notes:              Optional[str]  = None
    created_at:         Optional[str]  = None
    updated_at:         Optional[str]  = None
    id:                 Optional[int]  = None


def _ensure_drafts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_drafts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id            TEXT NOT NULL,
            client_name         TEXT NOT NULL,
            status              TEXT NOT NULL,
            currency            TEXT NOT NULL DEFAULT '',
            exchange_rate       REAL,
            source_lines_json   TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id  TEXT,
            notes               TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            UNIQUE(batch_id, client_name)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pd_status ON proforma_drafts(status)"
    )


def _row_to_draft(row: sqlite3.Row) -> ProformaDraft:
    return ProformaDraft(
        id                 = row["id"],
        batch_id           = row["batch_id"],
        client_name        = row["client_name"],
        status             = row["status"],
        currency           = row["currency"] or "",
        exchange_rate      = row["exchange_rate"],
        source_lines_json  = row["source_lines_json"] or "[]",
        wfirma_proforma_id = row["wfirma_proforma_id"],
        notes              = row["notes"],
        created_at         = row["created_at"],
        updated_at         = row["updated_at"],
    )


def get_draft(
    db_path:     Path,
    batch_id:    str,
    client_name: str,
) -> Optional[ProformaDraft]:
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        )
        row = cur.fetchone()
        return _row_to_draft(row) if row else None


def upsert_pending_draft(
    db_path:           Path,
    *,
    batch_id:          str,
    client_name:       str,
    currency:          str,
    exchange_rate:     Optional[float],
    source_lines_json: str,
) -> tuple:
    """
    Return (ProformaDraft, was_created).

    Idempotent on (batch_id, client_name): if a draft already exists for
    that key (in any status), it is returned unchanged with was_created=False.
    The caller decides whether to retry, surface, or escalate based on the
    existing row's status.
    """
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        existing = conn.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (str(batch_id), str(client_name)),
        ).fetchone()
        if existing is not None:
            return (_row_to_draft(existing), False)

        now = _now_utc_iso()
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, wfirma_proforma_id, notes,
                 created_at, updated_at)
            VALUES (?, ?, 'pending_local', ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (str(batch_id), str(client_name), str(currency or ""),
             exchange_rate, source_lines_json, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id=?", (cur.lastrowid,),
        ).fetchone()
        return (_row_to_draft(row), True)


def mark_draft_failed(db_path: Path, batch_id: str, client_name: str,
                      *, notes: str) -> None:
    if not (notes or "").strip():
        raise ValueError("notes is required when marking failed")
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "UPDATE proforma_drafts SET status='failed', notes=?, updated_at=? "
            "WHERE batch_id=? AND client_name=?",
            (notes, _now_utc_iso(), str(batch_id), str(client_name)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no draft for ({batch_id!r}, {client_name!r})")


def mark_draft_issued(db_path: Path, batch_id: str, client_name: str,
                      *, wfirma_proforma_id: str) -> None:
    if not (wfirma_proforma_id or "").strip():
        raise ValueError("wfirma_proforma_id is required to mark issued")
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_drafts_table(conn)
        cur = conn.execute(
            "UPDATE proforma_drafts SET status='issued', wfirma_proforma_id=?, "
            "updated_at=? WHERE batch_id=? AND client_name=?",
            (str(wfirma_proforma_id), _now_utc_iso(),
             str(batch_id), str(client_name)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"no draft for ({batch_id!r}, {client_name!r})")


__all__ = [
    "ProformaInvoiceLink",
    "ProformaAlreadyConverted",
    "VALID_STATUSES",
    "validate",
    "init_db",
    "create_pending_link",
    "mark_issued",
    "mark_failed",
    "get_link_by_proforma",
    "get_link_by_invoice",
    "list_links",
    # ── Proforma drafts (pre-create staging) ──
    "ProformaDraft",
    "DRAFT_STATUSES",
    "upsert_pending_draft",
    "get_draft",
    "mark_draft_failed",
    "mark_draft_issued",
]

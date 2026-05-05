"""
customer_invoice_snapshot_db.py — local snapshot of wFirma sales invoices.

Three tables:
  customer_invoice_snapshot              (one row per invoice)
  customer_invoice_lines                 (one row per invoicecontent line)
  customer_commercial_profile_snapshot   (one row per customer, latest profile)

Pure CRUD. NEVER imports wFirma client. The sync tool in
app/tools/sync_customer_invoice_snapshot.py orchestrates wFirma fetch +
calls into here.

Idempotency:
  - Invoices upsert by `invoice_id` (wFirma id, globally unique).
  - On update, lines for the snapshot are replaced (delete + re-insert).
  - Profiles upsert by `contractor_id`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InvoiceLineRow:
    line_type:    str   # product | freight | insurance | service | other
    good_id:      Optional[str] = None
    product_code: Optional[str] = None
    name:         Optional[str] = None
    qty:          Optional[Decimal] = None
    unit:         Optional[str] = None
    price:        Optional[Decimal] = None
    vat_code_id:  Optional[str] = None
    line_net:     Optional[Decimal] = None
    line_gross:   Optional[Decimal] = None


@dataclass(frozen=True)
class InvoiceSnapshotRow:
    invoice_id:               str
    contractor_id:            str
    contractor_name:          Optional[str] = None
    country:                  Optional[str] = None
    nip:                      Optional[str] = None
    invoice_number:           Optional[str] = None
    invoice_type:             str = "normal"
    invoice_date:             Optional[str] = None
    currency:                 Optional[str] = None
    series_id:                Optional[str] = None
    translation_language_id:  Optional[str] = None
    vat_codes_used:           Optional[str] = None    # comma-joined
    contractor_receiver_id:   Optional[str] = None
    description:              Optional[str] = None
    total_net:                Optional[Decimal] = None
    total_gross:              Optional[Decimal] = None
    lines:                    Tuple[InvoiceLineRow, ...] = ()


@dataclass(frozen=True)
class ProfileSnapshotRow:
    contractor_id:                 str
    period_from:                   Optional[str] = None
    period_to:                     Optional[str] = None
    invoice_count:                 int = 0
    preferred_currency:            Optional[str] = None
    preferred_language_id:         Optional[str] = None
    preferred_invoice_series_id:   Optional[str] = None
    vat_mode:                      Optional[int] = None
    last_freight_amount:           Optional[Decimal] = None
    avg_freight_amount:            Optional[Decimal] = None
    freight_mode:                  Optional[str] = None
    insurance_min_detected:        Optional[Decimal] = None
    insurance_mode:                Optional[str] = None
    ship_to_mode:                  Optional[str] = None
    confidence_state:              Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dec_to_str(d) -> Optional[str]:
    return str(Decimal(d)) if d is not None else None


def _str_to_dec(s) -> Optional[Decimal]:
    if s is None or s == "":
        return None
    return Decimal(str(s))


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create all 3 tables. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_invoice_snapshot (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id               TEXT NOT NULL UNIQUE,
                contractor_id            TEXT NOT NULL,
                contractor_name          TEXT,
                country                  TEXT,
                nip                      TEXT,
                invoice_number           TEXT,
                invoice_type             TEXT NOT NULL,
                invoice_date             TEXT,
                currency                 TEXT,
                series_id                TEXT,
                translation_language_id  TEXT,
                vat_codes_used           TEXT,
                contractor_receiver_id   TEXT,
                description              TEXT,
                total_net                TEXT,
                total_gross              TEXT,
                created_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_invoice_contractor
            ON customer_invoice_snapshot (contractor_id, invoice_date DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_invoice_type_date
            ON customer_invoice_snapshot (invoice_type, invoice_date DESC)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_invoice_lines (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL,
                line_type    TEXT NOT NULL,
                good_id      TEXT,
                product_code TEXT,
                name         TEXT,
                qty          TEXT,
                unit         TEXT,
                price        TEXT,
                vat_code_id  TEXT,
                line_net     TEXT,
                line_gross   TEXT,
                FOREIGN KEY (snapshot_id) REFERENCES customer_invoice_snapshot(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_lines_snapshot
            ON customer_invoice_lines (snapshot_id)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_commercial_profile_snapshot (
                contractor_id                 TEXT PRIMARY KEY,
                period_from                   TEXT,
                period_to                     TEXT,
                invoice_count                 INTEGER NOT NULL DEFAULT 0,
                preferred_currency            TEXT,
                preferred_language_id         TEXT,
                preferred_invoice_series_id   TEXT,
                vat_mode                      INTEGER,
                last_freight_amount           TEXT,
                avg_freight_amount            TEXT,
                freight_mode                  TEXT,
                insurance_min_detected        TEXT,
                insurance_mode                TEXT,
                ship_to_mode                  TEXT,
                confidence_state              TEXT,
                updated_at                    TEXT NOT NULL
            )
        """)


# ── Invoices ──────────────────────────────────────────────────────────────────

def upsert_invoice_with_lines(db_path: Path,
                               row: InvoiceSnapshotRow) -> int:
    """Upsert by `invoice_id`. Lines are replaced (delete + insert) on update.
    Returns the snapshot row id."""
    if not row.invoice_id or not row.contractor_id or not row.invoice_type:
        raise ValueError("invoice_id, contractor_id, invoice_type are required")

    init_db(db_path)
    now = _now()

    payload = {
        "invoice_id":              row.invoice_id,
        "contractor_id":           row.contractor_id,
        "contractor_name":         row.contractor_name,
        "country":                 (row.country or "").upper() or None,
        "nip":                     row.nip,
        "invoice_number":          row.invoice_number,
        "invoice_type":            row.invoice_type,
        "invoice_date":            row.invoice_date,
        "currency":                row.currency,
        "series_id":               row.series_id,
        "translation_language_id": row.translation_language_id,
        "vat_codes_used":          row.vat_codes_used,
        "contractor_receiver_id":  row.contractor_receiver_id,
        "description":             row.description,
        "total_net":               _dec_to_str(row.total_net),
        "total_gross":             _dec_to_str(row.total_gross),
        "updated_at":              now,
    }

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM customer_invoice_snapshot WHERE invoice_id = ?",
            (row.invoice_id,),
        ).fetchone()
        if existing is None:
            cols = ",".join(payload.keys()) + ",created_at"
            placeholders = ",".join("?" for _ in payload) + ",?"
            cur = conn.execute(
                f"INSERT INTO customer_invoice_snapshot ({cols}) VALUES ({placeholders})",
                tuple(payload.values()) + (now,),
            )
            snapshot_id = int(cur.lastrowid or 0)
        else:
            snapshot_id = int(existing["id"])
            set_clause = ",".join(f"{k} = ?" for k in payload.keys())
            conn.execute(
                f"UPDATE customer_invoice_snapshot SET {set_clause} WHERE id = ?",
                tuple(payload.values()) + (snapshot_id,),
            )
            # Replace lines
            conn.execute("DELETE FROM customer_invoice_lines WHERE snapshot_id = ?",
                         (snapshot_id,))

        # Insert lines
        for ln in row.lines:
            conn.execute("""
                INSERT INTO customer_invoice_lines
                  (snapshot_id, line_type, good_id, product_code, name, qty, unit,
                   price, vat_code_id, line_net, line_gross)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, ln.line_type, ln.good_id, ln.product_code, ln.name,
                _dec_to_str(ln.qty), ln.unit, _dec_to_str(ln.price),
                ln.vat_code_id, _dec_to_str(ln.line_net), _dec_to_str(ln.line_gross),
            ))
        return snapshot_id


def get_invoice_by_invoice_id(db_path: Path,
                              invoice_id: str) -> Optional[InvoiceSnapshotRow]:
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customer_invoice_snapshot WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        if row is None:
            return None
        line_rows = conn.execute(
            "SELECT * FROM customer_invoice_lines WHERE snapshot_id = ? ORDER BY id",
            (row["id"],),
        ).fetchall()
    lines = tuple(_row_to_line(lr) for lr in line_rows)
    return _row_to_invoice(row, lines)


def list_invoices(db_path: Path,
                  contractor_id:   Optional[str] = None,
                  invoice_type:    Optional[str] = None,
                  date_from:       Optional[str] = None,
                  date_to:         Optional[str] = None,
                  limit:           int = 500) -> List[InvoiceSnapshotRow]:
    if not Path(db_path).is_file():
        return []
    sql = "SELECT * FROM customer_invoice_snapshot WHERE 1=1"
    params: list = []
    if contractor_id:
        sql += " AND contractor_id = ?"; params.append(contractor_id)
    if invoice_type:
        sql += " AND invoice_type = ?"; params.append(invoice_type)
    if date_from:
        sql += " AND invoice_date >= ?"; params.append(date_from)
    if date_to:
        sql += " AND invoice_date <= ?"; params.append(date_to)
    sql += " ORDER BY invoice_date DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        snapshots: List[InvoiceSnapshotRow] = []
        for r in rows:
            line_rows = conn.execute(
                "SELECT * FROM customer_invoice_lines WHERE snapshot_id = ? ORDER BY id",
                (r["id"],),
            ).fetchall()
            snapshots.append(_row_to_invoice(r, tuple(_row_to_line(lr) for lr in line_rows)))
    return snapshots


def list_distinct_contractors(db_path: Path,
                              invoice_type: Optional[str] = "normal",
                              date_from:    Optional[str] = None,
                              date_to:      Optional[str] = None) -> List[str]:
    """Distinct contractor_ids in the snapshot, optionally filtered."""
    if not Path(db_path).is_file():
        return []
    sql = "SELECT DISTINCT contractor_id FROM customer_invoice_snapshot WHERE 1=1"
    params: list = []
    if invoice_type:
        sql += " AND invoice_type = ?"; params.append(invoice_type)
    if date_from:
        sql += " AND invoice_date >= ?"; params.append(date_from)
    if date_to:
        sql += " AND invoice_date <= ?"; params.append(date_to)
    sql += " ORDER BY contractor_id"
    with sqlite3.connect(str(db_path)) as conn:
        return [r[0] for r in conn.execute(sql, params).fetchall()]


def _row_to_line(r: sqlite3.Row) -> InvoiceLineRow:
    return InvoiceLineRow(
        line_type    = r["line_type"],
        good_id      = r["good_id"],
        product_code = r["product_code"],
        name         = r["name"],
        qty          = _str_to_dec(r["qty"]),
        unit         = r["unit"],
        price        = _str_to_dec(r["price"]),
        vat_code_id  = r["vat_code_id"],
        line_net     = _str_to_dec(r["line_net"]),
        line_gross   = _str_to_dec(r["line_gross"]),
    )


def _row_to_invoice(r: sqlite3.Row,
                    lines: Tuple[InvoiceLineRow, ...]) -> InvoiceSnapshotRow:
    return InvoiceSnapshotRow(
        invoice_id              = r["invoice_id"],
        contractor_id           = r["contractor_id"],
        contractor_name         = r["contractor_name"],
        country                 = r["country"],
        nip                     = r["nip"],
        invoice_number          = r["invoice_number"],
        invoice_type            = r["invoice_type"],
        invoice_date            = r["invoice_date"],
        currency                = r["currency"],
        series_id               = r["series_id"],
        translation_language_id = r["translation_language_id"],
        vat_codes_used          = r["vat_codes_used"],
        contractor_receiver_id  = r["contractor_receiver_id"],
        description             = r["description"],
        total_net               = _str_to_dec(r["total_net"]),
        total_gross             = _str_to_dec(r["total_gross"]),
        lines                   = lines,
    )


# ── Profiles ──────────────────────────────────────────────────────────────────

def upsert_profile(db_path: Path, p: ProfileSnapshotRow) -> None:
    if not p.contractor_id:
        raise ValueError("contractor_id required")
    init_db(db_path)
    payload = {
        "contractor_id":               p.contractor_id,
        "period_from":                 p.period_from,
        "period_to":                   p.period_to,
        "invoice_count":               int(p.invoice_count),
        "preferred_currency":          p.preferred_currency,
        "preferred_language_id":       p.preferred_language_id,
        "preferred_invoice_series_id": p.preferred_invoice_series_id,
        "vat_mode":                    p.vat_mode,
        "last_freight_amount":         _dec_to_str(p.last_freight_amount),
        "avg_freight_amount":          _dec_to_str(p.avg_freight_amount),
        "freight_mode":                p.freight_mode,
        "insurance_min_detected":      _dec_to_str(p.insurance_min_detected),
        "insurance_mode":              p.insurance_mode,
        "ship_to_mode":                p.ship_to_mode,
        "confidence_state":            p.confidence_state,
        "updated_at":                  _now(),
    }
    with sqlite3.connect(str(db_path)) as conn:
        cols = ",".join(payload.keys())
        placeholders = ",".join("?" for _ in payload)
        update_clause = ",".join(f"{k}=excluded.{k}" for k in payload.keys()
                                 if k != "contractor_id")
        conn.execute(
            f"INSERT INTO customer_commercial_profile_snapshot ({cols}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(contractor_id) DO UPDATE SET {update_clause}",
            tuple(payload.values()),
        )


def get_profile(db_path: Path, contractor_id: str) -> Optional[ProfileSnapshotRow]:
    if not Path(db_path).is_file():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customer_commercial_profile_snapshot WHERE contractor_id = ?",
            (contractor_id,),
        ).fetchone()
    if row is None:
        return None
    return ProfileSnapshotRow(
        contractor_id               = row["contractor_id"],
        period_from                 = row["period_from"],
        period_to                   = row["period_to"],
        invoice_count               = int(row["invoice_count"]),
        preferred_currency          = row["preferred_currency"],
        preferred_language_id       = row["preferred_language_id"],
        preferred_invoice_series_id = row["preferred_invoice_series_id"],
        vat_mode                    = row["vat_mode"],
        last_freight_amount         = _str_to_dec(row["last_freight_amount"]),
        avg_freight_amount          = _str_to_dec(row["avg_freight_amount"]),
        freight_mode                = row["freight_mode"],
        insurance_min_detected      = _str_to_dec(row["insurance_min_detected"]),
        insurance_mode              = row["insurance_mode"],
        ship_to_mode                = row["ship_to_mode"],
        confidence_state            = row["confidence_state"],
    )


def list_profiles(db_path: Path) -> List[ProfileSnapshotRow]:
    if not Path(db_path).is_file():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM customer_commercial_profile_snapshot").fetchall()
    out = []
    for r in rows:
        out.append(ProfileSnapshotRow(
            contractor_id               = r["contractor_id"],
            period_from                 = r["period_from"],
            period_to                   = r["period_to"],
            invoice_count               = int(r["invoice_count"]),
            preferred_currency          = r["preferred_currency"],
            preferred_language_id       = r["preferred_language_id"],
            preferred_invoice_series_id = r["preferred_invoice_series_id"],
            vat_mode                    = r["vat_mode"],
            last_freight_amount         = _str_to_dec(r["last_freight_amount"]),
            avg_freight_amount          = _str_to_dec(r["avg_freight_amount"]),
            freight_mode                = r["freight_mode"],
            insurance_min_detected      = _str_to_dec(r["insurance_min_detected"]),
            insurance_mode              = r["insurance_mode"],
            ship_to_mode                = r["ship_to_mode"],
            confidence_state            = r["confidence_state"],
        ))
    return out


__all__ = [
    "InvoiceLineRow",
    "InvoiceSnapshotRow",
    "ProfileSnapshotRow",
    "init_db",
    "upsert_invoice_with_lines",
    "get_invoice_by_invoice_id",
    "list_invoices",
    "list_distinct_contractors",
    "upsert_profile",
    "get_profile",
    "list_profiles",
]

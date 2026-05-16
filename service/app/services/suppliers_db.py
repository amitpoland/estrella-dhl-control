"""
suppliers_db.py — Master Data: Suppliers registry.

Goods exporters and consignment senders. Maps supplier names on invoices to
canonical records used during SAD/ZC429 verification.

This module is additive and local-only. It DOES NOT write to wFirma, does
NOT participate in PZ/customs/landed-cost calculation, and does NOT modify
any existing schema.

Storage: <storage_root>/suppliers.sqlite
Table:   suppliers (single)
Key:     supplier_code (UNIQUE)
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Domain ────────────────────────────────────────────────────────────────────

_ISO_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")
_EMAIL_RE      = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Supplier:
    supplier_code: str
    name:          str
    country:       str                       # ISO alpha-2, normalised to upper
    vat_id:        Optional[str] = None
    eori:          Optional[str] = None
    address:       Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    active:        bool          = True
    notes:         Optional[str] = None
    wfirma_id:     Optional[str] = None      # B0 (MDOC-cache): soft ref into wFirma contractors
    id:            Optional[int] = None
    created_at:    Optional[str] = None
    updated_at:    Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_supplier(row: sqlite3.Row) -> Supplier:
    # Use dict access via row.keys() to tolerate legacy schemas pre-B0
    # that may lack the wfirma_id column on already-open connections.
    try:
        wfid = row["wfirma_id"]
    except (IndexError, KeyError):
        wfid = None
    return Supplier(
        id            = row["id"],
        supplier_code = row["supplier_code"],
        name          = row["name"],
        country       = row["country"],
        vat_id        = row["vat_id"],
        eori          = row["eori"],
        address       = row["address"],
        contact_email = row["contact_email"],
        contact_phone = row["contact_phone"],
        active        = bool(int(row["active"])),
        notes         = row["notes"],
        wfirma_id     = wfid,
        created_at    = row["created_at"],
        updated_at    = row["updated_at"],
    )


def _clean(v: Any) -> Optional[str]:
    """Normalise input: '' or whitespace-only → None; trim others."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# ── Validation ────────────────────────────────────────────────────────────────

def validate_supplier(data: Dict[str, Any]) -> List[str]:
    """Return list of error strings; empty list = OK."""
    errors: List[str] = []

    code = _clean(data.get("supplier_code"))
    if not code:
        errors.append("supplier_code is required")
    elif len(code) > 64:
        errors.append("supplier_code must be ≤ 64 characters")

    name = _clean(data.get("name"))
    if not name:
        errors.append("name is required")

    country = _clean(data.get("country"))
    if not country:
        errors.append("country is required")
    elif not _ISO_ALPHA2_RE.match(country.upper()):
        errors.append(f"country must be ISO alpha-2, got {country!r}")

    email = _clean(data.get("contact_email"))
    if email is not None and not _EMAIL_RE.match(email):
        errors.append(f"contact_email is malformed: {email!r}")

    return errors


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create suppliers table if it does not exist. Idempotent.

    B0 (MDOC-cache): adds nullable ``wfirma_id`` column to enable dedup
    against the wFirma contractor master cache. Soft reference only; no
    SQL FK constraint (consistent with the rest of master-data style).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_code   TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                country         TEXT NOT NULL,
                vat_id          TEXT,
                eori            TEXT,
                address         TEXT,
                contact_email   TEXT,
                contact_phone   TEXT,
                active          INTEGER NOT NULL DEFAULT 1,
                notes           TEXT,
                wfirma_id       TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_country ON suppliers (country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_active  ON suppliers (active)")
        # ── B0 additive migration: backfill wfirma_id column on legacy DBs ────
        cols = {row[1] for row in conn.execute("PRAGMA table_info(suppliers)").fetchall()}
        if "wfirma_id" not in cols:
            conn.execute("ALTER TABLE suppliers ADD COLUMN wfirma_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_wfirma_id ON suppliers (wfirma_id)")
        conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_supplier(db_path: Path, data: Dict[str, Any]) -> int:
    """Create a new supplier. Raises ValueError on validation or DUPLICATE_CODE."""
    errs = validate_supplier(data)
    if errs:
        raise ValueError("; ".join(errs))
    init_db(db_path)
    now = _now()
    payload = {
        "supplier_code": _clean(data.get("supplier_code")),
        "name":          _clean(data.get("name")),
        "country":       _clean(data.get("country")).upper(),
        "vat_id":        _clean(data.get("vat_id")),
        "eori":          _clean(data.get("eori")),
        "address":       _clean(data.get("address")),
        "contact_email": _clean(data.get("contact_email")),
        "contact_phone": _clean(data.get("contact_phone")),
        "active":        1 if data.get("active", True) else 0,
        "notes":         _clean(data.get("notes")),
        "wfirma_id":     _clean(data.get("wfirma_id")),
    }
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("""
                INSERT INTO suppliers
                    (supplier_code, name, country, vat_id, eori, address,
                     contact_email, contact_phone, active, notes, wfirma_id,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (payload["supplier_code"], payload["name"], payload["country"],
                  payload["vat_id"], payload["eori"], payload["address"],
                  payload["contact_email"], payload["contact_phone"],
                  payload["active"], payload["notes"], payload["wfirma_id"],
                  now, now))
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"DUPLICATE_CODE: supplier_code={payload['supplier_code']!r} already exists")
            raise


def get_supplier(db_path: Path, supplier_id: int) -> Optional[Supplier]:
    """Return supplier by primary key id, or None if missing / table absent."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_supplier(row) if row else None


def get_supplier_by_code(db_path: Path, supplier_code: str) -> Optional[Supplier]:
    """Return supplier by unique supplier_code."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM suppliers WHERE supplier_code = ?", (supplier_code,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return _row_to_supplier(row) if row else None


def list_suppliers(
    db_path: Path,
    *,
    active:  Optional[bool] = None,
    country: Optional[str] = None,
    limit:   int = 200,
) -> List[Supplier]:
    """List suppliers ordered by most recently updated."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where: List[str] = []
    params: List[Any] = []
    if active is not None:
        where.append("active = ?")
        params.append(1 if active else 0)
    if country:
        where.append("country = ?")
        params.append(country.strip().upper())
    sql = "SELECT * FROM suppliers"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_row_to_supplier(r) for r in rows]


def update_supplier(db_path: Path, supplier_id: int, data: Dict[str, Any]) -> Optional[Supplier]:
    """Update supplier. Returns updated row, or None if no row affected.

    Validates the full payload as if creating (since callers send the entire form).
    Preserves supplier_code if not present in payload (silent no-op on code field).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    existing = get_supplier(db_path, supplier_id)
    if existing is None:
        return None
    # Merge over existing so partial PUTs don't unset other fields
    merged = {
        "supplier_code": data.get("supplier_code", existing.supplier_code),
        "name":          data.get("name",          existing.name),
        "country":       data.get("country",       existing.country),
        "vat_id":        data.get("vat_id",        existing.vat_id),
        "eori":          data.get("eori",          existing.eori),
        "address":       data.get("address",       existing.address),
        "contact_email": data.get("contact_email", existing.contact_email),
        "contact_phone": data.get("contact_phone", existing.contact_phone),
        "active":        data.get("active",        existing.active),
        "notes":         data.get("notes",         existing.notes),
    }
    errs = validate_supplier(merged)
    if errs:
        raise ValueError("; ".join(errs))
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        try:
            conn.execute("""
                UPDATE suppliers SET
                    supplier_code = ?, name = ?, country = ?, vat_id = ?,
                    eori = ?, address = ?, contact_email = ?, contact_phone = ?,
                    active = ?, notes = ?, updated_at = ?
                WHERE id = ?
            """, (_clean(merged["supplier_code"]), _clean(merged["name"]),
                  _clean(merged["country"]).upper(),
                  _clean(merged["vat_id"]), _clean(merged["eori"]),
                  _clean(merged["address"]), _clean(merged["contact_email"]),
                  _clean(merged["contact_phone"]),
                  1 if merged["active"] else 0, _clean(merged["notes"]),
                  now, supplier_id))
            conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise ValueError(f"DUPLICATE_CODE: supplier_code={merged['supplier_code']!r} already exists")
            raise
    return get_supplier(db_path, supplier_id)


def delete_supplier(db_path: Path, supplier_id: int) -> bool:
    """Hard delete. Returns True if a row was removed."""
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


# ── B0 (MDOC-cache) — wFirma identity sync ────────────────────────────────────
#
# Read-only against wFirma. Pulls contractors via wfirma_client and upserts
# them into the local suppliers table. No wFirma write. No proforma / PZ /
# finance side effects. Dedup by wfirma_id (primary) AND by (vat_id+name)
# fallback for legacy rows entered before the wFirma cache existed.

def _supplier_code_from_wfirma(wfirma_id: str, name: str) -> str:
    """Deterministic supplier_code from wFirma identity. Stable across re-syncs."""
    base = (name or "").strip().upper()
    base = "".join(ch if ch.isalnum() else "_" for ch in base)[:48].strip("_")
    if not base:
        base = "WFIRMA"
    return f"WF-{wfirma_id}-{base}" if wfirma_id else f"LOCAL-{base}"


def sync_from_wfirma(db_path: Path, *, dry_run: bool = True) -> Dict[str, Any]:
    """Pull wFirma contractors and reconcile into local suppliers.

    No wFirma write. Local-only mutation when dry_run=False.

    Dedup rules (in order):
      1. row.wfirma_id matches a fetched contractor.wfirma_id → UPDATE that row.
      2. row.wfirma_id is NULL/empty AND row.vat_id == contractor.nip
         AND row.name == contractor.name → backfill wfirma_id on that row.
      3. otherwise → INSERT new supplier.

    Returns: dict with counts {fetched, inserted, updated_match, backfilled,
    skipped, conflicts}. dry_run mode reports the same counts but never writes.
    """
    from . import wfirma_client as wfc  # local import to avoid top-level cycle

    init_db(db_path)
    contractors: List["wfc.WFirmaContractor"] = []
    page = 1
    page_size = 100
    while True:
        batch = wfc.list_contractors_page(page=page, limit=page_size)
        if not batch:
            break
        contractors.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
        if page > 200:  # safety
            break

    counts = {
        "fetched":         len(contractors),
        "inserted":        0,
        "updated_match":   0,
        "backfilled":      0,
        "skipped":         0,
        "conflicts":       0,
        "dry_run":         bool(dry_run),
    }
    examples: List[Dict[str, Any]] = []

    if not contractors:
        return {**counts, "examples": examples}

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row

        # Build lookup maps once per call.
        all_rows = conn.execute("SELECT id, supplier_code, name, country, vat_id, wfirma_id FROM suppliers").fetchall()
        by_wfirma:  Dict[str, sqlite3.Row] = {}
        by_vat:     Dict[str, sqlite3.Row] = {}
        for r in all_rows:
            wf = (r["wfirma_id"] or "").strip()
            if wf:
                by_wfirma[wf] = r
            vat = (r["vat_id"] or "").strip().lower()
            nm  = (r["name"] or "").strip().lower()
            if vat and nm:
                by_vat[f"{vat}|{nm}"] = r

        now = _now()
        seen_wfirma_ids = set()

        for c in contractors:
            wfid = (c.wfirma_id or "").strip()
            if not wfid:
                counts["skipped"] += 1
                continue
            if wfid in seen_wfirma_ids:
                counts["skipped"] += 1
                continue
            seen_wfirma_ids.add(wfid)

            cname = (c.name or "").strip()
            cnip  = (c.nip or "").strip()
            ccountry = (c.country or "").strip().upper()

            # Rule 1: exact wfirma_id match → UPDATE
            existing = by_wfirma.get(wfid)
            if existing is not None:
                if not dry_run:
                    conn.execute(
                        """UPDATE suppliers SET name=?, country=?, vat_id=COALESCE(NULLIF(?,''), vat_id),
                                                updated_at=? WHERE id=?""",
                        (cname or existing["name"], ccountry or existing["country"], cnip, now, existing["id"]),
                    )
                counts["updated_match"] += 1
                continue

            # Rule 2: vat+name fallback → backfill wfirma_id
            vat_key = f"{cnip.lower()}|{cname.lower()}"
            existing = by_vat.get(vat_key) if cnip and cname else None
            if existing is not None:
                if not dry_run:
                    conn.execute(
                        "UPDATE suppliers SET wfirma_id=?, updated_at=? WHERE id=?",
                        (wfid, now, existing["id"]),
                    )
                counts["backfilled"] += 1
                continue

            # Rule 3: new row
            sup_code = _supplier_code_from_wfirma(wfid, cname)
            if not cname or not ccountry:
                counts["skipped"] += 1
                if len(examples) < 5:
                    examples.append({"reason": "incomplete", "wfirma_id": wfid, "name": cname, "country": ccountry})
                continue
            if not dry_run:
                try:
                    conn.execute(
                        """INSERT INTO suppliers
                            (supplier_code, name, country, vat_id, eori, address,
                             contact_email, contact_phone, active, notes, wfirma_id,
                             created_at, updated_at)
                           VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, 1, NULL, ?, ?, ?)""",
                        (sup_code, cname, ccountry, cnip or None, wfid, now, now),
                    )
                    counts["inserted"] += 1
                except sqlite3.IntegrityError as exc:
                    # supplier_code clash — shouldn't happen given deterministic key,
                    # but record as conflict and move on
                    counts["conflicts"] += 1
                    if len(examples) < 5:
                        examples.append({"reason": "code_conflict", "wfirma_id": wfid,
                                         "supplier_code": sup_code, "err": str(exc)})
            else:
                counts["inserted"] += 1  # would-insert in dry-run

        if not dry_run:
            conn.commit()

    return {**counts, "examples": examples}

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
from typing import Any, Dict, Iterable, List, Optional


# ── Domain ────────────────────────────────────────────────────────────────────

_ISO_ALPHA2_RE  = re.compile(r"^[A-Z]{2}$")
_EMAIL_RE       = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PUNCT_RE       = re.compile(r"[^\w\s]")   # for name normalization
_MULTI_SPACE_RE = re.compile(r"\s+")


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

    # B0 supplier deep-enrichment 2026-05-17 — wFirma contractor-detail
    # fields. Filled-when-empty by ``upsert_identity_from_wfirma``; never
    # overwrites operator-set values. Mirrors the Client Master plumbing
    # (PR #154) for symmetry.
    street:              Optional[str] = None
    city:                Optional[str] = None
    postal_code:         Optional[str] = None
    contact_mobile:      Optional[str] = None
    bank_account:        Optional[str] = None
    last_wfirma_sync_at: Optional[str] = None
    wfirma_sync_source:  Optional[str] = None
    # Phase 4B Wave 3b-1 — soft-delete timestamp (NULL = not deleted).
    deleted_at:          Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_supplier(row: sqlite3.Row) -> Supplier:
    # Use dict access via row.keys() to tolerate legacy schemas that may
    # lack the wfirma_id or deep-enrichment columns on already-open
    # connections.
    def _get(col: str):
        try:
            return row[col]
        except (IndexError, KeyError):
            return None
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
        wfirma_id     = _get("wfirma_id"),
        created_at    = row["created_at"],
        updated_at    = row["updated_at"],
        # Deep-enrichment columns — None for rows pre-additive-migration.
        street              = _get("street"),
        city                = _get("city"),
        postal_code         = _get("postal_code"),
        contact_mobile      = _get("contact_mobile"),
        bank_account        = _get("bank_account"),
        last_wfirma_sync_at = _get("last_wfirma_sync_at"),
        wfirma_sync_source  = _get("wfirma_sync_source"),
        deleted_at          = _get("deleted_at"),
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
        # ── B0 supplier deep-enrichment 2026-05-17 — additive columns ────────
        # Mirrors the Client Master schema additions (PR #154). Each column
        # is nullable; existing rows retain NULL until apply fills them.
        for c, t in (
            ("street",              "TEXT"),
            ("city",                "TEXT"),
            ("postal_code",         "TEXT"),
            ("contact_mobile",      "TEXT"),
            ("bank_account",        "TEXT"),
            ("last_wfirma_sync_at", "TEXT"),
            ("wfirma_sync_source",  "TEXT"),
            # Phase 4B Wave 3b-1 — soft-delete column.
            ("deleted_at",          "TEXT"),
        ):
            if c not in cols:
                try:
                    conn.execute(f"ALTER TABLE suppliers ADD COLUMN {c} {t}")
                except sqlite3.OperationalError:
                    pass
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
    """Hard delete. Returns True if a row was removed.

    Phase 4B Wave 3b-1 retains this as the hard-delete primitive; the route
    layer chooses between soft-delete (default) and hard-delete.
    """
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


# ── Phase 4B Wave 3b-1 — soft-delete + restore ──────────────────────────────
#
# Pure-local. No wFirma client import, no sync side effects. The wFirma sync
# code path (sync_from_wfirma / upsert_supplier_identity_from_wfirma below) is
# NOT modified by this phase.

def soft_delete_supplier(db_path: Path, supplier_id: int) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute(
                "UPDATE suppliers SET active = 0, deleted_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, supplier_id),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


def restore_supplier(db_path: Path, supplier_id: int) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        try:
            cur = conn.execute(
                "UPDATE suppliers SET active = 1, deleted_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (now, supplier_id),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.OperationalError:
            return False


def hard_delete_supplier(db_path: Path, supplier_id: int) -> bool:
    return delete_supplier(db_path, supplier_id)


# ── Name-normalised lookup ─────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace.

    Used for fuzzy supplier name matching between audit-resolved names
    (e.g. "Estrella Jewels LLP") and master-data canonical names
    (e.g. "ESTRELLA JEWELS LLP.").  Removes trailing periods and other
    punctuation so both normalise to "estrella jewels llp".
    """
    if not name:
        return ""
    s = name.lower().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def find_by_name_normalized(db_path: Path, name: str) -> Optional[Supplier]:
    """Return the first *active* supplier whose normalised name matches ``name``.

    Matching is case- and punctuation-insensitive (see ``_normalize_name``).
    Returns ``None`` when:
      - ``name`` is blank
      - the DB file does not exist
      - no active supplier matches
    Never raises; returns ``None`` on any DB error.
    """
    if not (name or "").strip():
        return None
    target = _normalize_name(name)
    if not target:
        return None

    db_path = Path(db_path)
    if not db_path.exists():
        return None

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM suppliers WHERE active = 1 ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return None

    for row in rows:
        if _normalize_name(row["name"] or "") == target:
            return _row_to_supplier(row)
    return None


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


# ── B0 (MDOC-cache) — proposal status constants ─────────────────────────────
#
# Per the review-and-assign requirement: the sync layer emits per-row
# *proposals* the operator can View / Edit / Assign / Skip in the UI. Statuses
# are enumerated and stable so the dashboard can render them deterministically.

PROPOSAL_MATCHED_EXISTING      = "matched_existing"      # exact wfirma_id match → safe update
PROPOSAL_NEW_CANDIDATE         = "new_candidate"         # no local match, valid → assignable insert
PROPOSAL_NEEDS_OPERATOR_REVIEW = "needs_operator_review" # vat+name match but wfirma_id missing → backfill on confirm
PROPOSAL_SKIPPED_INVALID       = "skipped_invalid"       # missing required fields → not applicable

# Status → applicable action mapping. Operator opt-in apply uses these.
PROPOSAL_ACTIONS = {
    PROPOSAL_MATCHED_EXISTING:      "update",
    PROPOSAL_NEW_CANDIDATE:         "insert",
    PROPOSAL_NEEDS_OPERATOR_REVIEW: "backfill",
    PROPOSAL_SKIPPED_INVALID:       "none",
}


def _fetch_contractors() -> List[Any]:
    """Read-only paged fetch from wFirma. No write. Returns list of
    WFirmaContractor objects."""
    from . import wfirma_client as wfc
    contractors: List[Any] = []
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
    return contractors


_SUP_EXPENSE_HINTS = (
    "dhl", "fedex", " ups ", "tnt", "courier", "kurier", "hotel",
    "airline", "ryanair", "lufthansa", "lot polish", "uber",
    "tax office", "urzad skarbowy", "izba", "skarbowy",
    "bank ", "orlen ", "lotos ", "shell", "paypal", "stripe",
)
_SUP_EXPORTER_HINTS = (
    "estrella", " llp", " llp.", "pvt ltd", "pvt. ltd", "exporter",
    "exports", "manufacturing", " factory", "industries", "jewels pvt",
    "gems & jewel",
)


def _suggest_target(name: str, vat_id: str, country: str) -> Dict[str, str]:
    """Deterministic per-row target hint for the dashboard selector.
    Returns ``{"suggested_target": str, "reason": str}``."""
    nm = (name or "").lower().strip()
    if not nm:
        return {"suggested_target": "needs_operator_review", "reason": "missing_name"}
    if any(h in nm for h in _SUP_EXPENSE_HINTS):
        return {"suggested_target": "ignore", "reason": "expense_or_carrier_keyword"}
    if any(h in nm for h in _SUP_EXPORTER_HINTS):
        return {"suggested_target": "supplier_master", "reason": "exporter_keyword"}
    if vat_id and country:
        return {"suggested_target": "client_master", "reason": "vat_and_country_present"}
    return {"suggested_target": "needs_operator_review", "reason": "ambiguous"}


def compute_proposals(db_path: Path) -> List[Dict[str, Any]]:
    """Build per-row proposals for the review-and-assign UI. Pure read: no
    DB mutation, no wFirma write.

    Each proposal carries:
      wfirma_id, name, vat_id, country, email (always None — wFirma client
      does not surface email yet), status, proposed_action, local_id,
      local_supplier_code, local_name, local_email.

    Duplicate wfirma_ids in the wFirma response are collapsed (first wins).
    """
    init_db(db_path)
    contractors = _fetch_contractors()
    proposals: List[Dict[str, Any]] = []
    if not contractors:
        return proposals

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        all_rows = conn.execute(
            "SELECT id, supplier_code, name, country, vat_id, contact_email, wfirma_id FROM suppliers"
        ).fetchall()
        by_wfirma: Dict[str, sqlite3.Row] = {}
        by_vat:    Dict[str, sqlite3.Row] = {}
        for r in all_rows:
            wf = (r["wfirma_id"] or "").strip()
            if wf:
                by_wfirma[wf] = r
            vat = (r["vat_id"] or "").strip().lower()
            nm  = (r["name"] or "").strip().lower()
            if vat and nm:
                by_vat[f"{vat}|{nm}"] = r

    seen: set = set()
    for c in contractors:
        wfid = (c.wfirma_id or "").strip()
        cname = (c.name or "").strip()
        cnip  = (c.nip or "").strip()
        ccountry = (c.country or "").strip().upper()
        # B0 enrichment — opportunistic from wFirma XML.
        cemail  = (getattr(c, "email", "") or "").strip()
        cphone  = (getattr(c, "phone", "") or "").strip()
        cstreet = (getattr(c, "street", "") or "").strip()
        czip    = (getattr(c, "zip", "") or "").strip()
        ccity   = (getattr(c, "city", "") or "").strip()
        # Compose a single-line address (street, zip city, country)
        addr_parts = [p for p in (cstreet, " ".join([czip, ccity]).strip(), ccountry) if p]
        caddr = ", ".join(addr_parts) if addr_parts else ""

        if not wfid or wfid in seen:
            # Invalid (no wfirma_id) — record as skipped, but only once.
            if not wfid:
                proposals.append({
                    "wfirma_id":            "",
                    "name":                 cname,
                    "vat_id":               cnip,
                    "country":              ccountry,
                    "email":                None,
                    "status":               PROPOSAL_SKIPPED_INVALID,
                    "proposed_action":      "none",
                    "reason":               "missing_wfirma_id",
                    "local_id":             None,
                    "local_supplier_code":  None,
                    "local_name":           None,
                    "local_email":          None,
                })
            continue
        seen.add(wfid)

        existing = by_wfirma.get(wfid)
        if existing is not None:
            proposals.append({
                "wfirma_id":            wfid,
                "name":                 cname,
                "vat_id":               cnip,
                "country":              ccountry,
                "email":                None,
                "status":               PROPOSAL_MATCHED_EXISTING,
                "proposed_action":      PROPOSAL_ACTIONS[PROPOSAL_MATCHED_EXISTING],
                "reason":               "wfirma_id_match",
                "local_id":             existing["id"],
                "local_supplier_code":  existing["supplier_code"],
                "local_name":           existing["name"],
                "local_email":          existing["contact_email"],
            })
            continue

        vat_key = f"{cnip.lower()}|{cname.lower()}"
        existing = by_vat.get(vat_key) if cnip and cname else None
        if existing is not None:
            proposals.append({
                "wfirma_id":            wfid,
                "name":                 cname,
                "vat_id":               cnip,
                "country":              ccountry,
                "email":                None,
                "status":               PROPOSAL_NEEDS_OPERATOR_REVIEW,
                "proposed_action":      PROPOSAL_ACTIONS[PROPOSAL_NEEDS_OPERATOR_REVIEW],
                "reason":               "vat_and_name_match",
                "local_id":             existing["id"],
                "local_supplier_code":  existing["supplier_code"],
                "local_name":           existing["name"],
                "local_email":          existing["contact_email"],
            })
            continue

        if not cname or not ccountry:
            proposals.append({
                "wfirma_id":            wfid,
                "name":                 cname,
                "vat_id":               cnip,
                "country":              ccountry,
                "email":                None,
                "status":               PROPOSAL_SKIPPED_INVALID,
                "proposed_action":      "none",
                "reason":               "incomplete_name_or_country",
                "local_id":             None,
                "local_supplier_code":  None,
                "local_name":           None,
                "local_email":          None,
            })
            continue

        proposals.append({
            "wfirma_id":            wfid,
            "name":                 cname,
            "vat_id":               cnip,
            "country":              ccountry,
            "email":                cemail or None,
            "phone":                cphone or None,
            "address":              caddr or None,
            "status":               PROPOSAL_NEW_CANDIDATE,
            "proposed_action":      PROPOSAL_ACTIONS[PROPOSAL_NEW_CANDIDATE],
            "reason":               "no_local_match",
            "local_id":             None,
            "local_supplier_code":  _supplier_code_from_wfirma(wfid, cname),
            "local_name":           None,
            "local_email":          None,
        })

    # Annotate every proposal with a deterministic target suggestion. The
    # dashboard renders this as the default selection in the "Assign to"
    # dropdown; the operator can override per row.
    for p in proposals:
        hint = _suggest_target(p["name"], p["vat_id"], p["country"])
        # Force skipped_invalid rows to suggested_target="ignore" so they
        # cannot be applied accidentally even if operator changes target.
        if p["status"] == PROPOSAL_SKIPPED_INVALID:
            p["suggested_target"] = "ignore"
        else:
            p["suggested_target"] = hint["suggested_target"]
        p["target_reason"] = hint["reason"]
    return proposals


def _proposals_counts(proposals: List[Dict[str, Any]]) -> Dict[str, int]:
    """Aggregate counts by status. Used in both preview and write responses
    so the operator sees a consistent shape."""
    counts = {
        "fetched":         len(proposals),
        "inserted":        0,
        "updated_match":   0,
        "backfilled":      0,
        "skipped":         0,
        "conflicts":       0,
    }
    for p in proposals:
        s = p["status"]
        if s == PROPOSAL_MATCHED_EXISTING:
            counts["updated_match"] += 1
        elif s == PROPOSAL_NEW_CANDIDATE:
            counts["inserted"] += 1
        elif s == PROPOSAL_NEEDS_OPERATOR_REVIEW:
            counts["backfilled"] += 1
        elif s == PROPOSAL_SKIPPED_INVALID:
            counts["skipped"] += 1
    return counts


def sync_from_wfirma(
    db_path: Path,
    *,
    dry_run: bool = True,
    wfirma_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Pull wFirma contractors, classify into proposals, and optionally apply.

    No wFirma write. Local-only mutation when ``dry_run=False``.

    Per-row apply: when ``wfirma_ids`` is provided, only proposals whose
    ``wfirma_id`` is in that set are written. When ``None`` (full-batch
    legacy mode), every eligible proposal is applied.

    Skipped-invalid proposals are never applied regardless of filter.

    Returns: ``{fetched, inserted, updated_match, backfilled, skipped,
    conflicts, dry_run, examples, proposals}``. Counts are aggregates from
    the proposals list (which is always present).
    """
    proposals = compute_proposals(db_path)
    counts = _proposals_counts(proposals)
    counts["dry_run"] = bool(dry_run)
    counts["conflicts"] = 0  # incremented if INSERT collides
    examples: List[Dict[str, Any]] = []
    for p in proposals:
        if p["status"] == PROPOSAL_SKIPPED_INVALID and len(examples) < 5:
            examples.append({"reason": p["reason"], "wfirma_id": p["wfirma_id"],
                             "name": p["name"], "country": p["country"]})

    if dry_run or not proposals:
        return {**counts, "examples": examples, "proposals": proposals}

    filter_set = None
    if wfirma_ids is not None:
        filter_set = {str(x).strip() for x in wfirma_ids if str(x).strip()}

    # Recount after filter application (so the response reflects what we
    # actually wrote, not what we would have written without the filter).
    applied = {"inserted": 0, "updated_match": 0, "backfilled": 0, "skipped": 0, "conflicts": 0}
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        for p in proposals:
            wfid = p["wfirma_id"]
            status = p["status"]
            if status == PROPOSAL_SKIPPED_INVALID:
                applied["skipped"] += 1
                continue
            if filter_set is not None and wfid not in filter_set:
                applied["skipped"] += 1
                continue

            if status == PROPOSAL_MATCHED_EXISTING:
                conn.execute(
                    """UPDATE suppliers SET name=?, country=?,
                                            vat_id=COALESCE(NULLIF(?,''), vat_id),
                                            updated_at=? WHERE id=?""",
                    (p["name"] or p["local_name"], p["country"] or "",
                     p["vat_id"], now, p["local_id"]),
                )
                applied["updated_match"] += 1
            elif status == PROPOSAL_NEEDS_OPERATOR_REVIEW:
                conn.execute(
                    "UPDATE suppliers SET wfirma_id=?, updated_at=? WHERE id=?",
                    (wfid, now, p["local_id"]),
                )
                applied["backfilled"] += 1
            elif status == PROPOSAL_NEW_CANDIDATE:
                try:
                    conn.execute(
                        """INSERT INTO suppliers
                            (supplier_code, name, country, vat_id, eori, address,
                             contact_email, contact_phone, active, notes, wfirma_id,
                             created_at, updated_at)
                           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 1, NULL, ?, ?, ?)""",
                        (p["local_supplier_code"], p["name"], p["country"],
                         p["vat_id"] or None,
                         (p.get("address") or None),
                         (p.get("email")   or None),
                         (p.get("phone")   or None),
                         wfid, now, now),
                    )
                    applied["inserted"] += 1
                except sqlite3.IntegrityError as exc:
                    applied["conflicts"] += 1
                    if len(examples) < 5:
                        examples.append({"reason": "code_conflict",
                                         "wfirma_id": wfid,
                                         "supplier_code": p["local_supplier_code"],
                                         "err": str(exc)})
        conn.commit()

    counts.update(applied)
    return {**counts, "examples": examples, "proposals": proposals}


# ── B0 supplier deep-enrichment 2026-05-17 ────────────────────────────────────
#
# upsert_supplier_identity_from_wfirma() mirrors customer_master_db.
# upsert_identity_only(): fill-when-empty COALESCE-NULLIF semantics, never
# overwrites operator-set values. Insert path creates a minimal supplier
# row keyed by wfirma_id; update path refreshes identity (name, country)
# always and back-fills empty enrichment columns from wFirma. Last-sync
# audit columns are always stamped.

def upsert_supplier_identity_from_wfirma(
    db_path: Path,
    *,
    wfirma_id:     str,
    name:          str,
    country:       str,
    vat_id:        Optional[str] = None,
    # Deep-enrichment fields (all optional, all fill-when-empty)
    street:         Optional[str] = None,
    city:           Optional[str] = None,
    postal_code:    Optional[str] = None,
    contact_email:  Optional[str] = None,
    contact_phone:  Optional[str] = None,
    contact_mobile: Optional[str] = None,
    bank_account:   Optional[str] = None,
    address_fallback: Optional[str] = None,  # legacy free-form address line
    sync_source:    str           = "review_assign",
) -> Dict[str, Any]:
    """Symmetric supplier upsert from wFirma contractor detail.

    Hard rules:
    - Read-only against wFirma (caller has already fetched).
    - Fill-when-empty: operator-set local values ALWAYS win on UPDATE
      via ``COALESCE(NULLIF(local, ''), NULLIF(?, ''))``.
    - Insert path writes only the minimum identity + enrichment stub.
      eori, notes, active stay at table defaults.
    - Identity columns (``name``, ``country``) ARE always rewritten so
      the operator can refresh the canonical wFirma name.

    Returns ``{"id", "action", "row"}`` where action ∈ {inserted, updated}.
    Raises ``ValueError`` if any required field is missing/malformed.
    """
    wfid = (wfirma_id or "").strip()
    nm   = (name or "").strip()
    cty  = (country or "").strip().upper()

    blockers: List[str] = []
    if not wfid:
        blockers.append("wfirma_id is required")
    if not nm:
        blockers.append("name is required")
    if not cty or len(cty) != 2:
        blockers.append("country must be ISO-3166 alpha-2 (2 letters)")
    if blockers:
        raise ValueError("supplier identity validation failed: " + "; ".join(blockers))

    # Normalise enrichment values.
    vid  = (vat_id or "").strip()
    str_ = (street or "").strip()
    cit  = (city or "").strip()
    zp   = (postal_code or "").strip()
    em   = (contact_email or "").strip()
    ph   = (contact_phone or "").strip()
    mob  = (contact_mobile or "").strip()
    bnk  = (bank_account or "").strip()
    addr = (address_fallback or "").strip()
    src  = (sync_source or "review_assign").strip() or "review_assign"

    init_db(db_path)
    now = _now()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id, supplier_code FROM suppliers WHERE wfirma_id = ?",
            (wfid,),
        ).fetchone()
        if existing is None:
            # New supplier — deterministic code (same convention as
            # sync_from_wfirma's INSERT path).
            sup_code = _supplier_code_from_wfirma(wfid, nm)
            cur = conn.execute(
                """INSERT INTO suppliers
                       (supplier_code, name, country, vat_id, eori, address,
                        contact_email, contact_phone, active, notes, wfirma_id,
                        street, city, postal_code, contact_mobile, bank_account,
                        last_wfirma_sync_at, wfirma_sync_source,
                        created_at, updated_at)
                   VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sup_code, nm, cty, (vid or None), (addr or None),
                 (em or None), (ph or None), wfid,
                 (str_ or None), (cit or None), (zp or None),
                 (mob or None), (bnk or None),
                 now, src, now, now),
            )
            row_id = int(cur.lastrowid or 0)
            action = "inserted"
        else:
            row_id = int(existing["id"])
            # UPDATE — fill-when-empty for every enrichment column;
            # name + country always refreshed; eori / notes / active
            # never touched here.
            conn.execute(
                """UPDATE suppliers
                       SET name                = ?,
                           country             = ?,
                           vat_id              = COALESCE(NULLIF(vat_id, ''),         NULLIF(?, '')),
                           address             = COALESCE(NULLIF(address, ''),        NULLIF(?, '')),
                           contact_email       = COALESCE(NULLIF(contact_email, ''),  NULLIF(?, '')),
                           contact_phone       = COALESCE(NULLIF(contact_phone, ''),  NULLIF(?, '')),
                           street              = COALESCE(NULLIF(street, ''),         NULLIF(?, '')),
                           city                = COALESCE(NULLIF(city, ''),           NULLIF(?, '')),
                           postal_code         = COALESCE(NULLIF(postal_code, ''),    NULLIF(?, '')),
                           contact_mobile      = COALESCE(NULLIF(contact_mobile, ''), NULLIF(?, '')),
                           bank_account        = COALESCE(NULLIF(bank_account, ''),   NULLIF(?, '')),
                           last_wfirma_sync_at = ?,
                           wfirma_sync_source  = ?,
                           updated_at          = ?
                       WHERE id = ?""",
                (nm, cty,
                 vid, addr, em, ph,
                 str_, cit, zp, mob, bnk,
                 now, src, now, row_id),
            )
            action = "updated"
        conn.commit()

    rec = get_supplier(db_path, row_id)
    return {"id": row_id, "action": action, "row": rec}

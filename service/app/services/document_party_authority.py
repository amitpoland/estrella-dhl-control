"""B-020 — Document-party contractor authority for consumers.

Canonical source: ``shipment_documents`` rows written by intake (#1198
document-slot authority). Batch-level consumers MUST NOT pick
``LIMIT 1`` over non-empty contractor columns — AWB/SAD/PZ rows may
*inherit* IDs and SQLite row order is not a business rule.

Roles
-----
- ``supplier`` → column ``supplier_contractor_id``; authority document
  types: purchase_invoice, purchase_packing_list
- ``client``   → column ``client_contractor_id``; authority document
  types: sales_packing_list, sales_invoice

Statuses
--------
- ``NONE``      — no non-empty ID on authority documents
- ``SINGLE``    — exactly one distinct ID
- ``AMBIGUOUS`` — two or more distinct IDs (fail closed at consumer)

When ``document_id`` is supplied, only that row is read (document-specific
contractor) — multiparty batches remain usable with explicit context.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

STATUS_NONE = "NONE"
STATUS_SINGLE = "SINGLE"
STATUS_AMBIGUOUS = "AMBIGUOUS"

ROLE_SUPPLIER = "supplier"
ROLE_CLIENT = "client"

_ROLE_COLUMN = {
    ROLE_SUPPLIER: "supplier_contractor_id",
    ROLE_CLIENT: "client_contractor_id",
}

# Inherited / derived document types are NOT batch-level party authority.
SUPPLIER_AUTHORITY_TYPES: Sequence[str] = (
    "purchase_invoice",
    "purchase_packing_list",
)
CLIENT_AUTHORITY_TYPES: Sequence[str] = (
    "sales_packing_list",
    "sales_invoice",
)

_ROLE_TYPES = {
    ROLE_SUPPLIER: SUPPLIER_AUTHORITY_TYPES,
    ROLE_CLIENT: CLIENT_AUTHORITY_TYPES,
}


@dataclass(frozen=True)
class PartyResolution:
    status: str
    contractor_id: Optional[str]
    candidates: tuple  # distinct IDs observed (sorted)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SINGLE and bool(self.contractor_id)


def _column_for(role: str) -> str:
    try:
        return _ROLE_COLUMN[role]
    except KeyError as exc:
        raise ValueError(f"unknown party role: {role!r}") from exc


def _types_for(role: str) -> Sequence[str]:
    try:
        return _ROLE_TYPES[role]
    except KeyError as exc:
        raise ValueError(f"unknown party role: {role!r}") from exc


def list_distinct_party_ids(
    docs_db: Path,
    batch_id: str,
    role: str,
    *,
    document_types: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return sorted distinct non-empty contractor IDs for ``role`` on the batch."""
    if not batch_id or not Path(docs_db).exists():
        return []
    col = _column_for(role)
    types = tuple(document_types) if document_types is not None else tuple(_types_for(role))
    if not types:
        return []
    placeholders = ",".join("?" for _ in types)
    sql = (
        f"SELECT DISTINCT {col} AS cid FROM shipment_documents "
        f"WHERE batch_id=? AND document_type IN ({placeholders}) "
        f"AND {col} IS NOT NULL AND TRIM({col}) != ''"
    )
    try:
        con = sqlite3.connect(str(docs_db))
        try:
            rows = con.execute(sql, (batch_id, *types)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    ids = sorted({str(r[0]).strip() for r in rows if r and str(r[0]).strip()})
    return ids


def resolve_party_id(
    docs_db: Path,
    batch_id: str,
    role: str,
    *,
    document_id: Optional[str] = None,
    document_types: Optional[Sequence[str]] = None,
) -> PartyResolution:
    """Resolve a single party contractor ID or fail closed as AMBIGUOUS/NONE.

    ``document_id`` — when set, read only that shipment_documents row's column
    for ``role`` (document-specific contractor). Types filter is ignored.
    """
    col = _column_for(role)
    db = Path(docs_db)
    if not batch_id or not db.exists():
        return PartyResolution(STATUS_NONE, None, ())

    if document_id:
        try:
            con = sqlite3.connect(str(db))
            try:
                row = con.execute(
                    f"SELECT {col} AS cid FROM shipment_documents "
                    "WHERE id=? AND batch_id=?",
                    (document_id, batch_id),
                ).fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            return PartyResolution(STATUS_NONE, None, ())
        cid = (str(row[0]).strip() if row and row[0] is not None else "")
        if not cid:
            return PartyResolution(STATUS_NONE, None, ())
        return PartyResolution(STATUS_SINGLE, cid, (cid,))

    ids = list_distinct_party_ids(
        db, batch_id, role, document_types=document_types
    )
    if not ids:
        return PartyResolution(STATUS_NONE, None, ())
    if len(ids) == 1:
        return PartyResolution(STATUS_SINGLE, ids[0], tuple(ids))
    return PartyResolution(STATUS_AMBIGUOUS, None, tuple(ids))


__all__ = [
    "STATUS_NONE",
    "STATUS_SINGLE",
    "STATUS_AMBIGUOUS",
    "ROLE_SUPPLIER",
    "ROLE_CLIENT",
    "SUPPLIER_AUTHORITY_TYPES",
    "CLIENT_AUTHORITY_TYPES",
    "PartyResolution",
    "list_distinct_party_ids",
    "resolve_party_id",
]

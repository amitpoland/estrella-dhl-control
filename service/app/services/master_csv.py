"""
master_csv.py — Shared CSV import/export helper for the Master Data domains
(Customer Master + Suppliers), EJ Dashboard Stabilization Wave 5.

ONE authority for CSV shaping so Clients and Suppliers share identical safety
behaviour. No new database, no new writer: the import routes reuse each domain's
existing upsert/create/update writers; this module only (a) serialises rows to
CSV bytes and (b) parses uploaded CSV into row dicts.

Safety properties:
  * Formula-injection guard on EVERY exported cell — a value beginning with
    ``= + - @`` (or a leading tab/CR) is prefixed with an apostrophe so Excel /
    Sheets never evaluate uploaded content as a formula (CSV-injection defence).
  * UTF-8 BOM output so Excel opens PL/EU diacritics correctly, returned as
    BYTES via Response (never Path.write_text — that doubles CRLF on py3.9,
    see reference-windows-csv-crlf-write-text).
  * Column allow-lists derive from the real dataclass fields minus system-managed
    columns, so a CSV can never write VIES results, timestamps, sync provenance,
    or the soft-delete flag. Identity key column is always first.
"""
from __future__ import annotations

import csv
import io
from dataclasses import fields
from typing import Any, Dict, List, Tuple

# ── Column policy ────────────────────────────────────────────────────────────
CUSTOMER_KEY = "bill_to_contractor_id"
SUPPLIER_KEY = "supplier_code"

# System-managed columns: exported for reference but NEVER writable via import.
_CUSTOMER_SYSTEM_COLS = {
    "id", "vat_eu_valid", "vat_eu_validated_at", "created_at", "updated_at",
    "last_wfirma_sync_at", "wfirma_sync_source", "deleted_at",
}
_SUPPLIER_SYSTEM_COLS = {
    "id", "created_at", "updated_at", "last_wfirma_sync_at",
    "wfirma_sync_source", "deleted_at",
}
# ``active`` is exported (informational) but not writable via CSV — activation
# state is owned by the delete/restore endpoints, not a spreadsheet.
_CUSTOMER_IMPORT_READONLY = _CUSTOMER_SYSTEM_COLS | {"active"}
_SUPPLIER_IMPORT_READONLY = _SUPPLIER_SYSTEM_COLS | {"active"}

_FORMULA_LEAD = ("=", "+", "-", "@")
_WHITESPACE_LEAD = ("\t", "\r", "\n")

# Import ceilings (defence-in-depth against memory / SQLite-write-lock DoS).
MAX_IMPORT_BYTES = 5 * 1024 * 1024   # 5 MB upload
MAX_IMPORT_ROWS = 5000               # per-request row cap


def _ordered_columns(dataclass_type: Any, key: str) -> List[str]:
    """All dataclass field names, identity key first, original order otherwise."""
    names = [f.name for f in fields(dataclass_type)]
    rest = [n for n in names if n != key]
    return [key] + rest if key in names else names


def customer_columns() -> List[str]:
    from .customer_master_db import CustomerMaster
    return _ordered_columns(CustomerMaster, CUSTOMER_KEY)


def supplier_columns() -> List[str]:
    from .suppliers_db import Supplier
    return _ordered_columns(Supplier, SUPPLIER_KEY)


def customer_import_writable() -> List[str]:
    return [c for c in customer_columns() if c not in _CUSTOMER_IMPORT_READONLY]


def supplier_import_writable() -> List[str]:
    return [c for c in supplier_columns() if c not in _SUPPLIER_IMPORT_READONLY]


# ── Serialisation ────────────────────────────────────────────────────────────
def _safe_cell(v: Any) -> str:
    """Stringify a cell, neutralising CSV-injection formula leads."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    s = str(v)
    if s and (s[0] in _FORMULA_LEAD or s[0] in _WHITESPACE_LEAD):
        return "'" + s
    return s


def rows_to_csv(rows: List[Dict[str, Any]], columns: List[str]) -> bytes:
    """Render dict rows to CSV bytes (UTF-8 BOM, CRLF, injection-safe)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_safe_cell(r.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8-sig")


def parse_csv(raw: bytes) -> List[Tuple[int, Dict[str, str]]]:
    """Parse uploaded CSV bytes into ``(line_number, row_dict)`` tuples.

    ``line_number`` is 1-based counting the header as line 1, so the first data
    row is line 2 — matching what an operator sees in a spreadsheet. Blank
    header columns are dropped; all values are stripped.
    """
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out: List[Tuple[int, Dict[str, str]]] = []
    for i, row in enumerate(reader, start=2):
        clean: Dict[str, str] = {}
        for k, v in row.items():
            if k is None:
                continue
            kk = k.strip()
            if not kk:
                continue
            clean[kk] = v.strip() if isinstance(v, str) else ("" if v is None else str(v))
        out.append((i, clean))
    return out


async def read_capped(file: Any, max_bytes: int = MAX_IMPORT_BYTES) -> Any:
    """Read an UploadFile in bounded chunks, returning bytes or ``None`` if the
    stream exceeds ``max_bytes``. Caps memory at ~max_bytes+64 KB instead of
    buffering an arbitrarily large body before the size gate (DoS defence)."""
    buf = bytearray()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            return None
    return bytes(buf)


def project_writable(row: Dict[str, str], writable: List[str]) -> Dict[str, str]:
    """Keep only writable columns that are actually present + non-empty.

    Empty cells are dropped (not written as empty strings) so a partial CSV
    performs a partial update rather than blanking stored fields.
    """
    ws = set(writable)
    return {k: v for k, v in row.items() if k in ws and v != ""}

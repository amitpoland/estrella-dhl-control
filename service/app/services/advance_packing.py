"""
advance_packing.py — Pre-shipment ("advance") packing lists.

WHAT THIS IS NOT
----------------
Not a second packing authority.  Every row this module writes goes into the
one packing authority — ``packing_db`` (``packing_documents`` +
``packing_lines``) — through that module's own writers.  Nothing here holds
business truth of its own; this file is policy over the existing store:
which rows are provisional, what may not be derived from them, and how they
are reconciled against the real shipment when it finally arrives.

THE PROBLEM
-----------
A supplier sends the packing list of what they are ABOUT to ship, days or
weeks before dispatch.  At that moment there is:

  * no AWB          -> no ``SHIPMENT_<tracking>_<YYYY-MM>_<hex>`` batch id,
  * no invoice      -> no ``product_code`` (ADR-024 mints product identity as
                      ``invoice_no-N``; inventing one here would be inventing
                      an external id),
  * no goods        -> nothing to receive, reserve, value or declare.

So an advance list is EXPECTED quantity by design_no and nothing more.

WHERE IT LIVES
--------------
``packing_documents.doc_stage = 'advance'`` under a batch id of the form
``ADVANCE_<YYYY-MM>_<8hex>``.  That batch deliberately has NO directory under
``storage/outputs/``: the shipment list is a directory scan of that folder
(``routes_dashboard.list_batches``), so an advance list can never show up as
a phantom shipment.  Every existing packing reader is called with a concrete
shipment batch id and therefore never sees these rows either.

WHAT ADVANCE ROWS MAY NEVER DO
------------------------------
  * seed inventory state — ``seed_purchase_transit`` is NOT called; goods that
    do not exist cannot be PURCHASE_TRANSIT,
  * carry a ``scan_code`` — that is the identity of a physical piece,
  * carry a ``product_code`` — see above,
  * feed product_master (CPA), wFirma, PZ, proforma or customs.

RECONCILIATION
--------------
When the shipment finally arrives it goes through the ordinary intake and
gets its own real batch and final packing list.  The operator then LINKS the
advance document to that batch (``link_to_batch``).  ``reconcile`` compares
expected (advance) against actual (final) per design_no.  Linking never
rewrites either document — the advance list stays exactly as the supplier
sent it, which is the whole point of keeping it.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import packing_db as pdb
from .invoice_packing_extractor import extract_packing

log = get_logger(__name__)

ADVANCE = "advance"
_ADVANCE_RE = re.compile(r"^ADVANCE_\d{4}-\d{2}_[0-9a-f]{8}$")


def new_advance_id() -> str:
    """``ADVANCE_<YYYY-MM>_<8hex>`` — the same shape family as SHIPMENT_*, so
    it reads as a batch id everywhere, but it is never a shipment."""
    return (f"ADVANCE_{datetime.now(timezone.utc):%Y-%m}"
            f"_{uuid.uuid4().hex[:8]}")


def is_advance_batch(batch_id: str) -> bool:
    return bool(_ADVANCE_RE.match(batch_id or ""))


def _storage() -> Path:
    return Path(settings.storage_root)


def advance_source_dir(batch_id: str) -> Path:
    """Advance sources live OUTSIDE outputs/ so the shipment directory scan
    never sees them."""
    return _storage() / "advance_packing" / batch_id


# ── Ingest ──────────────────────────────────────────────────────────────────

def ingest_advance(
    file_path: Path,
    *,
    supplier_id: Optional[int] = None,
    batch_id: Optional[str] = None,
    operator: str = "",
) -> Dict[str, Any]:
    """Parse a pre-shipment packing list and store it as an advance document.

    Uses the plain parser (``extract_packing``) rather than
    ``process_packing_upload``: the latter matches rows against the batch's
    purchase invoice to mint product_code, and an advance list has no invoice
    to match against.  Rows therefore keep design_no + quantity and nothing
    that would pass for product identity.

    Idempotent: re-ingesting the same file into the same advance batch dedups
    on the document's source_file_hash and on packing_db's own line key.
    """
    rows, parser_name, parser_version, diagnostic = extract_packing(
        file_path, supplier_id=supplier_id,
    )

    bid = batch_id or new_advance_id()
    if not is_advance_batch(bid):
        raise ValueError(f"not an advance batch id: {bid!r}")

    diagnostic = dict(diagnostic or {})
    diagnostic["doc_stage"] = ADVANCE
    diagnostic["ingested_by"] = operator

    doc_id = pdb.upsert_packing_document(
        batch_id          = bid,
        invoice_no        = "",          # there is no invoice yet
        source_file_path  = str(file_path),
        source_file_hash  = hashlib.sha256(file_path.read_bytes()).hexdigest(),
        parser_name       = parser_name,
        parser_version    = parser_version,
        extraction_status = "extracted" if rows else "empty",
        parser_diagnostic = diagnostic,
        supplier_id       = supplier_id,
        doc_stage         = ADVANCE,
    )

    line_records: List[Dict[str, Any]] = []
    for row in rows:
        line_records.append({
            "packing_document_id": doc_id,
            "batch_id":     bid,
            "invoice_no":   "",
            "product_code": None,        # minted at final invoice, never here
            "design_no":    str(row.get("design_no") or ""),
            "batch_no":     str(row.get("batch_no") or ""),
            "bag_id":       str(row.get("bag_id") or ""),
            "tray_id":      str(row.get("tray_id") or ""),
            "item_type":    str(row.get("item_type") or ""),
            "uom":          str(row.get("uom") or ""),
            "quantity":     _f(row.get("quantity")),
            "gross_weight": _f(row.get("gross_weight")),
            "net_weight":   _f(row.get("net_weight")),
            "metal":        str(row.get("metal") or ""),
            "karat":        str(row.get("karat") or ""),
            "metal_color":  str(row.get("metal_color") or ""),
            "stone_type":   str(row.get("stone_type") or ""),
            "quality_string": str(row.get("quality_string") or ""),
            "size":         str(row.get("size") or ""),
            "diamond_weight": _f(row.get("diamond_weight")),
            "color_weight": _f(row.get("color_weight")),
            "remarks":      str(row.get("remarks") or ""),
            "pack_sr":      row.get("pack_sr"),
            "extracted_confidence": _f(row.get("extracted_confidence")),
            "requires_manual_review": bool(row.get("requires_manual_review", False)),
        })

    stored = pdb.upsert_packing_lines(line_records)
    _null_scan_codes(bid)

    return {
        "batch_id":    bid,
        "document_id": doc_id,
        "doc_stage":   ADVANCE,
        "rows_parsed": len(rows),
        "rows_stored": stored,
        "parser":      f"{parser_name} {parser_version}".strip(),
        "diagnostic":  diagnostic,
    }


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _null_scan_codes(batch_id: str) -> None:
    """Advance rows describe goods that do not exist, so they carry no piece
    identity.  ``_compute_scan_code`` would otherwise hand them a degenerate
    ``|<design_no>`` code that an unscoped scan lookup could resolve."""
    if pdb._db_path is None:
        return
    with pdb._lock:
        with pdb._connect() as con:
            con.execute("UPDATE packing_lines SET scan_code=NULL WHERE batch_id=?",
                        (batch_id,))


# ── Read ────────────────────────────────────────────────────────────────────

def list_advance_documents(
    *, linked: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Advance documents, newest first.  ``linked=False`` returns only the
    ones still waiting for their shipment."""
    if pdb._db_path is None:
        return []
    sql = "SELECT * FROM packing_documents WHERE doc_stage=? "
    args: List[Any] = [ADVANCE]
    if linked is True:
        sql += "AND linked_batch_id != '' "
    elif linked is False:
        sql += "AND linked_batch_id = '' "
    sql += "ORDER BY created_at DESC"
    with pdb._connect() as con:
        rows = con.execute(sql, args).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["line_count"] = con.execute(
                "SELECT COUNT(*) FROM packing_lines WHERE packing_document_id=?",
                (d["id"],),
            ).fetchone()[0]
            out.append(d)
    return out


def get_advance_document(document_id: str) -> Optional[Dict[str, Any]]:
    doc = pdb.get_packing_document(document_id)
    if not doc or doc.get("doc_stage") != ADVANCE:
        return None
    return doc


# ── Link ────────────────────────────────────────────────────────────────────

def link_to_batch(document_id: str, batch_id: str, *,
                  operator: str = "") -> Dict[str, Any]:
    """Record which real shipment fulfilled this advance document.

    Neither document is rewritten.  The link is the only thing that changes,
    and it is set on an advance document exactly once — re-linking to a
    different batch is refused, because the first link is the operator's
    statement about what actually arrived.
    """
    doc = get_advance_document(document_id)
    if doc is None:
        raise ValueError(f"no advance packing document {document_id!r}")
    if is_advance_batch(batch_id):
        raise ValueError("an advance document must be linked to a real shipment batch")
    if "/" in batch_id or "\\" in batch_id or ".." in batch_id:
        raise ValueError("invalid batch_id")
    if not (_storage() / "outputs" / batch_id).is_dir():
        raise ValueError(f"shipment batch {batch_id!r} does not exist")

    current = (doc.get("linked_batch_id") or "").strip()
    if current and current != batch_id:
        raise ValueError(
            f"already linked to {current!r}; unlink is deliberately not offered"
        )
    if current == batch_id:
        return {"document_id": document_id, "linked_batch_id": batch_id,
                "changed": False}

    with pdb._lock:
        with pdb._connect() as con:
            con.execute(
                "UPDATE packing_documents SET linked_batch_id=?, updated_at=? "
                "WHERE id=?",
                (batch_id, pdb._now_iso(), document_id),
            )
    log.info("advance packing %s linked to shipment %s by %s",
             document_id, batch_id, operator or "unknown")
    return {"document_id": document_id, "linked_batch_id": batch_id, "changed": True}


# ── Reconcile ───────────────────────────────────────────────────────────────

def reconcile(document_id: str) -> Dict[str, Any]:
    """Expected (advance) vs actual (final purchase packing) by design_no.

    Read-only.  Compares against the linked shipment's own packing lines —
    the same rows ``warehouse_receipt.expected_lines`` treats as the import
    expectation — so this answers "did the supplier ship what they announced",
    NOT "did we physically receive it".  That second question is already owned
    by ``warehouse_receipt`` (accepted_qty / shortage_qty) and is deliberately
    not duplicated here.
    """
    doc = get_advance_document(document_id)
    if doc is None:
        raise ValueError(f"no advance packing document {document_id!r}")
    batch_id = (doc.get("linked_batch_id") or "").strip()
    if not batch_id:
        raise ValueError("advance document is not linked to a shipment yet")

    expected = _qty_by_design(pdb.get_packing_lines_for_batch(doc["batch_id"]))
    actual   = _qty_by_design(pdb.get_packing_lines_for_batch(batch_id))

    lines: List[Dict[str, Any]] = []
    for design in sorted(set(expected) | set(actual)):
        exp = expected.get(design, 0.0)
        act = actual.get(design, 0.0)
        lines.append({
            "design_no":    design,
            "expected_qty": exp,
            "actual_qty":   act,
            "variance_qty": round(act - exp, 4),
            "status":       _variance_status(exp, act),
        })

    counts: Dict[str, int] = {}
    for ln in lines:
        counts[ln["status"]] = counts.get(ln["status"], 0) + 1

    return {
        "document_id":       document_id,
        "advance_batch_id":  doc["batch_id"],
        "shipment_batch_id": batch_id,
        "lines":             lines,
        "summary": {
            "designs":        len(lines),
            "expected_total": round(sum(expected.values()), 4),
            "actual_total":   round(sum(actual.values()), 4),
            "by_status":      counts,
            "fully_matched":  all(ln["status"] == "match" for ln in lines),
        },
    }


def _variance_status(expected: float, actual: float) -> str:
    if abs(actual - expected) < 1e-9:
        return "match"
    if actual == 0:
        return "missing"      # announced, never shipped
    if expected == 0:
        return "extra"        # shipped, never announced
    return "short" if actual < expected else "over"


def _qty_by_design(lines: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for ln in lines:
        d = str(ln.get("design_no") or "").strip().upper()
        if not d:
            continue
        out[d] = round(out.get(d, 0.0) + _f(ln.get("quantity")), 4)
    return out

"""
design_product_bridge.py — populate design_product_mapping from packing_lines.

Each `packing_lines` row carries BOTH the invoice-line `product_code`
(e.g. ``EJL/26-27/121-1``) AND the sales/design `design_no`
(e.g. ``CSTR07718``). The bridge data therefore exists in packing_lines on
every batch, but `design_product_mapping` (the registry the Proforma
preview, reservation worker, and future resolvers consult) was never
populated by an automatic observer.

This module's single job is to project the `(design_no → product_code)`
pairs from `packing_lines` into `design_product_mapping`. It is
idempotent — re-running on the same batch never duplicates rows. It is
read-only on the source side (does not mutate packing_lines).

It also exposes a query helper that returns ALL product_codes a design_no
maps to, so callers can detect ambiguity (e.g. ``PND`` mapped to both
``EJL/26-27/123-2`` and ``EJL/26-27/123-3``) explicitly rather than
silently pick the last one.

Public API
----------
- ``populate_from_packing(batch_id, *, packing_db_path=None,
  reservation_db_path=None) -> Dict[str, Any]``
    Returns a summary: ``{batch_id, scanned, inserted, updated, skipped,
    ambiguous_design_codes}``.

- ``get_product_codes_for_design(design_no, *, db_path=None) -> List[str]``
    Returns every distinct product_code currently mapped to the design.
    Empty list when the bridge has no entry.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from . import reservation_db

log = logging.getLogger(__name__)


def _resolve_packing_db_path(override: Optional[Path]) -> Optional[Path]:
    if override is not None:
        return Path(override)
    from . import packing_db as pdb
    return pdb._db_path


def _resolve_reservation_db_path(override: Optional[Path]) -> Optional[Path]:
    if override is not None:
        return Path(override)
    # Standard project location
    return settings.storage_root / "reservation_queue.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def populate_from_packing(
    batch_id: str,
    *,
    packing_db_path:     Optional[Path] = None,
    reservation_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Project (design_no, product_code) pairs from packing_lines for the
    given batch into design_product_mapping. Idempotent.

    Args:
        batch_id: shipment batch id; rows are filtered by packing_lines.batch_id.
        packing_db_path: override for packing.db (defaults to packing_db._db_path)
        reservation_db_path: override for reservation_queue.db
    Returns:
        {
          'batch_id': str,
          'scanned': int,                           # distinct pairs found
          'inserted': int,                          # new rows added
          'updated': int,                           # existing rows refreshed
          'skipped': int,                           # invalid/empty pairs
          'ambiguous_design_codes': dict[str, list[str]],
              # design_no → all product_codes mapped to it (only when len>1)
          'errors': list[str],                      # non-fatal errors
        }

    Idempotency: the underlying ``reservation_db.upsert_design_mapping``
    is keyed by ``UNIQUE(design_no, product_code)`` and refreshes
    ``updated_at`` on re-run. Repeated calls with the same packing_lines
    state produce ``inserted=0`` after the first call.

    Source field is set to ``"packing_bridge"`` so this provenance can be
    distinguished from the legacy ``"purchase_packing"`` source written
    by the older reservation_worker importer.
    """
    out: Dict[str, Any] = {
        "batch_id":              batch_id,
        "scanned":               0,
        "inserted":              0,
        "updated":               0,
        "skipped":               0,
        "ambiguous_design_codes": {},
        "errors":                [],
    }

    pdb_path = _resolve_packing_db_path(packing_db_path)
    if pdb_path is None or not Path(pdb_path).exists():
        out["errors"].append(f"packing_db not initialised at {pdb_path}")
        return out
    rdb_path = _resolve_reservation_db_path(reservation_db_path)
    if rdb_path is None:
        out["errors"].append("reservation_db path could not be resolved")
        return out

    # ── Scan packing_lines for this batch ──────────────────────────────────
    try:
        with sqlite3.connect(str(pdb_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT DISTINCT design_no, product_code "
                "FROM packing_lines WHERE batch_id=?",
                (batch_id,),
            ).fetchall()
    except Exception as exc:
        out["errors"].append(f"packing_db read failed: {exc}")
        return out

    # Build accurate (design_no → product_codes) ambiguity map for this batch
    # alongside the upsert loop. Any design that maps to >1 product_code
    # within the same batch is flagged. (PND → 123-2 + 123-3 is the
    # canonical case from AWB 6049349806.)
    pairs_seen: Dict[str, set] = {}
    for r in rows:
        design = (r["design_no"]    or "").strip()
        prod   = (r["product_code"] or "").strip()
        if not design or not prod:
            out["skipped"] += 1
            continue
        out["scanned"] += 1
        pairs_seen.setdefault(design, set()).add(prod)

        # Idempotent upsert via the existing reservation_db helper.
        try:
            existing = reservation_db.get_product_code_by_design_no(
                rdb_path, design,
            )
            # Note: get_product_code_by_design_no returns the most recent
            # mapping, but uniqueness is on (design_no, product_code) so
            # we still call upsert which checks the precise pair.
            row_id = reservation_db.upsert_design_mapping(
                rdb_path,
                design_no=design,
                product_code=prod,
                confidence="locked",
                source="packing_bridge",
            )
            # Re-query to determine if this was insert vs update by
            # checking whether the pair existed BEFORE this upsert.
            with sqlite3.connect(str(rdb_path)) as con:
                con.row_factory = sqlite3.Row
                # Whether a row existed BEFORE the upsert: we can't know
                # post-hoc with strict accuracy, so use created_at vs
                # updated_at proximity as a heuristic.
                row = con.execute(
                    "SELECT created_at, updated_at FROM design_product_mapping "
                    "WHERE design_no=? AND product_code=?",
                    (design, prod),
                ).fetchone()
                if row and row["created_at"] == row["updated_at"]:
                    out["inserted"] += 1
                else:
                    out["updated"] += 1
        except Exception as exc:
            out["errors"].append(f"upsert failed for {design}->{prod}: {exc}")

    # Surface ambiguity (design with >1 product_code in same batch)
    for design, prods in pairs_seen.items():
        if len(prods) > 1:
            out["ambiguous_design_codes"][design] = sorted(prods)

    log.info(
        "[design_product_bridge] batch=%s scanned=%d inserted=%d updated=%d "
        "skipped=%d ambiguous=%d errors=%d",
        batch_id, out["scanned"], out["inserted"], out["updated"],
        out["skipped"], len(out["ambiguous_design_codes"]), len(out["errors"]),
    )
    return out


def get_product_codes_for_design(
    design_no: str,
    *,
    db_path: Optional[Path] = None,
) -> List[str]:
    """Return EVERY product_code mapped to *design_no* in
    design_product_mapping, sorted. Empty list if the bridge has no entry.
    Use ``len(result) > 1`` to detect ambiguity at the call site."""
    rdb_path = _resolve_reservation_db_path(db_path)
    if rdb_path is None or not Path(rdb_path).exists():
        return []
    try:
        with sqlite3.connect(str(rdb_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT DISTINCT product_code FROM design_product_mapping "
                "WHERE design_no=? ORDER BY product_code",
                (design_no,),
            ).fetchall()
        return [r["product_code"] for r in rows if r["product_code"]]
    except Exception as exc:
        log.warning("[design_product_bridge] lookup failed for %s: %s",
                    design_no, exc)
        return []

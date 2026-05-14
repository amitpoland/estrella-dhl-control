"""
backfill_product_identity.py — Write-mode product identity backfill.

Reads all outputs/SHIPMENT_*/pz_rows.json files and populates
product_descriptions in document.db with canonical product identities.

SAFETY CONTRACT
---------------
- Dry-run is the DEFAULT.  Pass --write to commit changes.
- 417G product codes are ALWAYS skipped (non-unique key, corruption risk).
- Generic descriptions are ALWAYS blocked.
- Existing rows with source='manual' are NEVER overwritten.
- First-seen dedup: the same EJL product_code encountered in multiple
  batch folders is written only once (first occurrence wins).
- Stub deletion (--write only): removes legacy generic stubs keyed by
  item_type names (RING, PENDANT, BRACELET, EARRINGS) that have
  source != 'manual'.

Usage
-----
    # Mandatory first step — review before any writes:
    python service/scripts/backfill_product_identity.py

    # Write mode (run only after reviewing dry-run output):
    python service/scripts/backfill_product_identity.py --write

    # Custom paths:
    python service/scripts/backfill_product_identity.py \\
        --outputs-root "C:/PZ/storage/outputs" \\
        --db-path "C:/PZ/storage/document.db" \\
        --write --verbose

Rollback
--------
    sqlite3 C:/PZ/storage/document.db \\
        "DELETE FROM product_descriptions WHERE source='pz_rows_backfill';"

    This removes all backfill rows without touching source='manual' rows.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Path bootstrap ────────────────────────────────────────────────────────────

_SCRIPT_DIR  = Path(__file__).resolve().parent
_SERVICE_DIR = _SCRIPT_DIR.parent           # service/
_APP_DIR     = _SERVICE_DIR / "app"

if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

# ── Imports ───────────────────────────────────────────────────────────────────

try:
    from app.services.product_identity_engine import (
        resolve_product_identity,
        is_generic_description,
        FORBIDDEN_PRODUCT_CODE_KEYS,
    )
    _ENGINE_AVAILABLE = True
except ImportError as _e:
    print(f"[ERROR] Cannot import product_identity_engine: {_e}", file=sys.stderr)
    _ENGINE_AVAILABLE = False

try:
    from app.services.document_db import upsert_product_identity_from_backfill
    _DB_AVAILABLE = True
except ImportError as _e:
    print(f"[ERROR] Cannot import upsert_product_identity_from_backfill: {_e}", file=sys.stderr)
    _DB_AVAILABLE = False

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_OUTPUTS_ROOT = Path("C:/PZ/storage/outputs")
_DEFAULT_DB_PATH      = Path("C:/PZ/storage/documents.db")   # note: documents.db (with 's')

# Generic stubs that must be removed from product_descriptions before backfill.
# These are keyed by item_type names — they are legacy noise, never real codes.
_GENERIC_STUBS: Tuple[str, ...] = ("RING", "PENDANT", "BRACELET", "EARRINGS")

import json


# ── Stub cleanup ──────────────────────────────────────────────────────────────

def _run_stub_cleanup(
    con: sqlite3.Connection,
    *,
    dry_run: bool,
    verbose: bool,
) -> Dict[str, object]:
    """
    Delete legacy generic stubs from product_descriptions.

    Only rows with source != 'manual' are deleted.  The pre-count assertion
    guards against accidentally deleting legitimate rows.

    Returns a dict with keys: found, manual_protected, would_delete / deleted.
    """
    placeholders = ",".join("?" * len(_GENERIC_STUBS))
    rows = con.execute(
        f"SELECT product_code, source FROM product_descriptions "
        f"WHERE product_code IN ({placeholders})",
        _GENERIC_STUBS,
    ).fetchall()

    stubs_found     = [dict(r) for r in rows]
    manual_stubs    = [r for r in stubs_found if r["source"] == "manual"]
    deletable_stubs = [r for r in stubs_found if r["source"] != "manual"]

    if verbose and stubs_found:
        for s in stubs_found:
            tag = " [manual — PROTECTED]" if s["source"] == "manual" else ""
            print(f"  stub: {s['product_code']!r} source={s['source']!r}{tag}")

    if dry_run:
        return {
            "found":            len(stubs_found),
            "manual_protected": len(manual_stubs),
            "would_delete":     len(deletable_stubs),
        }

    # Safety: never delete more than len(_GENERIC_STUBS) rows
    if len(deletable_stubs) > len(_GENERIC_STUBS):
        print(
            f"[ERROR] Stub pre-count check failed: found {len(deletable_stubs)} "
            f"deletable stubs (expected ≤ {len(_GENERIC_STUBS)}). Aborting stub deletion.",
            file=sys.stderr,
        )
        return {
            "found":            len(stubs_found),
            "manual_protected": len(manual_stubs),
            "deleted":          0,
            "error":            "pre_count_exceeded",
        }

    con.execute(
        f"DELETE FROM product_descriptions "
        f"WHERE product_code IN ({placeholders}) AND source != 'manual'",
        _GENERIC_STUBS,
    )
    return {
        "found":            len(stubs_found),
        "manual_protected": len(manual_stubs),
        "deleted":          len(deletable_stubs),
    }


# ── Main backfill scan ────────────────────────────────────────────────────────

def run_backfill(
    outputs_root: Path,
    db_path: Path,
    *,
    dry_run: bool = True,
    verbose: bool = False,
) -> Dict[str, object]:
    """
    Scan pz_rows.json files and (in write mode) upsert into product_descriptions.

    Returns a summary dict with all disposition counts.
    """
    if not _ENGINE_AVAILABLE:
        return {"error": "product_identity_engine not available"}
    if not _DB_AVAILABLE:
        return {"error": "upsert_product_identity_from_backfill not available"}

    outputs_root = Path(outputs_root)
    db_path      = Path(db_path)

    # ── DB connection ──────────────────────────────────────────────────────
    if dry_run:
        # Dry-run still opens DB read-only to check existing rows for dispositions.
        # Use the real DB if it exists; if not, operate without row-existence info.
        if db_path.exists():
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
        else:
            con = None
    else:
        if not db_path.exists():
            print(f"[ERROR] DB not found: {db_path}", file=sys.stderr)
            return {"error": f"db_not_found: {db_path}"}
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")

    try:
        return _run_with_con(
            con=con,
            outputs_root=outputs_root,
            db_path=db_path,
            dry_run=dry_run,
            verbose=verbose,
        )
    finally:
        if con is not None:
            con.close()


def _run_with_con(
    con: Optional[sqlite3.Connection],
    outputs_root: Path,
    db_path: Path,
    *,
    dry_run: bool,
    verbose: bool,
) -> Dict[str, object]:

    # ── Stub cleanup phase ─────────────────────────────────────────────────
    if con is not None:
        stub_result = _run_stub_cleanup(con, dry_run=dry_run, verbose=verbose)
    else:
        stub_result = {"found": 0, "manual_protected": 0,
                       "would_delete" if dry_run else "deleted": 0}

    # ── Scan batch folders ─────────────────────────────────────────────────
    batch_dirs: List[Path] = []
    if outputs_root.exists():
        batch_dirs = sorted(
            d for d in outputs_root.iterdir()
            if d.is_dir() and d.name.startswith("SHIPMENT_")
        )

    batches_scanned      = len(batch_dirs)
    batches_with_pz_rows = 0
    total_rows           = 0

    # Disposition counters
    n_inserted         = 0
    n_updated          = 0
    n_skipped_manual   = 0
    n_skipped_417g     = 0
    n_skipped_generic  = 0
    n_skipped_dup      = 0
    n_error            = 0

    # Confidence distribution (for wFirma-eligible rows)
    n_high   = 0
    n_medium = 0
    n_low    = 0

    # Dedup: first-seen EJL product_code wins
    seen_codes: Dict[str, str] = {}   # product_code → batch_id_first_seen

    for batch_dir in batch_dirs:
        pz_file = batch_dir / "pz_rows.json"
        if not pz_file.exists():
            continue

        try:
            rows = json.loads(pz_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] {pz_file}: {exc}", file=sys.stderr)
            continue

        if not isinstance(rows, list) or not rows:
            continue

        batches_with_pz_rows += 1
        batch_id = batch_dir.name

        for row in rows:
            if not isinstance(row, dict):
                continue
            total_rows += 1

            pc          = str(row.get("product_code") or "").strip()
            item_type   = str(row.get("item_type")    or "").strip()
            pl_desc     = str(row.get("pl_desc")      or "").strip()
            desc_en     = str(row.get("description_en") or "").strip()

            # Resolve identity (read-only engine call)
            identity = resolve_product_identity(
                pc,
                item_type=item_type,
                description_pl=pl_desc,
                description_en=desc_en,
                source="pz_rows_backfill",
            )

            # Track confidence
            if identity.confidence == "HIGH":
                n_high += 1
            elif identity.confidence == "MEDIUM":
                n_medium += 1
            else:
                n_low += 1

            # ── Dedup: first-seen wins ──────────────────────────────────
            if pc in seen_codes:
                n_skipped_dup += 1
                if verbose:
                    print(
                        f"  [DUP] {pc:<40} already seen in "
                        f"{seen_codes[pc]!r}, skipping {batch_id!r}"
                    )
                continue
            seen_codes[pc] = batch_id

            # ── Upsert (or dry-run equivalent) ──────────────────────────
            if con is not None:
                try:
                    disposition = upsert_product_identity_from_backfill(
                        con, pc, identity, dry_run=dry_run,
                    )
                except Exception as exc:
                    n_error += 1
                    print(f"[WARN] {pc}: {exc}", file=sys.stderr)
                    continue
            else:
                # No DB connection (dry-run without existing DB)
                disposition = "dry_run_insert"

            if verbose:
                print(
                    f"  [{disposition:<20}] {pc:<40} "
                    f"{identity.confidence:<7} {item_type}"
                )

            # Tally dispositions
            if disposition in ("inserted", "dry_run_insert"):
                n_inserted += 1
            elif disposition in ("updated", "dry_run_update"):
                n_updated += 1
            elif disposition in ("skipped_manual", "dry_run_skip_manual"):
                n_skipped_manual += 1
            elif disposition in ("skipped_417g", "dry_run_skip_417g"):
                n_skipped_417g += 1
            elif disposition in ("skipped_generic", "dry_run_skip_generic"):
                n_skipped_generic += 1

        # Commit per batch in write mode to limit transaction size
        if not dry_run and con is not None:
            con.commit()

    return {
        "mode":                 "dry_run" if dry_run else "write",
        "outputs_root":         str(outputs_root),
        "db_path":              str(db_path),
        "batches_scanned":      batches_scanned,
        "batches_with_pz_rows": batches_with_pz_rows,
        "total_rows":           total_rows,
        "unique_seen":          len(seen_codes),
        "stub_cleanup":         stub_result,
        "inserted":             n_inserted,
        "updated":              n_updated,
        "skipped_manual":       n_skipped_manual,
        "skipped_417g":         n_skipped_417g,
        "skipped_generic":      n_skipped_generic,
        "skipped_duplicate":    n_skipped_dup,
        "errors":               n_error,
        "confidence_high":      n_high,
        "confidence_medium":    n_medium,
        "confidence_low":       n_low,
    }


# ── Report printer ────────────────────────────────────────────────────────────

def _print_report(summary: Dict[str, object]) -> None:
    mode    = str(summary.get("mode", "?")).upper()
    stubs   = summary.get("stub_cleanup", {})
    is_dry  = (mode == "DRY_RUN")

    print()
    print("=== Product Identity Backfill ===")
    print(f"Mode:           {'DRY-RUN  (pass --write to commit)' if is_dry else 'WRITE MODE ACTIVE'}")
    print(f"Outputs root:   {summary.get('outputs_root')}")
    print(f"DB path:        {summary.get('db_path')}")
    print(
        f"Scan complete:  {summary.get('batches_scanned')} batches, "
        f"{summary.get('batches_with_pz_rows')} with pz_rows.json, "
        f"{summary.get('total_rows')} rows"
    )
    print()

    # Stub cleanup
    print("--- Stub cleanup ---")
    if is_dry:
        print(f"Stubs to delete:     {stubs.get('would_delete', stubs.get('found', '?'))}")
    else:
        print(f"Stubs deleted:       {stubs.get('deleted', '?')}")
    print(f"Manual protected:    {stubs.get('manual_protected', 0)}")
    print()

    # Backfill
    print("--- Backfill ---")
    if is_dry:
        print(f"Would insert:        {summary.get('inserted')}")
        print(f"Would update:        {summary.get('updated')}")
    else:
        print(f"Inserted:            {summary.get('inserted')}")
        print(f"Updated:             {summary.get('updated')}")
    print(f"Skipped manual:      {summary.get('skipped_manual')}")
    print(f"Skipped 417G:        {summary.get('skipped_417g')}")
    print(f"Skipped generic:     {summary.get('skipped_generic')}")
    print(f"Skipped duplicate:   {summary.get('skipped_duplicate')}")
    if summary.get("errors", 0):
        print(f"Errors:              {summary.get('errors')}  ← check stderr")
    print()

    # Confidence
    print("--- Confidence (unique, non-skipped) ---")
    print(f"HIGH:   {summary.get('confidence_high')}")
    print(f"MEDIUM: {summary.get('confidence_medium')}")
    print(f"LOW:    {summary.get('confidence_low')}   (karat not in pz_rows — expected)")
    print()

    if is_dry:
        print("DRY-RUN complete — pass --write to execute.")
    else:
        print("WRITE complete.")
        print()
        print("Rollback command:")
        print("  sqlite3 \"C:/PZ/storage/document.db\" \\")
        print("    \"DELETE FROM product_descriptions WHERE source='pz_rows_backfill';\"")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Product identity backfill — populate product_descriptions from pz_rows.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=_DEFAULT_OUTPUTS_ROOT,
        help=f"Root folder containing SHIPMENT_* batch dirs (default: {_DEFAULT_OUTPUTS_ROOT})",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=_DEFAULT_DB_PATH,
        help=f"Path to document.db (default: {_DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="Commit writes to DB. Default is dry-run (no writes).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print per-row disposition.",
    )

    args = parser.parse_args(argv)

    if not _ENGINE_AVAILABLE or not _DB_AVAILABLE:
        print("[ERROR] Required modules unavailable — see errors above.", file=sys.stderr)
        return 1

    summary = run_backfill(
        outputs_root=args.outputs_root,
        db_path=args.db_path,
        dry_run=not args.write,
        verbose=args.verbose,
    )

    if "error" in summary:
        print(f"[ERROR] {summary['error']}", file=sys.stderr)
        return 1

    _print_report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

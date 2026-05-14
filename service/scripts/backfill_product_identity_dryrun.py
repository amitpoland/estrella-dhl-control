"""
backfill_product_identity_dryrun.py — Read-only backfill audit for product identity.

Scans all outputs/SHIPMENT_*/pz_rows.json files and reports what would be
inserted into product_descriptions if a real backfill were executed.

By default (--dry-run, the default) NO writes are made.  The script is safe
to run against any environment.

Usage
-----
    # Dry-run against production outputs (default — no writes):
    python service/scripts/backfill_product_identity_dryrun.py

    # Specify a custom outputs root:
    python service/scripts/backfill_product_identity_dryrun.py \
        --outputs-root "C:/PZ/storage/outputs"

    # Show per-row detail (verbose):
    python service/scripts/backfill_product_identity_dryrun.py --verbose

The --write flag is intentionally NOT implemented in this PR.
Write operations require product_identity_engine to be fully wired into
the service DB layer and tested end-to-end (next PR).

Output summary fields
---------------------
    batches_scanned          — number of batch folders examined
    batches_with_pz_rows     — batches that had a parseable pz_rows.json
    total_rows               — total pz_rows across all batches
    ejl_codes                — EJL-format codes (globally unique)
    g417_codes               — 417 Global codes (NOT globally unique, LOW/manual)
    unknown_codes            — unrecognised product_code formats
    confidence_high          — would be assigned HIGH confidence
    confidence_medium        — would be assigned MEDIUM confidence
    confidence_low           — would be assigned LOW confidence
    wfirma_eligible          — rows eligible for wFirma registration
    generic_blocked          — rows blocked by generic description guard
    unique_product_codes     — distinct product_codes seen
    cufflink_rows            — CUFFLINK item_type rows (translation bug check)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ── Path bootstrap ────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVICE_DIR = _SCRIPT_DIR.parent                       # service/
_APP_DIR     = _SERVICE_DIR / "app"

if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

# ── Import engine ─────────────────────────────────────────────────────────────

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


# ── Default outputs root ──────────────────────────────────────────────────────

_DEFAULT_OUTPUTS_ROOT = Path("C:/PZ/storage/outputs")


# ── Per-row result ────────────────────────────────────────────────────────────

@dataclass
class RowResult:
    batch_id:        str
    product_code:    str
    item_type:       str
    supplier_prefix: str
    confidence:      str
    wfirma_eligible: bool
    generic_blocked: bool
    missing_fields:  List[str]
    pl_desc:         str
    description_en:  str


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_outputs(
    outputs_root: Path,
    verbose: bool = False,
) -> dict:
    """
    Scan all SHIPMENT_*/pz_rows.json under outputs_root.

    Returns a summary dict.  Never writes to any DB or file.
    """
    outputs_root = Path(outputs_root)
    if not outputs_root.exists():
        print(f"[WARN] outputs_root not found: {outputs_root}", file=sys.stderr)

    batch_dirs = sorted(
        d for d in outputs_root.iterdir()
        if d.is_dir() and d.name.startswith("SHIPMENT_")
    ) if outputs_root.exists() else []

    batches_scanned      = len(batch_dirs)
    batches_with_pz_rows = 0
    total_rows           = 0
    all_results: List[RowResult] = []
    seen_codes: dict[str, int] = {}   # product_code → first seen batch index

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
            pc           = str(row.get("product_code") or "").strip()
            item_type    = str(row.get("item_type")    or "").strip()
            description_en = str(row.get("description_en") or "").strip()
            pl_desc      = str(row.get("pl_desc")      or "").strip()

            if not _ENGINE_AVAILABLE:
                all_results.append(RowResult(
                    batch_id=batch_id, product_code=pc, item_type=item_type,
                    supplier_prefix="?", confidence="?", wfirma_eligible=False,
                    generic_blocked=False, missing_fields=[], pl_desc=pl_desc,
                    description_en=description_en,
                ))
                seen_codes[pc] = seen_codes.get(pc, 0) + 1
                continue

            identity = resolve_product_identity(
                pc,
                item_type=item_type,
                description_pl=pl_desc,
                description_en=description_en,
                source="pz_rows_backfill",
            )
            generic_blocked = is_generic_description(pl_desc)

            rr = RowResult(
                batch_id=batch_id,
                product_code=pc,
                item_type=item_type,
                supplier_prefix=identity.supplier_prefix,
                confidence=identity.confidence,
                wfirma_eligible=identity.wfirma_eligible,
                generic_blocked=generic_blocked,
                missing_fields=identity.missing_fields,
                pl_desc=pl_desc,
                description_en=description_en,
            )
            all_results.append(rr)
            seen_codes[pc] = seen_codes.get(pc, 0) + 1

            if verbose:
                flag = ("✓" if identity.wfirma_eligible else
                        "G" if generic_blocked else
                        "M" if identity.requires_manual_code else "L")
                print(
                    f"  [{flag}] {pc:<35} {identity.confidence:<7} "
                    f"{item_type:<12} missing={identity.missing_fields}"
                )

    # ── Aggregate ──────────────────────────────────────────────────────────
    c_ejl = sum(1 for r in all_results if r.supplier_prefix == "EJL")
    c_417 = sum(1 for r in all_results if r.supplier_prefix == "417G")
    c_unk = sum(1 for r in all_results if r.supplier_prefix == "UNKNOWN")
    c_high = sum(1 for r in all_results if r.confidence == "HIGH")
    c_med  = sum(1 for r in all_results if r.confidence == "MEDIUM")
    c_low  = sum(1 for r in all_results if r.confidence == "LOW")
    c_elig = sum(1 for r in all_results if r.wfirma_eligible)
    c_gen  = sum(1 for r in all_results if r.generic_blocked)
    c_cuff = sum(1 for r in all_results if "CUFFLINK" in r.item_type.upper())

    # Stale generic stub check (product_codes that are item_type names)
    generic_stubs = [pc for pc in seen_codes if pc.upper() in FORBIDDEN_PRODUCT_CODE_KEYS] if _ENGINE_AVAILABLE else []

    summary = {
        "dry_run":                True,
        "outputs_root":           str(outputs_root),
        "batches_scanned":        batches_scanned,
        "batches_with_pz_rows":   batches_with_pz_rows,
        "total_rows":             total_rows,
        "ejl_codes":              c_ejl,
        "g417_codes":             c_417,
        "unknown_codes":          c_unk,
        "confidence_high":        c_high,
        "confidence_medium":      c_med,
        "confidence_low":         c_low,
        "wfirma_eligible":        c_elig,
        "generic_blocked":        c_gen,
        "unique_product_codes":   len(seen_codes),
        "cufflink_rows":          c_cuff,
        "generic_stub_keys_in_pz_rows": generic_stubs,
    }
    return summary, all_results


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run product identity backfill audit (read-only).",
    )
    parser.add_argument(
        "--outputs-root",
        default=str(_DEFAULT_OUTPUTS_ROOT),
        help=f"Path to SHIPMENT_* batch folders (default: {_DEFAULT_OUTPUTS_ROOT})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-row results",
    )
    args = parser.parse_args(argv)

    print("=" * 68)
    print("PRODUCT IDENTITY BACKFILL — DRY RUN (no writes)")
    print("=" * 68)

    summary, _rows = scan_outputs(
        outputs_root=Path(args.outputs_root),
        verbose=args.verbose,
    )

    print()
    print(f"  outputs_root           : {summary['outputs_root']}")
    print(f"  batches_scanned        : {summary['batches_scanned']}")
    print(f"  batches_with_pz_rows   : {summary['batches_with_pz_rows']}")
    print(f"  total_rows             : {summary['total_rows']}")
    print()
    print(f"  Product code formats:")
    print(f"    EJL (globally unique): {summary['ejl_codes']}")
    print(f"    417 Global (scoped)  : {summary['g417_codes']}")
    print(f"    Unknown              : {summary['unknown_codes']}")
    print()
    print(f"  Confidence distribution:")
    print(f"    HIGH                 : {summary['confidence_high']}")
    print(f"    MEDIUM               : {summary['confidence_medium']}")
    print(f"    LOW                  : {summary['confidence_low']}")
    print()
    print(f"  wFirma eligible        : {summary['wfirma_eligible']}")
    print(f"  Generic blocked        : {summary['generic_blocked']}")
    print(f"  Unique product_codes   : {summary['unique_product_codes']}")
    print(f"  CUFFLINK rows          : {summary['cufflink_rows']}")
    if summary["generic_stub_keys_in_pz_rows"]:
        print(f"  [WARN] Generic stub keys in pz_rows: {summary['generic_stub_keys_in_pz_rows']}")
    print()
    print("Dry-run complete. No writes were made.")
    print("=" * 68)

    return 0


if __name__ == "__main__":
    sys.exit(main())

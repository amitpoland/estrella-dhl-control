#!/usr/bin/env python3
"""
backfill_clearance_decision.py — One-time backfill for clearance_decision field.

Scans all audit.json files in storage/outputs/ and storage/archived/.
For any batch where clearance_decision is absent, computes and writes it.

SAFE:
  - Never modifies PZ data, invoice_totals, customs_data, or verification
  - Only adds/updates clearance_decision key
  - Atomic write (tmp → rename)
  - Dry-run mode by default (pass --write to actually persist)
  - Idempotent: safe to run multiple times

Usage:
    python3 scripts/backfill_clearance_decision.py              # dry-run
    python3 scripts/backfill_clearance_decision.py --write      # persist changes
    python3 scripts/backfill_clearance_decision.py --write --verbose
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import os

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).resolve().parent
_SERVICE = _HERE.parent           # service/
_VENV_SITE = _SERVICE.parent / "Library" / "Application Support" / "estrellajewels" / "venv" / "lib" / "python3.9" / "site-packages"

# Try venv first, then local service package
for _path in (_VENV_SITE, _SERVICE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# ── Storage root ──────────────────────────────────────────────────────────────
_DEFAULT_STORAGE = pathlib.Path.home() / "Library" / "Application Support" / "estrellajewels" / "storage"


def _write_atomic(path: pathlib.Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def backfill(storage_root: pathlib.Path, write: bool, verbose: bool) -> None:
    from app.services.clearance_decision import build_clearance_decision

    scan_dirs = [
        storage_root / "outputs",
        storage_root / "archived",
        storage_root / "working",
    ]

    total = skipped = updated = failed = 0

    for base in scan_dirs:
        if not base.exists():
            continue
        for batch_dir in sorted(base.iterdir()):
            audit_path = batch_dir / "audit.json"
            if not audit_path.is_file():
                continue
            total += 1

            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  [SKIP] {batch_dir.name}: cannot read audit ({e})")
                failed += 1
                continue

            existing = audit.get("clearance_decision")
            if existing and existing.get("clearance_path") != "routing_pending":
                # Already populated with a real decision — skip
                skipped += 1
                if verbose:
                    print(f"  [OK  ] {batch_dir.name}: {existing['clearance_path']}")
                continue

            try:
                dec = build_clearance_decision(audit)
            except Exception as e:
                print(f"  [FAIL] {batch_dir.name}: build_clearance_decision error: {e}")
                failed += 1
                continue

            path_label = dec.get("clearance_path", "?")
            cif        = dec.get("total_value_usd", 0)

            if write:
                try:
                    audit["clearance_decision"] = dec
                    _write_atomic(audit_path, audit)
                    updated += 1
                    print(f"  [WRITE] {batch_dir.name}: {path_label}  CIF=${cif:.2f}")
                except Exception as e:
                    print(f"  [FAIL] {batch_dir.name}: write error: {e}")
                    failed += 1
            else:
                updated += 1
                print(f"  [DRY ] {batch_dir.name}: would set {path_label}  CIF=${cif:.2f}")

    print()
    print(f"{'DRY RUN' if not write else 'WRITTEN'} — scanned={total}  "
          f"already_ok={skipped}  {'would_update' if not write else 'updated'}={updated}  "
          f"failed={failed}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write",   action="store_true", help="Actually write changes (default: dry-run)")
    p.add_argument("--verbose", action="store_true", help="Print already-ok batches too")
    p.add_argument("--storage", default=str(_DEFAULT_STORAGE), help="Path to storage root")
    args = p.parse_args()

    storage = pathlib.Path(args.storage)
    if not storage.exists():
        print(f"ERROR: storage root not found: {storage}", file=sys.stderr)
        sys.exit(1)

    print(f"Storage: {storage}")
    print(f"Mode:    {'WRITE' if args.write else 'DRY-RUN (pass --write to persist)'}")
    print()

    backfill(storage, write=args.write, verbose=args.verbose)


if __name__ == "__main__":
    main()

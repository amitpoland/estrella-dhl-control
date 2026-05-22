#!/usr/bin/env python
"""load_fixture_to_storage.py — seed a SAD-authority fixture into local storage.

Local dev / browser-smoke helper. Copies one of the four SAD-authority audit
fixtures into a synthetic batch directory under your storage outputs path so
the shipment-detail.html renderer and the batch_detail API can be exercised
end-to-end without waiting for the next real ZC429 ingest.

Safety guards
-------------
- Refuses to write outside a path whose final segment is ``outputs``.
- Refuses to overwrite a destination whose ``batch_id`` does not contain
  the ``TEST`` token (i.e. it will never trample a real shipment dir).
- Refuses to run unless ``--i-understand-this-is-dev-only`` is passed.

Usage
-----
    python service/tests/fixtures/sad_authority/load_fixture_to_storage.py \\
        --fixture n935_match \\
        --storage-dir C:\\PZ\\storage\\outputs \\
        --i-understand-this-is-dev-only

The helper prints the synthetic shipment URL you can open in the dashboard
once the file is in place.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

FIXTURE_DIR = Path(__file__).parent

FIXTURE_NAMES = (
    "n935_match",
    "n935_absent",
    "inferred_free_text",
    "n935_mismatch",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Seed a SAD-authority fixture into dev storage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--fixture",
        required=True,
        choices=FIXTURE_NAMES,
        help="Which fixture to load.",
    )
    p.add_argument(
        "--storage-dir",
        required=True,
        type=Path,
        help=r"Path to the storage outputs dir (e.g. C:\PZ\storage\outputs).",
    )
    p.add_argument(
        "--i-understand-this-is-dev-only",
        action="store_true",
        help="Required acknowledgement that this is a dev helper.",
    )
    return p.parse_args()


def _refuse_if_unsafe(storage_dir: Path, batch_id: str) -> Optional[str]:
    """Return a reason string if the operation is unsafe, else None."""
    if storage_dir.name != "outputs":
        return (
            f"--storage-dir final segment must be 'outputs' "
            f"(got '{storage_dir.name}'). Refusing to write."
        )
    if "TEST" not in batch_id:
        return (
            f"Fixture batch_id '{batch_id}' does not contain 'TEST'. "
            f"Refusing to write a non-synthetic batch."
        )
    return None


def main() -> int:
    args = _parse_args()
    if not args.i_understand_this_is_dev_only:
        print(
            "[refuse] --i-understand-this-is-dev-only is required.",
            file=sys.stderr,
        )
        return 2

    fixture_path = FIXTURE_DIR / f"{args.fixture}.json"
    if not fixture_path.exists():
        print(f"[refuse] Fixture not found: {fixture_path}", file=sys.stderr)
        return 2

    with fixture_path.open("r", encoding="utf-8") as f:
        audit = json.load(f)
    batch_id = audit.get("batch_id", "")

    refusal = _refuse_if_unsafe(args.storage_dir, batch_id)
    if refusal:
        print(f"[refuse] {refusal}", file=sys.stderr)
        return 2

    if not args.storage_dir.exists():
        print(
            f"[refuse] Storage dir does not exist: {args.storage_dir}. "
            f"Create it manually before running this helper.",
            file=sys.stderr,
        )
        return 2

    dest_dir = args.storage_dir / batch_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "audit.json"
    with dest_path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)

    print(f"[ok] Wrote {dest_path}")
    print(f"[ok] batch_id = {batch_id}")
    print(f"[ok] Open the dashboard at /shipment-detail.html?batch={batch_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

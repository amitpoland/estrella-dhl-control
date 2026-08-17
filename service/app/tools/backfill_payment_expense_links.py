"""Converge payment_state.db expense_id from live wFirma payments/find.

Read-only against wFirma. Local snapshot writes only. Does not delete
existing payment snapshots. Resumable via JSONL checkpoint.

Usage (from service/):

  python -m app.tools.backfill_payment_expense_links --dry-run
  python -m app.tools.backfill_payment_expense_links --apply
  python -m app.tools.backfill_payment_expense_links --apply --contractor-id 38142296
  python -m app.tools.backfill_payment_expense_links --apply --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[2]
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))


def main(argv: list[str] | None = None) -> int:
    _bootstrap()
    parser = argparse.ArgumentParser(
        description="Backfill payment snapshot expense_id from wFirma payments/find"
    )
    parser.add_argument("--apply", action="store_true", help="Write expense_id onto snapshots")
    parser.add_argument("--dry-run", action="store_true", help="Report coverage only (default)")
    parser.add_argument("--bulk", action="store_true", help="Use bulk payments/find (live AP authority)")
    parser.add_argument("--as-of", default="2026-08-17", help="As-of date for --bulk")
    parser.add_argument("--db", type=Path, default=None, help="payment_state.db path")
    parser.add_argument(
        "--contractor-id", action="append", default=[], help="Limit to contractor_id (repeatable)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max contractors this run")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="JSONL checkpoint path (resumable)",
    )
    args = parser.parse_args(argv)

    from app.core.config import settings
    from app.services.wfirma_payment_db import (
        init_payment_db,
        list_snapshot_contractor_ids,
        payment_expense_link_coverage,
    )
    from app.services.wfirma_payment_sync_processor import (
        backfill_payment_expense_links,
        backfill_payment_expense_links_from_period,
    )

    db = args.db or (Path(settings.storage_root) / "payment_state.db")
    init_payment_db(db)
    coverage = payment_expense_link_coverage(db)
    contractors = args.contractor_id or list_snapshot_contractor_ids(db)
    print(json.dumps({
        "db": str(db),
        "coverage": coverage,
        "contractor_count": len(contractors),
        "mode": "apply" if args.apply else "dry-run",
    }, ensure_ascii=False))

    if not args.apply:
        return 0

    checkpoint = args.checkpoint
    if checkpoint is None:
        checkpoint = Path(settings.storage_root) / "payment_expense_backfill.checkpoint.jsonl"

    if args.bulk:
        result = backfill_payment_expense_links_from_period(
            payment_db=db,
            date_to=args.as_of,
            date_from="",
            now=datetime.now(timezone.utc).isoformat(),
        )
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 2 if result.get("error") else 0

    result = backfill_payment_expense_links(
        payment_db=db,
        contractor_ids=args.contractor_id or None,
        now=datetime.now(timezone.utc).isoformat(),
        checkpoint_path=checkpoint,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result.get("errors"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

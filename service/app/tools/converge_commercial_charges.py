"""converge_commercial_charges.py — CLI for the charge-convergence capability.

Thin wrapper. All logic lives in
``app.services.commercial_charge_convergence`` — the ONE shared function that
the scheduler tick and the Business API also call. This file adds argument
parsing and printing, nothing else.

Historical backfill is exactly this command with an explicit window: it is
never a startup or scheduler side effect.

Usage::

    python -m app.tools.converge_commercial_charges --from 2020-01-01 --to 2026-08-31
    python -m app.tools.converge_commercial_charges --from 2026-08-01 --to 2026-08-31 --apply
    python -m app.tools.converge_commercial_charges --months 2 --out artifact.json

``--dry-run`` is the default; ``--apply`` additionally requires
``COMMERCIAL_CHARGE_CONVERGENCE_APPLY_ENABLED=1`` and writes only to the local
``commercial_charges.db``. wFirma is read-only on this path. Exit code 2 means
the run found contradictions needing manual review.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[3]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.services.commercial_charge_convergence import (  # noqa: E402
    ChargeConvergenceWriteDenied,
    resolve_window,
    run_charge_convergence,
)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="converge_commercial_charges")
    p.add_argument("--from", dest="date_from", default=None, help="ISO YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", default=None, help="ISO YYYY-MM-DD")
    p.add_argument("--months", type=int, default=None,
                   help="window = last N*31 days (used when --from/--to are absent)")
    p.add_argument("--apply", action="store_true",
                   help="write to commercial_charges.db (default is a dry run)")
    p.add_argument("--db", default=None, help="override the record DB path")
    p.add_argument("--out", default=None, help="write the reconciliation artifact here")
    args = p.parse_args(argv)

    date_from, date_to = resolve_window(args.months, args.date_from, args.date_to)
    try:
        summary = run_charge_convergence(
            date_from=date_from,
            date_to=date_to,
            apply=args.apply,
            operator="cli",
            record_path=Path(args.db) if args.db else None,
        )
    except ChargeConvergenceWriteDenied as exc:
        print("REFUSED: %s" % exc)
        return 3

    artifact = summary["artifact"]
    if args.out:
        Path(args.out).write_text(json.dumps(artifact, indent=1, ensure_ascii=False),
                                  encoding="utf-8")

    c = artifact["counts"]
    print("mode=%s window=%s..%s" % (summary["mode"], date_from, date_to))
    print("  scanned=%d in_window=%d" % (c["scanned"], c["in_window"]))
    print("  inserted=%d unchanged=%d conflict=%d" % (c.get("inserted", 0),
                                                      c.get("unchanged", 0),
                                                      c.get("conflict", 0)))
    print("  with_insurance=%d without_insurance=%d" % (c["with_insurance"],
                                                        c["without_insurance"]))
    for ccy, amount in summary["billed_insurance_by_currency"].items():
        print("  billed %s %s" % (ccy, amount))
    if summary["unattributed"]:
        print("  UNATTRIBUTED insurance-like lines: %d (not recorded)"
              % summary["unattributed"])
    if summary["conflicts"]:
        print("  CONFLICTS needing manual review: %d" % summary["conflicts"])
    return 2 if summary["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

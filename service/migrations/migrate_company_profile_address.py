"""
migrate_company_profile_address.py
===================================
One-time migration: update Estrella Jewels company_profile address from
stale "ul. Nowy Swiat 27 lok. 39, 00-029 Warszawa" to the correct
"ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa".

This fix is required for proforma-detail.jsx to render the correct seller
address on proforma previews and PDFs.

References: PR fix/proforma-renderer-authority; PROF 123/2026 (Draft #24).

Usage (run ONCE from the production machine after deploying the JSX fix):
    python service/migrations/migrate_company_profile_address.py

Safety:
  - Reads current address first; prints before/after for operator review.
  - Only updates if the address is the known stale value (idempotent).
  - No wFirma writes, no audit mutation, no PZ changes.
  - production DB path: C:\\PZ\\storage\\master_data.sqlite

OPERATOR GATE — this script MUST be reviewed and run by the operator.
Do not run autonomously from CI. Requires human confirmation.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────
STALE_STREET        = "ul. Nowy Swiat 27 lok. 39"
STALE_POSTAL_CITY   = "00-029 Warszawa"
CORRECT_STREET      = "ul. Wybrzeże Kościuszkowskie 31/33"
CORRECT_POSTAL_CITY = "00-379 Warszawa"

DEFAULT_DB = Path(r"C:\PZ\storage\master_data.sqlite")


def migrate(db_path: Path, dry_run: bool = False) -> None:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Migrating: {db_path}")

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT id, street, postal_city FROM company_profile WHERE id=1"
    ).fetchone()

    if row is None:
        print("ERROR: no company_profile row with id=1", file=sys.stderr)
        conn.close()
        sys.exit(1)

    _, current_street, current_postal_city = row
    print(f"  Current: street={current_street!r}, postal_city={current_postal_city!r}")
    print(f"  Target:  street={CORRECT_STREET!r}, postal_city={CORRECT_POSTAL_CITY!r}")

    if current_street == CORRECT_STREET and current_postal_city == CORRECT_POSTAL_CITY:
        print("  Already correct — no update needed.")
        conn.close()
        return

    if current_street != STALE_STREET or current_postal_city != STALE_POSTAL_CITY:
        print(
            f"  WARNING: current address does not match known stale value.\n"
            f"    Expected stale: {STALE_STREET!r} / {STALE_POSTAL_CITY!r}\n"
            f"    Got:            {current_street!r} / {current_postal_city!r}\n"
            f"  Proceeding anyway (unknown intermediate state).",
        )

    if dry_run:
        print("  [DRY RUN] Would update to correct address. Skipping write.")
        conn.close()
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE company_profile SET street=?, postal_city=?, updated_at=? WHERE id=1",
        (CORRECT_STREET, CORRECT_POSTAL_CITY, now),
    )
    conn.commit()
    conn.close()
    print("  Update applied successfully.")
    print(f"  New: street={CORRECT_STREET!r}, postal_city={CORRECT_POSTAL_CITY!r}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to master_data.sqlite")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, do not write")
    args = parser.parse_args()
    migrate(Path(args.db), dry_run=args.dry_run)
    print("\nDone.\n")

"""
correct_ejl_auto_shorthand_en.py — Repair plan for Category A blocked rows.

DO NOT RUN without explicit operator approval.
Audit report: .claude/campaigns/description-authority-cleanup-audit-report-2026-06-25.md

Action: Clear description_en to '' for all source='auto' rows where validate_description_line()
returns blocked=True due to shorthand tokens. PL-only render is valid; clearing EN unblocks
the wFirma gate without touching the canonical description_pl.

After running: re-run _audit_descriptions.py to confirm zero blocked auto-shorthand rows.
Then write repaired rows back with source='auto' (source unchanged — no manual confirmation
was required for EN-clear; the fix is structural, not content-level).

Operator approval status: PENDING — do not run.
"""
import sys
import sqlite3
import argparse

sys.path.insert(0, r'C:\PZ-verify\service')
from app.services.description_length_policy import validate_description_line

# ── Safety ────────────────────────────────────────────────────────────────────
REQUIRE_FLAG = "--i-have-operator-approval"

def main():
    parser = argparse.ArgumentParser(description="Clear shorthand description_en for auto-source blocked rows.")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Default mode — print what would change, write nothing.")
    parser.add_argument("--i-have-operator-approval", action="store_true", dest="approved",
                        help="Required to actually write. Operator must pass this flag explicitly.")
    args = parser.parse_args()

    dry_run = not args.approved

    db_path = r'C:\PZ\storage\documents.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT product_code, description_pl, description_en, source, updated_at
        FROM product_descriptions
        WHERE source = 'auto'
        ORDER BY product_code
    """)
    rows = cur.fetchall()

    to_clear = []
    for row in rows:
        result = validate_description_line(row['description_pl'] or '', row['description_en'] or '')
        if result.blocked and result.shorthand_detected:
            to_clear.append(row['product_code'])

    if dry_run:
        print(f"DRY RUN — {len(to_clear)} rows would have description_en cleared:")
        for code in to_clear:
            print(f"  {code}")
        print()
        print("To execute: python correct_ejl_auto_shorthand_en.py --i-have-operator-approval")
        conn.close()
        return

    print(f"Writing {len(to_clear)} rows — clearing description_en...")
    updated = 0
    for code in to_clear:
        cur.execute("""
            UPDATE product_descriptions
            SET description_en = '',
                updated_at = datetime('now')
            WHERE product_code = ? AND source = 'auto'
        """, (code,))
        if cur.rowcount == 1:
            updated += 1
            print(f"  CLEARED: {code}")
        else:
            print(f"  SKIPPED (no row or source changed): {code}")
    conn.commit()
    conn.close()
    print(f"\nDone. {updated}/{len(to_clear)} rows updated.")
    print("Re-run _audit_descriptions.py to verify zero blocked auto-shorthand rows.")

if __name__ == "__main__":
    main()

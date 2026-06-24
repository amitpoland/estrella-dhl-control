"""
correct_ejl_auto_shorthand_en.py — Repair plan for Category A blocked rows.

DO NOT RUN without explicit operator approval.
Audit report: .claude/campaigns/description-authority-cleanup-audit-report-2026-06-25.md

Action: Clear description_en to '' for source='auto' rows where validate_description_line()
returns blocked=True due to shorthand tokens. PL-only render is valid; clearing EN unblocks
the wFirma gate without touching the canonical description_pl.

Process in batches by product type so each type can be verified independently:
  --type ring        Pierścionek / RING / TIE PIN rows
  --type earrings    Kolczyki / EARRINGS rows
  --type pendant     Wisiorek / Zawieszka / PENDANT rows
  --type bracelet    Bransoletka / BRACELET rows
  --type other       Everything else (necklaces, aggregates, etc.)
  --type all         All shorthand auto rows (use with caution)

After each batch: re-run _audit_descriptions.py to confirm zero blocked rows for that type.
"""
import sys
import sqlite3
import argparse
import re

sys.path.insert(0, r'C:\PZ-verify\service')

from app.services.description_length_policy import validate_description_line

# ── Product type classification ────────────────────────────────────────────────

_TYPE_MAP = {
    "ring":      [re.compile(r'\bPierścionek\b', re.IGNORECASE), re.compile(r'\bRING\b|\bTIE PIN\b')],
    "earrings":  [re.compile(r'\bKolczyki\b',    re.IGNORECASE), re.compile(r'\bEARRINGS\b')],
    "pendant":   [re.compile(r'\bWisiorek\b|\bZawieszka\b', re.IGNORECASE), re.compile(r'\bPENDANT\b')],
    "bracelet":  [re.compile(r'\bBransoletka\b', re.IGNORECASE), re.compile(r'\bBRACELET\b')],
    "necklace":  [re.compile(r'\bNaszyjnik\b',   re.IGNORECASE), re.compile(r'\bNECKLACE\b')],
}

def _classify(description_pl: str, description_en: str) -> str:
    text = f"{description_pl} {description_en}"
    for typ, patterns in _TYPE_MAP.items():
        if any(p.search(text) for p in patterns):
            return typ
    return "other"


def main():
    parser = argparse.ArgumentParser(
        description="Clear shorthand description_en for auto-source blocked rows by product type."
    )
    parser.add_argument(
        "--type",
        choices=["ring", "earrings", "pendant", "bracelet", "necklace", "other", "all"],
        required=True,
        help="Product type batch to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default) Print what would change, write nothing.",
    )
    parser.add_argument(
        "--i-have-operator-approval",
        action="store_true",
        dest="approved",
        help="Required to actually write. Operator must pass this flag explicitly.",
    )
    args = parser.parse_args()

    dry_run = not args.approved
    target_type = args.type

    db_path = r'C:\PZ\storage\documents.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT product_code, description_pl, description_en, source
        FROM product_descriptions
        WHERE source = 'auto'
        ORDER BY product_code
    """)
    rows = cur.fetchall()

    to_clear = []
    skipped_wrong_type = []
    for row in rows:
        result = validate_description_line(row['description_pl'] or '', row['description_en'] or '')
        if result.blocked and result.shorthand_detected:
            row_type = _classify(row['description_pl'] or '', row['description_en'] or '')
            if target_type == "all" or row_type == target_type:
                to_clear.append((row['product_code'], row_type))
            else:
                skipped_wrong_type.append((row['product_code'], row_type))

    if dry_run:
        print(f"DRY RUN — type={target_type!r} — {len(to_clear)} rows would have description_en cleared:")
        for code, typ in to_clear:
            print(f"  [{typ:10s}] {code}")
        if skipped_wrong_type:
            print(f"\n  (skipped {len(skipped_wrong_type)} rows of other types)")
        print()
        print(f"To execute: python correct_ejl_auto_shorthand_en.py --type {target_type} --i-have-operator-approval")
        conn.close()
        return

    print(f"Writing {len(to_clear)} rows (type={target_type!r}) — clearing description_en...")
    updated = 0
    for code, typ in to_clear:
        cur.execute("""
            UPDATE product_descriptions
            SET description_en = '',
                updated_at = datetime('now')
            WHERE product_code = ? AND source = 'auto'
        """, (code,))
        if cur.rowcount == 1:
            updated += 1
            print(f"  CLEARED [{typ}]: {code}")
        else:
            print(f"  SKIPPED (no row or source changed): {code}")
    conn.commit()
    conn.close()
    print(f"\nDone. {updated}/{len(to_clear)} rows updated.")
    print("Re-run _audit_descriptions.py to verify zero blocked auto-shorthand rows for this type.")


if __name__ == "__main__":
    main()

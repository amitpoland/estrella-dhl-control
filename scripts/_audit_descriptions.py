"""Audit all product_descriptions rows for validate_description_line blocked/warn status."""
import sqlite3
import sys
import os

sys.path.insert(0, r'C:\PZ-verify\service')
sys.stdout.reconfigure(encoding='utf-8')

from app.services.description_length_policy import validate_description_line

db_path = r'C:\PZ\storage\documents.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('''
    SELECT product_code, description_pl, description_en, description_line, source, updated_at
    FROM product_descriptions
    ORDER BY product_code
''')
rows = cur.fetchall()
conn.close()

print(f'Total rows in product_descriptions: {len(rows)}')
print()

blocked_rows = []
warn_rows = []
ok_rows = []

for row in rows:
    code = row['product_code']
    pl = row['description_pl'] or ''
    en = row['description_en'] or ''
    source = row['source'] or ''
    updated = row['updated_at'] or ''

    result = validate_description_line(pl, en)

    if result.blocked:
        blocked_rows.append((code, pl, en, source, updated, result))
    elif not result.ok or result.warnings:
        warn_rows.append((code, pl, en, source, updated, result))
    else:
        ok_rows.append((code, pl, en, source, updated, result))

print(f'=== BLOCKED ({len(blocked_rows)} rows) ===')
for code, pl, en, source, updated, r in blocked_rows:
    print(f'product_code : {code}')
    print(f'source       : {source}')
    print(f'updated_at   : {updated}')
    print(f'description_pl: {pl!r}')
    print(f'description_en: {en!r}')
    print(f'shorthand    : {r.shorthand_detected}')
    print(f'advisory     : {r.advisory}')
    print()

print()
print(f'=== WARNINGS only (not blocked, {len(warn_rows)} rows) ===')
for code, pl, en, source, updated, r in warn_rows:
    print(f'product_code : {code} | source={source}')
    print(f'description_en: {en!r}')
    for w in r.warnings:
        print(f'  WARN: {w}')
    print()

print()
print(f'=== OK ({len(ok_rows)} rows) ===')
for code, pl, en, source, updated, r in ok_rows:
    print(f'  {code} | source={source} | combined_chars={r.combined_chars}')

# Summary by source for blocked rows
print()
print('=== BLOCKED ROWS — SOURCE BREAKDOWN ===')
from collections import Counter
source_counts = Counter(src for _, _, _, src, _, _ in blocked_rows)
for src, count in sorted(source_counts.items()):
    print(f'  source={src!r}: {count} rows')

# Shorthand-specific subset
shorthand_blocked = [(c, pl, en, src, upd, r) for c, pl, en, src, upd, r in blocked_rows if r.shorthand_detected]
print()
print(f'=== SHORTHAND-DETECTED BLOCKED rows ({len(shorthand_blocked)}) ===')
for code, pl, en, source, updated, r in shorthand_blocked:
    print(f'  product_code={code} | source={source} | en={en!r}')

non_shorthand_blocked = [(c, pl, en, src, upd, r) for c, pl, en, src, upd, r in blocked_rows if not r.shorthand_detected]
print()
print(f'=== NON-SHORTHAND BLOCKED rows ({len(non_shorthand_blocked)}) — first 10 ===')
for code, pl, en, source, updated, r in non_shorthand_blocked[:10]:
    print(f'  product_code={code} | source={source}')
    print(f'    pl={pl!r}')
    print(f'    en={en!r}')
    print(f'    advisory={r.advisory[:120]}')

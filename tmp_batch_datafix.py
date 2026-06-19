# Batch data fix: SHIPMENT_7123231135_2026-06_f255bbb5
# - Draft 30 (Verhoeven): assign product_codes to 2 ambiguous J4007R08118-0.6 rows
# - Draft 32 (UAB Monodija): register JNP00033 as EJL/26-27/258-6 and assign product_codes
import sqlite3, json, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

BATCH = 'SHIPMENT_7123231135_2026-06_f255bbb5'
DOC_DB  = r'C:\PZ\storage\documents.db'
PACK_DB = r'C:\PZ\storage\packing.db'
PF_DB   = r'C:\PZ\storage\proforma_links.db'
ENV_PATH = r'C:\PZ\.env'

# --- read API key ---
api_key = ''
with open(ENV_PATH) as f:
    for line in f:
        if line.startswith('API_KEY='):
            api_key = line.strip().split('=', 1)[1]
if not api_key:
    raise RuntimeError('API key not found in .env')

def api(method, path, body=None):
    url = f'http://127.0.0.1:47213{path}'
    data = json.dumps(body or {}).encode() if body is not None else b'{}'
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json', 'X-API-Key': api_key, 'X-Operator': 'batch_datafix'},
        method=method,
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

# ── Fix A: Verhoeven draft 30 ────────────────────────────────────────────────
print('\n=== Fix A: Verhoeven draft 30 (J4007R08118-0.6 metal disambiguation) ===')
# From Excel: Sr=2 → 18KT Y → purchase packing = 257-4; Sr=5 → PT950 → 257-2
# Sales rows identified by unit_price: 439 EUR → 257-4 (18KT Y), 431 EUR → 257-2 (PT950)
doc_db = sqlite3.connect(DOC_DB)
doc_db.row_factory = sqlite3.Row
rows_257 = doc_db.execute(
    'SELECT id, unit_price, product_code FROM sales_packing_lines '
    'WHERE design_no=? AND batch_id=? ORDER BY unit_price DESC',
    ('J4007R08118-0.6', BATCH)
).fetchall()
print(f'Found {len(rows_257)} rows for J4007R08118-0.6')
assert len(rows_257) == 2, f'Expected 2 rows, got {len(rows_257)}'

for r in rows_257:
    price = r['unit_price']
    if abs(price - 439.0) < 0.5:
        target_pc = 'EJL/26-27/257-4'  # 18KT Y
        print(f'  Row {r["id"]} price={price} → {target_pc} (18KT Y)')
    elif abs(price - 431.0) < 0.5:
        target_pc = 'EJL/26-27/257-2'  # PT950
        print(f'  Row {r["id"]} price={price} → {target_pc} (PT950)')
    else:
        raise ValueError(f'Unexpected price {price} for J4007R08118-0.6 row {r["id"]}')
    doc_db.execute('UPDATE sales_packing_lines SET product_code=? WHERE id=?', (target_pc, r['id']))

doc_db.commit()
print('  sales_packing_lines updated for draft 30.')

# Get current updated_at for draft 30
pf_db = sqlite3.connect(PF_DB)
pf_db.row_factory = sqlite3.Row
d30 = pf_db.execute('SELECT id, updated_at FROM proforma_drafts WHERE id=30').fetchone()
pf_db.close()
if d30 is None:
    print('  WARNING: draft 30 not found in proforma_links.db, skipping reset.')
else:
    updated_at_30 = d30['updated_at']
    print(f'  Draft 30 updated_at: {updated_at_30}')
    try:
        result = api('POST', '/api/v1/proforma/draft/30/reset-from-sales-packing',
                     {'expected_updated_at': updated_at_30, 'reset_all': False})
        new_updated_at_30 = result.get('updated_at', updated_at_30)
        print(f'  Draft 30 reset: status={result.get("status")} new_updated_at={new_updated_at_30}')
    except Exception as e:
        print(f'  Draft 30 reset ERROR: {e}')
        new_updated_at_30 = updated_at_30
    try:
        result2 = api('POST', '/api/v1/proforma/draft/30/enrich-from-product-descriptions',
                      {'expected_updated_at': new_updated_at_30})
        print(f'  Draft 30 enrich: enriched={result2.get("enriched_count")} missing={result2.get("missing_count")}')
    except Exception as e:
        print(f'  Draft 30 enrich ERROR: {e}')

doc_db.close()

# ── Fix B: UAB Monodija draft 32 ─────────────────────────────────────────────
print('\n=== Fix B: UAB Monodija draft 32 (JNP00033 → EJL/26-27/258-6) ===')
NEW_PC = 'EJL/26-27/258-6'
# Only update rows associated with the real UAB Monodija sales_document
# (doc_id starting with 3a5474b0 = 'UAB Monodija Ir Ko')
doc_db2 = sqlite3.connect(DOC_DB)
doc_db2.row_factory = sqlite3.Row
mono_rows = doc_db2.execute(
    "SELECT id, sales_document_id, unit_price FROM sales_packing_lines "
    "WHERE design_no=? AND batch_id=? AND client_name=?",
    ('JNP00033', BATCH, 'UAB Monodija Ir Ko')
).fetchall()
print(f'Found {len(mono_rows)} UAB Monodija JNP00033 rows')
for r in mono_rows:
    print(f'  id={r["id"]} price={r["unit_price"]} doc={r["sales_document_id"][:8]}...')
    doc_db2.execute('UPDATE sales_packing_lines SET product_code=? WHERE id=?', (NEW_PC, r['id']))

# Also update packing_lines (purchase side) to mint the product_code for future matches
pack_db = sqlite3.connect(PACK_DB)
pack_db.row_factory = sqlite3.Row
packing_rows = pack_db.execute(
    'SELECT rowid, product_code, metal, unit_price FROM packing_lines WHERE design_no=? AND batch_id=?',
    ('JNP00033', BATCH)
).fetchall()
print(f'Found {len(packing_rows)} purchase packing_lines for JNP00033')
for r in packing_rows:
    print(f'  rowid={r["rowid"]} metal={r["metal"]} price={r["unit_price"]} current_pc={r["product_code"]}')
    pack_db.execute('UPDATE packing_lines SET product_code=? WHERE rowid=?', (NEW_PC, r['rowid']))
pack_db.commit()
pack_db.close()

# Create product_descriptions entry for EJL/26-27/258-6 (TPN nose pin)
import datetime
now_ts = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
name_pl = 'kolczyk do nosa z 14-karatowego różowego i żółtego złota'
desc_pl = 'kolczyk do nosa z 14-karatowego różowego i żółtego złota'
desc_en = '14kt gold nose pin'
material_pl = 'Metal (srebro/stop metali)'
purpose_pl = 'Ozdoba noszona na nosie'
# check if already exists
existing = doc_db2.execute('SELECT product_code FROM product_descriptions WHERE product_code=?', (NEW_PC,)).fetchone()
if existing:
    print(f'  product_descriptions entry for {NEW_PC} already exists — skipping insert.')
else:
    doc_db2.execute(
        '''INSERT INTO product_descriptions
           (product_code, item_type, name_pl, description_pl, material_pl, purpose_pl,
            description_en, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (NEW_PC, 'TPN', name_pl, desc_pl, material_pl, purpose_pl, desc_en, 'auto', now_ts, now_ts)
    )
    print(f'  product_descriptions entry created for {NEW_PC}.')

doc_db2.commit()
doc_db2.close()

# Call reset + enrich for draft 32
pf_db2 = sqlite3.connect(PF_DB)
pf_db2.row_factory = sqlite3.Row
d32 = pf_db2.execute('SELECT id, updated_at FROM proforma_drafts WHERE id=32').fetchone()
pf_db2.close()
if d32 is None:
    print('  WARNING: draft 32 not found in proforma_links.db, skipping reset.')
else:
    updated_at_32 = d32['updated_at']
    print(f'  Draft 32 updated_at: {updated_at_32}')
    try:
        result = api('POST', '/api/v1/proforma/draft/32/reset-from-sales-packing',
                     {'expected_updated_at': updated_at_32, 'reset_all': False})
        new_updated_at_32 = result.get('updated_at', updated_at_32)
        print(f'  Draft 32 reset: status={result.get("status")} new_updated_at={new_updated_at_32}')
    except Exception as e:
        print(f'  Draft 32 reset ERROR: {e}')
        new_updated_at_32 = updated_at_32
    try:
        result2 = api('POST', '/api/v1/proforma/draft/32/enrich-from-product-descriptions',
                      {'expected_updated_at': new_updated_at_32})
        print(f'  Draft 32 enrich: enriched={result2.get("enriched_count")} missing={result2.get("missing_count")}')
    except Exception as e:
        print(f'  Draft 32 enrich ERROR: {e}')

print('\nDone.')

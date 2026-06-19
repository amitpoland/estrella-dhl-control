import openpyxl, sqlite3, json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

_CATEGORY_PL = {'PND':'wisiorek','RNG':'pierścionek','EAR':'kolczyki','BRC':'bransoletka','NEC':'naszyjnik'}
_CATEGORY_EN = {'PND':'pendant','RNG':'ring','EAR':'earrings','BRC':'bracelet','NEC':'necklace'}
_KARAT_PL = {'14KT':'14-karatowego','18KT':'18-karatowego','PT950':'platynowego','PT':'platynowego','9KT':'9-karatowego'}
_KARAT_EN = {'14KT':'14kt','18KT':'18kt','PT950':'platinum','PT':'platinum','9KT':'9kt'}
_COLOR_PL = {'W':'białego','Y':'żółtego','R':'różowego','-':''}
_COLOR_EN = {'W':'white','Y':'yellow','R':'rose','-':''}

def stones_from_quality(quality):
    q=(quality or '').strip().upper()
    parts = re.split(r'[/,+]', q)
    pl_parts, en_parts = [], []
    for p in parts:
        p=p.strip()
        if not p: continue
        if re.match(r'^[A-Z]{1,4}-[A-Z0-9]+', p):
            pl_parts.append('diamentami'); en_parts.append('diamonds')
        elif 'SAPPH' in p or 'SAPH' in p:
            pl_parts.append('szafirami'); en_parts.append('sapphires')
    if not pl_parts:
        return '', ''
    return ' i '.join(dict.fromkeys(pl_parts)), ' and '.join(dict.fromkeys(en_parts))

def gen_desc(ctg, kt, col, quality):
    cat_pl = _CATEGORY_PL.get(ctg.upper(), 'wyrób')
    cat_en = _CATEGORY_EN.get(ctg.upper(), 'item')
    kar_pl = _KARAT_PL.get(kt.upper().strip(), '')
    kar_en = _KARAT_EN.get(kt.upper().strip(), '')
    col_pl = _COLOR_PL.get(col.upper().strip(), '')
    col_en = _COLOR_EN.get(col.upper().strip(), '')
    st_pl, st_en = stones_from_quality(quality)
    parts_pl = ['z ' + kar_pl if kar_pl else '']
    if col_pl:
        parts_pl.append(col_pl)
    parts_pl.append('złota')
    if st_pl:
        parts_pl.append('z ' + st_pl)
    parts_en = []
    if kar_en:
        parts_en.append(kar_en)
    if col_en:
        parts_en.append(col_en)
    parts_en.append('gold')
    parts_en.append(cat_en)
    if st_en:
        parts_en.append('with ' + st_en)
    pl = cat_pl + ' ' + ' '.join(p for p in parts_pl if p)
    en = ' '.join(parts_en)
    return pl.strip(), en.strip()

HEADER_ALIASES = {
    'pk sr': 'sr', 'sr': 'sr',
    'design no': 'design', 'design': 'design',
    'karat': 'kt', 'kt': 'kt',
    'color': 'col', 'col': 'col',
    'quality': 'quality',
    'ctg': 'ctg',
}
xlsx = r'C:\PZ\storage\outputs\SHIPMENT_7123231135_2026-06_f255bbb5\source\sales\EJL-26-27-257-Packing list of shipment-6pcs-06-06-26-Client.xlsx'
wb = openpyxl.load_workbook(xlsx, data_only=True)
ws = wb.active
headers = None
col_idx = {}
excel_rows = []
for row in ws.iter_rows(values_only=True):
    cells = [str(v).strip() if v is not None else '' for v in row]
    if headers is None:
        lower = [c.lower() for c in cells]
        normalized = [HEADER_ALIASES.get(l, l) for l in lower]
        if 'sr' in normalized:
            headers = normalized
            col_idx = {h: i for i, h in enumerate(headers)}
            print('Header:', normalized[:15])
        continue
    def get(key):
        idx = col_idx.get(key)
        return cells[idx].strip() if idx is not None and idx < len(cells) else ''
    sr_raw = get('sr')
    if not sr_raw.isdigit():
        continue
    row_data = {'sr': int(sr_raw), 'ctg': get('ctg'), 'kt': get('kt'), 'col': get('col'), 'quality': get('quality'), 'design': get('design')}
    excel_rows.append(row_data)
    print('Row:', row_data)

pf_db = sqlite3.connect(r'C:\PZ\storage\proforma_links.db')
pf_db.row_factory = sqlite3.Row
dr = pf_db.execute('SELECT editable_lines_json, updated_at FROM proforma_drafts WHERE id=30').fetchone()
lines = json.loads(dr['editable_lines_json'] or '[]')
updated_at = dr['updated_at']
pf_db.close()

design_map = {r['design']: r for r in excel_rows}
updates = {}
for ln in lines:
    pc = ln.get('product_code', '')
    dn = ln.get('design_no', '')
    er = design_map.get(dn)
    if er:
        pl, en = gen_desc(er['ctg'], er['kt'], er['col'], er['quality'])
        updates[pc] = (pl, en, er['ctg'])
        print('Match: ' + pc + ' (' + dn + '): ' + repr(pl))
    else:
        print('MISS: ' + pc + ' (' + dn + ')')

doc_db = sqlite3.connect(r'C:\PZ\storage\documents.db')
now = '2026-06-11T17:30:00Z'
for pc, (pl, en, ctg) in updates.items():
    item_type_map = {'PND': 'pendant', 'RNG': 'ring', 'EAR': 'earrings'}
    item_type = item_type_map.get(ctg.upper(), 'jewellery')
    doc_db.execute('UPDATE product_descriptions SET name_pl=?, description_pl=?, description_en=?, item_type=?, updated_at=? WHERE product_code=?', (pl, pl, en, item_type, now, pc))
    print('UPDATED ' + pc + ': ' + repr(pl))
doc_db.commit()
doc_db.close()

# Re-enrich draft 30
import urllib.request

api_key = ''
with open(r'C:\PZ\.env') as f:
    for line in f:
        if line.startswith('API_KEY='):
            api_key = line.strip().split('=', 1)[1]

pf_db2 = sqlite3.connect(r'C:\PZ\storage\proforma_links.db')
pf_db2.row_factory = sqlite3.Row
dr2 = pf_db2.execute('SELECT updated_at FROM proforma_drafts WHERE id=30').fetchone()
updated_at2 = dr2['updated_at']
pf_db2.close()

body = json.dumps({'expected_updated_at': updated_at2}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:47213/api/v1/proforma/draft/30/enrich-from-product-descriptions',
    data=body,
    headers={'Content-Type': 'application/json', 'X-API-Key': api_key, 'X-Operator': 'fix_257'},
    method='POST',
)
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
print('Draft 30 re-enriched: enriched=' + str(data.get('enriched_count')) + ' missing=' + str(data.get('missing_count')))

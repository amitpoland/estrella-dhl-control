"""
Fix blank name_pl in proforma drafts for batch SHIPMENT_7123231135_2026-06_f255bbb5.

Strategy:
1. For each draft, build Sr → product_code mapping via line_ids
2. Parse each sales Excel for: Sr → (ctg, kt, col, quality)
3. Generate full Polish/English descriptions using generate_description()
4. Upsert product_descriptions in documents.db
5. Call POST /draft/{id}/enrich-from-product-descriptions for each draft
"""
import sqlite3, json, sys, os, re
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── Config ────────────────────────────────────────────────────────────────────
BATCH_ID    = "SHIPMENT_7123231135_2026-06_f255bbb5"
SALES_DIR   = Path(r"C:\PZ\storage\outputs\SHIPMENT_7123231135_2026-06_f255bbb5\source\sales")
PF_DB       = Path(r"C:\PZ\storage\proforma_links.db")
DOC_DB      = Path(r"C:\PZ\storage\documents.db")
API_BASE    = "http://127.0.0.1:47213/api/v1"

# Read API key
api_key = ""
with open(r"C:\PZ\.env") as f:
    for line in f:
        if line.startswith("API_KEY="):
            api_key = line.strip().split("=", 1)[1]
            break
print(f"API key found: {bool(api_key)}")

# ── Description generator ─────────────────────────────────────────────────────
_CATEGORY_PL = {
    "PND": "wisiorek", "RNG": "pierścionek", "EAR": "kolczyki",
    "BRC": "bransoletka", "BAN": "bransoletka", "NEC": "naszyjnik",
    "BRO": "broszka", "SET": "zestaw biżuterii", "CHR": "zawieszka",
    "CUF": "spinki do mankietów", "NRG": "wisiorek nosowy",
    "TPN": "kolczyk nosowy",
}
_CATEGORY_EN = {
    "PND": "pendant", "RNG": "ring", "EAR": "earrings",
    "BRC": "bracelet", "BAN": "bracelet", "NEC": "necklace",
    "BRO": "brooch", "SET": "jewellery set", "CHR": "charm",
    "CUF": "cufflinks", "NRG": "nose ring", "TPN": "nose ring",
}
_KARAT_PL = {
    "14KT": "14-karatowego", "18KT": "18-karatowego", "10KT": "10-karatowego",
    "9KT": "9-karatowego", "22KT": "22-karatowego", "24KT": "24-karatowego",
    "PT": "platynowego", "SS": "srebrnego", "925": "srebrnego",
}
_KARAT_EN = {
    "14KT": "14kt", "18KT": "18kt", "10KT": "10kt", "9KT": "9kt",
    "22KT": "22kt", "24KT": "24kt", "PT": "platinum", "SS": "silver", "925": "silver",
}
_COLOR_PL = {
    "W": "białego", "Y": "żółtego", "R": "różowego",
    "WY": "białego i żółtego", "WR": "białego i różowego",
    "YR": "żółtego i różowego", "TT": "dwukolorowego",
    "P": "różowego",
}
_COLOR_EN = {
    "W": "white", "Y": "yellow", "R": "rose",
    "WY": "white and yellow", "WR": "white and rose",
    "YR": "yellow and rose", "TT": "two-tone",
    "P": "pink",
}

def stones_from_quality(quality):
    q = (quality or "").strip().upper()
    parts = re.split(r"[/,+]", q)
    pl_parts, en_parts = [], []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.match(r"^[A-Z]{1,4}-[A-Z0-9]+", p):
            pl_parts.append("diamentami")
            en_parts.append("diamonds")
        elif "RUBY" in p:
            pl_parts.append("rubinami"); en_parts.append("rubies")
        elif "EMERALD" in p or "EMLD" in p:
            pl_parts.append("szmaragdami"); en_parts.append("emeralds")
        elif "SAPPH" in p or "SAPH" in p:
            pl_parts.append("szafirami"); en_parts.append("sapphires")
        elif "PEARL" in p:
            pl_parts.append("perłami"); en_parts.append("pearls")
        else:
            pl_parts.append("kamieniami"); en_parts.append("stones")
    if not pl_parts:
        return "kamieniami", "stones"
    pl = " i ".join(dict.fromkeys(pl_parts))
    en = " and ".join(dict.fromkeys(en_parts))
    return pl, en

def generate_description(ctg, kt, col, quality):
    cat_pl = _CATEGORY_PL.get((ctg or "").upper().strip(), "wyrób")
    cat_en = _CATEGORY_EN.get((ctg or "").upper().strip(), "item")
    kar_pl = _KARAT_PL.get((kt or "").upper().strip(), "")
    kar_en = _KARAT_EN.get((kt or "").upper().strip(), "")
    col_pl = _COLOR_PL.get((col or "").upper().strip(), "")
    col_en = _COLOR_EN.get((col or "").upper().strip(), "")
    stones_pl, stones_en = stones_from_quality(quality)
    if kar_pl:
        if col_pl:
            pl = f"{cat_pl} z {kar_pl} {col_pl} złota z {stones_pl}"
            en = f"{kar_en} {col_en} gold {cat_en} with {stones_en}"
        else:
            pl = f"{cat_pl} z {kar_pl} złota z {stones_pl}"
            en = f"{kar_en} gold {cat_en} with {stones_en}"
    else:
        pl = f"{cat_pl} z {stones_pl}"
        en = f"{cat_en} with {stones_en}"
    return pl, en

# ── Draft → Excel mapping ─────────────────────────────────────────────────────
DRAFT_TO_EXCEL = {
    27: "EJL-26-27-254-Shipment packing list of -8pcs 06.06.26-Client.xlsx",
    28: "EJL-26-27-255-Shipment packing list of 1pc-06.06.26-Client.xlsx",
    29: "EJL-26-27-256-Shipment packing list of 68pcs-06.06.26-Client.xlsx",
    30: "EJL-26-27-257-Packing list of shipment-6pcs-06-06-26-Client.xlsx",
    31: "EJL-26-27-259-Packing list of shipment-1pc-06-06-26-Client.xlsx",
    32: "EJL-26-27-258 Shipment packing list of 25pcs-06.06.26 Client.xlsx",
    33: "EJL-26-27-260-Packing list of shipment-1pc-06.06.26-Client.xlsx",
}

# ── Excel reader ──────────────────────────────────────────────────────────────
def read_excel_rows(xlsx_path):
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    headers = None
    col_idx = {}
    rows = []
    for row in ws.iter_rows(values_only=True):
        cells = [str(v).strip() if v is not None else "" for v in row]
        if headers is None:
            lower = [c.lower() for c in cells]
            if "sr" in lower and ("design" in lower or "design description" in lower):
                headers = lower
                col_idx = {h: i for i, h in enumerate(headers)}
            continue
        def get(key):
            idx = col_idx.get(key)
            return cells[idx].strip() if idx is not None and idx < len(cells) else ""
        sr_raw = get("sr")
        if not sr_raw.isdigit():
            continue
        sr = int(sr_raw)
        ctg = get("ctg")
        kt = get("kt")
        col = get("col")
        quality = get("quality")
        design = get("design")
        rows.append({"sr": sr, "ctg": ctg, "kt": kt, "col": col, "quality": quality, "design": design})
    return rows

# ── Main ──────────────────────────────────────────────────────────────────────
pf_db = sqlite3.connect(str(PF_DB))
pf_db.row_factory = sqlite3.Row

doc_db = sqlite3.connect(str(DOC_DB))
now = "2026-06-11T17:00:00Z"
updates = {}  # product_code → (pl, en, ctg, kt, col, quality)

print("\n=== Step 1: Parse Excels + Build product_code → description map ===")

for draft_id, excel_name in DRAFT_TO_EXCEL.items():
    xlsx_path = SALES_DIR / excel_name
    if not xlsx_path.exists():
        print(f"  WARNING: Excel not found: {xlsx_path}")
        continue

    excel_rows = read_excel_rows(str(xlsx_path))
    sr_map = {r["sr"]: r for r in excel_rows}

    dr = pf_db.execute(
        "SELECT editable_lines_json, client_name FROM proforma_drafts WHERE id=?", (draft_id,)
    ).fetchone()
    if not dr:
        print(f"  WARNING: draft {draft_id} not found")
        continue

    lines = json.loads(dr["editable_lines_json"] or "[]")
    print(f"\nDraft {draft_id} ({dr['client_name']}) - {len(lines)} lines, {len(excel_rows)} excel rows")

    for ln in lines:
        pc = ln.get("product_code", "")
        line_id = ln.get("line_id")
        design_no = ln.get("design_no", "")

        # Primary: match by line_id → Sr
        excel_row = sr_map.get(int(line_id)) if line_id is not None else None
        # Fallback: match by design_no
        if excel_row is None:
            excel_row = next((r for r in excel_rows if r["design"] == design_no), None)

        if excel_row is None:
            print(f"  MISS: line_id={line_id} design_no={design_no} pc={pc}")
            continue

        ctg = excel_row["ctg"]
        kt = excel_row["kt"]
        col = excel_row["col"]
        quality = excel_row["quality"]

        pl, en = generate_description(ctg, kt, col, quality)
        updates[pc] = (pl, en, ctg, kt, col, quality)
        print(f"  {pc}: '{pl}'")

pf_db.close()

# Step 2: Update product_descriptions
print(f"\n=== Step 2: Updating {len(updates)} product_descriptions ===")
item_type_map = {
    "PND": "pendant", "RNG": "ring", "EAR": "earrings",
    "BRC": "bracelet", "BAN": "bracelet", "NEC": "necklace",
    "TPN": "nose_ring", "NRG": "nose_ring",
}

for pc, (pl, en, ctg, kt, col, quality) in updates.items():
    item_type = item_type_map.get((ctg or "").upper(), "jewellery")
    existing = doc_db.execute(
        "SELECT source, name_pl FROM product_descriptions WHERE product_code=?", (pc,)
    ).fetchone()
    if existing:
        if existing[0] in ("auto", None, ""):
            doc_db.execute("""
                UPDATE product_descriptions
                SET name_pl=?, description_pl=?, description_en=?, item_type=?, updated_at=?
                WHERE product_code=?
            """, (pl, pl, en, item_type, now, pc))
            print(f"  UPDATED {pc}: '{pl}'")
        else:
            print(f"  SKIP {pc}: source={existing[0]}")
    else:
        doc_db.execute("""
            INSERT INTO product_descriptions
            (product_code, item_type, name_pl, description_pl, description_en, description_block,
             material_pl, purpose_pl, description_line, source, created_at, updated_at)
            VALUES (?,?,?,?,?,'','','','','auto',?,?)
        """, (pc, item_type, pl, pl, en, now, now))
        print(f"  INSERTED {pc}: '{pl}'")

doc_db.commit()
doc_db.close()

# Step 3: Call enrich endpoint for each draft
import urllib.request, urllib.error

print("\n=== Step 3: Calling enrich-from-product-descriptions ===")

for draft_id in DRAFT_TO_EXCEL.keys():
    pf_db2 = sqlite3.connect(str(PF_DB))
    dr = pf_db2.execute(
        "SELECT updated_at, client_name FROM proforma_drafts WHERE id=?", (draft_id,)
    ).fetchone()
    pf_db2.close()

    if not dr:
        print(f"  Draft {draft_id}: not found")
        continue

    updated_at, client_name = dr
    body_bytes = json.dumps({"expected_updated_at": updated_at}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/proforma/draft/{draft_id}/enrich-from-product-descriptions",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Operator": "system_fix_name_pl",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        enriched = data.get("enriched_count", "?")
        missing = data.get("missing_count", "?")
        print(f"  Draft {draft_id} ({client_name}): enriched={enriched} missing={missing} OK")
    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="replace")
        print(f"  Draft {draft_id} ({client_name}): HTTP {e.code} — {body_err[:300]}")
    except Exception as ex:
        print(f"  Draft {draft_id} ({client_name}): ERROR — {ex}")

print("\n=== Done ===")

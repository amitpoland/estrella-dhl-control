"""
Inspection-only: explain why proforma 465611619 has only 1 invoicecontent line.
No live writes. No DB writes. Reads:
  - proforma_drafts row
  - sales / packing / invoice_lines for batch
  - rebuilds preview + proforma request to compare against current state
  - re-fetches the live wFirma proforma to confirm actual line count
"""
from __future__ import annotations
import os, sys, json, sqlite3, xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
env_path = ROOT / "service" / ".env"
if env_path.exists():
    for raw in env_path.read_text().splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#") or "=" not in ln: continue
        k,_,v = ln.partition("=")
        v = v.split("#",1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import wfirma_db as wfdb
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client as wf
from app.api import routes_proforma as rp

# Wire DB paths from settings storage_root (same as service runtime)
storage = Path(getattr(settings, "storage_root", "/Users/amitgupta/Library/Application Support/estrellajewels"))
print(f"storage_root: {storage}")
ddb.init_document_db(storage / "documents.db")
pdb.init_packing_db(storage / "packing.db")
wdb.init_warehouse_db(storage / "warehouse.db")
wfdb.init_wfirma_db(storage / "wfirma.db")

BATCH  = "SHIPMENT_3369800350_2026-05_e31a0999"
CLIENT = "Juliany EOOD"
WID    = "465611619"

print(f"\n── Inspecting batch={BATCH!r} client={CLIENT!r} proforma={WID!r}\n")

# 1. proforma_drafts row + source_lines_json
print("── (1) proforma_drafts row + source_lines_json ──")
proforma_db_path = storage / "proforma_links.db"
draft = pildb.get_draft(proforma_db_path, BATCH, CLIENT)
if draft is None:
    print(f"  ❌ no draft row for ({BATCH!r}, {CLIENT!r})")
    src_count = -1
    src_lines = []
else:
    print(f"  draft.id     = {draft.id}")
    print(f"  status       = {draft.status}")
    print(f"  wfirma_id    = {draft.wfirma_proforma_id}")
    print(f"  currency     = {draft.currency}")
    src_lines = json.loads(draft.source_lines_json) if draft.source_lines_json else []
    src_count = len(src_lines)
    print(f"  source_lines_json count = {src_count}")
    pcs = Counter([(l.get('product_code') or '<none>') for l in src_lines])
    for pc, n in pcs.most_common(10):
        print(f"    {pc:30s}  ×{n}")

# 2. preview today
print("\n── (2) routes_proforma._build_preview today ──")
preview = rp._build_preview(BATCH, CLIENT)
preview_lines = preview.get("lines", [])
print(f"  preview lines = {len(preview_lines)}  ready={preview.get('ready')}")
print(f"  blocking_reasons:")
for br in preview.get("blocking_reasons", [])[:5]:
    print(f"    • {br}")
ready_count    = sum(1 for l in preview_lines if l.get("product_match"))
unmatched      = sum(1 for l in preview_lines if not l.get("product_match"))
missing_price  = sum(1 for l in preview_lines if l.get("unit_price") is None)
print(f"  per-line: matched={ready_count} unmatched={unmatched} missing_price={missing_price}")
pcs2 = Counter([(l.get('product_code') or '<none>') for l in preview_lines])
print(f"  product_code distribution (top 10):")
for pc, n in pcs2.most_common(10):
    print(f"    {pc:30s}  ×{n}")

# 3. how many lines _build_proforma_request would emit
print("\n── (3) _build_proforma_request today ──")
try:
    req = rp._build_proforma_request(preview)
    print(f"  request line count = {len(req.lines)}")
    pc3 = Counter([l.product_code for l in req.lines])
    for pc, n in pc3.most_common(10):
        print(f"    {pc:30s}  ×{n}")
except Exception as exc:
    print(f"  ❌ {type(exc).__name__}: {exc}")
    req = None

# 4. how many invoicecontent rows would the XML carry
print("\n── (4) _build_proforma_xml today ──")
if req is not None and req.lines:
    try:
        xml_body = wf._build_proforma_xml(req)
        ic_count = xml_body.count("<invoicecontent>")
        print(f"  XML invoicecontent count = {ic_count}")
    except Exception as exc:
        print(f"  ❌ {type(exc).__name__}: {exc}")

# 5. live wFirma proforma — confirm actual row count
print("\n── (5) live wFirma proforma 465611619 ──")
try:
    inv_xml = wf.fetch_invoice_xml(WID)
    inv = ET.fromstring(inv_xml).find(".//invoice")
    ics = inv.findall(".//invoicecontent")
    print(f"  invoicecontent count = {len(ics)}")
    for ic in ics:
        gid = ic.find("good")
        print(f"    line_id={ic.findtext('id')}  good_id={(gid.findtext('id') if gid is not None else '?')}  name={(ic.findtext('name') or '')[:60]!r}")
    print(f"  invoice <type>          = {inv.findtext('type')!r}")
    print(f"  invoice <fullnumber>    = {inv.findtext('fullnumber')!r}")
    print(f"  invoice <created>       = {inv.findtext('created')!r}")
    print(f"  invoice <netto>         = {inv.findtext('netto')!r}")
except Exception as exc:
    print(f"  ❌ {type(exc).__name__}: {exc}")

# 6. raw sales / packing / invoice_lines coverage for Juliany
print("\n── (6) raw source data coverage ──")
sales_docs = ddb.get_sales_documents(BATCH)
juliany_docs = [d for d in sales_docs if (d.get("client_name") or "").strip() == CLIENT]
print(f"  sales_documents (any client): {len(sales_docs)}; for Juliany: {len(juliany_docs)}")

spl = ddb.get_sales_packing_lines(BATCH)
juliany_spl = [r for r in spl if (r.get("client_name") or "").strip() == CLIENT]
print(f"  sales_packing_lines (any):    {len(spl)}; for Juliany: {len(juliany_spl)}")
designs = sorted({(r.get('design_no') or '') for r in juliany_spl})
print(f"  Juliany designs: {designs}")

stwf = ddb.query_sales_to_wfirma(BATCH)
juliany_stwf = [r for r in stwf if (r.get("client_name") or "").strip() == CLIENT]
print(f"  query_sales_to_wfirma: total={len(stwf)} Juliany={len(juliany_stwf)}")
for r in juliany_stwf[:20]:
    print(f"    design={r.get('design_no')!r} pc={r.get('product_code')!r} qty={r.get('qty')} match={r.get('product_match')}")

inv_lines = ddb.get_invoice_lines_for_batch(BATCH)
priced_pcs = Counter([(r.get('product_code') or '') for r in inv_lines if r.get('unit_price')])
print(f"  invoice_lines: {len(inv_lines)} rows; priced product_codes: {len(priced_pcs)}")
for pc, n in priced_pcs.most_common(10):
    print(f"    {pc:30s}  ×{n}")

# 7. wfirma_products mapping coverage for the involved product_codes
print("\n── (7) wfirma_products mapping coverage ──")
involved_codes = sorted({(r.get('product_code') or '') for r in juliany_stwf if r.get('product_code')})
for pc in involved_codes:
    p = wfdb.get_product(pc)
    wid_local = (p or {}).get('wfirma_product_id') or '<unmapped>'
    print(f"    {pc:30s} → {wid_local}")

print("\n── DONE ──")

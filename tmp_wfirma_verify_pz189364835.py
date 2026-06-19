# READ-ONLY post-edit verification: re-fetch wFirma PZ 189364835 and score the
# four acceptance criteria. GET only. No writes, no mutation.
import os, sys, xml.etree.ElementTree as ET
os.chdir(r"C:\PZ")
sys.path.insert(0, r"C:\PZ")
from app.services import wfirma_client as wc

res = wc.fetch_warehouse_pz("189364835")
raw = res.raw_response or ""
with open(r"C:\Users\Super Fashion\PZ APP\tmp_pz189364835_postedit.xml", "w", encoding="utf-8") as f:
    f.write(raw)

print("GET ok:", res.ok, "| pz_number:", res.pz_number, "| error:", res.error)
root = ET.fromstring(raw)
wd = root.find(".//warehouse_document")
print("doc status   :", (wd.findtext("status") or "").strip())
print("doc netto    :", (wd.findtext("netto") or "").strip())
print("doc brutto   :", (wd.findtext("brutto") or "").strip())
print("created      :", (wd.findtext("created") or "").strip())
print("modified     :", (wd.findtext("modified") or "").strip())
print("-" * 60)

contents = wd.find("warehouse_document_contents")
for i, c in enumerate(contents.findall("warehouse_document_content"), start=1):
    good_id = (c.findtext("good/id") or "").strip()
    price = (c.findtext("price") or "").strip()
    pmod  = (c.findtext("price_modified") or "").strip()
    netto = (c.findtext("netto") or "").strip()
    count = (c.findtext("count") or "").strip()
    print(f"LINE {i}: good={good_id} count={count}")
    print(f"   document <price>          = {price}")
    print(f"   document <price_modified> = {pmod}")
    print(f"   document line <netto>     = {netto}")
    parcels = c.find("warehouse_good_parcels")
    for p in parcels.findall("warehouse_good_parcel"):
        pid = (p.findtext("id") or "").strip()
        pcount = (p.findtext("count") or "").strip()
        pp = (p.findtext("purchase_price") or "").strip()
        prod = (p.findtext("production_price") or "").strip()
        print(f"   PARCEL id={pid} count={pcount} purchase_price={pp} production_price={prod}")
    print()

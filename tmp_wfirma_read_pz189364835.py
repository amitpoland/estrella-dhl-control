# READ-ONLY diagnostic: fetch wFirma PZ document 189364835 (PZ 4/6/2026).
# Uses the proven GET-only fetch_warehouse_pz(). No writes. No cancel. No mutation.
import os, sys
os.chdir(r"C:\PZ")
sys.path.insert(0, r"C:\PZ")

from app.services import wfirma_client as wc

print("=== check_config ===")
try:
    print(wc.check_config())
except Exception as e:
    print("config error:", repr(e))

print("\n=== fetch_warehouse_pz('189364835')  [GET warehouse_document_p_z/get/189364835] ===")
res = wc.fetch_warehouse_pz("189364835")
print("ok:", res.ok)
print("pz_doc_id:", res.pz_doc_id)
print("pz_number:", res.pz_number)
print("error:", res.error)
raw = res.raw_response or ""
out = r"C:\Users\Super Fashion\PZ APP\tmp_pz189364835_raw.xml"
with open(out, "w", encoding="utf-8") as f:
    f.write(raw)
print("\nRAW XML written to:", out, "(", len(raw), "chars )")

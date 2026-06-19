# READ-ONLY independent read-back of the closure event. Reads audit.json,
# recomputes the integrity hash, asserts fields. No write. Reuses the closure
# module's own verifier (main() is guarded, so importing runs nothing).
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "cm", r"C:\Users\Super Fashion\PZ APP\stage_valuation_execution_verified_189364835.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ev = m._verify_persisted({})          # raises on missing event / field / hash mismatch
d = ev["detail"]
print("READ-BACK: OK (event present, integrity hash recomputed and matched)")
print("  event           :", ev["event"])
print("  write_ts        :", ev["ts"])
print("  edit_executed   :", d["edit_executed"])
print("  edit_executed_at:", d["edit_executed_at"])
print("  document_id     :", d["document_id"], "(", d["pz_number"], ")")
print("  correction      :", d["correction_amount_display"])
print("  integrity_sha256:", d["integrity_sha256"])
acc = d["acceptance"]
print("  netto           :", acc["netto_pln"]["value"], "pass=", acc["netto_pln"]["pass"])
print("  price_modified  :", acc["price_modified"]["L1"], "/", acc["price_modified"]["L2"])
print("  parcel L1       :", acc["parcel_purchase_price"]["L1"])
print("  parcel L2       :", acc["parcel_purchase_price"]["L2"])
ev2 = d["evidence"]
print("  pre_edit_xml    :", ev2["pre_edit_xml"]["sha256"])
print("  post_edit_xml   :", ev2["post_edit_xml"]["sha256"])

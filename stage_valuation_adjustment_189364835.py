# Operator-run: append the approved valuation-adjustment record to the AWB 2315714531 audit trail.
# Read + append-only timeline event + atomic replace. Idempotent. No wFirma write.
import os, sys, json, datetime, tempfile
os.chdir(r"C:\PZ"); sys.path.insert(0, r"C:\PZ")

p = r"C:\PZ\storage\outputs\SHIPMENT_2315714531_2026-06_ffe086f3\audit.json"
a = json.load(open(p, encoding="utf-8"))
tl = a.get("timeline") or []

EVENT = "pz_valuation_correction_approved"
if any(isinstance(e, dict) and e.get("event") == EVENT
       and str((e.get("detail") or {}).get("document_id")) == "189364835" for e in tl):
    print("ALREADY_RECORDED — idempotent, nothing written."); raise SystemExit(0)

now = datetime.datetime.now(datetime.timezone.utc).isoformat()
detail = {
    "record_type": "valuation_adjustment (NOT linkage — same document number, no old->new relationship)",
    "document_id": "189364835",
    "pz_number": "PZ 4/6/2026",
    "original_net_pln": 2280.14,
    "corrected_net_pln": 2736.94,
    "authority_net_pln": 2736.87,
    "rounding_diff_pln": 0.07,
    "rounding_pct": 0.0026,
    "method": "direct UI edit of pending document; no cancel/recreate",
    "line_targets": ["L1 36.55 x 66 = 2412.30", "L2 81.16 x 4 = 324.64"],
    "reason": "Freight and insurance allocation correction following AWB 2315714531 landed-cost authority correction",
    "customs_unchanged": {"cif_usd": 732.0, "freight_insurance_usd": 125.0, "duty_pln": 62.0},
    "materiality": "immaterial; no material impact on inventory valuation, customs value, VAT, duty, or financial reporting",
    "approved_by": "Accounting",
    "approved_at": now,
    "edit_executed": False,
    "edit_executed_at": None,
    "incident": "AWB-2315714531-2026-06 (closed; not reopened)",
}
tl.append({"ts": now, "event": EVENT, "trigger_source": "operator", "actor": "accounting", "detail": detail})
a["timeline"] = tl
d = os.path.dirname(p); fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(a, f, ensure_ascii=False, indent=2)
os.replace(tmp, p)
print("RECORDED valuation-adjustment event at", now)

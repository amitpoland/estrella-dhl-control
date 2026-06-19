#!/usr/bin/env python3
"""One-shot operator unblock: promote a CONFIRMED-quality vision_invoice proposal
into the PZ engine authority rows so the engine bridge fires and PZ generates.

This is the manual form of "Stage C" (bridge confirmed vision -> engine). It is
deliberately conservative:

  * reads audit["vision_invoice"] (the advisory OCR/AI proposal already on disk),
  * validates that the line-item totals reconcile to the proposal FOB within $1,
  * refuses to run if reconciliation fails or no line items exist,
  * writes ONLY the engine-authority sidecar keys the bridge reads
    (_pz_engine_authority_rows / _pz_engine_authority_meta / _customs_aggregation)
    plus operator-confirmation provenance on vision_invoice,
  * NEVER touches invoice_totals / rows / clearance / wfirma_export (the engine
    recomputes invoice_totals from the bridged rows on the next Retry PZ).

Default is DRY-RUN (prints the rows, writes nothing). Pass --apply to write.

Usage:
  python unblock_vision_pz.py "C:\\PZ\\storage\\outputs\\SHIPMENT_2315714531_2026-06_ffe086f3"            # dry-run
  python unblock_vision_pz.py "C:\\PZ\\storage\\outputs\\SHIPMENT_2315714531_2026-06_ffe086f3" --apply    # write
"""
import json
import os
import re
import sys
import tempfile
import time

_ITEM_TYPES = ["CUFFLINK", "EARRINGS", "EARRING", "BRACELET", "NECKLACE",
               "BANGLE", "ANKLET", "PENDANT", "RING"]
_FORBIDDEN = ("UNKNOWN", "metal szlachetny", "Wyrob jubilerski",
              "Wyrób jubilerski", "grouped invoice aggregate", "wysadzany")


def infer_item_type(desc: str) -> str:
    du = (desc or "").upper()
    for t in _ITEM_TYPES:
        if t in du:
            return t
    m = re.search(r"\(([A-Z]+)", du)
    if m and m.group(1) in _ITEM_TYPES:
        return m.group(1)
    return "ITEM"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        print("ERROR: pass the batch output dir (folder containing audit.json)")
        sys.exit(2)
    batch_dir = args[0]
    audit_path = os.path.join(batch_dir, "audit.json")
    if not os.path.isfile(audit_path):
        print(f"ERROR: audit.json not found at {audit_path}")
        sys.exit(2)

    with open(audit_path, "r", encoding="utf-8") as fh:
        audit = json.load(fh)

    vi = audit.get("vision_invoice") or {}
    items = vi.get("line_items") or []
    inv_no = (vi.get("invoice_no") or "").strip()
    fob_proposal = float(vi.get("fob_usd") or 0)
    currency = (vi.get("currency") or "").upper()

    if not items:
        print("ABORT: vision_invoice has no line_items — nothing to promote.")
        sys.exit(1)
    if currency and currency != "USD":
        print(f"ABORT: vision_invoice currency is {currency!r}, not USD.")
        sys.exit(1)

    rows = []
    line_sum = 0.0
    qty_sum = 0.0
    for i, it in enumerate(items, start=1):
        qty = float(it.get("quantity") or 0)
        total = float(it.get("total_usd") or 0)
        unit_p = float(it.get("unit_price_usd") or (total / qty if qty else 0))
        desc = (it.get("description") or "").strip()
        hsn = (it.get("hsn") or "").strip()
        if qty <= 0 or total <= 0:
            print(f"ABORT: line {i} has qty={qty} total={total} — must both be > 0.")
            sys.exit(1)
        row = {
            "line_position":   i,
            "invoice_number":  inv_no,
            "description":     desc,
            "description_en":  desc,
            "item_type":       infer_item_type(desc),
            "hsn_code":        hsn,
            "quantity":        int(qty) if qty == int(qty) else qty,
            "uom":             "PCS",
            "unit_price":      round(unit_p, 4),
            "line_total_usd":  round(total, 2),
            "line_total":      round(total, 2),
        }
        rows.append(row)
        line_sum += total
        qty_sum += qty

    line_sum = round(line_sum, 2)
    blob = json.dumps(rows, ensure_ascii=False)
    for tok in _FORBIDDEN:
        if tok in blob:
            print(f"ABORT: forbidden token in rows: {tok!r}")
            sys.exit(1)
    if fob_proposal > 0 and abs(line_sum - fob_proposal) > 1.0:
        print(f"ABORT: rows sum ${line_sum:,.2f} != proposal FOB ${fob_proposal:,.2f} "
              f"(>$1 drift) — refusing to promote unreconciled data.")
        sys.exit(1)

    fob = fob_proposal if fob_proposal > 0 else line_sum
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print("=== PROMOTE PLAN (vision_invoice -> engine authority rows) ===")
    print(f" batch     : {os.path.basename(batch_dir)}")
    print(f" invoice   : {inv_no}   supplier: {vi.get('supplier')}")
    print(f" FOB (USD) : {fob:,.2f}   qty total: {int(qty_sum)}   rows: {len(rows)}")
    for r in rows:
        print(f"   [{r['line_position']}] {r['quantity']:>4} x ${r['unit_price']:<7} "
              f"= ${r['line_total_usd']:<8} {r['item_type']:<8} HSN {r['hsn_code']}  "
              f"{r['description'][:54]}")
    print("=" * 60)

    if not apply:
        print("DRY-RUN — nothing written. Re-run with --apply to commit, then click "
              "Retry PZ in the dashboard.")
        return

    audit["_pz_engine_authority_rows"] = rows
    audit["_pz_engine_authority_meta"] = {
        "source":            "vision_invoice_operator_unblock",
        "captured_at":       now,
        "fob_sum_preserved": line_sum,
        "row_count":         len(rows),
        "invoice_pdf":       vi.get("source_file") or "inv_122.pdf",
    }
    audit["_customs_aggregation"] = {
        "source":            "vision_invoice_operator_unblock",
        "position_count":    len(rows),
        "fob_sum_preserved": line_sum,
    }
    vi["operator_confirmed"] = True
    vi["status"] = "confirmed"
    vi["confirmed_by"] = os.environ.get("PZ_OPERATOR", "operator_manual_unblock")
    vi["confirmed_at"] = now
    audit["vision_invoice"] = vi

    # Atomic write
    d = os.path.dirname(audit_path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, audit_path)
    print(f"APPLIED: wrote {len(rows)} authority rows (FOB ${fob:,.2f}) to {audit_path}")
    print("Next: open the shipment in the dashboard and click 'Retry PZ'.")


if __name__ == "__main__":
    main()

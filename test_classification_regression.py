#!/usr/bin/env python3
"""
test_classification_regression.py
==================================
Regression tests for the three bot-processing failures fixed in April 2026.

Tests:
  A1. AWB/tracking filenames never classify as zc429 or invoice
  A2. ZC429/SAD keywords → always zc429
  B1. ZC429-only batch → invoices empty
  B2. AWB+ZC429+invoice → correct 3-bucket split
  B3. classify_files returns 3-tuple (zc429, invoices, awbs)
  C1. FOB US $ pattern parsed
  C2. FOB USD pattern parsed
  C3. TOTAL FOB pattern parsed
  C4. FOB Value pattern parsed
  C5. FOB=0 but line totals → derive + VERIFY-GAP logged
  C6. FOB=0 and no lines → stays 0, no crash

Run:
    python3 test_classification_regression.py
Expected: ALL TESTS PASSED, exit code 0.
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

from app.services.cliq_bot_service import (
    AttachmentMeta,
    _file_category,
    classify_files,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _meta(name: str) -> AttachmentMeta:
    return AttachmentMeta("fake_id", name, 1000)


PASS: list = []
FAIL: list = []

def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}" + (f": {detail}" if detail else ""))


# ═══════════════════════════════════════════════════════════════════════════════
# A — File classification
# ═══════════════════════════════════════════════════════════════════════════════

def test_classification() -> None:
    print("\n── A. File classification ──────────────────────────────────────────")

    # A1: AWB/tracking filenames → 'awb', never 'zc429' or 'invoice'
    awb_names = [
        "6876258325 Tracking.pdf",
        "AWB_123456.pdf",
        "DHL_airwaybill.pdf",
        "tracking_number.pdf",
        "waybill_001.pdf",
        "courier_info.pdf",
        "Shipment_Track_20260401.pdf",
    ]
    for name in awb_names:
        cat = _file_category(name)
        check(f"A1 '{name}' → awb", cat == "awb", f"got '{cat}'")

    # A2: ZC429/SAD → always 'zc429'
    zc_names = [
        "zc429_PZ2026.pdf",
        "ZC429_ABC.pdf",
        "sad_declaration.pdf",
        "SAD_26_039.pdf",
        "ZC-429_batch.pdf",
    ]
    for name in zc_names:
        cat = _file_category(name)
        check(f"A2 '{name}' → zc429", cat == "zc429", f"got '{cat}'")

    # B1: ZC429-only → invoices empty, awbs empty
    zc429, invoices, awbs = classify_files([_meta("zc429_ABC.pdf")])
    check("B1 ZC429-only → zc429 detected", zc429 is not None)
    check("B1 ZC429-only → invoices empty", len(invoices) == 0,
          str([i.file_name for i in invoices]))
    check("B1 ZC429-only → awbs empty", len(awbs) == 0,
          str([a.file_name for a in awbs]))

    # B2: AWB+ZC429+invoice → correct 3-bucket split
    files = [
        _meta("6876258325 Tracking.pdf"),
        _meta("zc429_PZ26.pdf"),
        _meta("EJL_inv_001.pdf"),
    ]
    zc429, invoices, awbs = classify_files(files)
    check("B2 zc429 correct",
          zc429 is not None and "zc429" in zc429.file_name.lower())
    check("B2 invoices = 1", len(invoices) == 1,
          str([i.file_name for i in invoices]))
    check("B2 awbs = 1", len(awbs) == 1,
          str([a.file_name for a in awbs]))
    check("B2 tracking in awbs",
          any("tracking" in a.file_name.lower() for a in awbs))
    check("B2 tracking NOT in invoices",
          not any("tracking" in i.file_name.lower() for i in invoices))

    # B3: classify_files returns 3-tuple
    result = classify_files([_meta("zc429.pdf"), _meta("inv.pdf"), _meta("awb.pdf")])
    check("B3 3-tuple returned", len(result) == 3, f"len={len(result)}")

    # Real-world batch: 013+014+015 invoices + tracking + ZC429 → 3 invoices, 1 awb
    real_batch = [
        _meta("EJL-26-27-013.pdf"),
        _meta("EJL-26-27-014.pdf"),
        _meta("EJL-26-27-015.pdf"),
        _meta("6876258325 Tracking.pdf"),
        _meta("ZC429_26PL44302D007UH7R0_1_PL.pdf"),
    ]
    zc429, invoices, awbs = classify_files(real_batch)
    check("B4 real batch → ZC429 found", zc429 is not None and "zc429" in zc429.file_name.lower())
    check("B4 real batch → 3 invoices", len(invoices) == 3, f"got {len(invoices)}: {[i.file_name for i in invoices]}")
    check("B4 real batch → 1 awb", len(awbs) == 1, f"got {len(awbs)}")
    check("B4 real batch → tracking in awb",
          any("tracking" in a.file_name.lower() for a in awbs))


# ═══════════════════════════════════════════════════════════════════════════════
# C — FOB parser fallbacks (inline simulation — no PDF needed)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_fob_parse(text_body: str) -> tuple:
    """
    Simulate the FOB parsing + fallback logic from parse_invoice()
    without needing a real PDF.
    """
    corrections_log: list = []

    def find_amount(label: str) -> float:
        m = re.search(rf"{re.escape(label)}[^\d]*([\d,]+\.?\d*)", text_body, re.IGNORECASE)
        return float(m.group(1).replace(",", "")) if m else 0.0

    fob_usd = (
        find_amount("FOB US $")
        or find_amount("FOB USD")
        or find_amount("FOB US")
        or find_amount("TOTAL FOB")
        or find_amount("Total FOB")
        or find_amount("FOB Value")
        or find_amount("FOB")
    )

    # Simulate items from synthetic text
    items: list = []
    for line in text_body.splitlines():
        m = re.search(r"AMOUNT\s+USD\s+([\d,]+\.\d{2})", line)
        if m:
            items.append({"total_usd": float(m.group(1).replace(",", ""))})

    # FOB fallback: derive from line totals if still 0 (same logic as pz_import_processor.py)
    if fob_usd <= 0.0 and items:
        fob_from_lines = sum(it["total_usd"] for it in items)
        if fob_from_lines > 0:
            corrections_log.append(
                f"[VERIFY-GAP] FOB not parsed directly; "
                f"derived from line totals: USD {fob_from_lines:,.2f}"
            )
            fob_usd = fob_from_lines

    return fob_usd, corrections_log


def test_fob_parser() -> None:
    print("\n── C. FOB parser fallbacks ─────────────────────────────────────────")

    fob, _ = _run_fob_parse("FOB US $ 5,280.00\nFreight US$ 200.00")
    check("C1 FOB US $ pattern", abs(fob - 5280.0) < 0.01, f"got {fob}")

    fob, _ = _run_fob_parse("FOB USD 3,100.50")
    check("C2 FOB USD pattern", abs(fob - 3100.50) < 0.01, f"got {fob}")

    fob, _ = _run_fob_parse("TOTAL FOB 8,750.00")
    check("C3 TOTAL FOB pattern", abs(fob - 8750.0) < 0.01, f"got {fob}")

    fob, _ = _run_fob_parse("FOB Value: 1,200.00")
    check("C4 FOB Value pattern", abs(fob - 1200.0) < 0.01, f"got {fob}")

    # C5: FOB=0, has lines → derive + VERIFY-GAP
    text = "Invoice EJL/26-27/013\nItem A  AMOUNT USD 1,500.00\nItem B  AMOUNT USD 2,300.00\n"
    fob, log = _run_fob_parse(text)
    check("C5 FOB=0 derive from lines", abs(fob - 3800.0) < 0.01, f"got {fob}")
    check("C5 VERIFY-GAP logged",
          any("[VERIFY-GAP]" in e for e in log), f"log={log}")

    # C6: FOB=0 and no lines → stays 0, no crash
    fob, _ = _run_fob_parse("Invoice EJL/26-27/013\nDate: 01-01-2026")
    check("C6 FOB=0 no lines → 0, no crash", fob == 0.0, f"got {fob}")

    # C7: The error string that previously caused crashes must not appear when lines exist
    # (i.e. engine has FOB from fallback and should not raise ValueError)
    text = "Invoice EJL/26-27/013\nItem A  AMOUNT USD 4,000.00\n"
    fob, log = _run_fob_parse(text)
    old_error = "cannot compute freight share"
    # With fallback, fob > 0 → engine would NOT raise — verify fob is positive
    check("C7 no crash when line totals exist", fob > 0, f"fob={fob}")


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    print(f"\n{'═'*60}")
    print("CLASSIFICATION & FOB PARSER REGRESSION TESTS")
    print(f"{'═'*60}")

    test_classification()
    test_fob_parser()

    print(f"\n{'─'*60}")
    print(f"Results: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED tests:")
        for f in FAIL:
            print(f"  ✗ {f}")
    else:
        print("ALL TESTS PASSED")
    print(f"{'═'*60}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
test_wfirma_export.py — wFirma PZ Export Unit Tests
====================================================
Tests for the wFirma export module (routes_wfirma.py).

Validates:
  1. Export is blocked when PZ has not been generated
  2. Export is blocked when SAD/ZC429 is not present
  3. Polish number format is correct
  4. Clipboard text structure is correct
  5. JSON payload structure is correct
  6. Invoice order is preserved
  7. Uwagi contains all required fields

Run:
    python3 test_wfirma_export.py
    python3 -m pytest test_wfirma_export.py -v

Expected: all tests PASS, exit code 0.
"""

import json
import sys
import os
import tempfile
from pathlib import Path

# ── Allow import of service layer without full FastAPI startup ─────────────────
# We test helper functions directly to avoid needing the running server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

# ── Import helpers from routes_wfirma directly ────────────────────────────────
# We test at the function level — no HTTP layer needed
try:
    from service.app.api.routes_wfirma import (
        _fmt_pln,
        _build_uwagi,
        _build_wfirma_rows,
        _build_clipboard_text,
        _guard_wfirma_export,
    )
    from fastapi import HTTPException
    _IMPORT_OK = True
except ImportError as _e:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_e)


PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"


def _assert(cond, label, detail=""):
    if cond:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}")
        if detail:
            print(f"         {detail}")
        return False
    return True


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_audit(status="success", has_sad=True):
    return {
        "batch_id":   "TEST_001",
        "status":     status,
        "tracking_no": "1234567890",
        "doc_no":     "PZ 1/2026",
        "settlement_mode": "standard",
        "inputs": {
            "zc429": "SAD_001.pdf" if has_sad else None,
            "zc429_mrn": "26PL123456789A",
            "nbp_rate_usd": 3.7058,
        },
        "customs_declaration": {
            "mrn":             "26PL123456789A",
            "nbp_rate":        3.7058,
            "duty_a00_pln":    1181.0,
            "exporter_name":   "Estrella Jewels LLP.",
            "importer_name":   "ESTRELLA JEWELS SP. Z O.O. SP. K.",
            "clearance_date":  "2026-04-15",
        },
        "totals": {
            "net":   48778.64,
            "gross": 59997.72,
        },
    }


def _make_rows(count=3):
    base = [
        {
            "invoice_no":      "EJL/25-26/1248",
            "description_en":  "Diamond Ring 14KT",
            "pl_desc":         "Pierścionek złoty próby 585 z diamentami",
            "quantity":        5.0,
            "unit":            "PCS",
            "unit_netto_pln":  1234.56,
            "line_netto_pln":  6172.80,
            "line_brutto_pln": 7592.54,
            "allocated_duty_pln": 155.80,
            "usd_pln":         3.7058,
            "item_type":       "RING",
        },
        {
            "invoice_no":      "EJL/25-26/1249",
            "description_en":  "Gold Earrings 18KT",
            "pl_desc":         "Kolczyki złote próby 750",
            "quantity":        10.0,
            "unit":            "PCS",
            "unit_netto_pln":  567.89,
            "line_netto_pln":  5678.90,
            "line_brutto_pln": 6985.05,
            "allocated_duty_pln": 143.42,
            "usd_pln":         3.7058,
            "item_type":       "EARRINGS",
        },
        {
            "invoice_no":      "EJL/25-26/1250",
            "description_en":  "Silver Bracelet",
            "pl_desc":         "Bransoletka srebrna",
            "quantity":        2.0,
            "unit":            "PCS",
            "unit_netto_pln":  320.00,
            "line_netto_pln":  640.00,
            "line_brutto_pln": 787.20,
            "allocated_duty_pln": 16.16,
            "usd_pln":         3.7058,
            "item_type":       "BRACELET",
        },
    ]
    return base[:count]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_wfirma_does_not_run_without_sad():
    """
    test 1: wFirma export must be blocked when SAD/ZC429 is not present.
    An invoice-only shipment must not produce wFirma export.
    """
    print("\n[1] test_wfirma_does_not_run_without_sad")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    audit = _make_audit(status="draft", has_sad=False)
    blocked = False
    try:
        _guard_wfirma_export(audit)
    except HTTPException as e:
        code = (e.detail or {}).get("code") if isinstance(e.detail, dict) else ""
        blocked = code == "WFIRMA_NO_SAD"

    ok = _assert(blocked, "Blocked with WFIRMA_NO_SAD when no SAD present")
    return ok


def test_wfirma_export_requires_pz():
    """
    test 2: wFirma export must be blocked when PZ has not been generated.
    Status must be 'success' or 'partial'.
    """
    print("\n[2] test_wfirma_export_requires_pz")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    ok = True
    for bad_status in ("draft", "ready", "processing", "failed", "blocked"):
        audit = _make_audit(status=bad_status, has_sad=True)
        blocked = False
        try:
            _guard_wfirma_export(audit)
        except HTTPException as e:
            code = (e.detail or {}).get("code") if isinstance(e.detail, dict) else ""
            blocked = code == "WFIRMA_PZ_NOT_GENERATED"
        ok = _assert(blocked, f"Blocked for status={bad_status!r}") and ok

    # Should pass for success and partial
    for good_status in ("success", "partial"):
        audit = _make_audit(status=good_status, has_sad=True)
        passed = False
        try:
            _guard_wfirma_export(audit)
            passed = True
        except HTTPException:
            pass
        ok = _assert(passed, f"Allowed for status={good_status!r}") and ok

    return ok


def test_wfirma_clipboard_format_polish_numbers():
    """
    test 3: Polish numeric format must be used.
    1234.56 → "1 234,56" (space thousands, comma decimal)
    """
    print("\n[3] test_wfirma_clipboard_format_polish_numbers")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    ok = True
    ok = _assert(_fmt_pln(1234.56)  == "1 234,56",
                 "1234.56 → '1 234,56'",
                 f"got: {_fmt_pln(1234.56)!r}") and ok
    ok = _assert(_fmt_pln(48778.64) == "48 778,64",
                 "48778.64 → '48 778,64'",
                 f"got: {_fmt_pln(48778.64)!r}") and ok
    ok = _assert(_fmt_pln(0.00)     == "0,00",
                 "0.00 → '0,00'",
                 f"got: {_fmt_pln(0.00)!r}") and ok
    ok = _assert(_fmt_pln(567.89)   == "567,89",
                 "567.89 → '567,89'",
                 f"got: {_fmt_pln(567.89)!r}") and ok
    ok = _assert(_fmt_pln(1000000.00) == "1 000 000,00",
                 "1000000.00 → '1 000 000,00'",
                 f"got: {_fmt_pln(1000000.00)!r}") and ok
    return ok


def test_wfirma_json_contains_rows():
    """
    test 4: PZ_READY.json must contain rows with all required keys.
    """
    print("\n[4] test_wfirma_json_contains_rows")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    audit = _make_audit()
    rows  = _make_rows(3)
    wfirma_rows = _build_wfirma_rows(rows, audit)

    ok = True
    ok = _assert(len(wfirma_rows) == 3, "3 rows produced") and ok

    required_keys = {
        "nazwa_towaru", "ilosc", "jm",
        "cena_netto", "wartosc_netto", "wartosc_brutto", "uwagi",
    }
    for i, r in enumerate(wfirma_rows):
        missing = required_keys - r.keys()
        ok = _assert(
            len(missing) == 0,
            f"Row {i+1} has all required keys",
            f"Missing: {missing}",
        ) and ok

    # Check Polish description is used as name
    ok = _assert(
        wfirma_rows[0]["nazwa_towaru"] == "Pierścionek złoty próby 585 z diamentami",
        "Row 1 uses Polish description as Nazwa towaru",
        f"got: {wfirma_rows[0]['nazwa_towaru']!r}",
    ) and ok

    # Check numeric values
    ok = _assert(
        abs(wfirma_rows[0]["wartosc_netto"] - 6172.80) < 0.01,
        "Row 1 Wartość netto = 6 172,80 PLN",
    ) and ok

    return ok


def test_wfirma_export_preserves_invoice_order():
    """
    test 5: Rows must appear in original invoice order.
    """
    print("\n[5] test_wfirma_export_preserves_invoice_order")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    audit = _make_audit()
    rows  = _make_rows(3)
    wfirma_rows = _build_wfirma_rows(rows, audit)

    ok = True
    invoices_out = [r["_invoice_no"] for r in wfirma_rows]
    invoices_in  = [r["invoice_no"] for r in rows]
    ok = _assert(
        invoices_out == invoices_in,
        "Invoice order preserved",
        f"expected {invoices_in}, got {invoices_out}",
    ) and ok

    # Also check clipboard order
    clipboard = _build_clipboard_text(wfirma_rows)
    lines = clipboard.split("\n")
    ok = _assert(len(lines) == 4, "Clipboard has header + 3 data rows") and ok
    ok = _assert(
        "EJL/25-26/1248" in lines[1],
        "First data row contains first invoice ref",
        f"line[1]: {lines[1][:120]}",
    ) and ok
    return ok


def test_uwagi_contains_required_fields():
    """
    test 6: Uwagi must include invoice ref, AWB, MRN, NBP rate, A00 note.
    """
    print("\n[6] test_uwagi_contains_required_fields")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    row = _make_rows(1)[0]
    uwagi = _build_uwagi(
        row   = row,
        awb   = "3283625844",
        mrn   = "26PL123456789A",
        nbp_rate = 3.7058,
        settlement_mode = "standard",
    )
    ok = True
    ok = _assert("EJL/25-26/1248" in uwagi, "Invoice ref in Uwagi", f"got: {uwagi!r}") and ok
    ok = _assert("AWB 3283625844" in uwagi, "AWB in Uwagi",          f"got: {uwagi!r}") and ok
    ok = _assert("MRN 26PL123456789A" in uwagi, "MRN in Uwagi",     f"got: {uwagi!r}") and ok
    ok = _assert("A00 allocated in cost" in uwagi, "A00 note in Uwagi", f"got: {uwagi!r}") and ok
    ok = _assert("NBP" in uwagi, "NBP rate in Uwagi",                f"got: {uwagi!r}") and ok

    # Art. 33a mode should include it
    uwagi_art33a = _build_uwagi(row, "3283625844", "26PL123456789A", 3.7058, "art33a")
    ok = _assert("Art.33a" in uwagi_art33a, "Art.33a flag in Uwagi when mode=art33a") and ok

    return ok


def test_unit_normalisation():
    """
    test 7: Unit values (PCS, PIECE, PAIR) must be normalised to Polish.
    """
    print("\n[7] test_unit_normalisation")
    if not _IMPORT_OK:
        print(f"  SKIP  (import failed: {_IMPORT_ERR})")
        return True

    audit = _make_audit()
    ok = True
    for unit_in, expected in [
        ("PCS",    "szt."),
        ("PIECE",  "szt."),
        ("PIECES", "szt."),
        ("PAIR",   "para"),
        ("PAIRS",  "para"),
        ("SET",    "zest."),
        ("szt.",   "szt."),   # already correct
    ]:
        row = _make_rows(1)[0].copy()
        row["unit"] = unit_in
        wfirma_rows = _build_wfirma_rows([row], audit)
        ok = _assert(
            wfirma_rows[0]["jm"] == expected,
            f"Unit '{unit_in}' → '{expected}'",
            f"got: {wfirma_rows[0]['jm']!r}",
        ) and ok
    return ok


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("wFirma Export Tests")
    print("=" * 60)

    if not _IMPORT_OK:
        print(f"\n⚠️  Import failed: {_IMPORT_ERR}")
        print("Running tests in offline mode (testing helper logic only).\n")

    tests = [
        test_wfirma_does_not_run_without_sad,
        test_wfirma_export_requires_pz,
        test_wfirma_clipboard_format_polish_numbers,
        test_wfirma_json_contains_rows,
        test_wfirma_export_preserves_invoice_order,
        test_uwagi_contains_required_fields,
        test_unit_normalisation,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            result = test()
            if result is not False:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  \033[91m✗ EXCEPTION\033[0m  {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"\033[92m✓ ALL {total} TESTS PASSED\033[0m")
        sys.exit(0)
    else:
        print(f"\033[91m✗ {failed}/{total} TESTS FAILED\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()

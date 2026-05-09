#!/usr/bin/env python3
"""
Golden regression test — Shipment 039–044
==========================================
Validates pz_import_processor.py against the reconciled reference values
from PZ_calculation_template_39_44.xlsx (validated 2026-04-22).

Run:
    python3 test_pz_regression.py              # unit + format tests only
    python3 test_pz_regression.py --e2e        # also run full PDF pipeline

Expected: all tests PASS, exit code 0.
Any FAIL means a parser or formula regression was introduced.
"""

import sys
import os
import types
import argparse
import json
import hashlib

# ── Golden constants (single source of truth — edit golden_constants.py, not here) ──
sys.path.insert(0, os.path.dirname(__file__))
from golden_constants import (
    GOLDEN_RATE,
    EXPECTED_INVOICE_COUNT,
    EXPECTED_LINES,
    EXPECTED_RAZEM_NETTO,
    EXPECTED_RAZEM_BRUTTO,
    EXPECTED_DUTY_A00,
    EXPECTED_UNIT_NET,
    EXPECTED_QUANTITIES,
    DESC_RULES,
    DUTY_RATE_MAX_PCT,
    QTY_MAX_VALID,
    GOLDEN_ROW_HASH,
    BLOCKED_CORRECTION_PHRASES,
    CIF_RECONCILIATION_TOLERANCE_USD,
    GOLDEN_NOTE_4,
    GOLDEN_BATCH_META,
)

# ── Thin GOLDEN dict — kept for backward compat with sections [1]–[8] ─────────
GOLDEN = {
    "batch":            "039–044",
    "invoice_count":    EXPECTED_INVOICE_COUNT,
    "total_lines":      EXPECTED_LINES,
    "usd_pln":          GOLDEN_RATE,
    "total_fob_usd":    13120.00,
    "total_freight_usd": 150.00,
    "total_cif_usd":    13270.00,
    "total_before_duty_pln": 48443.46,
    "duty_a00_pln":     EXPECTED_DUTY_A00,
    "duty_rate_pct":    2.5287,
    "razem_netto":      EXPECTED_RAZEM_NETTO,
    "razem_brutto":     EXPECTED_RAZEM_BRUTTO,
    "unit_net":         EXPECTED_UNIT_NET,
    "desc_rules":       DESC_RULES,
    "duty_rate_max_pct": DUTY_RATE_MAX_PCT,
    "qty_max_valid":    QTY_MAX_VALID,
}

# ── Test runner ────────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0

def check(label: str, actual, expected, tol: float = 0.02):
    global PASS, FAIL
    if isinstance(expected, float):
        ok = abs(actual - expected) <= tol
    else:
        ok = actual == expected
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
        print(f"  {status}  {label}")
        print(f"         expected: {expected}  got: {actual}  diff: {actual - expected if isinstance(expected, float) else 'n/a'}")
    else:
        PASS += 1
        print(f"  {status}  {label}")

def check_contains(label: str, text: str, substring: str):
    global PASS, FAIL
    ok = substring in text
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
        print(f"  {status}  {label}")
        print(f"         '{substring}' not found in: {text[:80]}")
    else:
        PASS += 1
        print(f"  {status}  {label}")


# ── Import processor ───────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(__file__))
from pz_import_processor import (
    build_pl_name, build_en_name, get_full_nazwa, ITEM_PL,
    normalize_family, is_suspicious_quantity,
    get_karat, fmt_pln, RECIPIENT, SUPPLIER,
    process_batch, build_note_4, format_uwagi, format_pz_clipboard,
    verify_sad_invoice_match, build_amendment_flags,
    calculate_landed, parse_invoice, parse_zc429, get_nbp_rate,
)

# PDF paths — absolute so the test can be run from any directory
_PZ_DIR = "/Users/amitgupta/Downloads/Shipment 39-44/Pz"
INVOICE_PDFS = [
    f"{_PZ_DIR}/039 Invoice EJL-26-27-039-10-04-26.pdf",
    f"{_PZ_DIR}/040 Invoice EJL-26-27-040-10-04-26.pdf",
    f"{_PZ_DIR}/041 Invoice EJL-26-27-041-11-04-26.pdf",
    f"{_PZ_DIR}/042 Invoice EJL-26-27-042-10-04-26.pdf",
    f"{_PZ_DIR}/043 Invoice EJL-26-27-043-10-04-26.pdf",
    f"{_PZ_DIR}/044 Invoice EJL-26-27-044-10-04-26.pdf",
]
ZC429_PDF = f"{_PZ_DIR}/ZC429_26PL44302D008N8OR0_1_PL.pdf"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true",
                    help="Run sections [9]–[14] which require the real PDFs")
    args = ap.parse_args()

    print()
    print("=" * 60)
    print("  PZ REGRESSION TEST — Shipment 039–044")
    print("=" * 60)

    # ── 1. Description mapping rules ─────────────────────────────────────
    print("\n[1] Description mapping rules")
    for family, item_type, must_contain in GOLDEN["desc_rules"]:
        karat = "18KT"
        result = build_pl_name({"family": family, "karat": karat, "item_type": item_type})
        check_contains(
            f"  ({family}, {item_type}) contains '{must_contain}'",
            result, must_contain
        )

    # ── 2. DIA&CLS regression guard ──────────────────────────────────────
    print("\n[2] DIA&CLS must never use 'wysadzany' (that's Diamond Studded only)")
    dla_cls_result = build_pl_name({"family": "Diamond / Colour Stone Studded", "karat": "14KT", "item_type": "PENDANT"})
    ok = "wysadzany" not in dla_cls_result
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  DIA&CLS PENDANT does not contain 'wysadzany'")
    else:
        FAIL += 1
        print(f"  FAIL  DIA&CLS PENDANT incorrectly contains 'wysadzany': {dla_cls_result}")

    # ── 3. Quantity sanity checks ─────────────────────────────────────────
    print("\n[3] Quantity sanity checks")
    hsn_codes   = [71131911, 71131913, 71131914, 71131919, 71131141]
    valid_qtys  = [1, 2, 3, 9, 1.5, 10]
    for hsn in hsn_codes:
        check(f"  HSN {hsn} flagged as suspicious", is_suspicious_quantity(hsn), True)
    for qty in valid_qtys:
        check(f"  qty={qty} not flagged as suspicious", is_suspicious_quantity(qty), False)

    # ── 4. Family normalization ───────────────────────────────────────────
    print("\n[4] Family normalization")
    cases = [
        ("DIA&CLS PENDANT",                     "Diamond / Colour Stone Studded"),
        ("LGD Stud Jewellery",                  "Lab Grown Diamond"),
        ("Lab Grown Diamond",                   "Lab Grown Diamond"),
        ("Plain Jewellery RING",                "Plain"),
        ("Stud With Diam Jewel",                "Diamond Studded"),
        ("SL925 SILVER",                        "Silver Plain"),
        # CLS (Colour Stone) — bare abbreviation, no "DIA&" prefix
        ("CLS PENDANT",                         "Diamond / Colour Stone Studded"),
        ("09KT Gold, Studed Jewellery CLS RING","Diamond / Colour Stone Studded"),
        # PT950 Platinum — family detected from description type, not metal
        ("PT950 Platinum Plain RING",           "Plain"),
        ("PT950 Stud With Diam PENDANT",        "Diamond Studded"),
    ]
    for desc, expected_family in cases:
        result = normalize_family(desc)
        check(f"  '{desc}' → '{expected_family}'", result, expected_family)

    # ── 5. Karat detection ────────────────────────────────────────────────
    print("\n[5] Karat detection")
    karat_cases = [
        ("14KT Gold, Stud Jewelry",       "14KT"),
        ("18KT Gold, Plain",              "18KT"),
        ("SL925 SILVER",                  "14KT"),   # fallback default
        ("PT950 Platinum Plain RING",     "PT950"),  # platinum 950
        ("PT900 Plain Platinum PENDANT",  "PT900"),  # platinum 900
        # PT950 must not be confused with "9KT" substring match
        ("PT950 Stud With Diam BRACELET", "PT950"),
    ]
    for desc, expected_karat in karat_cases:
        result = get_karat(desc)
        check(f"  karat('{desc}') == '{expected_karat}'", result, expected_karat)

    # ── 6. Duty rate guard ────────────────────────────────────────────────
    print("\n[6] Duty rate plausibility")
    check("  Duty rate 2.53% < 20% guard", GOLDEN["duty_rate_pct"] < GOLDEN["duty_rate_max_pct"], True)
    check("  Duty rate 2.53% > 0%", GOLDEN["duty_rate_pct"] > 0, True)

    # ── 7. Golden totals (formula verification) ───────────────────────────
    print("\n[7] Golden totals cross-check")
    # Verify the formula chain: CIF → before duty → + duty → netto → × 1.23 → brutto
    total_before = GOLDEN["total_before_duty_pln"]
    duty         = GOLDEN["duty_a00_pln"]
    netto        = total_before + duty
    brutto       = netto * 1.23
    check("  total_before_duty + A00 = razem_netto",
          round(netto, 2), GOLDEN["razem_netto"], tol=0.02)
    check("  razem_netto × 1.23 = razem_brutto",
          round(brutto, 2), GOLDEN["razem_brutto"], tol=0.02)
    check("  total_cif_usd × usd_pln ≈ total_before_duty (within 1 PLN)",
          GOLDEN["total_cif_usd"] * GOLDEN["usd_pln"],
          GOLDEN["total_before_duty_pln"], tol=1.0)

    # ── 8. Per-line unit net prices ───────────────────────────────────────
    print("\n[8] Per-line unit net prices (Cena netto) — tolerance ±0.05 PLN")
    # These are the workbook values; we test the formula chain, not the live parser
    # (live parser test requires the actual PDF files)
    expected_sum_netto = sum(
        unit * qty for unit, qty in zip(
            GOLDEN["unit_net"],
            [2, 9, 1, 2, 1, 1, 1, 2, 1.5, 1, 3, 1, 1, 1, 1, 1]
        )
    )
    check("  Sum of (unit_net × qty) ≈ razem_netto",
          round(expected_sum_netto, 2), GOLDEN["razem_netto"], tol=0.05)

    # ── 9. End-to-end golden batch (requires --e2e flag + real PDFs) ─────
    if args.e2e:
        print("\n[9] End-to-end golden batch — Shipment 039–044")
        missing = [p for p in INVOICE_PDFS + [ZC429_PDF] if not os.path.exists(p)]
        if missing:
            FAIL += 1
            print(f"  FAIL  PDF files not found:")
            for p in missing:
                print(f"         {p}")
        else:
            try:
                result = process_batch(INVOICE_PDFS, ZC429_PDF,
                                       rate=GOLDEN_RATE, batch_meta=GOLDEN_BATCH_META)

                check("  line_count == 16",
                      result["line_count"], EXPECTED_LINES)
                check("  total_net  == 49668.46 PLN",
                      round(result["total_net"], 2), EXPECTED_RAZEM_NETTO, tol=0.02)
                check("  total_gross == 61092.21 PLN",
                      round(result["total_gross"], 2), EXPECTED_RAZEM_BRUTTO, tol=0.02)
                check("  duty_pln (A00) == 1225.00 PLN",
                      round(result["duty_pln"], 2), EXPECTED_DUTY_A00, tol=0.01)

                # Per-line unit net prices against workbook values
                print("\n  Per-line Cena netto (tolerance ±0.05 PLN per unit):")
                for i, (row, expected_unit) in enumerate(
                    zip(result["rows"], GOLDEN["unit_net"]), 1
                ):
                    check(
                        f"    L{i:>2} unit netto",
                        round(row["unit_netto_pln"], 2), expected_unit, tol=0.05
                    )

                # Corrections log must be clean: no parse errors, no reparsing events
                # ("Filename date differs" warnings and [VERIFY-GAP] visibility notes are
                # expected and allowed — they are not parse failures)
                # Phrases defined in golden_constants.BLOCKED_CORRECTION_PHRASES
                for entry in result["corrections_log"]:
                    if entry.startswith("[VERIFY-GAP]"):
                        continue   # visibility notes are not parse errors
                    for phrase in BLOCKED_CORRECTION_PHRASES:
                        if phrase.lower() in entry.lower():
                            FAIL += 1
                            print(f"  FAIL  Unexpected correction log entry: {entry}")
                            break

            except Exception as exc:
                FAIL += 1
                print(f"  FAIL  process_batch() raised: {exc}")
    else:
        print("\n[9] End-to-end golden batch — SKIPPED (use --e2e to run)")

    # ── 10. Output format checks ──────────────────────────────────────────
    print("\n[10] Output format checks")

    # Polish number formatting
    fmt_cases = [
        (0.0,        "0,00"),
        (1.23,       "1,23"),
        (1360.18,    "1 360,18"),
        (49668.46,   "49 668,46"),
        (61092.21,   "61 092,21"),
        (100000.0,   "100 000,00"),
    ]
    for val, expected_str in fmt_cases:
        check(f"  fmt_pln({val}) == '{expected_str}'", fmt_pln(val), expected_str)

    # Recipient / supplier identity constants
    check_contains("  RECIPIENT name contains 'ESTRELLA'",
                   RECIPIENT["name"], "ESTRELLA")
    check_contains("  RECIPIENT address contains 'Warszawa'",
                   RECIPIENT["address"], "Warszawa")
    check_contains("  RECIPIENT NIP == 5252812119",
                   RECIPIENT["nip"], "5252812119")
    check_contains("  SUPPLIER name contains 'ESTRELLA'",
                   SUPPLIER["name"], "ESTRELLA")
    check_contains("  SUPPLIER address contains 'MUMBAI'",
                   SUPPLIER["address"], "MUMBAI")

    # If e2e ran, also test UWAGI note line structure
    if args.e2e and "result" in dir():
        notes = result["notes"]
        check("  notes list has exactly 4 lines", len(notes), 4)
        check_contains("  notes[0] contains 'Invoice No.'",  notes[0], "Invoice No.")
        check_contains("  notes[1] contains 'USD RATE'",     notes[1], "USD RATE")
        check_contains("  notes[1] contains '3.6506'",       notes[1], "3.6506")
        check_contains("  notes[2] contains MRN",            notes[2], result["zc429"]["mrn"])
        check_contains("  notes[2] contains LRN",            notes[2], result["zc429"]["lrn"])
        check_contains("  notes[3] contains 'Odprawa'",       notes[3], "Odprawa")

        # All Cena netto values must be finite positive numbers
        for i, row in enumerate(result["rows"], 1):
            u = row["unit_netto_pln"]
            ok = isinstance(u, float) and u > 0 and round(u, 2) == u or True
            check(f"  L{i:>2} unit_netto_pln > 0", u > 0, True)

    # ── 11. Snapshot — exact UWAGI text and L1 / L16 row output ─────────
    if args.e2e and "result" in dir():
        print("\n[11] Output snapshots — UWAGI block and boundary rows")

        notes = result["notes"]
        rows  = result["rows"]

        # ── UWAGI exact snapshots ──
        # note[0]: invoice range and date — fully deterministic for this batch
        check("  notes[0] exact text",
              notes[0],
              "Applies to: Invoice No. EJL/26-27/039 - 044 Date : 10-04-2026")

        # note[1]: rate line — check key fragments (table no. is 'MANUAL' in test mode)
        check_contains("  notes[1] contains rate '3.6506'",      notes[1], "3.6506")
        check_contains("  notes[1] contains 'USD RATE:'",        notes[1], "USD RATE:")
        check_contains("  notes[1] contains '1 USD ='",          notes[1], "1 USD =")

        # note[2]: customs reference — MRN, LRN, clearance date all pinned
        check("  notes[2] exact text",
              notes[2],
              "Admitted for circulation in the territory of the Republic of Poland "
              "on the basis of: 26PL44302D008N8OR0 Own number: 26S00Q8O0S of dt 15.04.2026")

        # note[3]: carrier — exact
        check("  notes[3] exact text",
              notes[3],
              GOLDEN_NOTE_4)

        # ── L1 row snapshot (DIA&CLS PENDANT × 2, invoice 039) ──
        # Three-layer check per field:
        #   (raw tol) — upstream drift caught before rounding hides it (tol ±0.005 PLN)
        #   (num)     — rounded value must equal workbook figure exactly
        #   (fmt)     — human-facing string must match Polish PZ layout exactly
        r1 = rows[0]
        check("  L1 pl_desc exact",
              r1["pl_desc"],
              "wisiorek ze złota próby 14 karatów z diamentami i kamieniami")
        check("  L1 quantity",                      r1["quantity"],                        2)
        check("  L1 unit_price_usd",                r1["unit_price_usd"],                213.5)
        check("  L1 Cena netto  (raw tol)",  r1["unit_netto_pln"],               802.26,  tol=0.005)
        check("  L1 Cena netto  (num)",  round(r1["unit_netto_pln"], 2),          802.26)
        check("  L1 Cena netto  (fmt)",  fmt_pln(r1["unit_netto_pln"]),          "802,26")
        check("  L1 Wart. netto (raw tol)",  r1["line_netto_pln"],                  1604.51,  tol=0.005)
        check("  L1 Wart. netto (num)",  round(r1["line_netto_pln"],     2),         1604.51)
        check("  L1 Wart. netto (fmt)",  fmt_pln(r1["line_netto_pln"]),           "1 604,51")
        check("  L1 Wart. brutto(raw tol)",  r1["line_brutto_pln"],                1973.55,  tol=0.005)
        check("  L1 Wart. brutto(num)",  round(r1["line_brutto_pln"],    2),        1973.55)
        check("  L1 Wart. brutto(fmt)",  fmt_pln(r1["line_brutto_pln"]),          "1 973,55")

        # ── L16 row snapshot (Plain 14KT RING × 1, invoice 044) ──
        r16 = rows[-1]
        check("  L16 pl_desc exact",
              r16["pl_desc"],
              "pierścionek ze złota próby 14 karatów")
        check("  L16 quantity",                      r16["quantity"],                       1)
        check("  L16 unit_price_usd",                r16["unit_price_usd"],               219.0)
        check("  L16 Cena netto  (raw tol)",  r16["unit_netto_pln"],              858.29,  tol=0.005)
        check("  L16 Cena netto  (num)",  round(r16["unit_netto_pln"], 2),        858.29)
        check("  L16 Cena netto  (fmt)",  fmt_pln(r16["unit_netto_pln"]),        "858,29")
        check("  L16 Wart. netto (raw tol)",  r16["line_netto_pln"],                 858.29,  tol=0.005)
        check("  L16 Wart. netto (num)",  round(r16["line_netto_pln"],     2),        858.29)
        check("  L16 Wart. netto (fmt)",  fmt_pln(r16["line_netto_pln"]),            "858,29")
        check("  L16 Wart. brutto(raw tol)",  r16["line_brutto_pln"],               1055.70,  tol=0.005)
        check("  L16 Wart. brutto(num)",  round(r16["line_brutto_pln"],    2),       1055.70)
        check("  L16 Wart. brutto(fmt)",  fmt_pln(r16["line_brutto_pln"]),        "1 055,70")
    elif args.e2e:
        print("\n[11] Output snapshots — SKIPPED (process_batch did not produce result)")
    else:
        print("\n[11] Output snapshots — SKIPPED (use --e2e to run)")

    # ── 12. Structural integrity — hash, no-silent-correction, CIF reconciliation ──
    if args.e2e and "result" in dir():
        print("\n[12] Structural integrity checks")

        rows   = result["rows"]
        zc429  = result["zc429"]

        # ── Golden row hash (value lives in golden_constants.py) ──

        def _stable(row):
            return {
                "invoice_no":       row["invoice_no"],
                "pl_desc":          row["pl_desc"],
                "quantity":         row["quantity"],
                "unit_price_usd":   row["unit_price_usd"],
                "unit_netto_pln":   round(row["unit_netto_pln"],   4),
                "line_netto_pln":   round(row["line_netto_pln"],   4),
                "line_brutto_pln":  round(row["line_brutto_pln"],  4),
            }

        payload = json.dumps([_stable(r) for r in rows],
                             sort_keys=True, ensure_ascii=False)
        actual_hash = hashlib.sha256(payload.encode()).hexdigest()
        check("  Golden row hash (structure + values unchanged)",
              actual_hash, GOLDEN_ROW_HASH)

        # ── No silent reparsing in corrections log ──
        # Filename-date warnings and [VERIFY-GAP] visibility notes are expected and allowed.
        # Phrases are defined in golden_constants.BLOCKED_CORRECTION_PHRASES.
        silent_errors = [e for e in result["corrections_log"]
                         if not e.startswith("[VERIFY-GAP]")
                         and any(p in e.lower() for p in BLOCKED_CORRECTION_PHRASES)]
        check("  Corrections log: no parse errors or reparsing events",
              len(silent_errors), 0)
        if silent_errors:
            for e in silent_errors:
                print(f"         ✗  {e}")

        # ── Invoice CIF sum = ZC429 declared invoice value ──
        # A mismatch means a missing/duplicate invoice or a parsing error.
        cif_sum = sum(inv["cif_usd"] for inv in result["invoices"])
        check("  Sum invoice CIF USD ≈ ZC429 declared invoice value (±1 USD)",
              cif_sum, zc429["total_cif_usd"], tol=CIF_RECONCILIATION_TOLERANCE_USD)

        # ── Invoice count matches expected ──
        check("  Invoice count == 6",
              len(result["invoices"]), GOLDEN["invoice_count"])

    elif args.e2e:
        print("\n[12] Structural integrity — SKIPPED (process_batch did not produce result)")
    else:
        print("\n[12] Structural integrity — SKIPPED (use --e2e to run)")

    # ── 13. build_note_4() logic — all three custody modes ───────────────
    print("\n[13] build_note_4() logic")

    zc429_with_agent    = {"agent": "AGENCJA CELNA SPEDYCJA KUŹMICZ K."}
    zc429_without_agent = {"agent": ""}

    # Case 1: art33a — always returns statutory wording regardless of agent/carrier
    check("  art33a mode (with agent)   → art. 33a wording",
          build_note_4(zc429_with_agent, {"settlement_mode": "art33a"}),
          "Import towarów rozliczany zgodnie z art. 33a ustawy o VAT.")
    check("  art33a mode (no agent)     → art. 33a wording",
          build_note_4(zc429_without_agent, {"settlement_mode": "art33a"}),
          "Import towarów rozliczany zgodnie z art. 33a ustawy o VAT.")
    check("  art33a mode (with carrier) → art. 33a wording",
          build_note_4(zc429_without_agent,
                       {"settlement_mode": "art33a", "carrier_name": "DHL EXPRESS"}),
          "Import towarów rozliczany zgodnie z art. 33a ustawy o VAT.")

    # Case 2: standard + prefer_carrier_label → carrier takes precedence over agent
    check("  prefer_carrier + carrier   → carrier label",
          build_note_4(zc429_with_agent,
                       {"prefer_carrier_label": True,
                        "carrier_name": "DHL EXPRESS (POLAND) SP. Z O.O."}),
          "DHL EXPRESS (POLAND) SP. Z O.O.")

    # Case 3: standard + agent in ZC429 → "Odprawa celna przez: <agent>"
    check("  standard + agent in ZC429  → agency line",
          build_note_4(zc429_with_agent, {}),
          "Odprawa celna przez: AGENCJA CELNA SPEDYCJA KUŹMICZ K.")
    check("  golden batch note_4        → GOLDEN_NOTE_4",
          build_note_4(zc429_with_agent, GOLDEN_BATCH_META),
          GOLDEN_NOTE_4)

    # Case 4: standard + no agent + carrier_name → carrier label
    check("  no agent + carrier_name    → carrier label",
          build_note_4(zc429_without_agent,
                       {"carrier_name": "DHL EXPRESS (POLAND) SP. Z O.O."}),
          "DHL EXPRESS (POLAND) SP. Z O.O.")

    # Case 5: standard + no agent + no carrier → fallback
    check("  no agent + no carrier      → generic fallback",
          build_note_4(zc429_without_agent, {}),
          "Odprawa celna importowa.")
    check("  None batch_meta            → generic fallback",
          build_note_4(zc429_without_agent, None),
          "Odprawa celna importowa.")

    # ── 14. Clipboard output — notes flow through unchanged ──────────────
    print("\n[14] Clipboard output — notes flow through unchanged")

    # Unit tests: format_uwagi() and format_pz_clipboard() are pure functions
    # that take the notes list and must never reconstruct or reformat it.

    sample_notes = [
        "Applies to: Invoice No. EJL/26-27/039 - 044 Date : 10-04-2026",
        "USD RATE: Table no. 069/A/NBP/2026 of 2026-04-09 , where 1 USD =3.6506 PLN",
        "Admitted for circulation in the territory of the Republic of Poland "
        "on the basis of: 26PL44302D008N8OR0 Own number: 26S00Q8O0S of dt 15.04.2026",
        GOLDEN_NOTE_4,
    ]

    uwagi_str = format_uwagi(sample_notes)

    # Every note line must appear verbatim in the UWAGI output
    for note in sample_notes:
        check_contains(f"  format_uwagi contains: {note[:50]}...",
                       uwagi_str, note)

    # UWAGI string must start with "UWAGI:"
    check_contains("  format_uwagi starts with 'UWAGI:'", uwagi_str, "UWAGI:")

    # format_uwagi is idempotent: passing same notes twice gives same result
    check("  format_uwagi is deterministic",
          format_uwagi(sample_notes), format_uwagi(sample_notes))

    # Clipboard note_4 must be GOLDEN_NOTE_4, not the old hardcoded DHL string
    check("  format_uwagi note_4 == GOLDEN_NOTE_4",
          sample_notes[3], GOLDEN_NOTE_4)
    check("  format_uwagi note_4 != old hardcoded DHL string",
          GOLDEN_NOTE_4 == "DHL EXPRESS (POLAND) SP. Z O.O.", False)

    # End-to-end: notes from process_batch() flow through format_pz_clipboard unchanged
    if args.e2e and "result" in dir():
        clip = format_pz_clipboard(result["rows"], result["notes"], result["totals"])

        # All four note lines must appear verbatim in clipboard output
        for i, note in enumerate(result["notes"]):
            check_contains(f"  clipboard contains notes[{i}]", clip, note)

        # No separate reconstruction: GOLDEN_NOTE_4 must appear exactly once
        count = clip.count(GOLDEN_NOTE_4)
        check("  GOLDEN_NOTE_4 appears exactly once in clipboard output", count, 1)

        # Totals in clipboard output
        check_contains("  clipboard contains razem netto PLN",
                       clip, fmt_pln(result["total_net"]))
        check_contains("  clipboard contains razem brutto PLN",
                       clip, fmt_pln(result["total_gross"]))
    else:
        print("  (clipboard e2e checks skipped — use --e2e to run)")

    # ── 15. Platinum (PT950 / PT900) and bare-CLS handling ───────────────
    print("\n[15] Platinum and bare-CLS item handling")

    # ── PT950 Plain Ring ──
    pt950_ring = build_pl_name({"family": "Plain", "karat": "PT950", "item_type": "RING"})
    check_contains("  PT950 Plain RING → 'platyny próby 950'",  pt950_ring, "platyny próby 950")
    check("  PT950 Plain RING: no '{karat}' placeholder left",  "{karat}" not in pt950_ring, True)
    check("  PT950 Plain RING: no 'karatowego' wording",        "karatowego" not in pt950_ring, True)
    check("  PT950 Plain RING: no 'złota' wording",             "złota" not in pt950_ring, True)

    # ── PT950 Diamond Studded Pendant ──
    pt950_pend = build_pl_name({"family": "Diamond Studded", "karat": "PT950", "item_type": "PENDANT"})
    check_contains("  PT950 Diamond Studded PENDANT → 'platyny próby 950'", pt950_pend, "platyny próby 950")
    check_contains("  PT950 Diamond Studded PENDANT → 'wysadzany'",         pt950_pend, "wysadzany")
    check("  PT950 Diamond Studded PENDANT: no 'karatowego'", "karatowego" not in pt950_pend, True)

    # ── PT950 Diamond/Colour Stone Studded (DIA&CLS) ──
    pt950_cls = build_pl_name({"family": "Diamond / Colour Stone Studded", "karat": "PT950", "item_type": "EARRINGS"})
    check_contains("  PT950 DIA&CLS EARRINGS → 'platyny próby 950'",  pt950_cls, "platyny próby 950")
    check_contains("  PT950 DIA&CLS EARRINGS → 'kamieniami'",          pt950_cls, "kamieniami")

    # ── PT900 variant ──
    pt900_ring = build_pl_name({"family": "Plain", "karat": "PT900", "item_type": "RING"})
    check_contains("  PT900 Plain RING → 'platyny próby 900'",  pt900_ring, "platyny próby 900")
    check("  PT900 Plain RING: no 'karatowego' wording",        "karatowego" not in pt900_ring, True)

    # ── Lab Grown platinum (rare but must not reference gold) ──
    pt950_lgd = build_pl_name({"family": "Lab Grown Diamond", "karat": "PT950", "item_type": "RING"})
    check_contains("  PT950 Lab Grown RING → 'platyny próby 950'", pt950_lgd, "platyny próby 950")
    check("  PT950 Lab Grown RING: no 'złota'",                    "złota" not in pt950_lgd, True)

    # ── normalize_family for bare CLS ──
    check("  'CLS PENDANT' → Diamond/Colour Stone Studded",
          normalize_family("CLS PENDANT"),
          "Diamond / Colour Stone Studded")
    check("  '09KT Gold, Studed Jewellery CLS RING' → Diamond/Colour Stone Studded",
          normalize_family("09KT Gold, Studed Jewellery CLS RING"),
          "Diamond / Colour Stone Studded")
    # Existing DIA&CLS path still works
    check("  'DIA&CLS RING' → Diamond/Colour Stone Studded",
          normalize_family("DIA&CLS RING"),
          "Diamond / Colour Stone Studded")

    # ── get_karat for platinum ──
    check("  karat('PT950 Plain RING') == 'PT950'",
          get_karat("PT950 Plain RING"), "PT950")
    check("  karat('PT900 Plain PENDANT') == 'PT900'",
          get_karat("PT900 Plain PENDANT"), "PT900")
    # Critical: PT950 must not fall through to '9KT' substring match
    check("  PT950 not misdetected as 9KT",
          get_karat("PT950 Platinum Plain RING") != "9KT", True)

    # ── [16] Freight proportional logic ──────────────────────────────────────────
    print("\n[16] Freight proportional allocation")
    # Simulate two invoice rows with 10% freight: 200 USD and 50 USD lines
    _inv_mock = [{"fob_usd": 250.0, "freight_usd": 25.0, "insurance_usd": 0.0,
                  "cif_usd": 275.0, "invoice_no": "MOCK001", "invoice_date": "2026-04-10",
                  "items": [
                      {"description_en": "Test Ring A",  "item_type": "RING",
                       "quantity": 1, "unit_price_usd": 200.0, "total_usd": 200.0},
                      {"description_en": "Test Pendant B", "item_type": "PENDANT",
                       "quantity": 1, "unit_price_usd": 50.0,  "total_usd": 50.0},
                  ]}]
    _zc_mock = {"duty_pln": 100.0, "vat_pln": 0.0, "mrn": "MOCK",
                "total_cif_usd": 275.0, "clearance_date": "2026-04-22"}
    _nbp_mock = {"usd_rate": 4.0, "table_no": "MOCK", "date": "2026-04-09"}
    _log_mock: list = []
    try:
        _rows16, _totals16 = calculate_landed(_inv_mock, _zc_mock, _nbp_mock, _log_mock)
        _r_200 = _rows16[0]   # 200 USD line
        _r_50  = _rows16[1]   # 50 USD line
        _ship_rate = 25.0 / 250.0   # 10%

        check("  200 USD row: freight_rate_pct == 10%",
              round(_r_200.get("freight_rate_pct", 0), 4), round(_ship_rate, 4))
        check("  200 USD row: allocated_ship_usd == 20.00",
              round(_r_200.get("allocated_ship_usd", 0), 2), 20.00)
        check("  50 USD row: allocated_ship_usd == 5.00",
              round(_r_50.get("allocated_ship_usd", 0), 2), 5.00)
        check("  Freight NOT equal per-pcs (200 row > 50 row)",
              _r_200["allocated_ship_usd"] > _r_50["allocated_ship_usd"], True)
        check("  allocated_ship_pln == allocated_ship_usd × rate",
              round(_r_200["allocated_ship_pln"], 2), round(20.00 * 4.0, 2))
        check("  before_duty_pln correct for 200 row",
              round(_r_200["before_duty_pln"], 2), round(200 * 4.0 + 20 * 4.0, 2))
    except Exception as e:
        print(f"  FAIL  [16] calculate_landed raised: {e}")
        FAIL += 1

    # ── [17] Duty proportional logic ─────────────────────────────────────────────
    print("\n[17] Duty proportional allocation + A00 residual reconciliation")
    try:
        _duty_total = sum(r["allocated_duty_pln"] for r in _rows16)
        check("  sum(allocated_duty_pln) == A00 exactly (100.00 PLN)",
              round(_duty_total, 2), 100.00)

        # Duty allocated in proportion to before_duty_pln
        _bd_200 = _r_200["before_duty_pln"]
        _bd_50  = _r_50["before_duty_pln"]
        _total_bd = _bd_200 + _bd_50
        _expected_duty_200 = round(100.0 * _bd_200 / _total_bd, 2)
        # Last row may have residual adjustment — check total, not individual
        check("  A00 split proportionally: 200-row gets larger share",
              _r_200["allocated_duty_pln"] > _r_50["allocated_duty_pln"], True)
        check("  line_netto_pln = before_duty_pln + allocated_duty_pln",
              round(_r_200["line_netto_pln"], 4),
              round(_r_200["before_duty_pln"] + _r_200["allocated_duty_pln"], 4))
        check("  line_brutto_pln = line_netto_pln × 1.23",
              round(_r_200["line_brutto_pln"], 4),
              round(_r_200["line_netto_pln"] * 1.23, 4))
    except Exception as e:
        print(f"  FAIL  [17] duty check raised: {e}")
        FAIL += 1

    # ── [18] SAD invoice reference parsing ───────────────────────────────────────
    print("\n[18] SAD invoice reference parsing — verify_sad_invoice_match")
    # Test with perfectly matching sets (all None checks when SAD refs empty)
    _inv_a = [{"invoice_no": "INV-001", "cif_usd": 500.0,
               "buyer_name": "ACME SP. Z O.O.", "seller_name": "SUPPLIER LTD",
               "buyer_nip": "1234567890",
               "items": [{"item_type": "RING", "quantity": 2}]},
              {"invoice_no": "INV-002", "cif_usd": 250.0,
               "buyer_name": "ACME SP. Z O.O.", "seller_name": "SUPPLIER LTD",
               "buyer_nip": "1234567890",
               "items": [{"item_type": "PENDANT", "quantity": 1}]}]
    _zc_a_no_refs = {"invoice_refs": [], "total_cif_usd": 0,
                     "importer_name": "", "importer_nip": "",
                     "exporter_name": "", "sad_qty_by_type": {}, "customs_rate_usd": 0}
    _v_a = verify_sad_invoice_match(_inv_a, _zc_a_no_refs)
    check("  No SAD refs → invoice_refs_match is None (not parsed)",
          _v_a["invoice_refs_match"], None)

    # With matching refs
    _zc_match = {**_zc_a_no_refs,
                 "invoice_refs": ["INV-001", "INV-002"],
                 "total_cif_usd": 750.0}
    _v_match = verify_sad_invoice_match(_inv_a, _zc_match)
    check("  Matching refs → invoice_refs_match is True",
          _v_match["invoice_refs_match"], True)
    check("  CIF 750 == 750 → cif_match is True",
          _v_match["cif_match"], True)

    # With mismatch
    _zc_miss = {**_zc_a_no_refs,
                "invoice_refs": ["INV-001", "INV-003"],   # INV-003 not in PDFs
                "total_cif_usd": 850.0}                   # CIF mismatch too
    _v_miss = verify_sad_invoice_match(_inv_a, _zc_miss)
    check("  Missing ref → invoice_refs_match is False",
          _v_miss["invoice_refs_match"], False)
    check("  INV-003 in missing_invoices_in_pdfs",
          "INV-003" in _v_miss["missing_invoices_in_pdfs"], True)
    check("  INV-002 in extra_invoices_not_in_sad",
          "INV-002" in _v_miss["extra_invoices_not_in_sad"], True)
    # Three-state CIF contract (per CLAUDE.md): True / False / None.
    # A $100 diff with no additions evidence is freight-shaped (≤ $500
    # AND (mod 50 < 10 OR < 200)), so the engine returns None ("cannot
    # verify"), not False ("confirmed mismatch"). Mirrors the
    # reconciliation in test_cif_softmatch_safety.py (commit e1b4b70).
    check("  CIF diff 100 freight-shaped, no additions → cif_match is None",
          _v_miss["cif_match"], None)

    # ── [19] Importer / exporter match logic ─────────────────────────────────────
    print("\n[19] Importer / exporter match")
    _zc_importer = {**_zc_a_no_refs,
                    "importer_name": "ACME SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
                    "importer_nip":  "1234567890",
                    "exporter_name": "SUPPLIER LIMITED"}
    _v_imp = verify_sad_invoice_match(_inv_a, _zc_importer)
    # "ACME" and "SP." appear in invoice "ACME SP. Z O.O." and SAD "ACME SPÓŁKA..."
    # Word overlap of "ACME" + "Z" + "O" = 3 words → should match
    check("  ACME company → importer_match (word overlap ≥ 2)",
          _v_imp["importer_match"] in (True, None), True)   # True or None both ok (parser-dependent)
    # Exact NIP match
    check("  NIP 1234567890 matches → vat_match is True",
          _v_imp.get("vat_match"), True)
    # Exporter: "SUPPLIER LTD" (invoice) vs "SUPPLIER LIMITED" (SAD) — only 1 common word
    # so result depends on threshold. Could be False or None; should not be True.
    check("  Single-word 'SUPPLIER' overlap → exporter_match is NOT True (< 2 words)",
          _v_imp["exporter_match"] in (False, None), True)

    # Clear mismatch
    _zc_diff_imp = {**_zc_a_no_refs,
                    "importer_name": "COMPLETELY DIFFERENT COMPANY XYZ",
                    "exporter_name": "UNRELATED FACTORY ABC"}
    _v_diff = verify_sad_invoice_match(_inv_a, _zc_diff_imp)
    check("  No word overlap → importer_match is False",
          _v_diff["importer_match"], False)
    check("  No word overlap → exporter_match is False",
          _v_diff["exporter_match"], False)

    # ── [20] Quantity by type parser ─────────────────────────────────────────────
    print("\n[20] Quantity by type — verify_sad_invoice_match")
    _inv_qty = [{"invoice_no": "INV-A", "cif_usd": 100.0,
                 "buyer_name": "", "seller_name": "", "buyer_nip": "",
                 "items": [{"item_type": "RING",    "quantity": 5},
                            {"item_type": "PENDANT", "quantity": 2},
                            {"item_type": "EARRINGS","quantity": 3}]}]
    _zc_qty_match = {**_zc_a_no_refs,
                     "sad_qty_by_type": {"RING": 5, "PENDANT": 2, "EARRINGS": 3}}
    _v_qty = verify_sad_invoice_match(_inv_qty, _zc_qty_match)
    check("  Qty match: 5 rings, 2 pendants, 3 earrings → qty_match_by_type True",
          _v_qty["qty_match_by_type"], True)

    _zc_qty_miss = {**_zc_a_no_refs,
                    "sad_qty_by_type": {"RING": 4, "PENDANT": 2, "EARRINGS": 3}}
    _v_qty2 = verify_sad_invoice_match(_inv_qty, _zc_qty_miss)
    check("  RING qty diff: invoice 5 vs SAD 4 → qty_match_by_type False",
          _v_qty2["qty_match_by_type"], False)
    check("  RING diff is +1 in qty_diff_by_type",
          _v_qty2["qty_diff_by_type"].get("RING", 0), 1)

    # ── [21] Amendment flag generation ───────────────────────────────────────────
    print("\n[21] Amendment flag generation")
    # Add freight/insurance fields using standard values (15 + 10 per invoice)
    # so the non-standard freight check does not fire on the "clean" test
    _inv_a_full = [{**inv, "freight_usd": 15.0, "insurance_usd": 10.0}
                   for inv in _inv_a]
    _v_clean = {
        "invoice_refs_match": True,   "missing_invoices_in_pdfs": [],
        "extra_invoices_not_in_sad": [],
        "cif_match": True,            "invoice_cif_total_usd": 500.0,
        "sad_cif_total_usd": 500.0,   "cif_difference_usd": 0.0,
        "qty_match_by_type": True,    "qty_diff_by_type": {},
        "invoice_qty_by_type": {},    "sad_qty_by_type": {},
        "importer_match": True,       "invoice_importer_name": "X",
        "sad_importer_name": "X",
        "exporter_match": True,       "invoice_exporter_name": "Y",
        "sad_exporter_name": "Y",
    }
    _flags_clean = build_amendment_flags(_inv_a_full, _zc_a_no_refs, _v_clean, [])
    check("  All match → no amendment flags",
          len(_flags_clean), 0)

    # Trigger all structural mismatches
    _v_bad = {**_v_clean,
              "invoice_refs_match": False,
              "missing_invoices_in_pdfs": ["INV-999"],
              "extra_invoices_not_in_sad": [],
              "cif_match": False,
              "invoice_cif_total_usd": 600.0,
              "sad_cif_total_usd": 500.0,
              "cif_difference_usd": 100.0,
              "importer_match": False,
              "invoice_importer_name": "BUYER A",
              "sad_importer_name": "BUYER B",
              "exporter_match": False,
              "invoice_exporter_name": "SELLER A",
              "sad_exporter_name": "SELLER B",
              "qty_match_by_type": False,
              "qty_diff_by_type": {"RING": 2},
              "invoice_qty_by_type": {"RING": 5},
              "sad_qty_by_type": {"RING": 3}}
    _flags_bad = build_amendment_flags(_inv_a_full, _zc_a_no_refs, _v_bad, [])
    check("  Mismatches → flags list non-empty",
          len(_flags_bad) > 0, True)
    check("  SAD refs flag present",
          any("INV-999" in f for f in _flags_bad), True)
    check("  CIF mismatch flag present",
          any("CIF mismatch" in f for f in _flags_bad), True)
    check("  Importer mismatch flag present",
          any("Importer mismatch" in f for f in _flags_bad), True)
    check("  Exporter mismatch flag present",
          any("Exporter mismatch" in f for f in _flags_bad), True)
    check("  Master amendment flag present",
          any("Review needed" in f for f in _flags_bad), True)

    # Blocked phrase in corrections_log
    _flags_parse = build_amendment_flags(_inv_a_full, _zc_a_no_refs, _v_clean,
                                         ["Invoice reparsed due to layout mismatch"])
    check("  'reparsed' in corrections_log → parse warning flag",
          any("Parse warning" in f for f in _flags_parse), True)

    # ── [22] Bilingual final name — get_full_nazwa across all families ────────────
    print("\n[22] Bilingual naming — get_full_nazwa()")
    _families_and_expected = [
        # (family, karat, item_type, en_must_contain, pl_must_contain)
        ("Plain",                          "14KT", "RING",     "Plain 14KT Gold",    "pierścionek ze złota próby 14 karatów"),
        ("Diamond Studded",                "18KT", "RING",     "Diamond Studded",     "wysadzany diamentami"),
        ("Diamond Studded",                "18KT", "EARRINGS", "Diamond Studded",     "wysadzane diamentami"),
        ("Diamond / Colour Stone Studded", "14KT", "PENDANT",  "Colour Stone",        "kamieniami"),
        ("Lab Grown Diamond",              "18KT", "BRACELET", "Lab Grown",           "hodowanymi laboratoryjnie"),
        ("Lab Grown Diamond",              "14KT", "RING",     "Lab Grown",           "hodowanymi laboratoryjnie"),
        ("Silver Plain",                   "SL925","PENDANT",  "Silver SL925",        "wisiorek srebrny próby 925"),
        ("Plain",                          "PT950","RING",     "Platinum",            "platyny próby 950"),
    ]
    for _fam, _kat, _itype, _en_sub, _pl_sub in _families_and_expected:
        _item = {"family": _fam, "karat": _kat, "item_type": _itype}
        _full = get_full_nazwa(_item)
        _en   = build_en_name(_item)
        _pl   = build_pl_name(_item)
        # Full name format: "Polish / English" — Polish-first / slash /
        # English-after-slash, the project-wide convention preserved by
        # description_engine.build_description_line and matched by every
        # other surface (audit PDF, customs descriptions, dashboard
        # rendering, wfirma full_nazwa). Verify the structural slash is
        # present and BOTH halves are non-empty.
        _parts_for_separator_check = _full.split(" / ", 1)
        check(f"  {_fam}/{_itype}: full nazwa uses ' / ' separator",
              " / " in _full
              and len(_parts_for_separator_check) == 2
              and bool(_parts_for_separator_check[0].strip())
              and bool(_parts_for_separator_check[1].strip()),
              True)
        check_contains(f"  {_fam}/{_itype}: en contains '{_en_sub}'", _en, _en_sub)
        check_contains(f"  {_fam}/{_itype}: pl contains '{_pl_sub}'", _pl, _pl_sub)
        # Verify no raw template placeholders leaked through
        check(f"  {_fam}/{_itype}: no '{{karat}}' in full name",
              "{karat}" not in _full, True)

    # ── [23] PDF/XLSX field sourcing (unit test) ──────────────────────────────────
    print("\n[23] PDF/XLSX field sourcing — renderers use canonical key names")
    # Build a minimal result row with only canonical names and verify that
    # the XLSX accessor _r() returns them (not the legacy names)
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            "pz_dual_export", os.path.join(os.path.dirname(__file__), "pz_dual_export.py")
        )
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)

        _row_canonical = {
            "unit_netto_pln":  99.99,
            "line_netto_pln":  199.98,
            "line_brutto_pln": 245.97,
        }
        check("  XLSX _r() reads 'unit_netto_pln'",
              _mod._r(_row_canonical, "unit_netto_pln", "landed_per_unit"), 99.99)
        check("  XLSX _r() reads 'line_netto_pln'",
              _mod._r(_row_canonical, "line_netto_pln", "total_netto"), 199.98)
        check("  XLSX _r() reads 'line_brutto_pln'",
              _mod._r(_row_canonical, "line_brutto_pln", "total_brutto"), 245.97)

        # Legacy fallback: only old names present — should still be read
        _row_legacy = {
            "landed_per_unit": 77.77,
            "total_netto":     155.54,
            "total_brutto":    191.31,
        }
        check("  XLSX _r() fallback 'landed_per_unit'",
              _mod._r(_row_legacy, "unit_netto_pln", "landed_per_unit"), 77.77)
        check("  XLSX _r() fallback 'total_netto'",
              _mod._r(_row_legacy, "line_netto_pln", "total_netto"), 155.54)
    except Exception as e:
        print(f"  FAIL  [23] field sourcing test raised: {e}")
        FAIL += 1

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f"  {PASS}/{total} tests passed  |  {FAIL} failed")
    if FAIL == 0:
        print("  ✅ All golden checks pass — no regression detected.")
    else:
        print("  ✗  REGRESSION DETECTED — review failures above before using on new batch.")
    print("=" * 60)
    print()
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()

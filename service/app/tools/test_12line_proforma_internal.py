"""
test_12line_proforma_internal.py — Guarded 12-line TEST proforma create.

Scope: ESTRELLA INTERNAL TEST contractor only. No delete. No invoice
conversion. No third-party proforma touched. One-shot diagnostic to verify the
corrected invoices/add payload persists all 12 invoicecontent rows and
preserves VAT code parity (vat_code_id=222, domestic PL).

Source: an internal 12-line test distribution (EJL/25-26/1274), mapped to the 7
wfirma_product ids from wfirma_products table. All values taken from live
packing_lines rows (unit_price, product_name). Currency: USD.

Contractor: ESTRELLA INTERNAL TEST (wfirma_contractor_id supplied out-of-band
by the operator — never commit a real wFirma id to this public repo)
VAT context: domestic (PL) → vat_code_id=222

Hard guard: only runs with --live-confirm-I-understand flag.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[2]
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))


_bootstrap()

from app.services import wfirma_client as wc  # noqa: E402

# ── Exact 12-line payload (from live packing_lines, sr1..sr12 order) ─────────
# product_code, wfirma_good_id, product_name_pl, unit_price_usd

_LINES = [
    ("EJL/25-26/1274-3", "48611875", "Pierścionek",  173.0),   # sr1
    ("EJL/25-26/1274-4", "48612067", "Bransoletka",  194.0),   # sr2
    ("EJL/25-26/1274-4", "48612067", "Bransoletka",  159.0),   # sr3
    ("EJL/25-26/1274-1", "48611939", "Wisiorek",     216.0),   # sr4
    ("EJL/25-26/1274-5", "48612131", "Wisiorek",     199.0),   # sr5
    ("EJL/25-26/1274-5", "48612131", "Wisiorek",     146.0),   # sr6
    ("EJL/25-26/1274-2", "48612003", "Pierścionek",  378.0),   # sr7
    ("EJL/25-26/1274-6", "48612195", "Kolczyki",     281.0),   # sr8
    ("EJL/25-26/1274-7", "48612259", "Kolczyki",     361.0),   # sr9
    ("EJL/25-26/1274-7", "48612259", "Kolczyki",     224.0),   # sr10
    ("EJL/25-26/1274-7", "48612259", "Kolczyki",     372.0),   # sr11
    ("EJL/25-26/1274-7", "48612259", "Kolczyki",     140.0),   # sr12
]

_CONTRACTOR_ID  = ""            # ESTRELLA INTERNAL TEST — set the real wFirma id out-of-band (operator-local; never commit a real id)
_VAT_CODE_ID    = "222"         # domestic PL 23%
_CURRENCY       = "USD"


def _build_request() -> wc.ProformaRequest:
    lines = [
        wc.ReservationLine(
            product_code   = code,
            wfirma_good_id = good_id,
            product_name   = name,
            qty            = 1.0,
            unit_price     = price,
            unit           = "szt.",
            currency       = _CURRENCY,
        )
        for code, good_id, name, price in _LINES
    ]
    return wc.ProformaRequest(
        client_name          = "ESTRELLA INTERNAL TEST [TEST DO NOT USE]",
        client_zip           = "",
        client_city          = "",
        lines                = lines,
        currency             = _CURRENCY,
        wfirma_contractor_id = _CONTRACTOR_ID,
        vat_code_id          = _VAT_CODE_ID,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live-confirm-I-understand", action="store_true",
                   help="Required to actually POST to wFirma. Without this flag, "
                        "only a dry-run preview is shown.")
    args = p.parse_args()

    req = _build_request()
    expected_count   = len(req.lines)
    expected_good_ids = [ln.wfirma_good_id for ln in req.lines]

    print("=" * 60)
    print("12-LINE TEST PROFORMA — ESTRELLA INTERNAL TEST")
    print("=" * 60)
    print(f"Contractor:          {req.client_name}")
    print(f"wfirma_contractor_id:{_CONTRACTOR_ID}")
    print(f"currency:            {_CURRENCY}")
    print(f"vat_code_id:         {_VAT_CODE_ID}  (domestic PL 23%)")
    print(f"Expected line count: {expected_count}")
    print("Lines:")
    for i, ln in enumerate(req.lines, 1):
        print(f"  {i:2d}. {ln.product_code:<25} good={ln.wfirma_good_id}  "
              f"{ln.product_name:<16} {ln.unit_price:.2f} {ln.currency}")

    if not args.live_confirm_I_understand:
        print()
        print("DRY-RUN — no HTTP call. Re-run with --live-confirm-I-understand to POST.")
        return

    print()
    print("LIVE CREATE — posting to wFirma invoices/add ...")
    print()

    try:
        result = wc.create_proforma_draft(req)
    except RuntimeError as exc:
        msg = str(exc)
        print("CREATE STATUS:  FAILED")
        print(f"ERROR:          {msg}")

        # Attempt to extract wfirma_id from partial-persistence error for
        # operator awareness.
        if "wfirma_invoice_id=" in msg:
            wid = msg.split("wfirma_invoice_id=")[1].split(" ")[0]
            print(f"NOTE: proforma may exist in wFirma as id={wid} — "
                  "manual review required before any reissue attempt.")

        print()
        print("Flag: WFIRMA_CREATE_PROFORMA_ALLOWED — restore to false manually.")
        sys.exit(1)

    print(f"Create status:       ok=True")
    print(f"wfirma_proforma_id:  {result.wfirma_invoice_id}")

    # ── Parse verify response to extract persisted counts and VAT codes ───────
    # The gate already validated; we re-fetch to display the persisted state.
    try:
        verify_xml  = wc.fetch_invoice_xml(result.wfirma_invoice_id)
        verify_root = ET.fromstring(verify_xml)
        persisted   = verify_root.findall(".//invoicecontent")
        actual_count = len(persisted)

        persisted_good_ids  = []
        persisted_vat_ids   = []
        for ln in persisted:
            g = ln.find("good")
            gid = (g.findtext("id") or "").strip() if g is not None else ""
            vc  = ln.find("vat_code")
            vid = (vc.findtext("id") or "").strip() if vc is not None else ""
            persisted_good_ids.append(gid)
            persisted_vat_ids.append(vid)

        missing = [g for g in expected_good_ids if g not in persisted_good_ids]
        vat_ok  = all(v == _VAT_CODE_ID for v in persisted_vat_ids)
        vat_display = ", ".join(sorted(set(persisted_vat_ids))) or "(none)"

    except Exception as exc:
        print(f"WARNING: post-create re-fetch failed: {exc}")
        actual_count        = "?"
        persisted_good_ids  = []
        persisted_vat_ids   = []
        missing             = []
        vat_ok              = False
        vat_display         = "?"

    print(f"Expected line count: {expected_count}")
    print(f"Actual line count:   {actual_count}")
    print(f"Persisted good_ids:  {persisted_good_ids}")
    print(f"Missing good_ids:    {missing or 'none'}")
    print(f"Expected vat_code_id:{_VAT_CODE_ID}")
    print(f"Persisted vat_codes: {vat_display}")

    count_ok = actual_count == expected_count
    if count_ok and vat_ok:
        print()
        print("Verification result: PASS — 12 lines persisted, all VAT codes correct.")
    elif not count_ok:
        print()
        print(f"Verification result: FAIL — line count mismatch "
              f"(expected={expected_count} actual={actual_count}).")
    else:
        print()
        print(f"Verification result: FAIL — VAT code mismatch on one or more lines "
              f"(expected={_VAT_CODE_ID}, persisted={vat_display}).")


if __name__ == "__main__":
    main()

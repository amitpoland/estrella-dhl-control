"""
build_wfirma_pz_csv.py — emit wFirma CSV import file from a PZ_READY JSON.

CSV format (locked by operator spec):
  - separator     : semicolon (;)
  - encoding      : UTF-8 (with BOM, so Excel/wFirma read Polish chars correctly)
  - no header row
  - 11 columns per row, in this exact order:
        1.  Nazwa             (Polish / English description)
        2.  PKWiU             (empty)
        3.  Jednostka         (szt.)
        4.  Ilość             (quantity, dot-or-comma decimal — comma per PL)
        5.  Cena              (PLN net price, comma decimal)
        6.  Stawka            (23%)
        7.  Szczegółowy opis  (product_code)
        8.  Rodzaj ceny       (netto)
        9.  Kod produktu      (exact product_code)
       10.  Typ               (towar)
       11.  Kod EAN           (empty)

Validation (CSV not written if any blocker found):
  - no row may have a missing product_code
  - no two rows may share a product_code
  - quantity > 0
  - net_price_pln > 0
  - name is non-empty
  - exactly 11 columns per row (enforced by output writer)

Usage:
    python3 -m app.tools.build_wfirma_pz_csv PZ_READY_EJL-26-27-013.json
    python3 -m app.tools.build_wfirma_pz_csv PZ_READY_EJL-26-27-013.json \\
        PZ_READY_EJL-26-27-014.json PZ_READY_EJL-26-27-015.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ── Column spec (LOCKED) ──────────────────────────────────────────────────────

CSV_COLUMNS: Tuple[str, ...] = (
    "Nazwa",            # 1
    "PKWiU",            # 2
    "Jednostka",        # 3
    "Ilość",            # 4
    "Cena",             # 5
    "Stawka",           # 6
    "Szczegółowy opis", # 7
    "Rodzaj ceny",      # 8
    "Kod produktu",     # 9
    "Typ",              # 10
    "Kod EAN",          # 11
)

CSV_SEPARATOR = ";"
CSV_ENCODING  = "utf-8-sig"   # UTF-8 with BOM for cross-app safety
DEFAULT_UNIT  = "szt."
DEFAULT_VAT   = "23%"
DEFAULT_PRICE_TYPE = "netto"
DEFAULT_TYPE  = "towar"


# ── PL number formatting ──────────────────────────────────────────────────────

def _pl_decimal(value: float, places: int = 2) -> str:
    """Format with comma decimal, no thousands separator: 70.41 → '70,41'."""
    return f"{float(value):.{places}f}".replace(".", ",")


def _pl_qty(value: float) -> str:
    """Quantity: integers stay as '1', non-integers use comma decimal."""
    f = float(value)
    if f == int(f):
        return str(int(f))
    return _pl_decimal(f, places=4).rstrip("0").rstrip(",") or "0"


# ── Validation ────────────────────────────────────────────────────────────────

@dataclass
class CsvValidation:
    ok:       bool
    blockers: List[str]
    warnings: List[str]
    summary:  Dict[str, Any]


def validate(data: Dict[str, Any]) -> CsvValidation:
    blockers: List[str] = []
    warnings: List[str] = []

    rows = data.get("rows") or []
    if not rows:
        blockers.append("rows is empty")

    seen: Dict[str, int] = {}
    for i, row in enumerate(rows, start=1):
        code = (row.get("product_code") or "").strip()
        name = (row.get("name") or "").strip()
        try:
            qty   = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            price = float(row.get("net_price_pln") or 0)
        except (TypeError, ValueError):
            price = 0

        if not code:
            blockers.append(f"Row {i}: product_code MISSING")
        elif code in seen:
            blockers.append(f"Row {i}: duplicate product_code='{code}' (also row {seen[code]})")
        else:
            seen[code] = i

        if not name:
            blockers.append(f"Row {i} ({code or 'no-code'}): name is empty")
        if qty <= 0:
            blockers.append(f"Row {i} ({code or 'no-code'}): quantity must be > 0, got {qty}")
        if price <= 0:
            blockers.append(f"Row {i} ({code or 'no-code'}): net_price_pln must be > 0, got {price}")

    summary = {
        "invoice_no":  data.get("invoice_no", ""),
        "supplier":    data.get("supplier", ""),
        "rows":        len(rows),
        "net_pln":     (data.get("totals") or {}).get("net_pln", 0),
        "currency":    data.get("currency", "PLN"),
    }
    return CsvValidation(ok=not blockers, blockers=blockers, warnings=warnings, summary=summary)


# ── CSV building ──────────────────────────────────────────────────────────────

def build_csv_rows(data: Dict[str, Any]) -> List[List[str]]:
    """Return list-of-lists, each inner list has exactly len(CSV_COLUMNS) items."""
    out: List[List[str]] = []
    for row in data["rows"]:
        code  = row["product_code"]
        name  = row.get("name") or code
        qty   = float(row["quantity"])
        price = float(row["net_price_pln"])

        record = [
            name,                    # 1 Nazwa
            "",                      # 2 PKWiU
            DEFAULT_UNIT,            # 3 Jednostka
            _pl_qty(qty),            # 4 Ilość
            _pl_decimal(price, 2),   # 5 Cena
            DEFAULT_VAT,             # 6 Stawka
            code,                    # 7 Szczegółowy opis (product_code)
            DEFAULT_PRICE_TYPE,      # 8 Rodzaj ceny
            code,                    # 9 Kod produktu
            DEFAULT_TYPE,            # 10 Typ
            "",                      # 11 Kod EAN
        ]
        if len(record) != len(CSV_COLUMNS):
            raise RuntimeError(
                f"internal: built {len(record)} cols, expected {len(CSV_COLUMNS)}"
            )
        out.append(record)
    return out


def render_csv(rows: List[List[str]]) -> str:
    """Render rows to a CSV string. No header row. Semicolon separator."""
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter=CSV_SEPARATOR, quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    for r in rows:
        if len(r) != len(CSV_COLUMNS):
            raise RuntimeError(
                f"row has {len(r)} cols, expected {len(CSV_COLUMNS)}"
            )
        writer.writerow(r)
    return buf.getvalue()


def write_csv(path: Path, rows: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_csv(rows)
    # write_bytes, not write_text: on Windows/py3.9 write_text re-translates the
    # csv writer's \r\n into \r\r\n, injecting a blank line after every row.
    path.write_bytes(text.encode(CSV_ENCODING))


def build_for_file(src: Path, out_dir: Path) -> Tuple[CsvValidation, Path | None, List[List[str]]]:
    data = json.loads(src.read_text(encoding="utf-8"))
    val = validate(data)
    if not val.ok:
        return val, None, []
    rows = build_csv_rows(data)
    invoice = (val.summary.get("invoice_no") or "unknown").replace("/", "-")
    out_path = out_dir / f"wfirma_pz_csv_{invoice}.csv"
    write_csv(out_path, rows)
    return val, out_path, rows


# ── Preview / runbook ─────────────────────────────────────────────────────────

def print_preview(invoice_no: str, rows: List[List[str]]) -> None:
    width_code = max(len(r[8]) for r in rows) if rows else 12
    print(f"\nPreview — {invoice_no} ({len(rows)} row(s))")
    print(f"  {'Kod produktu':{width_code}}  {'Ilość':>6}  {'Cena':>10}  Nazwa")
    print(f"  {'-' * width_code}  {'-' * 6}  {'-' * 10}  ----")
    for r in rows:
        nazwa = r[0]
        if len(nazwa) > 60:
            nazwa = nazwa[:57] + "..."
        print(f"  {r[8]:{width_code}}  {r[3]:>6}  {r[4]:>10}  {nazwa}")


def write_runbook(out_path: Path, csv_files: List[Path]) -> None:
    """Write a short operator runbook for the wFirma UI CSV import path."""
    lines = [
        "# wFirma CSV import — operator runbook",
        "",
        "## Files",
        "",
    ]
    for p in csv_files:
        lines.append(f"- `{p}`")
    lines.extend([
        "",
        "## Step-by-step (per CSV)",
        "",
        "1. Log into wFirma → **Magazyn → Towary → Importuj z pliku**.",
        "2. Click **Wybierz plik**, pick the CSV.",
        "3. Set the column mapping if prompted (no header row, semicolon, UTF-8). The column order exactly matches the wFirma template:",
        "",
        "   `Nazwa ; PKWiU ; Jednostka ; Ilość ; Cena ; Stawka ; Szczegółowy opis ; Rodzaj ceny ; Kod produktu ; Typ ; Kod EAN`",
        "",
        "4. Confirm the preview shows: `Typ = towar`, `Stawka = 23%`, `Rodzaj ceny = netto`, `Jednostka = szt.`",
        "5. Click **Importuj**. wFirma creates the goods AND opens a stock receipt.",
        "6. Confirm the SKUs in **Magazyn → Towary**:",
        "   - search by **Indeks = `EJL/26-27/013-1`** (etc) → must show one row per code, never duplicate.",
        "7. Verify stock in **Magazyn → Stany** for warehouse 347088:",
        "   - quantities must match the invoice (e.g. EJL/26-27/015-6 → 21 szt.).",
        "",
        "## After all 3 imports succeed",
        "",
        "- Tell Claude Code: \"All 3 CSV imports completed; sync wFirma product mappings.\"",
        "  Claude Code will then call `POST /api/v1/wfirma/products/sync-by-codes` for all 14 codes,",
        "  populate `wfirma_product_mapping`, and the queue rows will move to `status=ready`.",
        "- Then we can proceed to the one-line live test reservation.",
        "",
        "## Rules during this path",
        "",
        "- Do NOT create more goods via API while the CSV path is active.",
        "- Do NOT create reservations until product mappings are synced.",
        "- The test good `EJL/26-27/015-3` (wfirma_id `48461283`) already exists — wFirma will warn during",
        "  CSV preview that this code is already in use. Skip that single row in the import or accept the",
        "  duplicate-code warning depending on UI prompt; if duplicate is rejected, re-export the CSV with",
        "  that row removed and add the stock manually via PZ for the test good only.",
        "",
        "## If the import fails",
        "",
        "- wFirma reports the row+column. Fix the CSV (or PZ_READY JSON), re-emit, retry.",
        "- The tool refuses to write the CSV if any row has a missing/duplicate product_code or zero qty/price.",
        "",
    ])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_support_ticket(out_path: Path) -> None:
    """Draft the wFirma support ticket asking for warehouse_document_p_z/add schema."""
    body = """\
Subject: Exact XML schema required for warehouse_document_p_z/add (PZ external receipt) — opaque INPUT ERROR responses

Hi wFirma support team,

We're integrating the wFirma API for PZ (Przyjęcie Zewnętrzne) document creation
and we keep getting opaque INPUT ERROR responses from POST /warehouse_document_p_z/add.
The endpoint is reachable, our 3-header API Key auth works, and our payload is
modelled on the structure returned by warehouse_document_p_z/find for an existing
PZ in our company (id 33365789, "PZ 1/5/2020"). Despite this we get only:

    <api>
        <status>
            <code>INPUT ERROR</code>
        </status>
    </api>

without any field-level message.

Company: ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA (NIP 5252812119)
wFirma company_id: 359292
Warehouse id: 347088 (warehouse_type extended, module enabled)

Could you please confirm the EXACT add-payload schema for warehouse_document_p_z/add?
Specifically:

1. The wrapping element — is it <warehouse_documents> (plural umbrella) or
   <warehouse_document_p_z> (typed)? Both? Are the rules identical?

2. Required document-level fields. Our current attempt includes:
       <type>PZ</type>
       <date>YYYY-MM-DD</date>
       <status>pending</status>
       <currency>PLN</currency>
       <vat_payer>1</vat_payer>
       <price_type>netto</price_type>
       <description>...</description>
       <contractor><id>...</id></contractor>
       <warehouse><id>347088</id></warehouse>
       <series><id>15827163</id></series>
   Which of these are required? Are any prohibited? Is <series><id> required for
   add, or does the API auto-assign from an active default series? (Our existing
   PZ documents all reference series id 15827163 but the newest is from 2020.)

3. Required line-level fields inside <warehouse_document_content>. Our current
   attempt includes:
       <name>...</name>
       <good><id>48461283</id></good>
       <unit><id>17456790</id></unit>
       <unit_count>1.0000</unit_count>
       <price>70.41</price>
       <vat_code><id>222</id></vat_code>
   Is <warehouse_good_parcels> required for goods with warehouse_type "extended"?
   If yes, what fields are required inside it for an add operation? Are
   <purchase_expense> / <production_expense> / <netto> / <brutto> required, or
   are they always system-calculated?

4. Decimal format — must <price> and <unit_count> use a dot ("70.41") or comma
   ("70,41")? wFirma's UI uses comma; XML responses use dot.

5. Does the endpoint return field-level errors anywhere we can read (a verbose
   flag, an X-header, the response envelope)? Right now we have no way to
   diagnose which field is wrong.

6. Sample minimal accepted payload — could you share one? Even one line, one
   good, one warehouse — that is guaranteed to be accepted by your validator
   today. We can build everything else from there.

Without this, we have to fall back to the CSV import in the UI for our customs
intake, which works but doesn't scale to our shipment automation. Any pointer
to a non-public schema reference, a working example, or a debug mode is much
appreciated.

Thanks,
Amit Gupta
ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="build_wfirma_pz_csv")
    p.add_argument("pz_ready_json", nargs="+", help="One or more PZ_READY_*.json files")
    p.add_argument("--out-dir", default=None,
                   help="Output directory (default: <repo>/outputs)")
    p.add_argument("--no-runbook", action="store_true",
                   help="Skip writing the operator runbook")
    p.add_argument("--no-ticket", action="store_true",
                   help="Skip writing the support-ticket draft")
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]   # …/CLI
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else repo_root / "outputs"

    written: List[Path] = []
    any_blockers = False
    for src_str in args.pz_ready_json:
        src = Path(src_str).expanduser()
        if not src.is_file():
            print(f"ERROR: file not found: {src}", file=sys.stderr)
            any_blockers = True
            continue

        validation, out_path, rows = build_for_file(src, out_dir)
        s = validation.summary
        print(f"\n=== {src.name} → {s.get('invoice_no')} ({s.get('rows')} rows, "
              f"{s.get('net_pln'):,.2f} {s.get('currency')}) ===")
        if not validation.ok:
            print("  BLOCKERS:")
            for b in validation.blockers:
                print(f"    ✗ {b}")
            any_blockers = True
            continue
        print(f"  ✓ wrote: {out_path}")
        print_preview(s.get("invoice_no", "?"), rows)
        written.append(out_path)

    if written and not args.no_runbook:
        runbook = out_dir / "wfirma_csv_import_runbook.md"
        write_runbook(runbook, written)
        print(f"\n📋 Runbook: {runbook}")

    if not args.no_ticket:
        ticket = out_dir / "wfirma_support_ticket_pz_api.txt"
        write_support_ticket(ticket)
        print(f"📨 Support ticket draft: {ticket}")

    return 1 if any_blockers else 0


if __name__ == "__main__":
    sys.exit(main())

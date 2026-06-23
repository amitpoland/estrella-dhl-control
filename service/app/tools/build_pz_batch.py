"""
build_pz_batch.py — generate ONE PZ batch (JSON + CSV + UI payload) from one
or more PZ_READY invoice files for a single shipment.

Rule:    1 AWB / 1 SAD  →  1 PZ  →  1 truth.

Inputs: any number of PZ_READY_*.json files. They MUST share the same supplier.
Outputs:
  outputs/PZ_BATCH_<awb>.json       — canonical batch (all decimals, totals)
  outputs/PZ_BATCH_<awb>.csv        — wFirma-CSV-friendly backup (semicolon, PL comma)
  outputs/PZ_BATCH_<awb>_ui.json    — minimal payload for the v3 autofill JS

The PZ_READY format already used in this repo:
  {
    "invoice_no":           "EJL/26-27/015",
    "supplier":             "ESTRELLA JEWELS LLP.",
    "supplier_wfirma_id":   "38142296",
    "document_date":        "2026-04-04",
    "warehouse_id":         "347088",
    "rows": [
      {
        "product_code":     "EJL/26-27/015-3",
        "wfirma_good_id":   "48461283",       # OPTIONAL — auto-resolved if absent
        "name":             "Wisiorek ... / SL925 Silver LGD Diamond Pendant",
        "quantity":         2,
        "unit":             "szt.",
        "net_price_pln":    70.41,
        "vat_code_id":      "222"             # OPTIONAL — defaults to 222 (VAT 23%)
      },
      ...
    ],
    ...
  }

Field-name normalisation (PZ_READY → PZBatchLine):
  rows[i].quantity        →  qty
  rows[i].net_price_pln   →  price_net_pln
  parent.invoice_no       →  line.invoice_no

Auto-resolution (when --resolve is set):
  If a row has no wfirma_good_id, this script calls
  app.services.wfirma_client.get_product_by_code(code) once per missing code
  and fills the bridge. Dry-run by default.

Usage:
  python3 -m app.tools.build_pz_batch \\
    --awb 6876258325 --sad PL123456 \\
    /path/to/PZ_READY_EJL-26-27-013.json \\
    /path/to/PZ_READY_EJL-26-27-014.json \\
    /path/to/PZ_READY_EJL-26-27-015.json
  python3 -m app.tools.build_pz_batch ... --resolve   # call goods/find for missing IDs
  python3 -m app.tools.build_pz_batch ... --json      # JSON output only
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.models.pz_batch_schema import (   # noqa: E402
    DEFAULT_CURRENCY,
    DEFAULT_PRICE_TYPE,
    DEFAULT_PZ_SERIES_ID,
    DEFAULT_UNIT_ID,
    DEFAULT_VAT_CODE_ID,
    DEFAULT_WAREHOUSE_ID,
    PZBatch,
    PZBatchLine,
    Supplier,
)
from app.tools.validate_pz_batch import validate    # noqa: E402


# ── Loading / normalisation ───────────────────────────────────────────────────

def _decimal(v: Any) -> Decimal:
    """Coerce to Decimal via str (avoid float→Decimal precision loss)."""
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"cannot parse {v!r} as Decimal: {exc}") from exc


def load_pz_ready(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalise_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Pull supplier/invoice metadata into a normalised shape."""
    supplier_name = inv.get("supplier") or ""
    if isinstance(supplier_name, dict):
        # Already an object form — accept either {wfirma_id, name} or {id, name}
        wfid = supplier_name.get("wfirma_id") or supplier_name.get("id") or ""
        sname = supplier_name.get("name") or ""
    else:
        wfid = inv.get("supplier_wfirma_id") or ""
        sname = supplier_name
    return {
        "invoice_no":     inv.get("invoice_no", ""),
        "supplier_id":    str(wfid),
        "supplier_name":  sname,
        "warehouse_id":   str(inv.get("warehouse_id") or DEFAULT_WAREHOUSE_ID),
        "document_date":  inv.get("document_date") or "",
        "rows":           inv.get("rows", []),
    }


# ── Optional good_id auto-resolver ────────────────────────────────────────────

def resolve_missing_good_ids(rows_by_code: Dict[str, dict]) -> Tuple[Dict[str, str], List[str]]:
    """For codes whose wfirma_good_id is missing, look it up via goods/find.

    Returns ({code: wfirma_good_id}, [unresolved_codes]).
    Only called when --resolve flag is explicit. Read-only on wFirma.
    """
    from app.services import wfirma_client as wfc

    out: Dict[str, str] = {}
    missing: List[str] = []
    for code, row in rows_by_code.items():
        if row.get("wfirma_good_id"):
            out[code] = str(row["wfirma_good_id"])
            continue
        prod = wfc.get_product_by_code(code)
        if prod is None:
            missing.append(code)
        else:
            out[code] = prod.wfirma_id
    return out, missing


# ── Build ─────────────────────────────────────────────────────────────────────

def build_batch(
    invoices_data: List[Dict[str, Any]],
    awb: str,
    sad_number: str,
    *,
    resolve_good_ids: bool = False,
    document_date: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    series_id:    Optional[str] = None,
) -> PZBatch:
    """Combine N invoice payloads into one PZBatch (1 AWB → 1 PZ)."""
    if not invoices_data:
        raise ValueError("no invoices provided")

    normed = [normalise_invoice(i) for i in invoices_data]

    # Same-supplier guard
    suppliers = {(n["supplier_id"], n["supplier_name"]) for n in normed}
    if len({s[0] for s in suppliers}) != 1:
        raise ValueError(
            f"different suppliers across invoices: {suppliers} — refuse to merge into single PZ"
        )
    supplier_id, supplier_name = next(iter(suppliers))
    if not supplier_id:
        raise ValueError("supplier_wfirma_id missing")

    # Warehouse + date pin
    warehouses = {n["warehouse_id"] for n in normed}
    if len(warehouses) != 1:
        raise ValueError(f"different warehouse_id across invoices: {warehouses}")
    chosen_warehouse = warehouse_id or next(iter(warehouses))

    chosen_date = (
        document_date
        or (normed[0].get("document_date"))
        or date.today().isoformat()
    )

    # Optional good_id resolution
    if resolve_good_ids:
        all_rows_by_code: Dict[str, dict] = {}
        for n in normed:
            for r in n["rows"]:
                code = (r.get("product_code") or "").strip()
                if code and code not in all_rows_by_code:
                    all_rows_by_code[code] = r
        resolved, missing = resolve_missing_good_ids(all_rows_by_code)
        if missing:
            raise ValueError(
                f"goods/find could not resolve {len(missing)} codes: {missing[:5]} ... "
                "create them via send_wfirma_good_live_test before building the batch."
            )
        # Patch back
        for n in normed:
            for r in n["rows"]:
                code = (r.get("product_code") or "").strip()
                if code and not r.get("wfirma_good_id"):
                    r["wfirma_good_id"] = resolved.get(code, "")

    # Lines
    lines: List[PZBatchLine] = []
    for n in normed:
        for r in n["rows"]:
            lines.append(PZBatchLine(
                product_code   = (r.get("product_code") or "").strip(),
                wfirma_good_id = str(r.get("wfirma_good_id") or "").strip(),
                name           = (r.get("name") or "").strip(),
                qty            = _decimal(r.get("quantity") or r.get("qty") or 0),
                price_net_pln  = _decimal(r.get("net_price_pln") or r.get("price_net_pln") or 0),
                invoice_no     = n["invoice_no"],
                vat_code_id    = str(r.get("vat_code_id") or DEFAULT_VAT_CODE_ID),
                unit_id        = str(r.get("unit_id") or DEFAULT_UNIT_ID),
            ))

    return PZBatch(
        batch_id      = f"AWB_{awb}",
        awb           = awb,
        sad_number    = sad_number or "",
        supplier      = Supplier(wfirma_id=supplier_id, name=supplier_name),
        warehouse_id  = chosen_warehouse,
        document_date = chosen_date,
        currency      = DEFAULT_CURRENCY,
        price_type    = DEFAULT_PRICE_TYPE,
        series_id     = series_id or DEFAULT_PZ_SERIES_ID,
        lines         = lines,
        invoices      = [n["invoice_no"] for n in normed if n["invoice_no"]],
        notes         = "",
    )


# ── Output writers ────────────────────────────────────────────────────────────

def save_json(batch: PZBatch, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"PZ_BATCH_{batch.awb}.json"
    p.write_text(json.dumps(batch.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def save_csv(batch: PZBatch, out_dir: Path) -> Path:
    """Backup CSV (semicolon, comma decimal, no header).

    Column order matches build_wfirma_pz_csv.py spec:
       Nazwa ; PKWiU ; Jednostka ; Ilość ; Cena ; Stawka ; Szczegółowy opis ;
       Rodzaj ceny ; Kod produktu ; Typ ; Kod EAN
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"PZ_BATCH_{batch.awb}.csv"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for ln in batch.lines:
        qty_str = str(ln.qty) if ln.qty == ln.qty.to_integral() else str(ln.qty).replace(".", ",")
        w.writerow([
            ln.name,
            "",                               # PKWiU
            "szt.",                           # Jednostka
            qty_str,
            str(ln.price_net_pln).replace(".", ","),
            "23%",
            ln.product_code,                  # Szczegółowy opis = code
            "netto",
            ln.product_code,                  # Kod produktu = code
            "towar",
            "",                               # Kod EAN
        ])
    # write_bytes (not write_text): the csv.writer already emits explicit \r\n
    # line terminators; on Windows/py3.9 Path.write_text opens in text mode and
    # re-translates \n -> \r\n, doubling every terminator into \r\r\n. Writing
    # bytes preserves the writer's line endings exactly.
    p.write_bytes(buf.getvalue().encode("utf-8-sig"))
    return p


def save_ui_payload(batch: PZBatch, out_dir: Path) -> Path:
    """Compact JSON the v3 autofill JS reads (just what it needs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"PZ_BATCH_{batch.awb}_ui.json"
    payload = {
        "batch_id":       batch.batch_id,
        "awb":            batch.awb,
        "supplier_id":    batch.supplier.wfirma_id,
        "supplier_name":  batch.supplier.name,
        "warehouse_id":   batch.warehouse_id,
        "document_date":  batch.document_date,
        "lines": [
            {
                "product_code":   ln.product_code,
                "wfirma_good_id": ln.wfirma_good_id,
                "name":           ln.name,
                "qty":            str(ln.qty),
                "price_net_pln":  str(ln.price_net_pln),
                "invoice_no":     ln.invoice_no,
            }
            for ln in batch.lines
        ],
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(batch: PZBatch, paths: Dict[str, Path]) -> None:
    print("=" * 76)
    print(f" PZ BATCH CREATED — 1 AWB → 1 PZ")
    print("=" * 76)
    print(f"  AWB           : {batch.awb}")
    print(f"  SAD           : {batch.sad_number or '(pending)'}")
    print(f"  Supplier      : {batch.supplier.name}  (wfirma_id={batch.supplier.wfirma_id})")
    print(f"  Warehouse     : {batch.warehouse_id}")
    print(f"  Date          : {batch.document_date}")
    print(f"  Invoices      : {', '.join(batch.invoices) or '(none)'}")
    print(f"  Lines         : {len(batch.lines)}")
    print(f"  Total NET     : {batch.total_net()} PLN")
    print(f"  Total BRUTTO  : {batch.total_brutto()} PLN  (@ 23% VAT)")
    print()
    print(f"  JSON          : {paths['json']}")
    print(f"  CSV (backup)  : {paths['csv']}")
    print(f"  UI payload    : {paths['ui']}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="build_pz_batch")
    p.add_argument("files", nargs="+", help="One or more PZ_READY_*.json files (same supplier)")
    p.add_argument("--awb", required=True, help="AWB / shipment number")
    p.add_argument("--sad", default="", help="SAD number (optional, may be empty)")
    p.add_argument("--date", default=None, help="Override document_date (YYYY-MM-DD)")
    p.add_argument("--warehouse", default=None, help="Override warehouse_id")
    p.add_argument("--series",    default=None, help="Override series_id")
    p.add_argument("--resolve",   action="store_true",
                   help="If a row is missing wfirma_good_id, call goods/find to fill it")
    p.add_argument("--out-dir",   default=None, help="Output directory (default: <repo>/outputs)")
    p.add_argument("--json",      action="store_true", help="Print JSON instead of human summary")
    args = p.parse_args(argv)

    invoices = [load_pz_ready(Path(f).expanduser()) for f in args.files]

    try:
        batch = build_batch(
            invoices,
            awb              = args.awb,
            sad_number       = args.sad,
            resolve_good_ids = args.resolve,
            document_date    = args.date,
            warehouse_id     = args.warehouse,
            series_id        = args.series,
        )
    except ValueError as exc:
        print(f"BUILD ERROR: {exc}", file=sys.stderr)
        return 2

    val = validate(batch)
    if not val.ok:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in val.errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 3

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else \
              Path(__file__).resolve().parents[3] / "outputs"
    paths = {
        "json": save_json(batch, out_dir),
        "csv":  save_csv(batch, out_dir),
        "ui":   save_ui_payload(batch, out_dir),
    }

    if args.json:
        print(json.dumps({
            "batch":     batch.to_dict(),
            "ok":        val.ok,
            "warnings":  val.warnings,
            "out":       {k: str(v) for k, v in paths.items()},
        }, indent=2, ensure_ascii=False))
    else:
        _print_summary(batch, paths)
        if val.warnings:
            print("WARNINGS:")
            for w in val.warnings:
                print(f"  ⚠ {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

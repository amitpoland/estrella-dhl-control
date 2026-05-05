"""
build_wfirma_pz_payload.py — wFirma PZ (Przyjęcie Zewnętrzne) XML payload builder.

Builds a candidate XML payload from a PZ_READY JSON file. NEVER calls wFirma.
The payload shape is a HYPOTHESIS based on:
  - existing wfirma_client patterns (warehouse_document_r/add for reservations)
  - wfirma_client._WAREHOUSE_MODULES which already lists "warehouse_document_p_z"
  - public wFirma API docs at doc.wfirma.pl

The exact schema for warehouse_document_p_z/add is NOT yet confirmed by a probe.
Treat the output as a draft until probe_wfirma_pz_api.py verifies the endpoint.

Usage:
    python3 -m app.tools.build_wfirma_pz_payload PZ_READY_EJL-26-27-013.json
    python3 -m app.tools.build_wfirma_pz_payload PZ_READY_EJL-26-27-013.json --json

Outputs:
    outputs/wfirma_pz_payload_<invoice_no>.xml
    Console: validation summary + XML preview

Validation blockers (any of these abort with non-zero exit):
    - missing supplier_wfirma_id
    - missing warehouse_id
    - missing document_date
    - any row missing product_code
    - duplicate product_code within payload
    - non-positive quantity or unit price
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape


# ── Module + endpoint constants (HYPOTHESIS) ──────────────────────────────────

WFIRMA_PZ_MODULE = "warehouse_document_p_z"   # Przyjęcie Zewnętrzne (POST URL module)
WFIRMA_PZ_ACTION = "add"
WFIRMA_PZ_ENDPOINT_HYPOTHESIS = f"{WFIRMA_PZ_MODULE}/{WFIRMA_PZ_ACTION}"
SCHEMA_CONFIRMED = False    # flip to True only after a successful live PZ POST

# XML wrapper — confirmed via warehouse_document_p_z/find response (umbrella plural,
# same shape as wfirma_client._build_reservation_xml uses for warehouse_document_r/add).
WFIRMA_PZ_WRAPPER = "warehouse_documents"
WFIRMA_PZ_TYPE    = "PZ"          # uppercase document type marker

# Fixed wFirma VAT id for VAT 23% in this account, confirmed live via goods/find.
DEFAULT_VAT_CODE_ID = "222"

# wFirma units module — szt. (sztuka, "piece") in this account, confirmed via units/find.
DEFAULT_UNIT_ID = "17456790"      # category=piece:szt → name "szt."

# wFirma series — per-document-type numbering sequence. The PZ series id used by
# the existing 300 PZ documents in this account, confirmed via warehouse_document_p_z/find.
DEFAULT_PZ_SERIES_ID = "15827163"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(value: Any) -> str:
    """XML-escape any scalar."""
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _decimal(value: float, places: int = 4) -> str:
    """Format a decimal with dot separator (XML-safe). Comma is for CSV only."""
    fmt = f"{{:.{places}f}}"
    return fmt.format(float(value))


# ── Validation ────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    blockers: List[str]
    warnings: List[str]
    summary: Dict[str, Any]


def validate_pz_ready(data: Dict[str, Any]) -> ValidationResult:
    """Validate a PZ_READY payload. Returns blockers + warnings, never raises."""
    blockers: List[str] = []
    warnings: List[str] = []

    if not data.get("supplier_wfirma_id"):
        blockers.append("supplier_wfirma_id is missing — required for <contractor><id>")
    if not data.get("warehouse_id"):
        blockers.append("warehouse_id is missing — required for <warehouse><id>")
    if not data.get("document_date"):
        blockers.append("document_date is missing — required for <date>")

    rows = data.get("rows") or []
    if not rows:
        blockers.append("rows is empty — at least one line required")

    seen_codes: Dict[str, int] = {}
    seen_good_ids: Dict[str, int] = {}
    for i, row in enumerate(rows, start=1):
        code = (row.get("product_code") or "").strip()
        if not code:
            blockers.append(f"Row {i}: product_code MISSING — name-only matching forbidden")
        else:
            if code in seen_codes:
                blockers.append(
                    f"Row {i}: duplicate product_code='{code}' (also row {seen_codes[code]})"
                )
            else:
                seen_codes[code] = i

        # wfirma_good_id is now mandatory — PZ references existing goods by ID,
        # never upserts via <code>+<name>. The good must exist in wFirma first.
        good_id = str(row.get("wfirma_good_id") or "").strip()
        if not good_id:
            blockers.append(
                f"Row {i} ({code or 'no-code'}): wfirma_good_id MISSING — "
                f"resolve product_code → wfirma_good_id via goods/find before building PZ"
            )
        elif good_id in seen_good_ids:
            blockers.append(
                f"Row {i} ({code or 'no-code'}): duplicate wfirma_good_id={good_id} "
                f"(also row {seen_good_ids[good_id]})"
            )
        else:
            seen_good_ids[good_id] = i

        try:
            qty = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            blockers.append(f"Row {i} ({code or 'no-code'}): quantity must be > 0, got {qty}")

        try:
            price = float(row.get("net_price_pln") or 0)
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            blockers.append(f"Row {i} ({code or 'no-code'}): net_price_pln must be > 0, got {price}")

        if not (row.get("name") or "").strip():
            warnings.append(f"Row {i} ({code or 'no-code'}): name is empty")
        if not (row.get("unit") or "").strip():
            warnings.append(f"Row {i} ({code or 'no-code'}): unit is empty, defaulting to 'szt.'")

    summary = {
        "invoice_no":   data.get("invoice_no", ""),
        "supplier":     data.get("supplier", ""),
        "supplier_id":  data.get("supplier_wfirma_id", ""),
        "warehouse_id": data.get("warehouse_id", ""),
        "date":         data.get("document_date", ""),
        "rows":         len(rows),
        "net_pln":      (data.get("totals") or {}).get("net_pln", 0),
    }

    return ValidationResult(
        ok=not blockers,
        blockers=blockers,
        warnings=warnings,
        summary=summary,
    )


# ── XML payload builder ───────────────────────────────────────────────────────

def build_pz_xml(data: Dict[str, Any]) -> str:
    """
    Build a candidate XML payload for warehouse_document_p_z/add.

    Each <warehouse_document_content> references an EXISTING good by
    <good><id>{wfirma_good_id}</id></good>. wFirma does not auto-create goods
    from a PZ — the good must already exist (verified live 2026-05-03 against
    a one-line PZ that returned INPUT ERROR when sent with <good><code>...).

    VAT is given as <vat_code><id>222</id></vat_code> — the wFirma internal
    id for VAT 23%, confirmed via goods/find against existing EJL goods in
    this account. The literal <vat>23</vat> form is NOT accepted.

    The line-level <name> and <unit> mirror the existing reservation builder
    in wfirma_client._build_reservation_xml — they describe the PZ line, not
    the good's master record.

    Caller MUST run validate_pz_ready first. This function does not re-validate.
    """
    invoice_no   = data.get("invoice_no", "")
    supplier_id  = data["supplier_wfirma_id"]
    warehouse_id = data["warehouse_id"]
    date         = data["document_date"]
    rows         = data["rows"]
    series_id    = str(data.get("series_id") or DEFAULT_PZ_SERIES_ID).strip()
    currency     = (data.get("currency") or "PLN").strip()
    status       = (data.get("status") or "pending").strip()

    description_parts = [f"PZ from {invoice_no}"] if invoice_no else ["PZ"]
    if data.get("batch_id"):
        description_parts.append(f"batch={data['batch_id']}")
    description = " | ".join(description_parts)

    lines_xml = ""
    for row in rows:
        name        = row.get("name") or row["product_code"]
        qty         = float(row["quantity"])
        net         = float(row["net_price_pln"])
        good_id     = str(row["wfirma_good_id"]).strip()
        vat_code_id = str(row.get("vat_code_id") or DEFAULT_VAT_CODE_ID).strip()
        unit_id     = str(row.get("unit_id") or DEFAULT_UNIT_ID).strip()
        # warehouse_good_parcels block — required for warehouse_type=extended goods.
        # Lifted verbatim from existing live PZ id 33365789 in this account.
        parcel_warehouse_id = str(row.get("parcel_warehouse_id") or warehouse_id).strip()

        lines_xml += f"""
      <warehouse_document_content>
        <name>{_esc(name)}</name>
        <good>
          <id>{_esc(good_id)}</id>
        </good>
        <unit>
          <id>{_esc(unit_id)}</id>
        </unit>
        <unit_count>{_decimal(qty, 4)}</unit_count>
        <price>{_decimal(net, 2)}</price>
        <vat_code>
          <id>{_esc(vat_code_id)}</id>
        </vat_code>
        <warehouse_good_parcels>
          <warehouse_good_parcel>
            <count>{_decimal(qty, 4)}</count>
            <purchase_price>{_decimal(net, 2)}</purchase_price>
            <production_price>{_decimal(net, 2)}</production_price>
            <warehouse>
              <id>{_esc(parcel_warehouse_id)}</id>
            </warehouse>
          </warehouse_good_parcel>
        </warehouse_good_parcels>
      </warehouse_document_content>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <{WFIRMA_PZ_WRAPPER}>
    <warehouse_document>
      <type>{_esc(WFIRMA_PZ_TYPE)}</type>
      <date>{_esc(date)}</date>
      <status>{_esc(status)}</status>
      <currency>{_esc(currency)}</currency>
      <vat_payer>1</vat_payer>
      <price_type>netto</price_type>
      <description>{_esc(description)}</description>
      <contractor>
        <id>{_esc(supplier_id)}</id>
      </contractor>
      <warehouse>
        <id>{_esc(warehouse_id)}</id>
      </warehouse>
      <series>
        <id>{_esc(series_id)}</id>
      </series>
      <warehouse_document_contents>{lines_xml}
      </warehouse_document_contents>
    </warehouse_document>
  </{WFIRMA_PZ_WRAPPER}>
</api>
"""


def build_payload(pz_ready_path: Path) -> Tuple[ValidationResult, str]:
    """High-level: load JSON → validate → build XML (or empty if blocked)."""
    data = json.loads(pz_ready_path.read_text(encoding="utf-8"))
    validation = validate_pz_ready(data)
    if not validation.ok:
        return validation, ""
    xml = build_pz_xml(data)
    return validation, xml


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_human(validation: ValidationResult, xml: str, out_path: Path | None) -> None:
    print("=" * 76)
    print(" wFirma PZ payload builder — DRY-RUN ONLY (no HTTP calls)")
    print("=" * 76)
    print(f"  endpoint hypothesis : POST {WFIRMA_PZ_ENDPOINT_HYPOTHESIS}")
    print(f"  schema confirmed    : {SCHEMA_CONFIRMED}  (false until probe verifies)")
    print()
    print("  SUMMARY")
    for k, v in validation.summary.items():
        print(f"    {k:14s}: {v}")
    print()

    if validation.blockers:
        print("  BLOCKERS (XML not generated):")
        for b in validation.blockers:
            print(f"    ✗ {b}")
        print()
    if validation.warnings:
        print("  WARNINGS:")
        for w in validation.warnings:
            print(f"    ⚠ {w}")
        print()

    if xml:
        print("  XML PAYLOAD:")
        print("  " + "-" * 70)
        for line in xml.splitlines():
            print(f"  {line}")
        print("  " + "-" * 70)
        if out_path:
            print(f"\n  Saved to: {out_path}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="build_wfirma_pz_payload")
    p.add_argument("pz_ready_json", help="Path to PZ_READY_*.json")
    p.add_argument("--json", action="store_true", help="Emit JSON output")
    p.add_argument("--no-write", action="store_true", help="Do not write the .xml file")
    args = p.parse_args(argv)

    src = Path(args.pz_ready_json).expanduser()
    if not src.is_file():
        print(f"ERROR: file not found: {src}", file=sys.stderr)
        return 2

    validation, xml = build_payload(src)

    out_path: Path | None = None
    if xml and not args.no_write:
        out_dir = Path(__file__).resolve().parents[3] / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        invoice = (validation.summary.get("invoice_no") or "unknown").replace("/", "-")
        out_path = out_dir / f"wfirma_pz_payload_{invoice}.xml"
        out_path.write_text(xml, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "endpoint_hypothesis": WFIRMA_PZ_ENDPOINT_HYPOTHESIS,
            "schema_confirmed":    SCHEMA_CONFIRMED,
            "ok":                  validation.ok,
            "summary":             validation.summary,
            "blockers":            validation.blockers,
            "warnings":            validation.warnings,
            "out_path":            str(out_path) if out_path else None,
            "xml":                 xml,
        }, indent=2, default=str))
    else:
        _print_human(validation, xml, out_path)

    return 0 if validation.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""
routes_wfirma.py — wFirma PZ Export
=====================================
Exports generated PZ data into formats ready for wFirma.pl import.

Modes
-----
  Mode 1  — Clipboard (tab-separated)
    POST /api/v1/upload/shipment/{batch_id}/wfirma/clipboard
    Returns tab-delimited rows ready for paste into wFirma PZ table.

  Mode 1B — PZ_READY.json
    GET  /api/v1/upload/shipment/{batch_id}/wfirma/json
    Returns structured JSON saved as outputs/{batch_id}/PZ_READY.json.

Guards (both modes)
-------------------
  - SAD/ZC429 must be present
  - PZ must be in status "success" or "partial"
  - PZ rows must exist (read from pz_rows.json or XLSX Rows sheet)

Rules
-----
  - Duty A00 is already allocated into cost price (line_netto_pln includes duty)
  - Do NOT add VAT — PZ is stock receipt cost basis
  - Polish numeric format: 1 234,56
  - Uwagi includes: Invoice, AWB, MRN, NBP rate, A00 note
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..core.logging import get_logger
from ..core.security import require_api_key
from ..core import timeline as tl
from ..services.batch_service import get_output_dir
from ..utils.io import write_json_atomic

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/upload", tags=["wfirma"])
_auth  = Depends(require_api_key)

# ── Timeline events ───────────────────────────────────────────────────────────
EV_WFIRMA_CLIPBOARD = "wfirma_clipboard_generated"
EV_WFIRMA_JSON      = "wfirma_json_generated"

# PZ statuses that indicate a completed run
_PZ_DONE = {"success", "partial"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_audit(output_dir: Path) -> dict:
    p = output_dir / "audit.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"audit.json unreadable: {e}")


def _guard_wfirma_export(audit: dict) -> None:
    """Block wFirma export if SAD is missing or PZ not yet generated."""
    inputs = audit.get("inputs") or {}
    if not inputs.get("zc429"):
        raise HTTPException(
            status_code=422,
            detail={
                "guard": "wfirma",
                "error": "wFirma export requires SAD (ZC429). Upload SAD before exporting.",
                "code": "WFIRMA_NO_SAD",
            },
        )
    status = audit.get("status", "")
    if status not in _PZ_DONE:
        raise HTTPException(
            status_code=422,
            detail={
                "guard": "wfirma",
                "error": f"wFirma export requires a completed PZ. Current status: {status!r}.",
                "code": "WFIRMA_PZ_NOT_GENERATED",
            },
        )


def _fmt_pln(v: float) -> str:
    """Polish numeric format: 1 234,56 (space thousands, comma decimal)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "0,00"
    # Format with comma thousands first, then swap separators
    formatted = f"{f:,.2f}"  # e.g. "1,234.56"
    return formatted.replace(",", "X").replace(".", ",").replace("X", chr(32))


def _load_rows_from_pz_rows_json(output_dir: Path) -> Optional[List[dict]]:
    """Try to load rows from pz_rows.json (written by export_service post-processing)."""
    p = output_dir / "pz_rows.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("rows")
        if rows and isinstance(rows, list):
            return rows
    except Exception as e:
        log.warning("pz_rows.json parse error: %s", e)
    return None


def _load_rows_from_xlsx(output_dir: Path, audit: dict) -> Optional[List[dict]]:
    """
    Fallback: read the Rows sheet of the calc XLSX.
    Extracts columns by header name — robust to column reorder.
    """
    xlsx_name = (audit.get("files") or {}).get("xlsx", {}).get("name")
    if not xlsx_name:
        # Try glob for any *_calc.xlsx
        candidates = list(output_dir.glob("*_calc.xlsx"))
        if not candidates:
            return None
        xlsx_name = candidates[0].name

    xlsx_path = output_dir / xlsx_name
    if not xlsx_path.exists():
        return None

    try:
        import openpyxl
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
        if "Rows" not in wb.sheetnames:
            wb.close()
            return None

        ws = wb["Rows"]
        # Read header row (row 1) to build column-name → index map
        header_map: Dict[str, int] = {}
        rows_raw = list(ws.iter_rows(values_only=True))
        if not rows_raw:
            wb.close()
            return None

        for c_idx, cell_val in enumerate(rows_raw[0]):
            if cell_val:
                header_map[str(cell_val).strip()] = c_idx

        def _col(row_vals, name, default=None):
            idx = header_map.get(name)
            if idx is None:
                return default
            v = row_vals[idx] if idx < len(row_vals) else None
            return v if v is not None else default

        rows_out = []
        for row_vals in rows_raw[1:]:
            if all(v is None for v in row_vals):
                continue  # skip empty rows
            lp = _col(row_vals, "Lp")
            if lp is None:
                continue

            # Extract a clean unit from Item Type or default "szt."
            item_type = str(_col(row_vals, "Item Type", "")).strip()
            unit = _col(row_vals, "Unit", "szt.") or "szt."

            rows_out.append({
                "lp":               int(lp) if lp else 0,
                "invoice_no":       str(_col(row_vals, "Invoice No", "") or ""),
                "description_en":   str(_col(row_vals, "English Name", "") or ""),
                "pl_desc":          str(_col(row_vals, "Polish Name", "") or ""),
                "quantity":         float(_col(row_vals, "Qty", 1) or 1),
                "unit":             unit,
                "unit_netto_pln":   float(_col(row_vals, "Unit Netto PLN", 0) or 0),
                "line_netto_pln":   float(_col(row_vals, "Line Netto PLN", 0) or 0),
                "line_brutto_pln":  float(_col(row_vals, "Line Brutto PLN", 0) or 0),
                "allocated_duty_pln": float(_col(row_vals, "Alloc. Duty PLN", 0) or 0),
                "usd_pln":          float(_col(row_vals, "Rate PLN/USD", 0) or 0),
                "item_type":        item_type,
            })
        wb.close()
        return rows_out or None

    except Exception as e:
        log.warning("XLSX Rows read error: %s", e)
        return None


def _build_rows(output_dir: Path, audit: dict) -> List[dict]:
    """Load PZ rows from best available source, or raise 422."""
    rows = _load_rows_from_pz_rows_json(output_dir)
    if not rows:
        rows = _load_rows_from_xlsx(output_dir, audit)
    if not rows:
        raise HTTPException(
            status_code=422,
            detail={
                "guard": "wfirma",
                "error": "PZ rows not found. pz_rows.json and XLSX Rows sheet both missing.",
                "code": "WFIRMA_NO_ROWS",
            },
        )
    return rows


def _resolve_supplier(audit: dict) -> tuple[str, str, list[str]]:
    """
    Resolve the supplier name for wFirma export using a priority chain.

    Returns (supplier_name, source_label, risk_flags).
    Never returns blank — always falls back to UNKNOWN_SUPPLIER with a risk flag.

    Priority (first non-empty wins):
      1. customs_declaration.exporter_name  (canonical, from SAD)
      2. verification.invoice_exporter_name (parsed from invoice PDFs)
      3. exporter_check.invoice_exporter    (alternate invoice check)
      4. zc429.exporter_name / .exporter    (raw ZC429 fields)
      5. learning_traces[0].supplier_key    (last-known supplier from learning system)
      6. fallback                           "UNKNOWN_SUPPLIER" + risk flag
    """
    risks: list[str] = []
    cd       = audit.get("customs_declaration") or {}
    ver      = audit.get("verification") or {}
    expchk   = audit.get("exporter_check") or {}
    zc429    = audit.get("zc429") or {}
    traces   = audit.get("learning_traces") or []

    candidates = [
        ("customs_declaration.exporter_name", cd.get("exporter_name")),
        ("verification.invoice_exporter_name", ver.get("invoice_exporter_name")),
        ("exporter_check.invoice_exporter",   expchk.get("invoice_exporter")),
        ("zc429.exporter_name",               zc429.get("exporter_name")),
        ("zc429.exporter",                    zc429.get("exporter")),
    ]
    for source, value in candidates:
        if value and str(value).strip():
            return str(value).strip(), source, risks

    # Soft fallback: learning system supplier key (humanise estrella_jewels_llp → "Estrella Jewels LLP")
    if traces:
        key = (traces[0] or {}).get("supplier_key") or ""
        if key:
            humanised = " ".join(w.capitalize() if w not in ("llp","ltd","pvt") else w.upper()
                                 for w in key.replace("_"," ").split())
            risks.append("supplier_from_learning_only")
            return humanised, "learning_traces[0].supplier_key", risks

    risks.append("supplier_missing_for_wfirma")
    return "UNKNOWN_SUPPLIER", "fallback", risks


def _build_uwagi(row: dict, awb: str, mrn: str, nbp_rate: float, settlement_mode: str = "standard") -> str:
    """Build Uwagi cell content for one PZ row."""
    invoice_no = row.get("invoice_no", "")
    duty_pln   = row.get("allocated_duty_pln", 0.0)

    parts = []
    if invoice_no:
        parts.append(f"Invoice {invoice_no}")
    if awb:
        parts.append(f"AWB {awb}")
    if mrn:
        parts.append(f"MRN {mrn}")
    parts.append("A00 allocated in cost")
    if nbp_rate:
        parts.append(f"NBP {_fmt_pln(nbp_rate)}")
    if settlement_mode == "art33a":
        parts.append("Art.33a")

    return "; ".join(parts)


def _build_wfirma_rows(rows: List[dict], audit: dict) -> List[dict]:
    """
    Transform PZ engine rows into wFirma-ready row dicts.
    Returns list of dicts with keys matching wFirma PZ columns.
    """
    cd   = audit.get("customs_declaration") or {}
    awb  = audit.get("tracking_no", "") or ""
    mrn  = cd.get("mrn", "") or audit.get("inputs", {}).get("zc429_mrn", "") or ""
    nbp  = float(cd.get("nbp_rate", 0) or audit.get("inputs", {}).get("nbp_rate_usd", 0) or 0)
    mode = audit.get("settlement_mode", "standard")

    out = []
    for row in rows:
        # Nazwa towaru: prefer Polish description, fall back to English
        nazwa = (row.get("pl_desc") or row.get("description_en") or
                 row.get("item_type") or "Towar").strip()

        qty     = float(row.get("quantity", 1) or 1)
        unit    = str(row.get("unit", "szt.") or "szt.")
        # Normalise: wFirma uses "szt." for PCS/PIECE
        if unit.upper() in ("PCS", "PIECE", "PIECES", "PC", "ITEM", "ITEMS"):
            unit = "szt."
        elif unit.upper() in ("PAIR", "PAIRS", "PR"):
            unit = "para"
        elif unit.upper() == "SET":
            unit = "zest."

        unit_netto  = float(row.get("unit_netto_pln", 0) or 0)
        line_netto  = float(row.get("line_netto_pln", 0) or 0)
        line_brutto = float(row.get("line_brutto_pln", 0) or 0)

        out.append({
            "nazwa_towaru":   nazwa,
            "ilosc":          qty,
            "jm":             unit,
            "cena_netto":     unit_netto,
            "wartosc_netto":  line_netto,
            "wartosc_brutto": line_brutto,
            "uwagi":          _build_uwagi(row, awb, mrn, nbp, mode),
            # extended fields (not in clipboard, but in JSON)
            "_invoice_no":    row.get("invoice_no", ""),
            "_description_en": row.get("description_en", ""),
            "_pl_desc":       row.get("pl_desc", "") or row.get("description_en", ""),
            "_allocated_duty_pln": row.get("allocated_duty_pln", 0),
        })
    return out


def _build_clipboard_text(wfirma_rows: List[dict]) -> str:
    """
    Build tab-separated clipboard string.
    Columns: Nazwa towaru | Ilość | J.m. | Cena netto | Wartość netto | Wartość brutto | Uwagi
    Numeric values use Polish format (space thousands, comma decimal).
    """
    lines = []
    header = "\t".join([
        "Nazwa towaru", "Ilość", "J.m.",
        "Cena netto", "Wartość netto", "Wartość brutto", "Uwagi",
    ])
    lines.append(header)

    for r in wfirma_rows:
        qty_str = (
            str(int(r["ilosc"])) if r["ilosc"] == int(r["ilosc"])
            else _fmt_pln(r["ilosc"]).replace(" ", "")       # remove thousands sep from qty
        )
        line = "\t".join([
            r["nazwa_towaru"],
            qty_str,
            r["jm"],
            _fmt_pln(r["cena_netto"]),
            _fmt_pln(r["wartosc_netto"]),
            _fmt_pln(r["wartosc_brutto"]),
            r["uwagi"],
        ])
        lines.append(line)

    return "\n".join(lines)


def _patch_audit_wfirma(output_dir: Path, mode: str, row_count: int) -> None:
    """Write wfirma_export block into audit.json."""
    audit_path = output_dir / "audit.json"
    if not audit_path.exists():
        return
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        existing = audit.get("wfirma_export") or {}
        audit["wfirma_export"] = {
            "clipboard_generated": existing.get("clipboard_generated") or (mode == "clipboard"),
            "json_generated":      existing.get("json_generated")      or (mode == "json"),
            "last_generated_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
            "row_count":           row_count,
            "mode":                mode,
        }
        if mode == "clipboard":
            audit["wfirma_export"]["clipboard_generated"] = True
        elif mode == "json":
            audit["wfirma_export"]["json_generated"] = True
        write_json_atomic(audit_path, audit)
    except Exception as e:
        log.warning("wfirma_export audit patch failed: %s", e)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/shipment/{batch_id}/wfirma/clipboard", dependencies=[_auth])
async def wfirma_clipboard(batch_id: str) -> JSONResponse:
    """
    Mode 1 — Clipboard Export.

    Returns tab-separated PZ rows ready for copy/paste into wFirma PZ table.
    Guard: SAD must exist + PZ must be generated.
    """
    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)
    _guard_wfirma_export(audit)

    rows        = _build_rows(output_dir, audit)
    wfirma_rows = _build_wfirma_rows(rows, audit)
    clipboard   = _build_clipboard_text(wfirma_rows)

    # Audit
    _patch_audit_wfirma(output_dir, "clipboard", len(wfirma_rows))
    tl.log_event(
        output_dir / "audit.json",
        EV_WFIRMA_CLIPBOARD,
        "dashboard",
        "user",
        detail={"batch_id": batch_id, "row_count": len(wfirma_rows)},
    )

    # Resolve supplier + doc_no for warnings (preview should also surface these)
    supplier, supplier_source, risk_flags = _resolve_supplier(audit)
    doc_no_curr = (audit.get("doc_no") or "").strip()
    requires_doc_no = not doc_no_curr
    warnings: list[str] = []
    if requires_doc_no:
        warnings.append("PZ document number not set — confirm via dashboard before final wFirma save")
    if supplier == "UNKNOWN_SUPPLIER":
        warnings.append("Supplier name could not be resolved from invoice or SAD — fill manually in wFirma")
    elif "supplier_from_learning_only" in risk_flags:
        warnings.append(f"Supplier '{supplier}' inferred from learning history only — verify against invoice")

    log.info("[%s] wFirma clipboard generated: %d rows", batch_id, len(wfirma_rows))

    return JSONResponse({
        "batch_id":        batch_id,
        "row_count":       len(wfirma_rows),
        "mode":            "clipboard",
        "supplier":        supplier,
        "supplier_source": supplier_source,
        "doc_no":          doc_no_curr,
        "requires_doc_no": requires_doc_no,
        "risk_flags":      risk_flags,
        "warnings":        warnings,
        "clipboard":       clipboard,
        "rows":            [
            {
                "nazwa_towaru":   r["nazwa_towaru"],
                "ilosc":          r["ilosc"],
                "jm":             r["jm"],
                "cena_netto":     round(r["cena_netto"], 2),
                "wartosc_netto":  round(r["wartosc_netto"], 2),
                "wartosc_brutto": round(r["wartosc_brutto"], 2),
                "uwagi":          r["uwagi"],
            }
            for r in wfirma_rows
        ],
    })


@router.get("/shipment/{batch_id}/wfirma/json", dependencies=[_auth])
async def wfirma_json(batch_id: str) -> FileResponse:
    """
    Mode 1B — PZ_READY.json.

    Generates and returns PZ_READY.json, saved to outputs/{batch_id}/PZ_READY.json.
    Guard: SAD must exist + PZ must be generated.
    """
    output_dir = get_output_dir(batch_id)
    audit      = _read_audit(output_dir)
    _guard_wfirma_export(audit)

    rows        = _build_rows(output_dir, audit)
    wfirma_rows = _build_wfirma_rows(rows, audit)

    cd       = audit.get("customs_declaration") or {}
    totals   = audit.get("totals") or {}
    awb      = audit.get("tracking_no", "") or ""
    mrn      = cd.get("mrn", "") or audit.get("inputs", {}).get("zc429_mrn", "") or ""
    doc_no   = (audit.get("doc_no") or "").strip()
    importer = cd.get("importer_name", "") or "ESTRELLA JEWELS SP. Z O.O. SP. K."
    doc_date = cd.get("clearance_date", "") or audit.get("timestamp", "")[:10]

    # ── Supplier resolution (priority chain + fallback) ──────────────────────
    supplier, supplier_source, risk_flags = _resolve_supplier(audit)

    # ── Warnings (do not block preview/copy/JSON) ────────────────────────────
    warnings: list[str] = []
    requires_doc_no = not doc_no
    if requires_doc_no:
        warnings.append("PZ document number not set — confirm via dashboard before final wFirma save")
    if supplier == "UNKNOWN_SUPPLIER":
        warnings.append("Supplier name could not be resolved from invoice or SAD — fill manually in wFirma")
    elif "supplier_from_learning_only" in risk_flags:
        warnings.append(f"Supplier '{supplier}' inferred from learning history only — verify against invoice")

    payload: Dict[str, Any] = {
        "batch_id":      batch_id,
        "awb":           awb,
        "mrn":           mrn,
        "doc_no":        doc_no,
        "supplier":      supplier,
        "supplier_source": supplier_source,
        "importer":      importer,
        "document_date": doc_date,
        "currency":      "PLN",
        "source":        "SAD/PZ engine",
        "requires_doc_no": requires_doc_no,
        "risk_flags":    risk_flags,
        "warnings":      warnings,
        "rows": [
            {
                "name":             r["nazwa_towaru"],
                "quantity":         r["ilosc"],
                "unit":             r["jm"],
                "net_price_pln":    round(r["cena_netto"], 2),
                "net_value_pln":    round(r["wartosc_netto"], 2),
                "gross_value_pln":  round(r["wartosc_brutto"], 2),
                "invoice_no":       r["_invoice_no"],
                "original_description": r["_description_en"],
                "polish_description":   r["_pl_desc"],
                "notes":            r["uwagi"],
            }
            for r in wfirma_rows
        ],
        "totals": {
            "net":      round(float(totals.get("net") or 0), 2),
            "gross":    round(float(totals.get("gross") or 0), 2),
            "duty_a00": round(float(cd.get("duty_a00_pln") or 0), 2),
        },
    }

    # Save to disk
    out_path = output_dir / "PZ_READY.json"
    write_json_atomic(out_path, payload)

    # Audit
    _patch_audit_wfirma(output_dir, "json", len(wfirma_rows))
    tl.log_event(
        output_dir / "audit.json",
        EV_WFIRMA_JSON,
        "dashboard",
        "user",
        detail={"batch_id": batch_id, "row_count": len(wfirma_rows), "path": str(out_path)},
    )

    log.info("[%s] PZ_READY.json → %s (%d rows)", batch_id, out_path, len(wfirma_rows))

    return FileResponse(
        path=str(out_path),
        media_type="application/json",
        filename=f"PZ_READY_{batch_id}.json",
    )

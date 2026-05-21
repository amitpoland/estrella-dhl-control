"""
routes_dhl_clearance.py — DHL Customs Clearance API endpoints.

GET  /api/v1/dhl/scan-inbox                          — scan Zoho Mail for DHL customs emails
POST /api/v1/dhl/match-and-handle                    — match AWB to batch + run clearance handler
GET  /api/v1/dhl/clearance-status/{batch_id}         — get clearance status for a batch
POST /api/v1/dhl/generate-description/{batch_id}     — manually trigger Polish description
GET  /api/v1/dhl/download/{filename}                 — download generated PDF
POST /api/v1/dhl/generate-customs-package/{batch_id} — generate full customs description package (PDF + SAD JSON)
GET  /api/v1/dhl/sad-ready/{batch_id}                — return SAD-ready JSON data for a batch
POST /api/v1/dhl/approve/{batch_id}                  — approve the customs description (stores name + timestamp)

All endpoints require API key auth.
None of these endpoints send email — they only prepare packages.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..core.guards import guard_dhl_requires_email
from ..services.clearance_path_alias import (
    is_agency_clearance,
    is_dhl_self_clearance,
)
from ..pipelines.dhl import receive_dhl_email as _pipeline_dhl_email
from ..core import timeline as tl
from ..config.email_routing import (
    DHL_TO,
    DHL_DSK_SOURCE,
    INTERNAL_CC,
    format_to,
    format_cc,
    is_dsk_source,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/dhl", tags=["dhl-clearance"])
_auth = Depends(require_api_key)

# ── Engine path setup ─────────────────────────────────────────────────────────
_engine_dir = str(settings.engine_dir)
if _engine_dir not in sys.path:
    sys.path.insert(0, _engine_dir)

# ── Output directories ────────────────────────────────────────────────────────
_DSK_OUTPUT_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "estrellajewels" / "storage" / "dsk_outputs"
    if os.name == "nt"
    else Path.home() / "Library" / "Application Support"
    / "estrellajewels" / "storage" / "dsk_outputs"
)
if not _DSK_OUTPUT_DIR.parent.exists():
    _DSK_OUTPUT_DIR = settings.storage_root / "dsk_outputs"
_DSK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_POLISH_DESC_DIR = settings.storage_root / "polish_descriptions"
_POLISH_DESC_DIR.mkdir(parents=True, exist_ok=True)

_SAD_READY_DIR = settings.storage_root / "sad_ready"
_SAD_READY_DIR.mkdir(parents=True, exist_ok=True)

# ── Zoho Mail constants ───────────────────────────────────────────────────────
_ZOHO_ACCOUNT_ID   = "2261204000000002002"
_ZOHO_INBOX_FOLDER = "2261204000000002014"


# ── Schemas ───────────────────────────────────────────────────────────────────

class MatchAndHandleRequest(BaseModel):
    awb:                str
    dhl_ticket:         Optional[str] = None
    message_id:         Optional[str] = None
    thread_id:          Optional[str] = None
    subject:            Optional[str] = None
    value_usd_override: Optional[float] = None


class ClearanceStatusResponse(BaseModel):
    batch_id:         str
    clearance_status: Optional[str] = None
    clearance_action: Optional[str] = None
    dhl_ticket:       Optional[str] = None
    awb:              Optional[str] = None
    updated_at:       Optional[str] = None
    found:            bool


class ScanInboxResult(BaseModel):
    scanned:      int
    matched:      int
    emails:       List[Dict[str, Any]]
    scan_method:  str
    scanned_at:   str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_audit(batch_id: str) -> Optional[dict]:
    """Load audit.json for a batch_id from storage."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _write_audit(batch_id: str, audit: dict) -> None:
    """Write audit.json back to disk atomically."""
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / batch_id / "audit.json"
        if p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
            return


def _find_generated_file(filename: str) -> Optional[Path]:
    """Search DSK output dir, Polish descriptions dir, and SAD-ready dir for a named file."""
    for search_dir in (_DSK_OUTPUT_DIR, _POLISH_DESC_DIR, _SAD_READY_DIR):
        candidate = search_dir / filename
        if candidate.exists():
            return candidate
    return None


def _inject_rows_from_xlsx(batch_id: str, audit: dict) -> dict:
    """
    Read the PZ calculation XLSX for a batch and inject invoice rows into the audit dict.

    This enriches the audit dict with structured line-item data so that
    customs_description_engine can build a proper goods table even when
    audit.json only has aggregate invoice_totals.

    Returns the audit dict (modified in-place, also returned for chaining).
    """
    # Already has rows — nothing to do
    if audit.get("rows") or audit.get("invoices"):
        return audit

    # Find the XLSX in the batch output folder
    batch_dir: Optional[Path] = None
    for sub in ("outputs", "working"):
        candidate = settings.storage_root / sub / batch_id
        if candidate.is_dir():
            batch_dir = candidate
            break

    if batch_dir is None:
        return audit

    # Find any *_calc.xlsx file in the batch dir
    xlsx_files = list(batch_dir.glob("*_calc.xlsx")) or list(batch_dir.glob("*.xlsx"))
    if not xlsx_files:
        return audit

    xlsx_path = xlsx_files[0]
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(xlsx_path), data_only=True)

        # The "Rows" sheet has columns:
        # Lp, Invoice No, English Name, Polish Name, Qty, Unit USD, Line USD, ..., Item Type, ...
        if "Rows" not in wb.sheetnames:
            return audit

        ws = wb["Rows"]
        rows_iter = ws.iter_rows(values_only=True)
        header = [str(c).strip() if c is not None else "" for c in next(rows_iter)]

        def _col(name: str) -> Optional[int]:
            try:
                return header.index(name)
            except ValueError:
                return None

        c_inv  = _col("Invoice No")
        c_desc = _col("English Name")
        c_qty  = _col("Qty")
        c_usd  = _col("Unit USD")
        c_tot  = _col("Line USD")
        c_type = _col("Item Type")

        if c_inv is None or c_desc is None:
            return audit

        injected: list[dict] = []
        for row in rows_iter:
            if not any(row):
                continue
            inv_no  = str(row[c_inv]).strip()  if c_inv  is not None and row[c_inv]  is not None else ""
            desc    = str(row[c_desc]).strip() if c_desc is not None and row[c_desc] is not None else ""
            qty     = float(row[c_qty])  if c_qty  is not None and row[c_qty]  is not None else 0.0
            unit_p  = float(row[c_usd])  if c_usd  is not None and row[c_usd]  is not None else 0.0
            line_t  = float(row[c_tot])  if c_tot  is not None and row[c_tot]  is not None else 0.0
            itype   = str(row[c_type]).strip().upper() if c_type is not None and row[c_type] is not None else ""
            if not desc or not inv_no:
                continue
            injected.append({
                "invoice_number": inv_no,
                "description":    desc,
                "item_type":      itype,
                "quantity":       qty,
                "unit_price":     unit_p,
                "line_total":     line_t,
            })

        if injected:
            audit["rows"] = injected
            log.debug("Injected %d invoice rows from XLSX into audit for description generation", len(injected))

    except Exception as _xe:
        log.warning("_inject_rows_from_xlsx: could not read XLSX %s — %s", xlsx_path, _xe)

    return audit


# ── PR-206: DB-first row injection ─────────────────────────────────────────
#
# Source priority for batch["rows"] (engine input):
#   1. invoice_lines from documents.db for THIS batch_id        (primary)
#   2. invoice_lines from documents.db for batches sharing the
#      same AWB                                                  (cross-batch
#                                                                 union fallback)
#   3. XLSX Rows sheet (existing _inject_rows_from_xlsx)         (legacy)
#   4. nothing — guard fires below, generation refused
#
# Synthetic per-piece averaging (_build_synthetic_lines_from_totals in the
# engine) is intentionally unreachable in production after this PR: when
# none of the four sources produce rows, the route refuses generation
# with HTTP 422 lines_missing_for_description.
#
# Pure / read-only.  No wFirma / PZ / DHL email / proforma posting writes.


def _row_uom_from_description(desc: str) -> str:
    """Derive UoM from the leading token of an EJL invoice line description.

    Real lines start with "PCS, " or "PRS, " — we honour that prefix.
    Falls back to PCS when the prefix is absent or unrecognised.
    """
    if not desc:
        return "PCS"
    head = desc.strip().split(",", 1)[0].strip().upper()
    if head in ("PCS", "PRS"):
        return head
    return "PCS"


def _project_invoice_line_to_engine_row(line: dict) -> dict:
    """Map a documents.db invoice_lines row to the engine row shape used
    by customs_description_engine._extract_invoices / process_batch_items.

    Permissive aliases on the engine side:
      description: description | desc | name
      quantity:    quantity | qty | line_qty
      unit_price:  unit_price | rate | price
      line_total:  line_total | amount | total
      hsn_code:    hsn_code | hs_code | hsn
      uom:         unit | uom (default 'PCS')
    """
    desc      = str(line.get("description") or "")
    unit_p    = float(line.get("unit_price") or line.get("rate_usd") or 0.0)
    line_tot  = float(line.get("total_value") or line.get("amount_usd") or 0.0)
    hsn       = str(line.get("hsn_code") or line.get("hs_code") or "")
    return {
        "invoice_number": str(line.get("invoice_no") or ""),
        "line_position":  int(line.get("line_position") or 0),
        "product_code":   str(line.get("product_code") or ""),
        "description":    desc,
        "item_type":      "",            # engine derives from description
        "quantity":       float(line.get("quantity") or 0.0),
        "unit_price":     unit_p,
        "line_total":     line_tot,
        "hsn_code":       hsn,
        "currency":       str(line.get("currency") or "USD"),
        "uom":            _row_uom_from_description(desc),
    }


def _is_placeholder_invoice_line(row: dict) -> bool:
    """Detect invoice_intake_parser's fallback placeholder row.

    The intake parser falls back to a single zero-valued placeholder row
    when it can't extract real line items (e.g. for the global_jewellery
    invoice template whose line layout differs from the EJL template the
    extractor was tuned for). These rows have qty=0, total_value=0, and a
    description starting with "(placeholder". Projecting them into the
    reconciler poisons the FOB sum to 0 even when aggregate invoice_totals
    were extracted correctly.

    Returns True only for the unambiguous placeholder signature.
    """
    if not isinstance(row, dict):
        return False
    qty   = float(row.get("quantity")    or 0.0)
    total = float(row.get("total_value") or row.get("amount_usd") or 0.0)
    desc  = str(row.get("description") or "")
    return qty == 0.0 and total == 0.0 and desc.lstrip().startswith("(placeholder")


def _inject_rows_from_db_invoice_lines(batch_id: str, audit: dict) -> dict:
    """Project documents.db invoice_lines into ``audit["rows"]``.

    Primary path:
      - Read invoice_lines for ``batch_id``.
      - If empty AND the audit carries an AWB, union invoice_lines from
        all batches sharing the same AWB (dedup by
        (invoice_no, line_position, product_code)).

    Placeholder filter:
      - Intake-time zero-valued placeholder rows (qty=0, total_value=0,
        description starts with "(placeholder") are dropped here. Their
        presence in the DB is a record-of-existence marker, not real
        per-line data — projecting them would crash the reconciler.

    Idempotent: if ``audit`` already has ``rows`` or ``invoices``, no-op.
    """
    if audit.get("rows") or audit.get("invoices"):
        return audit

    try:
        from app.services import document_db as _ddb
        rows = _ddb.get_invoice_lines_for_batch(batch_id) or []
        rows = [r for r in rows if not _is_placeholder_invoice_line(r)]

        if not rows:
            # Cross-batch fallback: same AWB, different batch_id.
            awb = (
                audit.get("dhl_awb")
                or audit.get("awb")
                or (audit.get("batch_meta") or {}).get("awb")
                or audit.get("tracking_no")
                or ""
            )
            if awb:
                seen: set = set()
                docs = _ddb.get_documents_by_awb(awb, "purchase_invoice")
                # Iterate distinct batch_ids referenced by these documents.
                visited_batches: set = set()
                for d in docs:
                    bid = str(d.get("batch_id") or "")
                    if not bid or bid == batch_id or bid in visited_batches:
                        continue
                    visited_batches.add(bid)
                    for ln in (_ddb.get_invoice_lines_for_batch(bid) or []):
                        # Same placeholder filter as primary path.
                        if _is_placeholder_invoice_line(ln):
                            continue
                        key = (
                            str(ln.get("invoice_no") or ""),
                            int(ln.get("line_position") or 0),
                            str(ln.get("product_code") or ""),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(ln)

        if not rows:
            return audit

        projected = [_project_invoice_line_to_engine_row(r) for r in rows]
        audit["rows"]            = projected
        audit["_rows_source"]    = "db_invoice_lines"
        audit["_rows_row_count"] = len(projected)
        log.info(
            "[%s] _inject_rows_from_db_invoice_lines: projected %d rows from "
            "invoice_lines (this batch + shared-AWB union)",
            batch_id, len(projected),
        )
    except Exception as exc:
        log.warning(
            "[%s] _inject_rows_from_db_invoice_lines: failed (non-fatal): %s",
            batch_id, exc,
        )
    return audit


def _synthesize_rows_from_invoice_aggregates(batch_id: str, audit: dict) -> dict:
    """Last-resort grouped-row synthesizer.

    When the DB and XLSX paths produce no per-line rows but the engine
    successfully parsed aggregate invoice_totals (fob_usd, freight_usd,
    insurance_usd, product_counts_by_unit) — as happens for the
    `global_jewellery` template whose per-line layout differs from the
    EJL template the intake extractor was tuned for — synthesize one
    grouped row per (invoice, unit_type) so the reconciler can verify
    against the same aggregate the engine produced.

    Properties:
      - Pure read of files in source/invoices/ via engine parse_invoice
      - Re-uses the C27.1 PDF-magic quarantine helper to skip non-PDF
        masqueraders
      - One grouped row per (invoice_file, PCS|PRS) — preserves the
        unit breakdown the operator's customs description needs
      - Row totals sum exactly to the engine's parsed FOB per file
      - Idempotent: no-op if audit already has rows or no aggregates

    NEVER touches CIF formula, customs threshold logic, SAD/ZC429 gate,
    wFirma/PZ write paths.
    """
    if audit.get("rows") or audit.get("invoices"):
        return audit

    inv_totals = audit.get("invoice_totals") or {}
    declared_fob = 0.0
    try:
        declared_fob = float(inv_totals.get("total_fob_usd") or 0.0)
    except Exception:
        declared_fob = 0.0
    if declared_fob <= 0:
        return audit  # no aggregate to synthesize from

    # Resolve batch dir using the same pattern as other helpers in this file
    inv_dir: Optional[Path] = None
    for sub in ("outputs", "working"):
        candidate = settings.storage_root / sub / batch_id / "source" / "invoices"
        if candidate.is_dir():
            inv_dir = candidate
            break
    if inv_dir is None:
        return audit

    inv_pdfs_all = sorted(inv_dir.glob("*.pdf"))
    # Re-use the C27.1 magic-header quarantine — never feed a non-PDF
    # to the engine's parser (it would crash or emit empty results that
    # poison the synthesized rows).
    try:
        # Import locally to avoid circular reference; helper lives in
        # routes_dashboard for the recheck loops.
        from .routes_dashboard import _partition_valid_pdfs as _ppvp
        inv_pdfs, _bad = _ppvp(inv_pdfs_all)
    except Exception:
        inv_pdfs, _bad = inv_pdfs_all, []

    if not inv_pdfs:
        return audit

    # Ensure engine importable
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    synthesized: List[dict] = []
    try:
        from pz_import_processor import parse_invoice as _pi  # noqa: PLC0415
    except Exception as exc:
        log.warning("[%s] synthesize_rows: engine import failed: %s", batch_id, exc)
        return audit

    line_pos = 0
    for pdf in inv_pdfs:
        try:
            inv = _pi(str(pdf), [])
        except Exception:
            inv = None
        if not isinstance(inv, dict):
            continue
        fob = float(inv.get("fob_usd") or 0.0)
        if fob <= 0:
            continue
        invoice_no = (
            str(inv.get("invoice_no") or "").strip()
            or pdf.stem
        )
        counts_by_unit = inv.get("product_counts_by_unit") or {}
        # Sum qty across PCS / PRS groups; if engine returned empty dict,
        # fall back to a single PCS group inferred from total_units or
        # qty=1 sentinel so the row still carries SOMETHING.
        pcs_qty = 0
        prs_qty = 0
        try:
            pcs_qty = int(round(sum(float(v or 0) for v in
                                    (counts_by_unit.get("PCS") or {}).values())))
            prs_qty = int(round(sum(float(v or 0) for v in
                                    (counts_by_unit.get("PRS") or {}).values())))
        except Exception:
            pcs_qty = prs_qty = 0

        # Fallback: scan the engine's raw text for the GLOBAL/IEC summary
        # block layout ``PCS 183.0`` / ``PRS 62.0``. Pure read of engine
        # output — no parser arithmetic, no customs logic.
        if pcs_qty == 0 and prs_qty == 0:
            import re as _re_local
            raw = str(inv.get("_raw_text") or "")
            m_pcs = _re_local.search(r"\bPCS\s+(\d+(?:\.\d+)?)\b", raw)
            m_prs = _re_local.search(r"\bPRS\s+(\d+(?:\.\d+)?)\b", raw)
            if m_pcs:
                try: pcs_qty = int(round(float(m_pcs.group(1))))
                except Exception: pass
            if m_prs:
                try: prs_qty = int(round(float(m_prs.group(1))))
                except Exception: pass

        total_qty = pcs_qty + prs_qty
        if total_qty == 0:
            # Fallback: try engine top-level qty
            try:
                total_qty = int(round(float(
                    inv.get("total_pcs") or inv.get("total_units") or 0)))
            except Exception:
                total_qty = 0
            pcs_qty = total_qty
            prs_qty = 0
            if total_qty == 0:
                # Nothing to split — emit one grouped row with qty=1
                # so the reconciler sees a row sum = fob.
                pcs_qty = 1
                total_qty = 1

        # Allocate FOB proportionally to qty per unit so the sum is
        # exact. Rounding residue placed on the last row.
        groups: list[tuple[str, int]] = []
        if pcs_qty > 0:
            groups.append(("PCS", pcs_qty))
        if prs_qty > 0:
            groups.append(("PRS", prs_qty))

        alloc_remaining = round(fob, 2)
        for i, (unit, qty) in enumerate(groups):
            if i == len(groups) - 1:
                line_total = round(alloc_remaining, 2)
            else:
                # Proportional allocation by qty.
                line_total = round(fob * (qty / total_qty), 2)
                alloc_remaining = round(alloc_remaining - line_total, 2)
            line_pos += 1
            unit_price = round(line_total / qty, 6) if qty > 0 else 0.0
            synthesized.append({
                "invoice_number": invoice_no,
                "line_position":  line_pos,
                "product_code":   f"{invoice_no}-AGG-{unit}",
                "description":    (
                    f"{unit}, grouped invoice aggregate from "
                    f"{inv.get('invoice_format') or 'invoice'} ({pdf.name})"
                ),
                "item_type":      "",
                "quantity":       float(qty),
                "unit_price":     unit_price,
                "line_total":     line_total,
                "hsn_code":       "",
                "currency":       "USD",
                "uom":            unit,
            })

    if not synthesized:
        return audit

    audit["rows"]            = synthesized
    audit["_rows_source"]    = "synthesized_from_invoice_aggregates"
    audit["_rows_row_count"] = len(synthesized)
    log.info(
        "[%s] _synthesize_rows_from_invoice_aggregates: produced %d grouped "
        "row(s) summing to USD %.2f across %d invoice file(s)",
        batch_id, len(synthesized),
        sum(r["line_total"] for r in synthesized),
        len({r["invoice_number"] for r in synthesized}),
    )
    return audit


def _inject_rows_from_sources(batch_id: str, audit: dict) -> dict:
    """Chain row sources in priority order.

    Order:
      1. _inject_rows_from_db_invoice_lines        (DB primary, placeholder-filtered)
      2. _inject_rows_from_xlsx                    (legacy XLSX Rows sheet)
      3. _synthesize_rows_from_invoice_aggregates  (engine-aggregate grouped fallback)

    Idempotent on subsequent calls. Caller MUST apply the lines-missing
    guard (HTTP 422) when the chain still produces no rows.
    """
    audit = _inject_rows_from_db_invoice_lines(batch_id, audit)
    audit = _inject_rows_from_xlsx(batch_id, audit)
    audit = _synthesize_rows_from_invoice_aggregates(batch_id, audit)
    return audit


def _reconcile_rows_with_audit_totals(audit: dict) -> dict:
    """Validate ``audit["rows"]`` (or projected invoices) against the
    aggregate totals declared in ``audit["invoice_totals"]``.

    Pure / deterministic / side-effect free.  Returns a dict::

        {
          "ok":            bool,
          "warnings":      list[str],
          "details": {
            "row_count":              int,
            "row_invoice_numbers":    list[str],
            "row_fob_sum":            float,
            "row_qty_total":          int,
            "audit_invoice_names":    list[str],
            "audit_fob_total":        float,
            "audit_qty_total":        int,
            "fob_drift_usd":          float,
            "qty_drift_units":        int,
            "missing_in_rows":        list[str],
            "extra_in_rows":          list[str],
          }
        }

    The caller decides whether ``ok=False`` is a hard block (route returns
    HTTP 422) or just a flag.  All checks are tolerant of empty totals
    (drift defaults to 0 when the audit totals are absent / zero).
    """
    import re as _re

    def _safe_float(x):
        try: return float(x or 0)
        except Exception: return 0.0

    rows = audit.get("rows") or []
    invoice_totals = audit.get("invoice_totals") or {}
    audit_names    = audit.get("invoice_names") or []

    # Row-side aggregates
    row_inv_set: set = set()
    row_fob_sum = 0.0
    row_qty_tot = 0
    for r in rows:
        inv = str(r.get("invoice_number") or r.get("invoice_no") or "").strip()
        if inv:
            row_inv_set.add(inv)
        row_fob_sum += _safe_float(r.get("line_total")
                                    or r.get("amount")
                                    or r.get("total"))
        try:
            row_qty_tot += int(round(_safe_float(r.get("quantity")
                                                  or r.get("qty"))))
        except Exception:
            pass

    # Audit-side aggregates
    audit_fob = _safe_float(invoice_totals.get("total_fob_usd"))
    audit_units = invoice_totals.get("total_units")
    try:
        audit_qty = int(round(_safe_float(audit_units))) if audit_units is not None else 0
    except Exception:
        audit_qty = 0

    # Extract invoice-number tokens from both sides.
    #
    # invoice_names entries look like one of:
    #     "180 Invoice EJL-26-27-180-16-05-26.pdf"   ← leading numeric token
    #     "Invoice EJL-26-27-180-16-05-26.pdf"       ← no leading number
    # Row-side invoice_number is the canonical "EJL/26-27/180" form.
    #
    # We try (in order): EJL-NN-NN-NNN  pattern → leading "^\d+" →
    # last "\d{3,}" digit run in the stem.  Same rule for both sides
    # so the resulting sets compare apples to apples.
    def _token(s: str) -> Optional[str]:
        if not s:
            return None
        # Normalise separators
        norm = s.replace("\\", "/").replace("_", "-")
        # EJL[-/]NN[-/]NN[-/](NNN…)
        m = _re.search(r"EJL[\-/]\d+[\-/]\d+[\-/](\d+)", norm, _re.IGNORECASE)
        if m:
            return m.group(1)
        stem = Path(norm).stem
        m = _re.match(r"^(\d+)\b", stem)
        if m:
            return m.group(1)
        m = _re.search(r"(\d{3,})", stem)
        return m.group(1) if m else None

    audit_tokens = {t for t in (_token(n) for n in audit_names) if t}
    row_tokens   = {t for t in (_token(i) for i in row_inv_set)  if t}

    missing_in_rows = sorted(audit_tokens - row_tokens) if audit_tokens else []
    extra_in_rows   = sorted(row_tokens - audit_tokens) if audit_tokens else []

    fob_drift = round(row_fob_sum - audit_fob, 2) if audit_fob else 0.0
    qty_drift = (row_qty_tot - audit_qty) if audit_qty else 0

    warnings: list[str] = []
    # Tolerances: ±$1 FOB, ±0 units, exact invoice set.
    if audit_fob and abs(fob_drift) > 1.00:
        warnings.append(
            f"fob_total_drift: row sum USD {row_fob_sum:,.2f} differs from "
            f"audit total USD {audit_fob:,.2f} by USD {fob_drift:+,.2f}"
        )
    if audit_qty and qty_drift != 0:
        warnings.append(
            f"qty_total_drift: row qty {row_qty_tot} differs from "
            f"audit total {audit_qty} by {qty_drift:+d}"
        )
    if missing_in_rows:
        warnings.append(
            "invoices_missing_in_rows: "
            + ", ".join(missing_in_rows)
            + " present in invoice_names but not in projected rows"
        )

    return {
        "ok":       not warnings,
        "warnings": warnings,
        "details":  {
            "row_count":           len(rows),
            "row_invoice_numbers": sorted(row_inv_set),
            "row_fob_sum":         round(row_fob_sum, 2),
            "row_qty_total":       row_qty_tot,
            "audit_invoice_names": list(audit_names),
            "audit_fob_total":     round(audit_fob, 2),
            "audit_qty_total":     audit_qty,
            "fob_drift_usd":       fob_drift,
            "qty_drift_units":     qty_drift,
            "missing_in_rows":     missing_in_rows,
            "extra_in_rows":       extra_in_rows,
        },
    }


def _find_sad_json(batch_id: str, awb: Optional[str] = None) -> Optional[Path]:
    """Find the SAD_READY JSON file for a batch."""
    # Search by awb-derived filename pattern or scan the sad_ready dir
    search_dirs = [
        _SAD_READY_DIR,
        _POLISH_DESC_DIR,
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix == ".json" and f.name.startswith("SAD_READY_"):
                # If awb is known, match on it
                if awb:
                    awb_clean = re.sub(r"\s+", "", awb)
                    if awb_clean in f.name:
                        return f
                else:
                    return f  # Return first found
    return None


# ── New request schemas ───────────────────────────────────────────────────────

class GenerateCustomsPackageRequest(BaseModel):
    awb:          str
    dhl_email_id: Optional[str] = None
    date_override: Optional[str] = None


class ApproveDescriptionRequest(BaseModel):
    approved_by: str


class MarkEmailReceivedRequest(BaseModel):
    sender:       Optional[str] = "odprawacelna@dhl.com"
    subject:      Optional[str] = None
    ticket:       Optional[str] = None
    request_type: Optional[str] = "unknown"   # polish_description | dsk_broker | unknown
    received_at:  Optional[str] = None        # ISO datetime string; defaults to now
    note:         Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/scan-inbox", dependencies=[_auth])
async def scan_dhl_inbox(
    limit:      int = 50,
    account_id: str = _ZOHO_ACCOUNT_ID,
    folder_id:  str = _ZOHO_INBOX_FOLDER,
    batch_id:   Optional[str] = None,
    awb:        Optional[str] = None,
    refresh:    bool = False,
) -> Dict[str, Any]:
    """
    Scan Zoho Mail inbox for shipment correspondence.

    When `batch_id` is provided, the AWB is auto-resolved from that batch's
    audit.json and an AWB-targeted search is performed. Otherwise, the most
    recent `limit` messages are scanned.

    Matching is permissive: subject, body, attachments, and forwarded content
    are all checked across DHL/agency/Ganther/internal/FedEx senders.

    Optional: `awb` — explicit AWB to search for (overrides batch_id resolution).
    """
    from dhl_email_monitor import scan_for_dhl_customs_emails
    from ..services.zoho_auth import (
        has_zoho_credentials,
        get_valid_access_token,
        ZohoAuthError,
    )

    # Routing mode — see settings.email_scan_mode for full semantics
    scan_mode = (settings.email_scan_mode or "auto").lower()
    api_allowed = scan_mode != "bridge_only"
    bridge_allowed = scan_mode != "api_only"
    creds_present = has_zoho_credentials() and api_allowed
    # Override account ID from settings if configured
    if settings.zoho_mail_account_id:
        account_id = settings.zoho_mail_account_id

    # ── Resolve AWB from batch_id if not given ────────────────────────────────
    target_awb = (awb or "").strip() or None
    if batch_id and not target_awb:
        for sub in ("outputs", "working"):
            _ap = settings.storage_root / sub / batch_id / "audit.json"
            if _ap.exists():
                try:
                    import json as _json
                    a = _json.loads(_ap.read_text(encoding="utf-8"))
                    target_awb = (
                        a.get("awb")
                        or a.get("tracking_no")
                        or (a.get("batch_meta") or {}).get("awb")
                    )
                except Exception:
                    pass
                break

    # Bridge dispatcher — used by bridge_only mode and as auto-fallback
    def _dispatch_to_bridge(reason: str) -> Dict[str, Any]:
        from ..services.ai_bridge import create_task as _bridge_create_task
        from ..services.email_search_context import build_email_search_context

        # Pull the audit so we can extract invoice numbers / DHL ticket / MRN
        ctx_audit: Dict[str, Any] = {}
        if batch_id:
            for sub in ("outputs", "working"):
                _ap = settings.storage_root / sub / batch_id / "audit.json"
                if _ap.exists():
                    try:
                        import json as _json
                        ctx_audit = _json.loads(_ap.read_text(encoding="utf-8"))
                    except Exception:
                        ctx_audit = {}
                    break
        # If awb wasn't resolved earlier, seed audit minimally so the helper
        # at least knows the AWB
        if target_awb and not ctx_audit.get("awb"):
            ctx_audit.setdefault("awb", target_awb)

        ctx = build_email_search_context(ctx_audit)

        # Connector pins come from the helper (canonical Estrella mailbox)
        PREFERRED_CONN_ID = "mcp__620999a3"

        task = _bridge_create_task(
            batch_id=batch_id or "_global_",
            task_type="email_scan",
            payload={
                "awb":             ctx["awb"] or target_awb or "",
                "invoice_numbers": ctx["invoice_numbers"],
                "dhl_ticket":      ctx["dhl_ticket"],
                "mrn":             ctx["mrn"],
                "search_terms":    ctx["search_terms"],
                "known_senders":   ctx["known_senders"],
                "known_domains":   ctx["known_domains"],
                "batch_id":        batch_id or "",
                "account_id":      account_id,
                "folder_id":       folder_id,
                # ── Mailbox identity (single account; multiple identities) ───
                "target_account_id":            ctx["target_account_id"],
                "target_mailbox":               ctx["target_mailbox"],
                "related_identities":           ctx["related_identities"],
                "preferred_mcp_connector_hint": PREFERRED_CONN_ID,
                "instructions": (
                    f"STEP 0: Verify mailbox binding — call getMailAccounts on "
                    f"connector starting with {PREFERRED_CONN_ID}. Confirm "
                    f"accountId == {ctx['target_account_id']} and "
                    f"primaryEmailAddress == {ctx['target_mailbox']}. "
                    "If mismatch, return connector_mismatch=true and stop. "
                    "related_identities[] are aliases of the same mailbox — "
                    "match To/Cc against any of them as in-scope.\n"
                    "Then: search by AWB first, then invoice numbers, then "
                    "sender domain combos. Inspect attachment filenames and "
                    "forwarded chains. Do NOT stop at the first 0-result step. "
                    "If matched=0 but search_terms had >1 entry, mark "
                    "search_unreliable=true."
                ),
            },
            note=f"Bridge scan for AWB {target_awb or '(none)'} — reason: {reason}.",
        )
        return {
            "scanned":     0,
            "matched":     0,
            "emails":      [],
            "scan_method": "ai_bridge_pending",
            "search_mode": "awb_targeted" if target_awb else "broad_recent",
            "query_used":  "ai_bridge:email_scan",
            "awb_used":    target_awb,
            "search_context": {
                "awb":              ctx["awb"],
                "invoice_numbers":  ctx["invoice_numbers"],
                "dhl_ticket":       ctx["dhl_ticket"],
                "mrn":              ctx["mrn"],
                "search_terms":     ctx["search_terms"],
                "search_terms_count": len(ctx["search_terms"]),
            },
            "scanned_at":  datetime.now(timezone.utc).isoformat(),
            "bridge_task": {
                "task_id":     task["task_id"],
                "task_type":   "email_scan",
                "result_file": task.get("result_file"),
                "message": (
                    "Email scan dispatched to AI Bridge. Open the AI Bridge tab "
                    "to execute the task in Cowork, then import the result."
                ),
                "reason": reason,
            },
        }

    # ── Path 0: stored email intelligence cache (skip Cowork if we have data)─
    # Verified prior scans are reusable. Unreliable cached results still let
    # the operator re-run via the dashboard's explicit button.
    # Skip cache when refresh=true (operator forced re-scan).
    try:
        if refresh:
            raise LookupError("operator-forced refresh")
        from ..services.email_intelligence_store import find_existing_email_context
        # Only check when we have an audit context to look up against
        ctx_audit_for_cache: Dict[str, Any] = {}
        if batch_id:
            for sub in ("outputs", "working"):
                _ap = settings.storage_root / sub / batch_id / "audit.json"
                if _ap.exists():
                    try:
                        import json as _json
                        ctx_audit_for_cache = _json.loads(_ap.read_text(encoding="utf-8"))
                    except Exception:
                        ctx_audit_for_cache = {}
                    break
        if target_awb and not ctx_audit_for_cache.get("awb"):
            ctx_audit_for_cache["awb"] = target_awb

        cached = find_existing_email_context(ctx_audit_for_cache) if ctx_audit_for_cache else None
        # Use cache if it's a verified record (not unreliable, matched > 0 or
        # explicitly verified-with-zero). Operator can force re-run from UI.
        if cached and cached.get("matched", 0) > 0 and not cached.get("search_unreliable"):
            log.info(
                "[scan-inbox] using cached email intelligence for AWB %s (matched=%d, scanned %s)",
                cached.get("awb"), cached.get("matched"), cached.get("last_scanned_at", ""),
            )
            return {
                "scanned":     cached.get("matched", 0),
                "matched":     cached.get("matched", 0),
                "emails":      cached.get("emails") or [],
                "scan_method": "email_intelligence_cache",
                "search_mode": "awb_targeted" if target_awb else "broad_recent",
                "query_used":  f"cache:by_awb:{cached.get('awb')}",
                "awb_used":    cached.get("awb"),
                "scanned_at":  datetime.now(timezone.utc).isoformat(),
                "email_scan_results": cached,
                "search_context": {
                    "awb":               cached.get("awb"),
                    "invoice_numbers":   cached.get("invoice_numbers", []),
                    "dhl_ticket":        cached.get("dhl_ticket"),
                    "mrn":               cached.get("mrn"),
                    "search_terms":      [],
                    "search_terms_count": 0,
                },
                "cached": {
                    "source":          cached.get("source"),
                    "last_scanned_at": cached.get("last_scanned_at"),
                    "connector_used":  cached.get("connector_used"),
                    "linked_batches":  cached.get("linked_batches", []),
                },
            }
    except Exception as exc:
        log.debug("[scan-inbox] email intelligence cache lookup failed (non-fatal): %s", exc)

    # ── Path A: native backend scan (when Zoho creds are configured) ──────────
    if creds_present:
        try:
            result = scan_for_dhl_customs_emails(
                zoho_account_id=account_id,
                zoho_folder_id=folder_id,
                limit=limit,
                target_awb=target_awb,
                api_base=settings.zoho_mail_api_base,
                token_provider=get_valid_access_token,
            )
        except ZohoAuthError as exc:
            # Auth failure — auto-fallback to bridge in 'auto' mode; hard 401 in 'api_only'
            log.warning("Zoho auth error during scan: %s", exc)
            if bridge_allowed:
                log.info("Falling back to AI Bridge after auth_error")
                return _dispatch_to_bridge(reason="zoho_auth_error")
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            log.error("DHL inbox scan failed: %s", exc)
            if bridge_allowed:
                log.info("Falling back to AI Bridge after API error")
                return _dispatch_to_bridge(reason="zoho_api_error")
            raise HTTPException(status_code=500, detail=f"Inbox scan error: {exc}") from exc

        # Auto-fallback to bridge if scan returned auth_error path silently
        if result.get("scan_method") == "auth_error" and bridge_allowed:
            log.info("Scan returned auth_error — auto-falling back to bridge")
            return _dispatch_to_bridge(reason="zoho_auth_error_silent")
    # ── Path B: AI Bridge (forced or no creds) ────────────────────────────────
    elif bridge_allowed:
        reason = "bridge_only_mode" if scan_mode == "bridge_only" else "no_credentials"
        try:
            return _dispatch_to_bridge(reason=reason)
        except Exception as exc:
            log.error("AI Bridge task creation failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Bridge task error: {exc}") from exc
    else:
        # api_only mode but no creds — clean error, no bridge fallback
        raise HTTPException(
            status_code=503,
            detail=(
                "Email scan unavailable: EMAIL_SCAN_MODE=api_only but no Zoho "
                "credentials configured. Set ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN "
                "or change EMAIL_SCAN_MODE to 'auto' or 'bridge_only'."
            ),
        )

    scanned_at = datetime.now(timezone.utc).isoformat()

    emails      = result.get("emails", [])
    scanned     = result.get("scanned", 0)
    matched     = result.get("matched", 0)
    scan_method = result.get("scan_method", "no_credentials")
    search_mode = result.get("search_mode", "broad_recent")
    query_used  = result.get("query_used", "")

    # ── Timeline logging — only when something actually matched ───────────────
    if matched > 0 and batch_id and "/" not in batch_id and ".." not in batch_id:
        for sub in ("outputs", "working"):
            _ap = settings.storage_root / sub / batch_id / "audit.json"
            if _ap.exists():
                emails_preview = [
                    {
                        "subject":        e.get("subject") or e.get("raw_subject", ""),
                        "from":           e.get("from", ""),
                        "received_at":    e.get("received_at", ""),
                        "ticket":         e.get("dhl_ticket", ""),
                        "awb":            e.get("awb", ""),
                        "matched_fields": e.get("matched_fields", []),
                        "detected_type":  e.get("detected_type", ""),
                    }
                    for e in emails[:3]
                ]
                tl.log_event(
                    _ap,
                    tl.EV_DHL_INBOX_SCANNED,
                    trigger_source="dashboard",
                    actor="admin",
                    detail={
                        "scanned":        scanned,
                        "matched":        matched,
                        "scan_method":    scan_method,
                        "search_mode":    search_mode,
                        "query_used":     query_used,
                        "awb_used":       target_awb or "",
                        "emails_preview": emails_preview,
                    },
                )
                log.info(
                    "DHL inbox scan logged to timeline: batch=%s scanned=%d matched=%d "
                    "method=%s mode=%s awb=%s",
                    batch_id, scanned, matched, scan_method, search_mode, target_awb,
                )
                break

    log.info(
        "DHL inbox scan: scanned=%d matched=%d method=%s mode=%s awb=%s",
        scanned, matched, scan_method, search_mode, target_awb,
    )

    return {
        "scanned":     scanned,
        "matched":     matched,
        "emails":      emails,
        "scan_method": scan_method,
        "search_mode": search_mode,
        "query_used":  query_used,
        "awb_used":    target_awb,
        "scanned_at":  scanned_at,
    }


@router.post("/match-and-handle", dependencies=[_auth])
async def match_and_handle(body: MatchAndHandleRequest) -> Dict[str, Any]:
    """
    Match an AWB number to a batch and run the DHL clearance handler.

    Steps:
    1. Search all audit.json files for the AWB
    2. Determine clearance route (DHL self-clear vs broker)
    3. Generate DSK (broker) or Polish description (DHL direct)
    4. Return reply package (does NOT send email)
    """
    from dhl_email_monitor import match_awb_to_batch
    from dhl_clearance_handler import handle_dhl_customs_email

    # Build synthetic dhl_email dict from request
    dhl_email = {
        "message_id":  body.message_id or "",
        "thread_id":   body.thread_id or "",
        "subject":     body.subject or f"[{body.dhl_ticket or ''}] - Agencja Celna DHL - przesyłka numer: {body.awb}",
        "from":        "odprawacelna@dhl.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "dhl_ticket":  body.dhl_ticket or "",
        "awb":         body.awb,
    }

    # 1. Find matching batch
    batch = match_awb_to_batch(
        awb=body.awb,
        storage_root=str(settings.storage_root),
    )
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"No batch found matching AWB {body.awb}. "
                   "Ensure the batch has been processed and audit.json contains the AWB.",
        )

    # 2. Apply value override if provided
    if body.value_usd_override is not None:
        # Inject into batch for handler routing
        batch.setdefault("result", {}).setdefault("verification", {})[
            "invoice_cif_total_usd"
        ] = body.value_usd_override

    log.info("DHL match-and-handle: awb=%s batch_path=%s", body.awb, batch.get("_audit_path"))

    # 3. Run handler
    try:
        result = handle_dhl_customs_email(
            dhl_email=dhl_email,
            batch=batch,
            storage_root=str(settings.storage_root),
            dsk_output_dir=str(_DSK_OUTPUT_DIR),
        )
    except Exception as exc:
        log.error("DHL clearance handler error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Clearance handler error: {exc}") from exc

    # ── DSK source tracking (automated path) ─────────────────────────────────
    # If the incoming email originated from DHL_DSK_SOURCE, record dsk_received.
    _dhl_sender = dhl_email.get("from", "")
    _batch_audit_path = Path(batch.get("_audit_path", ""))
    if _dhl_sender and is_dsk_source(_dhl_sender) and _batch_audit_path.exists():
        try:
            from ..utils.io import write_json_atomic as _wja
            _ba = json.loads(_batch_audit_path.read_text(encoding="utf-8"))
            _ba["dsk_received"]    = True
            _ba["dsk_source"]      = _dhl_sender
            _ba["dsk_received_at"] = datetime.now(timezone.utc).isoformat()
            _wja(_batch_audit_path, _ba)
            log.info("DSK source email auto-detected in match-and-handle: awb=%s sender=%s",
                     body.awb, _dhl_sender)
        except Exception as _dsk_exc:
            log.warning("DSK source tracking (non-fatal): %s", _dsk_exc)

    # Timeline: DHL email received
    if _batch_audit_path.exists():
        try:
            await _pipeline_dhl_email(
                batch,
                _batch_audit_path,
                ticket=body.dhl_ticket or "",
                awb=body.awb,
                actor="dhl_monitor",
            )
        except Exception as _tl_exc:
            log.warning("DHL timeline event failed (non-fatal): %s", _tl_exc)

    # 4. Enrich reply_package attachments with download URLs (strip local paths)
    reply_pkg = result.get("reply_package", {})
    attachments_safe = []
    for att in (reply_pkg.get("attachments") or []):
        fn = Path(att.get("path", "")).name
        attachments_safe.append({
            "label":        att.get("label", ""),
            "filename":     fn,
            "download_url": f"{settings.fastapi_public_url}/api/v1/dhl/download/{fn}" if fn else None,
        })

    reply_validation = result.get("reply_validation") or {}
    decision_reason  = result.get("decision_reason") or {}

    return {
        "action":            result["action"],
        "clearance_status":  result["clearance_status"],
        "awb":               body.awb,
        "batch_found":       True,
        "batch_path":        batch.get("_audit_path", ""),
        "dsk":               _safe_dsk(result.get("dsk")),
        "polish_description": _safe_polish(result.get("polish_description")),
        "decision_reason":   decision_reason,
        "reply_validation":  reply_validation,
        "reply_package": {
            "to":          format_to(DHL_TO),   # always use centralized config
            "cc":          format_cc(INTERNAL_CC),
            "subject":     reply_pkg.get("subject", ""),
            "thread_id":   reply_pkg.get("thread_id", ""),
            "message_id":  reply_pkg.get("message_id", ""),
            "body_pl":     reply_pkg.get("body_pl", ""),
            "body_en":     reply_pkg.get("body_en", ""),
            "attachments": attachments_safe,
            "blocked":     reply_validation.get("blocked", False),
        },
    }


@router.get("/clearance-status/{batch_id}", response_model=ClearanceStatusResponse, dependencies=[_auth])
async def get_clearance_status(batch_id: str) -> ClearanceStatusResponse:
    """Get the current clearance status for a batch."""
    audit = _load_audit(batch_id)
    if audit is None:
        return ClearanceStatusResponse(
            batch_id=batch_id,
            found=False,
        )

    return ClearanceStatusResponse(
        batch_id=batch_id,
        clearance_status=audit.get("clearance_status"),
        clearance_action=audit.get("clearance_action"),
        dhl_ticket=audit.get("dhl_ticket"),
        awb=audit.get("dhl_awb") or audit.get("awb"),
        updated_at=audit.get("clearance_updated_at"),
        found=True,
    )


@router.post("/generate-description/{batch_id}", dependencies=[_auth])
async def generate_description(
    batch_id: str,
    awb: str = "",
    date_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Manually trigger Polish customs description generation for a batch.
    Now calls generate_customs_description_package() which also generates the SAD-ready JSON.

    Parameters
    ----------
    batch_id      : batch ID to generate for
    awb           : AWB number (optional; taken from audit if not provided)
    date_override : date string YYYY-MM-DD (optional; defaults to today)
    """
    from customs_description_engine import generate_customs_description_package

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    # ── Guard: DHL email check — RELAXED for external_agency_clearance ────────
    # For high-value shipments routed through Agencja Celna Spedycja, the
    # operational order is: generate description IMMEDIATELY → send agency
    # package → THEN handle DHL customs email when it arrives. Blocking the
    # description on dhl_email_received reverses the real workflow.
    _decision = audit.get("clearance_decision") or {}
    _is_agency_path = is_agency_clearance(_decision.get("clearance_path"))
    if not _is_agency_path:
        try:
            guard_dhl_requires_email(audit)
        except HTTPException as _ge:
            raise HTTPException(
                status_code=422,
                detail={
                    "guard":   "generate_description_requires_dhl_email",
                    "error":   "Polish description generation requires a DHL customs email or admin override.",
                    "code":    "dhl_email_not_received",
                    "hint":    "Use 'Scan DHL Inbox' first, or mark the email received via the DHL Pre-check panel.",
                },
            ) from _ge

    # ── Guard: CIF must be non-zero ───────────────────────────────────────────
    _inv_totals  = audit.get("invoice_totals") or {}
    _cif_inv     = float(_inv_totals.get("total_cif_usd") or 0)
    _cif_ver     = float((audit.get("verification") or {}).get("invoice_cif_total_usd") or 0)
    if _cif_inv == 0.0 and _cif_ver == 0.0:
        raise HTTPException(
            status_code=422,
            detail={
                "guard":  "cif_zero",
                "error":  "Invoice CIF value is 0.00 — invoice values were not parsed correctly. "
                          "Generating a Polish customs description with zero value would produce an invalid document.",
                "code":   "cif_zero",
                "hint":   "Re-process the batch with valid invoice PDFs before generating the customs description.",
            },
        )

    # Resolve AWB — check all locations where it may be stored
    resolved_awb = (
        awb or
        audit.get("dhl_awb") or
        audit.get("awb") or
        (audit.get("batch_meta") or {}).get("awb") or
        audit.get("tracking_no") or    # dashboard-upload shipments store AWB here
        ""
    )
    if not resolved_awb:
        raise HTTPException(
            status_code=422,
            detail="AWB not provided and not found in batch audit.json.",
        )

    # PR-206: Enrich audit with invoice rows.  Priority chain is
    # DB invoice_lines (this batch + shared-AWB union) → legacy XLSX
    # Rows sheet → (no rows → 422 below).  Synthetic per-piece averaging
    # in the engine is intentionally unreachable: when neither the DB
    # nor the XLSX has rows, the operator gets a clear manual-review
    # error instead of a misleading PDF.
    audit = _inject_rows_from_sources(batch_id, audit)

    if not audit.get("rows") and not audit.get("invoices"):
        raise HTTPException(
            status_code=422,
            detail={
                "guard":  "lines_missing_for_description",
                "error":  "No per-line invoice data found in DB invoice_lines, "
                          "XLSX Rows sheet, or audit.json. Generating from "
                          "aggregate totals would average per-piece values "
                          "and lose per-line HSN/karat/stone detail.",
                "code":   "lines_missing_for_description",
                "hint":   "Re-process the batch with valid invoice PDFs or "
                          "attach the PZ calculation XLSX.",
            },
        )

    # PR-206: Reconcile projected rows against aggregate audit totals.
    # Hard block when the row set is materially inconsistent — missing
    # invoices, FOB drift > $1, or qty mismatch — so an obviously-wrong
    # PDF is never produced.
    _recon = _reconcile_rows_with_audit_totals(audit)
    if not _recon["ok"]:
        raise HTTPException(
            status_code=422,
            detail={
                "guard":    "rows_audit_reconciliation_failed",
                "error":    "Projected per-line rows do not reconcile with "
                            "the aggregate invoice_totals declared in "
                            "audit.json. Generating a customs document with "
                            "this mismatch would be unsafe.",
                "code":     "rows_audit_reconciliation_failed",
                "warnings": _recon["warnings"],
                "details":  _recon["details"],
                "hint":     "Re-process the batch (Reparse all) or attach a "
                            "fresh PZ calculation XLSX, then retry.",
            },
        )

    try:
        pkg = generate_customs_description_package(
            batch         = audit,
            awb           = resolved_awb,
            output_dir    = str(_POLISH_DESC_DIR),
            date_override = date_override,
        )
    except Exception as exc:
        log.error("Customs description generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pdf_result = pkg.get("pdf") or {}
    if not pdf_result.get("generated"):
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {pdf_result.get('error', 'unknown error')}",
        )

    # Update audit
    audit["clearance_status"]     = "polish_description_generated"
    audit["polish_desc_filename"] = pdf_result.get("filename")
    audit["polish_desc_path"]     = pdf_result.get("output_path")
    json_result = pkg.get("json") or {}
    if json_result.get("generated"):
        audit["sad_ready_filename"] = json_result.get("filename")
        audit["sad_ready_path"]     = json_result.get("output_path")
    _write_audit(batch_id, audit)

    # Log timeline event
    for sub in ("outputs", "working"):
        _ap = settings.storage_root / sub / batch_id / "audit.json"
        if _ap.exists():
            tl.log_event(_ap, tl.EV_DESCRIPTION_READY, "dashboard", "admin",
                         detail={"filename": pdf_result.get("filename", "")})
            break

    # ── Auto-trigger agency package build for external_agency_clearance ───────
    # When CIF > threshold (agency path), Polish description → agency package
    # is the standard, deterministic next step. Build immediately so the operator
    # doesn't have to click again. Skip if already built.
    auto_agency_built = False
    auto_agency_error = None
    if _is_agency_path and not (audit.get("agency_reply_package") or {}).get("status"):
        try:
            from ..services.agency_email_builder import build_agency_package
            from ..services.email_service       import queue_email
            _pkg = build_agency_package(audit, batch_id)
            _missing_files = [
                a["label"] for a in _pkg.get("attachments", [])
                if not Path(a.get("path", "")).exists()
            ] + (_pkg.get("missing") or [])
            if _missing_files:
                auto_agency_error = {"missing": _missing_files,
                                     "hint": "regenerate missing files before agency build"}
            elif not (_pkg.get("to") or "").strip():
                auto_agency_error = {"error": "no recipients"}
            else:
                _body_text = f"{_pkg['body_pl']}\n\n---\n\n{_pkg['body_en']}".strip()
                _body_html = ("<div style='font-family:sans-serif'>"
                              f"<pre style='white-space:pre-wrap'>{_pkg['body_pl']}</pre><hr/>"
                              f"<pre style='white-space:pre-wrap'>{_pkg['body_en']}</pre></div>")
                _email_id = queue_email(
                    to          = _pkg["to"],
                    subject     = _pkg["subject"],
                    body_html   = _body_html,
                    body_text   = _body_text,
                    batch_id    = batch_id,
                    cc          = _pkg.get("cc", ""),
                    from_address= _pkg.get("from_address", ""),
                    email_type  = _pkg.get("email_type", "agency"),
                    # Pass attachments at queue time — integrity guard must fire
                    # on the synchronous SMTP attempt before audit.json is written.
                    attachments = _pkg.get("attachments", []),
                )
                from ..utils.io import write_json_atomic
                from datetime import datetime as _dt, timezone as _tz
                audit["agency_reply_package"] = {
                    "to":          _pkg["to"],
                    "to_list":     _pkg.get("to_list", []),
                    "cc":          _pkg.get("cc", ""),
                    "cc_list":     _pkg.get("cc_list", []),
                    "subject":     _pkg["subject"],
                    "body_pl":     _pkg["body_pl"],
                    "body_en":     _pkg["body_en"],
                    "attachments": _pkg["attachments"],
                    "email_id":    _email_id,
                    "status":      "queued",
                    "queued_at":   _dt.now(_tz.utc).isoformat(),
                    "source":      "auto_after_polish_desc",
                }
                _write_audit(batch_id, audit)
                auto_agency_built = True
                # Log timeline event
                for sub in ("outputs", "working"):
                    _ap = settings.storage_root / sub / batch_id / "audit.json"
                    if _ap.exists():
                        tl.log_event(_ap, "agency_package_auto_built", "system", "auto",
                                     detail={"email_id": _email_id, "trigger": "polish_desc_generated"})
                        break
                log.info("[auto-agency] package built and queued for batch %s (email_id=%s)",
                         batch_id, _email_id)
        except Exception as exc:
            log.warning("[auto-agency] auto-build failed for batch %s: %s", batch_id, exc)
            auto_agency_error = {"error": str(exc)}

    fn = pdf_result.get("filename", "")
    return {
        "ok":              True,
        "batch_id":        batch_id,
        "action":          "polish_description_generated",
        "status":          "generated",
        "generated":       True,
        "filename":        fn,
        "download_url":    f"{settings.fastapi_public_url}/api/v1/dhl/download/{fn}" if fn else None,
        "items_described": pdf_result.get("items_described"),
        "sad_json_filename": json_result.get("filename"),
        "auto_agency_built": auto_agency_built,
        "auto_agency_error": auto_agency_error,
        "errors":          [],
        "warnings":        [],
    }


@router.get("/download/{filename}", dependencies=[_auth])
async def download_dhl_file(filename: str) -> FileResponse:
    """
    Download a DHL clearance-related file (PDF or SAD-ready JSON).

    Searches in:
    - DSK output directory
    - Polish descriptions directory
    - SAD-ready directory
    """
    # Sanitize filename — no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".json"):
        raise HTTPException(status_code=400, detail="Only PDF and JSON files are served here.")

    found = _find_generated_file(filename)
    if found is None:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    media_type = "application/pdf" if ext == ".pdf" else "application/json"
    return FileResponse(
        path=str(found),
        media_type=media_type,
        filename=filename,
    )


# ── New endpoints: customs description package, SAD-ready JSON, approval ──────

@router.post("/generate-customs-package/{batch_id}", dependencies=[_auth])
async def generate_customs_package(
    batch_id: str,
    body: GenerateCustomsPackageRequest,
) -> Dict[str, Any]:
    """
    Generate the full customs description package (Polish PDF + SAD-ready JSON) for a batch.

    Body: {"awb": "...", "dhl_email_id": "...", "date_override": "YYYY-MM-DD"}
    Returns combined result with download URLs for both files.
    """
    from customs_description_engine import generate_customs_description_package

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    awb = (
        body.awb or
        audit.get("dhl_awb") or
        audit.get("awb") or
        (audit.get("batch_meta") or {}).get("awb") or
        audit.get("tracking_no") or
        ""
    )
    if not awb:
        raise HTTPException(status_code=422, detail="AWB not provided and not found in audit.json.")

    # PR-206: DB-first row injection + lines-missing guard + reconciliation.
    audit = _inject_rows_from_sources(batch_id, audit)

    if not audit.get("rows") and not audit.get("invoices"):
        raise HTTPException(
            status_code=422,
            detail={
                "guard":  "lines_missing_for_description",
                "error":  "No per-line invoice data found in DB invoice_lines, "
                          "XLSX Rows sheet, or audit.json.",
                "code":   "lines_missing_for_description",
                "hint":   "Re-process the batch with valid invoice PDFs or "
                          "attach the PZ calculation XLSX.",
            },
        )

    _recon = _reconcile_rows_with_audit_totals(audit)
    if not _recon["ok"]:
        raise HTTPException(
            status_code=422,
            detail={
                "guard":    "rows_audit_reconciliation_failed",
                "error":    "Projected rows do not reconcile with aggregate "
                            "invoice_totals declared in audit.json.",
                "code":     "rows_audit_reconciliation_failed",
                "warnings": _recon["warnings"],
                "details":  _recon["details"],
                "hint":     "Re-process the batch or attach a fresh PZ XLSX.",
            },
        )

    try:
        pkg = generate_customs_description_package(
            batch          = audit,
            awb            = awb,
            output_dir     = str(_POLISH_DESC_DIR),
            dhl_email_id   = body.dhl_email_id or "",
            date_override  = body.date_override,
        )
    except Exception as exc:
        log.error("generate_customs_package error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pdf_result  = pkg.get("pdf") or {}
    json_result = pkg.get("json") or {}

    if not pdf_result.get("generated"):
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {pdf_result.get('error', 'unknown')}",
        )
    if not json_result.get("generated"):
        raise HTTPException(
            status_code=500,
            detail=f"SAD JSON generation failed: {json_result.get('error', 'unknown')}",
        )

    # Update audit.json
    audit["clearance_status"]            = "polish_description_generated"
    audit["polish_desc_filename"]        = pdf_result.get("filename")
    audit["polish_desc_path"]            = pdf_result.get("output_path")
    audit["sad_ready_filename"]          = json_result.get("filename")
    audit["sad_ready_path"]              = json_result.get("output_path")
    audit["customs_package_generated_at"] = pkg.get("audit", {}).get("generated_at")
    audit["customs_pdf_hash"]            = pdf_result.get("pdf_hash")
    audit["customs_json_hash"]           = json_result.get("json_hash")
    _write_audit(batch_id, audit)

    pdf_fn  = pdf_result.get("filename", "")
    json_fn = json_result.get("filename", "")

    # Read classification_summary and error_flags from the generated SAD JSON
    classification_summary: Optional[dict] = None
    error_flags: Optional[dict] = None
    sad_output_path = json_result.get("output_path") or audit.get("sad_ready_path")
    if sad_output_path:
        try:
            sad_data = json.loads(Path(sad_output_path).read_text(encoding="utf-8"))
            classification_summary = sad_data.get("classification_summary")
            error_flags            = sad_data.get("error_flags")
        except Exception:
            pass

    return {
        "generated":             True,
        "batch_id":              batch_id,
        "awb":                   re.sub(r"\s+", "", awb),
        "classification_summary": classification_summary,
        "error_flags":           error_flags,
        "pdf": {
            "filename":        pdf_fn,
            "items_described": pdf_result.get("items_described"),
            "pdf_hash":        pdf_result.get("pdf_hash"),
            "download_url":    f"{settings.fastapi_public_url}/api/v1/dhl/download/{pdf_fn}" if pdf_fn else None,
        },
        "json": {
            "filename":    json_fn,
            "total_lines": json_result.get("total_lines"),
            "json_hash":   json_result.get("json_hash"),
            "download_url": f"{settings.fastapi_public_url}/api/v1/dhl/download/{json_fn}" if json_fn else None,
        },
        "audit": pkg.get("audit"),
    }


@router.get("/sad-ready/{batch_id}", dependencies=[_auth])
async def get_sad_ready(batch_id: str) -> Dict[str, Any]:
    """
    Return the parsed SAD-ready JSON data for a batch.

    This returns the structured data, not a raw file download.
    Use /download/{filename} for the raw JSON file.
    """
    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    sad_path = audit.get("sad_ready_path")
    awb      = audit.get("dhl_awb") or audit.get("awb") or ""

    # Try the stored path first
    if sad_path:
        p = Path(sad_path)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Could not parse SAD JSON: {exc}") from exc

    # Fallback: search by AWB
    found = _find_sad_json(batch_id, awb=awb)
    if found:
        try:
            return json.loads(found.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not parse SAD JSON: {exc}") from exc

    raise HTTPException(
        status_code=404,
        detail=f"SAD-ready JSON not found for batch {batch_id}. "
               "Run POST /api/v1/dhl/generate-customs-package/{batch_id} first.",
    )


def _update_batch_reply_delivery(batch_id: str, delivery_status: str, error: Optional[str] = None) -> bool:
    """
    Propagate email delivery confirmation back to the batch audit.json.
    Called by mark_email_sent (admin endpoint) after MCP confirms send/fail.

    delivery_status: "sent" | "failed"
    Returns True if the audit was found and updated.
    """
    audit = _load_audit(batch_id)
    if audit is None:
        log.warning("_update_batch_reply_delivery: batch %s not found", batch_id)
        return False

    now = datetime.now(timezone.utc).isoformat()
    audit["dhl_reply_status"] = delivery_status          # sent | failed
    audit["email_status"]     = delivery_status
    if delivery_status == "sent":
        audit["clearance_status"]    = "reply_sent"
        audit["dhl_reply_sent_at"]   = now
    else:
        audit["clearance_status"]    = "reply_failed"
        audit["dhl_reply_failed_at"] = now
        audit["dhl_reply_error"]     = error or "unknown"

    audit["clearance_updated_at"] = now
    _write_audit(batch_id, audit)
    log.info("DHL reply delivery propagated: batch=%s status=%s", batch_id, delivery_status)
    return True


@router.get("/reply-status/{batch_id}", dependencies=[_auth])
async def get_reply_status(batch_id: str) -> Dict[str, Any]:
    """
    Return current DHL reply delivery status for a batch.
    Cross-references audit.json (batch state) with email_queue.json (queue state).
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..services import email_service as _email_svc

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    email_id = audit.get("dhl_reply_email_id")

    # Cross-reference the email queue entry
    queue_entry = None
    if email_id:
        for e in _email_svc.get_all_emails(limit=200):
            if e.get("id") == email_id:
                queue_entry = e
                break

    # Determine live status — queue entry is authoritative over audit if available
    live_status = audit.get("dhl_reply_status") or "not_queued"
    if queue_entry:
        q_status = queue_entry.get("status", "pending")
        # Propagate to audit if queue shows a terminal state we haven't recorded yet
        if q_status == "sent" and live_status == "queued":
            _update_batch_reply_delivery(batch_id, "sent")
            live_status = "sent"
        elif q_status == "failed" and live_status not in ("failed",):
            _update_batch_reply_delivery(batch_id, "failed", queue_entry.get("error"))
            live_status = "failed"

    return {
        "batch_id":          batch_id,
        "clearance_status":  audit.get("clearance_status"),
        "dhl_reply_status":  live_status,
        "email_status":      audit.get("email_status"),
        "email_id":          email_id,
        "queue_status":      queue_entry.get("status") if queue_entry else None,
        "queued_at":         audit.get("dhl_reply_queued_at"),
        "sent_at":           queue_entry.get("sent_at") if queue_entry else audit.get("dhl_reply_sent_at"),
        "failed_at":         audit.get("dhl_reply_failed_at"),
        "error":             queue_entry.get("error") if queue_entry else audit.get("dhl_reply_error"),
        "to":                audit.get("dhl_reply_to"),
        "subject":           audit.get("dhl_reply_subject"),
    }


@router.post("/send-reply/{batch_id}", dependencies=[_auth])
async def send_dhl_reply(batch_id: str) -> Dict[str, Any]:
    """
    Queue the prepared DHL reply email for sending.

    Reads the reply package built by /email-package or /match-and-handle from audit.json,
    queues it via email_service, updates clearance_status → "reply_queued",
    and logs an EV_REPLY_APPROVED timeline event.

    Does NOT send immediately — the email goes to the JSON queue for MCP pickup.
    Admin clicks this button manually after reviewing the reply package.
    """
    from ..services import email_service

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    # Guard: DHL email must have been received first
    clr_status = audit.get("clearance_status") or ""
    if not clr_status or clr_status in ("awaiting_dhl_customs_email", "shipment_created", ""):
        raise HTTPException(
            status_code=422,
            detail={
                "guard": "send_reply_requires_email",
                "error": "Cannot send reply — no DHL customs email has been received yet.",
                "code":  "dhl_email_not_received",
            },
        )

    # Resolve reply package from audit
    reply_pkg = audit.get("reply_package") or {}
    if not reply_pkg or not reply_pkg.get("to"):
        raise HTTPException(
            status_code=422,
            detail="Reply package not found. Run 'Build Reply Package' first.",
        )

    # ── Clearance routing guard (Step A: assert reply package valid) ────────────
    # Order: (1) reply_package validity → (2) DSK exists for high-value → (3) proceed
    try:
        from ..services.clearance_decision import assert_valid_dhl_reply, resolve_dhl_action
        assert_valid_dhl_reply(audit, reply_pkg)
        _dhl_action = resolve_dhl_action(audit)
        _is_dsk_transfer = _dhl_action["action"] == "dsk_transfer"
    except ValueError as _guard_exc:
        raise HTTPException(
            status_code=422,
            detail={
                "guard":   "clearance_routing",
                "error":   str(_guard_exc),
                "code":    "invalid_dhl_flow_high_value",
                "hint":    "Generate DSK first, then use 'Build DHL Reply Package' to include it.",
            },
        ) from _guard_exc
    except ImportError:
        _is_dsk_transfer = False   # clearance_decision module unavailable — allow legacy flow

    # ── Agency flow lock: DSK file must exist on disk before DHL transfer ────
    if _is_dsk_transfer:
        _dsk_file = audit.get("dsk_filename") or ""
        _dsk_on_disk = False
        if _dsk_file:
            for _sub in ("dsk_outputs", "outputs"):
                _candidate = settings.storage_root / _sub / _dsk_file
                if not _candidate.exists():
                    _candidate = settings.storage_root / _sub / batch_id / _dsk_file
                if _candidate.exists():
                    _dsk_on_disk = True
                    break
        if not _dsk_on_disk:
            raise HTTPException(
                status_code=422,
                detail={
                    "guard":  "dsk_file_required",
                    "error":  "DSK file must be generated before sending DHL transfer notification.",
                    "code":   "dsk_missing_high_value",
                    "hint":   "Click 'Generate DSK', verify the file appears, then rebuild the reply package.",
                },
            )

    # ── Polish description physical file check (carrier path) ────────────────
    # For both paths the description is an attachment; confirm file exists on disk.
    _pd_file = audit.get("polish_desc_filename") or audit.get("polish_desc_path") or ""
    if _pd_file:
        _pd_on_disk = False
        for _pd_sub in ("polish_descriptions", "outputs", "dsk_outputs"):
            _pd_candidate = settings.storage_root / _pd_sub / _pd_file
            if not _pd_candidate.exists():
                _pd_candidate = settings.storage_root / _pd_sub / batch_id / _pd_file
            if _pd_candidate.exists():
                _pd_on_disk = True
                break
        if not _pd_on_disk:
            raise HTTPException(
                status_code=422,
                detail={
                    "guard":  "polish_desc_missing",
                    "error":  f"Polish description file not found on disk: {_pd_file}",
                    "code":   "polish_desc_missing",
                    "hint":   "Re-generate Polish Description before building the reply package.",
                },
            )

    # ── Resolve TO/CC from centralized config ────────────────────────────────
    # Always send to DHL_TO from config (overrides anything stored in reply_package).
    # Keep subject from reply_package to preserve thread continuity.
    to_addr   = format_to(DHL_TO)   # "odprawacelna@dhl.com" (or override from config)
    cc_addr   = format_cc(INTERNAL_CC)  # internal always in CC
    subject   = reply_pkg.get("subject",  "")
    body_pl   = reply_pkg.get("body_pl",  "")
    body_en   = reply_pkg.get("body_en",  "")
    thread_id = reply_pkg.get("thread_id", "")

    # ── Validation guard: TO must be present ─────────────────────────────────
    if not to_addr:
        raise HTTPException(
            status_code=422,
            detail={"guard": "missing_recipients", "error": "DHL reply has no recipients (TO is empty)."},
        )

    # Build email body (Polish first, then EN)
    full_body_text = f"{body_pl}\n\n---\n\n{body_en}".strip()
    full_body_html = (
        f"<div style='font-family:sans-serif'>"
        f"<pre style='white-space:pre-wrap'>{body_pl}</pre>"
        f"<hr/>"
        f"<pre style='white-space:pre-wrap'>{body_en}</pre>"
        f"</div>"
    )

    # Queue the email
    # Pass attachment metadata directly into the queue entry so the integrity
    # guard can fire on the synchronous SMTP attempt inside queue_email(),
    # which fires before audit.json is updated.
    _reply_attachments = list(reply_pkg.get("attachments") or [])
    try:
        email_id = email_service.queue_email(
            to          = to_addr,
            subject     = subject,
            body_html   = full_body_html,
            body_text   = full_body_text,
            batch_id    = batch_id,   # links queue entry → batch for delivery propagation
            cc          = cc_addr,
            email_type  = "dhl_reply",
            attachments = _reply_attachments,
        )
    except Exception as exc:
        log.error("send_dhl_reply: queue_email failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue email: {exc}") from exc

    # Update audit
    sent_at = datetime.now(timezone.utc).isoformat()
    audit["clearance_status"]      = "reply_queued"   # NOT reply_sent — email is queued, not delivered
    audit["clearance_updated_at"]  = sent_at
    audit["dhl_reply_email_id"]    = email_id
    audit["dhl_reply_queued_at"]   = sent_at
    audit["dhl_reply_status"]      = "queued"         # explicit delivery state: queued / sent / failed
    audit["email_status"]          = "queued"         # MCP pickup pending
    audit["dhl_reply_to"]          = to_addr
    audit["dhl_reply_cc"]          = cc_addr
    audit["dhl_reply_subject"]     = subject
    _write_audit(batch_id, audit)

    # ── Mirror into email evidence store ─────────────────────────────────────
    _awb_reply = str(audit.get("dhl_awb") or audit.get("awb") or audit.get("tracking_no") or "")
    if _awb_reply:
        try:
            from ..services import email_evidence_store as evs
            evs.link_batch(_awb_reply, batch_id)
            evs.save_message(_awb_reply, {
                "message_id":      f"op_dhl_reply:{batch_id}",
                "thread_id":       f"op_dhl_reply:{batch_id}",
                "direction":       "outgoing",
                "sender":          "import@estrellajewels.eu",
                "to":              [to_addr] if to_addr else [],
                "cc":              [cc_addr] if cc_addr else [],
                "subject":         subject,
                "body_text":       f"DHL reply queued for batch {batch_id}.",
                "timestamp":       sent_at,
                "event_type":      "our_dhl_reply",
                "delivery_status": "queued",
                "matched_identifiers": {"awb": True},
                "attachments":     [],
                "source":          "operator_send",
            }, source="operator_send")
        except Exception as _evs_exc:
            log.warning("[send_dhl_reply] evidence store write failed (non-fatal): %s", _evs_exc)

    # Timeline event — distinguish DSK transfer from standard description reply
    _tl_event = tl.EV_DSK_TRANSFER_SENT if _is_dsk_transfer else tl.EV_REPLY_APPROVED
    for sub in ("outputs", "working"):
        audit_path = settings.storage_root / sub / batch_id / "audit.json"
        if audit_path.exists():
            tl.log_event(
                audit_path,
                _tl_event,
                trigger_source="dashboard",
                actor="admin",
                detail={
                    "email_id":    email_id,
                    "to":          to_addr,
                    "cc":          cc_addr,
                    "subject":     subject,
                    "reply_type":  "dsk_transfer" if _is_dsk_transfer else "description_reply",
                },
            )
            break

    log.info("DHL reply queued: batch=%s email_id=%s to=%s cc=%s type=%s",
             batch_id, email_id, to_addr, cc_addr, "dsk_transfer" if _is_dsk_transfer else "description")

    return {
        "ok":           True,
        "batch_id":     batch_id,
        "action":       "dsk_transfer" if _is_dsk_transfer else "description_reply",
        "status":       "reply_queued",
        "queued":       True,
        "email_id":     email_id,
        "to":           to_addr,
        "cc":           cc_addr,
        "subject":      subject,
        "thread_id":    thread_id,
        "queued_at":    sent_at,
        "clearance_status": "reply_queued",
        "errors":       [],
        "warnings":     [],
        "message": (
            "Reply queued for sending. Open the email queue (Admin → Email Queue) "
            "to send via ZohoMail MCP."
        ),
    }


@router.post("/approve/{batch_id}", dependencies=[_auth])
async def approve_description(
    batch_id: str,
    body: ApproveDescriptionRequest,
) -> Dict[str, Any]:
    """
    Approve the customs description package for a batch.

    Stores approved_by (name) and approved_at (ISO8601 timestamp) in both
    the SAD-ready JSON and the batch audit.json.

    Body: {"approved_by": "amit.gupta"}
    """
    if not body.approved_by or not body.approved_by.strip():
        raise HTTPException(status_code=422, detail="approved_by must not be empty.")

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    approved_at  = datetime.now(timezone.utc).isoformat()
    approved_by  = body.approved_by.strip()

    # Update audit.json
    audit["customs_approved_by"] = approved_by
    audit["customs_approved_at"] = approved_at
    _write_audit(batch_id, audit)

    # Update SAD-ready JSON if it exists
    sad_path = audit.get("sad_ready_path")
    sad_updated = False
    if sad_path:
        p = Path(sad_path)
        if p.exists():
            try:
                sad_data = json.loads(p.read_text(encoding="utf-8"))
                sad_data["audit"]["approved_by"] = approved_by
                sad_data["audit"]["approved_at"] = approved_at
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(sad_data, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.replace(p)
                sad_updated = True
            except Exception as exc:
                log.warning("Could not update SAD JSON approval: %s", exc)

    return {
        "approved":     True,
        "batch_id":     batch_id,
        "approved_by":  approved_by,
        "approved_at":  approved_at,
        "sad_updated":  sad_updated,
    }


@router.post("/mark-email-received/{batch_id}", dependencies=[_auth])
async def mark_email_received(
    batch_id: str,
    body: Optional[MarkEmailReceivedRequest] = Body(default=None),
) -> Dict[str, Any]:
    """
    Admin manual override: mark a DHL customs email as received for this batch.

    This satisfies guard_dhl_requires_email so that Generate Description,
    Generate DSK, and Build Reply Package can proceed without waiting for
    the automatic email scan.

    Body fields are all optional — admin fills in what they know.
    """
    if body is None:
        raise HTTPException(
            status_code=422,
            detail="Request body required. Use dashboard form or send JSON fields: "
                   "{sender, subject, ticket, request_type, received_at, note} (all optional).",
        )

    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit = _load_audit(batch_id)
    if audit is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    received_at = body.received_at or datetime.now(timezone.utc).isoformat()
    _sender = body.sender or "odprawacelna@dhl.com"

    dhl_email = {
        "received":      True,
        "source":        "manual_admin",
        "sender":        _sender,
        "subject":       body.subject or "",
        "ticket":        body.ticket or "",
        "request_type":  body.request_type or "unknown",
        "received_at":   received_at,
        "note":          body.note or "",
    }
    if body.ticket:
        audit["dhl_ticket"] = body.ticket

    # ── DSK source tracking ───────────────────────────────────────────────────
    # If the email came from administracja_centralna@dhl.com (DHL_DSK_SOURCE),
    # it carries the broker (DSK) notification — record in audit.
    if is_dsk_source(_sender):
        audit["dsk_received"]    = True
        audit["dsk_source"]      = _sender
        audit["dsk_received_at"] = received_at
        log.info("DSK source email detected: batch=%s sender=%s", batch_id, _sender)

    audit["dhl_email"]       = dhl_email
    audit["clearance_status"] = "dhl_email_received"
    audit["clearance_updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_audit(batch_id, audit)

    # ── Mirror into email evidence store ─────────────────────────────────────
    _awb = str(audit.get("dhl_awb") or audit.get("awb") or audit.get("tracking_no") or "")
    if _awb:
        try:
            from ..services import email_evidence_store as evs
            evs.link_batch(_awb, batch_id)
            evs.save_message(_awb, {
                "message_id":  f"op_dhl_request:{batch_id}",
                "thread_id":   f"op_dhl_request:{batch_id}",
                "direction":   "incoming",
                "sender":      _sender,
                "to":          [],
                "cc":          [],
                "subject":     body.subject or "",
                "body_text":   f"DHL customs email manually marked as received for batch {batch_id}.",
                "timestamp":   received_at,
                "event_type":  "dhl_request",
                "matched_identifiers": {"awb": True},
                "attachments": [],
                "source":      "manual_admin",
            }, source="manual_admin")
        except Exception as _evs_exc:
            log.warning("[mark_email_received] evidence store write failed (non-fatal): %s", _evs_exc)

    # Log timeline event
    for sub in ("outputs", "working"):
        audit_path = settings.storage_root / sub / batch_id / "audit.json"
        if audit_path.exists():
            tl.log_event(
                audit_path,
                tl.EV_DHL_EMAIL_RECEIVED,
                trigger_source="dashboard",
                actor="admin",
                detail={
                    "source":       "manual_admin",
                    "ticket":       body.ticket or "",
                    "request_type": body.request_type or "unknown",
                },
            )
            break

    log.info("DHL email manually marked received: batch=%s ticket=%s", batch_id, body.ticket or "—")

    return {
        "ok":               True,
        "batch_id":         batch_id,
        "action":           "dhl_email_marked_received",
        "status":           "dhl_email_received",
        "marked":           True,
        "clearance_status": "dhl_email_received",
        "dhl_email":        dhl_email,
        "errors":           [],
        "warnings":         [],
        "message":          "DHL email marked as received. Generate Description and DSK are now unlocked.",
    }


# ── Serialization helpers ─────────────────────────────────────────────────────

def _safe_dsk(dsk: Optional[dict]) -> Optional[dict]:
    """Return a serialization-safe subset of the DSK result."""
    if not dsk:
        return None
    return {
        "generated":        dsk.get("generated"),
        "filename":         dsk.get("filename"),
        "awb_clean":        dsk.get("awb_clean"),
        "awb_formatted":    dsk.get("awb_formatted"),
        "date":             dsk.get("date"),
        "skip_reason":      dsk.get("skip_reason"),
        "error":            dsk.get("error"),
        "version":          dsk.get("version"),
        "file_hash_sha256": dsk.get("file_hash_sha256"),
    }


def _safe_polish(pol: Optional[dict]) -> Optional[dict]:
    """Return a serialization-safe subset of the Polish description result."""
    if not pol:
        return None
    return {
        "generated":       pol.get("generated"),
        "filename":        pol.get("filename"),
        "items_described": pol.get("items_described"),
        "error":           pol.get("error"),
    }


# ── P2 Slice A: Proactive DHL customs dispatch ──────────────────────────────
# First-contact endpoint that creates an action proposal for proactive
# customs dispatch on a low-value DHL self-clearance shipment. Uses the
# existing routes_action_proposals approve/queue pipeline; no new execute
# endpoint. Locked under proposal_write_lock(batch_id) so concurrent POSTs
# for the same batch dedupe to a single proposal.

class ProactiveDispatchRequest(BaseModel):
    """Request body — operator_id ONLY. NO recipient/CC fields."""
    operator_id: str

    class Config:
        # Pydantic v1 — reject unknown fields so a malicious caller cannot
        # smuggle a `to:` or `cc:` override through the schema.
        extra = "forbid"


def _resolve_proactive_awb(audit: Dict[str, Any]) -> str:
    return (
        audit.get("dhl_awb")
        or audit.get("awb")
        or (audit.get("batch_meta") or {}).get("awb")
        or audit.get("tracking_no")
        or ""
    )


def _check_proactive_preconditions(audit: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Run G-PC1..G-PC8 against the live audit.

    Returns ``None`` on success, or a dict ``{"guard", "error", "code"}``
    that the caller raises as HTTP 422.
    """
    # G-PC7 — carrier must be DHL
    carrier = (audit.get("carrier") or "").upper()
    if carrier != "DHL":
        return {
            "guard": "carrier_not_dhl",
            "error": f"Carrier is {carrier!r}; proactive dispatch requires DHL.",
            "code":  "carrier_not_dhl",
        }

    # G-PC1 — must be carrier_self_clearance path
    cd = audit.get("clearance_decision") or {}
    clearance_path = (cd.get("clearance_path") or "").strip()
    if is_agency_clearance(clearance_path):
        return {
            "guard": "agency_path_active",
            "error": "Clearance path is agency clearance — proactive "
                     "dispatch not applicable.",
            "code":  "agency_path_active",
        }
    if clearance_path and not is_dhl_self_clearance(clearance_path):
        return {
            "guard": "not_self_clearance_path",
            "error": f"Clearance path is {clearance_path!r}; expected "
                     "carrier_self_clearance.",
            "code":  "not_self_clearance_path",
        }

    # G-PC2 — customs package must have been generated
    if not audit.get("customs_package_generated_at"):
        return {
            "guard": "customs_package_not_generated",
            "error": "Run /generate-customs-package before proactive dispatch.",
            "code":  "customs_package_not_generated",
        }

    # G-PC3 — must not have been dispatched
    if audit.get("proactive_dispatch_sent_at"):
        return {
            "guard": "already_dispatched",
            "error": "Proactive dispatch already sent for this batch.",
            "code":  "already_dispatched",
        }

    # G-PC5 — no agency
    if audit.get("agency_name") or (audit.get("agency_reply_package") or {}).get("status"):
        return {
            "guard": "agency_path_active",
            "error": "Agency forwarding active — proactive dispatch blocked.",
            "code":  "agency_path_active",
        }

    # G-PC6 — no DSK
    if audit.get("dsk_filename") or audit.get("dsk_reference"):
        return {
            "guard": "dsk_already_created",
            "error": "DSK has been generated — proactive dispatch blocked.",
            "code":  "dsk_already_created",
        }

    return None


@router.post("/proactive-dispatch/{batch_id}", dependencies=[_auth])
def request_proactive_dispatch(
    batch_id: str,
    body: ProactiveDispatchRequest,
) -> Dict[str, Any]:
    """
    Create an action proposal for proactive DHL customs dispatch.

    Step 1 of a two-step flow: this endpoint creates the proposal only.
    Approval and queueing go through the existing
    /api/v1/action-proposals/{proposal_id}/approve and /queue endpoints.

    No email is queued by this endpoint. No clearance_status is mutated.
    """
    from ..utils.proposal_lock import proposal_write_lock
    from ..api.routes_action_proposals import (
        create_proposal,
        _save_audit as _proposal_save_audit,
        _audit_path as _proposal_audit_path,
    )
    from ..services.dhl_proactive_dispatch_builder import (
        build_dhl_proactive_dispatch,
    )

    operator_id = (body.operator_id or "").strip()
    if not operator_id:
        raise HTTPException(
            status_code=422,
            detail={"guard": "missing_operator_id",
                    "error": "operator_id is required."},
        )

    # Phase 2.3.1 (Finding 1.2): reject operator_id values that match the
    # auto-actor sentinel space. Without this guard, an operator could mint
    # a self-approving proposal by spoofing the system actor name and bypass
    # the G9 self-approval block via the auto-actor exemption.
    from .routes_action_proposals import _is_auto_actor
    if _is_auto_actor(operator_id):
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "auto_actor_sentinel_reserved",
                "guard":   "auto_actor_sentinel_reserved",
                "error":   f"operator_id is reserved for system actors and cannot be set by request.",
            },
        )

    # Acquire per-batch lock — concurrent POSTs serialise here.
    with proposal_write_lock(batch_id):
        audit = _load_audit(batch_id)
        if audit is None:
            raise HTTPException(
                status_code=404,
                detail={"guard": "batch_not_found",
                        "error": f"Batch {batch_id!r} not found."},
            )

        # G-PC8 — batch exists (just validated above)
        # Run remaining preconditions G-PC1..G-PC7
        gate_failure = _check_proactive_preconditions(audit)
        if gate_failure is not None:
            raise HTTPException(status_code=422, detail=gate_failure)

        # G-PC4 — idempotent dedup. create_proposal already returns
        # existing active proposal of the same type (lines 220-224 of
        # routes_action_proposals.py).
        proposal = create_proposal(
            audit         = audit,
            batch_id      = batch_id,
            proposal_type = "dhl_proactive_dispatch",
            reason        = "operator_initiated_proactive_dispatch",
            confidence    = "high",
        )

        # If we just created a NEW proposal (status pending_review and no
        # approved_by yet AND no created_by yet), stamp created_by + the
        # batch-level requested_at. If create_proposal returned an
        # existing active proposal, we must not stamp anything fresh.
        proposal_id = proposal["proposal_id"]
        is_new_proposal = (
            not proposal.get("created_by")
            and proposal.get("status") == "pending_review"
        )

        if is_new_proposal:
            # Re-verify attachments exist on disk via the builder's missing
            # list. Abort with 503 if anything is missing — do NOT persist
            # a partial proposal.
            draft = proposal.get("draft") or {}
            missing = draft.get("missing") or []
            if missing:
                # Roll back the in-memory append (not yet persisted)
                proposals = audit.get("action_proposals") or []
                audit["action_proposals"] = [
                    p for p in proposals
                    if p.get("proposal_id") != proposal_id
                ]
                raise HTTPException(
                    status_code=503,
                    detail={
                        "guard":   "attachment_missing",
                        "error":   "Required attachments missing on disk.",
                        "missing": missing,
                    },
                )

            # Stamp creator + batch-level timestamp
            proposal["created_by"] = operator_id
            audit["proactive_dispatch_requested_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            audit["proactive_dispatch_proposal_id"] = proposal_id

            _proposal_save_audit(batch_id, audit)

            tl.log_event(
                _proposal_audit_path(batch_id),
                tl.EV_DHL_PROACTIVE_DISPATCH_REQUESTED,
                "admin",
                actor=operator_id,
                detail={
                    "batch_id":         batch_id,
                    "proposal_id":      proposal_id,
                    "awb":              _resolve_proactive_awb(audit),
                    "operator_id":      operator_id,
                    "attachment_count": len(draft.get("attachments") or []),
                    "recipient":        draft.get("to") or "",
                },
            )
            log.info(
                "[proactive-dispatch] proposal created batch=%s proposal=%s by=%s",
                batch_id, proposal_id, operator_id,
            )
        else:
            log.info(
                "[proactive-dispatch] returning existing proposal batch=%s proposal=%s",
                batch_id, proposal_id,
            )

    return {
        "ok":           True,
        "batch_id":     batch_id,
        "proposal_id":  proposal_id,
        "status":       proposal.get("status", "pending_review"),
        "is_new":       bool(is_new_proposal),
    }


# ── W-5 P2: read-only self-clearance state for Mac dashboard state pill ──────
# Per Windows Atlas memory rule: no operator-facing write controls on Mac
# dashboard. This GET is the ONLY new surface from P2 on the Mac side.

@router.get("/selfclearance/state/{batch_id}", dependencies=[_auth])
def get_selfclearance_state(batch_id: str):
    """
    Return the current Path A self-clearance state for the batch.

    Response shape:
        {
          "batch_id": "...",
          "in_scope": true | false,
          "state": "awaiting_preemptive_send" | ... | "n/a",
          "p2_dispatch": {
            "shadow": <bool>,
            "message_id": <str|null>,
            "sent_at": <iso8601|null>,
          },
        }

    Returns `state: "n/a"` for non-Path-A shipments — the Mac dashboard
    renders the pill greyed-out in that case.
    """
    from ..services.dhl_clearance_coordinator import DhlClearanceCoordinator
    from ..services import dhl_clearance_manifest as _manifest

    # Load audit; if not present, return n/a (do not 500)
    audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.is_file():
        return {
            "batch_id":     batch_id,
            "in_scope":     False,
            "state":        "n/a",
            "p2_dispatch":  {"shadow": None, "message_id": None, "sent_at": None},
        }

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "batch_id":     batch_id,
            "in_scope":     False,
            "state":        "n/a",
            "p2_dispatch":  {"shadow": None, "message_id": None, "sent_at": None},
        }

    in_scope = DhlClearanceCoordinator.is_in_scope(audit)
    if not in_scope:
        return {
            "batch_id":     batch_id,
            "in_scope":     False,
            "state":        "n/a",
            "p2_dispatch":  {"shadow": None, "message_id": None, "sent_at": None},
        }

    block = audit.get(_manifest.MANIFEST_KEY) or {}
    p2 = block.get("p2_dispatch") or {}
    return {
        "batch_id":     batch_id,
        "in_scope":     True,
        "state":        block.get("state", "awaiting_preemptive_send"),
        "p2_dispatch":  {
            "shadow":     p2.get("shadow"),
            "message_id": p2.get("message_id"),
            "sent_at":    p2.get("sent_at"),
        },
    }

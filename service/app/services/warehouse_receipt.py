"""
warehouse_receipt.py — Operator quantity-confirmation service (WAREHOUSE authority).

Warehouse receipt = an operator confirms the quantity accepted against the expected
import (packing) quantity, by line or batch. This is the authority signal that goods
have been received. It deliberately does NOT require scanning every physical piece.

Per-piece barcode scan stays OPTIONAL traceability evidence, EXCEPT when the shipment
is explicitly marked ``serial_controlled`` — then scan completeness is required in
addition to quantity confirmation.

Public API
----------
  expected_lines(batch_id)          -> per-line expected quantities (import authority)
  confirm_receipt(batch_id, lines, operator, source_documents) -> summary
  get_receipt_status(batch_id)      -> per-line confirmed/expected + batch summary
  is_serial_controlled(batch_id)    -> bool (read from audit.json, default False)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger
from . import packing_db as pdb
from . import warehouse_receipt_db as wrdb

log = get_logger(__name__)


def line_key_for(pl: Dict[str, Any]) -> str:
    """
    Stable per-line key for a packing line. Prefers invoice_no + line position;
    falls back to design_no / product_code so a key always exists.
    """
    inv = str(pl.get("invoice_no") or "").strip()
    pos = str(pl.get("invoice_line_position") or "").strip()
    if inv and pos:
        return f"{inv}|{pos}"
    dn = str(pl.get("design_no") or "").strip()
    if dn:
        return f"design:{dn}"
    pc = str(pl.get("product_code") or "").strip()
    return f"code:{pc}" if pc else "unknown"


def expected_lines(batch_id: str) -> List[Dict[str, Any]]:
    """
    Expected receipt lines from the import packing authority (packing_lines).
    One entry per packing line with its expected quantity.
    """
    out: List[Dict[str, Any]] = []
    for pl in pdb.get_packing_lines_for_batch(batch_id):
        out.append({
            "line_key":     line_key_for(pl),
            "design_no":    str(pl.get("design_no") or ""),
            "product_code": str(pl.get("product_code") or ""),
            "invoice_no":   str(pl.get("invoice_no") or ""),
            "expected_qty": float(pl.get("quantity") or 0),
        })
    return out


def _audit_path(batch_id: str) -> Path:
    return settings.storage_root / "outputs" / batch_id / "audit.json"


def is_serial_controlled(batch_id: str) -> bool:
    """
    True when this shipment is explicitly serial-controlled. Read from
    ``audit.json`` key ``serial_controlled`` (default False). Serial-controlled
    shipments require per-piece scan completeness in addition to quantity
    confirmation; ordinary shipments do not.
    """
    try:
        p = _audit_path(batch_id)
        if not p.exists():
            return False
        audit = json.loads(p.read_text(encoding="utf-8"))
        return bool(audit.get("serial_controlled", False))
    except Exception:
        return False


def confirm_receipt(
    batch_id: str,
    lines: List[Dict[str, Any]],
    *,
    operator: str = "",
    source_documents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Persist operator quantity confirmations.

    `lines`: list of {line_key | (invoice_no,invoice_line_position) | design_no |
    product_code, accepted_qty}. Expected qty is resolved from the import packing
    authority — never trusted from the client — so shortage/overage are authoritative.
    """
    expected_idx = {e["line_key"]: e for e in expected_lines(batch_id)}
    confirmed: List[Dict[str, Any]] = []
    errors: List[str] = []

    for ln in (lines or []):
        lk = (ln.get("line_key") or "").strip() or line_key_for(ln)
        exp_rec = expected_idx.get(lk)
        if exp_rec is None:
            errors.append(f"line_key {lk!r} not found in import packing authority")
            continue
        try:
            accepted = float(ln.get("accepted_qty"))
        except (TypeError, ValueError):
            errors.append(f"line_key {lk!r}: accepted_qty missing or not numeric")
            continue
        rec = wrdb.upsert_confirmation(
            batch_id, lk,
            expected_qty=exp_rec["expected_qty"],
            accepted_qty=accepted,
            design_no=exp_rec["design_no"],
            product_code=exp_rec["product_code"],
            operator=operator,
            source_documents=source_documents,
            note=str(ln.get("note") or ""),
        )
        if rec:
            confirmed.append(rec)

    status = get_receipt_status(batch_id)
    status["confirmed_now"] = len(confirmed)
    status["errors"] = errors
    return status


def get_receipt_status(batch_id: str) -> Dict[str, Any]:
    """
    Per-line confirmed vs expected, plus a batch summary used by Import PZ
    advisory and the V2 'Confirm received quantities' UI.
    """
    expected = expected_lines(batch_id)
    conf_idx = {c["line_key"]: c for c in wrdb.get_confirmations(batch_id)}

    lines_out: List[Dict[str, Any]] = []
    unconfirmed = 0
    shortage_lines = 0
    overage_lines = 0
    for e in expected:
        c = conf_idx.get(e["line_key"])
        confirmed = c is not None
        if not confirmed:
            unconfirmed += 1
        if c and c.get("shortage_qty", 0) > 0:
            shortage_lines += 1
        if c and c.get("overage_qty", 0) > 0:
            overage_lines += 1
        lines_out.append({
            **e,
            "confirmed":    confirmed,
            "accepted_qty": (c or {}).get("accepted_qty"),
            "shortage_qty": (c or {}).get("shortage_qty"),
            "overage_qty":  (c or {}).get("overage_qty"),
            "operator":     (c or {}).get("operator"),
            "confirmed_at": (c or {}).get("confirmed_at"),
            "source_documents": (c or {}).get("source_documents", []),
        })

    total = len(expected)
    serial = is_serial_controlled(batch_id)
    fully_confirmed = total > 0 and unconfirmed == 0
    return {
        "batch_id":          batch_id,
        "total_lines":       total,
        "confirmed_lines":   total - unconfirmed,
        "unconfirmed_lines": unconfirmed,
        "shortage_lines":    shortage_lines,
        "overage_lines":     overage_lines,
        "fully_confirmed":   fully_confirmed,
        "serial_controlled": serial,
        "lines":             lines_out,
    }

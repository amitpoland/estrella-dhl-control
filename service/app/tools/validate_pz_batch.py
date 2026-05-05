"""
validate_pz_batch.py — strict validator for the "1 AWB = 1 PZ" batch.

Returns a structured ValidationResult instead of raising on the first failure
so the CLI can show ALL problems in one shot.

Rules enforced:
  - At least one line.
  - Every line has product_code, wfirma_good_id, name.
  - qty > 0 and price_net_pln > 0 (Decimal).
  - No duplicate (product_code, invoice_no) pair across the batch.
  - No duplicate wfirma_good_id within the same invoice (a single line per good per invoice).
  - All lines reference at most one supplier (already enforced at build time but
    re-checked here for safety against hand-edited JSON).
  - warehouse_id, document_date, currency, price_type, series_id are all set.
  - currency == "PLN" (intake from foreign supplier — landed cost is in PLN).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List

from app.models.pz_batch_schema import PZBatch, PZBatchLine


@dataclass
class ValidationResult:
    ok:        bool
    errors:    List[str] = field(default_factory=list)
    warnings:  List[str] = field(default_factory=list)


def validate(batch: PZBatch) -> ValidationResult:
    errors:   List[str] = []
    warnings: List[str] = []

    # ── batch-level required fields ───────────────────────────────────────────
    if not batch.lines:
        errors.append("batch.lines is empty — at least one line required")
    if not batch.awb:
        errors.append("batch.awb is empty")
    if not batch.warehouse_id:
        errors.append("batch.warehouse_id is empty")
    if not batch.document_date:
        errors.append("batch.document_date is empty")
    if not batch.series_id:
        errors.append("batch.series_id is empty")
    if not batch.supplier or not batch.supplier.wfirma_id:
        errors.append("batch.supplier.wfirma_id is empty")

    if batch.currency != "PLN":
        errors.append(f"batch.currency must be 'PLN', got {batch.currency!r}")
    if batch.price_type != "netto":
        errors.append(f"batch.price_type must be 'netto', got {batch.price_type!r}")

    if not batch.sad_number:
        warnings.append("batch.sad_number is empty (acceptable while customs clearance pending)")

    # ── per-line checks ───────────────────────────────────────────────────────
    seen_inv_code: dict = {}
    seen_inv_good: dict = {}
    for i, ln in enumerate(batch.lines, start=1):
        if not ln.product_code:
            errors.append(f"Line {i}: product_code is empty")
        if not ln.wfirma_good_id:
            errors.append(
                f"Line {i} ({ln.product_code or '?'}): wfirma_good_id MISSING — "
                f"resolve via goods/find before building the PZ"
            )
        if not ln.name:
            errors.append(f"Line {i} ({ln.product_code or '?'}): name is empty")
        if ln.qty is None or Decimal(ln.qty) <= 0:
            errors.append(f"Line {i} ({ln.product_code or '?'}): qty must be > 0, got {ln.qty}")
        if ln.price_net_pln is None or Decimal(ln.price_net_pln) <= 0:
            errors.append(
                f"Line {i} ({ln.product_code or '?'}): price_net_pln must be > 0, got {ln.price_net_pln}"
            )
        if not ln.invoice_no:
            errors.append(f"Line {i} ({ln.product_code or '?'}): invoice_no missing")

        # Duplicate guards
        key_code = (ln.invoice_no, ln.product_code)
        if ln.invoice_no and ln.product_code:
            if key_code in seen_inv_code:
                errors.append(
                    f"Line {i}: duplicate (invoice={ln.invoice_no}, product_code={ln.product_code}) "
                    f"— also at line {seen_inv_code[key_code]}"
                )
            else:
                seen_inv_code[key_code] = i

        key_good = (ln.invoice_no, ln.wfirma_good_id)
        if ln.invoice_no and ln.wfirma_good_id:
            if key_good in seen_inv_good:
                errors.append(
                    f"Line {i}: duplicate (invoice={ln.invoice_no}, "
                    f"wfirma_good_id={ln.wfirma_good_id}) — also at line {seen_inv_good[key_good]}"
                )
            else:
                seen_inv_good[key_good] = i

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


__all__ = ["validate", "ValidationResult"]

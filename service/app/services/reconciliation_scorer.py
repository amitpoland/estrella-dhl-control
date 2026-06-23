"""
reconciliation_scorer.py — Specification-based reconciliation for ambiguous
design_no → product_code mappings in proforma draft sync.

This is the SECONDARY resolution layer, firing after the primary batch-scoped
packing_lines lookup (product_authority_resolver) returns multiple candidates
for a design_no.

Scoring dimensions (weights must sum to 1.0):
  1. Quantity balance  — purchase qty distribution vs sales row count (0.40)
  2. Spec fingerprint  — are candidates distinguishable by physical spec?  (0.40)
  3. Price correlation — purchase price rank vs sales price rank           (0.20)

Confidence thresholds:
  HIGH   (>= 0.85): auto-resolve; sets product_code on each sales row
  MEDIUM (>= 0.40): surface distribution plan; operator confirms specific assignment
  LOW    (<  0.40): unresolvable by scorer; leave for manual resolution

Audit contract: every resolution decision emits a human-readable audit_trail
list explaining WHY a mapping was selected.  These are stored on the sales row
under ``reconciliation_audit`` and passed back in the resolution summary.

Safety gates (never violated):
  - No wFirma writes
  - No inventory mutations
  - No PZ creation
  - No posting actions
  - Read-only against packing.db
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

HIGH_CONFIDENCE_THRESHOLD   = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.40

# Scoring dimension weights
WEIGHT_QUANTITY_BALANCE  = 0.40
WEIGHT_SPEC_FINGERPRINT  = 0.40
WEIGHT_PRICE_CORRELATION = 0.20

# Per-field spec differentiation weights (total <= WEIGHT_SPEC_FINGERPRINT)
_SPEC_FIELD_WEIGHTS = [
    # (field_name, weight, is_numeric)
    ("item_type",      0.15, False),
    ("karat",          0.10, False),
    ("metal",          0.08, False),
    ("metal_color",    0.05, False),
    ("diamond_weight", 0.08, True),
    ("gross_weight",   0.05, True),
    ("quality_string", 0.04, False),
]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SalesAssignment:
    """Recommended assignment for one sales_packing_lines row."""
    sales_row_index: int                      # index in the original sales_rows list
    recommended_product_code: Optional[str]   # None if unresolvable
    confidence: float
    is_auto_resolved: bool                    # True iff confidence >= HIGH_CONFIDENCE_THRESHOLD
    audit_reason: str


@dataclass
class ReconciliationResult:
    """Full result of scoring one design_no ambiguity."""
    design_no: str
    method: str            # quantity_only | spec_and_quantity | price_correlation | unresolvable
    confidence: float      # 0.0 – 1.0
    confidence_label: str  # HIGH | MEDIUM | LOW | UNRESOLVABLE
    recommended_assignments: List[SalesAssignment]
    distribution_hint: Dict[str, int]  # {product_code: expected_sales_row_count}
    spec_diff_fields: List[str]        # fields that actually differentiated candidates
    audit_trail: List[str]
    requires_operator_review: bool

    @property
    def is_auto_resolvable(self) -> bool:
        return self.confidence >= HIGH_CONFIDENCE_THRESHOLD


# ── Packing spec reader ───────────────────────────────────────────────────────

def _fetch_candidate_specs(
    batch_id: str,
    design_no: str,
    *,
    packing_db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read packing_lines rows for (batch_id, design_no) with full spec fields.

    Returns one dict per physical packing row, scoped strictly to batch_id.
    Returns [] on any read failure (scorer degrades gracefully).
    """
    try:
        if packing_db_path is None:
            from . import packing_db as _pdb  # noqa: PLC0415
            _path = getattr(_pdb, "_db_path", None)
            if _path is None:
                log.warning(
                    "[%s] reconciliation_scorer: packing_db not initialised for %r",
                    batch_id, design_no,
                )
                return []
            packing_db_path = str(_path)
        con = sqlite3.connect(packing_db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT
                    product_code, scan_code, quantity, unit_price, invoice_no,
                    item_type, karat, metal, metal_color,
                    gross_weight, net_weight, diamond_weight, color_weight,
                    quality_string, size
                FROM packing_lines
                WHERE batch_id = ?
                  AND TRIM(LOWER(COALESCE(design_no, ''))) = TRIM(LOWER(?))
                  AND TRIM(COALESCE(product_code, '')) != ''
                ORDER BY product_code, scan_code
                """,
                (batch_id, design_no),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception as exc:
        log.warning(
            "[%s] reconciliation_scorer: failed to read packing specs for %r: %s",
            batch_id, design_no, exc,
        )
        return []


# ── Spec utilities ────────────────────────────────────────────────────────────

def _representative_spec(rows: List[Dict]) -> Dict[str, Any]:
    """Compute a representative spec from multiple packing rows for one product_code."""
    if not rows:
        return {}
    rep: Dict[str, Any] = {}
    for fname in ("gross_weight", "net_weight", "diamond_weight", "color_weight"):
        vals = [float(r[fname]) for r in rows if r.get(fname)]
        rep[fname] = sum(vals) / len(vals) if vals else 0.0
    for fname in ("item_type", "karat", "metal", "metal_color", "quality_string", "size"):
        vals = [str(r[fname]).strip().upper() for r in rows if r.get(fname)]
        rep[fname] = Counter(vals).most_common(1)[0][0] if vals else ""
    return rep


def _is_differentiating(
    values: Dict[str, Any],
    is_numeric: bool,
) -> bool:
    """Return True if values across product codes are meaningfully different."""
    if is_numeric:
        nums = [float(v) for v in values.values() if v is not None]
        if len(nums) < 2:
            return False
        # All-zero means "absent / not measured" — not a differentiating signal
        if all(n == 0.0 for n in nums):
            return False
        return (max(nums) - min(nums)) > 0.001
    else:
        strs = [str(v).strip().upper() for v in values.values() if v]
        return len(set(strs)) > 1


# ── Scoring functions ─────────────────────────────────────────────────────────

def _score_quantity_balance(
    candidate_groups: Dict[str, List[Dict]],
    sales_count: int,
) -> Tuple[float, Dict[str, int], List[str]]:
    """Score how well purchase row counts match the sales row count."""
    distribution = {pc: len(rows) for pc, rows in candidate_groups.items()}
    total_purchase = sum(distribution.values())
    audit: List[str] = []

    audit.append(
        f"Purchase packing: {total_purchase} rows across {len(candidate_groups)} "
        f"product codes {dict(distribution)}"
    )
    audit.append(f"Sales packing: {sales_count} rows to assign")

    if total_purchase == 0:
        audit.append("No purchase packing rows found — cannot score quantity balance")
        return 0.0, distribution, audit

    if total_purchase == sales_count:
        score = WEIGHT_QUANTITY_BALANCE
        audit.append(
            f"Quantity-balanced: {total_purchase} purchase == {sales_count} sales "
            f"SCORE +{score:.2f}"
        )
    else:
        ratio = min(total_purchase, sales_count) / max(total_purchase, sales_count)
        score = WEIGHT_QUANTITY_BALANCE * ratio * 0.5
        audit.append(
            f"Quantity mismatch: {total_purchase} purchase vs {sales_count} sales "
            f"(ratio={ratio:.2f}) SCORE +{score:.2f} (partial)"
        )

    return score, distribution, audit


def _score_spec_fingerprint(
    candidate_groups: Dict[str, List[Dict]],
) -> Tuple[float, List[str], List[str]]:
    """Score how well candidates are distinguishable by physical specification."""
    codes = [pc for pc, rows in candidate_groups.items() if rows]
    audit: List[str] = []

    if len(codes) < 2:
        audit.append("Only one candidate with packing rows — no spec differentiation needed")
        return 0.0, [], audit

    per_code = {pc: _representative_spec(candidate_groups[pc]) for pc in codes}
    diff_fields: List[str] = []
    score = 0.0

    for fname, weight, is_numeric in _SPEC_FIELD_WEIGHTS:
        vals = {pc: per_code[pc].get(fname) for pc in codes}
        if _is_differentiating(vals, is_numeric):
            score += weight
            diff_fields.append(fname)
            audit.append(
                f"Field '{fname}' differentiates candidates {dict(vals)} "
                f"SCORE +{weight:.2f}"
            )

    if not diff_fields:
        audit.append(
            "No spec fields differentiate candidates "
            "(sparse data or all specs identical) — spec score: 0.00"
        )

    score = min(score, WEIGHT_SPEC_FINGERPRINT)
    return score, diff_fields, audit


def _score_price_correlation(
    candidate_groups: Dict[str, List[Dict]],
    sales_rows: List[Dict],
) -> Tuple[float, List[str]]:
    """Score based on price rank correlation between purchase and sales.

    Only applies when each candidate has exactly 1 purchase row and the
    number of candidates equals the number of sales rows.
    """
    audit: List[str] = []

    if any(len(rows) != 1 for rows in candidate_groups.values()):
        audit.append(
            "Price correlation: skipped (some product codes have >1 purchase row)"
        )
        return 0.0, audit

    if len(candidate_groups) != len(sales_rows):
        audit.append(
            f"Price correlation: skipped "
            f"(candidates={len(candidate_groups)} != sales_rows={len(sales_rows)})"
        )
        return 0.0, audit

    purchase_prices = {
        pc: float(rows[0].get("unit_price") or 0.0)
        for pc, rows in candidate_groups.items()
    }
    price_spread = max(purchase_prices.values()) - min(purchase_prices.values())

    if price_spread < 0.01:
        audit.append("Purchase prices are all equal — no price correlation signal")
        return 0.0, audit

    score = WEIGHT_PRICE_CORRELATION * 0.5   # partial: we detect variation but cannot rank sales
    audit.append(
        f"Purchase prices vary (spread={price_spread:.2f}) — correlation signal present "
        f"SCORE +{score:.2f}"
    )
    return score, audit


# ── Assignment logic ──────────────────────────────────────────────────────────

def _assign_rows_to_codes(
    candidate_groups: Dict[str, List[Dict]],
    sales_rows: List[Dict],
    spec_diff_fields: List[str],
    distribution_hint: Dict[str, int],
    confidence: float,
) -> Tuple[List[SalesAssignment], List[str]]:
    """Assign each sales row to a recommended product_code.

    Strategy: sort product codes by purchase count descending (most common first),
    then assign sales rows proportionally.  This is quantity-first; spec-guided
    row selection within a code group is future work when per-row spec data is
    richer.
    """
    audit: List[str] = []
    assignments: List[SalesAssignment] = []

    if not candidate_groups or not sales_rows:
        for i in range(len(sales_rows)):
            assignments.append(SalesAssignment(
                sales_row_index=i,
                recommended_product_code=None,
                confidence=0.0,
                is_auto_resolved=False,
                audit_reason="No purchase candidates available",
            ))
        return assignments, audit

    # Sort: highest purchase count first, then alphabetic for determinism
    sorted_codes = sorted(
        distribution_hint.keys(),
        key=lambda pc: (-distribution_hint.get(pc, 0), pc),
    )

    total_purchase = sum(distribution_hint.values())
    plan: List[Tuple[str, int]] = []
    remaining = len(sales_rows)

    for idx, pc in enumerate(sorted_codes):
        if idx == len(sorted_codes) - 1:
            count = remaining
        else:
            count = round(len(sales_rows) * distribution_hint.get(pc, 0) / max(total_purchase, 1))
            count = min(count, remaining)
        plan.append((pc, count))
        remaining -= count

    audit.append(f"Assignment plan (quantity-proportional): {plan}")

    is_auto = confidence >= HIGH_CONFIDENCE_THRESHOLD
    row_idx = 0

    for pc, count in plan:
        for _ in range(count):
            if row_idx >= len(sales_rows):
                break
            reason = (
                f"Assigned to {pc}: quantity-proportional "
                f"(purchase_qty={distribution_hint.get(pc, 0)})"
            )
            if spec_diff_fields:
                reason += f"; differentiating spec fields: {spec_diff_fields}"
            assignments.append(SalesAssignment(
                sales_row_index=row_idx,
                recommended_product_code=pc,
                confidence=confidence,
                is_auto_resolved=is_auto,
                audit_reason=reason,
            ))
            row_idx += 1

    # Any leftover rows (sales > purchase) get None
    while row_idx < len(sales_rows):
        assignments.append(SalesAssignment(
            sales_row_index=row_idx,
            recommended_product_code=None,
            confidence=0.0,
            is_auto_resolved=False,
            audit_reason=(
                f"Sales row count ({len(sales_rows)}) exceeds total purchase "
                f"rows ({total_purchase}) — cannot assign"
            ),
        ))
        row_idx += 1

    return assignments, audit


# ── Main entry point ──────────────────────────────────────────────────────────

def score_ambiguous_design(
    batch_id: str,
    design_no: str,
    candidates: List[str],
    sales_rows: List[Dict],
    *,
    packing_db_path: Optional[str] = None,
) -> ReconciliationResult:
    """Score resolution for an ambiguous design_no (multiple product_code candidates).

    Args:
        batch_id:       Batch to scope packing evidence.
        design_no:      The ambiguous design number (e.g. 'PND', 'J4006R01513').
        candidates:     Product codes that match design_no in packing_lines.
        sales_rows:     sales_packing_lines rows with empty product_code for this design.
        packing_db_path: Override for testing; omit in production.

    Returns:
        ReconciliationResult with recommended assignments, confidence, and audit trail.
        Never raises — degrades gracefully to UNRESOLVABLE on any internal error.
    """
    audit: List[str] = []
    audit.append(
        f"Spec reconciliation for design_no={design_no!r} in batch {batch_id!r}"
    )
    audit.append(
        f"Input: {len(candidates)} candidates {candidates}, "
        f"{len(sales_rows)} unresolved sales rows"
    )

    # Fetch purchase packing rows with spec data
    packing_rows = _fetch_candidate_specs(
        batch_id, design_no, packing_db_path=packing_db_path
    )

    if not packing_rows:
        audit.append(
            "No packing rows found in packing.db for this design in this batch — "
            "spec reconciliation cannot proceed (zero-candidate case)"
        )
        return ReconciliationResult(
            design_no=design_no,
            method="unresolvable",
            confidence=0.0,
            confidence_label="UNRESOLVABLE",
            recommended_assignments=[
                SalesAssignment(
                    sales_row_index=i,
                    recommended_product_code=None,
                    confidence=0.0,
                    is_auto_resolved=False,
                    audit_reason="No packing spec data available in batch",
                )
                for i in range(len(sales_rows))
            ],
            distribution_hint={pc: 0 for pc in candidates},
            spec_diff_fields=[],
            audit_trail=audit,
            requires_operator_review=True,
        )

    # Group packing rows by product_code, filtered to known candidates
    candidate_groups: Dict[str, List[Dict]] = {pc: [] for pc in candidates}
    for row in packing_rows:
        pc = str(row.get("product_code") or "").strip()
        if pc in candidate_groups:
            candidate_groups[pc].append(row)

    audit.append(
        f"Packing rows by product_code: "
        f"{dict((pc, len(rows)) for pc, rows in candidate_groups.items())}"
    )

    # Dimension 1: Quantity balance
    qty_score, distribution_hint, qty_audit = _score_quantity_balance(
        candidate_groups, len(sales_rows)
    )
    audit.extend(qty_audit)

    # Dimension 2: Spec fingerprint
    spec_score, spec_diff_fields, spec_audit = _score_spec_fingerprint(candidate_groups)
    audit.extend(spec_audit)

    # Dimension 3: Price correlation
    price_score, price_audit = _score_price_correlation(candidate_groups, sales_rows)
    audit.extend(price_audit)

    total_confidence = min(qty_score + spec_score + price_score, 1.0)
    audit.append(
        f"Total confidence: {qty_score:.2f} (qty) + {spec_score:.2f} (spec) + "
        f"{price_score:.2f} (price) = {total_confidence:.2f}"
    )

    # Label and method
    if total_confidence >= HIGH_CONFIDENCE_THRESHOLD:
        confidence_label = "HIGH"
        method = "spec_and_quantity" if spec_diff_fields else "quantity_only"
    elif total_confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        confidence_label = "MEDIUM"
        method = "quantity_only"
    else:
        confidence_label = "LOW"
        method = "unresolvable"

    audit.append(f"Confidence label: {confidence_label} method: {method}")

    # Build row assignments
    assignments, assign_audit = _assign_rows_to_codes(
        candidate_groups, sales_rows, spec_diff_fields, distribution_hint, total_confidence
    )
    audit.extend(assign_audit)

    if confidence_label == "HIGH":
        audit.append(f"AUTO-RESOLVED: {len(assignments)} sales rows assigned automatically")
    elif confidence_label == "MEDIUM":
        audit.append(
            "DISTRIBUTION PLAN: operator confirmation required for "
            "specific row-to-product assignment"
        )
    else:
        audit.append("UNRESOLVABLE: manual assignment required")

    return ReconciliationResult(
        design_no=design_no,
        method=method,
        confidence=total_confidence,
        confidence_label=confidence_label,
        recommended_assignments=assignments,
        distribution_hint=distribution_hint,
        spec_diff_fields=spec_diff_fields,
        audit_trail=audit,
        requires_operator_review=(confidence_label != "HIGH"),
    )

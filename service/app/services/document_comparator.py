"""document_comparator.py — pure, I/O-free comparison of a FinalInvoicePlan
(the EXPECTED projection) against an ACTUAL wFirma invoice XML snapshot.

Campaign-2 · Phase A1. Extracted verbatim from
``routes_proforma._verify_created_invoice`` so that ONE comparison matrix feeds
BOTH:

  * the irreversible creation gate (``_verify_created_invoice``, which raises
    ``RuntimeError(first_blocking_gap.message)``), and
  * the read-only reconciliation report (Campaign-2 A2).

Building a second, parallel matrix would be a duplicate authority (CLAUDE.md
GATE-1 / OS-v1.4 §5). This module is the single comparison authority; the gate
delegates to it.

CONTRACT PRESERVATION (senior-review pt 2): the ordered gaps and their
``message`` strings reproduce the historic ``verify-after-create`` RuntimeError
messages **byte-for-byte**, in the **same order** (parse → id → type →
contractor → line-count → per-line → currency → total → receiver). The gate
raises the first BLOCKED gap's message, so callers that assert on
``body["error"]`` substrings are unchanged.

Pure: no HTTP, no DB, no writes, no mutation of inputs.
"""
from __future__ import annotations

import xml.etree.ElementTree as _VET
from dataclasses import dataclass, field
from decimal import Decimal as _D, InvalidOperation as _DI
from typing import Any, List, Optional

# ── Classification vocabularies (senior-review pt 4: severity ≠ policy) ────────
# severity  = the NATURE of the difference.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
# resolution_policy = what the system is ALLOWED to do about it.
POLICY_NONE = "none"
POLICY_LOCAL_REPAIR = "local_projection_repair"
POLICY_APPROVAL = "approval_required"
POLICY_BLOCKED = "blocked"
# evidence_quality = how trustworthy the "actual"/"expected" pairing is
# (senior-review pt 9). The verify matrix compares against the exact remote XML
# just fetched, so every gap here is EXACT_REMOTE_SNAPSHOT.
EQ_EXACT = "exact_remote_snapshot"
EQ_CURRENT = "current_master_projection"
EQ_NOT_VERIFIABLE = "not_verifiable"

# The verify matrix is a fiscal creation gate: every difference it finds is a
# true blocker (Lesson N — currency/total/tax/quantity/customer are true
# blockers, never advisory). So each gap below is critical + blocked + exact.
_AUTHORITY = "IMPORT_PZ/PROFORMA"


@dataclass(frozen=True)
class Gap:
    """One field-level difference between expected and actual."""
    field: str
    expected: Any
    actual: Any
    authority: str
    severity: str
    resolution_policy: str
    evidence_quality: str
    message: str  # operator-visible string; byte-identical to the legacy gate

    @property
    def blocking(self) -> bool:
        return self.resolution_policy == POLICY_BLOCKED


@dataclass(frozen=True)
class ReconciliationResult:
    """Ordered gaps from comparing a plan against an actual document."""
    gaps: List[Gap] = field(default_factory=list)

    @property
    def has_blocking_gaps(self) -> bool:
        return any(g.blocking for g in self.gaps)

    def first_blocking_gap(self) -> Optional[Gap]:
        for g in self.gaps:
            if g.blocking:
                return g
        return None


def _blocking_gap(field_name: str, expected: Any, actual: Any, message: str) -> Gap:
    """Every verify-matrix difference is critical + blocked + exact-snapshot."""
    return Gap(
        field=field_name,
        expected=expected,
        actual=actual,
        authority=_AUTHORITY,
        severity=SEVERITY_CRITICAL,
        resolution_policy=POLICY_BLOCKED,
        evidence_quality=EQ_EXACT,
        message=message,
    )


def compare_invoice_plan(plan, verify_xml: str) -> ReconciliationResult:
    """Compare a ``FinalInvoicePlan`` (expected) to an actual wFirma invoice XML
    snapshot and return the ordered gaps.

    Reproduces the exact ``_verify_created_invoice`` check set and messages. The
    creation gate raises ``RuntimeError`` on the first BLOCKED gap; the read-only
    report surfaces the full list. Never raises on any XML the legacy verifier
    could parse — malformed nodes degrade to empty strings / structural gaps,
    exactly as the original did.
    """
    gaps: List[Gap] = []

    verify_root = _VET.fromstring(verify_xml)
    v_inv = verify_root.find(".//invoice")
    if v_inv is None:
        # Structural failure — nothing further is parseable. Return early with
        # the single gap, mirroring the legacy immediate-raise.
        gaps.append(_blocking_gap(
            "invoice", "present", "absent",
            "verify-after-create: fetched invoice "
            "but no <invoice> element in response",
        ))
        return ReconciliationResult(gaps=gaps)

    # Check 1: invoice ID exists
    v_id = (v_inv.findtext("id") or "").strip()
    if not v_id:
        gaps.append(_blocking_gap(
            "id", "non-empty", "",
            "verify-after-create: fetched invoice has empty <id>",
        ))

    # Check 2: type is normal/vat (not proforma)
    v_type = (v_inv.findtext("type") or "").strip().lower()
    if v_type not in ("normal", "vat"):
        gaps.append(_blocking_gap(
            "type", "normal|vat", v_type,
            f"verify-after-create: expected type='normal' or 'vat', "
            f"got type={v_type!r} — wFirma may have created wrong document type",
        ))

    # Check 3: contractor matches source proforma
    v_contractor_node = v_inv.find("contractor")
    v_contractor_id = (
        (v_contractor_node.findtext("id") or "").strip()
        if v_contractor_node is not None else ""
    )
    if v_contractor_id != plan.contractor_id:
        gaps.append(_blocking_gap(
            "contractor_id", plan.contractor_id, v_contractor_id,
            f"verify-after-create: contractor mismatch — "
            f"expected={plan.contractor_id!r} got={v_contractor_id!r}",
        ))

    # Check 4: line count matches source proforma
    v_lines = verify_root.findall(".//invoicecontent")
    expected_line_count = len(plan.contents)
    actual_line_count = len(v_lines)
    if actual_line_count != expected_line_count:
        gaps.append(_blocking_gap(
            "line_count", expected_line_count, actual_line_count,
            f"verify-after-create: line count mismatch — "
            f"expected={expected_line_count} persisted={actual_line_count} "
            f"(wFirma silently dropped lines)",
        ))

    # Check 4b: per-line field verification (name, good_id, unit_count, price, vat)
    for idx, (expected_line, actual_el) in enumerate(
        zip(plan.contents, v_lines), start=1
    ):
        _a_name = (actual_el.findtext("name") or "").strip()
        _a_good_node = actual_el.find("good")
        _a_good_id = (
            (_a_good_node.findtext("id") or "").strip()
            if _a_good_node is not None else ""
        )
        _a_unit_count = (actual_el.findtext("unit_count") or "").strip()
        _a_price = (actual_el.findtext("price") or "").strip()
        _a_vat_node = actual_el.find("vat_code")
        _a_vat_id = (
            (_a_vat_node.findtext("id") or "").strip()
            if _a_vat_node is not None else ""
        )
        _mismatches = []
        if _a_name != expected_line.name:
            _mismatches.append(
                f"name: expected={expected_line.name!r} got={_a_name!r}"
            )
        if _a_good_id != expected_line.good_id:
            _mismatches.append(
                f"good_id: expected={expected_line.good_id!r} got={_a_good_id!r}"
            )
        if _a_unit_count != expected_line.unit_count:
            _mismatches.append(
                f"unit_count: expected={expected_line.unit_count!r} got={_a_unit_count!r}"
            )
        if _a_price != expected_line.price:
            _mismatches.append(
                f"price: expected={expected_line.price!r} got={_a_price!r}"
            )
        if _a_vat_id != expected_line.vat_code_id:
            _mismatches.append(
                f"vat_code_id: expected={expected_line.vat_code_id!r} got={_a_vat_id!r}"
            )
        if _mismatches:
            gaps.append(_blocking_gap(
                f"line[{idx}]",
                {
                    "name": expected_line.name, "good_id": expected_line.good_id,
                    "unit_count": expected_line.unit_count,
                    "price": expected_line.price, "vat_code_id": expected_line.vat_code_id,
                },
                {
                    "name": _a_name, "good_id": _a_good_id,
                    "unit_count": _a_unit_count, "price": _a_price,
                    "vat_code_id": _a_vat_id,
                },
                f"verify-after-create: line {idx} field mismatch — "
                + "; ".join(_mismatches),
            ))

    # Check 5: currency matches (only when actual currency is present)
    v_currency = (v_inv.findtext("currency") or "").strip()
    if v_currency and v_currency != plan.currency:
        gaps.append(_blocking_gap(
            "currency", plan.currency, v_currency,
            f"verify-after-create: currency mismatch — "
            f"expected={plan.currency!r} got={v_currency!r}",
        ))

    # Check 6: total matches within rounding tolerance (0.02)
    v_total_str = (v_inv.findtext("total") or "0").strip()
    try:
        v_total = _D(v_total_str)
    except _DI:
        v_total = _D("0")
    total_diff = abs(v_total - plan.expected_total)
    if total_diff > _D("0.02"):
        gaps.append(_blocking_gap(
            "total", plan.expected_total, v_total,
            f"verify-after-create: total mismatch beyond tolerance — "
            f"expected={plan.expected_total} got={v_total} "
            f"diff={total_diff} (tolerance=0.02)",
        ))

    # Check 7: contractor_receiver preserved when present
    if plan.contractor_receiver_id:
        v_rcv_node = v_inv.find("contractor_receiver")
        v_rcv_id = (
            (v_rcv_node.findtext("id") or "").strip()
            if v_rcv_node is not None else ""
        )
        if v_rcv_id != plan.contractor_receiver_id:
            gaps.append(_blocking_gap(
                "contractor_receiver_id", plan.contractor_receiver_id, v_rcv_id,
                f"verify-after-create: contractor_receiver mismatch — "
                f"expected={plan.contractor_receiver_id!r} "
                f"got={v_rcv_id!r}",
            ))

    return ReconciliationResult(gaps=gaps)

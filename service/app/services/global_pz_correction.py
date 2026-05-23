"""
global_pz_correction.py — Read-only correction proposal for Global PZ grouping.

PURPOSE
-------
After a Global Jewellery PZ is posted (or proposed), the lineage authority may
reveal structural discrepancies between the posted PZ grouping and what the
invoice-position or style-level authority says should exist.

This module compares:

    posted PZ rows  (from pz_rows.json — "what was grouped")
    authority rows  (from _pz_engine_authority_rows — "what the engine computed")
    lineage links   (from build_global_pz_lineage — "what the invoice+packing says")

And produces a CorrectionProposal with one or more CorrectionOptions, each with:

    • a human-readable description of what the option would do
    • a proposed line layout
    • risk classification
    • whether a wFirma write / cancel+recreate would be required

HARD RULES
----------
- NO wFirma writes here. Ever.
- NO PZ cancellation or creation.
- NO audit.json mutation.
- NO wfirma_client imports.
- Operator approval is required before any corrective write can proceed.
- This module is a pure function: given inputs → return CorrectionProposal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .global_pz_lineage import LineageResult, PositionRowLink


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclasses (all read-only value objects)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PZLineSummary:
    """One PZ line as it currently stands (from pz_rows.json)."""
    product_code:    str
    item_type:       str
    qty:             float
    value_pln:       float
    wfirma_doc_id:   Optional[str]   # None when not yet confirmed in wFirma


@dataclass
class ProposedLine:
    """One line in a proposed PZ layout."""
    invoice_position_no: int
    item_type:           str
    invoice_qty:         float
    packing_qty:         float
    match_status:        str
    allocation_confidence: str
    allocation_reason_codes: List[str] = field(default_factory=list)
    style_codes:         List[str]     = field(default_factory=list)
    suggested_product_code: str        = ""


@dataclass
class CorrectionOption:
    """One actionable correction path."""
    option_id:    str
    # KEEP_CURRENT          — posted structure is acceptable; no write needed
    # ALIGN_TO_AUTHORITY    — rename product codes to INV-NN format; no qty change
    # SPLIT_TO_STYLE_LEVEL  — one line per (invoice_position, item_type) slot
    # NO_ACTION             — structure matches authority exactly; nothing to do

    label:                  str
    description:            str
    risk_level:             str    # NONE | LOW | MEDIUM | HIGH
    line_count_current:     int
    line_count_proposed:    int    # delta = proposed - current
    requires_wfirma_edit:   bool   # True if any wFirma API call would be needed
    requires_wfirma_cancel: bool   # True only for full recreate (SPLIT path)
    proposed_lines:         List[ProposedLine] = field(default_factory=list)
    blocking_reasons:       List[str]          = field(default_factory=list)
    notes:                  List[str]          = field(default_factory=list)


@dataclass
class CorrectionProposal:
    """Complete read-only correction analysis for one Global batch."""
    batch_id:      str
    invoice_no:    str
    generated_at:  str

    # What exists
    current_pz_line_count:   int
    authority_row_count:     int
    lineage_link_count:      int
    pz_confirmed_in_wfirma:  bool   # True only when wfirma_doc_id present on ≥1 row

    # Structural diagnostics
    product_code_format_mismatch: bool     # pz_rows use -N; authority uses -INV-NN
    qty_mismatch_positions:       List[int]  # positions where posted qty ≠ authority qty
    type_mismatch_positions:      List[int]  # positions where item_type differs
    mixed_type_positions:         List[int]  # positions with >1 item_type in lineage
    overflow_positions:           List[int]  # lineage links with OVERFLOW
    partial_positions:            List[int]  # lineage links with PARTIAL
    unmatched_packing_serials:    List[int]

    # Options (always non-empty; at minimum KEEP_CURRENT or NO_ACTION)
    options:             List[CorrectionOption]
    recommended_option:  str
    recommendation_basis: str

    # Snapshot of current posted lines
    current_lines:       List[PZLineSummary] = field(default_factory=list)

    notes:               List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_INV_FMT = re.compile(r"-INV-0*(\d+)$")
_POS_FMT = re.compile(r"-POS-0*(\d+)$")
_SEQ_FMT = re.compile(r"-(\d+)$")


def _extract_pos_no(product_code: str) -> int:
    """Extract 1-based position number from any supported product_code format."""
    for pat in (_INV_FMT, _POS_FMT, _SEQ_FMT):
        m = pat.search(product_code or "")
        if m:
            return int(m.group(1))
    return 0


def _is_inv_format(product_code: str) -> bool:
    return bool(_INV_FMT.search(product_code or ""))


def _to_inv_format(product_code: str, pos_no: int) -> str:
    """Convert any product_code to the canonical INV-NN format."""
    base = _SEQ_FMT.sub("", _POS_FMT.sub("", _INV_FMT.sub("", product_code)))
    base = base.rstrip("-")
    return f"{base}-INV-{pos_no:02d}"


def _normalise_type(t: str) -> str:
    return (t or "").upper().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Core builder
# ─────────────────────────────────────────────────────────────────────────────

def build_correction_proposal(
    batch_id:        str,
    invoice_no:      str,
    lineage_result:  LineageResult,
    pz_rows:         Optional[List[Dict[str, Any]]],
    authority_rows:  Optional[List[Dict[str, Any]]],
) -> CorrectionProposal:
    """
    Pure function. Derives a CorrectionProposal from three independent inputs.

    Args:
        batch_id:       Internal batch identifier (e.g. SHIPMENT_4789974092_…)
        invoice_no:     Invoice number (e.g. "088/2026-2027")
        lineage_result: Result of build_global_pz_lineage() — the authority.
        pz_rows:        Contents of pz_rows.json (the "posted grouping").
                        May be None/empty if no PZ has been issued yet.
        authority_rows: Contents of audit._pz_engine_authority_rows.
                        May be None/empty if audit predates the authority field.

    Returns:
        CorrectionProposal — never raises, always returns a valid proposal.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_pz   = pz_rows or []
    safe_auth = authority_rows or []

    # ── 1. Snapshot current posted lines ─────────────────────────────────────
    current_lines: List[PZLineSummary] = [
        PZLineSummary(
            product_code=r.get("product_code") or "",
            item_type=_normalise_type(r.get("item_type") or ""),
            qty=float(r.get("quantity") or 0),
            value_pln=float(r.get("unit_netto_pln") or r.get("line_total") or 0),
            wfirma_doc_id=r.get("wfirma_document_id") or None,
        )
        for r in safe_pz
    ]

    pz_confirmed = any(ln.wfirma_doc_id for ln in current_lines)

    # ── 2. Index authority rows by position ───────────────────────────────────
    auth_by_pos: Dict[int, Dict] = {}
    for r in safe_auth:
        pos = _extract_pos_no(r.get("product_code") or "")
        if pos:
            auth_by_pos[pos] = r

    # ── 3. Index lineage links by position ───────────────────────────────────
    links_by_pos: Dict[int, List[PositionRowLink]] = {}
    for lk in lineage_result.position_links:
        links_by_pos.setdefault(lk.position_no, []).append(lk)

    # ── 4. Structural diagnostics ─────────────────────────────────────────────
    product_code_format_mismatch = False
    qty_mismatch_positions:  List[int] = []
    type_mismatch_positions: List[int] = []

    pz_by_pos: Dict[int, PZLineSummary] = {}
    for ln in current_lines:
        pos = _extract_pos_no(ln.product_code)
        if pos:
            pz_by_pos[pos] = ln
            if not _is_inv_format(ln.product_code):
                product_code_format_mismatch = True

    for pos, ln in pz_by_pos.items():
        auth = auth_by_pos.get(pos)
        if not auth:
            continue
        if abs(float(auth.get("quantity") or 0) - ln.qty) > 1e-3:
            qty_mismatch_positions.append(pos)
        if _normalise_type(auth.get("item_type") or "") != ln.item_type:
            type_mismatch_positions.append(pos)

    mixed_type_positions: List[int] = sorted(
        pos for pos, lks in links_by_pos.items() if len(lks) > 1
    )
    overflow_positions: List[int] = sorted(set(
        lk.position_no for lk in lineage_result.position_links
        if lk.match_status == "OVERFLOW"
    ))
    partial_positions: List[int] = sorted(set(
        lk.position_no for lk in lineage_result.position_links
        if lk.match_status == "PARTIAL"
    ))

    # ── 5. Build proposed lines for each option ───────────────────────────────

    # Helper: build a ProposedLine from a single PositionRowLink
    def _link_to_proposed(lk: PositionRowLink, pos_no: int) -> ProposedLine:
        inv_no_base = invoice_no or ""
        code = f"{inv_no_base}-INV-{pos_no:02d}"
        return ProposedLine(
            invoice_position_no=pos_no,
            item_type=lk.invoice_item_type,
            invoice_qty=lk.invoice_qty,
            packing_qty=lk.packing_qty_sum,
            match_status=lk.match_status,
            allocation_confidence=lk.allocation_confidence,
            allocation_reason_codes=list(lk.allocation_reason_codes),
            style_codes=list(lk.style_codes),
            suggested_product_code=code,
        )

    # Option A: KEEP_CURRENT — current pz_rows as-is
    keep_lines: List[ProposedLine] = [
        ProposedLine(
            invoice_position_no=_extract_pos_no(ln.product_code),
            item_type=ln.item_type,
            invoice_qty=ln.qty,
            packing_qty=ln.qty,  # posted = what was written; packing unknown from this source
            match_status="POSTED",
            allocation_confidence="",
            suggested_product_code=ln.product_code,
        )
        for ln in current_lines
    ]

    # Option B: ALIGN_TO_AUTHORITY — same structure, INV-NN product codes
    align_lines: List[ProposedLine] = []
    for pos in sorted(links_by_pos.keys()):
        lks = links_by_pos[pos]
        # Canonical = first link (primary item type, same as the posted grouping)
        primary = lks[0]
        align_lines.append(_link_to_proposed(primary, pos))

    # Option C: SPLIT_TO_STYLE_LEVEL — one line per (pos, item_type) slot
    split_lines: List[ProposedLine] = []
    for pos in sorted(links_by_pos.keys()):
        for lk in links_by_pos[pos]:
            pl = _link_to_proposed(lk, pos)
            # Differentiate product code for secondary types
            if len(links_by_pos[pos]) > 1:
                pl.suggested_product_code = (
                    f"{invoice_no or ''}-INV-{pos:02d}-{lk.invoice_item_type}"
                )
            split_lines.append(pl)

    # ── 6. Assess options ─────────────────────────────────────────────────────
    n_current  = len(current_lines)
    n_align    = len(align_lines)
    n_split    = len(split_lines)
    n_lineage  = len(lineage_result.position_links)

    # Structural equivalence: current matches authority
    structurally_equivalent = (
        not qty_mismatch_positions
        and not type_mismatch_positions
        and n_current == len(auth_by_pos or links_by_pos)
    )

    options: List[CorrectionOption] = []
    notes: List[str] = []

    # ── Fallback: no posted PZ rows at all ───────────────────────────────────
    if not safe_pz:
        options.append(CorrectionOption(
            option_id="NO_ACTION",
            label="No action required (no posted PZ rows found)",
            description=(
                "No pz_rows.json entries were found for this batch. "
                "There is no posted PZ grouping to assess or correct."
            ),
            risk_level="NONE",
            line_count_current=0,
            line_count_proposed=0,
            requires_wfirma_edit=False,
            requires_wfirma_cancel=False,
            proposed_lines=[],
            notes=["pz_rows.json is absent or empty — PZ may not have been generated yet."],
        ))
        recommended = _recommend(
            options, structurally_equivalent, product_code_format_mismatch,
            mixed_type_positions, qty_mismatch_positions, type_mismatch_positions,
        )
        return CorrectionProposal(
            batch_id=batch_id,
            invoice_no=invoice_no,
            generated_at=now,
            current_pz_line_count=0,
            authority_row_count=len(auth_by_pos),
            lineage_link_count=n_lineage,
            pz_confirmed_in_wfirma=False,
            product_code_format_mismatch=False,
            qty_mismatch_positions=[],
            type_mismatch_positions=[],
            mixed_type_positions=mixed_type_positions,
            overflow_positions=overflow_positions,
            partial_positions=partial_positions,
            unmatched_packing_serials=list(lineage_result.unmatched_packing_serials),
            options=options,
            recommended_option=recommended["option_id"],
            recommendation_basis=recommended["basis"],
            current_lines=[],
            notes=["No posted PZ rows found. Nothing to correct."],
        )

    if not pz_confirmed:
        notes.append(
            "No wFirma document ID found on any posted PZ row — PZ may not yet be "
            "confirmed in wFirma. Correction risk is lower (no live document to cancel)."
        )

    # ── Option: NO_ACTION ────────────────────────────────────────────────────
    if structurally_equivalent and not product_code_format_mismatch:
        options.append(CorrectionOption(
            option_id="NO_ACTION",
            label="No action required",
            description=(
                "Posted PZ structure matches the authority exactly: same positions, "
                "same item types, same quantities, and matching product-code format. "
                "No wFirma write needed."
            ),
            risk_level="NONE",
            line_count_current=n_current,
            line_count_proposed=n_current,
            requires_wfirma_edit=False,
            requires_wfirma_cancel=False,
            proposed_lines=keep_lines,
        ))

    # ── Option: KEEP_CURRENT ─────────────────────────────────────────────────
    if structurally_equivalent and product_code_format_mismatch:
        keep_notes = [
            "Product codes use the sequential suffix format (e.g. -1, -2) instead "
            "of the canonical INV-NN format (e.g. -INV-01, -INV-02). The lineage "
            "engine handles both formats — no functional impact. Keep if the "
            "posted wFirma document already uses this format and an edit is undesirable."
        ]
        options.append(CorrectionOption(
            option_id="KEEP_CURRENT",
            label="Keep current posted grouping",
            description=(
                "Posted PZ has the same positions, item types, and quantities as the "
                "authority. Product-code format differs (sequential vs. INV-NN) but "
                "the lineage engine reads both. Keeping avoids any wFirma API call."
            ),
            risk_level="NONE",
            line_count_current=n_current,
            line_count_proposed=n_current,
            requires_wfirma_edit=False,
            requires_wfirma_cancel=False,
            proposed_lines=keep_lines,
            notes=keep_notes,
        ))

    # ── Option: ALIGN_TO_AUTHORITY ───────────────────────────────────────────
    if product_code_format_mismatch or qty_mismatch_positions or type_mismatch_positions:
        align_blocking: List[str] = []
        align_risk = "LOW"
        if qty_mismatch_positions or type_mismatch_positions:
            align_risk = "MEDIUM"
            align_blocking.append(
                "Quantity or item-type discrepancies between posted PZ and authority — "
                "alignment requires operator to reconcile differences, not just rename codes."
            )

        align_desc_parts = ["Rename product codes to canonical INV-NN format."]
        if qty_mismatch_positions:
            align_desc_parts.append(
                f"Also corrects qty on positions: {qty_mismatch_positions}."
            )
        if type_mismatch_positions:
            align_desc_parts.append(
                f"Also corrects item type on positions: {type_mismatch_positions}."
            )
        align_desc_parts.append(
            "Line count unchanged. Requires a wFirma document edit (not cancel+recreate) "
            "if the PZ is confirmed in wFirma."
        )

        options.append(CorrectionOption(
            option_id="ALIGN_TO_AUTHORITY",
            label="Align to invoice-position authority (rename only)",
            description=" ".join(align_desc_parts),
            risk_level=align_risk,
            line_count_current=n_current,
            line_count_proposed=n_align,
            requires_wfirma_edit=pz_confirmed,
            requires_wfirma_cancel=False,
            proposed_lines=align_lines,
            blocking_reasons=align_blocking,
        ))

    # ── Option: SPLIT_TO_STYLE_LEVEL ─────────────────────────────────────────
    if mixed_type_positions:
        split_blocking: List[str] = []
        if pz_confirmed:
            split_blocking.append(
                "PZ is confirmed in wFirma. Split requires cancelling the existing "
                "document and re-creating with more lines. This is a high-risk, "
                "non-reversible wFirma operation — operator must approve explicitly."
            )
        options.append(CorrectionOption(
            option_id="SPLIT_TO_STYLE_LEVEL",
            label="Split to style-level lines (one per invoice position × item type)",
            description=(
                f"Expands grouped PZ from {n_current} lines to {n_split} lines — "
                f"one per (invoice position, item type) slot as reported by the lineage "
                f"authority. Mixed positions {mixed_type_positions} each produce "
                f"separate lines. Increases visibility of intra-position allocation. "
                f"Requires cancel + recreate in wFirma."
            ),
            risk_level="HIGH" if pz_confirmed else "MEDIUM",
            line_count_current=n_current,
            line_count_proposed=n_split,
            requires_wfirma_edit=True,
            requires_wfirma_cancel=pz_confirmed,
            proposed_lines=split_lines,
            blocking_reasons=split_blocking,
            notes=[
                "OVERFLOW and PARTIAL positions remain in the split layout — "
                "splitting does not resolve allocation ambiguity, it only makes "
                "existing ambiguity visible as separate lines.",
                "Suggested product codes for secondary types use the pattern "
                "INV-{pos}-{ITEM_TYPE}. Exact wFirma product code must be agreed "
                "before any write operation proceeds.",
            ],
        ))

    # ── 7. Recommendation ────────────────────────────────────────────────────
    recommended = _recommend(
        options,
        structurally_equivalent,
        product_code_format_mismatch,
        mixed_type_positions,
        qty_mismatch_positions,
        type_mismatch_positions,
    )

    return CorrectionProposal(
        batch_id=batch_id,
        invoice_no=invoice_no,
        generated_at=now,
        current_pz_line_count=n_current,
        authority_row_count=len(auth_by_pos),
        lineage_link_count=n_lineage,
        pz_confirmed_in_wfirma=pz_confirmed,
        product_code_format_mismatch=product_code_format_mismatch,
        qty_mismatch_positions=sorted(qty_mismatch_positions),
        type_mismatch_positions=sorted(type_mismatch_positions),
        mixed_type_positions=mixed_type_positions,
        overflow_positions=overflow_positions,
        partial_positions=partial_positions,
        unmatched_packing_serials=list(lineage_result.unmatched_packing_serials),
        options=options,
        recommended_option=recommended["option_id"],
        recommendation_basis=recommended["basis"],
        current_lines=current_lines,
        notes=notes,
    )


def _recommend(
    options:                    List[CorrectionOption],
    structurally_equivalent:    bool,
    product_code_format_mismatch: bool,
    mixed_type_positions:       List[int],
    qty_mismatch_positions:     List[int],
    type_mismatch_positions:    List[int],
) -> Dict[str, str]:
    """Return {"option_id": ..., "basis": ...} for the primary recommendation."""
    option_ids = {o.option_id for o in options}

    if "NO_ACTION" in option_ids:
        return {
            "option_id": "NO_ACTION",
            "basis": (
                "Posted PZ structure is structurally identical to the authority. "
                "No wFirma interaction required."
            ),
        }

    if qty_mismatch_positions or type_mismatch_positions:
        if "ALIGN_TO_AUTHORITY" in option_ids:
            return {
                "option_id": "ALIGN_TO_AUTHORITY",
                "basis": (
                    f"Quantity or item-type discrepancies detected on positions "
                    f"{sorted(set(qty_mismatch_positions + type_mismatch_positions))}. "
                    "Authority alignment corrects these with minimal risk."
                ),
            }

    if structurally_equivalent and product_code_format_mismatch:
        return {
            "option_id": "KEEP_CURRENT",
            "basis": (
                "Structure is correct; only product-code format differs. "
                "The lineage engine handles both formats — keeping avoids "
                "an unnecessary wFirma write."
            ),
        }

    # Fallback: lowest-risk available option
    for preferred in ("NO_ACTION", "KEEP_CURRENT", "ALIGN_TO_AUTHORITY", "SPLIT_TO_STYLE_LEVEL"):
        if preferred in option_ids:
            return {
                "option_id": preferred,
                "basis": "Lowest-risk available option selected by default.",
            }

    return {"option_id": "KEEP_CURRENT", "basis": "No specific recommendation computed."}

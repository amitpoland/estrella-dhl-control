"""
customs_desc_checker.py — AI validation layer for product descriptions.

Compares invoice/packing source data against what the customs description
engine would generate.  Emits ``ReverificationProposal`` entries when the
engine output contains forbidden placeholders or fails to resolve metal/purity.

Architecture (read-only):
  1. Read invoice_lines from documents.db for the batch.
  2. For each line run ``normalize_item_description`` from the engine.
  3. If ``material_pl`` resolves to a forbidden placeholder → emit proposal.
  4. Proposals flow to Inbox via ``write_reverification_proposals_to_audit``.
  5. Human approves with corrected material_pl / description_pl.
  6. Approved correction written to ``audit["description_corrections"][product_code]``.
  7. Next generate-description call applies overrides before passing rows to engine.

BOUNDARIES (HARD):
  - NEVER writes a master row.
  - NEVER modifies the PDF or audit outside the correction application path.
  - NEVER auto-approves.
  - Does not raise — all failures are logged and return an empty proposal list.

FORBIDDEN_MATERIAL_PL: the exact strings that indicate an unresolved metal.
Adding new strings here tightens the net without code changes elsewhere.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── What counts as an unresolved / forbidden material_pl ─────────────────────
FORBIDDEN_MATERIAL_PL: frozenset[str] = frozenset({
    "metal szlachetny",
    "metal z kamienie szlachetne",
    "metal z kamieni szlachetnych",
})

PROP_CUSTOMS_DESC_MISMATCH = "customs_description_mismatch"
REVERIFICATION_CHANNEL     = "ai_reverification"


# ── Engine import ─────────────────────────────────────────────────────────────

def _load_engine():
    """Return customs_description_engine module or None if unavailable."""
    try:
        from ..core.config import settings as _s  # type: ignore
        engine_dir = str(_s.engine_dir)
        if engine_dir not in sys.path:
            sys.path.insert(0, engine_dir)
        import customs_description_engine as cde  # type: ignore
        return cde
    except Exception as exc:
        log.warning("customs_desc_checker: engine import failed (%s)", exc)
        return None


# ── Invoice-line reader ───────────────────────────────────────────────────────

def _get_invoice_lines(batch_id: str) -> List[Dict[str, Any]]:
    """Read invoice_lines for batch from documents.db. Never raises."""
    try:
        from . import document_db as ddb  # type: ignore
        return ddb.get_invoice_lines_for_batch(batch_id) or []
    except Exception as exc:
        log.warning("[%s] customs_desc_checker: invoice_lines read failed: %s", batch_id, exc)
        return []


# ── Core check ────────────────────────────────────────────────────────────────

def check_customs_description_accuracy(
    batch_id:     str,
    audit:        Dict[str, Any],
    storage_root: Path,
) -> List[Dict[str, Any]]:
    """Run description-accuracy check for every invoice line in the batch.

    Returns a list of proposal dicts ready to be appended to
    ``audit["action_proposals"]``.  Empty list = all lines OK.

    For each invoice line:
      - Pass its description through ``normalize_item_description``.
      - If ``material_pl`` is a forbidden placeholder or empty: emit a proposal.

    The proposal carries:
      ``product_code``         — which product has the issue
      ``invoice_no``           — invoice it belongs to
      ``line_position``        — line within invoice
      ``data.source``          — raw invoice description
      ``data.current_material_pl`` — what the engine produced
      ``data.issue``           — machine-readable issue code
      ``data.reason``          — human-readable explanation
      ``data.hint``            — operator action hint
      ``data.proposed_material_pl``     — empty (operator fills in at approval)
      ``data.proposed_description_pl``  — empty (operator fills in at approval)

    Already-active proposals (status=pending_review) for the same
    (batch, product_code) are deduplicated by the caller via
    ``write_reverification_proposals_to_audit``.
    """
    cde = _load_engine()
    if cde is None:
        return []

    lines = _get_invoice_lines(batch_id)
    if not lines:
        return []

    proposals: List[Dict[str, Any]] = []

    for ln in lines:
        desc         = str(ln.get("description") or "").strip()
        product_code = str(ln.get("product_code") or "").strip()
        invoice_no   = str(ln.get("invoice_no")   or "").strip()
        line_pos     = int(ln.get("line_position") or 0)

        if not desc or not product_code:
            continue

        # Skip placeholder rows (qty=0, total=0, desc starts with "(placeholder")
        if (float(ln.get("quantity")    or 0) == 0.0
                and float(ln.get("total_value") or ln.get("amount_usd") or 0) == 0.0
                and desc.startswith("(placeholder")):
            continue

        # Skip lines that already have an approved correction
        corrections = audit.get("description_corrections") or {}
        if product_code in corrections:
            continue

        try:
            norm = cde.normalize_item_description(
                desc,
                item_type        = "",
                hsn_from_invoice = str(ln.get("hsn_code") or ln.get("hs_code") or ""),
            )
        except Exception as exc:
            log.warning(
                "[%s] customs_desc_checker: normalize_item_description failed "
                "for product_code=%r: %s", batch_id, product_code, exc,
            )
            continue

        material_pl = (norm.get("material_pl") or "").strip()

        # Is it forbidden?
        is_forbidden = material_pl in FORBIDDEN_MATERIAL_PL or not material_pl

        if not is_forbidden:
            continue  # this line is fine

        # Emit proposal
        import uuid as _uuid
        from datetime import datetime, timezone

        issue_code = "forbidden_placeholder" if material_pl else "empty_material_pl"
        proposals.append({
            "proposal_id":  str(_uuid.uuid4()),
            "type":         PROP_CUSTOMS_DESC_MISMATCH,
            "channel":      REVERIFICATION_CHANNEL,
            "status":       "pending_review",
            "created_at":   datetime.now(timezone.utc).isoformat(),
            # Targeting
            "product_code": product_code,
            "invoice_no":   invoice_no,
            "line_position": line_pos,
            # Evidence + proposed correction
            "data": {
                "source":               desc,
                "current_material_pl":  material_pl or "(empty)",
                "issue":                issue_code,
                "reason": (
                    f"Engine resolved material_pl to {material_pl!r} — a forbidden "
                    f"placeholder — for invoice line {invoice_no!r} position "
                    f"{line_pos} (product {product_code!r}). "
                    f"Raw description: {desc!r}"
                ),
                "hint": (
                    "Enter the correct Polish purity/material description at approval "
                    "time (e.g. 'platyna próby 950', 'złoto próby 750'). "
                    "The corrected value will be used when the customs PDF is regenerated."
                ),
                # Operator fills these in at approval:
                "proposed_material_pl":     "",
                "proposed_description_pl":  "",
            },
            "confidence": "high",
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "reject_reason": None,
        })

    return proposals


# ── Dedup helper ──────────────────────────────────────────────────────────────

def _already_active(audit: Dict[str, Any], product_code: str) -> bool:
    """True if there is already a pending/approved customs_desc_mismatch proposal
    for this product_code in this batch."""
    for p in (audit.get("action_proposals") or []):
        if (p.get("type") == PROP_CUSTOMS_DESC_MISMATCH
                and p.get("product_code") == product_code
                and p.get("status") in ("pending_review", "approved")):
            return True
    return False


def write_customs_desc_proposals_to_audit(
    audit:     Dict[str, Any],
    proposals: List[Dict[str, Any]],
) -> int:
    """Append proposals to ``audit["action_proposals"]``, dedup by product_code.

    Returns number of proposals actually appended.
    """
    if not proposals:
        return 0

    action_proposals: List[Dict[str, Any]] = audit.setdefault("action_proposals", [])
    added = 0
    for p in proposals:
        pc = p.get("product_code") or ""
        if _already_active(audit, pc):
            continue
        action_proposals.append(p)
        added += 1
    return added


# ── Correction application ────────────────────────────────────────────────────

def apply_description_corrections(audit: Dict[str, Any]) -> None:
    """Apply approved ``description_corrections`` to ``audit["rows"]`` in-place.

    Called by the generate-description route BEFORE passing ``audit`` to the
    engine.  Any row whose ``product_code`` has an entry in
    ``audit["description_corrections"]`` gets its ``material`` and
    ``description`` fields overridden with the operator-approved values.

    This is the ONLY write path for corrections — never called automatically,
    only at generate-description time.
    """
    corrections: Dict[str, Any] = audit.get("description_corrections") or {}
    if not corrections:
        return

    rows: List[Dict[str, Any]] = audit.get("rows") or []
    if not rows:
        return

    patched = 0
    for row in rows:
        pc = str(row.get("product_code") or "")
        if pc not in corrections:
            continue
        corr = corrections[pc]
        # Override the material field the engine reads.  The engine uses
        # row["description"] for all text-based parsing.  We inject a
        # deterministic material token so the engine renders the correct PL.
        override_material = (corr.get("material_pl") or "").strip()
        override_desc_pl  = (corr.get("description_pl") or "").strip()
        if override_material:
            # Persist the corrected values as engine-visible fields.
            row["description_pl"] = override_desc_pl or override_material
            row["material"]       = override_material
            row["_correction_applied"] = True
            patched += 1
            log.info(
                "apply_description_corrections: patched product_code=%r "
                "material_pl=%r", pc, override_material,
            )

    if patched:
        log.info(
            "apply_description_corrections: %d row(s) patched with "
            "operator-approved corrections", patched,
        )

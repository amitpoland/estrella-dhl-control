"""Document Registry readiness authority.

Single source of truth for the per-document **review state** rendered in the
Document Registry. The frontend is a dumb renderer: it displays whatever this
module decides and never invents a state of its own.

Background (root cause this module closes):
  * purchase_packing_list extraction writes packing.db / packing_documents, but
    the Document Registry reads documents.db / shipment_documents — whose
    parser_status/extraction_status were never written back. The registry showed
    "pending" forever even when the parse was complete (RC-1).
  * shipment_documents stored raw parser_status / extraction_status /
    requires_manual_review but nothing derived a single per-document verdict, so
    the Review column was blank (RC-2).

This module is **pure** — it performs no DB or network I/O. Callers pass the
already-resolved facts (the registry row, the effective line count, the
authoritative extraction status when it lives in another store, and a small
contractor context). It returns one of four states with a human reason and a
stable machine code:

    ready | needs_review | blocked | not_applicable

It NEVER returns blank/empty. A registry row always gets a concrete state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

__all__ = [
    "REVIEW_READY",
    "REVIEW_NEEDS_REVIEW",
    "REVIEW_BLOCKED",
    "REVIEW_NOT_APPLICABLE",
    "DocumentReview",
    "derive_document_review",
]

REVIEW_READY = "ready"
REVIEW_NEEDS_REVIEW = "needs_review"
REVIEW_BLOCKED = "blocked"
REVIEW_NOT_APPLICABLE = "not_applicable"

# Document types that carry extracted lines and therefore have a meaningful
# extraction review. Everything else (awb, service_invoice, carnet, legacy
# 'packing', unknown) is "not applicable" for line-extraction review.
_LINE_TYPES = frozenset({
    "purchase_invoice",
    "sales_invoice",
    "purchase_packing_list",
    "sales_packing_list",
})

# Extraction-status vocab observed across the codebase.
_COMPLETE_TOKENS = frozenset({"extracted", "complete", "completed"})
_FAILED_TOKENS = frozenset({"extraction_failed", "failed", "error", "empty"})
_PLACEHOLDER_TOKENS = frozenset({"placeholder"})


@dataclass(frozen=True)
class DocumentReview:
    """The derived review verdict for one Document Registry row."""
    state: str
    reason: str
    code: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "review_state": self.state,
            "review_reason": self.reason,
            "review_code": self.code,
        }


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def derive_document_review(
    row: Dict[str, Any],
    line_count: Optional[int] = None,
    contractor_context: Optional[Dict[str, Any]] = None,
    effective_extraction_status: Optional[str] = None,
) -> DocumentReview:
    """Derive the review verdict for a single Document Registry row.

    Parameters
    ----------
    row
        A ``shipment_documents`` row dict. Reads ``document_type``,
        ``extraction_status``, ``parser_status``, ``requires_manual_review``.
    line_count
        Effective number of extracted lines for the row (from the row's
        authoritative line store), or ``None`` when unknown. A positive line
        count is itself proof that extraction produced data, even when the
        ``shipment_documents`` status column is stale.
    contractor_context
        Optional dict carrying the resolved client/supplier identity for the
        row, e.g. ``{"client_contractor_id": "...", "client_name": "..."}``.
        Used only to flag sales packing lists whose customer is unresolved
        (those cannot become a sales draft). When omitted, the contractor gate
        is skipped (never a false block).
    effective_extraction_status
        The authoritative extraction status when it lives in a store other than
        ``shipment_documents`` (e.g. packing.db / packing_documents for
        purchase packing lists). When provided it overrides the row's own
        ``extraction_status`` for the completeness decision.

    Returns
    -------
    DocumentReview
        Never blank. One of ready / needs_review / blocked / not_applicable.
    """
    dt = _norm(row.get("document_type"))

    # Non-line documents have no extraction review surface.
    if dt not in _LINE_TYPES:
        return DocumentReview(
            REVIEW_NOT_APPLICABLE,
            "No line-extraction review required for this document type",
            "non_line_document",
        )

    raw_ext = _norm(effective_extraction_status) or _norm(row.get("extraction_status"))
    parser = _norm(row.get("parser_status"))
    requires_review = bool(row.get("requires_manual_review"))
    has_lines = isinstance(line_count, int) and line_count > 0

    is_complete = (raw_ext in _COMPLETE_TOKENS) or (parser == "complete")
    is_failed = (raw_ext in _FAILED_TOKENS) or (parser == "failed")
    is_placeholder = raw_ext in _PLACEHOLDER_TOKENS

    # Completion is proven by an explicit complete status OR by the presence of
    # real extracted lines (the authoritative line store is the tie-breaker that
    # corrects a stale 'pending' on shipment_documents — RC-1).
    effective_complete = is_complete or has_lines

    # Genuine failure: status says failed/empty AND no lines were produced.
    if is_failed and not has_lines:
        return DocumentReview(
            REVIEW_BLOCKED,
            "Extraction failed or produced no lines — re-upload or run Recheck",
            "extraction_failed",
        )

    if not effective_complete:
        if is_placeholder:
            return DocumentReview(
                REVIEW_NEEDS_REVIEW,
                "Placeholder extraction (filename only) — run a real parse",
                "placeholder_extraction",
            )
        return DocumentReview(
            REVIEW_NEEDS_REVIEW,
            "Awaiting extraction — run Recheck to parse",
            "awaiting_extraction",
        )

    # ---- effective_complete is True from here ----

    # Sales packing lists cannot become a sales draft without a resolved
    # customer. Surface that explicitly instead of letting the row look "ready"
    # while it is silently dropped from draft creation. Conservative: only
    # blocks when contractor_context is supplied AND shows no resolution.
    if dt == "sales_packing_list" and contractor_context is not None:
        resolved = bool(_norm(contractor_context.get("client_contractor_id"))) or \
            bool(_norm(contractor_context.get("client_name")))
        if not resolved:
            return DocumentReview(
                REVIEW_BLOCKED,
                "Client/contractor unresolved — no sales draft will be created",
                "client_unresolved",
            )

    if requires_review:
        return DocumentReview(
            REVIEW_NEEDS_REVIEW,
            "Flagged for manual review",
            "manual_review_flagged",
        )

    return DocumentReview(
        REVIEW_READY,
        "Extraction complete",
        "ok",
    )

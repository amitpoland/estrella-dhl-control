"""Canonical customer-document byte resolver.

Email / confirmation ask for bytes by type + draft identity. This module owns
NO business mapping — it delegates to the existing Packing List and CMR
authorities only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

SUPPORTED_DOCUMENT_TYPES = frozenset({"packing_list", "cmr"})


def resolve_canonical_document_bytes(
    document_type: str,
    draft_id: int,
    *,
    storage_root: Path,
    proforma_db: Optional[Path] = None,
    carrier_db: Optional[Path] = None,
) -> Tuple[bytes, str]:
    """Return ``(pdf_bytes, filename)`` for a draft-scoped canonical document.

    Raises:
      ValueError: unknown type, missing draft, or document unavailable.
    """
    doc_type = (document_type or "").strip().lower()
    if doc_type not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError(f"Unsupported document_type: {document_type!r}")

    storage_root = Path(storage_root)
    pf_db = Path(proforma_db) if proforma_db else storage_root / "proforma_links.db"

    if doc_type == "packing_list":
        from . import proforma_invoice_link_db as pildb
        from .commercial_packing_list import export_packing_list_pdf_for_draft

        draft = pildb.get_draft_by_id(pf_db, int(draft_id))
        if draft is None:
            raise ValueError(f"draft {draft_id} not found")
        pdf, filename, _document = export_packing_list_pdf_for_draft(
            draft=draft,
            storage_root=storage_root,
        )
        return pdf, filename

    # cmr
    from .commercial_cmr import export_cmr_pdf_for_draft

    if carrier_db is None:
        raise ValueError("carrier_db is required to resolve CMR bytes")
    exported = export_cmr_pdf_for_draft(
        draft_id=int(draft_id),
        storage_root=storage_root,
        proforma_db=pf_db,
        carrier_db=Path(carrier_db),
    )
    if not exported:
        raise ValueError(f"CMR not available for draft {draft_id}")
    return exported

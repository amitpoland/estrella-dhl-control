"""Deterministic short CMR document number.

The CMR transport document needs a human-sized, stable document number. The
underlying authority remains the carrier shipment's own stable identifier
(``export_shipment_id`` = ``carrier_shipments.idempotency_key``, a 64-char
sha256). Printing that verbatim produced an unusable 64-hex CMR number
(``CMR-EJ-92bd984dbdb70c24…``).

This module derives a short, deterministic DISPLAY identifier from that same id
— it introduces NO second numbering authority and NO mutable counter. The full
``export_shipment_id`` stays in the transport projection / audit metadata; only
the short form is printed on the document.

Format (operator-approved, ADR-proforma-cmr-short-number):
    CMR-EJ-<first 10 hex chars of export_shipment_id, uppercased>
e.g. export_shipment_id "92bd984dbdb70c24f5c1bbe5440a7f4b…" → "CMR-EJ-92BD984DBD".

Properties:
  * Deterministic — same id always yields the same number.
  * Rebook-stable — a same-parameters re-book keeps export_shipment_id, so the
    CMR number does not move.
  * Independent of the AWB (tracking_ref) — the AWB is referenced inside the CMR
    (Box 16), never the document number.
  * Honest-missing — no export_shipment_id ⇒ no CMR number (never batch_id).
"""
from __future__ import annotations

from typing import Optional

_PREFIX = "CMR-EJ-"
_SHORT_LEN = 10


def short_export_id(export_shipment_id: Optional[str]) -> Optional[str]:
    """Return the short uppercased token (first 10 chars), or None.

    export_shipment_id is a sha256 hexdigest in practice; taking its first
    ``_SHORT_LEN`` characters preserves uniform distribution. Any non-empty
    string is accepted defensively (uppercased, truncated); empty/None → None.
    """
    if not export_shipment_id:
        return None
    token = str(export_shipment_id).strip()
    if not token:
        return None
    return token[:_SHORT_LEN].upper()


def cmr_document_number(export_shipment_id: Optional[str]) -> Optional[str]:
    """Return the printable CMR document number, or None (honest-missing)."""
    short = short_export_id(export_shipment_id)
    return f"{_PREFIX}{short}" if short else None

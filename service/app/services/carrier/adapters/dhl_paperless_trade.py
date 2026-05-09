"""
dhl_paperless_trade.py — Pure-logic validator for Paperless Trade
attachments to DHL create_shipment.

DL-F3 scope
-----------
Validates a customs-invoice PDF before the live adapter inlines it
into a DHL ``documentImages[]`` payload. Failures are NON-FATAL at
the adapter layer — they suppress the PLT inline and let the
shipment proceed without the attachment. The dashboard surfaces
``paperless_trade_attached=False`` so the operator can chase up.

Hard rules
----------
* No HTTP. No env reads. No FastAPI / coordinator / adapter import.
* Only ``hashlib`` + ``pathlib`` for I/O.
* The full file bytes are read into memory exactly once on a valid
  PDF. The caller is responsible for not retaining the bytes longer
  than the HTTP request.

DHL-documented limit
--------------------
Paperless Trade images must be ≤ 5 MB and (for our DL-F3 surface)
PDF-only. JPG/PNG support is deferred. The 5 MB cap is checked
BEFORE the file is read into memory so an oversize file does not
exhaust process RAM.

Public API
----------
  validate_paperless_trade_pdf(path, *, max_bytes=5*1024*1024)
      -> PLTValidationResult
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


#: DHL's documented Paperless Trade size cap.
PLT_MAX_BYTES: int = 5 * 1024 * 1024


# ── Result type ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PLTValidationResult:
    """Outcome of validating a candidate PLT attachment.

    ``ok=True`` implies all gates passed and ``pdf_bytes`` is the
    full file content. ``reason`` carries a stable lowercase token
    suitable for manifest persistence.
    """
    ok:         bool
    reason:     str
    sha256:     str = ""
    size:       int = 0
    pdf_bytes:  Optional[bytes] = None


# ── Public API ──────────────────────────────────────────────────────────────

def validate_paperless_trade_pdf(
    path: str,
    *,
    max_bytes: int = PLT_MAX_BYTES,
) -> PLTValidationResult:
    """Validate *path* as a Paperless Trade PDF.

    Returns
    -------
    PLTValidationResult — never raises. Failures are signalled via
    ``ok=False`` and a stable ``reason`` token:

      * ``no_path_provided``   — path is empty / whitespace-only
      * ``file_not_found``     — path does not resolve to an existing file
      * ``empty_file``         — file size is 0 bytes
      * ``oversize``           — file size > ``max_bytes``
      * ``not_pdf``            — first 4 bytes are not ``b"%PDF"``
      * ``read_error``         — OS-level read error after size check passed
      * ``ok``                 — all gates passed; ``pdf_bytes`` populated
    """
    if not (path or "").strip():
        return PLTValidationResult(ok=False, reason="no_path_provided")

    p = Path(path)
    try:
        if not p.exists() or not p.is_file():
            return PLTValidationResult(ok=False, reason="file_not_found")
        size = p.stat().st_size
    except OSError:
        return PLTValidationResult(ok=False, reason="file_not_found")

    if size == 0:
        return PLTValidationResult(ok=False, reason="empty_file", size=0)
    if size > int(max_bytes):
        # Size check is FIRST so an oversize file does not get read
        # into memory. The DHL cap is documented as 5 MB.
        return PLTValidationResult(
            ok=False, reason="oversize", size=size,
        )

    try:
        data = p.read_bytes()
    except OSError:
        return PLTValidationResult(
            ok=False, reason="read_error", size=size,
        )

    if not data.startswith(b"%PDF"):
        return PLTValidationResult(
            ok=False, reason="not_pdf", size=size,
        )

    sha = hashlib.sha256(data).hexdigest()
    return PLTValidationResult(
        ok=True, reason="ok",
        sha256=sha, size=size, pdf_bytes=data,
    )

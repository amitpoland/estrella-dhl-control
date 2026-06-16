"""
document_text_quality.py — Image-only / low-text PDF detector.

A single, pure, dependency-light assessment of "does this PDF actually carry
extractable text, or is it a scan / image-only document that the deterministic
text parsers will silently return nothing for?".

Why this exists
---------------
Every existing extraction layer in the platform is text-only:

  * ``pz_import_processor.parse_invoice`` / ``invoice_intake_parser`` —
    ``pdfplumber.extract_text`` only.
  * ``awb_parser.parse_awb_pdf`` — ``pdfplumber`` page text only.
  * ``ai_customs_parser`` — feeds extracted *text* to the model; returns None
    when the page text is empty.
  * ``ai_gateway.call`` — text-in / text-out, no image content path.

So when a DHL waybill / invoice / packing list is a flat scan (image-only
PDF), every layer produces nothing, CIF collapses to UNKNOWN, and nobody is
told *why*. This detector is the gate that decides "the text path has nothing
to work with — escalate to the vision fallback" deterministically, before any
network/AI call is made.

Contract
--------
- Pure. No AI, no network, no writes. Never raises — a broken/locked/missing
  PDF returns ``image_only_pdf=True`` with ``exists``/``error`` set so the
  caller can still decide to try (or skip) vision rather than crash.
- Uses ``pdfplumber`` first, falls back to ``pypdf`` if pdfplumber is absent or
  errors, and degrades to a conservative "treat as image-only" verdict if
  neither can read the file.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
# A page carrying fewer than this many extractable characters is treated as
# having no usable text (headers/footers/stamps alone can leak a few chars even
# on a pure scan).
PAGE_TEXT_MIN_CHARS: int = 20
# A whole document below this many extractable characters across all scanned
# pages is treated as image-only regardless of per-page distribution.
DOC_TEXT_MIN_CHARS: int = 40
# Default number of leading pages to inspect — customs values live on the first
# couple of pages of a waybill/invoice; scanning the whole document is wasteful.
DEFAULT_MAX_PAGES: int = 8

# A loose numeric signal: any run of 2+ digits, optionally with separators. Used
# only to flag "this text has numbers in it at all", never to extract a value.
_NUMERIC_RE = re.compile(r"\d[\d.,]{1,}")


def _extract_per_page_text_pdfplumber(
    pdf_path: str, max_pages: int
) -> Optional[List[str]]:
    """Return per-page extracted text using pdfplumber, or None if pdfplumber is
    unavailable / cannot open the file. Never raises."""
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return None
    try:
        out: List[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:max_pages]:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    out.append("")
        return out
    except Exception as exc:  # locked / corrupt / not-a-pdf
        log.info("[doc_text_quality] pdfplumber failed on %s: %s", pdf_path, exc)
        return None


def _extract_per_page_text_pypdf(
    pdf_path: str, max_pages: int
) -> Optional[List[str]]:
    """Return per-page extracted text using pypdf, or None if pypdf is
    unavailable / cannot open the file. Never raises."""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return None
    try:
        reader = PdfReader(pdf_path)
        out: List[str] = []
        for page in reader.pages[:max_pages]:
            try:
                out.append(page.extract_text() or "")
            except Exception:
                out.append("")
        return out
    except Exception as exc:
        log.info("[doc_text_quality] pypdf failed on %s: %s", pdf_path, exc)
        return None


def assess_pdf_text_quality(
    pdf_path: str,
    expected_labels: Optional[List[str]] = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Dict[str, Any]:
    """Assess whether ``pdf_path`` carries extractable text or is image-only.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF to inspect.
    expected_labels : list[str] | None
        Optional list of labels we'd expect a *text* document of this kind to
        contain (e.g. ["customs", "value", "invoice", "cif"]). Matched
        case-insensitively. Used only to populate ``has_expected_labels`` — it
        is advisory context for the caller, never a hard gate here.
    max_pages : int
        Number of leading pages to scan.

    Returns
    -------
    dict::

        {
          "source_file":          str,
          "exists":               bool,
          "error":                str | None,
          "pages_scanned":        int,
          "extracted_text_chars": int,           # total across scanned pages
          "per_page_chars":       [int, ...],
          "has_numeric_values":   bool,
          "has_expected_labels":  bool,
          "image_only_pdf":       bool,          # THE decision flag
          "text_extractor":       "pdfplumber" | "pypdf" | "none",
        }

    Guarantees
    ----------
    - Never raises.
    - A missing / unreadable file returns ``exists=False`` (or ``error`` set)
      with ``image_only_pdf=True`` so the caller can decide whether to attempt
      the vision fallback rather than crash.
    """
    result: Dict[str, Any] = {
        "source_file": pdf_path,
        "exists": False,
        "error": None,
        "pages_scanned": 0,
        "extracted_text_chars": 0,
        "per_page_chars": [],
        "has_numeric_values": False,
        "has_expected_labels": False,
        "image_only_pdf": True,  # conservative default
        "text_extractor": "none",
    }

    try:
        if not pdf_path or not os.path.isfile(pdf_path):
            result["error"] = "file not found"
            return result
    except Exception as exc:
        result["error"] = f"path check failed: {exc}"
        return result

    result["exists"] = True

    per_page = _extract_per_page_text_pdfplumber(pdf_path, max_pages)
    if per_page is not None:
        result["text_extractor"] = "pdfplumber"
    else:
        per_page = _extract_per_page_text_pypdf(pdf_path, max_pages)
        if per_page is not None:
            result["text_extractor"] = "pypdf"

    if per_page is None:
        # Neither extractor could read the file. We genuinely do not know if it
        # has text — treat as image-only so the vision fallback can attempt it,
        # and record why.
        result["error"] = "no text extractor could read the PDF"
        result["image_only_pdf"] = True
        return result

    per_page_chars = [len((t or "").strip()) for t in per_page]
    total_chars = sum(per_page_chars)
    joined = "\n".join(t or "" for t in per_page)

    result["pages_scanned"] = len(per_page)
    result["per_page_chars"] = per_page_chars
    result["extracted_text_chars"] = total_chars
    result["has_numeric_values"] = bool(_NUMERIC_RE.search(joined))

    if expected_labels:
        low = joined.lower()
        result["has_expected_labels"] = any(
            str(lbl).lower() in low for lbl in expected_labels if lbl
        )

    # Image-only verdict: either the whole document is below the doc threshold,
    # OR every scanned page is individually below the per-page threshold (a
    # multi-page scan where one cover page leaked a stamp's worth of text still
    # counts as image-only).
    if not per_page_chars:
        result["image_only_pdf"] = True
    else:
        result["image_only_pdf"] = (
            total_chars < DOC_TEXT_MIN_CHARS
            or all(c < PAGE_TEXT_MIN_CHARS for c in per_page_chars)
        )

    return result


def needs_vision_fallback(
    quality: Dict[str, Any],
    *,
    value_missing: bool,
) -> Tuple[bool, str]:
    """Decide whether the vision/AI fallback should run for this document.

    The fallback is justified only when BOTH:
      1. the authoritative value the text path was supposed to produce is still
         missing (``value_missing=True`` — e.g. CIF is UNKNOWN), AND
      2. the document is image-only / low-text (so there is a concrete reason
         the text path produced nothing, not merely a parser miss on a
         text-bearing PDF).

    Returning a reason string makes the decision auditable in provenance.

    Parameters
    ----------
    quality : dict
        Output of :func:`assess_pdf_text_quality`.
    value_missing : bool
        Whether the field the text path should have produced is still missing.

    Returns
    -------
    (should_run, reason)
    """
    quality = quality or {}
    if not value_missing:
        return (False, "value already resolved — no fallback needed")

    if not quality.get("exists", False):
        return (
            True,
            "source document unreadable/missing for text extraction — "
            "attempt vision",
        )

    if quality.get("image_only_pdf"):
        chars = quality.get("extracted_text_chars", 0)
        return (
            True,
            f"image-only PDF (only {chars} extractable chars) — text parsers "
            f"cannot produce a value; escalate to vision",
        )

    # The document DOES carry text but the value is still missing. That is a
    # text-parser miss on a text-bearing document, not an image-only case — the
    # vision fallback is not the right tool, and running it would risk
    # double-extracting from a document the text path already saw.
    return (
        False,
        "document carries extractable text — value gap is a text-parse issue, "
        "not an image-only case; vision fallback not applicable",
    )

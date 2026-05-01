"""
attachment_pattern_engine.py — Attachment Document Type Classifier
===================================================================
Classifies email attachments by filename (and optional MIME type) into
structured customs document types.

Extracted as a standalone module from inline classifier logic so it can be
used independently by:
  - email_classifier.py (email-level classification)
  - intelligence_engine.py (doc-level knowledge extraction)
  - routes_intelligence.py (classify endpoint)
  - PZ processor attachment routing

Document types (from ONE_YEAR_ATTACHMENT_INTELLIGENCE.md):
  zc429_sad        — ZC429_<MRN>_1_PL.pdf  (MRN source — highest automation value)
  dsk              — DSK broker notification (DHL → ACS → Estrella path)
  cesja_form       — FedEx cesja form (requires importer signature)
  pzc              — Potwierdzenie Zgłoszenia Celnego (customs clearance proof)
  ganther_invoice  — Ganther service invoice (FV/Faktura VAT)
  commercial_invoice — Supplier commercial invoice (EJL series)
  acs_vat_statement — ACS monthly VAT statement (billing, not clearance)
  packing_list     — Packing list
  awb_label        — Airway bill / carrier label
  sad_form         — Customs declaration form (non-ZC429)
  unknown          — Unrecognized attachment type

READ-ONLY: No writes to audit or disk. Pure classification function.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Filename patterns (ordered by specificity — most specific first) ──────────

# ZC429 / AIS automated SAD notification
_ZC429_RE   = re.compile(r'^ZC429_([A-Z0-9]+)_\d+_PL\.pdf$', re.IGNORECASE)
# DSK broker notification
_DSK_RE     = re.compile(r'^DSK_', re.IGNORECASE)
# Ganther invoice — FV (Faktura VAT) series
_GANTHER_INV_RE = re.compile(r'^(FV|faktura|invoice_ganther|ganther_fv)', re.IGNORECASE)
# PZC — Potwierdzenie Zgłoszenia Celnego
_PZC_RE     = re.compile(r'pzc|potwierdzenie', re.IGNORECASE)
# FedEx cesja form (importer-signed authorization)
_CESJA_FEDEX_RE = re.compile(r'cesja|cession|authorization_form|power.of.attorney', re.IGNORECASE)
# DHL cesja (forwarded to ACS — not Estrella's document)
_CESJA_DHL_RE   = re.compile(r'cesja_awb|dhl.*cesja', re.IGNORECASE)
# ACS VAT statement (monthly billing)
_ACS_VAT_RE = re.compile(r'vat_statement|oswiadczenie_vat|vat_osw|abf.*vat', re.IGNORECASE)
# Commercial invoice (EJL series)
_COMMERCIAL_INV_RE = re.compile(r'^(EJL|inv|invoice|commercial_invoice|handels)', re.IGNORECASE)
# Packing list
_PACKING_RE = re.compile(r'packing|plist|pakowanie', re.IGNORECASE)
# AWB / air waybill label
_AWB_LABEL_RE = re.compile(r'awb|waybill|label|etikett', re.IGNORECASE)
# SAD / customs declaration form
_SAD_RE     = re.compile(r'^SAD|customs.declaration|deklaracja_celna', re.IGNORECASE)


# ── Document type definitions ──────────────────────────────────────────────────

_DOC_TYPES: Dict[str, Dict[str, Any]] = {
    "zc429_sad": {
        "label":          "ZC429 / SAD (AIS Automated)",
        "carrier":        "DHL",
        "extract_target": "mrn",          # extract MRN from filename
        "should_extract": True,
        "source_trust":   "automated",    # from WinSADMS — reliable
        "contains":       ["mrn", "cif_value", "duty_a00", "importer"],
        "route_to":       "pz_processor", # auto-upload to PZ processor
    },
    "dsk": {
        "label":          "DSK Broker Notification",
        "carrier":        "DHL",
        "extract_target": "batch_reference",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["dsk_reference", "awb"],
        "route_to":       "clearance_file",
    },
    "cesja_form_fedex": {
        "label":          "FedEx Cesja Form (Requires Submission)",
        "carrier":        "FEDEX",
        "extract_target": "awb",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["awb", "importer_fields"],
        "route_to":       "cesja_queue",  # must be submitted to pl-import@fedex.com
        "alert":          "Submit to pl-import@fedex.com within 24h",
    },
    "cesja_form_dhl": {
        "label":          "DHL Cesja (ACS-Handled)",
        "carrier":        "DHL",
        "extract_target": None,
        "should_extract": False,
        "source_trust":   "automated",
        "contains":       ["awb"],
        "route_to":       "acs_clearance", # ACS handles — Estrella does not need to act
    },
    "pzc": {
        "label":          "PZC — Potwierdzenie Zgłoszenia Celnego",
        "carrier":        "BOTH",
        "extract_target": "clearance_date",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["clearance_date", "mrn", "awb"],
        "route_to":       "clearance_file",
    },
    "ganther_invoice": {
        "label":          "Ganther Service Invoice",
        "carrier":        "BOTH",
        "extract_target": "invoice_amount_pln",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["invoice_number", "amount_pln", "vat"],
        "route_to":       "accounting",   # route to account@ for payment
    },
    "acs_vat_statement": {
        "label":          "ACS VAT Statement (Monthly Billing)",
        "carrier":        "DHL",
        "extract_target": "amount_pln",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["period", "amount_pln"],
        "route_to":       "accounting",
        "note":           "Not clearance — route to account@ for bookkeeping",
    },
    "commercial_invoice": {
        "label":          "Supplier Commercial Invoice",
        "carrier":        "BOTH",
        "extract_target": "invoice_total_usd",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["items", "total_usd", "shipper", "incoterms"],
        "route_to":       "pz_processor",
    },
    "packing_list": {
        "label":          "Packing List",
        "carrier":        "BOTH",
        "extract_target": None,
        "should_extract": False,
        "source_trust":   "manual",
        "contains":       ["quantities", "weights"],
        "route_to":       "supporting_docs",
    },
    "awb_label": {
        "label":          "AWB / Carrier Label",
        "carrier":        "BOTH",
        "extract_target": "awb",
        "should_extract": True,
        "source_trust":   "automated",
        "contains":       ["awb", "route"],
        "route_to":       "tracking",
    },
    "sad_form": {
        "label":          "SAD / Customs Declaration",
        "carrier":        "BOTH",
        "extract_target": "mrn",
        "should_extract": True,
        "source_trust":   "manual",
        "contains":       ["mrn", "duty_a00"],
        "route_to":       "pz_processor",
    },
    "unknown": {
        "label":          "Unknown Document Type",
        "carrier":        "UNKNOWN",
        "extract_target": None,
        "should_extract": False,
        "source_trust":   "unknown",
        "contains":       [],
        "route_to":       "manual_review",
    },
}


# ── Core classifier ───────────────────────────────────────────────────────────

def detect_document_type(
    filename: str,
    mime: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classify an attachment by filename (and optional MIME type).

    Args:
        filename: The attachment filename (e.g. "ZC429_26PL44302D005LJ4R0_1_PL.pdf")
        mime:     Optional MIME type (e.g. "application/pdf")

    Returns:
        Dict with:
          type          str   — document type key
          label         str   — human-readable label
          carrier       str   — DHL | FEDEX | BOTH | UNKNOWN
          confidence    str   — high | medium | low
          mrn           str | None — extracted MRN (only for zc429_sad)
          should_extract bool  — whether content extraction is recommended
          extract_target str | None — what to extract from this document
          route_to      str   — where to route this document
          alert         str | None — action alert (e.g. cesja submission)
          contains      list  — known content fields
    """
    fn = filename.strip()

    # ── ZC429 (most specific — exact naming pattern from WinSADMS) ────────────
    m = _ZC429_RE.match(fn)
    if m:
        return _build_result("zc429_sad", "high", mrn=m.group(1))

    # ── DSK ───────────────────────────────────────────────────────────────────
    if _DSK_RE.match(fn):
        return _build_result("dsk", "high")

    # ── FedEx cesja (check before generic cesja) ──────────────────────────────
    if _CESJA_DHL_RE.search(fn):
        return _build_result("cesja_form_dhl", "high")
    if _CESJA_FEDEX_RE.search(fn):
        return _build_result("cesja_form_fedex", "high")

    # ── PZC ───────────────────────────────────────────────────────────────────
    if _PZC_RE.search(fn):
        return _build_result("pzc", "high")

    # ── ACS VAT statement ─────────────────────────────────────────────────────
    if _ACS_VAT_RE.search(fn):
        return _build_result("acs_vat_statement", "high")

    # ── Ganther invoice ───────────────────────────────────────────────────────
    if _GANTHER_INV_RE.match(fn):
        return _build_result("ganther_invoice", "high")

    # ── SAD form (non-ZC429) ──────────────────────────────────────────────────
    if _SAD_RE.match(fn):
        return _build_result("sad_form", "medium")

    # ── Commercial invoice ────────────────────────────────────────────────────
    if _COMMERCIAL_INV_RE.match(fn):
        return _build_result("commercial_invoice", "medium")

    # ── Packing list ──────────────────────────────────────────────────────────
    if _PACKING_RE.search(fn):
        return _build_result("packing_list", "medium")

    # ── AWB label ─────────────────────────────────────────────────────────────
    if _AWB_LABEL_RE.search(fn):
        return _build_result("awb_label", "low")

    # ── MIME fallback — PDF with no pattern match ─────────────────────────────
    if mime and "pdf" in mime.lower():
        return _build_result("unknown", "low",
                             note=f"Unrecognized PDF: {fn}")

    return _build_result("unknown", "low", note=f"Unrecognized: {fn}")


def _build_result(
    doc_type: str,
    confidence: str,
    mrn: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    defn = _DOC_TYPES.get(doc_type, _DOC_TYPES["unknown"])
    result: Dict[str, Any] = {
        "type":           doc_type,
        "label":          defn["label"],
        "carrier":        defn["carrier"],
        "confidence":     confidence,
        "mrn":            mrn,
        "should_extract": defn["should_extract"],
        "extract_target": defn["extract_target"],
        "route_to":       defn["route_to"],
        "alert":          defn.get("alert"),
        "contains":       defn["contains"],
    }
    if note:
        result["note"] = note
    return result


# ── Batch classification ──────────────────────────────────────────────────────

def classify_attachments(
    filenames: List[str],
    mimes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Classify a list of attachments.

    Args:
        filenames: List of attachment filenames
        mimes:     Optional list of MIME types (parallel to filenames)

    Returns:
        List of classification results, one per filename.
    """
    mimes = mimes or [None] * len(filenames)
    return [
        detect_document_type(fn, mime)
        for fn, mime in zip(filenames, mimes)
    ]


def extract_mrns_from_attachments(filenames: List[str]) -> List[str]:
    """
    Extract all MRNs from a list of attachment filenames.
    Returns list of MRN strings (may be empty).
    """
    mrns = []
    for fn in filenames:
        result = detect_document_type(fn)
        if result["mrn"]:
            mrns.append(result["mrn"])
    return mrns


def has_cesja_requiring_action(filenames: List[str]) -> bool:
    """
    Return True if any attachment is a FedEx cesja form (requires importer submission).
    """
    return any(
        detect_document_type(fn)["type"] == "cesja_form_fedex"
        for fn in filenames
    )


def list_all_types() -> Dict[str, str]:
    """Return {type_key: label} for all known document types."""
    return {k: v["label"] for k, v in _DOC_TYPES.items()}

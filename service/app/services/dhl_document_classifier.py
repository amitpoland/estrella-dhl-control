"""
dhl_document_classifier.py — Classify DHL email attachments into document types.

DHL-aware wrapper around customs_doc_classifier that uses email context
(sender, subject, body snippet) for disambiguation. Returns richer classification
with DHL-specific categories.

Pure function — no I/O. Deterministic.

Public API:
    classify_dhl_email_documents(email_record, attachments, audit) -> dict
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .customs_doc_classifier import classify as base_classify


# ── DHL document categories ──────────────────────────────────────────────────

DHL_CESJA_DOC      = "DHL_CESJA_DOC"
DSK_DOCUMENT       = "DSK_DOCUMENT"
SAD_DOCUMENT       = "SAD_DOCUMENT"
PZC_DOCUMENT       = "PZC_DOCUMENT"
ZC429_DOCUMENT     = "ZC429_DOCUMENT"
AWB_DOCUMENT       = "AWB_DOCUMENT"
INVOICE_DOCUMENT   = "INVOICE_DOCUMENT"
POLISH_DESCRIPTION = "POLISH_DESCRIPTION"
UNKNOWN            = "UNKNOWN"

# Filename keyword → DHL category (priority order)
_DHL_FILENAME_RULES: List[tuple[str, str, str]] = [
    ("cesja",        DHL_CESJA_DOC,      "high"),
    ("przekazanie",  DHL_CESJA_DOC,      "high"),
    ("assignment",   DHL_CESJA_DOC,      "medium"),
    ("dsk",          DSK_DOCUMENT,       "high"),
    ("ds_",          DSK_DOCUMENT,       "high"),
    ("broker",       DSK_DOCUMENT,       "medium"),
    ("pzc",          PZC_DOCUMENT,       "high"),
    ("powiadomi",    PZC_DOCUMENT,       "medium"),
    ("sad",          SAD_DOCUMENT,       "high"),
    ("jda",          SAD_DOCUMENT,       "medium"),
    ("zc429",        ZC429_DOCUMENT,     "high"),
    ("zc_429",       ZC429_DOCUMENT,     "high"),
    ("mrn",          SAD_DOCUMENT,       "medium"),
    ("awb",          AWB_DOCUMENT,       "high"),
    ("waybill",      AWB_DOCUMENT,       "medium"),
    ("airway",       AWB_DOCUMENT,       "medium"),
    ("lotniczy",     AWB_DOCUMENT,       "medium"),
    ("invoice",      INVOICE_DOCUMENT,   "high"),
    ("faktura",      INVOICE_DOCUMENT,   "high"),
    ("fv",           INVOICE_DOCUMENT,   "medium"),
    ("ejl",          INVOICE_DOCUMENT,   "medium"),
    ("polish_desc",  POLISH_DESCRIPTION, "high"),
    ("description",  POLISH_DESCRIPTION, "medium"),
    ("opis",         POLISH_DESCRIPTION, "high"),
    ("opis_towaru",  POLISH_DESCRIPTION, "high"),
]

# Body/subject keywords → boost confidence or detect doc types
_BODY_AWB_RE   = re.compile(r"\bAWB[\s:]*(\d{10})\b", re.IGNORECASE)
_BODY_TICKET_RE = re.compile(r"T#\d+[A-Z]*\d+", re.IGNORECASE)
_BODY_CIF_RE   = re.compile(r"(?:CIF|Value)[:\s]*(?:USD|EUR)\s*[\d,.]+", re.IGNORECASE)
_BODY_MRN_RE   = re.compile(r"\b\d{2}PL\d{11,14}[A-Z0-9]*\b")
_BODY_INV_RE   = re.compile(r"(?:EJL|INV|FV)[-/]?\d{2,4}[-/]\d{2,4}", re.IGNORECASE)

_BODY_DOC_KEYWORDS = [
    ("dokumenty do cesji",                  DHL_CESJA_DOC),
    ("cesja praw",                          DHL_CESJA_DOC),
    ("dsk",                                 DSK_DOCUMENT),
    ("po dokonanej odprawie",               PZC_DOCUMENT),
    ("przesłanie pzc",                      PZC_DOCUMENT),
    ("pzc",                                 PZC_DOCUMENT),
    ("zc429",                               ZC429_DOCUMENT),
    ("sad",                                 SAD_DOCUMENT),
]


# ── Public API ───────────────────────────────────────────────────────────────

def classify_dhl_email_documents(
    email_record: Dict[str, Any],
    attachments: List[str],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Classify DHL email attachments and validate against shipment audit.

    Args:
        email_record: normalised email (subject, from, body_text, attachments[])
        attachments:  list of downloaded file paths
        audit:        shipment audit dict

    Returns:
        {
            awb_match: bool,
            ticket_match: bool | None,
            invoice_matches: [...],
            cif_match: bool | None,
            mrn_detected: str | None,
            document_types: [...],
            classified_files: [{file, dhl_type, base_type, confidence}, ...],
            complete_for_agency_forward: bool,
            missing: [...],
            risk_flags: [...],
            confidence: "high" | "medium" | "low",
        }
    """
    subject   = email_record.get("subject") or ""
    body      = email_record.get("body_text") or ""
    text_blob = f"{subject}\n{body}".lower()

    audit_awb    = _get_audit_awb(audit)
    audit_ticket = _get_audit_ticket(audit)
    audit_cif    = _get_audit_cif(audit)

    # ── Classify each attachment ─────────────────────────────────────────────
    classified_files: List[Dict[str, str]] = []
    doc_types_found: List[str] = []

    for fpath in attachments:
        fname = Path(fpath).name
        cls = _classify_single(fname, text_blob)
        cls["file_path"] = fpath
        classified_files.append(cls)
        if cls["dhl_type"] != UNKNOWN:
            doc_types_found.append(cls["dhl_type"])

    # ── Extract references from email text ───────────────────────────────────
    awb_refs     = _BODY_AWB_RE.findall(text_blob)
    ticket_refs  = _BODY_TICKET_RE.findall(text_blob)
    cif_refs     = _BODY_CIF_RE.findall(text_blob)
    mrn_refs     = _BODY_MRN_RE.findall(text_blob)
    inv_refs     = _BODY_INV_RE.findall(text_blob)

    # ── Validate AWB match ───────────────────────────────────────────────────
    awb_match = False
    if audit_awb:
        awb_match = audit_awb in awb_refs or audit_awb in subject

    # ── Validate ticket match ────────────────────────────────────────────────
    ticket_match: Optional[bool] = None
    if audit_ticket and ticket_refs:
        ticket_lower = audit_ticket.lower()
        ticket_match = any(ticket_lower in t.lower() for t in ticket_refs)
    elif audit_ticket:
        ticket_match = audit_ticket.lower() in text_blob

    # ── CIF match (within 5% tolerance) ──────────────────────────────────────
    cif_match: Optional[bool] = None
    if audit_cif and cif_refs:
        for cref in cif_refs:
            amount = _extract_amount(cref)
            if amount and abs(amount - audit_cif) / max(audit_cif, 1) < 0.05:
                cif_match = True
                break
        if cif_match is None:
            cif_match = False

    # ── Invoice number overlap ───────────────────────────────────────────────
    invoice_matches = list(set(inv_refs))

    # ── MRN detection ────────────────────────────────────────────────────────
    mrn_detected = mrn_refs[0] if mrn_refs else None

    # ── Completeness check for agency forward ────────────────────────────────
    missing: List[str] = []
    risk_flags: List[str] = []

    has_cesja_or_dsk = any(t in (DHL_CESJA_DOC, DSK_DOCUMENT) for t in doc_types_found)
    has_awb          = any(t == AWB_DOCUMENT for t in doc_types_found) or _audit_has_awb_file(audit)
    has_invoices     = any(t == INVOICE_DOCUMENT for t in doc_types_found) or _audit_has_invoices(audit)
    has_polish_desc  = any(t == POLISH_DESCRIPTION for t in doc_types_found) or _audit_has_polish_desc(audit)

    if not has_cesja_or_dsk:
        missing.append("DHL_CESJA_DOC or DSK_DOCUMENT")
    if not has_awb:
        missing.append("AWB_DOCUMENT")
    if not has_invoices:
        missing.append("INVOICE_DOCUMENT (invoices)")
    if not has_polish_desc:
        missing.append("POLISH_DESCRIPTION")

    complete_for_agency_forward = (has_cesja_or_dsk and has_awb and has_invoices and has_polish_desc)

    # ── Risk flags ───────────────────────────────────────────────────────────
    if not awb_match and audit_awb:
        risk_flags.append("awb_not_found_in_email")
    if ticket_match is False:
        risk_flags.append("ticket_mismatch")
    if cif_match is False:
        risk_flags.append("cif_mismatch")

    # ── Overall confidence ───────────────────────────────────────────────────
    if awb_match and not risk_flags and complete_for_agency_forward:
        confidence = "high"
    elif awb_match and len(risk_flags) <= 1:
        confidence = "medium"
    else:
        confidence = "low"

    # ── Check for PZC/SAD/ZC429 → triggers customs importer ──────────────────
    has_customs_docs = any(t in (SAD_DOCUMENT, PZC_DOCUMENT, ZC429_DOCUMENT) for t in doc_types_found)

    return {
        "awb_match":                   awb_match,
        "ticket_match":                ticket_match,
        "invoice_matches":             invoice_matches,
        "cif_match":                   cif_match,
        "mrn_detected":                mrn_detected,
        "document_types":              list(set(doc_types_found)),
        "classified_files":            classified_files,
        "complete_for_agency_forward": complete_for_agency_forward,
        "has_customs_docs":            has_customs_docs,
        "missing":                     missing,
        "risk_flags":                  risk_flags,
        "confidence":                  confidence,
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _classify_single(filename: str, text_blob: str = "") -> Dict[str, str]:
    """Classify a single file by filename, with email-body boost."""
    fn_lower = filename.lower()

    # DHL-specific filename rules (priority order)
    for kw, dhl_type, conf in _DHL_FILENAME_RULES:
        if kw in fn_lower:
            base = base_classify(filename)
            return {
                "file":       filename,
                "dhl_type":   dhl_type,
                "base_type":  base.get("type", "other"),
                "confidence": conf,
            }

    # Body-keyword boost: if the email body mentions a doc type and
    # the file is a PDF, upgrade from UNKNOWN
    ext = fn_lower.rsplit(".", 1)[-1] if "." in fn_lower else ""
    if ext == "pdf" and text_blob:
        for kw, dhl_type in _BODY_DOC_KEYWORDS:
            if kw in text_blob:
                base = base_classify(filename)
                return {
                    "file":       filename,
                    "dhl_type":   dhl_type,
                    "base_type":  base.get("type", "other"),
                    "confidence": "low",
                }

    # Fall back to base classifier
    base = base_classify(filename)
    base_type = base.get("type", "other")
    dhl_type = _BASE_TO_DHL.get(base_type, UNKNOWN)
    return {
        "file":       filename,
        "dhl_type":   dhl_type,
        "base_type":  base_type,
        "confidence": base.get("confidence", "low"),
    }


_BASE_TO_DHL: Dict[str, str] = {
    "customs_pdf":  SAD_DOCUMENT,
    "customs_xml":  SAD_DOCUMENT,
    "customs_html": SAD_DOCUMENT,
    "invoice":      INVOICE_DOCUMENT,
    "awb":          AWB_DOCUMENT,
    "polish_desc":  POLISH_DESCRIPTION,
    "duty_note":    UNKNOWN,
    "payment":      UNKNOWN,
    "other":        UNKNOWN,
}


def _get_audit_awb(audit: Dict[str, Any]) -> str:
    return str(
        audit.get("tracking_no")
        or audit.get("awb")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )


def _get_audit_ticket(audit: Dict[str, Any]) -> str:
    return str((audit.get("dhl_email") or {}).get("ticket") or "")


def _get_audit_cif(audit: Dict[str, Any]) -> float:
    cd = audit.get("clearance_decision") or {}
    return float(cd.get("total_value_usd") or cd.get("cif_usd") or 0)


def _extract_amount(text: str) -> Optional[float]:
    """Extract a numeric amount from a CIF/Value reference string."""
    nums = re.findall(r"[\d,.]+", text)
    if not nums:
        return None
    try:
        # Handle both 10,366.00 and 10366.00
        raw = nums[-1].replace(",", "")
        return float(raw)
    except (ValueError, IndexError):
        return None


def _audit_has_awb_file(audit: Dict[str, Any]) -> bool:
    return bool((audit.get("inputs") or {}).get("awb"))


def _audit_has_invoices(audit: Dict[str, Any]) -> bool:
    inv = (audit.get("inputs") or {}).get("invoices") or []
    return len(inv) > 0


def _audit_has_polish_desc(audit: Dict[str, Any]) -> bool:
    return bool(
        (audit.get("polish_description") or {}).get("generated")
        or (audit.get("inputs") or {}).get("polish_desc")
    )

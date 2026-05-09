"""
customs_doc_classifier.py — Classify a customs-document filename into a type.

Pure function — no I/O. Deterministic. Used by sad_importer + invoice monitor
to route incoming files into the correct shipment subfolder.
"""
from __future__ import annotations

import re
from typing import Dict


# (lower-case keyword, type, confidence)
_RULES = [
    ("zc429",                 "customs_pdf", "high"),
    ("pzc",                   "customs_pdf", "high"),
    ("sad",                   "customs_pdf", "high"),
    ("dsk",                   "customs_pdf", "high"),
    ("cesja",                 "customs_pdf", "medium"),
    ("polish_desc",           "polish_desc", "high"),
    ("invoice",               "invoice",     "high"),
    ("ejl-",                  "invoice",     "medium"),
    ("inv",                   "invoice",     "medium"),    # INV_*, _inv_, etc.
    ("fv",                    "invoice",     "medium"),    # Polish "Faktura VAT"
    ("awb",                   "awb",         "high"),
    ("tracking",              "awb",         "medium"),
    ("nota",                  "duty_note",   "medium"),
    ("duty",                  "duty_note",   "medium"),
    ("payment",               "payment",     "medium"),
    ("potwierdz",             "payment",     "medium"),
]


def classify(filename: str) -> Dict[str, str]:
    """
    Classify a filename. Returns {file, type, confidence}.

    Rules (in priority order):
      - extension-based: .xml → customs_xml, .html → customs_html
      - filename-keyword based — first match wins
      - fallback: type=other, confidence=low
    """
    if not filename:
        return {"file": "", "type": "unknown", "confidence": "low"}

    fn_lower = filename.lower()
    ext = (fn_lower.rsplit(".", 1)[-1] if "." in fn_lower else "")

    # Extension wins for customs XML/HTML
    if ext == "xml":
        return {"file": filename, "type": "customs_xml",  "confidence": "high"}
    if ext in ("html", "htm"):
        return {"file": filename, "type": "customs_html", "confidence": "high"}

    # DHL WAW agency notification convention:
    #   <AWB>^^^^INVOICE^^_…   <AWB>^^^^MAIL^^_…   <AWB>^^^^OTHERS^^_…
    #   <AWB>.AWB.BOM.GTW.…    ZC429_<MRN>_<n>_PL.(xml|pdf)
    # Tested before the generic keyword scan so the "^^^^" tag wins over
    # any incidental keyword present elsewhere in the filename.
    if "^^^^mail^^" in fn_lower:
        return {"file": filename, "type": "email_evidence", "confidence": "high"}
    if "^^^^others^^" in fn_lower:
        return {"file": filename, "type": "other", "confidence": "high"}
    if "^^^^invoice^^" in fn_lower:
        return {"file": filename, "type": "invoice", "confidence": "high"}
    if ".awb." in fn_lower or fn_lower.startswith("awb_") or "_awb_" in fn_lower:
        return {"file": filename, "type": "awb", "confidence": "high"}

    # Keyword scan
    for kw, doc_type, conf in _RULES:
        if kw in fn_lower:
            return {"file": filename, "type": doc_type, "confidence": conf}

    # Pattern fallback for invoice numbers like EJL-25-26-1247-09-03-26
    if re.search(r"ejl[-/]\d{2}[-/]\d{2}[-/]\d{3,4}", fn_lower):
        return {"file": filename, "type": "invoice", "confidence": "medium"}

    return {"file": filename, "type": "other", "confidence": "low"}

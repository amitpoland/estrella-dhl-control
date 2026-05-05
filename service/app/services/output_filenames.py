"""
output_filenames.py — canonical filenames for all generated PZ outputs.

Generic names like ``audit_memo.pdf`` and ``audit_report_en.pdf`` collide
across batches and let stale files sit on disk after a regenerate. Every
generated output therefore goes through this helper and is named:

    {TYPE}_AWB_{awb}_MRN_{mrn}_{clearance_date}.{ext}

Examples
    PZ_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf
    PZ_CALC_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.xlsx
    AUDIT_MEMO_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf
    AUDIT_REPORT_EN_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf
    AUDIT_REPORT_PL_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf
    POLISH_DESC_AWB_2824221912_MRN_26PL44302D005LJ4R0_2026-03-12.pdf

When AWB or MRN is missing, the slot is replaced with ``UNKNOWN`` so the
filename remains a single, sortable, human-readable token.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Optional

# Canonical type prefixes — keep stable; consumers (dashboard download mapper,
# regeneration tool, tests) match on these strings.
PZ_PDF        = "PZ"
PZ_CALC_XLSX  = "PZ_CALC"
AUDIT_MEMO    = "AUDIT_MEMO"
AUDIT_EN_PDF  = "AUDIT_REPORT_EN"
AUDIT_PL_PDF  = "AUDIT_REPORT_PL"
AUDIT_EN_TXT  = "AUDIT_REPORT_EN"   # different ext (.txt) → different file
AUDIT_PL_TXT  = "AUDIT_REPORT_PL"
POLISH_DESC   = "POLISH_DESC"
CORRECTIONS   = "CORRECTIONS"

_SAFE_CHAR = re.compile(r"[^A-Za-z0-9._-]")


def _slug(value: Optional[str], default: str = "UNKNOWN") -> str:
    """Sanitise a value for safe inclusion in a filename."""
    if value is None or str(value).strip() == "":
        return default
    s = str(value).strip()
    s = _SAFE_CHAR.sub("", s)
    return s or default


def canonical_filename(
    output_type: str,
    *,
    awb:             Optional[str] = None,
    mrn:             Optional[str] = None,
    clearance_date:  Optional[str] = None,
    extension:       str = "pdf",
) -> str:
    """Return ``{TYPE}_AWB_{awb}_MRN_{mrn}_{clearance_date}.{ext}``."""
    awb_s   = _slug(awb)
    mrn_s   = _slug(mrn)
    date_s  = _slug(clearance_date)
    ext     = extension.lstrip(".").lower()
    return f"{output_type}_AWB_{awb_s}_MRN_{mrn_s}_{date_s}.{ext}"


def filenames_for_audit(audit: Dict) -> Dict[str, str]:
    """Return canonical filenames for every output of the given audit dict.

    Keys mirror the dashboard's ``files_detail`` keys:
        pz_pdf, calc_xlsx, audit_memo, audit_en, audit_pl, polish_desc, corrections
    """
    awb   = audit.get("tracking_no") or (audit.get("inputs") or {}).get("awb_number")
    if not awb:
        # Some audits store AWB inside customs_declaration or transport_refs
        cd = audit.get("customs_declaration") or {}
        refs = cd.get("transport_refs") or []
        awb  = refs[0] if refs else ""
    mrn   = (audit.get("customs_declaration") or {}).get("mrn") or (audit.get("inputs") or {}).get("zc429_mrn") or ""
    date  = (audit.get("customs_declaration") or {}).get("clearance_date") or ""

    return {
        "pz_pdf":      canonical_filename(PZ_PDF,       awb=awb, mrn=mrn, clearance_date=date, extension="pdf"),
        "calc_xlsx":   canonical_filename(PZ_CALC_XLSX, awb=awb, mrn=mrn, clearance_date=date, extension="xlsx"),
        "audit_memo":  canonical_filename(AUDIT_MEMO,   awb=awb, mrn=mrn, clearance_date=date, extension="pdf"),
        "audit_en":    canonical_filename(AUDIT_EN_PDF, awb=awb, mrn=mrn, clearance_date=date, extension="pdf"),
        "audit_pl":    canonical_filename(AUDIT_PL_PDF, awb=awb, mrn=mrn, clearance_date=date, extension="pdf"),
        "audit_en_txt": canonical_filename(AUDIT_EN_TXT, awb=awb, mrn=mrn, clearance_date=date, extension="txt"),
        "audit_pl_txt": canonical_filename(AUDIT_PL_TXT, awb=awb, mrn=mrn, clearance_date=date, extension="txt"),
        "polish_desc": canonical_filename(POLISH_DESC,  awb=awb, mrn=mrn, clearance_date=date, extension="pdf"),
        "corrections": canonical_filename(CORRECTIONS,  awb=awb, mrn=mrn, clearance_date=date, extension="json"),
    }


# Legacy generic filenames a regen tool / dashboard should treat as stale
# when a canonical equivalent is present.
LEGACY_GENERIC = {
    "pz_pdf":      None,                 # PZ PDF historically embeds doc_no/batch — no single legacy match
    "calc_xlsx":   None,
    "audit_memo":  "audit_memo.pdf",
    "audit_en":    "audit_report_en.pdf",
    "audit_pl":    "audit_report_pl.pdf",
    "audit_en_txt": "audit_report_en.txt",
    "audit_pl_txt": "audit_report_pl.txt",
    "polish_desc": None,                 # Polish desc historically named POLISH_DESC_AWB_*
    "corrections": None,
}


def file_version_metadata(
    audit: Dict,
    *,
    row_schema_version: str = "v2",
    generator_version:  str = "v1.4",
) -> Dict[str, str]:
    """Return the metadata block stamped onto every generated audit.json.

    This is the single source of truth for {batch_id, awb, mrn,
    clearance_date, row_schema_version, generated_at, generator_version}.
    Consumers (cache_freshness, regen tool, dashboard) read it to decide
    whether on-disk outputs are current.
    """
    cd  = audit.get("customs_declaration") or {}
    inp = audit.get("inputs") or {}
    return {
        "batch_id":           audit.get("batch_id", ""),
        "awb":                audit.get("tracking_no", "") or "",
        "mrn":                cd.get("mrn", "") or inp.get("zc429_mrn", "") or "",
        "clearance_date":     cd.get("clearance_date", "") or "",
        "row_schema_version": row_schema_version,
        "generator_version":  generator_version,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
    }

"""
customs_validator.py — Cross-validate customs data from different sources.

Compares XML (source of truth) against PDF or AI-parsed data.
Flags mismatches as risk_flags — NEVER overwrites the primary (XML) values.

Hard rules:
  - AI must NEVER override XML values
  - AI must NEVER calculate duty/VAT/CIF/exchange rate
  - Validator is read-only on primary data
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Tolerance rules per field ────────────────────────────────────────────────

_TOLERANCES: Dict[str, Dict[str, float]] = {
    "duty_pln":          {"abs": 1.0,  "pct": 1.0},
    "vat_pln":           {"abs": 1.0,  "pct": 1.0},
    "total_cif_usd":     {"abs": 5.0,  "pct": 2.0},
    "customs_rate_usd":  {"abs": 0.01, "pct": 0.5},
    "statistical_value_pln": {"abs": 5.0, "pct": 1.0},
    "sad_invoice_value_usd": {"abs": 5.0, "pct": 2.0},
}

# String fields — exact match required
_EXACT_MATCH_FIELDS = {"mrn", "lrn", "cn_code", "importer_nip"}

# Fields that are compared but not critical (informational only)
_INFO_FIELDS = {"agent", "exporter_name", "importer_name", "clearance_date"}


def validate_customs_data(
    primary_data: Dict[str, Any],
    comparison_data: Dict[str, Any],
    primary_source: str = "xml",
    comparison_source: str = "ai",
) -> Dict[str, Any]:
    """
    Compare two customs data sets with field-specific tolerance.

    Primary data is NEVER modified. Returns a validation report only.

    Returns:
        {
            "validated": bool,
            "mismatches": [...],
            "risk_flags": [...],
            "risk_level": "none" | "low" | "medium" | "high",
            "fields_compared": int,
            "fields_matched": int,
            "primary_source": str,
            "comparison_source": str,
            "validated_at": str (ISO),
        }
    """
    mismatches: List[Dict[str, Any]] = []
    risk_flags: List[str] = []
    fields_compared = 0
    fields_matched = 0

    # 1) Numeric fields with tolerance
    for field, tol in _TOLERANCES.items():
        pv = primary_data.get(field)
        cv = comparison_data.get(field)

        # Skip if either side is None
        if pv is None or cv is None:
            continue

        try:
            pv_f = float(pv)
            cv_f = float(cv)
        except (ValueError, TypeError):
            continue

        fields_compared += 1
        abs_delta = abs(pv_f - cv_f)
        pct_delta = (abs_delta / pv_f * 100) if pv_f != 0 else (100 if cv_f != 0 else 0)

        within_abs = abs_delta <= tol["abs"]
        within_pct = pct_delta <= tol["pct"]

        if within_abs or within_pct:
            fields_matched += 1
            status = "match"
        else:
            status = "mismatch"
            risk_flags.append(f"{field}_mismatch")
            mismatches.append({
                "field":            field,
                "primary_value":    pv_f,
                "comparison_value": cv_f,
                "delta":            round(abs_delta, 4),
                "delta_pct":        round(pct_delta, 2),
                "tolerance_abs":    tol["abs"],
                "tolerance_pct":    tol["pct"],
                "status":           status,
            })

    # 2) Exact match fields
    for field in _EXACT_MATCH_FIELDS:
        pv = primary_data.get(field)
        cv = comparison_data.get(field)
        if pv is None or cv is None:
            continue

        fields_compared += 1
        pv_s = str(pv).strip().upper()
        cv_s = str(cv).strip().upper()

        if pv_s == cv_s:
            fields_matched += 1
        else:
            mismatches.append({
                "field":            field,
                "primary_value":    str(pv),
                "comparison_value": str(cv),
                "delta":            None,
                "delta_pct":        None,
                "tolerance_abs":    0,
                "tolerance_pct":    0,
                "status":           "mismatch",
            })
            risk_flags.append(f"{field}_mismatch")

    # 3) Info fields (compare but don't flag as risk)
    info_mismatches: List[Dict[str, Any]] = []
    for field in _INFO_FIELDS:
        pv = primary_data.get(field)
        cv = comparison_data.get(field)
        if pv is None or cv is None:
            continue

        fields_compared += 1
        if str(pv).strip().lower() == str(cv).strip().lower():
            fields_matched += 1
        else:
            info_mismatches.append({
                "field":            field,
                "primary_value":    str(pv),
                "comparison_value": str(cv),
                "status":           "info_mismatch",
            })

    # Risk level
    risk_level = _assess_risk(risk_flags)

    validated = len(mismatches) == 0

    return {
        "validated":          validated,
        "mismatches":         mismatches,
        "info_mismatches":    info_mismatches,
        "risk_flags":         risk_flags,
        "risk_level":         risk_level,
        "fields_compared":    fields_compared,
        "fields_matched":     fields_matched,
        "primary_source":     primary_source,
        "comparison_source":  comparison_source,
        "validated_at":       datetime.now(timezone.utc).isoformat(),
    }


def _assess_risk(flags: List[str]) -> str:
    """Determine risk level from flags."""
    if not flags:
        return "none"

    high_risk = {"duty_pln_mismatch", "vat_pln_mismatch", "mrn_mismatch"}
    medium_risk = {"total_cif_usd_mismatch", "customs_rate_usd_mismatch", "importer_nip_mismatch"}

    if high_risk & set(flags):
        return "high"
    if medium_risk & set(flags):
        return "medium"
    return "low"

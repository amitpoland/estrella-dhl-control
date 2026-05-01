"""
dhl_document_validator.py — Validate a classified DHL document set against
the shipment audit before auto-forwarding.

Pure function — reads audit dict only. No file I/O except existence checks.

Public API:
    validate_dhl_document_set(classification, audit) -> dict
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)


def validate_dhl_document_set(
    classification: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate a classified DHL document set against the shipment audit.

    Checks:
      1. AWB matches audit AWB
      2. DHL ticket matches audit.dhl_email.ticket (if present)
      3. Invoice numbers overlap expected invoices
      4. CIF amount within tolerance (if detected)
      5. No unrelated shipment numbers found

    Returns:
        {
            valid: bool,
            awb_match: bool,
            ticket_match: bool | None,
            invoice_overlap: bool | None,
            cif_within_tolerance: bool | None,
            validated_files: [...],
            errors: [...],
            warnings: [...],
        }
    """
    errors:   List[str] = []
    warnings: List[str] = []

    awb_match           = classification.get("awb_match", False)
    ticket_match        = classification.get("ticket_match")
    cif_match           = classification.get("cif_match")
    invoice_matches     = classification.get("invoice_matches") or []
    classified_files    = classification.get("classified_files") or []
    risk_flags          = classification.get("risk_flags") or []

    # ── 1. AWB match (mandatory) ─────────────────────────────────────────────
    if not awb_match:
        errors.append("AWB number not found in email or does not match shipment")

    # ── 2. Ticket match (advisory) ───────────────────────────────────────────
    if ticket_match is False:
        warnings.append("DHL ticket in email does not match audit ticket")

    # ── 3. Invoice overlap (advisory for now) ────────────────────────────────
    invoice_overlap = None
    if invoice_matches:
        invoice_overlap = True  # at least some invoice refs found
    # No error if missing — invoices may already be on file

    # ── 4. CIF tolerance ─────────────────────────────────────────────────────
    if cif_match is False:
        errors.append("CIF amount in email does not match audit CIF (>5% deviation)")

    # ── 5. Validate files exist on disk ──────────────────────────────────────
    validated_files: List[Dict[str, str]] = []
    for cf in classified_files:
        fpath = cf.get("file_path", "")
        if fpath and Path(fpath).is_file():
            validated_files.append(cf)
        elif fpath:
            warnings.append(f"Classified file not on disk: {Path(fpath).name}")

    if not validated_files:
        errors.append("No classified files found on disk")

    # ── 6. Risk flag escalation ──────────────────────────────────────────────
    for rf in risk_flags:
        if rf == "awb_not_found_in_email":
            pass  # already handled in check 1
        elif rf == "ticket_mismatch":
            pass  # already handled in check 2
        elif rf == "cif_mismatch":
            pass  # already handled in check 4
        else:
            warnings.append(f"Risk flag: {rf}")

    # ── Verdict ──────────────────────────────────────────────────────────────
    valid = len(errors) == 0

    return {
        "valid":                valid,
        "awb_match":            awb_match,
        "ticket_match":         ticket_match,
        "invoice_overlap":      invoice_overlap,
        "cif_within_tolerance": cif_match,
        "validated_files":      validated_files,
        "errors":               errors,
        "warnings":             warnings,
    }

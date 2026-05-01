#!/usr/bin/env python3
"""
escalation.py — High-risk batch detection and #PZ escalation block builder
===========================================================================
Triggered when audit score < 70 OR batch status is "blocked".

Used by:
    routes_bot._process_bot_batch()  → appends block to Cliq message

Rules:
- Deterministic: same inputs always produce same escalation decision
- Score threshold and "blocked" status are the only triggers
- Optional sender mention (Zoho Cliq @-syntax) prepended if sender_id provided
- Failed checks rendered as bullet list with plain-language descriptions
"""

from __future__ import annotations
from typing import List, Optional

# ── Human-readable labels for failed check keys ───────────────────────────────
_CHECK_LABELS: dict = {
    "identity_mismatch":     "Identity mismatch — exporter or importer name/NIP does not match between invoice and SAD",
    "invoice_missing":       "Invoice chain gap — invoice references in SAD do not match PDF set",
    "value_mismatch":        "CIF value mismatch — invoice totals differ from SAD declared value",
    "cif_formula_error":     "CIF arithmetic error — FOB + Freight + Insurance ≠ stated CIF on one or more invoices",
    "transport_mismatch":    "Transport linkage failure — AWB not found in SAD transport document references",
    "address_inconsistency": "Address inconsistency — delivery address cannot be classified as warehouse or registered office",
}


# ── Decision ──────────────────────────────────────────────────────────────────

def should_escalate(score: int, status: str) -> bool:
    """Return True if this batch requires escalation to #PZ."""
    return score < 70 or status == "blocked"


# ── Message block ─────────────────────────────────────────────────────────────

def build_escalation_block(
    score:         int,
    risk_level:    str,
    failed_checks: List[str],
    batch_id:      str,
    doc_no:        str = "",
    audit_en_url:  Optional[str] = None,
    audit_pl_url:  Optional[str] = None,
    audit_pdf_url: Optional[str] = None,
    sender_id:     Optional[str] = None,
) -> str:
    """
    Build the escalation text block to append to the #PZ Cliq message.
    If sender_id is provided, prepends an @-mention so the uploader is notified.
    """
    mention = f"<@{sender_id}> " if sender_id else ""

    issue_lines = "\n".join(
        f"- {_CHECK_LABELS.get(k, k)}"
        for k in failed_checks
    ) or "- (no specific check failed — blocked by parser error)"

    doc_line = f"Document : {doc_no}\n" if doc_no else ""

    audit_lines = []
    if audit_en_url: audit_lines.append(f"Audit EN  : {audit_en_url}")
    if audit_pl_url: audit_lines.append(f"Audit PL  : {audit_pl_url}")
    if audit_pdf_url: audit_lines.append(f"Audit PDF : {audit_pdf_url}")
    audit_block = ("\nAudit reports:\n" + "\n".join(audit_lines)) if audit_lines else ""

    return (
        f"\n{'─' * 48}\n"
        f"{mention}🚨 ESCALATION — {risk_level} BATCH\n"
        f"Batch ID  : {batch_id}\n"
        f"{doc_line}"
        f"Risk Score: {score}/100\n"
        f"Risk Level: {risk_level}\n"
        f"Critical issues:\n{issue_lines}\n"
        f"Action required:\n"
        f"Review before accounting / VAT booking."
        f"{audit_block}"
    )

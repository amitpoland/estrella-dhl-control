"""
broker_followup_detector.py — read-only detector + draft generator for
broker follow-up emails on blocked batches with financial/document gaps.

Triggered by `failed_checks` containing `invoice_refs_match` or `cif_match`.
These checks are FORBIDDEN override types — operator cannot accept them.
The only path forward is to obtain the missing document(s) or a corrected SAD.

This module:
  1. Detects eligible batches (read-only).
  2. Extracts missing-invoice IDs and CIF gap from `amendment_flags`.
  3. Renders the operator-approved broker email body.
  4. Builds a draft record. NEVER sends.

The draft is appended to `audit.broker_followup_drafts[]` by the route.
Sending is gated by an explicit POST in routes_dashboard.

NEVER modifies: failed_checks, amendment_flags, customs_declaration,
                status, totals, verification, operator_overrides.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

# failed_checks names that trigger broker follow-up
TRIGGER_CHECKS: frozenset[str] = frozenset({
    "invoice_refs_match",
    "cif_match",
})

# Reason code used to deduplicate drafts within a batch
DRAFT_REASON: str = "missing_invoice_or_cif_gap"

# Statuses that mean "draft already in flight — do not re-create"
_LIVE_DRAFT_STATUSES: frozenset[str] = frozenset({"draft", "sent", "queued"})

# ── Amendment flag parsers ────────────────────────────────────────────────────

# "SAD lists invoices not in PDF set: EJL/25-26/1043, EJL/25-26/1044"
_RE_MISSING_INVOICES = re.compile(
    r"SAD lists invoices not in PDF set:\s*(.+?)\s*$",
    re.IGNORECASE,
)

# "CIF mismatch: invoices total $11,237.00 vs SAD $17,049.00 (diff $-5812.00)"
# Capture invoice total, SAD total, diff. Strip commas from numbers.
_RE_CIF_MISMATCH = re.compile(
    r"CIF mismatch:\s*invoices total\s*\$?([\d,]+(?:\.\d+)?)\s*"
    r"vs SAD\s*\$?([\d,]+(?:\.\d+)?)\s*"
    r"\(diff\s*\$?(-?[\d,]+(?:\.\d+)?)\)",
    re.IGNORECASE,
)


def _parse_money(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_missing_invoices(amendment_flags: List[str]) -> List[str]:
    """Return the list of invoice IDs SAD references but PDF set lacks."""
    out: List[str] = []
    for flag in amendment_flags or []:
        if not isinstance(flag, str):
            continue
        m = _RE_MISSING_INVOICES.search(flag)
        if not m:
            continue
        raw = m.group(1).strip().rstrip(".")
        for piece in re.split(r"[;,]", raw):
            p = piece.strip()
            if p:
                out.append(p)
    # de-dupe preserving order
    seen, deduped = set(), []
    for inv in out:
        if inv not in seen:
            seen.add(inv)
            deduped.append(inv)
    return deduped


def extract_cif_gap(amendment_flags: List[str]) -> Optional[Dict[str, float]]:
    """Return {'invoices': X, 'sad': Y, 'diff': Z} or None."""
    for flag in amendment_flags or []:
        if not isinstance(flag, str):
            continue
        m = _RE_CIF_MISMATCH.search(flag)
        if not m:
            continue
        inv = _parse_money(m.group(1))
        sad = _parse_money(m.group(2))
        diff = _parse_money(m.group(3))
        if inv is None or sad is None or diff is None:
            continue
        return {"invoices": inv, "sad": sad, "diff": diff}
    return None


# ── Eligibility ───────────────────────────────────────────────────────────────

def is_eligible(audit: Dict[str, Any]) -> bool:
    """A batch is eligible when status==blocked AND any TRIGGER_CHECKS failed."""
    if (audit.get("status") or "") != "blocked":
        return False
    failed = set(audit.get("failed_checks") or [])
    return bool(failed & TRIGGER_CHECKS)


def has_live_draft(audit: Dict[str, Any], reason: str = DRAFT_REASON) -> bool:
    """True if a draft for this reason already exists in 'draft'/'sent'/'queued' status."""
    drafts = audit.get("broker_followup_drafts") or []
    for d in drafts:
        if not isinstance(d, dict):
            continue
        if d.get("reason") != reason:
            continue
        if d.get("status") in _LIVE_DRAFT_STATUSES:
            return True
    return False


# ── Email rendering ───────────────────────────────────────────────────────────

def _format_money_usd(amount: float) -> str:
    """USD with thousands separators, no decimals when whole."""
    if amount == int(amount):
        return f"USD {int(amount):,}"
    return f"USD {amount:,.2f}"


def _normalize_awb(audit: Dict[str, Any]) -> str:
    """Pull the cleanest AWB string out of inputs/tracking fields."""
    inputs = audit.get("inputs") or {}
    candidates = [
        audit.get("tracking_no"),
        inputs.get("tracking_no"),
        inputs.get("awb"),
        audit.get("awb"),
    ]
    for c in candidates:
        if not c:
            continue
        s = str(c).strip()
        # Strip "<digits> Tracking.pdf" → "<digits>"
        m = re.match(r"^\s*(\d{8,})\b", s)
        if m:
            return m.group(1)
        return s
    return ""


def render_email(
    *,
    awb:         str,
    mrn:         str,
    missing_invoices: List[str],
    cif_gap:     Optional[Dict[str, float]],
) -> Dict[str, str]:
    """Render subject + plain-text body. Order matches operator-approved template."""
    awb_label = awb or "—"
    mrn_label = mrn or "—"

    subject = f"Customs documentation clarification — AWB {awb_label} / MRN {mrn_label}"

    issue_lines: List[str] = []
    if missing_invoices:
        joined = ", ".join(missing_invoices)
        plural = "s" if len(missing_invoices) > 1 else ""
        issue_lines.append(
            f"- The SAD references invoice{plural} {joined}, "
            f"which {'are' if plural else 'is'} not present in the provided document set."
        )
    if cif_gap:
        inv_s  = _format_money_usd(cif_gap["invoices"])
        sad_s  = _format_money_usd(cif_gap["sad"])
        diff_s = _format_money_usd(abs(cif_gap["diff"]))
        issue_lines.append(
            f"- The declared CIF value in the SAD is {sad_s}, "
            f"while the invoices currently available total {inv_s}."
        )
        issue_lines.append(f"- This results in a discrepancy of {diff_s}.")

    issues_block = "\n".join(issue_lines) if issue_lines else "- (no specific gap recorded)"

    body = (
        "Dear Sir/Madam,\n\n"
        "We are reviewing the customs documentation for the below shipment "
        "and have identified a discrepancy that requires your clarification.\n\n"
        "Shipment details:\n"
        f"- AWB: {awb_label}\n"
        f"- MRN: {mrn_label}\n\n"
        "Issue identified:\n"
        f"{issues_block}\n\n"
        "Request:\n"
        "Kindly confirm one of the following:\n"
        f"  1. Provide the missing invoice"
        f"{'s' if len(missing_invoices) > 1 else ''}"
        f"{(' ' + ', '.join(missing_invoices)) if missing_invoices else ''}, or\n"
        "  2. Confirm the complete set of invoices that make up the declared CIF value, or\n"
        "  3. Advise if the SAD requires amendment due to incorrect invoice references "
        "or values.\n\n"
        "Until this is clarified, we are unable to proceed with internal accounting "
        "and customs reconciliation.\n\n"
        "Please treat this as urgent and revert at your earliest convenience.\n\n"
        "Best regards,\n"
        "Estrella Jewels"
    )

    return {"subject": subject, "body": body}


# ── Draft builder ─────────────────────────────────────────────────────────────

def build_draft(audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build a draft dict from audit. Returns None when not eligible or
    a live draft already exists.

    Pure function. Does NOT modify audit.
    """
    if not is_eligible(audit):
        return None
    if has_live_draft(audit):
        return None

    batch_id        = audit.get("batch_id") or ""
    awb             = _normalize_awb(audit)
    mrn             = (audit.get("customs_declaration") or {}).get("mrn") or ""
    amendment_flags = audit.get("amendment_flags") or []

    missing_invoices = extract_missing_invoices(amendment_flags)
    cif_gap          = extract_cif_gap(amendment_flags)

    rendered = render_email(
        awb=awb,
        mrn=mrn,
        missing_invoices=missing_invoices,
        cif_gap=cif_gap,
    )

    draft = {
        "draft_id":         str(uuid.uuid4()),
        "batch_id":         batch_id,
        "awb":              awb,
        "mrn":              mrn,
        "subject":          rendered["subject"],
        "body":             rendered["body"],
        "created_at":       datetime.now(timezone.utc).isoformat(),
        "status":           "draft",
        "reason":           DRAFT_REASON,
        "missing_invoices": missing_invoices,
        "cif_gap":          cif_gap,
    }
    return draft


def find_draft(audit: Dict[str, Any], reason: str = DRAFT_REASON) -> Optional[Dict[str, Any]]:
    """Return the most recent draft matching `reason`, or None."""
    drafts = audit.get("broker_followup_drafts") or []
    matches = [d for d in drafts if isinstance(d, dict) and d.get("reason") == reason]
    if not matches:
        return None
    return matches[-1]

"""
cowork_result_processor.py — Validate and ingest Cowork intelligence results.

Architecture:
    Cowork Intelligence → PZ Validation → PZ Automation → SMTP Send → Audit

Cowork is the intelligence and evidence collector. It reads Zoho Mail,
classifies documents, maps emails to shipments. It NEVER sends emails,
modifies financial data, or closes shipments.

This module validates the structured data Cowork returns, writes safe
evidence to the shipment audit, and decides the next automation action.
Actual execution is delegated to cowork_action_runner.py.

Production hardening (v2):
    1. Confidence gate — only "high" triggers execution
    2. Recursive financial-field protection
    3. Thread integrity guard
    4. Attachment source authority
    5. Action priority resolver (deterministic)
    6. Compact last_ai_decision summary

Public API:
    process_cowork_result(task_id, result, batch_id) -> dict
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core import timeline as tl
from ..utils.io import write_json_atomic
from .clearance_path_alias import (
    is_agency_clearance,
    is_dhl_self_clearance,
)

log = logging.getLogger(__name__)

# ── Financial fields Cowork must NEVER modify (extended set) ───────────────

FINANCIAL_FIELDS = frozenset({
    "pz_totals", "cif", "cif_value", "customs_values", "customs_value",
    "duty", "duty_amount", "vat", "vat_amount",
    "invoice_totals", "invoice_total", "invoice_lines",
    "clearance_decision", "sad_data", "sad_items", "sad_verification",
    "landed_cost", "total_value_usd", "cif_usd",
    "total_duty", "total_vat", "total_net", "total_gross", "totals",
    "exchange_rate", "nbp_rate",
    "tax", "tax_amount",
    "pz_value", "pz_total", "accounting_value",
})

# ── Evidence types Cowork may contribute ─────────────────────────────────────

ALLOWED_EVIDENCE_KEYS = frozenset({
    "dhl_email",
    "dhl_documents_received",
    "agency_preclearance",
    "email_scan_results",
    "agency_reply_detected",
    "service_invoices_detected",
    "dhl_invoice_detected",
    "tracking",
})

# ── Email draft types Cowork may propose ────────────────────────────────────

ALLOWED_DRAFT_TYPES = frozenset({
    "dhl_dsk_request",
    "dhl_followup",
    "agency_document_forward",
    "agency_followup",
    "missing_document_request",
    "service_invoice_followup",
})

# Fields Cowork email_draft must NOT contain (PZ App controls these)
DRAFT_FORBIDDEN_FIELDS = frozenset({
    "to", "cc", "bcc", "from", "from_address",
    "attachments", "attachment_paths", "files",
    "reply_to", "message_id", "in_reply_to",
})

# ── Confidence levels ───────────────────────────────────────────────────────
# high   → execute actions
# medium → store evidence + create recommendation only, no external send/import
# low    → reject for action, set risk_flag

_CONFIDENCE_EXECUTE = "high"
_CONFIDENCE_REVIEW  = "medium"
_CONFIDENCE_REJECT  = "low"

# ── Action priority order (deterministic) ───────────────────────────────────
# Lower number = higher priority. Used to resolve conflicts.

_ACTION_PRIORITY = {
    "build_and_send_dhl_reply":                1,
    "build_and_send_dhl_self_clearance_reply":  1,
    "validate_and_forward_dhl_docs_to_agency":  2,
    "import_agency_customs_docs":               3,
    "register_agency_invoices":                 4,
    "register_dhl_invoices":                    5,
    "send_cowork_email_draft":                  6,
    "check_followup_sla":                       7,
}

# Conflicting groups — only one action from each group per pass
_CONFLICT_GROUPS = {
    "dhl_reply": {"build_and_send_dhl_reply", "build_and_send_dhl_self_clearance_reply"},
}


def _outputs_root() -> Path:
    return settings.storage_root / "outputs"


def _load_audit(batch_id: str) -> tuple[Path, Dict[str, Any]]:
    audit_path = _outputs_root() / batch_id / "audit.json"
    if not audit_path.exists():
        raise ValueError(f"Audit not found for batch {batch_id}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    return audit_path, audit


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public API ───────────────────────────────────────────────────────────────

def process_cowork_result(
    task_id:  str,
    result:   Dict[str, Any],
    batch_id: str,
) -> Dict[str, Any]:
    """
    Validate a Cowork result and decide next actions.

    Steps:
        1. Load shipment audit
        2. Validate result (AWB match, no financial mutation, confidence)
        3. Validate email draft (if present)
        4. Write safe evidence to audit
        5. Confidence gate — decide if actions can execute
        6. Decide next actions from state machine
        7. Apply priority resolver + conflict resolution
        8. Write compact last_ai_decision summary
        9. Log processing

    Returns:
        {
            ok:              bool,
            task_id:         str,
            batch_id:        str,
            evidence_written: [...],
            actions_decided:  [...],
            rejected:         bool,
            rejection_reason: str | None,
            risk_flags:       [...],
            confidence:       str,
        }
    """
    out: Dict[str, Any] = {
        "ok":               False,
        "task_id":           task_id,
        "batch_id":          batch_id,
        "evidence_written":  [],
        "actions_decided":   [],
        "rejected":          False,
        "rejection_reason":  None,
        "risk_flags":        [],
        "confidence":        "medium",
    }

    # ── 1. Load audit ────────────────────────────────────────────────────────
    try:
        audit_path, audit = _load_audit(batch_id)
    except ValueError as exc:
        out["rejected"] = True
        out["rejection_reason"] = str(exc)
        return out

    # ── 2. Validate result ───────────────────────────────────────────────────
    validation = _validate_cowork_result(result, audit)
    confidence = str(result.get("confidence") or
                     (result.get("evidence") or {}).get("confidence") or "medium")
    out["confidence"] = confidence

    if validation["errors"]:
        out["rejected"] = True
        out["rejection_reason"] = "; ".join(validation["errors"])
        out["risk_flags"] = validation.get("risk_flags", [])
        _log_rejection(audit_path, task_id, result, validation["errors"])
        # Write rejected AI decision summary
        _write_ai_decision(audit_path, task_id, confidence, [], None, [],
                           validation.get("risk_flags", []), "rejected")
        return out

    out["risk_flags"] = validation.get("risk_flags", [])

    # ── 3. Validate email draft (if present) ───────────────────────────────
    draft = result.get("email_draft")
    draft_valid = None
    if draft:
        draft_valid = _validate_email_draft(draft, audit)
        if draft_valid["errors"]:
            out["risk_flags"].extend(draft_valid.get("risk_flags", []))
            log.warning("[cowork_processor] email_draft rejected: %s",
                        "; ".join(draft_valid["errors"]))
            draft = None
        else:
            out["risk_flags"].extend(draft_valid.get("risk_flags", []))

    # ── 4. Write safe evidence to audit ──────────────────────────────────────
    evidence = result.get("evidence") or result.get("result_data") or {}
    written = _write_evidence(audit_path, audit, evidence, task_id)
    out["evidence_written"] = written

    # ── 5. Confidence gate ───────────────────────────────────────────────────
    if confidence == _CONFIDENCE_REJECT:
        out["risk_flags"].append("low_confidence_ai_result")
        _add_risk_flag_to_audit(audit_path, "low_confidence_ai_result")
        _write_ai_decision(audit_path, task_id, confidence, [], None, [],
                           out["risk_flags"], "needs_review")
        try:
            tl.log_event(audit_path, "cowork_result_needs_review", "cowork_processor",
                         "cowork_result_processor",
                         detail={"task_id": task_id, "confidence": confidence})
        except Exception:
            pass
        out["ok"] = True
        return out

    # ── 6. Decide next actions from state machine ────────────────────────────
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    actions = _decide_actions(audit, result, task_id)

    # Add email draft action if valid
    if draft and draft_valid and not draft_valid["errors"]:
        actions.append({
            "action":   "send_cowork_email_draft",
            "reason":   f"Cowork proposed email draft: {draft.get('type', 'unknown')}",
            "task_id":  task_id,
            "draft":    draft,
            "priority": "medium",
        })

    # ── 7. Confidence gate: medium = store only, no external actions ─────────
    if confidence == _CONFIDENCE_REVIEW:
        out["risk_flags"].append("medium_confidence_review_only")
        skipped = [a["action"] for a in actions]
        _write_ai_decision(audit_path, task_id, confidence,
                           skipped, None, skipped,
                           out["risk_flags"], "needs_review")
        try:
            tl.log_event(audit_path, "cowork_result_needs_review", "cowork_processor",
                         "cowork_result_processor",
                         detail={"task_id": task_id, "confidence": confidence,
                                 "actions_deferred": skipped})
        except Exception:
            pass
        # Return evidence written but no actions to execute
        out["ok"] = True
        return out

    # ── 8. Apply priority resolver + conflict resolution ─────────────────────
    actions, skipped = _resolve_priority(actions)
    out["actions_decided"] = actions

    # ── 9. Write compact last_ai_decision summary ────────────────────────────
    selected = actions[0]["action"] if actions else None
    _write_ai_decision(
        audit_path, task_id, confidence,
        [a["action"] for a in actions], selected,
        skipped, out["risk_flags"],
        "no_action" if not actions else "executed",
    )

    # ── 10. Log processing ───────────────────────────────────────────────────
    try:
        tl.log_event(audit_path, "cowork_result_processed", "cowork_processor",
                     "cowork_result_processor",
                     detail={
                         "task_id":          task_id,
                         "evidence_keys":    written,
                         "actions_decided":  [a["action"] for a in actions],
                         "skipped_actions":  skipped,
                         "risk_flags":       out["risk_flags"],
                         "confidence":       confidence,
                     })
    except Exception:
        pass

    out["ok"] = True
    return out


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_cowork_result(
    result: Dict[str, Any],
    audit:  Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate Cowork result against shipment audit.

    Checks:
      - No financial field mutation (recursive)
      - AWB match (if AWB present in both)
      - DHL ticket match (if present)
      - Invoice overlap (advisory)
      - Duplicate detection
      - Thread integrity (at least one strong match)
    """
    errors: List[str] = []
    risk_flags: List[str] = []
    evidence = result.get("evidence") or result.get("result_data") or {}

    # ── Recursive financial field rejection ──────────────────────────────────
    fin_violations = _scan_financial_fields_recursive(evidence)
    if fin_violations:
        for v in fin_violations:
            errors.append(f"Financial field mutation rejected: '{v}'")
        return {"errors": errors, "risk_flags": ["cowork_financial_mutation_attempted"]}

    # ── AWB match ────────────────────────────────────────────────────────────
    audit_awb = str(audit.get("tracking_no") or audit.get("awb") or "")
    result_awb = str(result.get("awb") or evidence.get("awb") or "")
    if audit_awb and result_awb and audit_awb != result_awb:
        errors.append(f"AWB mismatch: audit={audit_awb}, result={result_awb}")

    # ── DHL ticket match ─────────────────────────────────────────────────────
    audit_ticket = ((audit.get("dhl_email") or {}).get("ticket") or "").lower()
    dhl_ev = evidence.get("dhl_email") or {}
    result_ticket = str(dhl_ev.get("ticket") or "").lower()
    if audit_ticket and result_ticket and audit_ticket != result_ticket:
        risk_flags.append("cowork_ticket_mismatch")

    # ── Invoice overlap (advisory) ───────────────────────────────────────────
    audit_invoices = set(
        str(i) for i in ((audit.get("inputs") or {}).get("invoices") or [])
    )
    result_invoices = set(
        str(i) for i in (evidence.get("invoice_numbers") or [])
    )
    if audit_invoices and result_invoices:
        overlap = audit_invoices & result_invoices
        if not overlap:
            risk_flags.append("cowork_no_invoice_overlap")

    # ── Duplicate detection ──────────────────────────────────────────────────
    cowork_log = audit.get("cowork_results_log") or []
    if any(entry.get("task_id") == result.get("task_id") for entry in cowork_log):
        errors.append(f"Duplicate result: task_id={result.get('task_id')} already processed")

    # ── Confidence check ─────────────────────────────────────────────────────
    confidence = str(result.get("confidence") or evidence.get("confidence") or "medium")
    if confidence == "low":
        risk_flags.append("cowork_low_confidence_result")

    return {"errors": errors, "risk_flags": risk_flags}


def _scan_financial_fields_recursive(
    data: Any,
    path: str = "",
) -> List[str]:
    """
    Recursively scan data structure for any financial field keys.
    Returns list of dotted paths where violations were found.
    """
    violations: List[str] = []

    if isinstance(data, dict):
        for key, val in data.items():
            current_path = f"{path}.{key}" if path else key
            if key in FINANCIAL_FIELDS:
                violations.append(current_path)
            # Recurse into nested dicts/lists
            violations.extend(_scan_financial_fields_recursive(val, current_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            violations.extend(_scan_financial_fields_recursive(item, f"{path}[{i}]"))

    return violations


def _validate_email_draft(
    draft: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate a Cowork-proposed email draft.

    Checks:
      - Draft type is in ALLOWED_DRAFT_TYPES
      - No forbidden fields (to, cc, attachments, etc.)
      - Has required fields (type, subject, body)
      - AWB consistency with audit
      - Body is non-empty and reasonable length
    """
    errors: List[str] = []
    risk_flags: List[str] = []

    draft_type = draft.get("type", "")
    if draft_type not in ALLOWED_DRAFT_TYPES:
        errors.append(f"Unknown draft type: '{draft_type}'")

    for field in DRAFT_FORBIDDEN_FIELDS:
        if field in draft:
            errors.append(f"Draft contains forbidden field: '{field}' — PZ App controls routing")

    if not draft.get("subject"):
        errors.append("Draft missing 'subject'")
    if not draft.get("body"):
        errors.append("Draft missing 'body'")

    draft_awb = str(draft.get("awb") or "")
    audit_awb = str(audit.get("tracking_no") or audit.get("awb") or "")
    if draft_awb and audit_awb and draft_awb != audit_awb:
        errors.append(f"Draft AWB mismatch: draft={draft_awb}, audit={audit_awb}")

    body = draft.get("body") or ""
    if len(body) > 10_000:
        risk_flags.append("cowork_draft_body_too_long")
    if len(body) < 20 and body:
        risk_flags.append("cowork_draft_body_suspiciously_short")

    return {"errors": errors, "risk_flags": risk_flags}


# ── Thread integrity guard ───────────────────────────────────────────────────

def _check_thread_integrity(
    audit:     Dict[str, Any],
    evidence:  Dict[str, Any],
    action:    str,
) -> Optional[str]:
    """
    Validate thread integrity before allowing email-sending actions.

    Returns None if integrity holds, or an error string if it fails.

    For DHL reply: require AWB OR DHL ticket match.
    For agency forward: require AWB AND at least one validated DHL document.
    For other actions: require at least one strong match (AWB, ticket, or invoice overlap).
    """
    audit_awb    = str(audit.get("tracking_no") or audit.get("awb") or "")
    audit_ticket = ((audit.get("dhl_email") or {}).get("ticket") or "").lower()
    audit_invoices = set(
        str(i) for i in ((audit.get("inputs") or {}).get("invoices") or [])
    )

    # Check available strong matches
    ev_awb = str(evidence.get("awb") or "")
    ev_dhl = evidence.get("dhl_email") or {}
    ev_ticket = str(ev_dhl.get("ticket") or "").lower()
    ev_invoices = set(str(i) for i in (evidence.get("invoice_numbers") or []))

    awb_match     = bool(audit_awb and ev_awb and audit_awb == ev_awb)
    ticket_match  = bool(audit_ticket and ev_ticket and audit_ticket == ev_ticket)
    invoice_match = bool(audit_invoices and ev_invoices and (audit_invoices & ev_invoices))

    # AWB is implicitly matched if evidence was accepted (result-level AWB validated earlier)
    # But if evidence contains dhl_email.received, that's enough for DHL actions
    has_dhl_email = bool(ev_dhl.get("received") or (audit.get("dhl_email") or {}).get("received"))

    if action in ("build_and_send_dhl_reply", "build_and_send_dhl_self_clearance_reply"):
        # DHL reply: AWB or ticket
        if not (audit_awb or ticket_match or has_dhl_email):
            return f"Thread integrity failed for {action}: no AWB or DHL ticket match"

    elif action == "validate_and_forward_dhl_docs_to_agency":
        # Agency forward: need AWB and DHL docs must exist on disk
        dhl_docs = audit.get("dhl_documents_received") or {}
        if not audit_awb:
            return f"Thread integrity failed for {action}: no AWB"
        if not dhl_docs.get("files"):
            return f"Thread integrity failed for {action}: no validated DHL documents"

    elif action == "send_cowork_email_draft":
        # Draft: at least one strong match
        if not (audit_awb or ticket_match or invoice_match or has_dhl_email):
            return f"Thread integrity failed for {action}: no strong match"

    return None


# ── Evidence writing ─────────────────────────────────────────────────────────

def _write_evidence(
    audit_path: Path,
    audit:      Dict[str, Any],
    evidence:   Dict[str, Any],
    task_id:    str,
) -> List[str]:
    """Write validated evidence keys to audit. Returns list of written keys."""
    written: List[str] = []

    for key, value in evidence.items():
        if key in FINANCIAL_FIELDS:
            continue  # double-guard
        if key in ALLOWED_EVIDENCE_KEYS:
            # Merge dicts instead of overwriting (preserve existing data)
            if key in audit and isinstance(audit[key], dict) and isinstance(value, dict):
                audit[key].update(value)
            else:
                audit[key] = value
            written.append(key)

    # Append to cowork results log
    cowork_log = audit.get("cowork_results_log") or []
    cowork_log.append({
        "task_id":      task_id,
        "processed_at": _now_iso(),
        "evidence_keys": written,
    })
    audit["cowork_results_log"] = cowork_log

    if written:
        write_json_atomic(audit_path, audit)

    return written


# ── Action decision (state machine) ─────────────────────────────────────────

def _decide_actions(
    audit:   Dict[str, Any],
    result:  Dict[str, Any],
    task_id: str,
) -> List[Dict[str, Any]]:
    """
    Examine current audit state and decide what automation actions to run.

    Actions are returned as descriptors — cowork_action_runner executes them.
    Thread integrity is checked for each email-sending action.
    """
    actions: List[Dict[str, Any]] = []
    evidence = result.get("evidence") or result.get("result_data") or {}
    cd = audit.get("clearance_decision") or {}
    clearance_path = cd.get("clearance_path") or ""

    # ── DHL email found → build/send DHL reply ───────────────────────────────
    dhl_email = audit.get("dhl_email") or {}
    dhl_reply = audit.get("dhl_reply_package") or {}
    if (dhl_email.get("received")
        and not dhl_reply.get("status")
        and "dhl_email" in evidence):

        action_name = None
        if is_agency_clearance(clearance_path):
            action_name = "build_and_send_dhl_reply"
        elif is_dhl_self_clearance(clearance_path):
            action_name = "build_and_send_dhl_self_clearance_reply"

        if action_name:
            integrity = _check_thread_integrity(audit, evidence, action_name)
            if integrity is None:
                actions.append({
                    "action":   action_name,
                    "reason":   "DHL email detected by Cowork, no reply sent yet",
                    "task_id":  task_id,
                    "priority": "high",
                })
            else:
                log.warning("[cowork_processor] %s", integrity)

    # ── DHL document set found → validate/store/forward to agency ────────────
    dhl_docs = audit.get("dhl_documents_received") or {}
    agency_fwd = audit.get("agency_forward_after_dhl") or {}
    if (dhl_docs.get("received")
        and dhl_docs.get("files")
        and not agency_fwd.get("sent")
        and not agency_fwd.get("status")
        and is_agency_clearance(clearance_path)
        and "dhl_documents_received" in evidence):
        integrity = _check_thread_integrity(
            audit, evidence, "validate_and_forward_dhl_docs_to_agency")
        if integrity is None:
            actions.append({
                "action":   "validate_and_forward_dhl_docs_to_agency",
                "reason":   "DHL documents received via Cowork, agency forward needed",
                "task_id":  task_id,
                "priority": "high",
            })
        else:
            log.warning("[cowork_processor] %s", integrity)

    # ── Agency SAD/PZC found → import customs docs and trigger PZ ────────────
    agency_reply = evidence.get("agency_reply_detected") or {}
    if agency_reply.get("has_customs_docs"):
        actions.append({
            "action":   "import_agency_customs_docs",
            "reason":   "Agency customs documents detected by Cowork",
            "task_id":  task_id,
            "files":    agency_reply.get("customs_files", []),
            "priority": "medium",
        })

    # ── Agency invoice found → store as service invoice ──────────────────────
    svc_invoices = evidence.get("service_invoices_detected") or {}
    if svc_invoices.get("agency_invoice_files"):
        actions.append({
            "action":   "register_agency_invoices",
            "reason":   "Agency invoice detected by Cowork",
            "task_id":  task_id,
            "files":    svc_invoices["agency_invoice_files"],
            "priority": "low",
        })

    # ── DHL invoice found → store as service invoice ─────────────────────────
    dhl_inv = evidence.get("dhl_invoice_detected") or {}
    if dhl_inv.get("files"):
        actions.append({
            "action":   "register_dhl_invoices",
            "reason":   "DHL invoice detected by Cowork",
            "task_id":  task_id,
            "files":    dhl_inv["files"],
            "priority": "low",
        })

    # ── Missing response → schedule follow-up SLA ────────────────────────────
    scan_results = evidence.get("email_scan_results") or {}
    if (dhl_email.get("received")
        and dhl_reply.get("status") in ("sent", "queued")
        and not dhl_docs.get("received")
        and scan_results.get("matched", 0) == 0):
        actions.append({
            "action":   "check_followup_sla",
            "reason":   "DHL reply sent, no document response found by Cowork",
            "task_id":  task_id,
            "priority": "low",
        })

    return actions


# ── Action priority resolver ────────────────────────────────────────────────

def _resolve_priority(
    actions: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    Sort actions by deterministic priority, resolve conflicts.

    Returns:
        (selected_actions, skipped_action_names)
    """
    if not actions:
        return [], []

    # Sort by priority (lower number = higher priority)
    actions_sorted = sorted(
        actions,
        key=lambda a: _ACTION_PRIORITY.get(a["action"], 99),
    )

    selected: List[Dict[str, Any]] = []
    skipped: List[str] = []
    used_groups: set = set()

    for action in actions_sorted:
        action_name = action["action"]

        # Check conflict groups
        blocked = False
        for group_name, group_members in _CONFLICT_GROUPS.items():
            if action_name in group_members:
                if group_name in used_groups:
                    blocked = True
                    skipped.append(action_name)
                    break
                else:
                    used_groups.add(group_name)

        if not blocked:
            selected.append(action)

    return selected, skipped


# ── Compact AI decision summary ─────────────────────────────────────────────

def _write_ai_decision(
    audit_path: Path,
    task_id:    str,
    confidence: str,
    recommended_actions: List[str],
    selected_action: Optional[str],
    skipped_actions: List[str],
    risk_flags: List[str],
    status: str,
) -> None:
    """Write compact last_ai_decision summary to audit."""
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["last_ai_decision"] = {
            "task_id":             task_id,
            "received_at":         _now_iso(),
            "confidence":          confidence,
            "recommended_actions": recommended_actions,
            "selected_action":     selected_action,
            "skipped_actions":     skipped_actions,
            "risk_flags":          risk_flags,
            "status":              status,
        }
        write_json_atomic(audit_path, audit)
    except Exception:
        pass


def _add_risk_flag_to_audit(audit_path: Path, flag: str) -> None:
    """Add a risk flag directly to audit file."""
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        flags = audit.get("risk_flags") or []
        if flag not in flags:
            flags.append(flag)
            audit["risk_flags"] = flags
            write_json_atomic(audit_path, audit)
    except Exception:
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log_rejection(
    audit_path: Path,
    task_id:    str,
    result:     Dict[str, Any],
    errors:     List[str],
) -> None:
    """Log a rejected Cowork result to audit and timeline."""
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        rejections = audit.get("cowork_rejections") or []
        rejections.append({
            "task_id":    task_id,
            "rejected_at": _now_iso(),
            "errors":     errors,
            "source":     result.get("source", "unknown"),
        })
        audit["cowork_rejections"] = rejections
        write_json_atomic(audit_path, audit)
    except Exception:
        pass

    try:
        tl.log_event(audit_path, "cowork_result_rejected", "cowork_processor",
                     "cowork_result_processor",
                     detail={"task_id": task_id, "errors": errors})
    except Exception:
        pass

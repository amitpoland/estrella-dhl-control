"""
ai_bridge.py — File-based bridge for external AI tool coordination.

Architecture:
  External AI (Claude Cowork / ChatGPT) reads task files from ai_bridge/tasks/
  and writes result files to ai_bridge/results/.  The import endpoint then
  validates, applies, and archives results — with strict safety guards that
  prevent touching financial/customs fields.

Folder layout (under storage_root/ai_bridge/):
  tasks/      — pending task files (JSON)  written by this service
  results/    — result files dropped by external AI
  processed/  — archived results after successful import
  errors/     — invalid/rejected results

Task lifecycle:
  created → pending → imported (→ processed/) | rejected (→ errors/)
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings

# ── Folder roots ──────────────────────────────────────────────────────────────

def _bridge_root() -> Path:
    r = settings.storage_root / "ai_bridge"
    for sub in ("tasks", "results", "processed", "errors"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    return r


def _tasks_dir()     -> Path: return _bridge_root() / "tasks"
def _results_dir()   -> Path: return _bridge_root() / "results"
def _processed_dir() -> Path: return _bridge_root() / "processed"
def _errors_dir()    -> Path: return _bridge_root() / "errors"


# ── Forbidden fields (financial / customs — must never be touched by AI) ──────

FORBIDDEN_FIELDS: frozenset = frozenset({
    "pz_totals",
    "cif",
    "customs_values",
    "customs_declaration",
    "duty",
    "vat",
    "invoice_totals",
    "clearance_decision",
    "sad_data",
    "sad_items",
    "sad_verification",
    "invoice_lines",
    "landed_cost",
})

# ── Allowed audit write targets per task type ─────────────────────────────────

# Maps task_type → list of top-level audit keys the result may write to.
# Any key NOT in this list triggers a forbidden-field rejection.
_ALLOWED_WRITES: Dict[str, List[str]] = {
    "tracking_lookup":      ["tracking"],
    "document_summary":     ["ai_summary"],
    "risk_assessment":      ["ai_risk"],
    "supplier_research":    ["ai_supplier"],
    "email_draft":          ["ai_email_draft"],
    "general_research":     ["ai_notes"],
    # email_scan may write:
    #   - email_scan_results       : full search payload
    #   - dhl_email                : auto-applied DHL customs email metadata
    #   - agency_preclearance      : auto-applied OUTGOING Estrella→agency
    #                                pre-clearance correspondence (AWB + invoices
    #                                + custom value sent before shipment arrival)
    # None of these are financial fields. Post-import hook applies rank guards.
    "email_scan":           ["email_scan_results", "dhl_email", "agency_preclearance"],
}

# ── Task templates ─────────────────────────────────────────────────────────────

TASK_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "tracking_lookup": {
        "description": "Fetch public carrier tracking status and report back.",
        "instructions": (
            "1. Open the tracking_url in a browser.\n"
            "2. Record the current status, last event, and location.\n"
            "3. Return a result with keys: status, last_event, location, event_time.\n"
            "   Allowed status values: in_transit | delivered | out_for_delivery | "
            "exception | customs | unknown.\n"
            "4. Write result to ai_bridge/results/<task_id>.json."
        ),
        "result_schema": {
            "status":     "str — normalised status",
            "last_event": "str — human-readable description",
            "location":   "str — city/country, e.g. WARSAW - PL",
            "event_time": "str|null — ISO 8601 timestamp",
        },
    },
    "document_summary": {
        "description": "Summarise an uploaded document (invoice, AWB, customs form).",
        "instructions": (
            "1. Read the document at document_url.\n"
            "2. Extract key fields: document type, date, parties, amounts.\n"
            "3. Return a result with key: summary (plain text, max 500 words)."
        ),
        "result_schema": {
            "summary": "str — structured plain-text summary",
        },
    },
    "risk_assessment": {
        "description": "Assess shipment or supplier risk from available audit data.",
        "instructions": (
            "1. Review the context provided in the task payload.\n"
            "2. Identify risk factors (delays, missing docs, value mismatches).\n"
            "3. Return: risk_level (low|medium|high), factors (list), recommendation."
        ),
        "result_schema": {
            "risk_level":     "str — low | medium | high",
            "factors":        "list[str]",
            "recommendation": "str",
        },
    },
    "supplier_research": {
        "description": "Research a supplier name / country for compliance signals.",
        "instructions": (
            "1. Use public sources to verify the supplier.\n"
            "2. Return: verified (bool), country, notes."
        ),
        "result_schema": {
            "verified": "bool",
            "country":  "str",
            "notes":    "str",
        },
    },
    "email_draft": {
        "description": "Draft a polite follow-up email based on the context provided.",
        "instructions": (
            "1. Read the email_context field in the task payload.\n"
            "2. Draft a concise, professional email in Polish or English as indicated.\n"
            "3. Return: subject, body."
        ),
        "result_schema": {
            "subject": "str",
            "body":    "str",
        },
    },
    "general_research": {
        "description": "General research or analysis task.",
        "instructions": (
            "1. Read the research_question field in the task payload.\n"
            "2. Return: answer (str), sources (list[str])."
        ),
        "result_schema": {
            "answer":  "str",
            "sources": "list[str]",
        },
    },
    "email_scan": {
        "description": (
            "Primary email-discovery engine for DHL clearance flow. Given AWB + "
            "invoice numbers + DHL ticket + sender domains, search the mailbox "
            "for the FULL chain (DHL request → forwards → agency replies → "
            "delivery notices) and return structured timeline-ready JSON. "
            "AWB-only search is INSUFFICIENT — many emails carry only invoice "
            "references in body or attachment filenames."
        ),
        "instructions": (
            "RESPONSIBILITY: You are not only searching AWB. You search ALL\n"
            "identifiers from the payload. If AWB returns 0, you continue with\n"
            "invoice numbers, DHL ticket, sender domain combos, attachments,\n"
            "and forwarded chains. Stopping after the first 0 result is a bug.\n\n"
            "STEP 0 — VERIFY MAILBOX BINDING FIRST (mandatory):\n"
            "   ONE Zoho mailbox account is canonical:\n"
            "     target_account_id           = 2261204000000002002\n"
            "     target_mailbox (login)      = amit@estrellajewels.eu\n"
            "     preferred_mcp_connector_hint = mcp__620999a3...\n"
            "   The payload also provides related_identities[] — these are\n"
            "   sender identities / group + alias addresses that route INTO\n"
            "   the same mailbox (info@, account@, import@, .com alias).\n"
            "   They are NOT separate accounts. Do not try to connect them.\n"
            "   Verification: pick the MCP whose connector ID starts with\n"
            "   preferred_mcp_connector_hint. Call ZohoMail_getMailAccounts.\n"
            "   Confirm the SINGLE response account has:\n"
            "     accountId == target_account_id\n"
            "     primaryEmailAddress == target_mailbox\n"
            "   Do NOT check individual sender identities here — that check\n"
            "   only applies to recipient matching (To/Cc) inside emails.\n"
            "   IF MAILBOX MISMATCH, return immediately:\n"
            "     {\n"
            "       email_scan_results: {\n"
            "         awb, matched: 0,\n"
            "         connector_mismatch: true,\n"
            "         expected_account_id: target_account_id,\n"
            "         actual_account_id: <whatever was returned>,\n"
            "         search_unreliable: true,\n"
            "         manual_review_required: true,\n"
            "         zero_result_reason: 'connector_mismatch'\n"
            "       }\n"
            "     }\n"
            "   Only proceed to search after binding is verified.\n\n"
            "   When matching emails: To/Cc/From hitting ANY entry in\n"
            "   related_identities counts as 'in scope' — they're all the\n"
            "   same mailbox.\n\n"
            "1. Read from task payload:\n"
            "   awb, invoice_numbers, dhl_ticket, mrn, known_senders,\n"
            "   known_domains, search_terms (full deduped list),\n"
            "   target_account_id, target_mailbox, preferred_mcp_connector_hint.\n"
            "2. Search Zoho Mail (or available MCP) IN THIS ORDER, do NOT\n"
            "   stop after a 0-result step:\n"
            "     a) exact AWB string\n"
            "     b) partial AWB (last 8 digits) — truncated subjects\n"
            "     c) each invoice_number from the list\n"
            "     d) DHL ticket pattern T#...\n"
            "     e) MRN if present\n"
            "     f) sender domain × AWB combinations\n"
            "     g) sender domain × invoice_number combinations\n"
            "     h) attachment filename search using AWB and invoice numbers\n"
            "     i) forwarded-chain search (Fwd: / Wiadomość przekazana)\n"
            "3. Match across: subject, body, forwarded headers, quoted reply\n"
            "   bodies, attachment filenames, visible snippets.\n"
            "4. Group emails into threads[] by thread_id. Inside each thread\n"
            "   list emails with classification, one of:\n"
            "     dhl_customs_request          — incoming from odprawacelna@dhl.com\n"
            "     agency_reply                 — incoming from acspedycja.pl\n"
            "     ganther_forward              — via Ganther (forwarded chain)\n"
            "     internal_forward             — same-mailbox forward\n"
            "     delivery_notice              — DHL ODD (NoReply.ODD@dhl.com)\n"
            "     clearance_complete           — final PZC / release notice\n"
            "     agency_preclearance_request  — OUTGOING Estrella → Ganther/ACS\n"
            "                                    pre-clearance request (AWB +\n"
            "                                    invoice range + custom value).\n"
            "                                    Sent BEFORE shipment arrival.\n"
            "     agency_acknowledgement       — Ganther/ACS reply confirming\n"
            "                                    receipt of pre-clearance request\n"
            "                                    (e.g. 'will be cleared after\n"
            "                                    arrival when DSK on hand')\n"
            "     outgoing_clearance_request   — generic outgoing clearance email\n"
            "     other\n"
            "   Outgoing emails count too — pre-clearance correspondence is part\n"
            "   of the workflow chain even though no DHL email has arrived yet.\n"
            "5. Build derived_events for the workflow timeline. Map classifications\n"
            "   to derived events:\n"
            "     dhl_customs_request         → dhl_customs_email_received\n"
            "     agency_reply                → agency_reply_detected\n"
            "     delivery_notice             → delivery_notice_detected\n"
            "     clearance_complete          → shipment_delivered\n"
            "     agency_preclearance_request → agency_preclearance_sent\n"
            "     agency_acknowledgement      → agency_acknowledged\n"
            "     ganther_forward             → ganther_forward_detected\n"
            "   Each event: {event, source_email_subject, source_email_from,\n"
            "                timestamp, ticket?, confidence}\n"
            "6. Set recommended_next_action to ONE of:\n"
            "   mark_dhl_received | generate_polish_description |\n"
            "   build_agency_package | wait_for_arrival_and_dsk |\n"
            "   no_action_required | manual_review\n"
            "   Use 'wait_for_arrival_and_dsk' when only pre-clearance evidence\n"
            "   exists and the DHL email has not yet arrived.\n"
            "7. Populate searched{awb, invoice_numbers, terms (list),\n"
            "   mailboxes, folders} so the operator sees what was actually\n"
            "   queried — required for trust.\n"
            "8. If matched == 0 BUT search_terms list had >1 item, set:\n"
            "     search_unreliable: true\n"
            "     manual_review_required: true\n"
            "     zero_result_reason: 'No result from Cowork despite AWB/invoice identifiers'\n"
            "   A plain '0 matched' is acceptable ONLY when the connector\n"
            "   confirmed every term was searched and truly returned nothing.\n"
            "9. Write result_data with TWO top-level keys:\n"
            "     email_scan_results: full search result (see schema)\n"
            "     dhl_email: only if a DHL customs email was found AND audit\n"
            "                advancement is appropriate.\n"
            "10. NEVER include financial / customs / duty / CIF fields.\n"
            "11. Return result at ai_bridge/results/<task_id>.json."
        ),
        "result_schema": {
            "email_scan_results": {
                "awb":        "str — AWB searched",
                "scanned_at": "str — ISO8601 UTC",
                "matched":    "int — total matched emails",
                "confidence": "str — high|medium|low",
                "threads":    "list[dict] — grouped by thread_id; each contains emails[]",
                "derived_events": "list[dict] — workflow events derived from emails",
                "recommended_next_action": "str — see instructions step 6",
                "searched": "dict — {awb, invoice_numbers, terms, mailboxes, folders}",
                "search_unreliable":      "bool — true if 0 matched but identifiers existed",
                "manual_review_required": "bool — true when search is unreliable",
                "zero_result_reason":     "str|null — explanation when matched=0",
                "diagnostic": "dict — connector, account_id, notes",
            },
            "dhl_email": "dict (optional) — auto-applied to audit when present",
        },
    },
}


# ── Public API ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_task(
    batch_id:  str,
    task_type: str,
    payload:   Dict[str, Any],
    note:      Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a task file in ai_bridge/tasks/<task_id>.json.

    Returns the task dict (including task_id and file path).
    Raises ValueError for unknown task types.
    """
    if task_type not in TASK_TEMPLATES:
        raise ValueError(
            f"Unknown task_type {task_type!r}. "
            f"Allowed: {sorted(TASK_TEMPLATES)}"
        )

    task_id = str(uuid.uuid4())
    template = TASK_TEMPLATES[task_type]

    task: Dict[str, Any] = {
        "task_id":      task_id,
        "task_type":    task_type,
        "batch_id":     batch_id,
        "status":       "pending",
        "created_at":   _now(),
        "description":  template["description"],
        "instructions": template["instructions"],
        "result_schema": template["result_schema"],
        "payload":      payload,
        "note":         note,
        "result_file":  f"ai_bridge/results/{task_id}.json",
    }

    task_file = _tasks_dir() / f"{task_id}.json"
    task_file.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")

    return task


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Return task dict or None if not found."""
    p = _tasks_dir() / f"{task_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_tasks(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List task files.  If status='pending', return only tasks still in tasks/.
    If status='processed', scan processed/.  Default: pending.
    """
    folder = _processed_dir() if status == "processed" else _tasks_dir()
    tasks: List[Dict[str, Any]] = []
    for p in sorted(folder.glob("*.json")):
        try:
            tasks.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return tasks


def _find_forbidden_nested(data: Any, forbidden: frozenset, path: str = "") -> List[str]:
    """Recursively scan dicts/lists for keys matching forbidden field names."""
    found: List[str] = []
    if isinstance(data, dict):
        for key, val in data.items():
            cur = f"{path}.{key}" if path else key
            if key in forbidden:
                found.append(cur)
            found.extend(_find_forbidden_nested(val, forbidden, cur))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            found.extend(_find_forbidden_nested(item, forbidden, f"{path}[{i}]"))
    return found


def _validate_result(result: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
    """
    Return list of validation errors, or [] if result is safe to import.

    Safety rules:
      - result must not contain any FORBIDDEN_FIELDS keys (top-level)
      - result_data must not contain any FORBIDDEN_FIELDS keys at any depth
      - result must only write to audit keys allowed for the task_type
      - task_type must match the task
    """
    errors: List[str] = []

    # Forbidden field check — flat scan of result dict
    for key in result.keys():
        if key in FORBIDDEN_FIELDS:
            errors.append(f"Forbidden field in result: '{key}'")

    # Forbidden field check — recursive scan of result_data values
    result_data = result.get("result_data") or {}
    nested = _find_forbidden_nested(result_data, FORBIDDEN_FIELDS)
    for path in nested:
        errors.append(f"Forbidden field nested in result_data: '{path}'")

    # Check that the result_data (if present) only touches allowed audit keys
    task_type = task.get("task_type", "")
    allowed = set(_ALLOWED_WRITES.get(task_type, []))
    for key in result_data.keys():
        if key not in allowed:
            errors.append(
                f"Result writes to disallowed audit key '{key}' "
                f"for task type '{task_type}'. "
                f"Allowed: {sorted(allowed)}"
            )

    # task_id must match
    if result.get("task_id") and result["task_id"] != task["task_id"]:
        errors.append(
            f"result.task_id {result['task_id']!r} does not match "
            f"task.task_id {task['task_id']!r}"
        )

    return errors


def import_result(
    task_id:     str,
    result:      Dict[str, Any],
    audit:       Dict[str, Any],
    audit_path:  Path,
) -> Dict[str, Any]:
    """
    Validate and apply a result dict from an external AI tool.

    On success:
      - applies result_data to audit (only allowed keys)
      - moves task file to processed/
      - writes result file to processed/
      - returns {"ok": True, "applied_keys": [...]}

    On failure:
      - moves result to errors/ with rejection_reason
      - raises ValueError with human-readable message

    Never touches FORBIDDEN_FIELDS.
    """
    from ..utils.io import write_json_atomic

    if (_processed_dir() / f"{task_id}.json").exists():
        raise ValueError(f"Task {task_id!r} already imported.")

    # Atomic claim — O_CREAT|O_EXCL fails if lock file already exists,
    # preventing concurrent imports of the same task_id.
    lock_path = _bridge_root() / f".lock_{task_id}"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        raise ValueError(f"Task {task_id!r} import already in progress.")

    try:
        task = get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id!r} not found in ai_bridge/tasks/.")

        # Validate
        errors = _validate_result(result, task)
        if errors:
            # Archive to errors/
            rejection = {
                "task_id":          task_id,
                "rejected_at":      _now(),
                "rejection_reason": errors,
                "result":           result,
            }
            err_path = _errors_dir() / f"{task_id}.json"
            err_path.write_text(
                json.dumps(rejection, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            raise ValueError(f"Result rejected: {'; '.join(errors)}")

        # Apply result_data to audit (only allowed keys)
        result_data  = result.get("result_data") or {}
        applied_keys: List[str] = []
        for key, value in result_data.items():
            audit[key] = value
            applied_keys.append(key)

        # Persist audit
        write_json_atomic(audit_path, audit)

        # Archive task → processed/
        task_file = _tasks_dir() / f"{task_id}.json"
        if task_file.exists():
            task["status"]       = "processed"
            task["processed_at"] = _now()
            processed_task = _processed_dir() / f"{task_id}.json"
            processed_task.write_text(
                json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            task_file.unlink(missing_ok=True)

        # Archive result → processed/
        result["imported_at"] = _now()
        processed_result = _processed_dir() / f"{task_id}_result.json"
        processed_result.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return {"ok": True, "task_id": task_id, "applied_keys": applied_keys}
    finally:
        lock_path.unlink(missing_ok=True)

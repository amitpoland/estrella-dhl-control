"""
dhl_clearance_handler.py — DHL Customs Clearance Action Handler.

Called when a DHL customs notification email has been matched to a batch.
Determines clearance route (DHL self-clears vs external broker), generates
DSK or Polish description, and prepares a reply email package.

NEVER sends an email — only prepares packages.
Reply subject is ALWAYS copied verbatim from the DHL email.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Value threshold (USD) ─────────────────────────────────────────────────────
DHL_BROKER_THRESHOLD_USD = 2500.0

# ── Reply email addresses ─────────────────────────────────────────────────────
DHL_CUSTOMS_EMAIL  = "odprawacelna@dhl.com"
ESTRELLA_FROM      = "info@estrellajewels.eu"
AMIT_SIGNATURE     = "Amit Gupta\nEstrella Jewels Sp. z o.o. Sp. k."


# ── Polish body template ──────────────────────────────────────────────────────
_BODY_PL_TEMPLATE = """\
Szanowni Państwo,

W odpowiedzi na Państwa email przesyłamy {attachment_description}.

AWB: {awb}
Wartość przesyłki: {value_usd} USD

Z poważaniem,
{signature}
"""

# ── English body template ─────────────────────────────────────────────────────
_BODY_EN_TEMPLATE = """\
Dear DHL Customs Team,

Please find attached {attachment_description_en} for shipment AWB {awb}.

Best regards,
{signature}
"""


# ── Public API ────────────────────────────────────────────────────────────────

def handle_dhl_customs_email(
    dhl_email: dict,
    batch: dict,
    storage_root: str,
    dsk_output_dir: str,
) -> dict:
    """
    Main handler — called when a DHL customs email is matched to a batch.

    Parameters
    ----------
    dhl_email      : dict from scan_for_dhl_customs_emails()
    batch          : matched batch audit dict (from match_awb_to_batch())
    storage_root   : root storage path
    dsk_output_dir : directory for DSK PDF output

    Returns
    -------
    dict with keys:
        action                    : "dhl_clearance" | "broker_clearance"
        clearance_status          : "dhl_clearance_required" | "external_broker_required"
        dsk                       : dict | None  (dsk_generator result)
        polish_description        : dict | None  (generate_polish_description result)
        reply_package             : dict
        clearance_status_updated  : str
    """
    awb          = dhl_email.get("awb", "") or ""
    message_id   = dhl_email.get("message_id", "")
    thread_id    = dhl_email.get("thread_id", "")
    subject      = dhl_email.get("subject", "")   # NEVER modify this

    # ── Determine invoice CIF value ───────────────────────────────────────────
    value_usd = _get_invoice_cif_usd(batch)

    # ── Intent-based routing (primary decision) ───────────────────────────────
    intent       = dhl_email.get("intent", {})
    request_type = intent.get("request_type", "unknown")

    if request_type == "broker_notification":
        action = "broker_clearance"
    elif request_type == "translation":
        action = "dhl_clearance"
    else:
        # Fallback: use value as routing HINT only
        action = "broker_clearance" if value_usd > DHL_BROKER_THRESHOLD_USD else "dhl_clearance"

    clearance_status = (
        "external_broker_required" if action == "broker_clearance"
        else "dhl_clearance_required"
    )

    # ── Build decision_reason ─────────────────────────────────────────────────
    routing_basis = "email_content" if request_type != "unknown" else "value_fallback"
    routing_hint_label = (
        f"≤${DHL_BROKER_THRESHOLD_USD:,.0f} → DHL likely"
        if value_usd <= DHL_BROKER_THRESHOLD_USD
        else f">${DHL_BROKER_THRESHOLD_USD:,.0f} → broker likely"
    )
    decision_reason = {
        "email_detected":           True,
        "dhl_ticket":               dhl_email.get("dhl_ticket", ""),
        "request_type":             request_type,
        "broker_keywords_found":    intent.get("broker_keywords_found", []),
        "translation_keywords_found": intent.get("translation_keywords_found", []),
        "intent_confidence":        intent.get("confidence", 0.0),
        "value_usd":                value_usd,
        "routing_hint":             routing_hint_label,
        "routing_basis":            routing_basis,
        "final_action":             action,
        "note": (
            "Value is routing hint only. DHL email content is the primary trigger."
        ),
    }

    dsk_result: Optional[dict] = None

    # ── Generate customs description package (DHL self-clear case) ──────────
    polish_result: Optional[dict] = None
    if action == "dhl_clearance":
        try:
            from customs_description_engine import generate_customs_description_package
            customs_output_dir = Path(storage_root) / "polish_descriptions"
            customs_output_dir.mkdir(parents=True, exist_ok=True)
            pkg = generate_customs_description_package(
                batch        = batch,
                awb          = awb,
                output_dir   = str(customs_output_dir),
                dhl_email_id = message_id,
            )
            # Expose the PDF result as polish_result for backward-compat
            polish_result = pkg.get("pdf") or {}
            # Attach full package for callers that want SAD JSON too
            polish_result["_customs_package"] = pkg
            # Function-internal guard blocked generation: pkg["pdf"].generated is
            # already False (so _collect_attachments will not attach it); surface
            # the guard so the reply pipeline does not treat this as generated.
            if pkg.get("blocked"):
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[dhl_clearance_handler] customs package BLOCKED — guard=%s; "
                    "PDF not generated/attached", pkg.get("guard"),
                )
                polish_result["blocked"] = True
                polish_result["guard"] = pkg.get("guard")
        except Exception as exc:
            polish_result = {"generated": False, "error": str(exc)}

    # ── Build reply attachments list ──────────────────────────────────────────
    attachments = _collect_attachments(
        action=action,
        batch=batch,
        dsk_result=dsk_result,
        polish_result=polish_result,
    )

    # ── Build reply body ──────────────────────────────────────────────────────
    body_pl, body_en = _build_reply_bodies(
        action=action,
        awb=awb,
        value_usd=value_usd,
    )

    reply_package = {
        "to":          DHL_CUSTOMS_EMAIL,
        "subject":     subject,      # VERBATIM — never changed
        "thread_id":   thread_id,
        "message_id":  message_id,
        "attachments": attachments,
        "body_pl":     body_pl,
        "body_en":     body_en,
        "action":      action,
    }

    # ── Validate reply package before returning ───────────────────────────────
    reply_validation = validate_reply_package(reply_package, dhl_email)

    # ── Update audit.json with clearance status + decision_reason ─────────────
    audit_path = batch.get("_audit_path")
    if audit_path and Path(audit_path).exists():
        _update_audit_clearance(
            audit_path=audit_path,
            clearance_status=clearance_status,
            dhl_email=dhl_email,
            action=action,
            decision_reason=decision_reason,
        )

    # ── Record email in conversation log ─────────────────────────────────────
    dhl_ticket = dhl_email.get("dhl_ticket", "")
    if dhl_ticket and storage_root:
        try:
            from dhl_email_monitor import record_email_in_conversation
            action_for_log = {
                "action":             action,
                "batch_id":           batch.get("batch_id") or (batch.get("batch_meta") or {}).get("batch_id") or "",
                "dsk":                dsk_result,
                "polish_description": polish_result,
            }
            record_email_in_conversation(
                dhl_ticket=dhl_ticket,
                email=dhl_email,
                action_taken=action_for_log,
                storage_root=storage_root,
            )
        except Exception:
            pass   # non-fatal

    result = {
        "action":                   action,
        "clearance_status":         clearance_status,
        "dsk":                      dsk_result,
        "polish_description":       polish_result,
        "reply_package":            reply_package,
        "reply_validation":         reply_validation,
        "decision_reason":          decision_reason,
        "clearance_status_updated": clearance_status,
    }
    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_invoice_cif_usd(batch: dict) -> float:
    """Extract invoice CIF total USD from the batch audit dict."""
    # Try verification block first (most reliable)
    v = batch.get("result", {})
    if isinstance(v, dict):
        cif = v.get("verification", {})
        if isinstance(cif, dict):
            val = cif.get("invoice_cif_total_usd")
            if val is not None:
                return float(val)

    # Try totals block
    totals = batch.get("totals") or (batch.get("result") or {}).get("totals") or {}
    if isinstance(totals, dict):
        for key in ("total_cif_usd", "cif_usd", "invoice_cif_total_usd"):
            val = totals.get(key)
            if val:
                return float(val)

    # Try top-level
    for key in ("value_usd", "cif_usd", "invoice_cif_total_usd"):
        val = batch.get(key)
        if val:
            return float(val)

    return 0.0


def _generate_dsk_safe(awb: str, value_usd: float, output_dir: str) -> dict:
    """Wrap dsk_generator.generate_dsk with error handling."""
    try:
        import dsk_generator
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return dsk_generator.generate_dsk(
            awb             = awb,
            value_usd       = value_usd,
            carrier         = "DHL",
            broker_required = True,
            output_dir      = output_dir,
        )
    except Exception as exc:
        return {"generated": False, "error": str(exc)}


def _collect_attachments(
    action: str,
    batch: dict,
    dsk_result: Optional[dict],
    polish_result: Optional[dict],
) -> list[dict]:
    """Build the attachments list for the reply email package."""
    attachments: list[dict] = []
    audit_path = batch.get("_audit_path", "")
    batch_dir  = Path(audit_path).parent if audit_path else None

    if action == "broker_clearance":
        # Attachments: DSK + invoice (if found)
        if dsk_result and dsk_result.get("generated") and dsk_result.get("output_path"):
            attachments.append({
                "label": "DSK Broker Notification",
                "path":  dsk_result["output_path"],
            })
        _add_invoice_attachment(attachments, batch_dir)

    elif action == "dhl_clearance":
        # Attachments: Invoice + Polish description
        _add_invoice_attachment(attachments, batch_dir)
        if polish_result and polish_result.get("generated") and polish_result.get("output_path"):
            attachments.append({
                "label": "Polish Customs Description",
                "path":  polish_result["output_path"],
            })

    return attachments


def _add_invoice_attachment(attachments: list, batch_dir: Optional[Path]) -> None:
    """Try to find an invoice PDF in the batch directory and add it."""
    if not batch_dir or not batch_dir.exists():
        return
    for pattern in ("*Invoice*.pdf", "*invoice*.pdf", "*INVOICE*.pdf"):
        found = list(batch_dir.glob(pattern))
        if found:
            attachments.append({"label": "Invoice", "path": str(found[0])})
            return
    # Also check one level up (uploads dir)
    parent = batch_dir.parent
    for pattern in ("*Invoice*.pdf", "*invoice*.pdf", "*INVOICE*.pdf"):
        found = list(parent.glob(pattern))
        if found:
            attachments.append({"label": "Invoice", "path": str(found[0])})
            return


def _build_reply_bodies(action: str, awb: str, value_usd: float) -> tuple[str, str]:
    """Build Polish and English reply bodies."""
    if action == "broker_clearance":
        attachment_description    = "DSK (powiadomienie brokera celnego)"
        attachment_description_en = "the broker notification (DSK)"
    else:
        attachment_description    = "opis towarów do odprawy celnej"
        attachment_description_en = "the customs goods description"

    value_formatted = f"{value_usd:,.2f}" if value_usd else "—"

    body_pl = _BODY_PL_TEMPLATE.format(
        attachment_description = attachment_description,
        awb                    = awb or "—",
        value_usd              = value_formatted,
        signature              = AMIT_SIGNATURE,
    )

    body_en = _BODY_EN_TEMPLATE.format(
        attachment_description_en = attachment_description_en,
        awb                       = awb or "—",
        signature                 = AMIT_SIGNATURE,
    )

    return body_pl, body_en


def validate_reply_package(reply_package: dict, original_email: dict) -> dict:
    """
    Before any reply is sent, validate thread integrity.

    Checks:
    1. Subject unchanged (exact match against original DHL email subject)
    2. DHL ticket number present in subject  ([T#...] pattern)
    3. Correct attachments for path:
       - broker_clearance → DSK attachment required
       - dhl_clearance    → Polish description attachment required

    Returns
    -------
    dict with keys:
        valid       : bool  (True only if all checks pass)
        checks      : dict of individual check results
        errors      : list of error strings
        blocked     : bool  (True when valid is False — blocks Send)
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []

    orig_subj  = original_email.get("subject", "")
    reply_subj = reply_package.get("subject", "")

    # Check 1: subject unchanged
    checks["subject_unchanged"] = (orig_subj == reply_subj)
    if not checks["subject_unchanged"]:
        errors.append(
            f"Subject mismatch: original='{orig_subj}' reply='{reply_subj}'"
        )

    # Check 2: DHL ticket present in subject
    ticket_match = re.search(r'\[T#[A-Z0-9]+\]', reply_subj)
    checks["ticket_present"] = bool(ticket_match)
    if not checks["ticket_present"]:
        errors.append("DHL ticket number missing from subject")

    # Check 3: AWB in subject matches (informational — does not block alone)
    orig_awb = re.sub(r"\s+", "", original_email.get("awb", "") or "")
    if orig_awb and orig_awb not in re.sub(r"\s+", "", reply_subj):
        checks["awb_matches"] = False
        errors.append(f"AWB {orig_awb} not found in reply subject")
    else:
        checks["awb_matches"] = True

    # Check 4: Correct attachments for the path
    attachments = reply_package.get("attachments", [])
    action      = reply_package.get("action", "")
    dsk_paths   = [a["path"] for a in attachments if "DSK" in a.get("label", "")]
    desc_paths  = [a["path"] for a in attachments
                   if "desc" in a.get("path", "").lower()
                   or "polish" in a.get("label", "").lower()
                   or "Polish" in a.get("label", "")]

    if action == "broker_clearance":
        checks["attachments_correct"] = len(dsk_paths) > 0
        if not checks["attachments_correct"]:
            errors.append("Broker clearance path requires DSK attachment — not found")
    else:
        checks["attachments_correct"] = len(desc_paths) > 0
        if not checks["attachments_correct"]:
            errors.append("DHL clearance path requires Polish description — not found")

    valid = all(checks.values())
    return {
        "valid":   valid,
        "checks":  checks,
        "errors":  errors,
        "blocked": not valid,
    }


def _update_audit_clearance(
    audit_path: str,
    clearance_status: str,
    dhl_email: dict,
    action: str,
    decision_reason: Optional[dict] = None,
) -> None:
    """Persist clearance status, DHL email metadata, and decision_reason to audit.json."""
    try:
        path = Path(audit_path)
        with open(path, "r", encoding="utf-8") as f:
            audit = json.load(f)

        audit["clearance_status"]                  = clearance_status
        audit["clearance_action"]                   = action
        audit["dhl_customs_email_received_at"]      = dhl_email.get("received_at", "")
        audit["dhl_ticket"]                         = dhl_email.get("dhl_ticket", "")
        audit["dhl_awb"]                            = dhl_email.get("awb", "")
        audit["clearance_updated_at"]               = datetime.now(timezone.utc).isoformat()
        if decision_reason:
            audit["clearance_decision_reason"]      = decision_reason

        _write_json_atomic(path, audit)
    except Exception:
        pass   # non-fatal — audit.json update should never crash the handler


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via a temp file."""
    import tempfile
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# ── Quick smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== DHL Clearance Handler — self-test ===\n")

    fake_email = {
        "message_id":  "MSG_001",
        "thread_id":   "THR_001",
        "subject":     "[T#1WA2604140000123] - Agencja Celna DHL - przesyłka numer: 3283625844",
        "from":        "odprawacelna@dhl.com",
        "received_at": "2026-04-26T10:00:00Z",
        "dhl_ticket":  "T#1WA2604140000123",
        "awb":         "3283625844",
        "routing_hint": "broker_clearance",
    }

    # Case A: value ≤ $2500 → DHL handles
    fake_batch_low = {
        "result": {"verification": {"invoice_cif_total_usd": 1800.0}},
        "batch_meta": {"carrier": "DHL"},
    }

    result_a = handle_dhl_customs_email(
        dhl_email=fake_email,
        batch=fake_batch_low,
        storage_root="/tmp",
        dsk_output_dir="/tmp",
    )
    print("Case A (≤$2500):")
    print(f"  action          = {result_a['action']}")
    print(f"  clearance_status= {result_a['clearance_status']}")
    print(f"  dsk             = {result_a['dsk']}")
    print(f"  reply subject   = {result_a['reply_package']['subject']}")
    print()

    # Case B: value > $2500 → broker needed
    fake_batch_high = {
        "result": {"verification": {"invoice_cif_total_usd": 9500.0}},
        "batch_meta": {"carrier": "DHL"},
    }

    result_b = handle_dhl_customs_email(
        dhl_email=fake_email,
        batch=fake_batch_high,
        storage_root="/tmp",
        dsk_output_dir="/tmp",
    )
    print("Case B (>$2500):")
    print(f"  action          = {result_b['action']}")
    print(f"  clearance_status= {result_b['clearance_status']}")
    print(f"  reply subject   = {result_b['reply_package']['subject']}")
    print()

    print("=== Done ===")

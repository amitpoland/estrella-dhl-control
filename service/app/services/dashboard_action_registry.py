"""
Dashboard Action V2 — central action registry.

Single source of truth for every dashboard button: stable ID, label, endpoint,
method, auth, enable rule, and disabled-reason. The frontend renders fixed
slots; visible actions stay visible, disabled actions show their reason.

Per approved decisions:
  - Permanent visible slots — disabled actions stay rendered with reason.
  - Recomputed every fetch (no cache).
  - Auth labeled, never changed by this layer.
  - All endpoints must be validatable by route_contract_validator.

Stable ID convention: "<section>.<verb_noun>"
"""
from __future__ import annotations

from typing import Dict, List

from .clearance_path_alias import is_agency_clearance
from .dashboard_action_types import Action, NormalizedState, SECTION_KEYS


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ready_or(reasons: list[str], ready_msg: str = "Ready") -> tuple[bool, str]:
    """Return (enabled, reason). enabled=True iff no reasons; reason joined for display."""
    reasons = [r for r in reasons if r]
    if not reasons:
        return True, ready_msg
    return False, " · ".join(reasons)


def _state_label(enabled: bool, done: bool = False, blocked: bool = False) -> str:
    if blocked: return "blocked"
    if done:    return "done"
    if enabled: return "ready"
    return "pending"


# ── Section builders ───────────────────────────────────────────────────────

def _shipment_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []

    # Re-check tracking — always available
    out.append(Action(
        id       = "shipment.recheck_tracking",
        label    = "↻ Re-check Tracking",
        section  = "shipment",
        style    = "secondary",
        enabled  = True,
        method   = "POST",
        endpoint = f"/dashboard/batches/{s.batch_id}/recheck",
        reason   = "Refresh DHL tracking + re-derive shipment state",
        state    = "ready",
        auth     = "session",
    ))

    # Archive — always available unless terminal
    out.append(Action(
        id       = "shipment.archive",
        label    = "🗄 Archive",
        section  = "shipment",
        style    = "danger",
        enabled  = not s.shipment_terminal or True,  # archive allowed any time
        method   = "DELETE",
        endpoint = f"/dashboard/batches/{s.batch_id}",
        requires_confirmation = True,
        reason   = "Soft-archive (14-day retention)",
        state    = "ready",
        auth     = "session",
    ))

    return out


def _dhl_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []

    # Find DHL emails
    out.append(Action(
        id       = "dhl.find_emails",
        label    = "⌕ Find DHL Emails",
        section  = "dhl_clearance",
        style    = "primary",
        enabled  = True,
        method   = "GET",
        endpoint = f"/api/v1/dhl/scan-inbox?batch_id={s.batch_id}",
        reason   = "Scan Zoho inbox for DHL clearance emails",
        state    = "ready",
        auth     = "session",
    ))

    # Generate Polish description
    pd_done = s.has_polish_description
    pd_enabled, pd_reason = _ready_or(
        ["Already generated — use Download" if pd_done else "",
         "" if s.has_invoice_files else "No invoice files"],
        ready_msg="Generate Polish customs description from invoices",
    )
    out.append(Action(
        id       = "dhl.generate_polish_desc",
        label    = "⊞ Generate Polish Desc.",
        section  = "dhl_clearance",
        style    = "secondary",
        enabled  = pd_enabled and not pd_done,
        method   = "POST",
        endpoint = f"/api/v1/dhl/generate-description/{s.batch_id}",
        reason   = pd_reason,
        state    = _state_label(pd_enabled and not pd_done, done=pd_done),
        auth     = "session",
    ))

    # Download Polish desc
    out.append(Action(
        id       = "dhl.download_polish_desc",
        label    = "↓ Polish Customs Desc.",
        section  = "dhl_clearance",
        style    = "info",
        enabled  = pd_done,
        method   = "GET",
        endpoint = f"/api/v1/dhl/download/{s.polish_desc_filename}" if s.polish_desc_filename else "",
        reason   = "Download generated Polish description PDF" if pd_done else "Polish description not generated yet",
        state    = _state_label(pd_done, done=pd_done),
        auth     = "session",
    ))

    # Generate DSK
    has_cif = s.has_customs_declaration  # CIF is part of customs_declaration
    dsk_done = s.has_dsk_pdf
    dsk_enabled, dsk_reason = _ready_or(
        ["Already generated — use Download" if dsk_done else "",
         "" if has_cif else "Customs/CIF value required (run PZ or recheck first)"],
        ready_msg="Generate DSK transfer document for DHL",
    )
    out.append(Action(
        id       = "dhl.generate_dsk",
        label    = "⊟ Generate DSK",
        section  = "dhl_clearance",
        style    = "secondary",
        enabled  = dsk_enabled and not dsk_done,
        method   = "POST",
        endpoint = "/api/v1/dsk/generate",
        reason   = dsk_reason,
        state    = _state_label(dsk_enabled and not dsk_done, done=dsk_done),
        auth     = "session",
    ))

    # Download DSK — uses /api/v1/dsk/download/<file> (NOT /api/v1/dhl/download — fixes audit item #26)
    out.append(Action(
        id       = "dhl.download_dsk",
        label    = "↓ DSK PDF",
        section  = "dhl_clearance",
        style    = "info",
        enabled  = dsk_done,
        method   = "GET",
        endpoint = f"/api/v1/dsk/download/{s.dsk_filename}" if s.dsk_filename else "",
        reason   = "Download generated DSK transfer PDF" if dsk_done else "DSK not generated yet",
        state    = _state_label(dsk_done, done=dsk_done),
        auth     = "session",
    ))

    # Build DHL reply package
    drp_done = s.dhl_reply_built
    out.append(Action(
        id       = "dhl.build_reply_package",
        label    = "⊡ Build DHL Reply Package",
        section  = "dhl_clearance",
        style    = "secondary",
        enabled  = pd_done and dsk_done and not drp_done,
        method   = "POST",
        endpoint = "/api/v1/dsk/email-package",
        reason   = (
            "Already built" if drp_done else
            "Bundle Polish desc + DSK as DHL reply email" if (pd_done and dsk_done) else
            " · ".join(filter(None, [
                "Polish desc required" if not pd_done else "",
                "DSK required" if not dsk_done else "",
            ])) or "Ready"
        ),
        state    = _state_label(not drp_done and pd_done and dsk_done, done=drp_done),
        auth     = "session",
    ))

    # Send DHL reply — explicit method=smtp body, no MCP fallback (Email Evidence V2)
    drp_send_enabled = s.dhl_reply_built and not s.dhl_reply_sent
    out.append(Action(
        id       = "dhl.send_reply",
        label    = "↗ Queue Reply to DHL",
        section  = "dhl_clearance",
        style    = "primary",
        enabled  = drp_send_enabled,
        method   = "POST",
        endpoint = f"/api/v1/admin/email-queue/{s.dhl_reply_queue_id}/send" if s.dhl_reply_queue_id else "",
        body     = {"method": "smtp"},
        reason   = (
            "Already sent — idempotent" if s.dhl_reply_sent else
            "Send queued DHL reply via SMTP" if drp_send_enabled else
            "Build DHL reply package first"
        ),
        state    = _state_label(drp_send_enabled, done=s.dhl_reply_sent),
        auth     = "session",
    ))

    # Manual: Mark DHL email received
    out.append(Action(
        id       = "dhl.mark_received",
        label    = "↩ Manual: Mark DHL Received",
        section  = "dhl_clearance",
        style    = "secondary",
        enabled  = True,
        method   = "POST",
        endpoint = f"/api/v1/dhl/mark-email-received/{s.batch_id}",
        requires_confirmation = True,
        reason   = "Fallback when email scan misses DHL message",
        state    = "ready",
        auth     = "session",
    ))

    return out


def _customs_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []

    # Re-parse SAD — handled by /dashboard/recheck with explicit mode='sad'.
    # Body MUST be explicit so this action does not depend on backend defaults.
    out.append(Action(
        id       = "customs.reparse_sad",
        label    = "↻ Re-parse SAD",
        section  = "customs_documents",
        style    = "secondary",
        enabled  = s.has_sad_pdf,
        method   = "POST",
        endpoint = f"/dashboard/batches/{s.batch_id}/recheck",
        body     = {"mode": "sad"},
        reason   = "Re-run SAD parser; never overwrites with null" if s.has_sad_pdf else "No SAD file uploaded",
        state    = _state_label(s.has_sad_pdf),
        auth     = "session",
    ))

    return out


def _pz_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []

    # Run PZ
    run_reasons = []
    if not s.has_sad_pdf:           run_reasons.append("SAD missing")
    if not s.has_invoice_files:     run_reasons.append("No invoice files")
    if not s.has_customs_declaration: run_reasons.append("Customs not parsed")
    run_enabled, run_reason = _ready_or(run_reasons, ready_msg="All inputs present — ready to run PZ")

    out.append(Action(
        id       = "pz.run",
        label    = "↺ Regenerate PZ" if s.pz_generated else "▶ Run PZ",
        section  = "pz_accounting",
        style    = "primary",
        enabled  = run_enabled,
        method   = "POST",
        endpoint = f"/api/v1/upload/shipment/{s.batch_id}/process",
        reason   = "Re-run PZ engine with current inputs" if s.pz_generated else run_reason,
        missing  = [m for m, ok in {
            "zc429_sad": s.has_sad_pdf,
            "invoices": s.has_invoice_files,
            "customs_declaration": s.has_customs_declaration,
        }.items() if not ok],
        state    = "blocked" if s.pz_blocked else _state_label(run_enabled, done=s.pz_generated),
        auth     = "session",
    ))

    # Confirm PZ Number
    out.append(Action(
        id       = "pz.confirm_number",
        label    = "✎ Confirm PZ Number",
        section  = "pz_accounting",
        style    = "secondary",
        enabled  = s.pz_generated,
        method   = "POST",
        endpoint = f"/api/v1/upload/shipment/{s.batch_id}/set_pz",
        requires_confirmation = True,
        reason   = "Set the PZ document number after wFirma assigns one" if s.pz_generated else "Generate PZ first",
        state    = _state_label(s.pz_generated),
        auth     = "session",
    ))

    # Downloads
    for did, label, fname_attr, file_present in (
        ("pz.download_pdf",      "↓ PZ PDF",       "pz_pdf_filename",  s.has_pz_pdf),
        ("pz.download_xlsx",     "↓ Calc XLSX",    "pz_xlsx_filename", s.has_pz_xlsx),
    ):
        fname = getattr(s, fname_attr) or ""
        out.append(Action(
            id       = did,
            label    = label,
            section  = "pz_accounting",
            style    = "info",
            enabled  = file_present,
            method   = "GET",
            endpoint = f"/api/v1/files/{s.batch_id}/{fname}" if fname else "",
            reason   = "Download" if file_present else "PZ not generated yet — file missing",
            state    = _state_label(file_present, done=file_present),
            auth     = "session",
        ))

    # Audit reports
    for did, label, fname in (
        ("pz.download_audit_en", "↓ Audit EN",    "audit_report_en.pdf"),
        ("pz.download_audit_pl", "↓ Audit PL",    "audit_report_pl.pdf"),
        ("pz.download_memo",     "↓ Memo",        "audit_memo.pdf"),
    ):
        out.append(Action(
            id       = did,
            label    = label,
            section  = "pz_accounting",
            style    = "info",
            enabled  = s.pz_generated,
            method   = "GET",
            endpoint = f"/api/v1/files/{s.batch_id}/{fname}",
            reason   = "Download audit document" if s.pz_generated else "PZ not generated yet",
            state    = _state_label(s.pz_generated, done=s.pz_generated),
            auth     = "session",
        ))

    return out


def _wfirma_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []
    ready = s.wfirma_ready
    not_ready_reason = (
        "" if ready else
        " · ".join(filter(None, [
            "PZ not generated" if not s.pz_generated else "",
            "SAD required"     if not s.has_sad_pdf  else "",
        ])) or "Not ready"
    )

    out.append(Action(
        id       = "wfirma.preview",
        label    = "⊞ Preview wFirma Rows",
        section  = "wfirma",
        style    = "primary",
        enabled  = ready,
        method   = "POST",
        endpoint = f"/api/v1/upload/shipment/{s.batch_id}/wfirma/clipboard",
        reason   = "Preview the rows that will be imported into wFirma" if ready else not_ready_reason,
        state    = _state_label(ready, done=ready),
        auth     = "session",
    ))
    out.append(Action(
        id       = "wfirma.copy_clipboard",
        label    = "📋 Copy wFirma PZ",
        section  = "wfirma",
        style    = "secondary",
        enabled  = ready,
        method   = "POST",
        endpoint = f"/api/v1/upload/shipment/{s.batch_id}/wfirma/clipboard",
        reason   = "Copy tab-separated rows for paste into wFirma" if ready else not_ready_reason,
        state    = _state_label(ready, done=ready),
        auth     = "session",
    ))
    out.append(Action(
        id       = "wfirma.download_json",
        label    = "↓ Download PZ_READY.json",
        section  = "wfirma",
        style    = "info",
        enabled  = ready,
        method   = "GET",
        endpoint = f"/api/v1/upload/shipment/{s.batch_id}/wfirma/json",
        reason   = "Download structured payload for Chrome AutoFill script" if ready else not_ready_reason,
        state    = _state_label(ready, done=ready),
        auth     = "session",
    ))
    out.append(Action(
        id       = "wfirma.chrome_guide",
        label    = "⚙ Chrome AutoFill Guide",
        section  = "wfirma",
        style    = "info",
        enabled  = True,    # validator confirmed at /chrome_wfirma_autofill/{path:path}
        method   = "GET",
        endpoint = "/chrome_wfirma_autofill/README.md",
        reason   = "Setup guide for the Chrome console autofill script",
        state    = "ready",
        auth     = "session",
    ))
    out.append(Action(
        id       = "wfirma.api_export",
        label    = "⛔ Direct API Export",
        section  = "wfirma",
        style    = "secondary",
        enabled  = False,
        visible  = True,
        method   = "POST",
        endpoint = None,    # intentionally not implemented; visible as disabled
        reason   = "Disabled — Mode 3 requires endpoint verification + sandbox testing",
        state    = "blocked",
        auth     = "admin",
    ))

    return out


def _cowork_actions(s: NormalizedState) -> List[Action]:
    """Agency clearance flow — visible always, gated by clearance path."""
    out: List[Action] = []
    is_agency = is_agency_clearance(s.clearance_path)

    # Build agency package
    build_enabled = is_agency and s.has_polish_description and s.has_sad_pdf and s.has_customs_declaration and not s.pz_generated
    build_reason = (
        "Not an agency-clearance batch" if not is_agency else
        "Already past agency stage — PZ generated" if s.pz_generated else
        "Ready to build agency email package" if (s.has_polish_description and s.has_sad_pdf and s.has_customs_declaration) else
        " · ".join(filter(None, [
            "Polish desc required" if not s.has_polish_description else "",
            "SAD required"          if not s.has_sad_pdf            else "",
            "Customs required"      if not s.has_customs_declaration else "",
        ])) or "Ready"
    )
    out.append(Action(
        id       = "cowork.build_agency_email",
        label    = "📨 Build Agency Email",
        section  = "cowork",
        style    = "secondary",
        enabled  = build_enabled,
        method   = "POST",
        endpoint = f"/api/v1/agency/email-package/{s.batch_id}",
        reason   = build_reason,
        state    = _state_label(build_enabled, done=s.agency_package_built),
        auth     = "session",
    ))

    # Send via SMTP / MCP / Manual — three variants of the same queue endpoint
    send_endpoint = f"/api/v1/admin/email-queue/{s.agency_queue_id}/send" if s.agency_queue_id else ""
    send_enabled  = bool(s.agency_queue_id) and not s.agency_email_sent
    send_reason   = (
        "Already sent — idempotent" if s.agency_email_sent else
        "Send via SMTP (preferred)" if send_enabled else
        "No agency email queued" if not s.agency_queue_id else
        "Build agency package first"
    )
    # Three send variants on the same endpoint — body distinguishes them.
    # MCP variant is intentionally disabled (Email Evidence V2 gate); kept visible
    # with reason so operators see the explicit policy.
    _mcp_disabled_reason = "MCP send disabled (Email Evidence V2). Use SMTP or Manual."
    for did, label, style, body, enabled, reason in (
        ("cowork.send_smtp",   "↗ SMTP",        "primary",   {"method": "smtp"},
            send_enabled, send_reason),
        ("cowork.send_mcp",    "↗ MCP fallback", "secondary", {"method": "zoho_mcp"},
            False, _mcp_disabled_reason),
        ("cowork.send_manual", "⊟ Manual",      "secondary", {"method": "manual_package"},
            send_enabled, send_reason),
    ):
        out.append(Action(
            id       = did,
            label    = label,
            section  = "cowork",
            style    = style,
            enabled  = enabled,
            method   = "POST",
            endpoint = send_endpoint,
            body     = body,
            requires_confirmation = (did != "cowork.send_smtp"),
            reason   = reason,
            state    = "blocked" if did == "cowork.send_mcp" else _state_label(enabled, done=s.agency_email_sent),
            auth     = "session",
        ))

    return out


def _system_actions(s: NormalizedState) -> List[Action]:
    out: List[Action] = []
    out.append(Action(
        id       = "system.regenerate_outputs",
        label    = "↻ Regenerate All Outputs",
        section  = "system",
        style    = "danger",
        enabled  = s.has_invoice_files and s.has_sad_pdf,
        method   = "POST",
        endpoint = f"/dashboard/batches/{s.batch_id}/regenerate",
        requires_confirmation = True,
        reason   = "Re-run engine and overwrite all generated files" if (s.has_invoice_files and s.has_sad_pdf) else "Need invoices + SAD",
        state    = _state_label(s.has_invoice_files and s.has_sad_pdf),
        auth     = "session",
    ))
    return out


# ── Public API ──────────────────────────────────────────────────────────────

def build_actions_for_batch(batch_id: str, normalized: NormalizedState) -> Dict[str, List[Action]]:
    """
    Build the full action map. Always returns all 7 sections (possibly empty list).
    """
    return {
        "shipment":          _shipment_actions(normalized),
        "dhl_clearance":     _dhl_actions(normalized),
        "customs_documents": _customs_actions(normalized),
        "pz_accounting":     _pz_actions(normalized),
        "wfirma":            _wfirma_actions(normalized),
        "cowork":            _cowork_actions(normalized),
        "system":            _system_actions(normalized),
    }


def all_action_endpoints(normalized: NormalizedState) -> List[tuple[str, str, str]]:
    """Return (action_id, method, endpoint) for every action with a non-empty endpoint.
    Used by route_contract_validator and the audit script.
    """
    out: List[tuple[str, str, str]] = []
    for section, actions in build_actions_for_batch(normalized.batch_id, normalized).items():
        for a in actions:
            if a.endpoint:
                out.append((a.id, a.method, a.endpoint))
    return out

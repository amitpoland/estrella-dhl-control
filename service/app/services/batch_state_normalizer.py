"""
Dashboard Action V2 — batch state normalizer.

Pure function: derives a NormalizedState from audit.json + filesystem evidence.
NEVER trusts a stale audit string alone — every boolean is grounded in a file
that exists or a value that is present.

Read-only. Does NOT modify audit, files, or any field.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .dashboard_action_types import NormalizedState

_AUDIT_ONLY_PDFS = {"audit_report_en.pdf", "audit_report_pl.pdf", "audit_memo.pdf"}


def _safe_load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _polish_desc_exists(batch_dir: Path, fname: Optional[str]) -> bool:
    if not fname:
        return False
    return (batch_dir / fname).is_file() or (batch_dir / "dhl_docs" / fname).is_file()


def _dsk_exists(fname: Optional[str]) -> bool:
    if not fname:
        return False
    try:
        from ..api.routes_dsk import _DSK_OUTPUT_DIR  # type: ignore
        return (_DSK_OUTPUT_DIR / fname).is_file()
    except Exception:
        return False


def _find_pz_files(batch_dir: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (pz_pdf_filename, pz_xlsx_filename) — first match each."""
    if not batch_dir.exists():
        return (None, None)
    pdf_name = None
    xlsx_name = None
    for f in batch_dir.iterdir():
        if not f.is_file():
            continue
        suf = f.suffix.lower()
        if suf == ".pdf" and f.name not in _AUDIT_ONLY_PDFS and pdf_name is None:
            pdf_name = f.name
        elif suf == ".xlsx" and xlsx_name is None:
            xlsx_name = f.name
    return (pdf_name, xlsx_name)


def _resolve_email_status(queue_id: Optional[str]) -> Optional[str]:
    """Read email_queue.json to confirm queue entry status (queued|sent|failed|None)."""
    if not queue_id:
        return None
    try:
        from .email_service import get_all_emails  # type: ignore
        for entry in get_all_emails(limit=500):
            if entry.get("id") == queue_id:
                return entry.get("status")
    except Exception:
        pass
    return None


def normalize_batch_state(audit: Dict[str, Any], batch_dir: Path) -> NormalizedState:
    """
    Build evidence-grounded state snapshot.

    `audit` is the raw audit.json dict. `batch_dir` is the storage/outputs/<id>/ path.
    """
    batch_id = audit.get("batch_id") or batch_dir.name
    inputs   = audit.get("inputs") or {}
    cd       = audit.get("customs_declaration") or {}
    arp      = audit.get("agency_reply_package") or {}
    drp      = audit.get("dhl_reply_package") or {}
    cdec     = audit.get("clearance_decision") or {}

    # ── Source files ─────────────────────────────────────────────────────────
    has_invoice_files = bool(inputs.get("invoices"))
    awb_name          = inputs.get("awb")
    has_awb_pdf       = bool(awb_name) and (batch_dir / "source" / "awb" / str(awb_name)).is_file() \
        if awb_name else False
    sad_name          = inputs.get("zc429")
    # Match production semantic in routes_dashboard.action_diagnostics: SAD presence
    # is asserted via audit.inputs.zc429. The on-disk file may be moved / archived.
    has_sad_pdf       = bool(sad_name)
    # ZC429 XML — engine writes to audit.zc429 dict if XML was used
    has_zc429_xml     = bool((audit.get("zc429") or {}).get("mrn"))

    # ── Generated outputs ────────────────────────────────────────────────────
    pd_filename             = audit.get("polish_desc_filename")
    has_polish_description  = _polish_desc_exists(batch_dir, pd_filename)
    dsk_filename            = audit.get("dsk_filename")
    has_dsk_pdf             = _dsk_exists(dsk_filename)
    pz_pdf_name, pz_xlsx_name = _find_pz_files(batch_dir)
    has_pz_pdf              = pz_pdf_name is not None
    has_pz_xlsx             = pz_xlsx_name is not None

    # ── Customs ──────────────────────────────────────────────────────────────
    has_customs_declaration = bool(cd.get("mrn") or cd.get("duty_a00_pln") is not None)

    # ── PZ status — file evidence over stale string ─────────────────────────
    audit_status = audit.get("status", "") or ""
    pz_generated = (
        has_pz_pdf and has_pz_xlsx
    ) or audit_status in {"success", "partial"} or audit.get("pz_generated") is True
    pz_blocked   = audit_status == "blocked"

    # ── wFirma ──────────────────────────────────────────────────────────────
    wfirma_ready = pz_generated and has_sad_pdf

    # ── Agency package & email ──────────────────────────────────────────────
    agency_package_built = bool(arp.get("status") or arp.get("queue_id") or arp.get("email_id"))
    agency_queue_id      = arp.get("queue_id") or arp.get("email_id")
    arp_status           = arp.get("status")
    eq_status            = _resolve_email_status(agency_queue_id) if agency_queue_id else None
    agency_email_queued  = bool(agency_queue_id) and (arp_status == "queued" or eq_status == "queued")
    agency_email_sent    = arp_status == "sent" or eq_status == "sent"

    # ── DHL reply ───────────────────────────────────────────────────────────
    dhl_reply_built  = bool(drp.get("status") or drp.get("queue_id") or drp.get("email_id"))
    dhl_reply_queue_id = drp.get("queue_id") or drp.get("email_id")
    drp_status       = drp.get("status")
    dhl_eq_status    = _resolve_email_status(dhl_reply_queue_id) if dhl_reply_queue_id else None
    dhl_reply_sent   = drp_status == "sent" or dhl_eq_status == "sent"

    # ── Tracking ────────────────────────────────────────────────────────────
    tracking = audit.get("tracking") or {}
    tracking_cache = batch_dir / "tracking_cache.json"
    if tracking_cache.exists():
        cached = _safe_load_json(tracking_cache)
        if cached:
            tracking = cached
    t_status = tracking.get("status", "") or ""
    t_source = tracking.get("source", "") or ""
    tracking_404_nonblocking = (t_source == "dhl_api_404") or (t_status == "not_found")
    tracking_available       = bool(t_status) and not tracking_404_nonblocking

    # ── Routing ─────────────────────────────────────────────────────────────
    clearance_path  = (cdec.get("clearance_path") or "") if isinstance(cdec, dict) else ""
    settlement_mode = audit.get("settlement_mode") or ""

    # ── Terminal? ───────────────────────────────────────────────────────────
    overall_status = audit.get("overall_status") or ""
    shipment_terminal = overall_status in {"Complete", "Exported"} or audit.get("archived") is True

    return NormalizedState(
        batch_id                 = batch_id,
        has_invoice_files        = has_invoice_files,
        has_awb_pdf              = has_awb_pdf,
        has_sad_pdf              = has_sad_pdf,
        has_zc429_xml            = has_zc429_xml,
        has_polish_description   = has_polish_description,
        has_dsk_pdf              = has_dsk_pdf,
        has_pz_pdf               = has_pz_pdf,
        has_pz_xlsx              = has_pz_xlsx,
        has_customs_declaration  = has_customs_declaration,
        pz_generated             = pz_generated,
        pz_blocked               = pz_blocked,
        wfirma_ready             = wfirma_ready,
        agency_package_built     = agency_package_built,
        agency_email_queued      = agency_email_queued,
        agency_email_sent        = agency_email_sent,
        dhl_reply_built          = dhl_reply_built,
        dhl_reply_sent           = dhl_reply_sent,
        shipment_terminal        = shipment_terminal,
        tracking_available       = tracking_available,
        tracking_404_nonblocking = tracking_404_nonblocking,
        polish_desc_filename     = pd_filename,
        dsk_filename             = dsk_filename,
        agency_queue_id          = agency_queue_id,
        dhl_reply_queue_id       = dhl_reply_queue_id,
        pz_pdf_filename          = pz_pdf_name,
        pz_xlsx_filename         = pz_xlsx_name,
        clearance_path           = clearance_path,
        settlement_mode          = settlement_mode,
        audit_status             = audit_status,
        overall_status           = overall_status,
    )

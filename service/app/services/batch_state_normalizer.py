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

# ── Operator override constants ───────────────────────────────────────────────
# Checks that operators may accept without re-running the engine.
# These are non-financial classification/identity checks only.
ALLOWED_OVERRIDE_TYPES: frozenset[str] = frozenset({
    "cn_match",                      # CN parent/child mismatch
    "exporter_match",                # SAD truncation of known legal entity
    "invoice_number_parse_warning",  # filename-derived invoice number
})

# Checks that can NEVER be overridden — financial or document completeness.
FORBIDDEN_OVERRIDE_TYPES: frozenset[str] = frozenset({
    "cif_match",
    "invoice_refs_match",
    "importer_match",
    "qty_match_by_type",
})

# Amendment-flag prefixes suppressed when the corresponding check is overridden.
# Each entry lists the flag prefixes the engine emits for that check.
# cn_match is intentionally empty — it produces no amendment_flag of its own.
_OVERRIDE_FLAG_PREFIXES: dict[str, tuple[str, ...]] = {
    "cn_match":                     (),
    "exporter_match":               ("Exporter mismatch",),
    "invoice_number_parse_warning": ("Parse warning:",),
}

# Checks that contribute to the engine's composite "Review needed: SAD / invoice set …" flag.
# When all structural checks remaining in failed_checks are overridden, that flag is suppressed.
_STRUCTURAL_MISMATCH_CHECKS: frozenset[str] = frozenset({
    "invoice_refs_match",
    "cif_match",
    "qty_match_by_type",
    "importer_match",
    "exporter_match",
})
_REVIEW_NEEDED_PREFIX = "Review needed: SAD / invoice set may require amendment"

_AUDIT_ONLY_PDFS = {"audit_report_en.pdf", "audit_report_pl.pdf", "audit_memo.pdf"}


def _safe_load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _polish_desc_exists(batch_dir: Path, fname: Optional[str]) -> bool:
    """Polish descriptions are written by the engine to one of three places:
       1. <batch_dir>/<fname>                 (legacy in-batch placement)
       2. <batch_dir>/dhl_docs/<fname>        (DHL doc copy)
       3. <storage_root>/polish_descriptions/<fname>  (canonical shared dir)
    Check all three so the dashboard never reports "not generated yet" when
    the file is sitting in the shared polish_descriptions directory.
    """
    if not fname:
        return False
    if (batch_dir / fname).is_file():
        return True
    if (batch_dir / "dhl_docs" / fname).is_file():
        return True
    try:
        from ..core.config import settings
        if (settings.storage_root / "polish_descriptions" / fname).is_file():
            return True
    except Exception:
        pass
    return False


def resolve_polish_desc_filename(batch_dir: Path, awb: Optional[str],
                                 stored_fname: Optional[str]) -> Optional[str]:
    """Auto-resolve the canonical Polish description filename for a batch.

    Use case: ``audit.polish_desc_filename`` may point at a stale file
    (e.g. an Apr 28 generation that was later replaced by a May 2 regen).
    This helper returns:
        1. ``stored_fname`` if it exists on disk (legacy or canonical dir)
        2. otherwise, the most recent file in
           ``<storage_root>/polish_descriptions/`` whose name contains the
           batch's AWB
        3. otherwise None.

    Generation logic is untouched — this only fixes the audit pointer at
    read-time so the dashboard download link always works.
    """
    if stored_fname and _polish_desc_exists(batch_dir, stored_fname):
        return stored_fname
    if not awb:
        return stored_fname
    awb_digits = "".join(ch for ch in str(awb) if ch.isdigit())
    if not awb_digits:
        return stored_fname
    try:
        from ..core.config import settings
        pd_dir = settings.storage_root / "polish_descriptions"
        if not pd_dir.is_dir():
            return stored_fname
        candidates = [
            p for p in pd_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"
            and awb_digits in p.name
        ]
        if not candidates:
            return stored_fname
        # Newest by mtime — the regenerated file is preferred over older copies
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        return latest.name
    except Exception:
        return stored_fname


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


def _compute_effective_blocked(audit: Dict[str, Any]) -> bool:
    """
    Return True if the batch is effectively blocked AFTER applying operator overrides.

    Rules:
      - audit.status must be "blocked" or this returns False immediately.
      - Each override in audit.operator_overrides may clear one allowed check.
      - Financial checks (cif_match, invoice_refs_match, …) can NEVER be cleared.
      - Each allowed override also suppresses the specific amendment flags the engine
        emits for that check (see _OVERRIDE_FLAG_PREFIXES).
      - The composite "Review needed: SAD / invoice set …" flag is suppressed when all
        structural-mismatch checks remaining in failed_checks are overridden.
      - audit.status, audit.failed_checks, and audit.verification are NEVER modified.

    This is called at read time only — it does not write to audit.
    """
    if (audit.get("status") or "") != "blocked":
        return False

    # Collect valid, batch-matched overrides
    batch_id = audit.get("batch_id") or ""
    raw_overrides = audit.get("operator_overrides") or []
    overridden_checks: set[str] = set()

    for o in raw_overrides:
        check = o.get("check", "")
        if check not in ALLOWED_OVERRIDE_TYPES:
            continue                        # invalid or forbidden — ignored
        if o.get("batch_id") != batch_id:
            continue                        # batch_id mismatch — ignored
        overridden_checks.add(check)

    # Hard failures remaining after subtracting overridden checks
    failed_checks = set(audit.get("failed_checks") or [])
    remaining_hard = failed_checks - overridden_checks

    # Build the set of flag prefixes to suppress based on active overrides
    suppressed_prefixes: set[str] = set()
    for check in overridden_checks:
        for prefix in _OVERRIDE_FLAG_PREFIXES.get(check, ()):
            suppressed_prefixes.add(prefix)

    # Suppress the composite "Review needed" flag when every structural-mismatch check
    # that appears in failed_checks is covered by an override.
    structural_in_failed = failed_checks & _STRUCTURAL_MISMATCH_CHECKS
    if structural_in_failed and structural_in_failed.issubset(overridden_checks):
        suppressed_prefixes.add(_REVIEW_NEEDED_PREFIX)

    # Drop suppressed flags; anything remaining still blocks
    amendment_flags = audit.get("amendment_flags") or []
    remaining_flags = [
        f for f in amendment_flags
        if not any(f.startswith(p) for p in suppressed_prefixes)
    ]

    return bool(remaining_hard) or bool(remaining_flags)


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
    pz_blocked   = _compute_effective_blocked(audit)

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

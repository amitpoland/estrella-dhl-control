from __future__ import annotations

import json
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..utils.batch_lock import batch_write_lock
from ..auth.dependencies import require_admin, require_role
from ..core import timeline as tl
from ..services import cliq_service
from ..utils.io import write_json_atomic
# ATLAS P1: PZ-status authority lives in operational_authority (single source).
# Re-imported under their historical private names so call sites are unchanged.
from ..services.operational_authority import (
    derive_status as _derive_status,
    derive_sad_status as _derive_sad_status,
    derive_pz_status as _derive_pz_status,
)

log = get_logger(__name__)

DeliveryStatus = Literal["success", "failed", "skipped"]
_ARCHIVE_RETENTION_DAYS = 14

router    = APIRouter(prefix="/dashboard", tags=["dashboard"])
_auth     = Depends(require_api_key)
_admin_auth = Depends(require_admin)
_op_auth  = Depends(require_role("admin", "logistics", "accounts"))

_OUTPUTS  = settings.storage_root / "outputs"
_WORKING  = settings.storage_root / "working"
_ARCHIVED = settings.storage_root / "archived"        # reversible, 14-day retention
# Note: storage/permanently_deleted/ used for expired/admin-deleted batches (inline in endpoints)
_MAX_LIST = 300  # read more before dedup


def _resolve_audit_path(batch_id: str):
    """
    Return the first existing audit.json path across (outputs/, working/).

    Active batches live under working/; finalized ones under outputs/.  The
    older email-evidence / actions endpoints only checked outputs/, which 404'd
    for batches that hadn't been finalized yet.  Returns None if neither has
    the batch.
    """
    for sub in (_OUTPUTS, _WORKING):
        p = sub / batch_id / "audit.json"
        if p.exists():
            return p
    return None


# ── Carrier detection ─────────────────────────────────────────────────────────

def _detect_carrier(tracking_no: str, awb_filename: str = "") -> Dict[str, str]:
    """
    Detect carrier (DHL / FedEx / Unknown) from tracking number format and AWB filename.
    Returns dict with: carrier, tracking_url, tracking_label
    Phase 1 — no API, just public tracking page links.
    """
    t   = (tracking_no or "").strip()
    fn  = (awb_filename or "").lower()
    digits = re.sub(r"[^\d]", "", t)
    n   = len(digits)

    # DHL: 10-digit waybill, OR filename/tracking contains DHL hints
    is_dhl = (
        n == 10
        or "dhl" in fn
        or "waybill" in fn
        or "mydhl" in fn
        or re.search(r"\bdhl\b", t, re.IGNORECASE) is not None
    )
    # FedEx: 12 / 15 / 20 / 22 digit, OR filename contains fedex
    is_fedex = (
        n in (12, 15, 20, 22)
        or "fedex" in fn
        or re.search(r"\bfedex\b", t, re.IGNORECASE) is not None
    )

    # DHL takes priority if both match (10-digit alone is a strong DHL signal)
    if is_dhl and not (is_fedex and n not in (10,)):
        url = f"https://www.dhl.com/pl-en/home/tracking.html?tracking-id={t}" if t else ""
        return {"carrier": "DHL", "tracking_url": url, "tracking_label": "Open DHL Tracking"}
    if is_fedex:
        url = f"https://www.fedex.com/en-pl/tracking.html?trknbr={t}" if t else ""
        return {"carrier": "FedEx", "tracking_url": url, "tracking_label": "Open FedEx Tracking"}

    # Unknown carrier — still provide tracking number
    return {"carrier": "Unknown", "tracking_url": "", "tracking_label": "Carrier not detected"}


def _with_download_urls(audit: Dict[str, Any]) -> Dict[str, Any]:
    batch_id = audit.get("batch_id", "")
    out_dir  = settings.storage_root / "outputs" / batch_id if batch_id else None
    for key, entry in audit.get("files", {}).items():
        # Guard: only process dict entries — string paths (legacy or backfilled)
        # are skipped; the proper file URLs come from _build_files_detail().
        if isinstance(entry, dict) and entry.get("name"):
            entry["download_url"] = f"/api/v1/files/{batch_id}/{entry['name']}"
            # Stamp `exists` based on disk presence so the View/Download
            # buttons render correctly. Frontend reads this; without it the
            # button stays disabled even when the file is on disk.
            if entry.get("exists") in (None, ""):
                try:
                    entry["exists"] = bool(out_dir and (out_dir / entry["name"]).exists())
                except Exception:
                    entry["exists"] = False
    return audit


def _derive_clearance_status(a: Dict[str, Any]) -> str:
    """
    Fix 6: Derive normalized clearance_status from actual audit fields.

    Canonical values:
      awaiting_dhl_email | dhl_email_received | dsk_generated | agency_email_queued |
      agency_email_sent  | customs_parsed | ready_for_pz | pz_generated | completed

    Priority: concrete audit evidence beats stored string labels so that stale
    strings cannot mask real state.
    """
    # PZ generated — three independent signals to be robust in both list and detail views
    files_detail = a.get("files_detail", {})
    pz_pdf = (files_detail.get("files") or {}).get("pz_pdf", {})
    pz_done = (
        pz_pdf.get("exists")                          # files_detail populated (batch_detail view)
        or a.get("pz_generated") is True              # explicit flag
        or a.get("status") in {"success", "partial"}  # engine ran — covers list view too
    )
    if pz_done:
        return "pz_generated"

    # Agency email state
    arp = a.get("agency_reply_package") or {}
    if arp.get("status") == "sent":
        return "agency_email_sent"
    if arp.get("status") == "queued":
        return "agency_email_queued"

    # DSK generated
    if a.get("dsk_filename") or a.get("dsk_status") == "generated":
        return "dsk_generated"

    # Customs/SAD parsed
    cd = a.get("customs_declaration") or {}
    if cd.get("mrn") or cd.get("duty_a00_pln") is not None or a.get("inputs", {}).get("zc429_mrn"):
        return "customs_parsed"

    # DHL email received
    if a.get("dhl_email_received") or a.get("clearance_status") == "dhl_email_received":
        return "dhl_email_received"

    # Awaiting DHL email
    if a.get("inputs", {}).get("zc429") or a.get("inputs", {}).get("invoices"):
        if a.get("carrier", "").upper() == "DHL":
            stored = a.get("clearance_status", "")
            # If there is a stored value from a legitimate path, honour it
            _valid = {
                "awaiting_dhl_email", "dhl_email_received", "dsk_generated",
                "agency_email_queued", "agency_email_sent", "customs_parsed",
                "ready_for_pz", "pz_generated", "completed",
                "awaiting_dhl_customs_email",   # legacy alias
            }
            if stored in _valid:
                # Map legacy aliases
                return "awaiting_dhl_email" if stored == "awaiting_dhl_customs_email" else stored
            return "awaiting_dhl_email"

    return a.get("clearance_status", "")


# _derive_status → moved to services.operational_authority.derive_status
# (re-imported above as _derive_status; ATLAS P1 single-authority).


def _derive_action_reason(a: Dict[str, Any]) -> str:
    """Return a short human-readable reason for Action Required status, or empty string."""
    fc = a.get("failed_checks") or []
    if fc:
        return fc[0]
    err = a.get("engine_error") or ""
    if err:
        # Truncate long errors to a badge-friendly length
        return err[:120]
    v = a.get("verification", {})
    hard_fails = [k for k, val in v.items() if not isinstance(val, list) and val is False]
    if hard_fails:
        return f"Verification failed: {hard_fails[0]}"
    return ""


def _derive_failed_checks(a: Dict[str, Any]) -> List[str]:
    """Return failed_checks list, deriving from verification if the field is absent."""
    stored = a.get("failed_checks")
    if stored is not None:
        return stored[:3]
    v = a.get("verification", {})
    return [k for k, val in v.items() if not isinstance(val, list) and val is False][:3]


# _derive_sad_status → moved to services.operational_authority.derive_sad_status
# (re-imported above as _derive_sad_status; ATLAS P1 single-authority).


# _derive_pz_status → moved to services.operational_authority.derive_pz_status
# (re-imported above as _derive_pz_status; ATLAS P1 single-authority — the one
# canonical PZ-status derivation that routes_wfirma + the frontend now agree with).


# ── Lightweight per-batch status hints (cheap COUNT-only queries) ─────────────
#
# Used by /dashboard/batches list view to show at-a-glance Warehouse / Sales /
# wFirma columns. Each hint MUST fail silently (return 'n/a') — the list view
# must never break when a sub-database is missing or empty.

def _warehouse_hint(batch_id: str) -> str:
    """Return 'clean' | 'partial' | 'empty' | 'n/a' based on completion %."""
    try:
        from ..services import warehouse_audit as waudit
        c = waudit.get_batch_completion(batch_id)
        total   = c.get("total_items") or 0
        scanned = c.get("scanned_items") or 0
        missing = c.get("missing_items") or 0
        if total == 0:
            return "n/a"
        if missing == 0 and scanned > 0:
            return "clean"
        if scanned > 0:
            return "partial"
        return "empty"
    except Exception:  # noqa: BLE001
        return "n/a"


def _sales_hint(batch_id: str) -> str:
    """Return 'present' | 'none' based on sales packing line presence."""
    try:
        from ..services import document_db as ddb
        rows = ddb.get_sales_packing_lines(batch_id)
        return "present" if rows else "none"
    except Exception:  # noqa: BLE001
        return "n/a"


def _wfirma_hint(batch_id: str, a: Dict[str, Any] | None = None) -> str:
    """Return 'posted' | 'preview_built' | 'none' based on PZ and draft state.

    Precedence:
      1. 'posted'        — wfirma_export.wfirma_pz_doc_id is set in audit
      2. 'preview_built' — reservation drafts exist but no PZ created yet
      3. 'none'          — no drafts, no PZ
    """
    try:
        # Ground truth: PZ doc ID in audit means it was posted to wFirma
        if a and (a.get("wfirma_export") or {}).get("wfirma_pz_doc_id"):
            return "posted"
        from ..services import wfirma_db as wfdb
        drafts = wfdb.list_reservation_drafts(batch_id)
        return "preview_built" if drafts else "none"
    except Exception:  # noqa: BLE001
        return "n/a"


def _batch_summary(a: Dict[str, Any], batch_dir_name: str) -> Dict[str, Any]:
    t      = a.get("totals", {})
    inp    = a.get("inputs", {})
    mrn    = inp.get("zc429_mrn") or a.get("mrn")
    doc_no = a.get("doc_no") or ""
    # Extract tracking number from batch_id (SHIPMENT_<tracking>_<YYYY-MM>_<uuid>)
    raw_batch_id = a.get("batch_id", batch_dir_name)
    tracking_no  = a.get("tracking_no", "")
    if not tracking_no and raw_batch_id.startswith("SHIPMENT_"):
        parts = raw_batch_id.split("_")
        if len(parts) >= 4 and parts[1] != "AUTO":
            tracking_no = parts[1]

    # Carrier: use explicit field first (set by user at creation), fall back to auto-detection
    awb_filename = inp.get("awb") or ""
    stored_carrier = a.get("carrier", "")
    if stored_carrier and stored_carrier != "Unknown":
        carrier_info = {
            "carrier":        stored_carrier,
            "tracking_url":   a.get("tracking_url") or _detect_carrier(tracking_no, awb_filename)["tracking_url"],
            "tracking_label": f"Open {stored_carrier} Tracking" if stored_carrier in ("DHL", "FedEx") else "Carrier not detected",
        }
    else:
        carrier_info = _detect_carrier(tracking_no, awb_filename)

    # invoice_refs for search
    invoice_refs = inp.get("invoice_refs", [])

    # Tracking status from audit (populated by POST /refresh)
    tracking = a.get("tracking", {})

    return {
        "batch_id":              raw_batch_id,
        "tracking_no":           tracking_no,
        "doc_no":                doc_no,
        "timestamp":             a.get("timestamp", ""),
        "status":                _derive_status(a),
        "engine_version":        a.get("engine_version"),
        "net":                   t.get("net"),
        "gross":                 t.get("gross"),
        "duty":                  t.get("duty"),
        "total_duty":            t.get("duty"),
        "total_gross":           t.get("gross"),
        "mrn":                   mrn,
        "failed_checks":         _derive_failed_checks(a),
        "action_reason":         _derive_action_reason(a),
        # Single-authority DHL follow-up mode (2026-05-26).
        # Read straight from audit.followup.mode; default "manual" when
        # the shipment has never been enrolled. Used by the Inbox to
        # render the mode selector + correct action set per row.
        "followup_mode":         ((a.get("followup") or {}).get("mode")
                                  or "manual"),
        "invoice_refs":          invoice_refs,
        "run_count":             1,   # populated by dedup logic
        "has_sad":               _derive_sad_status(a) != "missing",
        "pz_confirmed":          a.get("pz_confirmed", False),
        # Carrier tracking (Phase 1: public tracking pages only)
        "carrier":               carrier_info["carrier"],
        "tracking_url":          carrier_info["tracking_url"],
        "tracking_label":        carrier_info["tracking_label"],
        # Live tracking status (populated after API refresh)
        "tracking_status":       tracking.get("status_label") if tracking else None,
        "tracking_status_key":   tracking.get("status") if tracking else None,
        "tracking_available":    tracking.get("available", False) if tracking else False,
        # ── Pipeline statuses (for dashboard list columns) ────────────────────
        "clearance_status": _derive_clearance_status(a),
        "dhl_status":   _derive_clearance_status(a) or None,
        "sad_status":   _derive_sad_status(a),
        "pz_status":    _derive_pz_status(a),
        # ── Lightweight hints for new batch-list columns (Phase 1 polish) ─────
        # Each fails silently to 'n/a' — list view must never break.
        "warehouse_status_hint": _warehouse_hint(raw_batch_id),
        "sales_status_hint":     _sales_hint(raw_batch_id),
        "wfirma_status_hint":    _wfirma_hint(raw_batch_id, a),
    }


# ── Files detail helper ───────────────────────────────────────────────────────

_AUDIT_ONLY_PDFS = {"audit_report_en.pdf", "audit_report_pl.pdf", "audit_memo.pdf"}


def _build_source_files(batch_id: str) -> Dict[str, Any]:
    """Scan source/ subdirectory in the output folder for uploaded source files."""
    src_base = _OUTPUTS / batch_id / "source"

    def _src_url(category: str, name: str) -> str:
        from urllib.parse import quote
        return f"/api/v1/files/{quote(batch_id)}/source/{category}/{quote(name)}"

    def _scan(category: str) -> List[Dict[str, Any]]:
        d = src_base / category
        if not d.exists():
            return []
        return [
            {"name": f.name, "url": _src_url(category, f.name), "exists": True}
            for f in sorted(d.iterdir())
            if f.is_file() and not f.name.startswith(".")
        ]

    return {
        "invoices": _scan("invoices"),
        "sad":      _scan("sad"),
        "awb":      _scan("awb"),
    }


def _build_files_detail(batch_id: str) -> Dict[str, Any]:
    """Scan the batch output folder and return availability of all known files.

    Resolution order for each output:
      1. canonical filename `{TYPE}_AWB_{awb}_MRN_{mrn}_{date}.{ext}`
         (read from audit.json `canonical_filenames` block when present)
      2. legacy generic name (e.g. ``audit_memo.pdf``) — flagged ``stale=True``
    """
    import json as _json
    from urllib.parse import quote
    batch_dir = _OUTPUTS / batch_id

    def _url(name: str) -> str:
        return f"/api/v1/files/{quote(batch_id)}/{quote(name)}"

    # Try to read canonical filenames stamped on the audit.json by the engine.
    # Also read pz_output — it is the single source of truth for PDF/XLSX names
    # when present (populated by _build_pz_output in export_service after each run).
    canon: Dict[str, str] = {}
    pz_output_block: Dict[str, Any] = {}
    try:
        ap = batch_dir / "audit.json"
        if ap.is_file():
            _audit_raw = _json.loads(ap.read_text(encoding="utf-8")) or {}
            canon = _audit_raw.get("canonical_filenames") or {}
            pz_output_block = _audit_raw.get("pz_output") or {}
    except Exception:
        canon = {}
        pz_output_block = {}

    def _resolve(key: str, legacy: str) -> Dict[str, Any]:
        """Prefer canonical filename if it exists on disk; fall back to legacy."""
        canon_name = canon.get(key) or ""
        if canon_name and (batch_dir / canon_name).is_file():
            return {"name": canon_name, "url": _url(canon_name), "exists": True, "stale": False}
        if legacy and (batch_dir / legacy).is_file():
            return {"name": legacy, "url": _url(legacy), "exists": True, "stale": True}
        return {"name": canon_name or legacy, "url": "", "exists": False, "stale": False}

    def _find_pdf() -> Dict[str, Any]:
        """PZ PDF: if pz_output block present use it exclusively (no scan fallback).
        Without pz_output fall back to canonical name then directory scan."""
        if pz_output_block:
            po_name = pz_output_block.get("pdf") or ""
            if po_name and (batch_dir / po_name).is_file():
                return {"name": po_name, "url": _url(po_name), "exists": True, "stale": False}
            return {"name": po_name, "url": "", "exists": False, "stale": False}
        canon_name = canon.get("pz_pdf") or ""
        if canon_name and (batch_dir / canon_name).is_file():
            return {"name": canon_name, "url": _url(canon_name), "exists": True, "stale": False}
        if batch_dir.exists():
            for f in sorted(batch_dir.iterdir()):
                if f.suffix.lower() == ".pdf" and f.name not in _AUDIT_ONLY_PDFS:
                    return {"name": f.name, "url": _url(f.name), "exists": True, "stale": True}
        return {"name": canon_name, "url": "", "exists": False, "stale": False}

    def _find_xlsx() -> Dict[str, Any]:
        """Calc XLSX: if pz_output block present use it exclusively (no scan fallback).
        Without pz_output fall back to canonical name then directory scan."""
        if pz_output_block:
            po_name = pz_output_block.get("xlsx") or ""
            if po_name and (batch_dir / po_name).is_file():
                return {"name": po_name, "url": _url(po_name), "exists": True, "stale": False}
            return {"name": po_name, "url": "", "exists": False, "stale": False}
        canon_name = canon.get("calc_xlsx") or ""
        if canon_name and (batch_dir / canon_name).is_file():
            return {"name": canon_name, "url": _url(canon_name), "exists": True, "stale": False}
        if batch_dir.exists():
            for f in sorted(batch_dir.iterdir()):
                if f.suffix.lower() == ".xlsx":
                    return {"name": f.name, "url": _url(f.name), "exists": True, "stale": True}
        return {"name": canon_name, "url": "", "exists": False, "stale": False}

    def _find_corrections() -> Dict[str, Any]:
        canon_name = canon.get("corrections") or ""
        if canon_name and (batch_dir / canon_name).is_file():
            return {"name": canon_name, "url": _url(canon_name), "exists": True, "stale": False}
        if batch_dir.exists():
            for f in sorted(batch_dir.iterdir()):
                if f.name.startswith("corrections") and f.suffix.lower() == ".json":
                    return {"name": f.name, "url": _url(f.name), "exists": True, "stale": True}
        return {"name": canon_name or "corrections.json", "url": "", "exists": False, "stale": False}

    pz_pdf  = _find_pdf()
    calc    = _find_xlsx()
    en_pdf  = _resolve("audit_en",   "audit_report_en.pdf")
    pl_pdf  = _resolve("audit_pl",   "audit_report_pl.pdf")
    memo    = _resolve("audit_memo", "audit_memo.pdf")
    corr    = _find_corrections()

    return {
        "batch_id":     batch_id,
        "source_files": _build_source_files(batch_id),
        "files": {
            "pz_pdf":      pz_pdf,
            "calc_xlsx":   calc,
            "audit_en":    en_pdf,
            "audit_pl":    pl_pdf,
            "audit_memo":  memo,
            "corrections": corr,
        },
    }


# ── List all batches ──────────────────────────────────────────────────────────

@router.get("/batches", dependencies=[_auth])
def list_batches(
    all_runs: bool = Query(False, alias="all"),
) -> List[Dict[str, Any]]:
    """
    Return completed batches sorted newest-first.

    By default (all=false) deduplicates by (mrn, doc_no) keeping only the
    latest run per document.  Pass ?all=1 to see every run.
    """
    if not _OUTPUTS.exists():
        return []

    dirs = sorted(_OUTPUTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)

    raw: List[Dict[str, Any]] = []
    for batch_dir in dirs[:_MAX_LIST]:
        if not batch_dir.is_dir():
            continue
        audit_path = batch_dir / "audit.json"
        if not audit_path.exists():
            continue
        try:
            with audit_path.open(encoding="utf-8") as fh:
                a = json.load(fh)
        except Exception:
            continue
        raw.append(_batch_summary(a, batch_dir.name))

    if all_runs:
        return raw

    # ── Dedup: keep latest run per (mrn, doc_no) key ────────────────────────
    seen: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = {}
    for b in raw:
        mrn    = b["mrn"] or ""
        doc_no = b["doc_no"] or ""
        key    = f"{mrn}||{doc_no}" if (mrn or doc_no) else b["batch_id"]
        if key not in seen:
            seen[key]   = b
            counts[key] = 1
        else:
            counts[key] += 1
            # Prefer a non-blocked run over a blocked one (same document, fixed re-run)
            existing_status = seen[key]["status"]
            incoming_status = b["status"]
            prefer_incoming = (
                existing_status == "blocked"
                and incoming_status in ("success", "partial")
            )
            if prefer_incoming:
                seen[key] = b

    result = list(seen.values())
    for b in result:
        mrn    = b["mrn"] or ""
        doc_no = b["doc_no"] or ""
        key    = f"{mrn}||{doc_no}" if (mrn or doc_no) else b["batch_id"]
        b["run_count"] = counts.get(key, 1)

    return result


# ── Batch detail ──────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}/files", dependencies=[_auth])
def batch_files(batch_id: str) -> Dict[str, Any]:
    """Return file availability for a batch folder."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    batch_dir = _OUTPUTS / batch_id
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")
    return _build_files_detail(batch_id)


@router.get("/batches/{batch_id}", dependencies=[_auth])
def batch_detail(batch_id: str) -> Dict[str, Any]:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    with audit_path.open(encoding="utf-8") as fh:
        audit = json.load(fh)

    # ── Guarantee clearance_decision on batch load (non-destructive backfill) ──
    if "clearance_decision" not in audit:
        try:
            from ..services.clearance_decision import build_clearance_decision
            _dec = build_clearance_decision(audit)
            audit["clearance_decision"] = _dec
            write_json_atomic(audit_path, audit)
            log.info("[%s] clearance_decision backfilled on load: path=%s",
                     batch_id, _dec.get("clearance_path"))
        except Exception as _e:
            log.warning("[%s] clearance_decision backfill on load (non-fatal): %s", batch_id, _e)
    else:
        # ── Drift detection: log warning if stored decision diverges from recomputed ──
        # Do NOT auto-overwrite — only expose in response for human review.
        try:
            from ..services.clearance_decision import build_clearance_decision as _bcd
            _stored  = audit["clearance_decision"]
            _recomp  = _bcd(audit)
            if _recomp.get("clearance_path") != _stored.get("clearance_path"):
                _drift = (
                    f"clearance_decision drift: stored={_stored.get('clearance_path')} "
                    f"recomputed={_recomp.get('clearance_path')} "
                    f"(cif_stored={_stored.get('total_value_usd')} "
                    f"cif_current={_recomp.get('total_value_usd')})"
                )
                log.warning("[%s] %s", batch_id, _drift)
                audit["_clearance_drift_warning"] = _drift
                # Persist the warning to disk so operators can see it without API call.
                # clearance_decision itself is NOT overwritten — human review required.
                try:
                    write_json_atomic(audit_path, audit)
                except Exception as _we:
                    log.debug("[%s] drift warning persist (non-fatal): %s", batch_id, _we)
        except Exception as _de:
            log.debug("[%s] clearance drift check (non-fatal): %s", batch_id, _de)

    audit = _with_download_urls(audit)
    audit["files_detail"] = _build_files_detail(batch_id)

    # Inject carrier info derived at read-time
    inp         = audit.get("inputs", {})
    tracking_no = audit.get("tracking_no", "")
    awb_fn      = inp.get("awb") or ""
    carrier_info = _detect_carrier(tracking_no, awb_fn)
    audit.update(carrier_info)

    # Fix 2: inject file-on-disk existence flags for generated documents
    # so the frontend can switch Generate → Download without a separate API call.
    _dsk_file = audit.get("dsk_filename")
    if _dsk_file:
        from .routes_dsk import _DSK_OUTPUT_DIR
        audit["dsk_file_exists"] = (_DSK_OUTPUT_DIR / _dsk_file).is_file()
    else:
        audit["dsk_file_exists"] = False

    _pd_file = audit.get("polish_desc_filename")
    if _pd_file:
        # Polish desc stored in dhl_docs/ subfolder or engine_dir outputs
        _pd_candidates = [
            _OUTPUTS / batch_id / _pd_file,
            _OUTPUTS / batch_id / "dhl_docs" / _pd_file,
        ]
        audit["polish_desc_file_exists"] = any(p.is_file() for p in _pd_candidates)
    else:
        audit["polish_desc_file_exists"] = False

    # Fix 6: Normalize clearance_status from actual audit fields — never stale strings
    audit["clearance_status"] = _derive_clearance_status(audit)

    # ── Auto-resolve stale polish_desc_filename pointer ─────────────────────
    # If audit.polish_desc_filename references a file that no longer exists,
    # scan the canonical polish_descriptions/ directory for the latest PDF
    # matching this batch's AWB and update the pointer at read-time only.
    # Generation logic is untouched.
    try:
        from ..services.batch_state_normalizer import resolve_polish_desc_filename
        _stored_pd = audit.get("polish_desc_filename")
        _resolved  = resolve_polish_desc_filename(
            batch_dir = _OUTPUTS / batch_id,
            awb       = audit.get("tracking_no") or "",
            stored_fname = _stored_pd,
        )
        if _resolved and _resolved != _stored_pd:
            audit["polish_desc_filename"] = _resolved
            audit["polish_desc_file_exists"] = True
            log.info("[%s] polish_desc auto-resolved: %s → %s",
                     batch_id, _stored_pd, _resolved)
    except Exception as _pd_err:
        log.debug("[%s] polish_desc auto-resolve (non-fatal): %s", batch_id, _pd_err)

    # ── Stale row-schema detection (no auto-mutation) ───────────────────────
    # Surface staleness so the dashboard can prompt regenerate-from-source
    # rather than re-rendering rows that lack product_code/nazwa fields.
    try:
        from ..services.cache_freshness import stale_field_summary
        audit["cache_freshness"] = stale_field_summary(audit)
    except Exception as _cf_err:
        log.debug("[%s] cache_freshness check (non-fatal): %s", batch_id, _cf_err)

    # ── PZ financial totals from pz_rows.json (read-time injection) ─────────
    # The engine never writes total_net_pln / total_gross_pln / duty_a00_pln to
    # audit.json root.  If any of the three fields is absent, derive them from
    # pz_rows.json by summing the per-row columns.  Read-only — never writes to
    # audit.json.  Fails silently if the file is missing or corrupt.
    _totals_missing = (
        audit.get("total_net_pln")   is None
        or audit.get("total_gross_pln") is None
        or audit.get("duty_a00_pln")    is None
    )
    if _totals_missing:
        try:
            _rows_path = _OUTPUTS / batch_id / "pz_rows.json"
            if _rows_path.is_file():
                _rows = json.loads(_rows_path.read_text(encoding="utf-8"))
                if isinstance(_rows, list) and _rows:
                    if audit.get("total_net_pln") is None:
                        audit["total_net_pln"] = round(
                            sum(r.get("line_netto_pln", 0) for r in _rows), 2
                        )
                    if audit.get("total_gross_pln") is None:
                        audit["total_gross_pln"] = round(
                            sum(r.get("line_brutto_pln", 0) for r in _rows), 2
                        )
                    if audit.get("duty_a00_pln") is None:
                        audit["duty_a00_pln"] = round(
                            sum(r.get("allocated_duty_pln", 0) for r in _rows), 2
                        )
                    log.debug("[%s] pz_rows totals injected: net=%.2f gross=%.2f duty=%.2f",
                              batch_id,
                              audit["total_net_pln"],
                              audit["total_gross_pln"],
                              audit["duty_a00_pln"])
        except Exception as _pz_err:
            log.debug("[%s] pz_rows totals injection (non-fatal): %s", batch_id, _pz_err)

    # UI-3.6: BatchDetailPage Pipeline Summary needs sales_status_hint.
    # audit.json never carries this field — the documents DB is the only
    # source of truth for sales packing-line presence. _sales_hint() already
    # fails silently to 'n/a', so no extra try/except is needed here.
    audit["sales_status_hint"] = _sales_hint(batch_id)

    # Freight parse-status authority — derived on read, never persisted.
    # Frontend must render Freight (PLN) from this, not from loose fields.
    try:
        from ..services.freight_authority import derive_freight_authority
        audit["freight_authority"] = derive_freight_authority(audit)
    except Exception as _fa_err:
        log.warning("[%s] freight_authority derivation failed: %s", batch_id, _fa_err)
        audit["freight_authority"] = {
            "freight_status":        "unparsed",
            "freight_pln":           None,
            "freight_usd":           None,
            "freight_source":        None,
            "freight_review_reason": "Authority unavailable — derivation error.",
        }

    # SAD invoice-reference authority — derived on read, never persisted.
    # Frontend must render invoice-ref status from this; never from inferred_refs
    # or raw corrections_log entries. Free-text tokens (e.g. ['3322','088','2026'])
    # are advisory only and never enter the authority object.
    try:
        from ..services.sad_invoice_authority import derive_sad_invoice_authority
        audit["sad_invoice_authority"] = derive_sad_invoice_authority(audit)
    except Exception as _sia_err:
        log.warning("[%s] sad_invoice_authority derivation failed: %s", batch_id, _sia_err)
        audit["sad_invoice_authority"] = {
            "status":              "unverified_no_structured_reference",
            "source":              "none",
            "references":          [],
            "matched_invoice_ids": [],
            "warning":             None,
            "review_reason":       "Authority derivation error.",
        }

    # AWB structured fields — injected from documents DB at read-time (never persisted).
    # Gives compliance_resolver access to receiver_name (importer) and
    # shipper_name (exporter) from the waybill parsed at intake time.
    # Only runs when the resolver flag is active to avoid unnecessary DB queries.
    if settings.compliance_intelligence_resolver_enabled and "awb_fields" not in audit:
        try:
            from ..services import document_db as _ddb
            _awb = _ddb.get_awb_document(batch_id)
            if _awb:
                audit["awb_fields"] = _awb
        except Exception as _awb_inj_err:
            log.debug("[%s] awb_fields injection (non-fatal): %s", batch_id, _awb_inj_err)

    # Compliance intelligence resolution — derived on read, never persisted.
    # audit.verification is NEVER mutated here. The compliance_resolution object
    # is a projection-only layer injected when the feature flag is enabled.
    # Frontend renders the "intelligence_resolved" (blue) badge state only when
    # compliance_resolution is present in the response.
    if settings.compliance_intelligence_resolver_enabled:
        try:
            from ..services.compliance_resolver import resolve_compliance
            audit["compliance_resolution"] = resolve_compliance(audit)
        except Exception as _cr_err:
            log.warning("[%s] compliance_resolution derivation failed (non-fatal): %s",
                        batch_id, _cr_err)
            audit.pop("compliance_resolution", None)

    return audit


# ── Delete individual file from batch ────────────────────────────────────────

@router.delete("/batches/{batch_id}/files/{filename}", dependencies=[_admin_auth])
def delete_batch_file(batch_id: str, filename: str) -> Dict[str, Any]:
    """Delete a single file from a batch output folder."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = _OUTPUTS / batch_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    file_path.unlink()
    log.info("[dashboard] deleted file %s from batch %s", filename, batch_id)

    # Log to timeline
    audit_path = _OUTPUTS / batch_id / "audit.json"
    if audit_path.exists():
        try:
            tl.log_event(audit_path, "file_deleted", "dashboard", "user",
                         detail={"filename": filename})
        except Exception:
            pass

    return {"ok": True, "deleted": filename, "files": _build_files_detail(batch_id)}


@router.delete("/batches/{batch_id}/files/source/{category}/{filename}", dependencies=[_admin_auth])
def delete_source_file(batch_id: str, category: str, filename: str) -> Dict[str, Any]:
    """Delete a source file (invoice, AWB, SAD) from a batch."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    if category not in ("invoices", "sad", "awb"):
        raise HTTPException(status_code=400, detail="Invalid category.")
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = _OUTPUTS / batch_id / "source" / category / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found.")

    file_path.unlink()
    log.info("[dashboard] deleted source file %s/%s from batch %s", category, filename, batch_id)

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if audit_path.exists():
        try:
            tl.log_event(audit_path, "source_file_deleted", "dashboard", "user",
                         detail={"category": category, "filename": filename})
        except Exception:
            pass

    return {"ok": True, "deleted": filename, "category": category,
            "files": _build_files_detail(batch_id)}


@router.delete("/batches/{batch_id}/polish-description", dependencies=[_admin_auth])
def delete_polish_description(batch_id: str) -> Dict[str, Any]:
    """
    Delete this batch's Polish customs description PDF.

    Path-safety: the filename is read from audit.polish_desc_filename — never
    from user input — so URL-injection (..\\..\\evil.pdf) cannot reach the
    filesystem. The resolved path must (a) be inside storage_root/
    polish_descriptions/, and (b) exactly match the audit-recorded filename
    for THIS batch. On success, audit.polish_desc_filename / polish_desc_path
    / polish_desc_file_exists are cleared so the dashboard regenerate flow
    sees a clean slate.

    Returns 404 when no Polish description is recorded or on disk; never
    falls back to a permissive scan.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}") from exc

    fn = (audit.get("polish_desc_filename") or "").strip()
    if not fn:
        raise HTTPException(
            status_code=404,
            detail="No Polish description recorded for this batch.",
        )
    # Path-safety: filename must be a bare filename, no separators
    if "/" in fn or "\\" in fn or ".." in fn:
        raise HTTPException(
            status_code=400,
            detail="Invalid polish_desc_filename in audit.",
        )

    polish_dir = settings.storage_root / "polish_descriptions"
    target    = polish_dir / fn
    # Defence in depth: resolved path must remain inside polish_dir
    try:
        target_resolved    = target.resolve()
        polish_dir_resolved = polish_dir.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Path resolution failed: {exc}") from exc
    if polish_dir_resolved not in target_resolved.parents:
        raise HTTPException(
            status_code=400,
            detail="Resolved path escapes polish_descriptions directory.",
        )

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Polish description not on disk: {fn}")

    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc

    # Clear audit pointers so the regenerate flow can write a fresh file
    for k in ("polish_desc_filename", "polish_desc_path", "polish_desc_file_exists",
              "polish_desc_generated_at"):
        audit.pop(k, None)
    try:
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        # Filesystem delete already succeeded; audit-write failure is
        # logged but not raised so the operator sees the deletion result.
        log.warning("[%s] polish_desc audit-clear failed after unlink", batch_id)

    log.info("[dashboard] deleted polish description %s for batch %s", fn, batch_id)
    try:
        tl.log_event(audit_path, "polish_description_deleted", "dashboard", "user",
                     detail={"filename": fn})
    except Exception:
        pass

    return {"ok": True, "deleted": fn, "batch_id": batch_id}


@router.post("/batches/{batch_id}/regenerate", dependencies=[_op_auth])
def regenerate_outputs(batch_id: str) -> Dict[str, Any]:
    """Delete existing output files and re-trigger processing for a batch."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    batch_dir = _OUTPUTS / batch_id
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    # Delete generated output files (keep source/ and audit.json)
    deleted_files = []
    keep = {"audit.json", "source", "timeline.jsonl", "dhl_docs", "agency_docs"}
    for item in batch_dir.iterdir():
        if item.name in keep or item.name.startswith("."):
            continue
        if item.is_dir():
            continue
        item.unlink()
        deleted_files.append(item.name)

    # Clear output-related fields in audit to reset state
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        # Reset output file references but preserve inputs and tracking
        for key in ["pz_pdf_path", "calc_xlsx_path", "audit_pdf_path",
                     "audit_en_path", "audit_pl_path", "audit_memo_path",
                     "corrections_path", "sad_status", "pz_status"]:
            audit.pop(key, None)
        audit["regenerate_requested_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(audit_path, audit)
        tl.log_event(audit_path, "regenerate_requested", "dashboard", "user",
                     detail={"deleted_files": deleted_files})
    except Exception as exc:
        log.warning("[dashboard] regenerate audit update: %s", exc)

    return {"ok": True, "deleted_files": deleted_files,
            "message": "Output files deleted. Re-upload or re-process to regenerate.",
            "files": _build_files_detail(batch_id)}


# ── Operator overrides ────────────────────────────────────────────────────────

from ..services.batch_state_normalizer import (
    ALLOWED_OVERRIDE_TYPES,
    FORBIDDEN_OVERRIDE_TYPES,
)


class OperatorOverrideRequest(BaseModel):
    check: str
    reason: str
    evidence_reference: str = ""


@router.post("/batches/{batch_id}/operator-override", dependencies=[_admin_auth])
def add_operator_override(
    batch_id: str,
    body: OperatorOverrideRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Record an operator acknowledgment for a non-financial blocker.

    Rules
    -----
    - Forbidden checks (financial) are always rejected (400).
    - check must be in ALLOWED_OVERRIDE_TYPES (400 otherwise).
    - reason must be at least 20 characters (400).
    - Batch must exist (404).
    - Batch must currently have audit.status == "blocked" (409 otherwise).
    - For non-parse-warning checks: check must appear in audit.failed_checks (409).
    - For invoice_number_parse_warning: at least one "Parse warning:" amendment flag must exist (409).
    - Duplicate override (same check already accepted) → 400.
    - audit.status / failed_checks / verification / amendment_flags are NEVER modified.
    - operator_overrides list is append-only.
    """
    _validate_batch_id(batch_id)

    check  = (body.check or "").strip()
    reason = (body.reason or "").strip()

    # ── Validate check type ──────────────────────────────────────────────────
    if check in FORBIDDEN_OVERRIDE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Override of '{check}' is forbidden — financial or document-completeness check.",
        )
    if check not in ALLOWED_OVERRIDE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or non-overridable check: '{check}'.",
        )

    # ── Validate reason length ───────────────────────────────────────────────
    if len(reason) < 20:
        raise HTTPException(
            status_code=400,
            detail="reason must be at least 20 characters.",
        )

    # ── Load audit ───────────────────────────────────────────────────────────
    batch_dir  = _OUTPUTS / batch_id
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    with batch_write_lock(batch_id):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Corrupt audit: {exc}")

        # ── Batch must be blocked ────────────────────────────────────────────
        if (audit.get("status") or "") != "blocked":
            raise HTTPException(
                status_code=409,
                detail="Batch is not currently blocked; override not applicable.",
            )

        existing_overrides = audit.get("operator_overrides") or []

        # ── Duplicate guard ──────────────────────────────────────────────────
        already = [
            o for o in existing_overrides
            if o.get("check") == check and o.get("batch_id") == batch_id
        ]
        if already:
            raise HTTPException(
                status_code=400,
                detail=f"Check '{check}' has already been overridden for this batch.",
            )

        # ── Check must currently be failing ─────────────────────────────────
        if check == "invoice_number_parse_warning":
            amendment_flags = audit.get("amendment_flags") or []
            parse_flags = [f for f in amendment_flags if f.startswith("Parse warning:")]
            if not parse_flags:
                raise HTTPException(
                    status_code=409,
                    detail="No 'Parse warning:' amendment flags found; override not applicable.",
                )
        else:
            failed_checks = set(audit.get("failed_checks") or [])
            if check not in failed_checks:
                raise HTTPException(
                    status_code=409,
                    detail=f"Check '{check}' is not in failed_checks for this batch.",
                )

        # ── Build override record ────────────────────────────────────────────
        operator = (request.headers.get("X-Operator-Id") or "").strip() or "operator"
        original_value = (audit.get("verification") or {}).get(check)

        override_record = {
            "override_id":        str(uuid.uuid4()),
            "check":              check,
            "reason":             reason,
            "operator":           operator,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
            "evidence_reference": body.evidence_reference or "",
            "batch_id":           batch_id,
            "original_value":     original_value,
        }

        # ── Append-only write ────────────────────────────────────────────────
        existing_overrides.append(override_record)
        audit["operator_overrides"] = existing_overrides

        write_json_atomic(audit_path, audit)

        tl.log_event(
            audit_path,
            "operator_override_added",
            "dashboard",
            operator,
            detail={
                "override_id": override_record["override_id"],
                "check":       check,
                "reason":      reason[:120],
            },
        )

    log.info("[dashboard] operator override added batch=%s check=%s by=%s",
             batch_id, check, operator)

    return {
        "ok":          True,
        "override_id": override_record["override_id"],
        "check":       check,
        "batch_id":    batch_id,
        "operator":    operator,
        "timestamp":   override_record["timestamp"],
    }


# ── Broker follow-up drafts (read-only detection + operator-approved send) ───
#
# Detects blocked batches whose failed_checks include `invoice_refs_match` or
# `cif_match` (forbidden override types), generates a draft broker email per
# batch, and lets the operator send approved drafts via the email queue.
#
# Strict rules:
#   - GET creates drafts only — never sends.
#   - POST sends an existing draft only — never auto-creates and never modifies
#     failed_checks, amendment_flags, customs_declaration, status, or totals.
#   - Idempotent: a batch with a 'draft' or 'sent' record is skipped on rescan.

from ..services import broker_followup_detector as _bfd
from ..services import email_service as _email_svc


@router.get("/broker-followups", dependencies=[_auth])
def list_broker_followups() -> Dict[str, Any]:
    """
    Scan all batches; for each eligible blocked batch with no live draft,
    create a draft and persist it under audit.broker_followup_drafts[].
    Returns the full list of drafts (newly created + pre-existing).

    NEVER sends. NEVER mutates other audit fields.
    """
    if not _OUTPUTS.exists():
        return {"drafts": [], "created": 0, "scanned": 0}

    drafts_out: List[Dict[str, Any]] = []
    created = 0
    scanned = 0

    for batch_dir in sorted(_OUTPUTS.iterdir()):
        if not batch_dir.is_dir():
            continue
        audit_path = batch_dir / "audit.json"
        if not audit_path.exists():
            continue
        scanned += 1

        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not _bfd.is_eligible(audit):
            continue

        # Pre-existing live draft → just surface it, do not re-create
        if _bfd.has_live_draft(audit):
            existing = _bfd.find_draft(audit)
            if existing:
                drafts_out.append(existing)
            continue

        # Build a new draft and persist (additive write)
        draft = _bfd.build_draft(audit)
        if draft is None:
            continue

        with batch_write_lock(batch_dir.name):
            try:
                fresh = json.loads(audit_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            # Re-check inside lock (another process may have created one)
            if _bfd.has_live_draft(fresh):
                existing = _bfd.find_draft(fresh)
                if existing:
                    drafts_out.append(existing)
                continue
            existing_drafts = fresh.get("broker_followup_drafts") or []
            existing_drafts.append(draft)
            fresh["broker_followup_drafts"] = existing_drafts
            write_json_atomic(audit_path, fresh)

            tl.log_event(
                audit_path,
                "broker_followup_draft_created",
                "dashboard",
                "system",
                detail={
                    "draft_id": draft["draft_id"],
                    "reason":   draft["reason"],
                },
            )

        drafts_out.append(draft)
        created += 1

    log.info("[dashboard] broker-followups scan: scanned=%d created=%d total=%d",
             scanned, created, len(drafts_out))

    return {
        "drafts":  drafts_out,
        "created": created,
        "scanned": scanned,
    }


class BrokerFollowupSendRequest(BaseModel):
    to:           str = ""    # required at send time; if empty, route returns 400
    cc:           str = ""    # optional CC
    from_address: str = ""    # optional sender override


@router.post("/broker-followups/{batch_id}/send", dependencies=[_op_auth])
def send_broker_followup(
    batch_id: str,
    body:     BrokerFollowupSendRequest,
    request:  Request,
) -> Dict[str, Any]:
    """
    Queue an existing broker follow-up draft via email_service.queue_email.

    Rules
    -----
    - Batch must exist (404).
    - A 'draft'-status broker_followup_drafts entry must exist (409).
    - 'to' is required (400).
    - On success: draft.status = 'sent', sent_at + queue_id recorded.
    - NEVER modifies failed_checks, amendment_flags, status, totals,
      customs_declaration, or operator_overrides.
    """
    _validate_batch_id(batch_id)

    if not body.to or not body.to.strip():
        raise HTTPException(status_code=400, detail="'to' is required.")

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    with batch_write_lock(batch_id):
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Corrupt audit: {exc}")

        drafts = audit.get("broker_followup_drafts") or []
        # Find latest 'draft'-status entry
        target_idx: Optional[int] = None
        for idx, d in enumerate(drafts):
            if isinstance(d, dict) and d.get("status") == "draft":
                target_idx = idx
        if target_idx is None:
            raise HTTPException(
                status_code=409,
                detail="No 'draft'-status broker follow-up to send.",
            )

        target = drafts[target_idx]
        subject = target.get("subject") or ""
        body_text = target.get("body") or ""

        # Queue via existing email service. Body served as plain text in HTML wrapper.
        body_html = (
            "<pre style=\"font-family: ui-sans-serif, system-ui, Arial, sans-serif;"
            " font-size: 14px; white-space: pre-wrap;\">"
            + body_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</pre>"
        )

        try:
            queue_id = _email_svc.queue_email(
                to           = body.to.strip(),
                subject      = subject,
                body_html    = body_html,
                body_text    = body_text,
                batch_id     = batch_id,
                cc           = body.cc or "",
                from_address = body.from_address or "",
                email_type   = "broker_followup",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"queue_email failed: {exc}")

        operator = (request.headers.get("X-Operator-Id") or "").strip() or "operator"
        target["status"]    = "sent"
        target["sent_at"]   = datetime.now(timezone.utc).isoformat()
        target["queue_id"]  = queue_id
        target["sent_by"]   = operator
        target["sent_to"]   = body.to.strip()
        target["sent_cc"]   = body.cc or ""
        drafts[target_idx]  = target
        audit["broker_followup_drafts"] = drafts

        write_json_atomic(audit_path, audit)

        tl.log_event(
            audit_path,
            "broker_followup_sent",
            "dashboard",
            operator,
            detail={
                "draft_id": target.get("draft_id"),
                "queue_id": queue_id,
                "to":       body.to.strip(),
            },
        )

    log.info("[dashboard] broker-followup sent batch=%s queue_id=%s by=%s",
             batch_id, queue_id, operator)

    return {
        "ok":        True,
        "draft_id":  target.get("draft_id"),
        "queue_id":  queue_id,
        "batch_id":  batch_id,
        "status":    "sent",
        "sent_at":   target["sent_at"],
        "sent_to":   target["sent_to"],
    }


# ── Broker reply analyzer (pure read-only classifier) ───────────────────────
#
# Operator pastes a broker email reply; this route runs a deterministic
# keyword + regex classifier and returns a structured suggestion. It NEVER:
#   - writes to audit
#   - sends or queues email
#   - creates a draft
#   - applies an override
#   - touches any file or storage
#
# Classification cases (first-match wins, ordered A → B → C → E → D):
#   A: invoice attached / forwarded (positive resolution candidate)
#   B: SAD amendment in flight (must stop and wait)
#   C: multiple-invoice or partial-shipment explanation (validate math)
#   D: clarifying question / asks us for info
#   E: rejects the discrepancy outright
#
# This module-level helper is read-only and side-effect-free.

class BrokerReplyAnalyzeRequest(BaseModel):
    text: str


_RE_INVOICE_ID  = re.compile(r"\b[A-Z]{2,4}\s*/\s*\d{2}-\d{2}\s*/\s*\d{2,6}\b")
_RE_USD_AMOUNT  = re.compile(
    r"(?:USD|US\$|\$)\s*([\d]{1,3}(?:[,\s]\d{3})*(?:\.\d+)?)"
    r"|"
    r"([\d]{1,3}(?:,\d{3})+(?:\.\d+)?)\s*(?:USD|US\$)?",
    re.IGNORECASE,
)

# Lower-case substrings; match against `text.lower()`.
_SIGNAL_INVOICE_ATTACHED = (
    "attached invoice",
    "please find invoice",
    "please find attached",
    "find attached",
    "find the invoice",
    "invoice is attached",
    "attached please find",
    "we attach",
    "see attached",
)
_SIGNAL_SAD_AMENDMENT = (
    "amend sad",
    "amended sad",
    "corrected sad",
    "correct sad",
    "new mrn",
    "sad will be amended",
    "sad needs amendment",
    "sad amendment",
    "amendment of the sad",
    "issue a corrected",
    "issue a new sad",
)
_SIGNAL_MULTIPLE_INVOICES = (
    "multiple invoices",
    "several invoices",
    "two invoices",
    "three invoices",
    "partial shipment",
    "split shipment",
    "consolidated",
    "combined invoices",
    "made up of",
    "comprises",
    "comprised of",
)
_SIGNAL_REQUESTS_INFO = (
    "please confirm",
    "please provide",
    "could you confirm",
    "could you provide",
    "kindly confirm",
    "kindly provide",
    "can you confirm",
    "can you provide",
    "we need",
    "we require",
)
_SIGNAL_REJECTS = (
    "values are correct",
    "correct as declared",
    "correct as stated",
    "no discrepancy",
    "no error",
    "we disagree",
    "we do not agree",
    "figures are correct",
    "amount is correct",
    "the cif is correct",
)


def _classify_broker_reply(text: str) -> Dict[str, Any]:
    """Pure deterministic classifier. Same input → same output."""
    if not isinstance(text, str):
        text = ""
    body  = text.strip()
    lower = body.lower()

    # Signal matrix
    s_attach    = any(p in lower for p in _SIGNAL_INVOICE_ATTACHED)
    s_amend     = any(p in lower for p in _SIGNAL_SAD_AMENDMENT)
    s_multi     = any(p in lower for p in _SIGNAL_MULTIPLE_INVOICES)
    s_requests  = any(p in lower for p in _SIGNAL_REQUESTS_INFO)
    s_rejects   = any(p in lower for p in _SIGNAL_REJECTS)

    # Extracted entities
    invoice_ids = sorted({
        re.sub(r"\s+", "", m.group(0))
        for m in _RE_INVOICE_ID.finditer(body)
    })
    usd_amounts: List[str] = []
    for m in _RE_USD_AMOUNT.finditer(body):
        amt = (m.group(1) or m.group(2) or "").strip()
        if amt:
            usd_amounts.append(amt)
    # de-dupe preserving order
    seen, deduped = set(), []
    for a in usd_amounts:
        if a not in seen:
            seen.add(a)
            deduped.append(a)
    usd_amounts = deduped

    # Case selection (priority order)
    case: Optional[str] = None
    rec : str = ""
    conf: str = "low"

    if s_attach:
        case = "A"
        rec  = ("Case A — invoice may be attached. Verify the attachment, upload it to "
                "the batch, and re-run inspection (NOT PZ). Confirm invoice_refs_match "
                "and cif_match are True before running PZ.")
    elif s_amend:
        case = "B"
        rec  = ("Case B — SAD amendment in flight. STOP. Do not re-run anything. Wait "
                "for the amended SAD / new MRN to arrive, then start from scratch.")
    elif s_multi:
        case = "C"
        rec  = ("Case C — explanation references multiple invoices or a partial shipment. "
                "Validate that the listed invoices total exactly USD 17,049. If yes, "
                "request and upload the missing documents, then re-run inspection. If "
                "no, push back.")
    elif s_rejects:
        case = "E"
        rec  = ("Case E — broker rejects the discrepancy. Do NOT proceed. Escalate to "
                "broker management; consider phone follow-up. Do not adjust totals or "
                "override checks.")
    elif s_requests:
        case = "D"
        rec  = ("Case D — broker is asking us for information (stalling or seeking input). "
                "Answer narrowly without conceding figures. Restart the 24-hour clock.")
    else:
        case = None
        rec  = ("Could not classify reliably. Read the email manually and pick the matching "
                "case from the operator playbook. Do not run PZ or override checks based on "
                "this reply alone.")

    # Confidence heuristic
    matched = sum([s_attach, s_amend, s_multi, s_requests, s_rejects])
    if case is None:
        conf = "low"
    elif matched >= 2 or (case == "A" and invoice_ids):
        conf = "high"
    elif matched == 1:
        conf = "medium"
    else:
        conf = "low"

    return {
        "case":               case,
        "confidence":         conf,
        "signals": {
            "has_invoice_attachment_hint": s_attach,
            "mentions_amendment":          s_amend,
            "mentions_multiple_invoices":  s_multi,
            "requests_info":               s_requests,
            "rejects_discrepancy":         s_rejects,
        },
        "extracted": {
            "invoice_ids":   invoice_ids,
            "usd_amounts":   usd_amounts,
        },
        "recommended_action": rec,
    }


@router.post("/broker-reply/analyze", dependencies=[_op_auth])
def analyze_broker_reply(body: BrokerReplyAnalyzeRequest) -> Dict[str, Any]:
    """Read-only classifier for pasted broker email replies.

    Returns a structured suggestion. NEVER mutates audit, queue, drafts,
    or any other state.
    """
    return _classify_broker_reply(body.text or "")


# ── Soft-delete batch ─────────────────────────────────────────────────────────

# ── Archive helpers ───────────────────────────────────────────────────────────

def _archive_summary(batch_id: str, a: dict) -> dict:
    """Return a summary dict for an archived shipment."""
    arch        = a.get("archive_meta", {})
    tracking_no = a.get("tracking_no") or a.get("inputs", {}).get("tracking_no") or ""
    doc_no      = a.get("doc_no") or a.get("inputs", {}).get("doc_no") or ""
    return {
        "batch_id":    batch_id,
        "awb":         tracking_no or doc_no or batch_id,
        "doc_no":      doc_no,
        "carrier":     a.get("carrier") or a.get("inputs", {}).get("carrier") or "—",
        "status":      a.get("status", "unknown"),
        "archived_at": arch.get("archived_at"),
        "delete_after":arch.get("delete_after"),
        "reason":      arch.get("reason", ""),
        "archived_by": arch.get("archived_by", "user"),
    }


def _validate_batch_id(batch_id: str) -> None:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")


# ── Action diagnostics endpoint ───────────────────────────────────────────────

@router.get("/batches/{batch_id}/action-diagnostics", dependencies=[_auth])
def action_diagnostics(batch_id: str) -> Dict[str, Any]:
    """
    Returns per-action enabled/disabled status derived purely from audit fields.
    Read-only — no mutations, no secrets, no financial data.
    """
    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read batch audit.")

    status     = audit.get("status", "")
    inputs     = audit.get("inputs") or {}
    cd         = audit.get("customs_declaration") or {}
    arp        = audit.get("agency_reply_package") or {}
    pz_done    = status in {"success", "partial"} or audit.get("pz_generated") is True
    has_sad    = bool(inputs.get("zc429"))
    has_customs= bool(cd.get("mrn") or cd.get("duty_a00_pln") is not None)
    has_invoices = bool(inputs.get("invoices"))

    # ── Polish description ────────────────────────────────────────────────────
    pd_file = audit.get("polish_desc_filename")
    pd_exists = False
    if pd_file:
        pd_exists = any(
            (_OUTPUTS / batch_id / pd_file).is_file(),
            ((_OUTPUTS / batch_id / "dhl_docs" / pd_file).is_file(),)
        ) if False else (
            (_OUTPUTS / batch_id / pd_file).is_file()
            or (_OUTPUTS / batch_id / "dhl_docs" / pd_file).is_file()
        )

    # ── DSK ──────────────────────────────────────────────────────────────────
    dsk_file = audit.get("dsk_filename")
    dsk_exists = False
    if dsk_file:
        try:
            from .routes_dsk import _DSK_OUTPUT_DIR
            dsk_exists = (_DSK_OUTPUT_DIR / dsk_file).is_file()
        except Exception:
            pass

    # CIF authority for the DSK button hint. The DSK action gate (routes_dsk)
    # resolves the customs value through the single cif_authority ladder, so this
    # button hint must reflect the SAME authority — never a raw
    # invoice_totals.total_cif_usd of 0, which falsely disabled DSK for shipments
    # whose CIF resolves only from the AWB Custom Val (AWB 2315714531: invoice CIF
    # 0, AWB Custom Val 732). is_resolved is True only for state=resolved, so a
    # declared_zero / unknown value correctly leaves the button disabled.
    try:
        from ..services.cif_authority import get_cif_authority
        _dsk_cif      = get_cif_authority(audit)
        _dsk_cif_ok   = bool(_dsk_cif.get("is_resolved"))
        _dsk_cif_why  = (
            "Ready — CIF value available"
            if _dsk_cif_ok
            else (_dsk_cif.get("blocker_reason")
                  or "CIF value required (run PZ or recheck first)")
        )
    except Exception:
        _dsk_cif_ok  = bool((audit.get("invoice_totals") or {}).get("total_cif_usd"))
        _dsk_cif_why = (
            "Ready — CIF value available"
            if _dsk_cif_ok
            else "CIF value required (run PZ or recheck first)"
        )

    # ── Agency email ─────────────────────────────────────────────────────────
    arp_queue_id = arp.get("queue_id") or arp.get("email_id")
    arp_status   = arp.get("status")

    # Check email_queue.json for queue_id confirmation
    eq_status = None
    if arp_queue_id:
        try:
            from ..services.email_service import get_all_emails
            for entry in get_all_emails(limit=500):
                if entry.get("id") == arp_queue_id:
                    eq_status = entry.get("status")
                    break
        except Exception:
            pass

    # ── PZ files on disk ─────────────────────────────────────────────────────
    batch_dir = _OUTPUTS / batch_id
    pz_pdf_exists  = any(
        f.suffix.lower() == ".pdf" and f.name not in _AUDIT_ONLY_PDFS
        for f in batch_dir.iterdir()
    ) if batch_dir.exists() else False
    pz_xlsx_exists = any(
        f.suffix.lower() == ".xlsx" for f in batch_dir.iterdir()
    ) if batch_dir.exists() else False

    # ── Tracking ─────────────────────────────────────────────────────────────
    tracking = audit.get("tracking") or {}
    tracking_cache_path = batch_dir / "tracking_cache.json"
    if tracking_cache_path.exists():
        try:
            tracking = json.loads(tracking_cache_path.read_text()) or tracking
        except Exception:
            pass
    t_status = tracking.get("status", "")
    t_source = tracking.get("source", "")
    t_blocking = t_status not in {"not_found", "pre_transit", ""}
    t_note = None
    if t_source == "dhl_api_404" or t_status == "not_found":
        t_note = "DHL tracking not available (API 404). Non-blocking — public DHL tracking may work."

    actions: Dict[str, Any] = {
        "run_pz": {
            "enabled": has_sad and has_invoices and has_customs,
            "reason": (
                "Ready — SAD, invoices, and customs all present"
                if (has_sad and has_invoices and has_customs)
                else " + ".join(filter(None, [
                    "SAD missing" if not has_sad else None,
                    "no invoice files" if not has_invoices else None,
                    "customs not parsed" if not has_customs else None,
                ]))
            ),
            "missing": [
                k for k, v in {
                    "zc429_sad": has_sad,
                    "invoices": has_invoices,
                    "customs_declaration": has_customs,
                }.items() if not v
            ],
            "pz_already_done": pz_done,
        },
        "rerun_pz": {
            "enabled": pz_done and has_sad and has_invoices and has_customs,
            "reason": "Re-run PZ with updated inputs" if pz_done else "PZ not yet generated",
        },
        "download_pz_pdf": {
            "enabled": pz_pdf_exists,
            "path_exists": pz_pdf_exists,
        },
        "download_pz_xlsx": {
            "enabled": pz_xlsx_exists,
            "path_exists": pz_xlsx_exists,
        },
        "generate_polish_desc": {
            "enabled": has_invoices and not pd_exists,
            "already_generated": pd_exists,
            "path_exists": pd_exists,
            "reason": (
                "Already generated — use download"
                if pd_exists else
                ("Ready to generate" if has_invoices else "No invoice files")
            ),
        },
        "download_polish_desc": {
            "enabled": pd_exists,
            "path_exists": pd_exists,
            "file_missing_repair": bool(pd_file and not pd_exists),
        },
        "generate_dsk": {
            "enabled": not dsk_exists and _dsk_cif_ok,
            "already_generated": dsk_exists,
            "path_exists": dsk_exists,
            "reason": (
                "Already generated — use download"
                if dsk_exists else _dsk_cif_why
            ),
        },
        "download_dsk": {
            "enabled": dsk_exists,
            "path_exists": dsk_exists,
            "file_missing_repair": bool(dsk_file and not dsk_exists),
        },
        "build_agency_email": {
            "enabled": pd_exists and has_sad and has_customs and not pz_done,
            "reason": (
                "Ready to build agency package"
                if (pd_exists and has_sad and has_customs and not pz_done)
                else " + ".join(filter(None, [
                    "Polish description required" if not pd_exists else None,
                    "SAD required" if not has_sad else None,
                    "Customs data required" if not has_customs else None,
                    "Already sent after PZ" if pz_done else None,
                ]))
            ),
        },
        "send_agency_email": {
            "enabled": bool(arp_queue_id and arp_status in {"queued", None}),
            "queue_id": arp_queue_id,
            "package_status": arp_status,
            "email_queue_status": eq_status,
            "endpoint": f"POST /api/v1/admin/email-queue/{arp_queue_id}/send" if arp_queue_id else None,
            "reason": (
                "Send via SMTP: POST /api/v1/admin/email-queue/{id}/send body={'method':'smtp'}"
                if arp_queue_id and arp_status not in {"sent"}
                else ("Already sent — idempotent" if arp_status == "sent" else "No agency email queued")
            ),
        },
        "wfirma_export": {
            "enabled": pz_done and has_sad,
            "reason": (
                "Ready — PZ generated and SAD present"
                if (pz_done and has_sad)
                else " + ".join(filter(None, [
                    "PZ not yet generated" if not pz_done else None,
                    "SAD required" if not has_sad else None,
                ]))
            ),
            "requires": "pz_generated + zc429_sad",
        },
        "tracking_refresh": {
            "enabled": True,
            "tracking_status": t_status,
            "source": t_source,
            "blocking": False,   # tracking 404 is never blocking
            "note": t_note,
        },
        "reparse_sad": {
            "enabled": has_sad,
            "reason": "Re-parse SAD and update customs_declaration" if has_sad else "No SAD file uploaded",
            "safe": "Never overwrites non-null fields with null; XML source beats PDF source",
        },
    }

    return {
        "batch_id": batch_id,
        "pz_status": status,
        "pz_generated": pz_done,
        "clearance_status": _derive_clearance_status(audit),
        "actions": actions,
    }


# ── Email Evidence V2 — read-only API ───────────────────────────────────────

@router.get("/batches/{batch_id}/email-evidence", dependencies=[_auth])
def email_evidence_for_batch(batch_id: str) -> Dict[str, Any]:
    """Return local email evidence summary + 9-stage timeline for the AWB on this batch."""
    from ..services import email_evidence_store as evs
    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read batch audit.")
    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if not awb:
        return {"batch_id": batch_id, "awb": None, "summary": {}, "timeline": [], "messages": []}

    doc      = evs.get_by_awb(awb)
    summary  = doc.get("summary", {})
    pz_done  = (
        _derive_status(audit) in {"success", "partial"}
        or audit.get("pz_generated") is True
        or bool((audit.get("files", {}).get("pdf") or {}).get("sha256"))
        or bool(audit.get("pz_output", {}).get("generated_at"))
    )
    archived = bool(audit.get("archived"))

    # Fixed 9-stage timeline. Outgoing stages distinguish queued vs sent.
    def _outgoing_status(sent_key: str, queued_key: str) -> str:
        if summary.get(sent_key):    return "sent"
        if summary.get(queued_key):  return "queued"
        return "missing"

    stages = [
        {"key": "dhl_request",      "label": "DHL request",            "status": "received" if summary.get("dhl_request_received") else "missing"},
        {"key": "our_dhl_reply",    "label": "Our DHL reply",          "status": _outgoing_status("our_dhl_reply_sent", "our_dhl_reply_queued")},
        {"key": "dhl_documents",    "label": "DHL document response",  "status": "received" if summary.get("dhl_documents_received") else "missing"},
        {"key": "agency_forward",   "label": "Agency forward",         "status": _outgoing_status("agency_forward_sent", "agency_forward_queued")},
        {"key": "agency_sad_reply", "label": "Agency SAD/PZC reply",   "status": "received" if summary.get("agency_sad_received")  else "missing"},
        {"key": "pz_generated",     "label": "PZ generated",           "status": "processed" if pz_done else "missing"},
        {"key": "dhl_invoice",      "label": "DHL invoice",            "status": "received" if summary.get("dhl_invoice_received")    else "missing"},
        {"key": "agency_invoice",   "label": "Agency invoice",         "status": "received" if summary.get("agency_invoice_received") else "missing"},
        {"key": "shipment_closed",  "label": "Shipment closed",        "status": "processed" if archived else "missing"},
    ]

    # Per-stage timestamps + message refs
    messages = []
    for thread in doc.get("threads", []):
        for m in thread.get("messages", []):
            messages.append({
                "message_id":      m.get("message_id"),
                "thread_id":       thread.get("thread_id"),
                "direction":       m.get("direction"),
                "sender":          m.get("sender"),
                "to":              m.get("to"),
                "subject":         m.get("subject"),
                "timestamp":       m.get("timestamp"),
                "event_type":      m.get("event_type"),
                "source":          m.get("source"),
                "processed":       m.get("processed", False),
                "delivery_status": m.get("delivery_status"),  # queued|sent|failed|None
                "sent_at":         m.get("sent_at"),
                "queued_at":       m.get("queued_at"),
                "provider_message_id": m.get("provider_message_id"),
                "attachment_count": len(m.get("attachments") or []),
                "attachments":  [{"filename": a.get("filename"), "sha256": a.get("sha256"),
                                  "size": a.get("size"), "document_type": a.get("document_type")}
                                 for a in (m.get("attachments") or [])],
            })

    # Annotate stages with latest matching message
    for st in stages:
        ev = next((m for m in sorted(messages, key=lambda x: x.get("timestamp") or "", reverse=True)
                   if m.get("event_type") == st["key"]), None)
        if ev:
            st["timestamp"] = ev.get("timestamp")
            st["sender"]    = ev.get("sender")
            st["attachment_count"] = ev.get("attachment_count", 0)
            st["source"]    = ev.get("source")

    return {
        "batch_id":     batch_id,
        "awb":          awb,
        "summary":      summary,
        "stages":       stages,
        "messages":     messages,
        "last_scan_at": doc.get("last_scan_at"),
        "last_message_at": doc.get("last_message_at"),
        "batch_ids":    doc.get("batch_ids", []),
    }


# ── DHL action-state — operator next-action guidance for the email tab ──────
#
# Read-only readiness endpoint. Tells the dashboard which single primary
# button to render in the DHL/Customs section based on:
#   * audit fields    (clearance_decision.clearance_path,
#                      customs_package_generated_at,
#                      proactive_dispatch_*, dsk_*, agency_*)
#   * action_proposals (existing dhl_proactive_dispatch proposal status)
#   * evidence summary (dhl_request_received, our_dhl_reply_*)
#
# The endpoint NEVER mutates state and NEVER triggers email send. Buttons
# returned by this endpoint either:
#   (a) call /api/v1/dhl/generate-customs-package    (creates files, no email)
#   (b) call /api/v1/dhl/proactive-dispatch          (creates proposal, no queue)
#   (c) link to the existing approve / queue flow    (queue stays behind
#                                                     /api/v1/action-proposals/{id}/approve+queue)
# No other email-send path is exposed by this endpoint.

def _find_active_proactive_proposal(audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Most recent dhl_proactive_dispatch proposal in {pending_review, approved, queued}."""
    proposals = audit.get("action_proposals") or []
    active = [p for p in proposals
              if p.get("type") == "dhl_proactive_dispatch"
              and p.get("status") in ("pending_review", "approved", "queued")]
    if not active:
        return None
    return sorted(active, key=lambda p: p.get("created_at") or "", reverse=True)[0]


def _evidence_summary_for(awb: str) -> Dict[str, Any]:
    """Best-effort load of the email-evidence summary; never raises."""
    if not awb:
        return {}
    try:
        from ..services import email_evidence_store as evs
        return (evs.get_by_awb(awb) or {}).get("summary") or {}
    except Exception:
        return {}


def _compute_dhl_action_state(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure-function decision: given an audit dict, return the next-action card
    payload. State priority is documented inline.
    """
    awb       = str(audit.get("awb") or audit.get("tracking_no") or "")
    batch_id  = audit.get("batch_id") or ""
    cd        = audit.get("clearance_decision") or {}
    clearance_path = (cd.get("clearance_path") or "").strip()
    # Spec/legacy alias normalization — accept both "agency_clearance"
    # (spec) and "external_agency_clearance" (legacy) etc.
    from ..services.clearance_path_alias import (
        is_agency_clearance as _is_agency_clearance,
    )

    customs_pkg_generated  = bool(audit.get("customs_package_generated_at"))
    proactive_sent         = bool(audit.get("proactive_dispatch_sent_at"))
    proactive_failed       = bool(audit.get("proactive_dispatch_failed_at"))
    proactive_proposal     = _find_active_proactive_proposal(audit)
    dsk_present            = bool(audit.get("dsk_filename") or audit.get("dsk_reference"))
    agency_active          = bool(
        audit.get("agency_name")
        or (audit.get("agency_reply_package") or {}).get("status")
        or _is_agency_clearance(clearance_path)
    )
    dhl_email_received     = bool((audit.get("dhl_email") or {}).get("received"))

    summary = _evidence_summary_for(awb)
    dhl_request_received   = bool(summary.get("dhl_request_received"))
    our_dhl_reply_present  = bool(
        summary.get("our_dhl_reply_sent")
        or summary.get("our_dhl_reply_queued")
    )

    proactive_failed_at = audit.get("proactive_dispatch_failed_at") or None
    proactive_failure_reason = audit.get("proactive_dispatch_failure_reason") or None
    if isinstance(proactive_failure_reason, str) and len(proactive_failure_reason) > 200:
        # Defensive read-side truncation: the audit is already bounded to
        # ≤200 chars by Slice A's _record_proactive_failure, but we re-bound
        # in case of legacy data.
        proactive_failure_reason = proactive_failure_reason[:200]

    detected = {
        "customs_package_generated":   customs_pkg_generated,
        "proactive_dispatch_sent":     proactive_sent,
        # E1-ii: the existing boolean is preserved unchanged for backward
        # compatibility. Two new sibling fields are added below for the
        # failure-retry surface.
        "proactive_dispatch_failed":   proactive_failed,
        "proactive_dispatch_failed_at":      proactive_failed_at,
        "proactive_dispatch_failure_reason": proactive_failure_reason,
        "proactive_proposal":          (
            None if proactive_proposal is None else {
                "proposal_id": proactive_proposal.get("proposal_id"),
                "status":      proactive_proposal.get("status"),
                "created_by":  proactive_proposal.get("created_by"),
                "approved_by": proactive_proposal.get("approved_by"),
            }
        ),
        "dhl_request_received":        dhl_request_received,
        "our_dhl_reply_present":       our_dhl_reply_present,
        "dsk_generated":               dsk_present,
        "agency_active":               agency_active,
        "dhl_email_received":          dhl_email_received,
        "clearance_path":              clearance_path,
    }

    # Build the state-summary chips operator sees above the action button.
    badges: List[Dict[str, str]] = []
    if our_dhl_reply_present:
        badges.append({"key": "our_dhl_reply", "tone": "ok",
                       "label": "Our DHL reply found"})
    if dhl_request_received:
        badges.append({"key": "dhl_request", "tone": "ok",
                       "label": "DHL request found"})
    elif customs_pkg_generated:
        badges.append({"key": "dhl_request_missing", "tone": "warn",
                       "label": "DHL original request not found"})
    if not customs_pkg_generated:
        badges.append({"key": "customs_package_missing", "tone": "warn",
                       "label": "Customs package not generated"})
    if proactive_sent:
        badges.append({"key": "proactive_sent", "tone": "ok",
                       "label": "Proactive package sent"})
    if proactive_failed:
        badges.append({"key": "proactive_failed", "tone": "warn",
                       "label": "Proactive dispatch failed — retry available"})
    if dsk_present:
        badges.append({"key": "dsk_generated", "tone": "info",
                       "label": "DSK generated"})
    if agency_active:
        badges.append({"key": "agency_active", "tone": "info",
                       "label": "Agency clearance path active"})

    info_messages: List[str] = []
    primary_action: Optional[Dict[str, Any]] = None
    # Optional state identifier for branches that have no primary_action
    # but want to be addressable by a stable name. Today only the
    # awaiting-DHL info-only branch sets this; other info-only branches
    # leave state_id=None pending a future cycle (B5) to backfill ids.
    state_id: Optional[str] = None

    # ── Decision priority ───────────────────────────────────────────────────
    # 1. Agency path active → no proactive dispatch is applicable
    if agency_active:
        info_messages.append(
            "Agency clearance path is active — proactive dispatch flow does "
            "not apply. Use the existing agency forward UI."
        )
    # 2. Customs package missing → generate it first
    elif not customs_pkg_generated:
        primary_action = {
            "id":       "generate_customs_package",
            "label":    "Generate customs package",
            "tone":     "primary",
            "endpoint": f"/api/v1/dhl/generate-customs-package/{batch_id}",
            "method":   "POST",
            "body":     {"awb": awb},
            "reason":   "Customs package has not been generated yet. "
                        "Generate it before proactive dispatch.",
            "disabled": not awb,
            "disabled_reason": "AWB missing on this batch" if not awb else None,
        }
    # 3. Proactive proposal already exists → guide through approve/queue lane.
    #    Retry-failed-queue takes priority over the regular queue branch when
    #    a previous queue attempt failed and the proposal stayed in "approved"
    #    state (Slice A failure handler preserves status="approved" so the
    #    operator can retry).
    elif proactive_proposal is not None:
        pid    = proactive_proposal.get("proposal_id")
        status = proactive_proposal.get("status")
        if proactive_failed_at and status == "approved":
            # Failure-retry state (C3): proposal stayed at status="approved"
            # after queue_email raised in Slice A's failure handler. Operator
            # retries via the existing /queue endpoint with empty body (C1).
            #
            # Badge label is verbatim per C4. The general ``if proactive_failed:``
            # block higher up already appends a badge with key="proactive_failed",
            # tone="warn", and the verbatim label — so this branch does NOT
            # double-append. The ``proactive_failed`` boolean fires on the
            # same audit field this branch keys off, so the badge is
            # always present when the retry primary_action is present.
            #
            # The Inspect-proposal action is INFO-MESSAGE ONLY (C2) —
            # no GET on an invented route.
            #
            # The action object emits BOTH ``target`` (per the failure-retry
            # contract) and ``endpoint`` (the wired key the dashboard React
            # component already consumes for fetch). Both point to the same
            # /queue URL so the live UI keeps working without JSX edits (C6).
            info_messages.append(f"Last failure: {proactive_failed_at}")
            if proactive_failure_reason:
                info_messages.append(f"Reason: {proactive_failure_reason}")
            info_messages.append(
                f"Proposal ID: {pid} — open the Proposals tab to inspect."
            )
            _retry_url = f"/api/v1/action-proposals/{pid}/queue"
            primary_action = {
                "id":       "retry_failed_queue",
                "label":    "Retry queue",
                "method":   "POST",
                "endpoint": _retry_url,
                "tone":     "warn",
                "body":     {},
                "reason":   "Previous queue attempt failed — proposal "
                            "remains approved; retry sends the same email.",
                "disabled": False,
                "disabled_reason": None,
                "proposal_id":     pid,
                "proposal_status": status,
            }
        elif status == "pending_review":
            primary_action = {
                "id":       "approve_proactive_proposal",
                "label":    "Review & approve proactive proposal",
                "tone":     "primary",
                "endpoint": f"/api/v1/action-proposals/{pid}/approve",
                "method":   "POST",
                "body":     {"approved_by": "<admin>"},
                "reason":   "A proactive dispatch proposal is awaiting "
                            "approval. The approver MUST be a different "
                            "operator than the requester.",
                "disabled": False,
                "disabled_reason": None,
                "proposal_id":   pid,
                "proposal_status": status,
            }
        elif status == "approved":
            primary_action = {
                "id":       "queue_proactive_proposal",
                "label":    "Queue proactive dispatch email",
                "tone":     "primary",
                "endpoint": f"/api/v1/action-proposals/{pid}/queue",
                "method":   "POST",
                "body":     {},
                "reason":   "Proactive proposal is approved — queue the "
                            "email to send.",
                "disabled": False,
                "disabled_reason": None,
                "proposal_id":   pid,
                "proposal_status": status,
            }
        else:  # queued
            info_messages.append(
                f"Proactive dispatch proposal {pid} is queued — awaiting "
                "MCP/SMTP delivery confirmation."
            )
    # 4. Already sent → terminal info
    elif proactive_sent:
        info_messages.append(
            "Proactive customs package already dispatched. Awaiting Poland "
            "arrival / DHL response."
        )
        badges.append({"key": "awaiting_dhl", "tone": "info",
                       "label": "Awaiting DHL"})
        state_id = "awaiting_dhl"
    # 5. Customs package ready, no proposal, not sent → primary path
    else:
        primary_action = {
            "id":       "proactive_dispatch_request",
            "label":    "Send proactive customs package to DHL",
            "tone":     "primary",
            "endpoint": f"/api/v1/dhl/proactive-dispatch/{batch_id}",
            "method":   "POST",
            "body":     {"operator_id": "<your operator id>"},
            "reason":   "Customs package is ready and proactive dispatch has "
                        "not been sent. This creates a proposal — no email "
                        "is queued by this button.",
            "disabled": False,
            "disabled_reason": None,
        }

    # ── Secondary action — incoming DHL request reply ──────────────────────
    secondary_actions: List[Dict[str, Any]] = []
    if dhl_request_received and not our_dhl_reply_present:
        secondary_actions.append({
            "id":       "prepare_dhl_reply",
            "label":    "Prepare reply to DHL thread",
            "tone":     "primary",
            "endpoint": f"/api/v1/dhl/match-and-handle",
            "method":   "POST",
            "body":     {"batch_id": batch_id},
            "reason":   "An incoming DHL customs request is in the evidence "
                        "store. Build the same-thread reply package — no "
                        "email is queued by this button.",
            "disabled": False,
            "disabled_reason": None,
        })
    elif our_dhl_reply_present:
        info_messages.append(
            "DHL reply already found in mailbox — no duplicate send button "
            "shown unless DHL sends a new request."
        )

    # Compact human-readable state line
    if primary_action:
        state_summary = primary_action["reason"]
    elif info_messages:
        state_summary = info_messages[0]
    else:
        state_summary = "No DHL action required at this time."

    return {
        "batch_id":          batch_id,
        "awb":               awb,
        "detected":          detected,
        "badges":            badges,
        "primary_action":    primary_action,
        "secondary_actions": secondary_actions,
        "info_messages":     info_messages,
        "state_summary":     state_summary,
        "state_id":          state_id,
    }


@router.get("/batches/{batch_id}/dhl-action-state", dependencies=[_auth])
def dhl_action_state(batch_id: str) -> Dict[str, Any]:
    """
    Return the operator's next DHL/customs action for this batch.

    Read-only. Never queues email. Buttons returned by this endpoint go
    through existing /generate-customs-package, /proactive-dispatch
    (proposal-create only), or /action-proposals/{id}/approve+queue
    flows. No new send path is exposed here.
    """
    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read batch audit.")
    return _compute_dhl_action_state(audit)


@router.post("/batches/{batch_id}/email-evidence/rescan", dependencies=[_op_auth])
def email_evidence_rescan(batch_id: str) -> Dict[str, Any]:
    """Scan Zoho Mail for this AWB and store any new messages in the evidence store."""
    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if not awb:
        raise HTTPException(status_code=400, detail="Batch has no AWB.")

    try:
        from ..services.email_evidence_ingestor import scan_and_ingest
        return scan_and_ingest(awb, batch_id, audit_path, audit, limit=100)
    except Exception as exc:
        log.exception("[%s] email-evidence rescan failed", batch_id)
        return {"ok": False, "awb": awb, "error": str(exc)}


@router.post("/batches/{batch_id}/email-evidence/process", dependencies=[_op_auth])
def email_evidence_process(batch_id: str) -> Dict[str, Any]:
    """Run the evidence processor against stored evidence (no Zoho call)."""
    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if not awb:
        raise HTTPException(status_code=400, detail="Batch has no AWB.")
    try:
        from ..services.email_evidence_processor import process_awb_evidence
        result = process_awb_evidence(awb, batch_id=batch_id)
        return {"ok": True, "awb": awb, "result": result}
    except Exception as exc:
        log.exception("[%s] email-evidence processor failed", batch_id)
        return {"ok": False, "awb": awb, "error": str(exc)}


@router.get("/batches/{batch_id}/email-evidence/attachments/{sha256}", dependencies=[_auth])
def email_evidence_attachment(batch_id: str, sha256: str):
    """Stream a stored attachment by sha256."""
    from fastapi.responses import FileResponse
    from ..services import email_evidence_store as evs
    if not re.match(r"^[a-f0-9]{16,64}$", sha256):
        raise HTTPException(status_code=400, detail="Invalid sha256.")
    p = evs.attachment_path(sha256)
    if not p:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return FileResponse(str(p), filename=p.name)


# ── Action Registry V2 — feature-flagged ────────────────────────────────────

@router.get("/batches/{batch_id}/actions", dependencies=[_auth])
def actions_v2(batch_id: str, request: Request) -> Dict[str, Any]:
    """
    Dashboard Action Registry V2 — single source of truth for buttons.

    Returns sectioned Action records derived from file evidence + audit.
    Frontend renders fixed slots; disabled actions stay visible with reason.

    Read-only. Does NOT modify any field.
    """
    from ..services.batch_state_normalizer import normalize_batch_state
    from ..services.dashboard_action_registry import build_actions_for_batch, all_action_endpoints
    from ..services.route_contract_validator import validate_endpoints

    _validate_batch_id(batch_id)
    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read batch audit.")

    batch_dir   = _OUTPUTS / batch_id
    normalized  = normalize_batch_state(audit, batch_dir)
    sections    = build_actions_for_batch(batch_id, normalized)

    # Validate endpoints against currently-mounted routes
    broken_routes = validate_endpoints(request.app, all_action_endpoints(normalized))

    # Disable any action whose endpoint is broken — annotate reason
    broken_ids = {b.action_id for b in broken_routes}
    if broken_ids:
        for section_actions in sections.values():
            for a in section_actions:
                if a.id in broken_ids:
                    a.enabled = False
                    a.reason  = f"Endpoint missing or method mismatch ({a.method} {a.endpoint})"
                    a.state   = "failed"

    return {
        "batch_id":          batch_id,
        "normalized_state":  normalized.to_dict(),
        "sections":          {k: [a.to_dict() for a in v] for k, v in sections.items()},
        "warnings":          [],
        "broken_routes":     [b.to_dict() for b in broken_routes],
    }


# ── Proforma readiness aggregator (read-only, local-only) ─────────────────
#
# Single read-only snapshot of every identity-resolution gate the operator
# needs to see before the Proforma readiness panel can render its decisions.
# Reads ONLY local SQLite tables and audit.json — never calls live wFirma,
# never writes anything. The panel's preview/create buttons trigger the
# existing capability endpoints when the operator wants live behaviour.


@router.get("/batches/{batch_id}/proforma-readiness", dependencies=[_auth])
def proforma_readiness(batch_id: str) -> Dict[str, Any]:
    """
    Local-only readiness snapshot for the Proforma flow. Reports product
    code mapping coverage, customer mapping coverage (against local
    wfirma_customers, with the same prefix-tolerance the live resolver
    uses), bridge state, PZ prerequisite state, and an overall verdict.

    Never raises. Returns an ``errors`` list and best-effort partial data
    when one DB is unavailable.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..core.config import settings as _s
    from ..services import wfirma_db as wfdb
    from ..services import document_db as ddb

    out: Dict[str, Any] = {
        "batch_id": batch_id,
        "products": {
            "total":            0,
            "mapped":           0,
            "missing":          0,
            "create_flag_on":   bool(getattr(_s, "wfirma_create_product_allowed", False)),
        },
        "customers": {
            "total":            0,
            "resolved":         0,
            "missing":          0,
            "ambiguous":        0,
            "create_flag_on":   bool(getattr(_s, "wfirma_create_customer_allowed", False)),
            "details":          [],
        },
        "bridge": {
            "design_product_mappings": 0,
            "ambiguous_design_codes":   {},
        },
        "pz": {
            "sad_received":          False,
            "wfirma_pz_doc_id":      None,
            "wfirma_pz_fullnumber":  None,
            "pz_rows_json_present":  False,
            "ready_for_pz_create":   False,
        },
        "proforma": {
            "ready":             False,
            "blocking_reasons":  [],
            "next_action":       "",
        },
        "errors": [],
    }
    blockers: List[str] = []

    # ── Products ─────────────────────────────────────────────────────────
    try:
        rows = ddb.get_invoice_lines_for_batch(batch_id) or []
        codes = {(r.get("product_code") or "").strip() for r in rows if r.get("product_code")}
        codes.discard("")
        out["products"]["total"] = len(codes)
        mapped = 0
        for c in codes:
            wp = wfdb.get_product(c)
            if wp and wp.get("wfirma_product_id") and wp.get("sync_status") == "matched":
                mapped += 1
        out["products"]["mapped"]  = mapped
        out["products"]["missing"] = max(0, len(codes) - mapped)
        if out["products"]["missing"]:
            blockers.append(
                f"{out['products']['missing']} product code(s) not in wfirma_products"
            )
    except Exception as exc:
        out["errors"].append(f"products read failed: {exc}")

    # ── Customers (local-only resolver, same prefix tolerance as live) ──
    try:
        from ..services.wfirma_customer_auto_resolve import _resolve_local
        seen: Dict[str, str] = {}
        if ddb._db_path is not None:
            import sqlite3 as _sql
            with _sql.connect(str(ddb._db_path)) as con:
                con.row_factory = _sql.Row
                # sales_documents primary
                rows_d = con.execute(
                    "SELECT DISTINCT client_name FROM sales_documents "
                    "WHERE batch_id=? AND client_name <> ''",
                    (batch_id,),
                ).fetchall()
                names = [r["client_name"] for r in rows_d]
                if not names:
                    rows_p = con.execute(
                        "SELECT DISTINCT client_name FROM sales_packing_lines "
                        "WHERE batch_id=? AND client_name <> ''",
                        (batch_id,),
                    ).fetchall()
                    names = [r["client_name"] for r in rows_p]
        else:
            names = []
        # Dedupe by normalized form
        from ..services.wfirma_customer_auto_resolve import _normalize_name
        for raw in names:
            key = _normalize_name(raw).lower()
            if key and key not in seen:
                seen[key] = raw
        out["customers"]["total"] = len(seen)
        for raw in seen.values():
            normalized = _normalize_name(raw)
            local = _resolve_local(normalized)
            # Surface ship-to (Odbiorca) routing per customer so the
            # dashboard can render mode + receiver id alongside the
            # bill-to identity. The fields default safely when the
            # customer isn't matched yet (no wfirma_customers row).
            ship_to_mode      = ""
            ship_to_rcv_id    = ""
            ship_to_warning   = False
            if local["status"] in ("exact_match", "normalized_match",
                                    "prefix_match", "reverse_prefix_match"):
                # Re-read the wfirma_customers row for the matched
                # candidate to pick up ship_to_* (the resolver only
                # surfaces wfirma_customer_id and matched_name).
                try:
                    from ..services import wfirma_db as _wfdb
                    wm = (local.get("matched_name") or "").strip()
                    if wm:
                        cust_row = _wfdb.get_customer(wm) or {}
                        ship_to_mode   = (cust_row.get("ship_to_mode")
                                            or "same_as_bill_to").lower()
                        ship_to_rcv_id = (cust_row.get(
                            "ship_to_wfirma_customer_id") or "").strip()
                        if (ship_to_mode == "separate_contractor"
                                and not ship_to_rcv_id):
                            ship_to_warning = True
                except Exception as exc:
                    log.warning("ship_to read for %s failed: %s", raw, exc)

            entry: Dict[str, Any] = {
                "client_name":        raw,
                "normalized_name":    normalized,
                "status":             local["status"],
                "wfirma_customer_id": local.get("wfirma_customer_id", ""),
                "matched_name":       local.get("matched_name", ""),
                "candidates":         local.get("candidates", []),
                # Step 3: ship-to routing surface for the operator UI.
                "ship_to_mode":                ship_to_mode or "same_as_bill_to",
                "ship_to_wfirma_customer_id":  ship_to_rcv_id,
                "ship_to_warning":             ship_to_warning,
            }
            out["customers"]["details"].append(entry)
            if local["status"] in ("exact_match", "normalized_match",
                                   "prefix_match", "reverse_prefix_match"):
                out["customers"]["resolved"] += 1
            elif local["status"] == "ambiguous":
                out["customers"]["ambiguous"] += 1
            else:
                out["customers"]["missing"] += 1
        if out["customers"]["missing"]:
            blockers.append(
                f"{out['customers']['missing']} customer(s) not mapped locally"
            )
        if out["customers"]["ambiguous"]:
            blockers.append(
                f"{out['customers']['ambiguous']} customer(s) ambiguous in wfirma_customers"
            )
    except Exception as exc:
        out["errors"].append(f"customers read failed: {exc}")

    # ── Bridge ─────────────────────────────────────────────────────────
    try:
        rdb_path = _s.storage_root / "reservation_queue.db"
        if rdb_path.exists():
            import sqlite3 as _sql
            with _sql.connect(str(rdb_path)) as con:
                con.row_factory = _sql.Row
                bridge_rows = con.execute(
                    "SELECT design_no, product_code FROM design_product_mapping"
                ).fetchall()
                out["bridge"]["design_product_mappings"] = len(bridge_rows)
                # Detect ambiguous design codes (1 design → 2+ product_codes)
                from collections import defaultdict
                groups: Dict[str, List[str]] = defaultdict(list)
                for r in bridge_rows:
                    groups[r["design_no"]].append(r["product_code"])
                ambig = {d: sorted(set(pcs)) for d, pcs in groups.items()
                         if len(set(pcs)) > 1}
                out["bridge"]["ambiguous_design_codes"] = ambig
                if ambig:
                    blockers.append(
                        f"{len(ambig)} design_code(s) map to multiple product_codes "
                        f"(e.g. {next(iter(ambig))})"
                    )
    except Exception as exc:
        out["errors"].append(f"bridge read failed: {exc}")

    # ── PZ prerequisites (read audit.json + pz_rows.json) ──────────────
    try:
        outputs_dir = _s.storage_root / "outputs" / batch_id
        audit_path  = outputs_dir / "audit.json"
        if audit_path.exists():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            # SAD: presence of customs_declaration with mrn or non-zero CIF.
            cd = audit.get("customs_declaration") or {}
            out["pz"]["sad_received"] = bool(
                cd.get("mrn") or cd.get("invoice_cif_usd")
            )
            wfx = audit.get("wfirma_export") or {}
            out["pz"]["wfirma_pz_doc_id"]     = (wfx.get("wfirma_pz_doc_id")     or "").strip() or None
            out["pz"]["wfirma_pz_fullnumber"] = (wfx.get("wfirma_pz_fullnumber") or "").strip() or None
        out["pz"]["pz_rows_json_present"] = (outputs_dir / "pz_rows.json").exists()
        out["pz"]["ready_for_pz_create"] = (
            out["pz"]["sad_received"]
            and out["products"]["missing"] == 0
            and not out["bridge"]["ambiguous_design_codes"]
        )
        if not out["pz"]["sad_received"]:
            blockers.append("SAD not received — customs_declaration empty")
        if not out["pz"]["wfirma_pz_doc_id"]:
            blockers.append("wFirma PZ document not yet created")
    except Exception as exc:
        out["errors"].append(f"pz read failed: {exc}")

    # ── Verdict ────────────────────────────────────────────────────────
    out["proforma"]["blocking_reasons"] = blockers
    out["proforma"]["ready"] = (not blockers)
    if blockers:
        # Map first blocker to a concrete next-action hint.
        b0 = blockers[0]
        if "product code" in b0:
            out["proforma"]["next_action"] = (
                "Click 'Auto-register products' to register the missing "
                "wFirma product codes (requires WFIRMA_CREATE_PRODUCT_ALLOWED=true)."
            )
        elif "customer" in b0 and "ambiguous" not in b0:
            out["proforma"]["next_action"] = (
                "Use the Customer Identity section to create the missing "
                "customers (requires WFIRMA_CREATE_CUSTOMER_ALLOWED=true)."
            )
        elif "ambiguous" in b0:
            out["proforma"]["next_action"] = (
                "Resolve the ambiguity in wFirma master data, then refresh."
            )
        elif "SAD" in b0:
            out["proforma"]["next_action"] = "Wait for SAD/ZC429 from DHL/agency."
        elif "PZ" in b0:
            out["proforma"]["next_action"] = "Generate the wFirma PZ document."
        else:
            out["proforma"]["next_action"] = b0

    return out


# ── DHL ZC429 intake lineage (read-only) ─────────────────────────────────────

@router.get("/batches/{batch_id}/zc429-lineage", dependencies=[_auth])
def zc429_lineage(batch_id: str) -> Dict[str, Any]:
    """
    Read-only lineage envelope for the operator's pre-PZ legal-evidence
    review. Pulls:

      • ``audit.customs_declaration.intake_event_id`` from this batch's
        audit.json (the canonical pointer written by dhl_zc429_intake).
      • The full ``intake_lineage`` envelope (event row + attachments +
        processing history + timeline events scoped to this event id).

    Never writes. Never deletes. Never reclassifies. Returns
    ``has_zc429=False`` cleanly when there is no ZC429 yet on the batch
    so the dashboard can render a "Waiting for DHL ZC429/SAD email"
    placeholder.

    Warnings surfaced (so the operator sees integrity issues before
    they touch PZ):
      • audit says SAD received but no ``intake_event_id`` is present
      • ``audit.customs_declaration.attachments_count`` differs from
        the count of rows in ``intake_attachments``
      • intake_event_id present but the lineage row was not found
        (e.g. stale audit pointer)
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..core.config import settings as _s
    from ..services import intake_lineage as _il
    from ..services import email_evidence_store as _evs

    out: Dict[str, Any] = {
        "batch_id":               batch_id,
        "has_zc429":              False,
        "intake_event_id":        "",
        "event":                  None,
        "attachments":            [],
        "classified_counts":      {
            "zc429":         0,
            "awb":           0,
            "invoices":      0,
            "mail_evidence": 0,
            "others":        0,
        },
        "processing_history":     [],
        "linked_timeline_events": [],
        "warnings":               [],
        # Recovery diagnostics — distinguish 4 mutually-exclusive states so
        # the dashboard can render a precise "what to do next" instruction
        # without the operator having to read service logs.
        "recovery_state":         "email_not_found",
        "recovery_detail":        {
            "plwawecs_messages_found": 0,
            "attachments_in_evidence": 0,
            "lineage_rows":            0,
            "instruction":             "",
        },
    }

    audit_path = _s.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        out["warnings"].append(f"audit.json not found at {audit_path}")
        # No audit → unknown AWB; recovery_state stays at default with
        # a generic instruction populated by the helper.
        return _attach_zc429_recovery_state(out, {}, 0)

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        out["warnings"].append(f"audit.json read failed: {exc}")
        return _attach_zc429_recovery_state(out, {}, 0)

    cd          = audit.get("customs_declaration") or {}
    received    = bool(cd.get("received"))
    eid         = (cd.get("intake_event_id") or "").strip()
    audit_count = int(cd.get("attachments_count") or 0)

    # Integrity warning #1 — declared received but no intake event
    # was ever recorded. Operator should NOT trust the SAD row.
    if received and not eid:
        out["warnings"].append(
            "customs_declaration.received=true but no intake_event_id "
            "is recorded — lineage cannot be verified")
        return _attach_zc429_recovery_state(out, audit, 0)

    if not eid:
        # No ZC429 intake yet. Return cleanly so the UI can render the
        # "waiting" state without further branching.
        return _attach_zc429_recovery_state(out, audit, 0)

    # Pull lineage envelope.
    try:
        env = _il.lineage_envelope(eid, audit_path=audit_path)
    except Exception as exc:
        out["warnings"].append(f"lineage_envelope read failed: {exc}")
        return _attach_zc429_recovery_state(out, audit, 0)

    if not env or not env.get("intake_event"):
        out["warnings"].append(
            f"intake_event_id={eid!r} present in audit but not found "
            "in intake_lineage.db (stale pointer)")
        return _attach_zc429_recovery_state(out, audit, 0)

    ev = env["intake_event"]
    out["has_zc429"]       = True
    out["intake_event_id"] = eid
    out["event"] = {
        "awb":                 ev.get("awb", "")        or cd.get("awb", ""),
        "zc_number":           ev.get("zc_number", "")  or cd.get("zc_number", ""),
        "sender":              ev.get("source_sender", ""),
        "subject":             ev.get("source_subject", ""),
        "received_at":         ev.get("received_at", ""),
        "processing_version":  ev.get("processing_version", ""),
        "created_at":          ev.get("created_at", ""),
    }

    atts = env.get("attachments") or []
    # Slim per-attachment shape for the UI; the full row is available
    # through the lineage envelope when needed.
    out["attachments"] = [
        {
            "filename":        a.get("original_filename", ""),
            "safe_filename":   a.get("safe_filename", ""),
            "classified_type": a.get("classified_type", ""),
            "bucket":          a.get("bucket", ""),
            "size":            int(a.get("size", 0) or 0),
            "sha256":          a.get("sha256", ""),
            "stored_path":     a.get("stored_path", ""),
            "received_at":     a.get("received_at", ""),
        }
        for a in atts
    ]

    # Aggregate classified counts (independent of ZC429 intake's runtime
    # bucketing — this is the ground truth from lineage.db).
    for a in atts:
        b = (a.get("bucket") or "").strip().lower()
        if b in out["classified_counts"]:
            out["classified_counts"][b] += 1
        else:
            out["classified_counts"]["others"] += 1

    out["processing_history"]     = list(env.get("processing_history") or [])
    out["linked_timeline_events"] = list(env.get("linked_timeline_events") or [])

    # Integrity warning #2 — audit declared a count but lineage rows
    # disagree. Either intake stored partial state or audit was edited.
    lineage_count = len(atts)
    if audit_count and audit_count != lineage_count:
        out["warnings"].append(
            f"audit.customs_declaration.attachments_count={audit_count} "
            f"differs from intake_attachments rows={lineage_count}")

    return _attach_zc429_recovery_state(out, audit, lineage_count)


def _attach_zc429_recovery_state(
    out: Dict[str, Any],
    audit: Dict[str, Any],
    lineage_count: int,
) -> Dict[str, Any]:
    """Compute and stamp the four-state recovery diagnostic onto a
    zc429-lineage response. Pure read of the email-evidence store.

    States:
      intake_completed                       — green; lineage + audit OK
      email_found_attachments_pending_intake — amber; binaries stored but
                                                no lineage row yet
      email_found_no_attachments             — amber; plwawecs message
                                                stored but binaries missing
      email_not_found                        — gray; no plwawecs email
                                                visible to the watcher

    Never fabricates attachments. The instruction text explicitly tells
    the operator NOT to use the printed-email PDF as a substitute.
    """
    from ..services import email_evidence_store as _evs
    awb = (audit.get("tracking_no") or audit.get("awb") or "")
    plwawecs_count = 0
    evs_atts_count = 0
    if awb:
        try:
            ev_doc = _evs.get_by_awb(awb)
            for thr in (ev_doc.get("threads") or []):
                for m in (thr.get("messages") or []):
                    sender = (m.get("sender") or "").lower()
                    if "plwawecs@dhl.com" in sender:
                        plwawecs_count += 1
                        evs_atts_count += len(m.get("attachments") or [])
        except Exception:
            pass

    out["recovery_detail"]["plwawecs_messages_found"] = plwawecs_count
    out["recovery_detail"]["attachments_in_evidence"] = evs_atts_count
    out["recovery_detail"]["lineage_rows"]            = int(lineage_count or 0)

    if out.get("has_zc429") and (lineage_count or 0) > 0:
        out["recovery_state"] = "intake_completed"
        out["recovery_detail"]["instruction"] = (
            "ZC429 evidence chain is complete. No action needed."
        )
    elif plwawecs_count > 0 and evs_atts_count > 0:
        out["recovery_state"] = "email_found_attachments_pending_intake"
        out["recovery_detail"]["instruction"] = (
            "Email and attachments are stored in email_evidence but no "
            "intake_lineage row exists. Re-run the ingestion worker for "
            "this AWB or POST /api/v1/upload/dhl-zc429/intake with the "
            "stored attachments."
        )
    elif plwawecs_count > 0:
        out["recovery_state"] = "email_found_no_attachments"
        out["recovery_detail"]["instruction"] = (
            "DHL plwawecs email is in the evidence store but no binary "
            "attachments were downloaded. Verify Zoho attachment-download "
            "permissions, then re-run the ingestion worker. Do NOT "
            "fabricate attachments from the printed email PDF."
        )
    else:
        out["recovery_state"] = "email_not_found"
        out["recovery_detail"]["instruction"] = (
            "No plwawecs ZC429 email is visible to the mailbox watcher. "
            "Check the import@ inbox in Zoho (Spam, Trash, sub-folders), "
            "trigger Rescan, or backfill via "
            "POST /api/v1/upload/dhl-zc429/intake using the original "
            "downloaded binaries (NEVER the printed-email PDF)."
        )
    return out


# ── CN / HSN classification + operator decisions (read-only + decisions) ────
#
# Replaces the legacy strict 8-digit CN==HSN equality check (which
# produced false "blocked" states for SAD aggregations) with the
# hierarchy compare in services.cn_hsn_classifier. The decision
# endpoints record operator choices into correction_registry — they
# never call PZ create, never write to wFirma, never send SMTP.

@router.get("/batches/{batch_id}/cn-hsn-classification", dependencies=[_auth])
def cn_hsn_classification(batch_id: str) -> Dict[str, Any]:
    """Read-only CN ↔ HSN classification for the operator review panel.

    Pulls SAD CN from ``audit.customs_declaration.cn_code`` and the
    invoice HSN list from ``audit.verification.invoice_hsn_codes``
    (with sensible fallbacks). Compares using the hierarchy rule and
    returns the structured result + any prior operator decision.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..core.config import settings as _s
    from ..services import cn_hsn_classifier as _cn

    out: Dict[str, Any] = {
        "batch_id":     batch_id,
        "has_data":     False,
        "sad_cn_code":  "",
        "invoice_hsns": [],
        "result":       None,
        "decision":     None,
        "warnings":     [],
    }
    audit_path = _s.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        out["warnings"].append(f"audit.json not found at {audit_path}")
        return out
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        out["warnings"].append(f"audit read failed: {exc}")
        return out

    cd  = audit.get("customs_declaration") or {}
    ver = audit.get("verification") or {}
    sad_cn = (
        ver.get("sad_cn_code")
        or ver.get("cn_code")
        or cd.get("cn_code")
        or ""
    )
    invoice_hsns = (
        ver.get("invoice_hsn_codes")
        or audit.get("invoice_hsn_codes")
        or []
    )
    out["sad_cn_code"]  = sad_cn or ""
    out["invoice_hsns"] = list(invoice_hsns or [])
    out["has_data"]     = bool(sad_cn) or bool(invoice_hsns)
    out["result"]       = _cn.classify(sad_cn, list(invoice_hsns or []))
    out["decision"]     = audit.get("cn_decision") or None
    return out


class CNDecisionRequest(BaseModel):
    operator: str = ""
    reason:   str = ""


def _operator_or_default(req_operator: str, x_op_header: Optional[str]) -> str:
    val = (req_operator or x_op_header or "").strip()
    return val or "operator"


def _record_cn_decision(
    *,
    batch_id:        str,
    decision_type:   str,                 # accept_sad | correct_internal | escalate_agent
    correction_type: str,                 # mapped to correction_registry SUPPORTED_TYPES
    approved:        bool,
    operator:        str,
    reason:          str,
) -> Dict[str, Any]:
    """Single shared writer for the three CN-decision endpoints.

    Reads the audit, derives evidence pointers (intake_event_id from
    customs_declaration.intake_event_id when present, plus AWB), and
    appends an append-only correction-registry row. Also stamps a
    ``cn_decision`` block on the audit so the dashboard can render the
    chosen status without re-reading the registry. NEVER mutates SAD
    source values, financial fields, or wFirma master data.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    from ..core.config import settings as _s
    from ..services import cn_hsn_classifier as _cn
    from ..services import correction_registry as _cr
    from ..core import timeline as _tl

    audit_path = _s.storage_root / "outputs" / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="audit.json not found")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    cd     = audit.get("customs_declaration") or {}
    ver    = audit.get("verification") or {}
    sad_cn = (ver.get("sad_cn_code") or ver.get("cn_code")
              or cd.get("cn_code") or "")
    invoice_hsns = list(ver.get("invoice_hsn_codes")
                        or audit.get("invoice_hsn_codes") or [])
    awb = (audit.get("tracking_no") or audit.get("awb") or "")

    classified = _cn.classify(sad_cn, invoice_hsns)

    evidence_refs: List[Dict[str, str]] = [
        {"type": "endpoint",     "ref": f"/dashboard/batches/{batch_id}/cn-decision/{decision_type}"},
        {"type": "batch_id",     "ref": batch_id},
        {"type": "awb",          "ref": awb},
        {"type": "sad_cn_code",  "ref": str(sad_cn)},
        {"type": "invoice_hsns", "ref": ",".join(str(x) for x in invoice_hsns)},
        {"type": "cn_level",     "ref": classified.get("worst_level", "")},
    ]
    eid = (cd.get("intake_event_id") or "").strip()
    if eid:
        evidence_refs.append({"type": "intake_event", "ref": eid})

    rid = ""
    log_warning = ""
    try:
        rid = _cr.record_correction(
            correction_type = correction_type,
            entity_type     = "classification",
            entity_key      = f"{batch_id}::cn_hsn",
            old_value       = sad_cn,
            new_value       = {
                "decision":     decision_type,
                "sad_cn_code":  sad_cn,
                "invoice_hsns": invoice_hsns,
                "level":        classified.get("worst_level"),
            },
            shipment_id     = awb,
            batch_id        = batch_id,
            operator        = operator,
            module_source   = "cn_hsn_decision",
            confidence      = 1.0 if approved else 0.0,
            approved        = approved,
            notes           = reason or decision_type,
            evidence_refs   = evidence_refs,
        )
    except Exception as exc:
        log_warning = f"correction_registry log failed: {type(exc).__name__}: {exc}"

    # ── Branch: accept_sad clears the legacy cn_match block ─────────────
    # Operator-explicit decision to accept the SAD CN as authoritative.
    # Mutates verification provenance, removes 'cn_match' from
    # failed_checks, and recomputes audit.status. Never touches CN/HSN
    # source values, financial fields, or wFirma master data. Idempotent:
    # repeated calls converge on the same final audit state.
    previous_status = audit.get("status")
    new_status      = previous_status

    if decision_type == "accept_sad":
        ver = audit.get("verification") or {}
        # Provenance — preserve original SAD CN + invoice HSN values
        ver["cn_match"]                  = True
        ver["cn_status"]                 = "operator_accepted_sad_cn"
        ver["cn_risk_level"]             = "operator_accepted"
        ver["cn_match_overridden_by"]    = "cn_decision/accept_sad"
        ver["cn_match_correction_id"]    = rid
        ver["cn_match_overridden_at"]    = datetime.now(timezone.utc).isoformat()
        ver["cn_match_overridden_by_op"] = operator
        # Note: ver["sad_cn_code"], ver["cn_code"], ver["invoice_hsn_codes"]
        # are intentionally NOT touched — those are the source-of-truth
        # values the engine wrote.
        audit["verification"] = ver

        # Remove cn_match from failed_checks (idempotent).
        fc = list(audit.get("failed_checks") or [])
        fc_clean = [c for c in fc if c != "cn_match"]
        audit["failed_checks"] = fc_clean

        # Append an operator_overrides[] entry so the existing
        # _compute_effective_blocked() helper recognises this clearance
        # at read time too. Append-only, never updated.
        ov_list = audit.get("operator_overrides") or []
        if not isinstance(ov_list, list):
            ov_list = []
        ov_list.append({
            "override_id":         rid,
            "check":               "cn_match",
            "reason":              reason or "operator accepted SAD CN as authoritative",
            "operator":            operator,
            "timestamp":           datetime.now(timezone.utc).isoformat(),
            "evidence_reference":  f"correction:{rid}",
            "batch_id":            batch_id,
            "original_value":      False,
            "decision_source":     "cn_decision/accept_sad",
        })
        audit["operator_overrides"] = ov_list

        # Recompute audit.status — minimal, conservative rule:
        #   - If status was 'blocked' AND failed_checks now empty → 'partial'.
        #   - Otherwise leave the engine-derived status untouched.
        # Never invent 'success' / 'complete'.
        if previous_status == "blocked" and not fc_clean:
            audit["status"] = "partial"
        new_status = audit.get("status")

    # Stamp audit.cn_decision so the dashboard can render quickly.
    audit["cn_decision"] = {
        "decision_type":      decision_type,
        "approved":           bool(approved),
        "operator":           operator,
        "sad_cn_code":        sad_cn,
        "invoice_hsns":       invoice_hsns,
        "classification":     classified,
        "reason":             reason or "",
        "correction_id":      rid,
        "recorded_at":        datetime.now(timezone.utc).isoformat(),
        "intake_event_id":    eid,
        "previous_status":    previous_status,
        "new_status":         new_status,
    }
    tmp = audit_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(audit, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(audit_path)

    # Timeline note (non-fatal). Uses generic status_change so we don't
    # add a new event constant for a UI-level decision.
    try:
        _tl.log_event(
            audit_path     = audit_path,
            event          = _tl.EV_STATUS_CHANGE,
            trigger_source = "cn_hsn_decision",
            actor          = operator,
            detail         = {
                "decision_type":   decision_type,
                "sad_cn_code":     sad_cn,
                "invoice_hsns":    invoice_hsns,
                "approved":        approved,
                "level":           classified.get("worst_level"),
                "correction_id":   rid,
                "intake_event_id": eid,
                "previous_status": previous_status,
                "new_status":      new_status,
                "operator":        operator,
            },
        )
    except Exception:
        pass

    return {
        "ok":             True,
        "batch_id":       batch_id,
        "decision_type":  decision_type,
        "correction_id":  rid,
        "approved":       approved,
        "classification": classified,
        "warning":        log_warning,
    }


@router.post("/batches/{batch_id}/cn-decision/accept-sad", dependencies=[_op_auth])
def cn_decision_accept_sad(
    batch_id: str,
    body: CNDecisionRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> Dict[str, Any]:
    """Operator chose to accept the SAD CN as authoritative for this
    shipment. Records ``accepted_match`` in correction_registry and
    sets ``audit.cn_decision``. Does NOT execute PZ. The PZ-create
    button stays operator-explicit and gated by the existing
    pz_preview readiness rules."""
    return _record_cn_decision(
        batch_id        = batch_id,
        decision_type   = "accept_sad",
        correction_type = "accepted_match",
        approved        = True,
        operator        = _operator_or_default(body.operator, x_operator),
        reason          = body.reason or "Operator accepted SAD CN as authoritative",
    )


@router.post("/batches/{batch_id}/cn-decision/correct-internal",
             dependencies=[_op_auth])
def cn_decision_correct_internal(
    batch_id: str,
    body: CNDecisionRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> Dict[str, Any]:
    """Operator chose to record an internal classification correction
    (e.g. flag for invoice-side reclassification) WITHOUT modifying
    the SAD source value. Recorded as ``ambiguity_resolution`` in
    correction_registry."""
    return _record_cn_decision(
        batch_id        = batch_id,
        decision_type   = "correct_internal",
        correction_type = "ambiguity_resolution",
        approved        = True,
        operator        = _operator_or_default(body.operator, x_operator),
        reason          = body.reason or "Operator flagged for internal CN/HSN correction",
    )


@router.post("/batches/{batch_id}/cn-decision/escalate-agent",
             dependencies=[_op_auth])
def cn_decision_escalate_agent(
    batch_id: str,
    body: CNDecisionRequest,
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> Dict[str, Any]:
    """Operator chose to send the classification mismatch back to the
    customs agent for clarification. Recorded as ``rejected_match``
    (approved=False) — the gate stays blocked."""
    return _record_cn_decision(
        batch_id        = batch_id,
        decision_type   = "escalate_agent",
        correction_type = "rejected_match",
        approved        = False,
        operator        = _operator_or_default(body.operator, x_operator),
        reason          = body.reason or "Operator escalated CN/HSN mismatch to customs agent",
    )


# ── Archive a shipment (soft — 14-day retention) ──────────────────────────────

class ArchiveRequest(BaseModel):
    reason: str = ""


@router.delete("/batches/{batch_id}", dependencies=[_admin_auth])
def delete_batch(batch_id: str, body: ArchiveRequest = ArchiveRequest()) -> Dict[str, Any]:
    """
    Archive a shipment: moves it to storage/archived/ with 14-day retention.
    Nothing is permanently removed. Restore is available via POST /archive/{id}/restore.
    """
    _validate_batch_id(batch_id)

    src = _OUTPUTS / batch_id
    if not src.exists():
        raise HTTPException(status_code=404, detail="Shipment not found.")

    audit_path  = src / "audit.json"
    now         = datetime.now(timezone.utc)
    delete_after = now.replace(microsecond=0)
    from datetime import timedelta
    delete_after = (now + timedelta(days=_ARCHIVE_RETENTION_DAYS)).isoformat()

    # Write archive metadata into audit before moving
    try:
        a = json.loads(audit_path.read_text(encoding="utf-8"))
        a["archive_meta"] = {
            "archived_at":  now.isoformat(),
            "delete_after": delete_after,
            "reason":       body.reason or "archived by user",
            "archived_by":  "user",
        }
        write_json_atomic(audit_path, a)
    except Exception:
        pass

    tl.log_event(audit_path, tl.EV_SHIPMENT_ARCHIVED, "dashboard", "user",
                 detail={"reason": body.reason or "archived by user", "delete_after": delete_after})

    _ARCHIVED.mkdir(parents=True, exist_ok=True)
    dst = _ARCHIVED / batch_id
    if dst.exists():
        dst = _ARCHIVED / f"{batch_id}_{int(time.time())}"

    shutil.move(str(src), str(dst))
    return {
        "success":      True,
        "batch_id":     batch_id,
        "archived_at":  now.isoformat(),
        "delete_after": delete_after,
        "message":      f"Shipment archived. Eligible for permanent deletion after {_ARCHIVE_RETENTION_DAYS} days.",
    }


# ── List archived shipments ───────────────────────────────────────────────────

@router.get("/archive", dependencies=[_auth])
def list_archived() -> List[Dict[str, Any]]:
    """Return all archived shipments sorted newest-archived-first."""
    if not _ARCHIVED.exists():
        return []
    result = []
    for batch_dir in sorted(_ARCHIVED.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not batch_dir.is_dir():
            continue
        audit_path = batch_dir / "audit.json"
        if not audit_path.exists():
            continue
        try:
            a = json.loads(audit_path.read_text(encoding="utf-8"))
            result.append(_archive_summary(batch_dir.name, a))
        except Exception:
            continue
    return result


# ── Restore a shipment ────────────────────────────────────────────────────────

@router.post("/archive/{batch_id}/restore", dependencies=[_admin_auth])
def restore_batch(batch_id: str) -> Dict[str, Any]:
    """Restore an archived shipment back to active outputs."""
    _validate_batch_id(batch_id)

    src = _ARCHIVED / batch_id
    if not src.exists():
        # Try with timestamp suffix (edge case)
        matches = list(_ARCHIVED.glob(f"{batch_id}_*"))
        if matches:
            src = sorted(matches)[-1]
        else:
            raise HTTPException(status_code=404, detail="Archived shipment not found.")

    audit_path = src / "audit.json"

    # Clear archive metadata
    try:
        a = json.loads(audit_path.read_text(encoding="utf-8"))
        a.pop("archive_meta", None)
        write_json_atomic(audit_path, a)
    except Exception:
        pass

    tl.log_event(audit_path, tl.EV_SHIPMENT_RESTORED, "dashboard", "user",
                 detail={"restored_from": "archived"})

    dst = _OUTPUTS / batch_id
    if dst.exists():
        dst = _OUTPUTS / f"{batch_id}_restored_{int(time.time())}"

    shutil.move(str(src), str(dst))
    return {
        "success":  True,
        "batch_id": batch_id,
        "message":  "Shipment restored to active dashboard.",
    }


# ── Permanently delete an archived shipment (admin only) ─────────────────────

@router.delete("/archive/{batch_id}", dependencies=[Depends(require_admin)])
def permanently_delete_archived(batch_id: str) -> Dict[str, Any]:
    """Permanently delete an archived shipment. Admin only. Cannot be undone."""
    _validate_batch_id(batch_id)

    src = _ARCHIVED / batch_id
    if not src.exists():
        matches = list(_ARCHIVED.glob(f"{batch_id}_*"))
        if matches:
            src = sorted(matches)[-1]
        else:
            raise HTTPException(status_code=404, detail="Archived shipment not found.")

    audit_path = src / "audit.json"
    tl.log_event(audit_path, tl.EV_SHIPMENT_PERMANENTLY_DELETED, "dashboard", "admin",
                 detail={"batch_id": batch_id})

    # Move to a permanent-delete log folder rather than os.rmtree, for a final safety net
    perm_del = settings.storage_root / "permanently_deleted"
    perm_del.mkdir(parents=True, exist_ok=True)
    dst = perm_del / f"{batch_id}_{int(time.time())}"
    shutil.move(str(src), str(dst))

    return {
        "success":  True,
        "batch_id": batch_id,
        "message":  "Shipment permanently deleted.",
    }


# ── Cleanup: expire archived shipments past 14-day retention (admin only) ─────

@router.post("/archive/cleanup", dependencies=[Depends(require_admin)])
def archive_cleanup() -> Dict[str, Any]:
    """
    Move archived shipments past their delete_after date to permanently_deleted/.
    Admin only. Must be triggered explicitly — never runs automatically.
    """
    if not _ARCHIVED.exists():
        return {"deleted": [], "skipped": [], "errors": []}

    now     = datetime.now(timezone.utc)
    deleted = []
    skipped = []
    errors  = []
    perm_del = settings.storage_root / "permanently_deleted"
    perm_del.mkdir(parents=True, exist_ok=True)

    for batch_dir in _ARCHIVED.iterdir():
        if not batch_dir.is_dir():
            continue
        audit_path = batch_dir / "audit.json"
        try:
            a = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            skipped.append(batch_dir.name)
            continue

        delete_after_str = (a.get("archive_meta") or {}).get("delete_after")
        if not delete_after_str:
            skipped.append(batch_dir.name)
            continue

        try:
            delete_after = datetime.fromisoformat(delete_after_str)
            if delete_after.tzinfo is None:
                delete_after = delete_after.replace(tzinfo=timezone.utc)
        except Exception:
            skipped.append(batch_dir.name)
            continue

        if now >= delete_after:
            tl.log_event(audit_path, tl.EV_SHIPMENT_PERMANENTLY_DELETED,
                         "archive_cleanup", "system",
                         detail={"expired_at": delete_after_str})
            dst = perm_del / f"{batch_dir.name}_{int(time.time())}"
            shutil.move(str(batch_dir), str(dst))
            deleted.append(batch_dir.name)
        else:
            days_left = (delete_after - now).days
            skipped.append({"batch_id": batch_dir.name, "days_remaining": days_left})

    return {
        "deleted": deleted,
        "skipped": skipped,
        "errors":  errors,
        "ran_at":  now.isoformat(),
    }


# ── Recheck / Reparse ─────────────────────────────────────────────────────────

_DHL_BROKER_THRESHOLD_USD = 2500.0


def _is_valid_pdf_file(path: Path) -> bool:
    """Return True iff the file at *path* has a valid PDF magic header.

    A file claiming `.pdf` extension but starting with anything other than
    ``%PDF-`` (e.g. an Excel doc renamed during a "Save As Compatibility
    Mode" workflow) is not a real PDF and will either crash the invoice
    parser or — worse — produce zero results that poison
    ``compute_invoice_totals``.

    Read-only header sniff (5 bytes). Never raises; on any IO error the
    file is treated as invalid so it gets quarantined out of the parse
    loop rather than crashing the recheck.
    """
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except Exception:
        return False


def _partition_valid_pdfs(pdfs: List[Path]) -> tuple[List[Path], List[Path]]:
    """Split *pdfs* into (valid, invalid) by PDF magic header check.

    Used by the recheck loops to skip files that masquerade as PDFs
    (e.g. ``Global-inv-088.xls _Compatibility Mode_.pdf``) so they
    don't poison invoice totals when a valid sibling exists.
    """
    valid:   List[Path] = []
    invalid: List[Path] = []
    for p in pdfs:
        (valid if _is_valid_pdf_file(p) else invalid).append(p)
    return valid, invalid

class RecheckRequest(BaseModel):
    mode: str = "all"


# Keys on the audit that recheck must NEVER author from its own in-memory
# snapshot — they belong to a different sole-writer. recheck reads the audit
# once at the top (unguarded) and writes the whole object back seconds later;
# if an operator confirms the vision invoice inside that window, a whole-object
# write would silently revert operator_confirmed=true (a #570-class lost
# update). `confirm_vision_invoice` is the SOLE writer of operator_confirmed on
# audit["vision_invoice"]; recheck overlays the on-disk authoritative copy of
# these keys immediately before persisting so it can never clobber a concurrent
# confirmation.
_RECHECK_DISK_AUTHORITATIVE_KEYS = ("vision_invoice",)


def _persist_recheck(audit_path: Path, batch_id: str, audit: Dict[str, Any]) -> None:
    """Persist recheck's audit snapshot WITHOUT clobbering sole-writer-owned keys.

    recheck legitimately owns most of the audit it rewrites (verification,
    learning_traces, inputs.zc429_mrn, amendment_flags, cif_reconciliation,
    clearance_decision, recheck, …). Those mutations are scattered and the local
    ``updated`` dict keys are display labels, not audit keys — so copying "only
    the keys recheck updated" would silently drop recheck's own writes. Instead
    we persist recheck's full snapshot but OVERLAY the on-disk authoritative copy
    of the keys recheck must never author (``_RECHECK_DISK_AUTHORITATIVE_KEYS``).

    The overlay + write happen under ``batch_write_lock`` so a concurrent
    ``confirm_vision_invoice`` (which holds the same per-batch lock) cannot
    interleave between the disk re-read and the write. operator_confirmed=true
    and its metadata (confirmed_by / confirmed_at) therefore survive recheck.
    """
    def _overlay_from_disk(target: Dict[str, Any]) -> None:
        try:
            fresh = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            # No readable on-disk copy (first write / corrupt) — nothing to
            # preserve. recheck's own snapshot is the best available truth.
            return
        if not isinstance(fresh, dict):
            return
        for _k in _RECHECK_DISK_AUTHORITATIVE_KEYS:
            if _k in fresh:
                target[_k] = fresh[_k]
        _vi = target.get("vision_invoice")
        if isinstance(_vi, dict) and _vi.get("operator_confirmed") is True:
            log.info(
                "[recheck] preserved operator-confirmed vision_invoice for %s "
                "(confirmed_by=%s, confirmed_at=%s) — merge-write did not revert it",
                batch_id, _vi.get("confirmed_by"), _vi.get("confirmed_at"),
            )

    try:
        with batch_write_lock(batch_id):
            _overlay_from_disk(audit)
            write_json_atomic(audit_path, audit)
    except TimeoutError as exc:
        # Lock contention should not strand recheck's results. Fall back to a
        # best-effort vision-safe write: overlay the disk-authoritative keys
        # (still preserving a confirmation that landed) then persist unlocked.
        log.warning(
            "[recheck] batch lock timeout for %s (%s) — vision-safe fallback write",
            batch_id, exc,
        )
        _overlay_from_disk(audit)
        write_json_atomic(audit_path, audit)


@router.post("/batches/{batch_id}/recheck", dependencies=[_op_auth])
async def recheck_batch(batch_id: str, body: RecheckRequest = RecheckRequest()) -> Dict[str, Any]:
    """
    Re-run parsers against existing uploaded source files.
    Does NOT regenerate PZ PDF/XLSX — only updates audit.json parsed fields.
    Supported modes: all | invoice | sad | dhl_precheck | quantity
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    batch_dir  = _OUTPUTS / batch_id
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Shipment not found.")

    mode    = body.mode or "all"
    audit   = json.loads(audit_path.read_text(encoding="utf-8"))
    updated: Dict[str, bool] = {}
    warnings: List[str]      = []
    errors:   List[str]      = []

    # ── Ensure engine is importable ──────────────────────────────────────────
    engine_dir = str(settings.engine_dir)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    # ── A. Reparse invoices ──────────────────────────────────────────────────
    if mode in ("all", "invoice", "quantity"):
        inv_dir = batch_dir / "source" / "invoices"
        inv_pdfs_all = sorted(inv_dir.glob("*.pdf")) if inv_dir.exists() else []
        # Quarantine files that claim .pdf but lack the %PDF- magic header
        # (e.g. Excel "Compatibility Mode" .xls renamed to .pdf). They would
        # otherwise either crash the parser or silently return zero rows that
        # poison compute_invoice_totals. Skip + name them as warnings, never
        # block valid siblings.
        inv_pdfs, _bad_pdfs = _partition_valid_pdfs(inv_pdfs_all)
        for _bp in _bad_pdfs:
            warnings.append(
                f"Skipped non-PDF file in source/invoices (no %PDF- header): {_bp.name}"
            )
        if not inv_pdfs:
            if not _bad_pdfs:
                warnings.append("No invoice PDFs found in source/invoices — invoice recheck skipped")
            else:
                warnings.append("No valid invoice PDFs to parse — all files failed PDF header validation")
        else:
            try:
                from pz_import_processor import parse_invoice as _pi, compute_invoice_totals as _ct  # noqa: PLC0415
                _corr:   list = []
                _parsed: list = []
                for _pdf in inv_pdfs:
                    try:
                        _inv = _pi(str(_pdf), _corr)
                        if _inv:
                            _parsed.append(_inv)
                    except Exception as _ie:
                        warnings.append(f"Invoice parse error ({_pdf.name}): {_ie}")
                if _parsed:
                    _totals = _ct(_parsed)
                    audit["invoice_totals"] = _totals
                    updated["invoice_totals"] = True
                    # Refresh invoice_names so the rows-vs-audit reconciler
                    # compares against the actually-valid PDFs in source/invoices/
                    # — NOT the stale filename of a pre-C27.1 quarantined file
                    # whose name lingered in audit.json from an earlier intake.
                    audit["invoice_names"] = [p.name for p in inv_pdfs]
                    updated["invoice_names"] = True
                    # Update verification CIF reference
                    ver = audit.setdefault("verification", {})
                    ver["invoice_cif_total_usd"] = _totals.get("total_cif_usd")
                    updated["verification_cif"]  = True
                    # ── Persist learning traces ──────────────────────────
                    # parse_invoice() already called learn_from_parse() internally.
                    # We just capture the _learning_trace it attached and write to audit.
                    try:
                        _learning_traces = [
                            inv["_learning_trace"]
                            for inv in _parsed
                            if isinstance(inv.get("_learning_trace"), dict)
                        ]
                        if _learning_traces:
                            audit["learning_traces"] = _learning_traces
                            updated["learning"] = True
                            log.info("[LEARNING] [recheck/%s] %d trace(s) written to audit",
                                     batch_id, len(_learning_traces))
                        else:
                            log.debug("[LEARNING] [recheck/%s] no traces in parsed invoices", batch_id)
                    except Exception as _le:
                        log.warning("[LEARNING] [recheck/%s] persist error: %s", batch_id, _le)
                else:
                    errors.append("Invoice parsing returned no results")
            except ImportError as _imp:
                errors.append(f"Parser engine not available: {_imp}")

    # ── B. Re-run DHL pre-check ──────────────────────────────────────────────
    if mode in ("all", "dhl_precheck"):
        carrier = (audit.get("inputs", {}).get("carrier") or audit.get("carrier") or "DHL").upper()
        inv_dir = batch_dir / "source" / "invoices"
        inv_pdfs_all_b = sorted(inv_dir.glob("*.pdf")) if inv_dir.exists() else []
        # Same quarantine guard as Section A — a non-PDF masquerading as
        # .pdf cannot be allowed to drive DHL pre-check CIF to zero when
        # a valid sibling exists.
        inv_pdfs, _bad_b = _partition_valid_pdfs(inv_pdfs_all_b)
        for _bp in _bad_b:
            warnings.append(
                f"DHL precheck skipped non-PDF in source/invoices: {_bp.name}"
            )
        cif_usd  = 0.0
        parsed_n = 0
        cif_source = "not_parsed"
        try:
            from pz_import_processor import parse_invoice as _pi2, compute_invoice_totals as _ct2  # noqa: PLC0415
            _c2: list = []; _p2: list = []
            for _pdf in inv_pdfs:
                try:
                    _inv = _pi2(str(_pdf), _c2)
                    if _inv:
                        _p2.append(_inv)
                except Exception:
                    pass
            if _p2:
                _t2     = _ct2(_p2)
                cif_usd = _t2.get("total_cif_usd", 0.0)
                parsed_n = len(_p2)
                cif_source = "invoice_parser"
                # Persist learning traces only when Section A didn't already run
                if mode == "dhl_precheck":
                    try:
                        _lt2 = [
                            inv["_learning_trace"]
                            for inv in _p2
                            if isinstance(inv.get("_learning_trace"), dict)
                        ]
                        if _lt2:
                            audit["learning_traces"] = _lt2
                            updated["learning"] = True
                            log.info("[LEARNING] [recheck/dhl/%s] %d trace(s) written to audit",
                                     batch_id, len(_lt2))
                    except Exception as _lt2e:
                        log.warning("[LEARNING] [recheck/dhl/%s] persist error: %s", batch_id, _lt2e)
        except Exception:
            pass

        precheck: dict = {
            "completed_at":          datetime.now(timezone.utc).isoformat(),
            "carrier":               carrier,
            "invoice_cif_total_usd": round(cif_usd, 2) if cif_usd > 0 else None,
            "cif_source":            cif_source,
            "invoices_parsed":       parsed_n,
            "threshold_usd":         _DHL_BROKER_THRESHOLD_USD,
            "recheck_mode":          mode,
        }
        if carrier == "DHL":
            if cif_usd > 0:
                if cif_usd > _DHL_BROKER_THRESHOLD_USD:
                    precheck["clearance_hint"]    = "Broker / DSK may be required"
                    precheck["dsk_required_hint"] = True
                    precheck["note"] = (f"Invoice CIF ${cif_usd:,.2f} exceeds ${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold.")
                else:
                    precheck["clearance_hint"]    = "DHL standard clearance likely"
                    precheck["dsk_required_hint"] = False
                    precheck["note"] = (f"Invoice CIF ${cif_usd:,.2f} within ${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold.")
            else:
                precheck["clearance_hint"]    = "Invoice CIF not parsed — routing pending"
                precheck["dsk_required_hint"] = None
                precheck["note"] = "Invoice value could not be extracted."
        # Merge-not-replace guard (#570 link-wipe class): a fresh text-parse that
        # produced no CIF must NOT erase a CIF that a prior run already resolved
        # into dhl_precheck (e.g. the OCR/AI vision fallback). Only overwrite
        # invoice_cif_total_usd when this parse actually produced a positive value;
        # otherwise preserve the previously-resolved value and re-derive its hint.
        if cif_usd <= 0:
            _prev_pc = audit.get("dhl_precheck") or {}
            # Preserve every prior vision-written authority/provenance key the fresh
            # text-parse does not itself produce — not just invoice_cif_total_usd.
            # fob_total_usd is resolver ladder layer 5; vision_extracted /
            # vision_source_page are provenance. Dropping any of these on a no-CIF
            # recheck is the same #570 link-wipe class this guard exists to prevent.
            for _k in ("fob_total_usd", "vision_extracted", "vision_source_page"):
                if _k in _prev_pc and _k not in precheck:
                    precheck[_k] = _prev_pc[_k]
            _prev_cif = _prev_pc.get("invoice_cif_total_usd")
            if isinstance(_prev_cif, (int, float)) and _prev_cif > 0:
                precheck["invoice_cif_total_usd"] = round(_prev_cif, 2)
                precheck["cif_source"] = _prev_pc.get("cif_source", "preserved")
                precheck["invoice_cif_preserved"] = True
                if carrier == "DHL":
                    if _prev_cif > _DHL_BROKER_THRESHOLD_USD:
                        precheck["clearance_hint"]    = "Broker / DSK may be required"
                        precheck["dsk_required_hint"] = True
                        precheck["note"] = (f"Invoice CIF ${_prev_cif:,.2f} (preserved) exceeds ${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold.")
                    else:
                        precheck["clearance_hint"]    = "DHL standard clearance likely"
                        precheck["dsk_required_hint"] = False
                        precheck["note"] = (f"Invoice CIF ${_prev_cif:,.2f} (preserved) within ${_DHL_BROKER_THRESHOLD_USD:,.0f} threshold.")
        audit["dhl_precheck"] = precheck
        updated["dhl_precheck"] = True
        # Ensure clearance_status is set for DHL shipments so downstream guards
        # do not block doc generation.  Mirror the same rule used in the upload
        # precheck pipeline (routes_upload.py).
        if carrier == "DHL" and not audit.get("clearance_status"):
            audit["clearance_status"] = "awaiting_dhl_customs_email"
            updated["clearance_status"] = True

    # ── C. Reparse SAD / ZC429 (orchestrated: XML → PDF → AI fallback) ─────
    if mode in ("all", "sad"):
        sad_dir = batch_dir / "source" / "sad"
        has_files = sad_dir.exists() and any(
            sad_dir.glob("*.xml")) or any(
            sad_dir.glob("*.pdf")) or any(
            sad_dir.glob("*parsed*.json")
        ) if sad_dir.exists() else False
        if not has_files and not (audit.get("zc429") or {}).get("mrn"):
            warnings.append("No SAD/ZC429 files found in source/sad — SAD recheck skipped")
        else:
            try:
                from ..services.customs_parser_orchestrator import parse_customs_document
                orch = parse_customs_document(batch_id, sad_dir, audit=audit)
                if orch.get("mapped"):
                    cd = audit.setdefault("customs_declaration", {})
                    # Fix 5: Never overwrite non-null with null. XML source always beats PDF source.
                    # Only update a field when: new value is non-null, OR existing field is null/missing.
                    existing_source = cd.get("source", "")
                    new_source = orch.get("source", "")
                    # Source priority: xml_validated > xml_parsed > pdf_parsed > ai_supplemented
                    _src_rank = {"xml_validated": 4, "xml_parsed": 3, "pdf_parsed": 2,
                                 "ai_supplemented": 1, "": 0}
                    new_beats_existing = _src_rank.get(new_source, 0) >= _src_rank.get(existing_source, 0)
                    for _k, _v in orch["mapped"].items():
                        if _v is not None:
                            # New value is non-null: update if new source is >= existing, or field is absent
                            if new_beats_existing or cd.get(_k) is None:
                                cd[_k] = _v
                        # else: new value is null — never overwrite existing non-null with null
                    # Always update source+confidence if new source wins
                    if new_beats_existing:
                        if new_source:
                            cd["source"] = new_source
                        if orch.get("confidence") is not None:
                            cd["confidence"] = orch["confidence"]
                    # Propagate MRN to inputs
                    mrn = cd.get("mrn")
                    if mrn:
                        audit.setdefault("inputs", {})["zc429_mrn"] = mrn
                    updated["customs_declaration"] = True
                    # Log source for traceability
                    log.info("[recheck] customs_declaration updated: source=%s confidence=%s (prev_source=%s)",
                             new_source, orch.get("confidence"), existing_source)
                    if orch.get("corrections"):
                        warnings.extend([f"SAD: {c}" for c in orch["corrections"][:5]])
                    if orch.get("ai_supplemented_fields"):
                        warnings.append(
                            f"AI supplemented {len(orch['ai_supplemented_fields'])} field(s): "
                            f"{', '.join(orch['ai_supplemented_fields'])}"
                        )
                    # Persist AI evidence recovery result (PR #263 module).
                    # Stored regardless of reconciliation status so operators
                    # see the AI attempt; financial fields are never touched
                    # by this store.
                    if orch.get("ai_customs_evidence"):
                        audit["ai_customs_evidence"] = orch["ai_customs_evidence"]
                        updated["ai_customs_evidence"] = True
                        _ace_status = (orch["ai_customs_evidence"]
                                       .get("reconciliation", {}).get("status") or "")
                        if _ace_status == "verified_with_advisory":
                            warnings.append(
                                "SAD verified by MRN/AWB/CIF. Invoice "
                                "reference confirmed by AI evidence extraction."
                            )
                elif orch.get("error"):
                    errors.append(orch["error"])
                else:
                    errors.append("Customs parsing returned no results")
            except ImportError as _imp:
                errors.append(f"Parser engine not available: {_imp}")
            except Exception as _se:
                errors.append(f"SAD parse error: {_se}")

    # ── D. Rebuild verification summary (basic) ──────────────────────────────
    if mode in ("all",) and not errors:
        ver = audit.setdefault("verification", {})
        it  = audit.get("invoice_totals") or {}
        cd  = audit.get("customs_declaration") or {}
        # Only overwrite invoice CIF if invoice_totals was actually recomputed
        # this run — prevents stale invoice_totals from diverging with existing PDFs
        if updated.get("invoice_totals"):
            cif = it.get("total_cif_usd") or 0
            if cif:
                ver["invoice_cif_total_usd"] = cif
        if cd.get("duty_a00_pln") is not None:
            ver["duty_a00"] = cd["duty_a00_pln"]

        # ── Recompute CIF difference whenever either CIF value is refreshed ──
        # Without this the difference stays stale from the last engine run,
        # causing the CIF Comparison panel to show a non-zero diff even when
        # invoice CIF == SAD CIF.
        _inv_cif = ver.get("invoice_cif_total_usd")
        _sad_cif = ver.get("sad_cif_total_usd") or cd.get("sad_cif_usd")
        if _inv_cif is not None and _sad_cif is not None:
            _diff = round(_inv_cif - _sad_cif, 2)
            ver["cif_difference_usd"] = _diff
            _match = abs(_diff) < 1.0   # tolerance: $1 rounding
            ver["cif_match"] = _match
            if _match:
                ver["cif_status"] = "Verified"
                # Clear the stale CIF-mismatch amendment flag so the engine
                # run result no longer poisons the panel after a correct recheck.
                _flags = audit.get("amendment_flags") or []
                audit["amendment_flags"] = [
                    f for f in _flags if "CIF mismatch" not in f
                ]
                # Sync customs_declaration CIF fields too
                if cd:
                    cd["invoice_cif_usd"]  = _inv_cif
                    cd["cif_diff_usd"]     = _diff
                    cd["cif_alert"]        = False
                # Sync cif_reconciliation if present
                _rec = audit.get("cif_reconciliation")
                if _rec:
                    _rec["invoice_cif_total_usd"] = _inv_cif
                    _rec["difference_usd"]         = _diff
                    _rec["status"]                 = "Verified"
                    _rec["explanation"]            = "Verified by recheck"
                # ── Clear cif_match from failed_checks ──────────────────────
                # Stale failed_checks entry blocks the wFirma PZ guard even
                # after CIF is verified.  Mirrors the accept_sad pattern.
                _fc = list(audit.get("failed_checks") or [])
                if "cif_match" in _fc:
                    _fc = [c for c in _fc if c != "cif_match"]
                    audit["failed_checks"] = _fc
                    updated["failed_checks"] = True
                    # Upgrade blocked → partial when no checks remain and PZ files exist
                    if not _fc and audit.get("status") == "blocked":
                        _pz_exists = bool(
                            audit.get("pz_output", {}).get("generated_at")
                            or (audit.get("files", {}).get("pdf") or {}).get("sha256")
                        )
                        if _pz_exists:
                            audit["status"] = "partial"
                            updated["status"] = True
                            log.info(
                                "[recheck] status upgraded blocked → partial"
                                " (cif_match cleared from failed_checks)"
                            )

        updated["verification"] = True

    # ── D2. Upgrade status if customs data fully parsed ────────────────────
    if updated.get("customs_declaration") and audit.get("status") == "draft":
        cd_check = audit.get("customs_declaration") or {}
        if cd_check.get("mrn") and cd_check.get("duty_a00_pln") is not None:
            audit["status"] = "ready"
            updated["status"] = True
            log.info("[recheck] status upgraded draft → ready (customs_declaration parsed)")

    # ── E. Clearance decision (runs on all modes, non-fatal) ─────────────────
    _clearance_dec_for_tl: Optional[Dict[str, Any]] = None
    try:
        from ..services.clearance_decision import build_clearance_decision
        _dec = build_clearance_decision(audit)
        audit["clearance_decision"] = _dec
        updated["clearance_decision"] = True
        _clearance_dec_for_tl = _dec   # logged after write so event isn't overwritten
    except Exception as _de:
        log.warning("[recheck] clearance_decision failed (non-fatal): %s", _de)

    # ── Write recheck block + updated audit ─────────────────────────────────
    recheck_block = {
        "last_run_at":     datetime.now(timezone.utc).isoformat(),
        "last_mode":       mode,
        "warnings":        warnings,
        "errors":          errors,
        "updated_fields":  [k for k, v in updated.items() if v],
    }
    audit["recheck"] = recheck_block
    # Merge-not-replace: persist recheck's snapshot but overlay disk-authoritative
    # sole-writer keys (vision_invoice) so a concurrent operator confirmation that
    # landed in the read→write window is not reverted (#646, #570-class).
    _persist_recheck(audit_path, batch_id, audit)

    # ── E2. Image-only OCR/AI CIF fallback (LAST — self-contained) ───────────
    # When text reparse above left CIF UNKNOWN because the AWB / invoice is an
    # image-only scan, escalate to the vision extractor. It re-reads the
    # just-written audit, no-ops unless CIF is still UNKNOWN, and does its own
    # atomic merge-not-replace write. If it writes a CIF/AWB authority value,
    # rebuild the clearance decision so THIS recheck reflects it rather than
    # forcing the operator to recheck twice. Runs only on CIF-relevant modes.
    if mode in ("all", "dhl_precheck", "invoice"):
        try:
            from ..services.vision_extractor import run_image_only_cif_fallback
            _vres = run_image_only_cif_fallback(batch_dir, batch_id)
            if _vres.get("wrote"):
                updated["vision_extraction"] = True
                warnings.append(
                    "CIF/AWB value extracted via OCR/AI vision fallback from an "
                    "image-only document — review the source before booking."
                )
                # Re-read the audit the fallback just wrote, rebuild clearance.
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                try:
                    from ..services.clearance_decision import build_clearance_decision
                    _dec2 = build_clearance_decision(audit)
                    audit["clearance_decision"] = _dec2
                    _clearance_dec_for_tl = _dec2
                    updated["clearance_decision"] = True
                except Exception as _de2:
                    log.warning("[recheck] post-vision clearance rebuild failed: %s", _de2)
                audit["recheck"]["updated_fields"] = [k for k, v in updated.items() if v]
                # Merge-not-replace again: this post-fallback re-read+write also
                # runs after the read→write window, so overlay the disk copy of
                # vision_invoice rather than clobbering it (#646).
                _persist_recheck(audit_path, batch_id, audit)
                log.info("[recheck] vision CIF fallback wrote authority value for %s", batch_id)
                # Authority-chain evidence: trace the OCR/AI-sourced CIF/AWB write.
                tl.log_event(
                    audit_path, tl.EV_VISION_CIF_WRITTEN, "recheck", "vision_fallback",
                    detail={
                        "source": f"recheck:{mode}",
                        "documents": _vres.get("documents"),
                        "reason": _vres.get("reason"),
                    },
                )
            elif _vres.get("ran"):
                log.info("[recheck] vision CIF fallback ran, no write: %s", _vres.get("reason"))
        except Exception as _ve:
            log.warning("[recheck] vision CIF fallback failed (non-fatal): %s", _ve)

        # Advisory image-only invoice extraction (LAST — self-contained). Recovers
        # supplier / FOB / goods lines from an image-only invoice into the advisory
        # `vision_invoice` proposal (operator_confirmed=false) so the operator can
        # later confirm it to unblock PZ. Does NOT touch CIF / invoice_totals / rows.
        try:
            from ..services.vision_extractor import run_image_only_invoice_extraction
            _ires = run_image_only_invoice_extraction(batch_dir, batch_id)
            if _ires.get("wrote"):
                updated["vision_invoice"] = True
                warnings.append(
                    "An image-only invoice was read by OCR/AI into an advisory "
                    "proposal (supplier / FOB / goods lines) — review and confirm "
                    "it before generating PZ."
                )
            elif _ires.get("ran"):
                log.info("[recheck] vision invoice extraction ran, no write: %s", _ires.get("reason"))
        except Exception as _ie:
            log.warning("[recheck] vision invoice extraction failed (non-fatal): %s", _ie)

    # ── Log timeline events (after write so they're not overwritten) ──────────
    if _clearance_dec_for_tl is not None:
        tl.log_event(
            audit_path,
            tl.EV_CLEARANCE_DECISION,
            "recheck",
            "system",
            detail={
                "clearance_path":  _clearance_dec_for_tl.get("clearance_path"),
                "total_value_usd": _clearance_dec_for_tl.get("total_value_usd"),
                "require_dsk":     _clearance_dec_for_tl.get("require_dsk"),
            },
        )
    tl.log_event(audit_path, tl.EV_SHIPMENT_RECHECKED, "dashboard", "user",
                 detail={"mode": mode, "updated": list(updated.keys()), "warnings": len(warnings), "errors": len(errors)})

    return {
        "ok":       not errors,
        "batch_id": batch_id,
        "mode":     mode,
        "updated":  updated,
        "warnings": warnings,
        "errors":   errors,
        "next_step": "Review updated values before regenerating PZ" if not errors else "Fix errors and recheck again",
    }


# ── Vision-invoice operator confirmation (PR-2) ───────────────────────────────
# Sole writer of operator_confirmed=true on audit["vision_invoice"]. The machine
# extractor only ever writes operator_confirmed=false (sticky); this endpoint is
# the one human write-gate that promotes an advisory image-only invoice proposal
# to operator-attested authority. It does NOT inject into the engine, generate
# PZ, or post to wFirma — those stay blocked by design until the gated injection
# path ships (runbook Stage B).

@router.post("/batches/{batch_id}/vision-invoice/confirm")
async def confirm_vision_invoice_route(
    batch_id: str,
    session_user: dict = _op_auth,
) -> Dict[str, Any]:
    """Operator confirms the advisory image-only invoice proposal.

    Sets ``operator_confirmed=true`` on ``audit["vision_invoice"]`` (sole writer)
    and records ``confirmed_by`` / ``confirmed_at``. Advisory supplier
    cross-validation is returned but never blocks. Returns 409 when there is no
    confirmable proposal. Does NOT inject to the engine, generate PZ, or post to
    wFirma — confirmation alone does not produce PZ rows.

    Operator identity is the authenticated ``require_role`` user injected via
    ``_op_auth`` — derived SERVER-SIDE only, never from a client header/body. The
    role gate guarantees a real authenticated user, so ``operator_confirmed=true``
    is always attributable to a named human (no ghost-identity fallback).
    """
    if "/" in batch_id or "\\" in batch_id or ".." in batch_id:
        # Reject path separators (both POSIX and Windows) and parent-dir tokens
        # before any filesystem resolution — _resolve_audit_path joins batch_id
        # into a path, so traversal must be blocked here.
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = _resolve_audit_path(batch_id)
    if audit_path is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    batch_dir = audit_path.parent

    operator = (
        (session_user.get("full_name") or "").strip()
        or (session_user.get("email") or "").strip()
        or str(session_user.get("id") or "").strip()
    )
    if not operator:
        # require_role guarantees an authenticated user; this only fires on a
        # malformed user record. Refuse rather than mint an unattributable attest.
        raise HTTPException(status_code=401, detail="Operator identity required to confirm.")

    suppliers_db_path = settings.storage_root / "suppliers.sqlite"

    from ..services.vision_extractor import confirm_vision_invoice
    result = confirm_vision_invoice(
        batch_dir,
        batch_id,
        confirmed_by=operator,
        suppliers_db_path=suppliers_db_path,
    )

    if not result.get("ok"):
        reason = result.get("reason") or "cannot_confirm"
        if reason == "no_proposal":
            raise HTTPException(
                status_code=409,
                detail="No image-only invoice proposal to confirm for this shipment.",
            )
        if "unreadable" in reason or "audit not a dict" in reason:
            raise HTTPException(status_code=404, detail="Shipment audit not found.")
        if reason.startswith("batch busy"):
            raise HTTPException(status_code=409, detail=reason)
        raise HTTPException(status_code=400, detail=reason)

    # Stage C is live: the PZ engine bridge (_authority_rows_from_confirmed_vision
    # in pz_import_processor) consumes a confirmed vision_invoice as a Priority-3
    # authority source. Confirmation alone still does not generate PZ — it arms the
    # bridge — but the operator's next action ("Run/Retry PZ") now succeeds for
    # image-only invoices. wFirma posting remains a separate, explicit operator step.
    result["next_step"] = (
        "Invoice proposal confirmed. Click \"Run PZ\" (or \"Retry PZ\") on this "
        "shipment — the engine now reads these confirmed line items and generates "
        "the PZ document. Posting to wFirma remains a separate Create-PZ step."
    )
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _is_link_alive(url: str) -> bool:
    if not url.startswith("http"):
        return True  # local paths are always "alive"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.head(url)
            return r.status_code < 400
    except Exception:
        return False


# ── Resend to Cliq ────────────────────────────────────────────────────────────

@router.post("/batches/{batch_id}/resend", dependencies=[_op_auth])
async def resend_to_cliq(batch_id: str) -> Dict[str, Any]:
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")

    audit_path = _OUTPUTS / batch_id / "audit.json"
    if not audit_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found.")

    if not settings.cliq_webhook_url:
        raise HTTPException(status_code=503, detail="CLIQ_WEBHOOK_URL not configured.")

    # ── In-flight file lock (prevents cross-tab racing) ───────────────────────
    lock_path = _OUTPUTS / batch_id / ".resend_lock"
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age < 10:
            return {
                "success": False,
                "skipped": True,
                "status":  "skipped",
                "reason":  "send already in progress — retry in a moment",
                "error":   None,
            }
    lock_path.touch()

    try:
        with audit_path.open(encoding="utf-8") as fh:
            audit = json.load(fh)

        # ── Idempotency cooldown ──────────────────────────────────────────────
        cooldown     = settings.resend_cooldown_seconds
        delivery_log = audit.get("delivery_log", [])
        last         = delivery_log[-1] if delivery_log else None
        if last and last.get("status") == "success":
            elapsed = time.time() - last.get("ts_epoch", 0)
            if elapsed < cooldown:
                return {
                    "success":  False,
                    "skipped":  True,
                    "status":   "skipped",
                    "ts_epoch": last["ts_epoch"],
                    "cooldown": cooldown,
                    "reason":   f"recent successful send (< {cooldown}s ago) — retry later",
                    "error":    None,
                }

        # ── Resolve file URLs ─────────────────────────────────────────────────
        wdl      = audit.get("workdrive_links") or {}
        files    = audit.get("files", {})
        base_url = settings.fastapi_public_url.rstrip("/")

        async def _resolve(wd_key: str, file_key: str) -> str:
            wd_url    = wdl.get(wd_key, "")
            fname     = files.get(file_key, {}).get("name", "")
            local_url = f"{base_url}/api/v1/files/{batch_id}/{fname}" if fname else ""
            if wd_url and await _is_link_alive(wd_url):
                return wd_url
            if wd_url and local_url:
                return local_url  # WorkDrive link stale — fall back to local
            return wd_url or local_url

        pdf_url, xlsx_url = await _resolve("pdf", "pdf"), await _resolve("xlsx", "xlsx")

        if not pdf_url and not xlsx_url:
            raise HTTPException(
                status_code=422,
                detail="No file links available (WorkDrive sync incomplete or files missing).",
            )

        # ── Build message ─────────────────────────────────────────────────────
        status          = audit.get("status", "unknown")
        doc_no          = audit.get("doc_no", "")
        tracking_no     = audit.get("tracking_no", "")
        # Fallback: extract from batch_id if not stored in audit
        if not tracking_no and batch_id.startswith("SHIPMENT_"):
            _parts = batch_id.split("_")
            if len(_parts) >= 4 and _parts[1] != "AUTO":
                tracking_no = _parts[1]
        t               = audit.get("totals", {})
        amendment_flags = audit.get("amendment_flags", [])
        corrections     = audit.get("corrections_log", [])
        verify_gaps = [
            c.removeprefix("[VERIFY-GAP]").strip()
            for c in corrections if c.startswith("[VERIFY-GAP]")
        ]
        msg_id = str(uuid.uuid4())

        if status == "blocked":
            failed_checks = audit.get("failed_checks", [])
            failed_lines  = "\n".join(f"- {k} = FALSE" for k in failed_checks)
            flag_lines    = "\n".join(f"- {f}" for f in amendment_flags)
            trk_block     = f"Shipment / AWB: {tracking_no}\n" if tracking_no else ""
            text = (
                f"⚠️ PZ BLOCKED — verification mismatch\n"
                f"Document: {doc_no or '—'}\n"
                f"{trk_block}"
                f"Batch ID: {batch_id}\n"
                f"Failed checks:\n{failed_lines}"
                + (f"\nAmendment flags:\n{flag_lines}" if amendment_flags else "")
                + f"\nAction required: verify SAD vs invoices\nNo files posted."
                + f"\n---\nmsg:{msg_id}"
            )
        else:
            text = cliq_service.build_success_message(
                doc_no          = doc_no,
                tracking_no     = tracking_no,
                batch_id        = batch_id,
                lines           = t.get("line_count") or audit.get("line_count", 0),
                total_net       = t.get("net") or 0,
                total_gross     = t.get("gross") or 0,
                duty_pln        = t.get("duty") or 0,
                amendment_flags = amendment_flags,
                verify_gaps     = verify_gaps,
                pdf_url         = pdf_url,
                xlsx_url        = xlsx_url,
                msg_id          = msg_id,
            )

        # ── Send ──────────────────────────────────────────────────────────────
        ts        = time.strftime("%Y-%m-%dT%H:%M:%S")
        ts_epoch  = time.time()
        masked    = (settings.cliq_webhook_url or "")[:40] + "…"
        ok        = await cliq_service.post_to_channel(text)
        error_msg = None if ok else "Channel post failed"
        dlv_status: DeliveryStatus = "success" if ok else "failed"

        log_entry: Dict[str, Any] = {
            "timestamp":      ts,
            "ts_epoch":       ts_epoch,
            "action":         "resend_to_cliq",
            "status":         dlv_status,
            "target":         masked,
            "message_id":     msg_id,
            "error":          error_msg,
        }

        audit.setdefault("delivery_log", []).append(log_entry)
        audit["message_version"] = "v1"
        # Atomic write — prevents partial reads by the dashboard poller
        import os, tempfile
        dir_ = audit_path.parent
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(audit, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, audit_path)
        except Exception:
            try: os.remove(tmp)
            except OSError: pass
            raise

        if not ok:
            raise HTTPException(status_code=502, detail="Cliq delivery failed — webhook returned error.")

        return {
            "success":         True,
            "skipped":         False,
            "status":          "success",
            "timestamp":       ts,
            "ts_epoch":        ts_epoch,
            "delivery_target": masked,
            "message_id":      msg_id,
            "message_text":    text,
            "error":           None,
            "delivery_log":    audit["delivery_log"],
        }

    finally:
        if lock_path.exists():
            lock_path.unlink(missing_ok=True)

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.io import write_json_atomic

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# Add the engine directory to sys.path once at import time so process_batch()
# and its siblings are importable without copying source files.
_engine_dir = str(settings.engine_dir)
if _engine_dir not in sys.path:
    sys.path.insert(0, _engine_dir)


def run_engine_health_check() -> tuple[bool, str]:
    """
    Run `make verify` (or the test suite directly) against the engine.
    Returns (passed, message).
    """
    makefile = settings.engine_dir / "Makefile"
    if makefile.exists():
        result = subprocess.run(
            ["make", "verify"],
            cwd=str(settings.engine_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = result.returncode == 0
        detail = (result.stdout + result.stderr).strip()[-500:]
        return ok, detail

    # Fallback: run the test suite directly
    result = subprocess.run(
        [sys.executable, "test_pz_regression.py"],
        cwd=str(settings.engine_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    ok = result.returncode == 0
    detail = (result.stdout + result.stderr).strip()[-500:]
    return ok, detail


def process_shipment(
    invoice_dir: Path,
    zc429_path:  Path,
    output_dir:  Path,
    doc_no:          str   = "",
    settlement_mode: str   = "standard",
    carrier:         str   = "",
    nbp_rate:        Optional[float] = None,
    zc429_dict:      Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Bridge into the Python engine.
    Returns the full process_batch() result dict plus pdf_path / xlsx_path.
    Raises RuntimeError on engine failure.

    If zc429_dict is provided, it bypasses the PDF parser and uses
    the pre-parsed XML data directly (e.g. from audit.zc429).
    """
    from pz_import_processor import process_batch, collect_pdfs
    from pz_pdf_export import save_pz_pdf
    from pz_dual_export import export_pz_calculation_xlsx

    inv_paths = collect_pdfs([str(invoice_dir)])
    if not inv_paths:
        raise RuntimeError("No invoice PDFs found in invoice directory.")

    batch_meta = {
        "settlement_mode":      settlement_mode,
        "prefer_carrier_label": bool(carrier),
        "carrier_name":         carrier,
    }

    log.info("Running process_batch() for %d invoice(s), ZC429=%s",
             len(inv_paths), zc429_path.name)

    # If pre-parsed ZC429 dict is available, use it directly instead of
    # calling process_batch (which would try to parse the PDF and fail
    # on non-ZC429 PDFs like duty notices / awizo).
    if zc429_dict:
        log.info("Using pre-parsed ZC429 dict (XML source), bypassing PDF parser")
        # Build a parse_zc429-compatible dict from the XML data
        zc429_parsed = _build_zc429_from_xml_dict(zc429_dict)

        # Monkey-patch parse_zc429 to return our pre-parsed data, then call
        # process_batch normally — this preserves the full pipeline (NBP,
        # calculate_landed, verification, amendment_flags, etc.).
        import pz_import_processor as _engine
        _original_parse_zc429 = _engine.parse_zc429
        _engine.parse_zc429 = lambda path, corr: zc429_parsed

        try:
            result = process_batch(
                inv_paths  = inv_paths,
                zc429_path = str(zc429_path),
                rate       = nbp_rate,
                batch_meta = batch_meta,
            )
        finally:
            _engine.parse_zc429 = _original_parse_zc429
    else:
        result = process_batch(
            inv_paths  = inv_paths,
            zc429_path = str(zc429_path),
            rate       = nbp_rate,
            batch_meta = batch_meta,
        )

    # ── PDF export ────────────────────────────────────────────────────────────
    # Filenames include batch_id to prevent WorkDrive search collisions
    batch_id  = output_dir.name
    safe_doc  = (doc_no or "PZ").replace(" ", "_").replace("/", "-")
    pdf_path  = output_dir / f"{safe_doc}_{batch_id}.pdf"
    xlsx_path = output_dir / f"{safe_doc}_{batch_id}_calc.xlsx"

    # Sanity: doc_no slug should appear in the filename
    if doc_no and safe_doc not in pdf_path.stem:
        log.warning("Filename mismatch: doc_no=%r but pdf stem=%r", doc_no, pdf_path.stem)

    log.info("Generating PDF → %s", pdf_path)
    save_pz_pdf(result, str(pdf_path), document_no=doc_no)

    log.info("Generating XLSX → %s", xlsx_path)
    export_pz_calculation_xlsx(result, str(xlsx_path), document_no=doc_no)

    result["pdf_path"]  = pdf_path
    result["xlsx_path"] = xlsx_path

    # ── Audit log ─────────────────────────────────────────────────────────────
    _write_audit(output_dir, batch_id, doc_no, result, pdf_path, xlsx_path,
                 inv_paths=inv_paths, zc429_path=zc429_path)

    # ── PZ rows snapshot (wFirma export source) ───────────────────────────────
    # Written separately from audit.json so the wFirma exporter can read rows
    # without re-running the engine or parsing the XLSX.
    _write_pz_rows_json(output_dir, result)

    # ── Compliance audit report (bilingual EN + PL) + PDF memo + risk score ──
    result["audit_generation_status"] = "pending"
    try:
        log.info("Generating Audit EN/PL reports (build_audit_report)…")
        from audit_agent import build_audit_report
        from audit_pdf import generate_audit_pdf

        audit_reports = build_audit_report(result, output_dir, batch_id, doc_no)
        result["audit_en_path"]       = audit_reports["en"]
        result["audit_pl_path"]       = audit_reports["pl"]
        result["audit_score"]         = audit_reports["score"]
        result["audit_risk_level"]    = audit_reports["risk_level"]
        result["audit_failed_checks"] = audit_reports["failed_checks"]
        result["audit_data"]          = audit_reports.get("audit_data", {})
        result["freight_checks"]      = audit_reports.get("freight_checks", [])
        log.info("Audit EN PDF → %s", audit_reports["en"])
        log.info("Audit PL PDF → %s", audit_reports["pl"])
        log.info("Audit score  → %d (%s)", audit_reports["score"], audit_reports["risk_level"])

        # PDF memo
        log.info("Generating Audit Memo PDF (generate_audit_pdf)…")
        audit_pdf_path = output_dir / "audit_memo.pdf"
        generate_audit_pdf(audit_pdf_path, audit_reports["audit_data"])
        result["audit_pdf_path"] = audit_pdf_path
        result["audit_generation_status"] = "ok"
        log.info("Audit Memo PDF → %s", audit_pdf_path)

    except Exception as exc:
        _err = str(exc)
        log.error("Audit PDF generation failed: %s", _err, exc_info=True)
        result["audit_generation_error"]  = _err
        result["audit_generation_status"] = "failed"

    # ── Auto-correction suggestion engine ─────────────────────────────────────
    try:
        from correction_engine import build_corrections, write_correction_report

        import os
        learning_frozen = os.environ.get("LEARNING_FROZEN", "0").lower() in ("1", "true", "yes")
        corrections = build_corrections(
            audit_data          = result.get("audit_data", {}),
            result              = result,
            batch_id            = batch_id,
            doc_no              = doc_no,
            freight_checks      = result.get("freight_checks", []),
            learning_confidence = result.get("learning_confidence", {}),
            learning_frozen     = learning_frozen,
        )
        corr_paths = write_correction_report(
            corrections = corrections,
            output_dir  = output_dir,
            batch_id    = batch_id,
            doc_no      = doc_no,
        )
        result["corrections_en_path"]   = corr_paths["en"]
        result["corrections_pl_path"]   = corr_paths["pl"]
        result["corrections_json_path"] = corr_paths["json"]
        result["correction_report"]     = corrections.to_dict()
        log.info(
            "Correction report → %d item(s) [critical=%s, warning=%s]",
            len(corrections.corrections), corrections.has_critical, corrections.has_warning,
        )
    except Exception as exc:
        log.warning("Correction engine failed (non-fatal): %s", exc, exc_info=True)
        result["correction_generation_error"] = str(exc)

    # ── TrueSync mirror (optional — convenience copy only) ───────────────────
    # When WORKDRIVE_SYNC_ROOT is configured, mirror output files into the
    # TrueSync folder as a convenience backup. This is NEVER used as a success
    # condition or as the primary cloud upload path. Local storage is truth.
    sync_root = settings.workdrive_sync_root
    _sync_dir_str: str = ""
    if sync_root:
        import shutil as _shutil
        from datetime import datetime as _dt, timezone as _tz
        _now   = _dt.now(_tz.utc)
        sync_dir = Path(sync_root) / _now.strftime("%Y") / _now.strftime("%m") / output_dir.name
        try:
            sync_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(pdf_path,  sync_dir / pdf_path.name)
            _shutil.copy2(xlsx_path, sync_dir / xlsx_path.name)
            for _k in ("audit_en_path", "audit_pl_path", "audit_pdf_path",
                       "corrections_en_path", "corrections_pl_path", "corrections_json_path"):
                _p = result.get(_k)
                if _p and Path(_p).exists():
                    _shutil.copy2(_p, sync_dir / Path(_p).name)
            for _src in (inv_paths or []):
                _sp = Path(_src)
                if _sp.exists():
                    _shutil.copy2(_sp, sync_dir / _sp.name)
            if zc429_path and zc429_path.exists():
                _shutil.copy2(zc429_path, sync_dir / zc429_path.name)
            _sync_dir_str = str(sync_dir)
            log.info("TrueSync mirror → %s", sync_dir)
        except Exception as _exc:
            log.warning("TrueSync mirror failed (non-fatal, not blocking): %s", _exc)

    # ── WorkDrive direct upload (primary cloud path) ──────────────────────────
    # Upload PDF + XLSX directly to WorkDrive REST API (MYSPACE_LIBRARY).
    # This is the ONLY authoritative cloud upload — NOT TrueSync.
    #
    # Architecture rules:
    #   - PZ completes regardless of WorkDrive upload outcome
    #   - On success: resource IDs returned in result + written to audit
    #   - On failure: retry queue entry created; Cliq still notified
    #   - Never block, never retry inline, never search TrueSync
    from datetime import datetime as _dt2, timezone as _tz2
    _now2  = _dt2.now(_tz2.utc)
    _year2 = _now2.strftime("%Y")
    _month2= _now2.strftime("%m")
    _wd_upload: dict = {
        "success": False,
        "pdf_resource_id": None,
        "xlsx_resource_id": None,
        "batch_folder_id": None,
        "error": "not_attempted",
        "retry_queued": False,
    }

    try:
        from .workdrive_uploader import is_configured as _wd_is_configured
        from .workdrive_uploader import upload_pz_outputs as _wd_upload_fn

        if _wd_is_configured():
            log.info("[workdrive] direct upload starting — batch=%s", batch_id)
            _raw = _wd_upload_fn(
                batch_id=batch_id,
                pdf_path=pdf_path,
                xlsx_path=xlsx_path,
            )
            _wd_upload.update(_raw)

            if _raw.get("success"):
                result["workdrive_pdf_resource_id"]  = _raw.get("pdf_resource_id")
                result["workdrive_xlsx_resource_id"] = _raw.get("xlsx_resource_id")
                result["workdrive_batch_folder_id"]  = _raw.get("batch_folder_id")
                log.info(
                    "[workdrive] ✅ upload OK — pdf=%s xlsx=%s folder=%s",
                    _raw.get("pdf_resource_id"),
                    _raw.get("xlsx_resource_id"),
                    _raw.get("batch_folder_id"),
                )
            else:
                # Upload failed — enqueue retry for each failed file, non-blocking
                _target_folder = f"PZ/{_year2}/{_month2}/{batch_id}"
                log.warning(
                    "[workdrive] upload failed (%s) — enqueueing retry",
                    _raw.get("error"),
                )
                try:
                    from .workdrive_retry_service import enqueue as _wd_enqueue
                    if not _raw.get("pdf_resource_id") and pdf_path.exists():
                        _wd_enqueue(batch_id, "pdf", pdf_path, _target_folder)
                    if not _raw.get("xlsx_resource_id") and xlsx_path.exists():
                        _wd_enqueue(batch_id, "xlsx", xlsx_path, _target_folder)
                    _wd_upload["retry_queued"] = True
                except Exception as _rq_exc:
                    log.warning("[workdrive] retry enqueue failed: %s", _rq_exc)
        else:
            _wd_upload["error"] = "workdrive_not_configured"
            log.debug("[workdrive] not configured — skipping direct upload")

    except Exception as _wd_exc:
        _wd_upload["error"] = str(_wd_exc)
        log.warning("[workdrive] upload error (non-fatal): %s", _wd_exc)
        # Still try to enqueue retry
        try:
            from .workdrive_retry_service import enqueue as _wd_enqueue
            _target_folder = f"PZ/{_year2}/{_month2}/{batch_id}"
            if pdf_path.exists():
                _wd_enqueue(batch_id, "pdf", pdf_path, _target_folder)
            if xlsx_path.exists():
                _wd_enqueue(batch_id, "xlsx", xlsx_path, _target_folder)
            _wd_upload["retry_queued"] = True
        except Exception:
            pass

    # ── Patch audit.json with WorkDrive fields (always) ──────────────────────
    _audit_path = output_dir / "audit.json"
    try:
        _audit = json.loads(_audit_path.read_text()) if _audit_path.exists() else {}
        # TrueSync mirror info (informational only)
        if _sync_dir_str:
            _audit["truesync_mirror"] = _sync_dir_str
        # WorkDrive upload status block
        _audit["workdrive_upload"] = {
            "status":          "success" if _wd_upload.get("success") else (
                               "retry_queued" if _wd_upload.get("retry_queued") else "failed"
            ),
            "retry_required":  not _wd_upload.get("success"),
            "error":           _wd_upload.get("error") if not _wd_upload.get("success") else None,
            "timestamp":       _dt2.now(_tz2.utc).isoformat(),
        }
        # Flat resource ID fields for easy polling
        _audit["workdrive_direct_upload"]    = _wd_upload.get("success", False)
        _audit["workdrive_pdf_resource_id"]  = _wd_upload.get("pdf_resource_id")
        _audit["workdrive_xlsx_resource_id"] = _wd_upload.get("xlsx_resource_id")
        _audit["workdrive_batch_folder_id"]  = _wd_upload.get("batch_folder_id")
        write_json_atomic(_audit_path, _audit)
    except Exception as _exc2:
        log.warning("audit.json WorkDrive patch failed: %s", _exc2)

    log.info("Batch complete. Lines=%d  Netto=%.2f  Brutto=%.2f",
             result["line_count"], result["total_net"], result["total_gross"])

    return result


# ── Audit log ─────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


_ENGINE_VERSION = "v1.4"


def _derive_status(v: dict, amendment_flags: list, corrections_log: list) -> str:
    if amendment_flags or any(
        val is False for val in v.values() if not isinstance(val, (list, dict))
    ):
        return "blocked"
    if any(c.startswith("[VERIFY-GAP]") for c in corrections_log) or any(
        val is None for val in v.values() if not isinstance(val, (list, dict))
    ):
        return "partial"
    return "success"


def _build_customs_declaration(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and enrich customs declaration metadata from the engine result.
    Stored in audit.json as 'customs_declaration' — used by dashboard.
    Does NOT modify any calculated values.
    """
    zc429  = result.get("zc429", {})
    nbp    = result.get("nbp", {})
    v      = result.get("verification", {})

    nbp_rate     = nbp.get("usd_rate", 0.0)
    nbp_table    = nbp.get("table_no", "")
    nbp_date     = nbp.get("table_date", "")
    customs_rate = zc429.get("customs_rate_usd") or v.get("sad_customs_rate", 0.0)

    # Art. 33a: B00 payment method "G" = deferred VAT (Art. 33a)
    b00_method = zc429.get("b00_payment_method", "")
    a00_method = zc429.get("a00_payment_method", "")
    art33a     = (b00_method == "G")

    # Exchange rate delta
    rate_delta = None
    rate_pct   = None
    if nbp_rate and customs_rate:
        rate_delta = round(abs(nbp_rate - customs_rate), 4)
        rate_pct   = round(rate_delta / customs_rate * 100, 2) if customs_rate else None

    # CIF values
    inv_cif_usd  = v.get("invoice_cif_total_usd", 0.0)
    sad_cif_usd  = v.get("sad_cif_total_usd", 0.0) or zc429.get("total_cif_usd", 0.0)
    cif_diff_usd = round(abs((inv_cif_usd or 0) - (sad_cif_usd or 0)), 2)

    return {
        # Identification
        "mrn":              zc429.get("mrn", ""),
        "lrn":              zc429.get("lrn", ""),
        "clearance_date":   zc429.get("clearance_date", ""),
        "customs_agent":    zc429.get("agent", ""),
        "importer_name":    zc429.get("importer_name", ""),
        "importer_nip":     zc429.get("importer_nip", ""),
        "exporter_name":    zc429.get("exporter_name", ""),
        # Exchange rates
        "sad_customs_rate": customs_rate,
        "nbp_rate":         nbp_rate,
        "nbp_table":        nbp_table,
        "nbp_date":         nbp_date,
        "rate_delta":       rate_delta,
        "rate_delta_pct":   rate_pct,
        "rate_alert":       (rate_pct is not None and rate_pct > 1.0),
        # Payment / Art. 33a
        "a00_payment_method": a00_method,   # R = standard, G = deferred
        "b00_payment_method": b00_method,   # R = standard, G = Art. 33a
        "art33a":           art33a,
        "vat_mode":         "art33a" if art33a else "standard",
        "vat_mode_label_en": "Art. 33a — VAT deferred (settled in VAT return)" if art33a
                             else "Standard import — VAT paid at customs",
        "vat_mode_label_pl": "Art. 33a — VAT rozliczany w deklaracji VAT" if art33a
                             else "Standardowy import — VAT płatny przy odprawie",
        # Duties
        "duty_a00_pln":     zc429.get("duty_pln", 0.0),
        "vat_b00_pln":      zc429.get("vat_pln", 0.0),
        # CIF
        "invoice_cif_usd":  inv_cif_usd,
        "sad_cif_usd":      sad_cif_usd,
        "cif_diff_usd":     cif_diff_usd,
        "cif_alert":        cif_diff_usd > 0.5,
        # AWB refs from SAD
        "transport_refs":   zc429.get("transport_refs", []),
        # SAD Qty by type (from goods description parsing)
        "sad_qty_total":    sum(zc429.get("sad_qty_by_type", {}).values()) or None,
        "sad_qty_by_type":  zc429.get("sad_qty_by_type", {}),
        # Extended SAD fields
        "statistical_value_pln": zc429.get("statistical_value_pln", 0.0),
        "goods_description":     zc429.get("goods_description", ""),
        "cn_code":               zc429.get("cn_code", ""),
        # Values comparison
        "awb_customs_value_usd": inv_cif_usd,   # commercial invoice CIF = declared AWB value
        "sad_invoice_value_usd": sad_cif_usd,   # Wartość faktur from SAD (field 14 06)
        "values_match":          abs(cif_diff_usd) <= 1.0 if (inv_cif_usd and sad_cif_usd) else None,
    }


def _build_structured_checks(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the four structured audit check blocks required for Global Jewellery
    and any shipment where SAD/invoice reconciliation needs detailed explanation.

    All four blocks are always present in audit.json — never omitted.
    """
    v        = result.get("verification", {})
    zc429    = result.get("zc429", {})
    invoices = result.get("invoices", [])

    # ── 1. Invoice reference check ────────────────────────────────────────────
    _inv_refs_from_pdf = v.get("parsed_invoice_nos", [])
    _inv_refs_from_sad = v.get("sad_invoice_refs", [])
    _inferred_refs     = zc429.get("inferred_refs", [])
    _refs_method       = zc429.get("invoice_refs_method", "N935")

    _inv_ref_status = v.get("invoice_refs_label", "")
    if not _inv_ref_status:
        if v.get("invoice_refs_match") is True:
            _inv_ref_status = "Verified"
        elif v.get("invoice_refs_match") is False:
            _inv_ref_status = "Not found in SAD"
        else:
            if _inferred_refs or _refs_method == "inferred_from_sad_free_text":
                _inv_ref_status = "Partially verified — invoice references inferred from SAD/free text"
            elif _inv_refs_from_sad:
                _inv_ref_status = "Partially verified — invoice references inferred from SAD/free text"
            else:
                _inv_ref_status = "Not found in SAD"

    invoice_reference_check = {
        "status":               _inv_ref_status,
        "invoice_refs_from_pdf": _inv_refs_from_pdf,
        "invoice_refs_from_sad": _inv_refs_from_sad,
        "inferred_refs":         _inferred_refs,
        "method":                _refs_method,
    }

    # ── 2. CIF reconciliation ─────────────────────────────────────────────────
    _inv_cif_usd     = v.get("invoice_cif_total_usd", 0.0)
    _sad_cif_usd     = v.get("sad_cif_total_usd", 0.0)
    _sad_inv_val_usd = zc429.get("sad_invoice_value_usd", 0.0)
    _sad_add_pln     = zc429.get("sad_additions_pln", 0.0)
    _customs_rate    = zc429.get("customs_rate_usd", 0.0)
    _diff_usd        = v.get("cif_difference_usd", 0.0)

    _sad_add_usd_est = 0.0
    if _sad_add_pln and _customs_rate and _customs_rate > 0:
        _sad_add_usd_est = round(_sad_add_pln / _customs_rate, 2)

    _cif_status = v.get("cif_status", "")
    if not _cif_status:
        if v.get("cif_match") is True:
            _cif_status = "Verified"
        elif v.get("cif_match") is False:
            _cif_status = "Mismatch after additions check"
        elif _diff_usd and abs(_diff_usd) > 0:
            _cif_status = "Verification needed — difference appears to be freight/insurance/customs adjustment"
        else:
            _cif_status = "SAD CIF not available"

    # Use awb_customs_value = invoice CIF total (commercial invoice is the AWB declared value)
    cif_reconciliation = {
        "invoice_cif_total_usd":   _inv_cif_usd,
        "sad_invoice_value_usd":   _sad_inv_val_usd or _sad_cif_usd,
        "awb_customs_value_usd":   _inv_cif_usd,
        "sad_additions_pln":       _sad_add_pln,
        "sad_additions_usd_estimate": _sad_add_usd_est,
        "difference_usd":          _diff_usd,
        "explanation":             _cif_status,
        "status":                  _cif_status,
    }

    # ── 3. Blocked phrase check ───────────────────────────────────────────────
    _blocked_clean   = v.get("blocked_phrases_clean", True)
    _corr_log        = result.get("corrections_log", [])
    _blocked_hits    = [
        c.replace("[BLOCKED-PHRASE] ", "")
        for c in _corr_log
        if c.startswith("[BLOCKED-PHRASE]")
    ]
    _scanned_files   = [inv.get("filename", "") for inv in invoices]

    if _blocked_clean:
        _blocked_status = "Verified — no blocked phrases detected"
    else:
        _blocked_status = "Blocked phrase detected"

    blocked_phrase_check = {
        "status":       _blocked_status,
        "hits":         _blocked_hits,
        "scanned_files": _scanned_files,
    }

    # ── 4. Exporter check ─────────────────────────────────────────────────────
    _inv_exporter  = v.get("invoice_exporter_name", "")
    _sad_exporter  = v.get("sad_exporter_name", "")
    _exp_source    = v.get("exporter_source", "neither")
    _exp_match     = v.get("exporter_match")

    _exp_label = v.get("exporter_label", "")
    if not _exp_label:
        if _exp_match is True:
            _exp_label = "Parsed from SAD"
        elif _exp_source == "invoice_only":
            _exp_label = "Parsed from invoice; SAD exporter not available"
        elif _exp_match is False:
            _exp_label = "Parsed with variance"
        else:
            _exp_label = "Parsed from invoice; SAD exporter not available"

    # Determine source description
    if _exp_source == "invoice_and_sad":
        _source_desc = "invoice and SAD"
    elif _exp_source == "invoice_only":
        _source_desc = "invoice"
    elif _exp_source == "sad_only":
        _source_desc = "SAD"
    else:
        _source_desc = "not parsed"

    exporter_check = {
        "invoice_exporter": _inv_exporter,
        "sad_exporter":     _sad_exporter,
        "source":           _source_desc,
        "status":           _exp_label,
    }

    return {
        "invoice_reference_check": invoice_reference_check,
        "cif_reconciliation":      cif_reconciliation,
        "blocked_phrase_check":    blocked_phrase_check,
        "exporter_check":          exporter_check,
    }


def _write_pz_rows_json(output_dir: Path, result: Dict[str, Any]) -> None:
    """
    Write a slim pz_rows.json alongside audit.json.
    Contains only the fields needed by the wFirma exporter — no recalculation.
    Non-fatal: silently skips on any error so the main pipeline is never blocked.
    """
    try:
        rows = result.get("rows") or []
        slim = []
        for r in rows:
            slim.append({
                "invoice_no":        r.get("invoice_no", ""),
                "description_en":    r.get("description_en", ""),
                "pl_desc":           r.get("pl_desc", "") or r.get("description_en", ""),
                "quantity":          r.get("quantity", 1),
                "unit":              r.get("unit", "PCS"),
                "unit_netto_pln":    r.get("unit_netto_pln", r.get("landed_per_unit", 0)),
                "line_netto_pln":    r.get("line_netto_pln", r.get("total_netto", 0)),
                "line_brutto_pln":   r.get("line_brutto_pln", r.get("total_brutto", 0)),
                "allocated_duty_pln": r.get("allocated_duty_pln", 0),
                "usd_pln":           r.get("usd_pln", 0),
                "item_type":         r.get("item_type", ""),
            })
        write_json_atomic(output_dir / "pz_rows.json", slim)
        log.info("pz_rows.json → %s (%d rows)", output_dir / "pz_rows.json", len(slim))
    except Exception as e:
        log.warning("pz_rows.json write failed (non-fatal): %s", e)


def _write_audit(
    output_dir:  Path,
    batch_id:    str,
    doc_no:      str,
    result:      Dict[str, Any],
    pdf_path:    Path,
    xlsx_path:   Path,
    inv_paths:   Optional[list] = None,
    zc429_path:  Optional[Path] = None,
    tracking_no: str = "",
) -> None:
    v              = result.get("verification", {})
    amendment_flags = v.get("amendment_flags", [])
    corrections     = result.get("corrections_log", [])
    ver_scalar      = {k: val for k, val in v.items() if not isinstance(val, (list, dict))}
    failed_checks   = [k for k, val in ver_scalar.items() if val is False]

    status = _derive_status(v, amendment_flags, corrections)

    # Derive tracking_no from batch_id if not supplied explicitly
    if not tracking_no and batch_id.startswith("SHIPMENT_"):
        _parts = batch_id.split("_")
        if len(_parts) >= 4 and _parts[1] != "AUTO":
            tracking_no = _parts[1]

    # Build structured checks (Global Jewellery / multi-source reconciliation)
    structured_checks = _build_structured_checks(result)

    # Preserve pre-processing fields from the existing draft audit.json
    # (timeline, dhl_precheck, clearance_status, carrier, etc.)
    audit_path = output_dir / "audit.json"
    _existing: Dict[str, Any] = {}
    try:
        if audit_path.exists():
            import json as _json
            _existing = _json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        pass  # non-fatal: old audit missing or corrupt

    audit = {
        "correction_schema_version": "v2",    # guards UI against old batches
        "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        "batch_id":       batch_id,
        "tracking_no":    tracking_no,
        "doc_no":         doc_no,
        "status":         status,
        "engine_version": _ENGINE_VERSION,
        "folder_path":    str(output_dir.resolve()),
        "inputs": {
            "invoices":     [Path(p).name for p in (inv_paths or [])],
            "zc429":        zc429_path.name if zc429_path else None,
            "zc429_mrn":    result.get("zc429", {}).get("mrn"),
            "nbp_rate_usd": result.get("nbp", {}).get("usd_rate"),
            "nbp_table":    result.get("nbp", {}).get("table_no"),
            "invoice_refs": v.get("sad_invoice_refs", []),
            # Preserve AWB filename from draft audit (set at upload time)
            "awb":          _existing.get("inputs", {}).get("awb"),
        },
        "totals": {
            "net":        result.get("total_net"),
            "gross":      result.get("total_gross"),
            "duty":       result.get("duty_pln"),
            "line_count": result.get("line_count", 0),
        },
        "verification":     ver_scalar,
        "failed_checks":    failed_checks,
        "amendment_flags":  amendment_flags,
        "corrections_log":  corrections,
        "correction_report": result.get("correction_report"),   # structured v2 report
        "files": {
            "pdf":  {"name": pdf_path.name,  "sha256": _sha256(pdf_path)},
            "xlsx": {"name": xlsx_path.name, "sha256": _sha256(xlsx_path)},
        },
        "customs_declaration": _build_customs_declaration(result),
        "invoice_totals":      result.get("invoice_totals", {}),
        "settlement_mode":     result.get("settlement_mode", "standard"),
        # Audit generation status — always present
        "audit_generation_status":     result.get("audit_generation_status", "not_run"),
        "audit_generation_error":      result.get("audit_generation_error"),
        "correction_generation_error": result.get("correction_generation_error"),
        # Invoice parser learning traces (one per invoice)
        "learning_traces": result.get("learning_traces", []),
        # Structured reconciliation checks (per-shipment audit detail)
        **structured_checks,
        # ── Preserve dashboard-upload fields from draft audit ─────────────────
        # These are written at shipment-creation time and must survive engine rewrite.
        "carrier":          _existing.get("carrier", ""),
        "tracking_url":     _existing.get("tracking_url", ""),
        "source":           _existing.get("source", ""),
        "dhl_precheck":     _existing.get("dhl_precheck"),
        "clearance_status": _existing.get("clearance_status"),
        # Preserve pre-processing timeline events (batch_created, invoice_uploaded, etc.)
        "timeline":         _existing.get("timeline", []),
    }
    write_json_atomic(audit_path, audit)
    log.info("Audit log (atomic) → %s", audit_path)
    # Expose derived status on the result dict so callers can check it
    result["status"] = status


def _build_zc429_from_xml_dict(xml_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert an audit.zc429 XML-parsed dict into the format that parse_zc429()
    returns, so the rest of the engine pipeline (distribute_duty, build_rows,
    verify_sad_invoice_match, etc.) works without modification.
    """
    items = xml_dict.get("goods_items") or []

    # Aggregate values
    total_a00 = xml_dict.get("total_A00_duty_pln") or sum(
        (g.get("A00_duty_pln") or 0) for g in items
    )
    total_b00 = xml_dict.get("total_B00_vat_pln") or sum(
        (g.get("B00_vat_pln") or 0) for g in items
    )
    total_invoiced = xml_dict.get("total_invoiced") or sum(
        (g.get("invoiced_usd") or 0) for g in items
    )
    total_stat = sum((g.get("statistical_value_pln") or 0) for g in items)

    # Invoice refs
    invoice_refs = []
    for g in items:
        for inv in (g.get("invoices") or []):
            if inv not in invoice_refs:
                invoice_refs.append(inv)

    # CN codes
    cn_codes = [g.get("hs_code", "") for g in items if g.get("hs_code")]

    # Descriptions
    descriptions = [g.get("description", "") for g in items if g.get("description")]

    # Qty by type — XML has HS codes mapped to descriptions, not per-type quantities.
    # The engine expects {"RING": 5, "PENDANT": 2} format from PDF parsing.
    # Set to empty dict since XML doesn't provide this granularity — verification
    # will correctly report qty_match=None (not parseable).
    sad_qty_by_type: dict = {}

    # Clearance date
    clearance_date = ""
    for g in items:
        rd = g.get("release_date", "")
        if rd:
            clearance_date = str(rd)[:10]
            break
    if not clearance_date:
        acc = xml_dict.get("acceptance_date", "")
        if acc:
            clearance_date = str(acc)[:10]

    # Exchange rate
    customs_rate = 0.0
    if total_invoiced and total_stat:
        customs_rate = round(total_stat / total_invoiced, 4)

    # Payment methods
    a00_method = ""
    b00_method = ""
    for g in items:
        if not a00_method:
            a00_method = g.get("A00_payment_method") or g.get("a00_payment_method") or ""
        if not b00_method:
            b00_method = g.get("B00_payment_method") or g.get("b00_payment_method") or ""

    # Transport
    awb = xml_dict.get("awb", "")
    transport_refs = [awb] if awb else []

    return {
        "mrn":                  xml_dict.get("mrn", ""),
        "lrn":                  xml_dict.get("lrn", ""),
        "clearance_date":       clearance_date,
        "duty_pln":             total_a00,
        "vat_pln":              total_b00,
        "total_cif_usd":        total_invoiced,
        "agent":                "",
        "invoice_refs":         invoice_refs,
        "invoice_refs_method":  "xml_goods_items",
        "inferred_refs":        [],
        "transport_refs":       transport_refs,
        "importer_name":        "",
        "importer_nip":         xml_dict.get("importer_nip", ""),
        "exporter_name":        xml_dict.get("exporter", ""),
        "customs_rate_usd":     customs_rate,
        "sad_qty_by_type":      sad_qty_by_type,
        "a00_payment_method":   a00_method,
        "b00_payment_method":   b00_method,
        "statistical_value_pln": total_stat,
        "goods_description":    "; ".join(descriptions),
        "cn_code":              ", ".join(cn_codes),
        "sad_invoice_value_usd": total_invoiced,
        "sad_additions_pln":    0.0,
    }

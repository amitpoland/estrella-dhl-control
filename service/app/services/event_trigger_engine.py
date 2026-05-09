"""
event_trigger_engine.py — Pure routing of detected email/tracking events to
the right downstream service.

This module knows nothing about how an event was discovered (worker, monitor,
or push). It only takes a normalised event + already-downloaded attachment
paths and dispatches to the correct importer / SLA action.

All operations are idempotent — replays are safe. The caller is expected to
de-dupe at the message-id level via `audit.email_ingestion.processed_message_ids`.

Public API:
    route_email(audit_path, email_record, attachment_paths) -> dict
    handle_tracking_event(audit_path, tracking_event) -> dict
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.io import write_json_atomic
from .customs_doc_classifier  import classify
from .agency_sad_monitor      import register_agency_documents
from .sad_importer            import import_customs_docs
from .service_invoice_monitor import register_service_invoices, classify_vendor
from .agency_sla_engine       import stop_agency_sla

log = logging.getLogger(__name__)


_CUSTOMS_TYPES = {"customs_pdf", "customs_xml", "customs_html"}
_INVOICE_TYPES = {"invoice"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_audit(audit_path: Path) -> Dict[str, Any]:
    return json.loads(Path(audit_path).read_text(encoding="utf-8"))


def _batch_id(audit: Dict[str, Any], audit_path: Path) -> str:
    return str(audit.get("batch_id") or Path(audit_path).parent.name)


def route_email(
    audit_path: str | Path,
    email_record: Dict[str, Any],
    attachment_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Dispatch a single matched email to the right downstream handler.

    Args:
        audit_path:       Path to the shipment audit.json
        email_record:     Output of match_email_to_shipment (subject, from,
                          message_id, sender_role, detected_type, attachments[])
        attachment_paths: Already-downloaded attachment file paths (optional).
                          When empty, only event-detection metadata is recorded.

    Returns:
        Summary dict with `actions` list.
    """
    p = Path(audit_path)
    if not p.exists():
        return {"ok": False, "error": f"audit not found: {p}"}

    audit = _read_audit(p)
    batch_id   = _batch_id(audit, p)
    msg_id     = str(email_record.get("message_id") or "")
    sender     = (email_record.get("from") or "").lower()
    role       = email_record.get("sender_role") or ""
    detected   = email_record.get("detected_type") or ""
    att_metas  = email_record.get("attachments") or []
    paths      = list(attachment_paths or [])

    # ── Idempotency: skip already-processed messages ─────────────────────────
    ingest = audit.get("email_ingestion") or {}
    processed = set(ingest.get("processed_message_ids") or [])
    if msg_id and msg_id in processed:
        return {"ok": True, "skipped": "already_processed", "message_id": msg_id}

    # ── Bucket attachments by classified type (filename-only) ────────────────
    customs_paths:  List[str] = []
    invoice_paths:  List[str] = []
    other_paths:    List[str] = []

    def _classify_path(pth: str) -> str:
        return classify(Path(pth).name).get("type", "other")

    for ap in paths:
        t      = _classify_path(ap)
        vendor = classify_vendor(Path(ap).name)
        if t in _CUSTOMS_TYPES:
            customs_paths.append(ap)
        elif vendor in {"DHL", "Ganther", "ACS"}:
            invoice_paths.append(ap)
        else:
            other_paths.append(ap)

    actions: List[Dict[str, Any]] = []

    # ── 0. DHL WAW agency ZC429 completion email ────────────────────────────
    # Wins over the generic customs branch so a single email never gets
    # imported twice (once via dhl_zc429_intake, once via import_customs_docs).
    # Idempotency lives in intake_lineage; re-delivery is safe.
    if (email_record.get("detected_type") == "zc429_completion"
            or email_record.get("type") == "zc429_completion"):
        try:
            from .zc429_email_dispatcher import maybe_dispatch_zc429
            dispatch = maybe_dispatch_zc429(p, email_record, paths)
        except Exception as exc:
            log.exception("[trigger] zc429 dispatcher raised")
            dispatch = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if dispatch is not None:
            actions.append({
                "action":           "dhl_zc429_intake",
                "ok":               bool(dispatch.get("ok")),
                "intake_event_id":  dispatch.get("intake_event_id", ""),
                "duplicate":        bool(dispatch.get("duplicate")),
                "attachment_count": int(dispatch.get("attachment_count") or 0),
                "reason":           dispatch.get("reason", ""),
            })
            # Record processed and short-circuit BEFORE the generic
            # customs branch so we never double-import.
            if msg_id:
                audit_p = _read_audit(p)
                ing = audit_p.setdefault("email_ingestion", {})
                pmids = ing.setdefault("processed_message_ids", [])
                if msg_id not in pmids:
                    pmids.append(msg_id)
                    write_json_atomic(p, audit_p)
            return {"ok": True, "actions": actions, "message_id": msg_id,
                    "branch": "zc429_completion"}

    # ── 1. Agency reply with documents ──────────────────────────────────────
    if role == "agency" and (customs_paths or other_paths):
        files_for_agency = customs_paths + other_paths
        res = register_agency_documents(batch_id, files_for_agency, source="email_ingestion")
        actions.append({"action": "register_agency_documents",
                        "ok": res.get("ok"), "files": len(files_for_agency)})
        # Stop SLA immediately when agency docs detected via ingestion
        try:
            audit2 = _read_audit(p)
            stop_agency_sla(audit2, reason="agency_documents_detected_via_ingestion")
            write_json_atomic(p, audit2)
            actions.append({"action": "stop_agency_sla", "ok": True})
        except Exception as exc:
            log.warning("[trigger] stop_agency_sla failed: %s", exc)

    # ── 2. Customs SAD/PZC documents from any sender ─────────────────────────
    elif customs_paths:
        res = import_customs_docs(batch_id, customs_paths, source="email_ingestion",
                                   auto_trigger_pz=True)
        actions.append({"action": "import_customs_docs",
                        "ok": res.get("ok"), "files": len(customs_paths)})

    # ── 3. Service invoices (DHL / agency invoices) ──────────────────────────
    if invoice_paths:
        res = register_service_invoices(batch_id, invoice_paths, source="email_ingestion")
        actions.append({"action": "register_service_invoices",
                        "ok": res.get("ok"), "files": len(invoice_paths),
                        "dhl": res.get("dhl_invoice_received"),
                        "agency": res.get("agency_invoice_received")})

    # ── 4. DHL customs request (no auto-action; just flag for monitor) ───────
    if role == "dhl" and detected in ("translation", "broker_notification", "carrier_status"):
        audit3 = _read_audit(p)
        flags = audit3.get("dhl_inbox_flags") or {}
        flags[detected] = {
            "message_id":  msg_id,
            "received_at": email_record.get("received_at"),
            "subject":     email_record.get("subject"),
        }
        audit3["dhl_inbox_flags"] = flags
        write_json_atomic(p, audit3)
        actions.append({"action": "flag_dhl_event", "type": detected})

    # ── 5. DHL email with attachments → classify → validate → register ──────
    if role == "dhl" and paths:
        try:
            from .dhl_document_classifier import classify_dhl_email_documents
            from .dhl_document_validator  import validate_dhl_document_set
            from . import shipment_folder_manager as fm

            audit_cls = _read_audit(p)
            classification = classify_dhl_email_documents(email_record, paths, audit_cls)

            if classification.get("classified_files"):
                validation = validate_dhl_document_set(classification, audit_cls)

                if validation["valid"]:
                    # Store validated docs in shipment folder (04_dhl_docs)
                    stored_files = []
                    for cf in validation["validated_files"]:
                        fpath = cf.get("file_path", "")
                        if fpath:
                            saved = fm.save_file(batch_id, fpath, "dhl_doc")
                            stored_files.append({
                                "path":     str(saved),
                                "type":     cf.get("dhl_type", ""),
                                "filename": Path(fpath).name,
                            })

                    # Register in audit.dhl_documents_received
                    audit_reg = _read_audit(p)
                    audit_reg["dhl_documents_received"] = {
                        "received":         True,
                        "validated":        True,
                        "classification":   {
                            "document_types":  classification["document_types"],
                            "awb_match":       classification["awb_match"],
                            "ticket_match":    classification["ticket_match"],
                            "cif_match":       classification["cif_match"],
                            "mrn_detected":    classification.get("mrn_detected"),
                            "invoice_matches": classification["invoice_matches"],
                            "confidence":      classification["confidence"],
                        },
                        "files":            stored_files,
                        "source_email_id":  msg_id,
                        "received_at":      _now_iso(),
                        "complete_for_agency_forward": classification["complete_for_agency_forward"],
                    }
                    write_json_atomic(p, audit_reg)

                    actions.append({
                        "action":     "dhl_docs_classified_and_registered",
                        "ok":         True,
                        "doc_count":  len(stored_files),
                        "types":      classification["document_types"],
                        "complete":   classification["complete_for_agency_forward"],
                    })

                    # If PZC/SAD/ZC429 present → also trigger customs importer
                    if classification.get("has_customs_docs"):
                        customs_files = [cf["file_path"] for cf in validation["validated_files"]
                                         if cf.get("dhl_type") in ("SAD_DOCUMENT", "PZC_DOCUMENT", "ZC429_DOCUMENT")
                                         and cf.get("file_path")]
                        if customs_files:
                            res = import_customs_docs(batch_id, customs_files,
                                                       source="dhl_email_ingestion",
                                                       auto_trigger_pz=True)
                            actions.append({"action": "import_customs_docs",
                                            "ok": res.get("ok"),
                                            "files": len(customs_files),
                                            "source": "dhl_document_classifier"})
                else:
                    # Validation failed — store risk flags but don't auto-forward
                    audit_fail = _read_audit(p)
                    rf = audit_fail.get("risk_flags") or []
                    rf.append("dhl_document_validation_failed")
                    audit_fail["risk_flags"] = rf
                    audit_fail["dhl_documents_received"] = {
                        "received":    True,
                        "validated":   False,
                        "errors":      validation["errors"],
                        "warnings":    validation["warnings"],
                        "source_email_id": msg_id,
                        "received_at": _now_iso(),
                    }
                    write_json_atomic(p, audit_fail)
                    actions.append({
                        "action":  "dhl_docs_validation_failed",
                        "ok":      False,
                        "errors":  validation["errors"],
                        "warnings": validation["warnings"],
                    })
        except Exception as exc:
            log.warning("[trigger] DHL document classification failed: %s", exc)
            actions.append({"action": "dhl_docs_classification_error",
                            "ok": False, "error": str(exc)})

    # ── Persist ingestion bookkeeping ───────────────────────────────────────
    audit_final = _read_audit(p)
    ing = audit_final.get("email_ingestion") or {
        "last_scan_at": None, "emails_processed": 0,
        "attachments_extracted": 0, "events_detected": 0,
        "processed_message_ids": [],
    }
    if msg_id and msg_id not in ing.get("processed_message_ids", []):
        ing.setdefault("processed_message_ids", []).append(msg_id)
        ing["emails_processed"] = int(ing.get("emails_processed", 0)) + 1
    ing["attachments_extracted"] = int(ing.get("attachments_extracted", 0)) + len(paths)
    ing["events_detected"]       = int(ing.get("events_detected", 0)) + len(actions)
    ing["last_event_at"]         = _now_iso()
    audit_final["email_ingestion"] = ing
    write_json_atomic(p, audit_final)

    return {"ok": True, "batch_id": batch_id, "message_id": msg_id,
            "actions": actions, "attachment_count": len(paths)}


def handle_tracking_event(
    audit_path: str | Path,
    tracking_event: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Inspect a tracking event. If it indicates a customs-status change,
    flag the audit so the next ingestion sweep prioritises this AWB.

    Returns: {ok, immediate_scan: bool, reason: str | None}
    """
    p = Path(audit_path)
    if not p.exists():
        return {"ok": False, "error": f"audit not found: {p}"}

    desc = (tracking_event.get("description")
            or tracking_event.get("status")
            or "").lower()
    if not desc:
        return {"ok": True, "immediate_scan": False, "reason": "no_description"}

    needs_scan = any(kw in desc for kw in (
        "customs clearance status updated",
        "clearance event",
        "customs released",
        "agency",
    ))

    if not needs_scan:
        return {"ok": True, "immediate_scan": False}

    audit = _read_audit(p)
    flags = audit.get("ingestion_priority") or {}
    flags["requested_at"] = _now_iso()
    flags["reason"]       = desc[:120]
    audit["ingestion_priority"] = flags
    write_json_atomic(p, audit)
    return {"ok": True, "immediate_scan": True, "reason": desc[:120]}


def run_for_audit(audit_path: str | Path,
                   email_records: List[Dict[str, Any]],
                   attachment_lookup: Optional[Dict[str, List[str]]] = None,
                   ) -> Dict[str, Any]:
    """
    Convenience: route a list of email records (e.g. from one ingestion cycle)
    against one shipment audit.

    attachment_lookup maps message_id → [downloaded_path, ...].
    """
    attachment_lookup = attachment_lookup or {}
    summaries: List[Dict[str, Any]] = []
    for rec in email_records:
        msg_id = str(rec.get("message_id") or "")
        paths  = attachment_lookup.get(msg_id, [])
        summaries.append(route_email(audit_path, rec, paths))
    return {"ok": True, "count": len(summaries), "summaries": summaries}

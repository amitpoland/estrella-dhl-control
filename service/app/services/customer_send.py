"""
Customer Send — document eligibility + options projection (NO second registry).

Authority:
  * Availability facts → ``shipment_document_manifest.build_manifest``
  * Reply state       → ``delivery_confirmation_db.get_delivery_summary_for_draft``
  * Packing List bytes → ``commercial_packing_list.export_packing_list_pdf_for_draft``
    (SAME export Documents Hub / packing-list.pdf uses — no duplicate renderer)
  * Air Waybill bytes → carrier waybill/label store (manifest-backed)
  * Queue/send        → ``email_service`` / ``email_sender`` (callers only)

Customer-sendable types are an explicit fail-closed whitelist. CMR is NOT in
this whitelist — it attaches only via delivery_confirmation when available.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .shipment_document_manifest import GENERATED, build_manifest

log = logging.getLogger(__name__)

# Deterministic attachment order for multi-document customer sends.
# CMR is intentionally absent — confirmation workflow owns CMR attachment.
CUSTOMER_SENDABLE_DOCUMENT_TYPES: Tuple[str, ...] = (
    "official_proforma",
    "invoice",
    "packing_list",
    "air_waybill",
)

CUSTOMER_SENDABLE_LABELS: Dict[str, str] = {
    "official_proforma": "Proforma",
    "invoice": "Invoice",
    "packing_list": "Packing List",
    "air_waybill": "Air Waybill",
}

_CUSTOMER_SENDABLE_SET = frozenset(CUSTOMER_SENDABLE_DOCUMENT_TYPES)

# Manifest may still label the carrier document ``dhl_waybill``; customer Send
# projects it as ``air_waybill`` (provider-neutral).
_AIR_WAYBILL_MANIFEST_TYPES = ("air_waybill", "dhl_waybill")


def is_customer_sendable_document(entry: Optional[Dict[str, Any]]) -> bool:
    """True when a manifest entry is an allowed, currently available customer doc.

    Fail closed: missing entry, unknown type, non-Generated status, or no
    download/byte authority → False.
    """
    if not isinstance(entry, dict):
        return False
    doc_type = (entry.get("document_type") or "").strip()
    # Provider-internal names (dhl_waybill) are never customer-facing types.
    # Air Waybill availability is projected via _resolve_air_waybill_entry.
    if doc_type not in _CUSTOMER_SENDABLE_SET:
        return False
    if (entry.get("status") or "") != GENERATED:
        return False
    if not entry.get("download_available"):
        return False
    if not (entry.get("download_url") or "").strip():
        return False
    return True


def _iter_manifest_docs(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = (manifest or {}).get("groups") or {}
    out: List[Dict[str, Any]] = []
    for key in ("commercial", "transport", "carrier"):
        for entry in groups.get(key) or []:
            if isinstance(entry, dict):
                out.append(entry)
    return out


def _entry_by_type(manifest: Dict[str, Any], document_type: str) -> Optional[Dict[str, Any]]:
    wanted = {document_type}
    if document_type == "air_waybill":
        wanted.update(_AIR_WAYBILL_MANIFEST_TYPES)
    for entry in _iter_manifest_docs(manifest):
        if (entry.get("document_type") or "") in wanted:
            return entry
    return None


def _resolve_air_waybill_entry(manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Customer-facing Air Waybill projection over carrier document store.

    Prefer real waybillDoc (``dhl_waybill``). For FEDEX/UPS external bookings the
    uploaded AWB PDF lives in the label store — use that only when waybill is absent.
    """
    waybill = None
    label = None
    for entry in _iter_manifest_docs(manifest):
        dt = (entry.get("document_type") or "")
        if dt in _AIR_WAYBILL_MANIFEST_TYPES:
            waybill = entry
        elif dt == "dhl_label":
            label = entry
    if waybill and (waybill.get("status") or "") == GENERATED and waybill.get("download_available"):
        return {**waybill, "document_type": "air_waybill", "_store_kind": "waybill-doc"}
    if label and (label.get("status") or "") == GENERATED and label.get("download_available"):
        source = (label.get("source") or "").strip().upper()
        # Promote label→Air Waybill for external carrier uploads (not DHL default).
        if source in ("FEDEX", "UPS", "EXTERNAL") or source.startswith("FEDEX") or source.startswith("UPS"):
            return {**label, "document_type": "air_waybill", "_store_kind": "label"}
    return None


def normalize_document_types(requested: Optional[Sequence[Any]]) -> List[str]:
    """Dedupe preserving canonical order; drop empties. Does not authorize."""
    if not requested:
        return []
    seen = set()
    ordered: List[str] = []
    raw = [(str(x or "").strip()) for x in requested if str(x or "").strip()]
    raw = ["air_waybill" if t == "dhl_waybill" else t for t in raw]
    for canon in CUSTOMER_SENDABLE_DOCUMENT_TYPES:
        if canon in raw and canon not in seen:
            ordered.append(canon)
            seen.add(canon)
    for t in raw:
        if t not in seen:
            ordered.append(t)
            seen.add(t)
    return ordered


def _doc_reason_unavailable(doc_type: str, entry: Optional[Dict[str, Any]]) -> str:
    if entry and (entry.get("reason") or "").strip():
        return str(entry.get("reason")).strip()
    if doc_type == "invoice":
        return "Convert the Proforma to an Invoice first."
    if doc_type == "air_waybill":
        return "Air Waybill PDF is not on file yet."
    if doc_type == "packing_list":
        return "Packing List is not available (no commercial lines)."
    if doc_type == "official_proforma":
        return "Official Proforma PDF is not available yet."
    return f"Document '{doc_type}' is not available for customer send."


def project_customer_send_options(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Dict[str, Any]:
    """Read-only Send-options projection for the Proforma Send UI.

    No filesystem paths. Eligibility is computed here; React must not re-decide.
    """
    from . import delivery_confirmation_db as dcdb
    from . import commercial_cmr as ccmr

    manifest = build_manifest(
        int(draft_id),
        storage_root=Path(storage_root),
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    delivery = dcdb.get_delivery_summary_for_draft(
        Path(storage_root) / "delivery_confirmations.db", int(draft_id),
    )
    awaiting = bool(delivery and delivery.get("operator_status") == "awaiting_customer")

    documents: List[Dict[str, Any]] = []
    any_doc_available = False
    for doc_type in CUSTOMER_SENDABLE_DOCUMENT_TYPES:
        if doc_type == "air_waybill":
            entry = _resolve_air_waybill_entry(manifest)
            available = bool(
                entry
                and (entry.get("status") or "") == GENERATED
                and entry.get("download_available")
                and (entry.get("download_url") or "").strip()
            )
        else:
            entry = _entry_by_type(manifest, doc_type)
            available = is_customer_sendable_document(entry)
        if available:
            any_doc_available = True
        documents.append({
            "type": doc_type,
            "label": CUSTOMER_SENDABLE_LABELS[doc_type],
            "available": available,
            "reason": None if available else _doc_reason_unavailable(doc_type, entry),
            "status": (entry or {}).get("status"),
            "reference": (entry or {}).get("reference"),
            "source": (entry or {}).get("source"),
        })

    notif_status = (delivery or {}).get("notification_status") if delivery else None
    op_status = (delivery or {}).get("operator_status") if delivery else None
    send_confirmation = False
    confirmation_reason = "No delivery-confirmation record for this draft."
    if delivery is None:
        # First-time confirmation only when outbound AWB is proven delivered.
        try:
            from .carrier.persistence import shipment_db
            from . import proforma_invoice_link_db as pildb
            from . import delivery_confirmation_service as dcs
            from .shipment_document_manifest import _batch_client_count

            draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
            awb_probe = ""
            if draft is not None:
                batch_id = (draft.batch_id or "").strip()
                client_name = (draft.client_name or "").strip() or None
                single_client = _batch_client_count(Path(proforma_db), batch_id) <= 1
                row = shipment_db.get_shipment_for_draft(
                    Path(carrier_db),
                    batch_id,
                    client_name,
                    allow_single_client_fallback=single_client,
                )
                if row:
                    awb_probe = (row.get("tracking_ref") or "").strip()
            if awb_probe and dcs._prove_outbound_delivered(awb_probe).get("ok"):
                send_confirmation = True
                confirmation_reason = None
                op_status = op_status or "delivered"
            else:
                confirmation_reason = (
                    "Delivery Confirmation becomes available after the shipment is delivered."
                )
        except Exception as exc:
            log.debug("confirmation eligibility probe failed: %s", exc)
            confirmation_reason = (
                "Delivery Confirmation becomes available after the shipment is delivered."
            )
    elif op_status in ("confirmed_good", "issue_reported"):
        confirmation_reason = f"Customer already responded ({op_status})."
    elif awaiting:
        confirmation_reason = "Already awaiting customer — use reminder."
    elif notif_status == "failed":
        send_confirmation = True
        confirmation_reason = None
    else:
        confirmation_reason = "Confirmation already in progress or not operator-sendable."

    cmr_available = False
    try:
        cmr_available = bool(ccmr.cmr_available_for_draft(
            draft_id=int(draft_id),
            storage_root=Path(storage_root),
            proforma_db=Path(proforma_db),
            carrier_db=Path(carrier_db),
        ))
    except Exception as exc:
        log.debug("cmr availability probe failed: %s", exc)

    return {
        "draft_id": int(draft_id),
        "documents": documents,
        "actions": {
            "send_documents": any_doc_available,
            "send_confirmation": send_confirmation,
            "send_reminder": awaiting,
        },
        "awaiting_customer": awaiting,
        "delivery": {
            "operator_status": op_status,
            "notification_status": notif_status,
            "awb": (delivery or {}).get("awb") if delivery else None,
            "customer_name": (delivery or {}).get("customer_name") if delivery else None,
        } if delivery else None,
        "confirmation_reason": confirmation_reason,
        "cmr_will_attach": bool(send_confirmation and cmr_available),
        "cmr_available": cmr_available,
    }


def assert_types_customer_sendable(
    manifest: Dict[str, Any],
    document_types: Sequence[str],
) -> List[str]:
    """Re-validate selections against a fresh manifest. Raises ValueError."""
    normalized = normalize_document_types(document_types)
    if not normalized:
        raise ValueError("No document types selected.")
    allowed: List[str] = []
    for doc_type in normalized:
        if doc_type not in _CUSTOMER_SENDABLE_SET:
            raise ValueError(
                f"Document type '{doc_type}' is not customer-sendable "
                "(fail closed)."
            )
        if doc_type == "air_waybill":
            entry = _resolve_air_waybill_entry(manifest)
            ok = bool(
                entry
                and (entry.get("status") or "") == GENERATED
                and entry.get("download_available")
                and (entry.get("download_url") or "").strip()
            )
        else:
            entry = _entry_by_type(manifest, doc_type)
            ok = is_customer_sendable_document(entry)
        if not ok:
            reason = _doc_reason_unavailable(doc_type, entry)
            raise ValueError(
                f"Document type '{doc_type}' is not available for send: {reason}"
            )
        allowed.append(doc_type)
    return allowed


def render_packing_list_pdf_bytes(draft: Any, storage_root: Path) -> Tuple[bytes, str]:
    """Thin delegate — ONE commercial packing export (Documents Hub + email)."""
    from .commercial_packing_list import export_packing_list_pdf_for_draft

    pdf, fname, _document = export_packing_list_pdf_for_draft(
        draft=draft,
        storage_root=Path(storage_root),
    )
    return pdf, fname


def _materialize_air_waybill_bytes(
    *,
    draft: Any,
    manifest: Dict[str, Any],
) -> Tuple[bytes, str]:
    """Read carrier-stored Air Waybill bytes (never invent)."""
    from ..api.routes_carrier_actions import _shipment_doc_file

    batch_id = (getattr(draft, "batch_id", None) or "").strip()
    entry = _resolve_air_waybill_entry(manifest)
    if not entry:
        raise ValueError("Air Waybill PDF is not on file.")
    awb = (entry.get("reference") or "").strip()
    kind = entry.get("_store_kind") or "waybill-doc"
    if not batch_id or not awb:
        raise ValueError("Air Waybill PDF is not on file.")
    path = _shipment_doc_file(kind, batch_id, awb)
    if path is None or not path.is_file():
        raise ValueError("Air Waybill PDF is not on file.")
    data = path.read_bytes()
    if not data or not data.startswith(b"%PDF"):
        raise ValueError("Air Waybill file is not a valid PDF.")
    safe_awb = "".join(c if (c.isalnum() or c in "-_") else "_" for c in awb)
    return data, f"air-waybill-{safe_awb}.pdf"


def materialize_customer_attachments(
    *,
    draft: Any,
    document_types: Sequence[str],
    storage_root: Path,
    manifest: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Fetch/render PDFs into storage_root temp files for queue_email.

    Returns ``[{"label": filename, "path": abs_path}, ...]`` in canonical order.
    Does not accept caller-supplied paths.
    """
    from . import wfirma_client as wfc

    storage_root = Path(storage_root)
    out_dir = storage_root / "proforma_email_pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_id = int(getattr(draft, "id"))
    attachments: List[Dict[str, str]] = []
    written: List[Path] = []

    def _write(filename: str, data: bytes) -> Dict[str, str]:
        safe_fn = "".join(
            c if (c.isalnum() or c in "._-") else "_" for c in filename
        )
        safe_fn = f"{draft_id}_{safe_fn}"
        path = out_dir / safe_fn
        path.write_bytes(data)
        written.append(path)
        return {"label": safe_fn, "path": str(path)}

    try:
        for doc_type in document_types:
            if doc_type == "official_proforma":
                wfirma_id = (getattr(draft, "wfirma_proforma_id", None) or "").strip()
                if not wfirma_id:
                    raise ValueError("No wFirma proforma id for official_proforma.")
                pdf = wfc.fetch_invoice_pdf(wfirma_id)
                if not pdf or len(pdf) < 10:
                    raise ValueError("wFirma returned empty proforma PDF.")
                doc_no = (
                    getattr(draft, "wfirma_proforma_fullnumber", None)
                    or f"Draft-{draft_id}"
                )
                fname = f"proforma-{str(doc_no).replace('/', '-').replace(' ', '_')}.pdf"
                attachments.append(_write(fname, pdf))
            elif doc_type == "invoice":
                inv_id = (getattr(draft, "wfirma_invoice_id", None) or "").strip()
                if not inv_id:
                    raise ValueError("No wFirma invoice id for invoice.")
                pdf = wfc.fetch_invoice_pdf(inv_id)
                if not pdf or len(pdf) < 10:
                    raise ValueError("wFirma returned empty invoice PDF.")
                inv_ref = (
                    getattr(draft, "wfirma_invoice_number", None)
                    or inv_id
                )
                fname = f"invoice-{str(inv_ref).replace('/', '-').replace(' ', '_')}.pdf"
                attachments.append(_write(fname, pdf))
            elif doc_type == "packing_list":
                pdf, fname = render_packing_list_pdf_bytes(draft, storage_root)
                attachments.append(_write(fname, pdf))
            elif doc_type == "air_waybill":
                if manifest is None:
                    raise ValueError("Air Waybill requires a fresh manifest.")
                pdf, fname = _materialize_air_waybill_bytes(
                    draft=draft, manifest=manifest,
                )
                attachments.append(_write(fname, pdf))
            else:
                raise ValueError(
                    f"Document type '{doc_type}' is not customer-sendable "
                    "(fail closed)."
                )
    except Exception:
        for p in written:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return attachments


def customer_documents_email_bodies(
    draft: Any,
    document_types: Sequence[str],
) -> Tuple[str, str]:
    """(subject, html_body) for a customer document send."""
    from html import escape as esc

    labels = [CUSTOMER_SENDABLE_LABELS.get(t, t) for t in document_types]
    joined = ", ".join(labels)
    client = esc(getattr(draft, "client_name", None) or "Customer")
    doc_no = esc(
        getattr(draft, "wfirma_proforma_fullnumber", None)
        or f"Draft #{getattr(draft, 'id', '')}"
    )
    draft_label = (
        getattr(draft, "wfirma_proforma_fullnumber", None)
        or f"Draft #{getattr(draft, 'id', '')}"
    )
    if list(document_types) == ["official_proforma"]:
        subject = f"Proforma {draft_label}"
        html = (
            f"<p>Dear {client},</p>"
            f"<p>Please find attached the proforma invoice: <strong>{doc_no}</strong>.</p>"
            "<p>If you have any questions, please do not hesitate to contact us.</p>"
            "<p>Best regards,<br>Estrella Jewels</p>"
        )
        return subject, html
    subject = f"Documents for {draft_label}: {joined}"
    items = "".join(f"<li>{esc(x)}</li>" for x in labels)
    html = (
        f"<p>Dear {client},</p>"
        f"<p>Please find attached the following document(s) for "
        f"<strong>{doc_no}</strong>:</p>"
        f"<ul>{items}</ul>"
        "<p>If you have any questions, please do not hesitate to contact us.</p>"
        "<p>Best regards,<br>Estrella Jewels</p>"
    )
    return subject, html

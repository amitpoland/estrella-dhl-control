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
    "shipping_information",
)

CUSTOMER_SENDABLE_LABELS: Dict[str, str] = {
    "official_proforma": "Proforma",
    "invoice": "Invoice",
    "packing_list": "Packing List",
    "air_waybill": "Air Waybill",
    "shipping_information": "Shipping Information",
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

    Prefer dedicated waybillDoc (``dhl_waybill``). When absent, the Transport Label
    (``dhl_label``) is the customer-safe Air Waybill for DHL modern bookings —
    MyDHL often embeds the courier Waybill Doc page inside the label PDF (PROF 179
    evidence). FEDEX/UPS external uploads also live in the label store.
    Never promotes Shipment Receipt (billing/account data).
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
    if doc_type == "shipping_information":
        return "Shipping Information is available after an outbound AWB is booked."
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
    from . import commercial_cmr as ccmr
    from . import commercial_shipping_information as csi
    from . import delivery_followup as dfu

    manifest = build_manifest(
        int(draft_id),
        storage_root=Path(storage_root),
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    followup = dfu.compose_delivery_followup(
        draft_id=int(draft_id),
        storage_root=Path(storage_root),
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    carrier = followup.get("carrier") or {}
    confirmation = followup.get("confirmation") or {}

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
            reference = (entry or {}).get("reference") or carrier.get("awb")
            source = (entry or {}).get("source") or carrier.get("provider")
        elif doc_type == "shipping_information":
            entry = None
            available = False
            try:
                available = bool(csi.shipping_information_available_for_draft(
                    draft_id=int(draft_id),
                    storage_root=Path(storage_root),
                    proforma_db=Path(proforma_db),
                    carrier_db=Path(carrier_db),
                ))
            except Exception as exc:
                log.debug("shipping information availability failed: %s", exc)
            reference = carrier.get("awb")
            source = carrier.get("provider")
            entry = {
                "status": GENERATED if available else None,
                "reference": reference,
                "source": source,
            }
        else:
            entry = _entry_by_type(manifest, doc_type)
            available = is_customer_sendable_document(entry)
            reference = (entry or {}).get("reference")
            source = (entry or {}).get("source")
        if available:
            any_doc_available = True
        documents.append({
            "type": doc_type,
            "label": CUSTOMER_SENDABLE_LABELS[doc_type],
            "available": available,
            "reason": None if available else _doc_reason_unavailable(doc_type, entry),
            "status": (entry or {}).get("status"),
            "reference": reference,
            "source": source,
        })

    send_confirmation = bool(confirmation.get("can_send"))
    awaiting = bool(confirmation.get("can_remind")) or (
        (confirmation.get("state") or "") == "awaiting_customer"
    )

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
            "send_reminder": bool(confirmation.get("can_remind")),
        },
        "awaiting_customer": awaiting,
        "delivery_followup": followup,
        # Back-compat projection for older UI readers.
        "delivery": {
            "operator_status": confirmation.get("operator_status")
            or (
                "delivered"
                if carrier.get("delivered") and confirmation.get("state") == "not_sent"
                else confirmation.get("state")
            ),
            "notification_status": confirmation.get("notification_status"),
            "awb": carrier.get("awb"),
            "customer_name": confirmation.get("customer_name"),
            "carrier_status": carrier.get("status"),
            "delivered": carrier.get("delivered"),
            "delivered_at": carrier.get("delivered_at"),
            "location": carrier.get("location"),
            "provider": carrier.get("provider"),
        },
        "confirmation_reason": confirmation.get("reason"),
        "cmr_will_attach": bool(send_confirmation and cmr_available),
        "cmr_available": cmr_available,
        "recipients": _project_send_recipients(draft_id=int(draft_id), proforma_db=Path(proforma_db)),
    }


def _project_send_recipients(*, draft_id: int, proforma_db: Path) -> Dict[str, Any]:
    """Resolve Customer Master communication recipients for Send UI (read-only)."""
    empty = {"to": [], "cc": [], "source": "none", "primary": None, "contractor_id": None}
    try:
        from . import customer_communication_recipients as ccr
        from . import proforma_invoice_link_db as pildb
        from ..core.config import settings

        draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
        if draft is None:
            return empty
        cid = (getattr(draft, "client_contractor_id", None) or "").strip()
        if not cid:
            return empty
        db_path = Path(settings.storage_root) / "customer_master.sqlite"
        return ccr.resolve_customer_communication_recipients(
            db_path=db_path, contractor_id=cid,
        )
    except Exception as exc:
        log.debug("send recipients projection failed: %s", exc)
        return empty


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
        elif doc_type == "shipping_information":
            # Available when an outbound AWB is bound on the carrier manifest.
            entry = None
            ok = False
            for e in _iter_manifest_docs(manifest):
                if (e.get("document_type") or "") in (
                    "dhl_label", "dhl_waybill", "air_waybill",
                ) and (e.get("reference") or "").strip():
                    ok = True
                    entry = e
                    break
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
            elif doc_type == "shipping_information":
                from . import commercial_shipping_information as csi
                from ..core.config import settings
                exported = csi.export_shipping_information_pdf_for_draft(
                    draft_id=draft_id,
                    storage_root=storage_root,
                    proforma_db=Path(settings.storage_root) / "proforma_links.db",
                    carrier_db=Path(
                        settings.carrier_storage_root
                        or (Path(settings.storage_root) / "carrier")
                    ) / "carrier_shipments.db",
                )
                if not exported:
                    raise ValueError("Shipping Information is not available.")
                pdf, fname = exported
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
    """(subject, html_body) for a customer document send.

    Semantics only here — brand HTML lives in ``customer_email_template``.
    """
    from .customer_email_template import customer_documents_email

    labels = [CUSTOMER_SENDABLE_LABELS.get(t, t) for t in document_types]
    draft_label = (
        getattr(draft, "wfirma_proforma_fullnumber", None)
        or f"Draft #{getattr(draft, 'id', '')}"
    )
    client = getattr(draft, "client_name", None) or "Customer"
    if list(document_types) == ["official_proforma"]:
        subject = f"Proforma {draft_label}"
    else:
        subject = f"Documents for {draft_label}: {', '.join(labels)}"
    _html, _text = customer_documents_email(
        customer_name=str(client),
        doc_ref=str(draft_label),
        document_labels=labels,
    )
    # Route historically returned (subject, html); plain text is built by
    # email_service from html when body_text omitted — keep subject + branded html.
    return subject, _html

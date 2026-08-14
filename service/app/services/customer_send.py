"""
Customer Send — document eligibility + options projection (NO second registry).

Authority:
  * Availability facts → ``shipment_document_manifest.build_manifest``
  * Reply state       → ``delivery_confirmation_db.get_delivery_summary_for_draft``
  * Bytes             → existing wFirma / ``doc_package`` packing-list authorities
  * Queue/send        → ``email_service`` / ``email_sender`` (callers only)

Customer-sendable types are an explicit fail-closed whitelist. Unknown and
internal/customs/carrier types are never eligible.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .shipment_document_manifest import GENERATED, build_manifest

log = logging.getLogger(__name__)

# Deterministic attachment order for multi-document customer sends.
CUSTOMER_SENDABLE_DOCUMENT_TYPES: Tuple[str, ...] = (
    "official_proforma",
    "invoice",
    "packing_list",
)

CUSTOMER_SENDABLE_LABELS: Dict[str, str] = {
    "official_proforma": "Proforma",
    "invoice": "Invoice",
    "packing_list": "Packing List",
}

_CUSTOMER_SENDABLE_SET = frozenset(CUSTOMER_SENDABLE_DOCUMENT_TYPES)


def is_customer_sendable_document(entry: Optional[Dict[str, Any]]) -> bool:
    """True when a manifest entry is an allowed, currently available customer doc.

    Fail closed: missing entry, unknown type, non-Generated status, or no
    download/byte authority → False.
    """
    if not isinstance(entry, dict):
        return False
    doc_type = (entry.get("document_type") or "").strip()
    if doc_type not in _CUSTOMER_SENDABLE_SET:
        return False
    if (entry.get("status") or "") != GENERATED:
        return False
    # official_proforma / invoice: wFirma PDF via download_url.
    # packing_list: download_url points at packing-list.pdf authority.
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
    for entry in _iter_manifest_docs(manifest):
        if (entry.get("document_type") or "") == document_type:
            return entry
    return None


def normalize_document_types(requested: Optional[Sequence[Any]]) -> List[str]:
    """Dedupe preserving canonical order; drop empties. Does not authorize."""
    if not requested:
        return []
    seen = set()
    ordered: List[str] = []
    raw = [(str(x or "").strip()) for x in requested if str(x or "").strip()]
    for canon in CUSTOMER_SENDABLE_DOCUMENT_TYPES:
        if canon in raw and canon not in seen:
            ordered.append(canon)
            seen.add(canon)
    # Preserve rejection of unknown types for the caller (append uniques not in whitelist).
    for t in raw:
        if t not in seen:
            ordered.append(t)
            seen.add(t)
    return ordered


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
        entry = _entry_by_type(manifest, doc_type)
        available = is_customer_sendable_document(entry)
        if available:
            any_doc_available = True
        documents.append({
            "type": doc_type,
            "label": CUSTOMER_SENDABLE_LABELS[doc_type],
            "available": available,
            "reason": None if available else (
                (entry or {}).get("reason")
                or (f"Document '{doc_type}' is not available for customer send.")
            ),
            "status": (entry or {}).get("status"),
        })

    # Confirmation: only when a delivery notification row does not yet put us
    # in awaiting/confirmed/issue — i.e. operator may trigger first notify when
    # delivery_confirmation service would accept it. Reminder owns awaiting.
    notif_status = (delivery or {}).get("notification_status") if delivery else None
    op_status = (delivery or {}).get("operator_status") if delivery else None
    send_confirmation = False
    confirmation_reason = "No delivery-confirmation record for this draft."
    if delivery is None:
        send_confirmation = False
    elif op_status in ("confirmed_good", "issue_reported"):
        confirmation_reason = f"Customer already responded ({op_status})."
    elif awaiting:
        confirmation_reason = "Already awaiting customer — use reminder."
    elif notif_status == "failed":
        send_confirmation = True
        confirmation_reason = None
    else:
        # Token issued / notification present but not awaiting yet — rare.
        # Prefer reminder path only for awaiting; confirmation for failed retry.
        confirmation_reason = "Confirmation already in progress or not operator-sendable."

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
        } if delivery else None,
        "confirmation_reason": confirmation_reason,
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
        entry = _entry_by_type(manifest, doc_type)
        if not is_customer_sendable_document(entry):
            reason = (entry or {}).get("reason") or "not available"
            raise ValueError(
                f"Document type '{doc_type}' is not available for send: {reason}"
            )
        allowed.append(doc_type)
    return allowed


def render_packing_list_pdf_bytes(draft: Any, storage_root: Path) -> Tuple[bytes, str]:
    """Bytes from the ONE commercial packing-list authority (doc_package)."""
    from .carrier import doc_package

    batch_id = (getattr(draft, "batch_id", None) or "").strip()
    client_name = (getattr(draft, "client_name", None) or "").strip()
    draft_id = int(getattr(draft, "id"))
    if not batch_id:
        raise ValueError("Draft has no batch_id — cannot render packing list.")
    company = doc_package._load_company_profile(Path(storage_root))
    pdraft = doc_package._load_proforma_draft(batch_id, client_name, Path(storage_root))
    customer = doc_package._resolve_customer_from_batch(
        batch_id, client_name, Path(storage_root),
    )
    packing_pdf = doc_package.render_packing_list_pdf(
        batch_id, Path(storage_root), company, customer, pdraft or draft,
    )
    if not packing_pdf or len(packing_pdf) < 10:
        raise ValueError("Commercial Packing List has no lines to export.")
    prof_ref = (
        getattr(draft, "wfirma_proforma_fullnumber", None)
        or getattr(draft, "wfirma_proforma_id", None)
        or f"draft-{draft_id}"
    )
    safe_ref = str(prof_ref).replace("/", "-").replace("\\", "-").replace(" ", "_")
    return packing_pdf, f"packing-list-{safe_ref}.pdf"


def materialize_customer_attachments(
    *,
    draft: Any,
    document_types: Sequence[str],
    storage_root: Path,
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

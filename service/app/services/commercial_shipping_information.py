"""
commercial_shipping_information.py — customer-safe Shipping Information export.

Authority: carrier_shipments row + booking parties already shown in the AWB
Generate success summary (``awb-result-summary``). This module is the PDF/export
adapter over those facts — not a second booking calculator.

Never includes billed account / rate / internal DHL account numbers
(Shipment Receipt remains internal).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


def build_shipping_information_document(
    *,
    draft: Any,
    shipment_row: Dict[str, Any],
    company: Any = None,
    customer: Any = None,
) -> Dict[str, Any]:
    """Canonical shipping-information model (mirrors AWB result summary fields)."""
    dims = {}
    raw_dims = shipment_row.get("dimensions_json")
    if isinstance(raw_dims, str) and raw_dims.strip():
        try:
            import json
            dims = json.loads(raw_dims) or {}
        except Exception:
            dims = {}
    elif isinstance(raw_dims, dict):
        dims = raw_dims

    shipper_name = getattr(company, "legal_name", None) or "Estrella Jewels"
    customer_name = (
        getattr(customer, "bill_to_name", None)
        or getattr(draft, "client_name", None)
        or shipment_row.get("client_ref")
        or ""
    )
    return {
        "authority": "commercial_shipping_information",
        "awb": (shipment_row.get("tracking_ref") or "").strip(),
        "provider": (shipment_row.get("provider") or "DHL").strip() or "DHL",
        "batch_id": (getattr(draft, "batch_id", None) or shipment_row.get("batch_id") or "").strip(),
        "proforma": getattr(draft, "wfirma_proforma_fullnumber", None) or "",
        "customer": customer_name,
        "service_product": shipment_row.get("service_product") or "",
        "weight_kg": shipment_row.get("weight_kg"),
        "dimensions": {
            "length_cm": dims.get("length_cm"),
            "width_cm": dims.get("width_cm"),
            "height_cm": dims.get("height_cm"),
        },
        "box_type_code": shipment_row.get("box_type_code") or "",
        "declared_value": shipment_row.get("declared_value"),
        "currency": shipment_row.get("currency") or getattr(draft, "currency", None) or "",
        "shipper": shipper_name,
        "created_at": shipment_row.get("created_at"),
    }


def render_shipping_information_pdf(document: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
    body = ParagraphStyle("b", parent=styles["Normal"], fontSize=10, leading=14)
    story = [
        Paragraph("Shipping Information", title),
        Paragraph(
            "Customer-facing summary of the booked outbound shipment "
            "(same facts as the Atlas AWB Generate confirmation).",
            body,
        ),
        Spacer(1, 8),
    ]
    rows = [
        ["Air Waybill", document.get("awb") or "—"],
        ["Carrier", document.get("provider") or "—"],
        ["Proforma", document.get("proforma") or "—"],
        ["Customer", document.get("customer") or "—"],
        ["Service", document.get("service_product") or "—"],
        ["Weight", f"{document.get('weight_kg')} kg" if document.get("weight_kg") is not None else "—"],
        [
            "Dimensions",
            (
                f"{document['dimensions'].get('length_cm')}×"
                f"{document['dimensions'].get('width_cm')}×"
                f"{document['dimensions'].get('height_cm')} cm"
                if document.get("dimensions") else "—"
            ),
        ],
        ["Box type", document.get("box_type_code") or "—"],
        [
            "Declared value",
            (
                f"{document.get('declared_value')} {document.get('currency') or ''}".strip()
                if document.get("declared_value") is not None else "—"
            ),
        ],
        ["Shipper", document.get("shipper") or "—"],
        ["Booked at", document.get("created_at") or "—"],
    ]
    table = Table(rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def export_shipping_information_pdf_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Optional[Tuple[bytes, str]]:
    """Return (pdf_bytes, filename) when an outbound booking exists; else None."""
    from . import proforma_invoice_link_db as pildb
    from .carrier import doc_package
    from .carrier.persistence import shipment_db
    from .shipment_document_manifest import _batch_client_count

    draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
    if draft is None:
        return None
    batch_id = (draft.batch_id or "").strip()
    client_name = (draft.client_name or "").strip() or None
    single_client = _batch_client_count(Path(proforma_db), batch_id) <= 1
    row = shipment_db.get_shipment_for_draft(
        Path(carrier_db), batch_id, client_name,
        allow_single_client_fallback=single_client,
    )
    if not row or not (row.get("tracking_ref") or "").strip():
        return None
    company = doc_package._load_company_profile(Path(storage_root))
    customer = doc_package._resolve_customer_from_batch(
        batch_id, (draft.client_name or "").strip(), Path(storage_root),
    )
    model = build_shipping_information_document(
        draft=draft, shipment_row=dict(row), company=company, customer=customer,
    )
    pdf = render_shipping_information_pdf(model)
    if not pdf or len(pdf) < 10:
        return None
    awb = model["awb"]
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in awb)
    return pdf, f"shipping-information-{safe}.pdf"


def shipping_information_available_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> bool:
    from . import proforma_invoice_link_db as pildb
    from .carrier.persistence import shipment_db
    from .shipment_document_manifest import _batch_client_count

    draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
    if draft is None:
        return False
    batch_id = (draft.batch_id or "").strip()
    client_name = (draft.client_name or "").strip() or None
    single_client = _batch_client_count(Path(proforma_db), batch_id) <= 1
    row = shipment_db.get_shipment_for_draft(
        Path(carrier_db), batch_id, client_name,
        allow_single_client_fallback=single_client,
    )
    return bool(row and (row.get("tracking_ref") or "").strip())

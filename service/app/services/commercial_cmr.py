"""
commercial_cmr.py — ONE CMR / delivery-note document authority.

Canonical model for Logistics Preview (cmr.json), Download PDF, and Delivery
Confirmation. Presentation is solely ``commercial_cmr_html`` + Chrome print.

Do not rebuild parties/lines/carrier in React for the CMR document.

CMR is NOT a customer-send whitelist document. Attachments are used only by
delivery_confirmation when a CMR number exists for the linked outbound shipment.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ISO2_COUNTRY = {
    "PL": "Poland", "DE": "Germany", "FR": "France", "IT": "Italy",
    "ES": "Spain", "NL": "Netherlands", "BE": "Belgium", "AT": "Austria",
    "CZ": "Czech Republic", "SK": "Slovakia", "HU": "Hungary", "RO": "Romania",
    "BG": "Bulgaria", "HR": "Croatia", "SI": "Slovenia", "LT": "Lithuania",
    "LV": "Latvia", "EE": "Estonia", "SE": "Sweden", "DK": "Denmark",
    "FI": "Finland", "IE": "Ireland", "PT": "Portugal", "GR": "Greece",
    "IN": "India", "CN": "China", "US": "United States", "GB": "United Kingdom",
    "CH": "Switzerland", "NO": "Norway", "UA": "Ukraine",
    "SG": "Singapore", "AE": "United Arab Emirates", "AU": "Australia",
    "KR": "South Korea", "MU": "Mauritius", "JP": "Japan",
}

_CMR_INSURANCE_TEXT = (
    "Yes — Insurance covers the Door to Door delivery of this package by "
    "Future Generali India Insurance Company Limited"
)


def _country_name(code_or_name: Optional[str]) -> Optional[str]:
    raw = (code_or_name or "").strip()
    if not raw or raw == "—":
        return None
    up = raw.upper()
    if len(up) == 2 and up in _ISO2_COUNTRY:
        return _ISO2_COUNTRY[up]
    return raw


def _item_category_label(item_type: str) -> str:
    try:
        import sys
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.insert(0, root)
        from description_grammar import ITEM_TYPE_EN, canonical_item_type
        key = canonical_item_type(item_type or "")
        if key and key in ITEM_TYPE_EN:
            return ITEM_TYPE_EN[key]
    except Exception:
        pass
    return (item_type or "").strip() or "Goods"


def _buyer_shipto(customer: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Thin compatibility delegate — prefer resolve_document_parties with draft."""
    from .commercial_document_parties import resolve_document_parties

    _seller, buyer, shipto = resolve_document_parties(
        draft=None, company=None, customer=customer, delivery_addr=None,
    )
    return {"vat": buyer.get("vat") or ""}, {
        "name": shipto.get("name") or "",
        "addr": shipto.get("addr") or "",
        "city": shipto.get("city") or "",
        "zip": shipto.get("zip") or "",
        "country": shipto.get("country") or "",
    }


def _aggregate_lines(raw_lines: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
    """Transport summary rows + goods_summary for the canonical CMR projection."""
    buckets: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    metals: set = set()
    stones: set = set()
    for ln in raw_lines:
        label = _item_category_label(str(ln.get("item_type") or ""))
        key = label or "Goods"
        if key not in buckets:
            buckets[key] = {
                "item_type": key,
                "qty": 0.0,
                "net_weight": 0.0,
                "origin": None,
                "_origins": set(),
            }
            order.append(key)
        b = buckets[key]
        try:
            b["qty"] += float(ln.get("qty") or ln.get("quantity") or 0)
        except (TypeError, ValueError):
            pass
        try:
            nw = float(ln.get("net_weight") or 0)
            if nw > 0:
                b["net_weight"] += nw
        except (TypeError, ValueError):
            pass
        origin = _country_name(str(ln.get("origin") or "").strip() or None)
        if origin:
            b["_origins"].add(origin)
        metal = str(ln.get("metal") or "").strip()
        if metal:
            metals.add(metal)
        stone = str(ln.get("stone_type") or "").strip()
        if stone:
            stones.add(stone)
    out: List[Dict[str, Any]] = []
    for key in sorted(order):
        b = buckets[key]
        origins = sorted(b.pop("_origins"))
        qty = b["qty"]
        nw = b["net_weight"]
        out.append({
            "item_type": b["item_type"],
            "qty": int(qty) if qty == int(qty) else qty,
            "net_weight": nw if nw > 0 else None,
            "origin": " / ".join(origins) if origins else None,
        })
    metals_str = " & ".join(sorted(metals))
    stones_str = " & ".join(sorted(stones))
    goods_summary = " · ".join(x for x in (metals_str, stones_str) if x)
    return out, goods_summary


def _draft_has_insurance(draft: Any) -> bool:
    raw = getattr(draft, "service_charges_json", None) if draft is not None else None
    if raw is None and isinstance(draft, dict):
        raw = draft.get("service_charges_json") or draft.get("service_charges")
    charges = []
    try:
        if isinstance(raw, str) and raw.strip():
            charges = json.loads(raw) or []
        elif isinstance(raw, list):
            charges = raw
    except Exception:
        charges = []
    for c in charges:
        if not isinstance(c, dict):
            continue
        if str(c.get("charge_type") or "").lower() != "insurance":
            continue
        try:
            if float(c.get("amount") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def build_cmr_document(
    *,
    draft: Any,
    storage_root: Path,
    company: Any = None,
    customer: Any = None,
    shipment_row: Optional[Dict[str, Any]] = None,
    cmr_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical CMR document model (sole CMR business projection)."""
    from .commercial_document_parties import resolve_document_parties

    raw_lines: List[Dict[str, Any]] = []
    if draft is not None:
        try:
            raw = getattr(draft, "editable_lines_json", None)
            if raw is None and isinstance(draft, dict):
                raw = draft.get("editable_lines_json")
                if not raw and isinstance(draft.get("editable_lines"), list):
                    raw_lines = list(draft["editable_lines"])
            if not raw_lines and raw:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                raw_lines = list(parsed or [])
        except Exception as exc:
            log.warning("cmr: editable_lines parse failed: %s", exc)

    batch_id = ""
    if draft is not None:
        batch_id = str(
            getattr(draft, "batch_id", None)
            or (draft.get("batch_id") if isinstance(draft, dict) else "")
            or ""
        )
    try:
        from .commercial_authority import attach_physical_weights_to_lines
        raw_lines = attach_physical_weights_to_lines(batch_id or "", list(raw_lines))
    except Exception as exc:
        log.debug("cmr physical-weight enrich failed: %s", exc)

    lines, goods_summary = _aggregate_lines(raw_lines)
    seller, buyer_full, shipto = resolve_document_parties(
        draft=draft,
        company=company,
        customer=customer,
        delivery_addr=None,
    )
    # CMR Preview buyer contract is VAT-focused; keep full name available on shipto.
    buyer = {"vat": buyer_full.get("vat") or ""}

    awb = None
    carrier_name = None
    service = None
    weight_kg = None
    pickup = None
    if shipment_row:
        awb = (shipment_row.get("tracking_ref") or "").strip() or None
        carrier_name = (shipment_row.get("provider") or shipment_row.get("carrier") or "").strip() or None
        service = shipment_row.get("service_product") or shipment_row.get("service")
        pickup = shipment_row.get("pickup_date") or shipment_row.get("booked_at")
        try:
            weight_kg = float(shipment_row.get("weight_kg") or 0) or None
        except (TypeError, ValueError):
            weight_kg = None

    total_pcs = sum(float(l.get("qty") or 0) for l in lines) or None
    doc_ref = ""
    incoterm = None
    if draft is not None:
        doc_ref = (
            getattr(draft, "wfirma_proforma_fullnumber", None)
            or (draft.get("wfirma_proforma_fullnumber") if isinstance(draft, dict) else None)
            or getattr(draft, "wfirma_proforma_id", None)
            or (draft.get("wfirma_proforma_id") if isinstance(draft, dict) else None)
            or ""
        )
        incoterm = (
            getattr(draft, "incoterm_resolved", None)
            or getattr(draft, "incoterm", None)
            or (draft.get("incoterm_resolved") if isinstance(draft, dict) else None)
            or (draft.get("incoterm") if isinstance(draft, dict) else None)
        )

    carrier = None
    if awb or shipment_row:
        carrier = {
            "name": str(carrier_name) if carrier_name else "—",
            "awb": awb,
            "service": service or "—",
            "incoterm": incoterm or "—",
            "origin": seller.get("city") or "—",
            "destination": shipto.get("city") or shipto.get("country") or "—",
            "pickup": str(pickup)[:10] if pickup else None,
            "pieces": int(total_pcs) if total_pcs else None,
            "weight_kg": weight_kg,
            "insurance": _CMR_INSURANCE_TEXT if _draft_has_insurance(draft) else None,
            "batch_ref": batch_id or None,
        }
        if not awb:
            # Linked booking without AWB yet — still surface carrier block honestly.
            carrier["awb"] = None

    origins = sorted({
        o for l in lines for o in [l.get("origin")] if o
    })
    return {
        "authority": "commercial_cmr",
        "cmr_no": cmr_number,
        "doc_ref": doc_ref or "—",
        "batch_ref": batch_id or None,
        "seller": seller,
        "shipto": shipto,
        "buyer": buyer,
        "carrier": carrier,
        "lines": lines,
        "goods_summary": goods_summary or "",
        "goods_origin_country": " / ".join(origins) if origins else None,
    }


def render_cmr_pdf(document: Dict[str, Any]) -> bytes:
    """ONE CMR PDF — Chrome print of ``render_commercial_cmr_html`` (sole presentation)."""
    from .chrome_html_pdf import html_to_pdf_bytes
    from .commercial_cmr_html import render_commercial_cmr_html

    html = render_commercial_cmr_html(document or {})
    return html_to_pdf_bytes(html)


def render_cmr_html(document: Dict[str, Any]) -> str:
    """ONE CMR HTML presentation (Preview iframe + Chrome PDF source)."""
    from .commercial_cmr_html import render_commercial_cmr_html
    return render_commercial_cmr_html(document or {})


def cmr_available_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> bool:
    """True when a CMR number exists for the draft's outbound shipment."""
    from .shipment_document_manifest import GENERATED, build_manifest

    manifest = build_manifest(
        int(draft_id),
        storage_root=Path(storage_root),
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    for entry in ((manifest.get("groups") or {}).get("transport") or []):
        if (entry or {}).get("document_type") == "cmr" and (entry or {}).get("status") == GENERATED:
            return bool((entry or {}).get("reference"))
    return False


def _assemble_cmr_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
    require_cmr_number: bool,
) -> Optional[Dict[str, Any]]:
    """ONE CMR projection loader used by Preview JSON/HTML and PDF export.

    When ``require_cmr_number`` is True (PDF / confirmation), returns None if the
    CMR number is not yet generated. Preview uses ``require_cmr_number=False`` so
    Logistics can show an honest incomplete document.
    """
    from . import proforma_invoice_link_db as pildb
    from .carrier import doc_package
    from .carrier.cmr_number import cmr_document_number
    from .shipment_document_manifest import GENERATED, build_manifest

    storage_root = Path(storage_root)
    draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
    if draft is None:
        return None

    manifest = build_manifest(
        int(draft_id),
        storage_root=storage_root,
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    cmr_number = ""
    for entry in ((manifest.get("groups") or {}).get("transport") or []):
        if (entry or {}).get("document_type") == "cmr":
            if (entry.get("status") or "") == GENERATED:
                cmr_number = (entry.get("reference") or "").strip()
            break

    company = doc_package._load_company_profile(storage_root)
    customer = doc_package._resolve_customer_from_batch(
        (draft.batch_id or "").strip(),
        (draft.client_name or "").strip(),
        storage_root,
    )

    shipment_row = None
    try:
        from .carrier.persistence import shipment_db
        from .shipment_document_manifest import _batch_client_count

        batch_id = (draft.batch_id or "").strip()
        client_name = (draft.client_name or "").strip() or None
        single_client = _batch_client_count(Path(proforma_db), batch_id) <= 1
        shipment_row = shipment_db.get_shipment_for_draft(
            Path(carrier_db),
            batch_id,
            client_name,
            allow_single_client_fallback=single_client,
        )
    except Exception as exc:
        log.debug("cmr shipment lookup failed: %s", exc)

    if shipment_row and not cmr_number:
        idem = (shipment_row.get("idempotency_key") or "").strip()
        cmr_number = cmr_document_number(idem) or cmr_number

    if require_cmr_number and not cmr_number:
        return None

    return build_cmr_document(
        draft=draft,
        storage_root=storage_root,
        company=company,
        customer=customer,
        shipment_row=shipment_row,
        cmr_number=cmr_number or None,
    )


def export_cmr_pdf_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Optional[Tuple[bytes, str]]:
    """Return (pdf_bytes, filename) when CMR number exists; else None."""
    document = _assemble_cmr_for_draft(
        draft_id=int(draft_id),
        storage_root=storage_root,
        proforma_db=proforma_db,
        carrier_db=carrier_db,
        require_cmr_number=True,
    )
    if document is None:
        return None
    pdf = render_cmr_pdf(document)
    if not pdf or len(pdf) < 10:
        return None
    cmr_number = (document.get("cmr_no") or "cmr").strip()
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in cmr_number)
    return pdf, f"cmr-{safe}.pdf"


def export_cmr_document_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
    require_cmr_number: bool = False,
) -> Optional[Dict[str, Any]]:
    """Canonical CMR document model for Preview / Logistics (and PDF when numbered)."""
    return _assemble_cmr_for_draft(
        draft_id=int(draft_id),
        storage_root=storage_root,
        proforma_db=proforma_db,
        carrier_db=carrier_db,
        require_cmr_number=require_cmr_number,
    )

"""Accounting AWB projection — consume Logistics shipment authority only.

Never creates wz.awb / accounting_awb. Resolves WZ→invoice via wFirma
DIRECT JOIN (invoice/id on warehouse_document_w_z/get) and projects
carrier shipments linked to the related batch/invoice context.

Read-only projection helper for Accounting document screens.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class AwbProjectionRow:
    carrier: str
    awb: str
    source: str  # API | MANUAL_EXTERNAL | RETIRED
    shipment_key: str
    batch_id: str = ""
    actions: tuple = ()  # Track, Waybill, Label, Open Shipment, Resolve in Logistics


def classify_shipment_source(row: Dict[str, Any]) -> str:
    state = (row.get("state") or "").strip().lower()
    mode = (row.get("mode") or "").strip().lower()
    if state in ("retired", "cancelled", "void"):
        return "RETIRED"
    if mode in ("external", "manual"):
        return "MANUAL_EXTERNAL"
    return "API"


def actions_for_source(source: str) -> tuple:
    if source == "RETIRED":
        return ("Open Shipment", "Resolve in Logistics")
    if source == "MANUAL_EXTERNAL":
        return ("Track", "Open Shipment", "Resolve in Logistics")
    return ("Track", "Waybill", "Label", "Open Shipment", "Resolve in Logistics")


def project_awbs_from_shipment_rows(
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Map carrier_shipments rows → Accounting display DTOs (0..N AWBs)."""
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        awb = (row.get("tracking_ref") or "").strip()
        if not awb:
            continue
        source = classify_shipment_source(row)
        dto = AwbProjectionRow(
            carrier=(row.get("provider") or row.get("carrier") or "").strip().upper() or "—",
            awb=awb,
            source=source,
            shipment_key=str(row.get("idempotency_key") or row.get("id") or ""),
            batch_id=str(row.get("batch_id") or ""),
            actions=actions_for_source(source),
        )
        out.append(asdict(dto))
    return out


def resolve_wz_invoice_id(wz_get_payload: Dict[str, Any]) -> Optional[str]:
    """Extract DIRECT JOIN invoice id from a sanitized WZ get probe/document dict."""
    if not isinstance(wz_get_payload, dict):
        return None
    doc = wz_get_payload.get("document") or wz_get_payload
    inv = (doc.get("invoice_id") or "").strip()
    if inv and inv != "0":
        return inv
    inv_el = doc.get("invoice")
    if isinstance(inv_el, dict):
        inv = str(inv_el.get("id") or "").strip()
        if inv and inv != "0":
            return inv
    nested = doc.get("nested_invoice_ids") or []
    for i in nested:
        s = str(i).strip()
        if s and s != "0":
            return s
    return None


def _invoice_id_from_wfirma_xml(response_text: str) -> Optional[str]:
    """Parse invoice/id from a warehouse_document get XML response."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(response_text or "")
    except ET.ParseError:
        return None
    wd = root.find(".//warehouse_document")
    if wd is None:
        return None
    inv = wd.find("invoice")
    if inv is not None:
        iid = (inv.findtext("id") or "").strip()
        if iid and iid != "0":
            return iid
    return None


def _batch_ids_for_wz_invoice(invoice_id: str, storage_root: Path) -> List[str]:
    """Resolve Logistics batch ids via proforma draft that owns the invoice."""
    from .proforma_invoice_link_db import get_draft_by_wfirma_invoice_id

    draft = get_draft_by_wfirma_invoice_id(storage_root / "proforma_drafts.sqlite", invoice_id)
    if not draft:
        return []
    bid = (getattr(draft, "batch_id", None) or "").strip()
    return [bid] if bid else []


def _batch_ids_for_pz_doc(pz_doc_id: str, storage_root: Path) -> List[str]:
    """Best-effort: find import batch whose audit records this PZ wFirma id."""
    import json

    out: List[str] = []
    batches_root = storage_root / "batches"
    if not batches_root.is_dir():
        return out
    # Cap scan — read-only, honest when not found.
    checked = 0
    for batch_dir in sorted(batches_root.iterdir(), reverse=True):
        if not batch_dir.is_dir() or not batch_dir.name.startswith("SHIPMENT_"):
            continue
        checked += 1
        if checked > 400:
            break
        audit_path = batch_dir / "output" / batch_dir.name / "audit.json"
        if not audit_path.is_file():
            audit_path = batch_dir / "audit.json"
        if not audit_path.is_file():
            continue
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        wfx = audit.get("wfirma_export") or {}
        if str(wfx.get("wfirma_pz_doc_id") or "").strip() == str(pz_doc_id).strip():
            out.append(batch_dir.name)
    return out


def _shipment_rows_for_batches(batch_ids: Sequence[str], storage_root: Path) -> List[Dict[str, Any]]:
    from .carrier.persistence import shipment_db as csdb

    carrier_root = storage_root / "carrier" / "carrier_shipments.db"
    if not carrier_root.is_file():
        alt = storage_root / "carrier_shipments.db"
        carrier_root = alt if alt.is_file() else carrier_root
    if not batch_ids or not carrier_root.is_file():
        return []
    return csdb.list_outbound_rows_for_batches(carrier_root, list(batch_ids))


def resolve_awbs_for_warehouse_document(
    doc_type: str,
    wfirma_id: str,
    *,
    storage_root: Path,
) -> Dict[str, Any]:
    """Read-only AWB projection for Accounting WZ/PZ rows (Logistics authority).

    Never writes. Never creates accounting AWB fields. Returns 0..N AWBs.
    """
    from .accounting_documents import WAREHOUSE_MODULE_BY_TYPE
    from . import wfirma_client

    key = (doc_type or "").strip().upper()
    wid = (wfirma_id or "").strip()
    if key not in ("WZ", "PZ") or not wid:
        return {"awbs": [], "batch_ids": [], "invoice_id": None, "note": "unsupported or missing id"}

    module = WAREHOUSE_MODULE_BY_TYPE.get(key)
    if not module:
        return {"awbs": [], "batch_ids": [], "invoice_id": None, "note": f"no module for {key}"}

    try:
        http_status, response_text = wfirma_client._http_request(  # noqa: SLF001 — read-only get
            "GET", module, f"get/{wid}", "",
        )
    except Exception as exc:
        return {"awbs": [], "batch_ids": [], "invoice_id": None, "note": f"wFirma read failed: {exc}"}

    if http_status >= 400:
        return {"awbs": [], "batch_ids": [], "invoice_id": None, "note": f"wFirma HTTP {http_status}"}

    invoice_id = _invoice_id_from_wfirma_xml(response_text)
    batch_ids: List[str] = []
    if key == "WZ" and invoice_id:
        batch_ids = _batch_ids_for_wz_invoice(invoice_id, storage_root)
    elif key == "PZ":
        batch_ids = _batch_ids_for_pz_doc(wid, storage_root)

    rows = _shipment_rows_for_batches(batch_ids, storage_root)
    awbs = project_awbs_from_shipment_rows(rows)
    note = None
    if not awbs and batch_ids:
        note = "batch linked — no carrier AWB on record"
    elif not awbs:
        note = "no Logistics batch link found"
    return {
        "awbs": awbs,
        "batch_ids": batch_ids,
        "invoice_id": invoice_id,
        "note": note,
    }

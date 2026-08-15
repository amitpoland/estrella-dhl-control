"""
commercial_packing_list.py — ONE Commercial Packing List document authority.

Canonical document model matches the Proforma Documents tab Preview
(`packingListData` in proforma-detail.jsx → ``EJPackingList``):

  * Row authority = draft billed ``editable_lines`` (never batch packing.db)
  * Commercial fields = Sales Packing / draft only
  * Physical gross/net = draft then purchase packing enrich
    (``commercial_authority.attach_physical_weights_to_lines``)
  * Descriptions / origin = draft values, with the same Product Master /
    product_descriptions fill-in used by GET /proforma/draft/{id}
  * Missing values stay honestly blank ("—") — never invented

The PDF exporter renders the SAME HTML presentation definition as
``EJPackingList`` (estrella-doc-packing.jsx) via Chrome headless print.
ReportLab visual layout is retired — do not reintroduce a second renderer.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    # service/app/services → repo root (description_grammar lives at root)
    return Path(__file__).resolve().parents[3]


def _item_category_label(item_type: str) -> str:
    """Map item_type token → human category (Ring / Pendant / …).

    Uses root ``description_grammar`` — the same canonical EN table the platform
    already owns. Never invents a parallel category vocabulary.
    """
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from description_grammar import ITEM_TYPE_EN, canonical_item_type
    except Exception:
        return (item_type or "").strip()
    key = canonical_item_type(item_type or "")
    if key and key in ITEM_TYPE_EN:
        return ITEM_TYPE_EN[key]
    return (item_type or "").strip()


def _party(
    *,
    name: str = "",
    addr: str = "",
    city: str = "",
    zip_code: str = "",
    country: str = "",
    vat: str = "",
    email: str = "",
    phone: str = "",
) -> Dict[str, str]:
    return {
        "name": name or "",
        "addr": addr or "",
        "city": city or "",
        "zip": zip_code or "",
        "country": country or "",
        "vat": vat or "",
        "email": email or "",
        "phone": phone or "",
    }


def _seller_from_company(company: Any) -> Dict[str, str]:
    if company is None:
        return _party()
    return _party(
        name=getattr(company, "legal_name", None) or "",
        addr=getattr(company, "street", None) or "",
        city=getattr(company, "postal_city", None) or "",
        country=getattr(company, "country", None) or "",
        vat=getattr(company, "vat_eu", None) or getattr(company, "nip", None) or "",
        email=getattr(company, "email", None) or "",
        phone=getattr(company, "phone", None) or "",
    )


def _buyer_shipto_from_customer(
    customer: Any,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> tuple:
    """Return (buyer, shipto) party dicts from Customer Master helpers."""
    buyer = _party()
    shipto = _party()
    if customer is None and not delivery_addr:
        return buyer, shipto
    try:
        from .customer_master import resolve_billing_address, resolve_delivery_address
    except Exception:
        resolve_billing_address = None  # type: ignore
        resolve_delivery_address = None  # type: ignore

    if customer is not None and resolve_billing_address is not None:
        bill = resolve_billing_address(customer)
        buyer = _party(
            name=bill.get("name", ""),
            addr=bill.get("street", ""),
            city=bill.get("city", ""),
            zip_code=bill.get("postal_code", ""),
            country=bill.get("country", ""),
            email=bill.get("email", ""),
            phone=bill.get("phone", ""),
            vat=getattr(customer, "vat_number", None)
            or getattr(customer, "nip", None)
            or "",
        )
        if delivery_addr is None and resolve_delivery_address is not None:
            delivery_addr = resolve_delivery_address(customer)

    if delivery_addr:
        shipto = _party(
            name=delivery_addr.get("name", "") or buyer.get("name", ""),
            addr=delivery_addr.get("street", ""),
            city=delivery_addr.get("city", ""),
            zip_code=delivery_addr.get("postal_code", "") or delivery_addr.get("zip", ""),
            country=delivery_addr.get("country", ""),
            email=delivery_addr.get("email", ""),
            phone=delivery_addr.get("phone", ""),
        )
    elif buyer.get("name"):
        shipto = dict(buyer)
    return buyer, shipto


def _enrich_draft_lines(
    batch_id: str,
    lines: List[Dict[str, Any]],
    storage_root: Path,
) -> List[Dict[str, Any]]:
    """Apply the same read-time enrichments GET /proforma/draft uses.

    Description + origin from product_descriptions / Product Master; physical
    weights via commercial_authority. Never invents missing SKUs or prices.
    """
    out = [dict(ln) for ln in (lines or [])]
    try:
        from .master_data_db import (
            get_product_local,
            normalize_origin_country,
        )
    except Exception as exc:
        log.debug("commercial packing enrich imports failed: %s", exc)
        get_product_local = None  # type: ignore
        normalize_origin_country = None  # type: ignore

    # product_descriptions live in documents.db — read directly so we do not
    # depend on document_db module-level path init (request-scoped).
    desc_db = storage_root / "documents.db"
    desc_conn = None
    if desc_db.exists():
        try:
            desc_conn = sqlite3.connect(str(desc_db))
            desc_conn.row_factory = sqlite3.Row
        except Exception as exc:
            log.debug("documents.db open failed: %s", exc)
            desc_conn = None

    try:
        for ln in out:
            pc = str(ln.get("product_code") or "").strip()
            if not pc:
                continue
            if desc_conn is not None:
                try:
                    row = desc_conn.execute(
                        "SELECT * FROM product_descriptions WHERE product_code=?",
                        (pc,),
                    ).fetchone()
                    row = dict(row) if row else {}
                except Exception:
                    row = {}
                if row:
                    for src, dst in (
                        ("item_type", "item_type"),
                        ("name_pl", "name_pl"),
                        ("description_pl", "description_pl"),
                        ("description_en", "description_en"),
                    ):
                        if not str(ln.get(dst) or "").strip():
                            v = str(row.get(src) or "").strip()
                            if v:
                                ln[dst] = v
            if get_product_local is not None and normalize_origin_country is not None:
                try:
                    md_db = storage_root / "master_data.sqlite"
                    if not str(ln.get("origin") or "").strip():
                        pl = get_product_local(md_db, pc) if md_db.exists() else None
                        oc = None
                        if pl is not None:
                            oc = normalize_origin_country(
                                getattr(pl, "origin_country", None)
                            )
                        if oc:
                            ln["origin"] = oc
                    else:
                        _norm = normalize_origin_country(ln.get("origin"))
                        if _norm:
                            ln["origin"] = _norm
                except Exception as exc:
                    log.debug("origin enrich failed for %s: %s", pc, exc)
    finally:
        if desc_conn is not None:
            try:
                desc_conn.close()
            except Exception:
                pass

    try:
        from .commercial_authority import attach_physical_weights_to_lines
        out = attach_physical_weights_to_lines(batch_id or "", out)
    except Exception as exc:
        log.debug("physical-weight enrich failed: %s", exc)
    return out


def build_commercial_packing_document(
    *,
    draft: Any,
    storage_root: Path,
    company: Any = None,
    customer: Any = None,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build the canonical Commercial Packing List document model.

    Shape mirrors frontend ``packingListData`` / ``EJPackingList`` contract.
    """
    storage_root = Path(storage_root)
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
            log.warning("commercial packing: editable_lines parse failed: %s", exc)
            raw_lines = []

    batch_id = ""
    if draft is not None:
        batch_id = str(getattr(draft, "batch_id", None) or (draft.get("batch_id") if isinstance(draft, dict) else "") or "")

    lines = _enrich_draft_lines(batch_id, raw_lines, storage_root)

    currency = "EUR"
    if draft is not None:
        currency = (
            getattr(draft, "currency", None)
            or (draft.get("currency") if isinstance(draft, dict) else None)
            or "EUR"
        )

    doc_ref = ""
    if draft is not None:
        doc_ref = (
            getattr(draft, "wfirma_proforma_fullnumber", None)
            or (draft.get("wfirma_proforma_fullnumber") if isinstance(draft, dict) else None)
            or getattr(draft, "wfirma_proforma_id", None)
            or (draft.get("wfirma_proforma_id") if isinstance(draft, dict) else None)
            or ""
        )
    invoice_ref = None
    if draft is not None:
        inv = (
            getattr(draft, "wfirma_invoice_number", None)
            or (draft.get("wfirma_invoice_number") if isinstance(draft, dict) else None)
            or ""
        )
        invoice_ref = str(inv).strip() or None

    issued_date = ""
    if draft is not None:
        issued_date = str(
            getattr(draft, "issue_date", None)
            or getattr(draft, "commercial_issue_date", None)
            or (draft.get("issue_date") if isinstance(draft, dict) else None)
            or ""
        ).strip()

    seller = _seller_from_company(company)
    buyer, shipto = _buyer_shipto_from_customer(customer, delivery_addr)

    rows: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines, 1):
        qty = 0.0
        try:
            qty = float(ln.get("qty") or ln.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        unit_price = 0.0
        try:
            unit_price = float(ln.get("unit_price") or 0)
        except (TypeError, ValueError):
            unit_price = 0.0
        metal = str(ln.get("metal") or "")
        kt = str(ln.get("karat") or (metal.split("/")[0] if metal else "") or "").strip()
        col = str(
            ln.get("metal_color") or (metal.split("/")[1] if "/" in metal else "") or ""
        ).strip()
        try:
            dia = float(ln.get("diamond_weight") or 0)
        except (TypeError, ValueError):
            dia = 0.0
        try:
            cwt = float(ln.get("color_weight") or 0)
        except (TypeError, ValueError):
            cwt = 0.0
        try:
            gw = float(ln.get("gross_weight") or 0)
        except (TypeError, ValueError):
            gw = 0.0
        try:
            nw = float(ln.get("net_weight") or 0)
        except (TypeError, ValueError):
            nw = 0.0

        rows.append({
            "sr": i,
            "ctg": _item_category_label(str(ln.get("item_type") or "")),
            "client_po": str(ln.get("client_po") or "").strip(),
            "product_code": str(ln.get("product_code") or "").strip() or "—",
            "design": str(ln.get("design_no") or "").strip() or "—",
            "description_en": str(ln.get("description_en") or "").strip(),
            "description_pl": str(ln.get("description_pl") or "").strip(),
            "kt": kt,
            "col": col,
            "quality": str(ln.get("quality_string") or "").strip(),
            "dia_wt": dia if dia > 0 else None,
            "col_wt": cwt if cwt > 0 else None,
            "gross_wt": gw if gw > 0 else None,
            "net_wt": nw if nw > 0 else None,
            "qty": int(qty) if qty == int(qty) else qty,
            "unit_price": unit_price,
            "total_value": unit_price * qty,
            "size": str(ln.get("size") or "").strip(),
            "origin": str(ln.get("origin") or "").strip() or "—",
        })

    grand_total = sum(float(r["total_value"] or 0) for r in rows)
    total_qty = sum(float(r["qty"] or 0) for r in rows)

    return {
        "doc_ref": doc_ref or "—",
        "invoice_ref": invoice_ref,
        "issued_date": issued_date,
        "seller": seller,
        "shipto": shipto,
        "buyer": buyer,
        "currency": currency or "EUR",
        "rows": rows,
        "grand_total": grand_total,
        "total_qty": total_qty,
        "batch_id": batch_id,
        "authority": "commercial_packing_list",
    }


def render_commercial_packing_list_pdf(document: Dict[str, Any]) -> bytes:
    """ONE Packing List PDF presentation — HTML (EJPackingList equivalent) + Chrome print.

    ReportLab visual path is retired. Preview Download, Documents Hub, ZIP, and
    customer-email attachment must all call this exporter.
    """
    from .commercial_packing_list_html import render_commercial_packing_list_html
    from .chrome_html_pdf import html_to_pdf_bytes

    html = render_commercial_packing_list_html(document or {})
    return html_to_pdf_bytes(html)



def render_packing_list_pdf_from_authorities(
    *,
    batch_id: str,
    storage_root: Path,
    company: Any,
    customer: Any,
    draft: Any,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> bytes:
    """Public entry used by Path-DOC / Complete Package — always commercial model."""
    document = build_commercial_packing_document(
        draft=draft,
        storage_root=storage_root,
        company=company,
        customer=customer,
        delivery_addr=delivery_addr,
    )
    if not document.get("batch_id"):
        document["batch_id"] = batch_id
    return render_commercial_packing_list_pdf(document)


def fingerprint_commercial_packing_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Semantic identity for Preview-model ↔ PDF-model drift tests.

    Compares business facts, not pixels. Rows are ordered by ``sr``.
    """
    rows_out: List[Dict[str, Any]] = []
    for r in (document or {}).get("rows") or []:
        if not isinstance(r, dict):
            continue
        rows_out.append({
            "sr": r.get("sr"),
            "product_code": r.get("product_code"),
            "design": r.get("design"),
            "description_en": r.get("description_en"),
            "qty": r.get("qty"),
            "unit_price": r.get("unit_price"),
            "total_value": r.get("total_value"),
            "client_po": r.get("client_po"),
            "gross_wt": r.get("gross_wt"),
            "net_wt": r.get("net_wt"),
            "origin": r.get("origin"),
        })
    return {
        "authority": (document or {}).get("authority"),
        "doc_ref": (document or {}).get("doc_ref"),
        "invoice_ref": (document or {}).get("invoice_ref"),
        "currency": (document or {}).get("currency"),
        "total_qty": (document or {}).get("total_qty"),
        "grand_total": (document or {}).get("grand_total"),
        "rows": rows_out,
    }


def export_packing_list_pdf_for_draft(
    *,
    draft: Any,
    storage_root: Path,
    delivery_addr: Optional[Dict[str, str]] = None,
) -> tuple:
    """ONE Packing List export used by Documents Hub download + customer email.

    Loads company/customer the same way as Path-DOC / shipment-documents, then
    builds ``build_commercial_packing_document`` and renders PDF bytes.

    Returns ``(pdf_bytes, filename, document_model)``.
    """
    from .carrier import doc_package

    storage_root = Path(storage_root)
    batch_id = (getattr(draft, "batch_id", None) or "").strip()
    client_name = (getattr(draft, "client_name", None) or "").strip()
    draft_id = int(getattr(draft, "id"))
    if not batch_id:
        raise ValueError("Draft has no batch_id — cannot render packing list.")

    company = doc_package._load_company_profile(storage_root)
    pdraft = doc_package._load_proforma_draft(batch_id, client_name, storage_root)
    customer = doc_package._resolve_customer_from_batch(
        batch_id, client_name, storage_root,
    )
    effective = pdraft or draft
    document = build_commercial_packing_document(
        draft=effective,
        storage_root=storage_root,
        company=company,
        customer=customer,
        delivery_addr=delivery_addr,
    )
    if not document.get("batch_id"):
        document["batch_id"] = batch_id
    packing_pdf = render_commercial_packing_list_pdf(document)
    if not packing_pdf or len(packing_pdf) < 10:
        raise ValueError("Commercial Packing List has no lines to export.")
    if not (document.get("rows") or []):
        raise ValueError("Commercial Packing List has no lines to export.")

    prof_ref = (
        getattr(draft, "wfirma_proforma_fullnumber", None)
        or getattr(draft, "wfirma_proforma_id", None)
        or f"draft-{draft_id}"
    )
    safe_ref = str(prof_ref).replace("/", "-").replace("\\", "-").replace(" ", "_")
    return packing_pdf, f"packing-list-{safe_ref}.pdf", document

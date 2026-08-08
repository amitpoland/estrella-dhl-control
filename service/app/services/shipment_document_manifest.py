"""
Shipment Document Hub — manifest builder (AGGREGATOR ONLY).

``build_manifest`` collects every document that already exists for a proforma
draft's shipment and reports each one's authority + status + API-relative
links. It is strictly an aggregator: it invents NO new Proforma / Invoice / CMR
/ DHL-tracker / email system. Every entry points at an EXISTING authority:

  * Proforma draft / packing list  → Estrella browser-preview surfaces.
  * Official proforma / invoice     → wFirma PDFs (via existing proforma routes,
                                       ultimately ``wfirma_client.fetch_invoice_pdf``).
  * DHL label / waybill / receipt   → files saved at booking under the carrier
                                       document store (same existence checks as
                                       routes_carrier_actions).
  * DHL ePOD                        → MyDHL proof-of-delivery PDF (optional;
                                       persisted under carrier/epods/).
  * Commercial package              → the persisted Path-DOC package.
  * Tracking                        → a thin pointer; the UI keeps using the
                                       existing tracking API.
  * Delivery confirmation           → summary from delivery_confirmation_db.

Client-scoped: the shipment is resolved with ``get_shipment_for_draft`` bound to
the draft's client_name, so one client's AWB/docs never leak onto another
client's draft in the same batch. No filesystem path is ever placed in the
returned structure — only API-relative URLs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

log = logging.getLogger(__name__)

# Status vocabulary (kept as literals so callers/tests read plainly).
GENERATED = "Generated"
PENDING = "Pending"
MISSING = "Missing"
FAILED = "Failed"
HISTORICAL_UNAVAILABLE = "Historical unavailable"


class DraftNotFound(Exception):
    """Raised when the draft id does not resolve — route maps to 404."""


def _entry(
    document_type: str,
    authority: str,
    status: str,
    *,
    reference: Optional[str] = None,
    generated_at: Optional[str] = None,
    preview_available: bool = False,
    download_available: bool = False,
    preview_url: Optional[str] = None,
    download_url: Optional[str] = None,
    required_for_complete_package: bool = False,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "document_type": document_type,
        "authority": authority,
        "status": status,
        "reference": reference,
        "generated_at": generated_at,
        "preview_available": preview_available,
        "download_available": download_available,
        "preview_url": preview_url,
        "download_url": download_url,
        "required_for_complete_package": required_for_complete_package,
        "reason": reason,
    }


def _draft_has_lines(draft: Any) -> bool:
    """True if the draft carries at least one commercial line.

    Checks editable_lines_json first (the live edited set), then the original
    source_lines_json snapshot.
    """
    for attr in ("editable_lines_json", "source_lines_json"):
        raw = getattr(draft, attr, None)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, list) and len(parsed) > 0:
            return True
    return False


def _batch_client_count(proforma_db: Path, batch_id: str) -> int:
    """Distinct client_name count for a batch (drives single-client fallback)."""
    try:
        from . import proforma_invoice_link_db as pildb
        drafts = pildb.list_drafts_for_batch(proforma_db, batch_id)
    except Exception:
        return 0
    names = {(getattr(d, "client_name", "") or "").strip() for d in drafts}
    names.discard("")
    return len(names)


def build_manifest(
    draft_id: int,
    *,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Dict[str, Any]:
    """Aggregate every shipment document for one proforma draft.

    Raises :class:`DraftNotFound` when the draft id is unknown.
    """
    from . import proforma_invoice_link_db as pildb
    from . import delivery_confirmation_db as dcdb
    from .carrier.persistence import shipment_db
    from .carrier.cmr_number import cmr_document_number
    from ..api.routes_carrier_actions import _shipment_doc_file, _doc_package_file

    draft = pildb.get_draft_by_id(proforma_db, int(draft_id))
    if draft is None:
        raise DraftNotFound(f"draft {draft_id} not found")

    batch_id = (draft.batch_id or "").strip()
    client_name = (draft.client_name or "").strip()

    # ── Resolve the client's shipment (client-scoped; never leak another AWB) ──
    awb: Optional[str] = None
    shipment_row: Optional[dict] = None
    cmr_number: Optional[str] = None
    if Path(carrier_db).exists():
        try:
            shipment_db.init_db(carrier_db)
            single_client = _batch_client_count(proforma_db, batch_id) <= 1
            shipment_row = shipment_db.get_shipment_for_draft(
                carrier_db, batch_id, client_name or None,
                allow_single_client_fallback=single_client,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("manifest shipment lookup failed: %s", exc)
            shipment_row = None
    if shipment_row:
        tr = shipment_row.get("tracking_ref")
        awb = tr if isinstance(tr, str) and tr.strip() else None
        idem = shipment_row.get("idempotency_key")
        cmr_number = cmr_document_number(idem) if idem else None

    # Encoded proforma document.pdf route components.
    b_enc = quote(batch_id, safe="")
    c_enc = quote(client_name, safe="")
    official_pdf_url = f"/api/v1/proforma/{b_enc}/{c_enc}/document.pdf"

    has_lines = _draft_has_lines(draft)

    # ── COMMERCIAL group ──────────────────────────────────────────────────────
    commercial: List[Dict[str, Any]] = []

    # draft_proforma — SAME canonical Estrella Proforma Preview modal as the
    # toolbar Preview button (estrella-doc-proforma.jsx + draft docData).
    # reason=browser_preview tells the Documents UI to call onOpenPreview
    # ('proforma') — never open the parallel server preview.html surface.
    commercial.append(_entry(
        "draft_proforma", "Estrella", GENERATED,
        reference=(draft.wfirma_proforma_fullnumber or f"Draft #{draft.id}"),
        generated_at=draft.created_at,
        preview_available=True, download_available=False,
        preview_url=None,
        reason="browser_preview",
    ))

    posted = bool((draft.wfirma_proforma_id or "").strip())
    converted = bool((getattr(draft, "wfirma_invoice_id", None) or "").strip())

    # official_proforma — wFirma PDF, only once posted. Never fabricated.
    if posted:
        commercial.append(_entry(
            "official_proforma", "wFirma", GENERATED,
            reference=(draft.wfirma_proforma_fullnumber or draft.wfirma_proforma_id),
            generated_at=getattr(draft, "posted_at", None),
            preview_available=True, download_available=True,
            preview_url=official_pdf_url, download_url=official_pdf_url,
            # Mandatory for the complete package ONLY when not yet converted to
            # an invoice (invoice supersedes the proforma as the fiscal doc).
            required_for_complete_package=not converted,
        ))
    else:
        commercial.append(_entry(
            "official_proforma", "wFirma", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="Proforma has not been posted to wFirma yet.",
        ))

    # invoice — Pending until wfirma_invoice_id, then the draft-scoped PDF.
    if converted:
        inv_url = f"/api/v1/proforma/draft/{draft.id}/invoice.pdf"
        commercial.append(_entry(
            "invoice", "wFirma", GENERATED,
            reference=(getattr(draft, "wfirma_invoice_number", None)
                       or getattr(draft, "wfirma_invoice_id", None)),
            generated_at=getattr(draft, "converted_at", None),
            preview_available=True, download_available=True,
            preview_url=inv_url, download_url=inv_url,
            required_for_complete_package=True,
        ))
    else:
        commercial.append(_entry(
            "invoice", "wFirma", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="No wFirma invoice yet — convert the proforma to an invoice first.",
        ))

    # packing_list — Estrella Commercial Packing List (same model as Preview).
    # ZIP / Path-DOC bytes = commercial_packing_list presentation adapter
    # (NOT the retired simplified packing.db sheet).
    commercial.append(_entry(
        "packing_list", "Estrella", GENERATED if has_lines else MISSING,
        reference=None,
        generated_at=draft.created_at if has_lines else None,
        preview_available=has_lines, download_available=False,
        preview_url=None,   # browser preview via existing _openPreview('packing')
        required_for_complete_package=has_lines,
        reason="browser_preview" if has_lines else "Draft has no commercial lines.",
    ))

    # ── TRANSPORT group (CMR) ─────────────────────────────────────────────────
    transport: List[Dict[str, Any]] = []
    if cmr_number:
        transport.append(_entry(
            "cmr", "Estrella", GENERATED,
            reference=cmr_number,
            preview_available=True, download_available=False,
            preview_url=None,   # browser preview only; no server CMR PDF authority
            required_for_complete_package=False,   # honest: no server CMR PDF
            reason="browser_preview",
        ))
    else:
        transport.append(_entry(
            "cmr", "Estrella", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="CMR is available after a DHL shipment is booked.",
        ))

    # ── CARRIER group (DHL label / waybill / receipt / ePOD / commercial pkg) ─
    carrier: List[Dict[str, Any]] = []
    label_present = False
    waybill_present = False
    waybill_required = False  # only when a real waybill file exists for this AWB

    # Label + receipt: disk only (saved at create_shipment). Waybill: disk first,
    # then best-effort MyDHL Get Image recovery when missing.
    for doc_type, kind, url_seg in (
        ("dhl_label", "label", "label"),
        ("dhl_receipt", "receipt", "receipt"),
    ):
        if not awb:
            carrier.append(_entry(
                doc_type, "DHL", PENDING,
                preview_available=False, download_available=False,
                required_for_complete_package=False,
                reason="No AWB booked for this client yet.",
            ))
            continue
        present = _shipment_doc_file(kind, batch_id, awb) is not None
        if doc_type == "dhl_label":
            label_present = present
        if present:
            url = f"/api/v1/carrier/{b_enc}/{url_seg}/{quote(awb, safe='')}"
            carrier.append(_entry(
                doc_type, "DHL", GENERATED,
                reference=awb,
                preview_available=True, download_available=True,
                preview_url=url, download_url=url,
                # Transport Label is the courier-attach authority for this stack.
                required_for_complete_package=(doc_type == "dhl_label"),
            ))
        else:
            carrier.append(_entry(
                doc_type, "DHL", HISTORICAL_UNAVAILABLE,
                reference=awb,
                preview_available=False, download_available=False,
                required_for_complete_package=(doc_type == "dhl_label"),
                reason=(
                    "AWB exists but no saved document file — this shipment was "
                    "booked before document capture, or the file was never stored."
                ),
            ))

    # dhl_waybill — try local file, then MyDHL Get Image (when account entitled).
    waybill_entry = _resolve_waybill_entry(
        batch_id=batch_id, awb=awb, b_enc=b_enc,
        shipment_created_at=(shipment_row or {}).get("created_at"),
    )
    carrier.append(waybill_entry)
    waybill_present = waybill_entry["status"] == GENERATED
    # Only a real on-disk waybill is package-mandatory. When DHL never provided
    # one (create omitted waybillDoc AND Get Image 403/404), do not permanently
    # block Complete Package — Transport Label remains the courier authority.
    waybill_required = waybill_present

    # dhl_epod — carrier POD; optional; never confuses with customer confirmation.
    carrier.append(_resolve_epod_entry(
        batch_id=batch_id, awb=awb, b_enc=b_enc, storage_root=storage_root,
    ))

    # dhl_commercial_package — Path-DOC composer (existing POST label-package).
    pkg = _doc_package_file(batch_id, client_name) if batch_id else None
    box_type_code = (shipment_row or {}).get("box_type_code") if shipment_row else None
    gen_meta = _commercial_package_generate_meta(
        storage_root=storage_root,
        batch_id=batch_id,
        client_name=client_name,
        posted=posted,
        box_type_code=box_type_code if isinstance(box_type_code, str) else None,
    )
    if pkg is not None:
        pkg_entry = _entry(
            "dhl_commercial_package", "Estrella", GENERATED,
            preview_available=False, download_available=True,
            download_url=f"/api/v1/carrier/{b_enc}/documents",
            required_for_complete_package=False,
        )
    else:
        pkg_entry = _entry(
            "dhl_commercial_package", "Estrella", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason=(
                "; ".join(g["reason"] for g in gen_meta["missing"])
                if gen_meta["missing"]
                else "Not generated yet — use Generate Commercial Package."
            ),
        )
    pkg_entry["generate"] = gen_meta
    carrier.append(pkg_entry)

    # ── Complete package readiness ─────────────────────────────────────────────
    # Mandatory: fiscal PDF + packing list + DHL transport label (when booked).
    # Waybill only when DHL actually provided one. ePOD/CMR/commercial pkg optional.
    complete_package = _build_complete_package(
        draft_id=draft.id,
        posted=posted, converted=converted, has_lines=has_lines,
        awb=awb, label_present=label_present,
        waybill_present=waybill_present, waybill_required=waybill_required,
    )

    # ── Delivery confirmation summary (or None) ────────────────────────────────
    delivery_summary = None
    try:
        delivery_summary = dcdb.get_delivery_summary_for_draft(
            Path(storage_root) / "delivery_confirmations.db", draft.id,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("manifest delivery summary failed: %s", exc)

    return {
        "draft_id": draft.id,
        "batch_id": batch_id,
        "client_name": client_name,
        "awb": awb,
        "groups": {
            "commercial": commercial,
            "transport": transport,
            "carrier": carrier,
            "complete_package": complete_package,
        },
        "tracking": {
            "awb": awb,
            "authority": "tracking_service / Unified API",
        },
        "delivery_confirmation": delivery_summary,
    }


def _resolve_waybill_entry(
    *,
    batch_id: str,
    awb: Optional[str],
    b_enc: str,
    shipment_created_at: Optional[str],
) -> Dict[str, Any]:
    """Waybill card: local file, else MyDHL Get Image recovery, else honest gap."""
    from ..api.routes_carrier_actions import _shipment_doc_file

    if not awb:
        return _entry(
            "dhl_waybill", "DHL", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="No AWB booked for this client yet.",
        )
    present = _shipment_doc_file("waybill-doc", batch_id, awb) is not None
    if not present:
        try:
            from .carrier.document_image_service import ensure_waybill_persisted
            ym = None
            created = (shipment_created_at or "").strip()
            if len(created) >= 7 and created[4] == "-":
                ym = created[:7]
            outcome = ensure_waybill_persisted(batch_id, awb, pickup_year_month=ym)
            present = outcome.status in ("present", "persisted")
            if not present:
                if outcome.status == "not_authorized":
                    return _entry(
                        "dhl_waybill", "DHL", PENDING,
                        reference=awb,
                        preview_available=False, download_available=False,
                        required_for_complete_package=False,
                        reason=(
                            "Not provided by DHL for this account — MyDHL Get Image "
                            "returned not authorized (8032). Transport Label is the "
                            "courier handover document for this booking."
                        ),
                    )
                if outcome.status == "not_found":
                    return _entry(
                        "dhl_waybill", "DHL", PENDING,
                        reference=awb,
                        preview_available=False, download_available=False,
                        required_for_complete_package=False,
                        reason=(
                            "Not provided by DHL for this shipment — MyDHL create "
                            "response had no waybillDoc and Get Image returned 404."
                        ),
                    )
                # skipped / error — do not invent Historical-unavailable blocker
                return _entry(
                    "dhl_waybill", "DHL", PENDING,
                    reference=awb,
                    preview_available=False, download_available=False,
                    required_for_complete_package=False,
                    reason=(
                        "No waybill on disk and recovery was not possible "
                        f"({outcome.status}: {outcome.detail or 'n/a'}). "
                        "Transport Label remains the courier document when present."
                    ),
                )
        except Exception as exc:  # pragma: no cover
            log.debug("waybill recovery failed: %s", exc)
            return _entry(
                "dhl_waybill", "DHL", PENDING,
                reference=awb,
                preview_available=False, download_available=False,
                required_for_complete_package=False,
                reason="Waybill recovery failed — see server logs.",
            )
    url = f"/api/v1/carrier/{b_enc}/waybill-doc/{quote(awb, safe='')}"
    return _entry(
        "dhl_waybill", "DHL", GENERATED,
        reference=awb,
        preview_available=True, download_available=True,
        preview_url=url, download_url=url,
        required_for_complete_package=True,
    )


def _resolve_epod_entry(
    *,
    batch_id: str,
    awb: Optional[str],
    b_enc: str,
    storage_root: Path,
) -> Dict[str, Any]:
    """ePOD card with best-effort persist + honest Pending reasons."""
    if not awb:
        return _entry(
            "dhl_epod", "DHL", PENDING,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="No AWB booked for this client yet.",
        )
    try:
        from .carrier.epod_service import ensure_epod_result
        outcome = ensure_epod_result(batch_id, awb)
    except Exception as exc:  # pragma: no cover
        log.debug("ePOD ensure failed: %s", exc)
        outcome = None

    if outcome is not None and outcome.status in ("present", "persisted") and outcome.path:
        url = f"/api/v1/carrier/{b_enc}/epod/{quote(awb, safe='')}"
        return _entry(
            "dhl_epod", "DHL", GENERATED,
            reference=awb,
            preview_available=True, download_available=True,
            preview_url=url, download_url=url,
            required_for_complete_package=False,
        )

    # Distinguish delivered-but-not-eligible vs not-yet-delivered when possible.
    delivered = _tracking_says_delivered(awb, storage_root)
    if outcome is not None and outcome.status == "not_eligible":
        return _entry(
            "dhl_epod", "DHL", PENDING,
            reference=awb,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason="Not provided by DHL for this shipment.",
        )
    if delivered:
        return _entry(
            "dhl_epod", "DHL", PENDING,
            reference=awb,
            preview_available=False, download_available=False,
            required_for_complete_package=False,
            reason=(
                "Shipment is delivered but MyDHL ePOD could not be retrieved "
                f"({getattr(outcome, 'status', 'unknown')})."
            ),
        )
    return _entry(
        "dhl_epod", "DHL", PENDING,
        reference=awb,
        preview_available=False, download_available=False,
        required_for_complete_package=False,
        reason="Available after eligible DHL delivery.",
    )


def _tracking_says_delivered(awb: str, storage_root: Path) -> bool:
    """Best-effort delivered check via tracking_service (never raises)."""
    try:
        from . import tracking_service
        cache_dir = Path(storage_root) / "outputs" / "_doc_hub_tracking"
        cache_dir.mkdir(parents=True, exist_ok=True)
        result = tracking_service.get_tracking_status(
            awb, "DHL", cache_dir, refresh=False,
        )
        status = (
            (result.get("status") or "")
            if isinstance(result, dict) else ""
        )
        return str(status).strip().lower() == "delivered"
    except Exception:
        return False


def _commercial_package_generate_meta(
    *,
    storage_root: Path,
    batch_id: str,
    client_name: str,
    posted: bool,
    box_type_code: Optional[str],
) -> Dict[str, Any]:
    """UI contract for the Generate Commercial Package action (no second composer)."""
    missing: List[Dict[str, str]] = []
    box_type_id = None
    if not batch_id:
        missing.append({"field": "batch", "reason": "No batch_id on this draft."})
    if not posted:
        missing.append({
            "field": "proforma",
            "reason": "Post the proforma to wFirma first (commercial invoice source).",
        })
    code = (box_type_code or "").strip()
    if not code:
        missing.append({
            "field": "box_type",
            "reason": "No box profile on the DHL booking — book with a Box Profile first.",
        })
    else:
        try:
            from .master_data_db import get_box_type_by_code, init_db as init_md
            md = Path(storage_root) / "master_data.sqlite"
            init_md(md)
            box = get_box_type_by_code(md, code)
            if box is None:
                missing.append({
                    "field": "box_type",
                    "reason": f"Box profile {code!r} not found in box_types master.",
                })
            else:
                box_type_id = int(box.id)
        except Exception as exc:
            missing.append({
                "field": "box_type",
                "reason": f"Box profile lookup failed: {exc}",
            })
    return {
        "can_generate": len(missing) == 0 and box_type_id is not None,
        "missing": missing,
        "box_type_code": code or None,
        "box_type_id": box_type_id,
        "endpoint": f"/api/v1/carrier/{quote(batch_id, safe='')}/label-package" if batch_id else None,
        "client_name": client_name or None,
    }


def _build_complete_package(
    *,
    draft_id: int,
    posted: bool,
    converted: bool,
    has_lines: bool,
    awb: Optional[str],
    label_present: bool,
    waybill_present: bool = False,
    waybill_required: bool = False,
) -> Dict[str, Any]:
    """Readiness of the one-click complete package (authoritative bytes only)."""
    missing: List[str] = []

    # Commercial fiscal doc: invoice if converted, else posted proforma.
    if converted:
        pass  # invoice PDF is fetchable from wFirma
    elif posted:
        pass  # official proforma PDF is fetchable from wFirma
    else:
        missing.append("Posted proforma or invoice (post the proforma to wFirma).")

    if not has_lines:
        missing.append("Packing list (draft has no commercial lines).")

    if awb:
        if not label_present:
            missing.append("DHL Transport Label (no saved file).")
        # Waybill only blocks when DHL actually provided one for this AWB.
        if waybill_required and not waybill_present:
            missing.append("DHL Waybill (file missing after it was known present).")
    else:
        missing.append("DHL booking — Available after DHL booking.")

    ready = len(missing) == 0
    result: Dict[str, Any] = {
        "ready": ready,
        "missing": missing,
        "status": GENERATED if ready else PENDING,
    }
    if ready:
        result["download_url"] = (
            f"/api/v1/shipment-documents/draft/{draft_id}/complete-package"
        )
    return result

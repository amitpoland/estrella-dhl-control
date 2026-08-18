"""
Carrier action routes — shipment creation, state retrieval, and Path-DOC package.

POST /api/v1/carrier/{batch_id}/shipment
    Creates a shipment via CarrierCoordinator.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, tracking_ref, simulated.

GET /api/v1/carrier/{batch_id}/shipment?client_ref={client_name}
    CLIENT-SCOPED shipment resolution (2026-07-16 cross-client AWB leak fix):
    returns the shipment that belongs to THIS client's draft — exact
    (batch_id, client_ref) match, with a legacy single-client fallback only
    when the batch is not affirmatively multi-client. A multi-client batch
    with no per-client row returns 404 honest-missing; it is NEVER the
    "most-recent row for the batch".
    Returns: batch_id, idempotency_key, export_shipment_id, cmr_number
    (short CMR-EJ-<10 hex>, ADR-proforma-cmr-short-number), client_ref, mode,
    state, simulated, error, plus the AWB logistics/document contract
    (tracking_ref, carrier, service_code, box_type_code, weight_kg, dimensions,
    declared_value, currency, created_at, label_download_url,
    commercial_documents_url, documents_available, saved_labels_exist).
    tracking_ref persisted since the 2026-07-06 incident fix; legacy rows
    return null fields honestly.

GET /api/v1/carrier/{batch_id}/shipment/legacy-probe
    Booking-modal pre-check (ADR-proforma-cmr-short-number §Known limitation):
    does a legacy (pre-client_ref, NULL client_ref, non-failed) shipment row
    exist for this batch? A re-book that now sends client_ref computes a NEW
    idempotency key, so the coordinator will NOT replay that row — the V2 AWB
    modal requires explicit operator confirmation before creating a new
    shipment record alongside it. Read-only; no carrier-config gate; never
    calls DHL; performs no cancellation or void.
    Returns: batch_id, legacy_exists, and (when true) tracking_ref, state,
    created_at of the newest legacy row.

POST /api/v1/carrier/{batch_id}/label-package   ← Path-DOC (WF4.5)
    Generates outbound customs/shipping document package.
    UNGATED — no carrier_api_status / creds / allowlist check.
    Returns: PDF or ZIP bytes containing invoice + packing list + CN23 (non-EU).
    422 {gaps:[...]} when mandatory inputs are missing.

Auth: read routes use require_api_key. Mutation routes (POST) that create a
shipment/AWB, mark an AWB do-not-use, or generate a document package ALSO
require role admin|logistics (require_role) — booking a carrier shipment is a
money-moving, outward-facing action and must not be reachable by a viewer-role
session holding only an API key. Consistent with the RBAC hardening in #504.
No live DHL calls in shadow mode.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..core.security import require_api_key
from ..auth.dependencies import require_role, require_permission
from ..services.carrier.coordinator import (
    CarrierCoordinator,
    CoordinatorConfig,
    register_external_shipment,
)
from ..services.carrier.factory import CarrierConfig
from ..services.carrier.cmr_number import cmr_document_number
from ..services.carrier.models.shipment import CarrierGateError, ShipmentRequest
from ..services.carrier.persistence import shipment_db

router = APIRouter(prefix="/api/v1/carrier", tags=["carrier"])

logger = logging.getLogger(__name__)

# Slice 2c — catalogue Gate 3 (stack on require_role; never drop role gate).
_perm_awb_create = Depends(require_permission("awb.create"))
_perm_awb_label = Depends(require_permission("awb.label"))
_perm_awb_docs = Depends(require_permission("awb.docs_fetch"))
_perm_shipments_edit = Depends(require_permission("shipments.edit"))


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_carrier_config() -> CarrierConfig:
    from ..core.config import settings
    from ..services.carrier.credentials.consumer_bridge import express_carrier_config_kwargs

    if settings.carrier_api_status == "pending":
        raise HTTPException(
            status_code=503,
            detail=(
                "Carrier API is not yet activated (carrier_api_status=pending). "
                "Set CARRIER_API_STATUS=shadow or CARRIER_API_STATUS=live to enable."
            ),
        )
    # Secrets via resolve_carrier_credentials (unmigrated → Settings only).
    return CarrierConfig(**express_carrier_config_kwargs("ship"))


def _get_coordinator(
    config: CarrierConfig = Depends(_get_carrier_config),
) -> CarrierCoordinator:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return CarrierCoordinator(
        CoordinatorConfig(
            carrier_config=config,
            shipment_db_path=root / "carrier_shipments.db",
            shadow_log_db_path=root / "shadow_log.db",
        )
    )


def _get_shipment_db_path() -> Path:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return root / "carrier_shipments.db"


def _batch_not_multi_client(batch_id: str) -> bool:
    """True unless the proforma authority AFFIRMATIVELY shows >1 client draft.

    Draft identity is (batch_id, client_name), so distinct client_name for a
    batch = number of client drafts. Governs the legacy single-client fallback
    in get_shipment_for_draft (attributing a NULL-client_ref row to a draft).

    Safety model: the resolver already refuses to fall back unless there is
    EXACTLY ONE shipment row for the batch. The only case that guard cannot
    catch is a multi-client batch with a single (pre-client_ref) booking —
    detectable only via proforma. proforma_links.db is always present in
    production, so:
      * DB absent (e.g. unit tests, fresh env) → permissive (True): the
        single-row guard is sufficient; there is no multi-client data to leak.
      * DB present, ≤1 distinct client → single-client → True.
      * DB present, >1 distinct client → multi-client → False (deny fallback,
        honest-missing — this is the leak fix).
      * DB present but unreadable → strict (False): never guess when real
        proforma data exists but we failed to read it.
    """
    from ..core.config import settings
    link_db = settings.storage_root / "proforma_links.db"
    if not link_db.exists():
        return True
    try:
        from ..services import proforma_invoice_link_db as pildb
        drafts = pildb.list_drafts_for_batch(link_db, batch_id)
        names = {
            (getattr(d, "client_name", "") or "").strip()
            for d in drafts
        }
        names.discard("")
        return len(names) <= 1
    except Exception:
        return False


# ── Label / document location helpers ─────────────────────────────────────────
# The UI never sees filesystem paths — only relative API URLs built here.

import re as _re

_SAFE_REF = _re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_SAFE_BATCH = _re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_SAFE_CLIENT_SUB = _re.compile(r"[^A-Za-z0-9_-]+")


def _safe_client(client_name: Optional[str]) -> str:
    """Filesystem-safe client token for client-scoped package filenames.

    Collapses any run of non-[A-Za-z0-9_-] to a single underscore and caps
    length. Empty/blank → "" (caller falls back to the batch-only filename).
    """
    s = _SAFE_CLIENT_SUB.sub("_", (client_name or "").strip()).strip("_")
    return s[:64]


def _carrier_root() -> Path:
    from ..core.config import settings
    return Path(settings.carrier_storage_root or (settings.storage_root / "carrier"))


# DHL shipment document kinds: URL segment → (storage subdir, filename label).
# Mirrors the live adapter's _DOC_TYPE_DIRS. The label keeps its historical
# directory so every legacy label remains downloadable unchanged.
_SHIPMENT_DOC_KINDS = {
    "label":       ("labels",            "AWB"),
    "waybill-doc": ("waybill_docs",      "WAYBILL"),
    "receipt":     ("shipment_receipts", "RECEIPT"),
    "epod":        ("epods",             "EPOD"),
}


def _shipment_doc_file(kind: str, batch_id: str, tracking_ref: str) -> Optional[Path]:
    """Resolve a saved shipment document for (kind, batch, AWB).

    Naming: {subdir}/{batch_id}-{tracking_ref}.pdf, as written by the live
    adapter's _save_shipment_documents(). Inputs are pattern-validated and
    the resolved path is confined to its directory (no traversal). None when
    absent/invalid.
    """
    if kind not in _SHIPMENT_DOC_KINDS:
        return None
    if not (isinstance(batch_id, str) and isinstance(tracking_ref, str)):
        return None
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return None
    subdir = _SHIPMENT_DOC_KINDS[kind][0]
    doc_dir = (_carrier_root() / subdir).resolve()
    candidate = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
    if candidate.parent != doc_dir or not candidate.is_file():
        return None
    return candidate


def _persist_shipment_doc(
    kind: str, batch_id: str, tracking_ref: str, pdf_bytes: bytes,
) -> Path:
    """Write PDF bytes into the existing shipment-document store.

    Same naming and containment as ``_shipment_doc_file`` / the live adapter
    label writer. Overwrite-safe (retry replaces the same confined path).
    Never accepts a caller-supplied filesystem path.
    """
    if kind not in _SHIPMENT_DOC_KINDS:
        raise ValueError(f"unknown shipment document kind {kind!r}")
    if not (isinstance(batch_id, str) and isinstance(tracking_ref, str)):
        raise ValueError("batch_id and tracking_ref are required")
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        raise ValueError("unsafe batch_id or tracking_ref")
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("file is not a PDF")
    from ..core.config import settings
    max_bytes = int(getattr(settings, "max_upload_bytes", 20 * 1024 * 1024) or (20 * 1024 * 1024))
    if len(pdf_bytes) > max_bytes:
        raise ValueError("file too large")
    subdir = _SHIPMENT_DOC_KINDS[kind][0]
    doc_dir = (_carrier_root() / subdir).resolve()
    doc_dir.mkdir(parents=True, exist_ok=True)
    candidate = (doc_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
    if candidate.parent != doc_dir:
        raise ValueError("path escape")
    candidate.write_bytes(pdf_bytes)
    return candidate


def _label_file(batch_id: str, tracking_ref: str) -> Optional[Path]:
    """Back-compat wrapper — the label is one _shipment_doc_file kind."""
    return _shipment_doc_file("label", batch_id, tracking_ref)


def _shipment_doc_urls(batch_id: str, tracking_ref: Optional[str]) -> dict:
    """Relative download URLs for every saved document of this shipment."""
    urls = {
        "label_download_url": None,
        "waybill_doc_download_url": None,
        "shipment_receipt_download_url": None,
        "epod_download_url": None,
    }
    if not tracking_ref or not isinstance(tracking_ref, str):
        return urls
    if _shipment_doc_file("label", batch_id, tracking_ref):
        urls["label_download_url"] = f"/api/v1/carrier/{batch_id}/label/{tracking_ref}"
    if _shipment_doc_file("waybill-doc", batch_id, tracking_ref):
        urls["waybill_doc_download_url"] = f"/api/v1/carrier/{batch_id}/waybill-doc/{tracking_ref}"
    if _shipment_doc_file("receipt", batch_id, tracking_ref):
        urls["shipment_receipt_download_url"] = f"/api/v1/carrier/{batch_id}/receipt/{tracking_ref}"
    if _shipment_doc_file("epod", batch_id, tracking_ref):
        urls["epod_download_url"] = f"/api/v1/carrier/{batch_id}/epod/{tracking_ref}"
    return urls


def _batch_has_any_label(batch_id: str) -> bool:
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        return False
    labels_dir = _carrier_root() / "labels"
    if not labels_dir.is_dir():
        return False
    return any(labels_dir.glob(f"{batch_id}-*.pdf"))


def _doc_package_file(batch_id: str, client_name: Optional[str] = None) -> Optional[Path]:
    """Saved commercial-document package for the batch, if one exists.

    create_label_package now PERSISTS the assembled package under
    doc_packages/ (in addition to streaming it), so this resolves the saved
    file. Client-scoped packages are written as ``{batch_id}__{safe_client}.ext``;
    when ``client_name`` is supplied we prefer that file and fall back to the
    legacy batch-only ``{batch_id}.ext`` (packages written before client scope).
    Path-confined; never returns a file outside doc_packages/.
    """
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        return None
    pkg_dir = (_carrier_root() / "doc_packages").resolve()
    if not pkg_dir.is_dir():
        return None
    names: List[str] = []
    safe_client = _safe_client(client_name)
    if safe_client:
        names += [f"{batch_id}__{safe_client}.pdf", f"{batch_id}__{safe_client}.zip"]
    names += [f"{batch_id}.pdf", f"{batch_id}.zip"]
    for name in names:
        candidate = (pkg_dir / name).resolve()
        if candidate.parent == pkg_dir and candidate.is_file():
            return candidate
    return None


_NO_STORE_HEADERS = {
    # Lesson G — download endpoints must never be cached.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


# ── Local do-not-use control ──────────────────────────────────────────────────
# Operational flag for duplicate/unused labels. This is NOT a DHL
# cancellation or void — no DHL API call is made anywhere on this path and
# the real tracking number, DB rows, and label PDFs are all preserved.

_DNU_FIELDS = {
    "do_not_use": False,
    "do_not_use_reason": None,
    "do_not_use_at": None,
    "do_not_use_by": None,
}


def _do_not_use_info(batch_id: str, tracking_ref: Optional[str]) -> dict:
    """Do-not-use flag fields for (batch, AWB) — safe defaults when unknown."""
    info = dict(_DNU_FIELDS)
    if not tracking_ref or not isinstance(tracking_ref, str):
        return info
    try:
        db_path = _get_shipment_db_path()
        shipment_db.init_db(db_path)
        row = shipment_db.get_do_not_use(db_path, batch_id, tracking_ref)
    except Exception:
        return info
    if row:
        info["do_not_use"] = bool(row.get("do_not_use"))
        info["do_not_use_reason"] = row.get("do_not_use_reason")
        info["do_not_use_at"] = row.get("do_not_use_at")
        info["do_not_use_by"] = row.get("do_not_use_by")
    return info


# ── Operator attribution ──────────────────────────────────────────────────────
# X-Operator names the operator who initiated a carrier write (AWB booking).
# It is recorded in the carrier audit trail (carrier_shipments.booked_by) so a
# booking can always be attributed to a person. Same sanitising contract as the
# rest of the app's audit actors (routes_upload._clean_operator): printable
# characters only + length cap → no audit-log injection, no unbounded values.
# Default "operator" matches routes_wfirma / routes_warehouse_receipt so a
# client that omits the header still yields a stable, non-empty booker.

def _clean_operator(x_operator: Optional[str]) -> str:
    """Sanitise the X-Operator audit actor for a carrier booking.

    Printable-only, capped at 120 chars, defaulting to 'operator'. Never
    raises; the header is untrusted input written into an audit column. A
    non-string argument (e.g. the FastAPI Header sentinel when a handler is
    unit-tested by direct call) is treated as absent.
    """
    raw = x_operator if isinstance(x_operator, str) else ""
    s = "".join(c for c in raw.strip() if c.isprintable())[:120]
    return s or "operator"


# ── Request body ──────────────────────────────────────────────────────────────


class ShipmentRequestBody(BaseModel):
    shipper_account: Optional[str] = None  # falls back to DHL_EXPRESS_ACCOUNT_NUMBER setting
    # ── DHL account authority (operator ruling 2026-07-20) ────────────────
    # Client Master owns the account, this route resolves it, the adapter only
    # sends it. Resolution goes through the canonical
    # dhl_account_resolver.resolve_dhl_billing_account() — never re-implemented
    # here, in the adapter, or in any React component.
    sender_contractor_id: Optional[str] = None
    receiver_contractor_id: Optional[str] = None
    billing_party: Optional[str] = None            # sender | receiver | third_party
    third_party_contractor_id: Optional[str] = None
    billing_account_id: Optional[int] = None       # operator's explicit pick
    recipient_address: dict
    declared_value: float
    currency: str
    weight_kg: float
    dimensions: dict
    special_instructions: Optional[str] = None
    # Upgraded AWB modal fields — all optional, defaults applied in ShipmentRequest
    product_code: Optional[str] = None        # DHL productCode; defaults to "P"
    description: Optional[str] = None         # legacy; ignored for automatic projection
    description_override: Optional[str] = None  # only when operator explicitly edits description
    customer_reference: Optional[str] = None  # proforma/order reference
    shipment_reference: Optional[str] = None  # internal batch reference
    receiver_vat_id: Optional[str] = None     # receiver EU VAT number
    receiver_eori: Optional[str] = None       # receiver EORI number
    box_type_code: Optional[str] = None       # Box Master profile selected in the modal
    client_ref: Optional[str] = None          # per-client shipment scope (draft client_name);
                                              # scopes idempotency key + row to one client so
                                              # two clients in the same batch never share an AWB
    # Optional echo only — server re-resolves from draft → CM; never invents.
    incoterm: Optional[str] = None
    # Booking provider. Default DHL. UPS is never silently converted to DHL.
    carrier: Optional[str] = None


class ExternalShipmentBody(BaseModel):
    """Customer-arranged FedEx/UPS registration — no carrier API fields."""
    provider: str
    tracking_ref: str
    client_ref: Optional[str] = None
    service_product: Optional[str] = None


def _resolve_booking_incoterm(
    *,
    storage_root,
    batch_id: str,
    client_ref: Optional[str],
) -> dict:
    """Authority for DHL booking Incoterm: saved draft → CM default → unset.

    Never invents DAP/EXW. Returns ``{"value", "source"}`` from
    ``commercial_authority.resolve_incoterm``.
    """
    from pathlib import Path as _Path
    from ..services.commercial_authority import resolve_incoterm
    from ..services import proforma_invoice_link_db as pildb
    from ..services import customer_master_db as cmdb

    draft_incoterm = None
    cm_default = None
    cid = None
    client_name = (client_ref or "").strip() or None
    pf_db = _Path(storage_root) / "proforma_links.db"
    if client_name and pf_db.exists():
        draft = pildb.get_draft(pf_db, batch_id, client_name)
        if draft is not None:
            draft_incoterm = getattr(draft, "incoterm", None)
            cid = (getattr(draft, "client_contractor_id", None) or "").strip() or None
    if cid:
        cm_path = _Path(storage_root) / "customer_master.sqlite"
        if cm_path.exists():
            try:
                cm = cmdb.get_customer(cm_path, cid)
                if cm is not None:
                    cm_default = getattr(cm, "default_incoterm", None)
            except Exception:
                cm_default = None
    return resolve_incoterm(draft_incoterm, cm_default)


def _load_draft_editable_lines(
    *,
    storage_root,
    batch_id: str,
    client_ref: Optional[str],
) -> list:
    """Read draft editable_lines for shipment description projection. Read-only."""
    import json as _json
    from pathlib import Path as _Path
    from ..services import proforma_invoice_link_db as pildb

    client_name = (client_ref or "").strip() or None
    if not client_name:
        return []
    pf_db = _Path(storage_root) / "proforma_links.db"
    if not pf_db.exists():
        return []
    draft = pildb.get_draft(pf_db, batch_id, client_name)
    if draft is None:
        return []
    try:
        lines = _json.loads(getattr(draft, "editable_lines_json", None) or "[]") or []
    except Exception:
        return []
    return lines if isinstance(lines, list) else []


def _resolve_shipment_description(
    *,
    description_override: Optional[str],
    storage_root,
    batch_id: str,
    client_ref: Optional[str],
) -> str:
    """Shipment description: explicit operator override → canonical projection → last resort.

    Canonical automatic authority is ONLY
    ``description_engine.project_shipment_content_description``.

    ``description_override`` is used solely when the operator intentionally edits
    the field. An automatically displayed canonical value must NOT be posted back
    as an override (that would let the browser become a competing mapper).

    Local ``Jewellery`` is transport last-resort only when override is absent and
    the draft has no usable item_type/description_en evidence.
    """
    from ..services.description_engine import (
        is_generic_shipment_description,
        project_shipment_content_description,
    )

    override = (description_override or "").strip()
    if override and not is_generic_shipment_description(override):
        return override

    projected = project_shipment_content_description(
        _load_draft_editable_lines(
            storage_root=storage_root,
            batch_id=batch_id,
            client_ref=client_ref,
        )
    )
    if projected:
        return projected
    # Generic override (Jewellery) or blank → still try projection first (above);
    # only then fall back for DHL's non-empty content.description contract.
    return override or "Jewellery"


def _project_shipment_description_for_client(
    *,
    storage_root,
    batch_id: str,
    client_ref: Optional[str],
) -> dict:
    """Read-only canonical projection for AWB modal display. Never books."""
    from ..services.description_engine import project_shipment_content_description

    projected = project_shipment_content_description(
        _load_draft_editable_lines(
            storage_root=storage_root,
            batch_id=batch_id,
            client_ref=client_ref,
        )
    )
    return {
        "batch_id": batch_id,
        "client_ref": (client_ref or "").strip() or None,
        "shipment_description": projected or "",
        "source": "canonical" if projected else "empty",
    }


def _carrier_address_from_delivery_authority(address: dict) -> dict:
    """Map Customer Master ``resolve_delivery_address`` shape → carrier recipient_address.

    CM authority: ``name`` = company, ``person`` = contact full name, ``country``.
    Carrier/DHL adapter: ``company`` / ``name`` (contact) / ``person`` / ``country_code``.
    Does not invent a contact person when CM ``person`` is blank.
    """
    company = (address.get("name") or address.get("company") or "").strip()
    person = (address.get("person") or "").strip()
    country = (
        address.get("country_code")
        or address.get("countryCode")
        or address.get("country")
        or ""
    ).strip()
    out = {
        "company": company,
        # Prefer person for contact; leave name empty when person missing (no invent).
        "name": person,
        "person": person,
        "street": (address.get("street") or address.get("addressLine1") or "").strip(),
        "city": (address.get("city") or address.get("cityName") or "").strip(),
        "postal_code": (
            address.get("postal_code") or address.get("postalCode") or ""
        ).strip(),
        "country_code": country,
        "phone": (address.get("phone") or "").strip(),
        "email": (address.get("email") or "").strip(),
    }
    return {k: v for k, v in out.items() if v != "" or k in ("name", "person", "company")}


# ── Routes ────────────────────────────────────────────────────────────────────


# Static DHL product catalogue — no live DHL call, no credentials required.
# Must appear before /{batch_id} routes to avoid path-parameter capture.
_DHL_SERVICES = [
    {"code": "P", "name": "Express Worldwide",             "delivery": "End of day"},
    {"code": "Y", "name": "Express 12:00",                 "delivery": "By 12:00"},
    {"code": "K", "name": "Express 9:00",                  "delivery": "By 09:00"},
    {"code": "D", "name": "Express Worldwide (Documents)", "delivery": "Documents only"},
    {"code": "T", "name": "Express Domestic",              "delivery": "Domestic service"},
]


@router.get("/dhl-account-resolution",
            summary="Resolve the DHL shipping / billing account (read-only)")
def resolve_dhl_accounts_endpoint(
    sender_contractor_id: Optional[str] = None,
    receiver_contractor_id: Optional[str] = None,
    billing_party: Optional[str] = None,
    third_party_contractor_id: Optional[str] = None,
    billing_account_id: Optional[int] = None,
    _auth: None = Depends(require_api_key),
) -> JSONResponse:
    """Pre-flight view of the account decision. Read-only — writes nothing.

    Exists so the shipment page can show the operator WHICH account will be
    used, and whether AWB creation is possible, before anything is created.
    The frontend must never derive a default itself; it asks this endpoint,
    which delegates to the ONE canonical authority
    (``dhl_account_resolver.resolve_dhl_billing_account``) and returns its
    verdict verbatim. No selection logic lives here.

    ``ok`` is the AWB-eligibility signal. Account numbers are returned masked
    only (``DHL account •••• 6789``); the full number never leaves the server.
    """
    from ..core.config import settings
    from ..services.dhl_account_resolver import (
        BILLING_SENDER,
        resolve_dhl_billing_account,
    )

    if not sender_contractor_id:
        return JSONResponse({
            "ok": False,
            "billing_party": (billing_party or BILLING_SENDER),
            "shipping_account": None, "billing_account": None,
            "choices": [], "choice_for": None,
            "reason": "sender_not_selected",
            "message": "No sender is selected for this shipment.",
            "awb_blocked": True,
        })

    resolved = resolve_dhl_billing_account(
        settings.storage_root / "customer_master.sqlite",
        sender_contractor_id,
        receiver_contractor_id,
        billing_party,
        third_party_contractor_id=third_party_contractor_id,
        selected_billing_account_id=billing_account_id,
    )

    payload = resolved.to_dict()
    # Strip the full account number from every account object — operational
    # surfaces and logs get the masked form only.
    for key in ("shipping_account", "billing_account"):
        if payload.get(key):
            payload[key].pop("account_number", None)
    for choice in payload.get("choices", []):
        choice.pop("account_number", None)

    # Sender-paid is the only billing party wired to DHL today; receiver and
    # third-party resolve for display but cannot execute (see the note on
    # _RECEIVER_BILLING_NOT_ENABLED).
    party = (billing_party or BILLING_SENDER).strip().lower()
    if resolved.ok and party != BILLING_SENDER:
        payload["awb_blocked"] = True
        payload["blocked_reason"] = "billing_party_not_enabled"
        payload["message"] = _RECEIVER_BILLING_NOT_ENABLED
    else:
        payload["awb_blocked"] = not resolved.ok

    return JSONResponse(payload)


@router.get("/services", summary="List available DHL Express product codes (static catalogue)")
def list_carrier_services(_auth: None = Depends(require_api_key)) -> JSONResponse:
    """Returns the static DHL Express product code catalogue.

    No live DHL call is made. Use this to populate the service dropdown in the AWB modal.
    Availability for a specific shipment requires a DHL /rates query (not yet implemented).
    """
    return JSONResponse(_DHL_SERVICES)


@router.get(
    "/{batch_id}/shipment-description",
    summary="Canonical AWB shipment description projection (read-only)",
)
def get_shipment_description_projection(
    batch_id: str,
    client_ref: Optional[str] = None,
    _auth: None = Depends(require_api_key),
) -> JSONResponse:
    """Return the sole automatic shipment-description projection for the AWB modal.

    Authority: draft editable_lines → description_engine.project_shipment_content_description.
    Read-only — no DHL call, no booking, no Customer/Product Master writes.
    """
    from ..core.config import settings

    return JSONResponse(
        _project_shipment_description_for_client(
            storage_root=settings.storage_root,
            batch_id=batch_id,
            client_ref=client_ref,
        )
    )


# ── DHL account resolution helper ─────────────────────────────────────────────
#
# Thin adapter over the CANONICAL resolver. It only translates the resolver's
# verdict into HTTP; it contains no account-selection logic of its own.
#
# Receiver-paid / third-party billing is resolved and surfaced (masked) so the
# operator sees the decision, but AWB creation is BLOCKED: the MyDHL REST
# `accounts[].typeCode` value for a payer entry is not yet verified against the
# official specification or a sandbox response. Guessing it would either be
# rejected by DHL or — worse — bill the wrong account. Silently falling back to
# charging the sender is explicitly forbidden.
_RECEIVER_BILLING_NOT_ENABLED = (
    "Receiver billing is configured, but DHL receiver-account billing is not "
    "yet enabled because the required MyDHL account type has not been verified."
)


def _resolve_shipment_accounts(body: "ShipmentRequestBody", settings):
    """Return ``(shipper_account, resolution_dict_or_None)``.

    Raises HTTPException(422) when the operator must choose an account, when
    the billing party owns no usable account, or when a non-sender billing
    party is selected (not yet enabled — see module note above).
    """
    from ..services.dhl_account_resolver import (
        BILLING_SENDER,
        REASON_AMBIGUOUS,
        resolve_dhl_billing_account,
    )
    # Same SQLite file the Client Master carrier-account routes own — one
    # store, one authority (routes_client_carrier_accounts.py:42).
    _CARRIER_DB = settings.storage_root / "customer_master.sqlite"

    party = (body.billing_party or BILLING_SENDER).strip().lower()

    # No client context supplied → legacy path (explicit body account, then the
    # controlled environment fallback). Unchanged behaviour for existing callers.
    if not body.sender_contractor_id:
        acct = body.shipper_account or settings.dhl_express_account_number
        if acct and not body.shipper_account:
            logger.warning(
                "dhl_account_fallback: no sender_contractor_id supplied; using "
                "DHL_EXPRESS_ACCOUNT_NUMBER environment fallback. The Client "
                "Master carrier account is the canonical authority."
            )
        return acct, None

    resolved = resolve_dhl_billing_account(
        _CARRIER_DB,
        body.sender_contractor_id,
        body.receiver_contractor_id,
        party,
        third_party_contractor_id=body.third_party_contractor_id,
        selected_billing_account_id=body.billing_account_id,
    )

    if not resolved.ok:
        # Operator must pick between several active accounts.
        if resolved.reason == REASON_AMBIGUOUS:
            raise HTTPException(status_code=422, detail={
                "error": resolved.message,
                "code": "DHL_ACCOUNT_CHOICE_REQUIRED",
                "billing_party": resolved.billing_party,
                "choice_for": resolved.choice_for,
                # Masked business display only — never the full number.
                "choices": [{"id": c.id, "account_name": c.account_name,
                             "masked": c.masked, "is_default": c.is_default}
                            for c in resolved.choices],
            })
        # Missing / invalid account for the chosen billing party → BLOCK.
        #
        # No environment fallback here, deliberately (operator ruling
        # 2026-07-20). Once a sender contractor is selected, the Client Master
        # account is the authority; silently billing DHL_EXPRESS_ACCOUNT_NUMBER
        # instead would charge an account the operator never chose. The
        # environment variable survives only for legacy callers that supply no
        # sender context at all (handled above).
        raise HTTPException(status_code=422, detail={
            "error": resolved.message,
            "code": "DHL_ACCOUNT_UNRESOLVED",
            "reason": resolved.reason,
            "billing_party": resolved.billing_party,
        })

    # Resolved. Sender-paid is the only billing party wired to DHL today.
    if party != BILLING_SENDER:
        raise HTTPException(status_code=422, detail={
            "error": _RECEIVER_BILLING_NOT_ENABLED,
            "code": "DHL_BILLING_PARTY_NOT_ENABLED",
            "billing_party": resolved.billing_party,
            # Show the operator that the account WAS resolved, masked.
            "resolved_billing_account": resolved.billing_account.masked,
        })

    return resolved.shipping_account.account_number, resolved.to_dict()


# ── Return DRAFT (Slice A) — prepare / get / patch; Live Create = HOLD ────────


class PrepareReturnBody(BaseModel):
    parent_tracking_ref: str
    client_ref: Optional[str] = None
    client_contractor_id: Optional[str] = None
    return_reason: Optional[str] = None
    pieces: Optional[int] = None
    weight_kg: Optional[float] = None
    declared_value: Optional[float] = None
    currency: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class PatchReturnBody(BaseModel):
    return_reason: Optional[str] = None
    pieces: Optional[int] = None
    weight_kg: Optional[float] = None
    declared_value: Optional[float] = None
    currency: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_country_code: Optional[str] = None
    customs_requirement_status: Optional[str] = None


@router.post(
    "/{batch_id}/return/prepare",
    summary="Prepare linked return DRAFT (no MyDHL create)",
)
def prepare_return(
    batch_id: str,
    body: PrepareReturnBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_shipments_edit,
    db_path: Path = Depends(_get_shipment_db_path),
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Create a linked return draft under carrier_shipments. Zero DHL writes."""
    from ..core.config import settings
    from ..services.carrier.return_draft_service import (
        ReturnDraftError,
        prepare_return_draft,
    )

    try:
        result = prepare_return_draft(
            storage_root=settings.storage_root,
            carrier_db_path=db_path,
            batch_id=batch_id,
            parent_tracking_ref=body.parent_tracking_ref,
            client_ref=(body.client_ref or None),
            client_contractor_id=(body.client_contractor_id or None),
            return_reason=body.return_reason,
            pieces=body.pieces,
            weight_kg=body.weight_kg,
            declared_value=body.declared_value,
            currency=body.currency,
            contact_email=body.contact_email,
            contact_phone=body.contact_phone,
            operator=_clean_operator(x_operator),
        )
    except ReturnDraftError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error": exc.message, "code": exc.code},
        ) from exc
    return JSONResponse(result)


@router.get(
    "/{batch_id}/return",
    summary="Get linked return DRAFT for batch/parent AWB",
)
def get_return(
    batch_id: str,
    parent_tracking_ref: Optional[str] = None,
    client_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    _auth: None = Depends(require_api_key),
    db_path: Path = Depends(_get_shipment_db_path),
) -> JSONResponse:
    from ..services.carrier.return_draft_service import get_return_draft_api

    draft = get_return_draft_api(
        db_path,
        batch_id=batch_id,
        parent_tracking_ref=parent_tracking_ref,
        client_ref=(client_ref or "").strip() or None,
        idempotency_key=idempotency_key,
    )
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=f"No return draft found for batch {batch_id!r}.",
        )
    return JSONResponse({"draft": draft})


@router.patch(
    "/{batch_id}/return/{idempotency_key}",
    summary="Edit linked return DRAFT (still no MyDHL create)",
)
def patch_return(
    batch_id: str,
    idempotency_key: str,
    body: PatchReturnBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_shipments_edit,
    db_path: Path = Depends(_get_shipment_db_path),
) -> JSONResponse:
    from ..services.carrier.return_draft_service import (
        ReturnDraftError,
        patch_return_draft,
    )

    try:
        draft = patch_return_draft(
            db_path,
            batch_id=batch_id,
            idempotency_key=idempotency_key,
            return_reason=body.return_reason,
            pieces=body.pieces,
            weight_kg=body.weight_kg,
            declared_value=body.declared_value,
            currency=body.currency,
            contact_email=body.contact_email,
            contact_phone=body.contact_phone,
            contact_country_code=body.contact_country_code,
            customs_requirement_status=body.customs_requirement_status,
        )
    except ReturnDraftError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error": exc.message, "code": exc.code},
        ) from exc
    return JSONResponse({"draft": draft})


@router.post(
    "/{batch_id}/return/create",
    summary="Live Create Return — HOLD (DHL capability pending)",
)
def create_return_blocked(
    batch_id: str,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
) -> JSONResponse:
    """Explicitly blocked — Slice A does not call MyDHL createShipment."""
    from ..services.carrier.return_draft_service import assert_create_return_blocked

    status, payload = assert_create_return_blocked()
    return JSONResponse(payload, status_code=status)


@router.post("/{batch_id}/shipment")
def create_shipment(
    batch_id: str,
    body: ShipmentRequestBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_create,
    coordinator: CarrierCoordinator = Depends(_get_coordinator),
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    from ..core.config import settings

    # Operator attribution — recorded as the booker in the carrier audit trail
    # (carrier_shipments.booked_by). Sanitised untrusted header input.
    operator = _clean_operator(x_operator)

    provider = shipment_db.normalize_provider_code(body.carrier or shipment_db.PROVIDER_DHL)
    if not provider:
        provider = shipment_db.PROVIDER_DHL
    if provider == "UPS":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "UPS is not configured",
                "code": "UPS_NOT_CONFIGURED",
                "guidance": "UPS has no adapter. Do not silently book DHL.",
            },
        )
    if provider == "OTHER":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "OTHER is customer-arranged only",
                "code": "OTHER_IS_EXTERNAL_ONLY",
            },
        )
    if provider not in (shipment_db.PROVIDER_DHL, "FEDEX"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Unknown booking provider {provider}",
                "code": "UNKNOWN_CARRIER",
                "guidance": "Never silently routed to DHL.",
            },
        )

    # ── DHL account resolution (operator ruling 2026-07-20) ──────────────
    #
    #   Selected Client Master account
    #   → sender default Client Master account
    #   → block
    #
    # DHL_EXPRESS_ACCOUNT_NUMBER is NOT a step in this chain. It survives only
    # for legacy callers that supply no sender contractor context at all. Once
    # a sender is selected, the Client Master account is the authority and a
    # missing account blocks — it never silently bills the environment account.
    if provider == "FEDEX":
        shipper_account = (body.shipper_account or "FEDEX").strip() or "FEDEX"
        billing_resolution = None
    else:
        shipper_account, billing_resolution = _resolve_shipment_accounts(body, settings)
        if not shipper_account:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "No DHL Express account number configured",
                    "code": "SHIPPER_ACCOUNT_MISSING",
                    "guidance": "Set DHL_EXPRESS_ACCOUNT_NUMBER in environment or pass shipper_account in request body.",
                },
            )

    # Resolve recipient address via Customer Master authority (Condition 2: feature flag)
    if settings.awb_address_authority_enabled:
        try:
            from ..services.awb_address_authority import (
                derive_awb_address_authority_with_fallback,
                CustomerNotFoundError,
                AddressMissingError
            )

            # Use authority derivation with graceful degradation (Condition 3)
            recipient_address = derive_awb_address_authority_with_fallback(
                batch_id,
                settings.storage_root,
                raw_fallback=body.recipient_address
            )

            # Map CM delivery shape (name=company, person=contact, country)
            # onto carrier recipient_address keys the DHL adapter understands.
            source = recipient_address.get('source', 'unknown')
            carrier_address = _carrier_address_from_delivery_authority(
                {k: v for k, v in recipient_address.items() if k != 'source'}
            )

            # Log address source for audit trail
            import logging
            logging.info(f"AWB {batch_id}: address authority source={source}")

        except CustomerNotFoundError as exc:
            # Condition 5: sanitized 422 error response
            raise HTTPException(status_code=422, detail={
                "error": "Customer resolution failed",
                "code": "CUSTOMER_NOT_FOUND",
                "batch_id": batch_id,
                "guidance": "Please ensure the batch has valid customer data in Customer Master or use historical batch override for batches older than 90 days"
            })
        except AddressMissingError as exc:
            # Condition 5: sanitized 422 error response
            raise HTTPException(status_code=422, detail={
                "error": "Address validation failed",
                "code": "ADDRESS_INCOMPLETE",
                "batch_id": batch_id,
                "guidance": "Please complete the customer address in Customer Master (ship-to or bill-to fields required: name, street, city, country)"
            })
    else:
        # Flag OFF = today's behavior unchanged (Condition 2)
        carrier_address = body.recipient_address

    # Incoterm: draft → Customer Master → unset. Never invent DAP.
    incoterm_res = _resolve_booking_incoterm(
        storage_root=settings.storage_root,
        batch_id=batch_id,
        client_ref=body.client_ref,
    )
    resolved_incoterm = (incoterm_res.get("value") or "").strip().upper() or None
    if provider == shipment_db.PROVIDER_DHL and not resolved_incoterm:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    "Incoterm is unset for this client. Set Customer Master."
                    "default_incoterm or save an Incoterm on the proforma draft "
                    "before booking DHL. The platform will not invent DAP."
                ),
                "code": "INCOTERM_UNSET",
                "incoterm_source": incoterm_res.get("source") or "unset",
                "guidance": (
                    "Open Client Master → Default Incoterm, or edit the draft "
                    "Incoterm field, then retry AWB booking."
                ),
            },
        )

    request = ShipmentRequest(
        batch_id=batch_id,
        shipper_account=shipper_account,
        recipient_address=carrier_address,
        declared_value=body.declared_value,
        currency=body.currency,
        weight_kg=body.weight_kg,
        dimensions=body.dimensions,
        special_instructions=body.special_instructions,
        product_code=body.product_code or "P",
        description=_resolve_shipment_description(
            description_override=body.description_override,
            storage_root=settings.storage_root,
            batch_id=batch_id,
            client_ref=body.client_ref,
        ),
        customer_reference=body.customer_reference,
        shipment_reference=body.shipment_reference,
        receiver_vat_id=body.receiver_vat_id,
        receiver_eori=body.receiver_eori,
        box_type_code=body.box_type_code,
        client_ref=(body.client_ref or None),
        incoterm=resolved_incoterm,
    )
    try:
        result = coordinator.create_shipment(
            request, operator=operator, provider=provider,
        )
    except CarrierGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Document link contract — relative API URLs only, never filesystem paths.
    doc_urls = _shipment_doc_urls(batch_id, result.tracking_ref
                                  if isinstance(result.tracking_ref, str) else None)
    commercial_documents_url = None
    if _doc_package_file(batch_id):
        commercial_documents_url = f"/api/v1/carrier/{batch_id}/documents"

    return JSONResponse({
        "batch_id": batch_id,
        "idempotency_key": result.idempotency_key,
        "mode": result.mode.value,
        "state": result.state.value,
        "tracking_ref": result.tracking_ref,
        "simulated": result.simulated,
        # Replay indicator: True when served from the stored COMPLETE row —
        # no adapter call was made, no new DHL shipment was created.
        "replayed": bool(result.replayed),
        # Operator attribution — who booked this AWB. On a replay this is the
        # ORIGINAL booker (from the stored row), not the current caller.
        # Guarded like tracking_ref/service_product above: a real result yields
        # str|None (both JSON-safe); the guard only coerces a non-str away.
        "booked_by": (result.booked_by if isinstance(result.booked_by, str) else None),
        # Local do-not-use flag (duplicate/unused label control; not a DHL void)
        **_do_not_use_info(batch_id, result.tracking_ref
                           if isinstance(result.tracking_ref, str) else None),
        **doc_urls,
        "commercial_documents_url": commercial_documents_url,
        "documents_available": commercial_documents_url is not None,
        # Legacy pre-migration rows have no stored tracking_ref; tell the UI
        # whether labels exist on the server for this batch anyway.
        "saved_labels_exist": _batch_has_any_label(batch_id),
        # AWB logistics summary — echoes the shipment intent for display.
        "carrier": provider,
        "service_code": (result.service_product if isinstance(result.service_product, str)
                         else (body.product_code or "P")),
        "box_type_code": body.box_type_code,
        "weight_kg": body.weight_kg,
        "dimensions": body.dimensions,
        "declared_value": body.declared_value,
        "currency": body.currency,
    })


def _external_shipment_payload(batch_id: str, result, db_path: Path) -> dict:
    """GET-shaped payload for an external registration (no DHL adapter fields)."""
    tracking_ref = result.tracking_ref if isinstance(result.tracking_ref, str) else None
    row = shipment_db.get_shipment(db_path, result.idempotency_key) or {}
    doc_urls = _shipment_doc_urls(batch_id, tracking_ref)
    commercial_documents_url = (
        f"/api/v1/carrier/{batch_id}/documents" if _doc_package_file(batch_id) else None
    )
    return {
        "batch_id": batch_id,
        "idempotency_key": result.idempotency_key,
        "export_shipment_id": result.idempotency_key,
        "cmr_number": cmr_document_number(result.idempotency_key),
        "client_ref": row.get("client_ref"),
        "mode": result.mode.value,
        "state": result.state.value,
        "tracking_ref": tracking_ref,
        "simulated": bool(result.simulated),
        "replayed": bool(result.replayed),
        "booked_by": (result.booked_by if isinstance(result.booked_by, str) else None),
        "carrier": row.get("provider"),
        "service_code": row.get("service_product"),
        "box_type_code": row.get("box_type_code"),
        "weight_kg": row.get("weight_kg"),
        "declared_value": row.get("declared_value"),
        "currency": row.get("currency"),
        "created_at": row.get("created_at"),
        **_do_not_use_info(batch_id, tracking_ref),
        **doc_urls,
        "commercial_documents_url": commercial_documents_url,
        "documents_available": commercial_documents_url is not None,
        "saved_labels_exist": _batch_has_any_label(batch_id),
        "error": result.error,
    }


@router.post(
    "/{batch_id}/shipment/external",
    summary="Register a customer-arranged FedEx/UPS shipment (no carrier API)",
)
def register_external_shipment_route(
    batch_id: str,
    body: ExternalShipmentBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_create,
    db_path: Path = Depends(_get_shipment_db_path),
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Persist provider + tracking on carrier_shipments. Never calls DHL/FedEx/UPS."""
    from ..core.config import settings
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        raise HTTPException(status_code=422, detail="Invalid batch_id")
    from ..services.carrier.models.shipment import normalize_tracking_ref
    tracking = normalize_tracking_ref(body.tracking_ref)
    if tracking and not _SAFE_REF.match(tracking):
        raise HTTPException(
            status_code=422,
            detail="tracking_ref must be 4–64 letters, digits, underscore or hyphen",
        )
    operator = _clean_operator(x_operator)
    try:
        result = register_external_shipment(
            db_path,
            batch_id=batch_id,
            provider=body.provider,
            tracking_ref=body.tracking_ref,
            client_ref=body.client_ref,
            operator=operator,
            service_product=body.service_product,
            master_data_db_path=settings.storage_root / "master_data.sqlite",
        )
    except CarrierGateError as exc:
        msg = str(exc)
        code = 409 if "already exists" in msg else 422
        raise HTTPException(status_code=code, detail=msg)
    return JSONResponse(_external_shipment_payload(batch_id, result, db_path))


@router.post(
    "/{batch_id}/shipment/external/document",
    summary="Upload the externally-issued AWB PDF into the existing label store",
)
async def upload_external_awb_document(
    batch_id: str,
    tracking_ref: str = Form(...),
    client_ref: Optional[str] = Form(None),
    awb_file: UploadFile = File(...),
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_create,
    db_path: Path = Depends(_get_shipment_db_path),
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Link uploaded AWB bytes to the existing shipment via the label store.

    Ownership: the shipment row for this batch + tracking must already exist
    and must be a customer-arranged (FEDEX/UPS) row. Cross-batch tracking
    numbers are rejected. Retry overwrites the same confined path.
    """
    del x_operator  # audit lives on the shipment row; upload does not re-attribute.
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        raise HTTPException(status_code=422, detail="Invalid batch_id")
    from ..services.carrier.models.shipment import normalize_tracking_ref
    tracking = normalize_tracking_ref(tracking_ref)
    if not tracking or not _SAFE_REF.match(tracking):
        raise HTTPException(status_code=422, detail="Invalid tracking_ref")

    shipment_db.init_db(db_path)
    scoped = (client_ref or "").strip() or None
    row = shipment_db.get_shipment_for_draft(
        db_path,
        batch_id,
        scoped,
        allow_single_client_fallback=not scoped,
    )
    if row is None or (row.get("tracking_ref") or "") != tracking:
        # Exact tracking match on this batch (client-scoped row may be missing
        # when the operator omitted client_ref on register).
        with_ref = shipment_db.get_shipment_by_tracking_ref(db_path, tracking)
        if with_ref is None:
            raise HTTPException(
                status_code=404,
                detail="No external shipment found for this batch and tracking number.",
            )
        if with_ref.get("batch_id") != batch_id:
            raise HTTPException(
                status_code=409,
                detail="tracking_ref belongs to a different batch.",
            )
        row = with_ref

    if (row.get("tracking_ref") or "") != tracking:
        raise HTTPException(
            status_code=404,
            detail="No external shipment found for this batch and tracking number.",
        )
    if row.get("batch_id") != batch_id:
        raise HTTPException(
            status_code=409,
            detail="tracking_ref belongs to a different batch.",
        )
    provider = (row.get("provider") or "").strip().upper()
    if provider not in shipment_db.EXTERNAL_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail="AWB upload on this path is only for customer-arranged FedEx/UPS shipments.",
        )
    if scoped and row.get("client_ref") and row.get("client_ref") != scoped:
        raise HTTPException(
            status_code=409,
            detail="Shipment belongs to a different client in this batch.",
        )

    content = await awb_file.read()
    try:
        _persist_shipment_doc("label", batch_id, tracking, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result_row = shipment_db.get_shipment(db_path, row["idempotency_key"])
    from ..services.carrier.models.shipment import ShipmentMode, ShipmentResult, ShipmentState
    fake = ShipmentResult(
        idempotency_key=row["idempotency_key"],
        mode=ShipmentMode(result_row["mode"] if result_row else "external"),
        state=ShipmentState(result_row["state"] if result_row else "complete"),
        tracking_ref=tracking,
        simulated=False,
        booked_by=(result_row or {}).get("booked_by"),
        replayed=True,
        service_product=(result_row or {}).get("service_product"),
    )
    payload = _external_shipment_payload(batch_id, fake, db_path)
    payload["awb_document_saved"] = True
    return JSONResponse(payload)


@router.get("/{batch_id}/shipment")
def get_shipment(
    batch_id: str,
    client_ref: Optional[str] = None,
    _auth: None = Depends(require_api_key),
    _config: CarrierConfig = Depends(_get_carrier_config),
    db_path: Path = Depends(_get_shipment_db_path),
) -> JSONResponse:
    shipment_db.init_db(db_path)
    # Per-client resolution — a shipment belongs to ONE client's draft, never to
    # "the latest row for the whole batch" (2026-07-16 cross-client AWB leak).
    # An exact (batch_id, client_ref) row is always safe; a legacy NULL-client_ref
    # row is attributed only when the batch is unambiguously single-client.
    _client = (client_ref or "").strip() or None
    row = shipment_db.get_shipment_for_draft(
        db_path,
        batch_id,
        _client,
        allow_single_client_fallback=_batch_not_multi_client(batch_id),
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No shipment linked to this client for batch {batch_id!r}."
                if _client else
                f"No shipment found for batch {batch_id!r}."
            ),
        )

    tracking_ref = row.get("tracking_ref")
    doc_urls = _shipment_doc_urls(batch_id, tracking_ref)
    commercial_documents_url = (
        f"/api/v1/carrier/{batch_id}/documents" if _doc_package_file(batch_id) else None
    )

    import json as _json
    dimensions = None
    if row.get("dimensions_json"):
        try:
            dimensions = _json.loads(row["dimensions_json"])
        except (TypeError, ValueError):
            dimensions = None

    return JSONResponse({
        "batch_id": row["batch_id"],
        "idempotency_key": row["idempotency_key"],
        # PR-5: the carrier shipment's own stable identifier, surfaced explicitly as
        # the export shipment reference. It is the carrier_shipments primary key
        # (one row per idempotency_key); a same-request re-book updates this row's
        # tracking_ref (the AWB) in place, so the AWB changes while this stable id
        # does not. This is the canonical source for the CMR document number —
        # NEVER batch_id and NEVER tracking_ref.
        "export_shipment_id": row["idempotency_key"],
        # Short, deterministic CMR document number derived from export_shipment_id
        # (ADR-proforma-cmr-short-number). The full id above stays as audit
        # provenance; only this short form is printed on the CMR. Independent of
        # the AWB; rebook-stable; NEVER batch_id.
        "cmr_number": cmr_document_number(row["idempotency_key"]),
        # Per-client shipment scope (draft client_name); null for legacy rows.
        "client_ref": row.get("client_ref"),
        "mode": row["mode"],
        "state": row["state"],
        "simulated": bool(row["simulated"]),
        "error": row["error"],
        # AWB logistics/document visibility (all additive)
        "tracking_ref": tracking_ref,
        # Carrier owning this shipment, from carrier_shipments.provider.
        # shipment_db._row() already resolved a legacy NULL to DHL, so this is
        # never blank and no consumer needs a fallback of its own.
        "carrier": row.get("provider"),
        "service_code": row.get("service_product"),
        "box_type_code": row.get("box_type_code"),
        "weight_kg": row.get("weight_kg"),
        "dimensions": dimensions,
        "declared_value": row.get("declared_value"),
        "currency": row.get("currency"),
        "created_at": row.get("created_at"),
        # Operator attribution — who booked this AWB (null for legacy rows).
        "booked_by": row.get("booked_by"),
        # Local do-not-use flag (duplicate/unused label control; not a DHL void)
        **_do_not_use_info(batch_id, tracking_ref),
        **doc_urls,
        "commercial_documents_url": commercial_documents_url,
        "documents_available": commercial_documents_url is not None,
        "saved_labels_exist": _batch_has_any_label(batch_id),
    })


@router.get(
    "/{batch_id}/shipment/legacy-probe",
    summary="Probe for a legacy (pre-client_ref) shipment row before re-booking",
)
def probe_legacy_shipment(
    batch_id: str,
    client_ref: Optional[str] = None,
    _auth: None = Depends(require_api_key),
    db_path: Path = Depends(_get_shipment_db_path),
) -> JSONResponse:
    """Read-only pre-booking probe (ADR-proforma-cmr-short-number §Known
    limitation).

    A batch booked BEFORE client-scoped idempotency keys carries a legacy
    row with NULL client_ref; a re-book that now sends client_ref computes a
    NEW key, so the coordinator's completed-key replay will not match — a new
    shipment record (and, in live mode, a new DHL booking) would be created
    alongside the legacy row. The V2 AWB modal calls this before booking and
    blocks on explicit operator confirmation when legacy_exists is true.

    When the optional client_ref query param is sent, the response also
    carries has_client_row: whether a non-failed row scoped to EXACTLY that
    client already exists for the batch. If it does, a same-params re-book
    replays that row (per-client key match) — no new record — so the modal
    suppresses the warning (reviewer-challenge MEDIUM-2, 2026-07-16). The
    legacy row is deliberately never mutated; suppression is read-side only.
    Without the param the response shape is unchanged (no has_client_row key).

    Deliberately NOT behind _get_carrier_config: the answer comes from the
    local shipment DB only. Never mutates state, never calls DHL, and never
    cancels/voids anything.
    """
    cr = (client_ref or "").strip() or None
    # Defensive-depth consistency with the other handlers in this file: a
    # malformed batch_id cannot name a real batch, so answer honestly-false.
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        body = {"batch_id": batch_id, "legacy_exists": False}
        if cr:
            body["has_client_row"] = False
        return JSONResponse(body)
    shipment_db.init_db(db_path)
    extra = {}
    if cr:
        extra["has_client_row"] = (
            shipment_db.get_client_shipment(db_path, batch_id, cr) is not None
        )
    row = shipment_db.get_legacy_shipment(db_path, batch_id)
    if row is None:
        return JSONResponse({"batch_id": batch_id, "legacy_exists": False, **extra})
    return JSONResponse({
        "batch_id": batch_id,
        "legacy_exists": True,
        "tracking_ref": row.get("tracking_ref"),
        "state": row.get("state"),
        "created_at": row.get("created_at"),
        **extra,
    })


# ── Local do-not-use marking ──────────────────────────────────────────────────


class DoNotUseBody(BaseModel):
    reason: str                      # mandatory audit reason (e.g. "duplicate of 7010522735")
    operator: Optional[str] = None   # who marked it, when the UI knows


@router.post(
    "/{batch_id}/shipment/{tracking_ref}/do-not-use",
    summary="Mark an AWB label as DO NOT USE (local operational flag — NOT a DHL cancellation)",
)
def mark_shipment_do_not_use(
    batch_id: str,
    tracking_ref: str,
    body: DoNotUseBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_label,
    db_path: Path = Depends(_get_shipment_db_path),
    x_operator: Optional[str] = Header(None, alias="X-Operator"),
) -> JSONResponse:
    """Set the local do-not-use flag on a recorded shipment.

    This does not cancel anything at DHL — no DHL API call is made, the
    tracking number is unchanged, and the label PDFs stay on disk for audit.
    It only marks the label so operators do not print it or hand it to the
    courier. Marked labels remain downloadable via ?archived=true.

    Operator attribution (stored in do_not_use_by): the request body's
    ``operator`` field takes precedence; the app-standard ``X-Operator`` header
    is the fallback. Both are sanitised; when neither is present the field is
    left NULL (attribution genuinely unknown — never fabricated).
    """
    if not (_SAFE_BATCH.match(batch_id or "") and _SAFE_REF.match(tracking_ref or "")):
        raise HTTPException(status_code=404, detail="Unknown batch or tracking reference.")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=422,
            detail="A reason is required to mark a label as do-not-use (audit trail).",
        )
    hdr_operator = (x_operator or "").strip() if isinstance(x_operator, str) else ""
    raw_operator = (body.operator or "").strip() or hdr_operator
    operator = _clean_operator(raw_operator) if raw_operator else None
    shipment_db.init_db(db_path)
    marked = shipment_db.mark_do_not_use(
        db_path, batch_id, tracking_ref, reason,
        operator=operator,
    )
    if marked == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No recorded shipment for batch {batch_id!r} AWB {tracking_ref!r} — "
                "nothing was marked."
            ),
        )
    return JSONResponse({
        "batch_id": batch_id,
        "tracking_ref": tracking_ref,
        "marked_rows": marked,
        "dhl_api_called": False,   # explicit: local flag only, never a DHL void
        **_do_not_use_info(batch_id, tracking_ref),
    })


# ── Path-DOC: label package ────────────────────────────────────────────────────


class LabelPackageBody(BaseModel):
    """Request body for POST /api/v1/carrier/{batch_id}/label-package.

    Dimensions and tare weight are resolved from the box_types master table
    by box_type_id (operator selects a pre-defined box at label time).
    Total package weight = sum(packing_lines.gross_weight) + box.tare_weight_kg.
    """
    box_type_id:   int               # required; resolved to dims + tare from box_types
    incoterm:      Optional[str]  = None
    receiver_eori: Optional[str]  = None
    client_name:   Optional[str]  = None


@router.post(
    "/{batch_id}/label-package",
    summary="Path-DOC: generate outbound customs/shipping document package (WF4.5)",
    description=(
        "UNGATED — no carrier_api_status / creds / allowlist check. "
        "Returns a PDF or ZIP containing: commercial invoice (from wFirma, read-only) "
        "+ packing list (generated) + CN23 (generated, non-EU only). "
        "Mandatory: box_type_id (resolved to dims+tare from box_types master). "
        "Non-EU also requires incoterm + receiver_eori. "
        "Receiver address: ship_to_* primary; bill_to_* fallback + advisory. "
        "Soft gaps (blank address, zero weight) are returned as advisories "
        "and do NOT block generation. "
        "422 {gaps:[...]} when mandatory inputs are missing. "
        "The assembled package is PERSISTED under doc_packages/ "
        "({batch}__{client}.pdf|zip) as well as streamed, so it is downloadable "
        "afterwards and appears in the Shipment Document Hub manifest."
    ),
)
async def create_label_package(
    batch_id: str,
    body: LabelPackageBody,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_label,
) -> Response:
    """Generate the Path-DOC outbound document package for a batch."""
    try:
        from ..services.carrier.doc_package import (
            LabelPackageInputs,
            LabelPackageGaps,
            LabelPackageResult,
            assemble_label_package,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"doc_package unavailable: {exc}", "code": "DOC_PKG_MISSING"},
        ) from exc

    from ..core.config import settings as _settings

    # Resolve box type → dimensions + tare
    try:
        from ..services.master_data_db import get_box_type, init_db as _init_md
        md_db = _settings.storage_root / "master_data.sqlite"
        _init_md(md_db)
        box = get_box_type(md_db, body.box_type_id)
    except Exception as _box_exc:
        box = None

    if box is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Missing mandatory inputs for label package",
                "code":  "LABEL_PACKAGE_GAPS",
                "gaps":  [{"field": "box_type",
                            "reason": (
                                f"box_type_id={body.box_type_id!r} not found in box_types master "
                                "or box_types table is empty. "
                                "Add box types via the master-data API before generating labels."
                            )}],
            },
        )

    inputs = LabelPackageInputs(
        length_cm      = float(box.length_cm or 0),
        width_cm       = float(box.width_cm  or 0),
        height_cm      = float(box.height_cm or 0),
        tare_weight_kg = float(box.tare_weight_kg or 0),
        incoterm       = (body.incoterm or "").strip() or None,
        receiver_eori  = (body.receiver_eori or "").strip() or None,
        client_name    = (body.client_name or "").strip() or None,
    )
    # Fill blank Incoterm from draft → CM authority (never invent DAP).
    if not inputs.incoterm and inputs.client_name:
        _ires = _resolve_booking_incoterm(
            storage_root=_settings.storage_root,
            batch_id=batch_id,
            client_ref=inputs.client_name,
        )
        inputs.incoterm = (_ires.get("value") or None)

    result = assemble_label_package(
        batch_id     = batch_id,
        inputs       = inputs,
        storage_root = _settings.storage_root,
    )

    if isinstance(result, LabelPackageGaps):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Missing mandatory inputs for label package",
                "code":  "LABEL_PACKAGE_GAPS",
                "gaps":  result.gaps,
            },
        )

    # LabelPackageResult — PERSIST the assembled package so it is downloadable
    # later (GET /{batch_id}/documents) and visible to the Shipment Document Hub
    # manifest, THEN stream it. Persistence is best-effort: a write failure must
    # never break the streaming response the operator is waiting on. Client-
    # scoped filename ({batch}__{safe_client}.ext) when a client is known, so
    # two clients in the same batch never overwrite each other's package;
    # otherwise the legacy batch-only filename.
    try:
        pkg_ext = "zip" if "zip" in (result.content_type or "").lower() else "pdf"
        pkg_dir = _carrier_root() / "doc_packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        safe_client = _safe_client(inputs.client_name)
        pkg_name = (
            f"{batch_id}__{safe_client}.{pkg_ext}" if safe_client
            else f"{batch_id}.{pkg_ext}"
        )
        (pkg_dir / pkg_name).write_bytes(result.content)
    except Exception as _persist_exc:
        logger.warning(
            "label-package persist failed for batch %s: %s", batch_id, _persist_exc,
        )

    headers = {"Content-Disposition": f'attachment; filename="{result.filename}"'}
    if result.advisories:
        # Surface advisories in a custom header (JSON-encoded list)
        import json as _json
        headers["X-Label-Advisories"] = _json.dumps(result.advisories)
    return Response(
        content      = result.content,
        media_type   = result.content_type,
        headers      = headers,
    )


# ── Label / document downloads ───────────────────────────────────────────────


def _serve_shipment_doc(
    kind: str, batch_id: str, tracking_ref: str, archived: bool = False,
) -> Response:
    """Serve one saved DHL shipment document as an attachment PDF.

    Pattern-validated + path-confined; filesystem paths never exposed;
    Lesson-G no-store headers. 404 when the document does not exist.

    Labels marked do-not-use are blocked from the primary download (409) so
    a duplicate/unused label is not printed or handed to DHL by accident.
    ?archived=true keeps them retrievable for audit — the file is never
    deleted — with an ARCHIVED-DUPLICATE filename so a printout is
    unmistakable.
    """
    doc = _shipment_doc_file(kind, batch_id, tracking_ref)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved {kind} document for batch {batch_id!r} AWB {tracking_ref!r}.",
        )
    prefix = _SHIPMENT_DOC_KINDS[kind][1]
    dnu = _do_not_use_info(batch_id, tracking_ref)
    if dnu["do_not_use"] and not archived:
        raise HTTPException(
            status_code=409,
            detail=(
                f"AWB {tracking_ref} is marked DO NOT USE "
                f"({dnu['do_not_use_reason'] or 'duplicate/unused label'}). "
                "Do not print or hand this label to the courier. "
                "For audit retrieval, download it as an archived duplicate label "
                "(?archived=true)."
            ),
        )
    if dnu["do_not_use"]:
        prefix = f"ARCHIVED-DUPLICATE-{prefix}"
    return Response(
        content=doc.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{prefix}-{tracking_ref}.pdf"',
            **_NO_STORE_HEADERS,
        },
    )


@router.get(
    "/{batch_id}/label/{tracking_ref}",
    summary="Download the saved DHL transport label PDF for a batch AWB",
)
def download_label(
    batch_id: str,
    tracking_ref: str,
    archived: bool = False,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the transport label PDF saved at AWB creation time."""
    return _serve_shipment_doc("label", batch_id, tracking_ref, archived=archived)


@router.get(
    "/{batch_id}/waybill-doc/{tracking_ref}",
    summary="Download the saved DHL waybill document (hand to courier)",
)
def download_waybill_doc(
    batch_id: str,
    tracking_ref: str,
    archived: bool = False,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the waybill document PDF saved at AWB creation time."""
    return _serve_shipment_doc("waybill-doc", batch_id, tracking_ref, archived=archived)


@router.get(
    "/{batch_id}/receipt/{tracking_ref}",
    summary="Download the saved DHL shipment receipt PDF",
)
def download_shipment_receipt(
    batch_id: str,
    tracking_ref: str,
    archived: bool = False,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the shipment receipt PDF saved at AWB creation time."""
    return _serve_shipment_doc("receipt", batch_id, tracking_ref, archived=archived)


@router.get(
    "/{batch_id}/epod/{tracking_ref}",
    summary="Download the saved MyDHL electronic proof of delivery (ePOD)",
)
def download_epod(
    batch_id: str,
    tracking_ref: str,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve a persisted MyDHL ePOD PDF (carrier proof — not customer receipt).

    Does not apply label do-not-use blocking: ePOD is a post-delivery evidence
    document, not a print-to-courier label.
    """
    doc = _shipment_doc_file("epod", batch_id, tracking_ref)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved ePOD for batch {batch_id!r} AWB {tracking_ref!r}.",
        )
    return Response(
        content=doc.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="EPOD-{tracking_ref}.pdf"',
            **_NO_STORE_HEADERS,
        },
    )


@router.post(
    "/{batch_id}/waybill-doc/{tracking_ref}/fetch",
    summary="Fetch MyDHL waybill via Get Image and persist (best-effort)",
)
def fetch_waybill_doc(
    batch_id: str,
    tracking_ref: str,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_docs,
) -> JSONResponse:
    """Operator-triggered waybill recovery via MyDHL Get Image.

    200 when present/persisted; 404 when DHL has no image; 403 when the
    account is not entitled to Get Image (honest not-provided).
    """
    from ..services.carrier.document_image_service import ensure_waybill_persisted

    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        raise HTTPException(status_code=400, detail="invalid batch_id")
    if not (isinstance(tracking_ref, str) and _SAFE_REF.match(tracking_ref)):
        raise HTTPException(status_code=400, detail="invalid tracking_ref")

    outcome = ensure_waybill_persisted(batch_id, tracking_ref)
    if outcome.status in ("present", "persisted"):
        return JSONResponse({
            "ok": True,
            "batch_id": batch_id,
            "tracking_ref": tracking_ref,
            "status": outcome.status,
            "download_url": f"/api/v1/carrier/{batch_id}/waybill-doc/{tracking_ref}",
        })
    if outcome.status == "not_authorized":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "MyDHL Get Image not authorized for this account.",
                "code": "WAYBILL_NOT_AUTHORIZED",
                "detail": outcome.detail,
            },
        )
    if outcome.status == "not_found":
        raise HTTPException(
            status_code=404,
            detail={
                "error": "MyDHL has no waybill image for this AWB.",
                "code": "WAYBILL_NOT_FOUND",
            },
        )
    raise HTTPException(
        status_code=502,
        detail={
            "error": "Waybill recovery failed.",
            "code": "WAYBILL_FETCH_FAILED",
            "detail": outcome.detail,
        },
    )


@router.post(
    "/{batch_id}/epod/{tracking_ref}/fetch",
    summary="Fetch MyDHL ePOD and persist it (best-effort)",
)
def fetch_epod(
    batch_id: str,
    tracking_ref: str,
    _auth: None = Depends(require_api_key),
    _op_auth: None = Depends(require_role("admin", "logistics")),
    _perm: None = _perm_awb_docs,
) -> JSONResponse:
    """Operator-triggered ePOD pull. Idempotent; 404 when MyDHL has no ePOD."""
    from ..services.carrier.epod_service import ensure_epod_persisted, epod_file_path

    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        raise HTTPException(status_code=400, detail="invalid batch_id")
    if not (isinstance(tracking_ref, str) and _SAFE_REF.match(tracking_ref)):
        raise HTTPException(status_code=400, detail="invalid tracking_ref")

    path = ensure_epod_persisted(batch_id, tracking_ref)
    if path is None:
        # Distinguish "already checked / still missing" from bad input.
        if epod_file_path(batch_id, tracking_ref) is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "MyDHL ePOD is not available for this AWB "
                    "(not delivered yet, account not entitled, or fetch failed)."
                ),
            )
    return JSONResponse({
        "ok": True,
        "batch_id": batch_id,
        "tracking_ref": tracking_ref,
        "download_url": f"/api/v1/carrier/{batch_id}/epod/{tracking_ref}",
    })


@router.get(
    "/{batch_id}/documents",
    summary="Download the saved commercial-document package for a batch",
)
def download_commercial_documents(
    batch_id: str,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the saved commercial-document package (invoice + packing list +
    CN23) when one has been persisted. 404 when none exists — Path-DOC
    packages generated via POST /label-package are streamed, not saved."""
    pkg = _doc_package_file(batch_id)
    if pkg is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved commercial-document package for batch {batch_id!r}.",
        )
    media = "application/zip" if pkg.suffix == ".zip" else "application/pdf"
    return Response(
        content=pkg.read_bytes(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="DOCS-{batch_id}{pkg.suffix}"',
            **_NO_STORE_HEADERS,
        },
    )

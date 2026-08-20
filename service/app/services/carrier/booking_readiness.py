"""Booking-readiness projection — a READ over authorities that already exist.

Nothing here persists. There is no readiness store, no second shipment DB, no
second tracking authority and no new weight/recipient/box/package authority:
every fact below is read from the module that already owns it, and anything
that cannot be read is reported as missing rather than guessed.

Shipment legs
-------------
An import batch is not one shipment. It carries:

* the **inbound supplier leg** — the AWB the supplier booked, uploaded at
  intake. It belongs to tracking / customs / warehouse and is never re-booked
  here. Projected by ``dhl_logistics_projector.project_inbound_row``.
* zero or more **outbound customer intents** — one per proforma draft, scoped
  by ``(batch_id, client_ref)``. Each has its own recipient, packages and
  release state, so two customers inside one import batch stay independently
  scoped. That is exactly what the carrier idempotency model's ``client_ref``
  already represents; this module reads it, it does not invent it.

``batch_id`` alone therefore never identifies a shipment, and "this batch is
inbound" never means "no outbound shipment may be prepared".

Blockers vs advisories (Lesson N / Lesson R)
--------------------------------------------
``blockers`` carries only conditions that already fail the booking POST closed
today — an unresolvable recipient, a missing measured weight, a missing
declared value, an unset Incoterm, an unresolvable carrier account. Everything
else is an ``advisory``: surfaced to the operator, never a gate. Warehouse
receipt is advisory by authority (Lesson R: WAREHOUSE may hard-block on
quantity risk only), so a pending receipt is disclosed and does NOT disable
preparation.

``release`` is a SEPARATE axis from ``booking``. A shipment can be fully
prepared and business-ready while live production writing is still not
released for it. That is the normal state, not an error.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Authority owners — every one of these is read, none is re-implemented.
from ...services import proforma_invoice_link_db as pildb
from ...services.carrier.persistence import shipment_db

# Lesson R rule 1: every structured blocker names the authority that owns it.
AUTH_PROFORMA = "PROFORMA"
AUTH_SALES = "SALES"
AUTH_WAREHOUSE = "WAREHOUSE"
AUTH_IMPORT_PZ = "IMPORT_PZ"

INTENT_INBOUND_EXISTING = "inbound_existing"
INTENT_OUTBOUND_CUSTOMER = "outbound_customer"


def _reason(code: str, message: str, authority: str) -> Dict[str, str]:
    return {"code": code, "message": message, "authority": authority}


def _audit_path(storage_root: Path, batch_id: str) -> Path:
    return Path(storage_root) / "outputs" / batch_id / "audit.json"


def _read_audit(storage_root: Path, batch_id: str) -> Optional[Dict[str, Any]]:
    path = _audit_path(storage_root, batch_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ── Inbound supplier leg ─────────────────────────────────────────────────────


def project_inbound_leg(batch_id: str, *, storage_root: Path) -> Optional[Dict[str, Any]]:
    """The supplier's existing AWB for this import batch, or None.

    Read straight from the batch audit through the existing inbound logistics
    projector — this module adds no tracking authority of its own. Returns None
    when the batch carries no inbound AWB (nothing to protect).
    """
    audit = _read_audit(storage_root, batch_id)
    if not audit:
        return None
    from ...services.dhl_logistics_projector import project_inbound_row

    try:
        row = project_inbound_row(audit)
    except Exception:  # a tracking read must never break a readiness read
        row = None
    if not row:
        awb = str(audit.get("awb") or audit.get("tracking_no") or "").strip()
        if not awb:
            return None
        return {
            "awb": awb,
            "provider": str(audit.get("carrier") or "").strip().upper() or None,
            "stage": None,
            "status": None,
            "location": None,
            "projection_available": False,
        }
    return {
        "awb": row.get("awb"),
        "provider": (row.get("carrier") or None),
        "stage": row.get("current_stage"),
        "stage_label": row.get("current_stage_label"),
        "status": row.get("current_status"),
        "location": row.get("current_location"),
        "customs_status": row.get("customs_status"),
        "delivered_at_utc": row.get("delivered_at_utc"),
        "projection_available": True,
    }


# ── Outbound customer intents ────────────────────────────────────────────────


def resolve_outbound_intents(
    batch_id: str,
    *,
    proforma_db_path: Path,
    client_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Every outbound customer intent on this batch, newest draft state included.

    An intent is a proforma draft: ``client_ref`` is its ``client_name``, which
    is the same value the carrier idempotency key already scopes a shipment by.
    Passing ``client_ref`` narrows to that one customer; omitting it lists all,
    so the caller can see that one import batch legitimately carries several.
    Cancelled drafts are not shipment intents and are excluded.
    """
    try:
        drafts = pildb.list_drafts_for_batch(proforma_db_path, batch_id)
    except Exception:
        drafts = []
    wanted = (client_ref or "").strip()
    out: List[Dict[str, Any]] = []
    for d in drafts:
        name = (getattr(d, "client_name", "") or "").strip()
        if wanted and name != wanted:
            continue
        if (getattr(d, "draft_state", "") or "").lower() == "cancelled":
            continue
        out.append({
            "draft_id": getattr(d, "id", None),
            "client_ref": name or None,
            "client_contractor_id": getattr(d, "client_contractor_id", None),
            "draft_state": getattr(d, "draft_state", None),
            "currency": getattr(d, "currency", None),
            "box_type_code": getattr(d, "box_type_code", None),
            "manual_gross_weight": getattr(d, "manual_gross_weight", None),
            "updated_at": getattr(d, "updated_at", None),
        })
    return out


def has_outbound_customer_scope(
    batch_id: str,
    *,
    proforma_db_path: Path,
    client_ref: Optional[str] = None,
) -> bool:
    """True when a real outbound customer intent exists for this booking scope.

    The server-side leg check. A request that resolves to no customer intent at
    all is a request to re-book the batch itself — i.e. the supplier's inbound
    leg — and must fail before any carrier adapter is reached.
    """
    return bool(resolve_outbound_intents(
        batch_id, proforma_db_path=proforma_db_path, client_ref=client_ref,
    ))


# ── Full readiness projection ────────────────────────────────────────────────


def _measured(value: Any) -> Optional[float]:
    """A positive number, or None. Zero is a MISSING measurement, never a fact."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _recipient_state(batch_id: str, storage_root: Path, client_ref: Optional[str]) -> Dict[str, Any]:
    """Ask the ONE recipient authority the booking itself asks (Customer Master)."""
    from ...services.awb_address_authority import (
        derive_awb_address_authority,
        AddressMissingError,
        CustomerNotFoundError,
    )
    try:
        address = derive_awb_address_authority(
            batch_id, storage_root, client_ref=client_ref,
        )
    except CustomerNotFoundError:
        return {"ready": False, "source": None, "blocker": _reason(
            "CUSTOMER_NOT_FOUND",
            "Customer Master has no contractor mapped to this outbound client. "
            "Map it in Client Master — the AWB never falls back to a typed address.",
            AUTH_PROFORMA)}
    except AddressMissingError:
        return {"ready": False, "source": None, "blocker": _reason(
            "ADDRESS_INCOMPLETE",
            "The mapped customer has no complete delivery address "
            "(name, street, city and country are required).",
            AUTH_PROFORMA)}
    except Exception as exc:
        return {"ready": False, "source": None, "blocker": _reason(
            "RECIPIENT_UNRESOLVED", f"Recipient could not be resolved: {exc}",
            AUTH_PROFORMA)}
    return {
        "ready": True,
        "source": address.get("source"),
        "company": address.get("name"),
        "city": address.get("city"),
        "country": address.get("country") or address.get("country_code"),
        "phone": (address.get("phone") or "") or None,
        "blocker": None,
    }


def _warehouse_state(batch_id: str) -> Dict[str, Any]:
    """Operator quantity confirmation (Lesson R: advisory, never a hard gate)."""
    try:
        from ...services.warehouse_receipt import get_receipt_status
        status = get_receipt_status(batch_id)
    except Exception:
        return {"required": True, "confirmed": None, "state": "unknown",
                "total_lines": None, "confirmed_lines": None}
    total = status.get("total_lines") or 0
    return {
        "required": bool(total),
        "confirmed": bool(status.get("fully_confirmed")),
        "state": ("confirmed" if status.get("fully_confirmed")
                  else ("pending" if total else "not_applicable")),
        "total_lines": total,
        "confirmed_lines": status.get("confirmed_lines"),
        "serial_controlled": bool(status.get("serial_controlled")),
    }


def _release_state(batch_id: str, settings) -> Dict[str, Any]:
    """Live-release state. NEVER suggests widening the allowlist."""
    # Parsed exactly as DhlExpressLiveAdapter.__init__ parses it, so the
    # preflight and the gate can never disagree about the same string
    # (pinned by test_booking_readiness_allowlist_matches_the_live_gate).
    raw = getattr(settings, "carrier_live_allowlist", "") or ""
    allowlist = {b.strip() for b in str(raw).split(",") if b.strip()}
    status = (getattr(settings, "carrier_api_status", "") or "").strip().lower()
    allowlisted = bool(allowlist) and (batch_id in allowlist or "*" in allowlist)
    return {
        "carrier_api_status": status or None,
        "live_allowlisted": allowlisted,
        "production_write_ready": bool(allowlisted and status == "live"),
        "reason": (None if allowlisted else
                   "Live booking is not released for this shipment. Release this "
                   "specific shipment through the governed live-booking process."),
    }


def project_booking_readiness(
    batch_id: str,
    *,
    storage_root: Path,
    proforma_db_path: Path,
    shipment_db_path: Path,
    settings,
    client_ref: Optional[str] = None,
    provider: str = "DHL",
    weight_kg: Any = None,
    declared_value: Any = None,
    packages_count: Any = None,
) -> Dict[str, Any]:
    """Compose one operator-facing readiness answer for ONE shipment leg.

    ``weight_kg`` / ``declared_value`` / ``packages_count`` are the values the
    caller resolved through their own existing authorities (the proforma weight
    authority, the draft total, the package split). They are validated here, not
    re-derived: re-deriving them would fork those authorities. Omitted values
    fall back to what the draft itself persists, and an unresolvable value is
    reported missing rather than assumed.
    """
    provider = (provider or "DHL").strip().upper() or "DHL"
    inbound = project_inbound_leg(batch_id, storage_root=storage_root)
    intents = resolve_outbound_intents(
        batch_id, proforma_db_path=proforma_db_path, client_ref=client_ref,
    )
    scoped = intents[0] if (client_ref and intents) else (intents[0] if len(intents) == 1 else None)

    blockers: List[Dict[str, str]] = []
    advisories: List[Dict[str, str]] = []

    # ── Which leg is the operator looking at? ────────────────────────────────
    if not intents:
        intent = INTENT_INBOUND_EXISTING if inbound else INTENT_OUTBOUND_CUSTOMER
        blockers.append(_reason(
            "NO_OUTBOUND_CUSTOMER_INTENT",
            "This batch carries no outbound customer proforma to ship. The "
            "existing AWB belongs to the inbound supplier leg and is tracked, "
            "not re-booked.",
            AUTH_SALES))
    else:
        intent = INTENT_OUTBOUND_CUSTOMER
        if client_ref is None and len(intents) > 1:
            blockers.append(_reason(
                "OUTBOUND_SCOPE_AMBIGUOUS",
                f"This import batch carries {len(intents)} customer proformas. "
                "Choose which customer's shipment to prepare — a batch is not a "
                "shipment.",
                AUTH_SALES))

    # ── Recipient (Customer Master, via the outbound client scope) ───────────
    if intent == INTENT_OUTBOUND_CUSTOMER and intents:
        recipient = _recipient_state(
            batch_id, storage_root,
            (client_ref or (scoped or {}).get("client_ref")),
        )
    else:
        recipient = {"ready": False, "source": None, "blocker": None}
    if recipient.get("blocker"):
        blockers.append(recipient["blocker"])

    # ── Warehouse receipt — advisory by authority ───────────────────────────
    warehouse = _warehouse_state(batch_id)
    if warehouse["required"] and warehouse["state"] == "pending":
        advisories.append(_reason(
            "WAREHOUSE_RECEIPT_PENDING",
            f"Warehouse receipt pending — {warehouse['confirmed_lines']} of "
            f"{warehouse['total_lines']} lines confirmed.",
            AUTH_WAREHOUSE))

    # ── Weight (proforma weight authority; zero is never a measurement) ──────
    resolved_weight = _measured(weight_kg)
    weight_source = "caller_resolved" if resolved_weight is not None else None
    if resolved_weight is None and scoped:
        resolved_weight = _measured(scoped.get("manual_gross_weight"))
        weight_source = "draft_manual_gross" if resolved_weight is not None else None
    if resolved_weight is None:
        try:
            shipment_db.init_db(shipment_db_path)
            row = shipment_db.get_shipment_for_draft(
                shipment_db_path, batch_id,
                (client_ref or (scoped or {}).get("client_ref")),
                allow_single_client_fallback=False,
            )
        except Exception:
            row = None
        if row:
            resolved_weight = _measured(row.get("weight_kg"))
            weight_source = "previous_carrier_booking" if resolved_weight is not None else None
    if resolved_weight is None:
        blockers.append(_reason(
            "WEIGHT_NOT_MEASURED",
            "Packed gross weight is required. Record it once in the proforma "
            "Weights panel — a zero or blank weight is a missing measurement, "
            "never a shipment fact.",
            AUTH_PROFORMA))

    # ── Box Master selection (code only; Box Master owns the dimensions) ─────
    box_code = (scoped or {}).get("box_type_code") or None
    if not box_code:
        advisories.append(_reason(
            "BOX_PROFILE_NOT_SELECTED",
            "No Box Profile selected — dimensions will be sent exactly as typed.",
            AUTH_PROFORMA))

    # ── Packages (neutral split; the booking validates each measurement) ─────
    try:
        packages = int(packages_count) if packages_count not in (None, "") else None
    except (TypeError, ValueError):
        packages = None

    # ── Declared value ──────────────────────────────────────────────────────
    resolved_value = _measured(declared_value)
    if resolved_value is None:
        blockers.append(_reason(
            "DECLARED_VALUE_MISSING",
            "Declared value is required for a customs-bearing shipment.",
            AUTH_PROFORMA))

    # ── Carrier account + Incoterm (same resolvers the booking POST uses) ────
    carrier_block: Dict[str, Any] = {"provider": provider}
    if provider == "DHL":
        account = (getattr(settings, "dhl_express_account_number", "") or "").strip()
        carrier_block["account_ready"] = bool(account)
        carrier_block["account_source"] = "environment" if account else None
        if not account:
            blockers.append(_reason(
                "SHIPPER_ACCOUNT_MISSING",
                "No DHL Express account is resolvable for this sender.",
                AUTH_SALES))
        from ...api.routes_carrier_actions import _resolve_booking_incoterm
        try:
            incoterm = _resolve_booking_incoterm(
                storage_root=storage_root, batch_id=batch_id,
                client_ref=(client_ref or (scoped or {}).get("client_ref")),
            )
        except Exception:
            incoterm = {"value": None, "source": "unset"}
        carrier_block["incoterm"] = (incoterm.get("value") or None)
        carrier_block["incoterm_source"] = incoterm.get("source") or "unset"
        if not carrier_block["incoterm"]:
            blockers.append(_reason(
                "INCOTERM_UNSET",
                "Incoterm is unset for this client. Set it in Client Master or on "
                "the proforma draft — the platform will not invent DAP.",
                AUTH_PROFORMA))
    else:
        carrier_block["account_ready"] = None
        carrier_block["account_source"] = None
    carrier_block["environment"] = (getattr(settings, "carrier_api_status", "") or None)

    release = _release_state(batch_id, settings)
    ready = not blockers

    return {
        "batch_id": batch_id,
        "shipment_intent": intent,
        # The supplier leg. Present and tracked — never re-booked from here.
        "existing_awb": (inbound or {}).get("awb"),
        "existing_awb_provider": (inbound or {}).get("provider"),
        "inbound_leg": inbound,
        # Every customer intent this batch carries, so the operator can see that
        # one import batch is legitimately several outbound shipments.
        "outbound_intents": intents,
        "customer_scope": (client_ref or (scoped or {}).get("client_ref")),
        "recipient": recipient,
        "warehouse": warehouse,
        "weight": {
            "value": resolved_weight,
            "source": weight_source,
            "ready": resolved_weight is not None,
        },
        "box": {"code": box_code, "ready": bool(box_code)},
        "packages": {"count": packages, "ready": packages is None or packages > 0},
        "commercial": {
            "declared_value": resolved_value,
            "currency": (scoped or {}).get("currency"),
            "ready": resolved_value is not None,
        },
        "carrier": carrier_block,
        "release": release,
        "booking": {
            "ready": ready,
            "blockers": blockers,
            "advisories": advisories,
        },
        # The two axes, stated plainly, so the UI never has to infer them.
        "ready_to_generate_real_awb": bool(ready),
        "live_release_blocked": not release["production_write_ready"],
    }

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

Business rules this module encodes (operator-ratified)
------------------------------------------------------
* **Warehouse receipt is DOWNSTREAM of dispatch.** Goods are packed and weighed
  in India and the AWB is created before they travel, so a pending destination
  receipt is the expected state at booking time. It is reported for information
  and is never a blocker, never a warning, never a booking dependency.
* **The Proforma Invoice is the value document at AWB stage.** A final sales /
  commercial invoice is NOT required to create an AWB and is never consulted
  here.
* **Direction alone never blocks a booking.** India -> Poland goods are
  "inbound" relative to the destination warehouse while the origin-side operator
  legitimately books the carrier before departure. Duplicate protection is tied
  to leg identity -- see ``resolve_existing_leg_awb``.

Blockers vs warnings (Lesson N / Lesson R)
------------------------------------------
``blockers`` carries only conditions that already fail the booking POST closed
today -- an unresolvable recipient, a missing measured weight, a missing declared
value, an unset Incoterm, an unresolvable carrier account. Everything else is a
``warning``: surfaced to the operator, never a gate.

``live_release`` is a SEPARATE axis from ``business_readiness``: it answers
"can this process reach the carrier at all", i.e. mode and capability, and never
"is this shipment's data valid". The UI must not conflate the two.

Since 2026-08-22 it is NOT a per-shipment release. The per-batch
``carrier_live_allowlist`` was retired from booking authorization, so this axis
no longer reports whether one batch was individually released -- it reports
``carrier_api_status`` and whether the factory hands back a usable adapter.
Reporting a batch "not released" when nothing releases batches any more would be
exactly the fake readiness this module exists to prevent.
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


def resolve_existing_leg_awb(
    batch_id: str,
    *,
    storage_root: Path,
    proforma_db_path: Path,
    client_ref: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """The AWB that ALREADY represents this canonical shipment leg, or None.

    This is duplicate protection, and the invariant is exactly one sentence:
    **the same canonical shipment leg must not receive a second AWB.**

    Direction is NOT consulted and never can be. Goods moving India → Poland are
    "inbound" relative to the destination warehouse while the origin-side
    operator legitimately books the carrier before departure; treating inbound as
    unbookable would forbid the normal workflow.

    Leg identity:

    * ``client_ref`` naming a real proforma draft is a DISTINCT outbound
      customer leg. Duplicates there are already handled correctly by the
      coordinator's idempotency key (it REPLAYS the stored booking rather than
      creating a second AWB), so this returns None and lets that path run.
    * Otherwise the request identifies the batch itself. For an import batch
      whose intake carried a supplier AWB, that batch-level leg IS the supplier
      leg, and it already has a real AWB.

    Returns ``{"awb", "provider", "source"}`` when the leg is already booked.
    """
    scoped = (client_ref or "").strip()
    if scoped and resolve_outbound_intents(
        batch_id, proforma_db_path=proforma_db_path, client_ref=scoped,
    ):
        return None      # distinct customer leg — coordinator idempotency owns it
    inbound = project_inbound_leg(batch_id, storage_root=storage_root)
    if inbound and inbound.get("awb"):
        return {
            "awb": inbound["awb"],
            "provider": inbound.get("provider"),
            "source": "intake_shipment_document",
        }
    return None


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
        # Deliberately no phone / street / email: readiness answers "is the
        # recipient resolvable", not "what is it". The booking already reads the
        # full address from the ONE authority; echoing contact PII into a
        # preflight response widens the surface for nothing.
        "blocker": None,
    }


def _warehouse_state(batch_id: str) -> Dict[str, Any]:
    """Destination receipt state — DOWNSTREAM of dispatch, never a booking gate.

    Warehouse authority answers "have these physical goods reached the
    destination warehouse", not "may the origin operator dispatch them". Goods
    are packed and weighed in India and the AWB is created BEFORE they travel,
    so a pending receipt is the expected state at booking time, not a defect.

    ``booking_dependency`` is hard-coded False and pinned by test: this value is
    reported for information only and never reaches blockers or warnings.
    """
    try:
        from ...services.warehouse_receipt import get_receipt_status
        status = get_receipt_status(batch_id)
    except Exception:
        return {"state": "unknown", "received_count": None, "expected_count": None,
                "serial_controlled": None, "booking_dependency": False}
    expected = status.get("total_lines") or 0
    received = status.get("confirmed_lines") or 0
    return {
        "state": ("received" if status.get("fully_confirmed")
                  else ("pending" if expected else "not_applicable")),
        "received_count": received,
        "expected_count": expected,
        "serial_controlled": bool(status.get("serial_controlled")),
        # Permanent contract. Warehouse receipt is downstream of dispatch.
        "booking_dependency": False,
    }


def _release_state(batch_id: str, settings, provider: str = "DHL") -> Dict[str, Any]:
    """Live carrier MODE + capability for ONE provider. Never per-shipment.

    Independent of business readiness: a not-live answer means this process is
    not configured to reach the carrier, NOT that the shipment data is invalid.

    Capability and credential state come from the carrier factory + credential
    resolver -- the same authorities Carrier Master renders -- so this can never
    report a provider ready that the factory would refuse.

    batch_id is accepted for call-shape stability and deliberately NOT read:
    nothing about carrier mode or capability varies per batch now that the
    per-batch allowlist is retired, and reading it would re-invent the
    per-shipment release this module no longer has.
    """
    del batch_id  # see docstring — mode/capability are not per-shipment.
    status = (getattr(settings, "carrier_api_status", "") or "").strip().lower()

    # Capability = "would the factory hand back a usable adapter for this
    # provider right now". Asking it is the only honest answer; a stored flag
    # would go stale the moment a credential changed.
    capability_ready, capability_reason, adapter_name = False, None, None
    try:
        # `.factory` -- app.services.carrier.factory, the same module the
        # coordinator imports (coordinator.py:34). This read `..factory`,
        # i.e. app.services.factory, which does not exist: every release
        # projection raised ImportError, was swallowed, and reported
        # capability_ready False with "No module named 'app.services.factory'"
        # leaking into an operator-facing field -- even for DHL, which Carrier
        # Master independently reports as fully provisioned.
        from .factory import CarrierConfig, get_adapter
        adapter = get_adapter(
            CarrierConfig(
                status=status or "pending",
                api_key=getattr(settings, "dhl_express_api_key", None),
                api_secret=getattr(settings, "dhl_express_api_secret", None),
                account_number=getattr(settings, "dhl_express_account_number", None),
            ),
            provider=provider,
        )
        capability_ready = True
        adapter_name = type(adapter).__name__
    except Exception as exc:
        capability_reason = str(exc) or type(exc).__name__

    live_mode = status == "live"
    ready = bool(capability_ready and live_mode)
    if ready:
        reason = None
    elif not capability_ready:
        reason = (
            "This carrier is not usable from this service right now: "
            "{0}. Fix the carrier configuration in Carrier Master.".format(
                capability_reason or "no adapter could be created")
        )
    else:
        reason = (
            "Carrier mode is {0!r}, so bookings are simulated rather than sent "
            "to the carrier. This is a service-wide mode, not a per-shipment "
            "release — no individual shipment needs releasing.".format(
                status or "unset")
        )
    return {
        "carrier_api_status": status or None,
        "credentials_ready": capability_ready,
        "capability_ready": capability_ready,
        "adapter": adapter_name,
        "capability_reason": capability_reason,
        # Permanent contract, pinned by test: booking authorization is never a
        # per-batch release list, so this key is always False. Kept (rather than
        # dropped) so a stale consumer reads an honest False instead of KeyError.
        "specifically_allowlisted": False,
        "ready": ready,
        "reason": reason,
    }


def _normalise_description(projected):
    """The description text out of whatever the projection returned.

    ``_project_shipment_description_for_client`` returns the full projection
    DICT (``batch_id`` / ``client_ref`` / ``shipment_description`` / ``source``),
    not a bare string. This consumer previously called ``.strip()`` on the
    return value directly, so every readiness request raised
    ``AttributeError: 'dict' object has no attribute 'strip'`` and the endpoint
    500'd -- the unit tests missed it because the stub returned a string the
    real builder never produces (Lesson A). Normalised here, at the one seam,
    rather than re-deriving the description: description_engine stays the sole
    authority and this function only reads what it published.
    """
    if isinstance(projected, dict):
        text = projected.get("shipment_description")
    else:
        text = projected
    return (text or "").strip() or None


def _description_state(batch_id, storage_root, client_ref):
    """Canonical shipment description -- the ONE backend projection, never a
    browser-side item_type mapping."""
    try:
        from ...api.routes_carrier_actions import _project_shipment_description_for_client
        projected = _project_shipment_description_for_client(
            storage_root=storage_root, batch_id=batch_id, client_ref=client_ref,
        )
    except Exception:
        return {"ready": False, "authority": "description_engine", "value": None}
    value = _normalise_description(projected)
    return {"ready": bool(value), "authority": "description_engine", "value": value}


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
    intents = resolve_outbound_intents(
        batch_id, proforma_db_path=proforma_db_path, client_ref=client_ref,
    )
    scoped = intents[0] if len(intents) == 1 else None
    scope = (client_ref or "").strip() or ((scoped or {}).get("client_ref"))

    blockers = []
    warnings = []

    # -- Is this leg already booked? (the ONLY duplicate rule) ---------------
    existing = resolve_existing_leg_awb(
        batch_id, storage_root=storage_root,
        proforma_db_path=proforma_db_path, client_ref=client_ref,
    )
    inbound = project_inbound_leg(batch_id, storage_root=storage_root)
    existing_booking = {
        "existing": bool(existing),
        "carrier": (existing or {}).get("provider"),
        "awb": (existing or {}).get("awb"),
        "source": (existing or {}).get("source"),
        "blocks_duplicate_booking": bool(existing),
        # Transport facts for the already-booked leg, from the ONE tracking
        # projection -- this module runs no tracking fetch of its own.
        "tracking_stage": (inbound or {}).get("stage"),
        "tracking_status": (inbound or {}).get("status"),
        "tracking_location": (inbound or {}).get("location"),
        "customs_status": (inbound or {}).get("customs_status"),
    }
    if existing:
        blockers.append(_reason(
            "SHIPMENT_LEG_ALREADY_BOOKED",
            "This shipment leg already has {0} AWB {1}. No new AWB is required.".format(
                existing.get("provider") or "a", existing["awb"]),
            AUTH_SALES))
    elif client_ref is None and len(intents) > 1:
        blockers.append(_reason(
            "OUTBOUND_SCOPE_AMBIGUOUS",
            "This import batch carries {0} customer proformas. Choose which "
            "customer's shipment to prepare -- a batch is not a shipment.".format(
                len(intents)),
            AUTH_SALES))

    # -- Proforma is the value document at AWB stage; no sales invoice needed -
    proforma = {
        "ready": bool(scope and intents),
        "authority": "proforma_invoice_link_db",
        "client_ref": scope,
        "draft_id": (scoped or {}).get("draft_id"),
        "draft_state": (scoped or {}).get("draft_state"),
        # Permanent contract, pinned by test: a final sales / commercial invoice
        # is NOT a prerequisite for creating an AWB and is never read here.
        "final_sales_invoice_required": False,
    }
    if not intents:
        warnings.append(_reason(
            "NO_CUSTOMER_PROFORMA",
            "No customer proforma is linked to this batch yet.",
            AUTH_SALES))

    # -- Recipient (Customer Master -- the ONE authority, no raw fallback) ----
    recipient = (_recipient_state(batch_id, storage_root, scope) if intents
                 else {"ready": False, "source": None, "blocker": None})
    if recipient.get("blocker"):
        blockers.append(recipient["blocker"])
    recipient["authority"] = "customer_master"

    # -- Warehouse -- downstream, reported only, never a gate ----------------
    warehouse = _warehouse_state(batch_id)

    # -- Weight: origin packing truth, entered before dispatch --------------
    resolved_weight = _measured(weight_kg)
    weight_source = "caller_resolved" if resolved_weight is not None else None
    if resolved_weight is None and scoped:
        resolved_weight = _measured(scoped.get("manual_gross_weight"))
        weight_source = "draft_manual_gross" if resolved_weight is not None else None
    if resolved_weight is None:
        try:
            shipment_db.init_db(shipment_db_path)
            row = shipment_db.get_shipment_for_draft(
                shipment_db_path, batch_id, scope,
                allow_single_client_fallback=False,
            )
        except Exception:
            row = None
        if row:
            resolved_weight = _measured(row.get("weight_kg"))
            weight_source = ("previous_carrier_booking"
                             if resolved_weight is not None else None)
    if resolved_weight is None:
        blockers.append(_reason(
            "WEIGHT_NOT_MEASURED",
            "Actual packed gross weight is required. Record it in the proforma "
            "Weights panel -- a zero or blank weight is a missing measurement, "
            "never a shipment fact. Destination receipt is NOT required for this.",
            AUTH_PROFORMA))

    # -- Box Master selection (code only; Box Master owns the dimensions) ----
    box_code = (scoped or {}).get("box_type_code") or None
    if not box_code:
        warnings.append(_reason(
            "BOX_PROFILE_NOT_SELECTED",
            "No Box Profile selected -- dimensions will be sent exactly as typed.",
            AUTH_PROFORMA))

    try:
        packages = int(packages_count) if packages_count not in (None, "") else None
    except (TypeError, ValueError):
        packages = None

    resolved_value = _measured(declared_value)
    if resolved_value is None:
        blockers.append(_reason(
            "DECLARED_VALUE_MISSING",
            "Declared value is required for a customs-bearing shipment. The "
            "Proforma Invoice is the value document at this stage.",
            AUTH_PROFORMA))

    description = _description_state(batch_id, storage_root, scope)

    # -- Carrier account + Incoterm (same resolvers the booking POST uses) ---
    carrier_block = {"provider": provider}
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
                storage_root=storage_root, batch_id=batch_id, client_ref=scope,
            )
        except Exception:
            incoterm = {"value": None, "source": "unset"}
        carrier_block["incoterm"] = (incoterm.get("value") or None)
        carrier_block["incoterm_source"] = incoterm.get("source") or "unset"
        if not carrier_block["incoterm"]:
            blockers.append(_reason(
                "INCOTERM_UNSET",
                "Incoterm is unset for this client. Set it in Client Master or on "
                "the proforma draft -- the platform will not invent DAP.",
                AUTH_PROFORMA))
    else:
        carrier_block["account_ready"] = None
        carrier_block["account_source"] = None

    live_release = _release_state(batch_id, settings, provider)
    ready = not blockers

    return {
        "batch_id": batch_id,
        "customer_scope": scope,
        "outbound_intents": intents,
        # 1. business preparation -- what the booking POST already enforces
        "business_readiness": {
            "ready": ready,
            "blockers": blockers,
            "warnings": warnings,
        },
        "proforma": proforma,
        "recipient": recipient,
        "weight": {
            "ready": resolved_weight is not None,
            "gross_weight": resolved_weight,
            "source": weight_source,
            "authority": "proforma_packing_weight_authority",
        },
        "box": {"ready": bool(box_code), "box_type_code": box_code,
                "authority": "box_master"},
        "packages": {"ready": packages is None or packages > 0, "count": packages,
                     "source": "neutral_package_model"},
        "declared_value": {
            "ready": resolved_value is not None,
            "value": resolved_value,
            "currency": (scoped or {}).get("currency"),
            "authority": "proforma_invoice",
        },
        "description": description,
        "carrier": carrier_block,
        # 3. existing shipment / AWB state
        "existing_booking": existing_booking,
        # 2. live carrier release -- INDEPENDENT of business readiness
        "live_release": live_release,
        # 4. downstream informational state only
        "warehouse": warehouse,
    }

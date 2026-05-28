"""master_reference_checks.py — Phase 4C referential-integrity helpers.

Purpose
=======
Now that 11 master entities can be inactive (soft-deleted), new writes that
reference inactive or missing parent records would silently corrupt the
local catalog. This module provides a small, pure set of validators that
the master-data route handlers invoke before persisting new rows.

Hard rules (encoded once here, enforced everywhere):

  1. Validation is READ-ONLY against local master DBs. No HTTP, no
     external systems, no wFirma, no NBP, no DHL, no PZ engine, no
     proforma, no FX engine, no inventory engine.
  2. Validation runs on writes (PUT / POST / update / restore) — NEVER
     on GET. Existing rows whose parents have since gone inactive remain
     readable; only new writes are gated.
  3. On conflict, raise ``ReferenceConflict`` carrying the
     {field, entity, key, reason} quadruple. Route handlers convert
     this to a 409 HTTPException with a stable error body.
  4. Customers do NOT yet have soft-delete (Wave 3+). Per operator
     instruction, an existing customer row is treated as active.

Error contract
==============
HTTPException(status_code=409, detail={
    "error":  "reference_conflict",
    "field":  "<offending input field name>",
    "entity": "<referenced entity tag>",
    "key":    "<referenced key value>",
    "reason": "missing" | "inactive",
})
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class ReferenceConflict(Exception):
    """Raised when a write references a missing or inactive master row."""
    field:  str
    entity: str
    key:    Any
    reason: str    # "missing" or "inactive"

    def to_detail(self) -> Dict[str, Any]:
        return {
            "error":  "reference_conflict",
            "field":  self.field,
            "entity": self.entity,
            "key":    str(self.key),
            "reason": self.reason,
        }

    def __str__(self) -> str:        # makes pytest -v output readable
        return (f"{self.entity} {self.key!r} is {self.reason} "
                f"(reference field: {self.field})")


# ── HS code referent check (used by product_local + designs) ────────────────

def check_hs_code_active(master_data_db_path: Path, *, field: str, code: str) -> None:
    """Verify the referenced HS code exists AND is active in the local
    ``hs_codes`` table. Raises ``ReferenceConflict`` otherwise.

    ``field`` is the inbound payload field name (e.g. "hs_code_override"
    for product_local, "hs_code" for designs) — used to build a
    surface-accurate error body.
    """
    # Lazy import to keep this module dependency-free at module load time.
    from .master_data_db import get_hs_code  # noqa: PLC0415
    rec = get_hs_code(master_data_db_path, code)
    if rec is None:
        raise ReferenceConflict(field=field, entity="hs_codes",
                                key=code, reason="missing")
    if not rec.active:
        raise ReferenceConflict(field=field, entity="hs_codes",
                                key=code, reason="inactive")


# ── Customer existence check (used by client_addresses + client_carrier_accounts) ─

def check_customer_exists(customer_master_db_path: Path, *,
                          field: str, contractor_id: str) -> None:
    """Verify the referenced contractor exists in customer_master.

    Customer soft-delete is NOT implemented yet (Wave 3+). Per operator
    instruction, any existing customer is treated as active — we only
    check for existence here. When customer soft-delete lands, this
    helper should be extended to also reject inactive customers.
    """
    import sqlite3  # noqa: PLC0415
    from .customer_master_db import get_customer  # noqa: PLC0415
    try:
        rec = get_customer(customer_master_db_path, contractor_id)
    except sqlite3.OperationalError as exc:
        # Common case during test/fresh-deploy: customer_master table has
        # not been initialised yet. Treat as "no customers exist" → missing.
        if "no such table" in str(exc).lower():
            rec = None
        else:
            raise
    if rec is None:
        raise ReferenceConflict(field=field, entity="customers",
                                key=contractor_id, reason="missing")
    # Future-proofing: if a customer record ever grows an ``active``
    # attribute, gate on it here. ``getattr`` keeps this hook dormant
    # until that field actually exists.
    active = getattr(rec, "active", True)
    if active is False:
        raise ReferenceConflict(field=field, entity="customers",
                                key=contractor_id, reason="inactive")


# ── Carrier referent check (Phase 4C-ext, used by client_carrier_accounts) ──

def check_carrier_active(storage_root: Path, carrier_code: str) -> None:
    """Verify the referenced carrier exists AND is active in the local
    ``carriers_config`` table. Raises ``ReferenceConflict`` otherwise.

    Storage convention (per repo): the master-data SQLite file lives at
    ``<storage_root>/master_data.sqlite``. The helper accepts the
    operator-provided storage root and resolves the file internally so
    route handlers don't need to know that internal layout.

    ``carriers_config`` table may be absent on a fresh deploy that has
    never written a carrier row — treat that the same as "missing".

    The ``field`` slot on ``ReferenceConflict`` is hard-coded to
    ``"carrier"`` since the only inbound field name is the
    carrier-account ``carrier`` attribute.
    """
    import sqlite3  # noqa: PLC0415
    from .master_data_db import get_carrier_config  # noqa: PLC0415
    master_data_path = storage_root / "master_data.sqlite"
    try:
        rec = get_carrier_config(master_data_path, carrier_code)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            rec = None
        else:
            raise
    if rec is None:
        raise ReferenceConflict(field="carrier", entity="carriers_config",
                                key=carrier_code, reason="missing")
    if not rec.active:
        raise ReferenceConflict(field="carrier", entity="carriers_config",
                                key=carrier_code, reason="inactive")


# ── Metal / stone hooks (defined but unused in Phase 4C) ────────────────────
#
# product_local does not currently have ``metal_code`` or ``primary_stone_code``
# columns. The scope rule "Do not invent new fields" applies. The hooks below
# exist so route handlers can wire them once Phase 4C+ extends the schema;
# until then they are NOT called.

def check_metal_active(metals_db_path: Path, *, field: str, code: str) -> None:
    from .metals_db import get_metal  # noqa: PLC0415
    rec = get_metal(metals_db_path, code)
    if rec is None:
        raise ReferenceConflict(field=field, entity="metals",
                                key=code, reason="missing")
    if not rec.active:
        raise ReferenceConflict(field=field, entity="metals",
                                key=code, reason="inactive")


def check_stone_active(stones_db_path: Path, *, field: str, code: str) -> None:
    from .stones_db import get_stone  # noqa: PLC0415
    rec = get_stone(stones_db_path, code)
    if rec is None:
        raise ReferenceConflict(field=field, entity="stones",
                                key=code, reason="missing")
    if not rec.active:
        raise ReferenceConflict(field=field, entity="stones",
                                key=code, reason="inactive")

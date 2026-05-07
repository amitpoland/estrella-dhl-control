"""
clearance_path_alias.py — back-compat aliases for clearance path names.

The codebase historically used the values "carrier_self_clearance" and
"external_agency_clearance" in audit.clearance_decision.clearance_path.
The locked spec at docs/dhl_clearance_paths.md uses "dhl_self_clearance"
and "agency_clearance" as the canonical names.

This module is the single source of truth for the alias mapping. Every
reader that branches on clearance_path SHOULD route through
``normalize_path`` so that either alias works during the transition.

Phase 1.1 (this module + writer migration in clearance_decision.py)
introduces the spec names on the WRITE side. Subsequent phases migrate
remaining readers; until they do, those readers must compare via
``normalize_path`` to remain correct against new audit data.

Public API:
    PATH_DHL_SELF_CLEARANCE   — spec canonical name for Path A
    PATH_AGENCY_CLEARANCE     — spec canonical name for Path B
    PATH_ROUTING_PENDING      — neither A nor B (CIF unknown / unset)
    LEGACY_CARRIER_SELF_CLEARANCE     — pre-spec name for Path A
    LEGACY_EXTERNAL_AGENCY_CLEARANCE  — pre-spec name for Path B
    LEGACY_TO_SPEC            — mapping legacy → spec
    KNOWN_PATHS               — frozenset of every accepted value
    normalize_path(value)     — collapse any value to spec canonical form
    is_dhl_self_clearance(v)  — True iff normalize_path(v) is Path A
    is_agency_clearance(v)    — True iff normalize_path(v) is Path B
    is_routing_pending(v)     — True iff normalize_path(v) is routing_pending
"""
from __future__ import annotations

from typing import Optional

# ── Spec canonical names ─────────────────────────────────────────────────────

PATH_DHL_SELF_CLEARANCE: str = "dhl_self_clearance"
PATH_AGENCY_CLEARANCE:   str = "agency_clearance"
PATH_ROUTING_PENDING:    str = "routing_pending"

# ── Legacy names (still present in older audit data) ─────────────────────────

LEGACY_CARRIER_SELF_CLEARANCE:    str = "carrier_self_clearance"
LEGACY_EXTERNAL_AGENCY_CLEARANCE: str = "external_agency_clearance"

# ── Alias mapping ────────────────────────────────────────────────────────────

LEGACY_TO_SPEC = {
    LEGACY_CARRIER_SELF_CLEARANCE:    PATH_DHL_SELF_CLEARANCE,
    LEGACY_EXTERNAL_AGENCY_CLEARANCE: PATH_AGENCY_CLEARANCE,
}

KNOWN_PATHS = frozenset({
    PATH_DHL_SELF_CLEARANCE,
    PATH_AGENCY_CLEARANCE,
    PATH_ROUTING_PENDING,
    LEGACY_CARRIER_SELF_CLEARANCE,
    LEGACY_EXTERNAL_AGENCY_CLEARANCE,
})


def normalize_path(value: Optional[str]) -> str:
    """Normalize any clearance_path value to its spec canonical form.

    - Spec names ("dhl_self_clearance", "agency_clearance",
      "routing_pending") return unchanged.
    - Legacy names map to their spec equivalents.
    - None / empty string / unknown values default to "routing_pending"
      (safe default — spec rule: unknown == not-yet-classified).
    """
    if not value:
        return PATH_ROUTING_PENDING
    if value in LEGACY_TO_SPEC:
        return LEGACY_TO_SPEC[value]
    if value in (PATH_DHL_SELF_CLEARANCE,
                 PATH_AGENCY_CLEARANCE,
                 PATH_ROUTING_PENDING):
        return value
    return PATH_ROUTING_PENDING


def is_dhl_self_clearance(value: Optional[str]) -> bool:
    """True iff *value* normalizes to Path A (dhl_self_clearance)."""
    return normalize_path(value) == PATH_DHL_SELF_CLEARANCE


def is_agency_clearance(value: Optional[str]) -> bool:
    """True iff *value* normalizes to Path B (agency_clearance)."""
    return normalize_path(value) == PATH_AGENCY_CLEARANCE


def is_routing_pending(value: Optional[str]) -> bool:
    """True iff *value* normalizes to routing_pending (or is unknown)."""
    return normalize_path(value) == PATH_ROUTING_PENDING

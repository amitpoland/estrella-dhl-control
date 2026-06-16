"""
clearance_decision.py — Value-based customs clearance decision engine.

Single source of truth for:
  - Whether this shipment goes through external agency or carrier self-clearance
  - Whether DSK broker notification is required
  - Whether Polish description is required
  - What action DHL should receive (DSK transfer vs description reply)
  - FedEx-specific clearance rules (cesja requirement, 9-day SLA)

Decision is written to audit["clearance_decision"] on every upload and recheck.
All downstream logic (send_reply, agency email, cowork) reads from that field.

Threshold: 2 500 USD (configurable via CLEARANCE_THRESHOLD_USD env var)

FedEx additions (intelligence layer):
  - FedEx uses a 2-actor chain: FedEx → Ganther (no ACS Spedycja)
  - FedEx requires manual cesja submission to pl-import@fedex.com
  - FedEx SLA = 9 days vs DHL SLA = 5 days
  - FedEx billing mode must be "sender pays" for duty/tax
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ..core.config import settings
from .clearance_path_alias import (
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
    PATH_ROUTING_PENDING,
)
from .cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
    resolve_cif,
)

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

THRESHOLD_USD: float = 2_500.0   # shipments above this require external agency + DSK
AGENCY_NAME:   str   = "Agencja Celna Spedycja"
AGENCY_EMAIL:  str   = "biuro@acspedycja.pl"

# ── FedEx-specific constants (from intelligence layer) ────────────────────────

FEDEX_CESJA_TARGET:   str = "pl-import@fedex.com"
FEDEX_SLA_DAYS:       int = 9
FEDEX_CESJA_WINDOW_H: int = 24   # hours after arrival to submit cesja
DHL_SLA_DAYS:         int = 5

# FedEx AWB pattern: 12 digits
_FEDEX_AWB_RE = re.compile(r'^\d{12}$')
_DHL_AWB_RE   = re.compile(r'^\d{10}$')


# ── Core decision engine ──────────────────────────────────────────────────────

def build_clearance_decision(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute the clearance decision from audit data and return it.

    The decision is NOT written here — callers are responsible for persisting
    it to audit["clearance_decision"].  This keeps the function pure and testable.

    CIF source priority (delegated to ``cif_resolver.resolve_cif``):
      1. audit["verification"]["invoice_cif_total_usd"]  (engine-verified)
      2. audit["invoice_totals"]["total_cif_usd"]
      3. audit["invoice_totals"]["total_fob_usd"]         (fallback, no freight)
      4. audit["dhl_precheck"]["invoice_cif_total_usd"]
      5. audit["dhl_precheck"]["fob_total_usd"]           (fallback)
      6. audit["awb_customs"]["value_usd"]                (carrier-declared, USD only)
      → UNKNOWN (extraction_gap) when no layer produces a value

    Invoice authority (1–5) always outranks the carrier-declared AWB Custom
    Val (6). A missing value surfaces as ``cif_state="unknown"`` +
    ``cif_extraction_gap`` + ``clearance_path=routing_pending`` — NEVER a
    fabricated 0.0.

    Returns
    -------
    dict with fields:
      total_value_usd        float
      threshold_usd          float
      clearance_path         "agency_clearance" | "dhl_self_clearance" | "routing_pending" (spec canonical names; legacy aliases "external_agency_clearance" / "carrier_self_clearance" remain accepted by readers via clearance_path_alias.normalize_path)
      require_dsk            bool
      require_polish_description  bool
      carrier_handles        bool
      agency                 str | None
      agency_email           str | None
      cif_source             str
      cif_state              "resolved" | "declared_zero" | "unknown"
      cif_extraction_gap     dict | None   (operator-actionable gap when unknown)
      decision_reason        str
      computed_at            str (ISO)
    """
    from datetime import datetime, timezone

    ver      = audit.get("verification") or {}
    it       = audit.get("invoice_totals") or {}
    precheck = audit.get("dhl_precheck") or {}

    # Tri-state CIF resolution. The resolver owns the source ladder, the
    # provenance trace, and the never-fake-zero contract. This builder reads
    # its verdict and maps it onto the clearance routing decision.
    res        = resolve_cif(audit)
    cif_state  = res["cif_state"]
    cif_source = res["cif_source"]
    cif_gap    = res["extraction_gap"]

    now_iso = datetime.now(timezone.utc).isoformat()

    # ── UNKNOWN — extraction failed / not run. Never a fake zero. ──────────
    if cif_state == CIF_UNKNOWN:
        # Operator-readable smallest-next-step. Kept here (not derived from the
        # resolver gap) so the long-pinned substrings stay stable; the machine-
        # readable gap travels alongside in cif_extraction_gap.
        if not audit.get("invoice_names") and not audit.get("inputs", {}).get("invoices"):
            missing_reason = "Purchase invoice not uploaded yet"
        elif not it and not ver and not precheck:
            missing_reason = "Purchase invoice not parsed yet — run Recheck"
        elif not (ver.get("invoice_cif_total_usd") or it.get("total_cif_usd")) and (
            it.get("total_fob_usd") or precheck.get("fob_total_usd")
        ):
            missing_reason = "FOB available but freight not allocated — CIF pending"
        else:
            missing_reason = "CIF not calculated yet — run Recheck after invoice parse"

        log.warning(
            "[clearance_decision] CIF UNKNOWN — routing_pending (%s) [gap=%s]",
            missing_reason, (cif_gap or {}).get("first_failed_layer"),
        )
        return {
            "total_value_usd":           0.0,
            "threshold_usd":             THRESHOLD_USD,
            "clearance_path":            PATH_ROUTING_PENDING,
            "require_dsk":               None,
            "require_polish_description": True,
            "carrier_handles":           None,
            "agency":                    None,
            "agency_email":              None,
            "cif_source":                cif_source,        # always "unavailable" here
            "cif_state":                 CIF_UNKNOWN,
            "cif_extraction_gap":        cif_gap,
            "missing_reason":            missing_reason,
            "decision_reason":           "cif_zero_routing_pending",
            "computed_at":               now_iso,
        }

    # ── DECLARED_ZERO — source explicitly says customs value is zero. ──────
    # A genuine zero-value shipment (e.g. no-commercial-value sample). 0 is
    # below threshold → carrier self-clearance, but flagged distinctly so the
    # operator sees this is an explicit zero, not a parser miss.
    if cif_state == CIF_DECLARED_ZERO:
        log.info(
            "[clearance_decision] CIF DECLARED_ZERO (source=%s) → %s",
            cif_source, PATH_DHL_SELF_CLEARANCE,
        )
        return {
            "total_value_usd":           0.0,
            "threshold_usd":             THRESHOLD_USD,
            "clearance_path":            PATH_DHL_SELF_CLEARANCE,
            "require_dsk":               False,
            "require_polish_description": True,
            "carrier_handles":           True,
            "agency":                    None,
            "agency_email":              None,
            "cif_source":                cif_source,
            "cif_state":                 CIF_DECLARED_ZERO,
            "cif_extraction_gap":        None,
            "decision_reason":           "cif_declared_zero",
            "computed_at":               now_iso,
        }

    # ── RESOLVED — a usable USD value was found. ───────────────────────────
    cif = float(res["cif_usd"])

    if cif >= THRESHOLD_USD:
        log.info(
            "[clearance_decision] CIF=%.2f >= %.0f → %s (source=%s)",
            cif, THRESHOLD_USD, PATH_AGENCY_CLEARANCE, cif_source,
        )
        return {
            "total_value_usd":           round(cif, 2),
            "threshold_usd":             THRESHOLD_USD,
            "clearance_path":            PATH_AGENCY_CLEARANCE,
            "require_dsk":               True,
            "require_polish_description": True,
            "carrier_handles":           False,
            "agency":                    AGENCY_NAME,
            "agency_email":              AGENCY_EMAIL,
            "cif_source":                cif_source,
            "cif_state":                 CIF_RESOLVED,
            "cif_extraction_gap":        None,
            "decision_reason":           "value_above_threshold",
            "computed_at":               now_iso,
        }

    log.info(
        "[clearance_decision] CIF=%.2f ≤ %.0f → %s (source=%s)",
        cif, THRESHOLD_USD, PATH_DHL_SELF_CLEARANCE, cif_source,
    )
    return {
        "total_value_usd":           round(cif, 2),
        "threshold_usd":             THRESHOLD_USD,
        "clearance_path":            PATH_DHL_SELF_CLEARANCE,
        "require_dsk":               False,
        "require_polish_description": True,
        "carrier_handles":           True,
        "agency":                    None,
        "agency_email":              None,
        "cif_source":                cif_source,
        "cif_state":                 CIF_RESOLVED,
        "cif_extraction_gap":        None,
        "decision_reason":           "value_below_threshold",
        "computed_at":               now_iso,
    }


# ── DHL action resolver ───────────────────────────────────────────────────────

def resolve_dhl_action(audit: Dict[str, Any], request_type: str = "") -> Dict[str, Any]:
    """
    Determine what action to take in response to a DHL customs inquiry.

    Reads from audit["clearance_decision"]; falls back to computing it live
    if absent (e.g. legacy batch).

    Returns
    -------
    dict with fields:
      action                        "dsk_transfer" | "carrier_description" | "unknown"
      send_description_to_dhl       bool
      send_description_to_agency    bool
      generate_dsk                  bool
      reason                        str
    """
    dec = audit.get("clearance_decision")
    if dec is None:
        # Legacy batch — compute on the fly (not persisted here)
        dec = build_clearance_decision(audit)

    path = dec.get("clearance_path", PATH_ROUTING_PENDING)

    from .clearance_path_alias import is_agency_clearance, is_dhl_self_clearance
    if is_agency_clearance(path):
        return {
            "action":                     "dsk_transfer",
            "send_description_to_dhl":    False,
            "send_description_to_agency": True,
            "generate_dsk":               True,
            "reason":                     "high_value_agency_path",
        }

    if is_dhl_self_clearance(path):
        return {
            "action":                     "carrier_description",
            "send_description_to_dhl":    True,
            "send_description_to_agency": False,
            "generate_dsk":               False,
            "reason":                     "standard_carrier_path",
        }

    # routing_pending — no hard decision yet
    return {
        "action":                     "unknown",
        "send_description_to_dhl":    False,
        "send_description_to_agency": False,
        "generate_dsk":               False,
        "reason":                     "cif_not_parsed_yet",
    }


# ── Carrier detection ─────────────────────────────────────────────────────────

def detect_carrier(audit: Dict[str, Any]) -> str:
    """
    Detect carrier from audit fields or AWB pattern.

    Returns "DHL", "FEDEX", or "UNKNOWN".
    """
    explicit = (audit.get("carrier") or "").upper().strip()
    if explicit in ("DHL", "FEDEX"):
        return explicit
    awb = str(audit.get("awb") or audit.get("tracking_no") or "").strip()
    if _FEDEX_AWB_RE.fullmatch(awb):
        return "FEDEX"
    if _DHL_AWB_RE.fullmatch(awb):
        return "DHL"
    return "UNKNOWN"


# ── FedEx-specific clearance decision ────────────────────────────────────────

def build_fedex_clearance_decision(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build FedEx-specific clearance decision.

    FedEx chain: FedEx → Ganther (no ACS Spedycja involvement)
    FedEx requires: manual cesja submission to pl-import@fedex.com

    Returns clearance_decision dict with FedEx-specific fields.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    ver      = audit.get("verification") or {}
    it       = audit.get("invoice_totals") or {}
    precheck = audit.get("dhl_precheck") or {}

    cif: float = (
        float(ver.get("invoice_cif_total_usd") or 0)
        or float(it.get("total_cif_usd") or 0)
        or float(it.get("total_fob_usd") or 0)
        or float(precheck.get("invoice_cif_total_usd") or 0)
        or float(precheck.get("fob_total_usd") or 0)
    )

    # FedEx always uses external agency (Ganther) — no carrier self-clearance
    # Cesja must be submitted manually by Estrella to pl-import@fedex.com
    base = {
        "carrier":                    "FEDEX",
        "total_value_usd":            round(cif, 2) if cif else 0.0,
        "threshold_usd":              THRESHOLD_USD,
        "clearance_path":             "fedex_ganther_clearance",
        "require_dsk":                True,   # DSK via FedEx after cesja submission
        "require_polish_description": False,  # FedEx uses standard customs forms
        "carrier_handles":            False,
        "require_cesja_manual":       True,   # Estrella must submit to pl-import@fedex.com
        "cesja_target":               FEDEX_CESJA_TARGET,
        "agency":                     "Ganther",
        "agency_email":               "ganther.com.pl",
        "sla_days":                   FEDEX_SLA_DAYS,
        "dsk_source":                 FEDEX_CESJA_TARGET,
        "decision_reason":            "fedex_ganther_direct_path",
        "computed_at":                now_iso,
    }

    if cif == 0.0:
        base["decision_reason"] = "fedex_cif_zero_routing_pending"
        log.warning("[clearance_decision] FedEx CIF = 0 — routing pending")

    return base


# ── Timeline-based decision override ─────────────────────────────────────────

def apply_timeline_overrides(
    decision: Dict[str, Any],
    timeline: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Apply confirmed timeline signals as overrides on a computed clearance decision.

    Priority: timeline evidence > value-computed path.

    Rules (in priority order):
      1. "agency_email_sent" in timeline
             → force clearance_path = "external_agency_clearance"
             Rationale: agency was already engaged; reverting to carrier path
             would cause duplicate clearance attempt.

      2. "dhl_reply_sent" in timeline AND total_value_usd < threshold
             → force clearance_path = "carrier_self_clearance"
             Rationale: reply already sent to DHL with description; low-value
             shipment does not need agency intervention.

    Args:
        decision: Output dict from build_clearance_decision() or
                  build_fedex_clearance_decision(). NOT mutated.
        timeline: List of timeline event dicts from audit["timeline"].

    Returns:
        New decision dict with overrides applied (or original if no overrides fire).
    """
    from datetime import datetime, timezone

    if not timeline:
        return decision

    result      = dict(decision)   # shallow copy — safe for top-level scalar fields
    event_names = {ev.get("event") for ev in timeline if ev.get("event")}

    from .clearance_path_alias import is_agency_clearance, is_dhl_self_clearance

    if "agency_email_sent" in event_names:
        if not is_agency_clearance(result.get("clearance_path")):
            log.info(
                "[clearance_decision] Timeline override: agency_email_sent "
                "→ force %s", PATH_AGENCY_CLEARANCE,
            )
            result["clearance_path"]  = PATH_AGENCY_CLEARANCE
            result["require_dsk"]     = True
            result["carrier_handles"] = False
            result["agency"]          = result.get("agency") or AGENCY_NAME
            result["agency_email"]    = result.get("agency_email") or AGENCY_EMAIL
            result["decision_reason"] = "timeline_override:agency_email_confirmed"
            result["overridden_at"]   = datetime.now(timezone.utc).isoformat()

    elif "dhl_reply_sent" in event_names:
        value = result.get("total_value_usd") or 0.0
        if value < THRESHOLD_USD and not is_dhl_self_clearance(result.get("clearance_path")):
            log.info(
                "[clearance_decision] Timeline override: dhl_reply_sent + low value "
                "(%.2f < %.0f) → force %s",
                value, THRESHOLD_USD, PATH_DHL_SELF_CLEARANCE,
            )
            result["clearance_path"]  = PATH_DHL_SELF_CLEARANCE
            result["require_dsk"]     = False
            result["carrier_handles"] = True
            result["decision_reason"] = "timeline_override:dhl_reply_confirmed_low_value"
            result["overridden_at"]   = datetime.now(timezone.utc).isoformat()

    return result


# ── Unified clearance decision (carrier-aware) ────────────────────────────────

def build_clearance_decision_for_carrier(
    audit: Dict[str, Any],
    timeline: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build clearance decision using carrier detection, then apply timeline overrides.

    If carrier is FEDEX → use FedEx rules.
    If carrier is DHL or UNKNOWN → use DHL threshold rules (default).

    Timeline overrides are applied after the value-based decision:
      - agency_email_sent → external_agency_clearance
      - dhl_reply_sent + low value → carrier_self_clearance

    Args:
        audit:    Audit dict.
        timeline: Optional explicit timeline list. If None, read from audit["timeline"].
    """
    carrier = detect_carrier(audit)
    if carrier == "FEDEX":
        log.info("[clearance_decision] Carrier=FEDEX → applying FedEx rules")
        decision = build_fedex_clearance_decision(audit)
    else:
        decision = build_clearance_decision(audit)

    if timeline is None:
        timeline = audit.get("timeline") or []
    if timeline:
        decision = apply_timeline_overrides(decision, timeline)
    return decision


# ── Safety guard ──────────────────────────────────────────────────────────────

def assert_valid_dhl_reply(audit: Dict[str, Any], reply_package: Dict[str, Any]) -> None:
    """
    Raise ValueError if the reply package is invalid for the clearance decision.

    Rule: High-value shipments (agency path) must send DSK, not a plain
    Polish description.  DHL should never receive the product description when
    value exceeds threshold — DSK (broker notification) is the correct document.
    """
    action = resolve_dhl_action(audit)
    if action["action"] != "dsk_transfer":
        return   # carrier path — description reply is correct

    attachments = reply_package.get("attachments") or []
    has_dsk = any(
        "dsk" in (a.get("label") or "").lower()
        or "DSK_" in (a.get("path") or "")
        for a in attachments
    )
    if not has_dsk:
        cif = (audit.get("clearance_decision") or {}).get("total_value_usd", "?")
        raise ValueError(
            f"Invalid flow: shipment value ${cif} exceeds ${THRESHOLD_USD:.0f} threshold. "
            f"DHL must receive DSK broker notification, not a product description. "
            f"Generate DSK and use 'Build DHL Reply Package' before sending."
        )

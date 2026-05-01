"""
risk_detector.py — Risk Detection Engine
==========================================
Detects routing gaps, SLA breaches, unknown senders, and operational risks
from audit state and inbound email classifications.

Output: warnings[] list with structured risk items.

All detection is READ-ONLY. No writes to audit.json. No emails sent.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Risk severity ──────────────────────────────────────────────────────────────

HIGH   = "HIGH"
MEDIUM = "MEDIUM"
LOW    = "LOW"


# ── Warning schema ─────────────────────────────────────────────────────────────

def _warn(code: str, severity: str, message: str, detail: Optional[Dict] = None) -> Dict[str, Any]:
    return {
        "code":     code,
        "severity": severity,
        "message":  message,
        "detail":   detail or {},
    }


# ── SLA thresholds ─────────────────────────────────────────────────────────────

_SLA_DHL_FULL_HOURS   = 120   # 5 days
_SLA_FEDEX_FULL_HOURS = 216   # 9 days
_DUTY_WARNING_HOURS   = 72
_DUTY_CRITICAL_HOURS  = 168   # 7 days
_DSK_WARNING_HOURS    = 24
_SAD_WARNING_HOURS    = 48
_CESJA_WARNING_HOURS  = 24
_STORAGE_FEE_DAYS     = 5     # DHL free storage window

# ── Known trusted senders ─────────────────────────────────────────────────────

_TRUSTED_SENDERS = frozenset([
    "piotr@acspedycja.pl",
    "logistyka@acspedycja.pl",
    "roman@acspedycja.pl",
    "adrian@acspedycja.pl",
    "michal@acspedycja.pl",
    "no-reply@acspedycja.pl",
    "biuro@acspedycja.pl",
    "odprawacelna@dhl.com",
    "administracja_centralna@dhl.com",
    "ganther.com.pl",
    "jaworska@ganther.com.pl",
    "krzysztof.suchodola@ganther.com.pl",
    "pl-import@fedex.com",
    # Internal
    "import@estrellajewels.eu",
    "tejal@estrellajewels.com",
    "account@estrellajewels.eu",
    "amit@estrellajewels.eu",
    "jyoti@estrellajewels.com",
    "info@estrellajewels.eu",
    # Known non-trigger
    "accounts@gjlindia.com",
    "datarwa@fedex.com",
    "poland@fedex.com",
    "zaneta.nagat@fedex.com",
    "dyszynska@abf-biurorachunkowe.pl",
    "kaushal@estrellajewelsllp.com",
    "jigar.p@simplex-hurtownia.pl",
    "iza@simplex-hurtownia.pl",
])

_CANONICAL_DUTY_TARGET = "account@estrellajewels.eu"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _hours_since(ts_str: str) -> float:
    if not ts_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _detect_carrier(audit: Dict[str, Any]) -> str:
    carrier = (audit.get("carrier") or "").upper()
    if carrier in ("DHL", "FEDEX"):
        return carrier
    # Heuristic: FedEx AWBs are 12 digits, DHL are 10
    awb = str(audit.get("awb") or audit.get("tracking_no") or "")
    if re.fullmatch(r"\d{12}", awb):
        return "FEDEX"
    if re.fullmatch(r"\d{10}", awb):
        return "DHL"
    return "DHL"  # default


# ── Per-domain risk detectors ─────────────────────────────────────────────────

def detect_duty_routing_gap(
    email_to: Optional[str] = None,
    email_cc: Optional[str] = None,
    email_body: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Detect if duty notice was sent to personal inbox without account@ in TO.

    Args:
        email_to:   TO header of Ganther duty email
        email_cc:   CC header of Ganther duty email
        email_body: Email body text (for PLN detection)

    Returns:
        List of warning dicts.
    """
    warnings = []
    if email_to is None:
        return warnings

    to_lower  = email_to.lower()
    cc_lower  = (email_cc or "").lower()

    has_account_to = _CANONICAL_DUTY_TARGET in to_lower
    has_account_cc = _CANONICAL_DUTY_TARGET in cc_lower
    has_amit_to    = "amit@estrellajewels.eu" in to_lower
    has_tejal_to   = "import@estrellajewels.eu" in to_lower or "tejal@" in to_lower

    if not has_account_to and not has_account_cc:
        recipient = to_lower.split(",")[0].strip()
        warnings.append(_warn(
            "DUTY_ROUTING_GAP",
            HIGH,
            f"Duty notice sent to '{recipient}' without account@estrellajewels.eu — "
            f"matches pattern that caused 28-day delay (AWB 2824221912 Mar 2026).",
            {"to": email_to, "cc": email_cc, "canonical_target": _CANONICAL_DUTY_TARGET},
        ))

    if has_amit_to and not has_account_to:
        warnings.append(_warn(
            "DUTY_TO_PERSONAL",
            HIGH,
            "Duty notice sent to amit@ without account@ in TO — known risk pattern.",
            {"to": email_to},
        ))

    if has_tejal_to and not has_account_to:
        warnings.append(_warn(
            "DUTY_TO_IMPORT",
            MEDIUM,
            "Duty notice sent to import@ (Tejal) without account@ in TO — accounts may miss it.",
            {"to": email_to},
        ))

    return warnings


def detect_sla_breach(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detect SLA breaches based on audit timestamps.
    """
    warnings = []
    carrier  = _detect_carrier(audit)

    # ── Duty payment SLA ──────────────────────────────────────────────────────
    duty_at = audit.get("duty_notice_received_at")
    paid_at = audit.get("duty_paid_signal_at")
    if duty_at and not paid_at:
        hrs = _hours_since(duty_at)
        if hrs > _DUTY_CRITICAL_HOURS:
            warnings.append(_warn(
                "DUTY_PAYMENT_CRITICAL",
                HIGH,
                f"Duty payment {hrs:.0f}h overdue (critical threshold: {_DUTY_CRITICAL_HOURS}h).",
                {"duty_notice_at": duty_at, "hours_elapsed": round(hrs, 1)},
            ))
        elif hrs > _DUTY_WARNING_HOURS:
            warnings.append(_warn(
                "DUTY_PAYMENT_WARNING",
                MEDIUM,
                f"Duty payment {hrs:.0f}h pending (warning threshold: {_DUTY_WARNING_HOURS}h).",
                {"duty_notice_at": duty_at, "hours_elapsed": round(hrs, 1)},
            ))

    # ── DHL: DSK missing after arrival ────────────────────────────────────────
    tracking = audit.get("tracking") or {}
    clearance_at = audit.get("clearance_updated_at") or audit.get("timestamp")

    if (carrier == "DHL" and
        tracking.get("arrived_warehouse") and
        not audit.get("dsk_filename") and
        clearance_at):
        hrs = _hours_since(clearance_at)
        if hrs > _DSK_WARNING_HOURS:
            warnings.append(_warn(
                "DSK_MISSING_WARNING",
                MEDIUM,
                f"DHL shipment arrived {hrs:.0f}h ago but no DSK generated.",
                {"hours_elapsed": round(hrs, 1), "awb": audit.get("awb")},
            ))

    # ── FedEx: cesja not submitted ────────────────────────────────────────────
    fedex_arrival = audit.get("fedex_arrival_at")
    cesja_at      = audit.get("cesja_submitted_at")
    if carrier == "FEDEX" and fedex_arrival and not cesja_at:
        hrs = _hours_since(fedex_arrival)
        if hrs > _CESJA_WARNING_HOURS:
            warnings.append(_warn(
                "FEDEX_CESJA_NOT_SUBMITTED",
                HIGH,
                f"FedEx shipment arrived {hrs:.0f}h ago. Cesja not submitted to pl-import@fedex.com.",
                {"fedex_arrival_at": fedex_arrival, "hours_elapsed": round(hrs, 1)},
            ))

    # ── Full clearance SLA breach ─────────────────────────────────────────────
    arrived_at   = audit.get("carrier_arrived_at") or audit.get("clearance_updated_at")
    cargo_released = audit.get("cargo_released_at")
    if arrived_at and not cargo_released:
        hrs = _hours_since(arrived_at)
        sla = _SLA_DHL_FULL_HOURS if carrier == "DHL" else _SLA_FEDEX_FULL_HOURS
        if hrs > sla:
            warnings.append(_warn(
                "CLEARANCE_SLA_BREACH",
                HIGH,
                f"Clearance SLA breached: {hrs:.0f}h elapsed (SLA={sla}h for {carrier}).",
                {"arrived_at": arrived_at, "hours_elapsed": round(hrs, 1), "carrier": carrier},
            ))
        elif hrs > sla * 0.8:  # 80% threshold warning
            warnings.append(_warn(
                "CLEARANCE_SLA_AT_RISK",
                MEDIUM,
                f"Clearance approaching SLA: {hrs:.0f}h elapsed ({sla}h limit for {carrier}).",
                {"arrived_at": arrived_at, "hours_elapsed": round(hrs, 1), "carrier": carrier},
            ))

    # ── DHL storage fee risk ──────────────────────────────────────────────────
    if carrier == "DHL" and arrived_at and not cargo_released:
        days_elapsed = _hours_since(arrived_at) / 24
        if days_elapsed > _STORAGE_FEE_DAYS:
            warnings.append(_warn(
                "DHL_STORAGE_FEE_RISK",
                MEDIUM,
                f"DHL shipment held {days_elapsed:.1f} days. Storage fees may apply after day {_STORAGE_FEE_DAYS}.",
                {"arrived_at": arrived_at, "days_elapsed": round(days_elapsed, 1)},
            ))

    return warnings


def detect_unknown_sender(sender: str) -> List[Dict[str, Any]]:
    """
    Detect if sender is not in the known trusted list.
    """
    if not sender:
        return []
    s = sender.strip().lower()
    if s in _TRUSTED_SENDERS:
        return []
    # Check domain match for ganther
    if s.endswith("@ganther.com.pl") or "ganther.com.pl" in s:
        return []
    return [_warn(
        "UNKNOWN_SENDER",
        LOW,
        f"Email from unknown sender '{sender}' — not in trusted senders list.",
        {"sender": sender, "action": "Admin review needed"},
    )]


def detect_vat_deferment(email_body: str) -> List[Dict[str, Any]]:
    """
    Detect VAT deferment issue keywords in email body (Ganther emails only).
    """
    body_low = email_body.lower()
    keywords = [
        "vat deferment", "odroczenie vat", "brak pozwolenia",
        "pozwolenie wygasło", "no permission for vat",
        "vat zostanie zapłacony przed",
    ]
    for kw in keywords:
        if kw in body_low:
            return [_warn(
                "VAT_DEFERMENT_GAP",
                HIGH,
                f"VAT deferment issue detected in Ganther email (keyword: '{kw}'). "
                f"Previous lapse caused clearance hold on AWB 6883058851 Dec 2025.",
                {"keyword_matched": kw, "action": "Contact account@ to renew VAT deferment permission"},
            )]
    return []


def detect_fca_complication(email_body: str) -> List[Dict[str, Any]]:
    """
    Detect FCA incoterms complication in email body.
    """
    body_low = email_body.lower()
    if "fca" in body_low and ("transport" in body_low or "faktura" in body_low):
        return [_warn(
            "FCA_COMPLICATION",
            MEDIUM,
            "FCA incoterms detected. Ganther will need transport invoice from shipper — "
            "adds 1-2 days to FedEx clearance.",
            {"action": "Request transport invoice from shipper now"},
        )]
    return []


def detect_ganther_invoice_overdue(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detect if Ganther invoice is overdue (2nd notice or >14 days unpaid).
    """
    warnings = []
    timeline  = audit.get("timeline") or []

    invoice_events = [e for e in timeline if e.get("event") == "ganther_invoice_received"]
    if len(invoice_events) >= 2:
        # Multiple invoice events for same batch — possible duplicate or overdue
        warnings.append(_warn(
            "GANTHER_INVOICE_DUPLICATE",
            MEDIUM,
            f"Multiple Ganther invoice events ({len(invoice_events)}) for this batch — "
            f"possible overdue re-send.",
            {"invoice_count": len(invoice_events)},
        ))

    for ev in invoice_events:
        ts = ev.get("ts", "")
        if ts:
            hrs = _hours_since(ts)
            if hrs > 24 * 14:  # 14 days
                warnings.append(_warn(
                    "GANTHER_INVOICE_OVERDUE",
                    MEDIUM,
                    f"Ganther invoice unpaid for {hrs/24:.0f} days. "
                    f"Pattern that caused 2,962 PLN accumulation Jan 2026.",
                    {"invoice_ts": ts, "days_unpaid": round(hrs/24, 1)},
                ))

    return warnings


# ── Main detection entry point ────────────────────────────────────────────────

def detect_all_risks(
    audit: Dict[str, Any],
    email_to: Optional[str] = None,
    email_cc: Optional[str] = None,
    email_body: Optional[str] = None,
    sender: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run all risk detectors and return combined warnings list.

    Args:
        audit:      audit.json dict for the current batch
        email_to:   TO header of latest inbound email (optional)
        email_cc:   CC header of latest inbound email (optional)
        email_body: Body of latest inbound email (optional)
        sender:     FROM address of latest inbound email (optional)

    Returns:
        List of warning dicts sorted by severity (HIGH first).
    """
    warnings: List[Dict[str, Any]] = []

    # Audit-based checks
    warnings.extend(detect_sla_breach(audit))
    warnings.extend(detect_ganther_invoice_overdue(audit))

    # Email-based checks (when email context provided)
    if email_to is not None or email_cc is not None:
        warnings.extend(detect_duty_routing_gap(email_to, email_cc, email_body))

    if email_body:
        warnings.extend(detect_vat_deferment(email_body))
        warnings.extend(detect_fca_complication(email_body))

    if sender:
        warnings.extend(detect_unknown_sender(sender))

    # Sort: HIGH first
    severity_order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    warnings.sort(key=lambda w: severity_order.get(w["severity"], 3))

    return warnings

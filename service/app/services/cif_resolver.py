"""
cif_resolver.py — Tri-state CIF authority resolver.

Single, pure function that answers ONE question for the whole platform:

    "What is the customs CIF value for this shipment, and how confident
     are we in it?"

The answer is tri-state — never a silent fake zero:

    RESOLVED      a usable USD value was found in an authoritative layer
    DECLARED_ZERO the source documents explicitly say the value is zero
    UNKNOWN       no layer produced a value — extraction failed / not run

The historic bug this module exists to kill: an OCR / parser / AI
extraction failure would collapse CIF to ``0.0`` and that fake zero would
flow downstream as if it were a real declared value, silently mis-routing
clearance and suppressing the "we don't know yet" signal the operator
needs. ``resolve_cif`` makes that impossible — a missing value is
``cif_usd=None`` + ``cif_state="unknown"`` + an ``extraction_gap`` marker,
NOT ``0.0``.

Authority ladder (highest priority first)
------------------------------------------
1. verification.invoice_cif_total_usd     engine-verified invoice CIF
2. invoice_totals.total_cif_usd           parsed invoice CIF total
3. invoice_totals.total_fob_usd           parsed invoice FOB (no freight) — fallback
4. dhl_precheck.invoice_cif_total_usd     pre-check parsed invoice CIF
5. dhl_precheck.fob_total_usd             pre-check parsed FOB — fallback
6. awb_customs.value_usd                  carrier-declared AWB Custom Val (USD only)

Invoice authority (layers 1–5) always outranks the carrier-declared AWB
Custom Val (layer 6). The AWB value is the last resort *before* UNKNOWN —
it is what lets a shipment whose invoice CIF never reached the audit still
resolve from the waybill's declared customs value.

Safety
------
- Pure. Never raises. Never writes. Never fabricates 0.0 for an UNKNOWN.
- AWB Custom Val is honoured only when its currency is USD; a non-USD AWB
  value (or one flagged with an extraction gap) is treated as a gap, never
  silently converted.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Tri-state constants ─────────────────────────────────────────────────────

CIF_RESOLVED:      str = "resolved"
CIF_DECLARED_ZERO: str = "declared_zero"
CIF_UNKNOWN:       str = "unknown"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _coerce_positive(value: Any) -> Optional[float]:
    """Return a positive float, or None if the value is missing / unparseable /
    non-positive. Never raises. A value of exactly 0 returns None here — a real
    declared zero is detected separately via ``_declared_zero_signal`` so that a
    parser-miss zero is never mistaken for an authoritative zero."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 0:
        return v
    return None


def _declared_zero_signal(audit: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Detect an EXPLICIT declared-zero signal in the source documents.

    A declared zero is only honoured when the source unambiguously says the
    customs value is zero — never inferred from a parser that simply failed to
    find a number. Two accepted signals:

      1. ``audit["customs_declared_value_zero"] is True`` — an explicit operator/
         document assertion that the declared customs value is genuinely zero
         (e.g. a no-commercial-value sample shipment).
      2. AWB Custom Val parsed a literal ``0`` with NO extraction gap — i.e. the
         waybill carried a customs value field and it really was zero.

    Returns a ``{source, reason}`` dict when a declared zero is found, else None.
    """
    if audit.get("customs_declared_value_zero") is True:
        return {
            "source": "audit.customs_declared_value_zero",
            "reason": "source explicitly declares customs value of zero",
        }

    awb = audit.get("awb_customs") or {}
    # Only treat AWB zero as declared when the parser actually read a value
    # field (no gap) AND the currency is USD. Anything else is a gap, not a
    # declared zero.
    if not awb.get("gap"):
        cur = str(awb.get("currency") or "").upper()
        raw = awb.get("value_usd")
        if cur in ("", "USD") and raw is not None:
            try:
                if float(raw) == 0.0:
                    return {
                        "source": "awb_customs.value_usd",
                        "reason": "AWB Custom Val field present and explicitly zero",
                    }
            except (TypeError, ValueError):
                pass
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def resolve_cif(audit: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the customs CIF value with full provenance and tri-state outcome.

    Parameters
    ----------
    audit : dict
        The shipment audit record.

    Returns
    -------
    dict with fields::

        {
          "cif_usd":       float | None,   # None ONLY when state == unknown
          "cif_state":     "resolved" | "declared_zero" | "unknown",
          "cif_source":    str,            # which layer won, or "unavailable"
          "attempts":      [ {layer, value, used}, ... ],  # ordered trace
          "extraction_gap": { first_failed_layer, reason, next_action } | None,
        }

    Contract guarantees:
      - ``cif_usd`` is never a fabricated 0.0. It is a positive float when
        RESOLVED, exactly 0.0 when DECLARED_ZERO, and None when UNKNOWN.
      - The function is pure and never raises.
    """
    audit = audit or {}
    ver      = audit.get("verification") or {}
    it       = audit.get("invoice_totals") or {}
    precheck = audit.get("dhl_precheck") or {}
    awb      = audit.get("awb_customs") or {}

    # AWB Custom Val is only usable as a number when the currency is USD and the
    # parser did not flag an extraction gap. Otherwise it counts as a failed
    # layer (gap), never a silent conversion.
    awb_usd: Optional[float] = None
    awb_blocked_reason: Optional[str] = None
    if awb:
        awb_cur = str(awb.get("currency") or "").upper()
        if awb.get("gap"):
            awb_blocked_reason = "AWB Custom Val present but parser flagged an extraction gap"
        elif awb_cur not in ("", "USD"):
            awb_blocked_reason = f"AWB Custom Val is in {awb_cur}, not USD — not auto-converted"
        else:
            awb_usd = _coerce_positive(awb.get("value_usd"))

    # Ordered authority ladder: (layer_label, raw_value)
    ladder: List[Tuple[str, Any]] = [
        ("verification.invoice_cif_total_usd",  ver.get("invoice_cif_total_usd")),
        ("invoice_totals.total_cif_usd",        it.get("total_cif_usd")),
        ("invoice_totals.total_fob_usd",        it.get("total_fob_usd")),
        ("dhl_precheck.invoice_cif_total_usd",  precheck.get("invoice_cif_total_usd")),
        ("dhl_precheck.fob_total_usd",          precheck.get("fob_total_usd")),
        ("awb_customs.value_usd",               awb_usd),
    ]

    attempts: List[Dict[str, Any]] = []
    for layer_label, raw in ladder:
        v = _coerce_positive(raw)
        attempts.append({"layer": layer_label, "value": v, "used": False})
        if v is not None:
            attempts[-1]["used"] = True
            log.info(
                "[cif_resolver] RESOLVED cif=%.2f from %s", v, layer_label,
            )
            return {
                "cif_usd":        round(v, 2),
                "cif_state":      CIF_RESOLVED,
                "cif_source":     layer_label,
                "attempts":       attempts,
                "extraction_gap": None,
            }

    # No positive value in any layer. Before declaring UNKNOWN, check for an
    # EXPLICIT declared-zero signal (genuine zero-value shipment).
    declared = _declared_zero_signal(audit)
    if declared is not None:
        log.info(
            "[cif_resolver] DECLARED_ZERO via %s (%s)",
            declared["source"], declared["reason"],
        )
        return {
            "cif_usd":        0.0,
            "cif_state":      CIF_DECLARED_ZERO,
            "cif_source":     declared["source"],
            "attempts":       attempts,
            "extraction_gap": None,
        }

    # UNKNOWN — every layer failed. Build an operator-actionable gap marker that
    # names the FIRST layer that should have produced a value and the next step.
    first_failed_layer, reason, next_action = _diagnose_gap(
        audit, it, ver, precheck, awb, awb_blocked_reason,
    )
    log.warning(
        "[cif_resolver] UNKNOWN — no CIF in any layer. first_failed=%s reason=%s",
        first_failed_layer, reason,
    )
    return {
        "cif_usd":        None,
        "cif_state":      CIF_UNKNOWN,
        "cif_source":     "unavailable",
        "attempts":       attempts,
        "extraction_gap": {
            "first_failed_layer": first_failed_layer,
            "reason":             reason,
            "next_action":        next_action,
        },
    }


def _diagnose_gap(
    audit: Dict[str, Any],
    it: Dict[str, Any],
    ver: Dict[str, Any],
    precheck: Dict[str, Any],
    awb: Dict[str, Any],
    awb_blocked_reason: Optional[str],
) -> Tuple[str, str, str]:
    """Decide the smallest operator-actionable next step for an UNKNOWN CIF.

    Returns ``(first_failed_layer, reason, next_action)``. Ordering mirrors the
    real extraction pipeline: invoice upload → invoice parse → CIF compute →
    AWB Custom Val fallback.
    """
    has_invoice = bool(
        audit.get("invoice_names")
        or (audit.get("inputs") or {}).get("invoices")
    )
    if not has_invoice:
        return (
            "invoice_upload",
            "No purchase invoice has been uploaded for this shipment",
            "Upload the commercial invoice PDF, then run Recheck",
        )

    parsed_anything = bool(it or ver or precheck)
    if not parsed_anything:
        return (
            "invoice_parse",
            "Invoice uploaded but no totals were parsed from it",
            "Run Recheck to re-parse the invoice; if it still fails the invoice "
            "may need manual review",
        )

    # Something parsed but no CIF/FOB number landed. If the AWB carried a value
    # we could not use, surface that as the proximate cause.
    if awb_blocked_reason:
        return (
            "awb_customs.value_usd",
            awb_blocked_reason,
            "Confirm the AWB Custom Val currency / re-run AWB parse, or enter "
            "the CIF from the invoice manually",
        )

    if awb and awb.get("gap"):
        return (
            "awb_customs.value_usd",
            "AWB Custom Val could not be parsed from the waybill",
            "Re-run AWB parse or enter the customs value from the invoice",
        )

    return (
        "invoice_totals.cif_compute",
        "Invoice parsed but neither CIF nor FOB produced a usable value",
        "Run Recheck after confirming the invoice shows FOB/Freight/Insurance "
        "or a CIF total; otherwise enter the CIF manually",
    )

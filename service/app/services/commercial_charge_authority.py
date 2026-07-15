"""commercial_charge_authority.py — the one CommercialChargeAuthority (PR-6).

Single interpretation of a proforma draft's persisted ``service_charges_json``
snapshot. Every commercial consumer — proforma totals, preview, print, AWB
declared value, wFirma posting, finance projection — reads THIS one resolved
result. No consumer re-sums the charges independently.

Explicit charge resolution
--------------------------
A zero freight or insurance amount is a *valid commercial decision*, not
automatically an error. The operator declares intent through a persisted
``resolution`` on each charge; the amount alone never implies intent.

Resolution states (persisted on the charge, written by the ONE service-charge
writer — never inferred at read time):

  * ``calculated``       — amount produced by an explicit Calculate-from-Customer
                           -Master action and FROZEN (with its formula evidence).
  * ``manual_amount``    — operator typed the amount (may legitimately be 0).
  * ``customer_courier`` — client provides their own courier; amount is 0.
  * ``waived``           — charge waived by the operator; amount is 0.
  * ``not_applicable``   — charge does not apply; amount is 0.
  * ``unresolved``       — no explicit decision yet. Excluded from the billable
                           subtotal and surfaced for operator review.

Governance rules (operator-ratified, PR-6):
  * The draft snapshot is the SOLE financial source once a charge is saved.
  * Only charges whose currency == the draft currency enter the subtotal.
  * Cross-currency charges are surfaced separately, never converted or summed.
  * The premium is computed by ONE formula (:func:`insurance_premium`) at the
    Calculate action (WRITE time) and frozen. **This module never recomputes a
    saved amount at read time** — a persisted zero stays zero.
  * A zero with an explicit zero-state (customer_courier / waived / not_applicable
    / manual_amount) is VALID and does not block. A zero with NO explicit
    resolution and with insurance formula/rate evidence is ``unresolved``.
  * Intent is never inferred from the amount alone.
  * Customs CIF is a SEPARATE import-side authority (``cif_resolver``). Nothing
    here feeds it, and it feeds nothing here.

Pure module: no I/O, no Customer Master dependency, no live-table read.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

_CENTS = Decimal("0.01")
_CHARGE_TYPES = ("freight", "insurance")

# ── Resolution vocabulary (the authority owns it; the writer imports it) ──────
RESOLUTION_CALCULATED = "calculated"
RESOLUTION_MANUAL = "manual_amount"
RESOLUTION_CUSTOMER_COURIER = "customer_courier"
RESOLUTION_WAIVED = "waived"
RESOLUTION_NOT_APPLICABLE = "not_applicable"
RESOLUTION_UNRESOLVED = "unresolved"

RESOLUTION_STATES = frozenset({
    RESOLUTION_CALCULATED,
    RESOLUTION_MANUAL,
    RESOLUTION_CUSTOMER_COURIER,
    RESOLUTION_WAIVED,
    RESOLUTION_NOT_APPLICABLE,
    RESOLUTION_UNRESOLVED,
})

#: Explicit zero-states: a persisted amount of 0 is a valid commercial decision.
_ZERO_OK_STATES = frozenset({
    RESOLUTION_CUSTOMER_COURIER,
    RESOLUTION_WAIVED,
    RESOLUTION_NOT_APPLICABLE,
})
#: States whose persisted amount is authoritative and billable as stored.
_AMOUNT_STATES = frozenset({RESOLUTION_CALCULATED, RESOLUTION_MANUAL})


def insurance_premium(sales_total: Any, rate: Any, minimum: Any = None) -> Decimal:
    """The ONE insurance premium formula: ``max(sales_total × rate, minimum)``,
    quantised to cents. ``rate`` is the fraction (e.g. 0.0035), NOT a percentage.

    Reused ONLY at write time — by ``customer_master.compute_insurance_suggestion``
    (the Calculate action). This module never calls it at read time, so a saved
    zero is never silently recomputed.
    """
    computed = Decimal(str(sales_total)) * Decimal(str(rate))
    if minimum is not None and Decimal(str(minimum)) > 0:
        computed = max(computed, Decimal(str(minimum)))
    return computed.quantize(_CENTS)


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _norm_resolution(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    return s if s in RESOLUTION_STATES else None


def _has_insurance_evidence(charge: Dict[str, Any]) -> bool:
    """True when a charge carries insurance formula/rate evidence (a rate or a
    sales_total in ``formula_basis``, or a top-level ``insurance_rate``)."""
    fb = charge.get("formula_basis") if isinstance(charge.get("formula_basis"), dict) else {}
    for key, src in (("rate_pct", fb), ("sales_total", fb), ("insurance_rate", charge)):
        val = src.get(key)
        if val is not None and str(val).strip() != "":
            return True
    return False


def classify_charge(charge: Dict[str, Any]) -> Dict[str, Any]:
    """Classify one charge into a resolved record WITHOUT recomputing anything.

    Returns::
        {charge_type, charge_id, currency, amount (billable Decimal),
         resolution (state|None), billable (bool), present (bool), reason (str|"")}

    * amount is the PERSISTED amount for billable/amount states; forced to 0 for
      explicit zero-states; 0 and non-billable for unresolved.
    * intent is read from ``resolution`` — never inferred from the amount.
    """
    ctype = str(charge.get("charge_type") or "").strip().lower()
    res = _norm_resolution(charge.get("resolution"))
    amt = _dec(charge.get("amount"))
    cur = str(charge.get("currency") or "").strip().upper()
    out = {
        "charge_type": ctype,
        "charge_id": charge.get("charge_id"),
        "currency": cur,
        "amount": Decimal("0"),
        "resolution": res,
        "billable": False,
        "present": False,
        "reason": "",
    }

    if res == RESOLUTION_UNRESOLVED:
        out["reason"] = "charge marked unresolved — awaiting operator decision"
        return out

    if res in _ZERO_OK_STATES:
        # Valid zero: a real commercial decision. Contributes 0, never blocks.
        out.update(amount=Decimal("0"), billable=True, present=True,
                   reason=f"zero by operator decision ({res})")
        return out

    if res in _AMOUNT_STATES:
        # calculated / manual_amount: the persisted amount is authoritative as-is
        # (including a legitimate 0 — never recomputed here).
        val = amt if amt is not None else Decimal("0")
        out.update(amount=val, billable=True, present=(val > 0),
                   reason=("manual zero" if (res == RESOLUTION_MANUAL and val == 0) else ""))
        return out

    # ── No explicit resolution (legacy row) ──────────────────────────────────
    if amt is not None and amt > 0:
        # A concrete persisted amount is billable as stored; resolution stays
        # None (UI may prompt the operator to confirm) — amount is NOT recomputed.
        out.update(amount=amt, billable=True, present=True)
        return out

    # amount is 0 / missing and there is no explicit resolution.
    if ctype == "insurance" and _has_insurance_evidence(charge):
        # Rule 2: ambiguous legacy zero with formula/rate evidence → unresolved.
        out.update(resolution=RESOLUTION_UNRESOLVED,
                   reason="insurance amount is zero with formula/rate evidence "
                          "but no explicit resolution — needs operator decision")
        return out

    # Plain zero with no evidence and no resolution: nothing to bill, not a
    # blocker. Contributes 0 and is not surfaced for review.
    out.update(amount=Decimal("0"), billable=True, present=False)
    return out


def resolve_commercial_charges(
    draft_currency: str,
    service_charges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve the canonical freight + insurance totals from the draft snapshot.

    Returns::
        {
          "currency": "USD",
          "freight_total": 100.00,
          "insurance_total": 18.79,
          "service_charge_subtotal": 118.79,
          "charges": [ {charge_type, amount, currency, resolution, billable, present, reason} ],
          "cross_currency_charges": [ {charge_type, amount, currency, charge_id, resolution} ],
          "unresolved_charges":     [ {charge_type, charge_id, resolution, reason, have} ],
          "provenance": {"source": "draft_snapshot", "currency_rule": "same_currency_only"},
        }
    """
    ccy = (draft_currency or "").strip().upper()
    charges = service_charges if isinstance(service_charges, list) else []

    freight_total = Decimal("0")
    insurance_total = Decimal("0")
    resolved: List[Dict[str, Any]] = []
    cross: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    for c in charges:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("charge_type") or "").strip().lower()
        if ctype not in _CHARGE_TYPES:
            continue
        cur = str(c.get("currency") or "").strip().upper()

        # Same-currency rule: a charge in another currency is surfaced but NEVER
        # summed or converted.
        if ccy and cur and cur != ccy:
            cross.append({
                "charge_type": ctype,
                "amount":      c.get("amount"),
                "currency":    cur,
                "charge_id":   c.get("charge_id"),
                "resolution":  _norm_resolution(c.get("resolution")),
            })
            continue

        rec = classify_charge(c)

        if rec["resolution"] == RESOLUTION_UNRESOLVED:
            fb = c.get("formula_basis") if isinstance(c.get("formula_basis"), dict) else {}
            unresolved.append({
                "charge_type": ctype,
                "charge_id":   c.get("charge_id"),
                "resolution":  RESOLUTION_UNRESOLVED,
                "reason":      rec["reason"],
                "have": {
                    "amount":      c.get("amount"),
                    "sales_total": fb.get("sales_total"),
                    "rate_pct":    fb.get("rate_pct"),
                    "currency":    cur or None,
                },
            })
            # Present it in the resolved view too (billable=False) so consumers
            # can render it as "needs review" without a second lookup.
            resolved.append({
                "charge_type": ctype, "amount": 0.0, "currency": cur or ccy or None,
                "resolution": RESOLUTION_UNRESOLVED, "billable": False,
                "present": False, "reason": rec["reason"],
            })
            continue

        amt = rec["amount"]
        if rec["billable"]:
            if ctype == "freight":
                freight_total += amt
            else:
                insurance_total += amt
        resolved.append({
            "charge_type": ctype,
            "amount":      float(amt.quantize(_CENTS)),
            "currency":    cur or ccy or None,
            "resolution":  rec["resolution"],
            "billable":    rec["billable"],
            "present":     rec["present"],
            "reason":      rec["reason"],
        })

    subtotal = freight_total + insurance_total
    return {
        "currency": ccy or None,
        "freight_total": float(freight_total.quantize(_CENTS)),
        "insurance_total": float(insurance_total.quantize(_CENTS)),
        "service_charge_subtotal": float(subtotal.quantize(_CENTS)),
        "charges": resolved,
        "cross_currency_charges": cross,
        "unresolved_charges": unresolved,
        "provenance": {"source": "draft_snapshot", "currency_rule": "same_currency_only"},
    }

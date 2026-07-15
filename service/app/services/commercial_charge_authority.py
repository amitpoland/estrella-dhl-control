"""commercial_charge_authority.py — the one CommercialChargeAuthority (PR-6).

Single interpretation of a proforma draft's persisted ``service_charges_json``
snapshot. Every commercial consumer — proforma totals, preview, print, AWB
declared value, wFirma posting, finance projection — reads THIS one resolved
result. No consumer re-sums the charges independently.

Governance rules (operator-ratified, PR-6):
  * The draft snapshot is the SOLE financial source once a charge is saved.
  * Only charges whose currency == the draft currency enter the subtotal.
  * Cross-currency charges are surfaced separately, never converted or summed
    (no FX in PR-6).
  * The insurance premium is computed by ONE formula (:func:`insurance_premium`)
    at WRITE time and frozen into the charge. The read authority consumes the
    frozen amount; it only recomputes a legacy ``amount == 0`` when the snapshot
    itself already carries the frozen inputs (sales_total, rate_pct, currency;
    minimum is optional by design) — otherwise it returns an incomplete-charge
    state and NEVER invents a premium.
  * Customs CIF is a SEPARATE import-side authority (``cif_resolver``). Nothing
    here feeds it, and it feeds nothing here.

Pure module: no I/O, no Customer Master dependency, no live-table read.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

_CENTS = Decimal("0.01")
_CHARGE_TYPES = ("freight", "insurance")


def insurance_premium(sales_total: Any, rate: Any, minimum: Any = None) -> Decimal:
    """The ONE insurance premium formula: ``max(sales_total × rate, minimum)``,
    quantised to cents. ``rate`` is the fraction (e.g. 0.0035), NOT a percentage.

    Reused by ``customer_master.compute_insurance_suggestion`` (the write path)
    and by this module's frozen-input normalization — it is never duplicated, so
    there is exactly one premium formula in the system.
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
          "cross_currency_charges": [ {charge_type, amount, currency, charge_id} ],
          "incomplete_charges":     [ {charge_type, charge_id, reason, have} ],
          "provenance": {"source": "draft_snapshot", "currency_rule": "same_currency_only"},
        }
    """
    ccy = (draft_currency or "").strip().upper()
    charges = service_charges if isinstance(service_charges, list) else []

    freight_total = Decimal("0")
    insurance_total = Decimal("0")
    cross: List[Dict[str, Any]] = []
    incomplete: List[Dict[str, Any]] = []

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
            })
            continue

        amt = _dec(c.get("amount"))

        if ctype == "freight":
            # Freight is a fixed amount (no formula). A missing amount is 0.
            if amt is not None and amt >= 0:
                freight_total += amt
            continue

        # ── insurance ──
        if amt is not None and amt > 0:
            insurance_total += amt          # frozen premium — the normal path
            continue

        # amount missing/zero: recompute ONLY from FROZEN snapshot inputs, never
        # from live Customer Master. minimum is optional by design (its absence
        # means "no floor", a complete state).
        fb = c.get("formula_basis") if isinstance(c.get("formula_basis"), dict) else {}
        sales_total = _dec(fb.get("sales_total"))
        rate_pct = _dec(fb.get("rate_pct"))
        minimum = _dec(fb.get("minimum_eur") if cur == "EUR" else fb.get("minimum_usd"))
        if sales_total is not None and rate_pct is not None and cur:
            insurance_total += insurance_premium(sales_total, rate_pct / Decimal("100"), minimum)
        else:
            incomplete.append({
                "charge_type": "insurance",
                "charge_id":   c.get("charge_id"),
                "reason":      "insurance amount not frozen and formula inputs incomplete",
                "have": {
                    "sales_total": fb.get("sales_total"),
                    "rate_pct":    fb.get("rate_pct"),
                    "currency":    cur or None,
                },
            })

    subtotal = freight_total + insurance_total
    return {
        "currency": ccy or None,
        "freight_total": float(freight_total.quantize(_CENTS)),
        "insurance_total": float(insurance_total.quantize(_CENTS)),
        "service_charge_subtotal": float(subtotal.quantize(_CENTS)),
        "cross_currency_charges": cross,
        "incomplete_charges": incomplete,
        "provenance": {"source": "draft_snapshot", "currency_rule": "same_currency_only"},
    }

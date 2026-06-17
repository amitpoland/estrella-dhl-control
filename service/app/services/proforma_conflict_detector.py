"""
proforma_conflict_detector.py — ADR-029 Proforma Workspace conflict detectors.

PURE, READ-ONLY, wFirma-FREE detection (ADR-021 Invariant 7). This module takes
already-resolved local inputs (the draft's stored values + the matched
``CustomerMaster`` row + the service-charge snapshot) and returns a list of
advisory ``Detection`` records. It performs NO database access and NO network
I/O — the calling route resolves the customer locally (``_resolve_customer`` →
``get_customer``) and passes the result in, which keeps every detector unit-
testable and keeps drift detection strictly pre-gate.

Conflict detection is advisory (ADR-029 §3, a typed extension of ADR-025 soft
validation). The route persists each ``Detection`` via
``proforma_conflict_db.upsert_conflict`` and the only hard gate (the wFirma
write boundary, ADR-029 §5) is consulted separately via
``has_open_blocking_conflict`` behind ``conflict_posting_blocker``.

Scope (PR-1) — four of the eight plan §6.2 validators are implemented here:

  V3  currency_vs_customer_default      (warning, Customer Service)
  V4  bank_account_currency_unsupported (error,   Proforma / Finance)
  V5  customer_vat_eu_changed           (warning / error, VAT authority)
  V8  service_charge_defaults_changed   (warning, Customer Service / Finance)

The other four (inventory_insufficient, sku_missing_or_discontinued,
customer_address_or_terms_changed, product_hs_origin_uom_changed) are registered
in ``proforma_conflict_db.CONFLICT_TYPES`` but their detectors are deferred to
PR-2 — see ``IMPLEMENTED_CONFLICT_TYPES`` below.

STATUS (governance — PR sequencing):
  - Divergence Detection (current draft vs current master) ... IMPLEMENTED (PR-1)
  - Temporal Drift Detection ("changed since draft creation") . DEFERRED to the
        ADR-022 snapshot layer (PR-2). Do NOT claim "changed since draft
        creation" before the snapshot columns exist — doing so without them
        asserts false authority. The master-COMPARISON divergence checks
        therefore carry ``evidence["semantic"] = "divergence_not_temporal_drift"``
        + a pr2_todo marker so reviewers/UI never misread divergence as
        temporal drift. That marker applies to the three checks that compare a
        draft value against a *current* master value — V3 currency_vs_customer_default,
        V5 customer_vat_eu_changed, V8 service_charge_defaults_changed — each of
        which is divergence now and becomes a true temporal-drift check in PR-2.
        V4 bank_account_currency_unsupported is deliberately NOT marked: it is a
        STATIC eligibility error (the draft currency has no company bank account),
        not a master comparison and never a temporal-drift candidate, so it
        carries no semantic marker.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from ..models.proforma_resolver import COMPANY_ACCOUNT_BY_CURRENCY
from ..models.vat_resolver import (
    CustomerForVAT,
    ManualReviewRequired,
    pick_vat_code,
)

# Only these conflict_type values are actually produced by this module in PR-1.
# The route uses this set to bound what it scans; the DB store still registers
# the full 8-type vocabulary so the schema/contract is stable for PR-2.
IMPLEMENTED_CONFLICT_TYPES = frozenset({
    "currency_vs_customer_default",
    "bank_account_currency_unsupported",
    "customer_vat_eu_changed",
    "service_charge_defaults_changed",
})

# Currencies for which a fixed service-charge column exists on CustomerMaster.
# PLN drafts have no *_fixed_amount_* column, so V8 cannot compare them and
# stays silent (conservative — never emit a conflict we cannot substantiate).
_FIXED_CHARGE_CURRENCIES = frozenset({"EUR", "USD"})

# The draft stores vat_code as a wFirma <code> STRING ("23"|"WDT"|"EXP"|"NP"),
# whereas vat_resolver.pick_vat_code returns the numeric wFirma vat_code_id
# (222/228/229). To compare like-for-like without importing wfirma_client
# (which would break the wFirma-free purity contract), we translate the
# resolver's numeric output back into the draft's code-string vocabulary using
# the same canonical pairing wfirma_client._VAT_ID_TO_CONTEXT pins
# (222→"23", 228→"WDT", 229→"EXP", 230→"NP"). pick_vat_code only ever returns
# 222/228/229, so those three are sufficient.
_VAT_ID_TO_CODE = {222: "23", 228: "WDT", 229: "EXP", 230: "NP"}

# Governance marker (ADR-029 / ADR-022). PR-1 detects DIVERGENCE (current draft
# vs current master), NOT temporal drift ("changed since draft creation"), which
# needs the ADR-022 snapshot layer (PR-2). Every divergence-class finding carries
# this so the marker is never silently mistaken for a since-creation claim.
_PR2_TODO = "PR-2/ADR-022 snapshot: replace divergence with true since-creation drift"
_DIVERGENCE_EVIDENCE = {"semantic": "divergence_not_temporal_drift", "pr2_todo": _PR2_TODO}


@dataclass(frozen=True)
class Detection:
    """One advisory finding. Maps 1:1 onto ``upsert_conflict`` kwargs.

    ``current_value`` / ``master_value`` are stringified for storage (the store
    column is TEXT and nullable). Detectors keep them human-readable.
    """
    conflict_type:   str
    severity:        str           # "error" | "warning"
    authority_owner: str
    field_affected:  str
    current_value:   Optional[str]
    master_value:    Optional[str]
    reason:          str
    evidence:        Dict[str, Any] = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _norm_currency(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().upper()
    return v or None


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Coerce a snapshot/master amount to Decimal; None/blank → None.

    Mirrors the route idiom ``Decimal(str(c.get("amount") or 0))`` but returns
    None (not 0) for genuinely-absent values so a missing charge is
    distinguishable from a zero charge.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def parse_service_charges(raw: Any) -> List[Dict[str, Any]]:
    """Normalise the draft ``service_charges_json`` snapshot to a list of dicts.

    Accepts either an already-parsed list (the route may pass the live list) or
    the JSON string stored on the draft row. Anything malformed → ``[]`` (a
    detector must never raise on bad snapshot data; absence simply means
    "nothing to compare").
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            return []
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, dict)]
    return []


def _charge_amount(charges: List[Dict[str, Any]], charge_type: str) -> Optional[Decimal]:
    """Return the draft snapshot amount for a charge_type, or None if absent."""
    for c in charges:
        if str(c.get("charge_type") or "").strip().lower() == charge_type:
            return _to_decimal(c.get("amount"))
    return None


def _master_fixed_charge(
    customer: Any, charge_type: str, currency: str,
) -> Optional[Decimal]:
    """Return the CustomerMaster fixed amount for (charge_type, currency).

    Only returns a value when the master is in a *fixed* mode for that charge
    AND the currency has a fixed-amount column. Otherwise None (no comparable
    default → V8 stays silent for that charge).
    """
    cur = currency.upper()
    if cur not in _FIXED_CHARGE_CURRENCIES:
        return None
    suffix = "eur" if cur == "EUR" else "usd"

    if charge_type == "freight":
        if (getattr(customer, "freight_mode", None) or "") != "fixed":
            return None
        return _to_decimal(getattr(customer, f"freight_fixed_amount_{suffix}", None))

    if charge_type == "insurance":
        if not getattr(customer, "insurance_enabled", True):
            return None
        if (getattr(customer, "insurance_mode", None) or "") != "fixed":
            return None
        return _to_decimal(getattr(customer, f"insurance_fixed_amount_{suffix}", None))

    return None


# ── Individual detectors ─────────────────────────────────────────────────────

def _detect_currency_vs_customer_default(
    currency: Optional[str], customer: Any,
) -> Optional[Detection]:
    """V3 — draft currency differs from the customer's master default currency.

    Advisory only (warning). Absent customer or absent default → no finding.
    """
    if customer is None:
        return None
    draft_cur = _norm_currency(currency)
    master_cur = _norm_currency(getattr(customer, "default_currency", None))
    if draft_cur is None or master_cur is None:
        return None
    if draft_cur == master_cur:
        return None
    return Detection(
        conflict_type="currency_vs_customer_default",
        severity="warning",
        authority_owner="Customer Service",
        field_affected="currency",
        current_value=draft_cur,
        master_value=master_cur,
        reason=(
            f"Draft currency {draft_cur} differs from the customer's master "
            f"default currency {master_cur}. Confirm the intended billing "
            f"currency before posting."
        ),
        evidence=_DIVERGENCE_EVIDENCE,
    )


def _detect_bank_account_currency_unsupported(
    currency: Optional[str],
) -> Optional[Detection]:
    """V4 — draft currency has no configured company bank account.

    Hard-class (error) because the proforma cannot carry a bank account line
    for an unsupported currency. Does not require a customer.
    """
    draft_cur = _norm_currency(currency)
    if draft_cur is None:
        return Detection(
            conflict_type="bank_account_currency_unsupported",
            severity="error",
            authority_owner="Proforma / Finance",
            field_affected="currency",
            current_value=None,
            master_value=",".join(sorted(COMPANY_ACCOUNT_BY_CURRENCY)),
            reason=(
                "Draft has no currency set; a company bank account cannot be "
                "selected. Set a supported currency "
                f"({', '.join(sorted(COMPANY_ACCOUNT_BY_CURRENCY))})."
            ),
        )
    if draft_cur in COMPANY_ACCOUNT_BY_CURRENCY:
        return None
    return Detection(
        conflict_type="bank_account_currency_unsupported",
        severity="error",
        authority_owner="Proforma / Finance",
        field_affected="currency",
        current_value=draft_cur,
        master_value=",".join(sorted(COMPANY_ACCOUNT_BY_CURRENCY)),
        reason=(
            f"No company bank account is configured for currency {draft_cur}. "
            f"Supported currencies: {', '.join(sorted(COMPANY_ACCOUNT_BY_CURRENCY))}."
        ),
    )


def _detect_customer_vat_eu_changed(
    vat_code: Any, vat_context: Optional[CustomerForVAT],
) -> Optional[Detection]:
    """V5 — the master now implies a different VAT code than the draft holds.

    - ManualReviewRequired from the resolver → the master is now ambiguous
      (e.g. EU customer lost a confirmed VAT-EU number): ERROR severity.
    - Resolver returns a code that differs from the draft's stored vat_code →
      WARNING (the master drifted; operator confirms / regenerates).
    - Equal, or no context to resolve → no finding.
    """
    if vat_context is None:
        return None

    try:
        expected = pick_vat_code(vat_context)
    except ManualReviewRequired as exc:
        return Detection(
            conflict_type="customer_vat_eu_changed",
            severity="error",
            authority_owner="VAT (master-resolved)",
            field_affected="vat_code",
            current_value=(None if vat_code is None else str(vat_code)),
            master_value="manual_review_required",
            reason=(
                "Customer master VAT state is now ambiguous and cannot be "
                f"auto-resolved: {exc}. Route to manual review before posting."
            ),
            evidence=_DIVERGENCE_EVIDENCE,
        )

    # Translate the resolver's numeric id back to the draft's code-string
    # vocabulary so we compare "23"/"WDT"/"EXP", not 222/228/229. If the id is
    # unexpectedly unmapped or non-numeric, stay silent rather than raise or
    # false-positive (fail-closed, consistent with the rest of this detector).
    try:
        expected_id = int(expected)
    except (TypeError, ValueError):
        return None
    expected_str = _VAT_ID_TO_CODE.get(expected_id)
    if expected_str is None:
        return None

    # Normalise both sides to string for comparison; draft may be int/str/None.
    draft_str = None if vat_code is None else str(vat_code).strip().upper()
    if draft_str is None or draft_str == "":
        # Draft has no VAT code yet but the master resolves one — advise.
        return Detection(
            conflict_type="customer_vat_eu_changed",
            severity="warning",
            authority_owner="VAT (master-resolved)",
            field_affected="vat_code",
            current_value=None,
            master_value=expected_str,
            reason=(
                f"Draft has no VAT code; the customer master resolves to "
                f"{expected_str}. Apply the master VAT code before posting."
            ),
            evidence=_DIVERGENCE_EVIDENCE,
        )
    if draft_str == expected_str:
        return None
    return Detection(
        conflict_type="customer_vat_eu_changed",
        severity="warning",
        authority_owner="VAT (master-resolved)",
        field_affected="vat_code",
        current_value=draft_str,
        master_value=expected_str,
        reason=(
            f"Draft VAT code {draft_str} differs from the master-resolved code "
            f"{expected_str}. The customer's VAT treatment may have changed; "
            f"confirm or regenerate the lines."
        ),
        evidence=_DIVERGENCE_EVIDENCE,
    )


def _detect_service_charge_defaults_changed(
    currency: Optional[str], service_charges: List[Dict[str, Any]], customer: Any,
) -> List[Detection]:
    """V8 — draft freight/insurance amount drifted from the master fixed default.

    Conservative: only compares when the master is in a *fixed* mode for that
    charge AND the currency has a fixed-amount column (EUR/USD). A missing draft
    charge against a configured fixed default is also a finding (operator may
    have dropped a charge the master expects).
    """
    out: List[Detection] = []
    if customer is None:
        return out
    draft_cur = _norm_currency(currency)
    if draft_cur is None:
        return out

    for charge_type in ("freight", "insurance"):
        master_fixed = _master_fixed_charge(customer, charge_type, draft_cur)
        if master_fixed is None:
            continue  # no comparable master default → silent
        draft_amount = _charge_amount(service_charges, charge_type)
        if draft_amount is not None and draft_amount == master_fixed:
            continue  # matches default → no drift
        out.append(Detection(
            conflict_type="service_charge_defaults_changed",
            severity="warning",
            authority_owner="Customer Service / Finance",
            field_affected=f"service_charge.{charge_type}",
            current_value=(None if draft_amount is None else str(draft_amount)),
            master_value=str(master_fixed),
            evidence=_DIVERGENCE_EVIDENCE,
            reason=(
                f"Draft {charge_type} charge "
                f"({'none' if draft_amount is None else draft_amount} {draft_cur}) "
                f"differs from the customer master fixed default "
                f"({master_fixed} {draft_cur}). Confirm the intended amount."
            ),
        ))
    return out


# ── Public entry point ───────────────────────────────────────────────────────

def detect_conflicts(
    *,
    proforma_id: str,
    currency: Optional[str],
    vat_code: Any = None,
    vat_context: Optional[CustomerForVAT] = None,
    service_charges: Optional[List[Dict[str, Any]]] = None,
    customer: Any = None,
) -> List[Detection]:
    """Run all PR-1 detectors and return the advisory findings.

    Pure / read-only / wFirma-free. ``proforma_id`` is accepted for symmetry
    with the store (and to keep the route call site explicit) but the detectors
    themselves do not key on it — the route owns persistence.

    Args:
      proforma_id:     the draft id (passed through for call-site clarity).
      currency:        the draft's stored currency.
      vat_code:        the draft's stored wFirma vat_code (int|str|None).
      vat_context:     CustomerForVAT built from the matched master, or None.
      service_charges: the draft's service-charge snapshot (list or JSON str).
      customer:        the matched CustomerMaster row, or None.
    """
    charges = parse_service_charges(service_charges)
    findings: List[Detection] = []

    v3 = _detect_currency_vs_customer_default(currency, customer)
    if v3 is not None:
        findings.append(v3)

    v4 = _detect_bank_account_currency_unsupported(currency)
    if v4 is not None:
        findings.append(v4)

    v5 = _detect_customer_vat_eu_changed(vat_code, vat_context)
    if v5 is not None:
        findings.append(v5)

    findings.extend(
        _detect_service_charge_defaults_changed(currency, charges, customer)
    )

    return findings

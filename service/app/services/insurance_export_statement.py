"""Insurance Export Statement — read-only assembly of the insurance population.

Two-layer model:
  1. CANONICAL INSURANCE FACTS — assembled here from five existing authorities,
     never persisted, never written back:
       - ledger_fact_universe.load_ar_fact_universe   (wFirma invoice facts)
       - proforma_invoice_link_db.get_draft_by_wfirma_invoice_id
       - commercial_charge_authority.resolve_commercial_charges
       - carrier.persistence.shipment_db.get_shipment_for_draft
       - insurance_fx_provider.get_rate               (approved insurer FX only)
  2. DECLARATION SELECTION — ephemeral, IDs only. The server re-resolves every
     monetary value from the same authorities; the browser never sends amounts.

Insurance premium recovered is read verbatim from the persisted commercial
charge authority. It is NEVER recomputed here (no premium formula of any
kind on the read side) —
the freight/insurance ADR forbids read-side recomputation.

Customer-arranged-transport exclusion is evidence-based only: a freight charge
resolved as ``customer_courier``. Never country- or nationality-based.

FX (fail-closed — operator ruling 2026-08-15, PR #1249 repair): INR conversion
comes exclusively from the ``insurance_fx_provider`` boundary. Until the
approved insurer benchmark is configured, every row degrades (``fx_error`` +
NEEDS REVIEW, null INR columns) — NBP is NOT an insurance FX authority and is
never consulted or silently substituted here.

Precision (operator ruling — Blocker 2): the calculation chain is UN-rounded
Decimals end to end (``cif_raw × 1.10 × fx_rate``); rounding happens only at
serialization (``_money``, ROUND_HALF_UP). Quantizing CIF×1.10 before the FX
multiply is a release blocker (73,621.21 vs the wrong 73,621.68).

Corrections (operator ruling — Blocker 4): a correction NEVER reduces the
insured total automatically. Each correction carries ``correction_reason`` +
``insurance_effect``; with no evidence source for the reason it defaults to
``unknown`` → ``BLOCKED`` (Needs review). Only an explicit operator selection
brings a correction into the declaration.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import wfirma_client
from . import insurance_fx_provider
from .insurance_fx_provider import InsuranceFxError
from .commercial_charge_authority import (
    RESOLUTION_CUSTOMER_COURIER,
    RESOLUTION_UNRESOLVED,
    SOURCE_ISSUED_DOCUMENT,
    resolve_commercial_charges,
)
from .commercial_charge_record_db import (
    CONFLICT_NEEDS_REVIEW,
    get_document_charges,
)
from .carrier.persistence import shipment_db
from .ledger_fact_universe import (
    load_ar_fact_universe,
    timing_fields_from_universe,
)
from .proforma_invoice_link_db import get_draft_by_wfirma_invoice_id
from .shipment_document_manifest import _batch_client_count

log = logging.getLogger("pz.insurance_export")

CENT = Decimal("0.01")
SUM_INSURED_FACTOR = Decimal("1.10")
TEN_PCT = Decimal("0.10")

# ---------------------------------------------------------------------------
# Business vocabulary


class InsuranceStatus:
    INCLUDED = "included"
    EXCLUDED = "excluded"
    CUSTOMER_TRANSPORT = "customer_transport"
    NO_INSURANCE_CHARGED = "no_insurance_charged"
    NEEDS_REVIEW = "needs_review"
    RETURN = "return"
    CANCELLED = "cancelled"


STATUS_LABELS: Dict[str, str] = {
    InsuranceStatus.INCLUDED: "Included",
    InsuranceStatus.EXCLUDED: "Excluded",
    InsuranceStatus.CUSTOMER_TRANSPORT: "Customer-arranged transport",
    InsuranceStatus.NO_INSURANCE_CHARGED: "No insurance charged",
    InsuranceStatus.NEEDS_REVIEW: "Needs review",
    InsuranceStatus.RETURN: "Return",
    InsuranceStatus.CANCELLED: "Cancellation",
}


class InsuranceRecommendation:
    INCLUDE = "recommend_include"
    EXCLUDE = "recommend_exclude"
    REVIEW = "recommend_review"


RECOMMENDATION_LABELS: Dict[str, str] = {
    InsuranceRecommendation.INCLUDE: "Include",
    InsuranceRecommendation.EXCLUDE: "Exclude",
    InsuranceRecommendation.REVIEW: "Review",
}


class CorrectionReason:
    """WHY a correction document was issued (operator vocabulary, Blocker 4).

    No repository evidence source records this today, so assembly defaults to
    UNKNOWN; the values exist so the operator (or a future evidence source)
    can classify each correction explicitly.
    """

    PHYSICAL_RETURN_PARTIAL = "physical_return_partial"
    PHYSICAL_RETURN_FULL = "physical_return_full"
    CANCELLED_BEFORE_DISPATCH = "cancelled_before_dispatch"
    DUPLICATE_DOCUMENT = "duplicate_document"
    COMMERCIAL_DISCOUNT = "commercial_discount"
    CLAIM_DAMAGE = "claim_damage"
    CLAIM_SHORTAGE = "claim_shortage"
    PRICE_CORRECTION = "price_correction"
    UNKNOWN = "unknown"


CORRECTION_REASON_LABELS: Dict[str, str] = {
    CorrectionReason.PHYSICAL_RETURN_PARTIAL: "Physical return (partial)",
    CorrectionReason.PHYSICAL_RETURN_FULL: "Physical return (full)",
    CorrectionReason.CANCELLED_BEFORE_DISPATCH: "Cancelled before dispatch",
    CorrectionReason.DUPLICATE_DOCUMENT: "Duplicate document",
    CorrectionReason.COMMERCIAL_DISCOUNT: "Commercial discount",
    CorrectionReason.CLAIM_DAMAGE: "Claim / damage credit",
    CorrectionReason.CLAIM_SHORTAGE: "Claim / shortage credit",
    CorrectionReason.PRICE_CORRECTION: "Price correction",
    CorrectionReason.UNKNOWN: "Unknown — operator review required",
}


class InsuranceEffect:
    """What a correction is allowed to do to the insured total (Blocker 4)."""

    PARTIAL_REVERSE = "PARTIAL_REVERSE"
    FULL_REVERSE = "FULL_REVERSE"
    NO_EFFECT = "NO_EFFECT"
    POSITIVE_ADJUSTMENT = "POSITIVE_ADJUSTMENT"
    BLOCKED = "BLOCKED"


INSURANCE_EFFECT_LABELS: Dict[str, str] = {
    InsuranceEffect.PARTIAL_REVERSE: "Partial reversal",
    InsuranceEffect.FULL_REVERSE: "Full reversal",
    InsuranceEffect.NO_EFFECT: "No insurance effect",
    InsuranceEffect.POSITIVE_ADJUSTMENT: "Positive adjustment",
    InsuranceEffect.BLOCKED: "Blocked — needs review",
}

# Effects that may move a total AUTOMATICALLY. NO_EFFECT (commercial
# discounts, claim/damage credits) and BLOCKED (unknown reason) never
# reduce the insured total without an explicit operator selection.
_AUTOMATIC_EFFECTS = frozenset(
    {
        InsuranceEffect.PARTIAL_REVERSE,
        InsuranceEffect.FULL_REVERSE,
        InsuranceEffect.POSITIVE_ADJUSTMENT,
    }
)


def classify_correction(
    reason: Optional[str], amount: Optional[Decimal] = None
) -> Tuple[str, str]:
    """Map a correction reason to its permitted insurance effect.

    Pure classifier — the assembly layer supplies the reason (today: always
    ``None`` → UNKNOWN, because no evidence source records why a correction
    was issued). Unknown or unrecognized reasons are BLOCKED: a correction
    can never reduce the insured total automatically.
    """
    normalized = (reason or "").strip().lower()
    if not normalized or normalized == CorrectionReason.UNKNOWN:
        return CorrectionReason.UNKNOWN, InsuranceEffect.BLOCKED
    mapping = {
        CorrectionReason.PHYSICAL_RETURN_PARTIAL: InsuranceEffect.PARTIAL_REVERSE,
        CorrectionReason.PHYSICAL_RETURN_FULL: InsuranceEffect.FULL_REVERSE,
        CorrectionReason.CANCELLED_BEFORE_DISPATCH: InsuranceEffect.FULL_REVERSE,
        CorrectionReason.DUPLICATE_DOCUMENT: InsuranceEffect.FULL_REVERSE,
        CorrectionReason.COMMERCIAL_DISCOUNT: InsuranceEffect.NO_EFFECT,
        CorrectionReason.CLAIM_DAMAGE: InsuranceEffect.NO_EFFECT,
        CorrectionReason.CLAIM_SHORTAGE: InsuranceEffect.NO_EFFECT,
    }
    if normalized in mapping:
        return normalized, mapping[normalized]
    if normalized == CorrectionReason.PRICE_CORRECTION:
        if amount is not None and amount > 0:
            return normalized, InsuranceEffect.POSITIVE_ADJUSTMENT
        return normalized, InsuranceEffect.BLOCKED
    # Unrecognized vocabulary — fail closed.
    return CorrectionReason.UNKNOWN, InsuranceEffect.BLOCKED


# ---------------------------------------------------------------------------
# Typed errors (routes map these to HTTP codes)


class InsuranceExportError(Exception):
    """Base class for insurance-export assembly errors."""


class InsuranceExportFetchError(InsuranceExportError):
    """Bulk wFirma universe fetch failed — route maps to 502."""


class UnknownSelectionError(InsuranceExportError):
    """Selection referenced IDs outside the period — route maps to 422."""

    def __init__(self, unknown: List[str]):
        self.unknown = sorted({str(u) for u in unknown})
        super().__init__("unknown selection ids: %s" % ", ".join(self.unknown))


# ---------------------------------------------------------------------------
# Decimal / serialization helpers


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(value: Optional[Decimal]) -> Optional[str]:
    """Serialize to a 2dp string with commercial rounding (ROUND_HALF_UP).

    The insurer statement rounds half-cents up (72.355 → 72.36,
    795.905 → 795.91); Decimal's default banker's rounding would show
    795.90. Rounding happens ONLY here — never inside the calculation chain
    (Blocker 2)."""
    if value is None:
        return None
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# FX — approved insurance benchmark only, via the fail-closed
# insurance_fx_provider boundary. This module never consults an FX source
# itself (operator ruling 2026-08-15 — Blocker 1) and performs no conversion
# arithmetic of its own: where the approved quote is a cross rate (PLN, via the
# provider's NBP USD bridge — ruling 2026-08-16), this layer only carries the
# provider's two-leg provenance through to the row, verbatim.


def _fx_to_inr(
    currency: Optional[str],
    invoice_date: str,
    cache: Dict[Tuple[str, str], Any],
) -> Tuple[Optional[Decimal], Optional[Dict[str, Any]], Optional[str]]:
    """Return (fx_rate, fx_provenance, fx_error) — errors degrade, never raise.

    The rate is passed through UN-quantized (raw Decimal); rounding happens
    only at serialization (Blocker 2).
    """
    ccy = (currency or "").strip().upper() or "PLN"
    key = (ccy, invoice_date)
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        quote = insurance_fx_provider.get_rate(ccy, invoice_date)
    except InsuranceFxError as exc:
        # The taxonomy kind travels with the message so the row discloses WHY
        # there is no rate (not published / unsupported currency / provider not
        # configured). A missing rate is never rendered as zero.
        result = (None, None, "%s: %s" % (getattr(exc, "kind", "fx_error"), exc))
        cache[key] = result
        return result
    except Exception as exc:  # provider defect — degrade the row
        result = (None, None, "fx_unavailable: %s" % exc)
        cache[key] = result
        return result
    rate = _dec(quote.get("rate"))
    if rate is None or rate <= 0:
        result = (None, None, "missing_rate: provider returned no usable rate")
        cache[key] = result
        return result
    provenance = {
        "source": quote.get("source"),
        "requested_date": quote.get("requested_date"),
        "effective_date": quote.get("effective_date"),
        # How far the applied publication sits before the requested date
        # (weekend / Mumbai or Warsaw holiday walk-back). Disclosed, never hidden.
        "staleness_days": quote.get("staleness_days"),
        "quote_unit": quote.get("quote_unit"),
        "rate_as_published": quote.get("rate_as_published"),
    }
    # Cross-rate quotes carry both source legs. Passed through unchanged (rates
    # stringified like fx_rate itself) so the statement shows WHICH two official
    # publications produced the rate — never a single flattened number.
    if quote.get("derivation"):
        provenance["derivation"] = quote.get("derivation")
        provenance["formula"] = quote.get("formula")
        for leg_key in ("nbp_leg", "india_leg"):
            leg = quote.get(leg_key)
            if isinstance(leg, dict):
                provenance[leg_key] = {
                    k: (str(v) if isinstance(v, Decimal) else v)
                    for k, v in leg.items()
                }
    result = (rate, provenance, None)
    cache[key] = result
    return result


# ---------------------------------------------------------------------------
# Draft linkage + commercial charge authority (read verbatim, never recompute)


def _link_draft(invoice_id: str, db_path: Path):
    try:
        return get_draft_by_wfirma_invoice_id(db_path, str(invoice_id))
    except Exception:
        log.warning("insurance-export: draft lookup failed for invoice %s", invoice_id)
        return None


def _resolve_draft_charges(draft, invoice_currency: Optional[str]) -> Dict[str, Any]:
    try:
        raw = json.loads(draft.service_charges_json or "[]")
    except (ValueError, TypeError):
        raw = []
    if not isinstance(raw, list):
        raw = []
    ccy = (getattr(draft, "currency", "") or "").strip() or (invoice_currency or "")
    return resolve_commercial_charges(ccy, raw)


def _insurance_recovered(resolved: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for ch in resolved.get("charges") or []:
        if (ch.get("charge_type") or "").strip().lower() == "insurance":
            amount = _dec(ch.get("amount"))
            return {
                "amount": _money(amount) if amount is not None else None,
                "currency": ch.get("currency") or resolved.get("currency"),
                "resolution": ch.get("resolution"),
            }
    for ch in resolved.get("unresolved_charges") or []:
        if (ch.get("charge_type") or "").strip().lower() == "insurance":
            return {
                "amount": None,
                "currency": resolved.get("currency"),
                "resolution": RESOLUTION_UNRESOLVED,
            }
    return None


def _invoiced_charges(invoice_id: str, invoice_currency: str) -> Optional[Dict[str, Any]]:
    """What the ISSUED document billed, resolved by the charge authority.

    ``None`` means the document has never been converged (``convergence``
    tool: ``app.tools.converge_commercial_charges``) — the authority holds no
    record and this report cannot speak for the premium. That is a different
    fact from a converged document that billed nothing, which is stored as an
    explicit 0.00 and resolves normally.
    """
    try:
        charges = get_document_charges(str(invoice_id))
    except Exception:
        log.warning("insurance-export: charge record lookup failed for invoice %s",
                    invoice_id)
        return None
    if not charges:
        return None
    ccy = next((c.get("currency") for c in charges if c.get("currency")), "") or invoice_currency
    resolved = resolve_commercial_charges(ccy, charges, source=SOURCE_ISSUED_DOCUMENT)
    resolved["needs_manual_review"] = any(
        (c.get("conflict_state") or "") == CONFLICT_NEEDS_REVIEW for c in charges
    )
    return resolved


def _freight_pickup(resolved: Dict[str, Any]) -> bool:
    """The ONLY pickup evidence in the system: freight resolved customer_courier."""
    for ch in resolved.get("charges") or []:
        if (ch.get("charge_type") or "").strip().lower() == "freight":
            if (ch.get("resolution") or "") == RESOLUTION_CUSTOMER_COURIER:
                return True
    return False


def _shipment_for_draft(draft, db_path: Path, carrier_db_path: Path) -> Optional[dict]:
    batch_id = (getattr(draft, "batch_id", "") or "").strip()
    if not batch_id:
        return None
    client_name = (getattr(draft, "client_name", "") or "").strip() or None
    try:
        single_client = _batch_client_count(db_path, batch_id) <= 1
    except Exception:
        single_client = False
    try:
        return shipment_db.get_shipment_for_draft(
            carrier_db_path,
            batch_id,
            client_name,
            allow_single_client_fallback=single_client,
        )
    except Exception:
        log.warning("insurance-export: shipment lookup failed for batch %s", batch_id)
        return None


# ---------------------------------------------------------------------------
# Recommendation engine — advice only; the operator always decides.
# NEVER country- or nationality-based (operator directive: pickup/shipment
# evidence, not country == Poland).


def _recommend(
    *,
    cif: Optional[Decimal],
    pickup: bool,
    has_draft: bool,
    shipment: Optional[dict],
) -> Tuple[str, Optional[str], str]:
    """Return (recommendation, forced_status_or_None, reason)."""
    if cif is not None and cif == 0:
        return (
            InsuranceRecommendation.EXCLUDE,
            InsuranceStatus.CANCELLED,
            "Zero-value document (cancellation)",
        )
    if pickup:
        return (
            InsuranceRecommendation.EXCLUDE,
            InsuranceStatus.CUSTOMER_TRANSPORT,
            "Freight resolved as customer courier — customer-arranged transport",
        )
    if not has_draft:
        return (
            InsuranceRecommendation.REVIEW,
            InsuranceStatus.NEEDS_REVIEW,
            "No proforma draft linked to this invoice",
        )
    if shipment is not None:
        awb = (shipment.get("tracking_ref") or "").strip()
        if awb:
            return (
                InsuranceRecommendation.INCLUDE,
                None,
                "Shipment on record with AWB",
            )
        if (shipment.get("mode") or "") == "external":
            return (
                InsuranceRecommendation.INCLUDE,
                None,
                "External shipment recorded",
            )
        return (
            InsuranceRecommendation.REVIEW,
            InsuranceStatus.NEEDS_REVIEW,
            "Shipment record has no AWB",
        )
    return (
        InsuranceRecommendation.REVIEW,
        InsuranceStatus.NEEDS_REVIEW,
        "Draft linked but no shipment record found",
    )


# ---------------------------------------------------------------------------
# Correction correlation — wFirma stores no parent link on the list envelope;
# each correction's own XML is fetched and candidate parent tags are parsed.

_PARENT_TAG_PATHS = (
    ".//invoicecorrection/invoice/id",
    ".//invoice_correction/id",
    ".//correction_of_id",
    ".//parent_id",
)


def _correlate_correction(
    invoice_id: str,
    fullnumber: str,
    originals_by_number: Dict[str, str],
) -> Tuple[Optional[str], str, Optional[str]]:
    """Return (parent_invoice_id, method, error).

    method: parent_tag | parent_inferred_by_number_pattern |
            no_parent_reference_found | fetch_failed | xml_parse_failed
    Only ``parent_tag`` may confirm a parent; a per-correction failure
    degrades that row only (never a global error).
    """
    try:
        xml_text = wfirma_client.fetch_invoice_xml(str(invoice_id))
    except Exception as exc:
        return None, "fetch_failed", str(exc)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return None, "xml_parse_failed", str(exc)
    for path in _PARENT_TAG_PATHS:
        node = root.find(path)
        if node is not None and (node.text or "").strip():
            return (node.text or "").strip(), "parent_tag", None
    fn = (fullnumber or "").strip()
    if fn:
        for orig_no, orig_id in originals_by_number.items():
            if orig_no and orig_no != fn and orig_no in fn:
                return orig_id, "parent_inferred_by_number_pattern", None
    return None, "no_parent_reference_found", None


# ---------------------------------------------------------------------------
# Row assembly


def _build_row(
    fact: Dict[str, Any],
    *,
    doc_type: str,
    db_path: Path,
    carrier_db_path: Path,
    fx_cache: Dict[Tuple[str, str], Any],
) -> Dict[str, Any]:
    invoice_id = str(fact.get("id") or "")
    currency = (fact.get("currency") or "").strip().upper() or "PLN"
    invoice_date = (fact.get("date") or "").strip()
    # Inv CIF — document-currency gross, UN-rounded (Blockers 2 + 3).
    #
    # CIF field authority is not asserted here; it is evidenced in
    # reports/inspection/2026-08-15-insurance-cif-authority.md — a read-only
    # reconciliation of four real May-2026 WDT documents (EUR + USD) against
    # the historical statement CIF, 4/4 matched, canonical field <total>.
    # The fact universe's "brutto" key is ledger_aggregator._invoice_gross_raw
    # (brutto → total → total_brutto), which yields that field on WDT
    # documents and <brutto> on domestic ones. Re-run the reconciliation in
    # that artifact before changing this line.
    cif = _dec(fact.get("brutto"))

    # The draft is PRE-ISSUE INTENT. It supplies pickup evidence and shipment
    # linkage only — never the recovered premium (census classes B1 / B2 prove
    # the two diverge in both directions).
    draft = _link_draft(invoice_id, db_path)
    pickup = False
    shipment = None
    if draft is not None:
        pickup = _freight_pickup(_resolve_draft_charges(draft, currency))
        shipment = _shipment_for_draft(draft, db_path, carrier_db_path)

    # Insurance recovered = what the ISSUED document billed, from the charge
    # authority's issued-document record. Single source: there is deliberately
    # NO draft fallback here, so an unconverged document reads as "unknown"
    # rather than silently reporting an intent as a recovery.
    invoiced = _invoiced_charges(invoice_id, currency)
    recovered = _insurance_recovered(invoiced) if invoiced is not None else None

    # Does the commercial charge authority hold an INSURANCE record for this
    # invoice? Distinguishes "the authority says no insurance was billed" (a
    # converged 0.00) from "the authority was never asked" — and a record that
    # captured other charge types but could not attribute insurance is the
    # second case, not the first. See _rows_without_charge_authority.
    charge_authority_on_record = recovered is not None
    charge_conflict = bool(invoiced and invoiced.get("needs_manual_review"))

    fx_rate = None
    fx_provenance = None
    fx_error = None
    if invoice_date:
        fx_rate, fx_provenance, fx_error = _fx_to_inr(currency, invoice_date, fx_cache)
    else:
        fx_error = "missing_invoice_date"

    # Raw Decimal chain — NEVER quantize CIF × 1.10 before the FX multiply
    # (Blocker 2: 723.55 × 1.10 × 92.50 must serialize 73621.21, not the
    # pre-rounded 73621.68). Rounding happens only in _money().
    plus_10 = None
    sum_insured = None
    sum_insured_inr = None
    if cif is not None:
        plus_10 = cif * TEN_PCT
        sum_insured = cif * SUM_INSURED_FACTOR
        if fx_rate is not None:
            sum_insured_inr = sum_insured * fx_rate

    recommendation, forced_status, reason = _recommend(
        cif=cif, pickup=pickup, has_draft=draft is not None, shipment=shipment
    )

    # Status precedence: cancellation / customer transport (forced by
    # evidence) → degraded facts (missing CIF or FX) → review → advisory
    # no-premium → included.
    if forced_status in (
        InsuranceStatus.CANCELLED,
        InsuranceStatus.CUSTOMER_TRANSPORT,
    ):
        status = forced_status
    elif charge_conflict:
        # A stored premium contradicted by the issued document is never
        # published as a fact and never auto-overwritten — operator only.
        status = InsuranceStatus.NEEDS_REVIEW
        recommendation = InsuranceRecommendation.REVIEW
        reason = (
            "Recorded insurance premium contradicts the issued document — "
            "manual review required"
        )
    elif cif is None:
        status = InsuranceStatus.NEEDS_REVIEW
        recommendation = InsuranceRecommendation.REVIEW
        reason = "Missing gross amount on the wFirma fact"
    elif fx_error is not None:
        status = InsuranceStatus.NEEDS_REVIEW
        recommendation = InsuranceRecommendation.REVIEW
        reason = "Insurance FX unavailable — INR columns cannot be resolved"
    elif forced_status is not None:
        status = forced_status
    elif recovered is None or recovered.get("resolution") in (
        RESOLUTION_UNRESOLVED,
        "waived",
        "not_applicable",
        "customer_courier",
    ) or recovered.get("amount") in (None, "0.00"):
        status = InsuranceStatus.NO_INSURANCE_CHARGED
    else:
        status = InsuranceStatus.INCLUDED

    # Corrections (Blocker 4): a correction is NEVER auto-classified as a
    # return. No repository evidence source records WHY a correction was
    # issued, so every correction defaults to reason=unknown → BLOCKED —
    # it can never reduce the insured total automatically. The operator may
    # still explicitly select a genuine return into the declaration.
    correction_reason = None
    insurance_effect = None
    if doc_type == "correction":
        correction_reason, insurance_effect = classify_correction(None, cif)
        if (
            insurance_effect == InsuranceEffect.BLOCKED
            and status != InsuranceStatus.CANCELLED
        ):
            status = InsuranceStatus.NEEDS_REVIEW
            recommendation = InsuranceRecommendation.REVIEW
            reason = (
                "Correction reason unknown — cannot reduce the insured "
                "total automatically; operator review required"
            )

    awb = ""
    shipment_mode = None
    if shipment is not None:
        awb = (shipment.get("tracking_ref") or "").strip()
        shipment_mode = shipment.get("mode")

    return {
        "invoice_id": invoice_id,
        "fullnumber": fact.get("fullnumber") or "",
        "doc_type": doc_type,
        "date": invoice_date,
        "contractor_id": str(fact.get("contractor_id") or ""),
        "contractor_name": fact.get("contractor_name") or "",
        "currency": currency,
        "inv_cif": _money(cif),
        "plus_10_pct": _money(plus_10),
        "sum_insured": _money(sum_insured),
        "fx_rate": str(fx_rate) if fx_rate is not None else None,
        "fx_provenance": fx_provenance,
        "fx_error": fx_error,
        "sum_insured_inr": _money(sum_insured_inr),
        "insurance_recovered": recovered,
        "charge_authority_on_record": charge_authority_on_record,
        "charge_conflict": charge_conflict,
        "recommendation": recommendation,
        "recommendation_label": RECOMMENDATION_LABELS[recommendation],
        "recommendation_reason": reason,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "correction_reason": correction_reason,
        "correction_reason_label": (
            CORRECTION_REASON_LABELS[correction_reason]
            if correction_reason
            else None
        ),
        "insurance_effect": insurance_effect,
        "insurance_effect_label": (
            INSURANCE_EFFECT_LABELS[insurance_effect] if insurance_effect else None
        ),
        "awb": awb,
        "shipment_found": shipment is not None,
        "shipment_mode": shipment_mode,
        "draft_id": getattr(draft, "id", None) if draft is not None else None,
        "batch_id": (getattr(draft, "batch_id", "") or "") if draft is not None else "",
        "adjustments": [],
    }


# ---------------------------------------------------------------------------
# Totals


def _sum_inr(rows: List[Dict[str, Any]]) -> Tuple[Decimal, int]:
    total = Decimal("0")
    missing = 0
    for row in rows:
        val = _dec(row.get("sum_insured_inr"))
        if val is None:
            missing += 1
        else:
            total += val
    return total.quantize(CENT), missing


def _sum_recovered(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    by_ccy: Dict[str, Decimal] = {}
    for row in rows:
        rec = row.get("insurance_recovered") or {}
        amount = _dec(rec.get("amount"))
        ccy = (rec.get("currency") or "").strip().upper()
        if amount is None or not ccy:
            continue
        by_ccy[ccy] = by_ccy.get(ccy, Decimal("0")) + amount
    return {ccy: str(v.quantize(CENT)) for ccy, v in sorted(by_ccy.items())}


def _rows_without_charge_authority(rows: List[Dict[str, Any]]) -> int:
    """Rows the recovered total cannot speak for.

    ``_sum_recovered`` silently skips any row whose premium it cannot read, so
    the total on its own is indistinguishable from a complete one. A row is
    counted here when the commercial charge authority holds no issued-document
    record for it — i.e. the document has never been converged by
    ``app.tools.converge_commercial_charges``. That is NOT evidence of "no
    insurance charged": the fiscal document may well carry an insurance line
    nobody has captured yet.

    A converged row is never counted, including one recorded as 0.00: the
    authority was asked and answered from the issued document, so "billed
    nothing" is a proven fact rather than an unknown.
    """
    return sum(1 for row in rows if not row.get("charge_authority_on_record"))


def _totals_for(
    document_rows: List[Dict[str, Any]],
    adjustment_rows: List[Dict[str, Any]],
    *,
    automatic: bool = True,
) -> Dict[str, Any]:
    """Roll up INR totals.

    Blocker 4: when ``automatic`` is True (the factual-report default), only
    adjustments whose ``insurance_effect`` is in ``_AUTOMATIC_EFFECTS`` may
    move the INR total — an unknown-reason correction (BLOCKED) or a
    commercial discount / claim credit (NO_EFFECT) never reduces it
    automatically. The declaration selection passes ``automatic=False``
    because it is built from the operator's explicit row-by-row selection,
    which already satisfies "never automatically".
    """
    docs_total, docs_missing = _sum_inr(document_rows)
    countable_adjustments = (
        [a for a in adjustment_rows if a.get("insurance_effect") in _AUTOMATIC_EFFECTS]
        if automatic
        else adjustment_rows
    )
    adj_total, adj_missing = _sum_inr(countable_adjustments)
    return {
        "sum_insured_inr_documents": str(docs_total),
        "sum_insured_inr_adjustments": str(adj_total),
        "sum_insured_inr_grand": str((docs_total + adj_total).quantize(CENT)),
        "insurance_recovered": _sum_recovered(document_rows + adjustment_rows),
        "insurance_recovered_rows_without_authority": _rows_without_charge_authority(
            document_rows + adjustment_rows
        ),
        "documents": len(document_rows),
        "adjustments": len(adjustment_rows),
        "rows_without_inr": docs_missing + adj_missing,
    }


# ---------------------------------------------------------------------------
# Public API


def assemble_insurance_export_report(
    date_from: str,
    date_to: str,
    *,
    db_path: Path,
    carrier_db_path: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """Assemble the complete factual report for the period. Read-only."""
    try:
        universe = load_ar_fact_universe(date_from, date_to, force=force)
    except Exception as exc:
        # Includes wfirma_client's credentials-not-configured ValueError —
        # every universe-fetch failure maps to the route's 502, never a 500.
        raise InsuranceExportFetchError(str(exc))

    facts = universe.get("invoice_facts") or []
    normal_facts = [f for f in facts if (f.get("type") or "") != "correction"]
    correction_facts = [f for f in facts if (f.get("type") or "") == "correction"]

    fx_cache: Dict[Tuple[str, str], Any] = {}
    build = lambda fact, doc_type: _build_row(  # noqa: E731
        fact,
        doc_type=doc_type,
        db_path=db_path,
        carrier_db_path=carrier_db_path,
        fx_cache=fx_cache,
    )

    document_rows = [build(f, "invoice") for f in normal_facts]
    rows_by_id = {r["invoice_id"]: r for r in document_rows}
    originals_by_number = {
        (r["fullnumber"] or "").strip(): r["invoice_id"]
        for r in document_rows
        if (r["fullnumber"] or "").strip()
    }

    adjustment_rows: List[Dict[str, Any]] = []
    for fact in correction_facts:
        adj = build(fact, "correction")
        parent_id, method, err = _correlate_correction(
            adj["invoice_id"], adj["fullnumber"], originals_by_number
        )
        confirmed = bool(
            method == "parent_tag" and parent_id and parent_id in rows_by_id
        )
        adj["parent_invoice_id"] = parent_id
        adj["parent_confirmed"] = confirmed
        adj["correlation_method"] = method
        if err:
            adj["correlation_error"] = err
        if not confirmed:
            adj["status"] = InsuranceStatus.NEEDS_REVIEW
            adj["status_label"] = STATUS_LABELS[InsuranceStatus.NEEDS_REVIEW]
            adj["recommendation"] = InsuranceRecommendation.REVIEW
            adj["recommendation_label"] = RECOMMENDATION_LABELS[
                InsuranceRecommendation.REVIEW
            ]
            adj["recommendation_reason"] = (
                "Correction parent could not be confirmed (%s)" % method
            )
        adjustment_rows.append(adj)
        if confirmed:
            rows_by_id[parent_id]["adjustments"].append(adj)

    # Contractor grouping — every invoice under its contractor; corrections
    # without a confirmed in-period parent surface as unattached adjustments
    # under their own contractor.
    groups: Dict[str, Dict[str, Any]] = {}

    def _group_for(row: Dict[str, Any]) -> Dict[str, Any]:
        key = row["contractor_id"] or "name:%s" % row["contractor_name"]
        grp = groups.get(key)
        if grp is None:
            grp = {
                "contractor_id": row["contractor_id"],
                "contractor_name": row["contractor_name"],
                "rows": [],
                "unattached_adjustments": [],
            }
            groups[key] = grp
        return grp

    for row in document_rows:
        _group_for(row)["rows"].append(row)
    for adj in adjustment_rows:
        if not adj["parent_confirmed"]:
            _group_for(adj)["unattached_adjustments"].append(adj)

    contractor_groups = sorted(
        groups.values(), key=lambda g: (g["contractor_name"], g["contractor_id"])
    )
    for grp in contractor_groups:
        grp_adjustments = [
            a for r in grp["rows"] for a in r["adjustments"]
        ] + grp["unattached_adjustments"]
        docs_total, _ = _sum_inr(grp["rows"])
        automatic_grp_adjustments = [
            a for a in grp_adjustments if a.get("insurance_effect") in _AUTOMATIC_EFFECTS
        ]
        adj_total, _ = _sum_inr(automatic_grp_adjustments)
        grp["subtotals"] = {
            "sum_insured_inr_documents": str(docs_total),
            "sum_insured_inr_adjustments": str(adj_total),
            "sum_insured_inr": str((docs_total + adj_total).quantize(CENT)),
            "documents": len(grp["rows"]),
            "adjustments": len(grp_adjustments),
            "insurance_recovered": _sum_recovered(grp["rows"] + grp_adjustments),
            "insurance_recovered_rows_without_authority": (
                _rows_without_charge_authority(grp["rows"] + grp_adjustments)
            ),
        }

    report_totals = _totals_for(document_rows, adjustment_rows)
    needs_review = sum(
        1
        for r in document_rows + adjustment_rows
        if r["status"] == InsuranceStatus.NEEDS_REVIEW
    )
    kpi = {
        "invoices": len(document_rows),
        "adjustments": len(adjustment_rows),
        "gross_insured_inr": report_totals["sum_insured_inr_documents"],
        "net_insured_inr": report_totals["sum_insured_inr_grand"],
        "needs_review": needs_review,
        "insurance_recovered": report_totals["insurance_recovered"],
        "insurance_recovered_rows_without_authority": report_totals[
            "insurance_recovered_rows_without_authority"
        ],
    }

    return {
        "period": {"from": date_from, "to": date_to},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contractors": contractor_groups,
        "report_totals": report_totals,
        "kpi": kpi,
        "query_stats": timing_fields_from_universe(universe),
    }


def resolve_declaration_selection(
    date_from: str,
    date_to: str,
    selected_document_ids: List[str],
    selected_adjustment_ids: List[str],
    *,
    db_path: Path,
    carrier_db_path: Path,
) -> Dict[str, Any]:
    """Re-resolve an ephemeral IDs-only selection against canonical facts.

    The browser sends identifiers and presentation choices, never monetary
    amounts. Everything monetary here comes from a fresh
    :func:`assemble_insurance_export_report` over the same period.
    """
    report = assemble_insurance_export_report(
        date_from, date_to, db_path=db_path, carrier_db_path=carrier_db_path
    )

    document_index: Dict[str, Dict[str, Any]] = {}
    adjustment_index: Dict[str, Dict[str, Any]] = {}
    for grp in report["contractors"]:
        for row in grp["rows"]:
            document_index[row["invoice_id"]] = row
            for adj in row["adjustments"]:
                adjustment_index[adj["invoice_id"]] = adj
        for adj in grp["unattached_adjustments"]:
            adjustment_index[adj["invoice_id"]] = adj

    doc_ids = [str(i) for i in (selected_document_ids or [])]
    adj_ids = [str(i) for i in (selected_adjustment_ids or [])]
    unknown = [i for i in doc_ids if i not in document_index] + [
        i for i in adj_ids if i not in adjustment_index
    ]
    if unknown:
        raise UnknownSelectionError(unknown)

    doc_selected = set(doc_ids)
    adj_selected = set(adj_ids)
    selected_rows: List[Dict[str, Any]] = []
    selected_adjustments: List[Dict[str, Any]] = []
    for grp in report["contractors"]:
        for row in grp["rows"]:
            if row["invoice_id"] in doc_selected:
                selected_rows.append(row)
            for adj in row["adjustments"]:
                if adj["invoice_id"] in adj_selected:
                    selected_adjustments.append(adj)
        for adj in grp["unattached_adjustments"]:
            if adj["invoice_id"] in adj_selected:
                selected_adjustments.append(adj)

    return {
        "period": report["period"],
        "generated_at": report["generated_at"],
        "selected_rows": selected_rows,
        "selected_adjustments": selected_adjustments,
        # automatic=False: this is the operator's explicit selection, not an
        # automatic reduction — Blocker 4 constrains automatic totals only.
        "declaration_totals": _totals_for(
            selected_rows, selected_adjustments, automatic=False
        ),
    }


__all__ = [
    "InsuranceStatus",
    "InsuranceRecommendation",
    "CorrectionReason",
    "InsuranceEffect",
    "STATUS_LABELS",
    "RECOMMENDATION_LABELS",
    "CORRECTION_REASON_LABELS",
    "INSURANCE_EFFECT_LABELS",
    "classify_correction",
    "InsuranceExportError",
    "InsuranceExportFetchError",
    "UnknownSelectionError",
    "assemble_insurance_export_report",
    "resolve_declaration_selection",
]

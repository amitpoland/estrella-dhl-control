"""Insurance Export Statement — read-only assembly of the insurance population.

Two-layer model:
  1. CANONICAL INSURANCE FACTS — assembled here from five existing authorities,
     never persisted, never written back:
       - ledger_fact_universe.load_ar_fact_universe   (wFirma invoice facts)
       - proforma_invoice_link_db.get_draft_by_wfirma_invoice_id
       - commercial_charge_authority.resolve_commercial_charges
       - carrier.persistence.shipment_db.get_shipment_for_draft
       - nbp_rate_service.fetch_rate                  (NBP Table A, PLN hub)
  2. DECLARATION SELECTION — ephemeral, IDs only. The server re-resolves every
     monetary value from the same authorities; the browser never sends amounts.

Insurance premium recovered is read verbatim from the persisted commercial
charge authority. It is NEVER recomputed here (no premium formula of any
kind on the read side) —
the freight/insurance ADR forbids read-side recomputation.

Personal-pickup exclusion is evidence-based only: a freight charge resolved as
``customer_courier``. Never country- or nationality-based.

FX benchmark (declared, provenance-stamped): NBP PLN-hub cross-rate
``PLN_per_CCY / PLN_per_INR``, both legs from NBP Table A for the business day
preceding the invoice date. A missing rate degrades the row (``fx_error`` +
NEEDS REVIEW), never the report.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import wfirma_client
from . import nbp_rate_service
from .nbp_rate_service import NbpRateError
from .commercial_charge_authority import (
    RESOLUTION_CUSTOMER_COURIER,
    RESOLUTION_UNRESOLVED,
    resolve_commercial_charges,
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
FX_QUANT = Decimal("0.000001")
SUM_INSURED_FACTOR = Decimal("1.10")
TEN_PCT = Decimal("0.10")

# ---------------------------------------------------------------------------
# Business vocabulary


class InsuranceStatus:
    INCLUDED = "included"
    EXCLUDED = "excluded"
    PERSONAL_PICKUP = "personal_pickup"
    NO_INSURANCE_CHARGED = "no_insurance_charged"
    NEEDS_REVIEW = "needs_review"
    RETURN = "return"
    CANCELLED = "cancelled"


STATUS_LABELS: Dict[str, str] = {
    InsuranceStatus.INCLUDED: "Included",
    InsuranceStatus.EXCLUDED: "Excluded",
    InsuranceStatus.PERSONAL_PICKUP: "Personal pickup",
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
    if value is None:
        return None
    return str(value.quantize(CENT))


# ---------------------------------------------------------------------------
# FX — NBP PLN-hub cross-rate, deduped per (currency, date)


def _fetch_rate_cached(
    currency: str, date: str, cache: Dict[Tuple[str, str], Any]
) -> Dict[str, Any]:
    key = (currency, date)
    hit = cache.get(key)
    if hit is not None:
        kind, payload = hit
        if kind == "err":
            raise payload
        return payload
    try:
        info = nbp_rate_service.fetch_rate(currency, date)
    except NbpRateError as exc:
        cache[key] = ("err", exc)
        raise
    cache[key] = ("ok", info)
    return info


def _fx_to_inr(
    currency: Optional[str],
    invoice_date: str,
    cache: Dict[Tuple[str, str], Any],
) -> Tuple[Optional[Decimal], Optional[Dict[str, Any]], Optional[str]]:
    """Return (fx_rate, fx_provenance, fx_error) — errors degrade, never raise."""
    ccy = (currency or "").strip().upper() or "PLN"
    try:
        info_ccy = _fetch_rate_cached(ccy, invoice_date, cache)
        info_inr = _fetch_rate_cached("INR", invoice_date, cache)
    except NbpRateError as exc:
        return None, None, "%s: %s" % (exc.kind, str(exc))
    except Exception as exc:  # engine subprocess trouble — degrade the row
        return None, None, "fx_unavailable: %s" % exc
    pln_per_ccy = _dec(info_ccy.get("rate"))
    pln_per_inr = _dec(info_inr.get("rate"))
    if not pln_per_ccy or not pln_per_inr or pln_per_inr == 0:
        return None, None, "missing_rate: NBP returned no usable mid"
    fx = (pln_per_ccy / pln_per_inr).quantize(FX_QUANT)
    provenance = {
        "nbp_table_ccy": info_ccy.get("table_number"),
        "nbp_table_inr": info_inr.get("table_number"),
        "nbp_date_used": info_inr.get("table_date") or info_ccy.get("table_date"),
    }
    return fx, provenance, None


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
            InsuranceStatus.PERSONAL_PICKUP,
            "Freight resolved as customer courier — customer arranged pickup",
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
    cif = _dec(fact.get("brutto"))
    if cif is not None:
        cif = cif.quantize(CENT)

    draft = _link_draft(invoice_id, db_path)
    resolved = None
    recovered = None
    pickup = False
    shipment = None
    if draft is not None:
        resolved = _resolve_draft_charges(draft, currency)
        recovered = _insurance_recovered(resolved)
        pickup = _freight_pickup(resolved)
        shipment = _shipment_for_draft(draft, db_path, carrier_db_path)

    fx_rate = None
    fx_provenance = None
    fx_error = None
    if invoice_date:
        fx_rate, fx_provenance, fx_error = _fx_to_inr(currency, invoice_date, fx_cache)
    else:
        fx_error = "missing_invoice_date"

    plus_10 = None
    sum_insured = None
    sum_insured_inr = None
    if cif is not None:
        plus_10 = (cif * TEN_PCT).quantize(CENT)
        sum_insured = (cif * SUM_INSURED_FACTOR).quantize(CENT)
        if fx_rate is not None:
            sum_insured_inr = (sum_insured * fx_rate).quantize(CENT)

    recommendation, forced_status, reason = _recommend(
        cif=cif, pickup=pickup, has_draft=draft is not None, shipment=shipment
    )

    # Status precedence: cancellation / pickup (forced by evidence) →
    # degraded facts (missing CIF or FX) → review → advisory no-premium → included.
    if forced_status in (InsuranceStatus.CANCELLED, InsuranceStatus.PERSONAL_PICKUP):
        status = forced_status
    elif cif is None:
        status = InsuranceStatus.NEEDS_REVIEW
        recommendation = InsuranceRecommendation.REVIEW
        reason = "Missing gross amount on the wFirma fact"
    elif fx_error is not None:
        status = InsuranceStatus.NEEDS_REVIEW
        recommendation = InsuranceRecommendation.REVIEW
        reason = "NBP FX unavailable — INR columns cannot be resolved"
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

    if doc_type == "correction" and status not in (
        InsuranceStatus.NEEDS_REVIEW,
        InsuranceStatus.CANCELLED,
    ):
        status = InsuranceStatus.RETURN

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
        "recommendation": recommendation,
        "recommendation_label": RECOMMENDATION_LABELS[recommendation],
        "recommendation_reason": reason,
        "status": status,
        "status_label": STATUS_LABELS[status],
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


def _totals_for(
    document_rows: List[Dict[str, Any]], adjustment_rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    docs_total, docs_missing = _sum_inr(document_rows)
    adj_total, adj_missing = _sum_inr(adjustment_rows)
    return {
        "sum_insured_inr_documents": str(docs_total),
        "sum_insured_inr_adjustments": str(adj_total),
        "sum_insured_inr_grand": str((docs_total + adj_total).quantize(CENT)),
        "insurance_recovered": _sum_recovered(document_rows + adjustment_rows),
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
        adj_total, _ = _sum_inr(grp_adjustments)
        grp["subtotals"] = {
            "sum_insured_inr_documents": str(docs_total),
            "sum_insured_inr_adjustments": str(adj_total),
            "sum_insured_inr": str((docs_total + adj_total).quantize(CENT)),
            "documents": len(grp["rows"]),
            "adjustments": len(grp_adjustments),
            "insurance_recovered": _sum_recovered(grp["rows"] + grp_adjustments),
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
        "declaration_totals": _totals_for(selected_rows, selected_adjustments),
    }


__all__ = [
    "InsuranceStatus",
    "InsuranceRecommendation",
    "STATUS_LABELS",
    "RECOMMENDATION_LABELS",
    "InsuranceExportError",
    "InsuranceExportFetchError",
    "UnknownSelectionError",
    "assemble_insurance_export_report",
    "resolve_declaration_selection",
]

"""
customer_intelligence.py — Customer Intelligence service layer.

ARCHITECTURE
  Phase 0 (prototype): read-only report generator.
  Phase 1 (current): adds VIES validation action + KUKE expiry guard.

  * External lookups are behind injectable connector protocols.
  * Every finding carries: field, value, source, confidence, status.
  * ProposedUpdate carries: current, suggested, source, confidence, action_type.
  * The read-only report (run_intelligence_check) has no side effects.
  * The validation action (validate_customer_vat) writes ONLY vat_eu_valid
    and vat_eu_validated_at via update_vat_eu_result() — no other fields.

GOVERNANCE
  * This module MUST NOT call upsert_customer(), upsert_identity_only(), or any
    write function.  It only imports CustomerMaster (read) and date utilities.
  * Unit tests must use mock connectors — no live network calls.
  * Suggested updates are advisory only.  Nothing in this module writes them.
"""
from __future__ import annotations

import urllib.request
import urllib.error
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)

# ─── Finding status vocabulary ─────────────────────────────────────────────────
VERIFIED            = "verified"
INTERNALLY_STORED   = "internally_stored"
OPERATOR_ENTERED    = "operator_entered"
MISSING             = "missing"
UNAVAILABLE         = "unavailable"
REQUIRES_COMMERCIAL = "requires_commercial_provider"

# ─── Confidence vocabulary ─────────────────────────────────────────────────────
HIGH   = "high"
MEDIUM = "medium"
LOW    = "low"
NONE_C = "none"

# ─── Risk levels ──────────────────────────────────────────────────────────────
CRITICAL = "critical"
WARNING  = "warning"
INFO     = "info"
CLEAR    = "clear"

# ─── Action types for proposed updates ───────────────────────────────────────
CAN_AUTOMATE       = "can_automate"
MANUAL_REQUIRED    = "manual_required"
COMMERCIAL_REQUIRED = "commercial_required"

# Days before KUKE expiry that triggers a WARNING (vs CLEAR)
KUKE_WARN_DAYS = 30


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    field: str
    value: Any
    source: str
    confidence: str
    status: str
    note: Optional[str] = None


@dataclass(frozen=True)
class RiskFinding:
    code: str
    level: str
    description: str
    recommended_action: str


@dataclass(frozen=True)
class ProposedUpdate:
    field: str
    current_value: Any
    suggested_value: Any
    source: str
    confidence: str
    action_type: str
    note: Optional[str] = None


# ─── Connector types ──────────────────────────────────────────────────────────

@dataclass
class ViesResult:
    status: str                      # "valid" | "invalid" | "unavailable"
    name: Optional[str] = None
    address: Optional[str] = None
    validated_at: Optional[str] = None
    country_code: Optional[str] = None
    vat_number: Optional[str] = None


@dataclass
class EoriResult:
    status: str                      # "valid" | "invalid" | "not_configured" | "unavailable"
    trader_name: Optional[str] = None
    country: Optional[str] = None


@runtime_checkable
class ViesConnector(Protocol):
    def check(self, vat_number: str) -> ViesResult: ...


@runtime_checkable
class EoriConnector(Protocol):
    def check(self, eori_number: str) -> EoriResult: ...


# ─── Connector implementations ────────────────────────────────────────────────

class PlaceholderViesConnector:
    """No live call.  Returns unavailable.  Use for tests and dry-run mode."""
    def check(self, vat_number: str) -> ViesResult:
        return ViesResult(status=UNAVAILABLE, vat_number=vat_number)


class HttpViesConnector:
    """
    Live call to EC VIES REST API.
    Endpoint: https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{number}
    Rate limit: ~10 req/min.  Use sparingly — this is read-only intelligence.
    """
    _BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}"
    _TIMEOUT = 8

    def check(self, vat_number: str) -> ViesResult:
        vat = vat_number.replace(" ", "").strip()
        if len(vat) < 3:
            return ViesResult(status="invalid", vat_number=vat)
        cc  = vat[:2].upper()
        num = vat[2:]
        url = self._BASE.format(cc=cc, num=num)
        try:
            with urllib.request.urlopen(url, timeout=self._TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            if data.get("isValid"):
                return ViesResult(
                    status="valid",
                    name=data.get("traderName"),
                    address=data.get("traderAddress"),
                    validated_at=datetime.utcnow().date().isoformat(),
                    country_code=cc,
                    vat_number=vat,
                )
            return ViesResult(
                status="invalid",
                country_code=cc,
                vat_number=vat,
                validated_at=datetime.utcnow().date().isoformat(),
            )
        except Exception as exc:
            log.warning("VIES check failed for %s: %s", vat_number, exc)
            return ViesResult(status=UNAVAILABLE, vat_number=vat_number)


class MockViesConnector:
    """Configurable mock for unit tests.  Pass a ViesResult to return."""
    def __init__(self, result: ViesResult):
        self._result = result

    def check(self, vat_number: str) -> ViesResult:
        return self._result


class PlaceholderEoriConnector:
    def check(self, eori_number: str) -> EoriResult:
        return EoriResult(status="not_configured")


# ─── Report structure ─────────────────────────────────────────────────────────

@dataclass
class CustomerIntelligenceReport:
    contractor_id: str
    customer_name: str
    generated_at: str
    check_date: str

    # Section 1: Customer Master baseline
    baseline: List[Finding] = field(default_factory=list)

    # Section 2: VIES VAT validation
    vies: List[Finding] = field(default_factory=list)

    # Section 3: EORI
    eori: List[Finding] = field(default_factory=list)

    # Section 4: KUKE credit insurance
    kuke: List[Finding] = field(default_factory=list)

    # Section 5: KYC / AML
    kyc_aml: List[Finding] = field(default_factory=list)

    # Section 6: Missing registry fields
    registry: List[Finding] = field(default_factory=list)

    # Section 7: Proposed Customer Master updates (fields that exist in schema)
    proposed_cm: List[ProposedUpdate] = field(default_factory=list)

    # Section 8: Proposed Customer Intelligence fields (not in CM schema)
    proposed_intel: List[ProposedUpdate] = field(default_factory=list)

    # Section 9: Risk summary
    risks: List[RiskFinding] = field(default_factory=list)

    # Raw connector output (for debugging / transparency)
    vies_raw: Optional[ViesResult] = None
    eori_raw: Optional[EoriResult] = None


# ─── Section checkers ─────────────────────────────────────────────────────────

def _check_baseline(cm, r: CustomerIntelligenceReport) -> None:
    def f(field_, value, source, conf, status, note=None):
        r.baseline.append(Finding(field_, value, source, conf, status, note))

    f("bill_to_contractor_id", cm.bill_to_contractor_id, "customer_master.sqlite", HIGH, INTERNALLY_STORED)
    f("bill_to_name",          cm.bill_to_name,          "wFirma sync + operator", HIGH, INTERNALLY_STORED)
    f("country",               cm.country,               "wFirma sync",            HIGH, INTERNALLY_STORED)
    f("nip",                   cm.nip,                   "wFirma sync",            HIGH, INTERNALLY_STORED)
    f("vat_eu_number",         cm.vat_eu_number or "—",  "operator / wFirma sync", HIGH if cm.vat_eu_number else NONE_C,
      INTERNALLY_STORED if cm.vat_eu_number else MISSING)
    f("bill_to_street",        cm.bill_to_street or "—", "wFirma sync",            HIGH if cm.bill_to_street else NONE_C,
      INTERNALLY_STORED if cm.bill_to_street else MISSING)
    f("bill_to_city",          cm.bill_to_city or "—",   "wFirma sync",            HIGH if cm.bill_to_city else NONE_C,
      INTERNALLY_STORED if cm.bill_to_city else MISSING)
    f("bill_to_postal_code",   cm.bill_to_postal_code or "—", "wFirma sync",       HIGH if cm.bill_to_postal_code else NONE_C,
      INTERNALLY_STORED if cm.bill_to_postal_code else MISSING)
    f("bill_to_email",         cm.bill_to_email or "—",  "wFirma sync",            HIGH if cm.bill_to_email else NONE_C,
      INTERNALLY_STORED if cm.bill_to_email else MISSING)
    f("bill_to_phone",         cm.bill_to_phone or "—",  "wFirma sync",            MEDIUM if cm.bill_to_phone else NONE_C,
      INTERNALLY_STORED if cm.bill_to_phone else MISSING)
    f("client_type",           cm.client_type or "—",    "operator",               HIGH if cm.client_type else NONE_C,
      OPERATOR_ENTERED if cm.client_type else MISSING)
    f("industry",              cm.industry or "—",        "operator",               HIGH if cm.industry else NONE_C,
      OPERATOR_ENTERED if cm.industry else MISSING)
    f("risk_status",           cm.risk_status or "—",    "operator",               MEDIUM if cm.risk_status else NONE_C,
      OPERATOR_ENTERED if cm.risk_status else MISSING)
    f("default_currency",      cm.default_currency or "—", "operator",             HIGH if cm.default_currency else NONE_C,
      OPERATOR_ENTERED if cm.default_currency else MISSING)
    f("payment_terms_days",    cm.payment_terms_days,    "operator",               HIGH if cm.payment_terms_days else NONE_C,
      OPERATOR_ENTERED if cm.payment_terms_days else MISSING)
    f("credit_limit",
      f"{cm.credit_limit} {cm.credit_currency}" if cm.credit_limit else "—",
      "operator", HIGH if cm.credit_limit else NONE_C,
      OPERATOR_ENTERED if cm.credit_limit else MISSING)


def _check_vies(cm, r: CustomerIntelligenceReport, vies_conn: ViesConnector, today: date) -> None:
    vat = cm.vat_eu_number

    if not vat:
        r.vies.append(Finding(
            "vat_eu_number", "—",
            "customer_master", NONE_C, MISSING,
            "No EU VAT number recorded. WDT treatment cannot be validated.",
        ))
        r.risks.append(RiskFinding(
            "VIES_NO_NUMBER", WARNING,
            "No EU VAT number stored. WDT 0% treatment cannot be substantiated.",
            "Enter the EU VAT number in Customer Master and validate via VIES.",
        ))
        return

    # Run the connector
    result = vies_conn.check(vat)
    r.vies_raw = result

    if result.status == "valid":
        r.vies.append(Finding("vat_eu_number", vat, "EC VIES API", HIGH, VERIFIED,
                              f"VIES confirmed valid. Name: {result.name!r}. "
                              f"Address: {result.address!r}."))
        r.vies.append(Finding("vat_eu_valid", True, "EC VIES API", HIGH, VERIFIED,
                              "Customer is a registered EU VAT payer. WDT 0% is substantiated."))
        r.vies.append(Finding("vat_eu_validated_at", result.validated_at or today.isoformat(),
                              "EC VIES API", HIGH, VERIFIED))
        # Propose update to Customer Master (advisory only — nothing is written here)
        r.proposed_cm.append(ProposedUpdate(
            field="vat_eu_valid",
            current_value=cm.vat_eu_valid,
            suggested_value=True,
            source="EC VIES API",
            confidence=HIGH,
            action_type=CAN_AUTOMATE,
            note="Set vat_eu_valid=True to silence D3 VIES advisory on future proformas.",
        ))
        r.proposed_cm.append(ProposedUpdate(
            field="vat_eu_validated_at",
            current_value=cm.vat_eu_validated_at,
            suggested_value=result.validated_at or today.isoformat(),
            source="EC VIES API",
            confidence=HIGH,
            action_type=CAN_AUTOMATE,
        ))

    elif result.status == "invalid":
        r.vies.append(Finding("vat_eu_number", vat, "EC VIES API", HIGH, VERIFIED,
                              "VIES returned INVALID. VAT number not confirmed in EU registry."))
        r.vies.append(Finding("vat_eu_valid", False, "EC VIES API", HIGH, VERIFIED,
                              "WDT 0% treatment is NOT substantiated. Risk of VAT liability."))
        r.risks.append(RiskFinding(
            "VIES_INVALID", CRITICAL,
            f"EU VAT {vat!r} returned INVALID by VIES. "
            "Applying WDT 0% VAT rate to this customer is legally unsubstantiated.",
            "Suspend WDT treatment. Contact customer to obtain valid EU VAT number. "
            "Set vat_eu_valid=False in Customer Master immediately.",
        ))
        r.proposed_cm.append(ProposedUpdate(
            field="vat_eu_valid",
            current_value=cm.vat_eu_valid,
            suggested_value=False,
            source="EC VIES API",
            confidence=HIGH,
            action_type=MANUAL_REQUIRED,
            note="Manual operator confirmation required before marking False — has tax consequences.",
        ))

    else:  # unavailable
        r.vies.append(Finding("vat_eu_number", vat, "EC VIES API", NONE_C, UNAVAILABLE,
                              "VIES check attempted but service was unavailable or timed out."))
        r.vies.append(Finding("vat_eu_valid", cm.vat_eu_valid, "customer_master (unchanged)",
                              LOW, OPERATOR_ENTERED,
                              "VIES unavailable — existing Customer Master value retained."))
        r.risks.append(RiskFinding(
            "VIES_UNAVAILABLE", INFO,
            f"VIES check for {vat!r} could not be completed (service unavailable). "
            "Current Customer Master vat_eu_valid value is advisory only.",
            "Retry VIES check when EC API is available. No change to Customer Master.",
        ))

    # Always report the current stored state for transparency
    if cm.vat_eu_valid is None:
        r.vies.append(Finding("vat_eu_valid (stored)", None, "customer_master",
                              NONE_C, OPERATOR_ENTERED,
                              "D3 VIES advisory fires on every proforma until this is set."))


def _check_eori(cm, r: CustomerIntelligenceReport, eori_conn: EoriConnector) -> None:
    if cm.eori:
        eori_result = eori_conn.check(cm.eori)
        r.eori_raw = eori_result
        if eori_result.status == "valid":
            r.eori.append(Finding("eori", cm.eori, "EU EORI database + operator",
                                  HIGH, VERIFIED))
        elif eori_result.status == "not_configured":
            r.eori.append(Finding("eori", cm.eori, "operator (unvalidated)",
                                  MEDIUM, OPERATOR_ENTERED,
                                  "EORI connector not configured — value not externally verified."))
        else:
            r.eori.append(Finding("eori", cm.eori, "EU EORI database",
                                  HIGH, VERIFIED, f"EORI check returned: {eori_result.status}"))
    else:
        r.eori.append(Finding(
            "eori", None, "customer_master", NONE_C, MISSING,
            "EORI number absent. Required for customs declarations as EU importer.",
        ))
        r.risks.append(RiskFinding(
            "EORI_MISSING", WARNING,
            "No EORI number recorded for this customer. "
            "EORI is required to identify the customer as importer of record in DHL customs declarations.",
            "Request EORI number from customer and enter in Customer Master.eori field. "
            "Validate against EU EORI database (ec.europa.eu) — free public API.",
        ))
        r.proposed_intel.append(ProposedUpdate(
            field="eori (Customer Intelligence)",
            current_value=None,
            suggested_value="Request from customer",
            source="Customer self-declaration + EU EORI validation API",
            confidence=NONE_C,
            action_type=MANUAL_REQUIRED,
            note="Customer must provide their EORI. EU EORI API can then validate it.",
        ))


def _check_kuke(cm, r: CustomerIntelligenceReport, today: date) -> None:
    approved  = cm.kuke_approved
    expiry_s  = cm.kuke_expiry_date
    limit     = cm.kuke_limit
    currency  = cm.kuke_currency
    pol_no    = cm.kuke_policy_number

    if approved is None:
        r.kuke.append(Finding("kuke_approved", None, "customer_master",
                              NONE_C, MISSING, "No KUKE approval status recorded."))
        return

    if not approved:
        r.kuke.append(Finding("kuke_approved", False, "operator",
                              HIGH, OPERATOR_ENTERED, "KUKE credit insurance not approved."))
        return

    # approved = True — check expiry
    r.kuke.append(Finding("kuke_approved", True, "operator",
                          HIGH, OPERATOR_ENTERED,
                          f"KUKE approved. Limit: {limit} {currency}."))
    r.kuke.append(Finding("kuke_limit",
                          f"{limit} {currency}" if limit else "—",
                          "operator", HIGH if limit else NONE_C,
                          OPERATOR_ENTERED if limit else MISSING))
    r.kuke.append(Finding("kuke_policy_number",
                          pol_no or "—", "operator",
                          HIGH if pol_no else NONE_C,
                          OPERATOR_ENTERED if pol_no else MISSING,
                          None if pol_no else "Policy number not recorded — required for audit trail."))
    r.kuke.append(Finding("kuke_self_retention_pct",
                          f"{cm.kuke_self_retention_pct}%" if cm.kuke_self_retention_pct else "—",
                          "operator", HIGH if cm.kuke_self_retention_pct else NONE_C,
                          OPERATOR_ENTERED if cm.kuke_self_retention_pct else MISSING))

    if not expiry_s:
        r.kuke.append(Finding("kuke_expiry_date", None, "customer_master",
                              NONE_C, MISSING, "No KUKE expiry date — cannot assess currency."))
        r.risks.append(RiskFinding(
            "KUKE_NO_EXPIRY", WARNING,
            "kuke_approved=True but kuke_expiry_date is missing. "
            "Cannot determine if coverage is current.",
            "Enter KUKE policy expiry date from the insurance certificate.",
        ))
        return

    try:
        expiry = date.fromisoformat(expiry_s)
    except ValueError:
        r.kuke.append(Finding("kuke_expiry_date", expiry_s, "operator",
                              LOW, OPERATOR_ENTERED, "Cannot parse date — check format."))
        return

    days_overdue = (today - expiry).days
    days_remaining = (expiry - today).days

    if expiry < today:
        r.kuke.append(Finding(
            "kuke_expiry_date", expiry_s, "operator", HIGH, OPERATOR_ENTERED,
            f"EXPIRED {days_overdue} day(s) ago (today: {today}). "
            "kuke_approved=True is stale — coverage has lapsed.",
        ))
        r.risks.append(RiskFinding(
            "KUKE_EXPIRED", CRITICAL,
            f"KUKE credit insurance expired {expiry_s} ({days_overdue} day(s) ago). "
            f"kuke_approved=True is a false positive. "
            f"Any shipment shipped since {expiry_s} is uninsured under KUKE.",
            "Immediately: (a) set kuke_approved=False OR update kuke_expiry_date after renewal. "
            "(b) Escalate to finance for KUKE renewal. "
            "(c) Review all shipments since expiry for uninsured exposure.",
        ))
        r.proposed_cm.append(ProposedUpdate(
            field="kuke_approved",
            current_value=True,
            suggested_value=False,
            source="Expiry date comparison",
            confidence=HIGH,
            action_type=MANUAL_REQUIRED,
            note=f"Policy expired {expiry_s}. Set False until renewal is confirmed.",
        ))
    elif days_remaining <= KUKE_WARN_DAYS:
        r.kuke.append(Finding(
            "kuke_expiry_date", expiry_s, "operator", HIGH, OPERATOR_ENTERED,
            f"Expiring in {days_remaining} day(s). Renewal action required.",
        ))
        r.risks.append(RiskFinding(
            "KUKE_EXPIRING_SOON", WARNING,
            f"KUKE credit insurance expires {expiry_s} ({days_remaining} day(s) remaining).",
            "Initiate KUKE renewal process now.",
        ))
    else:
        r.kuke.append(Finding(
            "kuke_expiry_date", expiry_s, "operator", HIGH, OPERATOR_ENTERED,
            f"Valid — {days_remaining} day(s) remaining.",
        ))


def _check_kyc_aml(cm, r: CustomerIntelligenceReport, today: date) -> None:
    def f(fld, val, src, conf, status, note=None):
        r.kyc_aml.append(Finding(fld, val, src, conf, status, note))

    kyc = cm.kyc_status
    f("kyc_status", kyc or "—", "operator", HIGH if kyc else NONE_C,
      OPERATOR_ENTERED if kyc else MISSING)

    if cm.kyc_expiry:
        try:
            exp = date.fromisoformat(cm.kyc_expiry)
            days_rem = (exp - today).days
            if exp < today:
                note = f"KYC EXPIRED {(today - exp).days} day(s) ago."
                r.risks.append(RiskFinding(
                    "KYC_EXPIRED", CRITICAL,
                    f"KYC approval expired {cm.kyc_expiry}.",
                    "Perform KYC renewal immediately.",
                ))
            elif days_rem <= 30:
                note = f"KYC expires in {days_rem} day(s)."
                r.risks.append(RiskFinding(
                    "KYC_EXPIRING_SOON", WARNING,
                    f"KYC approval expires {cm.kyc_expiry} ({days_rem} day(s)).",
                    "Initiate KYC renewal.",
                ))
            else:
                note = f"Valid — {days_rem} day(s) remaining."
            f("kyc_expiry", cm.kyc_expiry, "operator", HIGH, OPERATOR_ENTERED, note)
        except ValueError:
            f("kyc_expiry", cm.kyc_expiry, "operator", LOW, OPERATOR_ENTERED, "Cannot parse date.")
    else:
        f("kyc_expiry", None, "customer_master", NONE_C, MISSING)

    f("kyc_approved_on", cm.kyc_approved_on or "—", "operator",
      HIGH if cm.kyc_approved_on else NONE_C,
      OPERATOR_ENTERED if cm.kyc_approved_on else MISSING)

    aml = cm.aml_risk_rating
    f("aml_risk_rating", aml or "—", "operator (manual assessment)", MEDIUM if aml else NONE_C,
      OPERATOR_ENTERED if aml else MISSING,
      "Operator-assessed. No automated AML screening behind this field.")

    pep = cm.pep_check_result
    f("pep_check_result", pep or "—", "operator (manual check)", MEDIUM if pep else NONE_C,
      OPERATOR_ENTERED if pep else MISSING,
      "Operator-assessed. No connection to ComplyAdvantage / World-Check.")

    bo = cm.beneficial_owner
    f("beneficial_owner", bo or "—", "operator", HIGH if bo else NONE_C,
      OPERATOR_ENTERED if bo else MISSING,
      None if bo else "Required for AML beneficial ownership documentation.")
    f("owner_id_type", cm.owner_id_type or "—", "operator",
      HIGH if cm.owner_id_type else NONE_C,
      OPERATOR_ENTERED if cm.owner_id_type else MISSING)
    f("owner_id_number", cm.owner_id_number or "—", "operator",
      HIGH if cm.owner_id_number else NONE_C,
      OPERATOR_ENTERED if cm.owner_id_number else MISSING,
      None if cm.owner_id_number else "ID type recorded but number missing — KYC record is incomplete.")

    if not bo or not cm.owner_id_number:
        r.risks.append(RiskFinding(
            "KYC_INCOMPLETE_BO", WARNING,
            "Beneficial owner name and/or ID number not recorded. "
            "KYC record is structurally incomplete.",
            "Obtain and record beneficial owner name and passport/ID number.",
        ))

    if not cm.compliance_notes:
        r.kyc_aml.append(Finding(
            "compliance_notes", None, "customer_master", NONE_C, MISSING,
            "No compliance notes — basis for AML/PEP decisions is undocumented.",
        ))


def _check_registry(cm, r: CustomerIntelligenceReport) -> None:
    def f(fld, val, src, conf, status, note=None):
        r.registry.append(Finding(fld, val, src, conf, status, note))

    # Fields that DO exist in the schema but are missing for this customer
    f("regon", cm.regon or "—", "wFirma sync", NONE_C if not cm.regon else HIGH,
      INTERNALLY_STORED if cm.regon else MISSING,
      "N/A for FR customer (REGON is PL-specific)." if cm.country == "FR" else None)
    f("short_code", cm.short_code or "—", "operator", NONE_C,
      OPERATOR_ENTERED if cm.short_code else MISSING)

    # Fields that do NOT exist in schema — belong in Customer Intelligence layer
    r.registry.append(Finding(
        "registration_number (SIREN)", "—",
        "Schema does not have this field",
        NONE_C, MISSING,
        "French SIREN/SIRET not stored. Free API: api.insee.fr (Sirene). "
        "Requires schema addition or Customer Intelligence layer.",
    ))
    r.registry.append(Finding(
        "legal_form", "—",
        "Schema does not have this field",
        NONE_C, MISSING,
        "SAS / SA / SARL etc. — affects liability and AML profile. Requires schema addition.",
    ))
    r.registry.append(Finding(
        "directors / shareholders", "—",
        "Not in schema", NONE_C, MISSING,
        "Ownership structure. Requires Customer Intelligence layer + commercial provider "
        "or public registry lookup (Infogreffe for FR).",
    ))
    r.registry.append(Finding(
        "website", "—",
        "Not in schema", NONE_C, MISSING,
        "No website field. Useful for identity cross-check.",
    ))
    r.registry.append(Finding(
        "sanctions_screening", "—",
        "No integration", NONE_C, MISSING,
        "EU/OFAC/UN/UK sanctions lists not checked. "
        "AML programme requires at minimum EU Consolidated List check (free public API).",
    ))


def _build_proposals(cm, r: CustomerIntelligenceReport) -> None:
    # VIES proposals are added by _check_vies when relevant.
    # KUKE proposal is added by _check_kuke when expired.

    # Things that CAN be automated
    r.proposed_intel.append(ProposedUpdate(
        field="vies_validated_at",
        current_value=cm.vat_eu_validated_at,
        suggested_value="<date of VIES API call>",
        source="EC VIES API (free)",
        confidence=HIGH,
        action_type=CAN_AUTOMATE,
        note="Set automatically when HttpViesConnector confirms valid/invalid.",
    ))
    r.proposed_intel.append(ProposedUpdate(
        field="eori_validated (Customer Intelligence layer)",
        current_value=None,
        suggested_value="Validate via EU EORI API after customer provides number",
        source="EU EORI database — ec.europa.eu (free)",
        confidence=NONE_C,
        action_type=CAN_AUTOMATE,
        note="Once EORI is entered in CM, it can be validated automatically.",
    ))
    r.proposed_intel.append(ProposedUpdate(
        field="registration_number (SIREN) — Customer Intelligence layer",
        current_value=None,
        suggested_value="Retrieve from api.insee.fr/entreprises/sirene using company name + postcode",
        source="INSEE Sirene (France — free government API)",
        confidence=MEDIUM,
        action_type=CAN_AUTOMATE,
        note="No schema field exists today. Requires new Customer Intelligence table.",
    ))

    # Things that require commercial providers
    r.proposed_intel.append(ProposedUpdate(
        field="financial_data (revenue, employees, filings)",
        current_value=None,
        suggested_value="Revenue, employees, latest filing — not publicly available for private FR companies",
        source="Creditsafe / Dun & Bradstreet / Kompass (commercial)",
        confidence=NONE_C,
        action_type=COMMERCIAL_REQUIRED,
    ))
    r.proposed_intel.append(ProposedUpdate(
        field="sanctions_screening (EU / OFAC / UN / UK)",
        current_value="Not screened",
        suggested_value="EU Consolidated List (free) can be automated; PEP + adverse media requires commercial",
        source="EU sanctions: data.europa.eu (free). PEP: ComplyAdvantage / World-Check",
        confidence=NONE_C,
        action_type=COMMERCIAL_REQUIRED,
        note="EU list free; PEP/adverse-media requires commercial contract.",
    ))

    # Fields that MUST remain manual
    r.proposed_intel.append(ProposedUpdate(
        field="kyc_status / aml_risk_rating / pep_check_result — MANUAL ONLY",
        current_value=f"kyc={cm.kyc_status}, aml={cm.aml_risk_rating}, pep={cm.pep_check_result}",
        suggested_value="Retain as operator decision",
        source="Operator judgment — cannot be automated",
        confidence=HIGH,
        action_type=MANUAL_REQUIRED,
        note="Final KYC/AML/PEP determination is always a human decision even when automated "
             "inputs (VIES, sanctions lists) inform it.",
    ))


def _build_risk_summary(cm, r: CustomerIntelligenceReport, today: date) -> None:
    # Risks are accumulated by the section checkers above.
    # Add any cross-cutting risks here.

    # If no risk findings were added by section checkers but vat_eu_valid is still null, add one
    vies_risk_codes = {rf.code for rf in r.risks}
    if cm.vat_eu_number and cm.vat_eu_valid is None and "VIES_UNAVAILABLE" not in vies_risk_codes \
            and "VIES_INVALID" not in vies_risk_codes:
        r.risks.append(RiskFinding(
            "VIES_NOT_VALIDATED", WARNING,
            f"EU VAT {cm.vat_eu_number!r} is stored but never validated via VIES. "
            "D3 VIES advisory fires on every proforma.",
            "Validate via VIES and set vat_eu_valid=True/False in Customer Master.",
        ))

    # Overall trade readiness
    critical_count = sum(1 for rf in r.risks if rf.level == CRITICAL)
    warning_count  = sum(1 for rf in r.risks if rf.level == WARNING)

    if critical_count > 0:
        r.risks.append(RiskFinding(
            "OVERALL_RISK", CRITICAL,
            f"{critical_count} CRITICAL finding(s) require immediate action before next shipment.",
            "Resolve all CRITICAL findings before processing further orders for this customer.",
        ))
    elif warning_count > 0:
        r.risks.append(RiskFinding(
            "OVERALL_RISK", WARNING,
            f"No CRITICAL findings. {warning_count} WARNING(s) require scheduled attention.",
            "Schedule resolution of WARNING findings within 14 days.",
        ))
    else:
        r.risks.append(RiskFinding(
            "OVERALL_RISK", CLEAR,
            "No CRITICAL or WARNING findings from available checks.",
            "No immediate action required.",
        ))


# ─── Public entry point ───────────────────────────────────────────────────────

def run_intelligence_check(
    cm,
    *,
    vies_connector: ViesConnector,
    eori_connector: Optional[EoriConnector] = None,
    check_date: Optional[date] = None,
) -> CustomerIntelligenceReport:
    """
    Produce a CustomerIntelligenceReport for one CustomerMaster record.

    SAFETY CONTRACT
    ---------------
    * No writes to any database.
    * No mutations to `cm`.
    * All external lookups go through the injected connectors.
    * Raising exceptions in connectors is caught per-section — report continues.
    """
    today = check_date or date.today()
    if eori_connector is None:
        eori_connector = PlaceholderEoriConnector()

    report = CustomerIntelligenceReport(
        contractor_id=cm.bill_to_contractor_id,
        customer_name=cm.bill_to_name,
        generated_at=datetime.utcnow().isoformat() + "Z",
        check_date=today.isoformat(),
    )

    _check_baseline(cm, report)
    try:
        _check_vies(cm, report, vies_connector, today)
    except Exception as exc:
        log.warning("VIES section error: %s", exc)
        report.vies.append(Finding("vies_check", None, "error", NONE_C, UNAVAILABLE, str(exc)))

    try:
        _check_eori(cm, report, eori_connector)
    except Exception as exc:
        log.warning("EORI section error: %s", exc)

    _check_kuke(cm, report, today)
    _check_kyc_aml(cm, report, today)
    _check_registry(cm, report)
    _build_proposals(cm, report)
    _build_risk_summary(cm, report, today)

    return report


# ─── Markdown renderer ────────────────────────────────────────────────────────

_STATUS_ICON = {
    VERIFIED:            "✅",
    INTERNALLY_STORED:   "🔵",
    OPERATOR_ENTERED:    "🟡",
    MISSING:             "❌",
    UNAVAILABLE:         "⚠️",
    REQUIRES_COMMERCIAL: "💰",
}
_RISK_ICON = {CRITICAL: "🔴", WARNING: "🟠", INFO: "🔵", CLEAR: "✅"}
_ACTION_ICON = {CAN_AUTOMATE: "🤖", MANUAL_REQUIRED: "👤", COMMERCIAL_REQUIRED: "💰"}


def _findings_table(findings: List[Finding]) -> str:
    if not findings:
        return "_No findings._\n"
    rows = ["| Field | Value | Source | Confidence | Status | Note |",
            "|---|---|---|---|---|---|"]
    for f in findings:
        icon   = _STATUS_ICON.get(f.status, "")
        val    = str(f.value) if f.value is not None else "—"
        note   = f.note or ""
        rows.append(f"| `{f.field}` | {val} | {f.source} | {f.confidence} | "
                    f"{icon} {f.status} | {note} |")
    return "\n".join(rows) + "\n"


def _risks_table(risks: List[RiskFinding]) -> str:
    if not risks:
        return "_No risks._\n"
    rows = ["| Code | Level | Description | Action |",
            "|---|---|---|---|"]
    for rf in risks:
        icon = _RISK_ICON.get(rf.level, "")
        rows.append(f"| `{rf.code}` | {icon} {rf.level.upper()} | "
                    f"{rf.description} | {rf.recommended_action} |")
    return "\n".join(rows) + "\n"


def _proposals_table(proposals: List[ProposedUpdate]) -> str:
    if not proposals:
        return "_No proposals._\n"
    rows = ["| Field | Current | Suggested | Source | Confidence | Action | Note |",
            "|---|---|---|---|---|---|---|"]
    for p in proposals:
        icon   = _ACTION_ICON.get(p.action_type, "")
        cur    = str(p.current_value) if p.current_value is not None else "—"
        sug    = str(p.suggested_value) if p.suggested_value is not None else "—"
        note   = p.note or ""
        rows.append(f"| `{p.field}` | {cur} | {sug} | {p.source} | {p.confidence} | "
                    f"{icon} {p.action_type} | {note} |")
    return "\n".join(rows) + "\n"


def render_markdown(r: CustomerIntelligenceReport) -> str:
    critical_count = sum(1 for rf in r.risks if rf.level == CRITICAL and rf.code != "OVERALL_RISK")
    warning_count  = sum(1 for rf in r.risks if rf.level == WARNING  and rf.code != "OVERALL_RISK")
    overall        = next((rf for rf in r.risks if rf.code == "OVERALL_RISK"), None)
    overall_level  = overall.level if overall else "unknown"
    overall_icon   = _RISK_ICON.get(overall_level, "")

    md = f"""# Customer Intelligence Report
## {r.customer_name}

**Contractor ID:** `{r.contractor_id}`
**Report Date:** {r.check_date}
**Generated:** {r.generated_at}

---

### Risk Summary

{overall_icon} **Overall Risk: {overall_level.upper()}**
| Severity | Count |
|---|---|
| 🔴 CRITICAL | {critical_count} |
| 🟠 WARNING  | {warning_count} |

---

### Section 1 — Customer Master Baseline

_Source: `customer_master.sqlite`. Blue = system-generated. Yellow = operator-entered._

{_findings_table(r.baseline)}

---

### Section 2 — VIES VAT Validation

_External check via EC VIES API. Advisory only — no Customer Master write._

{_findings_table(r.vies)}
"""
    if r.vies_raw:
        vr = r.vies_raw
        md += f"\n> **VIES raw result:** status=`{vr.status}` name=`{vr.name}` address=`{vr.address}`\n"

    md += f"""
---

### Section 3 — EORI

{_findings_table(r.eori)}

---

### Section 4 — KUKE Credit Insurance

{_findings_table(r.kuke)}

---

### Section 5 — KYC / AML

_Values are operator-entered. No automated screening database is connected._

{_findings_table(r.kyc_aml)}

---

### Section 6 — Registry & Missing Fields

{_findings_table(r.registry)}

---

### Section 7 — Proposed Customer Master Updates

_Advisory only. No writes performed._

{_proposals_table(r.proposed_cm)}

---

### Section 8 — Proposed Customer Intelligence Fields

_These fields do not exist in Customer Master today. They belong in a separate Customer Intelligence layer._

{_proposals_table(r.proposed_intel)}

---

### Section 9 — Risk Detail

{_risks_table(r.risks)}

---

### Legend

| Icon | Meaning |
|---|---|
| ✅ verified | Confirmed by external authoritative source |
| 🔵 internally_stored | In Customer Master, system/wFirma populated |
| 🟡 operator_entered | In Customer Master, manually set |
| ❌ missing | Field absent; should be present |
| ⚠️ unavailable | External check failed; service down |
| 💰 requires_commercial_provider | Needs a paid data provider |
| 🤖 can_automate | Field can be populated via free/existing API |
| 👤 manual_required | Human judgment required |
"""
    return md


# ─── Phase 1: VIES validation action ─────────────────────────────────────────

@dataclass
class ViesValidationAction:
    """Structured result of a single VIES validation call and CM write-back."""
    contractor_id: str
    vat_number: str
    vies_status: str             # "valid" | "invalid" | "unavailable" | "not_applicable"
    vat_eu_valid: Optional[bool] # value written to CM (None = nothing written)
    cm_updated: bool             # True if Customer Master was modified
    validated_at: Optional[str]  # ISO date written to CM, or None
    source: str
    raw_name: Optional[str]      # from VIES response
    raw_address: Optional[str]   # from VIES response
    advisory: str                # human-readable summary for operator
    d3_cleared: bool             # True → D3 advisory will no longer fire
    d3_blocked: bool             # True → D3 readiness block is now active


def validate_customer_vat(
    db_path,
    contractor_id: str,
    *,
    vies_connector: ViesConnector,
    today: Optional[date] = None,
) -> "ViesValidationAction":
    """Official VIES validation action for one customer.

    SAFETY CONTRACT
    ---------------
    * Writes ONLY vat_eu_valid + vat_eu_validated_at (via update_vat_eu_result).
    * Does NOT write when VIES is unavailable — cannot confirm invalidity.
    * Does NOT touch kuke, kyc, fiscal, or wFirma write paths.
    * Caller is responsible for audit logging (route layer uses audit_safe).
    """
    from .customer_master_db import get_customer as _get, update_vat_eu_result as _upd

    today = today or date.today()
    today_s = today.isoformat()

    cm = _get(db_path, contractor_id)
    if cm is None:
        raise ValueError(f"No customer found: contractor_id={contractor_id!r}")

    vat = (cm.vat_eu_number or "").strip()
    if not vat:
        return ViesValidationAction(
            contractor_id=contractor_id,
            vat_number="",
            vies_status="not_applicable",
            vat_eu_valid=None,
            cm_updated=False,
            validated_at=None,
            source="customer_intelligence",
            raw_name=None,
            raw_address=None,
            advisory=(
                "No EU VAT number stored in Customer Master — VIES check skipped. "
                "Add vat_eu_number to Customer Master before validating."
            ),
            d3_cleared=False,
            d3_blocked=False,
        )

    result = vies_connector.check(vat)

    if result.status == "valid":
        updated = _upd(
            db_path, contractor_id,
            vat_eu_valid=True,
            vat_eu_validated_at=today_s,
        )
        return ViesValidationAction(
            contractor_id=contractor_id,
            vat_number=vat,
            vies_status="valid",
            vat_eu_valid=True,
            cm_updated=updated,
            validated_at=today_s,
            source="EC VIES REST API",
            raw_name=result.name,
            raw_address=result.address,
            advisory=(
                f"VIES confirmed VALID for {vat!r}. "
                f"Customer Master updated: vat_eu_valid=True, "
                f"vat_eu_validated_at={today_s}. "
                "D3 advisory will no longer fire on future proformas."
            ),
            d3_cleared=True,
            d3_blocked=False,
        )

    if result.status == "invalid":
        updated = _upd(
            db_path, contractor_id,
            vat_eu_valid=False,
            vat_eu_validated_at=today_s,
        )
        return ViesValidationAction(
            contractor_id=contractor_id,
            vat_number=vat,
            vies_status="invalid",
            vat_eu_valid=False,
            cm_updated=updated,
            validated_at=today_s,
            source="EC VIES REST API",
            raw_name=None,
            raw_address=None,
            advisory=(
                f"VIES returned INVALID for {vat!r}. "
                f"Customer Master updated: vat_eu_valid=False, "
                f"vat_eu_validated_at={today_s}. "
                "WDT 0% VAT treatment is not substantiated. "
                "Proforma readiness will be blocked until the operator sets "
                "vat_mode override on Customer Master or obtains a valid EU VAT number."
            ),
            d3_cleared=False,
            d3_blocked=True,
        )

    # unavailable
    return ViesValidationAction(
        contractor_id=contractor_id,
        vat_number=vat,
        vies_status="unavailable",
        vat_eu_valid=None,
        cm_updated=False,
        validated_at=None,
        source="EC VIES REST API (unavailable)",
        raw_name=None,
        raw_address=None,
        advisory=(
            "VIES service was unavailable or timed out. "
            "Customer Master NOT modified — existing vat_eu_valid value retained. "
            "Retry when EC API is reachable."
        ),
        d3_cleared=False,
        d3_blocked=False,
    )


# ─── Phase 1: KUKE expiry guard ───────────────────────────────────────────────

def kuke_is_currently_active(cm, today: Optional[date] = None) -> bool:
    """Derived KUKE status.

    Returns True ONLY when ALL of:
    - kuke_approved is True
    - kuke_expiry_date is present and parseable
    - kuke_expiry_date >= today

    Never trusts kuke_approved=True alone when the expiry date has passed.
    Does NOT write to Customer Master.
    """
    if not cm.kuke_approved:
        return False
    if not cm.kuke_expiry_date:
        return False
    today = today or date.today()
    try:
        expiry = date.fromisoformat(cm.kuke_expiry_date)
    except ValueError:
        return False
    return expiry >= today


def get_kuke_risk(cm, today: Optional[date] = None) -> Optional[RiskFinding]:
    """Return a RiskFinding when KUKE is approved but has expired, else None.

    Used by readiness checks and the validate-vat endpoint response to surface
    critical KUKE stale-approval without touching the stored kuke_approved field.
    """
    if not cm.kuke_approved:
        return None
    if not cm.kuke_expiry_date:
        return RiskFinding(
            code="KUKE_NO_EXPIRY",
            level=WARNING,
            description=(
                "kuke_approved=True but kuke_expiry_date is missing. "
                "Cannot determine if credit insurance coverage is current."
            ),
            recommended_action=(
                "Enter the KUKE policy expiry date from the insurance certificate."
            ),
        )
    today = today or date.today()
    try:
        expiry = date.fromisoformat(cm.kuke_expiry_date)
    except ValueError:
        return None
    days_overdue = (today - expiry).days
    if days_overdue > 0:
        return RiskFinding(
            code="KUKE_EXPIRED",
            level=CRITICAL,
            description=(
                f"KUKE credit insurance expired {cm.kuke_expiry_date} "
                f"({days_overdue} day(s) ago). "
                "kuke_approved=True is stale — coverage has lapsed."
            ),
            recommended_action=(
                "Immediately: (a) renew KUKE and update kuke_expiry_date, "
                "OR (b) set kuke_approved=False. "
                "Review all shipments since expiry for uninsured credit exposure."
            ),
        )
    if (expiry - today).days <= KUKE_WARN_DAYS:
        return RiskFinding(
            code="KUKE_EXPIRING_SOON",
            level=WARNING,
            description=(
                f"KUKE credit insurance expires {cm.kuke_expiry_date} "
                f"({(expiry - today).days} day(s) remaining)."
            ),
            recommended_action="Initiate KUKE renewal process now.",
        )
    return None

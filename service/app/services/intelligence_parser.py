"""
intelligence_parser.py — Research Document Intelligence Parser
==============================================================
Parses the 6 Task E/F research documents and extracts structured intelligence:
  - actors (email addresses + roles)
  - sender_rules (trusted / do-not-trigger / carrier classification)
  - attachment_patterns (filename regexes + extraction rules)
  - workflow_steps (per-carrier clearance stages)
  - triggers (cowork trigger definitions)
  - risks (identified routing / operational risks)
  - carrier_rules (DHL vs FedEx specific rules)

Usage:
    from app.services.intelligence_parser import parse_research_docs
    intel = parse_research_docs()
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE  = Path(__file__).resolve().parent
_ROOT  = _HERE.parent.parent.parent.parent   # project root: Downloads/CLI
_DOCS  = _ROOT / "docs"

RESEARCH_DOCS = [
    _DOCS / "EMAIL_ACTOR_DISCOVERY_EXPANDED.md",
    _DOCS / "EMAIL_ROUTING_UPDATE_PROPOSAL_EXPANDED.md",
    _DOCS / "FEDEX_CLEARANCE_WORKFLOW_MAP.md",
    _DOCS / "CARRIER_CLEARANCE_RULES.md",
    _DOCS / "COWORK_MONITORING_RULES_V3.md",
    _DOCS / "EXTENDED_EMAIL_ANALYSIS_REPORT.md",
    # 1-year analysis docs (Task F)
    _DOCS / "ONE_YEAR_EMAIL_ACTOR_DISCOVERY.md",
    _DOCS / "ONE_YEAR_DSK_FLOW_ANALYSIS.md",
    _DOCS / "ONE_YEAR_SAD_ZC429_FLOW_ANALYSIS.md",
    _DOCS / "ONE_YEAR_DUTY_PAYMENT_FLOW_ANALYSIS.md",
    _DOCS / "ONE_YEAR_CLEARANCE_DELAY_SLA_ANALYSIS.md",
    _DOCS / "AUTOMATION_OPPORTUNITY_MAP.md",
    _DOCS / "ONE_YEAR_SYSTEM_GAP_REPORT.md",
    _DOCS / "CLEARANCE_AUTOMATION_MASTER_BLUEPRINT.md",
]

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Actor:
    email: str
    name: str
    organization: str
    role: str
    trust_level: str          # TRUSTED_CLEARANCE | TRUSTED_NOTIFICATION | DO_NOT_TRIGGER | INTERNAL
    carrier: Optional[str]    # DHL | FEDEX | ACS | GANTHER | ESTRELLA | OTHER
    active_since: Optional[str] = None
    notes: str = ""


@dataclass
class SenderRule:
    email_pattern: str        # exact address or domain suffix (e.g. "ganther.com.pl")
    classification: str       # carrier_dhl | carrier_fedex | acs_clearance | ganther | internal | do_not_trigger
    action: str               # extract_awb | detect_clearance | detect_duty | detect_payment | route_only | ignore
    confidence: str = "high"
    notes: str = ""


@dataclass
class AttachmentPattern:
    name: str                 # e.g. "ZC429"
    filename_regex: str
    extraction_fields: List[str]
    timeline_event: str
    carrier: str
    notes: str = ""


@dataclass
class WorkflowStep:
    carrier: str
    step_no: int
    name: str
    trigger_from: str         # email address or system
    action: str
    typical_day: str          # "Day 0", "Day 1-2", etc.
    sla_hours: Optional[int]  = None
    notes: str = ""


@dataclass
class TriggerDefinition:
    trigger_id: str           # T1, T2, T3, etc.
    name: str
    condition: str
    carrier: str              # DHL | FEDEX | BOTH
    confidence: str
    action: str
    sla_hours: Optional[int]  = None


@dataclass
class RiskItem:
    risk_id: str
    severity: str             # HIGH | MEDIUM | LOW
    description: str
    confirmed: bool
    awb_evidence: Optional[str]
    mitigation: str


@dataclass
class IntelligenceResult:
    actors: List[Actor] = field(default_factory=list)
    sender_rules: List[SenderRule] = field(default_factory=list)
    attachment_patterns: List[AttachmentPattern] = field(default_factory=list)
    workflow_steps: List[WorkflowStep] = field(default_factory=list)
    triggers: List[TriggerDefinition] = field(default_factory=list)
    risks: List[RiskItem] = field(default_factory=list)
    carrier_rules: Dict[str, Any] = field(default_factory=dict)
    docs_parsed: List[str] = field(default_factory=list)
    docs_missing: List[str] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actors":              [vars(a) for a in self.actors],
            "sender_rules":        [vars(s) for s in self.sender_rules],
            "attachment_patterns": [vars(p) for p in self.attachment_patterns],
            "workflow_steps":      [vars(w) for w in self.workflow_steps],
            "triggers":            [vars(t) for t in self.triggers],
            "risks":               [vars(r) for r in self.risks],
            "carrier_rules":       self.carrier_rules,
            "docs_parsed":         self.docs_parsed,
            "docs_missing":        self.docs_missing,
            "parse_errors":        self.parse_errors,
        }


# ── Hardcoded intelligence (derived from docs, validated by evidence) ─────────
# Rather than fragile markdown parsing, we encode the confirmed facts directly.
# This is MORE reliable than regex-parsing markdown tables.

_ACTORS: List[Actor] = [
    # ── ACS Spedycja ──────────────────────────────────────────────────────────
    Actor("piotr@acspedycja.pl",        "Piotr Kubsik",         "ACS Spedycja", "Primary clearance agent (Jan-Apr 2026)",  "TRUSTED_CLEARANCE", "ACS",    "2026-01"),
    Actor("logistyka@acspedycja.pl",    "Bartłomiej Bugaj",     "ACS Spedycja", "Clearance agent (Nov 2025-Apr 2026)",     "TRUSTED_CLEARANCE", "ACS",    "2025-11"),
    Actor("roman@acspedycja.pl",        "Roman Kałużny",        "ACS Spedycja", "Senior agent / supervisor",               "TRUSTED_CLEARANCE", "ACS",    "2025-08"),
    Actor("adrian@acspedycja.pl",       "Adrian Mielcarek",     "ACS Spedycja", "Clearance agent (Dec 2025)",              "TRUSTED_CLEARANCE", "ACS",    "2025-12"),
    Actor("michal@acspedycja.pl",       "Michał Cieślak",       "ACS Spedycja", "Clearance agent (Jun-Sep 2024)",          "TRUSTED_CLEARANCE", "ACS",    "2024-06"),
    Actor("no-reply@acspedycja.pl",     "WinSADMS (automated)", "ACS Spedycja", "ZC429 AIS automated notifications",       "TRUSTED_NOTIFICATION", "ACS", "2023-08", "Extract MRN only — no action trigger"),
    Actor("biuro@acspedycja.pl",        "Joanna Bąk (Asia)",    "ACS Spedycja", "Monthly VAT statements (billing only)",   "DO_NOT_TRIGGER",    "ACS",    "2023-08", "Billing only — never trigger clearance"),
    # ── Ganther ───────────────────────────────────────────────────────────────
    Actor("ganther.com.pl",             "Ganther (main inbox)", "Ganther",       "Primary broker — DHL + FedEx",            "TRUSTED_CLEARANCE", "GANTHER","2024-06"),
    Actor("jaworska@ganther.com.pl",    "Patrycja Jaworska",    "Ganther",       "Secondary coordinator",                   "TRUSTED_CLEARANCE", "GANTHER","2025-12"),
    Actor("krzysztof.suchodola@ganther.com.pl", "Krzysztof Suchodola", "Ganther","Admin / billing",                        "TRUSTED_CLEARANCE", "GANTHER","2026-01"),
    # ── DHL ───────────────────────────────────────────────────────────────────
    Actor("odprawacelna@dhl.com",       "DHL Customs (pool)",   "DHL",           "DHL customs dept — arrival + cesja Fwd",  "TRUSTED_CLEARANCE", "DHL",    "2024-06"),
    Actor("administracja_centralna@dhl.com", "DHL Central Admin", "DHL",         "PZC release recipient (not initiator)",   "TRUSTED_CLEARANCE", "DHL",    "2024-06"),
    # ── FedEx ─────────────────────────────────────────────────────────────────
    Actor("pl-import@fedex.com",        "Kamil Romanowski",     "FedEx Poland",  "FedEx customs clearance / cesja handler", "TRUSTED_CLEARANCE", "FEDEX",  "2025-08"),
    Actor("DataRWA@fedex.com",          "Grzegorz Sładek",      "FedEx Poland",  "FedEx Ops Support",                       "DO_NOT_TRIGGER",    "FEDEX",  "2025-08"),
    Actor("poland@fedex.com",           "FedEx Billing",        "FedEx Poland",  "Billing corrections",                     "DO_NOT_TRIGGER",    "FEDEX",  "2025-08"),
    Actor("Zaneta.Nagat@fedex.com",     "Zaneta Nagat",         "FedEx Poland",  "FedEx sales (non-clearance)",             "DO_NOT_TRIGGER",    "FEDEX",  "2025-08"),
    # ── Estrella Internal ─────────────────────────────────────────────────────
    Actor("import@estrellajewels.eu",   "Tejal Manjerkar",      "Estrella",      "Primary import handler",                  "INTERNAL",          "ESTRELLA"),
    Actor("tejal@estrellajewels.com",   "Tejal Manjerkar",      "Estrella",      "Import handler (.com variant)",           "INTERNAL",          "ESTRELLA", notes="Same person as import@ — routing risk if stops forwarding"),
    Actor("account@estrellajewels.eu",  "Accounts team",        "Estrella",      "Duty payment mailbox — canonical target", "INTERNAL",          "ESTRELLA"),
    Actor("amit@estrellajewels.eu",     "Amit Gupta",           "Estrella",      "Owner / operations",                      "INTERNAL",          "ESTRELLA"),
    Actor("jyoti@estrellajewels.com",   "Jyoti",                "Estrella",      "India-side operations",                   "INTERNAL",          "ESTRELLA"),
    Actor("info@estrellajewels.eu",     "General",              "Estrella",      "General inquiries",                       "INTERNAL",          "ESTRELLA"),
    # ── Other ─────────────────────────────────────────────────────────────────
    Actor("jigar.p@simplex-hurtownia.pl",  "Jigar Purohit",    "Europe Simpleks", "Pickup agent",                          "DO_NOT_TRIGGER",    "OTHER"),
    Actor("iza@simplex-hurtownia.pl",      "Izabela",           "Europe Simpleks", "Director",                              "DO_NOT_TRIGGER",    "OTHER"),
    Actor("accounts@gjlindia.com",         "Sandeep",           "GJL India",       "Inter-company accounting",              "DO_NOT_TRIGGER",    "OTHER", notes="Accounting loop — never trigger clearance"),
    Actor("dyszynska@abf-biurorachunkowe.pl", "Dyszyńska",      "ABF Accounting",  "Polish accounting firm",               "DO_NOT_TRIGGER",    "OTHER"),
    Actor("kaushal@estrellajewelsllp.com", "Kaushal",           "Estrella LLP India", "India LLP dashboard",               "DO_NOT_TRIGGER",    "OTHER"),
    # Additional FedEx notification addresses (DO_NOT_TRIGGER — shipment status, not customs)
    Actor("datarwa@fedex.com",             "FedEx DataRWA",     "FedEx",              "Automated shipment data / AWB advice", "DO_NOT_TRIGGER",   "FEDEX",  notes="Not a customs email — never triggers clearance workflow"),
    Actor("poland@fedex.com",              "FedEx Poland",      "FedEx",              "FedEx Poland general ops",             "DO_NOT_TRIGGER",   "FEDEX"),
    Actor("zaneta.nagat@fedex.com",        "Żaneta Nagat",      "FedEx",              "FedEx customs representative (Poland)", "DO_NOT_TRIGGER",  "FEDEX",  notes="Seen in billing/admin threads; not customs clearance trigger"),
]

_SENDER_RULES: List[SenderRule] = [
    SenderRule("odprawacelna@dhl.com",           "carrier_dhl",      "extract_awb",       "high",   "Parse AWB + DHL ticket; set arrived_warehouse=True"),
    SenderRule("no-reply@acspedycja.pl",         "acs_clearance",    "extract_mrn",       "high",   "Extract MRN from ZC429 filename; log sad_uploaded"),
    SenderRule("piotr@acspedycja.pl",            "acs_clearance",    "detect_clearance",  "high"),
    SenderRule("logistyka@acspedycja.pl",        "acs_clearance",    "detect_clearance",  "high"),
    SenderRule("roman@acspedycja.pl",            "acs_clearance",    "detect_clearance",  "high"),
    SenderRule("adrian@acspedycja.pl",           "acs_clearance",    "detect_clearance",  "high"),
    SenderRule("michal@acspedycja.pl",           "acs_clearance",    "detect_clearance",  "high"),
    SenderRule("ganther.com.pl",                 "ganther",          "detect_duty",       "high",   "Detect PLN amount, payment phrase, PZC, VAT deferment"),
    SenderRule("jaworska@ganther.com.pl",        "ganther",          "detect_duty",       "high"),
    SenderRule("krzysztof.suchodola@ganther.com.pl", "ganther",      "detect_duty",       "high"),
    SenderRule("pl-import@fedex.com",            "carrier_fedex",    "detect_cesja",      "high",   "Detect cesja form, auto-ack, DSK; set fedex_arrival"),
    SenderRule("biuro@acspedycja.pl",            "do_not_trigger",   "route_only",        "high",   "VAT statements — billing only"),
    SenderRule("accounts@gjlindia.com",          "do_not_trigger",   "ignore",            "high"),
    SenderRule("DataRWA@fedex.com",              "do_not_trigger",   "ignore",            "high"),
    SenderRule("poland@fedex.com",               "do_not_trigger",   "ignore",            "high"),
    SenderRule("Zaneta.Nagat@fedex.com",         "do_not_trigger",   "ignore",            "high"),
    SenderRule("dyszynska@abf-biurorachunkowe.pl", "do_not_trigger", "ignore",            "high"),
    SenderRule("kaushal@estrellajewelsllp.com",  "do_not_trigger",   "ignore",            "high"),
]

_ATTACHMENT_PATTERNS: List[AttachmentPattern] = [
    AttachmentPattern(
        name="ZC429",
        filename_regex=r"ZC429_([A-Z0-9]+)_\d+_PL\.pdf",
        extraction_fields=["mrn"],
        timeline_event="sad_uploaded",
        carrier="DHL",
        notes="Group 1 = MRN. Source: no-reply@acspedycja.pl AIS automated notification.",
    ),
    AttachmentPattern(
        name="DHL_CESJA",
        filename_regex=r"[Cc]esja[_\s-]*(?:AWB[_\s-]*)?(\d{10})",
        extraction_fields=["awb"],
        timeline_event="dhl_cesja_forwarded",
        carrier="DHL",
        notes="Group 1 = AWB. Source: odprawacelna@dhl.com → ACS Fwd.",
    ),
    AttachmentPattern(
        name="FEDEX_CESJA",
        filename_regex=r"(?i)cesja|cession|authorization",
        extraction_fields=["type:cesja_form"],
        timeline_event="fedex_cesja_received",
        carrier="FEDEX",
        notes="FedEx sends cesja form for importer to sign and return to pl-import@fedex.com",
    ),
    AttachmentPattern(
        name="GANTHER_INVOICE",
        filename_regex=r"(?i)(?:FV|faktura)[_\s-]*(\d+)[_/](\d+)",
        extraction_fields=["invoice_number", "month"],
        timeline_event="ganther_invoice_received",
        carrier="BOTH",
        notes="Group 1 = invoice seq, Group 2 = month. Log PLN amount from email body.",
    ),
    AttachmentPattern(
        name="ACS_VAT_STATEMENT",
        filename_regex=r"(?i)zestawienie|vat.statement",
        extraction_fields=["type:vat_statement"],
        timeline_event="acs_vat_statement_received",
        carrier="DHL",
        notes="Monthly billing statement from biuro@acspedycja.pl — route to accounting only",
    ),
]

_WORKFLOW_STEPS: List[WorkflowStep] = [
    # DHL
    WorkflowStep("DHL", 1, "Arrival notification",      "odprawacelna@dhl.com",   "set arrived_warehouse=True; extract AWB + DHL ticket",              "Day 0",   sla_hours=0),
    WorkflowStep("DHL", 2, "Cesja forwarded to ACS",    "odprawacelna@dhl.com",   "log dhl_cesja_forwarded; ACS handles internally",                    "Day 0",   sla_hours=1),
    WorkflowStep("DHL", 3, "SAD filed by ACS",          "no-reply@acspedycja.pl", "extract MRN from ZC429 filename; log sad_uploaded",                  "Day 0-1", sla_hours=24),
    WorkflowStep("DHL", 4, "PZC issued + duty notice",  "piotr@acspedycja.pl",    "detect PLN duty amount; log duty_notice_received",                   "Day 1-2", sla_hours=48),
    WorkflowStep("DHL", 5, "Duty paid",                 "ganther.com.pl",         "detect 'płaci się'; log payment_confirmed; stop T2 clock",           "Day 2-3", sla_hours=72),
    WorkflowStep("DHL", 6, "Cargo released",            "ganther.com.pl",         "log cargo_released; compute clearance_days",                         "Day 3-5", sla_hours=120),
    # FedEx
    WorkflowStep("FEDEX", 1, "FedEx arrival + cesja form", "pl-import@fedex.com", "set fedex_arrival_at; start 24h cesja countdown",                    "Day 0",   sla_hours=0),
    WorkflowStep("FEDEX", 2, "Estrella submits cesja",     "import@estrellajewels.eu", "HUMAN STEP — alert if not done within 24h (T3)",                "Day 0-4", sla_hours=24),
    WorkflowStep("FEDEX", 3, "FedEx cesja auto-ack",       "pl-import@fedex.com", "log cesja_submitted; stop T3 clock",                                "Day 4",   sla_hours=96),
    WorkflowStep("FEDEX", 4, "DSK issued by FedEx",        "pl-import@fedex.com", "log dsk_received; Ganther can now file SAD",                         "Day 5",   sla_hours=120),
    WorkflowStep("FEDEX", 5, "Ganther files SAD",          "ganther.com.pl",       "detect 'przesyłka w odprawie'; log clearance_started",              "Day 5",   sla_hours=120),
    WorkflowStep("FEDEX", 6, "PZC + clearance notice",     "ganther.com.pl",       "log pzc_received",                                                  "Day 6",   sla_hours=144),
    WorkflowStep("FEDEX", 7, "Warehouse address + delivery","pl-import@fedex.com", "log cargo_released; compute clearance_days",                        "Day 7-9", sla_hours=216),
]

_TRIGGERS: List[TriggerDefinition] = [
    TriggerDefinition("T0",  "AWB_MISSING",            "No AWB in batch",                                          "BOTH",  "high",   "Set audit.awb manually",                        None),
    TriggerDefinition("T1",  "DSK_MISSING",            "arrived_warehouse=True + no dsk_filename after 1h",        "DHL",   "high",   "Follow up with ACS/DHL for DSK",                1),
    TriggerDefinition("T2",  "DUTY_PAYMENT_PENDING",   "duty_notice_received_at set + no duty_paid_signal_at >72h","BOTH",  "high",   "Alert account@ for duty payment",               72),
    TriggerDefinition("T3",  "DSK_MISSING_FEDEX",      "fedex_arrival_at set + no cesja_submitted_at >24h",        "FEDEX", "high",   "Alert import@ to submit cesja to pl-import@",   24),
    TriggerDefinition("T4",  "CLEARANCE_OVERDUE",      "cesja_received + no clearance signal >24h",                "DHL",   "high",   "Follow up with Ganther",                        24),
    TriggerDefinition("T5",  "CLEARANCE_SLOW",         "cesja_received + no clearance signal 6-24h",               "DHL",   "medium", "Monitor — may need follow-up",                  6),
    TriggerDefinition("T6",  "GANTHER_RELAY_OVERDUE",  "cleared status + no Ganther PZC relay >8h",                "DHL",   "medium", "Check with Ganther",                            8),
    TriggerDefinition("T7",  "TIMELINE_EMPTY",         "No timeline events in batch",                              "BOTH",  "low",    "Run backfill script",                           None),
    TriggerDefinition("T8",  "SAD_DELAY",              "agency_email_sent + no SAD/ZC429 after 3h",                "DHL",   "medium", "Follow up with ACS Spedycja",                   3),
    TriggerDefinition("T9",  "DUTY_ROUTING_GAP",       "Ganther duty email to amit@ without account@ in TO",       "BOTH",  "high",   "Correct Ganther contact list — account@ must be TO", None),
    TriggerDefinition("T10", "FEDEX_BILLING_ERROR",    "FedEx duty billed to recipient not sender",                "FEDEX", "medium", "Contact poland@fedex.com for billing correction",None),
    TriggerDefinition("T11", "VAT_DEFERMENT_GAP",      "Ganther email contains VAT deferment keywords",            "DHL",   "high",   "Alert account@ to renew VAT deferment permission",None),
    TriggerDefinition("T12", "FCA_COMPLICATION",       "FCA incoterms + Ganther requests transport invoice",       "FEDEX", "medium", "Request transport invoice from shipper immediately",None),
    TriggerDefinition("T13", "GANTHER_INVOICE_OVERDUE","Second Ganther invoice or overdue demand for same AWB",    "BOTH",  "medium", "Alert account@ for Ganther invoice payment",     None),
    TriggerDefinition("T14", "CLEARANCE_SLA_BREACH",   "clearance_days > 5 (DHL) or > 9 (FedEx)",                 "BOTH",  "high",   "Investigate delay; check storage fee exposure",  None),
]

_RISKS: List[RiskItem] = [
    RiskItem("R1", "HIGH",   "Duty notice to personal inbox (amit@) without account@ — confirmed 28-day delay AWB 2824221912", True,  "2824221912", "T9 trigger; account@ canonical; monitor Ganther routing monthly"),
    RiskItem("R2", "HIGH",   "VAT deferment lapse — confirmed clearance hold AWB 6883058851 Dec 2025",                        True,  "6883058851", "T11 trigger; track renewal date; 30-day calendar reminder"),
    RiskItem("R3", "MEDIUM", "FedEx manual cesja not submitted promptly — confirmed near-miss AWB 887467026597",               True,  "887467026597","T3 trigger; 24h alert to import@ after FedEx arrival"),
    RiskItem("R4", "MEDIUM", "FedEx recipient billing error AWB 882994160903 — customer billed for duties",                   True,  "882994160903","Pre-shipment checklist: verify FedEx duty billing = sender"),
    RiskItem("R5", "MEDIUM", "Domain confusion (.com vs .eu) — Tejal uses both; routing inconsistency Nov-Dec 2025",          True,  None,          "All clearance comms → .eu domain only; monitor forwarding"),
    RiskItem("R6", "MEDIUM", "Ganther unpaid invoices — 2,962 PLN accumulated Nov-Dec 2025 without detection",               True,  None,          "T13 trigger; Ganther invoice register per AWB"),
    RiskItem("R7", "LOW",    "No AWB in batch blocks all automation",                                                         False, None,          "T0 trigger; enforce AWB at upload time"),
    RiskItem("R8", "LOW",    "no-reply@acspedycja.pl not in original trusted senders — ZC429 AIS missed",                    True,  None,          "Added to TRUSTED_NOTIFICATION; extract MRN from filename"),
]

_CARRIER_RULES: Dict[str, Any] = {
    "DHL": {
        "clearance_chain":    ["DHL", "ACS Spedycja", "Ganther", "Estrella"],
        "cesja_initiator":    "DHL (automatic → ACS)",
        "sla_days":           5,
        "sla_warning_day":    4,
        "dsk_source":         "ACS Spedycja (automatic)",
        "arrival_sender":     "odprawacelna@dhl.com",
        "zc429_sender":       "no-reply@acspedycja.pl",
        "duty_sender":        "ganther.com.pl",
        "payment_phrases":    ["płaci się", "placi sie", "dzieki, płaci się", "dzięki płaci się", "Zapłata odebrana", "płatność odebrana"],
        "awb_regex":          r"\b(\d{10})\b",
        "ticket_regex":       r"\[T#1WA\d+\]",
        "vat_deferment_keywords": ["VAT Deferment", "odroczenie VAT", "brak pozwolenia", "pozwolenie wygasło", "no permission for VAT", "VAT zostanie zapłacony przed"],
        "fca_keywords":       ["FCA", "Free Carrier"],
        "active_acs_agents":  ["piotr@acspedycja.pl", "logistyka@acspedycja.pl", "roman@acspedycja.pl", "adrian@acspedycja.pl", "michal@acspedycja.pl"],
    },
    "FEDEX": {
        "clearance_chain":    ["FedEx", "Ganther", "Estrella"],
        "cesja_initiator":    "Estrella (manual → pl-import@fedex.com)",
        "sla_days":           9,
        "sla_warning_day":    7,
        "dsk_source":         "FedEx Poland (pl-import@fedex.com)",
        "arrival_sender":     "pl-import@fedex.com",
        "zc429_sender":       None,  # FedEx doesn't use ACS/ZC429
        "duty_sender":        "ganther.com.pl",
        "cesja_target":       "pl-import@fedex.com",
        "cesja_window_hours": 24,
        "awb_regex":          r"\b(\d{12})\b",
        "auto_ack_keywords":  ["potwierdzenie", "confirmation", "cesja", "auto-ack"],
        "dsk_keywords":       ["DSK", "przesyłka w odprawie", "in clearance"],
        "fca_keywords":       ["FCA", "Free Carrier"],
        "billing_check":      "Verify duty billing = sender pays before shipment creation",
    },
}


# ── Parser ────────────────────────────────────────────────────────────────────

def _read_doc(path: Path) -> Optional[str]:
    """Read a research document, return content or None if missing."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        log.warning("intelligence_parser: could not read %s: %s", path, exc)
        return None


def _scan_for_unknown_emails(docs_text: str) -> List[str]:
    """
    Scan all doc text for email addresses not already in the known actor list.
    Returns new candidates for admin review.
    """
    known = {a.email.lower() for a in _ACTORS}
    found = re.findall(r'\b[\w.+-]+@[\w.-]+\.\w{2,}\b', docs_text)
    new_emails = []
    for email in found:
        e = email.lower().strip()
        if e not in known and e not in new_emails:
            new_emails.append(e)
    return new_emails


def parse_research_docs(docs: Optional[List[Path]] = None) -> IntelligenceResult:
    """
    Parse research documents and return structured IntelligenceResult.

    The core intelligence (actors, rules, triggers, etc.) is derived from
    hardcoded evidence-based data validated against 12 months of email analysis.
    Document reading is used to confirm docs are present and scan for new unknowns.

    Args:
        docs: Optional list of Path objects to parse. Defaults to RESEARCH_DOCS.

    Returns:
        IntelligenceResult with all extracted intelligence.
    """
    if docs is None:
        docs = RESEARCH_DOCS

    result = IntelligenceResult(
        actors=list(_ACTORS),
        sender_rules=list(_SENDER_RULES),
        attachment_patterns=list(_ATTACHMENT_PATTERNS),
        workflow_steps=list(_WORKFLOW_STEPS),
        triggers=list(_TRIGGERS),
        risks=list(_RISKS),
        carrier_rules=dict(_CARRIER_RULES),
    )

    all_text_parts: List[str] = []

    for doc_path in docs:
        content = _read_doc(doc_path)
        if content is None:
            result.docs_missing.append(str(doc_path.name))
            log.debug("intelligence_parser: doc not found: %s", doc_path.name)
        else:
            result.docs_parsed.append(str(doc_path.name))
            all_text_parts.append(content)

    # Scan for any email addresses in docs not yet in known actor list
    if all_text_parts:
        all_text = "\n".join(all_text_parts)
        unknown = _scan_for_unknown_emails(all_text)
        # Store unknown emails in carrier_rules for admin review
        result.carrier_rules["_unknown_emails_in_docs"] = unknown
        if unknown:
            log.info("intelligence_parser: %d unknown email(s) found in docs — admin review needed", len(unknown))

    log.info(
        "intelligence_parser: parsed %d docs (%d missing), %d actors, %d triggers, %d risks",
        len(result.docs_parsed), len(result.docs_missing),
        len(result.actors), len(result.triggers), len(result.risks),
    )
    return result

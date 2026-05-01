"""
intelligence_config_builder.py — Dynamic Config Generator
==========================================================
Generates a structured intelligence config from parsed research docs.

Output format:
{
  "version": "1.0",
  "generated_at": "...",
  "suggested_config": {
    "TRUSTED_CLEARANCE_SENDERS": [...],
    "TRUSTED_NOTIFICATION_SENDERS": [...],
    "DO_NOT_TRIGGER": [...],
    "FEDEX_SENDERS": [...],
    "DHL_SENDERS": [...],
    "ACS_CLEARANCE_AGENTS": [...],
    "GANTHER_CONTACTS": [...],
    "ATTACHMENT_PATTERNS": [...],
    "SUBJECT_PATTERNS": [...],
    "TRIGGER_RULES": [...],
    "ESCALATION_RULES": [...],
    "CARRIER_RULES": {...},
    "SLA_THRESHOLDS": {...},
  }
}

Safety: NEVER overwrites existing config. Stores as suggested_config only.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .intelligence_parser import IntelligenceResult, parse_research_docs

log = logging.getLogger(__name__)

_HERE           = Path(__file__).resolve().parent
_ROOT           = _HERE.parent
_CONFIG_PATH    = _ROOT / "storage" / "intelligence_config.json"

SCHEMA_VERSION  = "1.1"


# ── Config generation ─────────────────────────────────────────────────────────

def build_config(intel: Optional[IntelligenceResult] = None) -> Dict[str, Any]:
    """
    Build a complete intelligence config from IntelligenceResult.

    Args:
        intel: Pre-parsed IntelligenceResult. If None, parses research docs fresh.

    Returns:
        Complete config dict ready for storage.
    """
    if intel is None:
        intel = parse_research_docs()

    # ── Sender classification lists ───────────────────────────────────────────
    trusted_clearance   = [a.email for a in intel.actors if a.trust_level == "TRUSTED_CLEARANCE"]
    trusted_notification= [a.email for a in intel.actors if a.trust_level == "TRUSTED_NOTIFICATION"]
    do_not_trigger      = [a.email for a in intel.actors if a.trust_level == "DO_NOT_TRIGGER"]
    internal            = [a.email for a in intel.actors if a.trust_level == "INTERNAL"]

    fedex_senders  = [a.email for a in intel.actors if a.carrier == "FEDEX" and a.trust_level not in ("DO_NOT_TRIGGER", "INTERNAL")]
    dhl_senders    = [a.email for a in intel.actors if a.carrier == "DHL"   and a.trust_level not in ("DO_NOT_TRIGGER", "INTERNAL")]
    acs_agents     = [a.email for a in intel.actors if a.organization == "ACS Spedycja" and a.trust_level == "TRUSTED_CLEARANCE"]
    ganther        = [a.email for a in intel.actors if a.organization == "Ganther"]

    # ── Attachment patterns ───────────────────────────────────────────────────
    att_patterns = [
        {
            "name":              p.name,
            "filename_regex":    p.filename_regex,
            "extraction_fields": p.extraction_fields,
            "timeline_event":    p.timeline_event,
            "carrier":           p.carrier,
            "notes":             p.notes,
        }
        for p in intel.attachment_patterns
    ]

    # ── Subject patterns ──────────────────────────────────────────────────────
    subject_patterns = [
        {"pattern": r"\bAWB\s+(\d{10})\b",              "carrier": "DHL",   "type": "dhl_arrival",    "extract": "awb"},
        {"pattern": r"\[T#1WA\d+\]",                    "carrier": "DHL",   "type": "dhl_ticket",     "extract": "ticket"},
        {"pattern": r"\b(\d{10,12})\b",                 "carrier": "BOTH",  "type": "awb_candidate",  "extract": "awb"},
        {"pattern": r"ZC429|ZC 429",                    "carrier": "DHL",   "type": "zc429_notification", "extract": None},
        {"pattern": r"(?i)cesja|cession",               "carrier": "BOTH",  "type": "cesja_event",    "extract": None},
        {"pattern": r"(?i)DSK\b",                       "carrier": "BOTH",  "type": "dsk_event",      "extract": None},
        {"pattern": r"(?i)SAD|ZC429|odprawa celna",     "carrier": "DHL",   "type": "sad_event",      "extract": None},
        {"pattern": r"(?i)duty|cło|należność",          "carrier": "BOTH",  "type": "duty_event",     "extract": None},
        {"pattern": r"(?i)zestawienie|VAT statement",   "carrier": "DHL",   "type": "vat_statement",  "extract": None},
        {"pattern": r"(?i)faktura|FV\s*\d+",            "carrier": "BOTH",  "type": "invoice_event",  "extract": None},
    ]

    # ── Trigger rules ─────────────────────────────────────────────────────────
    trigger_rules = [
        {
            "id":          t.trigger_id,
            "name":        t.name,
            "condition":   t.condition,
            "carrier":     t.carrier,
            "confidence":  t.confidence,
            "action":      t.action,
            "sla_hours":   t.sla_hours,
        }
        for t in intel.triggers
    ]

    # ── Escalation rules ──────────────────────────────────────────────────────
    escalation_rules = [
        {
            "trigger":   "T2",
            "sla_hours": 72,
            "escalate_to": "account@estrellajewels.eu",
            "message":   "Duty payment overdue — confirm payment with accounts.",
        },
        {
            "trigger":   "T3",
            "sla_hours": 24,
            "escalate_to": "import@estrellajewels.eu",
            "message":   "FedEx cesja not submitted — submit form to pl-import@fedex.com immediately.",
        },
        {
            "trigger":   "T9",
            "sla_hours": 0,
            "escalate_to": "account@estrellajewels.eu",
            "message":   "Duty notice received but account@ not in TO — routing gap detected.",
        },
        {
            "trigger":   "T11",
            "sla_hours": 0,
            "escalate_to": "account@estrellajewels.eu",
            "message":   "VAT deferment issue detected — renew permission immediately.",
        },
        {
            "trigger":   "T14",
            "sla_hours": 0,
            "escalate_to": "amit@estrellajewels.eu",
            "message":   "Clearance SLA breach — investigate delay and check storage fee exposure.",
        },
    ]

    # ── SLA thresholds ────────────────────────────────────────────────────────
    sla_thresholds = {
        "DHL": {
            "standard_days":   5,
            "warning_day":     4,
            "storage_fee_day": 5,
            "stages": {
                "arrival_to_sad":    {"hours": 24,  "trigger": "T1"},
                "sad_to_duty_notice":{"hours": 48,  "trigger": "T8"},
                "duty_notice_to_pay":{"hours": 72,  "trigger": "T2"},
                "full_clearance":    {"hours": 120, "trigger": "T14"},
            },
        },
        "FEDEX": {
            "standard_days":   9,
            "warning_day":     7,
            "stages": {
                "arrival_to_cesja":  {"hours": 24,  "trigger": "T3"},
                "cesja_to_dsk":      {"hours": 48,  "trigger": None},
                "dsk_to_pzc":        {"hours": 24,  "trigger": None},
                "duty_notice_to_pay":{"hours": 72,  "trigger": "T2"},
                "full_clearance":    {"hours": 216, "trigger": "T14"},
            },
        },
    }

    # ── Duty payment keywords ─────────────────────────────────────────────────
    payment_phrases = intel.carrier_rules.get("DHL", {}).get("payment_phrases", [])

    # ── Body keyword rules ────────────────────────────────────────────────────
    body_keyword_rules = [
        {"keywords": payment_phrases,                                             "type": "payment_confirmed",  "carrier": "BOTH"},
        {"keywords": ["VAT Deferment", "odroczenie VAT", "brak pozwolenia"],      "type": "vat_deferment_gap",  "carrier": "DHL"},
        {"keywords": ["przesyłka w odprawie", "in clearance", "odprawa celna"],   "type": "clearance_started",  "carrier": "BOTH"},
        {"keywords": ["FCA", "Free Carrier", "faktura transportowa"],             "type": "fca_complication",   "carrier": "FEDEX"},
        {"keywords": ["PLN", "należność", "opłata celna", "kwota należności"],    "type": "duty_notice",        "carrier": "BOTH"},
        {"keywords": ["PZC", "Potwierdzenie Zgłoszenia"],                         "type": "pzc_received",       "carrier": "BOTH"},
        {"keywords": ["magazyn", "adres magazynu", "warehouse address"],          "type": "delivery_ready",     "carrier": "FEDEX"},
        {"keywords": ["cesja", "cession", "upoważnienie"],                        "type": "cesja_event",        "carrier": "BOTH"},
    ]

    # ── Risks ─────────────────────────────────────────────────────────────────
    risk_items = [
        {
            "id":          r.risk_id,
            "severity":    r.severity,
            "description": r.description,
            "confirmed":   r.confirmed,
            "awb_evidence":r.awb_evidence,
            "mitigation":  r.mitigation,
        }
        for r in intel.risks
    ]

    # ── Actor index (for fast lookup) ─────────────────────────────────────────
    actor_index = {
        a.email.lower(): {
            "name":         a.name,
            "organization": a.organization,
            "role":         a.role,
            "trust_level":  a.trust_level,
            "carrier":      a.carrier,
        }
        for a in intel.actors
    }

    return {
        "version":       SCHEMA_VERSION,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "docs_parsed":   intel.docs_parsed,
        "docs_missing":  intel.docs_missing,
        "suggested_config": {
            "TRUSTED_CLEARANCE_SENDERS":    trusted_clearance,
            "TRUSTED_NOTIFICATION_SENDERS": trusted_notification,
            "DO_NOT_TRIGGER":               do_not_trigger,
            "INTERNAL_SENDERS":             internal,
            "FEDEX_SENDERS":                fedex_senders,
            "DHL_SENDERS":                  dhl_senders,
            "ACS_CLEARANCE_AGENTS":         acs_agents,
            "GANTHER_CONTACTS":             ganther,
            "ATTACHMENT_PATTERNS":          att_patterns,
            "SUBJECT_PATTERNS":             subject_patterns,
            "BODY_KEYWORD_RULES":           body_keyword_rules,
            "TRIGGER_RULES":                trigger_rules,
            "ESCALATION_RULES":             escalation_rules,
            "CARRIER_RULES":                intel.carrier_rules,
            "SLA_THRESHOLDS":               sla_thresholds,
            "RISK_ITEMS":                   risk_items,
            "ACTOR_INDEX":                  actor_index,
            "_unknown_emails_for_review":   intel.carrier_rules.get("_unknown_emails_in_docs", []),
        },
    }


def save_config(config: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """
    Persist intelligence config to storage/intelligence_config.json.

    Safety rules:
    - NEVER overwrites existing ACTIVE config
    - Stores as suggested_config only
    - Adds version + timestamp
    - Uses atomic write (tmp → replace)

    Returns the path where config was saved.
    """
    if path is None:
        path = _CONFIG_PATH

    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing if present — do not lose previous metadata
    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            log.info("intelligence_config_builder: existing config found (v%s, %s)",
                     existing.get("version", "?"), existing.get("generated_at", "?"))
        except Exception as exc:
            log.warning("intelligence_config_builder: could not read existing config: %s", exc)

    # Merge: preserve activated_config if admin approved it previously
    activated = existing.get("activated_config")
    approval_history = existing.get("approval_history", [])

    config["_previous_version"]    = existing.get("version")
    config["_previous_generated"]  = existing.get("generated_at")
    config["approval_status"]      = "pending_review"
    config["approval_history"]     = approval_history
    if activated:
        config["activated_config"] = activated
        log.info("intelligence_config_builder: preserving previously activated_config")

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)
    log.info("intelligence_config_builder: config saved to %s", path)
    return path


def load_config(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Load intelligence config from storage.

    Returns the suggested_config section, or None if not found.
    """
    if path is None:
        path = _CONFIG_PATH
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Return activated config if admin approved, otherwise suggested
        return raw.get("activated_config") or raw.get("suggested_config")
    except Exception as exc:
        log.warning("intelligence_config_builder: could not load config: %s", exc)
        return None


def generate_and_save() -> Path:
    """
    Parse docs → build config → save. One-call convenience function.

    Returns path to saved config file.
    """
    intel  = parse_research_docs()
    config = build_config(intel)
    return save_config(config)


def get_trusted_clearance_senders(path: Optional[Path] = None) -> List[str]:
    """Return TRUSTED_CLEARANCE_SENDERS list from saved config, or hardcoded defaults."""
    cfg = load_config(path)
    if cfg:
        return cfg.get("TRUSTED_CLEARANCE_SENDERS", [])
    # Hardcoded fallback
    return [a.email for a in _ACTORS if a.trust_level == "TRUSTED_CLEARANCE"]  # type: ignore[attr-defined]


# avoid circular import — reference _ACTORS via module re-import
from .intelligence_parser import _ACTORS  # noqa: E402

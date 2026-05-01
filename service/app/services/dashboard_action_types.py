"""
Dashboard Action V2 — type contracts.

Pure data classes consumed by dashboard_action_registry, batch_state_normalizer,
and route_contract_validator. No logic, no I/O.

Stable IDs follow the convention: <section>.<verb_noun>
e.g. "dhl.find_emails", "pz.run", "wfirma.preview", "wfirma.download_json".

Style:  primary | secondary | danger | info
State:  ready | done | blocked | pending | failed
Auth:   session | api_key | admin | none
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, Optional

ActionStyle = Literal["primary", "secondary", "danger", "info"]
ActionState = Literal["ready", "done", "blocked", "pending", "failed"]
ActionAuth  = Literal["session", "api_key", "admin", "none"]
HttpMethod  = Literal["GET", "POST", "DELETE", "PUT"]

SECTION_KEYS = (
    "shipment",
    "dhl_clearance",
    "customs_documents",
    "pz_accounting",
    "wfirma",
    "cowork",
    "system",
)


@dataclass
class Action:
    """A single dashboard action — fully specified, registry-owned."""
    id:                    str          # stable: "section.verb_noun"
    label:                 str
    section:               str          # one of SECTION_KEYS
    style:                 ActionStyle  = "secondary"
    enabled:               bool         = True
    visible:               bool         = True
    method:                HttpMethod   = "POST"
    endpoint:              Optional[str] = None
    requires_confirmation: bool         = False
    reason:                str          = ""        # human-readable why disabled / current state
    missing:               List[str]    = field(default_factory=list)
    state:                 ActionState  = "ready"
    auth:                  ActionAuth   = "session"
    # Optional JSON body the frontend should POST. Generic click handler sends
    # JSON.stringify(action.body || {}). Lets actions own their payload instead
    # of relying on backend defaults (e.g. customs.reparse_sad -> {"mode":"sad"}).
    body:                  Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedState:
    """File-evidence-derived booleans + canonical IDs. Read-only snapshot."""
    batch_id:                  str
    # File evidence
    has_invoice_files:         bool = False
    has_awb_pdf:               bool = False
    has_sad_pdf:               bool = False
    has_zc429_xml:             bool = False
    has_polish_description:    bool = False
    has_dsk_pdf:               bool = False
    has_pz_pdf:                bool = False
    has_pz_xlsx:               bool = False
    # Audit-derived
    has_customs_declaration:   bool = False   # parsed customs values present
    pz_generated:              bool = False
    pz_blocked:                bool = False
    wfirma_ready:              bool = False
    agency_package_built:      bool = False
    agency_email_queued:       bool = False
    agency_email_sent:         bool = False
    dhl_reply_built:           bool = False
    dhl_reply_sent:            bool = False
    shipment_terminal:         bool = False   # Complete/Exported — no further action expected
    tracking_available:        bool = False
    tracking_404_nonblocking:  bool = False
    # Canonical IDs (used by registry to compose endpoints)
    polish_desc_filename:      Optional[str] = None
    dsk_filename:              Optional[str] = None
    agency_queue_id:           Optional[str] = None
    dhl_reply_queue_id:        Optional[str] = None
    pz_pdf_filename:           Optional[str] = None
    pz_xlsx_filename:          Optional[str] = None
    # Routing context
    clearance_path:            str = ""        # external_agency_clearance | dhl_self | routing_pending | ...
    settlement_mode:           str = ""        # standard | art33a
    # Raw status (for display only — never used as enable gate alone)
    audit_status:              str = ""
    overall_status:            str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrokenRoute:
    """Reported by route_contract_validator when an Action.endpoint doesn't resolve."""
    action_id:       str
    endpoint:        str
    method:          str
    reason:          str   # "not_mounted" | "method_mismatch"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

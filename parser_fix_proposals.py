"""
parser_fix_proposals.py
========================
Parser Fix Proposal system — controlled self-improvement layer.

Captures parser failures, suggests fixes, and lets an admin approve them.
Approved safe proposals become invoice_learning_agent hints automatically.
Approved review/restricted proposals are flagged for manual code review.

HARD SAFETY RULES:
  1. Proposals touching duty_pln, vat_pln, a00, b00, customs_rate, nbp_rate,
     amendment_flags, or any financial value are ALWAYS classified "restricted".
  2. "restricted" proposals are NEVER auto-applied — they require manual action.
  3. "review" proposals are marked approved but applied_as = "code_change_required".
  4. Only "safe" proposals convert immediately to learning hints on approval.
  5. Proposal capture never raises — all errors are caught and logged.
  6. Store writes are atomic (tmp → rename).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Store path ────────────────────────────────────────────────────────────────

_DEFAULT_STORE_NAME = "parser_fix_proposals.json"


def _get_store_path(store_path=None) -> Path:
    if store_path:
        return Path(store_path)
    # Co-locate with invoice_learning_store.json (respects env var)
    env = os.environ.get("INVOICE_LEARNING_STORE")
    if env:
        return Path(env).parent / _DEFAULT_STORE_NAME
    return Path(__file__).parent / _DEFAULT_STORE_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_store(store_path=None) -> Dict[str, Any]:
    path = _get_store_path(store_path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_store(data: Dict[str, Any], store_path=None) -> None:
    path = _get_store_path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


# ── Risk classification ───────────────────────────────────────────────────────

# Fields that ALWAYS produce "restricted" risk — no exceptions
_RESTRICTED_FIELDS = {
    "duty_pln", "vat_pln", "a00", "b00", "a00_payment_method", "b00_payment_method",
    "customs_rate", "nbp_rate", "amendment_flags", "landed_cost",
    "fob_usd", "freight_usd", "insurance_usd", "cif_usd",
    "unit_price_usd", "total_usd", "total_net", "total_gross",
    "duty_rate", "cif_reconciliation",
}

# Fields that are "review" level (regex or structural change needed)
_REVIEW_FIELDS = {
    "qty_by_type", "invoice_refs", "date_parsing", "item_row",
    "cif_match", "blocked_phrases",
}

# Fields that are "safe" (label/hint only)
_SAFE_FIELDS = {
    "invoice_no", "exporter_name", "invoice_date", "consignee",
    "buyer", "fob_label", "freight_label", "insurance_label",
    "cif_label", "total_pcs", "conv_rate",
}


def _classify_risk(field_missing: str) -> str:
    """Classify risk level based on the field that triggered the proposal."""
    f = field_missing.lower()
    if f in _RESTRICTED_FIELDS or any(r in f for r in ("duty", "vat", "customs", "rate", "cif_reconciliation")):
        return "restricted"
    if f in _REVIEW_FIELDS or any(r in f for r in ("qty", "refs", "blocked", "item_row", "cif_match")):
        return "review"
    return "safe"


# ── Rule suggestion logic ─────────────────────────────────────────────────────

_RULE_SUGGESTIONS: Dict[str, Dict[str, Any]] = {
    "invoice_no": {
        "type": "label_pattern",
        "description": (
            "Search for common invoice number label variants near the top of the document. "
            "Labels to look for: 'Invoice No', 'Invoice No. & Date', 'Inv No', 'Invoice Number', "
            "'Invoice #', 'Ref No'. Extract the alphanumeric token immediately following the label."
        ),
        "label_to_search": "Invoice No|Invoice No. & Date|Inv No|Invoice Number|Invoice #|Ref No",
        "confidence": "medium",
    },
    "exporter_name": {
        "type": "label_pattern",
        "description": (
            "Search for exporter/shipper label block to extract the supplier company name. "
            "Labels to look for: 'Exporter:', 'Merchant Exporter:', 'Shipper:', 'Supplier:', "
            "'Seller:'. Extract the company name on the following line(s)."
        ),
        "label_to_search": "Exporter:|Merchant Exporter:|Shipper:|Supplier:|Seller:",
        "confidence": "medium",
    },
    "cif_usd": {
        "type": "label_pattern",
        "description": (
            "Search for CIF total value label near the invoice summary section. "
            "Labels to look for: 'CIF US$', 'CIF Value', 'Total CIF', 'CIF Amount', "
            "'CIF Total'. Extract the numeric USD value following the label."
        ),
        "label_to_search": "CIF US$|CIF Value|Total CIF|CIF Amount|CIF Total",
        "confidence": "medium",
    },
    "invoice_date": {
        "type": "label_pattern",
        "description": (
            "Search for invoice date label to extract the shipment date. "
            "Labels to look for: 'Date:', 'Invoice Date:', 'Date of Invoice:', 'Dated:'. "
            "Parse the date in DD/MM/YYYY, YYYY-MM-DD, or DD-Mon-YYYY format."
        ),
        "label_to_search": "Date:|Invoice Date:|Date of Invoice:|Dated:",
        "confidence": "medium",
    },
    "qty_by_type": {
        "type": "regex",
        "description": (
            "Add a regex pattern to extract item rows with quantity and item type. "
            "Typical row format: '<qty> <type> @ <price> = <total>'. "
            "Review the raw text snippet to identify the actual column structure, "
            "then write a regex that captures (quantity, item_type, unit_price, line_total)."
        ),
        "regex_pattern": r"(\d+)\s+(rings?|bangles?|earrings?|necklaces?|bracelets?|pendants?)\s+@\s+([\d.]+)",
        "confidence": "low",
    },
    "invoice_refs": {
        "type": "regex",
        "description": (
            "SAD invoice reference numbers could not be matched to parsed invoice numbers. "
            "Review the parsed invoice_no format and the SAD N935 reference format. "
            "Consider normalizing both sides before comparison (strip spaces, leading zeros, "
            "date components). Check if the invoice prefix/suffix convention differs."
        ),
        "regex_pattern": r"",
        "confidence": "low",
    },
    "cif_match": {
        "type": "review",
        "description": (
            "CIF total from invoices does not match the SAD customs value. "
            "Review whether insurance is included/excluded in the SAD figure, "
            "whether a currency conversion is applied at a different rate, "
            "or whether freight is partially included. No automatic rule — requires "
            "manual inspection of the SAD and invoice CIF fields."
        ),
        "confidence": "low",
    },
    "blocked_phrases": {
        "type": "hint",
        "description": (
            "A blocked phrase pattern produced a false positive on this invoice. "
            "Review the BLOCKED_PHRASES_PATTERNS list in pz_import_processor.py to check "
            "if a pattern is too broad and matches legitimate commercial text. "
            "Consider adding a negation condition or narrowing the pattern scope."
        ),
        "confidence": "low",
    },
    "consignee": {
        "type": "label_pattern",
        "description": (
            "Search for consignee/buyer label to extract the importer name. "
            "Labels to look for: 'Consignee:', 'Buyer:', 'Bill To:', 'Importer:'. "
            "Extract the company name on the following line(s)."
        ),
        "label_to_search": "Consignee:|Buyer:|Bill To:|Importer:",
        "confidence": "medium",
    },
}

_DEFAULT_RULE = {
    "type": "hint",
    "description": (
        "Parser could not extract this field. "
        "Manually inspect the raw text snippet to identify the label/pattern. "
        "Add a label_pattern or regex rule once the format is confirmed."
    ),
    "confidence": "low",
}


def _suggest_rule(field_missing: str) -> Dict[str, Any]:
    """Return a suggested_rule dict for the given missing field."""
    key = field_missing.lower()
    suggestion = _RULE_SUGGESTIONS.get(key, _DEFAULT_RULE).copy()
    return suggestion


# ── Proposal ID generation ────────────────────────────────────────────────────

def _make_proposal_id(field_missing: str, failure_reason: str, text_snippet: str) -> str:
    payload = f"{field_missing}|{failure_reason}|{text_snippet[:100]}"
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"prop_{sha}_{ts}"


# ── Public API ────────────────────────────────────────────────────────────────

def capture_proposal(
    field_missing: str,
    failure_reason: str,
    text_snippet: str,
    supplier_key: str = "",
    batch_id: str = "",
    invoice_file: str = "",
    store_path=None,
) -> dict:
    """
    Detect what rule would fix this failure and store a proposal.

    Always non-fatal — callers should catch exceptions, but this function
    tries to never raise.

    Returns the stored proposal dict, or an error dict on failure.
    """
    try:
        data = _load_store(store_path)
        proposals: List[Dict] = data.get("proposals", [])

        # Deduplicate: skip if an identical pending proposal already exists
        # (same field + supplier to avoid noise on repeated runs)
        for existing in proposals:
            if (
                existing.get("field_missing") == field_missing
                and existing.get("supplier_key") == supplier_key
                and existing.get("status") == "pending"
            ):
                return existing

        proposal_id = _make_proposal_id(field_missing, failure_reason, text_snippet)
        risk_level  = _classify_risk(field_missing)
        rule        = _suggest_rule(field_missing)

        proposal: Dict[str, Any] = {
            "proposal_id":     proposal_id,
            "created_at":      _now_iso(),
            "status":          "pending",
            "supplier_key":    supplier_key,
            "batch_id":        batch_id,
            "invoice_file":    invoice_file,
            "field_missing":   field_missing,
            "failure_reason":  failure_reason,
            "text_snippet":    text_snippet[:300],
            "suggested_rule":  rule,
            "risk_level":      risk_level,
            "approved_by":     None,
            "approved_at":     None,
            "applied_as":      None,
            "rejection_reason": None,
        }

        proposals.append(proposal)
        data["proposals"] = proposals
        _save_store(data, store_path)
        return proposal

    except Exception as exc:
        return {"error": str(exc), "field_missing": field_missing}


def get_proposals(status_filter: Optional[str] = None, store_path=None) -> List[Dict]:
    """Return all proposals, optionally filtered by status."""
    data = _load_store(store_path)
    proposals = data.get("proposals", [])
    if status_filter:
        proposals = [p for p in proposals if p.get("status") == status_filter]
    # Newest first
    return sorted(proposals, key=lambda p: p.get("created_at", ""), reverse=True)


def get_proposal(proposal_id: str, store_path=None) -> Optional[Dict]:
    """Return a single proposal by ID, or None if not found."""
    for p in get_proposals(store_path=store_path):
        if p.get("proposal_id") == proposal_id:
            return p
    return None


def approve_proposal(proposal_id: str, store_path=None) -> dict:
    """
    Approve a proposal.

    - safe proposals → convert to invoice_learning_agent hint immediately
      (applied_as = "learning_hint")
    - review/restricted proposals → mark approved but applied_as = "code_change_required"
      (no automatic code change)

    Returns result dict with outcome details.
    """
    data = _load_store(store_path)
    proposals: List[Dict] = data.get("proposals", [])

    proposal = next((p for p in proposals if p.get("proposal_id") == proposal_id), None)
    if proposal is None:
        return {"error": f"Proposal '{proposal_id}' not found", "approved": False}

    if proposal["status"] != "pending":
        return {
            "error": f"Proposal is already '{proposal['status']}' — cannot approve",
            "approved": False,
        }

    risk = proposal.get("risk_level", "review")
    now  = _now_iso()

    proposal["approved_by"] = "admin"
    proposal["approved_at"] = now
    proposal["status"]      = "approved"

    applied_as = None
    hint_result = None

    if risk == "safe":
        # Convert immediately to a learning hint
        hint_result = _apply_as_learning_hint(proposal, store_path)
        if hint_result.get("success"):
            proposal["status"]     = "applied"
            proposal["applied_as"] = "learning_hint"
            applied_as = "learning_hint"
        else:
            # Hint injection failed — still mark approved but require manual step
            proposal["applied_as"] = "code_change_required"
            applied_as = "code_change_required"
    else:
        # review or restricted — mark but do not auto-apply
        proposal["applied_as"] = "code_change_required"
        applied_as = "code_change_required"

    data["proposals"] = proposals
    _save_store(data, store_path)

    return {
        "approved":    True,
        "proposal_id": proposal_id,
        "risk_level":  risk,
        "applied_as":  applied_as,
        "hint_result": hint_result,
        "note": (
            "Applied as learning hint immediately."
            if applied_as == "learning_hint"
            else "Marked approved — manual code review step required before this can be applied."
        ),
    }


def reject_proposal(proposal_id: str, reason: str = "", store_path=None) -> dict:
    """Reject a proposal."""
    data = _load_store(store_path)
    proposals: List[Dict] = data.get("proposals", [])

    proposal = next((p for p in proposals if p.get("proposal_id") == proposal_id), None)
    if proposal is None:
        return {"error": f"Proposal '{proposal_id}' not found", "rejected": False}

    if proposal["status"] not in ("pending", "approved"):
        return {
            "error": f"Proposal is already '{proposal['status']}' — cannot reject",
            "rejected": False,
        }

    proposal["status"]           = "rejected"
    proposal["rejection_reason"] = reason or "No reason given"

    data["proposals"] = proposals
    _save_store(data, store_path)

    return {
        "rejected":    True,
        "proposal_id": proposal_id,
        "reason":      proposal["rejection_reason"],
    }


def get_proposal_summary(store_path=None) -> dict:
    """Return counts by status and risk_level."""
    proposals = get_proposals(store_path=store_path)

    by_status: Dict[str, int] = {}
    by_risk:   Dict[str, int] = {}

    for p in proposals:
        s = p.get("status", "unknown")
        r = p.get("risk_level", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        by_risk[r]   = by_risk.get(r, 0) + 1

    return {
        "total":     len(proposals),
        "by_status": by_status,
        "by_risk":   by_risk,
        "pending":   by_status.get("pending", 0),
        "approved":  by_status.get("approved", 0),
        "applied":   by_status.get("applied", 0),
        "rejected":  by_status.get("rejected", 0),
    }


# ── Learning hint injection ───────────────────────────────────────────────────

def _apply_as_learning_hint(proposal: Dict[str, Any], store_path=None) -> dict:
    """
    Convert an approved safe proposal into a learning hint.

    Injects the suggested label into the invoice_learning_store.json for the
    affected supplier, using the same store I/O as invoice_learning_agent.

    Only modifies label fields — never financial values.
    Returns {"success": True/False, "note": "..."}.
    """
    try:
        import invoice_learning_agent as ila
    except ImportError:
        return {"success": False, "note": "invoice_learning_agent not available"}

    supplier_key = proposal.get("supplier_key", "")
    if not supplier_key:
        return {"success": False, "note": "No supplier_key — cannot inject hint"}

    field   = proposal.get("field_missing", "")
    rule    = proposal.get("suggested_rule", {})
    rule_t  = rule.get("type", "")

    # Safety guard: never touch financial/restricted fields via this path
    if _classify_risk(field) != "safe":
        return {"success": False, "note": "Risk level is not safe — hint injection skipped"}

    # Map field_missing → learnable label field key
    _FIELD_TO_LABEL = {
        "invoice_no":    "invoice_no_label",
        "exporter_name": "exporter_label",
        "invoice_date":  "invoice_date_label",
        "consignee":     "consignee_label",
        "buyer":         "buyer_label",
        "fob_label":     "fob_label",
        "freight_label": "freight_label",
        "cif_label":     "cif_label",
    }
    label_key = _FIELD_TO_LABEL.get(field)
    if not label_key:
        return {"success": False, "note": f"No learnable label mapping for field '{field}'"}

    if rule_t != "label_pattern":
        return {"success": False, "note": f"Rule type '{rule_t}' is not label_pattern — skipping hint"}

    label_value = rule.get("label_to_search", "").split("|")[0].strip()
    if not label_value:
        return {"success": False, "note": "No label_to_search in suggested_rule"}

    # Load learning store and inject the hint pattern
    try:
        learning_store_env = os.environ.get("INVOICE_LEARNING_STORE")
        learn_store_path   = Path(learning_store_env) if learning_store_env else None

        store = ila.load_store(learn_store_path)

        if supplier_key not in store:
            # Bootstrap a minimal entry so the hint has a home
            store[supplier_key] = {
                "supplier_key":    supplier_key,
                "display_name":    supplier_key.replace("_", " ").title(),
                "confirmed_count": 0,
                "confidence":      "unconfirmed",
                "first_seen":      _now_iso(),
                "last_seen":       _now_iso(),
                "parse_count":     0,
                "failed_count":    0,
                "layouts":         {},
                "_proposal_hints": {},
            }

        entry = store[supplier_key]
        # Store the hint in a dedicated _proposal_hints section (separate from layouts)
        # so it can be reviewed/reverted without touching confirmed pattern data
        hints_section = entry.setdefault("_proposal_hints", {})
        hints_section[label_key] = {
            "value":       label_value,
            "from_proposal": proposal.get("proposal_id"),
            "applied_at":  _now_iso(),
            "risk_level":  "safe",
        }
        entry["last_seen"] = _now_iso()

        ila.save_store(store, learn_store_path)

        return {
            "success":    True,
            "note":       f"Injected hint: {label_key} = '{label_value}' for supplier '{supplier_key}'",
            "label_key":  label_key,
            "label_value": label_value,
        }

    except Exception as exc:
        return {"success": False, "note": f"Hint injection error: {exc}"}

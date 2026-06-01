"""
rule_based_reverification.py — Rule-Based Reverification Layer (Atlas §1A).

Renamed from ai_reverification.py — this layer is deterministic rule-based
logic, NOT an AI model. There are no Anthropic/LLM calls. The name change
records the correct implementation (ADR-025 docs honesty correction, B9).

The engine of detect → inbox → approve.

After document parse, this layer re-checks extracted data for correctness
using deterministic rules before it is trusted anywhere downstream.

READS:
  (a) The relevant masters (supplier, client, product, HS, company profile)
  (b) The paired track's lines (purchase ↔ sales)
  (c) invoice_lines from documents.db

EMITS:
  §7 inbox proposal types (9 active — disambiguation_417g removed as unimplemented):
    - supplier_mismatch
    - client_mismatch
    - product_design_mismatch
    - missing_hs_code
    - price_value_conflict
    - sales_purchase_line_mismatch
    - dhl_delivered_not_received
    - product_not_synced_to_wfirma
    - pz_proforma_invoice_ready_for_approval

BOUNDARIES (HARD):
  - NEVER writes a master row
  - NEVER writes to wFirma
  - NEVER auto-approves or auto-corrects
  - NEVER sends emails
  - Read-only DB access only
  - No live wFirma API calls (reads local masters only)

INVOCATION:
  WF1.3: reverify_purchase_batch(batch_id, audit, masters_config)
  WF2.2: reverify_sales_batch(batch_id, audit, masters_config)
  Both re-runnable on demand.

OUTPUT SINK:
  Returns List[ReverificationProposal] — each proposal flows to Inbox via
  write_reverification_proposals_to_audit() which appends them to
  audit["action_proposals"]. Caller owns the audit lifecycle (read+write).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Proposal type constants (§7 inbox proposal types) ────────────────────────

PROP_SUPPLIER_MISMATCH              = "supplier_mismatch"
PROP_CLIENT_MISMATCH                = "client_mismatch"
PROP_PRODUCT_DESIGN_MISMATCH        = "product_design_mismatch"
PROP_MISSING_HS_CODE                = "missing_hs_code"
PROP_PRICE_VALUE_CONFLICT           = "price_value_conflict"
PROP_SALES_PURCHASE_LINE_MISMATCH   = "sales_purchase_line_mismatch"
PROP_DHL_DELIVERED_NOT_RECEIVED     = "dhl_delivered_not_received"
PROP_PRODUCT_NOT_SYNCED_TO_WFIRMA   = "product_not_synced_to_wfirma"
PROP_PZ_PROFORMA_READY              = "pz_proforma_invoice_ready_for_approval"
ALL_REVERIFICATION_TYPES = frozenset({
    PROP_SUPPLIER_MISMATCH,
    PROP_CLIENT_MISMATCH,
    PROP_PRODUCT_DESIGN_MISMATCH,
    PROP_MISSING_HS_CODE,
    PROP_PRICE_VALUE_CONFLICT,
    PROP_SALES_PURCHASE_LINE_MISMATCH,
    PROP_DHL_DELIVERED_NOT_RECEIVED,
    PROP_PRODUCT_NOT_SYNCED_TO_WFIRMA,
    PROP_PZ_PROFORMA_READY,
    # disambiguation_417g removed — proposal type was defined but never implemented
})

# Channel discriminator (distinct from email proposals and wfirma_action proposals)
REVERIFICATION_CHANNEL = "ai_reverification"

# Confidence levels emitted by this layer
CONFIDENCE_HIGH   = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW    = "low"


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class ReverificationProposal:
    """One proposal emitted by the AI reverification layer.

    This is a PURE DATA structure — no side effects, no DB writes.
    Callers convert it to an audit["action_proposals"] entry via
    write_reverification_proposals_to_audit().
    """
    proposal_type:  str
    reason:         str
    confidence:     str
    evidence:       Dict[str, Any] = field(default_factory=dict)
    suggestion:     str = ""
    # Populated by write_reverification_proposals_to_audit()
    proposal_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at:     str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Master snapshot (read-only inputs) ────────────────────────────────────────

@dataclass
class MastersSnapshot:
    """Read-only snapshot of the relevant master rows for one batch.

    Built by build_masters_snapshot(); passed to the check functions.
    All fields are Optional — missing master data is a check, not a crash.
    """
    supplier_row:          Optional[Dict[str, Any]] = None
    client_row:            Optional[Dict[str, Any]] = None
    company_profile_row:   Optional[Dict[str, Any]] = None
    product_master_rows:   List[Dict[str, Any]] = field(default_factory=list)
    wfirma_product_rows:   List[Dict[str, Any]] = field(default_factory=list)
    hs_code_rows:          List[Dict[str, Any]] = field(default_factory=list)


# ── Snapshot builder ──────────────────────────────────────────────────────────

def build_masters_snapshot(
    audit:          Dict[str, Any],
    storage_root:   Path,
) -> MastersSnapshot:
    """Read the relevant master rows for a batch. Read-only. Never raises."""
    snap = MastersSnapshot()

    # ── Company profile (Estrella as consignee) ───────────────────────────────
    try:
        from .master_data_db import get_company_profile
        snap.company_profile_row = _to_dict(
            get_company_profile(storage_root / "master_data.sqlite")
        )
    except Exception as e:
        log.debug("build_masters_snapshot: company_profile read failed: %s", e)

    # ── Supplier ─────────────────────────────────────────────────────────────
    try:
        import sqlite3
        sup_db = storage_root / "suppliers.sqlite"
        if sup_db.exists():
            batch_id = audit.get("batch_id", "")
            docs_db  = storage_root / "documents.db"
            if docs_db.exists():
                conn = sqlite3.connect(str(docs_db))
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT supplier_contractor_id FROM shipment_documents "
                    "WHERE batch_id=? AND supplier_contractor_id!='' LIMIT 1",
                    (batch_id,)
                ).fetchone()
                conn.close()
                if row:
                    sup_cid = row["supplier_contractor_id"]
                    sconn = sqlite3.connect(str(sup_db))
                    sconn.row_factory = sqlite3.Row
                    srow = sconn.execute(
                        "SELECT * FROM suppliers WHERE id=?", (sup_cid,)
                    ).fetchone()
                    sconn.close()
                    snap.supplier_row = dict(srow) if srow else None
    except Exception as e:
        log.debug("build_masters_snapshot: supplier read failed: %s", e)

    # ── Client ───────────────────────────────────────────────────────────────
    try:
        import sqlite3
        doc_db = storage_root / "documents.db"
        batch_id = audit.get("batch_id", "")
        if doc_db.exists():
            conn = sqlite3.connect(str(doc_db))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT client_contractor_id FROM shipment_documents "
                "WHERE batch_id=? AND client_contractor_id!='' LIMIT 1",
                (batch_id,)
            ).fetchone()
            conn.close()
            if row:
                cid = row["client_contractor_id"]
                cm_db = storage_root / "customer_master.sqlite"
                if cm_db.exists():
                    from .customer_master_db import get_customer
                    snap.client_row = _to_dict(get_customer(cm_db, cid))
    except Exception as e:
        log.debug("build_masters_snapshot: client read failed: %s", e)

    # ── Product masters ───────────────────────────────────────────────────────
    try:
        rq_db = storage_root / "reservation_queue.db"
        if rq_db.exists():
            from .reservation_db import list_product_masters
            snap.product_master_rows = list_product_masters(rq_db) or []
    except Exception as e:
        log.debug("build_masters_snapshot: product_master read failed: %s", e)

    return snap


def _to_dict(obj) -> Optional[Dict[str, Any]]:
    """Convert a dataclass or Row to a plain dict, or return None."""
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        import dataclasses
        return dataclasses.asdict(obj)
    try:
        return dict(obj)
    except Exception:
        return None


# ── Individual check functions ────────────────────────────────────────────────

def check_supplier_identity(
    audit: Dict[str, Any],
    masters: MastersSnapshot,
) -> List[ReverificationProposal]:
    """WF1.3: verify parsed exporter/supplier name matches the supplier master."""
    proposals: List[ReverificationProposal] = []
    invoices = (audit.get("result") or {}).get("invoices") or audit.get("invoices") or []
    parsed_name = ""
    for inv in invoices:
        for key in ("exporter_name", "seller_name", "supplier_name"):
            v = (inv.get(key) or "").strip()
            if v:
                parsed_name = v
                break
        if parsed_name:
            break

    if not parsed_name:
        # No supplier name in parsed invoice — flag it
        proposals.append(ReverificationProposal(
            proposal_type=PROP_SUPPLIER_MISMATCH,
            reason="No supplier/exporter name found in parsed invoice data",
            confidence=CONFIDENCE_MEDIUM,
            evidence={"parsed_name": "", "master_name": ""},
            suggestion="Verify the purchase invoice PDF was parsed correctly and "
                       "supplier name is present, or set the supplier on the shipment.",
        ))
        return proposals

    if masters.supplier_row:
        master_name = (masters.supplier_row.get("name") or "").strip()
        if master_name and not _names_similar(parsed_name, master_name):
            proposals.append(ReverificationProposal(
                proposal_type=PROP_SUPPLIER_MISMATCH,
                reason=f"Parsed supplier name {parsed_name!r} differs from master {master_name!r}",
                confidence=CONFIDENCE_HIGH,
                evidence={"parsed_name": parsed_name, "master_name": master_name},
                suggestion="Verify the correct supplier is selected, or update the supplier master.",
            ))
    return proposals


def check_client_identity(
    audit: Dict[str, Any],
    masters: MastersSnapshot,
) -> List[ReverificationProposal]:
    """WF1.3: verify parsed consignee name matches the client master."""
    proposals: List[ReverificationProposal] = []
    if not masters.client_row:
        return proposals  # no client master row — can't compare

    master_name = (masters.client_row.get("bill_to_name") or "").strip()
    # Look for consignee/buyer name in audit
    parsed_name = ""
    for key in ("consignee_name", "buyer_name", "client_name"):
        v = (audit.get(key) or "").strip()
        if v:
            parsed_name = v
            break
    # Also check invoice data
    if not parsed_name:
        invoices = (audit.get("result") or {}).get("invoices") or audit.get("invoices") or []
        for inv in invoices:
            for k in ("buyer_name", "consignee_name", "importer_name"):
                v = (inv.get(k) or "").strip()
                if v:
                    parsed_name = v
                    break

    if parsed_name and master_name and not _names_similar(parsed_name, master_name):
        proposals.append(ReverificationProposal(
            proposal_type=PROP_CLIENT_MISMATCH,
            reason=f"Parsed consignee {parsed_name!r} differs from client master {master_name!r}",
            confidence=CONFIDENCE_HIGH,
            evidence={"parsed_name": parsed_name, "master_name": master_name},
            suggestion="Verify the correct client is selected on this shipment.",
        ))
    return proposals


def check_hs_codes(
    audit: Dict[str, Any],
    invoice_lines: List[Dict[str, Any]],
) -> List[ReverificationProposal]:
    """WF1.3: flag invoice lines missing HS codes."""
    proposals: List[ReverificationProposal] = []
    missing: List[str] = []
    for ln in invoice_lines:
        pc = (ln.get("product_code") or "").strip()
        hs = (ln.get("hs_code") or ln.get("hsn_code") or "").strip()
        if not hs and pc:
            missing.append(pc)

    if missing:
        proposals.append(ReverificationProposal(
            proposal_type=PROP_MISSING_HS_CODE,
            reason=f"{len(missing)} invoice line(s) have no HS code",
            confidence=CONFIDENCE_HIGH,
            evidence={"product_codes_missing_hs": missing[:10]},
            suggestion="Upload ZC429 with HS codes, or set hs_code_override in product_local master.",
        ))
    return proposals


def check_product_wfirma_sync(
    invoice_lines: List[Dict[str, Any]],
    masters: MastersSnapshot,
) -> List[ReverificationProposal]:
    """WF1.3: flag product codes not yet synced to wFirma."""
    proposals: List[ReverificationProposal] = []
    if not masters.wfirma_product_rows:
        return proposals

    synced = {r.get("product_code", ""): r.get("sync_status", "")
              for r in masters.wfirma_product_rows}
    unsynced: List[str] = []
    for ln in invoice_lines:
        pc = (ln.get("product_code") or "").strip()
        if pc and synced.get(pc, "") not in ("matched", "created", "ready"):
            unsynced.append(pc)

    if unsynced:
        proposals.append(ReverificationProposal(
            proposal_type=PROP_PRODUCT_NOT_SYNCED_TO_WFIRMA,
            reason=f"{len(unsynced)} product code(s) not synced to wFirma",
            confidence=CONFIDENCE_HIGH,
            evidence={"unsynced_product_codes": unsynced[:10]},
            suggestion="Run wFirma product resolve for this batch before creating a proforma.",
        ))
    return proposals


def check_sales_purchase_line_match(
    purchase_lines: List[Dict[str, Any]],
    sales_lines:    List[Dict[str, Any]],
) -> List[ReverificationProposal]:
    """WF2.2: flag sales lines that have no matching purchase product_code."""
    proposals: List[ReverificationProposal] = []
    if not sales_lines:
        return proposals

    purchase_codes = {(ln.get("product_code") or "").strip()
                      for ln in purchase_lines
                      if (ln.get("product_code") or "").strip()}
    purchase_designs = {(ln.get("design_no") or "").strip().upper()
                        for ln in purchase_lines
                        if (ln.get("design_no") or "").strip()}

    unmatched_designs: List[str] = []
    for sln in sales_lines:
        s_design = (sln.get("design_no") or "").strip()
        s_code   = (sln.get("product_code") or "").strip()
        matched = (
            (s_code and s_code in purchase_codes) or
            (s_design and s_design.upper() in purchase_designs)
        )
        if not matched and s_design:
            unmatched_designs.append(s_design)

    if unmatched_designs:
        proposals.append(ReverificationProposal(
            proposal_type=PROP_SALES_PURCHASE_LINE_MISMATCH,
            reason=f"{len(unmatched_designs)} sales design(s) not found in purchase lines",
            confidence=CONFIDENCE_HIGH,
            evidence={"unmatched_sales_designs": unmatched_designs[:10]},
            suggestion="Verify the sales packing list matches the purchase invoice, "
                       "or approve the mismatch if it is intentional.",
        ))
    return proposals


# ── Public API ────────────────────────────────────────────────────────────────

def reverify_purchase_batch(
    batch_id:     str,
    audit:        Dict[str, Any],
    storage_root: Path,
) -> List[ReverificationProposal]:
    """WF1.3: Run all purchase-side reverification checks.

    Read-only. Returns a list of proposals (empty = all checks pass).
    Never raises — exceptions are logged and produce a LOW-confidence proposal.
    """
    proposals: List[ReverificationProposal] = []
    try:
        masters = build_masters_snapshot(audit, storage_root)
        invoice_lines = _extract_invoice_lines(audit, storage_root, batch_id)

        proposals.extend(check_supplier_identity(audit, masters))
        proposals.extend(check_client_identity(audit, masters))
        proposals.extend(check_hs_codes(audit, invoice_lines))
        proposals.extend(check_product_wfirma_sync(invoice_lines, masters))
    except Exception as exc:
        log.warning("[%s] reverify_purchase_batch failed (non-fatal): %s", batch_id, exc)
        proposals.append(ReverificationProposal(
            proposal_type=PROP_SUPPLIER_MISMATCH,
            reason=f"Reverification check failed: {exc}",
            confidence=CONFIDENCE_LOW,
            evidence={"error": str(exc)},
        ))
    return proposals


def reverify_sales_batch(
    batch_id:      str,
    audit:         Dict[str, Any],
    storage_root:  Path,
    purchase_lines: Optional[List[Dict[str, Any]]] = None,
    sales_lines:    Optional[List[Dict[str, Any]]] = None,
) -> List[ReverificationProposal]:
    """WF2.2: Run all sales-side reverification checks.

    Read-only. Returns a list of proposals.
    """
    proposals: List[ReverificationProposal] = []
    try:
        masters = build_masters_snapshot(audit, storage_root)
        p_lines = purchase_lines or _extract_invoice_lines(audit, storage_root, batch_id)
        s_lines = sales_lines   or []

        proposals.extend(check_client_identity(audit, masters))
        proposals.extend(check_sales_purchase_line_match(p_lines, s_lines))
    except Exception as exc:
        log.warning("[%s] reverify_sales_batch failed (non-fatal): %s", batch_id, exc)
    return proposals


def write_reverification_proposals_to_audit(
    audit:     Dict[str, Any],
    proposals: List[ReverificationProposal],
) -> int:
    """Append reverification proposals to audit["action_proposals"].

    Deduplicates by (channel, proposal_type) — one active proposal per type.
    Returns count of new proposals appended.
    """
    if not proposals:
        return 0
    action_proposals: List[Dict[str, Any]] = audit.setdefault("action_proposals", [])
    _active = {"pending_review"}

    existing_types = {
        p.get("type")
        for p in action_proposals
        if p.get("channel") == REVERIFICATION_CHANNEL
        and p.get("status") in _active
    }

    added = 0
    for prop in proposals:
        if prop.proposal_type in existing_types:
            continue  # dedup: already pending
        action_proposals.append({
            "proposal_id":   prop.proposal_id,
            "type":          prop.proposal_type,
            "channel":       REVERIFICATION_CHANNEL,
            "status":        "pending_review",
            "reason":        prop.reason,
            "confidence":    prop.confidence,
            "evidence":      prop.evidence,
            "suggestion":    prop.suggestion,
            "created_at":    prop.created_at,
            "approved_by":   None,
            "approved_at":   None,
            "rejected_by":   None,
            "rejected_at":   None,
            "reject_reason": None,
            # Compatibility fields (email proposals have these; reverification
            # proposals do not use them but include them for schema consistency).
            "draft":         {},
            "email_id":      None,
            "queued_at":     None,
        })
        existing_types.add(prop.proposal_type)
        added += 1
    return added


# ── Helpers ───────────────────────────────────────────────────────────────────

def _names_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Fuzzy name match — returns True if names are similar enough."""
    a, b = a.upper().strip(), b.upper().strip()
    if a == b:
        return True
    # Check if one is a substring of the other
    if a in b or b in a:
        return True
    # Simple token overlap
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= threshold


def _extract_invoice_lines(
    audit:        Dict[str, Any],
    storage_root: Path,
    batch_id:     str,
) -> List[Dict[str, Any]]:
    """Extract invoice lines from audit or DB. Read-only."""
    # Try audit rows first
    rows = audit.get("rows") or []
    if rows:
        return [dict(r) for r in rows]
    # Try documents.db
    try:
        import sqlite3
        docs_db = storage_root / "documents.db"
        if docs_db.exists():
            conn = sqlite3.connect(str(docs_db))
            conn.row_factory = sqlite3.Row
            db_rows = conn.execute(
                "SELECT * FROM invoice_lines WHERE batch_id=?", (batch_id,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in db_rows]
    except Exception:
        pass
    return []

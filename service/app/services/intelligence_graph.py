"""
intelligence_graph.py -- Phase 8 Sprint 1: batch_id-centered Relationship Resolver.

batch_id is the universal hub. All four builders accept batch_id and return a
GraphResult that connects tracking events, document metadata, customer master,
supplier registry, invoice lines, and customs declarations into a single
authority-attributed graph.

Design rules (enforced by source-grep tests):
  - llm_used = False  (structural invariant -- never set True)
  - All DB connections via _ro_conn() with PRAGMA query_only = ON
  - No DB writes of any kind (read-only at PRAGMA level)
  - No external HTTP, no wFirma writes, no DHL calls
  - Conflict exposure: when two sources disagree, expose both (never pick winner)
  - Null + link_completeness for every unresolvable field (never infer)

Public API (Sprint 1)
---------------------
build_awb_graph(batch_id)      -> GraphResult  # AWB + tracking events
build_batch_graph(batch_id)    -> GraphResult  # full cross-DB graph
build_customer_graph(batch_id) -> GraphResult  # customer + contractor resolution
build_invoice_graph(batch_id)  -> GraphResult  # invoice lines + customs + PZ

All DB paths are injectable (keyword args) for test isolation.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── DB paths (read-only; all injectable for tests) ────────────────────────────

_DOC_DB      = settings.storage_root / "documents.db"
_TRACKING_DB = settings.storage_root / "tracking_events.db"
_CM_DB       = settings.storage_root / "customer_master.sqlite"
_SUPP_DB     = settings.storage_root / "suppliers.sqlite"
_MD_DB       = settings.storage_root / "master_data.sqlite"

# ── Constants ─────────────────────────────────────────────────────────────────

_BUILDER_AWB      = "build_awb_graph"
_BUILDER_BATCH    = "build_batch_graph"
_BUILDER_CUSTOMER = "build_customer_graph"
_BUILDER_INVOICE  = "build_invoice_graph"


# ── Read-only connection ──────────────────────────────────────────────────────

def _ro_conn(db_path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection (PRAGMA query_only = ON)."""
    con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class AttributedValue:
    """A resolved field value with its authority source table."""
    value: Optional[str]
    authority: str  # e.g. "shipment_documents", "customer_master"


@dataclass
class LinkCompleteness:
    """Honest gap report: which relationships were resolved and which are missing."""
    awb_linked:      bool = False
    tracking_linked: bool = False
    customer_linked: bool = False
    supplier_linked: bool = False
    invoice_linked:  bool = False
    customs_linked:  bool = False
    missing:         List[str] = field(default_factory=list)

    def _compute_missing(self) -> None:
        """Populate missing list from boolean flags. Called by builders after filling."""
        m: List[str] = []
        if not self.awb_linked:
            m.append("awb")
        if not self.tracking_linked:
            m.append("tracking")
        if not self.customer_linked:
            m.append("customer")
        if not self.supplier_linked:
            m.append("supplier")
        if not self.invoice_linked:
            m.append("invoice")
        if not self.customs_linked:
            m.append("customs")
        self.missing = m


@dataclass
class GraphResult:
    """
    Authority-attributed graph anchored on batch_id.

    Conflict fields: if two sources disagree, the primary source wins
    and the secondary is exposed as {field}_conflict. Never choose a
    winner silently -- expose both.

    All fields are Optional. Unresolvable fields are None + listed in
    link_completeness.missing. Never infer or fabricate a value.
    """
    batch_id:   str
    llm_used:   bool   # always False -- structural invariant
    built_at:   str
    builder:    str    # which builder function produced this result

    # ── Core attributed fields ────────────────────────────────────────────────
    awb:                Optional[AttributedValue] = None
    awb_conflict:       Optional[AttributedValue] = None   # set when sources disagree

    customer:           Optional[AttributedValue] = None   # primary (customer_master)
    customer_conflict:  Optional[AttributedValue] = None   # set when docs disagree

    supplier:           Optional[AttributedValue] = None   # via supplier_contractor_id
    supplier_code:      Optional[AttributedValue] = None   # canonical code from registry

    invoice_ref:        Optional[AttributedValue] = None   # related_invoice_no from docs
    invoice_line_count: int = 0

    mrn:                Optional[AttributedValue] = None   # customs declaration MRN
    pz_ref:             Optional[AttributedValue] = None   # related_pz_no from docs

    # ── Tracking summary ──────────────────────────────────────────────────────
    tracking_event_count:      int = 0
    tracking_latest_stage:     Optional[str] = None
    tracking_has_manual_review: bool = False

    # ── Gap reporting ─────────────────────────────────────────────────────────
    link_completeness: LinkCompleteness = field(default_factory=LinkCompleteness)
    conflict_keys:     List[str] = field(default_factory=list)  # fields with conflicts

    def to_dict(self) -> Dict[str, Any]:
        """Serialise GraphResult to a plain dict suitable for JSONResponse."""
        def _av(av: Optional[AttributedValue]) -> Optional[Dict[str, Any]]:
            if av is None:
                return None
            return {"value": av.value, "authority": av.authority}

        lc = self.link_completeness
        return {
            "batch_id":   self.batch_id,
            "llm_used":   self.llm_used,
            "built_at":   self.built_at,
            "builder":    self.builder,
            "awb":                _av(self.awb),
            "awb_conflict":       _av(self.awb_conflict),
            "customer":           _av(self.customer),
            "customer_conflict":  _av(self.customer_conflict),
            "supplier":           _av(self.supplier),
            "supplier_code":      _av(self.supplier_code),
            "invoice_ref":        _av(self.invoice_ref),
            "invoice_line_count": self.invoice_line_count,
            "mrn":    _av(self.mrn),
            "pz_ref": _av(self.pz_ref),
            "tracking_event_count":       self.tracking_event_count,
            "tracking_latest_stage":      self.tracking_latest_stage,
            "tracking_has_manual_review": self.tracking_has_manual_review,
            "link_completeness": {
                "awb_linked":      lc.awb_linked,
                "tracking_linked": lc.tracking_linked,
                "customer_linked": lc.customer_linked,
                "supplier_linked": lc.supplier_linked,
                "invoice_linked":  lc.invoice_linked,
                "customs_linked":  lc.customs_linked,
                "missing":         lc.missing,
            },
            "conflict_keys": self.conflict_keys,
        }


# ── Private resolution helpers ────────────────────────────────────────────────


def _resolve_awb_from_docs(
    batch_id: str,
    db_path:  Path,
) -> Optional[AttributedValue]:
    """
    Read the first non-empty AWB from shipment_documents for this batch.
    Returns None if DB missing, batch not found, or awb is blank.
    """
    if not db_path.exists():
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            "SELECT awb FROM shipment_documents WHERE batch_id = ? AND awb != '' LIMIT 1",
            (batch_id,),
        ).fetchone()
        con.close()
        if row:
            return AttributedValue(value=row["awb"], authority="shipment_documents")
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_awb_from_docs: %s", exc)
    return None


def _resolve_awb_from_tracking(
    batch_id: str,
    db_path:  Path,
) -> Optional[AttributedValue]:
    """
    Read the most recent AWB from shipment_tracking_events for this batch.
    Returns None if DB missing or batch has no events.
    """
    if not db_path.exists():
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            """
            SELECT awb FROM shipment_tracking_events
            WHERE batch_id = ? AND awb != ''
            ORDER BY event_time DESC LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
        con.close()
        if row:
            return AttributedValue(value=row["awb"], authority="shipment_tracking_events")
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_awb_from_tracking: %s", exc)
    return None


def _resolve_tracking_summary(
    batch_id: str,
    db_path:  Path,
) -> Dict[str, Any]:
    """
    Return aggregated tracking stats for a batch: event_count, latest_stage,
    has_manual_review. Returns zeros/None if DB missing or no events.
    """
    out: Dict[str, Any] = {
        "event_count":        0,
        "latest_stage":       None,
        "has_manual_review":  False,
    }
    if not db_path.exists():
        return out
    try:
        con = _ro_conn(db_path)
        agg = con.execute(
            """
            SELECT
                COUNT(*)                                  AS event_count,
                MAX(event_time)                           AS latest_event_time,
                SUM(requires_manual_review)               AS manual_review_sum
            FROM shipment_tracking_events
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if agg and agg["event_count"]:
            out["event_count"] = agg["event_count"]
            out["has_manual_review"] = bool(agg["manual_review_sum"])
            # Fetch stage for the latest event
            stage_row = con.execute(
                """
                SELECT normalized_stage, stage FROM shipment_tracking_events
                WHERE batch_id = ?
                ORDER BY event_time DESC LIMIT 1
                """,
                (batch_id,),
            ).fetchone()
            if stage_row:
                out["latest_stage"] = stage_row["normalized_stage"] or stage_row["stage"] or None
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_tracking_summary: %s", exc)
    return out


def _resolve_client_contractor_ids(
    batch_id: str,
    db_path:  Path,
) -> List[str]:
    """
    Return distinct non-empty client_contractor_ids from shipment_documents
    for this batch. Normally just one; more than one indicates a conflict.
    """
    if not db_path.exists():
        return []
    try:
        con = _ro_conn(db_path)
        rows = con.execute(
            """
            SELECT DISTINCT client_contractor_id
            FROM shipment_documents
            WHERE batch_id = ? AND client_contractor_id != ''
            """,
            (batch_id,),
        ).fetchall()
        con.close()
        return [r["client_contractor_id"] for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_client_contractor_ids: %s", exc)
    return []


def _resolve_supplier_contractor_id(
    batch_id: str,
    db_path:  Path,
) -> Optional[str]:
    """
    Read the first non-empty supplier_contractor_id from shipment_documents.
    Returns None if not found.
    """
    if not db_path.exists():
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            """
            SELECT supplier_contractor_id
            FROM shipment_documents
            WHERE batch_id = ? AND supplier_contractor_id != ''
            LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
        con.close()
        if row:
            return row["supplier_contractor_id"]
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_supplier_contractor_id: %s", exc)
    return None


def _resolve_customer_from_master(
    contractor_id: str,
    db_path:       Path,
) -> Optional[AttributedValue]:
    """
    Look up customer name + country in customer_master by bill_to_contractor_id.
    Returns None if DB missing or no match.
    """
    if not db_path.exists() or not contractor_id:
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            """
            SELECT bill_to_name, country, nip
            FROM customer_master
            WHERE bill_to_contractor_id = ?
            LIMIT 1
            """,
            (contractor_id,),
        ).fetchone()
        con.close()
        if row and row["bill_to_name"]:
            parts = [row["bill_to_name"]]
            if row["country"]:
                parts.append(row["country"])
            return AttributedValue(
                value=", ".join(parts),
                authority="customer_master",
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_customer_from_master: %s", exc)
    return None


def _resolve_supplier_from_registry(
    contractor_id: str,
    db_path:       Path,
) -> Optional[AttributedValue]:
    """
    Look up supplier name in suppliers.sqlite by wfirma_id = contractor_id.
    Falls back to any supplier if wfirma_id column is absent.
    Returns None if not found.
    """
    if not db_path.exists() or not contractor_id:
        return None
    try:
        con = _ro_conn(db_path)
        # Try wfirma_id first (added in B0 enrichment)
        try:
            row = con.execute(
                "SELECT supplier_code, name FROM suppliers WHERE wfirma_id = ? LIMIT 1",
                (contractor_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # wfirma_id column not present in older DBs
            row = None
        con.close()
        if row and row["name"]:
            return AttributedValue(
                value=row["name"],
                authority="suppliers",
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_supplier_from_registry: %s", exc)
    return None


def _resolve_supplier_code_from_registry(
    contractor_id: str,
    db_path:       Path,
) -> Optional[AttributedValue]:
    """Return canonical supplier_code for a wfirma_id contractor."""
    if not db_path.exists() or not contractor_id:
        return None
    try:
        con = _ro_conn(db_path)
        try:
            row = con.execute(
                "SELECT supplier_code FROM suppliers WHERE wfirma_id = ? LIMIT 1",
                (contractor_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        con.close()
        if row and row["supplier_code"]:
            return AttributedValue(
                value=row["supplier_code"],
                authority="suppliers",
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_supplier_code_from_registry: %s", exc)
    return None


def _resolve_doc_refs(
    batch_id: str,
    db_path:  Path,
) -> Dict[str, Optional[str]]:
    """
    Read related_invoice_no, related_mrn, related_pz_no from shipment_documents.
    Returns dict with keys: invoice_ref, mrn, pz_ref (first non-empty for each).
    """
    out: Dict[str, Optional[str]] = {"invoice_ref": None, "mrn": None, "pz_ref": None}
    if not db_path.exists():
        return out
    try:
        con = _ro_conn(db_path)
        rows = con.execute(
            """
            SELECT related_invoice_no, related_mrn, related_pz_no
            FROM shipment_documents
            WHERE batch_id = ?
            ORDER BY created_at
            """,
            (batch_id,),
        ).fetchall()
        con.close()
        for row in rows:
            if not out["invoice_ref"] and row["related_invoice_no"]:
                out["invoice_ref"] = row["related_invoice_no"]
            if not out["mrn"] and row["related_mrn"]:
                out["mrn"] = row["related_mrn"]
            if not out["pz_ref"] and row["related_pz_no"]:
                out["pz_ref"] = row["related_pz_no"]
            if all(out.values()):
                break
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_doc_refs: %s", exc)
    return out


def _resolve_invoice_line_count(
    batch_id: str,
    db_path:  Path,
) -> int:
    """Return the number of invoice_lines rows for this batch."""
    if not db_path.exists():
        return 0
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            "SELECT COUNT(*) AS n FROM invoice_lines WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        con.close()
        if row:
            return row["n"]
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_invoice_line_count: %s", exc)
    return 0


def _resolve_customs_mrn(
    batch_id: str,
    db_path:  Path,
) -> Optional[AttributedValue]:
    """
    Read MRN from customs_declarations table.  This is the authoritative source
    for customs MRN (vs related_mrn in shipment_documents which is a hint).
    """
    if not db_path.exists():
        return None
    try:
        con = _ro_conn(db_path)
        row = con.execute(
            """
            SELECT mrn, declaration_type
            FROM customs_declarations
            WHERE batch_id = ? AND mrn != ''
            LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
        con.close()
        if row and row["mrn"]:
            return AttributedValue(value=row["mrn"], authority="customs_declarations")
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_customs_mrn: %s", exc)
    return None


# ── Conflict detection helpers ────────────────────────────────────────────────


def _detect_awb_conflict(
    doc_awb:      Optional[AttributedValue],
    tracking_awb: Optional[AttributedValue],
) -> Optional[AttributedValue]:
    """
    If doc AWB and tracking AWB both exist but disagree, return the secondary
    as the conflict value.  Returns None if they agree or if either is absent.
    """
    if doc_awb is None or tracking_awb is None:
        return None
    if doc_awb.value and tracking_awb.value and doc_awb.value != tracking_awb.value:
        return tracking_awb  # expose tracking as conflict; doc is primary
    return None


def _detect_customer_conflict(
    contractor_ids: List[str],
    cm_db_path:     Path,
) -> Optional[AttributedValue]:
    """
    If multiple distinct client_contractor_ids exist in the batch's documents,
    the first is primary; the second exposes as a conflict with its CM name.
    Returns None if only one (or zero) contractor IDs.
    """
    if len(contractor_ids) < 2:
        return None
    secondary_id = contractor_ids[1]
    return _resolve_customer_from_master(secondary_id, cm_db_path)


# ── Public builder functions ──────────────────────────────────────────────────


def build_awb_graph(
    batch_id:    str,
    *,
    doc_db:      Optional[Path] = None,
    tracking_db: Optional[Path] = None,
) -> GraphResult:
    """
    Resolve AWB identity for a batch from both shipment_documents and
    shipment_tracking_events.  Detect and expose AWB conflicts when the
    two sources disagree.

    Emphasis: AWB + tracking event summary.
    Does not resolve customer, supplier, or invoice.
    """
    doc_db      = doc_db      or _DOC_DB
    tracking_db = tracking_db or _TRACKING_DB

    result = GraphResult(
        batch_id  = batch_id,
        llm_used  = False,
        built_at  = _now_iso(),
        builder   = _BUILDER_AWB,
    )

    # ── AWB from documents ────────────────────────────────────────────────────
    doc_awb      = _resolve_awb_from_docs(batch_id, doc_db)
    tracking_awb = _resolve_awb_from_tracking(batch_id, tracking_db)

    # Primary: docs authority; fall back to tracking if docs absent
    if doc_awb:
        result.awb = doc_awb
    elif tracking_awb:
        result.awb = tracking_awb

    # Conflict: both present but disagree
    awb_conflict = _detect_awb_conflict(doc_awb, tracking_awb)
    if awb_conflict:
        result.awb_conflict = awb_conflict
        result.conflict_keys.append("awb")

    # ── Tracking summary ──────────────────────────────────────────────────────
    tracking = _resolve_tracking_summary(batch_id, tracking_db)
    result.tracking_event_count       = tracking["event_count"]
    result.tracking_latest_stage      = tracking["latest_stage"]
    result.tracking_has_manual_review = tracking["has_manual_review"]

    # ── Link completeness ─────────────────────────────────────────────────────
    lc = LinkCompleteness(
        awb_linked      = result.awb is not None,
        tracking_linked = result.tracking_event_count > 0,
    )
    lc._compute_missing()
    result.link_completeness = lc

    return result


def build_batch_graph(
    batch_id:    str,
    *,
    doc_db:      Optional[Path] = None,
    tracking_db: Optional[Path] = None,
    cm_db:       Optional[Path] = None,
    supp_db:     Optional[Path] = None,
) -> GraphResult:
    """
    Full cross-DB graph anchored on batch_id.  Resolves AWB, customer,
    supplier, invoice ref, MRN, PZ ref, and tracking events.

    This is the most complete builder. All unresolvable fields are
    null + listed in link_completeness.missing.
    """
    doc_db      = doc_db      or _DOC_DB
    tracking_db = tracking_db or _TRACKING_DB
    cm_db       = cm_db       or _CM_DB
    supp_db     = supp_db     or _SUPP_DB

    result = GraphResult(
        batch_id = batch_id,
        llm_used = False,
        built_at = _now_iso(),
        builder  = _BUILDER_BATCH,
    )

    # ── AWB ───────────────────────────────────────────────────────────────────
    doc_awb      = _resolve_awb_from_docs(batch_id, doc_db)
    tracking_awb = _resolve_awb_from_tracking(batch_id, tracking_db)
    result.awb   = doc_awb or tracking_awb
    awb_conflict = _detect_awb_conflict(doc_awb, tracking_awb)
    if awb_conflict:
        result.awb_conflict = awb_conflict
        result.conflict_keys.append("awb")

    # ── Tracking ──────────────────────────────────────────────────────────────
    tracking = _resolve_tracking_summary(batch_id, tracking_db)
    result.tracking_event_count       = tracking["event_count"]
    result.tracking_latest_stage      = tracking["latest_stage"]
    result.tracking_has_manual_review = tracking["has_manual_review"]

    # ── Customer ──────────────────────────────────────────────────────────────
    contractor_ids = _resolve_client_contractor_ids(batch_id, doc_db)
    if contractor_ids:
        primary_id   = contractor_ids[0]
        result.customer = _resolve_customer_from_master(primary_id, cm_db)
        if result.customer is None:
            # CM has no entry: expose contractor_id as raw value with doc authority
            result.customer = AttributedValue(
                value=primary_id,
                authority="shipment_documents",
            )
        customer_conflict = _detect_customer_conflict(contractor_ids, cm_db)
        if customer_conflict:
            result.customer_conflict = customer_conflict
            result.conflict_keys.append("customer")

    # ── Supplier ──────────────────────────────────────────────────────────────
    supplier_cid = _resolve_supplier_contractor_id(batch_id, doc_db)
    if supplier_cid:
        result.supplier      = _resolve_supplier_from_registry(supplier_cid, supp_db)
        result.supplier_code = _resolve_supplier_code_from_registry(supplier_cid, supp_db)
        # If registry has no entry, surface raw contractor_id with doc authority
        if result.supplier is None:
            result.supplier = AttributedValue(
                value=supplier_cid,
                authority="shipment_documents",
            )

    # ── Invoice / MRN / PZ refs ───────────────────────────────────────────────
    refs = _resolve_doc_refs(batch_id, doc_db)
    if refs["invoice_ref"]:
        result.invoice_ref = AttributedValue(
            value=refs["invoice_ref"],
            authority="shipment_documents",
        )
    if refs["pz_ref"]:
        result.pz_ref = AttributedValue(
            value=refs["pz_ref"],
            authority="shipment_documents",
        )
    # MRN: prefer customs_declarations over shipment_documents hint
    customs_mrn = _resolve_customs_mrn(batch_id, doc_db)
    if customs_mrn:
        result.mrn = customs_mrn
    elif refs["mrn"]:
        result.mrn = AttributedValue(value=refs["mrn"], authority="shipment_documents")

    result.invoice_line_count = _resolve_invoice_line_count(batch_id, doc_db)

    # ── Link completeness ─────────────────────────────────────────────────────
    lc = LinkCompleteness(
        awb_linked      = result.awb is not None,
        tracking_linked = result.tracking_event_count > 0,
        customer_linked = (
            result.customer is not None
            and result.customer.authority == "customer_master"
        ),
        supplier_linked = (
            result.supplier is not None
            and result.supplier.authority == "suppliers"
        ),
        invoice_linked  = result.invoice_ref is not None or result.invoice_line_count > 0,
        customs_linked  = result.mrn is not None,
    )
    lc._compute_missing()
    result.link_completeness = lc

    return result


def build_customer_graph(
    batch_id: str,
    *,
    doc_db: Optional[Path] = None,
    cm_db:  Optional[Path] = None,
) -> GraphResult:
    """
    Resolve customer identity for a batch.

    Reads client_contractor_id from shipment_documents, resolves against
    customer_master, and exposes any contractor_id conflict when multiple
    distinct customers appear in the same batch's documents.

    Does not resolve supplier, tracking, or invoice data.
    """
    doc_db = doc_db or _DOC_DB
    cm_db  = cm_db  or _CM_DB

    result = GraphResult(
        batch_id = batch_id,
        llm_used = False,
        built_at = _now_iso(),
        builder  = _BUILDER_CUSTOMER,
    )

    # ── Customer resolution ───────────────────────────────────────────────────
    contractor_ids = _resolve_client_contractor_ids(batch_id, doc_db)
    if contractor_ids:
        primary_id = contractor_ids[0]
        cm_result  = _resolve_customer_from_master(primary_id, cm_db)
        if cm_result:
            result.customer = cm_result
        else:
            # CM miss: surface raw contractor_id with doc authority
            result.customer = AttributedValue(
                value=primary_id,
                authority="shipment_documents",
            )
        # Conflict: multiple distinct contractor_ids in same batch's docs
        customer_conflict = _detect_customer_conflict(contractor_ids, cm_db)
        if customer_conflict:
            result.customer_conflict = customer_conflict
            result.conflict_keys.append("customer")

    # ── Minimal AWB for context ───────────────────────────────────────────────
    result.awb = _resolve_awb_from_docs(batch_id, doc_db)

    # ── Link completeness ─────────────────────────────────────────────────────
    lc = LinkCompleteness(
        awb_linked      = result.awb is not None,
        customer_linked = (
            result.customer is not None
            and result.customer.authority == "customer_master"
        ),
    )
    lc._compute_missing()
    result.link_completeness = lc

    return result


def build_invoice_graph(
    batch_id: str,
    *,
    doc_db: Optional[Path] = None,
) -> GraphResult:
    """
    Resolve invoice, customs, and PZ document relationships for a batch.

    Reads invoice lines, customs declarations, and PZ/invoice ref hints
    from shipment_documents.  Exposes the authoritative MRN from
    customs_declarations (preferred over the hint in shipment_documents).

    Does not resolve customer, supplier, or tracking data.
    """
    doc_db = doc_db or _DOC_DB

    result = GraphResult(
        batch_id = batch_id,
        llm_used = False,
        built_at = _now_iso(),
        builder  = _BUILDER_INVOICE,
    )

    # ── Invoice ref and PZ ref ────────────────────────────────────────────────
    refs = _resolve_doc_refs(batch_id, doc_db)
    if refs["invoice_ref"]:
        result.invoice_ref = AttributedValue(
            value=refs["invoice_ref"],
            authority="shipment_documents",
        )
    if refs["pz_ref"]:
        result.pz_ref = AttributedValue(
            value=refs["pz_ref"],
            authority="shipment_documents",
        )

    # ── Invoice line count ────────────────────────────────────────────────────
    result.invoice_line_count = _resolve_invoice_line_count(batch_id, doc_db)

    # ── MRN: customs_declarations is authoritative ────────────────────────────
    customs_mrn = _resolve_customs_mrn(batch_id, doc_db)
    if customs_mrn:
        result.mrn = customs_mrn
    elif refs["mrn"]:
        result.mrn = AttributedValue(value=refs["mrn"], authority="shipment_documents")

    # ── Minimal AWB context ───────────────────────────────────────────────────
    result.awb = _resolve_awb_from_docs(batch_id, doc_db)

    # ── Link completeness ─────────────────────────────────────────────────────
    lc = LinkCompleteness(
        awb_linked     = result.awb is not None,
        invoice_linked = result.invoice_ref is not None or result.invoice_line_count > 0,
        customs_linked = result.mrn is not None,
    )
    lc._compute_missing()
    result.link_completeness = lc

    return result

"""search_engine.py -- Phase 7 / 7.1 / Phase 8 Sprint 4: Natural-Language Search.

Deterministic, read-only. llm_used=False. No writes. No LLM calls.

Public API
----------
parse_query(q)          -> SearchIntent
execute_search(intent)  -> SearchResult

Phase 8 Sprint 4 addition: enrich=True enriches each SearchHit with graph
metadata (related_count, related_batch_ids, graph_available) sourced from
documents.db. Read-only. PRAGMA query_only = ON.

Supported domains: document | customer | supplier | product | shipment

Pattern recognition (no LLM):
  - AWB:     10-12 digit number (DHL air waybill)
  - MRN:     Polish customs MRN (e.g. 26PLXXXXXXXXXXXXXXXXY)
  - PZ:      PZ number pattern NNN/YYYY
  - INVOICE: Invoice ref pattern PREFIX-NNN/YYYY
  - BATCH:   UUID or BATCH-NNN identifier
  - KEYWORD: free-text fallback for all unrecognized tokens

All DB connections use PRAGMA query_only = ON.
Forbidden: writes | LLM calls | external HTTP | wFirma | DHL
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ── DB paths (read-only) ──────────────────────────────────────────────────────

_CM_DB       = settings.storage_root / "customer_master.sqlite"
_MD_DB       = settings.storage_root / "master_data.sqlite"
_SUPP_DB     = settings.storage_root / "suppliers.sqlite"
_DOC_DB      = settings.storage_root / "documents.db"
_TRACKING_DB = settings.storage_root / "tracking_events.db"

# ── Patterns ─────────────────────────────────────────────────────────────────

# AWB: 10-12 consecutive digits, or 3x4-digit groups separated by space/hyphen
_AWB_RE = re.compile(
    r"\b(?:\d{4}[\s\-]?\d{4}[\s\-]?\d{2,4}|\d{10,12})\b"
)
# MRN: Polish customs format 2 digits + 2 upper alpha + 14-18 alphanum + 1 check
_MRN_RE = re.compile(r"\b\d{2}[A-Z]{2}[A-Z0-9]{14,18}\b")
# PZ / invoice: digits slash 4-digit year (e.g. 94/2026, WDT/94/2026)
_PZ_INVOICE_RE = re.compile(r"\b[A-Za-z0-9/]{0,12}?\d{1,6}/20\d{2}\b")
# UUID v4
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
# Explicit BATCH-NNN label
_BATCH_LABEL_RE = re.compile(r"\bBATCH-\d+\b", re.IGNORECASE)
# HS code: 4-12 consecutive digits that look like tariff codes
_HS_RE = re.compile(r"\b71\d{4,10}\b")

QUERY_MAX_LEN = 300
DEFAULT_LIMIT  = 10
MAX_LIMIT      = 50

# ── Public output types ───────────────────────────────────────────────────────


@dataclass
class SearchIntent:
    """Parsed representation of a raw query string."""
    raw_query:        str
    awb_matches:      List[str]     = field(default_factory=list)
    mrn_matches:      List[str]     = field(default_factory=list)
    pz_invoice_matches: List[str]   = field(default_factory=list)
    batch_matches:    List[str]     = field(default_factory=list)
    hs_matches:       List[str]     = field(default_factory=list)
    keyword:          str           = ""
    domains_hint:     List[str]     = field(default_factory=list)

    @property
    def has_ids(self) -> bool:
        return bool(
            self.awb_matches or self.mrn_matches or
            self.pz_invoice_matches or self.batch_matches
        )


@dataclass
class SearchHit:
    domain:       str              # "document" | "customer" | "supplier" | "product"
    entity_id:    str
    title:        str
    subtitle:     str
    match_reason: str
    details:      Dict[str, Any]
    score:        float = 1.0      # 0.0-1.0; higher = more relevant
    # Phase 8 Sprint 4: populated when enrich=True; None otherwise
    graph_enrichment: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    query:           str
    interpreted_as:  str
    domains_searched: List[str]
    hits:            List[SearchHit]
    total:           int
    llm_used:        bool          # always False
    generated_at:    str

    def to_dict(self) -> Dict[str, Any]:
        def _hit_dict(h: "SearchHit") -> Dict[str, Any]:
            d: Dict[str, Any] = {
                "domain":       h.domain,
                "entity_id":    h.entity_id,
                "title":        h.title,
                "subtitle":     h.subtitle,
                "match_reason": h.match_reason,
                "details":      h.details,
                "score":        round(h.score, 3),
            }
            if h.graph_enrichment is not None:
                d["graph_enrichment"] = h.graph_enrichment
            return d

        return {
            "query":            self.query,
            "interpreted_as":   self.interpreted_as,
            "domains_searched": self.domains_searched,
            "hits":             [_hit_dict(h) for h in self.hits],
            "total":            self.total,
            "llm_used":         self.llm_used,
            "generated_at":     self.generated_at,
        }


# ── Query parser ──────────────────────────────────────────────────────────────


def parse_query(q: str) -> SearchIntent:
    """Parse a raw query string into a SearchIntent.

    Extracts structured patterns (AWB, MRN, PZ/invoice ref, UUID batch IDs,
    HS codes) and falls back to keyword search for any remaining text.
    No LLM. No external calls. Pure regex + string operations.
    """
    if not isinstance(q, str):
        q = ""
    # Truncate to safety limit
    q = q[:QUERY_MAX_LEN]
    raw = q.strip()
    if not raw:
        return SearchIntent(raw_query="")

    working = raw

    awb_matches: List[str] = []
    mrn_matches: List[str] = []
    pz_matches:  List[str] = []
    batch_matches: List[str] = []
    hs_matches:  List[str] = []

    # Extraction order matters: specific patterns consume text before generic ones.
    # Order: UUID > BATCH-label > MRN > HS code > PZ/invoice > AWB (most generic last)

    # --- UUID batch IDs (before AWB — UUID digit segments look like AWBs) ---
    for m in _UUID_RE.finditer(working):
        batch_matches.append(m.group().lower())
    working = _UUID_RE.sub(" ", working)

    # --- Explicit BATCH-NNN ---
    for m in _BATCH_LABEL_RE.finditer(working):
        batch_matches.append(m.group().upper())
    working = _BATCH_LABEL_RE.sub(" ", working)

    # --- MRN (before AWB — contains letters that narrow the match) ---
    for m in _MRN_RE.finditer(working.upper()):
        mrn_matches.append(m.group().upper())
    working = _MRN_RE.sub(" ", working)

    # --- HS codes (before AWB — a 10-digit HS is also a valid AWB digit count) ---
    for m in _HS_RE.finditer(working):
        hs_matches.append(m.group())
    working = _HS_RE.sub(" ", working)

    # --- AWB (last digit-sequence pattern — catches remaining 10-12 digit numbers) ---
    for m in _AWB_RE.finditer(working):
        candidate = re.sub(r"[\s\-]", "", m.group())
        if len(candidate) in (10, 11, 12):
            awb_matches.append(candidate)
    working = _AWB_RE.sub(" ", working)

    # --- PZ / Invoice refs ---
    for m in _PZ_INVOICE_RE.finditer(working):
        pz_matches.append(m.group())
    working = _PZ_INVOICE_RE.sub(" ", working)

    # Remaining text = keyword
    keyword = " ".join(working.split())  # collapse whitespace

    # Deduplicate
    awb_matches   = list(dict.fromkeys(awb_matches))
    mrn_matches   = list(dict.fromkeys(mrn_matches))
    pz_matches    = list(dict.fromkeys(pz_matches))
    batch_matches = list(dict.fromkeys(batch_matches))
    hs_matches    = list(dict.fromkeys(hs_matches))

    # Infer domains from patterns
    domains: List[str] = []
    if awb_matches or mrn_matches or batch_matches or pz_matches:
        domains.append("document")
        domains.append("shipment")   # Phase 7.1: AWB/batch also searches tracking events
    if hs_matches:
        domains.append("product")
    if not domains:
        # Free-text keyword: search everywhere
        domains = ["document", "customer", "supplier", "product", "shipment"]

    return SearchIntent(
        raw_query=raw,
        awb_matches=awb_matches,
        mrn_matches=mrn_matches,
        pz_invoice_matches=pz_matches,
        batch_matches=batch_matches,
        hs_matches=hs_matches,
        keyword=keyword,
        domains_hint=domains,
    )


# ── Domain search functions ───────────────────────────────────────────────────


def _ro_conn(db_path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection (PRAGMA query_only = ON)."""
    con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def search_documents(
    intent: SearchIntent,
    limit: int = DEFAULT_LIMIT,
    db_path: Optional[Path] = None,
) -> List[SearchHit]:
    """Search documents.db for matching shipment documents and customs records.

    Searches:
    - shipment_documents: awb, batch_id, related_mrn, related_pz_no,
                          document_type, file_name
    - customs_declarations: mrn, goods_description, importer_name
    """
    path = db_path or _DOC_DB
    if not path or not Path(path).exists():
        return []
    hits: List[SearchHit] = []
    try:
        con = _ro_conn(path)
        try:
            # ---- shipment_documents ----
            clauses: List[str] = []
            params: List[Any] = []

            if intent.awb_matches:
                placeholders = ",".join("?" for _ in intent.awb_matches)
                clauses.append(f"awb IN ({placeholders})")
                params.extend(intent.awb_matches)

            if intent.mrn_matches:
                for mrn in intent.mrn_matches:
                    clauses.append("related_mrn = ?")
                    params.append(mrn)

            if intent.batch_matches:
                for bid in intent.batch_matches:
                    clauses.append("batch_id = ?")
                    params.append(bid)

            if intent.pz_invoice_matches:
                for ref in intent.pz_invoice_matches:
                    clauses.append("(related_pz_no = ? OR related_invoice_no = ?)")
                    params.extend([ref, ref])

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                clauses.append(
                    "(file_name LIKE ? OR document_type LIKE ? "
                    "OR batch_id LIKE ? OR awb LIKE ?)"
                )
                params.extend([kw, kw, kw, kw])

            if clauses:
                sql = (
                    "SELECT id, batch_id, awb, document_type, file_name, "
                    "extraction_status, parser_status, related_mrn, "
                    "related_pz_no, requires_manual_review "
                    "FROM shipment_documents WHERE "
                    + " OR ".join(f"({c})" for c in clauses)
                    + " ORDER BY updated_at DESC LIMIT ?"
                )
                params.append(limit)
                for row in con.execute(sql, params).fetchall():
                    score = _doc_score(row, intent)
                    hits.append(SearchHit(
                        domain="document",
                        entity_id=row["id"],
                        title=f"{row['document_type']} — {row['awb'] or row['batch_id']}",
                        subtitle=row["file_name"] or "",
                        match_reason=_doc_match_reason(row, intent),
                        details={
                            "batch_id":          row["batch_id"],
                            "awb":               row["awb"],
                            "document_type":     row["document_type"],
                            "extraction_status": row["extraction_status"],
                            "parser_status":     row["parser_status"],
                            "related_mrn":       row["related_mrn"],
                            "related_pz_no":     row["related_pz_no"],
                            "requires_manual_review": bool(row["requires_manual_review"]),
                        },
                        score=score,
                    ))

            # ---- customs_declarations ----
            cd_clauses: List[str] = []
            cd_params: List[Any] = []

            if intent.mrn_matches:
                placeholders = ",".join("?" for _ in intent.mrn_matches)
                cd_clauses.append(f"mrn IN ({placeholders})")
                cd_params.extend(intent.mrn_matches)

            if intent.batch_matches:
                for bid in intent.batch_matches:
                    cd_clauses.append("batch_id = ?")
                    cd_params.append(bid)

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                cd_clauses.append(
                    "(goods_description LIKE ? OR importer_name LIKE ? OR mrn LIKE ?)"
                )
                cd_params.extend([kw, kw, kw])

            if cd_clauses:
                cd_sql = (
                    "SELECT id, batch_id, mrn, clearance_date, "
                    "duty_pln, importer_name, goods_description "
                    "FROM customs_declarations WHERE "
                    + " OR ".join(f"({c})" for c in cd_clauses)
                    + " ORDER BY created_at DESC LIMIT ?"
                )
                cd_params.append(limit)
                for row in con.execute(cd_sql, cd_params).fetchall():
                    hits.append(SearchHit(
                        domain="document",
                        entity_id=row["id"],
                        title=f"SAD/MRN {row['mrn'] or '—'}",
                        subtitle=f"{row['importer_name'] or ''} | duty {row['duty_pln']} PLN",
                        match_reason=f"customs declaration MRN={row['mrn']}",
                        details={
                            "batch_id":       row["batch_id"],
                            "mrn":            row["mrn"],
                            "clearance_date": row["clearance_date"],
                            "duty_pln":       row["duty_pln"],
                            "importer_name":  row["importer_name"],
                            "goods_description": row["goods_description"],
                        },
                        score=0.95 if row["mrn"] in intent.mrn_matches else 0.6,
                    ))
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] documents search failed: %s", exc)
    return hits[:limit]


def search_customers(
    intent: SearchIntent,
    limit: int = DEFAULT_LIMIT,
    db_path: Optional[Path] = None,
) -> List[SearchHit]:
    """Search customer_master.sqlite for matching customers.

    Searches: bill_to_name, nip, vat_eu_number, country.
    """
    path = db_path or _CM_DB
    if not path or not Path(path).exists():
        return []
    hits: List[SearchHit] = []
    try:
        con = _ro_conn(path)
        try:
            clauses: List[str] = []
            params: List[Any] = []

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                clauses.append(
                    "(bill_to_name LIKE ? OR nip LIKE ? "
                    "OR vat_eu_number LIKE ? OR country LIKE ?)"
                )
                params.extend([kw, kw, kw, kw])

            # Treat short uppercase token as possible country code
            raw_up = intent.raw_query.strip().upper()
            if re.match(r"^[A-Z]{2}$", raw_up):
                clauses.append("country = ?")
                params.append(raw_up)

            # NIP / VAT direct match on raw query (strip spaces/hyphens)
            raw_digits = re.sub(r"[\s\-]", "", intent.raw_query)
            if re.match(r"^\d{10,15}$", raw_digits):
                clauses.append("(nip = ? OR vat_eu_number = ?)")
                params.extend([raw_digits, raw_digits])

            if not clauses:
                return []

            sql = (
                "SELECT bill_to_contractor_id, bill_to_name, country, "
                "nip, vat_eu_number, vat_eu_valid, default_currency "
                "FROM customer_master WHERE "
                + " OR ".join(f"({c})" for c in clauses)
                + " ORDER BY datetime(updated_at) DESC LIMIT ?"
            )
            params.append(limit)
            for row in con.execute(sql, params).fetchall():
                hits.append(SearchHit(
                    domain="customer",
                    entity_id=row["bill_to_contractor_id"],
                    title=row["bill_to_name"] or row["bill_to_contractor_id"],
                    subtitle=f"{row['country'] or ''} | NIP {row['nip'] or '—'}",
                    match_reason=_customer_match_reason(row, intent),
                    details={
                        "bill_to_contractor_id": row["bill_to_contractor_id"],
                        "bill_to_name":          row["bill_to_name"],
                        "country":               row["country"],
                        "nip":                   row["nip"],
                        "vat_eu_number":         row["vat_eu_number"],
                        "vat_eu_valid":          row["vat_eu_valid"],
                        "default_currency":      row["default_currency"],
                    },
                    score=_customer_score(row, intent),
                ))
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] customers search failed: %s", exc)
    return hits[:limit]


def search_suppliers(
    intent: SearchIntent,
    limit: int = DEFAULT_LIMIT,
    db_path: Optional[Path] = None,
) -> List[SearchHit]:
    """Search suppliers.sqlite for matching suppliers.

    Searches: name, supplier_code, country, vat_id, eori.
    """
    path = db_path or _SUPP_DB
    if not path or not Path(path).exists():
        return []
    hits: List[SearchHit] = []
    try:
        con = _ro_conn(path)
        try:
            clauses: List[str] = []
            params: List[Any] = []

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                clauses.append(
                    "(name LIKE ? OR supplier_code LIKE ? "
                    "OR country LIKE ? OR vat_id LIKE ? OR eori LIKE ?)"
                )
                params.extend([kw, kw, kw, kw, kw])

            raw_up = intent.raw_query.strip().upper()
            if re.match(r"^[A-Z]{2}$", raw_up):
                clauses.append("country = ?")
                params.append(raw_up)

            if not clauses:
                return []

            sql = (
                "SELECT id, supplier_code, name, country, "
                "vat_id, eori, wfirma_id, active "
                "FROM suppliers WHERE "
                + " OR ".join(f"({c})" for c in clauses)
                + " ORDER BY datetime(updated_at) DESC LIMIT ?"
            )
            params.append(limit)
            for row in con.execute(sql, params).fetchall():
                hits.append(SearchHit(
                    domain="supplier",
                    entity_id=row["supplier_code"],
                    title=row["name"] or row["supplier_code"],
                    subtitle=f"{row['country'] or ''} | {row['vat_id'] or row['eori'] or '—'}",
                    match_reason=_supplier_match_reason(row, intent),
                    details={
                        "supplier_code": row["supplier_code"],
                        "name":          row["name"],
                        "country":       row["country"],
                        "vat_id":        row["vat_id"],
                        "eori":          row["eori"],
                        "wfirma_id":     row["wfirma_id"],
                        "active":        bool(row["active"]),
                    },
                    score=_supplier_score(row, intent),
                ))
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] suppliers search failed: %s", exc)
    return hits[:limit]


def search_products(
    intent: SearchIntent,
    limit: int = DEFAULT_LIMIT,
    db_path: Optional[Path] = None,
) -> List[SearchHit]:
    """Search master_data.sqlite designs for matching products.

    Searches: design_code, display_name, collection, metal, stone_summary, hs_code.
    """
    path = db_path or _MD_DB
    if not path or not Path(path).exists():
        return []
    hits: List[SearchHit] = []
    try:
        con = _ro_conn(path)
        try:
            clauses: List[str] = []
            params: List[Any] = []

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                clauses.append(
                    "(design_code LIKE ? OR display_name LIKE ? "
                    "OR collection LIKE ? OR metal LIKE ? OR stone_summary LIKE ?)"
                )
                params.extend([kw, kw, kw, kw, kw])

            if intent.hs_matches:
                placeholders = ",".join("?" for _ in intent.hs_matches)
                clauses.append(f"hs_code IN ({placeholders})")
                params.extend(intent.hs_matches)

            if not clauses:
                return []

            sql = (
                "SELECT design_code, display_name, collection, "
                "metal, stone_summary, hs_code, active "
                "FROM designs WHERE "
                + " OR ".join(f"({c})" for c in clauses)
                + " ORDER BY datetime(updated_at) DESC LIMIT ?"
            )
            params.append(limit)
            for row in con.execute(sql, params).fetchall():
                hits.append(SearchHit(
                    domain="product",
                    entity_id=row["design_code"],
                    title=row["display_name"] or row["design_code"],
                    subtitle=f"{row['metal'] or ''} | {row['stone_summary'] or ''} | HS {row['hs_code'] or '—'}",
                    match_reason=_product_match_reason(row, intent),
                    details={
                        "design_code":   row["design_code"],
                        "display_name":  row["display_name"],
                        "collection":    row["collection"],
                        "metal":         row["metal"],
                        "stone_summary": row["stone_summary"],
                        "hs_code":       row["hs_code"],
                        "active":        bool(row["active"]),
                    },
                    score=_product_score(row, intent),
                ))
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] products search failed: %s", exc)
    return hits[:limit]


def search_shipments(
    intent: SearchIntent,
    limit: int = DEFAULT_LIMIT,
    db_path: Optional[Path] = None,
) -> List[SearchHit]:
    """Search shipment_tracking_events for matching shipments.

    Phase 7.1: wires AWB and batch_id queries into the tracking events store.

    Searches:
    - shipment_tracking_events: awb (exact / LIKE), batch_id (exact),
                                normalized_stage, description, raw_subject
    """
    path = db_path or _TRACKING_DB
    if not path or not Path(path).exists():
        return []
    hits: List[SearchHit] = []
    seen_shipments: set = set()   # dedup (batch_id, awb) pairs

    try:
        con = _ro_conn(path)
        try:
            clauses: List[str] = []
            params: List[Any] = []

            if intent.awb_matches:
                placeholders = ",".join("?" for _ in intent.awb_matches)
                clauses.append(f"awb IN ({placeholders})")
                params.extend(intent.awb_matches)

            if intent.batch_matches:
                for bid in intent.batch_matches:
                    clauses.append("batch_id = ?")
                    params.append(bid)

            if intent.keyword:
                kw = f"%{intent.keyword}%"
                clauses.append(
                    "(awb LIKE ? OR batch_id LIKE ? "
                    "OR description LIKE ? OR raw_subject LIKE ? "
                    "OR normalized_stage LIKE ?)"
                )
                params.extend([kw, kw, kw, kw, kw])

            if not clauses:
                return []

            # Fetch most-recent event per (batch_id, awb) pair
            sql = (
                "SELECT batch_id, awb, carrier, normalized_stage, stage, "
                "status, event_time, description, location, "
                "requires_manual_review "
                "FROM shipment_tracking_events WHERE ("
                + " OR ".join(f"({c})" for c in clauses)
                + ") AND direction='inbound' ORDER BY event_time DESC LIMIT ?"
            )
            params.append(limit * 5)   # over-fetch — dedup reduces to limit

            for row in con.execute(sql, params).fetchall():
                key = (row["batch_id"], row["awb"])
                if key in seen_shipments:
                    continue
                seen_shipments.add(key)
                score = _shipment_score(row, intent)
                hits.append(SearchHit(
                    domain="shipment",
                    entity_id=row["batch_id"],
                    title=f"Shipment {row['batch_id']}",
                    subtitle=(
                        f"AWB {row['awb']} | {row['carrier']} | "
                        f"{row['normalized_stage'] or row['stage']}"
                    ),
                    match_reason=_shipment_match_reason(row, intent),
                    details={
                        "batch_id":          row["batch_id"],
                        "awb":               row["awb"],
                        "carrier":           row["carrier"],
                        "normalized_stage":  row["normalized_stage"],
                        "stage":             row["stage"],
                        "status":            row["status"],
                        "event_time":        row["event_time"],
                        "location":          row["location"],
                        "description":       row["description"],
                        "requires_manual_review": bool(row["requires_manual_review"]),
                    },
                    score=score,
                ))
                if len(hits) >= limit:
                    break
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] shipments search failed: %s", exc)
    return hits[:limit]


# ── Top-level search executor ─────────────────────────────────────────────────


def execute_search(
    intent: SearchIntent,
    domains: Optional[List[str]] = None,
    limit: int = DEFAULT_LIMIT,
    *,
    doc_db:      Optional[Path] = None,
    cm_db:       Optional[Path] = None,
    supp_db:     Optional[Path] = None,
    md_db:       Optional[Path] = None,
    tracking_db: Optional[Path] = None,
    enrich:      bool = False,
) -> SearchResult:
    """Execute a parsed SearchIntent across the requested domains.

    domain filter overrides intent.domains_hint if provided.
    llm_used is always False.

    Phase 8 Sprint 4: when enrich=True, each returned hit gains a
    graph_enrichment dict with related_count, related_batch_ids,
    and graph_available sourced from documents.db.  Read-only only.
    """
    if not intent.raw_query:
        return SearchResult(
            query="",
            interpreted_as="empty query",
            domains_searched=[],
            hits=[],
            total=0,
            llm_used=False,
            generated_at=_now(),
        )

    effective_domains = domains if domains else intent.domains_hint
    effective_domains = [d for d in effective_domains if d in _ALL_DOMAINS]
    if not effective_domains:
        effective_domains = list(_ALL_DOMAINS)

    limit = max(1, min(limit, MAX_LIMIT))

    # Fetch up to `limit` per domain.  The cross-domain merge then sorts
    # globally and returns the top `limit`.  Using `limit` per domain ensures
    # every domain has a fair shot at the final ranking even when one domain
    # has many equal-score matches.  Total candidates before cut = limit *
    # num_domains (at most 50 * 5 = 250 — well within budget).
    per_domain = max(limit, DEFAULT_LIMIT)
    all_hits: List[SearchHit] = []

    if "document" in effective_domains:
        all_hits.extend(search_documents(intent, limit=per_domain, db_path=doc_db))
    if "customer" in effective_domains:
        all_hits.extend(search_customers(intent, limit=per_domain, db_path=cm_db))
    if "supplier" in effective_domains:
        all_hits.extend(search_suppliers(intent, limit=per_domain, db_path=supp_db))
    if "product" in effective_domains:
        all_hits.extend(search_products(intent, limit=per_domain, db_path=md_db))
    if "shipment" in effective_domains:
        all_hits.extend(search_shipments(intent, limit=per_domain, db_path=tracking_db))

    # Sort by score descending, stable (insertion order preserved for ties)
    all_hits.sort(key=lambda h: h.score, reverse=True)
    top_hits = all_hits[:limit]

    # Phase 8 Sprint 4: optional graph enrichment
    if enrich:
        _enrich_hits(top_hits, doc_db=doc_db)

    return SearchResult(
        query=intent.raw_query,
        interpreted_as=_describe_intent(intent),
        domains_searched=effective_domains,
        hits=top_hits,
        total=len(all_hits),
        llm_used=False,
        generated_at=_now(),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

_ALL_DOMAINS = {"document", "customer", "supplier", "product", "shipment"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _describe_intent(intent: SearchIntent) -> str:
    parts: List[str] = []
    if intent.awb_matches:
        parts.append(f"AWB {', '.join(intent.awb_matches)}")
    if intent.mrn_matches:
        parts.append(f"MRN {', '.join(intent.mrn_matches)}")
    if intent.batch_matches:
        parts.append(f"batch {', '.join(intent.batch_matches)}")
    if intent.pz_invoice_matches:
        parts.append(f"ref {', '.join(intent.pz_invoice_matches)}")
    if intent.hs_matches:
        parts.append(f"HS {', '.join(intent.hs_matches)}")
    if intent.keyword:
        parts.append(f"keyword '{intent.keyword}'")
    if not parts:
        return "no recognizable patterns"
    return "; ".join(parts)


def _doc_score(row: sqlite3.Row, intent: SearchIntent) -> float:
    awb = row["awb"] or ""
    if awb and awb in intent.awb_matches:
        return 1.0
    mrn = row["related_mrn"] or ""
    if mrn and mrn in intent.mrn_matches:
        return 0.95
    bid = row["batch_id"] or ""
    if bid and bid in intent.batch_matches:
        return 0.90
    pz = row["related_pz_no"] or ""
    if pz and pz in intent.pz_invoice_matches:
        return 0.85
    return 0.6


def _doc_match_reason(row: sqlite3.Row, intent: SearchIntent) -> str:
    awb = row["awb"] or ""
    if awb and awb in intent.awb_matches:
        return f"AWB exact match: {awb}"
    mrn = row["related_mrn"] or ""
    if mrn and mrn in intent.mrn_matches:
        return f"MRN exact match: {mrn}"
    bid = row["batch_id"] or ""
    if bid and bid in intent.batch_matches:
        return f"batch_id exact match: {bid}"
    pz = row["related_pz_no"] or ""
    if pz and pz in intent.pz_invoice_matches:
        return f"PZ/invoice ref match: {pz}"
    return f"keyword match in {row['document_type']} / {row['file_name']}"


def _customer_score(row: sqlite3.Row, intent: SearchIntent) -> float:
    name = (row["bill_to_name"] or "").lower()
    nip  = row["nip"] or ""
    kw   = intent.keyword.lower()
    raw  = re.sub(r"[\s\-]", "", intent.raw_query)
    if nip and nip == raw:
        return 1.0
    vat = row["vat_eu_number"] or ""
    if vat and vat == raw:
        return 1.0
    if kw and kw in name:
        return 0.8 if name.startswith(kw) else 0.65
    return 0.5


def _customer_match_reason(row: sqlite3.Row, intent: SearchIntent) -> str:
    nip = row["nip"] or ""
    raw = re.sub(r"[\s\-]", "", intent.raw_query)
    if nip == raw:
        return f"NIP exact match: {nip}"
    vat = row["vat_eu_number"] or ""
    if vat == raw:
        return f"VAT exact match: {vat}"
    if intent.keyword:
        return f"name keyword match: '{intent.keyword}'"
    return "country match"


def _supplier_score(row: sqlite3.Row, intent: SearchIntent) -> float:
    name = (row["name"] or "").lower()
    kw   = intent.keyword.lower()
    if kw and kw == name:
        return 1.0
    if kw and name.startswith(kw):
        return 0.85
    if kw and kw in name:
        return 0.7
    return 0.5


def _supplier_match_reason(row: sqlite3.Row, intent: SearchIntent) -> str:
    if intent.keyword:
        return f"name/code keyword match: '{intent.keyword}'"
    return "country match"


def _product_score(row: sqlite3.Row, intent: SearchIntent) -> float:
    code = (row["design_code"] or "").lower()
    name = (row["display_name"] or "").lower()
    kw   = intent.keyword.lower()
    if code == kw:
        return 1.0
    if name == kw:
        return 0.95
    if kw and (code.startswith(kw) or name.startswith(kw)):
        return 0.8
    if row["hs_code"] and row["hs_code"] in intent.hs_matches:
        return 0.9
    return 0.5


def _product_match_reason(row: sqlite3.Row, intent: SearchIntent) -> str:
    if row["hs_code"] and row["hs_code"] in intent.hs_matches:
        return f"HS code match: {row['hs_code']}"
    if intent.keyword:
        return f"design_code/name keyword match: '{intent.keyword}'"
    return "keyword match"


def _shipment_score(row: sqlite3.Row, intent: SearchIntent) -> float:
    awb = row["awb"] or ""
    bid = row["batch_id"] or ""
    if awb and awb in intent.awb_matches:
        return 1.0
    if bid and bid in intent.batch_matches:
        return 0.9
    return 0.6


def _shipment_match_reason(row: sqlite3.Row, intent: SearchIntent) -> str:
    awb = row["awb"] or ""
    bid = row["batch_id"] or ""
    if awb and awb in intent.awb_matches:
        return f"AWB exact match: {awb}"
    if bid and bid in intent.batch_matches:
        return f"batch_id exact match: {bid}"
    if intent.keyword:
        return f"keyword match in stage/description: '{intent.keyword}'"
    return "keyword match"


# ── Phase 8 Sprint 4: graph enrichment helpers ───────────────────────────────


def _resolve_batch_ids_for_hit(
    hit: SearchHit,
    con: sqlite3.Connection,
) -> List[str]:
    """Resolve batch_ids from a SearchHit depending on its domain.

    Read-only.  Uses the already-open, PRAGMA query_only connection.
    Returns an empty list when no batch relationship can be found.
    """
    try:
        if hit.domain == "document":
            # entity_id is document id; find its batch_id
            row = con.execute(
                "SELECT batch_id FROM shipment_documents "
                "WHERE id = ? AND batch_id != '' LIMIT 1",
                (hit.entity_id,),
            ).fetchone()
            if row:
                return [row[0]]

        elif hit.domain == "shipment":
            # entity_id IS the batch_id
            if hit.entity_id:
                return [hit.entity_id]

        elif hit.domain == "customer":
            # entity_id is bill_to_contractor_id
            rows = con.execute(
                "SELECT DISTINCT batch_id FROM shipment_documents "
                "WHERE client_contractor_id = ? AND batch_id != '' LIMIT 20",
                (hit.entity_id,),
            ).fetchall()
            return [r[0] for r in rows]

        elif hit.domain == "supplier":
            # entity_id is supplier_code; matched against supplier_contractor_id
            rows = con.execute(
                "SELECT DISTINCT batch_id FROM shipment_documents "
                "WHERE supplier_contractor_id = ? AND batch_id != '' LIMIT 20",
                (hit.entity_id,),
            ).fetchall()
            return [r[0] for r in rows]

        # "product" hits: no batch relationship available in documents.db

    except Exception as exc:
        log.debug(
            "[search] batch_id resolution failed for %s %s: %s",
            hit.domain, hit.entity_id, exc,
        )
    return []


def _enrich_hits(
    hits: List[SearchHit],
    doc_db: Optional[Path] = None,
) -> None:
    """Enrich hits in-place with graph metadata from documents.db.

    Sets hit.graph_enrichment = {
        "related_count":    int,    # number of documents in the same batch(es)
        "related_batch_ids": list,  # batch_ids connected to this hit
        "graph_available":  bool,   # True when at least one batch_id is found
    }

    Read-only.  PRAGMA query_only = ON.  No writes.  llm_used=False.
    """
    empty: Dict[str, Any] = {
        "related_count": 0,
        "related_batch_ids": [],
        "graph_available": False,
    }

    path = doc_db or _DOC_DB
    if not path or not Path(path).exists():
        for h in hits:
            h.graph_enrichment = dict(empty)
        return

    try:
        con = _ro_conn(path)
        try:
            for h in hits:
                batch_ids = _resolve_batch_ids_for_hit(h, con)
                if not batch_ids:
                    h.graph_enrichment = dict(empty)
                    continue

                placeholders = ",".join("?" for _ in batch_ids)
                count_row = con.execute(
                    f"SELECT COUNT(*) FROM shipment_documents "
                    f"WHERE batch_id IN ({placeholders})",
                    batch_ids,
                ).fetchone()
                count = count_row[0] if count_row else 0
                # For document hits subtract self from the count
                if h.domain == "document":
                    count = max(0, count - 1)

                h.graph_enrichment = {
                    "related_count":    count,
                    "related_batch_ids": batch_ids,
                    "graph_available":  True,
                }
        finally:
            con.close()
    except Exception as exc:
        log.warning("[search] graph enrichment failed: %s", exc)
        for h in hits:
            if h.graph_enrichment is None:
                h.graph_enrichment = dict(empty)

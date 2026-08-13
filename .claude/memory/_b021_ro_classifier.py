#!/usr/bin/env python3
"""B-021 read-only historical packing_contractor_resolution classifier.

READ-ONLY against production SQLite. No INSERT/UPDATE/DELETE.
Writes evidence JSON under .claude/memory/ only.

Evidence precedence (frozen before query):
  1. shipment_documents.<role>_contractor_id (per-document)
  2. proforma_drafts.client_contractor_id (0-pre / draft-carried)
  3. sales_documents → shipment_documents join (0a path inputs)
  4. packing_contractor_resolution (UNDER AUDIT — never self-proof)
  5. customer_master / name match — supporting only, never decisive for MISROUTING

Mutation candidate requires BOTH:
  - independent evidence that the batch-level row is wrong, AND
  - step 0b is reachable for a real-business draft (0-pre and 0a miss).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

STORAGE = Path(r"C:\PZ\storage")
PR_DB = STORAGE / "packing_resolutions.sqlite"
DOCS_DB = STORAGE / "documents.db"
PF_DB = STORAGE / "proforma_links.db"
OUT_JSON = Path(r"C:\PZ-verify\.claude\memory\b021-ro-assessment-2026-08-14.json")
CAND_JSON = Path(r"C:\PZ-verify\.claude\memory\b021-mutation-candidates.json")

# Fixture / test batch heuristics (ORPHANED_TEST_DATA) — structural, not name CM.
_FIXTURE_BATCH_RE = re.compile(
    r"(?i)(^BATCH_PR\d|_TEST_|TEST_|LAS_TEST|RSBOTH|FIXTURE|SMOKE|DEMO|"
    r"DUMMY|UNITTEST|PLAYWRIGHT|^SHIPMENT_TEST)"
)
_FIXTURE_NAME_RE = re.compile(
    r"(?i)^(Only A Name|WRONG TYPED NAME|Foo Client|ACME|Client A|Client B|"
    r"TEST CLIENT|Dummy)"
)

# Editable draft states that can still be resolved / posted.
_EDITABLE_STATES = {
    "draft", "preview", "ready", "blocked", "open", "editable",
    "needs_review", "in_progress", "",
}


def _conn(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _norm_cid(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def _is_fixture_batch(batch_id: str) -> bool:
    return bool(_FIXTURE_BATCH_RE.search(batch_id or ""))


def _table_cols(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def load_packing_rows() -> List[Dict[str, Any]]:
    with _conn(PR_DB) as c:
        rows = c.execute(
            "SELECT * FROM packing_contractor_resolution ORDER BY batch_id, role"
        ).fetchall()
    return [dict(r) for r in rows]


def doc_cids_by_batch(role: str) -> Dict[str, Set[str]]:
    """Independent per-document contractor IDs from shipment_documents."""
    field = "client_contractor_id" if role == "client" else "supplier_contractor_id"
    out: Dict[str, Set[str]] = defaultdict(set)
    with _conn(DOCS_DB) as c:
        cols = _table_cols(c, "shipment_documents")
        if field not in cols:
            return out
        for r in c.execute(
            f"SELECT batch_id, {field} AS cid, document_type "
            f"FROM shipment_documents WHERE batch_id IS NOT NULL"
        ):
            cid = _norm_cid(r["cid"])
            if cid:
                out[r["batch_id"]].add(cid)
    return out


def sales_doc_client_cids() -> Dict[str, Set[str]]:
    """0a chain: sales_packing_list docs → shipment_documents.client_contractor_id."""
    out: Dict[str, Set[str]] = defaultdict(set)
    with _conn(DOCS_DB) as c:
        cols_sd = _table_cols(c, "sales_documents")
        cols_sh = _table_cols(c, "shipment_documents")
        if "document_id" not in cols_sd or "client_contractor_id" not in cols_sh:
            # Fall back: sales_packing_list rows on shipment_documents alone
            if "client_contractor_id" in cols_sh:
                for r in c.execute(
                    "SELECT batch_id, client_contractor_id AS cid "
                    "FROM shipment_documents "
                    "WHERE document_type = 'sales_packing_list'"
                ):
                    cid = _norm_cid(r["cid"])
                    if cid:
                        out[r["batch_id"]].add(cid)
            return out
        q = """
            SELECT sd.batch_id AS batch_id, sh.client_contractor_id AS cid
            FROM sales_documents sd
            JOIN shipment_documents sh ON sh.id = sd.document_id
            WHERE sd.batch_id IS NOT NULL
        """
        try:
            rows = c.execute(q).fetchall()
        except sqlite3.Error:
            rows = c.execute(
                "SELECT batch_id, client_contractor_id AS cid "
                "FROM shipment_documents "
                "WHERE document_type = 'sales_packing_list'"
            ).fetchall()
        for r in rows:
            cid = _norm_cid(r["cid"])
            if cid:
                out[r["batch_id"]].add(cid)
    return out


def load_drafts() -> List[Dict[str, Any]]:
    with _conn(PF_DB) as c:
        cols = _table_cols(c, "proforma_drafts")
        want = [
            "id", "batch_id", "client_name", "client_contractor_id",
            "draft_state", "status", "wfirma_proforma_id", "clone_generation",
        ]
        sel = [w for w in want if w in cols]
        rows = c.execute(
            f"SELECT {', '.join(sel)} FROM proforma_drafts"
        ).fetchall()
    return [dict(r) for r in rows]


def classify_row(
    row: Dict[str, Any],
    doc_cids: Set[str],
    sales_cids: Set[str],
    drafts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    batch_id = row.get("batch_id") or ""
    role = row.get("role") or ""
    stored = _norm_cid(row.get("matched_master_id") or row.get("matched_wfirma_id"))
    status = (row.get("status") or "").strip()
    conf = row.get("confidence")
    reason = row.get("reason") or ""

    fixture = _is_fixture_batch(batch_id)
    # Independent evidence set for this role
    indep = set(doc_cids)
    if role == "client":
        indep |= set(sales_cids)

    # Drafts on this batch
    batch_drafts = [d for d in drafts if (d.get("batch_id") or "") == batch_id]
    drafts_with_cid = []
    drafts_missing_cid = []
    for d in batch_drafts:
        d_cid = _norm_cid(d.get("client_contractor_id"))
        name = d.get("client_name") or ""
        state = (d.get("draft_state") or d.get("status") or "").strip().lower()
        editable = state in _EDITABLE_STATES or not state
        # posted / issued drafts are not 0b exposure for future misroute
        if d.get("wfirma_proforma_id") and state in {"posted", "issued", "converted", "done"}:
            editable = False
        entry = {
            "id": d.get("id"),
            "client_name": name,
            "client_contractor_id": d_cid,
            "draft_state": state,
            "fixture_name": bool(_FIXTURE_NAME_RE.match(name)),
        }
        if d_cid:
            drafts_with_cid.append(entry)
        elif editable and role == "client":
            drafts_missing_cid.append(entry)

    # Can 0a resolve? If sales packing list docs carry client_contractor_id
    # OR draft carries client_contractor_id (0-pre), 0b is masked for those drafts.
    zero_a_possible = bool(sales_cids) or bool(
        { _norm_cid(x) for x in doc_cids }  # any doc cid for client role
        if role == "client" else False
    )
    # More precise: 0a needs a matching sales doc for the draft's client_name —
    # without simulating name join, treat presence of any sales doc cid as
    # "0a can resolve SOME drafts"; drafts_missing_cid without sales cid → 0b risk.

    # Step 0b reachable: client role, confirmed packing row, at least one
    # editable draft missing client_contractor_id, AND no sales-doc cid that
    # would let 0a succeed for that draft (conservative: if sales_cids empty
    # AND doc client cids empty for matching, 0b is reachable).
    if role == "client":
        zero_b_reachable = (
            status == "confirmed"
            and bool(stored)
            and bool(drafts_missing_cid)
            and not sales_cids  # no per-doc sales cid authority present on batch
        )
        # If sales_cids exist, 0a may still miss for name-mismatch drafts —
        # treat those drafts_missing_cid as 0b-reachable ONLY when sales_cids
        # is empty OR stored cid is not among sales_cids AND indep has >1.
        if sales_cids and drafts_missing_cid:
            # 0a walks by client_name join — without executing join, if the
            # draft has no cid and sales docs have cids, 0a may still resolve
            # by name. Conservatively: 0b reachable only if sales packing
            # client cids are empty on shipment_documents for sales_packing_list.
            with _conn(DOCS_DB) as c:
                filled = c.execute(
                    "SELECT COUNT(*) AS n FROM shipment_documents "
                    "WHERE batch_id = ? AND document_type = 'sales_packing_list' "
                    "AND IFNULL(client_contractor_id,'') != ''",
                    (batch_id,),
                ).fetchone()["n"]
            zero_b_reachable = bool(drafts_missing_cid) and filled == 0 and status == "confirmed"
    else:
        # Supplier role is not consumed by _resolve_customer 0b.
        zero_b_reachable = False

    # Wrongness proof from independent evidence
    multiparty = len(indep) > 1
    mismatch = bool(indep) and stored and stored not in indep
    agrees = bool(indep) and stored and stored in indep and len(indep) == 1
    no_indep = len(indep) == 0

    classification = "INSUFFICIENT_EVIDENCE"
    note = ""

    if fixture:
        classification = "ORPHANED_TEST_DATA"
        note = "fixture/test batch pattern"
        # Still record if 0b structurally reachable for transparency
    elif role == "supplier":
        # Supplier rows are not _resolve_customer 0b consumers.
        if multiparty and stored and stored not in indep:
            classification = "STALE_BUT_MASKED"
            note = "supplier multiparty/mismatch; not consumed by proforma 0b"
        elif agrees or (no_indep and status == "confirmed"):
            classification = "SAFE_SINGLE" if agrees or no_indep else "INSUFFICIENT_EVIDENCE"
            if no_indep:
                note = "no independent supplier doc cids; single batch row only"
            else:
                note = "single independent supplier cid matches batch row"
        elif multiparty and stored in indep:
            classification = "STALE_BUT_MASKED"
            note = "multiparty docs but batch row equals one of them; supplier not 0b"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
            note = "supplier role; cannot prove misrouting via proforma 0b"
    elif agrees and not multiparty:
        classification = "SAFE_SINGLE"
        note = "single independent client cid matches batch packing row"
    elif multiparty or mismatch:
        if zero_b_reachable and not fixture:
            # Need BOTH wrongness AND real-business 0b reachability
            real_drafts = [d for d in drafts_missing_cid if not d["fixture_name"]]
            if real_drafts and (mismatch or multiparty):
                classification = "POTENTIALLY_MISROUTING"
                note = (
                    "independent doc cids disagree with batch row AND "
                    "editable draft(s) missing client_contractor_id with 0a miss"
                )
            elif zero_b_reachable and (mismatch or multiparty):
                classification = "ORPHANED_TEST_DATA" if all(
                    d["fixture_name"] for d in drafts_missing_cid
                ) else "POTENTIALLY_MISROUTING"
                note = "0b reachable; drafts appear fixture" if classification == "ORPHANED_TEST_DATA" else note
            else:
                classification = "STALE_BUT_MASKED"
                note = "multiparty/mismatch but 0b not reachable (0a/0-pre covers)"
        else:
            classification = "STALE_BUT_MASKED"
            note = "multiparty or mismatch but step 0b not reachable for editable drafts"
    elif no_indep:
        if zero_b_reachable and not fixture:
            real_drafts = [d for d in drafts_missing_cid if not d["fixture_name"]]
            if real_drafts:
                # Cannot prove row WRONG without independent evidence → not a mutation candidate
                classification = "INSUFFICIENT_EVIDENCE"
                note = (
                    "0b reachable but no independent per-doc cid to prove row wrong "
                    "(mutation requires BOTH wrongness proof and 0b reachability)"
                )
            else:
                classification = "ORPHANED_TEST_DATA"
                note = "0b reachable only for fixture-named drafts; no indep doc cids"
        elif zero_b_reachable and fixture:
            classification = "ORPHANED_TEST_DATA"
            note = "fixture batch; 0b structurally reachable"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
            note = "no independent per-document contractor ids"
    else:
        classification = "INSUFFICIENT_EVIDENCE"
        note = "unclassified residual"

    mutation_candidate = (
        classification == "POTENTIALLY_MISROUTING"
        and not fixture
        and role == "client"
        and zero_b_reachable
        and (mismatch or multiparty)
        and any(not d["fixture_name"] for d in drafts_missing_cid)
    )

    return {
        "batch_id": batch_id,
        "role": role,
        "stored_contractor_id": stored,
        "status": status,
        "confidence": conf,
        "reason": reason,
        "distinct_independent_cids": sorted(indep),
        "independent_cid_count": len(indep),
        "sales_doc_cids": sorted(sales_cids),
        "multiparty": multiparty,
        "mismatch": mismatch,
        "agrees_single": agrees,
        "is_fixture_batch": fixture,
        "zero_a_sales_cids_present": bool(sales_cids),
        "zero_b_reachable": zero_b_reachable,
        "drafts_with_cid_count": len(drafts_with_cid),
        "drafts_missing_cid": drafts_missing_cid,
        "drafts_with_cid": drafts_with_cid[:10],
        "classification": classification,
        "note": note,
        "mutation_candidate": mutation_candidate,
    }


def main() -> int:
    prod_sha = Path(r"C:\PZ\version.txt").read_text(encoding="utf-8").strip()
    rows = load_packing_rows()
    client_docs = doc_cids_by_batch("client")
    supplier_docs = doc_cids_by_batch("supplier")
    sales_cids = sales_doc_client_cids()
    drafts = load_drafts()

    classified = []
    for row in rows:
        role = row.get("role") or ""
        bid = row.get("batch_id") or ""
        doc_set = client_docs.get(bid, set()) if role == "client" else supplier_docs.get(bid, set())
        sales_set = sales_cids.get(bid, set()) if role == "client" else set()
        classified.append(classify_row(row, doc_set, sales_set, drafts))

    counts = Counter(r["classification"] for r in classified)
    mutation_candidates = [r for r in classified if r["mutation_candidate"]]
    real_exposure = [
        r for r in classified
        if r["classification"] == "POTENTIALLY_MISROUTING" and not r["is_fixture_batch"]
    ]
    zero_b_count = sum(1 for r in classified if r["zero_b_reachable"])

    # Reproduce resolution chain RO for each real POTENTIALLY_MISROUTING
    chain_proofs = []
    sys.path.insert(0, r"C:\PZ")
    try:
        from app.services.customer_resolution_authority import (
            derive_customer_authority_for_draft,
            derive_customer_resolution_via_packing,
        )
        cm_path = STORAGE / "customer_master.sqlite"
        for r in real_exposure + [
            x for x in classified
            if x["classification"] == "POTENTIALLY_MISROUTING" and x["is_fixture_batch"]
        ]:
            for d in r["drafts_missing_cid"]:
                per_doc = derive_customer_authority_for_draft(
                    batch_id=r["batch_id"],
                    client_name=d["client_name"],
                    documents_db_path=DOCS_DB,
                    customer_master_db_path=cm_path,
                    client_contractor_id=d.get("client_contractor_id") or "",
                )
                packing = derive_customer_resolution_via_packing(
                    batch_id=r["batch_id"],
                    client_name=d["client_name"],
                    customer_master_db_path=cm_path,
                    packing_resolution_db_path=PR_DB,
                )
                chain_proofs.append({
                    "batch_id": r["batch_id"],
                    "draft_id": d["id"],
                    "client_name": d["client_name"],
                    "fixture_name": d["fixture_name"],
                    "step_0a_result": None if per_doc is None else {
                        "wfirma_customer_id": per_doc.get("wfirma_customer_id"),
                        "match_strategy": per_doc.get("match_strategy"),
                    },
                    "step_0b_result": None if packing is None else {
                        "wfirma_customer_id": packing.get("wfirma_customer_id"),
                        "match_strategy": packing.get("match_strategy"),
                    },
                    "0b_would_apply": per_doc is None and packing is not None,
                })
    except Exception as exc:
        chain_proofs.append({"error": str(exc)})

    # Re-filter mutation candidates: require chain proof 0b_would_apply on real draft
    proven_candidates = []
    for r in mutation_candidates:
        proofs = [
            p for p in chain_proofs
            if p.get("batch_id") == r["batch_id"]
            and p.get("0b_would_apply")
            and not p.get("fixture_name")
        ]
        if proofs:
            proven_candidates.append({
                **{k: r[k] for k in (
                    "batch_id", "role", "stored_contractor_id", "status",
                    "confidence", "reason", "distinct_independent_cids",
                    "classification", "note",
                )},
                "affected_drafts": proofs,
                "authoritative_action": (
                    "DELETE or REPLACE packing_contractor_resolution row "
                    "after operator authorization + B-019 backup checkpoint"
                ),
            })

    report = {
        "campaign": "B-021",
        "mode": "READ_ONLY",
        "mutation_performed": False,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "production_app_sha": prod_sha,
        "storage_root": str(STORAGE),
        "evidence_precedence": [
            "shipment_documents.*_contractor_id",
            "proforma_drafts.client_contractor_id",
            "sales_documents→shipment_documents (0a inputs)",
            "packing_contractor_resolution (UNDER AUDIT)",
            "customer_master/names (supporting only)",
        ],
        "population_count": len(classified),
        "classification_counts": dict(counts),
        "zero_b_reachable_count": zero_b_count,
        "real_business_potentially_misrouting_count": len(real_exposure),
        "mutation_candidate_count": len(proven_candidates),
        "mutation_candidates": proven_candidates,
        "chain_proofs": chain_proofs,
        "rows": classified,
    }

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    CAND_JSON.write_text(
        json.dumps(
            {
                "execute": False,
                "candidates": proven_candidates,
                "note": (
                    "Empty list means no mutation campaign required."
                    if not proven_candidates
                    else "DATA_MUTATION_HOLD — operator authorization required."
                ),
                "production_app_sha": prod_sha,
                "assessed_at": report["assessed_at"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("POPULATION", len(classified))
    print("COUNTS", dict(counts))
    print("ZERO_B_REACHABLE", zero_b_count)
    print("REAL_POTENTIALLY_MISROUTING", len(real_exposure))
    print("MUTATION_CANDIDATES", len(proven_candidates))
    for c in proven_candidates:
        print("CANDIDATE", c["batch_id"], c["stored_contractor_id"], c.get("affected_drafts"))
    print("WROTE", OUT_JSON)
    print("WROTE", CAND_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

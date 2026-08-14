"""
customer_external_enrichment.py — Client Master external enrichment (Cowork research).

Authority model
---------------
The Customer Master (customer_master_db.py + routes_customer_master.py) stays the
ONLY authority for customer data. This module owns a separate research-task /
proposal / evidence store (customer_enrichment.sqlite) and the acceptance flow.
Claude Cowork is a RESEARCHER, never a writer: the only Customer Master mutation
is `accept_enrichment_proposal`, which goes through
`customer_master_db.update_enrichment_fields` (fill-when-empty, six columns only)
and writes a master_audit row via `audit_safe`.

Phase 1 scope: missing-data only. An existing non-empty canonical value always
wins — acceptance of a proposal for a now-filled field sets conflict_flag and
never overwrites. Staleness is detected via a SHA-256 fingerprint of the six
researchable fields captured at task creation.

Research results are UNTRUSTED input (prompt-injection surface): every
submission passes `validate_enrichment_submission` regardless of what the MCP
inputSchema already rejected.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.audit import audit_safe
from ..core.logging import get_logger
from .customer_master_db import (
    CustomerMaster,
    get_customer,
    update_enrichment_fields,
)

log = get_logger(__name__)


# ── Field classification (single source of truth — pinned by tests) ──────────

#: The ONLY fields Cowork may research and propose in phase 1.
RESEARCHABLE_PHASE_1 = frozenset({
    "bill_to_street",
    "bill_to_city",
    "bill_to_postal_code",
    "bill_to_phone",
    "bill_to_email",
    "industry",
})

#: Read-only identity keys disclosed to the researcher (plus the current values
#: of the six researchable fields). Nothing else, ever.
IDENTITY_CONTEXT_ONLY = frozenset({
    "bill_to_contractor_id",
    "bill_to_name",
    "country",
    "nip",
    "vat_eu_number",
})

#: Never serialized into any enrichment payload, task, or MCP response.
SENSITIVE_NEVER_DISCLOSE = frozenset({
    "bank_account",
    "credit_limit", "credit_currency",
    "kuke_approved", "kuke_limit", "kuke_currency", "kuke_expiry_date",
    "kuke_policy_number", "kuke_self_retention_pct",
    "risk_status", "payment_terms_days",
    "kyc_status", "kyc_approved_on", "kyc_expiry",
    "beneficial_owner", "owner_id_type", "owner_id_number",
    "aml_risk_rating", "pep_check_result", "compliance_notes", "notes",
    "preferred_payment_method", "preferred_proforma_series_id",
    "preferred_invoice_series_id", "preferred_wdt_invoice_series_id",
    "preferred_export_invoice_series_id",
    "freight_service_id", "freight_last_amount", "freight_avg_amount",
    "freight_currency", "freight_mode", "freight_fixed_amount_eur",
    "freight_fixed_amount_usd", "freight_label_pl", "freight_label_en",
    "insurance_service_id", "insurance_min_amount", "insurance_min_override",
    "insurance_rate", "insurance_mode", "insurance_fixed_amount_eur",
    "insurance_fixed_amount_usd", "insurance_min_eur", "insurance_min_usd",
    "insurance_label_pl", "insurance_label_en", "insurance_enabled",
    "vat_mode", "default_incoterm", "default_currency", "default_language_id",
})

#: Explicitly out of scope for phase 1 (documented, not wired anywhere).
DEFERRED_PHASE_2 = frozenset({
    "eori", "regon", "vat_eu_valid", "vat_eu_validated_at",
    "bill_to_mobile", "short_code", "client_type",
    "ship_to_use_alternate", "ship_to_name", "ship_to_street", "ship_to_city",
    "ship_to_zip", "ship_to_country", "ship_to_phone", "ship_to_email",
    "ship_to_contractor_id",
})

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low", "none"})
SOURCE_TYPES = frozenset({
    "registry", "official_website", "vat_authority", "directory", "other",
})

TASK_STATUSES = frozenset({
    "pending", "researching", "proposed", "no_result", "failed",
    "partially_verified", "accepted", "partially_accepted", "rejected", "stale",
})

_MAX_VALUE_LEN = 500
_MAX_REASON_LEN = 1000
_MAX_URL_LEN = 2048
_MAX_TITLE_LEN = 500
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EnrichmentValidationError(ValueError):
    """A submitted research result failed fail-closed validation."""


class StaleProposalError(Exception):
    """Canonical customer changed since the research snapshot (→ HTTP 409)."""


class ProposalStateError(Exception):
    """Proposal/task is not in a state that permits the operation (→ HTTP 409)."""


# ── DB plumbing (same idiom as customer_master_db._connect) ──────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def init_enrichment_db(db_path: Path) -> None:
    """Create the enrichment tables idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_enrichment_tasks (
                id               TEXT PRIMARY KEY,
                contractor_id    TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'pending',
                missing_fields   TEXT NOT NULL,
                snapshot_json    TEXT NOT NULL,
                snapshot_fp      TEXT NOT NULL,
                identity_context TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                created_by       TEXT,
                completed_at     TEXT,
                error            TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enrichment_tasks_contractor
            ON customer_enrichment_tasks (contractor_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enrichment_tasks_status
            ON customer_enrichment_tasks (status)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_enrichment_proposals (
                id             TEXT PRIMARY KEY,
                task_id        TEXT NOT NULL REFERENCES customer_enrichment_tasks(id),
                field          TEXT NOT NULL,
                proposed_value TEXT,
                confidence     TEXT NOT NULL DEFAULT 'none',
                reason         TEXT,
                field_status   TEXT NOT NULL DEFAULT 'pending',
                decided_by     TEXT,
                decided_at     TEXT,
                conflict_flag  INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enrichment_proposals_task
            ON customer_enrichment_proposals (task_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_enrichment_evidence (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id  TEXT NOT NULL REFERENCES customer_enrichment_proposals(id),
                source_url   TEXT NOT NULL,
                source_title TEXT,
                source_type  TEXT NOT NULL DEFAULT 'other',
                retrieved_at TEXT,
                created_at   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enrichment_evidence_proposal
            ON customer_enrichment_evidence (proposal_id)
        """)
        conn.commit()
    finally:
        conn.close()


# ── Snapshot / disclosure serialization ──────────────────────────────────────

def _six_field_snapshot(customer: CustomerMaster) -> Dict[str, Optional[str]]:
    return {
        f: (getattr(customer, f, None) or None)
        for f in sorted(RESEARCHABLE_PHASE_1)
    }


def compute_snapshot_fingerprint(customer: CustomerMaster) -> str:
    """SHA-256 staleness key over the six researchable fields."""
    payload = json.dumps(_six_field_snapshot(customer), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_identity_context(customer: CustomerMaster) -> Dict[str, Optional[str]]:
    """Explicit key-by-key allowlist serializer — NEVER a row dump.

    Output keys are EXACTLY IDENTITY_CONTEXT_ONLY ∪ RESEARCHABLE_PHASE_1
    (11 keys). Anything in SENSITIVE_NEVER_DISCLOSE can never appear here
    because keys are enumerated literally, not derived from the dataclass.
    """
    ctx: Dict[str, Optional[str]] = {
        "bill_to_contractor_id": customer.bill_to_contractor_id,
        "bill_to_name":          customer.bill_to_name,
        "country":               customer.country,
        "nip":                   customer.nip,
        "vat_eu_number":         customer.vat_eu_number,
    }
    ctx.update(_six_field_snapshot(customer))
    return ctx


# ── Task lifecycle ───────────────────────────────────────────────────────────

def build_customer_enrichment_task(
    contractor_id: str,
    cm_db: Path,
    enrich_db: Path,
    *,
    actor: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Create a `pending` research task for a customer's missing fields.

    Returns None when the customer has no missing researchable fields
    (zero-work — the caller reports `no_missing_fields`). Raises KeyError
    when the contractor does not exist.
    """
    customer = get_customer(cm_db, contractor_id)
    if customer is None:
        raise KeyError(f"Customer not found: {contractor_id}")

    missing = [f for f in sorted(RESEARCHABLE_PHASE_1)
               if not (getattr(customer, f, None) or "").strip()]
    if not missing:
        return None

    init_enrichment_db(enrich_db)
    task_id = str(uuid.uuid4())
    now = _now_iso()
    snapshot = _six_field_snapshot(customer)
    row = {
        "id": task_id,
        "contractor_id": customer.bill_to_contractor_id,
        "status": "pending",
        "missing_fields": json.dumps(missing),
        "snapshot_json": json.dumps(snapshot, sort_keys=True, default=str),
        "snapshot_fp": compute_snapshot_fingerprint(customer),
        "identity_context": json.dumps(_build_identity_context(customer),
                                       sort_keys=True, default=str),
        "created_at": now,
        "created_by": actor,
    }
    conn = _connect(enrich_db)
    try:
        conn.execute(
            """INSERT INTO customer_enrichment_tasks
               (id, contractor_id, status, missing_fields, snapshot_json,
                snapshot_fp, identity_context, created_at, created_by)
               VALUES (:id, :contractor_id, :status, :missing_fields,
                       :snapshot_json, :snapshot_fp, :identity_context,
                       :created_at, :created_by)""",
            row,
        )
        conn.commit()
    finally:
        conn.close()
    log.info("enrichment_task_created task_id=%s contractor_id=%s missing=%s",
             task_id, contractor_id, missing)
    return _task_dict(row, missing, snapshot)


def _task_dict(row: Any, missing: Optional[List[str]] = None,
               snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = dict(row)
    d["missing_fields"] = (missing if missing is not None
                           else json.loads(d["missing_fields"]))
    d["snapshot"] = (snapshot if snapshot is not None
                     else json.loads(d.pop("snapshot_json")))
    d.pop("snapshot_json", None)
    d["identity_context"] = (json.loads(d["identity_context"])
                             if isinstance(d.get("identity_context"), str)
                             else d.get("identity_context"))
    return d


def claim_enrichment_task(enrich_db: Path,
                          task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Claim a task for research: `pending` → `researching`.

    With task_id: claim that task (ProposalStateError if not pending —
    except an already-`researching` task is returned as-is, so a retried
    MCP call is idempotent). Without: atomically claim the oldest pending
    task (BEGIN IMMEDIATE guards the read-then-update against a concurrent
    claimer). Returns None when nothing is pending.
    """
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if task_id is not None:
            row = conn.execute(
                "SELECT * FROM customer_enrichment_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Task not found: {task_id}")
            if row["status"] == "researching":
                conn.rollback()
                return _task_dict(row)
            if row["status"] != "pending":
                conn.rollback()
                raise ProposalStateError(
                    f"Task {task_id} is {row['status']}, not claimable")
        else:
            row = conn.execute(
                """SELECT * FROM customer_enrichment_tasks
                   WHERE status = 'pending' ORDER BY created_at LIMIT 1""",
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
        cur = conn.execute(
            """UPDATE customer_enrichment_tasks SET status = 'researching'
               WHERE id = ? AND status = 'pending'""",
            (row["id"],),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
    finally:
        conn.close()
    claimed = _task_dict(row)
    claimed["status"] = "researching"
    return claimed


# ── Submission validation (fail-closed; untrusted input) ─────────────────────

def _clean_text(value: Any, max_len: int, label: str) -> str:
    if not isinstance(value, str):
        raise EnrichmentValidationError(f"{label} must be a string")
    cleaned = _CONTROL_CHARS_RE.sub("", value).strip()
    if len(cleaned) > max_len:
        raise EnrichmentValidationError(
            f"{label} exceeds {max_len} characters")
    return cleaned


def validate_enrichment_submission(
    proposals: Any,
    allowed_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Validate an untrusted research submission. Raises EnrichmentValidationError.

    Rules (fail closed):
      - proposals must be a non-empty list of objects
      - field must be in RESEARCHABLE_PHASE_1 (and in allowed_fields when given)
      - no duplicate fields in one submission
      - a non-null proposed_value requires >= 1 evidence entry
      - evidence source_url must be http(s), <= 2048 chars
      - length caps on value/reason/title; control chars stripped
      - confidence must be one of CONFIDENCE_LEVELS
      - null proposed_value with no evidence is VALID (= not_verified)
    """
    if not isinstance(proposals, list) or not proposals:
        raise EnrichmentValidationError("proposals must be a non-empty list")
    seen_fields: set = set()
    validated: List[Dict[str, Any]] = []
    for i, item in enumerate(proposals):
        if not isinstance(item, dict):
            raise EnrichmentValidationError(f"proposals[{i}] must be an object")
        field = item.get("field")
        if field not in RESEARCHABLE_PHASE_1:
            raise EnrichmentValidationError(
                f"proposals[{i}].field {field!r} is not a researchable field")
        if allowed_fields is not None and field not in allowed_fields:
            raise EnrichmentValidationError(
                f"proposals[{i}].field {field!r} was not requested by this task")
        if field in seen_fields:
            raise EnrichmentValidationError(
                f"proposals[{i}].field {field!r} appears more than once")
        seen_fields.add(field)

        raw_value = item.get("proposed_value")
        value: Optional[str] = None
        if raw_value is not None:
            value = _clean_text(raw_value, _MAX_VALUE_LEN,
                                f"proposals[{i}].proposed_value")
            if not value:
                value = None
        if value is not None and field == "bill_to_email":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
                raise EnrichmentValidationError(
                    f"proposals[{i}].proposed_value is not a valid email")

        confidence = item.get("confidence", "none")
        if confidence not in CONFIDENCE_LEVELS:
            raise EnrichmentValidationError(
                f"proposals[{i}].confidence {confidence!r} invalid "
                f"(allowed: {sorted(CONFIDENCE_LEVELS)})")

        reason = item.get("reason")
        if reason is not None:
            reason = _clean_text(reason, _MAX_REASON_LEN,
                                 f"proposals[{i}].reason") or None

        raw_evidence = item.get("evidence") or []
        if not isinstance(raw_evidence, list):
            raise EnrichmentValidationError(
                f"proposals[{i}].evidence must be a list")
        evidence: List[Dict[str, Any]] = []
        for j, ev in enumerate(raw_evidence):
            if not isinstance(ev, dict):
                raise EnrichmentValidationError(
                    f"proposals[{i}].evidence[{j}] must be an object")
            url = _clean_text(ev.get("source_url"), _MAX_URL_LEN,
                              f"proposals[{i}].evidence[{j}].source_url")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise EnrichmentValidationError(
                    f"proposals[{i}].evidence[{j}].source_url must be http(s)")
            title = ev.get("source_title")
            if title is not None:
                title = _clean_text(
                    title, _MAX_TITLE_LEN,
                    f"proposals[{i}].evidence[{j}].source_title") or None
            source_type = ev.get("source_type", "other")
            if source_type not in SOURCE_TYPES:
                raise EnrichmentValidationError(
                    f"proposals[{i}].evidence[{j}].source_type "
                    f"{source_type!r} invalid (allowed: {sorted(SOURCE_TYPES)})")
            retrieved_at = ev.get("retrieved_at")
            if retrieved_at is not None:
                retrieved_at = _clean_text(
                    retrieved_at, 64,
                    f"proposals[{i}].evidence[{j}].retrieved_at") or None
            evidence.append({
                "source_url": url, "source_title": title,
                "source_type": source_type, "retrieved_at": retrieved_at,
            })

        if value is not None and not evidence:
            raise EnrichmentValidationError(
                f"proposals[{i}] proposes a value for {field!r} with no "
                f"evidence — evidence is required for every non-null value")

        validated.append({
            "field": field, "proposed_value": value,
            "confidence": confidence, "reason": reason, "evidence": evidence,
        })
    return validated


def submit_enrichment_result(enrich_db: Path, task_id: str,
                             proposals: Any) -> Dict[str, Any]:
    """Store validated research proposals. Task must be `researching`.

    Task → `proposed` when at least one non-null value was proposed,
    else `no_result`. A validation failure marks the task `failed`
    (error recorded) and re-raises.
    """
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        task = conn.execute(
            "SELECT * FROM customer_enrichment_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] != "researching":
            raise ProposalStateError(
                f"Task {task_id} is {task['status']!r}; results are only "
                f"accepted while researching")
        missing = json.loads(task["missing_fields"])
        try:
            validated = validate_enrichment_submission(
                proposals, allowed_fields=missing)
        except EnrichmentValidationError as exc:
            now = _now_iso()
            conn.execute(
                """UPDATE customer_enrichment_tasks
                   SET status = 'failed', error = ?, completed_at = ?
                   WHERE id = ?""",
                (str(exc)[:500], now, task_id),
            )
            conn.commit()
            raise

        now = _now_iso()
        any_value = False
        for p in validated:
            proposal_id = str(uuid.uuid4())
            if p["proposed_value"] is not None:
                any_value = True
            conn.execute(
                """INSERT INTO customer_enrichment_proposals
                   (id, task_id, field, proposed_value, confidence, reason,
                    field_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (proposal_id, task_id, p["field"], p["proposed_value"],
                 p["confidence"], p["reason"], now),
            )
            for ev in p["evidence"]:
                conn.execute(
                    """INSERT INTO customer_enrichment_evidence
                       (proposal_id, source_url, source_title, source_type,
                        retrieved_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (proposal_id, ev["source_url"], ev["source_title"],
                     ev["source_type"], ev["retrieved_at"], now),
                )
        new_status = "proposed" if any_value else "no_result"
        conn.execute(
            """UPDATE customer_enrichment_tasks
               SET status = ?, completed_at = ? WHERE id = ?""",
            (new_status, now, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("enrichment_result_submitted task_id=%s proposals=%d status=%s",
             task_id, len(validated), new_status)
    return {"task_id": task_id, "status": new_status,
            "proposal_count": len(validated)}


# ── Operator decisions (the ONLY Customer Master write path) ─────────────────

def _load_proposal(conn: sqlite3.Connection, proposal_id: str) -> Any:
    row = conn.execute(
        """SELECT p.*, t.contractor_id, t.snapshot_fp, t.id AS t_id
           FROM customer_enrichment_proposals p
           JOIN customer_enrichment_tasks t ON t.id = p.task_id
           WHERE p.id = ?""",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Proposal not found: {proposal_id}")
    return row


def _recompute_task_status(conn: sqlite3.Connection, task_id: str) -> str:
    counts = conn.execute(
        """SELECT
             SUM(CASE WHEN field_status = 'pending'  THEN 1 ELSE 0 END) AS pending,
             SUM(CASE WHEN field_status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
             SUM(CASE WHEN field_status = 'rejected' THEN 1 ELSE 0 END) AS rejected
           FROM customer_enrichment_proposals WHERE task_id = ?""",
        (task_id,),
    ).fetchone()
    pending = counts["pending"] or 0
    accepted = counts["accepted"] or 0
    rejected = counts["rejected"] or 0
    if pending > 0:
        status = "partially_verified" if (accepted or rejected) else "proposed"
    elif accepted and rejected:
        status = "partially_accepted"
    elif accepted:
        status = "accepted"
    else:
        status = "rejected"
    conn.execute(
        "UPDATE customer_enrichment_tasks SET status = ? WHERE id = ?",
        (status, task_id),
    )
    return status


def accept_enrichment_proposal(
    enrich_db: Path,
    cm_db: Path,
    proposal_id: str,
    *,
    actor: Optional[str] = None,
    request: Any = None,
) -> Dict[str, Any]:
    """Accept one proposal — the ONLY Customer Master mutation in this module.

    Staleness: recompute the six-field fingerprint from the CURRENT customer;
    mismatch with the task snapshot → StaleProposalError (route: 409
    ENRICHMENT_PROPOSAL_STALE) and the task is marked `stale`.

    Conflict: if the target field is meanwhile non-empty, the proposal is
    decided with conflict_flag=1 and the Customer Master is NOT written —
    an existing canonical value always wins.
    """
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        row = _load_proposal(conn, proposal_id)
        if row["field_status"] != "pending":
            raise ProposalStateError(
                f"Proposal {proposal_id} already {row['field_status']}")
        if row["proposed_value"] is None:
            raise ProposalStateError(
                f"Proposal {proposal_id} is not_verified (null value) — "
                f"nothing to accept")

        customer = get_customer(cm_db, row["contractor_id"])
        if customer is None:
            raise KeyError(f"Customer not found: {row['contractor_id']}")
        if compute_snapshot_fingerprint(customer) != row["snapshot_fp"]:
            conn.execute(
                "UPDATE customer_enrichment_tasks SET status = 'stale' WHERE id = ?",
                (row["task_id"],),
            )
            conn.commit()
            raise StaleProposalError(
                f"Customer {row['contractor_id']} changed since research "
                f"snapshot for task {row['task_id']}")

        field = row["field"]
        current = (getattr(customer, field, None) or "").strip()
        now = _now_iso()
        wrote = False
        conflict = bool(current)
        if conflict:
            log.warning(
                "enrichment_accept_conflict proposal_id=%s field=%s — canonical "
                "value present, NOT overwritten", proposal_id, field)
        else:
            wrote = update_enrichment_fields(
                cm_db, row["contractor_id"], {field: row["proposed_value"]},
                last_enrichment_at=now,
            )
            if not wrote:
                raise KeyError(f"Customer not found: {row['contractor_id']}")
            audit_safe(
                "customers", "update", row["contractor_id"],
                request=request, actor=actor,
                before={field: getattr(customer, field, None)},
                after={
                    "field": field,
                    "value": row["proposed_value"],
                    "task_id": row["task_id"],
                    "proposal_id": proposal_id,
                    "source": "external_enrichment",
                    "confidence": row["confidence"],
                },
                reason=f"enrichment_proposal:{proposal_id}",
            )

        conn.execute(
            """UPDATE customer_enrichment_proposals
               SET field_status = 'accepted', decided_by = ?, decided_at = ?,
                   conflict_flag = ?
               WHERE id = ?""",
            (actor, now, 1 if conflict else 0, proposal_id),
        )
        task_status = _recompute_task_status(conn, row["task_id"])
        conn.commit()
    finally:
        conn.close()
    log.info("enrichment_proposal_accepted proposal_id=%s wrote=%s conflict=%s",
             proposal_id, wrote, conflict)
    return {
        "proposal_id": proposal_id, "field_status": "accepted",
        "conflict_flag": conflict, "wrote_to_master": wrote,
        "task_status": task_status,
    }


def reject_enrichment_proposal(enrich_db: Path, proposal_id: str,
                               *, actor: Optional[str] = None) -> Dict[str, Any]:
    """Reject one proposal. No Customer Master write; the proposal row is the record."""
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        row = _load_proposal(conn, proposal_id)
        if row["field_status"] != "pending":
            raise ProposalStateError(
                f"Proposal {proposal_id} already {row['field_status']}")
        conn.execute(
            """UPDATE customer_enrichment_proposals
               SET field_status = 'rejected', decided_by = ?, decided_at = ?
               WHERE id = ?""",
            (actor, _now_iso(), proposal_id),
        )
        task_status = _recompute_task_status(conn, row["task_id"])
        conn.commit()
    finally:
        conn.close()
    return {"proposal_id": proposal_id, "field_status": "rejected",
            "task_status": task_status}


# ── Reads for UI / MCP status ────────────────────────────────────────────────

def get_enrichment_for_contractor(enrich_db: Path,
                                  contractor_id: str) -> Optional[Dict[str, Any]]:
    """Latest task (+ proposals + evidence) for a contractor, or None."""
    if not enrich_db.exists():
        return None
    conn = _connect(enrich_db)
    try:
        task = conn.execute(
            """SELECT * FROM customer_enrichment_tasks
               WHERE contractor_id = ? ORDER BY created_at DESC LIMIT 1""",
            (contractor_id,),
        ).fetchone()
        if task is None:
            return None
        return _assemble_task(conn, task)
    finally:
        conn.close()


def get_enrichment_task(enrich_db: Path, task_id: str) -> Dict[str, Any]:
    """One task with proposals + evidence. KeyError when absent."""
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        task = conn.execute(
            "SELECT * FROM customer_enrichment_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        return _assemble_task(conn, task)
    finally:
        conn.close()


def _assemble_task(conn: sqlite3.Connection, task: Any) -> Dict[str, Any]:
    result = _task_dict(task)
    proposals = conn.execute(
        """SELECT * FROM customer_enrichment_proposals
           WHERE task_id = ? ORDER BY field""",
        (task["id"],),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for p in proposals:
        pd = dict(p)
        pd["conflict_flag"] = bool(pd.get("conflict_flag"))
        pd["evidence"] = [dict(e) for e in conn.execute(
            """SELECT source_url, source_title, source_type, retrieved_at
               FROM customer_enrichment_evidence
               WHERE proposal_id = ? ORDER BY id""",
            (p["id"],),
        ).fetchall()]
        out.append(pd)
    result["proposals"] = out
    return result


def get_enrichment_status(enrich_db: Path) -> Dict[str, Any]:
    """Canonical status contract (CLAUDE.md), derived entirely by query.

    `skipped` counts conflict-flagged accepts (zero-work research runs create
    no task row and therefore surface only in the run response, not here).
    """
    init_enrichment_db(enrich_db)
    conn = _connect(enrich_db)
    try:
        agg = conn.execute(
            """SELECT COUNT(*) AS total,
                      MAX(created_at) AS last_started,
                      MAX(completed_at) AS last_completed
               FROM customer_enrichment_tasks""",
        ).fetchone()
        by_status = {r["status"]: r["n"] for r in conn.execute(
            """SELECT status, COUNT(*) AS n
               FROM customer_enrichment_tasks GROUP BY status""",
        ).fetchall()}
        prop = conn.execute(
            """SELECT
                 SUM(CASE WHEN field_status = 'accepted' AND conflict_flag = 0
                          THEN 1 ELSE 0 END) AS wrote,
                 SUM(CASE WHEN field_status = 'accepted' AND conflict_flag = 1
                          THEN 1 ELSE 0 END) AS conflicts
               FROM customer_enrichment_proposals""",
        ).fetchone()
        last_err = conn.execute(
            """SELECT error FROM customer_enrichment_tasks
               WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 1""",
        ).fetchone()
        last_done = conn.execute(
            """SELECT created_at, completed_at FROM customer_enrichment_tasks
               WHERE completed_at IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1""",
        ).fetchone()
    finally:
        conn.close()

    duration_ms = None
    if last_done is not None:
        try:
            started = datetime.fromisoformat(last_done["created_at"])
            completed = datetime.fromisoformat(last_done["completed_at"])
            duration_ms = int((completed - started).total_seconds() * 1000)
        except (ValueError, TypeError):
            duration_ms = None

    last_started = agg["last_started"]
    last_completed = agg["last_completed"]
    running = bool(last_started and
                   (not last_completed or last_started > last_completed))
    errors = by_status.get("failed", 0)
    return {
        "healthy": last_err is None,
        "running": running,
        "last_started_at": last_started,
        "last_completed_at": last_completed,
        "duration_ms": duration_ms,
        "processed": agg["total"] or 0,
        "created": agg["total"] or 0,
        "updated": prop["wrote"] or 0,
        "skipped": prop["conflicts"] or 0,
        "errors": errors,
        "last_error": last_err["error"] if last_err is not None else None,
        "tasks_by_status": by_status,
    }


def has_open_task(enrich_db: Path, contractor_id: str) -> bool:
    """True when a pending/researching task already exists for this contractor."""
    if not enrich_db.exists():
        return False
    conn = _connect(enrich_db)
    try:
        row = conn.execute(
            """SELECT 1 FROM customer_enrichment_tasks
               WHERE contractor_id = ? AND status IN ('pending', 'researching')
               LIMIT 1""",
            (contractor_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ── Shared service (Business Feature Completeness) ───────────────────────────

def run_customer_enrichment(
    contractor_id: str,
    cm_db: Path,
    enrich_db: Path,
    *,
    trigger: str = "operator",
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """The one shared `run_<capability>()` — API and UI call this; a future
    scheduler would call it with trigger="scheduler". Phase 1 creates the
    research task only (research itself happens over MCP)."""
    task = build_customer_enrichment_task(
        contractor_id, cm_db, enrich_db, actor=actor)
    if task is None:
        return {"ok": True, "trigger": trigger, "task": None,
                "result": "no_missing_fields"}
    return {"ok": True, "trigger": trigger, "task": task,
            "result": "task_created"}

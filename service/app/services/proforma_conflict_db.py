"""
proforma_conflict_db.py — ADR-029 Proforma Workspace conflict store.

A **typed extension** of the ADR-025 soft-validation model (NOT a parallel
authority): the ``proforma_conflicts`` table records advisory drift/eligibility
findings against a proforma draft so the operator can acknowledge / override /
regenerate / accept / revert. No workflow gate becomes a hard block here — the
only hard gate (the wFirma write boundary) is wired in the post handler behind
``conflict_posting_blocker`` (ADR-029 §5), not in this store.

Schema (additive, nullable-tolerant) — exact fields per
``docs/proforma-workspace-consolidation-plan.md`` §6.1::

  conflict_id (PK) · proforma_id · conflict_type · severity (error|warning)
  · authority_owner · field_affected · current_value · master_value · reason
  · detected_at · status (open|acknowledged|resolved|reverted)
  · resolution_type (use_master_default|override_with_reason|regenerate_lines
                     |accept_and_proceed|revert)
  · resolution_reason · resolved_by · resolved_at

Every detection (``upsert_conflict``) and every resolution (``resolve_conflict``)
ALSO writes ``master_audit`` via ``audit_safe()`` with before/after — reusing the
existing audit authority (Invariant 4; no new audit system).

Read-only / local-only: this module never calls wFirma (ADR-021 Invariant 7).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.audit import audit_safe

# ── Controlled vocabularies (the conflict_type enum registers ALL 8 — the four
#    detectors implemented in PR-1 plus the four deferred to PR-2 so the store
#    schema and the route contract are stable from the first slice). ───────────
SEVERITIES = frozenset({"error", "warning"})

STATUS_OPEN         = "open"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED     = "resolved"
STATUS_REVERTED     = "reverted"
STATUSES = frozenset({STATUS_OPEN, STATUS_ACKNOWLEDGED, STATUS_RESOLVED, STATUS_REVERTED})

# Statuses that mean "the operator has acted" — a re-scan must NOT resurrect
# these into OPEN even if the drift persists (respects operator intent).
TERMINAL_STATUSES = frozenset({STATUS_RESOLVED, STATUS_REVERTED, STATUS_ACKNOWLEDGED})

RESOLUTION_TYPES = frozenset({
    "use_master_default",
    "override_with_reason",
    "regenerate_lines",
    "accept_and_proceed",
    "revert",
})

# resolution_type → resulting status
_RESOLUTION_STATUS = {
    "use_master_default":   STATUS_RESOLVED,
    "override_with_reason": STATUS_RESOLVED,
    "regenerate_lines":     STATUS_RESOLVED,
    "accept_and_proceed":   STATUS_ACKNOWLEDGED,
    "revert":               STATUS_REVERTED,
}

# The full conflict_type vocabulary (ADR-029 / plan §6.2). PR-1 implements the
# detectors for {3,4,5,8}; {1,2,6,7} are registered here but their detectors are
# deferred to PR-2 (see proforma_conflict_detector.IMPLEMENTED_CONFLICT_TYPES).
CONFLICT_TYPES = frozenset({
    "inventory_insufficient",            # 1  (detector deferred → PR-2)
    "sku_missing_or_discontinued",       # 2  (detector deferred → PR-2)
    "currency_vs_customer_default",      # 3  ✓ PR-1
    "bank_account_currency_unsupported", # 4  ✓ PR-1
    "customer_vat_eu_changed",           # 5  ✓ PR-1
    "customer_address_or_terms_changed", # 6  (detector deferred → PR-2)
    "product_hs_origin_uom_changed",     # 7  (detector deferred → PR-2)
    "service_charge_defaults_changed",   # 8  ✓ PR-1
})

_AUDIT_ENTITY = "proforma_conflict"


# ── Row model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProformaConflict:
    conflict_id:       int
    proforma_id:       str
    conflict_type:     str
    severity:          str
    authority_owner:   str
    field_affected:    str
    current_value:     Optional[str]
    master_value:      Optional[str]
    reason:            str
    detected_at:       str
    status:            str
    resolution_type:   Optional[str] = None
    resolution_reason: Optional[str] = None
    resolved_by:       Optional[str] = None
    resolved_at:       Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_conflict(row: sqlite3.Row) -> ProformaConflict:
    return ProformaConflict(
        conflict_id       = row["conflict_id"],
        proforma_id       = row["proforma_id"],
        conflict_type     = row["conflict_type"],
        severity          = row["severity"],
        authority_owner   = row["authority_owner"],
        field_affected    = row["field_affected"],
        current_value     = row["current_value"],
        master_value      = row["master_value"],
        reason            = row["reason"],
        detected_at       = row["detected_at"],
        status            = row["status"],
        resolution_type   = row["resolution_type"],
        resolution_reason = row["resolution_reason"],
        resolved_by       = row["resolved_by"],
        resolved_at       = row["resolved_at"],
    )


# ── DB lifecycle ─────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Create the table if missing. Idempotent. Safe to call on every access."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proforma_conflicts (
                conflict_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                proforma_id       TEXT NOT NULL,
                conflict_type     TEXT NOT NULL,
                severity          TEXT NOT NULL,
                authority_owner   TEXT NOT NULL,
                field_affected    TEXT NOT NULL,
                current_value     TEXT,
                master_value      TEXT,
                reason            TEXT NOT NULL,
                detected_at       TEXT NOT NULL,
                status            TEXT NOT NULL,
                resolution_type   TEXT,
                resolution_reason TEXT,
                resolved_by       TEXT,
                resolved_at       TEXT,
                UNIQUE(proforma_id, conflict_type, field_affected)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pconf_proforma "
            "ON proforma_conflicts(proforma_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pconf_status "
            "ON proforma_conflicts(proforma_id, status)"
        )
        conn.commit()


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_detection(
    conflict_type: str, severity: str, authority_owner: str,
    field_affected: str, reason: str,
) -> None:
    if conflict_type not in CONFLICT_TYPES:
        raise ValueError(f"unknown conflict_type {conflict_type!r}")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(SEVERITIES)}; got {severity!r}")
    if not (authority_owner or "").strip():
        raise ValueError("authority_owner is required")
    if not (field_affected or "").strip():
        raise ValueError("field_affected is required")
    if not (reason or "").strip():
        raise ValueError("reason is required")


# ── Detection write (advisory) ───────────────────────────────────────────────

def upsert_conflict(
    db_path: Path,
    *,
    proforma_id:     str,
    conflict_type:   str,
    severity:        str,
    authority_owner: str,
    field_affected:  str,
    current_value:   Optional[str],
    master_value:    Optional[str],
    reason:          str,
    actor:           Optional[str] = None,
) -> ProformaConflict:
    """Insert or refresh ONE advisory conflict.

    Idempotency key is ``(proforma_id, conflict_type, field_affected)``:

      • No existing row             → INSERT as ``open`` (audit op=create).
      • Existing row is open/...    → REFRESH current/master/reason/severity +
        (re-detected, not acted on)   detected_at, keep ``open`` (audit op=update).
      • Existing row is terminal    → LEAVE UNTOUCHED and return it. A re-scan
        (resolved/reverted/ack'd)     must not resurrect an operator decision.

    Never raises on audit failure (audit_safe contract); raises ValueError only
    on an invalid detection payload.
    """
    _validate_detection(conflict_type, severity, authority_owner, field_affected, reason)
    init_db(db_path)
    pid = (proforma_id or "").strip()
    if not pid:
        raise ValueError("proforma_id is required")

    now = _now_utc_iso()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM proforma_conflicts "
            "WHERE proforma_id=? AND conflict_type=? AND field_affected=?",
            (pid, conflict_type, field_affected),
        ).fetchone()

        if existing is not None and existing["status"] in TERMINAL_STATUSES:
            # Operator already acted — do not resurrect. Return as-is.
            return _row_to_conflict(existing)

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO proforma_conflicts
                    (proforma_id, conflict_type, severity, authority_owner,
                     field_affected, current_value, master_value, reason,
                     detected_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, conflict_type, severity, authority_owner, field_affected,
                 current_value, master_value, reason, now, STATUS_OPEN),
            )
            conn.commit()
            new_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM proforma_conflicts WHERE conflict_id=?", (new_id,),
            ).fetchone()
            out = _row_to_conflict(row)
            audit_safe(
                _AUDIT_ENTITY, "create", out.conflict_id,
                actor=actor, before=None, after=out.to_dict(),
                reason=f"conflict detected: {conflict_type} on {field_affected}",
            )
            return out

        # Existing open/non-terminal row → refresh detection facts.
        before = _row_to_conflict(existing).to_dict()
        conn.execute(
            """
            UPDATE proforma_conflicts
               SET severity=?, authority_owner=?, current_value=?,
                   master_value=?, reason=?, detected_at=?, status=?
             WHERE conflict_id=?
            """,
            (severity, authority_owner, current_value, master_value, reason,
             now, STATUS_OPEN, existing["conflict_id"]),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proforma_conflicts WHERE conflict_id=?",
            (existing["conflict_id"],),
        ).fetchone()
        out = _row_to_conflict(row)
        audit_safe(
            _AUDIT_ENTITY, "update", out.conflict_id,
            actor=actor, before=before, after=out.to_dict(),
            reason=f"conflict re-detected: {conflict_type} on {field_affected}",
        )
        return out


# ── Reads ────────────────────────────────────────────────────────────────────

def list_conflicts(
    db_path: Path,
    proforma_id: str,
    *,
    statuses: Optional[List[str]] = None,
) -> List[ProformaConflict]:
    """List conflicts for a proforma, newest first. Optional status filter."""
    init_db(db_path)
    pid = (proforma_id or "").strip()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM proforma_conflicts "
                f"WHERE proforma_id=? AND status IN ({placeholders}) "
                f"ORDER BY conflict_id DESC",
                (pid, *statuses),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proforma_conflicts WHERE proforma_id=? "
                "ORDER BY conflict_id DESC",
                (pid,),
            ).fetchall()
    return [_row_to_conflict(r) for r in rows]


def get_conflict(db_path: Path, conflict_id: int) -> Optional[ProformaConflict]:
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM proforma_conflicts WHERE conflict_id=?", (conflict_id,),
        ).fetchone()
    return _row_to_conflict(row) if row is not None else None


def has_open_blocking_conflict(db_path: Path, proforma_id: str) -> bool:
    """True iff at least one OPEN, error-severity conflict exists.

    This is the predicate the post handler consults behind
    ``conflict_posting_blocker`` (ADR-029 §5). Acknowledged warnings do NOT
    block; only OPEN + severity=error.
    """
    init_db(db_path)
    pid = (proforma_id or "").strip()
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM proforma_conflicts "
            "WHERE proforma_id=? AND status=? AND severity=?",
            (pid, STATUS_OPEN, "error"),
        ).fetchone()
    return bool(row and row[0] > 0)


# ── Resolution (operator action) ─────────────────────────────────────────────

def resolve_conflict(
    db_path: Path,
    conflict_id: int,
    *,
    resolution_type:   str,
    resolution_reason: Optional[str],
    resolved_by:       str,
    actor:             Optional[str] = None,
) -> ProformaConflict:
    """Apply an operator resolution to a conflict (audited, op=transition).

    Status mapping:
      use_master_default / override_with_reason / regenerate_lines → resolved
      accept_and_proceed                                           → acknowledged
      revert                                                       → reverted

    ``override_with_reason`` requires a non-empty ``resolution_reason``.
    Raises ValueError on unknown id / invalid resolution_type / missing reason.
    """
    if resolution_type not in RESOLUTION_TYPES:
        raise ValueError(
            f"resolution_type must be one of {sorted(RESOLUTION_TYPES)}; "
            f"got {resolution_type!r}"
        )
    if resolution_type == "override_with_reason" and not (resolution_reason or "").strip():
        raise ValueError("override_with_reason requires a non-empty resolution_reason")
    if not (resolved_by or "").strip():
        raise ValueError("resolved_by is required")

    init_db(db_path)
    new_status = _RESOLUTION_STATUS[resolution_type]
    now = _now_utc_iso()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM proforma_conflicts WHERE conflict_id=?", (conflict_id,),
        ).fetchone()
        if existing is None:
            raise ValueError(f"conflict_id {conflict_id} not found")
        before = _row_to_conflict(existing).to_dict()
        conn.execute(
            """
            UPDATE proforma_conflicts
               SET status=?, resolution_type=?, resolution_reason=?,
                   resolved_by=?, resolved_at=?
             WHERE conflict_id=?
            """,
            (new_status, resolution_type, resolution_reason, resolved_by, now,
             conflict_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proforma_conflicts WHERE conflict_id=?", (conflict_id,),
        ).fetchone()
    out = _row_to_conflict(row)
    audit_safe(
        _AUDIT_ENTITY, "transition", out.conflict_id,
        actor=actor or resolved_by, before=before, after=out.to_dict(),
        reason=f"conflict {resolution_type}: {resolution_reason or ''}".strip(),
    )
    return out

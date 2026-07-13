"""
core/audit.py — Unified master-data audit trail (Phase 0 scaffolding).

This module is ADDITIVE and STANDALONE. It does NOT touch any existing
business table, does NOT change any current write path, and is NOT wired
into any route in Phase 0. Phase 1 will wire it into the 8+ master-data
write endpoints.

Authority
=========
Owned by Master Data Service. NOT used by:
  - wFirma sync paths (they own their own audit trail)
  - PZ shipment audit (audit_persist.py owns that)
  - DHL clearance state engine (its own audit)

Storage
=======
SQLite file at ``settings.storage_root / "master_audit.sqlite"``.
Single table ``master_audit`` — append-only from the API surface.

Schema invariants
=================
- ``entity``     non-null string tag, e.g. "hs_codes", "customers"
- ``pk``         stringified primary key (composite keys are JSON-encoded)
- ``op``         one of: create | update | upsert | delete | soft_delete |
                          restore | transition
- ``actor``      who performed the op (API-key label or session username)
- ``request_id`` correlation id from ``X-Request-Id`` header (nullable)
- ``reason``     operator-supplied ``X-Change-Reason`` (nullable)
- ``before_json`` NULL on create; full row JSON otherwise
- ``after_json``  NULL on delete;  full row JSON otherwise
- ``diff_json``   field-level diff (NULL on pure create/delete)
- ``created_at``  ISO-8601 UTC, set by this module — clients cannot forge

Retention
=========
``settings.master_audit_retention_days`` (default 2557 = 7y + 2 leap days)
governs the documented retention policy. Purge tooling is intentionally
NOT implemented in Phase 0 — the constant exists so a future purge job
reads from a single source. Records older than the retention window are
NOT automatically removed.

Money / Decimal safety
======================
Pre-serialised dataclasses or dicts pass through ``json.dumps(default=str)``
so Decimal-as-string discipline (already enforced in ``master_data_db.py``)
is preserved through audit. No float coercion.

Concurrency
===========
SQLite ``BEGIN IMMEDIATE`` per write. The audit table is single-writer-safe
under the standard FastAPI/uvicorn worker model used by this service.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import settings

_log = logging.getLogger(__name__)


VALID_OPS = frozenset({
    "create", "update", "upsert",
    # Delete semantics:
    #   "delete"      — soft-delete (Phase 4A default for jewelry entities).
    #                   Also covers hard-delete on entities that have not yet
    #                   migrated to soft-delete (legacy 10).
    #   "soft_delete" — reserved synonym, retained for migration flexibility.
    #   "restore"     — undo a soft-delete.
    #   "hard_delete" — permanent removal; requires explicit flag + role.
    "delete", "soft_delete", "restore", "hard_delete",
    "transition",
    # User-management admin actions (auth authority) — recorded on the unified
    # trail so admin approvals / rejections / role promotions / (de)activations
    # are queryable by op. Additive; existing callers are unaffected.
    "approve", "reject", "role", "activate", "deactivate",
})


# ── Storage path ────────────────────────────────────────────────────────────

def audit_db_path() -> Path:
    """Resolved at call time — supports tests that monkey-patch storage_root."""
    return settings.storage_root / "master_audit.sqlite"


# ── Serialisation helpers ───────────────────────────────────────────────────

def _to_jsonable(obj: Any) -> Any:
    """dataclass → dict; everything else passes through json.dumps(default=str)."""
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj


def _dump(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(_to_jsonable(obj), default=str, sort_keys=True,
                      ensure_ascii=False)


def _field_diff(before: Any, after: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Compute a shallow field-level diff between two dicts/dataclasses.

    Returns ``{field: {"before": <v1>, "after": <v2>}}`` for every changed
    field. Returns None when either side is None (i.e. pure create/delete);
    those cases are already covered by before_json / after_json.
    """
    if before is None or after is None:
        return None
    b = _to_jsonable(before) or {}
    a = _to_jsonable(after) or {}
    if not isinstance(b, dict) or not isinstance(a, dict):
        return None
    keys = set(b.keys()) | set(a.keys())
    diff: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        # Skip housekeeping fields — they change on every write and are noise.
        if k in {"updated_at", "created_at"}:
            continue
        bv = b.get(k)
        av = a.get(k)
        if bv != av:
            diff[k] = {"before": bv, "after": av}
    return diff or None


# ── Schema init (idempotent) ────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS master_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity        TEXT    NOT NULL,
    pk            TEXT    NOT NULL,
    op            TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    request_id    TEXT,
    reason        TEXT,
    before_json   TEXT,
    after_json    TEXT,
    diff_json     TEXT,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_master_audit_entity_pk
    ON master_audit (entity, pk, created_at);
CREATE INDEX IF NOT EXISTS ix_master_audit_actor
    ON master_audit (actor, created_at);
CREATE INDEX IF NOT EXISTS ix_master_audit_created_at
    ON master_audit (created_at);
"""


def init_audit_db(path: Optional[Path] = None) -> Path:
    """Idempotent. Safe to call from every write path."""
    p = path or audit_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p) as cx:
        cx.executescript(_SCHEMA)
    return p


# ── Write ───────────────────────────────────────────────────────────────────

class AuditWriteError(RuntimeError):
    """Raised on validation failure inside write_audit. Routes should map
    this to a 500 — never silently swallow."""


def write_audit(
    entity:     str,
    op:         str,
    pk:         Any,
    actor:      str,
    before:     Any = None,
    after:      Any = None,
    request_id: Optional[str] = None,
    reason:     Optional[str] = None,
    *,
    db_path:    Optional[Path] = None,
) -> int:
    """
    Append one row to ``master_audit``. Returns the inserted id.

    Honors ``settings.master_audit_enabled``: when False, the call is a
    no-op and returns -1. This allows emergency disable via env flip
    without removing call sites.
    """
    if not settings.master_audit_enabled:
        return -1

    if not entity or not isinstance(entity, str):
        raise AuditWriteError("entity must be a non-empty string")
    if op not in VALID_OPS:
        raise AuditWriteError(f"op must be one of {sorted(VALID_OPS)}; got {op!r}")
    if pk is None or pk == "":
        raise AuditWriteError("pk must be non-empty")
    if not actor or not isinstance(actor, str):
        raise AuditWriteError("actor must be a non-empty string")

    # Composite PKs come in as dict/tuple — JSON-encode for stable comparison.
    pk_str = pk if isinstance(pk, str) else json.dumps(pk, default=str, sort_keys=True)

    before_json = _dump(before)
    after_json  = _dump(after)
    diff        = _field_diff(before, after)
    diff_json   = _dump(diff) if diff else None

    created_at  = datetime.now(timezone.utc).isoformat()

    path = init_audit_db(db_path)
    with sqlite3.connect(path) as cx:
        cx.execute("BEGIN IMMEDIATE")
        cur = cx.execute(
            """INSERT INTO master_audit
               (entity, pk, op, actor, request_id, reason,
                before_json, after_json, diff_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity, pk_str, op, actor, request_id, reason,
             before_json, after_json, diff_json, created_at),
        )
        cx.commit()
        return int(cur.lastrowid or 0)


# ── Read (used by Phase 1 GET /api/v1/master/audit) ─────────────────────────

def list_audit(
    *,
    entity:     Optional[str] = None,
    pk:         Optional[str] = None,
    actor:      Optional[str] = None,
    op:         Optional[str] = None,
    since:      Optional[str] = None,    # ISO-8601 lower bound (inclusive)
    until:      Optional[str] = None,    # ISO-8601 upper bound (exclusive)
    limit:      int = 200,
    offset:     int = 0,
    db_path:    Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Read-only query. Returns rows newest-first."""
    limit  = max(1, min(int(limit), 2000))
    offset = max(0, int(offset))
    path   = init_audit_db(db_path)

    where: List[str]  = []
    args:  List[Any]  = []
    if entity: where.append("entity = ?");   args.append(entity)
    if pk:     where.append("pk = ?");       args.append(pk)
    if actor:  where.append("actor = ?");    args.append(actor)
    if op:     where.append("op = ?");       args.append(op)
    if since:  where.append("created_at >= ?"); args.append(since)
    if until:  where.append("created_at < ?");  args.append(until)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with sqlite3.connect(path) as cx:
        cx.row_factory = sqlite3.Row
        rows = cx.execute(
            f"""SELECT id, entity, pk, op, actor, request_id, reason,
                       before_json, after_json, diff_json, created_at
                FROM master_audit
                {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?""",
            (*args, limit, offset),
        ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("before_json", "after_json", "diff_json"):
            v = d.get(k)
            d[k] = json.loads(v) if v else None
        out.append(d)
    return out


# ── Request integration helpers (Phase 1) ───────────────────────────────────

def actor_from_request(request: Any) -> str:
    """Resolve the actor string from a FastAPI Request.

    Priority:
      1. ``request.state.api_key_label`` if a previous middleware set it.
      2. Session cookie user (when present and decoded).
      3. Fallback constant ``"apikey:unknown"`` so audit rows always have
         a non-empty actor.
    """
    # (1) middleware-set label
    try:
        label = getattr(request.state, "api_key_label", None)
        if label:
            return str(label)
    except Exception:
        # request without .state should not happen; defensive only.
        pass

    # (2) session cookie → user (best-effort, never raise)
    try:
        cookie = request.cookies.get("pz_session") if hasattr(request, "cookies") else None
        if cookie:
            from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
            user = get_current_user_optional(pz_session=cookie)
            if user:
                # Prefer username/email, fall back to id.
                return str(user.get("username")
                           or user.get("email")
                           or user.get("id")
                           or "session:unknown")
    except Exception:
        pass

    return "apikey:unknown"


def request_id_from_request(request: Any) -> Optional[str]:
    """Extract X-Request-Id header (case-insensitive). Returns None when absent."""
    try:
        return request.headers.get("X-Request-Id") or request.headers.get("x-request-id")
    except Exception:
        return None


def reason_from_request(request: Any) -> Optional[str]:
    """Extract X-Change-Reason header. Returns None when absent."""
    try:
        return request.headers.get("X-Change-Reason") or request.headers.get("x-change-reason")
    except Exception:
        return None


def audit_safe(
    entity:     str,
    op:         str,
    pk:         Any,
    *,
    request:    Any = None,
    actor:      Optional[str] = None,
    before:     Any = None,
    after:      Any = None,
    request_id: Optional[str] = None,
    reason:     Optional[str] = None,
) -> int:
    """
    Phase 1 contract: audit failure MUST NOT corrupt the primary write.

    Wraps ``write_audit`` so any exception is caught, logged at ERROR level
    with the entity/op/pk context, and an int is returned:

      > 0   audit row id (success)
      = -1  audit disabled by feature flag, or write_audit returned -1
      = -2  audit failed; row not written; primary write is unaffected

    Callers invoke this AFTER the primary write has succeeded. They MUST NOT
    propagate -2 to the client — the primary response is returned as-is.
    """
    try:
        if request is not None:
            if actor is None:
                actor = actor_from_request(request)
            if request_id is None:
                request_id = request_id_from_request(request)
            if reason is None:
                reason = reason_from_request(request)
        if not actor:
            actor = "apikey:unknown"
        return write_audit(
            entity=entity, op=op, pk=pk, actor=actor,
            before=before, after=after,
            request_id=request_id, reason=reason,
        )
    except Exception as exc:  # noqa: BLE001 — intentional broad catch per contract
        _log.error(
            "master_audit_write_failed entity=%s op=%s pk=%s actor=%s err=%s",
            entity, op, pk, actor, exc, exc_info=True,
        )
        return -2


# ── Test/diagnostic helper (NOT a public API) ───────────────────────────────

def _new_request_id() -> str:
    """Convenience for callers that want a stable correlation id."""
    return uuid.uuid4().hex

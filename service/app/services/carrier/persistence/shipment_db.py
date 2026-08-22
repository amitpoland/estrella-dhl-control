"""
Idempotency store and state tracker for carrier shipments.

Caller provides db_path — no global state, no app startup init required.
One row per idempotency_key. State transitions are the only allowed mutations.

tracking_ref: originally excluded by design ("labels live in the label
store"), but that invariant forced the coordinator to RE-INVOKE the adapter
on completed-key replay — which, for the live adapter, booked brand-new DHL
shipments (2026-07-06 duplicate-AWB incident, 3 duplicate live AWBs).
Superseded by operator decision 2026-07-06: tracking_ref IS persisted at
COMPLETE so replays return the stored result with zero adapter calls.
insert_shipment() still rejects LIVE-mode *inserts* — the pre-adapter
PENDING anchor row carries no AWB; the ref arrives only via update_state().
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import FrozenSet, List, Optional, Sequence

from ..models.shipment import ShipmentMode, ShipmentResult, ShipmentState

TABLE = "carrier_shipments"
PRE_EXT_TABLE = "carrier_shipments__pre_ext"


class CarrierShipmentsSchemaError(RuntimeError):
    """Ambiguous or unsafe carrier_shipments schema state. Fail closed."""

_DDL = """
CREATE TABLE IF NOT EXISTS carrier_shipments (
    idempotency_key TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK(mode IN ('shadow', 'live', 'external')),
    state           TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
    error           TEXT,
    simulated       INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

# Phase 5 — additive columns.  Separate from _DDL so older DBs can be
# migrated at init_db() time without recreating the table.
_ADDITIVE_COLUMNS = [
    ("service_product", "TEXT"),       # carrier service code (e.g. EXPRESS_WORLDWIDE)
    ("dimensions_json", "TEXT"),       # JSON snapshot of ShipmentRequest.dimensions
    # JSON snapshot of the booking-time multi-package split. NULL means the
    # shipment was booked as one package from the scalar weight/dimensions —
    # it is NOT a missing parcel count, and nothing infers one.
    ("packages_json", "TEXT"),
    # Per-client shipment ownership.  One import batch is split into several
    # per-client proforma drafts (draft identity = (batch_id, client_name)); a
    # shipment belongs to exactly one client.  Nullable: legacy rows predate
    # this column and carry NULL — get_shipment_for_draft only attributes such
    # a row to a draft when the batch is unambiguously single-client.
    ("client_ref", "TEXT"),
    ("tracking_ref", "TEXT"),          # AWB / tracking number, written at COMPLETE
                                       # (2026-07-06 duplicate-AWB incident fix)
    # AWB logistics visibility — Proforma V2 Logistics tab summary fields
    ("weight_kg", "REAL"),
    ("declared_value", "REAL"),
    ("currency", "TEXT"),
    ("box_type_code", "TEXT"),         # Box Master profile chosen in the AWB modal
    # Local do-not-use control — an OPERATIONAL flag for duplicate/unused
    # labels. It is NOT a DHL cancellation/void (no DHL API call exists or is
    # made); the real AWB and its PDFs are preserved for audit.
    ("do_not_use", "INTEGER NOT NULL DEFAULT 0"),
    ("do_not_use_reason", "TEXT"),
    ("do_not_use_at", "TEXT"),
    ("do_not_use_by", "TEXT"),
    # Operator attribution (X-Operator) for the AWB booking. Written once at
    # the PENDING anchor insert and never mutated by a state transition, so the
    # audit trail always names the operator who initiated the real booking —
    # not whoever later replayed the idempotent request. NULL for legacy rows
    # booked before attribution existed (honest missing).
    ("booked_by", "TEXT"),
    # WHO WAS BILLED for transport, written once at the PENDING anchor beside
    # booked_by. Without these a receiver-paid booking is indistinguishable
    # afterwards from a sender-paid one, so a disputed carrier invoice has no
    # server-side evidence of the arrangement in force when it was booked.
    # The account is stored MASKED (last four) — enough to reconcile against a
    # DHL invoice, never enough to be a credential. NULL on legacy rows booked
    # before the payer decision existed: honest missing, not "sender".
    ("transport_payer", "TEXT"),
    ("billing_account_masked", "TEXT"),
    # MyDHL shipmentNotification booking audit (no secrets — masks only).
    # Written once at COMPLETE when the coordinator persists the Create Shipment
    # request shape. Distinct from Estrella delivery-confirmation email.
    ("dhl_notify_email_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("dhl_notify_sms_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("dhl_notify_email_masked", "TEXT"),
    ("dhl_notify_sms_masked", "TEXT"),
    ("dhl_notify_recipient_source", "TEXT"),
    ("dhl_notify_provider", "TEXT"),
    ("dhl_notify_requested_at", "TEXT"),
    # Slice A — linked return DRAFT (no MyDHL create). NULL direction = outbound
    # legacy. Return rows use shipment_direction='return' + distinct idempotency
    # key (direction+parent AWB) so they never collide with outbound bookings.
    ("shipment_direction", "TEXT"),           # outbound | return (NULL=outbound)
    ("return_intent_status", "TEXT"),         # prepared | …
    ("parent_tracking_ref", "TEXT"),
    ("parent_idempotency_key", "TEXT"),
    ("return_reason", "TEXT"),
    ("proposed_shipper_json", "TEXT"),        # preview snapshot only
    ("proposed_receiver_json", "TEXT"),       # preview snapshot only
    ("pieces", "INTEGER"),
    ("customs_requirement_status", "TEXT"),   # not_required|required_pending|incomplete
    ("contact_email", "TEXT"),                # planned notify contact (normalized)
    ("contact_phone_e164", "TEXT"),
    ("contact_country_code", "TEXT"),         # ISO alpha-2 canonical
    ("contact_needs_review", "INTEGER NOT NULL DEFAULT 0"),
    ("dhl_return_capability", "TEXT"),        # pending until account confirmed
    ("create_return_available", "INTEGER NOT NULL DEFAULT 0"),
    # Carrier/provider owning this shipment — DHL | FEDEX | UPS.
    # Nullable: rows booked before this column existed carry NULL. Every such
    # row was created through the DHL-only live adapter (adapters/live.py has
    # no other carrier), so NULL resolves to DHL at read time via
    # resolve_provider(). Legacy rows are NOT rewritten on disk.
    ("provider", "TEXT"),
    # Neutral carrier transaction / confirmation id. Not vendor-prefixed.
    ("carrier_transaction_id", "TEXT"),
]

# Provider vocabulary. DHL is booked through the live adapter; FEDEX/UPS/OTHER
# (and active Carrier Master codes) are customer-arranged external registrations.
PROVIDER_DHL = "DHL"
PROVIDER_OTHER = "OTHER"
PROVIDERS = ("DHL", "FEDEX", "UPS", "OTHER")
EXTERNAL_PROVIDERS = ("FEDEX", "UPS", "OTHER")
_PROVIDER_RE = re.compile(r"^[A-Z0-9_]{2,32}$")


def normalize_provider_code(provider: str) -> str:
    return (provider or "").strip().upper()


def is_valid_provider_code(provider: str) -> bool:
    p = normalize_provider_code(provider)
    return bool(p and _PROVIDER_RE.match(p))


def resolve_provider(stored: Optional[str]) -> str:
    """Provider for a shipment row — the ONE place NULL is interpreted.

    NULL means the row predates the provider column. Only the DHL adapter
    existed then, so DHL is evidence-backed, not a guess. Callers must use
    this instead of defaulting a blank carrier in a projection or a UI.
    """
    return normalize_provider_code(stored or "") or PROVIDER_DHL


_MODE_CHECK_CURRENT = "CHECK(mode IN ('shadow', 'live', 'external'))"
_MODE_IN_RE = re.compile(
    r"CHECK\s*\(\s*mode\s+IN\s*\(([^)]*)\)\s*\)",
    re.IGNORECASE,
)
_MODE_CHECK_RE = re.compile(
    r"CHECK\s*\(\s*mode\s+IN\s*\(\s*[^)]+?\s*\)\s*\)",
    re.IGNORECASE,
)

# Outbound-only filter — return drafts must never leak into AWB attribution.
_OUTBOUND_ONLY = (
    "(shipment_direction IS NULL OR LOWER(shipment_direction) != 'return')"
)

# Which competing row IS this leg's shipment.
#
# "Newest row wins" was right while one booking meant one row. It stopped being
# right once the coordinator gained in-flight recovery: a PENDING row created
# earlier is re-executed in place (_execute(is_recovery=True) does not insert),
# so the row carrying the real AWB can be OLDER than a later shadow reservation
# for the same leg. Ordering by creation time then hands every consumer the
# shadow row and the live AWB disappears from the whole portal — Logistics,
# Documents, readiness and the CMR/insurance projections all read through here.
#
# Booking authority, not recency, decides:
#   1. a row carrying a real completed booking (tracking_ref + COMPLETE) wins;
#   2. among THOSE, a real carrier write outranks a simulated one;
#   3. otherwise the newest row, exactly as before.
#
# Both CASE arms are qualified by the completed-booking predicate on purpose, so
# rows that are NOT completed bookings keep their previous relative order. That
# matters beyond presentation: coordinator.py:520 uses this selector for
# duplicate protection and refuses a second external registration when the
# returned row is in (complete, submitted, pending). An unqualified tiebreak
# could reorder within the non-booking group and surface a FAILED row ahead of a
# PENDING one -- 'failed' is not in that set, so the refusal would silently
# become an acceptance and the leg could take a second registration. Ranking
# only among completed bookings makes the invariant exact: behaviour is
# unchanged unless a completed booking exists, which is the whole defect.
#
# A RETIRED label is not the authoritative booking while a newer one is in
# flight. do_not_use marks an AWB the operator has taken out of service, usually
# because it is being replaced. Ranking it as a completed booking would promote
# it over the newer PENDING row that supersedes it -- so CMR, the insurance
# statement and Logistics would print the very label the operator just retired,
# and the old created_at ordering did NOT do that. Excluding it from the
# completed-booking rank does not hide it: when a retired row is the only row
# for the leg it still falls through to the created_at ordering and is still
# returned, which keeps documents resolvable for an already-shipped leg.
_IS_COMPLETED_BOOKING = (
    "tracking_ref IS NOT NULL AND TRIM(tracking_ref) != '' "
    "AND LOWER(state) = 'complete' "
    "AND COALESCE(do_not_use, 0) = 0"
)
_BOOKING_AUTHORITY_ORDER = (
    "ORDER BY "
    f"CASE WHEN {_IS_COMPLETED_BOOKING} THEN 0 ELSE 1 END, "
    f"CASE WHEN {_IS_COMPLETED_BOOKING} AND simulated = 1 THEN 1 ELSE 0 END, "
    "created_at DESC"
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row(row) -> Optional[dict]:
    """Normalize a carrier_shipments row — the single read boundary.

    Every reader goes through here so ``provider`` is interpreted in exactly
    one place and no consumer (CMR, Logistics, Packing List, UI) has to invent
    a carrier for a legacy NULL.
    """
    if row is None:
        return None
    d = dict(row)
    d["provider"] = resolve_provider(d.get("provider"))
    return d


def init_db(db_path: Path) -> None:
    """Create or migrate carrier_shipments.

    Recovery of an interrupted CHECK rebuild runs BEFORE CREATE TABLE IF NOT
    EXISTS, so a leftover ``carrier_shipments__pre_ext`` cannot be masked by
    an empty new table. The CHECK rebuild itself runs in BEGIN IMMEDIATE.
    """
    conn = _connect(db_path)
    try:
        _recover_interrupted_mode_migration(conn)
        conn.execute(_DDL)
        _ensure_additive_columns(conn)
        _ensure_external_mode_allowed(conn)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _row_count(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])


def _create_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return (row[0] if row else "") or ""


def _mode_in_tokens(sql: str) -> Optional[FrozenSet[str]]:
    if not sql:
        return None
    matches = list(_MODE_IN_RE.finditer(sql))
    if len(matches) != 1:
        return None
    tokens = [t.lower() for t in re.findall(r"'([^']*)'", matches[0].group(1))]
    if not tokens:
        return None
    return frozenset(tokens)


def _mode_check_kind(sql: str) -> str:
    tokens = _mode_in_tokens(sql)
    if tokens is None:
        return "unknown"
    if tokens == frozenset({"shadow", "live", "external"}):
        return "current"
    if tokens == frozenset({"shadow", "live"}):
        return "legacy"
    return "unknown"


def _widen_mode_check_sql(sql: str) -> str:
    kind = _mode_check_kind(sql)
    if kind == "current":
        return sql
    if kind != "legacy":
        raise CarrierShipmentsSchemaError(
            "cannot widen mode CHECK: unrecognized constraint"
        )
    new_sql, n = _MODE_CHECK_RE.subn(_MODE_CHECK_CURRENT, sql, count=1)
    if n != 1:
        raise CarrierShipmentsSchemaError("cannot widen mode CHECK: replace failed")
    return new_sql


def _attached_schema_sqls(conn: sqlite3.Connection, table: str) -> Sequence[str]:
    """CREATE INDEX / CREATE TRIGGER statements attached to ``table``.

    Autoindexes (PRIMARY KEY) have sql IS NULL and are recreated by the
    replacement CREATE TABLE. Extra indexes/triggers must be replayed.
    """
    rows = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE tbl_name=? AND type IN ('index', 'trigger') "
        "AND sql IS NOT NULL "
        "ORDER BY type, name",
        (table,),
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def _ensure_additive_columns(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, TABLE):
        return
    for col, ddl in _ADDITIVE_COLUMNS:
        try:
            conn.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN {col} {ddl}')
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def _end_implicit_transaction(conn: sqlite3.Connection) -> None:
    try:
        conn.commit()
    except sqlite3.Error:
        pass


def _recover_interrupted_mode_migration(conn: sqlite3.Connection) -> None:
    """Restore a single carrier_shipments table before CREATE TABLE IF NOT EXISTS.

    Fail closed when both tables are populated. An empty current table beside
    a populated temp is interrupted-migration residue, not a second authority.
    """
    has_cur = _table_exists(conn, TABLE)
    has_tmp = _table_exists(conn, PRE_EXT_TABLE)
    if not has_tmp:
        return

    cur_n = _row_count(conn, TABLE) if has_cur else 0
    tmp_n = _row_count(conn, PRE_EXT_TABLE)

    if has_cur and cur_n > 0 and tmp_n > 0:
        raise CarrierShipmentsSchemaError(
            f"ambiguous carrier_shipments recovery: both {TABLE!r} ({cur_n} rows) "
            f"and {PRE_EXT_TABLE!r} ({tmp_n} rows) are populated"
        )

    conn.execute("PRAGMA foreign_keys=OFF")
    _end_implicit_transaction(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if has_cur and cur_n == 0 and tmp_n > 0:
            conn.execute(f'DROP TABLE "{TABLE}"')
            conn.execute(f'ALTER TABLE "{PRE_EXT_TABLE}" RENAME TO "{TABLE}"')
        elif (not has_cur) and has_tmp:
            conn.execute(f'ALTER TABLE "{PRE_EXT_TABLE}" RENAME TO "{TABLE}"')
        elif has_cur and tmp_n == 0:
            conn.execute(f'DROP TABLE "{PRE_EXT_TABLE}"')
        else:
            raise CarrierShipmentsSchemaError(
                f"unhandled carrier_shipments recovery "
                f"current={has_cur}/{cur_n} temp={has_tmp}/{tmp_n}"
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_external_mode_allowed(conn: sqlite3.Connection) -> None:
    """Widen the mode CHECK so customer-arranged rows can persist honestly.

    SQLite cannot ALTER a CHECK. The rebuild is one BEGIN IMMEDIATE
    transaction: rename, recreate, copy, restore indexes/triggers, drop temp.
    Row-count mismatch aborts the transaction.
    """
    if not _table_exists(conn, TABLE):
        return
    sql = _create_sql(conn, TABLE)
    kind = _mode_check_kind(sql)
    if kind == "current":
        return
    if kind != "legacy":
        raise CarrierShipmentsSchemaError(
            "carrier_shipments mode CHECK is unrecognized; refusing to migrate or skip"
        )

    old_count = _row_count(conn, TABLE)
    old_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{TABLE}")')]
    extra_sqls = _attached_schema_sqls(conn, TABLE)
    widened = _widen_mode_check_sql(sql)

    conn.execute("PRAGMA foreign_keys=OFF")
    _end_implicit_transaction(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f'ALTER TABLE "{TABLE}" RENAME TO "{PRE_EXT_TABLE}"')
        conn.execute(widened)
        for col, ddl in _ADDITIVE_COLUMNS:
            try:
                conn.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN {col} {ddl}')
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        new_cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{TABLE}")')}
        copy_cols = [c for c in old_cols if c in new_cols]
        col_sql = ", ".join(f'"{c}"' for c in copy_cols)
        conn.execute(
            f'INSERT INTO "{TABLE}" ({col_sql}) '
            f'SELECT {col_sql} FROM "{PRE_EXT_TABLE}"'
        )
        new_count = _row_count(conn, TABLE)
        if new_count != old_count:
            raise CarrierShipmentsSchemaError(
                f"carrier_shipments rebuild lost rows: before={old_count} after={new_count}"
            )
        conn.execute(f'DROP TABLE "{PRE_EXT_TABLE}"')
        for stmt in extra_sqls:
            conn.execute(stmt)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def insert_shipment(
    db_path: Path,
    result: ShipmentResult,
    batch_id: str,
    client_ref: Optional[str] = None,
    *,
    operator: Optional[str] = None,
    provider: str = PROVIDER_DHL,
    transport_payer: Optional[str] = None,
    billing_account_masked: Optional[str] = None,
) -> None:
    """
    Record a new shipment idempotency entry.

    Live mode results are rejected — AWBs must never appear in this table.
    tracking_ref is also absent from the schema for the same structural reason.

    client_ref (optional) scopes the row to a single client within the batch;
    None is stored for legacy/unscoped callers.

    operator (optional, keyword-only) is the X-Operator attribution for the
    booking, stored in booked_by. It is written ONLY at this PENDING anchor
    insert — state transitions never touch it — so the audit trail always names
    the operator who initiated the real booking, never a later replayer. None
    stores NULL (legacy/unattributed callers behave exactly as before).

    provider (keyword-only) is the carrier owning this shipment. Defaults to
    DHL — the only carrier with a booking adapter — so existing callers are
    unchanged. Customer-arranged FEDEX/UPS/OTHER registrations pass their own.
    Closed storage vocabulary: only PROVIDERS. Carrier Master codes that are
    not in this set must be normalised to OTHER by the coordinator before insert.
    """
    provider = normalize_provider_code(provider)
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown carrier provider {provider!r}; expected one of {PROVIDERS}"
        )
    if result.mode == ShipmentMode.LIVE:
        raise ValueError(
            "Live shipment results must not be inserted into carrier_shipments DB. "
            "AWB references are stored in the secure label store only."
        )
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO carrier_shipments
                (idempotency_key, batch_id, client_ref, mode, state, error, simulated,
                 service_product, dimensions_json, booked_by, provider,
                 transport_payer, billing_account_masked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.idempotency_key,
                batch_id,
                client_ref,
                result.mode.value,
                result.state.value,
                result.error,
                int(result.simulated),
                result.service_product,
                result.dimensions_json,
                operator,
                provider,
                # Written at the anchor beside booked_by, for the same reason:
                # the record must name the arrangement the REAL booking used,
                # not one a later replay happened to resolve.
                transport_payer,
                billing_account_masked,
            ),
        )


def exists(db_path: Path, idempotency_key: str) -> bool:
    """Return True if an entry exists for the given idempotency key."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM carrier_shipments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return row is not None


def get_shipment(db_path: Path, idempotency_key: str) -> Optional[dict]:
    """Return the shipment row as a plain dict, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return _row(row)


def get_shipment_by_batch_id(db_path: Path, batch_id: str) -> Optional[dict]:
    """Return the most recent shipment row for the given batch_id, or None.

    Batch-scoped — returns one row per batch regardless of client. Retained for
    internal/webhook correlation (batch_id ↔ tracking_ref) and legacy callers.
    For per-draft document resolution use get_shipment_for_draft, which never
    leaks one client's AWB onto another client's draft in the same batch.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM carrier_shipments WHERE batch_id = ? "
            f"AND {_OUTBOUND_ONLY} ORDER BY created_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return _row(row)


def get_legacy_shipment(db_path: Path, batch_id: str) -> Optional[dict]:
    """Newest legacy (NULL client_ref) shipment row for the batch, or None.

    A legacy row predates client-scoped idempotency keys: a re-book of the
    same batch that now sends client_ref computes a NEW key, so the
    coordinator's completed-key replay will NOT match that row — a new
    shipment record (and, in live mode, a new carrier booking) would be
    created alongside it (ADR-proforma-cmr-short-number §Known limitation).

    Powers the booking-modal legacy-rebook warning ONLY. It is not a
    document-attribution path — that stays get_shipment_for_draft, which
    owns the per-client leak rules. 'failed' rows are excluded: a failed
    attempt is not a prior booking, and re-booking over one is the normal
    retry path. Read-only — never mutates state.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments "
            f"WHERE batch_id = ? AND client_ref IS NULL AND state != 'failed' "
            f"AND {_OUTBOUND_ONLY} "
            "ORDER BY created_at DESC LIMIT 1",
            (batch_id,),
        ).fetchone()
    return _row(row)


def get_client_shipment(
    db_path: Path, batch_id: str, client_ref: Optional[str]
) -> Optional[dict]:
    """Newest non-failed shipment row scoped to EXACTLY this client, or None.

    Companion to get_legacy_shipment: once a client-scoped row exists for the
    batch, a same-params re-book computes the SAME per-client idempotency key,
    so the coordinator replays (complete) or recovers (pending) that row — it
    does NOT create a new record alongside the legacy one. The booking-modal
    legacy-rebook warning is therefore suppressed when this returns a row
    (reviewer-challenge MEDIUM-2, 2026-07-16). The legacy row itself is
    deliberately never mutated — suppression is read-side only.

    'failed' rows are excluded for the opposite reason: a failed client-scoped
    attempt is NOT a prior booking (the coordinator refuses a same-key retry;
    a changed-params retry computes a new key and books for real), so the
    warning must still fire. Powers probe suppression ONLY — never a
    document-attribution path (that stays get_shipment_for_draft, which owns
    the per-client leak rules). Read-only — never mutates state.
    """
    if not (client_ref or "").strip():
        # An empty/blank ref must never match: '' != NULL in SQLite, and a
        # blank-scoped row would be a data bug, not a prior booking.
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carrier_shipments "
            f"WHERE batch_id = ? AND client_ref = ? AND state != 'failed' "
            f"AND {_OUTBOUND_ONLY} "
            "ORDER BY created_at DESC LIMIT 1",
            (batch_id, client_ref),
        ).fetchone()
    return _row(row)


def get_active_booking_for_leg(
    db_path: Path, batch_id: str, client_ref: Optional[str] = None
) -> Optional[dict]:
    """The booking that is ALREADY in force for this canonical shipment leg.

    THE duplicate-protection read. "In force" is not a new idea invented here:
    it is _IS_COMPLETED_BOOKING, the same predicate _BOOKING_AUTHORITY_ORDER
    already uses to decide which competing row IS this leg's shipment — a real
    tracking_ref, state complete, and not marked do-not-use. Defining it twice
    is how the ranking and the guard would drift apart, so it is defined once
    and read here.

    Narrowed by one explicit clause: simulated rows are excluded. What this
    guard protects is the operator from a second CHARGEABLE AWB, and a shadow
    ``SIM-*`` reference is not a shipment anyone can hand to a courier. Letting
    a simulation block a real booking would be the same over-blocking this
    guard replaced the carrier_live_allowlist to end. A customer-arranged
    external registration is NOT simulated — it names a real parcel already in
    the carrier's hands — so it blocks, correctly.

    Leg identity is (batch_id, client_ref) when the caller names a client, and
    the batch alone when it does not. A blank client_ref does NOT collapse to
    "any row for the batch": an unscoped booking request is a batch-level leg
    and must see batch-level rows, which is exactly what the else-branch does.

    Why this exists separately from the coordinator's idempotency key: the key
    hashes weight, declared value, currency and account, so correcting a weight
    from 2.4 to 2.5 kg computes a NEW key and the replay path never fires. That
    is a second chargeable AWB for one parcel. The key answers "is this the
    same REQUEST"; this answers "is this the same SHIPMENT", and only the
    second one is duplicate protection.

    do_not_use is the operator's release valve, not a loophole: retiring a
    misprinted or superseded label is an explicit, attributed, audited act
    (mark_do_not_use), after which this returns None and the leg is bookable
    again. Read-only — never mutates state.
    """
    scoped = (client_ref or "").strip()
    with _connect(db_path) as conn:
        if scoped:
            row = conn.execute(
                "SELECT * FROM carrier_shipments "
                f"WHERE batch_id = ? AND client_ref = ? AND {_OUTBOUND_ONLY} "
                f"AND {_IS_COMPLETED_BOOKING} AND COALESCE(simulated, 0) = 0 "
                "ORDER BY created_at DESC LIMIT 1",
                (batch_id, scoped),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM carrier_shipments "
                f"WHERE batch_id = ? AND {_OUTBOUND_ONLY} "
                f"AND {_IS_COMPLETED_BOOKING} AND COALESCE(simulated, 0) = 0 "
                "ORDER BY created_at DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
    return _row(row)


def get_shipment_for_draft(
    db_path: Path,
    batch_id: str,
    client_ref: Optional[str] = None,
    *,
    allow_single_client_fallback: bool = False,
) -> Optional[dict]:
    """Resolve the carrier shipment that belongs to ONE client's draft.

    One import batch is split into several per-client proforma drafts. The
    carrier shipment belongs to exactly one client, so a draft must never be
    shown another client's AWB/CMR (2026-07-16 cross-client AWB contamination).

    Resolution order:
      1. Exact per-client match — the authoritative row for (batch_id,
         client_ref), ranked by _BOOKING_AUTHORITY_ORDER: a completed booking
         carrying a real tracking_ref outranks a shadow/pending reservation
         however recently that reservation was created. This is the correct
         path for any shipment booked after client_ref was introduced.
      2. Legacy single-client fallback — only when *allow_single_client_fallback*
         is True (caller has proven the batch maps to exactly one client draft)
         AND exactly one shipment row exists for the batch. That single row is
         unambiguously this client's, even though it predates client_ref (NULL).
      3. Otherwise None (honest missing) — a multi-client batch with no exact
         per-client row must NOT fall back to "the latest batch row", which is
         precisely the contamination bug.

    Never mutates state — purely read-only. Return drafts are excluded.
    """
    with _connect(db_path) as conn:
        if client_ref:
            row = conn.execute(
                "SELECT * FROM carrier_shipments "
                f"WHERE batch_id = ? AND client_ref = ? AND {_OUTBOUND_ONLY} "
                f"{_BOOKING_AUTHORITY_ORDER} LIMIT 1",
                (batch_id, client_ref),
            ).fetchone()
            if row:
                return _row(row)

        if allow_single_client_fallback:
            rows = conn.execute(
                f"SELECT * FROM carrier_shipments WHERE batch_id = ? "
                f"AND {_OUTBOUND_ONLY} "
                "ORDER BY created_at DESC",
                (batch_id,),
            ).fetchall()
            if len(rows) == 1:
                row = dict(rows[0])
                # Defence-in-depth (independent of the caller's multi-client
                # gate): the fallback may attribute ONLY a legacy NULL-client_ref
                # row. A row scoped to a DIFFERENT client must never be returned
                # to this requestor — even if the outer gate misfires (e.g.
                # proforma_links.db path drift), the original cross-client leak
                # cannot recur (2026-07-16 independent-review POST-1).
                if (
                    row.get("client_ref")
                    and client_ref
                    and row["client_ref"] != client_ref
                ):
                    return None
                return _row(row)

    return None


def list_outbound_rows_for_batches(
    db_path: Path, batch_ids: List[str]
) -> List[dict]:
    """Read-only: outbound carrier rows for many batches in one query.

    Used by Pro Forma search projection to resolve outbound ``tracking_ref``
    without N+1 ``get_shipment_for_draft`` calls. Attribution (exact client
    match + single-client fallback) stays with the caller — same rules as
    ``get_shipment_for_draft``. Return drafts excluded via ``_OUTBOUND_ONLY``.
    """
    ids = sorted({(b or "").strip() for b in batch_ids if (b or "").strip()})
    if not ids or not Path(db_path).exists():
        return []
    placeholders = ",".join("?" for _ in ids)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM carrier_shipments "
            f"WHERE batch_id IN ({placeholders}) AND {_OUTBOUND_ONLY} "
            # Same ranking as get_shipment_for_draft, for the same reason: the
            # caller takes the FIRST matching row per (batch, client), so if the
            # order differed the bulk projection would name a different shipment
            # than the per-draft one for the same leg.
            f"{_BOOKING_AUTHORITY_ORDER}",
            ids,
        ).fetchall()
    return [dict(r) for r in rows]


def update_state(
    db_path: Path,
    idempotency_key: str,
    state: ShipmentState,
    error: Optional[str] = None,
    *,
    tracking_ref: Optional[str] = None,
    mode: Optional[ShipmentMode] = None,
    simulated: Optional[bool] = None,
) -> None:
    """Advance the state of an existing shipment entry.

    At COMPLETE the coordinator also persists the adapter-truth fields
    (tracking_ref, mode, simulated) so a replay can return the stored
    result without re-invoking the adapter (2026-07-06 incident fix).
    Only non-None keyword fields are written.
    """
    sets = ["state = ?", "error = ?"]
    args: list = [state.value, error]
    if tracking_ref is not None:
        sets.append("tracking_ref = ?")
        args.append(tracking_ref)
    if mode is not None:
        sets.append("mode = ?")
        args.append(mode.value)
    if simulated is not None:
        sets.append("simulated = ?")
        args.append(int(simulated))
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    args.append(idempotency_key)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE carrier_shipments SET {', '.join(sets)} WHERE idempotency_key = ?",
            tuple(args),
        )


def persist_notification_audit(
    db_path: Path,
    idempotency_key: str,
    audit: dict,
) -> None:
    """Write MyDHL shipmentNotification booking audit (masks only; no secrets).

    Idempotent for COMPLETE rows that already carry a timestamp: a replay must
    not invent a second request_at. First write wins when ``dhl_notify_requested_at``
    is already set.
    """
    if not idempotency_key or not isinstance(audit, dict):
        return
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT dhl_notify_requested_at FROM carrier_shipments "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return
        if (row["dhl_notify_requested_at"] or "").strip():
            return
        conn.execute(
            """
            UPDATE carrier_shipments SET
                dhl_notify_email_requested = ?,
                dhl_notify_sms_requested = ?,
                dhl_notify_email_masked = ?,
                dhl_notify_sms_masked = ?,
                dhl_notify_recipient_source = ?,
                dhl_notify_provider = ?,
                dhl_notify_requested_at = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE idempotency_key = ?
            """,
            (
                int(audit.get("dhl_notify_email_requested") or 0),
                int(audit.get("dhl_notify_sms_requested") or 0),
                audit.get("dhl_notify_email_masked"),
                audit.get("dhl_notify_sms_masked"),
                audit.get("dhl_notify_recipient_source"),
                audit.get("dhl_notify_provider"),
                audit.get("dhl_notify_requested_at"),
                idempotency_key,
            ),
        )


def mark_do_not_use(
    db_path: Path,
    batch_id: str,
    tracking_ref: str,
    reason: str,
    operator: Optional[str] = None,
) -> int:
    """Mark every shipment row for (batch_id, tracking_ref) as do-not-use.

    Purely local operational status — never calls DHL, never changes the
    tracking_ref, state, or any booking field. Returns the number of rows
    marked (0 = no matching shipment).
    """
    if not (batch_id and tracking_ref and reason and reason.strip()):
        return 0
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE carrier_shipments
               SET do_not_use = 1,
                   do_not_use_reason = ?,
                   do_not_use_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   do_not_use_by = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE batch_id = ? AND tracking_ref = ?
            """,
            (reason.strip(), operator, batch_id, tracking_ref),
        )
    return cur.rowcount


def get_do_not_use(db_path: Path, batch_id: str, tracking_ref: str) -> Optional[dict]:
    """Return the do-not-use flag fields for (batch_id, tracking_ref), or None.

    None means no shipment row exists for that pair (legacy rows without a
    stored tracking_ref are never matched — they cannot be marked).
    """
    if not (batch_id and tracking_ref):
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT do_not_use, do_not_use_reason, do_not_use_at, do_not_use_by
              FROM carrier_shipments
             WHERE batch_id = ? AND tracking_ref = ?
             ORDER BY do_not_use DESC LIMIT 1
            """,
            (batch_id, tracking_ref),
        ).fetchone()
    return _row(row)


def update_shipment_fields(
    db_path: Path,
    idempotency_key: str,
    *,
    service_product: Optional[str] = None,
    dimensions_json: Optional[str] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    box_type_code: Optional[str] = None,
    carrier_transaction_id: Optional[str] = None,
    packages_json: Optional[str] = None,
) -> None:
    """Persist Phase-5 carrier API response fields on an existing row.

    Only writes non-None arguments.  A call with all None is a no-op.
    """
    sets, args = [], []
    if service_product is not None:
        sets.append("service_product = ?")
        args.append(service_product)
    if dimensions_json is not None:
        sets.append("dimensions_json = ?")
        args.append(dimensions_json)
    if weight_kg is not None:
        sets.append("weight_kg = ?")
        args.append(float(weight_kg))
    if declared_value is not None:
        sets.append("declared_value = ?")
        args.append(float(declared_value))
    if currency is not None:
        sets.append("currency = ?")
        args.append(currency)
    if box_type_code is not None:
        sets.append("box_type_code = ?")
        args.append(box_type_code)
    if carrier_transaction_id is not None:
        sets.append("carrier_transaction_id = ?")
        args.append(carrier_transaction_id)
    if packages_json is not None:
        sets.append("packages_json = ?")
        args.append(packages_json)
    if not sets:
        return
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    args.append(idempotency_key)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE carrier_shipments SET {', '.join(sets)} WHERE idempotency_key = ?",
            tuple(args),
        )


def get_shipment_by_tracking_ref(db_path: Path, tracking_ref: str) -> Optional[dict]:
    """Return the most recent full shipment row for an AWB, or None (read-only).

    Used by the outbound-delivery hook to resolve an AWB back to its owning
    draft context (batch_id, client_ref, created_at) so a customer
    delivery-confirmation email can be routed and its activation boundary
    checked. Never mutates state. Return drafts have no tracking_ref and are
    excluded by the outbound filter as defence-in-depth.
    """
    ref = (tracking_ref or "").strip()
    if not ref or not Path(db_path).exists():
        return None
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM carrier_shipments WHERE tracking_ref = ? "
                f"AND {_OUTBOUND_ONLY} "
                "ORDER BY created_at DESC LIMIT 1",
                (ref,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return _row(row)


def list_tracked_shipments(
    db_path: Path,
    *,
    limit: int = 5000,
) -> list:
    """Read-only list of carrier_shipments rows that have a tracking_ref (AWB).

    Used by the DHL Logistics Control Tower projection. Never invents AWBs —
    only returns rows where DHL booking already persisted ``tracking_ref``.
    Excludes return drafts (no tracking_ref; outbound filter as defence).
    """
    if not Path(db_path).exists():
        return []
    lim = max(1, min(int(limit or 5000), 20000))
    try:
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM carrier_shipments "
                "WHERE tracking_ref IS NOT NULL AND TRIM(tracking_ref) != '' "
                f"AND {_OUTBOUND_ONLY} "
                "ORDER BY created_at DESC LIMIT ?",
                (lim,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


# ── Return DRAFT persistence (Slice A — no MyDHL create) ─────────────────────


def insert_return_draft(
    db_path: Path,
    *,
    idempotency_key: str,
    batch_id: str,
    parent_tracking_ref: str,
    parent_idempotency_key: Optional[str] = None,
    client_ref: Optional[str] = None,
    return_reason: Optional[str] = None,
    proposed_shipper_json: Optional[str] = None,
    proposed_receiver_json: Optional[str] = None,
    pieces: Optional[int] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    customs_requirement_status: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone_e164: Optional[str] = None,
    contact_country_code: Optional[str] = None,
    contact_needs_review: int = 0,
    operator: Optional[str] = None,
) -> None:
    """Insert a linked return DRAFT row. Never calls DHL. No tracking_ref.

    mode=shadow + state=pending — draft is local-only until Live Create is
    enabled (HOLD). create_return_available is always 0; dhl_return_capability
    is always 'pending'.
    """
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO carrier_shipments
                (idempotency_key, batch_id, client_ref, mode, state, error, simulated,
                 shipment_direction, return_intent_status,
                 parent_tracking_ref, parent_idempotency_key, return_reason,
                 proposed_shipper_json, proposed_receiver_json,
                 pieces, weight_kg, declared_value, currency,
                 customs_requirement_status,
                 contact_email, contact_phone_e164, contact_country_code,
                 contact_needs_review,
                 dhl_return_capability, create_return_available,
                 booked_by)
            VALUES (?, ?, ?, 'shadow', 'pending', NULL, 1,
                    'return', 'prepared',
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?,
                    ?, ?, ?,
                    ?,
                    'pending', 0,
                    ?)
            """,
            (
                idempotency_key,
                batch_id,
                client_ref,
                parent_tracking_ref,
                parent_idempotency_key,
                return_reason,
                proposed_shipper_json,
                proposed_receiver_json,
                pieces,
                weight_kg,
                declared_value,
                currency,
                customs_requirement_status,
                contact_email,
                contact_phone_e164,
                contact_country_code,
                int(contact_needs_review or 0),
                operator,
            ),
        )


def get_return_draft(
    db_path: Path,
    *,
    batch_id: str,
    parent_tracking_ref: Optional[str] = None,
    client_ref: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[dict]:
    """Return the newest return DRAFT for the batch/parent, or None."""
    if not Path(db_path).exists():
        return None
    init_db(db_path)
    with _connect(db_path) as conn:
        if idempotency_key:
            row = conn.execute(
                "SELECT * FROM carrier_shipments WHERE idempotency_key = ? "
                "AND LOWER(COALESCE(shipment_direction, '')) = 'return'",
                (idempotency_key,),
            ).fetchone()
            return _row(row)

        clauses = [
            "LOWER(COALESCE(shipment_direction, '')) = 'return'",
            "batch_id = ?",
        ]
        args: list = [batch_id]
        if parent_tracking_ref:
            clauses.append("parent_tracking_ref = ?")
            args.append(parent_tracking_ref.strip())
        if client_ref:
            clauses.append("client_ref = ?")
            args.append(client_ref)
        row = conn.execute(
            f"SELECT * FROM carrier_shipments WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC LIMIT 1",
            tuple(args),
        ).fetchone()
    return _row(row)


def update_return_draft(
    db_path: Path,
    idempotency_key: str,
    *,
    return_reason: Optional[str] = None,
    proposed_shipper_json: Optional[str] = None,
    proposed_receiver_json: Optional[str] = None,
    pieces: Optional[int] = None,
    weight_kg: Optional[float] = None,
    declared_value: Optional[float] = None,
    currency: Optional[str] = None,
    customs_requirement_status: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone_e164: Optional[str] = None,
    contact_country_code: Optional[str] = None,
    contact_needs_review: Optional[int] = None,
) -> int:
    """Patch editable return-draft fields. Never touches outbound rows.

    Returns rows updated (0 if missing / not a return draft). Never sets
    create_return_available or calls DHL.
    """
    if not idempotency_key:
        return 0
    init_db(db_path)
    sets, args = [], []
    if return_reason is not None:
        sets.append("return_reason = ?")
        args.append(return_reason)
    if proposed_shipper_json is not None:
        sets.append("proposed_shipper_json = ?")
        args.append(proposed_shipper_json)
    if proposed_receiver_json is not None:
        sets.append("proposed_receiver_json = ?")
        args.append(proposed_receiver_json)
    if pieces is not None:
        sets.append("pieces = ?")
        args.append(int(pieces))
    if weight_kg is not None:
        sets.append("weight_kg = ?")
        args.append(float(weight_kg))
    if declared_value is not None:
        sets.append("declared_value = ?")
        args.append(float(declared_value))
    if currency is not None:
        sets.append("currency = ?")
        args.append(currency)
    if customs_requirement_status is not None:
        sets.append("customs_requirement_status = ?")
        args.append(customs_requirement_status)
    if contact_email is not None:
        sets.append("contact_email = ?")
        args.append(contact_email)
    if contact_phone_e164 is not None:
        sets.append("contact_phone_e164 = ?")
        args.append(contact_phone_e164)
    if contact_country_code is not None:
        sets.append("contact_country_code = ?")
        args.append(contact_country_code)
    if contact_needs_review is not None:
        sets.append("contact_needs_review = ?")
        args.append(int(contact_needs_review))
    if not sets:
        return 0
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    args.extend([idempotency_key])
    with _connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE carrier_shipments SET {', '.join(sets)} "
            "WHERE idempotency_key = ? "
            "AND LOWER(COALESCE(shipment_direction, '')) = 'return'",
            tuple(args),
        )
    return int(cur.rowcount or 0)


def get_batch_by_tracking_ref(db_path: Path, tracking_ref: str) -> Optional[str]:
    """CW-1: resolve a DHL tracking number to its batch_id (read-only).

    Used by the carrier webhook at ingest time to correlate an inbound event
    with a shipment BEFORE log-safe stripping removes the tracking identifiers.
    Returns the most recent matching batch_id, or None.
    """
    ref = (tracking_ref or "").strip()
    if not ref or not Path(db_path).exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT batch_id FROM carrier_shipments "
                "WHERE tracking_ref = ? ORDER BY rowid DESC LIMIT 1",
                (ref,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return str(row[0]) if row and row[0] else None

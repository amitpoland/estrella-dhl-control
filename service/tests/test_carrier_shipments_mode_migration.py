"""carrier_shipments mode-CHECK migration: atomic, recoverable, schema-preserving.

Does not touch FedEx tracking, AWB upload UI, or Customer Master.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services.carrier.persistence import shipment_db
from app.services.carrier.persistence.shipment_db import (
    CarrierShipmentsSchemaError,
    PRE_EXT_TABLE,
    TABLE,
)


_LEGACY_DDL = """
CREATE TABLE carrier_shipments (
    idempotency_key TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('shadow', 'live')),
    state TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
    error TEXT,
    simulated INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    tracking_ref TEXT,
    client_ref TEXT,
    booked_by TEXT
)
"""

_DHL_ROW = (
    "dhl-k", "BATCH-DHL", "live", "complete", 0, "1129315655", "Acme", "amit",
)
_SHADOW_ROW = (
    "sh-k", "BATCH-SH", "shadow", "complete", 1, "SHADOW1", None, None,
)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection):
    return {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def _fingerprints(conn: sqlite3.Connection, table: str):
    cols = "idempotency_key, batch_id, mode, state, simulated, tracking_ref, client_ref, booked_by"
    return list(conn.execute(
        f'SELECT {cols} FROM "{table}" ORDER BY idempotency_key'
    ).fetchall())


def _insert_seed(conn: sqlite3.Connection, table: str = "carrier_shipments") -> None:
    conn.execute(
        f'INSERT INTO "{table}" '
        "(idempotency_key, batch_id, mode, state, simulated, "
        "tracking_ref, client_ref, booked_by) "
        "VALUES (?,?,?,?,?,?,?,?)",
        _DHL_ROW,
    )
    conn.execute(
        f'INSERT INTO "{table}" '
        "(idempotency_key, batch_id, mode, state, simulated, "
        "tracking_ref, client_ref, booked_by) "
        "VALUES (?,?,?,?,?,?,?,?)",
        _SHADOW_ROW,
    )


def _legacy_db(path: Path, *, extra_index: bool = False) -> None:
    with _connect(path) as conn:
        conn.executescript(_LEGACY_DDL)
        _insert_seed(conn)
        if extra_index:
            conn.execute(
                "CREATE INDEX carrier_shipments_batch_idx "
                "ON carrier_shipments(batch_id)"
            )


def _assert_seed_intact(path: Path) -> None:
    with _connect(path) as conn:
        assert PRE_EXT_TABLE not in _tables(conn)
        assert TABLE in _tables(conn)
        rows = _fingerprints(conn, TABLE)
        assert len(rows) == 2
        by_key = {r[0]: tuple(r) for r in rows}
        assert by_key["dhl-k"] == _DHL_ROW
        assert by_key["sh-k"] == _SHADOW_ROW
        assert by_key["dhl-k"][2] == "live"
        assert by_key["dhl-k"][5] == "1129315655"


def _assert_external_inserts(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO carrier_shipments "
            "(idempotency_key, batch_id, mode, state, simulated) "
            "VALUES ('ext-k', 'BATCH-EXT', 'external', 'complete', 0)"
        )
        n = conn.execute(
            "SELECT COUNT(*) FROM carrier_shipments WHERE mode='external'"
        ).fetchone()[0]
        assert n == 1


def _schema_objects(conn: sqlite3.Connection, table: str):
    return list(conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE tbl_name=? AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name",
        (table,),
    ))


def test_interrupt_after_rename_recovers_all_rows(tmp_path: Path):
    """Proven crash window: rename committed, replacement never created."""
    p = tmp_path / "after-rename.db"
    _legacy_db(p)
    with _connect(p) as conn:
        before = _fingerprints(conn, TABLE)
        conn.execute(
            f'ALTER TABLE "{TABLE}" RENAME TO "{PRE_EXT_TABLE}"'
        )
        assert TABLE not in _tables(conn)
        assert _count(conn, PRE_EXT_TABLE) == 2

    shipment_db.init_db(p)

    with _connect(p) as conn:
        assert TABLE in _tables(conn)
        assert PRE_EXT_TABLE not in _tables(conn)
        after = _fingerprints(conn, TABLE)
    assert after == before
    _assert_seed_intact(p)
    _assert_external_inserts(p)


def test_interrupt_after_empty_replacement_recovers_all_rows(tmp_path: Path):
    """Replacement table created empty beside populated temp."""
    p = tmp_path / "after-create.db"
    _legacy_db(p)
    with _connect(p) as conn:
        before = _fingerprints(conn, TABLE)
        conn.execute(
            f'ALTER TABLE "{TABLE}" RENAME TO "{PRE_EXT_TABLE}"'
        )
        conn.executescript(
            """
            CREATE TABLE carrier_shipments (
                idempotency_key TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('shadow', 'live', 'external')),
                state TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
                error TEXT,
                simulated INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0, 1)),
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        assert _count(conn, TABLE) == 0
        assert _count(conn, PRE_EXT_TABLE) == 2

    shipment_db.init_db(p)

    with _connect(p) as conn:
        assert PRE_EXT_TABLE not in _tables(conn)
        after = _fingerprints(conn, TABLE)
    assert after == before
    _assert_seed_intact(p)
    _assert_external_inserts(p)


def test_legacy_migrates_and_keeps_dhl_rows(tmp_path: Path):
    p = tmp_path / "legacy.db"
    _legacy_db(p)
    with _connect(p) as conn:
        before = _fingerprints(conn, TABLE)
    shipment_db.init_db(p)
    with _connect(p) as conn:
        after = _fingerprints(conn, TABLE)
    assert after == before
    _assert_seed_intact(p)
    _assert_external_inserts(p)


def test_current_schema_is_noop(tmp_path: Path):
    p = tmp_path / "current.db"
    shipment_db.init_db(p)
    with _connect(p) as conn:
        conn.execute(
            "INSERT INTO carrier_shipments "
            "(idempotency_key, batch_id, mode, state, simulated, tracking_ref) "
            "VALUES ('k', 'B', 'live', 'complete', 0, 'AWB1')"
        )
        before = _fingerprints(conn, TABLE)
        objects = _schema_objects(conn, TABLE)
    shipment_db.init_db(p)
    shipment_db.init_db(p)
    with _connect(p) as conn:
        assert _fingerprints(conn, TABLE) == before
        assert _schema_objects(conn, TABLE) == objects
        assert PRE_EXT_TABLE not in _tables(conn)


def test_migration_twice_idempotent(tmp_path: Path):
    p = tmp_path / "twice.db"
    _legacy_db(p)
    shipment_db.init_db(p)
    with _connect(p) as conn:
        first = _fingerprints(conn, TABLE)
        first_objects = _schema_objects(conn, TABLE)
    shipment_db.init_db(p)
    with _connect(p) as conn:
        assert _fingerprints(conn, TABLE) == first
        assert _schema_objects(conn, TABLE) == first_objects
        assert PRE_EXT_TABLE not in _tables(conn)


def test_dual_populated_fails_closed(tmp_path: Path):
    p = tmp_path / "dual.db"
    _legacy_db(p)
    with _connect(p) as conn:
        conn.execute(
            f'ALTER TABLE "{TABLE}" RENAME TO "{PRE_EXT_TABLE}"'
        )
        conn.executescript(
            """
            CREATE TABLE carrier_shipments (
                idempotency_key TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('shadow', 'live', 'external')),
                state TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
                simulated INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO carrier_shipments "
            "(idempotency_key, batch_id, mode, state, simulated) "
            "VALUES ('other-k', 'BATCH-OTHER', 'live', 'complete', 0)"
        )
        assert _count(conn, TABLE) == 1
        assert _count(conn, PRE_EXT_TABLE) == 2

    with pytest.raises(CarrierShipmentsSchemaError, match="ambiguous"):
        shipment_db.init_db(p)

    with _connect(p) as conn:
        assert TABLE in _tables(conn)
        assert PRE_EXT_TABLE in _tables(conn)
        assert _count(conn, TABLE) == 1
        assert _count(conn, PRE_EXT_TABLE) == 2


def test_whitespace_variant_legacy_check_still_migrates(tmp_path: Path):
    p = tmp_path / "ws.db"
    with _connect(p) as conn:
        conn.execute(
            """
            CREATE TABLE carrier_shipments (
                idempotency_key TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('shadow','live')),
                state TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
                error TEXT,
                simulated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                tracking_ref TEXT,
                client_ref TEXT,
                booked_by TEXT
            )
            """
        )
        _insert_seed(conn)
    shipment_db.init_db(p)
    _assert_seed_intact(p)
    _assert_external_inserts(p)


def test_indexes_and_pk_preserved(tmp_path: Path):
    p = tmp_path / "idx.db"
    _legacy_db(p, extra_index=True)
    with _connect(p) as conn:
        before_idx = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL "
                "ORDER BY name",
                (TABLE,),
            )
        ]
        assert "carrier_shipments_batch_idx" in before_idx
        triggers = list(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (TABLE,),
        ))
        fks = list(conn.execute(f"PRAGMA foreign_key_list({TABLE})"))
        assert triggers == []
        assert fks == []

    shipment_db.init_db(p)

    with _connect(p) as conn:
        after_idx = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL "
                "ORDER BY name",
                (TABLE,),
            )
        ]
        assert "carrier_shipments_batch_idx" in after_idx
        pk = conn.execute(f"PRAGMA table_info({TABLE})").fetchall()
        pk_cols = [r[1] for r in pk if r[5]]
        assert pk_cols == ["idempotency_key"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO carrier_shipments "
                "(idempotency_key, batch_id, mode, state, simulated) "
                "VALUES ('dhl-k', 'DUP', 'live', 'complete', 0)"
            )
        assert list(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (TABLE,),
        )) == []
        assert list(conn.execute(f"PRAGMA foreign_key_list({TABLE})")) == []
    _assert_seed_intact(p)


def test_neither_table_creates_current_schema(tmp_path: Path):
    p = tmp_path / "fresh.db"
    shipment_db.init_db(p)
    with _connect(p) as conn:
        assert TABLE in _tables(conn)
        assert PRE_EXT_TABLE not in _tables(conn)
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()[0]
        assert "external" in sql.lower()
    _assert_external_inserts(p)


def test_rebuild_rowcount_mismatch_rolls_back(tmp_path: Path):
    """Injected failure after copy must not leave a half-rebuilt schema."""
    p = tmp_path / "rollback.db"
    _legacy_db(p)
    with _connect(p) as conn:
        before = _fingerprints(conn, TABLE)
    real = shipment_db._row_count
    calls = {"n": 0}

    def _lie(conn, name):
        calls["n"] += 1
        val = real(conn, name)
        if name == TABLE and calls["n"] >= 2:
            return val - 1
        return val

    shipment_db._row_count = _lie  # type: ignore[method-assign]
    try:
        with pytest.raises(CarrierShipmentsSchemaError, match="lost rows"):
            shipment_db.init_db(p)
    finally:
        shipment_db._row_count = real

    with _connect(p) as conn:
        assert PRE_EXT_TABLE not in _tables(conn)
        assert TABLE in _tables(conn)
        assert _fingerprints(conn, TABLE) == before
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()[0]
        assert shipment_db._mode_check_kind(sql) == "legacy"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO carrier_shipments "
                "(idempotency_key, batch_id, mode, state, simulated) "
                "VALUES ('ext-k', 'BATCH-EXT', 'external', 'complete', 0)"
            )

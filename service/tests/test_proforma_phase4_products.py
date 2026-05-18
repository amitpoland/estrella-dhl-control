"""Phase 4 — product data extensions tests.

Coverage:
  - product_local.origin_country: default 'IN', upsert/read, additive ALTER idempotent
  - product_descriptions.name_sk: nullable column, additive ALTER idempotent
  - HS code resolution: priority chain (_resolve_hs_code + _enrich_lines_with_hs)
  - sync_draft_from_packing_upload accepts master_db_path (source-grep)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ── Source-grep tests ─────────────────────────────────────────────────────────

_SYNC = Path(__file__).parent.parent / "app" / "services" / "proforma_draft_sync.py"
_MDB  = Path(__file__).parent.parent / "app" / "services" / "master_data_db.py"
_DDB  = Path(__file__).parent.parent / "app" / "services" / "document_db.py"

_sync_src = _SYNC.read_text()
_mdb_src  = _MDB.read_text()
_ddb_src  = _DDB.read_text()


def test_origin_country_in_product_local_dataclass():
    assert "origin_country" in _mdb_src


def test_origin_country_default_in():
    assert '"IN"' in _mdb_src or "'IN'" in _mdb_src


def test_origin_country_additive_alter():
    assert "origin_country" in _mdb_src
    assert "ALTER TABLE product_local ADD COLUMN origin_country" in _mdb_src


def test_name_sk_in_document_db():
    assert "name_sk" in _ddb_src


def test_name_sk_additive_alter():
    assert '"name_sk"' in _ddb_src or "'name_sk'" in _ddb_src


def test_resolve_hs_code_exists():
    assert "def _resolve_hs_code" in _sync_src


def test_enrich_lines_with_hs_exists():
    assert "def _enrich_lines_with_hs" in _sync_src


def test_sync_accepts_master_db_path():
    assert "master_db_path" in _sync_src


def test_sync_imports_master_data_db():
    assert "master_data_db" in _sync_src or "import mdb" in _sync_src or "from . import master_data_db" in _sync_src


def test_hs_resolution_uses_product_local():
    assert "hs_code_override" in _sync_src


def test_hs_resolution_falls_back_to_invoice_lines():
    assert "invoice_lines" in _sync_src


# ── DB round-trip tests ───────────────────────────────────────────────────────

def test_origin_country_default(tmp_path):
    """product_local rows default to origin_country='IN' when not specified."""
    from app.services.master_data_db import init_db, upsert_product_local, get_product_local

    db = tmp_path / "m.db"
    init_db(db)
    pl = upsert_product_local(db, {"product_code": "P001"})
    assert pl.origin_country == "IN"


def test_origin_country_roundtrip(tmp_path):
    """origin_country is stored and retrieved correctly."""
    from app.services.master_data_db import init_db, upsert_product_local, get_product_local

    db = tmp_path / "m.db"
    init_db(db)
    upsert_product_local(db, {"product_code": "P002", "origin_country": "CN"})
    pl = get_product_local(db, "P002")
    assert pl is not None
    assert pl.origin_country == "CN"


def test_origin_country_alter_idempotent(tmp_path):
    """Running init_db twice does not raise on origin_country column."""
    from app.services.master_data_db import init_db

    db = tmp_path / "m2.db"
    init_db(db)
    init_db(db)  # idempotent

    with sqlite3.connect(str(db)) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(product_local)")]
    assert "origin_country" in cols


def test_name_sk_nullable(tmp_path):
    """name_sk column is nullable — can be set to None and to a value."""
    from app.services.document_db import init_document_db as ddb_init

    db = tmp_path / "d.db"
    ddb_init(db)

    with sqlite3.connect(str(db)) as conn:
        # Insert a product_descriptions row without name_sk
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO product_descriptions "
            "(product_code, created_at, updated_at) "
            "VALUES ('X001', ?, ?)",
            (now, now),
        )
        conn.commit()

        row = conn.execute(
            "SELECT name_sk FROM product_descriptions WHERE product_code='X001'"
        ).fetchone()
        assert row[0] is None

        # Now set it
        conn.execute(
            "UPDATE product_descriptions SET name_sk=? WHERE product_code='X001'",
            ("Strieborný prsteň",),
        )
        conn.commit()
        row2 = conn.execute(
            "SELECT name_sk FROM product_descriptions WHERE product_code='X001'"
        ).fetchone()
        assert row2[0] == "Strieborný prsteň"


def test_name_sk_alter_idempotent(tmp_path):
    """Running init_db twice does not raise on name_sk column."""
    from app.services.document_db import init_document_db as ddb_init

    db = tmp_path / "d2.db"
    ddb_init(db)
    ddb_init(db)  # idempotent

    with sqlite3.connect(str(db)) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(product_descriptions)")]
    assert "name_sk" in cols


def test_resolve_hs_code_from_product_local(tmp_path):
    """_resolve_hs_code: returns product_local.hs_code_override when present."""
    from app.services.master_data_db import init_db, upsert_product_local
    from app.services.proforma_draft_sync import _resolve_hs_code

    master_db = tmp_path / "master.db"
    init_db(master_db)
    upsert_product_local(master_db, {"product_code": "ABC", "hs_code_override": "7113199090"})

    result = _resolve_hs_code("ABC", master_db)
    assert result == "7113199090"


def test_resolve_hs_code_returns_none_when_missing(tmp_path):
    """_resolve_hs_code: returns None when no override and docs_db is None."""
    from app.services.master_data_db import init_db, upsert_product_local
    from app.services.proforma_draft_sync import _resolve_hs_code
    import app.services.document_db as _ddb_mod

    master_db = tmp_path / "master.db"
    init_db(master_db)
    upsert_product_local(master_db, {"product_code": "XYZ"})  # no override

    # Patch docs db path to None so level 2 is skipped
    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        result = _resolve_hs_code("XYZ", master_db)
    finally:
        _ddb_mod._db_path = orig
    assert result is None


def test_enrich_lines_preserves_existing_hs(tmp_path):
    """_enrich_lines_with_hs does not overwrite lines that already have hs_code."""
    from app.services.master_data_db import init_db, upsert_product_local
    from app.services.proforma_draft_sync import _enrich_lines_with_hs

    master_db = tmp_path / "master.db"
    init_db(master_db)
    upsert_product_local(master_db, {"product_code": "P99", "hs_code_override": "9999999999"})

    lines = [{"product_code": "P99", "hs_code": "1111111111", "qty": 1}]
    enriched = _enrich_lines_with_hs(lines, master_db)
    # existing value must be preserved
    assert enriched[0]["hs_code"] == "1111111111"


def test_enrich_lines_fills_missing_hs(tmp_path):
    """_enrich_lines_with_hs fills hs_code from product_local when line has none."""
    from app.services.master_data_db import init_db, upsert_product_local
    from app.services.proforma_draft_sync import _enrich_lines_with_hs

    master_db = tmp_path / "master.db"
    init_db(master_db)
    upsert_product_local(master_db, {"product_code": "P77", "hs_code_override": "7113191000"})

    lines = [{"product_code": "P77", "qty": 2}]  # no hs_code
    enriched = _enrich_lines_with_hs(lines, master_db)
    assert enriched[0].get("hs_code") == "7113191000"


def test_enrich_lines_no_master_db_no_change():
    """_enrich_lines_with_hs returns lines unchanged when master_db_path=None
    and ddb._db_path is None."""
    import app.services.document_db as _ddb_mod
    from app.services.proforma_draft_sync import _enrich_lines_with_hs

    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [{"product_code": "P55", "qty": 1}]
        enriched = _enrich_lines_with_hs(lines, None)
    finally:
        _ddb_mod._db_path = orig

    assert enriched is lines  # same object returned (fast exit)

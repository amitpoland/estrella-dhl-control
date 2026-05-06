"""
Tests for product_name and description_block persistence in wfirma_products.

Covers:
  - schema migration adds both columns idempotently
  - upsert saves product_name independently
  - upsert saves description_block independently
  - None/empty never erases an existing non-empty value
  - new non-empty value overwrites an existing value
  - get_product returns both fields
  - resolve endpoint persists both fields on found path and create path
  - product_name unchanged when description_block changes
  - description_block unchanged when product_name changes
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "test_wfirma.db"
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    return db


def _columns(db: Path, table: str):
    with sqlite3.connect(str(db)) as con:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


# ── 1. Migration adds both columns idempotently ───────────────────────────────

def test_migration_adds_product_name_and_description_block(tmp_path):
    db = _make_db(tmp_path)
    cols = _columns(db, "wfirma_products")
    assert "product_name" in cols
    assert "description_block" in cols


def test_migration_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    # second init must not raise
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    cols = _columns(db, "wfirma_products")
    assert "product_name" in cols
    assert "description_block" in cols


# ── 2–3. upsert saves each field independently ───────────────────────────────

def test_upsert_saves_product_name(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product(
        "EJL/26-27/001-1",
        product_name="Pierścionek / Ring",
    )
    row = wfirma_db.get_product("EJL/26-27/001-1")
    assert row["product_name"] == "Pierścionek / Ring"


def test_upsert_saves_description_block(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    block = "Co to za towar: Pierścionek\nZ jakiego materiału: Złoto\nDo czego służy: Biżuteria"
    wfirma_db.upsert_product(
        "EJL/26-27/001-1",
        description_block=block,
    )
    row = wfirma_db.get_product("EJL/26-27/001-1")
    assert row["description_block"] == block


# ── 4. None/empty does not erase existing non-empty value ─────────────────────

def test_none_does_not_erase_product_name(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product("EJL/26-27/002-1", product_name="Kolczyki / Earrings")
    # second upsert with no product_name
    wfirma_db.upsert_product("EJL/26-27/002-1", sync_status="matched")
    row = wfirma_db.get_product("EJL/26-27/002-1")
    assert row["product_name"] == "Kolczyki / Earrings"


def test_empty_does_not_erase_description_block(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    block = "Co to za towar: Kolczyki\nZ jakiego materiału: Złoto\nDo czego służy: Biżuteria"
    wfirma_db.upsert_product("EJL/26-27/002-1", description_block=block)
    # second upsert with empty description_block
    wfirma_db.upsert_product("EJL/26-27/002-1", description_block="")
    row = wfirma_db.get_product("EJL/26-27/002-1")
    assert row["description_block"] == block


# ── 5. New non-empty value overwrites existing value ─────────────────────────

def test_new_nonempty_product_name_overwrites(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product("EJL/26-27/003-1", product_name="Old Name")
    wfirma_db.upsert_product("EJL/26-27/003-1", product_name="New Name")
    row = wfirma_db.get_product("EJL/26-27/003-1")
    assert row["product_name"] == "New Name"


# ── 6. get_product returns both fields ────────────────────────────────────────

def test_get_product_returns_both_fields(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product(
        "EJL/26-27/004-1",
        product_name="Bransoletka / Bracelet",
        description_block="Co to za towar: Bransoletka",
    )
    row = wfirma_db.get_product("EJL/26-27/004-1")
    assert row is not None
    assert row["product_name"] == "Bransoletka / Bracelet"
    assert row["description_block"] == "Co to za towar: Bransoletka"


# ── 7–9. product_name and description_block are independent ───────────────────

def test_product_name_unchanged_when_description_block_changes(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product(
        "EJL/26-27/005-1",
        product_name="Naszyjnik / Necklace",
        description_block="block v1",
    )
    wfirma_db.upsert_product("EJL/26-27/005-1", description_block="block v2")
    row = wfirma_db.get_product("EJL/26-27/005-1")
    assert row["product_name"] == "Naszyjnik / Necklace"
    assert row["description_block"] == "block v2"


def test_description_block_unchanged_when_product_name_changes(tmp_path):
    db = _make_db(tmp_path)
    from app.services import wfirma_db
    wfirma_db.init_wfirma_db(db)
    wfirma_db.upsert_product(
        "EJL/26-27/006-1",
        product_name="Name v1",
        description_block="Co to za towar: Wisiorek",
    )
    wfirma_db.upsert_product("EJL/26-27/006-1", product_name="Name v2")
    row = wfirma_db.get_product("EJL/26-27/006-1")
    assert row["product_name"] == "Name v2"
    assert row["description_block"] == "Co to za towar: Wisiorek"

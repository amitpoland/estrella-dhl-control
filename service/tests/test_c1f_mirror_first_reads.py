"""test_c1f_mirror_first_reads.py — Output-equivalence gate for C-1f.

Tests:
  (a) A payload-relevant read site returns the mirror id when mirror row present.
  (b) Fallback + WARNING path when mirror row absent (cache-only) keeps the cache id.
  (c) Divergence path: mirror id != cache id → mirror id used, WARNING logged.
  (d) Both absent → None returned.

These tests monkeypatch `wfdb` and the C-1f mirror accessor to simulate the three
operational states: mirror-confirmed, mirror-absent (cache-only), and divergent.
They validate the _c1f_mirror_good_id_with_fallback() helper that all migrated
sites share — proving output-equivalence: payload good_ids are identical to what
the cache would have produced in the normal case, plus a loud warning on divergence.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# Import helpers under test via the route module.
import app.api.routes_proforma as rp
import app.services.reservation_db as rdb
import app.services.wfirma_db as wfdb_module


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mirror_db(product_code: str, wfirma_id: str) -> Path:
    """Create a temp reservation_queue.db with one mirror row."""
    td = tempfile.mkdtemp()
    db_path = Path(td) / "reservation_queue.db"
    rdb.init_reservation_db(db_path)
    rdb.upsert_product_mirror(db_path, wfirma_id=wfirma_id, product_code=product_code)
    return db_path


def _make_empty_mirror_db() -> Path:
    """Create a temp reservation_queue.db with no mirror rows."""
    td = tempfile.mkdtemp()
    db_path = Path(td) / "reservation_queue.db"
    rdb.init_reservation_db(db_path)
    return db_path


# ── Test (a): mirror-confirmed path returns mirror id ────────────────────────

def test_c1f_mirror_good_id_returns_mirror_when_present():
    """(a) When mirror has a confirmed non-empty wfirma_id for a product_code,
    _c1f_mirror_good_id_with_fallback() returns the mirror id — regardless of
    what the cache has. This is the payload-equivalence guarantee: if the mirror
    and cache agree (normal production state after backfill), both return the same
    id, so the payload good_id is byte-identical before and after C-1f.
    """
    product_code = "TEST-C1F-001"
    mirror_id = "WFIRMA-001"
    cache_id = "WFIRMA-001"  # same as mirror — the normal case

    db_path = _make_mirror_db(product_code, mirror_id)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value={"wfirma_product_id": cache_id}):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result == mirror_id, (
        f"Expected mirror id {mirror_id!r}, got {result!r}. "
        "Mirror-first must return the mirror id when the row is confirmed."
    )


def test_c1f_mirror_returns_mirror_id_even_when_cache_absent():
    """(a-variant) Mirror confirmed, cache returns None → mirror id still returned.
    Proves the mirror is authoritative independently of the cache.
    """
    product_code = "TEST-C1F-002"
    mirror_id = "WFIRMA-002"

    db_path = _make_mirror_db(product_code, mirror_id)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value=None):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result == mirror_id, (
        f"Expected mirror id {mirror_id!r}, got {result!r}. "
        "Mirror row present + cache absent → mirror id must be returned."
    )


# ── Test (b): cache-only fallback path — WARNING logged, cache id returned ───

def test_c1f_fallback_to_cache_when_mirror_absent(caplog):
    """(b) When no mirror row exists for a product_code but the cache has an id,
    _c1f_mirror_good_id_with_fallback() returns the cache id (equivalence preserved)
    and logs a WARNING (loud, not silent).
    """
    product_code = "TEST-C1F-003"
    cache_id = "WFIRMA-003"

    db_path = _make_empty_mirror_db()

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value={"wfirma_product_id": cache_id}), \
         caplog.at_level(logging.WARNING):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result == cache_id, (
        f"Expected cache id {cache_id!r} as fallback, got {result!r}. "
        "Mirror absent → cache fallback must return the cache id."
    )
    assert any("C-1f" in m and "falling back" in m for m in caplog.messages), (
        "Expected a C-1f fallback WARNING to be logged when mirror is absent. "
        f"Messages seen: {caplog.messages}"
    )


def test_c1f_both_absent_returns_none():
    """(b-variant) No mirror row + no cache id → returns None. No crash."""
    product_code = "TEST-C1F-004"

    db_path = _make_empty_mirror_db()

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value=None):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result is None, (
        f"Both mirror and cache absent → must return None, got {result!r}."
    )


# ── Test (c): divergence path — mirror id used, WARNING logged ───────────────

def test_c1f_divergence_uses_mirror_and_logs_warning(caplog):
    """(c) When mirror id != cache id (data divergence), the MIRROR id wins and a
    WARNING is logged with both ids. This is the loud-surfacing design requirement:
    divergence is never silent.
    """
    product_code = "TEST-C1F-005"
    mirror_id = "WFIRMA-005-MIRROR"
    cache_id  = "WFIRMA-005-CACHE-STALE"

    db_path = _make_mirror_db(product_code, mirror_id)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value={"wfirma_product_id": cache_id}), \
         caplog.at_level(logging.WARNING):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result == mirror_id, (
        f"On divergence, mirror id {mirror_id!r} must win over cache id {cache_id!r}. "
        f"Got {result!r}."
    )
    assert any("C-1f" in m and "divergence" in m for m in caplog.messages), (
        "Expected a C-1f divergence WARNING to be logged. "
        f"Messages: {caplog.messages}"
    )


# ── Test (d): mirror db file absent ──────────────────────────────────────────

def test_c1f_missing_db_falls_back_to_cache():
    """When the reservation_queue.db file doesn't exist yet (first boot),
    returns the cache id without crashing.
    """
    product_code = "TEST-C1F-006"
    cache_id = "WFIRMA-006"

    non_existent = Path("/tmp/does_not_exist_c1f_test/reservation_queue.db")

    with patch.object(rp, "_c1f_rdb_path", return_value=non_existent), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value={"wfirma_product_id": cache_id}):

        result = rp._c1f_mirror_good_id_with_fallback(product_code)

    assert result == cache_id, (
        f"Missing DB → must fall back to cache id {cache_id!r}, got {result!r}."
    )


# ── Test: get_mirror_products_batch accessor ─────────────────────────────────

def test_rdb_get_mirror_products_batch_returns_correct_rows():
    """get_mirror_products_batch() returns a dict keyed by product_code."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db_path)
        rdb.upsert_product_mirror(db_path, wfirma_id="WF-A", product_code="CODE-A")
        rdb.upsert_product_mirror(db_path, wfirma_id="WF-B", product_code="CODE-B")

        result = rdb.get_mirror_products_batch(db_path, ["CODE-A", "CODE-B", "CODE-MISSING"])

    assert "CODE-A" in result
    assert "CODE-B" in result
    assert "CODE-MISSING" not in result
    assert result["CODE-A"]["wfirma_id"] == "WF-A"
    assert result["CODE-B"]["wfirma_id"] == "WF-B"


def test_rdb_get_mirror_product_returns_none_for_missing():
    """get_mirror_product() returns None when no row exists."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db_path)
        result = rdb.get_mirror_product(db_path, "NONEXISTENT")

    assert result is None


def test_rdb_list_mirror_products_returns_all_rows():
    """list_mirror_products() returns all rows including those with empty wfirma_id."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "reservation_queue.db"
        rdb.init_reservation_db(db_path)
        rdb.upsert_product_mirror(db_path, wfirma_id="WF-X", product_code="CODE-X")
        # Insert a row with empty wfirma_id (e.g. pending mapping)
        rdb.upsert_product_mirror(db_path, wfirma_id="", product_code="CODE-Y")

        rows = rdb.list_mirror_products(db_path)

    codes = {r["product_code"] for r in rows}
    assert "CODE-X" in codes
    assert "CODE-Y" in codes
    wf_ids = {r["wfirma_id"] for r in rows}
    assert "WF-X" in wf_ids

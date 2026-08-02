"""test_c1f_mirror_first_reads.py — mirror-only fiscal-read gate (C-1f → C-3g).

What this file pins
-------------------
`_c1f_mirror_good_id()` is the single fiscal read that every migrated proforma
site shares. Its contract, since C-3g, is **mirror-only**:

  (a) mirror row confirmed  → return the mirror wfirma_id
  (b) mirror row absent     → return None. There is no cache fallback.
  (c) mirror wfirma_id empty→ return None
  (d) mirror db file absent → return None, without crashing

Why these tests changed
-----------------------
C-1f (``6a781ee4``) introduced `_c1f_mirror_good_id_with_fallback()`: mirror-first
with a logged fallback to the wfirma cache, and a WARNING when the two ids
diverged. That was a migration scaffold, deliberately retired by C-3g
(``568c05b2`` *"mirror-only product reads; retire cache passthroughs"*), which
deleted both `_c1f_mirror_good_id_with_fallback()` and
`_c1f_mirror_good_id_or_cache_truthiness()`, migrated every call site to
`_c1f_mirror_good_id()`, and deleted `reservation_db.get_cached_product`.

This file was written against the scaffold and never followed. Six tests called
the deleted helper and died with ``AttributeError`` before asserting anything;
three of them asserted cache-fallback behaviour that C-3g removed **on purpose**.

So the repair is not a rename. Tests (b) and (d) are inverted: they now assert
that the fallback is *gone*, which is what the production contract says. The
cache accessor is still patched in every case — not to be consumed, but to
assert it is **never called**, so a future reintroduction of a cache passthrough
into the fiscal read path fails here loudly.

The production helper is unchanged by this file.
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
    """(a) Mirror row confirmed → the mirror wfirma_id is returned.

    The cache is stubbed with the *same* id (the normal post-backfill state) and
    asserted never to be called, so agreement between the two can never be what
    makes this pass.
    """
    product_code = "TEST-C1F-001"
    mirror_id = "WFIRMA-001"

    db_path = _make_mirror_db(product_code, mirror_id)
    cache = MagicMock(return_value={"wfirma_product_id": mirror_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache):

        result = rp._c1f_mirror_good_id(product_code)

    assert result == mirror_id, (
        f"Expected mirror id {mirror_id!r}, got {result!r}. "
        "Mirror-only must return the mirror id when the row is confirmed."
    )
    cache.assert_not_called()


def test_c1f_mirror_returns_mirror_id_even_when_cache_absent():
    """(a-variant) Mirror confirmed, cache empty → mirror id still returned.
    The mirror is authoritative independently of the cache.
    """
    product_code = "TEST-C1F-002"
    mirror_id = "WFIRMA-002"

    db_path = _make_mirror_db(product_code, mirror_id)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value=None):

        result = rp._c1f_mirror_good_id(product_code)

    assert result == mirror_id, (
        f"Expected mirror id {mirror_id!r}, got {result!r}. "
        "Mirror row present + cache absent → mirror id must be returned."
    )


# ── Test (b): mirror absent → None. The cache fallback is retired ────────────

def test_c1f_no_cache_fallback_when_mirror_absent(caplog):
    """(b) Mirror absent + cache holding an id → **None**, and the cache is never read.

    C-3g retired the C-1f cache fallback deliberately: an id that exists only in
    the wfirma cache is not a confirmed fiscal identity, and silently borrowing it
    is exactly the dual-write drift that migration removed. Inverted from the old
    `test_c1f_fallback_to_cache_when_mirror_absent`, which asserted the scaffold.
    """
    product_code = "TEST-C1F-003"
    cache_id = "WFIRMA-003"

    db_path = _make_empty_mirror_db()
    cache = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache), \
         caplog.at_level(logging.WARNING):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, (
        f"Mirror absent → must return None, got {result!r}. "
        f"Returning the cache id {cache_id!r} would resurrect the retired C-1f fallback."
    )
    cache.assert_not_called()


def test_c1f_empty_mirror_id_is_not_a_confirmed_identity():
    """A mirror row that exists with an empty wfirma_id (mapping pending) is not
    a confirmed id — it must read as None, not as an empty-string good_id."""
    product_code = "TEST-C1F-007"

    db_path = _make_empty_mirror_db()
    rdb.upsert_product_mirror(db_path, wfirma_id="", product_code=product_code)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value=None):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, f"Empty mirror wfirma_id must read as None, got {result!r}."


def test_c1f_both_absent_returns_none():
    """(b-variant) No mirror row + no cache id → returns None. No crash."""
    product_code = "TEST-C1F-004"

    db_path = _make_empty_mirror_db()

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value=None):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, (
        f"Both mirror and cache absent → must return None, got {result!r}."
    )


# ── Test (c): a stale cache id cannot influence the fiscal read ──────────────

def test_c1f_stale_cache_id_is_ignored_entirely(caplog):
    """(c) Mirror id != cache id → the mirror id is returned and the cache is
    never consulted.

    Under C-1f this was a divergence *detection* case that logged a WARNING.
    Mirror-only cannot detect divergence, because it never reads the cache — a
    strictly stronger guarantee than logging one. Inverted from the old
    `test_c1f_divergence_uses_mirror_and_logs_warning`.
    """
    product_code = "TEST-C1F-005"
    mirror_id = "WFIRMA-005-MIRROR"
    cache_id  = "WFIRMA-005-CACHE-STALE"

    db_path = _make_mirror_db(product_code, mirror_id)
    cache = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache), \
         caplog.at_level(logging.WARNING):

        result = rp._c1f_mirror_good_id(product_code)

    assert result == mirror_id, (
        f"Mirror id {mirror_id!r} must win over stale cache id {cache_id!r}. "
        f"Got {result!r}."
    )
    cache.assert_not_called()


# ── Test (d): mirror db file absent ──────────────────────────────────────────

def test_c1f_missing_db_returns_none_without_crashing():
    """Mirror db file absent (first boot) → None, no exception, no cache read.

    Inverted from `test_c1f_missing_db_falls_back_to_cache`: a missing mirror is
    an unresolved identity, not a reason to reach into the cache.
    """
    product_code = "TEST-C1F-006"
    cache_id = "WFIRMA-006"

    non_existent = Path("/tmp/does_not_exist_c1f_test/reservation_queue.db")
    cache = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=non_existent), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, (
        f"Missing mirror db → must return None, got {result!r}."
    )
    cache.assert_not_called()


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

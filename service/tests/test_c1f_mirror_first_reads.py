"""test_c1f_mirror_first_reads.py — mirror-only read gate (C-1f, as amended by C-3g).

This file originally pinned C-1f's `_c1f_mirror_good_id_with_fallback()`, whose
contract was mirror-first WITH a wfirma_db cache fallback: mirror absent → return
the cache id and log a warning. **C-3g removed that fallback**, renaming the
helper to `_c1f_mirror_good_id()` and making the mirror the sole identity
authority (`routes_proforma.py:80` "C-1f/C-3g: mirror-only fiscal read helpers";
`_c1f_product_mapping_lookup` docstring "C-3g: no cache fallback"). The cache is
no longer consulted at all on this path — which is the MASTER CONSUMPTION RULE
applied to fiscal reads, and is separately pinned by
`test_master_consumption_rule.py`.

The tests below therefore assert the CURRENT contract, not the removed one:

  (a) mirror row confirmed          → mirror id
  (b) mirror row absent             → None, and the cache is NOT consulted
  (c) mirror db file absent         → None, and the cache is NOT consulted
  (d) mirror id present, cache stale/divergent → mirror id (cache never read)

(b) and (c) are strictly STRONGER than the assertions they replace: they no
longer merely tolerate a cache read, they prove it does not happen — a cache
fallback reintroduced here would fail this file rather than silently restore a
second product-identity authority.
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
    """(a) When the mirror has a confirmed non-empty wfirma_id for a product_code,
    _c1f_mirror_good_id() returns the mirror id — regardless of what the cache
    has. With mirror and cache agreeing (normal production state after backfill)
    the payload good_id is byte-identical to the pre-C-1f cache read.
    """
    product_code = "TEST-C1F-001"
    mirror_id = "WFIRMA-001"
    cache_id = "WFIRMA-001"  # same as mirror — the normal case

    db_path = _make_mirror_db(product_code, mirror_id)

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", return_value={"wfirma_product_id": cache_id}):

        result = rp._c1f_mirror_good_id(product_code)

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

        result = rp._c1f_mirror_good_id(product_code)

    assert result == mirror_id, (
        f"Expected mirror id {mirror_id!r}, got {result!r}. "
        "Mirror row present + cache absent → mirror id must be returned."
    )


# ── Test (b): mirror absent → None, and the cache is never consulted ─────────

def test_c1f_mirror_absent_returns_none_and_never_reads_cache():
    """(b) C-3g: no cache fallback. When no mirror row exists for a product_code,
    _c1f_mirror_good_id() returns None EVEN IF the cache holds an id — and it must
    not call into wfirma_db at all.

    This replaces the pre-C-3g `test_c1f_fallback_to_cache_when_mirror_absent`,
    which asserted the opposite (cache id returned + "falling back" WARNING). The
    fallback was removed deliberately: a cache read here would make wfirma_db a
    second product-identity authority alongside the mirror.
    """
    product_code = "TEST-C1F-003"
    cache_id = "WFIRMA-003"

    db_path = _make_empty_mirror_db()
    cache_probe = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache_probe):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, (
        f"Mirror absent → must return None (C-3g removed the cache fallback), "
        f"got {result!r}."
    )
    cache_probe.assert_not_called()


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


# ── Test (d): a stale cache cannot influence the result ─────────────────────

def test_c1f_stale_cache_cannot_override_the_mirror():
    """(d) With a mirror row present and a DIVERGENT cache id, the mirror id is
    returned and the cache is never consulted.

    This replaces the pre-C-3g `test_c1f_divergence_uses_mirror_and_logs_warning`.
    That test also required a "divergence" WARNING, which only existed because the
    old helper read BOTH sources and could compare them. Under C-3g there is
    nothing to compare — divergence is structurally impossible on this path
    because only one source is read. Asserting the cache is untouched is the
    stronger guarantee and the one that matches the code.
    """
    product_code = "TEST-C1F-005"
    mirror_id = "WFIRMA-005-MIRROR"
    cache_id  = "WFIRMA-005-CACHE-STALE"

    db_path = _make_mirror_db(product_code, mirror_id)
    cache_probe = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=db_path), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache_probe):

        result = rp._c1f_mirror_good_id(product_code)

    assert result == mirror_id, (
        f"Mirror id {mirror_id!r} must win over stale cache id {cache_id!r}. "
        f"Got {result!r}."
    )
    cache_probe.assert_not_called()


# ── Test (c): mirror db file absent ─────────────────────────────────────────

def test_c1f_missing_db_returns_none_without_crashing():
    """(c) When reservation_queue.db doesn't exist yet (first boot), return None
    without crashing — and without reaching for the cache.

    Replaces the pre-C-3g `test_c1f_missing_db_falls_back_to_cache`. A missing
    mirror is 'identity not established', not 'ask the cache instead'.
    """
    product_code = "TEST-C1F-006"
    cache_id = "WFIRMA-006"

    non_existent = Path("/tmp/does_not_exist_c1f_test/reservation_queue.db")
    cache_probe = MagicMock(return_value={"wfirma_product_id": cache_id})

    with patch.object(rp, "_c1f_rdb_path", return_value=non_existent), \
         patch.object(wfdb_module, "_db_path", Path("/fake/wfirma.db")), \
         patch.object(wfdb_module, "get_product", cache_probe):

        result = rp._c1f_mirror_good_id(product_code)

    assert result is None, (
        f"Missing mirror db → must return None (no cache fallback), got {result!r}."
    )
    cache_probe.assert_not_called()


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

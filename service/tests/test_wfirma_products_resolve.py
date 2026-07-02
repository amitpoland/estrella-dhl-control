"""
test_wfirma_products_resolve.py — unit tests for POST .../wfirma/products/resolve
and product_code presence in PZ_READY JSON.

Covers:
  1. PZ_READY JSON includes product_code field in every row
  2. Already-mapped product_code is skipped (already_mapped counter increments)
  3. goods/find match is saved to wfirma_products table (found_and_mapped)
  4. Missing + WFIRMA_CREATE_PRODUCT_ALLOWED=false → reported in missing_codes
  5. Missing + WFIRMA_CREATE_PRODUCT_ALLOWED=true → creates product via goods/add
  6. goods/add failure writes no mapping (no fake rows in DB)
  7. Idempotent rerun: re-calling with all already mapped → already_mapped == considered
  8. pz_preview ready=true after all products mapped (integration through resolve)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

import sqlite3
from app.services import reservation_db as _rdb


def _mirror_row(db, code):
    """Read a wfirma_product_mirror row (or None) for DB-readback assertions."""
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM wfirma_product_mirror WHERE product_code=?", (code,)
    ).fetchone()
    con.close()
    return dict(row) if row else None


# ── Shared fixtures ────────────────────────────────────────────────────────────

_BATCH = "TEST_RESOLVE_001"

# Minimal audit that passes _guard_wfirma_export
_AUDIT = {
    "batch_id": _BATCH,
    "status": "processed",
    "customs_declaration": {
        "mrn": "26PL321000E0TEST123",
        "clearance_date": "2026-05-01",
    },
    "inputs": {},
}

# Row shape as returned by _build_rows (the private helper in routes_wfirma)
def _make_row(product_code: str, qty: float = 2.0, price: float = 173.00) -> dict:
    return {
        "product_code":   product_code,
        "_product_code":  product_code,
        "item_type":      "wisiorek",
        "description_en": "Silver Pendant",
        "pl_desc":        "Wisiorek",
        "quantity":       qty,
        "unit_netto_pln": price,
        "_unit_netto_pln": price,
        "invoice_no":     "EJL/26-27/013",
    }


def _make_wfirma_product(wfirma_id: str, code: str):
    """Build a WFirmaProduct-compatible mock object."""
    from app.services.wfirma_client import WFirmaProduct
    return WFirmaProduct(wfirma_id=wfirma_id, name="Wisiorek", code=code)


# ── Test 1: PZ_READY JSON includes product_code in every row ──────────────────

def test_pz_ready_json_includes_product_code():
    """
    _build_wfirma_rows must attach product_code to every row so it ends up
    in the PZ_READY JSON serialised output.
    """
    from app.api.routes_wfirma import _build_wfirma_rows

    rows = [
        {
            "supplier":         "Estrella Jewels LLP",
            "item_type":        "wisiorek",
            "product_code":     "EJL/26-27/013-1",
            "description_en":   "Silver Pendant",
            "quantity":         3,
            "unit_netto_pln":   173.00,
            "invoice_no":       "EJL/26-27/013",
        },
        {
            "supplier":         "Estrella Jewels LLP",
            "item_type":        "pierścionek",
            "product_code":     "EJL/26-27/013-2",
            "description_en":   "Gold Ring",
            "quantity":         1,
            "unit_netto_pln":   550.00,
            "invoice_no":       "EJL/26-27/013",
        },
    ]
    audit = {"customs_declaration": {"exporter_name": "Estrella Jewels LLP"}}
    with_warnings = _build_wfirma_rows(rows, audit)

    assert len(with_warnings) == 2
    assert with_warnings[0]["_product_code"] == "EJL/26-27/013-1"
    assert with_warnings[1]["_product_code"] == "EJL/26-27/013-2"


# ── Test 2: Already-mapped product is skipped (idempotency) ───────────────────

def test_already_mapped_product_skipped():
    """
    When a product_code already has a wfirma_product_id in the local table,
    the resolve endpoint must increment already_mapped and not call goods/find.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    """
    rows = [_make_row("EJL/26-27/013-1")]

    with (
        patch("app.api.routes_wfirma.get_output_dir") as mock_dir,
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: resolve reads the already-mapped cache via rdb.get_cached_products_batch.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch",
              return_value={"EJL/26-27/013-1": {"wfirma_product_id": "48611875",
                                                "product_name": "Wisiorek"}}),
        patch("app.api.routes_wfirma.rdb.list_cached_products",
              return_value=[{"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"}]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code") as mock_find,
    ):
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    mock_find.assert_not_called()
    assert body["already_mapped"] == 1
    assert body["found_and_mapped"] == 0
    assert body["missing_codes"] == []


# ── Test 3: goods/find match saved to wfirma_products ─────────────────────────

def test_goods_find_match_saved_to_db():
    """
    When local table has no entry but goods/find returns a product,
    the mapping must be registered and found_and_mapped incremented.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    rdb.register_product_identity is the new dual-write path.
    """
    rows = [_make_row("EJL/26-27/013-1")]
    found_product = _make_wfirma_product("48611875", "EJL/26-27/013-1")

    registered: List[dict] = []

    def fake_register(db_path, *, wfirma_id, product_code, name="",
                      also_set_master_status=None, cache_kwargs):
        registered.append({"wfirma_id": wfirma_id, "product_code": product_code,
                            **cache_kwargs})
        return {"collision": False, "cache_row_id": 1}

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: resolve reads the local cache via rdb.get_cached_products_batch —
        # empty cache forces the goods/find path.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.register_product_identity", side_effect=fake_register),
        patch("app.api.routes_wfirma.rdb.list_cached_products",
              return_value=[{"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"}]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code",
              return_value=found_product),
    ):
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    assert body["found_and_mapped"] == 1
    assert body["missing"] == 0
    assert len(registered) == 1
    assert registered[0]["product_code"] == "EJL/26-27/013-1"
    assert registered[0]["wfirma_product_id"] == "48611875"


# ── Test 4: Missing + gate off → reported in missing_codes ────────────────────

def test_missing_gate_off_reported_not_created(tmp_path):
    """
    When goods/find returns None and WFIRMA_CREATE_PRODUCT_ALLOWED=False,
    the code must appear in missing_codes and goods/add must never be called.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    """
    rows = [_make_row("EJL/26-27/013-UNKNOWN")]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: reads routed through rdb sync layer.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.list_cached_products", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code", return_value=None),
        patch("app.api.routes_wfirma.wfirma_client.create_product") as mock_create,
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = False
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        # C-1b: the Master-first write path needs a real reservation_queue.db.
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    mock_create.assert_not_called()
    assert "EJL/26-27/013-UNKNOWN" in body["missing_codes"]
    assert body["missing"] == 1
    assert body["ready_for_pz"] is False
    # C-1b invariant: Master written (sync-pending) even with the gate off; and
    # NO mirror linkage while the sync is pending.
    _db = tmp_path / "reservation_queue.db"
    _m = _rdb.get_product_master(_db, "EJL/26-27/013-UNKNOWN")
    assert _m is not None and _m["status"] == "mapping_required"
    assert _mirror_row(_db, "EJL/26-27/013-UNKNOWN") is None


# ── Test 5: Missing + gate on → creates product ────────────────────────────────

def test_missing_gate_on_creates_product(tmp_path):
    """
    When goods/find returns None and WFIRMA_CREATE_PRODUCT_ALLOWED=True,
    create_product must be called and the mapping registered on success.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    register_product_identity is the new dual-write; assertions updated accordingly.
    """
    rows = [_make_row("EJL/26-27/013-NEW", price=173.00)]
    created_product = _make_wfirma_product("99999999", "EJL/26-27/013-NEW")

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: reads routed through rdb sync layer.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.list_cached_products",
              return_value=[{"product_code": "EJL/26-27/013-NEW", "wfirma_product_id": "99999999"}]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code", return_value=None),
        patch("app.api.routes_wfirma.wfirma_client.create_product", return_value=created_product),
        patch("app.api.routes_wfirma.wfirma_client.find_vat_code_id", return_value="12345"),
        patch("app.api.routes_wfirma.deng.get_description_block",
              return_value={"description_line": "Wisiorek srebrny", "name_pl": "Wisiorek", "description_block": ""}),
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = True
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        # C-1e: register_product_identity writes mirror + cache; real db needed.
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    assert body["created"] == 1
    assert body["missing"] == 0
    assert body["missing_codes"] == []
    # C-1e invariant: mirror linkage written by register_product_identity.
    _db = tmp_path / "reservation_queue.db"
    assert _rdb.get_product_master(_db, "EJL/26-27/013-NEW")["status"] == "mapped"
    _mr = _mirror_row(_db, "EJL/26-27/013-NEW")
    assert _mr is not None and _mr["wfirma_id"] == "99999999"


# ── Test 6: goods/add failure writes no mapping ────────────────────────────────

def test_create_failure_writes_no_mapping(tmp_path):
    """
    When create_product raises an exception, no fake mapping must be written.
    The code appears in failed_details, not missing_codes.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    register_product_identity is NOT called when create_product fails (code
    reaches continue before the write site).
    """
    rows = [_make_row("EJL/26-27/013-FAIL")]
    registered: List[dict] = []

    def fake_register(db_path, *, wfirma_id, product_code, name="",
                      also_set_master_status=None, cache_kwargs):
        registered.append({"wfirma_id": wfirma_id, "product_code": product_code})
        return {"collision": False, "cache_row_id": 1}

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: reads routed through rdb sync layer.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.register_product_identity", side_effect=fake_register),
        patch("app.api.routes_wfirma.rdb.list_cached_products", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code", return_value=None),
        patch("app.api.routes_wfirma.wfirma_client.create_product",
              side_effect=RuntimeError("wFirma API timeout")),
        patch("app.api.routes_wfirma.wfirma_client.find_vat_code_id", return_value="12345"),
        patch("app.api.routes_wfirma.deng.get_description_block",
              return_value={"description_line": "Wisiorek", "name_pl": "Wisiorek", "description_block": ""}),
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = True
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        # C-1e: Master-first write path needs a real reservation_queue.db.
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    # No fake mapping must be written (create failed before write site 2).
    assert registered == []
    # Must appear in failed_details
    assert body["failed"] == 1
    assert any("EJL/26-27/013-FAIL" in d["product_code"] for d in body["failed_details"])
    assert body["created"] == 0


# ── Test 7: Idempotent rerun ───────────────────────────────────────────────────

def test_idempotent_rerun_increments_already_mapped():
    """
    Calling resolve twice when all products are already mapped must produce
    already_mapped == considered and skip all network calls.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    """
    rows = [_make_row("EJL/26-27/013-1"), _make_row("EJL/26-27/013-2", price=176.50)]
    db_entries = [
        {"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"},
        {"product_code": "EJL/26-27/013-2", "wfirma_product_id": "48612067"},
    ]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: reads routed through rdb sync layer.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch",
              return_value={
                  "EJL/26-27/013-1": {"wfirma_product_id": "48611875", "product_name": "Wisiorek"},
                  "EJL/26-27/013-2": {"wfirma_product_id": "48612067", "product_name": "Wisiorek"},
              }),
        patch("app.api.routes_wfirma.rdb.list_cached_products", return_value=db_entries),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code") as mock_find,
        patch("app.api.routes_wfirma.wfirma_client.create_product") as mock_create,
    ):
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    mock_find.assert_not_called()
    mock_create.assert_not_called()
    assert body["considered"] == 2
    assert body["already_mapped"] == 2
    assert body["found_and_mapped"] == 0
    assert body["created"] == 0


# ── Test 8: ready_for_pz=true when all products mapped ────────────────────────

def test_ready_for_pz_true_when_all_mapped(tmp_path):
    """
    After resolve succeeds for all product_codes, ready_for_pz must be True
    and unresolved_product_codes must be empty.
    C-1e: patches updated from wfirma_db.* to rdb.* (sync layer passthroughs).
    """
    rows = [
        _make_row("EJL/26-27/013-1", qty=3.0, price=173.00),
        _make_row("EJL/26-27/013-2", qty=2.0, price=176.50),
    ]
    db_entries = [
        {"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"},
        {"product_code": "EJL/26-27/013-2", "wfirma_product_id": "48612067"},
    ]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # C-1e: reads routed through rdb sync layer.
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch",
              return_value={
                  "EJL/26-27/013-1": {"wfirma_product_id": "48611875", "product_name": "Wisiorek"},
                  "EJL/26-27/013-2": {"wfirma_product_id": "48612067", "product_name": "Wisiorek"},
              }),
        patch("app.api.routes_wfirma.rdb.list_cached_products", return_value=db_entries),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code") as mock_find,
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_find.return_value = None  # not called — already_mapped path taken
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        mock_settings.wfirma_create_product_allowed = False
        # C-1e: resolve initialises the reservation_queue.db handle up front.
        mock_settings.storage_root = tmp_path

        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    assert body["ready_for_pz"] is True
    assert body["unresolved_product_codes"] == []
    assert body["price_conflicts"] == []
    assert body["missing"] == 0


# ── C-1e: mirror-write pins (write sites 1 + 2) ──────────────────────────────

def test_c1e_goods_find_path_writes_mirror(tmp_path):
    """C-1e write-site 1: when goods/find returns a product (found path),
    register_product_identity must write the mirror row with the confirmed
    wfirma_id. The mirror must exist in reservation_queue.db after the call."""
    import sqlite3
    from app.services import wfirma_client as _wc

    pc   = "EJL/C1E/FIND-1"
    wfid = "WF-FIND-7001"
    found_product = _wc.WFirmaProduct(
        wfirma_id=wfid, name="Test Ring", code=pc, unit="szt.", count=0, reserved=0,
    )
    rows = [_make_row(pc)]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        # Empty cache forces goods/find path (write site 1).
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.list_cached_products",
              return_value=[{"product_code": pc, "wfirma_product_id": wfid}]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code",
              return_value=found_product),
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = False
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    assert body["found_and_mapped"] == 1, f"expected found_and_mapped=1, got: {body}"
    # C-1e invariant: mirror row written by register_product_identity (write site 1).
    db_path = tmp_path / "reservation_queue.db"
    assert db_path.exists(), "reservation_queue.db must be auto-created"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    mrow = con.execute(
        "SELECT wfirma_id FROM wfirma_product_mirror WHERE product_code=?", (pc,)
    ).fetchone()
    con.close()
    assert mrow is not None, "C-1e write-site 1: mirror row must exist after found path"
    assert mrow["wfirma_id"] == wfid, (
        f"C-1e write-site 1: mirror wfirma_id must match confirmed id ({wfid!r}), "
        f"got {mrow['wfirma_id']!r}"
    )


def test_c1e_found_path_collision_returns_per_item_error(tmp_path):
    """C-1e write-site 1: when the confirmed wfirma_id already belongs to a different
    product_code in the mirror, the found path must report wfirma_id_collision per-item
    and NOT increment found_and_mapped (batch continues for other items)."""
    import sqlite3
    from app.services import wfirma_client as _wc
    from app.services import reservation_db as _rdb2

    pc_owner  = "EJL/C1E/COL-OWNER"
    pc_second = "EJL/C1E/COL-SECOND"
    shared_id = "WF-SHARED-C1E-99"

    # Pre-seed the mirror with pc_owner owning shared_id.
    db_path = tmp_path / "reservation_queue.db"
    _rdb2.init_reservation_db(db_path)
    _rdb2.upsert_product_mirror(db_path, wfirma_id=shared_id, product_code=pc_owner)

    found_second = _wc.WFirmaProduct(
        wfirma_id=shared_id, name="Collision Pendant", code=pc_second,
        unit="szt.", count=0, reserved=0,
    )
    rows = [_make_row(pc_second)]

    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma.rdb.get_cached_products_batch", return_value={}),
        patch("app.api.routes_wfirma.rdb.list_cached_products", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_client.get_product_by_code",
              return_value=found_second),
        patch("app.api.routes_wfirma.settings") as mock_settings,
    ):
        mock_settings.wfirma_create_product_allowed = False
        mock_settings.wfirma_supplier_contractor_id = "38142296"
        mock_settings.wfirma_warehouse_id = "347088"
        mock_settings.storage_root = tmp_path
        from app.api.routes_wfirma import wfirma_products_resolve
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_products_resolve(_BATCH)
        )
        body = json.loads(result.body)

    assert body["found_and_mapped"] == 0, (
        "C-1e write-site 1: collision must NOT increment found_and_mapped"
    )
    assert body["failed"] == 1, "C-1e write-site 1: collision must appear in failed"
    collision_detail = next(
        (d for d in body["failed_details"] if d.get("product_code") == pc_second), None
    )
    assert collision_detail is not None, "C-1e: collision detail missing from failed_details"
    assert collision_detail.get("error") == "wfirma_id_collision", (
        f"C-1e write-site 1: error must be wfirma_id_collision, got {collision_detail!r}"
    )

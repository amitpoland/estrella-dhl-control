"""Tests for Slice 1 — product_master_sync (the ONE Product Master sync).

Covers:
  * build_variant_signature — normalization / ordering / numeric folding
  * run_product_master_sync — projects every purchase product_code into the
    Master with a populated variant signature (a); idempotent (b); never invents
    a product_code / skips blanks (c); composes the description step live (d);
    wFirma goods step runs DRY-RUN, zero create calls (e); status envelope (f).

Governance the tests pin:
  * product_code is read from packing_lines, never minted here.
  * the Master is written but gates nothing; packing_lines is untouched.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import reservation_db as rdb
from app.services import product_master_sync as pms
from app.services.cpa_product_service import build_variant_signature


# ── fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect all storage to tmp and initialise the three DBs the sync uses."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path


def _rdb_path(env) -> Path:
    return env / "reservation_queue.db"


def _seed_packing(batch_id: str, rows: list[dict]) -> None:
    """Insert packing_lines rows directly (FK off on a raw connection)."""
    now = "2026-07-06T00:00:00Z"
    con = sqlite3.connect(str(pdb._db_path))
    try:
        for i, r in enumerate(rows):
            con.execute(
                """INSERT INTO packing_lines
                   (id, packing_document_id, batch_id, invoice_no,
                    invoice_line_position, product_code, design_no, item_type,
                    metal, karat, metal_color, quality_string, diamond_weight,
                    color_weight, stone_type, size, quantity, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), "doc-1", batch_id, r.get("invoice_no", "INV/1"),
                 i + 1, r.get("product_code"), r.get("design_no", ""),
                 r.get("item_type", "ring"), r.get("metal", ""), r.get("karat", ""),
                 r.get("metal_color", ""), r.get("quality_string", ""),
                 float(r.get("diamond_weight", 0.0) or 0.0),
                 float(r.get("color_weight", 0.0) or 0.0),
                 r.get("stone_type", ""), r.get("size", ""),
                 float(r.get("quantity", 1.0) or 0.0), now, now),
            )
        con.commit()
    finally:
        con.close()


# A spy result for the wFirma goods step (never touches the network).
def _mirror_spy():
    calls = []

    def _fake(batch_id, *, dry_run=False, operator="operator"):
        calls.append({"batch_id": batch_id, "dry_run": dry_run})
        return {"batch_id": batch_id, "dry_run": dry_run, "scanned": 0,
                "created": 0, "errors": []}

    return _fake, calls


# ── build_variant_signature ──────────────────────────────────────────────────

def test_variant_signature_orders_and_normalizes():
    row = {"design_no": "cstr07596", "karat": "14kt", "metal_color": "w",
           "diamond_weight": 0.50, "quality_string": "g-vs lab",
           "color_weight": 0.0, "stone_type": "", "size": "  7 "}
    sig = build_variant_signature(row)
    # 8 pipe-separated tokens in the fixed authority order:
    # design_no|karat|metal_color|diamond_weight|quality_string|color_weight|stone_type|size
    assert sig == "CSTR07596|14KT|W|0.5|G-VS LAB|||7"
    assert sig.split("|") == ["CSTR07596", "14KT", "W", "0.5", "G-VS LAB", "", "", "7"]


def test_variant_signature_numeric_folding_equal():
    a = build_variant_signature({"design_no": "D1", "diamond_weight": 0.50})
    b = build_variant_signature({"design_no": "D1", "diamond_weight": 0.5})
    assert a == b  # 0.50 and 0.5 collapse to the same token


def test_variant_signature_blank_row_is_all_empty_tokens():
    assert build_variant_signature({}) == "|||||||"


# ── run_product_master_sync ──────────────────────────────────────────────────

def test_sync_projects_every_code_with_variant_signature(env):
    """(a) every purchase product_code lands in the Master with its signature."""
    batch = "SHIPMENT_TEST_A"
    rows = [
        {"product_code": "EJL/26-27/001-1", "design_no": "CSTR001", "karat": "14KT",
         "metal_color": "W", "diamond_weight": 0.5, "quality_string": "G-VS", "size": "7"},
        {"product_code": "EJL/26-27/001-2", "design_no": "CSTR002", "karat": "18KT",
         "metal_color": "Y", "diamond_weight": 1.0, "quality_string": "F-VVS", "size": "6"},
    ]
    _seed_packing(batch, rows)
    fake, _calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        res = pms.run_product_master_sync(batch, dry_run=False)

    assert res["processed"] == 2
    assert res["created"] == 2
    assert res["updated"] == 0
    assert res["skipped"] == 0

    db = _rdb_path(env)
    for r in rows:
        pm = rdb.get_product_master(db, r["product_code"])
        assert pm is not None
        assert pm["normalized_design_attributes"] == build_variant_signature(r)


def test_sync_is_idempotent(env):
    """(b) second run creates nothing; the same codes update."""
    batch = "SHIPMENT_TEST_B"
    rows = [{"product_code": "EJL/26-27/010-1", "design_no": "D010", "karat": "14KT"}]
    _seed_packing(batch, rows)
    fake, _calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        r1 = pms.run_product_master_sync(batch, dry_run=False)
        r2 = pms.run_product_master_sync(batch, dry_run=False)

    assert r1["created"] == 1 and r1["updated"] == 0
    assert r2["created"] == 0 and r2["updated"] == 1

    db = _rdb_path(env)
    with sqlite3.connect(str(db)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM product_master WHERE product_code=?",
            ("EJL/26-27/010-1",),
        ).fetchone()[0]
    assert n == 1


def test_sync_never_invents_product_code(env):
    """(c) blank-product_code packing rows are skipped, never minted."""
    batch = "SHIPMENT_TEST_C"
    rows = [
        {"product_code": "EJL/26-27/020-1", "design_no": "D020"},
        {"product_code": "", "design_no": "PND"},           # supplementary row
        {"product_code": None, "design_no": "NCK"},
    ]
    _seed_packing(batch, rows)
    fake, _calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        res = pms.run_product_master_sync(batch, dry_run=False)

    assert res["processed"] == 3
    assert res["created"] == 1
    assert res["skipped"] == 2

    db = _rdb_path(env)
    all_codes = [r["product_code"] for r in rdb.list_product_masters(db, source_batch_id=batch)]
    assert all_codes == ["EJL/26-27/020-1"]


def test_sync_writes_legal_polish_descriptions(env):
    """(d) the description step runs live and produces a legal Polish block."""
    batch = "SHIPMENT_TEST_D"
    rows = [{"product_code": "EJL/26-27/030-1", "design_no": "D030", "item_type": "ring"}]
    _seed_packing(batch, rows)
    fake, _calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        res = pms.run_product_master_sync(batch, dry_run=False)

    # the composed description step reported a live (non-dry) write
    assert res["descriptions"].get("dry_run") is False
    row = ddb.get_product_description("EJL/26-27/030-1")
    assert row is not None
    assert (row.get("description_pl") or "").strip() != ""


def test_mirror_step_runs_dry_run_zero_creates(env):
    """(e) the wFirma goods step is always invoked in dry-run (no create calls)."""
    batch = "SHIPMENT_TEST_E"
    _seed_packing(batch, [{"product_code": "EJL/26-27/040-1", "design_no": "D040"}])
    fake, calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        pms.run_product_master_sync(batch, dry_run=False)

    assert len(calls) == 1
    assert calls[0]["dry_run"] is True


def test_status_envelope_shape_after_run(env):
    """(f) status endpoint returns the canonical four-questions envelope."""
    batch = "SHIPMENT_TEST_F"
    _seed_packing(batch, [{"product_code": "EJL/26-27/050-1", "design_no": "D050"}])
    fake, _calls = _mirror_spy()

    # before any run: honest 'never run'
    pre = pms.get_status(batch)
    assert pre["ever_run"] is False and pre["running"] is False

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        pms.run_product_master_sync(batch, dry_run=False)

    st = pms.get_status(batch)
    for key in ("healthy", "running", "last_started_at", "last_completed_at",
                "processed", "created", "updated", "skipped", "errors"):
        assert key in st
    assert st["ever_run"] is True
    assert st["running"] is False
    assert st["processed"] == 1
    assert st["created"] == 1


def test_dry_run_writes_nothing(env):
    """dry_run previews counts and does NOT write the Master or the status row."""
    batch = "SHIPMENT_TEST_DRY"
    _seed_packing(batch, [{"product_code": "EJL/26-27/060-1", "design_no": "D060"}])
    fake, _calls = _mirror_spy()

    with patch("app.services.wfirma_product_auto_register.ensure_products_for_batch", fake):
        res = pms.run_product_master_sync(batch, dry_run=True)

    assert res["dry_run"] is True
    assert res["created"] == 1  # would-create
    db = _rdb_path(env)
    assert rdb.get_product_master(db, "EJL/26-27/060-1") is None       # nothing written
    assert rdb.get_product_master_sync_status(db, batch) is None       # status untouched

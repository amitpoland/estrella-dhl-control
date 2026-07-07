"""test_inventory_reconciliation.py — Inventory Intelligence Phase 1 (read-only).

Pins the read-only reconciliation engine + endpoint:
  1. no write SQL / authority grep (never writes product_master, packing_lines,
     sales_packing_lines, inventory_state; connection is query_only)
  2. blank product_code counted
  3. under-scan detected
  4. over-scan detected
  5. Product Master coverage calculated
  6. health status computed (healthy / warning / critical)
  7. endpoint is read-only (GET works, contract shape, zero mutation)
  8. Product Master is consumed ADVISORY only (never gates health)
"""
from __future__ import annotations

import itertools
import re
import sqlite3
import sys
from pathlib import Path

_run_ctr = itertools.count()

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_reconciliation_service as svc


# ── hermetic minimal DBs (only the columns the service reads) ────────────────

def _make_dbs(tmp: Path, inv_rows, pak_rows, master_codes):
    """inv_rows: (batch_id, product_code, state); pak_rows: (batch_id, product_code, qty)."""
    wh = tmp / "warehouse.db"
    pk = tmp / "packing.db"
    rq = tmp / "reservation_queue.db"

    con = sqlite3.connect(str(wh))
    con.execute("CREATE TABLE inventory_state (id TEXT, scan_code TEXT, product_code TEXT, "
                "design_no TEXT, batch_id TEXT, state TEXT, updated_at TEXT)")
    for i, (b, pc, st) in enumerate(inv_rows):
        con.execute("INSERT INTO inventory_state (id, scan_code, product_code, batch_id, state, updated_at) "
                    "VALUES (?,?,?,?,?,?)", (f"i{i}", f"scan{i}", pc, b, st, "2026-01-01T00:00:00+00:00"))
    con.commit(); con.close()

    con = sqlite3.connect(str(pk))
    con.execute("CREATE TABLE packing_lines (batch_id TEXT, product_code TEXT, quantity REAL)")
    for b, pc, q in pak_rows:
        con.execute("INSERT INTO packing_lines (batch_id, product_code, quantity) VALUES (?,?,?)", (b, pc, q))
    con.commit(); con.close()

    con = sqlite3.connect(str(rq))
    con.execute("CREATE TABLE product_master (product_code TEXT)")
    for pc in master_codes:
        con.execute("INSERT INTO product_master (product_code) VALUES (?)", (pc,))
    con.commit(); con.close()
    return wh, pk, rq


def _run(tmp, inv_rows, pak_rows, master_codes):
    sub = tmp / f"run{next(_run_ctr)}"
    sub.mkdir()
    wh, pk, rq = _make_dbs(sub, inv_rows, pak_rows, master_codes)
    return svc.compute_reconciliation(warehouse_db_path=wh, packing_db_path=pk, reservation_db_path=rq)


def _batch(report, bid):
    return next(b for b in report["batches"] if b["batch_id"] == bid)


# ── 1. no write SQL / authority grep ─────────────────────────────────────────

def test_no_write_sql_against_any_authority():
    src = Path(svc.__file__).read_text(encoding="utf-8")
    # No SQL write verb anywhere in the module.
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "REPLACE INTO", "DROP ", "ALTER ", "CREATE TABLE"):
        assert verb not in src.upper(), f"read-only service must not contain {verb!r}"
    # Each consumed authority is only ever SELECTed, never written.
    for tbl in ("product_master", "packing_lines", "inventory_state"):
        for m in re.finditer(rf"\b{tbl}\b", src):
            head = src[:m.start()].upper()
            # nearest preceding SQL keyword must be SELECT/FROM, never a write verb
            assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM|REPLACE INTO)\s+$",
                                 head.rstrip().rsplit("\n", 1)[-1]), f"write near {tbl}"
    # Phase 1 does not touch sales at all.
    assert "sales_packing_lines" not in src
    # Hard runtime read-only guard present.
    assert "query_only" in src


def test_connection_is_query_only_blocks_writes(tmp_path):
    wh, _, _ = _make_dbs(tmp_path, [("B", "PC1", "WAREHOUSE_STOCK")], [], [])
    con = svc._ro_connect(wh)
    assert con is not None
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO inventory_state (id) VALUES ('x')")
    con.close()


def test_missing_db_file_never_created(tmp_path):
    ghost = tmp_path / "nope.db"
    assert svc._ro_connect(ghost) is None
    assert not ghost.exists(), "read-only service must never create a DB file"


# ── 2. blank product_code counted ────────────────────────────────────────────

def test_blank_product_code_counted(tmp_path):
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK"), ("B1", "", "WAREHOUSE_STOCK"),
                       ("B1", "  ", "PURCHASE_TRANSIT")],  # whitespace counts as blank
             pak_rows=[("B1", "PC1", 3)],
             master_codes=["PC1"])
    b = _batch(r, "B1")
    assert b["total_inventory_pieces"] == 3
    assert b["blank_product_code_pieces"] == 2


# ── 3 + 4. under / over scan ─────────────────────────────────────────────────

def test_under_scan_detected(tmp_path):
    # packing billed 10, only 4 pieces scanned → under_scan 6
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK")] * 4,
             pak_rows=[("B1", "PC1", 10)],
             master_codes=["PC1"])
    b = _batch(r, "B1")
    assert b["packing_quantity"] == 10
    assert b["inventory_quantity"] == 4
    assert b["under_scan"] == 6
    assert b["over_scan"] == 0


def test_over_scan_detected(tmp_path):
    # packing billed 2, but 5 pieces in stock → over_scan 3
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK")] * 5,
             pak_rows=[("B1", "PC1", 2)],
             master_codes=["PC1"])
    b = _batch(r, "B1")
    assert b["over_scan"] == 3
    assert b["under_scan"] == 0


# ── 5. Product Master coverage ───────────────────────────────────────────────

def test_product_master_coverage_calculated(tmp_path):
    # inventory codes PC1, PC2, PC3; master has PC1, PC2 → coverage 2, missing 1
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK"), ("B1", "PC2", "WAREHOUSE_STOCK"),
                       ("B1", "PC3", "WAREHOUSE_STOCK")],
             pak_rows=[("B1", "PC1", 1), ("B1", "PC2", 1), ("B1", "PC3", 1)],
             master_codes=["PC1", "PC2"])
    b = _batch(r, "B1")
    assert b["product_master_coverage_count"] == 2
    assert b["product_master_missing_count"] == 1


# ── 6. health status computed ────────────────────────────────────────────────

def test_health_healthy_when_clean(tmp_path):
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK")] * 3,
             pak_rows=[("B1", "PC1", 3)],
             master_codes=["PC1"])
    assert _batch(r, "B1")["health_status"] == "healthy"


def test_health_warning_on_under_scan(tmp_path):
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK")] * 2,
             pak_rows=[("B1", "PC1", 5)],
             master_codes=["PC1"])
    assert _batch(r, "B1")["health_status"] == "warning"


def test_health_critical_on_over_scan_or_blank(tmp_path):
    over = _run(tmp_path, inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK")] * 4,
                pak_rows=[("B1", "PC1", 1)], master_codes=["PC1"])
    assert _batch(over, "B1")["health_status"] == "critical"
    blank = _run(tmp_path, inv_rows=[("B2", "", "WAREHOUSE_STOCK"), ("B2", "PC1", "WAREHOUSE_STOCK")],
                 pak_rows=[("B2", "PC1", 2)], master_codes=["PC1"])
    assert _batch(blank, "B2")["health_status"] == "critical"


# ── 7. endpoint is read-only ─────────────────────────────────────────────────

def test_endpoint_read_only_and_contract(tmp_path, monkeypatch):
    wh, pk, rq = _make_dbs(
        tmp_path,
        inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK"), ("B1", "PC2", "PURCHASE_TRANSIT")],
        pak_rows=[("B1", "PC1", 1), ("B1", "PC2", 1)],
        master_codes=["PC1"])

    from app.services import warehouse_db as wdb
    from app.services import packing_db as pdb
    from app.core.config import settings
    from app.core.security import require_api_key
    from app.api.routes_inventory import router as inv_router

    monkeypatch.setattr(wdb, "_db_path", wh, raising=False)
    monkeypatch.setattr(pdb, "_db_path", pk, raising=False)
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)

    def _counts():
        out = {}
        for name, p, tbl in (("inv", wh, "inventory_state"), ("pak", pk, "packing_lines"),
                             ("pm", rq, "product_master")):
            c = sqlite3.connect(str(p))
            out[name] = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            c.close()
        return out

    before = _counts()

    app = FastAPI()
    app.include_router(inv_router)
    app.dependency_overrides[require_api_key] = lambda: None
    client = TestClient(app)

    resp = client.get("/api/v1/inventory/reconciliation")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # contract
    assert set(["generated_at", "batch_count", "totals", "batches"]).issubset(body.keys())
    assert body["batch_count"] == 1
    b = body["batches"][0]
    for k in ("batch_id", "total_inventory_pieces", "blank_product_code_pieces", "packing_quantity",
              "inventory_quantity", "under_scan", "over_scan", "product_master_coverage_count",
              "product_master_missing_count", "state_breakdown", "health_status"):
        assert k in b, f"missing metric {k}"
    # no repair suggestions in Phase 1
    assert "suggestion" not in str(body).lower() and "repair" not in str(body).lower()
    # read-only: row counts unchanged after the GET
    assert _counts() == before


# ── 8. Product Master consumed ADVISORY only (never gates) ────────────────────

def test_product_master_missing_does_not_affect_health(tmp_path):
    # Fully scanned (no under/over), no blanks, but ZERO product_master coverage.
    r = _run(tmp_path,
             inv_rows=[("B1", "PC1", "WAREHOUSE_STOCK"), ("B1", "PC2", "WAREHOUSE_STOCK")],
             pak_rows=[("B1", "PC1", 1), ("B1", "PC2", 1)],
             master_codes=[])  # empty Product Master
    b = _batch(r, "B1")
    assert b["product_master_coverage_count"] == 0
    assert b["product_master_missing_count"] == 2
    # PM coverage is advisory → still healthy, never blocked/critical on PM alone.
    assert b["health_status"] == "healthy"
    assert all("product_master" not in reason and "master" not in reason.lower()
               for reason in b["health_reasons"])

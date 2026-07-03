"""
test_c3e_c3f_inventory_batch_reads.py — Phase-C Wave 2, slices C-3e/C-3f.

  GET /api/v1/inventory/merchandising/{batch_id}  (C-3e — inventory_state
      ⋈ packing_lines, wireframe DELIVERABLE-2 columns)
  GET /api/v1/inventory/movements/{batch_id}      (C-3f — engine lifecycle
      event trail + document-trail pointers)

Pins:
  1. merchandising rows carry the wireframe columns (pack_sr, ctg, karat,
     color, quality, dia_wt, qty) joined with the live per-piece state
  2. client_po is best-effort advisory ('' when the sales side is silent)
  3. honest empty for unknown batch (200, rows=[]/events=[])
  4. movements returns the engine's append-only trail newest-first with
     document-trail pointers
  5. both endpoints are read-only (no state mutation across a GET)
  6. both routes registered on the production app

Lesson A: no stubs — real packing_db + engine seeding (BE-1 fixture idiom).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.security import require_api_key
from app.api.routes_inventory import router as _inv_router
from app.api.routes_packing import seed_purchase_transit
from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise

_BATCH = "BATCH_C3EF"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    app = FastAPI()
    app.include_router(_inv_router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def _line(n: int) -> dict:
    return {
        "batch_id":              _BATCH,
        "product_code":          f"EJL/26-27/400-{n}",
        "design_no":             f"D-{n:03}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/400",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            4.5,
        "item_type":             "RING",
        "karat":                 "14KT",
        "metal":                 "gold",
    }


def _seed(n_lines: int = 2):
    lines = [_line(i) for i in range(1, n_lines + 1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(_BATCH, lines)
    return lines


# ── C-3e ─────────────────────────────────────────────────────────────────────

def test_merchandising_rows_join_state(client):
    lines = _seed(2)
    sc0 = lines[0].get("scan_code") or pdb._compute_scan_code(lines[0])
    ise.transition(scan_code=sc0, to_state=ise.WAREHOUSE_STOCK,
                   trigger="pz_created", operator="test")

    body = client.get(f"/api/v1/inventory/merchandising/{_BATCH}").json()
    assert body["ok"] is True and body["count"] == 2
    by_scan = {r["scan_code"]: r for r in body["rows"]}
    assert by_scan[sc0]["state"] == ise.WAREHOUSE_STOCK
    other = next(r for r in body["rows"] if r["scan_code"] != sc0)
    assert other["state"] == ise.PURCHASE_TRANSIT
    row = by_scan[sc0]
    for col in ("pack_sr", "ctg", "client_po", "karat", "color", "quality",
                "dia_wt", "qty", "uom", "design_no", "product_code"):
        assert col in row, f"wireframe column {col} missing"
    assert row["ctg"] == "RING" and row["karat"] == "14KT"
    assert row["client_po"] == ""  # no sales side seeded → advisory empty


def test_merchandising_unknown_batch_honest_empty(client):
    body = client.get("/api/v1/inventory/merchandising/NOPE").json()
    assert body == {"ok": True, "batch_id": "NOPE", "count": 0, "rows": []}


# ── C-3f ─────────────────────────────────────────────────────────────────────

def test_movements_trail_newest_first_with_document_pointers(client):
    lines = _seed(1)
    sc = lines[0].get("scan_code") or pdb._compute_scan_code(lines[0])
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK,
                   trigger="pz_created", operator="test")

    body = client.get(f"/api/v1/inventory/movements/{_BATCH}").json()
    assert body["ok"] is True
    assert body["count"] >= 2  # seed event + promotion event
    events = body["events"]
    occurred = [e["occurred_at"] for e in events]
    assert occurred == sorted(occurred, reverse=True), "newest first"
    assert events[0]["scan_code"] == sc
    trails = body["document_trails"]
    assert trails["promotion_notes"] == 0
    assert trails["samples_endpoint"] == "/api/v1/inventory/samples"
    assert trails["returns_endpoint"] == "/api/v1/inventory/returns"


def test_movements_unknown_batch_honest_empty(client):
    body = client.get("/api/v1/inventory/movements/NOPE").json()
    assert body["ok"] is True and body["count"] == 0 and body["events"] == []


# ── read-only guarantee ──────────────────────────────────────────────────────

def test_batch_reads_do_not_mutate_state(client):
    lines = _seed(1)
    sc = lines[0].get("scan_code") or pdb._compute_scan_code(lines[0])
    before = ise.get_state(sc)
    client.get(f"/api/v1/inventory/merchandising/{_BATCH}")
    client.get(f"/api/v1/inventory/movements/{_BATCH}")
    after = ise.get_state(sc)
    assert before == after


# ── production registration ──────────────────────────────────────────────────

def test_batch_read_routes_registered_on_main_app():
    from app.main import app as prod_app
    paths = {r.path for r in prod_app.routes}
    assert "/api/v1/inventory/merchandising/{batch_id}" in paths
    assert "/api/v1/inventory/movements/{batch_id}" in paths

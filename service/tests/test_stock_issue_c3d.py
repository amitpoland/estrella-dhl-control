"""
test_stock_issue_c3d.py — Phase-C Wave 2 slice C-3d: shared
WAREHOUSE_STOCK → SALES_TRANSIT stock-issue authority.

Pins run_stock_issue() (services/stock_issue.py) — the ONE shared function
that fires the previously-unreachable ``invoice_issued`` engine trigger
(audit §Q3 / wireframe §B gap #2):

  - billed-quantity piece selection (deterministic scan_code order)
  - idempotent replay (already-SALES_TRANSIT pieces count toward the
    billed qty; nothing extra is drained; never demotes)
  - shortfall reporting (billed > available is an advisory counter,
    never an exception — Lesson N: custody state is advisory to fiscal)
  - never-raise contract (engine failure → errors counter)
  - audit summary mirror (EV_INVENTORY_SALES_TRANSIT_ISSUED)
  - source-grep: the convert route fires the shared function with
    trigger="invoice_issued" (no Logic A / Logic B)

Lesson A: no stubs — real packing_db + warehouse_db + real engine seeding,
same fixture pattern as test_stock_promotion_be1.py.
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.services.stock_issue import run_stock_issue
from app.api.routes_packing import seed_purchase_transit

_APP = Path(__file__).resolve().parent.parent / "app"

_BATCH = "BATCH_C3D"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    batch_dir = tmp_path / "outputs" / _BATCH
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "audit.json").write_text(
        _json.dumps({"batch_id": _BATCH, "timeline": []}), encoding="utf-8")
    return tmp_path


def _line(n: int, code: str) -> dict:
    return {
        "batch_id":              _BATCH,
        "product_code":          code,
        "design_no":             f"D-{n:03}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/300",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


def _seed_warehouse_stock(lines):
    """Seed pieces to PURCHASE_TRANSIT then promote to WAREHOUSE_STOCK —
    the real lifecycle path, no state stubbing."""
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(_BATCH, lines)
    for line in lines:
        sc = line.get("scan_code") or pdb._compute_scan_code(line)
        ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK,
                       trigger="pz_created", operator="test")


def _states():
    return {
        sc: (ise.get_state(sc) or {}).get("state")
        for sc in [
            r.get("scan_code") or pdb._compute_scan_code(r)
            for r in pdb.get_packing_lines_for_batch(_BATCH)
        ]
    }


# ── 1. happy path ────────────────────────────────────────────────────────────

def test_issues_billed_pieces_with_trigger(db):
    lines = [_line(i, "EJL/26-27/300-1") for i in (1, 2, 3)]
    _seed_warehouse_stock(lines)

    res = run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/26-27/300-1", "qty": 2}],
        client_name="ACME", operator="alice",
    )
    assert res["issued"] == 2
    assert res["shortfall"] == 0
    assert res["errors"] == 0
    states = list(_states().values())
    assert states.count(ise.SALES_TRANSIT) == 2
    assert states.count(ise.WAREHOUSE_STOCK) == 1


def test_deterministic_scan_code_order(db):
    lines = [_line(i, "EJL/26-27/300-1") for i in (1, 2)]
    _seed_warehouse_stock(lines)
    run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/26-27/300-1", "qty": 1}],
    )
    st = _states()
    issued = sorted(sc for sc, s in st.items() if s == ise.SALES_TRANSIT)
    remaining = sorted(sc for sc, s in st.items() if s == ise.WAREHOUSE_STOCK)
    assert len(issued) == 1 and len(remaining) == 1
    assert issued[0] < remaining[0], "lowest scan_code must be issued first"


# ── 2. idempotent replay ─────────────────────────────────────────────────────

def test_replay_is_idempotent_and_never_drains_extra(db):
    lines = [_line(i, "EJL/26-27/300-1") for i in (1, 2, 3)]
    _seed_warehouse_stock(lines)
    billed = [{"product_code": "EJL/26-27/300-1", "qty": 2}]

    first = run_stock_issue(_BATCH, trigger="invoice_issued",
                            source="proforma_convert", lines=billed)
    assert first["issued"] == 2
    second = run_stock_issue(_BATCH, trigger="invoice_issued",
                             source="proforma_convert", lines=billed)
    assert second["issued"] == 0, "replay must not issue more pieces"
    assert second["shortfall"] == 0, (
        "already-SALES_TRANSIT pieces satisfy the billed qty on replay"
    )
    assert list(_states().values()).count(ise.SALES_TRANSIT) == 2


# ── 3. shortfall is advisory ─────────────────────────────────────────────────

def test_shortfall_reported_never_raises(db):
    lines = [_line(1, "EJL/26-27/300-1")]
    _seed_warehouse_stock(lines)
    res = run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/26-27/300-1", "qty": 5}],
    )
    assert res["issued"] == 1
    assert res["shortfall"] == 4


def test_unknown_product_code_is_pure_shortfall(db):
    res = run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/NOPE-1", "qty": 2}],
    )
    assert res["issued"] == 0
    assert res["shortfall"] == 2
    assert res["errors"] == 0


# ── 4. state discipline ──────────────────────────────────────────────────────

def test_purchase_transit_pieces_never_issued(db):
    lines = [_line(1, "EJL/26-27/300-1")]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(_BATCH, lines)  # NOT promoted to WAREHOUSE_STOCK
    res = run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/26-27/300-1", "qty": 1}],
    )
    assert res["issued"] == 0
    assert res["shortfall"] == 1
    assert list(_states().values()) == [ise.PURCHASE_TRANSIT]


def test_no_lines_is_a_noop(db):
    res = run_stock_issue(_BATCH, trigger="invoice_issued",
                          source="proforma_convert", lines=[])
    assert res == {"batch_id": _BATCH, "trigger": "invoice_issued",
                   "source": "proforma_convert", "issued": 0,
                   "skipped": 0, "shortfall": 0, "errors": 0}


# ── 5. never-raise contract ──────────────────────────────────────────────────

def test_engine_failure_counted_never_raised(db):
    lines = [_line(1, "EJL/26-27/300-1")]
    _seed_warehouse_stock(lines)
    with patch.object(ise, "transition",
                      side_effect=RuntimeError("engine down")):
        res = run_stock_issue(
            _BATCH, trigger="invoice_issued", source="proforma_convert",
            lines=[{"product_code": "EJL/26-27/300-1", "qty": 1}],
        )
    assert res["errors"] == 1
    assert res["issued"] == 0


# ── 6. audit summary mirror ──────────────────────────────────────────────────

def test_summary_mirror_written(db, tmp_path):
    lines = [_line(1, "EJL/26-27/300-1")]
    _seed_warehouse_stock(lines)
    run_stock_issue(
        _BATCH, trigger="invoice_issued", source="proforma_convert",
        lines=[{"product_code": "EJL/26-27/300-1", "qty": 1}],
        client_name="ACME",
    )
    audit = _json.loads(
        (tmp_path / "outputs" / _BATCH / "audit.json").read_text())
    events = [e for e in audit.get("timeline", [])
              if e.get("event") == "inventory_sales_transit_issued"]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["issued"] == 1 and detail["client_name"] == "ACME"
    assert "pieces" in detail
    # No financial fields in the mirror payload
    flat = _json.dumps(detail).lower()
    for forbidden in ("price", "total", "netto", "brutto", "vat"):
        assert forbidden not in flat


# ── 7. wiring: the convert route fires the shared function ───────────────────

def test_convert_route_calls_shared_run_stock_issue():
    src = (_APP / "api" / "routes_proforma.py").read_text(encoding="utf-8")
    assert "from ..services.stock_issue import run_stock_issue" in src, (
        "proforma_to_invoice must call the ONE shared run_stock_issue() "
        "(Business Feature Completeness: no Logic A / Logic B)"
    )
    assert 'trigger     = "invoice_issued"' in src
    assert 'source      = "proforma_convert"' in src


def test_engine_trigger_reachable():
    """The (WAREHOUSE_STOCK → SALES_TRANSIT) trigger is now reachable: the
    shared function passes trigger='invoice_issued' as the engine's
    default-trigger table expects."""
    assert ise.DEFAULT_TRIGGER[(ise.WAREHOUSE_STOCK, ise.SALES_TRANSIT)] == \
        "invoice_issued"

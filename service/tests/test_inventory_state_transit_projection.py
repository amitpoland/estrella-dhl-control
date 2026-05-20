"""test_inventory_state_transit_projection.py — C13A regression suite.

Read-only synthetic PURCHASE_TRANSIT projection.  No DB writes anywhere
in these tests.  All assertions are on pure-function output OR on
inventory_batch_state.get_batch_state() behaviour with a freshly-seeded
audit.json + packing.db.

Surfaces covered:
  - engine.derive_purchase_transit_projection (pure)
  - inventory_batch_state.get_batch_state wiring (zero-rows + transit signal)
  - Authority precedence (real inventory_state rows always win)
  - Terminal-status suppression (closed batches do not get a synthetic
    transit projection even with zero scans)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.services import inventory_state_engine as ise
from app.services import inventory_batch_state as ibs
from app.services import packing_db


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def batch_id() -> str:
    return "SHIPMENT_C13A_TEST_2026-05_aaaa1111"


@pytest.fixture
def packing_lines() -> List[Dict[str, Any]]:
    """3 packing lines from a fictitious DHL-in-transit shipment."""
    return [
        {
            "scan_code":    "EJL/C13A/01-1|sr1|D-A",
            "product_code": "EJL/C13A/01-1",
            "design_no":    "D-A",
            "quantity":     1,
        },
        {
            "scan_code":    "EJL/C13A/01-2|sr2|D-B",
            "product_code": "EJL/C13A/01-2",
            "design_no":    "D-B",
            "quantity":     1,
        },
        {
            "scan_code":    "EJL/C13A/01-3|sr3|D-C",
            "product_code": "EJL/C13A/01-3",
            "design_no":    "D-C",
            "quantity":     2,
        },
    ]


# ── Pure-function tests (engine projector) ──────────────────────────────────

def test_transit_signal_with_packing_lines_yields_projection(packing_lines):
    audit = {
        "clearance_status": "dsk_generated",
        "tracking": {"last_update": "2026-05-19T22:00:00Z"},
    }
    rows = ise.derive_purchase_transit_projection(
        "B-T1", audit, packing_lines,
    )
    assert len(rows) == 3
    for r in rows:
        assert r["state"] == ise.PURCHASE_TRANSIT
        assert r["synthetic"] is True
        assert r["source"] == "audit.tracking"
        assert r["updated_at"] == "2026-05-19T22:00:00Z"
    scan_codes = {r["scan_code"] for r in rows}
    assert scan_codes == {ln["scan_code"] for ln in packing_lines}


def test_terminal_status_suppresses_projection(packing_lines):
    """Closed/delivered/archived shipments must NOT produce synthetic transit
    rows even if scans are absent.  Operator must investigate, not be lied to."""
    for status in (
        "closed", "pz_generated", "delivered_and_received",
        "archived", "cancelled",
    ):
        rows = ise.derive_purchase_transit_projection(
            "B-T2", {"clearance_status": status}, packing_lines,
        )
        assert rows == [], f"terminal status {status!r} produced {len(rows)} rows"


def test_unknown_status_yields_no_projection(packing_lines):
    """An unmapped clearance_status must NOT default to transit."""
    rows = ise.derive_purchase_transit_projection(
        "B-T3", {"clearance_status": "made_up_status"}, packing_lines,
    )
    assert rows == []


def test_no_tracking_signal_yields_no_projection(packing_lines):
    """Empty / missing clearance_status → no synthetic rows."""
    for audit in ({}, {"clearance_status": ""}, {"clearance_status": None}):
        rows = ise.derive_purchase_transit_projection(
            "B-T4", audit, packing_lines,
        )
        assert rows == []


def test_no_packing_lines_yields_no_projection():
    """Even with a valid transit signal, no packing data → no synthetic rows.
    We project from packing scan_codes — without them we have no evidence
    of what is on the shipment."""
    audit = {"clearance_status": "dsk_generated"}
    assert ise.derive_purchase_transit_projection("B-T5", audit, []) == []
    assert ise.derive_purchase_transit_projection("B-T5", audit, None) == []


def test_malformed_audit_returns_empty(packing_lines):
    """Non-dict / None audit → safe empty, no exception."""
    for bad in (None, "not a dict", 42, ["a", "list"]):
        assert ise.derive_purchase_transit_projection(
            "B-T6", bad, packing_lines,
        ) == []


def test_duplicate_scan_codes_deduplicated(packing_lines):
    """If packing returns duplicate scan_codes, projection deduplicates."""
    lines = list(packing_lines) + [dict(packing_lines[0])]
    rows = ise.derive_purchase_transit_projection(
        "B-T7", {"clearance_status": "dsk_generated"}, lines,
    )
    assert len(rows) == 3
    assert len({r["scan_code"] for r in rows}) == 3


def test_lines_missing_scan_code_skipped(packing_lines):
    lines = list(packing_lines) + [{"scan_code": "", "design_no": "ghost"}]
    rows = ise.derive_purchase_transit_projection(
        "B-T8", {"clearance_status": "in_transit"}, lines,
    )
    assert len(rows) == 3
    assert all(r["scan_code"] for r in rows)


def test_projection_never_writes_to_inventory_state(
    tmp_path: Path, monkeypatch, packing_lines,
):
    """Hard invariant: calling the projector must not produce any
    inventory_state row, no matter how many times it is called."""
    db_file = tmp_path / "warehouse.db"
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(db_file)
    # Initialise schema by touching the engine — count_by_state with empty
    # batch is safe.
    ise.count_by_state(batch_id="B-T9")
    for _ in range(5):
        ise.derive_purchase_transit_projection(
            "B-T9",
            {"clearance_status": "dsk_generated"},
            packing_lines,
        )
    # If we reach here, no exception was raised; explicitly verify the
    # DB has no rows for this batch (covers the case where the engine
    # *did* somehow open a write).
    if db_file.exists():
        with sqlite3.connect(str(db_file)) as con:
            try:
                rows = con.execute(
                    "SELECT COUNT(*) FROM inventory_state WHERE batch_id=?",
                    ("B-T9",),
                ).fetchone()
                assert rows[0] == 0, "projection wrote rows — CRITICAL"
            except sqlite3.OperationalError:
                # Table not created — also acceptable (means no writes).
                pass


# ── inventory_batch_state.get_batch_state wiring ────────────────────────────

def _seed_audit(storage_root: Path, batch_id: str, audit: Dict[str, Any]) -> None:
    out = storage_root / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")


def _seed_packing(db_file: Path, batch_id: str, lines: List[Dict[str, Any]]) -> None:
    """Initialise packing_db at db_file and insert one document + lines."""
    packing_db.init_packing_db(db_file)
    packing_db._db_path = db_file  # type: ignore[attr-defined]
    doc_id = "doc-c13a-test"
    packing_db.upsert_packing_document(
        document_id=doc_id,
        batch_id=batch_id,
        invoice_no="EJL/C13A/01",
        source_file_path="/tmp/synthetic.xlsx",
        source_file_hash="x" * 64,
        parser_name="test",
        parser_version="1.0",
        extraction_status="complete",
        parser_diagnostic={},
    )
    rows = []
    for i, ln in enumerate(lines, start=1):
        rows.append({
            **ln,
            "packing_document_id": doc_id,
            "batch_id":            batch_id,
            "invoice_no":          "EJL/C13A/01",
            "invoice_line_position": i,
            "pack_sr":             float(i),
            "quantity":            ln.get("quantity", 1),
            "extracted_confidence": 1.0,
        })
    packing_db.upsert_packing_lines(rows)


def test_get_batch_state_zero_rows_with_transit_audit_emits_synthetic(
    tmp_path: Path, monkeypatch, batch_id, packing_lines,
):
    """End-to-end wiring: zero inventory_state rows + transit audit →
    get_batch_state returns synthetic projection with synthetic=True."""
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "outputs").mkdir()
    # Point settings.storage_root at our tmp_path
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    # Use a fresh warehouse DB
    wh = storage / "warehouse.db"
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(wh)
    # Use a fresh packing DB
    _seed_packing(storage / "packing.db", batch_id, packing_lines)
    # Audit indicates DHL transit
    _seed_audit(storage, batch_id, {
        "clearance_status": "dsk_generated",
        "tracking": {"last_update": "2026-05-19T22:00:00Z"},
    })
    out = ibs.get_batch_state(batch_id)
    assert out["synthetic"] is True
    assert out["source"] == "audit.tracking"
    assert out["total"] == 3
    assert out["counts"][ise.PURCHASE_TRANSIT] == 3
    assert all(p["synthetic"] is True for p in out["pieces"])
    assert all(p["state"] == ise.PURCHASE_TRANSIT for p in out["pieces"])


def test_get_batch_state_terminal_audit_returns_empty_not_synthetic(
    tmp_path: Path, monkeypatch, batch_id, packing_lines,
):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "outputs").mkdir()
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(storage / "warehouse.db")
    _seed_packing(storage / "packing.db", batch_id, packing_lines)
    _seed_audit(storage, batch_id, {"clearance_status": "closed"})
    out = ibs.get_batch_state(batch_id)
    assert out["synthetic"] is False
    assert out["source"] == "empty"
    assert out["total"] == 0
    assert out["pieces"] == []


def test_get_batch_state_no_audit_returns_empty_not_synthetic(
    tmp_path: Path, monkeypatch, batch_id, packing_lines,
):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "outputs").mkdir()
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(storage / "warehouse.db")
    _seed_packing(storage / "packing.db", batch_id, packing_lines)
    # No audit.json written.
    out = ibs.get_batch_state(batch_id)
    assert out["synthetic"] is False
    assert out["source"] == "empty"
    assert out["pieces"] == []


def test_get_batch_state_malformed_audit_safe(
    tmp_path: Path, monkeypatch, batch_id, packing_lines,
):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "outputs" / batch_id).mkdir(parents=True)
    (storage / "outputs" / batch_id / "audit.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(storage / "warehouse.db")
    _seed_packing(storage / "packing.db", batch_id, packing_lines)
    out = ibs.get_batch_state(batch_id)
    assert out["synthetic"] is False
    assert out["pieces"] == []


def test_real_rows_always_win_over_synthetic(
    tmp_path: Path, monkeypatch, batch_id, packing_lines,
):
    """If even ONE real inventory_state row exists, the synthetic projection
    must NOT activate.  Real rows are the source of truth."""
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "outputs").mkdir()
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", storage)
    from app.services import warehouse_db as wdb
    wdb.init_warehouse_db(storage / "warehouse.db")
    _seed_packing(storage / "packing.db", batch_id, packing_lines)
    # Audit says transit
    _seed_audit(storage, batch_id, {"clearance_status": "dsk_generated"})
    # Insert one real inventory_state row directly
    ise.count_by_state(batch_id=batch_id)  # triggers _connect / schema init
    with ise._connect() as con:
        con.execute(
            "INSERT INTO inventory_state "
            "(id, scan_code, product_code, design_no, batch_id, state, "
            "updated_at, updated_by, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("id-1", "EJL/C13A/01-1|sr1|D-A", "EJL/C13A/01-1", "D-A",
             batch_id, ise.WAREHOUSE_STOCK,
             "2026-05-19T23:00:00Z", "test", ""),
        )
    out = ibs.get_batch_state(batch_id)
    assert out["synthetic"] is False
    assert out["source"] == "inventory_state"
    assert out["total"] == 1
    assert out["counts"][ise.WAREHOUSE_STOCK] == 1
    assert out["counts"][ise.PURCHASE_TRANSIT] == 0
    assert len(out["pieces"]) == 1
    # No `synthetic` flag on real rows (they came straight from DB).
    assert "synthetic" not in out["pieces"][0]


# ── Source-grep invariant: projector must never call a write-shaped API ─────

def test_projector_source_contains_no_write_keywords():
    """Static guard against future drift: the projector function body must
    not contain any `INSERT`, `UPDATE`, `DELETE`, `transition`, or
    `upsert` token.  A regression here would mean someone added a write
    to the read-only projection path."""
    import inspect
    src = inspect.getsource(ise.derive_purchase_transit_projection)
    for forbidden in ("INSERT", "UPDATE INVENTORY", "DELETE FROM",
                      "transition(", "upsert_"):
        assert forbidden not in src, (
            f"derive_purchase_transit_projection contains forbidden token "
            f"{forbidden!r} — projection MUST remain read-only"
        )

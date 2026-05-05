"""
test_warehouse_audit.py — Audit layer: gap detection between packing_lines and scans.

Covers:
  1. Missing scans    — packing line exists, never scanned
  2. Stuck inventory  — RECEIVE only, threshold exceeded
  3. Invalid flows    — DISPATCH without RECEIVE; MOVE without RECEIVE
  4. Orphan inventory — warehouse record with no packing line
  5. Summary math     — total / scanned / dispatched / missing / pct
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import warehouse_db as wdb
from app.services import warehouse_audit as waudit


BATCH = "AUDIT_TEST_BATCH_001"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("wh_audit_storage")


@pytest.fixture(scope="module")
def db(tmp_storage):
    pdb.init_packing_db(tmp_storage / "packing.db")
    ddb.init_document_db(tmp_storage / "documents.db")
    wdb.init_warehouse_db(tmp_storage / "warehouse.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, db):
    with patch.object(settings, "storage_root", tmp_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _line(n: int, **kwargs) -> dict:
    base = {
        "packing_document_id":   f"audit-doc-{n}",
        "batch_id":              BATCH,
        "invoice_no":            f"EJL/26-27/AUDIT",
        "invoice_line_position": n,
        "product_code":          f"EJL/AUDIT-{n:03}",
        "design_no":             f"AUDIT-DESIGN-{n:03}",
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
        "metal":                 "18KT",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  0.95,
        "requires_manual_review": False,
        "pack_sr":               float(n),
        "unit_price":            100.0,
        "total_value":           100.0,
        "batch_no":              "",
    }
    base.update(kwargs)
    return base


# ── Seed data ──────────────────────────────────────────────────────────────────
# line 1 → RECEIVE + DISPATCH  (scanned, dispatched)
# line 2 → RECEIVE only        (scanned, stuck at RECV if threshold=0)
# line 3 → never scanned       (missing)
# line 4 → DISPATCH without RECEIVE (invalid flow, seeded directly)
# line 5 → MOVE without RECEIVE     (invalid flow, seeded directly)
# orphan  → in warehouse but no packing line

@pytest.fixture(scope="module")
def seeded(db, client):
    lines = [_line(i) for i in range(1, 6)]
    pdb.upsert_packing_lines(lines)

    sc = {i: wdb.scan_code_for_packing_line(_line(i)) for i in range(1, 6)}

    # line 1: RECEIVE then DISPATCH
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[1], "action": "RECEIVE", "to_location": "MAIN/RECV-01"},
                headers=_auth())
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[1], "action": "DISPATCH", "to_location": "DHL-OUT"},
                headers=_auth())

    # line 2: RECEIVE only (will be stuck) — backdated so threshold tests are deterministic
    client.post("/api/v1/warehouse/scan",
                json={"scan_code": sc[2], "action": "RECEIVE", "to_location": "MAIN/RECV-01"},
                headers=_auth())
    past = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(str(wdb._db_path)) as con:
        con.execute("UPDATE inventory_current_location SET updated_at=? WHERE scan_code=?",
                    (past, sc[2]))

    # line 3: no scan at all

    # lines 4 & 5: invalid flows — insert events directly
    now = "2026-01-01T10:00:00+00:00"
    with sqlite3.connect(str(wdb._db_path)) as con:
        # line 4: DISPATCH without RECEIVE — create ICL row + event
        icl4 = str(uuid.uuid4())
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (icl4, BATCH, f"EJL/AUDIT-004", "AUDIT-DESIGN-004", "", 4.0,
             sc[4], "DHL-OUT", "dispatched", now, "test"),
        )
        con.execute(
            """INSERT INTO inventory_movement_events
               (id, batch_id, scan_code, action, from_location, to_location,
                operator, event_time, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, sc[4], "DISPATCH", "", "DHL-OUT",
             "test", now, "", now),
        )

        # line 5: MOVE without RECEIVE
        icl5 = str(uuid.uuid4())
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (icl5, BATCH, f"EJL/AUDIT-005", "AUDIT-DESIGN-005", "", 5.0,
             sc[5], "MAIN/TRAY-X", "in_warehouse", now, "test"),
        )
        con.execute(
            """INSERT INTO inventory_movement_events
               (id, batch_id, scan_code, action, from_location, to_location,
                operator, event_time, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), BATCH, sc[5], "MOVE", "", "MAIN/TRAY-X",
             "test", now, "", now),
        )

        # orphan: exists in warehouse but NOT in packing_lines
        orphan_sc = f"ORPHAN/SCAN/CODE|sr99|GHOST"
        icl_orphan = str(uuid.uuid4())
        con.execute(
            """INSERT INTO inventory_current_location
               (id, batch_id, product_code, design_no, bag_id, pack_sr,
                scan_code, current_location, current_status, updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (icl_orphan, BATCH, "ORPHAN/PRODUCT", "GHOST-DESIGN", "", 99.0,
             orphan_sc, "MAIN/SHELF-Z", "in_warehouse", now, "test"),
        )

    return {"sc": sc, "orphan_sc": orphan_sc}


# ── 1. Missing scans ──────────────────────────────────────────────────────────

class TestMissingScans:
    def test_unscanned_line_is_missing(self, db, seeded):
        sc3 = seeded["sc"][3]
        missing = waudit.get_missing_scans(BATCH)
        scan_codes = [m["_expected_scan_code"] for m in missing]
        assert sc3 in scan_codes, f"{sc3} should be missing; got {scan_codes}"

    def test_scanned_lines_not_in_missing(self, db, seeded):
        missing = waudit.get_missing_scans(BATCH)
        missing_codes = {m["_expected_scan_code"] for m in missing}
        assert seeded["sc"][1] not in missing_codes
        assert seeded["sc"][2] not in missing_codes

    def test_missing_scans_via_api(self, client, seeded):
        r = client.get(f"/api/v1/warehouse/audit/{BATCH}", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        missing_codes = [m["_expected_scan_code"] for m in body["missing_scans"]]
        assert seeded["sc"][3] in missing_codes


# ── 2. Stuck inventory ────────────────────────────────────────────────────────

class TestStuckInventory:
    def test_recv_only_item_appears_with_threshold(self, db, seeded):
        # sc[2] was backdated to 2026-01-01 — any threshold > 0 catches it
        stuck = waudit.get_stuck_inventory(BATCH, threshold_hours=1)
        codes = [s["scan_code"] for s in stuck]
        assert seeded["sc"][2] in codes, f"sc[2] should be stuck; got {codes}"

    def test_dispatched_item_not_stuck(self, db, seeded):
        stuck = waudit.get_stuck_inventory(BATCH, threshold_hours=0)
        codes = {s["scan_code"] for s in stuck}
        assert seeded["sc"][1] not in codes

    def test_stuck_threshold_includes_old_items(self, db, seeded):
        # sc[2] was backdated to 2026-01-01 — appears with any threshold, including 1000h
        stuck = waudit.get_stuck_inventory(BATCH, threshold_hours=1000)
        codes = [s["scan_code"] for s in stuck]
        assert seeded["sc"][2] in codes

    def test_stuck_threshold_excludes_item_not_at_recv(self, db, seeded):
        # sc[1] was dispatched — never appears in stuck regardless of threshold
        stuck = waudit.get_stuck_inventory(BATCH, threshold_hours=0)
        codes = {s["scan_code"] for s in stuck}
        assert seeded["sc"][1] not in codes  # dispatched, not at RECV


# ── 3. Invalid flows ──────────────────────────────────────────────────────────

class TestInvalidFlows:
    def test_dispatch_without_receive_detected(self, db, seeded):
        invalid = waudit.get_invalid_flows(BATCH)
        violations = {v["scan_code"]: v["violation"] for v in invalid}
        assert seeded["sc"][4] in violations
        assert violations[seeded["sc"][4]] == "DISPATCH_WITHOUT_RECEIVE"

    def test_move_without_receive_detected(self, db, seeded):
        invalid = waudit.get_invalid_flows(BATCH)
        violations = {v["scan_code"]: v["violation"] for v in invalid}
        assert seeded["sc"][5] in violations
        assert violations[seeded["sc"][5]] == "MOVE_WITHOUT_RECEIVE"

    def test_valid_sequence_not_flagged(self, db, seeded):
        invalid = waudit.get_invalid_flows(BATCH)
        bad_codes = {v["scan_code"] for v in invalid}
        # sc[1] has RECEIVE → DISPATCH — this is a valid flow
        assert seeded["sc"][1] not in bad_codes

    def test_invalid_flow_has_required_fields(self, db, seeded):
        invalid = waudit.get_invalid_flows(BATCH)
        for v in invalid:
            assert "scan_code"        in v
            assert "violation"        in v
            assert "actions_observed" in v
            assert "first_event_time" in v

    def test_invalid_flows_via_api(self, client, seeded):
        r = client.get(f"/api/v1/warehouse/audit/{BATCH}", headers=_auth())
        assert r.status_code == 200
        violations = {v["scan_code"]: v["violation"] for v in r.json()["invalid_flows"]}
        assert violations.get(seeded["sc"][4]) == "DISPATCH_WITHOUT_RECEIVE"
        assert violations.get(seeded["sc"][5]) == "MOVE_WITHOUT_RECEIVE"


# ── 4. Orphan inventory ───────────────────────────────────────────────────────

class TestOrphanInventory:
    def test_orphan_detected(self, db, seeded):
        orphans = waudit.get_orphan_inventory(BATCH)
        orphan_codes = [o["scan_code"] for o in orphans]
        assert seeded["orphan_sc"] in orphan_codes

    def test_valid_items_not_orphaned(self, db, seeded):
        orphans = waudit.get_orphan_inventory(BATCH)
        orphan_codes = {o["scan_code"] for o in orphans}
        assert seeded["sc"][1] not in orphan_codes
        assert seeded["sc"][2] not in orphan_codes

    def test_orphans_via_api(self, client, seeded):
        r = client.get(f"/api/v1/warehouse/audit/{BATCH}", headers=_auth())
        assert r.status_code == 200
        orphan_codes = [o["scan_code"] for o in r.json()["orphan_inventory"]]
        assert seeded["orphan_sc"] in orphan_codes


# ── 5. Summary / completion math ─────────────────────────────────────────────

class TestBatchCompletion:
    def test_summary_fields_present(self, db, seeded):
        s = waudit.get_batch_completion(BATCH)
        for field in ("batch_id", "total_items", "scanned_items",
                      "dispatched_items", "missing_items", "completion_pct"):
            assert field in s, f"summary missing field: {field}"

    def test_total_equals_packing_lines(self, db, seeded):
        s = waudit.get_batch_completion(BATCH)
        assert s["total_items"] == 5  # lines 1–5

    def test_dispatched_count_correct(self, db, seeded):
        s = waudit.get_batch_completion(BATCH)
        # line 1 dispatched via API; line 4 dispatched directly
        assert s["dispatched_items"] >= 2

    def test_missing_equals_total_minus_scanned(self, db, seeded):
        s = waudit.get_batch_completion(BATCH)
        assert s["missing_items"] == s["total_items"] - s["scanned_items"]

    def test_completion_pct_in_range(self, db, seeded):
        s = waudit.get_batch_completion(BATCH)
        assert 0.0 <= s["completion_pct"] <= 100.0

    def test_summary_endpoint(self, client, seeded):
        r = client.get(f"/api/v1/warehouse/audit-summary/{BATCH}", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["total_items"] == 5
        assert body["missing_items"] == body["total_items"] - body["scanned_items"]

    def test_full_audit_response_shape(self, client, seeded):
        r = client.get(f"/api/v1/warehouse/audit/{BATCH}", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        for key in ("batch_id", "missing_scans", "stuck_inventory",
                    "invalid_flows", "orphan_inventory", "summary"):
            assert key in body, f"response missing key: {key}"
        assert isinstance(body["missing_scans"],    list)
        assert isinstance(body["stuck_inventory"],  list)
        assert isinstance(body["invalid_flows"],    list)
        assert isinstance(body["orphan_inventory"], list)
        assert isinstance(body["summary"],          dict)

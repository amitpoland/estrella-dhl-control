"""
test_warehouse.py — Warehouse movement-tracking layer.

Covers:
  1. Receive: creates inventory_current_location row + first event.
  2. Move:    updates current location, appends second event, from_location set.
  3. History: every scan appends an event in chronological order.
  4. Unknown scan_code → 404.
  5. Movement does NOT alter packing_lines / invoice_lines / PZ.
  6. Location declaration + inventory-at-location query.
  7. Action verbs are validated; unknown verb → 400.
  8. scan_code computed from a packing line equals the barcode endpoint output.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import packing_db as pdb
from app.services import document_db as ddb
from app.services import warehouse_db as wdb


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("warehouse_storage")


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


@pytest.fixture(scope="module")
def seeded_packing_line(db):
    """Insert one packing line so we have a known scan_code to test against."""
    line = {
        "packing_document_id":   "test-doc-1",
        "batch_id":              "BATCH_WH_TEST",
        "invoice_no":             "EJL/26-27/013",
        "invoice_line_position":  2,
        "product_code":           "EJL/26-27/013-2",
        "design_no":              "CSTR07596",
        "batch_no":               "",
        "bag_id":                 "",
        "tray_id":                "",
        "item_type":              "RNG",
        "uom":                    "PCS",
        "quantity":               1.0,
        "gross_weight":           3.96,
        "net_weight":             3.96,
        "metal":                  "18KT/WPD",
        "karat":                  "",
        "stone_type":             "",
        "remarks":                "",
        "extracted_confidence":   0.95,
        "requires_manual_review": False,
        "pack_sr":                2.0,
        "unit_price":             570.0,
        "total_value":            570.0,
    }
    pdb.upsert_packing_lines([line])
    sc = wdb.scan_code_for_packing_line(line)
    return {"line": line, "scan_code": sc}


def _auth_headers() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── 1. Receive creates current location ───────────────────────────────────────

class TestReceive:
    def test_receive_creates_current_location(self, client, seeded_packing_line):
        sc = seeded_packing_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "RECEIVE",
                "to_location": "MAIN/RECV-01",
                "operator":    "amit",
                "note":        "initial intake",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["scan_code"]        == sc
        assert body["action"]           == "RECEIVE"
        assert body["current_location"] == "MAIN/RECV-01"
        assert body["current_status"]   == "received"
        assert body["event_count"]      == 1


# ── 2. Move updates location ──────────────────────────────────────────────────

class TestMove:
    def test_move_updates_location_and_records_from(self, client, seeded_packing_line):
        sc = seeded_packing_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "MOVE",
                "to_location": "MAIN/TRAY-A1",
                "operator":    "amit",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["current_location"] == "MAIN/TRAY-A1"
        assert body["current_status"]   == "in_warehouse"

        # History should now have 2 events; the second has from_location set.
        h = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth_headers()).json()
        history = h["history"]
        assert len(history) == 2
        assert history[0]["action"]        == "RECEIVE"
        assert history[0]["from_location"] == ""
        assert history[1]["action"]        == "MOVE"
        assert history[1]["from_location"] == "MAIN/RECV-01"
        assert history[1]["to_location"]   == "MAIN/TRAY-A1"


# ── 3. History append-only chronological ──────────────────────────────────────

class TestHistory:
    def test_event_history_appends_each_scan(self, client, seeded_packing_line):
        sc = seeded_packing_line["scan_code"]
        for action, loc in [("PICK","STAGING"), ("PACK","DISPATCH-Q"),
                            ("DISPATCH","DHL-OUTBOUND")]:
            r = client.post(
                "/api/v1/warehouse/scan",
                json={"scan_code": sc, "action": action, "to_location": loc, "operator": "amit"},
                headers=_auth_headers(),
            )
            assert r.status_code == 200, r.text

        h = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth_headers()).json()
        actions = [e["action"] for e in h["history"]]
        # Order: RECEIVE, MOVE, PICK, PACK, DISPATCH
        assert actions == ["RECEIVE", "MOVE", "PICK", "PACK", "DISPATCH"]

        # Final state
        assert h["current"]["current_location"] == "DHL-OUTBOUND"
        assert h["current"]["current_status"]   == "dispatched"


# ── 4. Unknown scan_code → 404 ────────────────────────────────────────────────

class TestUnknownScan:
    def test_unknown_scan_code_returns_404(self, client):
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   "NOT/A/REAL/CODE|sr999|XXXXX",
                "action":      "MOVE",
                "to_location": "MAIN/TRAY-A1",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 404
        body = r.json()
        assert "not found" in body["detail"].lower()


# ── 5. Movement does NOT alter invoice / PZ values ───────────────────────────

class TestNoAccountingMutation:
    def test_packing_line_unchanged_after_scan(self, db, seeded_packing_line, client):
        sc = seeded_packing_line["scan_code"]
        line_before = pdb.get_packing_lines_for_batch("BATCH_WH_TEST")[0]
        before_keys = {
            "quantity":     line_before["quantity"],
            "gross_weight": line_before["gross_weight"],
            "net_weight":   line_before["net_weight"],
            "unit_price":   line_before["unit_price"],
            "total_value":  line_before["total_value"],
        }

        # Hammer the scanner with multiple actions
        for action in ("RECEIVE", "MOVE", "PICK", "PACK"):
            client.post(
                "/api/v1/warehouse/scan",
                json={"scan_code": sc, "action": action, "to_location": "ANY"},
                headers=_auth_headers(),
            )

        line_after = pdb.get_packing_lines_for_batch("BATCH_WH_TEST")[0]
        for k, v in before_keys.items():
            assert line_after[k] == v, f"{k} mutated by movement: {v} → {line_after[k]}"


# ── 6. Locations + inventory-at-location ──────────────────────────────────────

class TestLocations:
    def test_create_and_list_location(self, client):
        r = client.post(
            "/api/v1/warehouse/locations",
            json={
                "location_code": "MAIN/TRAY-B7",
                "location_type": "tray",
                "warehouse":     "MAIN",
                "row_no":        "B",
                "tray_id":       "B7",
                "description":   "Diamond ring tray",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/v1/warehouse/locations", headers=_auth_headers())
        codes = {l["location_code"] for l in r2.json()["locations"]}
        assert "MAIN/TRAY-B7" in codes

    def test_inventory_at_location(self, client, seeded_packing_line):
        sc = seeded_packing_line["scan_code"]
        # Move our test item to TRAY-B7
        client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": sc, "action": "MOVE", "to_location": "MAIN/TRAY-B7"},
            headers=_auth_headers(),
        )
        r = client.get("/api/v1/warehouse/locations/MAIN/TRAY-B7/inventory",
                       headers=_auth_headers())
        assert r.status_code == 200
        body = r.json()
        codes = [it["scan_code"] for it in body["items"]]
        assert sc in codes


# ── 7. Action validation ─────────────────────────────────────────────────────

class TestActionValidation:
    def test_unknown_action_400(self, client, seeded_packing_line):
        sc = seeded_packing_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": sc, "action": "TELEPORT", "to_location": "?"},
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert "TELEPORT" in r.json()["detail"]


# ── 7b. Location soft validation ──────────────────────────────────────────────

class TestLocationSoftValidation:
    def test_undeclared_location_allowed_with_flag(self, client, seeded_packing_line):
        """Scanning to an undeclared location succeeds but sets unknown_location=True."""
        sc = seeded_packing_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "MOVE",
                "to_location": "GHOST/SHELF-99",   # never declared
                "operator":    "amit",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["current_location"] == "GHOST/SHELF-99"
        assert body["unknown_location"] is True

    def test_declared_location_has_no_flag(self, client, seeded_packing_line):
        """Scanning to a declared location sets unknown_location=False."""
        sc = seeded_packing_line["scan_code"]
        # Ensure MAIN/TRAY-B7 exists (created in TestLocations)
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "MOVE",
                "to_location": "MAIN/TRAY-B7",
                "operator":    "amit",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unknown_location"] is False

    def test_undeclared_location_warning_in_event_note(self, client, seeded_packing_line):
        """The movement event note must carry the UNKNOWN_LOCATION warning."""
        sc = seeded_packing_line["scan_code"]
        client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "MOVE",
                "to_location": "PHANTOM/BIN-X",
                "operator":    "amit",
                "note":        "urgent transfer",
            },
            headers=_auth_headers(),
        )
        h = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth_headers()).json()
        latest_event = h["history"][-1]
        assert "UNKNOWN_LOCATION" in latest_event["note"]
        assert "PHANTOM/BIN-X"    in latest_event["note"]
        assert "urgent transfer"  in latest_event["note"]


# ── 8. scan_code parity with barcode endpoint ────────────────────────────────

class TestScanCodeParity:
    def test_scan_code_matches_barcode_value_function(self):
        """warehouse_db.scan_code_for_packing_line must equal routes_packing._barcode_value."""
        from app.api.routes_packing import _barcode_value
        line = {
            "product_code": "EJL/26-27/015-6",
            "design_no":    "JR06076",
            "bag_id":       "",
            "pack_sr":      14.0,
        }
        assert wdb.scan_code_for_packing_line(line) == _barcode_value(line)

    def test_scan_code_with_bag(self):
        from app.api.routes_packing import _barcode_value
        line = {
            "product_code": "EJL/26-27/100-1",
            "design_no":    "D-RING-001",
            "bag_id":       "BAG-7",
            "pack_sr":      1.0,
        }
        assert wdb.scan_code_for_packing_line(line) == _barcode_value(line)
        assert "BAG-7" in wdb.scan_code_for_packing_line(line)


# ── 9. Aggregate-invoice items get DIFFERENT scan_codes ──────────────────────

class TestAggregateUniqueness:
    def test_two_same_design_pieces_have_distinct_scan_codes(self, db, client):
        """Defends the 'JR06076 collapse' regression: two pieces of the same
        design must scan as different items in the warehouse."""
        line_a = {
            "packing_document_id":   "test-doc-agg",
            "batch_id":              "BATCH_AGG_TEST",
            "invoice_no":             "EJL/26-27/015",
            "invoice_line_position":  6,
            "product_code":           "EJL/26-27/015-6",
            "design_no":              "JR06076",
            "bag_id":                 "",
            "quantity":               1.0,
            "unit_price":             392.0,
            "total_value":            392.0,
            "pack_sr":                14.0,
            "extracted_confidence":   0.6,
            "requires_manual_review": False,
        }
        line_b = dict(line_a)
        line_b.update({"unit_price": 431.0, "total_value": 431.0, "pack_sr": 22.0})
        pdb.upsert_packing_lines([line_a, line_b])

        sc_a = wdb.scan_code_for_packing_line(line_a)
        sc_b = wdb.scan_code_for_packing_line(line_b)
        assert sc_a != sc_b
        assert "sr14" in sc_a
        assert "sr22" in sc_b

        # Both scannable independently
        client.post("/api/v1/warehouse/scan",
                    json={"scan_code": sc_a, "action": "RECEIVE", "to_location": "TRAY-A"},
                    headers=_auth_headers())
        client.post("/api/v1/warehouse/scan",
                    json={"scan_code": sc_b, "action": "RECEIVE", "to_location": "TRAY-B"},
                    headers=_auth_headers())
        loc_a = wdb.get_current_location(sc_a)["current_location"]
        loc_b = wdb.get_current_location(sc_b)["current_location"]
        assert loc_a == "TRAY-A"
        assert loc_b == "TRAY-B"

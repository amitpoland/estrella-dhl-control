"""
test_warehouse_ui.py — API contract tests for the warehouse scanner UI.

These tests verify the backend contract that warehouse.html depends on:
  1. Scan form submits a valid payload → 200 with expected fields
  2. unknown_location flag appears in response for undeclared locations
  3. current_location updates correctly after each scan
  4. GET /inventory returns history after scan (history panel data)
  5. GET /locations returns list the datalist is built from
  6. GET /config returns api_key when session-authenticated (session mock)
"""
from __future__ import annotations

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
    return tmp_path_factory.mktemp("wh_ui_storage")


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
def seeded_line(db):
    line = {
        "packing_document_id":   "ui-doc-1",
        "batch_id":              "BATCH_UI_TEST",
        "invoice_no":             "EJL/26-27/020",
        "invoice_line_position":  1,
        "product_code":           "EJL/26-27/020-1",
        "design_no":              "UI-RING-001",
        "bag_id":                 "",
        "tray_id":                "",
        "item_type":              "RNG",
        "uom":                    "PCS",
        "quantity":               1.0,
        "gross_weight":           4.20,
        "net_weight":             4.20,
        "metal":                  "18KT",
        "karat":                  "",
        "stone_type":             "",
        "remarks":                "",
        "extracted_confidence":   0.95,
        "requires_manual_review": False,
        "pack_sr":                3.0,
        "unit_price":             480.0,
        "total_value":            480.0,
        "batch_no":               "",
    }
    pdb.upsert_packing_lines([line])
    sc = wdb.scan_code_for_packing_line(line)
    return {"line": line, "scan_code": sc}


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── 1. Scan form submits valid payload ────────────────────────────────────────

class TestScanPayload:
    def test_valid_scan_returns_200_with_required_fields(self, client, seeded_line):
        sc = seeded_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "RECEIVE",
                "to_location": "MAIN/RECV-01",
                "operator":    "operator-ui",
                "note":        "initial intake via UI test",
            },
            headers=_auth(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Fields the UI result panel reads
        assert body["ok"]               is True
        assert body["scan_code"]        == sc
        assert body["action"]           == "RECEIVE"
        assert body["current_location"] == "MAIN/RECV-01"
        assert body["current_status"]   == "received"
        assert "unknown_location"       in body
        assert "event_count"            in body
        assert "updated_at"             in body
        # Inventory sub-object carries design_no, product_code, batch_id
        inv = body.get("inventory", {})
        assert inv.get("design_no")    == "UI-RING-001"
        assert inv.get("product_code") == "EJL/26-27/020-1"
        assert inv.get("batch_id")     == "BATCH_UI_TEST"

    def test_all_action_verbs_accepted(self, client, seeded_line):
        sc = seeded_line["scan_code"]
        for action in ("MOVE", "PICK", "PACK", "DISPATCH", "RETURN"):
            r = client.post(
                "/api/v1/warehouse/scan",
                json={"scan_code": sc, "action": action, "to_location": "ANY"},
                headers=_auth(),
            )
            assert r.status_code == 200, f"{action}: {r.text}"
            assert r.json()["action"] == action


# ── 2. unknown_location warning ───────────────────────────────────────────────

class TestUnknownLocationWarning:
    def test_undeclared_location_sets_flag_true(self, client, seeded_line):
        """The UI warn-banner depends on unknown_location=true in the response."""
        sc = seeded_line["scan_code"]
        r = client.post(
            "/api/v1/warehouse/scan",
            json={
                "scan_code":   sc,
                "action":      "MOVE",
                "to_location": "GHOST/ZONE-UI",
            },
            headers=_auth(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unknown_location"] is True
        assert body["current_location"] == "GHOST/ZONE-UI"

    def test_declared_location_sets_flag_false(self, client, seeded_line):
        sc = seeded_line["scan_code"]
        # Declare the location first
        client.post(
            "/api/v1/warehouse/locations",
            json={"location_code": "MAIN/UI-TRAY-01", "location_type": "tray", "warehouse": "MAIN"},
            headers=_auth(),
        )
        r = client.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": sc, "action": "MOVE", "to_location": "MAIN/UI-TRAY-01"},
            headers=_auth(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["unknown_location"] is False


# ── 3. current_location updates ───────────────────────────────────────────────

class TestCurrentLocationUpdates:
    def test_location_reflects_each_scan(self, client, seeded_line):
        sc = seeded_line["scan_code"]
        for loc in ("STAGE-A", "STAGE-B", "DISPATCH-DOCK"):
            client.post(
                "/api/v1/warehouse/scan",
                json={"scan_code": sc, "action": "MOVE", "to_location": loc},
                headers=_auth(),
            )
        # Verify final state
        inv = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth()).json()
        assert inv["current"]["current_location"] == "DISPATCH-DOCK"


# ── 4. History loads after scan ───────────────────────────────────────────────

class TestHistoryAfterScan:
    def test_inventory_endpoint_returns_history_list(self, client, seeded_line):
        """The HistoryPanel fetches GET /inventory/{scan_code} after each scan."""
        sc = seeded_line["scan_code"]
        r = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth())
        assert r.status_code == 200, r.text
        body = r.json()
        # Required fields for the history table
        assert "current" in body
        assert "history" in body
        assert isinstance(body["history"], list)
        assert len(body["history"]) > 0

        ev = body["history"][0]
        for field in ("action", "from_location", "to_location", "operator", "event_time", "note"):
            assert field in ev, f"history event missing field: {field}"

    def test_history_is_chronological(self, client, seeded_line):
        sc = seeded_line["scan_code"]
        body = client.get(f"/api/v1/warehouse/inventory/{sc}", headers=_auth()).json()
        times = [ev["event_time"] for ev in body["history"]]
        assert times == sorted(times)


# ── 5. Locations list for datalist ────────────────────────────────────────────

class TestLocationsList:
    def test_locations_endpoint_returns_list(self, client):
        """The datalist in ScanForm is built from GET /locations."""
        r = client.get("/api/v1/warehouse/locations", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert "locations" in body
        assert isinstance(body["locations"], list)
        # Each location must have location_code (the datalist value)
        for loc in body["locations"]:
            assert "location_code" in loc


# ── 6. Config endpoint (api_key delivery) ────────────────────────────────────

class TestConfigEndpoint:
    def test_config_returns_401_without_session(self, client):
        """No session cookie → 401. The endpoint is not publicly accessible."""
        r = client.get("/api/v1/warehouse/config")
        assert r.status_code == 401

    def test_config_returns_api_key_with_session(self, client):
        """
        Authenticated session → 200 with api_key field.

        Uses dependency_override to inject a mock user (avoids wiring a full
        auth DB inside TestClient lifespan). The auth mechanism itself is
        tested in the auth test suite; here we only verify response contract.
        """
        from app.auth.dependencies import get_current_user

        mock_user = {"id": "mock-uid", "email": "scanner@test.internal",
                     "role": "logistics", "is_active": True}

        app.dependency_overrides[get_current_user] = lambda: mock_user
        try:
            r = client.get("/api/v1/warehouse/config")
            assert r.status_code == 200
            body = r.json()
            assert "api_key" in body
        finally:
            app.dependency_overrides.pop(get_current_user, None)

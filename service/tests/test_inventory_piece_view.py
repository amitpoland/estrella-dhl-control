"""Tests for GET /api/v1/inventory/pieces/{piece_id} (read-only)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.main import app
from app.core.security import require_api_key


app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


def test_endpoint_get_only():
    r = client.get("/api/v1/inventory/pieces/SCAN-001")
    assert r.status_code == 200, r.text
    for method in ("post", "put", "patch", "delete"):
        rr = getattr(client, method)("/api/v1/inventory/pieces/SCAN-001")
        assert rr.status_code in (404, 405), (
            f"{method.upper()} unexpectedly accepted: {rr.status_code}"
        )


def test_unknown_piece_returns_honest_empty():
    r = client.get("/api/v1/inventory/pieces/SCAN-NOPE-zzz")
    assert r.status_code == 200
    data = r.json()
    assert data["piece_id"] == "SCAN-NOPE-zzz"
    assert data["found"] is False
    assert data["state"] is None
    assert data["history"] == []


def test_envelope_schema():
    r = client.get("/api/v1/inventory/pieces/SCAN-001")
    data = r.json()
    # Phase B.2 — envelope now includes timeline + location + limitations.
    # `history` is preserved as a legacy alias for one release.
    for key in ("piece_id", "as_of", "found", "state",
                "history", "timeline", "location", "limitations", "degraded"):
        assert key in data, f"Missing top-level key: {key}"
    assert isinstance(data["timeline"],    list)
    assert isinstance(data["limitations"], list)
    assert isinstance(data["history"],     list)


def test_as_of_validation():
    r = client.get("/api/v1/inventory/pieces/SCAN-001?as_of=2026-05-11T00:00:00Z")
    assert r.status_code == 200
    assert r.json()["as_of"] == "2026-05-11T00:00:00Z"

    rb = client.get("/api/v1/inventory/pieces/SCAN-001?as_of=not-a-date")
    assert rb.status_code == 422


def test_found_piece_returns_state_and_history():
    fake_state = {
        "id": "row-1",
        "scan_code": "SCAN-FOUND",
        "product_code": "P1",
        "design_no": "D1",
        "batch_id": "B1",
        "state": "WAREHOUSE_STOCK",
        "updated_at": "2026-05-11T00:00:00Z",
        "updated_by": "test",
        "note": "",
    }
    fake_history = [
        {"id": "ev-1", "scan_code": "SCAN-FOUND",
         "from_state": "", "to_state": "PURCHASE_TRANSIT",
         "trigger": "pz_generated", "occurred_at": "2026-05-10T00:00:00Z",
         "operator": "test", "note": ""},
        {"id": "ev-2", "scan_code": "SCAN-FOUND",
         "from_state": "PURCHASE_TRANSIT", "to_state": "WAREHOUSE_STOCK",
         "trigger": "warehouse_receive", "occurred_at": "2026-05-11T00:00:00Z",
         "operator": "test", "note": ""},
    ]
    with patch(
        "app.services.inventory_piece_view.inventory_state_engine.get_state",
        return_value=fake_state,
    ), patch(
        "app.services.inventory_piece_view.inventory_state_engine.get_history",
        return_value=fake_history,
    ), patch(
        "app.services.inventory_piece_view.warehouse_db.get_current_location",
        return_value=None,
    ), patch(
        "app.services.inventory_piece_view.warehouse_db.get_movement_history",
        return_value=[],
    ), patch(
        "app.services.inventory_piece_view.warehouse_db.get_sample_out_history",
        return_value=[],
    ), patch(
        "app.services.inventory_piece_view.warehouse_db.get_returns_history",
        return_value=[],
    ):
        r = client.get("/api/v1/inventory/pieces/SCAN-FOUND")
        data = r.json()
        assert data["found"] is True
        assert data["state"]["scan_code"] == "SCAN-FOUND"
        assert data["state"]["state"] == "WAREHOUSE_STOCK"
        assert len(data["history"]) == 2
        assert data["degraded"] is False


def test_degraded_when_warehouse_db_unavailable():
    with patch(
        "app.services.inventory_piece_view.inventory_state_engine.get_state",
        side_effect=RuntimeError("warehouse_db not initialised"),
    ):
        r = client.get("/api/v1/inventory/pieces/SCAN-001")
        data = r.json()
        assert r.status_code == 200
        assert data["degraded"] is True
        assert data["found"] is False
        assert data["state"] is None


def test_no_write_methods_on_pieces_path():
    # Scope: the per-piece READ endpoint (/pieces/{piece_id}) is and
    # stays read-only. The /pieces/ prefix is now shared with the
    # Move stock writes router (POST /pieces/{piece_id}/location),
    # which is an intentional, security-reviewed activation. This
    # test enforces read-only on the piece-detail GET and explicitly
    # allowlists the one approved write.
    routes = [
        r for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/inventory/pieces")
    ]
    assert routes, "/api/v1/inventory/pieces route not registered"
    allowed_writes = {
        "/api/v1/inventory/pieces/{piece_id}/location",              # Move stock — POST
        "/api/v1/inventory/pieces/{piece_id}/sample-out",            # Sample-out — POST (Phase B.1)
        "/api/v1/inventory/pieces/{piece_id}/sample-return",         # Sample-return — POST (Phase B.1)
        "/api/v1/inventory/pieces/{piece_id}/return-from-client",    # Returns — POST (Phase B.2)
        "/api/v1/inventory/pieces/{piece_id}/return-to-producer",    # Returns — POST (Phase B.2)
        "/api/v1/inventory/pieces/{piece_id}/return-from-producer",  # Returns — POST (Phase B.2)
        "/api/v1/inventory/pieces/{piece_id}/qc-disposition",        # QC disposition — POST (Returns QC)
        "/api/v1/inventory/pieces/{piece_id}/correction/identity",   # Identity correction — POST (Package A)
        "/api/v1/inventory/pieces/{piece_id}/correction/archive-proposal",  # Archive proposal — POST (Package A)
        "/api/v1/inventory/pieces/{piece_id}/reversal/{reversal_target}",  # Transit reversal — POST (Package B)
    }
    for route in routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set())
        non_safe = methods - {"GET", "HEAD", "OPTIONS"}
        if non_safe and path in allowed_writes:
            continue
        assert not non_safe, f"Forbidden method on {path}: {non_safe}"


def test_service_module_has_no_writes():
    import inspect
    from app.services import inventory_piece_view as m
    src = inspect.getsource(m)
    for forbidden in ('"INSERT INTO', "'INSERT INTO",
                      '"UPDATE ', "'UPDATE ",
                      '"DELETE FROM', "'DELETE FROM",
                      ".commit(", ".add(", "executemany("):
        assert forbidden not in src, (
            f"inventory_piece_view contains forbidden write pattern: {forbidden}"
        )

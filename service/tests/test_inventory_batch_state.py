"""Tests for GET /api/v1/inventory/state/{batch_id} (read-only)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.smoke

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.main import app
from app.core.security import require_api_key


app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


CANONICAL_STATES = {
    "PURCHASE_TRANSIT",
    "WAREHOUSE_STOCK",
    "DIRECT_DISPATCH_READY",
    "CLIENT_DISPATCHED",
    "SALES_TRANSIT",
    "CLOSED",
    "SAMPLE_OUT",            # Phase B.1 — added with Sample-out activation
    "RETURNED_FROM_CLIENT",  # Phase B.2 — added with Returns activation
    "RETURNED_TO_PRODUCER",  # Phase B.2 — added with Returns activation
    "WRITTEN_OFF",           # Returns QC Disposition — write-off terminal state
}


def test_endpoint_get_only():
    r = client.get("/api/v1/inventory/state/batch-xyz")
    assert r.status_code == 200, r.text
    for method in ("post", "put", "patch", "delete"):
        rr = getattr(client, method)("/api/v1/inventory/state/batch-xyz")
        assert rr.status_code in (404, 405), (
            f"{method.upper()} unexpectedly accepted: {rr.status_code}"
        )


def test_unknown_batch_returns_honest_empty():
    r = client.get("/api/v1/inventory/state/batch-does-not-exist-zzz")
    assert r.status_code == 200
    data = r.json()
    assert data["batch_id"] == "batch-does-not-exist-zzz"
    assert data["total"] == 0
    assert data["pieces"] == []
    # Counts dict present with all canonical states zeroed
    assert set(data["counts"].keys()) == CANONICAL_STATES
    assert all(v == 0 for v in data["counts"].values())


def test_response_envelope_shape():
    r = client.get("/api/v1/inventory/state/some-batch")
    data = r.json()
    for key in ("batch_id", "as_of", "counts", "pieces", "total"):
        assert key in data, f"Missing top-level key: {key}"
    assert isinstance(data["counts"], dict)
    assert isinstance(data["pieces"], list)
    assert isinstance(data["total"], int)


def test_as_of_param_optional_and_validated():
    r1 = client.get("/api/v1/inventory/state/some-batch")
    assert r1.json()["as_of"], "Server should fill as_of when omitted"

    r2 = client.get(
        "/api/v1/inventory/state/some-batch?as_of=2026-05-11T00:00:00Z"
    )
    assert r2.status_code == 200
    assert r2.json()["as_of"] == "2026-05-11T00:00:00Z"

    r3 = client.get("/api/v1/inventory/state/some-batch?as_of=not-a-date")
    assert r3.status_code == 422


def test_counts_match_pieces_aggregation():
    """When pieces exist, counts must equal piece-state aggregation.

    Patched at the engine level to inject deterministic data.
    """
    fake_counts = {s: 0 for s in CANONICAL_STATES}
    fake_counts["WAREHOUSE_STOCK"] = 3
    fake_counts["PURCHASE_TRANSIT"] = 1

    fake_pieces = [
        {"scan_code": "S001", "state": "WAREHOUSE_STOCK",
         "product_code": "P1", "design_no": "D1", "updated_at": "2026-05-11"},
        {"scan_code": "S002", "state": "WAREHOUSE_STOCK",
         "product_code": "P1", "design_no": "D1", "updated_at": "2026-05-11"},
        {"scan_code": "S003", "state": "WAREHOUSE_STOCK",
         "product_code": "P2", "design_no": "D2", "updated_at": "2026-05-11"},
        {"scan_code": "S004", "state": "PURCHASE_TRANSIT",
         "product_code": "P2", "design_no": "D2", "updated_at": "2026-05-11"},
    ]

    with patch(
        "app.services.inventory_batch_state.inventory_state_engine.count_by_state",
        return_value=fake_counts,
    ), patch(
        "app.services.inventory_batch_state._list_pieces_for_batch",
        return_value=fake_pieces,
    ):
        r = client.get("/api/v1/inventory/state/some-batch")
        data = r.json()
        assert data["total"] == 4
        assert data["counts"]["WAREHOUSE_STOCK"] == 3
        assert data["counts"]["PURCHASE_TRANSIT"] == 1
        assert len(data["pieces"]) == 4


def _collect_routes(router_or_app):
    """Recursively collect APIRoute objects; handles FastAPI _IncludedRouter wrappers."""
    from fastapi.routing import APIRoute
    result = []
    for r in getattr(router_or_app, "routes", []):
        if isinstance(r, APIRoute):
            result.append(r)
        # FastAPI wraps include_router() in _IncludedRouter with .original_router
        inner = getattr(r, "original_router", None)
        if inner is not None:
            result.extend(_collect_routes(inner))
    return result


def test_no_write_methods_on_state_path():
    routes = [
        r for r in _collect_routes(app)
        if getattr(r, "path", "").startswith("/api/v1/inventory/state")
    ]
    assert routes, "/api/v1/inventory/state route not registered"
    for route in routes:
        methods = set(getattr(route, "methods", set()) or set())
        non_safe = methods - {"GET", "HEAD", "OPTIONS"}
        assert not non_safe, f"Forbidden method on {route.path}: {non_safe}"


def test_service_module_has_no_writes():
    import inspect
    from app.services import inventory_batch_state as m
    src = inspect.getsource(m)
    for forbidden in ('"INSERT INTO', "'INSERT INTO",
                      '"UPDATE ', "'UPDATE ",
                      '"DELETE FROM', "'DELETE FROM",
                      ".commit(", ".add(", "executemany("):
        assert forbidden not in src, (
            f"inventory_batch_state contains forbidden write pattern: {forbidden}"
        )

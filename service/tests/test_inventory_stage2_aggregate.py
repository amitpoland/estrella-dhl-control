"""Backend tests for /api/v1/inventory/stage2/aggregate (read-only)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure service/ is on sys.path for the `app.X` short imports.
_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.main import app
from app.core.security import require_api_key


# Test fixture — bypass auth per codebase convention
app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


CANONICAL_CATEGORIES = {"final_stock", "samples", "returns", "consignment", "unknown"}


def test_endpoint_exists_and_is_get_only():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    assert r.status_code == 200, f"GET returned {r.status_code}: {r.text}"
    for method in ("post", "put", "patch", "delete"):
        rr = getattr(client, method)("/api/v1/inventory/stage2/aggregate")
        assert rr.status_code in (404, 405), \
            f"{method.upper()} unexpectedly accepted: {rr.status_code}"


def test_response_envelope_schema():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    for key in ("status", "generated_at", "as_of", "source", "stage2", "limitations"):
        assert key in data, f"Missing top-level key: {key}"
    assert set(data["stage2"].keys()) == CANONICAL_CATEGORIES
    for cat in CANONICAL_CATEGORIES:
        assert set(data["stage2"][cat].keys()) >= {"count", "basis"}, \
            f"{cat} missing count/basis"


def test_count_is_int_or_null():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    for cat in CANONICAL_CATEGORIES:
        c = data["stage2"][cat]["count"]
        assert c is None or (isinstance(c, int) and c >= 0), \
            f"{cat}: bad count {c!r} (expected int >= 0 or None)"


def test_basis_is_non_empty_string():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    for cat in CANONICAL_CATEGORIES:
        b = data["stage2"][cat]["basis"]
        assert isinstance(b, str) and len(b) > 0, f"{cat}: empty basis"


def test_limitations_match_null_counts():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    null_cats = [c for c in CANONICAL_CATEGORIES if data["stage2"][c]["count"] is None]
    for cat in null_cats:
        assert any(cat in lim for lim in data["limitations"]), \
            f"No limitation referencing null category {cat}"


def test_no_500_when_source_missing():
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        side_effect=RuntimeError("warehouse_db not initialised"),
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "degraded"
        assert data["stage2"]["final_stock"]["count"] is None
        assert any("final_stock" in lim for lim in data["limitations"])


def test_no_write_methods_registered():
    # Note: trailing slash distinguishes /api/v1/inventory/* (this router)
    # from /api/v1/inventory-state/* (pre-existing lifecycle POST).
    routes = [r for r in app.routes
              if getattr(r, "path", "").startswith("/api/v1/inventory/")]
    assert routes, "No /api/v1/inventory/ routes registered"
    for route in routes:
        methods = set(getattr(route, "methods", set()) or set())
        non_safe = methods - {"GET", "HEAD", "OPTIONS"}
        assert not non_safe, \
            f"Non-GET method registered on {route.path}: {non_safe}"


def test_no_db_writes_in_aggregator_source():
    from app.services import inventory_stage2_aggregator as m
    src = inspect.getsource(m)
    # Scan non-docstring/non-comment lines only — the module docstring
    # legitimately mentions "No INSERT / UPDATE / DELETE" as documentation.
    code_lines = []
    in_docstring = False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # toggle (one-line or multi-line docstring boundary)
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                pass  # one-line docstring, no toggle
            else:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines)
    # Real write patterns: SQL-context or ORM-context
    for forbidden in ('"INSERT INTO', "'INSERT INTO",
                      '"UPDATE ',     "'UPDATE ",
                      '"DELETE FROM', "'DELETE FROM",
                      ".add(", ".commit(", ".flush(", "executemany("):
        assert forbidden not in code_only, \
            f"Aggregator code contains forbidden write pattern: {forbidden}"


def test_as_of_param_optional_and_round_trips():
    r1 = client.get("/api/v1/inventory/stage2/aggregate")
    assert r1.json()["as_of"], "Server should fill as_of when omitted"

    r2 = client.get("/api/v1/inventory/stage2/aggregate?as_of=2026-01-01T00:00:00Z")
    assert r2.status_code == 200
    assert r2.json()["as_of"] == "2026-01-01T00:00:00Z"

    r3 = client.get("/api/v1/inventory/stage2/aggregate?as_of=not-a-timestamp")
    assert r3.status_code == 422


def test_source_descriptions_reference_real_tables():
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    assert "inventory_state_engine.count_by_state" in data["source"]["warehouse"]
    assert "inventory_state" in data["source"]["lifecycle"]


def test_honest_zero_vs_null_distinguished():
    # Empty source → honest zero
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value={},
    ):
        r_zero = client.get("/api/v1/inventory/stage2/aggregate")
        d_zero = r_zero.json()
        assert d_zero["stage2"]["final_stock"]["count"] == 0
        assert d_zero["status"] == "ok"

    # Source raises → honest null
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        side_effect=RuntimeError("db not initialised"),
    ):
        r_null = client.get("/api/v1/inventory/stage2/aggregate")
        d_null = r_null.json()
        assert d_null["stage2"]["final_stock"]["count"] is None
        assert d_null["status"] == "degraded"

    assert d_zero["stage2"]["final_stock"] != d_null["stage2"]["final_stock"]

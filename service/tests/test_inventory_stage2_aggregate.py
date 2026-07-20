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


@pytest.fixture(autouse=True)
def _bypass_auth():
    # app is the shared app.main singleton — a module-level override here
    # fires at collection and disables auth for every test collected after
    # it, silently breaking 401 assertions across the suite.
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


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
    # Scope: the Stage 2 aggregator's router is and stays read-only.
    # The /api/v1/inventory/ prefix is now shared with the Move stock
    # writes router (POST /pieces/{piece_id}/location), which is an
    # intentional, security-reviewed activation. This test enforces
    # the read-only invariant on the AGGREGATOR's specific endpoints
    # and explicitly allowlists the one approved write.
    routes = [r for r in app.routes
              if getattr(r, "path", "").startswith("/api/v1/inventory/")]
    assert routes, "No /api/v1/inventory/ routes registered"
    allowed_writes = {
        "/api/v1/inventory/pieces/{piece_id}/location",              # Move stock — POST
        "/api/v1/inventory/pieces/{piece_id}/sample-out",            # Sample-out — POST (Phase B.1)
        "/api/v1/inventory/pieces/{piece_id}/sample-return",         # Sample-return — POST (Phase B.1)
        "/api/v1/inventory/pieces/{piece_id}/return-from-client",    # Returns — POST (Phase B.2)
        "/api/v1/inventory/pieces/{piece_id}/return-to-producer",    # Returns — POST (Phase B.2)
        "/api/v1/inventory/pieces/{piece_id}/return-from-producer",  # Returns — POST (Phase B.2)
    }
    for route in routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set())
        non_safe = methods - {"GET", "HEAD", "OPTIONS"}
        if non_safe and path in allowed_writes:
            continue
        assert not non_safe, \
            f"Non-GET method registered on {path}: {non_safe}"


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
    # Empty-source mock — final_stock takes 0 from .get(), but samples
    # degrades because the dict lacks the SAMPLE_OUT key (Phase B.1
    # missing-key contract). In production, count_by_state() pre-seeds
    # ALL keys including SAMPLE_OUT, so this case is mock-only.
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value={},
    ):
        r_zero = client.get("/api/v1/inventory/stage2/aggregate")
        d_zero = r_zero.json()
        assert d_zero["stage2"]["final_stock"]["count"] == 0
        assert d_zero["stage2"]["samples"]["count"] is None
        assert d_zero["status"] == "degraded"
        assert any("SAMPLE_OUT state missing" in lim
                   for lim in d_zero["limitations"])

    # Source raises → honest null on BOTH final_stock and samples.
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        side_effect=RuntimeError("db not initialised"),
    ):
        r_null = client.get("/api/v1/inventory/stage2/aggregate")
        d_null = r_null.json()
        assert d_null["stage2"]["final_stock"]["count"] is None
        assert d_null["stage2"]["samples"]["count"]     is None
        assert d_null["status"] == "degraded"

    assert d_zero["stage2"]["final_stock"] != d_null["stage2"]["final_stock"]


_FULL_COUNT_BY_STATE = {
    "WAREHOUSE_STOCK":       12,
    "SAMPLE_OUT":             3,
    "RETURNED_FROM_CLIENT":   2,
    "RETURNED_TO_PRODUCER":   1,
    "PURCHASE_TRANSIT":       0,
    "DIRECT_DISPATCH_READY":  0,
    "CLIENT_DISPATCHED":      0,
    "SALES_TRANSIT":          0,
    "CLOSED":                 0,
}


def test_samples_count_derived_from_sample_out_state():
    """Phase B.1 — samples count derives from
    inventory_state.state='SAMPLE_OUT'. With Phase B.2 keys present the
    response is fully ok status."""
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value=dict(_FULL_COUNT_BY_STATE),
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        data = r.json()
        assert data["stage2"]["samples"]["count"] == 3
        assert data["stage2"]["samples"]["basis"] == \
            "inventory_state.state = 'SAMPLE_OUT'"
        assert data["stage2"]["samples"]["confidence"] == "HIGH"
        assert data["stage2"]["final_stock"]["count"] == 12
        assert data["status"] == "ok"
        assert not any(lim.startswith("samples:")
                       for lim in data["limitations"])


def test_samples_zero_count_is_honest_when_no_sample_out_pieces():
    """Empty SAMPLE_OUT bucket in a real (fully-keyed) count_by_state
    dict → samples count = 0, NOT null, NOT a limitation."""
    zeros = dict(_FULL_COUNT_BY_STATE)
    zeros["WAREHOUSE_STOCK"] = 5
    for k in ("SAMPLE_OUT", "RETURNED_FROM_CLIENT", "RETURNED_TO_PRODUCER"):
        zeros[k] = 0
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value=zeros,
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        data = r.json()
        assert data["stage2"]["samples"]["count"] == 0
        assert data["status"] == "ok"
        assert not any(lim.startswith("samples:")
                       for lim in data["limitations"])


def test_returns_count_derived_from_two_states():
    """Phase B.2 — returns.count = RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER.
    subcounts.from_client / to_producer expose the split."""
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value=dict(_FULL_COUNT_BY_STATE),
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        data = r.json()
        returns = data["stage2"]["returns"]
        assert returns["count"] == 3   # 2 + 1
        assert returns["basis"] == \
            "inventory_state.state IN ('RETURNED_FROM_CLIENT', 'RETURNED_TO_PRODUCER')"
        assert returns["confidence"] == "HIGH"
        assert returns["subcounts"]["from_client"] == 2
        assert returns["subcounts"]["to_producer"] == 1
        assert data["status"] == "ok"
        assert not any(lim.startswith("returns:")
                       for lim in data["limitations"])


def test_returns_missing_key_degrades_alone():
    """Mock dict without RETURNED_FROM_CLIENT key → returns degrades,
    samples + final_stock still derive."""
    partial = dict(_FULL_COUNT_BY_STATE)
    del partial["RETURNED_FROM_CLIENT"]
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value=partial,
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        data = r.json()
        assert data["stage2"]["final_stock"]["count"] == 12
        assert data["stage2"]["samples"]["count"] == 3
        assert data["stage2"]["returns"]["count"] is None
        assert data["status"] == "degraded"
        assert any("RETURNED_FROM_CLIENT or RETURNED_TO_PRODUCER" in lim
                   for lim in data["limitations"])


def test_returns_subcounts_zero_when_no_returns_pieces():
    """Both returns keys present at 0 → returns.count=0,
    subcounts={from_client:0, to_producer:0}, no limitation."""
    zeros = dict(_FULL_COUNT_BY_STATE)
    for k in ("RETURNED_FROM_CLIENT", "RETURNED_TO_PRODUCER"):
        zeros[k] = 0
    with patch(
        "app.services.inventory_stage2_aggregator.inventory_state_engine.count_by_state",
        return_value=zeros,
    ):
        r = client.get("/api/v1/inventory/stage2/aggregate")
        data = r.json()
        assert data["stage2"]["returns"]["count"] == 0
        assert data["stage2"]["returns"]["subcounts"]["from_client"] == 0
        assert data["stage2"]["returns"]["subcounts"]["to_producer"] == 0
        assert data["status"] == "ok"
        assert not any(lim.startswith("returns:")
                       for lim in data["limitations"])


def test_no_stale_samples_limitation_emitted_anymore():
    """The Phase B.1 brief retired the
    'SAMPLE_OUT not in inventory_state_engine.STATES' claim. It must
    NEVER appear in the live aggregator response, even on degraded
    paths."""
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    for lim in data["limitations"]:
        assert "SAMPLE_OUT not in inventory_state_engine.STATES" not in lim, (
            f"Stale samples limitation must not be emitted: {lim!r}"
        )


def test_consignment_unknown_remain_pending():
    """Phase B.2 activated returns. Consignment + unknown remain
    null + limited until their backend support lands."""
    r = client.get("/api/v1/inventory/stage2/aggregate")
    data = r.json()
    for cat in ("consignment", "unknown"):
        assert data["stage2"][cat]["count"] is None, \
            f"{cat} must remain null until backend support lands"
        assert any(cat in lim for lim in data["limitations"]), \
            f"{cat} must still surface a limitation"

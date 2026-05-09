"""
test_carrier_proposal_routes_read_only.py — DL-D3 read-only proposal
routes test suite.

Required coverage:
  1. Route file contains only ``@router.get`` decorators.
  2. No ``@router.post / put / patch / delete`` in the route file.
  3. ``main.py`` mounts ``routes_carrier_proposals``.
  4. Empty proposal list returns count 0.
  5. ``/by-batch/{batch_id}`` returns the create-shipment proposal for
     an empty batch.
  6. Registry with a ``label_created`` shipment returns
     mark-label-printed and cancel proposals.
  7. Registry with a ``label_printed`` shipment returns
     mark-handed-to-carrier and cancel proposals.
  8. Terminal shipment emits no open shipment-state proposals; the
     create-shipment proposal is still emitted by the builder when
     batch is queried.
  9. Source-grep — no service-orchestration import.
  10. Source-grep — no carrier-adapter import (live or stub).
  11. Source-grep — no execution / approve / queue / reject logic.
  12. Source-grep — no DB write helper calls.
  13. Source-grep — no HTTP client imports.
  14. Source-grep — no DHL live/stub adapter references.
  15. Response shape always contains ``proposals`` and ``count``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_proposals as rcp
from app.core.config import settings
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.base import CARRIER_DHL


_ROUTE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_proposals.py"
)
_MAIN_FILE = (
    Path(__file__).resolve().parents[1] / "app" / "main.py"
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def route_src() -> str:
    return _ROUTE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_src() -> str:
    return _MAIN_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated carrier DB path.

    The route uses ``settings.storage_root / "carrier_shipments.db"``,
    so we monkey-patch ``settings.storage_root`` to a tmp dir and
    initialise the DB at the same path the route will resolve.
    """
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    csdb.init_db(tmp_path / "carrier_shipments.db")
    app = FastAPI()
    app.include_router(rcp.router)
    return TestClient(app, raise_server_exceptions=True)


# ── 1+2. Route file is read-only by source-grep ────────────────────────────

def test_route_file_only_has_get_decorators(route_src):
    decorators = re.findall(r"@router\.(get|post|put|patch|delete)\b", route_src)
    assert decorators, "no @router.* decorators found in route file"
    for verb in decorators:
        assert verb == "get", (
            f"non-GET verb @router.{verb} found in "
            f"routes_carrier_proposals.py — DL-D3 must remain read-only."
        )


@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_no_write_decorators(route_src, verb):
    pattern = re.compile(rf"@router\.{verb}\b")
    assert not pattern.search(route_src), (
        f"@router.{verb} found in routes_carrier_proposals.py — "
        f"DL-D3 is read-only."
    )


# ── 3. main.py mounts the router ───────────────────────────────────────────

def test_main_imports_proposals_router(main_src):
    assert (
        "from .api.routes_carrier_proposals import router "
        "as carrier_proposals_router"
    ) in main_src


def test_main_includes_proposals_router(main_src):
    assert "app.include_router(carrier_proposals_router)" in main_src


# ── 4. Empty list returns count 0 ──────────────────────────────────────────

def test_empty_registry_returns_count_zero(client):
    r = client.get("/api/v1/carrier/proposals")
    assert r.status_code == 200
    body = r.json()
    assert body["proposals"] == []
    assert body["count"] == 0


# ── 5. by-batch on empty batch yields create-shipment proposal ─────────────

def test_by_batch_empty_yields_create_shipment(client):
    r = client.get("/api/v1/carrier/proposals/by-batch/B-EMPTY")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    proposal = body["proposals"][0]
    assert proposal["action"] == "create_shipment"
    assert proposal["batch_id"] == "B-EMPTY"
    assert proposal["enabled"] is True
    assert proposal["severity"] == "info"


# ── 6. label_created shipment yields mark-printed + cancel ─────────────────

def test_label_created_yields_mark_printed_and_cancel(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="LBL-D3-1",
        state=cse.LABEL_CREATED, batch_id="B-D3-LC",
    )
    r = client.get("/api/v1/carrier/proposals/by-batch/B-D3-LC")
    assert r.status_code == 200
    body = r.json()
    actions = sorted({p["action"] for p in body["proposals"]})
    assert "mark_label_printed" in actions
    assert "cancel_shipment" in actions
    # Plus a (blocked) create-shipment because the batch already has
    # an active shipment.
    assert "create_shipment" in actions
    create = next(
        p for p in body["proposals"] if p["action"] == "create_shipment"
    )
    assert create["enabled"] is False
    mark = next(
        p for p in body["proposals"] if p["action"] == "mark_label_printed"
    )
    assert mark["enabled"] is True
    cancel = next(
        p for p in body["proposals"] if p["action"] == "cancel_shipment"
    )
    assert cancel["enabled"] is True


def test_global_endpoint_includes_per_shipment_proposals(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="GLO-D3-1",
        state=cse.LABEL_CREATED, batch_id="B-D3-GLO",
    )
    r = client.get("/api/v1/carrier/proposals")
    assert r.status_code == 200
    body = r.json()
    actions_for_awb = {
        p["action"] for p in body["proposals"] if p.get("awb") == "GLO-D3-1"
    }
    assert "mark_label_printed" in actions_for_awb
    assert "cancel_shipment" in actions_for_awb
    # Global endpoint never emits create_shipment (no batch context).
    assert "create_shipment" not in {p["action"] for p in body["proposals"]}


# ── 7. label_printed shipment yields mark-handed + cancel ──────────────────

def test_label_printed_yields_mark_handed_and_cancel(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="LBL-D3-2",
        state=cse.LABEL_PRINTED, batch_id="B-D3-LP",
    )
    r = client.get("/api/v1/carrier/proposals/by-batch/B-D3-LP")
    body = r.json()
    actions = sorted({p["action"] for p in body["proposals"]})
    assert "mark_handed_to_carrier" in actions
    assert "cancel_shipment" in actions
    assert "mark_label_printed" not in actions


# ── 8. Terminal shipment emits no per-shipment proposals ───────────────────

@pytest.mark.parametrize("state", [cse.DELIVERED, cse.RETURNED, cse.VOIDED])
def test_terminal_shipment_emits_only_create_proposal(client, state):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb=f"TRM-{state}",
        state=state, batch_id=f"B-D3-{state}",
    )
    r = client.get(f"/api/v1/carrier/proposals/by-batch/B-D3-{state}")
    body = r.json()
    actions = sorted({p["action"] for p in body["proposals"]})
    # Builder allows create-shipment again when only terminal
    # shipments are present.
    assert actions == ["create_shipment"]
    create = body["proposals"][0]
    assert create["enabled"] is True


def test_global_endpoint_excludes_terminal_shipments(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="DEL-D3-1",
        state=cse.DELIVERED, batch_id="B-D3-DEL",
    )
    r = client.get("/api/v1/carrier/proposals")
    body = r.json()
    awbs = {p.get("awb") for p in body["proposals"]}
    # The terminal shipment yields zero per-shipment proposals.
    assert "DEL-D3-1" not in awbs


# ── Sorting determinism ────────────────────────────────────────────────────

def test_sort_order_info_then_warning_then_blocked(client):
    """Mix shipments to provoke different severities, then check order."""
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="MIX-LC",
        state=cse.LABEL_CREATED, batch_id="B-MIX",
    )
    # second shipment in same batch — create_shipment will be blocked
    # which gives us a "blocked" severity entry to sort.
    r = client.get("/api/v1/carrier/proposals/by-batch/B-MIX")
    body = r.json()
    severity_seq = [p["severity"] for p in body["proposals"]]
    rank = {"info": 0, "warning": 1, "blocked": 2}
    ranks = [rank[s] for s in severity_seq]
    assert ranks == sorted(ranks), (
        f"proposals not sorted by severity: {severity_seq}"
    )


# ── 15. Response shape always contains proposals + count ───────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/carrier/proposals",
    "/api/v1/carrier/proposals/by-batch/SHAPE-1",
    "/api/v1/carrier/proposals/by-batch/SHAPE-EMPTY",
])
def test_response_shape_contains_proposals_and_count(client, path):
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    assert "proposals" in body
    assert "count" in body
    assert isinstance(body["proposals"], list)
    assert isinstance(body["count"], int)
    assert body["count"] == len(body["proposals"])


# ── 9. No coordinator import ───────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "carrier_coordinator",
    "from .services.carrier.carrier_coordinator",
    "from ..services.carrier.carrier_coordinator",
    "from .carrier_coordinator",
    "CarrierCoordinator",
])
def test_route_file_no_coordinator_import(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_proposals.py contains {forbidden!r} — "
        f"DL-D3 is read-only and must not couple to the orchestrator."
    )


# ── 10+14. No adapter import ──────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    ".adapters",
    "from .adapters",
    "from ..adapters",
    "from ..services.carrier.adapters",
    "from .services.carrier.adapters",
    "DHLExpressStubAdapter",
    "dhl_express_stub",
    "CarrierAdapter",
])
def test_route_file_no_adapter_reference(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_proposals.py contains {forbidden!r} — "
        f"the read-only proposal layer must not reach into any "
        f"carrier adapter, live or stub."
    )


# ── 11. No execution / approve / queue / reject logic ─────────────────────

@pytest.mark.parametrize("forbidden", [
    "queue_email(",
    "approve_proposal",
    "execute_proposal",
    "reject_proposal",
    "def approve(",
    "def execute(",
    "def queue(",
    "def reject(",
    "from ..api.routes_action_proposals",
    "from .routes_action_proposals",
    "import routes_action_proposals",
])
def test_route_file_no_execution_logic(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_proposals.py contains {forbidden!r} — "
        f"DL-D3 is read-only; execution lives in DL-D4."
    )


# ── 12. No DB write helper calls ──────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "csdb.upsert_shipment",
    "csdb.record_transition",
    "upsert_shipment(",
    "record_transition(",
])
def test_route_file_no_db_writes(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_proposals.py contains {forbidden!r} — "
        f"DL-D3 is read-only; DB writes belong in the coordinator."
    )


# ── 13. No HTTP client imports ────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_route_file_no_http_clients(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_proposals.py contains {forbidden!r} — "
        f"the read-only proposal layer makes no outbound HTTP calls."
    )

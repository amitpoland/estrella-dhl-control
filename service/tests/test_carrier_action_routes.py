"""
test_carrier_action_routes.py — DL-D5 gated carrier execution routes.

Required coverage (28 assertions total):
  1. Router uses dependencies=[Depends(require_api_key)].
  2. Route file contains only POST decorators.
  3. Route file contains no GET / PUT / PATCH / DELETE decorators.
  4. main.py mounts the carrier actions router.
  5. Route file does not import the adapter base or the live DHL adapter.
  6. Route file does not import requests / httpx / urllib.
  7. No live-DHL env flag is read (CARRIER_DHL_LIVE).
  8. Every route handler uses proposal_write_lock.
  9. Routes call CarrierCoordinator, never DB write helpers directly.
  10. create-shipment happy path creates row, label, manifest, two transitions.
  11. create-shipment stale proposal_id → 409.
  12. create-shipment duplicate active shipment → 409.
  13. mark-label-printed happy path label_created → label_printed.
  14. mark-label-printed wrong state → 409.
  15. mark-label-printed idempotent replay → 200, no new transition.
  16. mark-handed-to-carrier happy path label_printed → handed_to_carrier.
  17. mark-handed-to-carrier wrong state → 409.
  18. mark-handed-to-carrier idempotent replay → 200, no new transition.
  19. cancel-shipment pre-handover → voided.
  20. cancel-shipment after handed_to_carrier → 409.
  21. cancel-shipment idempotent replay on voided → 200, no new transition.
  22. Missing API key → 401 when settings.api_key is set.
  23. Empty actor → 422.
  24. Actor starting auto: / system: → 422.
  25. Rejected execution emits EV_CARRIER_EXECUTE_REJECTED.
  26. Successful execution emits the relevant carrier EV constant.
  27. Read-only carrier route tests still pass unchanged (covered by
      running them in the same suite — pinned by source-grep here too).
  28. Read-only carrier-proposal route tests still pass unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_actions as rca
from app.core import timeline as tl
from app.core.config import settings
from app.core.security import require_api_key
from app.services.carrier import carrier_proposal_builder as pb
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.base import CARRIER_DHL


_ROUTE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_actions.py"
)
_MAIN_FILE = (
    Path(__file__).resolve().parents[1] / "app" / "main.py"
)
_READ_ROUTES_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier.py"
)
_PROPOSAL_ROUTES_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_proposals.py"
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
    """TestClient with isolated carrier DB + label store + outputs root.

    The route resolves storage paths from settings.storage_root. We
    monkey-patch that to tmp_path so each test runs against a clean
    DB and label store.
    """
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    csdb.init_db(tmp_path / "carrier_shipments.db")

    app = FastAPI()
    app.include_router(rca.router)
    # Override require_api_key so most tests run without auth headers.
    # The auth-positive test re-installs the real dependency.
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    """Like ``client`` but the real require_api_key is wired up."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "test-api-key", raising=False)
    csdb.init_db(tmp_path / "carrier_shipments.db")
    app = FastAPI()
    app.include_router(rca.router)
    return TestClient(app, raise_server_exceptions=True)


def _shipment_request_payload(batch_id: str = "B-A-1", reference: str = "R-1"):
    return {
        "batch_id":  batch_id,
        "ship_from": {
            "name": "Estrella", "company": "Estrella",
            "street_1": "ul. Marszalkowska 1", "city": "Warsaw",
            "postal_code": "00-001", "country": "PL",
        },
        "ship_to": {
            "name": "John Doe", "street_1": "123 Main St",
            "city": "New York", "postal_code": "10001", "country": "US",
        },
        "packages": [{
            "weight_kg": 0.25, "length_cm": 15.0,
            "width_cm": 10.0, "height_cm": 5.0,
            "declared_value": 999.0, "declared_currency": "USD",
            "description": "Diamond pendant",
        }],
        "service_code": "EXPRESS_WORLDWIDE",
        "reference":    reference,
    }


def _create_shipment_via_route(client, batch_id="B-A-CREATED", reference="R-1"):
    """Run a full create-shipment execute and return the response body."""
    payload = _shipment_request_payload(batch_id, reference)
    proposal = pb.build_create_shipment_proposal(batch_id)
    body = {
        "batch_id":    batch_id,
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-x",
        "reason":      "test-create",
    }
    r = client.post("/api/v1/carrier/actions/create-shipment/execute", json=body)
    return r


# ── 1. Router uses require_api_key dependency ──────────────────────────────

def test_router_has_api_key_dependency():
    deps = rca.router.dependencies
    assert any(
        getattr(d, "dependency", None) is require_api_key for d in deps
    ), (
        "carrier-actions router must mount Depends(require_api_key) at the "
        "router level (mirrors routes_action_proposals.py)."
    )


def test_router_prefix_and_tags():
    assert rca.router.prefix == "/api/v1/carrier/actions"
    assert "carrier" in rca.router.tags


# ── 2+3. Only POST decorators, no other write or GET verbs ─────────────────

def test_route_file_only_has_post_decorators(route_src):
    decorators = re.findall(
        r"@router\.(get|post|put|patch|delete)\b", route_src,
    )
    assert decorators, "no @router.* decorators found in route file"
    for verb in decorators:
        assert verb == "post", (
            f"non-POST verb @router.{verb} found in "
            f"routes_carrier_actions.py — DL-D5 is POST-only."
        )


@pytest.mark.parametrize("verb", ["get", "put", "patch", "delete"])
def test_no_other_decorators(route_src, verb):
    pattern = re.compile(rf"@router\.{verb}\b")
    assert not pattern.search(route_src), (
        f"@router.{verb} found in routes_carrier_actions.py."
    )


# ── 4. main.py mount ───────────────────────────────────────────────────────

def test_main_imports_carrier_actions_router(main_src):
    assert (
        "from .api.routes_carrier_actions import router as carrier_actions_router"
    ) in main_src


def test_main_includes_carrier_actions_router(main_src):
    assert "app.include_router(carrier_actions_router)" in main_src


# ── 5. No adapter import ───────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "from ..services.carrier.adapters.base",
    "from .services.carrier.adapters.base",
    "import CarrierAdapter",
    "from ..services.carrier.adapters import",
    "from .services.carrier.adapters import",
])
def test_route_file_does_not_import_adapter_base(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_actions.py contains {forbidden!r}; the route "
        f"layer must not couple to the adapter base directly."
    )


def test_route_file_does_not_import_dhl_stub_at_module_scope(route_src):
    """The stub may be referenced inside a local factory function but
    not at module scope. Source-grep checks for top-of-file
    ``from … import DHLExpressStubAdapter`` patterns."""
    # Module-scope imports start at column 0. Local factory imports
    # are indented. Reject only column-0 occurrences.
    lines = route_src.splitlines()
    for line in lines:
        # A column-zero import that mentions the stub is forbidden.
        if line.startswith("from ") or line.startswith("import "):
            assert "DHLExpressStubAdapter" not in line, (
                f"module-scope import of DHLExpressStubAdapter found: {line!r}"
            )
            assert "dhl_express_stub" not in line, (
                f"module-scope import of dhl_express_stub found: {line!r}"
            )


# ── 6. No outbound HTTP imports ────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_route_file_no_http_clients(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_actions.py contains {forbidden!r}; all HTTP "
        f"goes through the adapter (which is the stub in this phase)."
    )


# ── 7. No live-DHL env flag ────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "CARRIER_DHL_LIVE",
    "DHL_LIVE",
    "os.environ",
    "os.getenv",
    "getenv(",
])
def test_route_file_no_live_dhl_env(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_actions.py contains {forbidden!r} — DL-D5 "
        f"must not read any live-DHL env flag; that's DL-F."
    )


# ── 8. proposal_write_lock used by every handler ───────────────────────────

def test_route_file_uses_proposal_write_lock(route_src):
    # At least one import of the lock helper.
    assert "proposal_write_lock" in route_src, (
        "routes_carrier_actions.py must import and use proposal_write_lock"
    )
    # The lock must be acquired at least once for each of the four
    # actions. Counting `with proposal_write_lock(` covers the
    # create_shipment route plus the shared per-shipment executor.
    n = len(re.findall(r"with\s+proposal_write_lock\(", route_src))
    assert n >= 2, (
        f"expected proposal_write_lock used in at least 2 critical "
        f"sections (create + shared executor); found {n}"
    )


# ── 9. Routes call CarrierCoordinator, not DB writers ─────────────────────

def test_route_file_calls_coordinator(route_src):
    assert "CarrierCoordinator" in route_src, (
        "routes_carrier_actions.py must reference CarrierCoordinator"
    )


@pytest.mark.parametrize("forbidden", [
    "csdb.upsert_shipment",
    "csdb.record_transition",
    "upsert_shipment(",
    "record_transition(",
])
def test_route_file_no_direct_db_writes(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_actions.py contains {forbidden!r}; writes "
        f"must go through CarrierCoordinator only."
    )


# ── 10. create-shipment happy path ─────────────────────────────────────────

def test_create_shipment_happy_path(client, tmp_path):
    r = _create_shipment_via_route(client, batch_id="B-CREATE-OK")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    assert body["idempotent_replay"] is False
    assert body["error"] is None
    assert body["code"] is None

    shipment = body["result"]["shipment"]
    assert shipment["state"] == cse.LABEL_CREATED
    assert shipment["carrier"] == CARRIER_DHL
    assert shipment["awb"].startswith("DHLSTUB")
    assert shipment["batch_id"] == "B-CREATE-OK"

    # Label file persisted on disk
    sha = body["result"]["label_sha256"]
    assert sha
    label_path = tmp_path / "carrier_labels" / "_attachments"
    matches = list(label_path.glob(f"{sha}*"))
    assert len(matches) == 1
    assert matches[0].read_bytes().startswith(b"%PDF")

    # Manifest exists
    manifest_path = Path(body["result"]["manifest_path"])
    assert manifest_path.is_file()

    # Two transitions recorded
    transitions = csdb.get_transitions(shipment["id"])
    moves = [(t["from_state"], t["to_state"]) for t in transitions]
    assert moves == [
        (cse.PRE_AWB,    cse.AWB_ISSUED),
        (cse.AWB_ISSUED, cse.LABEL_CREATED),
    ]


# ── 11. create-shipment stale proposal_id ─────────────────────────────────

def test_create_shipment_stale_proposal_id(client):
    payload = _shipment_request_payload("B-STALE", "R-S")
    body = {
        "batch_id":    "B-STALE",
        "request":     payload,
        "proposal_id": "carrier-create_shipment-deadbeefdeadbeef",
        "actor":       "operator-x",
    }
    r = client.post("/api/v1/carrier/actions/create-shipment/execute", json=body)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "stale_proposal"


# ── 12. create-shipment duplicate active shipment ─────────────────────────

def test_create_shipment_duplicate_active(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="DUP-1",
        state=cse.LABEL_CREATED, batch_id="B-DUP",
    )
    payload = _shipment_request_payload("B-DUP", "R-DUP")
    proposal = pb.build_create_shipment_proposal(
        "B-DUP", existing_shipments=csdb.get_by_batch("B-DUP"),
    )
    body = {
        "batch_id":    "B-DUP",
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-x",
    }
    r = client.post("/api/v1/carrier/actions/create-shipment/execute", json=body)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "active_shipment_exists"


# ── 13/14/15. mark-label-printed flow ─────────────────────────────────────

def test_mark_label_printed_happy_path(client):
    create_r = _create_shipment_via_route(client, batch_id="B-MLP-HP")
    awb = create_r.json()["result"]["shipment"]["awb"]

    row = csdb.get_by_awb(CARRIER_DHL, awb)
    proposal = pb.build_mark_label_printed_proposal(row)

    r = client.post(
        "/api/v1/carrier/actions/mark-label-printed/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    assert body["idempotent_replay"] is False
    assert body["result"]["shipment"]["state"] == cse.LABEL_PRINTED


def test_mark_label_printed_wrong_state(client):
    """Skip create_shipment; manually plant a row at AWB_ISSUED to
    make mark-label-printed structurally invalid."""
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="WRONG-STATE",
        state=cse.AWB_ISSUED, batch_id="B-WRONG",
    )
    row = csdb.get_by_awb(CARRIER_DHL, "WRONG-STATE")
    proposal = pb.build_mark_label_printed_proposal(row)
    r = client.post(
        "/api/v1/carrier/actions/mark-label-printed/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         "WRONG-STATE",
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_state"


def test_mark_label_printed_idempotent_replay(client):
    create_r = _create_shipment_via_route(client, batch_id="B-MLP-REPLAY")
    awb = create_r.json()["result"]["shipment"]["awb"]
    shipment_id = create_r.json()["result"]["shipment"]["id"]

    # Mark printed once.
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    proposal = pb.build_mark_label_printed_proposal(row)
    r1 = client.post(
        "/api/v1/carrier/actions/mark-label-printed/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r1.status_code == 200

    transitions_before = csdb.get_transitions(shipment_id)

    # Replay against the now-label_printed row. The body's
    # proposal_id references the previous label_created state, but
    # the route should short-circuit on idempotent replay BEFORE the
    # id-mismatch check fires.
    r2 = client.post(
        "/api/v1/carrier/actions/mark-label-printed/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["executed"] is False
    assert body["idempotent_replay"] is True

    transitions_after = csdb.get_transitions(shipment_id)
    assert transitions_before == transitions_after


# ── 16/17/18. mark-handed-to-carrier flow ─────────────────────────────────

def test_mark_handed_happy_path(client):
    create_r = _create_shipment_via_route(client, batch_id="B-MH-HP")
    awb = create_r.json()["result"]["shipment"]["awb"]

    # First go to LABEL_PRINTED.
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    p1 = pb.build_mark_label_printed_proposal(row)
    r1 = client.post(
        "/api/v1/carrier/actions/mark-label-printed/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": p1["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r1.status_code == 200

    row = csdb.get_by_awb(CARRIER_DHL, awb)
    p2 = pb.build_mark_handed_to_carrier_proposal(row)
    r2 = client.post(
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": p2["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["executed"] is True
    assert body["result"]["shipment"]["state"] == cse.HANDED_TO_CARRIER


def test_mark_handed_wrong_state(client):
    """Plant a label_created row; mark-handed should reject."""
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="HANDED-WRONG",
        state=cse.LABEL_CREATED, batch_id="B-HW",
    )
    row = csdb.get_by_awb(CARRIER_DHL, "HANDED-WRONG")
    proposal = pb.build_mark_handed_to_carrier_proposal(row)
    r = client.post(
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         "HANDED-WRONG",
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_state"


def test_mark_handed_idempotent_replay(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="HANDED-REPLAY",
        state=cse.HANDED_TO_CARRIER, batch_id="B-HR",
    )
    row = csdb.get_by_awb(CARRIER_DHL, "HANDED-REPLAY")
    transitions_before = csdb.get_transitions(row["id"])
    r = client.post(
        "/api/v1/carrier/actions/mark-handed-to-carrier/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         "HANDED-REPLAY",
            "proposal_id": "carrier-mark_handed_to_carrier-anything",
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["executed"] is False
    assert body["idempotent_replay"] is True
    assert csdb.get_transitions(row["id"]) == transitions_before


# ── 19/20/21. cancel-shipment flow ────────────────────────────────────────

def test_cancel_pre_handover_voids(client):
    create_r = _create_shipment_via_route(client, batch_id="B-CAN-OK")
    awb = create_r.json()["result"]["shipment"]["awb"]

    row = csdb.get_by_awb(CARRIER_DHL, awb)
    proposal = pb.build_cancel_shipment_proposal(row)
    r = client.post(
        "/api/v1/carrier/actions/cancel-shipment/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         awb,
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
            "reason":      "operator-cancel",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    assert body["result"]["shipment"]["state"] == cse.VOIDED


def test_cancel_after_handed_returns_409(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="POST-HAND",
        state=cse.HANDED_TO_CARRIER, batch_id="B-PH",
    )
    row = csdb.get_by_awb(CARRIER_DHL, "POST-HAND")
    proposal = pb.build_cancel_shipment_proposal(row)
    r = client.post(
        "/api/v1/carrier/actions/cancel-shipment/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         "POST-HAND",
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "invalid_state"


def test_cancel_idempotent_replay_on_voided(client):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="ALREADY-VOID",
        state=cse.VOIDED, batch_id="B-AV",
    )
    row = csdb.get_by_awb(CARRIER_DHL, "ALREADY-VOID")
    transitions_before = csdb.get_transitions(row["id"])
    r = client.post(
        "/api/v1/carrier/actions/cancel-shipment/execute",
        json={
            "carrier":     CARRIER_DHL,
            "awb":         "ALREADY-VOID",
            "proposal_id": "carrier-cancel_shipment-anything",
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["executed"] is False
    assert body["idempotent_replay"] is True
    assert csdb.get_transitions(row["id"]) == transitions_before


# ── 22. Auth — missing API key returns 401 ────────────────────────────────

def test_missing_api_key_returns_401(auth_client):
    r = auth_client.post(
        "/api/v1/carrier/actions/create-shipment/execute",
        json={
            "batch_id":    "B-AUTH",
            "request":     _shipment_request_payload("B-AUTH"),
            "proposal_id": "x",
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 401


def test_valid_api_key_passes_dependency(auth_client):
    proposal = pb.build_create_shipment_proposal("B-AUTH-OK")
    r = auth_client.post(
        "/api/v1/carrier/actions/create-shipment/execute",
        headers={"X-API-Key": "test-api-key"},
        json={
            "batch_id":    "B-AUTH-OK",
            "request":     _shipment_request_payload("B-AUTH-OK"),
            "proposal_id": proposal["proposal_id"],
            "actor":       "operator-x",
        },
    )
    assert r.status_code == 200


# ── 23. Empty actor returns 422 ───────────────────────────────────────────

def test_empty_actor_returns_422(client):
    proposal = pb.build_create_shipment_proposal("B-NO-ACTOR")
    r = client.post(
        "/api/v1/carrier/actions/create-shipment/execute",
        json={
            "batch_id":    "B-NO-ACTOR",
            "request":     _shipment_request_payload("B-NO-ACTOR"),
            "proposal_id": proposal["proposal_id"],
            "actor":       "",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "actor_required"


# ── 24. Auto-actor sentinel rejection ─────────────────────────────────────

@pytest.mark.parametrize("actor", [
    "auto:queue", "auto:approver",
    "system:path_a_auto_queue", "system:scheduler",
    "AUTO:upper", "System:Camel",  # case-insensitive
])
def test_auto_actor_sentinel_rejected(client, actor):
    proposal = pb.build_create_shipment_proposal("B-SENT")
    r = client.post(
        "/api/v1/carrier/actions/create-shipment/execute",
        json={
            "batch_id":    "B-SENT",
            "request":     _shipment_request_payload("B-SENT"),
            "proposal_id": proposal["proposal_id"],
            "actor":       actor,
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "auto_actor_sentinel_reserved"


# ── 25. Rejection emits EV_CARRIER_EXECUTE_REJECTED ───────────────────────

def test_route_file_uses_execute_rejected_constant(route_src):
    assert "EV_CARRIER_EXECUTE_REJECTED" in route_src, (
        "rejected execution paths must reference "
        "tl.EV_CARRIER_EXECUTE_REJECTED so the timeline names the event."
    )


# ── 26. Successful execution emits each action's EV constant ─────────────

@pytest.mark.parametrize("ev", [
    "EV_CARRIER_SHIPMENT_CREATED",
    "EV_CARRIER_LABEL_PRINTED",
    "EV_CARRIER_HANDED_TO_CARRIER",
    "EV_CARRIER_SHIPMENT_VOIDED",
])
def test_route_file_uses_each_carrier_ev_constant(route_src, ev):
    assert ev in route_src, (
        f"route file does not reference {ev}; successful executions "
        f"must emit the matching timeline event."
    )


def test_timeline_module_exports_all_five_carrier_constants():
    for ev in [
        "EV_CARRIER_SHIPMENT_CREATED",
        "EV_CARRIER_LABEL_PRINTED",
        "EV_CARRIER_HANDED_TO_CARRIER",
        "EV_CARRIER_SHIPMENT_VOIDED",
        "EV_CARRIER_EXECUTE_REJECTED",
    ]:
        assert hasattr(tl, ev), f"timeline.py missing constant {ev}"


# ── 27/28. Read-only carrier route files unchanged ────────────────────────

def test_read_only_route_file_has_no_post(route_src=None):
    src = _READ_ROUTES_FILE.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src), (
        "DL-D5 must not introduce any POST decorator into "
        "routes_carrier.py — that file is read-only."
    )


def test_read_only_proposal_route_file_has_no_post():
    src = _PROPOSAL_ROUTES_FILE.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src), (
        "DL-D5 must not introduce any POST decorator into "
        "routes_carrier_proposals.py — that file is read-only."
    )

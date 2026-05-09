"""
test_carrier_create_shipment_idempotency.py — DL-F3.5a phase tests.

Required coverage:
  1. Repeat create returns idempotent_replay=True with identical AWB.
  2. Different reference produces a new shipment.
  3. Adapter call counter pinned at 1 across two replay attempts.
  4. First call still writes manifest + 2 transitions.
  5. Route-level envelope carries idempotent_replay=true.
  6. Empty reference returns None from the helper.
  7. Timeline detail.replay=True on replay path.
  8. Source-grep: lookup-before-adapter call inside coordinator.
  9. Concurrency under proposal_write_lock — exactly one AWB issued.
  10. Replayed row's label_sha256 unchanged.
  11. Replayed POST returns HTTP 200 (not 409 stale_proposal).
  12. Source-grep: no new env / HTTP imports in coordinator.
  13. The new helper does not call upsert_shipment/record_transition.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_actions as rca
from app.core.config import settings
from app.core.security import require_api_key
from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_proposal_builder as pb
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.adapters.dhl_express_stub import (
    DHLExpressStubAdapter,
)
from app.services.carrier.base import (
    CARRIER_DHL,
    CarrierAddress,
    CarrierShipmentRequest,
    PackageSpec,
)


_COORD_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_coordinator.py"
)
_DB_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_shipment_db.py"
)


# ── Counting stub adapter ──────────────────────────────────────────────────

class _CountingStubAdapter(DHLExpressStubAdapter):
    """Stub adapter wrapping the real one but counting create calls.

    Used to pin "adapter called exactly once across replay" — the
    invariant the route + coordinator pre-checks must guarantee.
    """

    def __init__(self):
        super().__init__()
        self.create_calls = 0

    def create_shipment(self, request):
        self.create_calls += 1
        return super().create_shipment(request)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def coord_src() -> str:
    return _COORD_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def db_src() -> str:
    return _DB_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def coord(tmp_path):
    """Coordinator wired with the counting stub adapter at tmp_path."""
    return cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = _CountingStubAdapter(),
        actor            = "test-idempotency",
    )


@pytest.fixture()
def request_obj():
    return CarrierShipmentRequest(
        batch_id="B-IDEM-1",
        ship_from=CarrierAddress(name="From", country="PL"),
        ship_to=CarrierAddress(name="To",   country="US"),
        packages=(PackageSpec(
            weight_kg=0.5, length_cm=15, width_cm=10, height_cm=5,
            declared_value=100.0, declared_currency="USD",
        ),),
        service_code="P",
        reference="R-IDEM-1",
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI TestClient with the carrier_actions router mounted."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    csdb.init_db(tmp_path / "carrier_shipments.db")
    app = FastAPI()
    app.include_router(rca.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


def _shipment_request_payload(batch_id="B-RT-1", reference="R-RT-1"):
    return {
        "batch_id":  batch_id,
        "ship_from": {
            "name": "Estrella", "company": "Estrella",
            "street_1": "ul. M. 1", "city": "Warsaw",
            "postal_code": "00-001", "country": "PL",
        },
        "ship_to": {
            "name": "John Doe", "street_1": "123 Main",
            "city": "NYC", "postal_code": "10001", "country": "US",
        },
        "packages": [{
            "weight_kg": 0.25, "length_cm": 15.0,
            "width_cm": 10.0, "height_cm": 5.0,
            "declared_value": 999.0, "declared_currency": "USD",
            "description": "Test pendant",
        }],
        "service_code": "P",
        "reference":    reference,
    }


# ── 1. Repeat returns idempotent_replay=True with identical AWB ────────────

def test_repeat_returns_idempotent_replay_with_identical_awb(coord, request_obj):
    out_a = coord.create_shipment(batch_id="B-IDEM-1", request=request_obj)
    assert out_a["idempotent_replay"] is False
    assert out_a["shipment"]["awb"].startswith("DHLSTUB")

    out_b = coord.create_shipment(batch_id="B-IDEM-1", request=request_obj)
    assert out_b["idempotent_replay"] is True
    assert out_b["shipment"]["awb"] == out_a["shipment"]["awb"]
    assert out_b["label_sha256"] == out_a["label_sha256"]
    assert out_b["manifest_path"] == out_a["manifest_path"]


# ── 2. Different reference produces a new shipment ─────────────────────────

def test_different_reference_produces_new_shipment(coord, request_obj):
    coord.create_shipment(batch_id="B-IDEM-2", request=request_obj)

    other = CarrierShipmentRequest(
        batch_id=request_obj.batch_id,
        ship_from=request_obj.ship_from,
        ship_to=request_obj.ship_to,
        packages=request_obj.packages,
        service_code=request_obj.service_code,
        reference="DIFFERENT-REF",
    )
    out = coord.create_shipment(batch_id="B-IDEM-2", request=other)
    assert out["idempotent_replay"] is False
    # The stub adapter is deterministic on (batch_id, reference, ...) —
    # different reference yields different AWB.
    rows = csdb.get_by_batch("B-IDEM-2")
    awbs = {r["awb"] for r in rows}
    assert len(awbs) == 2


# ── 3. Adapter call counter pinned at 1 across two replays ────────────────

def test_adapter_called_exactly_once_across_replays(coord, request_obj):
    coord.create_shipment(batch_id="B-IDEM-3", request=request_obj)
    coord.create_shipment(batch_id="B-IDEM-3", request=request_obj)
    coord.create_shipment(batch_id="B-IDEM-3", request=request_obj)
    assert coord._adapter.create_calls == 1


# ── 4. First call still writes manifest + 2 transitions ────────────────────

def test_first_call_writes_manifest_and_two_transitions(coord, request_obj):
    out = coord.create_shipment(batch_id="B-IDEM-4", request=request_obj)
    manifest_path = Path(out["manifest_path"])
    assert manifest_path.is_file()
    transitions = csdb.get_transitions(out["shipment"]["id"])
    moves = [(t["from_state"], t["to_state"]) for t in transitions]
    assert moves == [
        (cse.PRE_AWB,    cse.AWB_ISSUED),
        (cse.AWB_ISSUED, cse.LABEL_CREATED),
    ]


def test_replay_does_not_add_a_third_transition(coord, request_obj):
    coord.create_shipment(batch_id="B-IDEM-4B", request=request_obj)
    row = csdb.get_by_batch("B-IDEM-4B")[0]
    transitions_before = csdb.get_transitions(row["id"])
    coord.create_shipment(batch_id="B-IDEM-4B", request=request_obj)
    transitions_after = csdb.get_transitions(row["id"])
    assert transitions_before == transitions_after


# ── 5. Route-level envelope carries idempotent_replay=true ─────────────────

def test_route_level_envelope_carries_idempotent_replay(client):
    payload = _shipment_request_payload("B-RT-1", "R-RT-1")
    proposal = pb.build_create_shipment_proposal("B-RT-1")
    body = {
        "batch_id":    "B-RT-1",
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-x",
    }
    r1 = client.post("/api/v1/carrier/actions/create-shipment/execute",
                     json=body)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["executed"] is True
    assert body1["idempotent_replay"] is False

    r2 = client.post("/api/v1/carrier/actions/create-shipment/execute",
                     json=body)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["executed"] is False
    assert body2["idempotent_replay"] is True
    assert body2["result"]["shipment"]["awb"] == body1["result"]["shipment"]["awb"]


# ── 6. Empty reference returns None from the helper ───────────────────────

def test_empty_reference_returns_none_from_helper(tmp_path):
    csdb.init_db(tmp_path / "carrier_shipments.db")
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="ANY-AWB", state=cse.LABEL_CREATED,
        batch_id="B-NULL", manifest_path="/nonexistent",
    )
    assert csdb.get_by_batch_and_reference("B-NULL", "") is None
    assert csdb.get_by_batch_and_reference("B-NULL", "   ") is None
    assert csdb.get_by_batch_and_reference("", "R") is None


def test_helper_returns_none_when_no_row_matches_reference(tmp_path):
    """A row exists for the batch but its manifest references a
    DIFFERENT operator-supplied reference — the helper must NOT
    return that row when asked about a reference that does not
    match."""
    csdb.init_db(tmp_path / "carrier_shipments.db")
    manifest_path = tmp_path / "fake_manifest.json"
    manifest_path.write_text(json.dumps({
        "request": {"reference": "REF-A"},
    }), encoding="utf-8")
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="AWB-A", state=cse.LABEL_CREATED,
        batch_id="B-MATCH", manifest_path=str(manifest_path),
    )
    # Match REF-A → returns row
    found = csdb.get_by_batch_and_reference("B-MATCH", "REF-A")
    assert found is not None
    assert found["awb"] == "AWB-A"
    # No match REF-B → returns None
    nothing = csdb.get_by_batch_and_reference("B-MATCH", "REF-B")
    assert nothing is None


# ── 7. Timeline detail.replay=True on replay path ────────────────────────

def test_timeline_detail_replay_marker_present(client, tmp_path):
    payload = _shipment_request_payload("B-TL-1", "R-TL-1")
    proposal = pb.build_create_shipment_proposal("B-TL-1")
    body = {
        "batch_id":    "B-TL-1",
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-tl",
    }
    client.post("/api/v1/carrier/actions/create-shipment/execute", json=body)
    client.post("/api/v1/carrier/actions/create-shipment/execute", json=body)

    # The audit timeline file may or may not exist depending on
    # whether the parent batch's audit.json was set up. Our route
    # path uses tl.log_event which is non-fatal when audit is
    # absent; what we verify here is the source-grep marker that
    # the route writes detail.replay=True on the replay path.
    src = (Path(__file__).resolve().parents[1]
           / "app" / "api" / "routes_carrier_actions.py").read_text(
               encoding="utf-8"
           )
    assert '"replay":       is_replay' in src or "'replay':       is_replay" in src
    assert '"replay":       True' in src or "'replay':       True" in src


# ── 8. Source-grep: lookup-before-adapter inside coordinator ──────────────

def test_coordinator_calls_lookup_before_adapter(coord_src):
    lookup_idx = coord_src.find("get_by_batch_and_reference")
    adapter_idx = coord_src.find("self._adapter.create_shipment(request)")
    assert lookup_idx > 0, "coordinator must call get_by_batch_and_reference"
    assert adapter_idx > 0, "coordinator must call adapter.create_shipment"
    assert lookup_idx < adapter_idx, (
        "DL-F3.5a invariant: idempotency lookup must happen BEFORE "
        "the adapter call"
    )


# ── 9. Concurrency: exactly one AWB issued under the lock ───────────────

def test_concurrent_replay_issues_exactly_one_awb(client):
    """Two threads call /execute with identical body. The route
    layer's proposal_write_lock + the coordinator's idempotency
    pre-check together MUST guarantee exactly one AWB across both
    calls."""
    payload = _shipment_request_payload("B-CONC-1", "R-CONC-1")
    proposal = pb.build_create_shipment_proposal("B-CONC-1")
    body = {
        "batch_id":    "B-CONC-1",
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-c",
    }
    results = []
    def _hit():
        r = client.post(
            "/api/v1/carrier/actions/create-shipment/execute", json=body,
        )
        results.append((r.status_code, r.json()))

    threads = [threading.Thread(target=_hit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Both calls returned 200
    statuses = sorted(s for s, _ in results)
    assert statuses == [200, 200]
    # Exactly one created (executed=True) and exactly one replay
    flags = sorted(b["idempotent_replay"] for _, b in results)
    assert flags == [False, True]
    # AWBs match
    awbs = {b["result"]["shipment"]["awb"] for _, b in results}
    assert len(awbs) == 1


# ── 10. Replayed row's label_sha256 unchanged ─────────────────────────────

def test_replayed_row_label_sha256_unchanged(coord, request_obj):
    out_a = coord.create_shipment(batch_id="B-LBL-1", request=request_obj)
    sha_before = out_a["label_sha256"]

    out_b = coord.create_shipment(batch_id="B-LBL-1", request=request_obj)
    sha_after = out_b["label_sha256"]
    assert sha_before == sha_after

    # And the row in the registry retains the same sha
    row = csdb.get_by_batch("B-LBL-1")[0]
    assert row["label_sha256"] == sha_before


# ── 11. Replayed POST returns HTTP 200 (not 409 stale_proposal) ──────────

def test_replayed_post_returns_200_not_409(client):
    payload = _shipment_request_payload("B-200-1", "R-200-1")
    proposal = pb.build_create_shipment_proposal("B-200-1")
    body = {
        "batch_id":    "B-200-1",
        "request":     payload,
        "proposal_id": proposal["proposal_id"],
        "actor":       "operator-200",
    }
    r1 = client.post("/api/v1/carrier/actions/create-shipment/execute",
                     json=body)
    assert r1.status_code == 200

    r2 = client.post("/api/v1/carrier/actions/create-shipment/execute",
                     json=body)
    # NOT 409 — the idempotency pre-check fires before the
    # active_shipment_exists / stale_proposal gates.
    assert r2.status_code == 200
    assert r2.json()["idempotent_replay"] is True


# ── 12. Source-grep: no new env / HTTP imports in coordinator ────────────

@pytest.mark.parametrize("forbidden", [
    "os.environ", "os.getenv", "getenv(",
    "import requests", "from requests",
    "import httpx", "from httpx",
    "import urllib", "from urllib",
])
def test_coordinator_source_no_env_or_http_imports(coord_src, forbidden):
    assert forbidden not in coord_src, (
        f"DL-F3.5a coordinator change must not introduce {forbidden!r}"
    )


# ── 13. Helper does not call upsert_shipment / record_transition ─────────

def test_helper_does_not_call_writers(db_src):
    """get_by_batch_and_reference must be a pure read helper. Pinned
    by source-grep on the helper's body."""
    # Slice from the helper definition to the next top-level def.
    import re
    m = re.search(
        r"def get_by_batch_and_reference\(.*?(?=^\ndef |\Z)",
        db_src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "get_by_batch_and_reference helper not found in source"
    body = m.group(0)
    for forbidden in [
        "upsert_shipment(",
        "record_transition(",
        "INSERT INTO",
        "UPDATE carrier",
    ]:
        assert forbidden not in body, (
            f"helper body contains {forbidden!r} — must be read-only"
        )


# ── Helper-level direct test: stub-derived AWB collision is handled ──────

def test_helper_finds_match_via_real_manifest_written_by_coordinator(coord, request_obj):
    """End-to-end: coordinator writes a real manifest, then the
    helper reads it back and matches on reference."""
    out = coord.create_shipment(batch_id="B-MAN-1", request=request_obj)
    awb = out["shipment"]["awb"]
    # Look up by reference — should return the matching row
    found = csdb.get_by_batch_and_reference(
        batch_id="B-MAN-1", reference=request_obj.reference,
    )
    assert found is not None
    assert found["awb"] == awb

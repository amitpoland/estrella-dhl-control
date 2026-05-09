"""
test_carrier_coordinator.py — DL-D1 coordinator skeleton tests.

Required coverage:
  1. create_shipment with DHLExpressStubAdapter creates a DB row.
  2. create_shipment stores the label attachment under the
     content-addressed store.
  3. create_shipment writes a manifest with request/response metadata.
  4. create_shipment records two transitions (pre_awb → awb_issued,
     awb_issued → label_created).
  5. cancel before handover transitions to voided.
  6. cancel after handed_to_carrier is rejected with the named
     "void after handover" rule.
  7. mark_label_printed requires state ``label_created``.
  8. mark_handed_to_carrier requires state ``label_printed``.
  9. Out-of-sequence transitions raise ValueError.
  10. Coordinator source does not import FastAPI.
  11. Coordinator source does not import routes_action_proposals.
  12. Coordinator source does not read os.environ / os.getenv.
  13. Coordinator source does not instantiate DHLExpressStubAdapter
      globally (no ``DHLExpressStubAdapter(`` literal in the source).

Plus a small set of safety tests for adapter validation, idempotent
DB row state on re-create, and the "no global adapter singleton" rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.carrier import base as cb
from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_label_store as cls
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.adapters.dhl_express_stub import DHLExpressStubAdapter


_COORD_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_coordinator.py"
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def coord(tmp_path) -> cc.CarrierCoordinator:
    """A coordinator wired to tmp_path with the DHL stub adapter."""
    return cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = DHLExpressStubAdapter(),
        actor            = "test-operator",
    )


@pytest.fixture()
def shipment_request() -> cb.CarrierShipmentRequest:
    addr_from = cb.CarrierAddress(
        name="Estrella Jewels", company="Estrella Jewels",
        street_1="ul. Marszalkowska 1", city="Warsaw",
        postal_code="00-001", country="PL",
    )
    addr_to = cb.CarrierAddress(
        name="John Doe", street_1="123 Main St",
        city="New York", postal_code="10001", country="US",
    )
    pkg = cb.PackageSpec(
        weight_kg=0.25, length_cm=15.0, width_cm=10.0, height_cm=5.0,
        declared_value=999.0, declared_currency="USD",
    )
    return cb.CarrierShipmentRequest(
        batch_id="BATCH-DL-D-001",
        ship_from=addr_from, ship_to=addr_to,
        packages=(pkg,),
        service_code="EXPRESS_WORLDWIDE",
        reference="OPERATOR-REF-1",
    )


@pytest.fixture(scope="module")
def coord_src() -> str:
    return _COORD_FILE.read_text(encoding="utf-8")


# ── 1-4. create_shipment ───────────────────────────────────────────────────

def test_create_shipment_creates_db_row(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-001", request=shipment_request,
    )
    assert out["shipment"]["state"] == cse.LABEL_CREATED
    assert out["shipment"]["carrier"] == cb.CARRIER_DHL
    assert out["shipment"]["awb"].startswith("DHLSTUB")
    assert out["shipment"]["batch_id"] == "BATCH-DL-D-001"
    # And we can look it up
    fetched = csdb.get_by_awb(cb.CARRIER_DHL, out["shipment"]["awb"])
    assert fetched is not None
    assert fetched["id"] == out["shipment"]["id"]


def test_create_shipment_stores_label_attachment(coord, tmp_path, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-002", request=shipment_request,
    )
    sha = out["label_sha256"]
    # The attachment exists on disk under the content-addressed dir
    attach_path = cls.get_attachment_path(sha)
    assert attach_path is not None
    assert attach_path.is_file()
    # And the bytes start with PDF magic (the stub returns PDF)
    assert attach_path.read_bytes().startswith(b"%PDF")
    # And the registry row links to the same sha
    assert out["shipment"]["label_sha256"] == sha


def test_create_shipment_writes_manifest(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-003", request=shipment_request,
        reason="initial-create",
    )
    awb = out["shipment"]["awb"]
    manifest_path = Path(out["manifest_path"])
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["awb"] == awb
    assert payload["carrier"] == cb.CARRIER_DHL
    assert payload["state"] == cse.LABEL_CREATED
    assert payload["batch_id"] == "BATCH-DL-D-003"
    assert payload["label_sha256"] == out["label_sha256"]
    assert payload["actor"] == "test-operator"
    assert payload["reason"] == "initial-create"
    assert payload["request"]["service_code"] == "EXPRESS_WORLDWIDE"
    assert payload["request"]["package_count"] == 1
    assert payload["request"]["ship_to_country"] == "US"
    # And the response section carries the stub marker so audit trail
    # makes it obvious which adapter served this.
    assert payload["response"]["raw"]["stub"] is True


def test_create_shipment_records_two_transitions(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-004", request=shipment_request,
    )
    transitions = csdb.get_transitions(out["shipment"]["id"])
    moves = [(t["from_state"], t["to_state"]) for t in transitions]
    assert moves == [
        (cse.PRE_AWB,    cse.AWB_ISSUED),
        (cse.AWB_ISSUED, cse.LABEL_CREATED),
    ]
    # All transitions carry the actor
    assert all(t["actor"] == "test-operator" for t in transitions)


def test_create_shipment_appends_message_to_manifest_dir(
    coord, tmp_path, shipment_request,
):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-005", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    msgs_dir = tmp_path / "carrier_labels" / "_by_awb" / awb / "messages"
    files = list(msgs_dir.glob("*.json"))
    assert len(files) >= 1


# ── 5. cancel before handover ───────────────────────────────────────────────

def test_cancel_before_handover_transitions_to_voided(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-006", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    rsp = coord.cancel_shipment(
        carrier=cb.CARRIER_DHL, awb=awb, reason="operator-cancel",
    )
    assert rsp["shipment"]["state"] == cse.VOIDED
    assert rsp["adapter_accepted"] is True
    transitions = csdb.get_transitions(out["shipment"]["id"])
    last = transitions[-1]
    assert last["from_state"] == cse.LABEL_CREATED
    assert last["to_state"]   == cse.VOIDED
    assert last["reason"]     == "operator-cancel"


def test_cancel_at_label_printed_also_voids(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-007", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb=awb)
    rsp = coord.cancel_shipment(carrier=cb.CARRIER_DHL, awb=awb)
    assert rsp["shipment"]["state"] == cse.VOIDED


# ── 6. cancel after handed_to_carrier ──────────────────────────────────────

def test_cancel_after_handed_to_carrier_is_rejected(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-008", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb=awb)
    coord.mark_handed_to_carrier(carrier=cb.CARRIER_DHL, awb=awb)
    with pytest.raises(ValueError) as exc:
        coord.cancel_shipment(carrier=cb.CARRIER_DHL, awb=awb)
    msg = str(exc.value).lower()
    assert "void" in msg
    assert "before handover" in msg or "illegal" in msg


def test_cancel_unknown_shipment_raises(coord):
    with pytest.raises(cc.CarrierCoordinatorError):
        coord.cancel_shipment(carrier=cb.CARRIER_DHL, awb="DOES-NOT-EXIST")


# ── 7-8. mark_label_printed / mark_handed_to_carrier preconditions ─────────

def test_mark_label_printed_requires_label_created(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-009", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    # Happy path
    rsp = coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb=awb)
    assert rsp["shipment"]["state"] == cse.LABEL_PRINTED
    # Calling again from label_printed must fail
    with pytest.raises(ValueError) as exc:
        coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb=awb)
    assert "label_created" in str(exc.value)


def test_mark_handed_to_carrier_requires_label_printed(coord, shipment_request):
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-010", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    # Skip label_printed → must reject
    with pytest.raises(ValueError) as exc:
        coord.mark_handed_to_carrier(carrier=cb.CARRIER_DHL, awb=awb)
    assert "label_printed" in str(exc.value)
    # Now do it the legal way
    coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb=awb)
    rsp = coord.mark_handed_to_carrier(carrier=cb.CARRIER_DHL, awb=awb)
    assert rsp["shipment"]["state"] == cse.HANDED_TO_CARRIER


def test_mark_label_printed_unknown_shipment_raises(coord):
    with pytest.raises(cc.CarrierCoordinatorError):
        coord.mark_label_printed(carrier=cb.CARRIER_DHL, awb="UNKNOWN")


def test_mark_handed_to_carrier_unknown_shipment_raises(coord):
    with pytest.raises(cc.CarrierCoordinatorError):
        coord.mark_handed_to_carrier(carrier=cb.CARRIER_DHL, awb="UNKNOWN")


# ── 9. Out-of-sequence transitions ─────────────────────────────────────────

def test_cannot_skip_states(coord, shipment_request):
    """label_created cannot jump straight to handed_to_carrier."""
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-011", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    with pytest.raises(ValueError):
        coord.mark_handed_to_carrier(carrier=cb.CARRIER_DHL, awb=awb)


def test_cancel_from_voided_terminal_rejected(coord, shipment_request):
    """Cancelling an already-voided shipment hits the terminal-state guard."""
    out = coord.create_shipment(
        batch_id="BATCH-DL-D-012", request=shipment_request,
    )
    awb = out["shipment"]["awb"]
    coord.cancel_shipment(carrier=cb.CARRIER_DHL, awb=awb)
    with pytest.raises(ValueError):
        coord.cancel_shipment(carrier=cb.CARRIER_DHL, awb=awb)


# ── 10-13. Source-grep guards ──────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi",
    "from fastapi",
    "import flask",
    "from flask",
])
def test_coordinator_does_not_import_web_framework(coord_src, forbidden):
    assert forbidden not in coord_src, (
        f"carrier_coordinator.py contains {forbidden!r} — coordinator "
        f"is service-layer only, no web framework imports."
    )


@pytest.mark.parametrize("forbidden", [
    "routes_action_proposals",
    "from ..api.routes_action_proposals",
    "from .api.routes_action_proposals",
])
def test_coordinator_does_not_import_action_proposals(coord_src, forbidden):
    assert forbidden not in coord_src, (
        f"carrier_coordinator.py contains {forbidden!r} — DL-D1 must "
        f"not couple to the proposal layer; that's DL-D2."
    )


@pytest.mark.parametrize("forbidden", [
    "os.environ",
    "os.getenv",
    "getenv(",
])
def test_coordinator_does_not_read_env(coord_src, forbidden):
    assert forbidden not in coord_src, (
        f"carrier_coordinator.py contains {forbidden!r} — coordinator "
        f"must accept all dependencies via the constructor."
    )


def test_coordinator_does_not_instantiate_dhl_stub_globally(coord_src):
    # The coordinator references the Protocol via type-hint only.
    # Any literal `DHLExpressStubAdapter(` (a constructor call) means
    # the coordinator is creating its own adapter — that breaks the
    # injection contract.
    assert "DHLExpressStubAdapter(" not in coord_src, (
        "carrier_coordinator.py instantiates DHLExpressStubAdapter "
        "directly — adapters MUST be injected via the constructor."
    )
    # The class name shouldn't even be referenced; the type hint uses
    # the Protocol, not the concrete stub.
    assert "DHLExpressStubAdapter" not in coord_src, (
        "carrier_coordinator.py references DHLExpressStubAdapter — "
        "the coordinator is adapter-agnostic."
    )


def test_coordinator_does_not_import_requests_or_httpx(coord_src):
    for forbidden in ["import requests", "from requests",
                      "import httpx", "from httpx"]:
        assert forbidden not in coord_src, (
            f"carrier_coordinator.py contains {forbidden!r} — all "
            f"network I/O must go through the injected adapter."
        )


# ── Constructor validation ─────────────────────────────────────────────────

def test_coordinator_rejects_none_adapter(tmp_path):
    with pytest.raises(ValueError):
        cc.CarrierCoordinator(
            db_path=tmp_path / "x.db",
            label_store_root=tmp_path / "labels",
            adapter=None,  # type: ignore[arg-type]
        )


def test_coordinator_rejects_non_protocol_adapter(tmp_path):
    class _Bad:
        carrier = "dhl"
        # missing all five methods
    with pytest.raises(TypeError):
        cc.CarrierCoordinator(
            db_path=tmp_path / "x.db",
            label_store_root=tmp_path / "labels",
            adapter=_Bad(),  # type: ignore[arg-type]
        )


def test_create_shipment_rejects_blank_batch_id(coord, shipment_request):
    with pytest.raises(ValueError):
        coord.create_shipment(batch_id="", request=shipment_request)


def test_create_shipment_rejects_wrong_request_type(coord):
    with pytest.raises(TypeError):
        coord.create_shipment(
            batch_id="X",
            request={"batch_id": "X"},  # type: ignore[arg-type]
        )

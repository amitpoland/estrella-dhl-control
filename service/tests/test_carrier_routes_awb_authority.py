"""POST /api/v1/carrier/{batch_id}/shipment — ONE recipient authority.

The shipped address is always derived as

    outbound proforma client (client_ref)
      -> client_contractor_id -> Customer Master -> canonical delivery

There is no feature flag, no raw-address fallback and no batch-age escape
hatch.  The operator-typed modal address is display data: it is accepted for
backward compatibility and never consulted.  A customer that cannot be
resolved unambiguously fails closed with 422 (Lesson R: customer unmatched is
a TRUE blocker).

Real SQLite fixtures, synthetic parties. No live MyDHL / wFirma / email writes.
"""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import router as actions_router
from app.auth.dependencies import get_current_user
from app.core.security import require_api_key
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb

BATCH = "SHIPMENT_1234567890_2026-08_abcdef01"

# Two commercial customers on ONE import batch -> batch-level party
# resolution is AMBIGUOUS; only the client scope disambiguates.
CLIENT_A, CID_A = "Alpha Gems Ltd", "700000222"
CLIENT_B, CID_B = "DG Handels GmbH", "900000111"

# What the operator might type into the modal. It must never ship.
TYPED_ADDRESS = {
    "name": "TYPED IN THE MODAL",
    "street": "Typed Street 1",
    "city": "Typedville",
    "postal_code": "00-000",
    "country": "PL",
}


@pytest.fixture(autouse=True)
def _incoterm_resolved_for_shipment_posts(monkeypatch):
    """Supply a resolved Incoterm so INCOTERM_UNSET does not mask address tests."""
    monkeypatch.setattr(
        "app.api.routes_carrier_actions._resolve_booking_incoterm",
        lambda **kwargs: {"value": "DAP", "source": "customer_master"},
    )


def _logistics_user():
    # POST /shipment is role-gated (require_role -> get_current_user, PR #1002).
    return {"id": 1, "email": "t@test.internal", "role": "logistics",
            "is_active": True, "is_approved": True}


# ── Settings patch helper ─────────────────────────────────────────────────────
#
# Every settings patch in this module MUST go through _patched_settings().
#
# `patch("app.core.config.settings")` returns a MagicMock, so every attribute
# the test does not set auto-creates as a *truthy* child mock. Production
# resolves the carrier storage root as
#
#     settings.carrier_storage_root or (settings.storage_root / "carrier")
#
# so leaving `carrier_storage_root` unset makes the `or` short-circuit onto a
# mock, and the resulting MagicMock repr is later opened as a RELATIVE path —
# creating a file named `<MagicMock name='settings.carrier_storage_root.
# __truediv__()' id='...'>` in the pytest CWD, i.e. inside `service/`.
#
# Setting `storage_root` alone (as this module used to) does NOT help: the `or`
# never reaches it. Both attributes must be real. See issue #1089.

_MOCK_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="pz-carrier-awb-"))


@contextmanager
def _patched_settings(**overrides):
    """Patch `app.core.config.settings` with the storage attributes pinned real."""
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.carrier_storage_root = None
        mock_settings.storage_root = _MOCK_STORAGE_ROOT
        for name, value in overrides.items():
            setattr(mock_settings, name, value)
        yield mock_settings


# ── Fixtures: a real two-client batch ────────────────────────────────────────


def _register(document_type: str, contractor_id: str, file_hash: str) -> None:
    ddb.register_document(
        batch_id=BATCH,
        document_type=document_type,
        file_name=f"{document_type}-{file_hash}.pdf",
        file_hash=file_hash,
        supplier_contractor_id="",
        client_contractor_id=contractor_id,
    )


def _draft(storage: Path, client_name: str, contractor_id: str) -> None:
    pf = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        pf,
        batch_id=BATCH,
        client_name=client_name,
        currency="EUR",
        exchange_rate=None,
        source_lines_json="[]",
    )
    with sqlite3.connect(str(pf)) as con:
        con.execute(
            "UPDATE proforma_drafts SET client_contractor_id=? "
            "WHERE batch_id=? AND client_name=?",
            (contractor_id, BATCH, client_name),
        )


def _customer_master(root: Path, rows) -> None:
    with sqlite3.connect(str(root / "customer_master.sqlite")) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS customer_master ("
            "bill_to_contractor_id TEXT PRIMARY KEY, bill_to_name TEXT, "
            "bill_to_street TEXT, bill_to_city TEXT, bill_to_postal_code TEXT, "
            "country TEXT, ship_to_name TEXT, ship_to_street TEXT, "
            "ship_to_city TEXT, ship_to_zip TEXT, ship_to_country TEXT, "
            "ship_to_phone TEXT, ship_to_email TEXT, ship_to_person TEXT, "
            "ship_to_use_alternate INTEGER)"
        )
        con.executemany(
            "INSERT OR REPLACE INTO customer_master (bill_to_contractor_id, "
            "bill_to_name, bill_to_street, bill_to_city, bill_to_postal_code, "
            "country) VALUES (?,?,?,?,?,?)",
            rows,
        )


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir()
    ddb.init_document_db(root / "documents.db")
    _register("sales_packing_list", CID_A, "spl-a")
    _register("sales_invoice", CID_B, "si-b")
    _customer_master(root, [
        (CID_A, CLIENT_A, "12 Marine Drive", "Mumbai", "400020", "IN"),
        (CID_B, CLIENT_B, "5 Bahnhofstrasse", "Pforzheim", "75172", "DE"),
    ])
    _draft(root, CLIENT_A, CID_A)
    _draft(root, CLIENT_B, CID_B)
    return root


@contextmanager
def _booking_client(storage: Path, **settings_overrides):
    """Yield (TestClient, captured_requests) with the carrier coordinator mocked."""
    captured: list = []

    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = _logistics_user

    def _mock_coordinator():
        coord = MagicMock()

        def _create(request, **_kwargs):
            captured.append(request)
            result = MagicMock()
            result.idempotency_key = "test-key-123"
            result.mode.value = "shadow"
            result.state.value = "completed"
            result.tracking_ref = "TEST123456789"
            result.simulated = True
            return result

        coord.create_shipment = _create
        return coord

    with _patched_settings(storage_root=storage, **settings_overrides):
        from app.api.routes_carrier_actions import _get_coordinator
        app.dependency_overrides[_get_coordinator] = _mock_coordinator
        yield TestClient(app), captured


@pytest.fixture()
def booked(storage: Path):
    with _booking_client(storage) as ctx:
        yield ctx


def _post(client, *, client_ref=None, recipient_address=TYPED_ADDRESS):
    body = {
        "shipper_account": "TEST_ACC",
        "recipient_address": recipient_address,
        "declared_value": 10733.21,
        "currency": "EUR",
        "weight_kg": 1.0,
        "dimensions": {"length_cm": 10, "width_cm": 10, "height_cm": 10},
    }
    if client_ref is not None:
        body["client_ref"] = client_ref
    return client.post(f"/api/v1/carrier/{BATCH}/shipment", json=body)


# ── The client-scoped Customer Master is the only recipient authority ────────


def test_client_scoped_booking_resolves_that_clients_contractor(booked):
    client, captured = booked
    resp = _post(client, client_ref=CLIENT_A)

    assert resp.status_code == 200, resp.text
    addr = captured[-1].recipient_address
    assert addr["company"] == CLIENT_A          # CM name -> carrier company
    assert addr["street"] == "12 Marine Drive"
    assert addr["city"] == "Mumbai"
    assert addr["country_code"] == "IN"


def test_second_client_on_the_same_batch_resolves_its_own_contractor(booked):
    """Scope must not leak: the other client's own Customer Master record ships."""
    client, captured = booked
    resp = _post(client, client_ref=CLIENT_B)

    assert resp.status_code == 200, resp.text
    addr = captured[-1].recipient_address
    assert addr["company"] == CLIENT_B
    assert addr["city"] == "Pforzheim"
    assert addr["country_code"] == "DE"


def test_multiparty_batch_without_client_scope_fails_closed(booked):
    """No client scope on an ambiguous batch -> 422, never a batch-level guess."""
    client, captured = booked
    resp = _post(client, client_ref=None)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "CUSTOMER_NOT_FOUND"
    assert detail["batch_id"] == BATCH
    assert captured == []          # nothing reached the carrier


def test_unknown_client_ref_fails_closed(booked):
    client, captured = booked
    resp = _post(client, client_ref="Client With No Draft")

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "CUSTOMER_NOT_FOUND"
    assert captured == []


# ── The typed modal address is never an authority ────────────────────────────


def test_typed_recipient_address_is_ignored(booked):
    """The operator can type anything; Customer Master is what ships."""
    client, captured = booked
    resp = _post(client, client_ref=CLIENT_A, recipient_address=TYPED_ADDRESS)

    assert resp.status_code == 200, resp.text
    shipped = captured[-1].recipient_address
    assert TYPED_ADDRESS["name"] not in shipped.values()
    assert shipped["city"] != TYPED_ADDRESS["city"]
    assert shipped["street"] != TYPED_ADDRESS["street"]
    assert shipped["company"] == CLIENT_A


def test_omitted_recipient_address_still_books(booked):
    """Display-only field: callers may stop sending it entirely."""
    client, captured = booked
    resp = client.post(
        f"/api/v1/carrier/{BATCH}/shipment",
        json={
            "shipper_account": "TEST_ACC",
            "client_ref": CLIENT_A,
            "declared_value": 10733.21,
            "currency": "EUR",
            "weight_kg": 1.0,
            "dimensions": {"length_cm": 10, "width_cm": 10, "height_cm": 10},
        },
    )

    assert resp.status_code == 200, resp.text
    assert captured[-1].recipient_address["company"] == CLIENT_A


def test_incomplete_customer_master_never_degrades_to_typed_address(
    booked, storage: Path
):
    """A complete typed address does not rescue an incomplete master record."""
    client, captured = booked
    with sqlite3.connect(str(storage / "customer_master.sqlite")) as con:
        con.execute(
            "UPDATE customer_master SET bill_to_street='', bill_to_city='' "
            "WHERE bill_to_contractor_id=?", (CID_A,))

    resp = _post(client, client_ref=CLIENT_A, recipient_address=TYPED_ADDRESS)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "ADDRESS_INCOMPLETE"
    assert "complete the customer address" in detail["guidance"]
    assert captured == []


def test_source_metadata_is_not_forwarded_to_the_carrier(booked):
    client, captured = booked
    assert _post(client, client_ref=CLIENT_A).status_code == 200
    assert "source" not in captured[-1].recipient_address


# ── No environment switch may re-open the raw path ───────────────────────────


@pytest.mark.parametrize("flag_value", [False, True])
def test_no_environment_flag_can_switch_recipient_authority(storage: Path, flag_value):
    """The retired flag, set either way, changes nothing about what ships."""
    with _booking_client(storage,
                         awb_address_authority_enabled=flag_value) as (client, captured):
        resp = _post(client, client_ref=CLIENT_A)

        assert resp.status_code == 200, resp.text
        assert captured[-1].recipient_address["company"] == CLIENT_A
        assert captured[-1].recipient_address["city"] == "Mumbai"


def test_settings_exposes_no_awb_address_authority_flag():
    """The rollout flag is gone from the settings model, not merely defaulted."""
    from app.core.config import Settings

    assert "awb_address_authority_enabled" not in Settings.model_fields


def test_route_source_has_no_flag_branch_around_the_derivation():
    """Source pin: re-introducing a config branch here must fail the suite."""
    src = (Path(__file__).parent.parent / "app" / "api"
           / "routes_carrier_actions.py").read_text(encoding="utf-8")

    assert "awb_address_authority_enabled" not in src
    assert "derive_awb_address_authority_with_fallback" not in src
    assert "carrier_address = body.recipient_address" not in src

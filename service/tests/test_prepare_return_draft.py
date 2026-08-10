"""Slice A — Prepare Return DRAFT lifecycle.

Proves:
1. Zero external DHL writes (create_shipment never called)
2. Outbound parent row unchanged
3. Parent linkage persisted
4. Live Create Return blocked (422 / capability pending)
5. Email / E.164 / country normalization basics
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
    compute_return_idempotency_key,
)
from app.services.carrier.persistence import shipment_db
from app.services.carrier.return_draft_service import (
    assert_create_return_blocked,
    prepare_return_draft,
    patch_return_draft,
    get_return_draft_api,
)
from app.services.contact_normalize import normalize_email, normalize_phone_e164
from app.services.country_lookup import country_display_name, normalize_country_alpha2
from app.services.carrier.models.shipment import ShipmentRequest


def _carrier_db(tmp_path: Path) -> Path:
    path = tmp_path / "carrier_shipments.db"
    shipment_db.init_db(path)
    return path


def _seed_outbound(db: Path, *, batch_id: str = "BATCH_R1", awb: str = "1234567890") -> dict:
    key = "outbound-key-001"
    shipment_db.insert_shipment(
        db,
        ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
            simulated=True,
        ),
        batch_id,
        client_ref="Acme GmbH",
    )
    shipment_db.update_state(
        db,
        key,
        ShipmentState.COMPLETE,
        tracking_ref=awb,
        mode=ShipmentMode.SHADOW,
        simulated=True,
    )
    shipment_db.update_shipment_fields(
        db,
        key,
        weight_kg=1.5,
        declared_value=100.0,
        currency="EUR",
    )
    return shipment_db.get_shipment(db, key)


# ── Normalizers ───────────────────────────────────────────────────────────────


def test_normalize_email_basics():
    assert normalize_email("  Alice@Example.COM ") == ("alice@example.com", None)
    assert normalize_email("") == (None, None)
    assert normalize_email("not-an-email")[1] == "email_invalid"


def test_normalize_phone_e164_and_ambiguous():
    ok, err, review = normalize_phone_e164("+48123456789")
    assert ok == "+48123456789" and err is None and review is False

    ok2, err2, review2 = normalize_phone_e164("123456789", country_code="PL")
    assert ok2 == "+48123456789" and err2 is None and review2 is False

    # Ambiguous national — never invent dial code
    ok3, err3, review3 = normalize_phone_e164("123456789")
    assert ok3 is None and err3 == "phone_needs_country" and review3 is True


def test_country_alpha2_display_derived():
    assert normalize_country_alpha2("de") == "DE"
    assert country_display_name("DE") == "Germany"
    assert country_display_name("ZZ") == "ZZ"  # honest unknown


def test_return_idempotency_distinct_from_outbound():
    req = ShipmentRequest(
        batch_id="B1",
        shipper_account="acct",
        recipient_address={},
        declared_value=1.0,
        currency="EUR",
        weight_kg=1.0,
        dimensions={},
        client_ref="C1",
    )
    out_key = compute_idempotency_key(req)
    ret_key = compute_return_idempotency_key(
        batch_id="B1", parent_tracking_ref="AWB1", client_ref="C1"
    )
    assert out_key != ret_key
    assert ret_key == compute_return_idempotency_key(
        batch_id="B1", parent_tracking_ref="AWB1", client_ref="C1"
    )


# ── Prepare Return ────────────────────────────────────────────────────────────


def test_prepare_return_zero_dhl_and_parent_unchanged(tmp_path, monkeypatch):
    db = _carrier_db(tmp_path)
    parent = _seed_outbound(db)
    before = dict(parent)

    # Spy: any live adapter create_shipment must NOT run.
    fake_adapter = MagicMock()
    fake_adapter.create_shipment = MagicMock(
        side_effect=AssertionError("DHL create_shipment must not be called")
    )
    monkeypatch.setattr(
        "app.services.carrier.adapters.live.DhlExpressLiveAdapter.create_shipment",
        fake_adapter.create_shipment,
        raising=False,
    )

    storage = tmp_path / "storage"
    storage.mkdir()

    result = prepare_return_draft(
        storage_root=storage,
        carrier_db_path=db,
        batch_id="BATCH_R1",
        parent_tracking_ref="1234567890",
        client_ref="Acme GmbH",
        return_reason="customer_return",
        contact_email="Ops@Acme.DE",
        contact_phone="+491701234567",
        operator="tester",
    )

    assert result["dhl_create_called"] is False
    assert result["created"] is True
    assert result["parent_unchanged"] is True
    draft = result["draft"]
    assert draft["shipment_direction"] == "return"
    assert draft["return_intent_status"] == "prepared"
    assert draft["parent_tracking_ref"] == "1234567890"
    assert draft["parent_idempotency_key"] == before["idempotency_key"]
    assert draft["create_return_available"] is False
    assert draft["dhl_return_capability"] == "pending"
    assert draft["tracking_ref"] is None
    assert draft["contact_email"] == "ops@acme.de"
    assert draft["contact_phone_e164"] == "+491701234567"
    assert fake_adapter.create_shipment.call_count == 0

    after = shipment_db.get_shipment(db, before["idempotency_key"])
    assert after["tracking_ref"] == before["tracking_ref"]
    assert after["weight_kg"] == before["weight_kg"]
    assert after["declared_value"] == before["declared_value"]
    assert after["state"] == before["state"]
    assert (after.get("shipment_direction") or "outbound") != "return"


def test_prepare_return_idempotent_replay(tmp_path):
    db = _carrier_db(tmp_path)
    _seed_outbound(db)
    storage = tmp_path / "storage"
    storage.mkdir()
    kwargs = dict(
        storage_root=storage,
        carrier_db_path=db,
        batch_id="BATCH_R1",
        parent_tracking_ref="1234567890",
        client_ref="Acme GmbH",
    )
    first = prepare_return_draft(**kwargs)
    second = prepare_return_draft(**kwargs)
    assert first["created"] is True
    assert second["replayed"] is True
    assert first["draft"]["idempotency_key"] == second["draft"]["idempotency_key"]
    # Only one return row
    assert shipment_db.get_return_draft(
        db, batch_id="BATCH_R1", parent_tracking_ref="1234567890"
    )


def test_return_draft_excluded_from_outbound_resolution(tmp_path):
    db = _carrier_db(tmp_path)
    _seed_outbound(db)
    storage = tmp_path / "storage"
    storage.mkdir()
    prepare_return_draft(
        storage_root=storage,
        carrier_db_path=db,
        batch_id="BATCH_R1",
        parent_tracking_ref="1234567890",
        client_ref="Acme GmbH",
    )
    outbound = shipment_db.get_shipment_for_draft(
        db, "BATCH_R1", "Acme GmbH", allow_single_client_fallback=True
    )
    assert outbound is not None
    assert outbound.get("tracking_ref") == "1234567890"
    assert (outbound.get("shipment_direction") or "").lower() != "return"


def test_patch_return_draft_editable(tmp_path):
    db = _carrier_db(tmp_path)
    _seed_outbound(db)
    storage = tmp_path / "storage"
    storage.mkdir()
    prepared = prepare_return_draft(
        storage_root=storage,
        carrier_db_path=db,
        batch_id="BATCH_R1",
        parent_tracking_ref="1234567890",
        client_ref="Acme GmbH",
    )
    key = prepared["draft"]["idempotency_key"]
    updated = patch_return_draft(
        db,
        batch_id="BATCH_R1",
        idempotency_key=key,
        return_reason="damaged",
        pieces=2,
        weight_kg=2.25,
    )
    assert updated["return_reason"] == "damaged"
    assert updated["pieces"] == 2
    assert updated["weight_kg"] == 2.25
    assert updated["create_return_available"] is False


def test_create_return_blocked():
    status, payload = assert_create_return_blocked()
    assert status == 422
    assert payload["code"] == "DHL_RETURN_CAPABILITY_PENDING"
    assert payload["create_return_available"] is False


def test_create_return_route_blocked():
    """HTTP path: Live Create remains unavailable (isolated app)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_carrier_actions import router as actions_router
    from app.auth.dependencies import get_current_user
    from app.core.security import require_api_key

    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "email": "t@test.internal", "role": "logistics",
        "is_active": True, "is_approved": True,
    }
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/v1/carrier/BATCH_R1/return/create", json={})
    assert r.status_code == 422
    body = r.json()
    assert body.get("code") == "DHL_RETURN_CAPABILITY_PENDING"
    assert body.get("create_return_available") is False


def test_prepare_return_route_no_dhl(tmp_path, monkeypatch):
    """HTTP prepare path never invokes live adapter create_shipment."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_carrier_actions import (
        router as actions_router,
        _get_shipment_db_path,
    )
    from app.auth.dependencies import get_current_user
    from app.core.security import require_api_key
    from unittest.mock import patch

    db = _carrier_db(tmp_path)
    _seed_outbound(db)
    storage = tmp_path / "storage"
    storage.mkdir()

    create_spy = MagicMock(
        side_effect=AssertionError("DHL create_shipment must not be called")
    )
    monkeypatch.setattr(
        "app.services.carrier.adapters.live.DhlExpressLiveAdapter.create_shipment",
        create_spy,
        raising=False,
    )

    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "email": "t@test.internal", "role": "logistics",
        "is_active": True, "is_approved": True,
    }
    app.dependency_overrides[_get_shipment_db_path] = lambda: db

    client = TestClient(app, raise_server_exceptions=True)
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.storage_root = storage
        mock_settings.carrier_storage_root = None
        mock_settings.dhl_express_shipper_name = "Estrella"
        mock_settings.dhl_express_shipper_address1 = "Ul. Test 1"
        mock_settings.dhl_express_shipper_city = "Warszawa"
        mock_settings.dhl_express_shipper_postal_code = "00-001"
        mock_settings.dhl_express_shipper_country_code = "PL"
        mock_settings.dhl_express_shipper_phone = "+48221234567"
        resp = client.post(
            "/api/v1/carrier/BATCH_R1/return/prepare",
            json={
                "parent_tracking_ref": "1234567890",
                "client_ref": "Acme GmbH",
                "return_reason": "test",
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["dhl_create_called"] is False
    assert data["draft"]["parent_tracking_ref"] == "1234567890"
    assert data["draft"]["create_return_available"] is False
    assert create_spy.call_count == 0

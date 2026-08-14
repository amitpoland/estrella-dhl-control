"""A2 — customer-arranged FedEx/UPS registration on existing carrier_shipments.

No FedEx/UPS/DHL network calls. No second shipment or document table.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import (
    _get_carrier_config,
    _get_shipment_db_path,
    _persist_shipment_doc,
    _shipment_doc_file,
    router as actions_router,
)
from app.auth.dependencies import get_current_user
from app.core.security import require_api_key
from app.services.carrier.coordinator import register_external_shipment
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    CarrierGateError,
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
    compute_external_idempotency_key,
    compute_idempotency_key,
)
from app.services.carrier.persistence import shipment_db


def _no_auth() -> None:
    return None


def _logistics_user() -> dict:
    return {"id": 1, "email": "t@test.internal", "role": "logistics",
            "is_active": True, "is_approved": True}


def _shadow_config() -> CarrierConfig:
    return CarrierConfig(status="shadow")


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "carrier_shipments.db"
    shipment_db.init_db(p)
    return p


def _pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


# ── coordinator: persist + isolation ──────────────────────────────────────────


def test_fedex_registration_persists_provider(db: Path):
    result = register_external_shipment(
        db, batch_id="BATCH-FX1", provider="fedex",
        tracking_ref="1234 5678 9012", client_ref="Acme", operator="amit",
    )
    assert result.mode == ShipmentMode.EXTERNAL
    assert result.state == ShipmentState.COMPLETE
    assert result.simulated is False
    assert result.tracking_ref == "123456789012"
    row = shipment_db.get_shipment(db, result.idempotency_key)
    assert row["provider"] == "FEDEX"
    assert row["tracking_ref"] == "123456789012"
    assert row["batch_id"] == "BATCH-FX1"
    assert row["client_ref"] == "Acme"
    assert row["booked_by"] == "amit"
    assert row["mode"] == "external"


def test_ups_registration_persists_provider(db: Path):
    result = register_external_shipment(
        db, batch_id="BATCH-UP1", provider="UPS",
        tracking_ref="1Z999AA10123456784", client_ref="Beta",
    )
    row = shipment_db.get_shipment(db, result.idempotency_key)
    assert row["provider"] == "UPS"
    assert row["tracking_ref"] == "1Z999AA10123456784"


def test_tracking_required(db: Path):
    with pytest.raises(CarrierGateError, match="tracking_ref is required"):
        register_external_shipment(
            db, batch_id="BATCH-X", provider="FEDEX", tracking_ref="   ",
        )


def test_dhl_rejected_from_external_path(db: Path):
    with pytest.raises(CarrierGateError, match="existing booking path"):
        register_external_shipment(
            db, batch_id="BATCH-X", provider="DHL", tracking_ref="1234567890",
        )


def test_unknown_provider_rejected(db: Path):
    with pytest.raises(CarrierGateError, match="Unknown carrier provider"):
        register_external_shipment(
            db, batch_id="BATCH-X", provider="TNT", tracking_ref="1234567890",
        )


def test_external_replay_is_idempotent(db: Path):
    kwargs = dict(
        batch_id="BATCH-IDEM", provider="FEDEX",
        tracking_ref="999988887777", client_ref="Acme", operator="first",
    )
    first = register_external_shipment(db, **kwargs)
    second = register_external_shipment(db, **{**kwargs, "operator": "second"})
    assert second.replayed is True
    assert second.idempotency_key == first.idempotency_key
    assert second.tracking_ref == first.tracking_ref
    assert second.booked_by == "first"
    with shipment_db._connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM carrier_shipments").fetchone()["n"]
    assert n == 1


def test_external_key_does_not_collide_with_dhl_booking_key():
    from app.services.carrier.models.shipment import ShipmentRequest
    req = ShipmentRequest(
        batch_id="BATCH-K", shipper_account="ACC",
        recipient_address={}, declared_value=1, currency="EUR",
        weight_kg=1, dimensions={}, client_ref="Acme",
    )
    dhl_key = compute_idempotency_key(req)
    ext_key = compute_external_idempotency_key(
        batch_id="BATCH-K", provider="FEDEX",
        tracking_ref="1234567890", client_ref="Acme",
    )
    assert dhl_key != ext_key


def test_second_outbound_for_same_draft_is_rejected(db: Path):
    register_external_shipment(
        db, batch_id="BATCH-DUP", provider="FEDEX",
        tracking_ref="111122223333", client_ref="Acme",
    )
    with pytest.raises(CarrierGateError, match="already exists"):
        register_external_shipment(
            db, batch_id="BATCH-DUP", provider="UPS",
            tracking_ref="1Z999AA10123456784", client_ref="Acme",
        )


def test_external_registration_never_calls_dhl_adapter(db: Path):
    with patch(
        "app.services.carrier.adapters.live.DhlExpressLiveAdapter.create_shipment"
    ) as live_create, patch(
        "app.services.carrier.factory.get_adapter"
    ) as get_adapter:
        register_external_shipment(
            db, batch_id="BATCH-ISO", provider="FEDEX",
            tracking_ref="555566667777",
        )
        live_create.assert_not_called()
        get_adapter.assert_not_called()


def test_legacy_mode_check_migrates_and_accepts_external(tmp_path: Path):
    """Existing DBs with CHECK(shadow, live) must accept mode=external after init_db."""
    p = tmp_path / "legacy.db"
    with sqlite3.connect(str(p)) as conn:
        conn.execute(
            """
            CREATE TABLE carrier_shipments (
                idempotency_key TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('shadow', 'live')),
                state TEXT NOT NULL CHECK(state IN ('pending', 'submitted', 'complete', 'failed')),
                error TEXT,
                simulated INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO carrier_shipments "
            "(idempotency_key, batch_id, mode, state, simulated) "
            "VALUES ('legacy-k', 'BATCH-LEG', 'shadow', 'complete', 1)"
        )
    shipment_db.init_db(p)
    result = register_external_shipment(
        p, batch_id="BATCH-NEW", provider="UPS", tracking_ref="1Z999AA10123456784",
    )
    assert result.mode == ShipmentMode.EXTERNAL
    kept = shipment_db.get_shipment(p, "legacy-k")
    assert kept is not None
    assert kept["batch_id"] == "BATCH-LEG"


# ── HTTP: route stays thin, DHL POST unchanged, GET round-trip ────────────────


@pytest.fixture()
def test_app(tmp_path: Path):
    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = _no_auth
    app.dependency_overrides[get_current_user] = _logistics_user
    app.dependency_overrides[_get_carrier_config] = _shadow_config
    dbp = tmp_path / "carrier_shipments.db"
    shipment_db.init_db(dbp)
    app.dependency_overrides[_get_shipment_db_path] = lambda: dbp
    app.state._db = dbp
    app.state._root = tmp_path
    return app


def test_http_fedex_register_and_get_round_trip(test_app, tmp_path: Path):
    client = TestClient(test_app)
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=tmp_path / "carrier"):
        post = client.post(
            "/api/v1/carrier/BATCH-HTTP/shipment/external",
            json={
                "provider": "FEDEX",
                "tracking_ref": "888877776666",
                "client_ref": "Acme",
            },
            headers={"X-Operator": "amit"},
        )
        assert post.status_code == 200, post.text
        body = post.json()
        assert body["carrier"] == "FEDEX"
        assert body["tracking_ref"] == "888877776666"
        assert body["mode"] == "external"
        assert body["state"] == "complete"
        assert body["replayed"] is False
        get = client.get(
            "/api/v1/carrier/BATCH-HTTP/shipment",
            params={"client_ref": "Acme"},
        )
        assert get.status_code == 200, get.text
        got = get.json()
        assert got["carrier"] == "FEDEX"
        assert got["tracking_ref"] == "888877776666"
        assert got["mode"] == "external"
        assert got["client_ref"] == "Acme"


def test_http_dhl_rejected(test_app):
    client = TestClient(test_app)
    resp = client.post(
        "/api/v1/carrier/BATCH-HTTP/shipment/external",
        json={"provider": "DHL", "tracking_ref": "1234567890"},
    )
    assert resp.status_code == 422
    assert "booking path" in resp.text


def test_http_unknown_provider_rejected(test_app):
    client = TestClient(test_app)
    resp = client.post(
        "/api/v1/carrier/BATCH-HTTP/shipment/external",
        json={"provider": "TNT", "tracking_ref": "1234567890"},
    )
    assert resp.status_code == 422


def test_http_blank_tracking_rejected(test_app):
    client = TestClient(test_app)
    resp = client.post(
        "/api/v1/carrier/BATCH-HTTP/shipment/external",
        json={"provider": "UPS", "tracking_ref": "  "},
    )
    assert resp.status_code == 422


def test_http_replay(test_app):
    client = TestClient(test_app)
    payload = {"provider": "UPS", "tracking_ref": "1Z999AA10123456784", "client_ref": "Acme"}
    first = client.post("/api/v1/carrier/BATCH-RP/shipment/external", json=payload)
    second = client.post("/api/v1/carrier/BATCH-RP/shipment/external", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["idempotency_key"] == first.json()["idempotency_key"]


def test_http_external_does_not_use_dhl_create_path(test_app):
    client = TestClient(test_app)
    with patch(
        "app.services.carrier.coordinator.CarrierCoordinator.create_shipment"
    ) as create:
        resp = client.post(
            "/api/v1/carrier/BATCH-NO/shipment/external",
            json={"provider": "FEDEX", "tracking_ref": "121212121212"},
        )
        assert resp.status_code == 200
        create.assert_not_called()


# ── documents: existing label store, ownership, retry ─────────────────────────


def test_external_awb_upload_linked_to_shipment(test_app, tmp_path: Path):
    client = TestClient(test_app)
    root = tmp_path / "carrier"
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=root):
        client.post(
            "/api/v1/carrier/BATCH-DOC/shipment/external",
            json={"provider": "FEDEX", "tracking_ref": "444433332222", "client_ref": "Acme"},
        )
        up = client.post(
            "/api/v1/carrier/BATCH-DOC/shipment/external/document",
            data={"tracking_ref": "444433332222", "client_ref": "Acme"},
            files={"awb_file": ("awb.pdf", _pdf(), "application/pdf")},
        )
        assert up.status_code == 200, up.text
        assert up.json()["awb_document_saved"] is True
        assert up.json()["label_download_url"]
        stored = _shipment_doc_file("label", "BATCH-DOC", "444433332222")
        assert stored is not None
        assert stored.read_bytes().startswith(b"%PDF")


def test_retry_upload_does_not_duplicate_file(test_app, tmp_path: Path):
    client = TestClient(test_app)
    root = tmp_path / "carrier"
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=root):
        client.post(
            "/api/v1/carrier/BATCH-RT/shipment/external",
            json={"provider": "UPS", "tracking_ref": "1Z999AA10123456784"},
        )
        files = {"awb_file": ("awb.pdf", _pdf(), "application/pdf")}
        data = {"tracking_ref": "1Z999AA10123456784"}
        assert client.post(
            "/api/v1/carrier/BATCH-RT/shipment/external/document", data=data, files=files,
        ).status_code == 200
        second_pdf = b"%PDF-1.4\nretry\n%%EOF\n"
        files2 = {"awb_file": ("awb.pdf", second_pdf, "application/pdf")}
        assert client.post(
            "/api/v1/carrier/BATCH-RT/shipment/external/document", data=data, files=files2,
        ).status_code == 200
        labels = list((root / "labels").glob("BATCH-RT-*.pdf"))
        assert len(labels) == 1
        assert labels[0].read_bytes() == second_pdf


def test_cross_batch_document_link_rejected(test_app, tmp_path: Path):
    client = TestClient(test_app)
    root = tmp_path / "carrier"
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=root):
        client.post(
            "/api/v1/carrier/BATCH-A1/shipment/external",
            json={"provider": "FEDEX", "tracking_ref": "777766665555"},
        )
        resp = client.post(
            "/api/v1/carrier/BATCH-B1/shipment/external/document",
            data={"tracking_ref": "777766665555"},
            files={"awb_file": ("awb.pdf", _pdf(), "application/pdf")},
        )
        assert resp.status_code in (404, 409)
        assert _shipment_doc_file("label", "BATCH-B1", "777766665555") is None


def test_dhl_row_cannot_use_external_upload(test_app, tmp_path: Path):
    dbp = test_app.state._db
    shipment_db.insert_shipment(
        dbp,
        ShipmentResult(
            idempotency_key="dhl-row-key",
            mode=ShipmentMode.SHADOW,
            state=ShipmentState.PENDING,
        ),
        "BATCH-DHL",
        "Acme",
        provider="DHL",
    )
    shipment_db.update_state(
        dbp, "dhl-row-key", ShipmentState.COMPLETE, tracking_ref="1122334455",
    )
    client = TestClient(test_app)
    root = tmp_path / "carrier"
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=root):
        resp = client.post(
            "/api/v1/carrier/BATCH-DHL/shipment/external/document",
            data={"tracking_ref": "1122334455", "client_ref": "Acme"},
            files={"awb_file": ("awb.pdf", _pdf(), "application/pdf")},
        )
    assert resp.status_code == 422


def test_persist_rejects_path_escape(tmp_path: Path):
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=tmp_path / "carrier"):
        with pytest.raises(ValueError, match="unsafe"):
            _persist_shipment_doc("label", "../etc", "passwd", _pdf())
        with pytest.raises(ValueError, match="not a PDF"):
            _persist_shipment_doc("label", "BATCH-OK", "12345678", b"not-pdf")


def test_missing_shipment_upload_rejected(test_app, tmp_path: Path):
    client = TestClient(test_app)
    root = tmp_path / "carrier"
    with patch("app.api.routes_carrier_actions._carrier_root", return_value=root):
        resp = client.post(
            "/api/v1/carrier/BATCH-NONE/shipment/external/document",
            data={"tracking_ref": "000011112222"},
            files={"awb_file": ("awb.pdf", _pdf(), "application/pdf")},
        )
    assert resp.status_code == 404


# ── UI / CMR source pins (no second modal, no DHL invention) ──────────────────


def test_ui_carrier_selector_and_forms():
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "v2" / "proforma-detail.jsx"
    ).read_text(encoding="utf-8")
    assert 'data-testid="awb-carrier-select"' in src
    assert 'data-testid="awb-dhl-form"' in src
    assert 'data-testid="awb-external-form"' in src
    assert 'data-testid="awb-field-tracking-ref"' in src
    assert 'data-testid="awb-field-awb-file"' in src
    assert "Register external shipment" in src
    assert "selectedCarrier === 'DHL'" in src
    assert "selectedCarrier === 'FEDEX'" in src
    assert "function AwbGenerateModal" in src
    assert src.count("function AwbGenerateModal") == 1
    assert "AwbFedexModal" not in src
    assert "AwbUpsModal" not in src


def test_transport_and_cmr_consume_provider_without_dhl_fallback():
    root = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
    detail = (root / "proforma-detail.jsx").read_text(encoding="utf-8")
    cmr = (root / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
    assert "outbound_awb:      ship ? (ship.tracking_ref || null) : null" in detail
    assert "name:        _transport.carrier" in detail
    assert "carrier:  _transport.linked" in detail
    assert "|| 'DHL'" not in cmr
    assert '|| "DHL"' not in cmr
    assert "if (carrier === 'FEDEX')" not in cmr
    assert "if (carrier === 'UPS')" not in cmr


def test_no_duplicate_authority_introduced():
    """A2 must not add a second shipment table, FedEx/UPS service, or CMR variant."""
    service = Path(__file__).resolve().parents[1]
    forbidden_files = [
        service / "app" / "services" / "external_shipments_db.py",
        service / "app" / "services" / "fedex_service.py",
        service / "app" / "services" / "ups_service.py",
        service / "app" / "static" / "v2" / "estrella-doc-cmr-fedex.jsx",
        service / "app" / "static" / "v2" / "estrella-doc-cmr-ups.jsx",
    ]
    for path in forbidden_files:
        assert not path.exists(), path
    models = (
        service / "app" / "services" / "carrier" / "models" / "shipment.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in models
    coord = (
        service / "app" / "services" / "carrier" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert "fedex.com" not in coord.lower()
    assert "ups.com" not in coord.lower()
    assert "express.api.dhl.com" not in coord
    assert "register_external_shipment" in coord
    assert "get_adapter" in coord  # DHL path still owns the adapter
    # The new function body must not call get_adapter / create_shipment.
    ext_fn = coord.split("def register_external_shipment(")[1].split(
        "def _complete_or_replay_external("
    )[0]
    assert "get_adapter(" not in ext_fn
    assert ".create_shipment(" not in ext_fn
    assert "adapters.live" not in ext_fn

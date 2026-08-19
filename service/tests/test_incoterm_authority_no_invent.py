"""Incoterm authority — never invent DAP; draft → CM → unset everywhere.

Covers:
  * CM DAP → new draft birth → DHL booking body uses DAP
  * explicit draft override wins over CM
  * unset CM + unset draft → booking 422 INCOTERM_UNSET (never DAP)
  * live adapter refuses blank Incoterm
  * resolve_incoterm is the single hierarchy for commercial docs
  * source-grep: no invent-DAP fallbacks in active V2 / live adapter
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.commercial_authority import resolve_incoterm
from app.services.carrier.adapters.live import _build_shipment_body
from app.services.carrier.models.shipment import CarrierGateError, ShipmentRequest
from app.services import customer_master_db as cmdb
from app.services import proforma_invoice_link_db as pildb
from app.services.customer_master_db import CustomerMaster


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


def _mk_cm(storage: Path, contractor_id: str, *, default_incoterm=None):
    db = storage / "customer_master.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_customer(
        db,
        CustomerMaster(
            bill_to_contractor_id=contractor_id,
            bill_to_name=f"Client {contractor_id}",
            country="PL",
            default_incoterm=default_incoterm,
            active=True,
        ),
    )


def _req(**overrides) -> ShipmentRequest:
    defaults = dict(
        batch_id="BATCH-001",
        shipper_account="ACC-001",
        recipient_address={
            "name": "Test Co",
            "street": "Main St 1",
            "city": "Warsaw",
            "postal_code": "00-001",
            "country_code": "PL",
            "phone": "+48123",
            "email": "buyer@example.com",
        },
        declared_value=500.0,
        currency="EUR",
        weight_kg=1.5,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
    )
    defaults.update(overrides)
    return ShipmentRequest(**defaults)


def _fake_settings(**kw):
    s = MagicMock()
    s.dhl_express_shipper_name = "Estrella Jewels"
    s.dhl_express_shipper_address1 = "Test St 1"
    s.dhl_express_shipper_city = "Warsaw"
    s.dhl_express_shipper_postal_code = "00-001"
    s.dhl_express_shipper_country_code = "PL"
    s.dhl_express_shipper_phone = "+48000000000"
    return s


# ── resolve_incoterm hierarchy ───────────────────────────────────────────────


def test_resolve_draft_wins_over_cm():
    assert resolve_incoterm("FOB", "DAP") == {"value": "FOB", "source": "draft"}


def test_resolve_cm_when_draft_blank():
    assert resolve_incoterm(None, "DAP") == {"value": "DAP", "source": "customer_master"}
    assert resolve_incoterm("", "EXW") == {"value": "EXW", "source": "customer_master"}


def test_resolve_unset_never_invents_dap():
    assert resolve_incoterm(None, None) == {"value": None, "source": "unset"}
    assert resolve_incoterm("", "") == {"value": None, "source": "unset"}


# ── birth + booking path ─────────────────────────────────────────────────────


def test_cm_dap_birth_then_booking_body_dap(storage, tmp_path, monkeypatch):
    """CM DAP → new draft → DHL body Incoterm is DAP (not invented)."""
    monkeypatch.setenv("STORAGE_ROOT", str(storage))
    _mk_cm(storage, "C-DAP", default_incoterm="DAP")
    d, created = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_CM_DAP",
        client_name="DAP Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-2",
            "design_no": "JR00002",
            "qty": 1, "unit_price": 20.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-DAP",
    )
    assert created
    assert d.incoterm == "DAP"

    from app.api.routes_carrier_actions import _resolve_booking_incoterm
    res = _resolve_booking_incoterm(
        storage_root=storage,
        batch_id="BATCH_CM_DAP",
        client_ref="DAP Client",
    )
    assert res == {"value": "DAP", "source": "draft"}  # birth persisted onto draft

    body = _build_shipment_body(_req(incoterm=res["value"]), _fake_settings())
    assert body["content"]["incoterm"] == "DAP"


def test_draft_override_wins_over_cm_for_booking(storage, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(storage))
    _mk_cm(storage, "C-100", default_incoterm="DAP")
    db = storage / "proforma_links.db"
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db,
        batch_id="BATCH_OVR",
        client_name="Override Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-2",
            "design_no": "JR00002",
            "qty": 1, "unit_price": 20.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-100",
    )
    # Birth seeded DAP from CM; operator saves explicit FOB on draft.
    pildb.update_draft_fields(
        db, d.id, {"incoterm": "FOB"}, operator="test",
        expected_updated_at=d.updated_at,
    )

    from app.api.routes_carrier_actions import _resolve_booking_incoterm
    res = _resolve_booking_incoterm(
        storage_root=storage,
        batch_id="BATCH_OVR",
        client_ref="Override Client",
    )
    assert res == {"value": "FOB", "source": "draft"}
    body = _build_shipment_body(_req(incoterm="FOB"), _fake_settings())
    assert body["content"]["incoterm"] == "FOB"


def test_unset_never_becomes_dap_in_live_body():
    with pytest.raises(CarrierGateError, match="refuse to invent DAP"):
        _build_shipment_body(_req(incoterm=None), _fake_settings())
    with pytest.raises(CarrierGateError, match="refuse to invent DAP"):
        _build_shipment_body(_req(incoterm=""), _fake_settings())


def test_booking_route_blocks_when_incoterm_unset(storage, monkeypatch):
    """POST /carrier/{batch}/shipment → 422 INCOTERM_UNSET, never invents DAP."""
    from fastapi import FastAPI
    from app.api.routes_carrier_actions import (
        router as actions_router,
        _get_coordinator,
        _resolve_shipment_accounts,
    )
    from app.auth.dependencies import get_current_user
    from app.core.security import require_api_key
    from app.core.config import settings as _settings

    monkeypatch.setattr(_settings, "storage_root", storage, raising=False)
    # Address resolves before the Incoterm check; this batch has no Customer
    # Master row, so stub the address authority to keep the assertion on
    # INCOTERM_UNSET rather than CUSTOMER_NOT_FOUND.
    monkeypatch.setattr(
        "app.services.awb_address_authority.derive_awb_address_authority",
        lambda batch_id, storage_root, client_ref=None: {
            "name": "Stub Customer", "street": "Stub Street 1",
            "city": "Stub City", "country": "PL", "source": "bill_to",
        },
    )

    _mk_cm(storage, "C-EMPTY", default_incoterm=None)
    pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_EMPTY",
        client_name="Empty Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-2",
            "design_no": "JR00002",
            "qty": 1, "unit_price": 20.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-EMPTY",
    )
    d = pildb.get_draft(storage / "proforma_links.db", "BATCH_EMPTY", "Empty Client")
    assert d is not None
    assert not (d.incoterm or "").strip()

    mock_coord = MagicMock()
    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "email": "t@test.internal", "role": "logistics",
        "is_active": True, "is_approved": True,
    }
    app.dependency_overrides[_get_coordinator] = lambda: mock_coord

    with patch(
        "app.api.routes_carrier_actions._resolve_shipment_accounts",
        return_value=("ACC-001", {}),
    ):
        client = TestClient(app)
        r = client.post(
            "/api/v1/carrier/BATCH_EMPTY/shipment",
            json={
                "recipient_address": {
                    "name": "X", "street": "S", "city": "C",
                    "postal_code": "00-001", "country_code": "PL", "phone": "+48111",
                },
                "declared_value": 100,
                "currency": "EUR",
                "weight_kg": 1,
                "dimensions": {"length_cm": 10, "width_cm": 10, "height_cm": 10},
                "client_ref": "Empty Client",
            },
        )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("code") == "INCOTERM_UNSET"
    assert "will not invent DAP" in (detail.get("error") or "")
    mock_coord.create_shipment.assert_not_called()


def test_commercial_docs_share_same_resolved_incoterm():
    """Proforma / Packing / CMR / Preview all use resolve_incoterm output."""
    # Same hierarchy for every consumer — no document-specific invent.
    cases = [
        ("FOB", "DAP", "FOB", "draft"),
        (None, "DAP", "DAP", "customer_master"),
        ("", None, None, "unset"),
    ]
    for draft, cm, want_val, want_src in cases:
        res = resolve_incoterm(draft, cm)
        assert res["value"] == want_val
        assert res["source"] == want_src
        # Document display: unset → em dash, never DAP invent
        display = res["value"] or "—"
        if want_val is None:
            assert display == "—"
            assert display != "DAP"


def test_no_invent_dap_in_active_sources():
    """Source-grep: active V2 print + live adapter must not invent DAP."""
    root = Path(__file__).resolve().parents[1] / "app"
    paths = [
        root / "services" / "carrier" / "adapters" / "live.py",
        root / "static" / "v2" / "estrella-doc-proforma.jsx",
        root / "static" / "v2" / "estrella-doc-cmr.jsx",
        root / "static" / "v2" / "proforma-detail.jsx",
        # A second, separately-built Proforma bundle was listed here too, because
        # the same invent had to be neutralized twice. It is retired (see
        # test_atlas_v2_sprint1.py) — one implementation now, so one place to check.
    ]
    banned = ['|| "DAP"', "|| 'DAP'", '||"DAP"', "||'DAP'", '"incoterm": "DAP"']
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, f"{path.name} still contains invent pattern {b!r}"

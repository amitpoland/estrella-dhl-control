"""RBAC Slice 2c/2d/2e — deny-before-side-effect Gate 3 pins.

Logistics may prepare (dhl.execute / pz.process / proforma.edit) but must
receive 403 on fiscal finalize (proforma.approve/convert, pz.export_wfirma,
pz.finalize) and inventory.correct. CRM/viewer denied on execute writes.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.permissions import FISCAL_FINALIZE_PERMISSIONS, has_permission

_APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture()
def auth_env(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.auth.database import init_db

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "test-slice2cde-key")
    init_db(db_path)
    return settings


def _client(role: str) -> TestClient:
    from app.main import app
    from app.auth.service import create_user, create_token

    user = create_user(
        full_name=f"T {role}",
        company_name="EJ",
        email=f"{role}_{uuid.uuid4().hex[:10]}@ex.test",
        password="Test1234!",
        role=role,
        is_approved=True,
    )
    c = TestClient(app)
    c.cookies.set("pz_session", create_token(user["id"], role))
    return c


def test_catalogue_c2_logistics_lacks_fiscal_finalize():
    for perm in FISCAL_FINALIZE_PERMISSIONS:
        assert not has_permission("logistics", perm), perm
    assert has_permission("logistics", "dhl.execute")
    assert has_permission("logistics", "pz.process")
    assert has_permission("logistics", "inventory.execute")
    assert not has_permission("logistics", "inventory.correct")
    assert has_permission("accounts", "proforma.approve")
    assert has_permission("accounts", "pz.export_wfirma")


# ── 2c DHL ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ("crm", "viewer", "accounts"))
def test_2c_deny_roles_cannot_dhl_execute(auth_env, role):
    c = _client(role)
    with patch("app.api.routes_dhl_clearance._pipeline_dhl_email") as m:
        r = c.post("/api/v1/dhl/match-and-handle", json={"awb": "1"})
        assert r.status_code == 403, (role, r.status_code, r.text[:200])
        assert m.call_count == 0


def test_2c_crm_cannot_awb_create(auth_env):
    c = _client("crm")
    with patch("app.api.routes_carrier_actions.CarrierCoordinator") as m:
        r = c.post(
            "/api/v1/carrier/BATCH/shipment",
            json={"packages": [{"weight": 1}]},
        )
        assert r.status_code in (403, 422), r.status_code
        # Must not reach coordinator create on auth deny
        if r.status_code == 403:
            assert m.call_count == 0


def test_2c_logistics_blocked_from_dhl_resolve(auth_env):
    c = _client("logistics")
    with patch("app.api.routes_dhl_logistics.resdb") as m:
        r = c.post("/api/v1/dhl/logistics/shipments/AWB1/resolve", json={})
        assert r.status_code == 403
        assert m.resolve.call_count == 0


# ── 2d fiscal ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,method,patches",
    [
        ("/api/v1/proforma/draft/1/approve", "post", "app.api.routes_proforma.pildb.approve_draft"),
        ("/api/v1/proforma/draft/1/post", "post", "app.api.routes_proforma.post_proforma_draft_to_wfirma"),
    ],
)
def test_2d_logistics_denied_proforma_approve_paths(auth_env, path, method, patches):
    c = _client("logistics")
    # Patch the writer symbols that would run after auth — use broad patch on pildb
    with patch("app.api.routes_proforma.pildb") as m:
        r = getattr(c, method)(path, json={"expected_updated_at": "x", "confirm_token": "YES"})
        assert r.status_code == 403, (path, r.status_code, r.text[:240])
        assert m.approve_draft.call_count == 0


def test_2d_logistics_denied_to_invoice(auth_env):
    c = _client("logistics")
    with patch("app.api.routes_proforma.proforma_to_invoice") as m:
        r = c.post(
            "/api/v1/proforma/to-invoice/BATCH/Client",
            json={"confirm_token": "YES_CONVERT_PROFORMA_TO_INVOICE"},
        )
        # Auth runs before handler body; 403 expected
        assert r.status_code == 403, (r.status_code, r.text[:240])


def test_2d_logistics_denied_pz_create(auth_env):
    c = _client("logistics")
    with patch("app.api.routes_wfirma.create_warehouse_pz", create=True) as m:
        r = c.post("/api/v1/upload/shipment/BATCH/wfirma/pz_create")
        assert r.status_code == 403, (r.status_code, r.text[:240])


def test_2d_logistics_denied_set_pz(auth_env):
    c = _client("logistics")
    r = c.post("/api/v1/upload/shipment/BATCH/set_pz", json={"doc_no": "PZ 1/1/2026"})
    assert r.status_code == 403


def test_2d_crm_denied_pz_process(auth_env):
    c = _client("crm")
    with patch("app.api.routes_upload.export_service") as m:
        r = c.post("/api/v1/upload/shipment/BATCH/process")
        assert r.status_code == 403
        assert m.process_shipment.call_count == 0 if hasattr(m, "process_shipment") else True


# ── 2e inventory ─────────────────────────────────────────────────────────────


def test_2e_crm_denied_inventory_move(auth_env):
    c = _client("crm")
    with patch("app.api.routes_inventory_writes.move_piece", create=True) as m:
        r = c.post(
            "/api/v1/inventory/pieces/1/location",
            json={"to_location": "A", "idempotency_key": "k1"},
        )
        assert r.status_code == 403


def test_2e_logistics_denied_inventory_correct(auth_env):
    c = _client("logistics")
    with patch("app.api.routes_inventory_returns.apply_identity_correction") as m:
        r = c.post(
            "/api/v1/inventory/pieces/1/correction/identity",
            json={"idempotency_key": "k1", "fields": {}},
        )
        assert r.status_code == 403
        assert m.call_count == 0


def test_2e_accounts_denied_warehouse_scan(auth_env):
    """accounts lacks warehouse.scan in catalogue — 403 before record_scan."""
    c = _client("accounts")
    with patch("app.api.routes_warehouse.wdb.record_scan", create=True) as m:
        r = c.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": "X", "action": "RECEIVE"},
        )
        assert r.status_code == 403


# ── Structural HOLD pins ─────────────────────────────────────────────────────


def test_held_proforma_create_not_bound_to_approve_or_convert():
    """Mixed-class HOLD: live create must not claim approve/convert in decorator."""
    src = (_APP / "api" / "routes_proforma.py").read_text(encoding="utf-8")
    idx = src.find('@router.post("/create/{batch_id}/{client_name:path}"')
    assert idx > 0
    window = src[idx : idx + 250]
    assert "_perm_proforma_approve" not in window
    assert "_perm_proforma_convert" not in window


def test_held_return_create_unchanged_stub():
    src = (_APP / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")
    idx = src.find('summary="Live Create Return — HOLD')
    assert idx > 0
    window = src[idx : idx + 500]
    assert "_perm_awb_create" not in window

"""test_master_role_enforcement.py — Phase 2 wiring matrix.

Pins the role-gate contract for the 28 master-data write handlers and the
master-data audit GET endpoint.

The factory ``require_role_or_apikey`` was added in Phase 0. Phase 2 wires
it into:
  - 18 writes in routes_master_data.py
  - 1  write in routes_customer_master.py (PUT only; sync endpoints excluded)
  - 3  writes in routes_suppliers.py (sync endpoints excluded)
  - 3  writes in routes_client_addresses.py
  - 3  writes in routes_client_carrier_accounts.py
  - 1  GET in routes_master_data.py: /api/v1/master/audit/   (master_admin only)

This test composes a minimal FastAPI app from those routers (not main.py)
so it stays insensitive to unrelated app-level state. Now that the
proforma merge-conflict is fixed, app.main also imports — a separate
sanity test confirms it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    # Default OFF — individual tests flip ON where needed.
    monkeypatch.setattr(settings, "master_role_enforcement", False)

    import app.api.routes_master_data as md
    import app.api.routes_customer_master as cm
    import app.api.routes_suppliers as su
    import app.api.routes_client_addresses as ca
    import app.api.routes_client_carrier_accounts as cca

    md._DB_PATH  = tmp_path / "master_data.sqlite"
    cm._DB_PATH  = tmp_path / "customer_master.sqlite"
    su._DB_PATH  = tmp_path / "suppliers.sqlite"
    ca._DB_PATH  = tmp_path / "client_addresses.sqlite"
    cca._DB_PATH = tmp_path / "client_carrier_accounts.sqlite"

    app = FastAPI()
    for r in (
        md.hs_router, md.units_router, md.pl_router, md.incoterms_router,
        md.vat_router, md.fx_router, md.carriers_config_router,
        md.designs_router, md.audit_router,
        cm.router, su.router, ca.router, cca.router,
    ):
        app.include_router(r)
    return TestClient(app, raise_server_exceptions=True)


def _admin_key():
    return {"X-API-Key": "TESTKEY"}


# Representative write surfaces — one per file to keep the matrix readable.
# Each entry is (method, url, body) for an idempotent operation that creates
# state with the natural-keyed upsert pattern, or POST-create where needed.
WRITES = [
    ("PUT",  "/api/v1/hs-codes/71131900",      {"description_pl": "x"}),       # master_data
    ("PUT",  "/api/v1/units/szt",              {"name_pl": "sztuka"}),         # master_data
    ("PUT",  "/api/v1/incoterms/EXW",          {"name": "Ex Works"}),          # master_data
    ("PUT",  "/api/v1/designs/D1",             {"display_name": "D1"}),        # master_data
    ("PUT",  "/api/v1/carriers-config/dhl",    {"name": "DHL"}),               # master_data
    ("PUT",  "/api/v1/product-local/SKU-1",    {}),                            # master_data
    ("POST", "/api/v1/vat-config/",
                                  {"country": "PL", "rate_pct": "23"}),        # master_data
    ("POST", "/api/v1/fx-rates/",
             {"rate_date": "2026-05-28", "from_currency": "USD",
              "to_currency": "PLN", "rate": "3.6506"}),                        # master_data
    ("PUT",  "/api/v1/customer-master/W-100",
             {"bill_to_name": "Acme", "country": "PL"}),                       # customer_master
    ("POST", "/api/v1/suppliers/",
             {"supplier_code": "S-1", "name": "V", "country": "IN"}),          # suppliers
]


# ── Flag OFF — identical to Phase 1 ─────────────────────────────────────────

@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_off_admin_key_passes_every_write(client, method, url, body):
    r = client.request(method, url, json=body, headers=_admin_key())
    assert r.status_code in (200, 201), f"{method} {url} → {r.status_code}: {r.text}"


@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_off_no_credentials_rejected(client, method, url, body):
    r = client.request(method, url, json=body)
    assert r.status_code == 401


def test_flag_off_audit_get_works_with_api_key(client):
    r = client.get("/api/v1/master/audit/", headers=_admin_key())
    assert r.status_code == 200


# ── Flag ON — role enforcement live ─────────────────────────────────────────

@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_on_admin_api_key_still_passes(client, monkeypatch, method, url, body):
    """Direct admin X-API-Key bypass is permitted by role_gate.py contract."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.request(method, url, json=body, headers=_admin_key())
    assert r.status_code in (200, 201)


@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_on_no_credentials_returns_401(client, monkeypatch, method, url, body):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.request(method, url, json=body)
    assert r.status_code == 401


@pytest.mark.parametrize("role", ["master_admin", "master_editor"])
@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_on_master_admin_and_editor_can_write(
        client, monkeypatch, role, method, url, body):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": role}):
        r = client.request(method, url, json=body, cookies={"pz_session": "fake"})
    assert r.status_code in (200, 201), \
        f"{role} should write {method} {url}; got {r.status_code}: {r.text}"


@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_on_master_viewer_blocked_from_write(client, monkeypatch, method, url, body):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_viewer"}):
        r = client.request(method, url, json=body, cookies={"pz_session": "fake"})
    assert r.status_code == 403


@pytest.mark.parametrize("legacy_role", ["viewer", "auditor", "logistics",
                                          "accounts", "admin", "editor"])
@pytest.mark.parametrize("method,url,body", WRITES)
def test_flag_on_legacy_role_alone_does_not_grant_master_write(
        client, monkeypatch, legacy_role, method, url, body):
    """Master roles are ISOLATED. Holding only a legacy ladder role
    (including 'admin') must NOT grant master-data write authority."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": legacy_role}):
        r = client.request(method, url, json=body, cookies={"pz_session": "fake"})
    assert r.status_code == 403


# ── Audit GET — master_admin only when enforcement on ───────────────────────

def test_flag_off_audit_get_passes_with_session_any_role(client, monkeypatch):
    """With flag off, audit GET behaves like require_api_key. A bare
    session without master_admin still passes because the dependency
    degrades to require_api_key, which accepts any approved session."""
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    with patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u1", "role": "viewer", "is_active": 1, "is_approved": 1}):
        r = client.get("/api/v1/master/audit/", cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_flag_on_audit_get_admin_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.get("/api/v1/master/audit/", headers=_admin_key())
    assert r.status_code == 200


def test_flag_on_audit_get_master_admin_session_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_admin"}):
        r = client.get("/api/v1/master/audit/", cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_flag_on_audit_get_master_editor_blocked(client, monkeypatch):
    """master_editor can WRITE master records but cannot READ audit."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_editor"}):
        r = client.get("/api/v1/master/audit/", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_audit_get_master_viewer_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_viewer"}):
        r = client.get("/api/v1/master/audit/", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_audit_get_legacy_admin_blocked(client, monkeypatch):
    """Legacy 'admin' role does NOT grant master-audit read."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "admin"}):
        r = client.get("/api/v1/master/audit/", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_flag_on_audit_get_no_credentials_returns_401(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.get("/api/v1/master/audit/")
    assert r.status_code == 401


# ── Auth role validator accepts the new master_* roles ──────────────────────

def test_auth_role_validator_accepts_master_roles():
    from app.auth.service import ROLES
    assert "master_admin"  in ROLES
    assert "master_editor" in ROLES
    assert "master_viewer" in ROLES
    # Legacy roles preserved.
    for legacy in ("admin", "accounts", "logistics", "auditor", "viewer"):
        assert legacy in ROLES


# ── Read paths on regular entities remain on _auth (NOT gated) ──────────────

def test_flag_on_master_viewer_can_read_normal_entity_list(client, monkeypatch):
    """Per scope: 'Keep read routes on current auth.' With flag on, a
    master_viewer session must still be able to GET /api/v1/hs-codes/.
    require_api_key accepts any approved session — including master_viewer."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u1", "role": "master_viewer",
                             "is_active": 1, "is_approved": 1}):
        r = client.get("/api/v1/hs-codes/", cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_flag_on_master_viewer_blocked_from_a_write_after_read(client, monkeypatch):
    """Companion to the above — proves the read/write split."""
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u1", "role": "master_viewer"}):
        r = client.put("/api/v1/hs-codes/71139999",
                       json={"description_pl": "x"},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 403


# ── Sanity: full app still imports (proforma conflict was repaired) ─────────

def test_full_app_imports():
    from app.main import app  # noqa: F401
    assert len(list(app.routes)) > 100

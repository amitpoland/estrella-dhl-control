"""
test_master_capabilities_wave7.py — EJ Dashboard Wave 7.

Pins the server-provided master capability contract: the single source of truth
the V2 UI renders instead of hardcoded "Backend pending" prose. Asserts each
domain reports its REAL capability (CRUD where it exists, honest-unavailable
where it does not) and that the required reference-only / VAT disclaimers and the
immutable-roles enum are present.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _caps(client):
    from app.core.config import settings
    r = client.get("/api/v1/master/capabilities",
                   headers={"X-API-KEY": settings.api_key or "test-key"})
    assert r.status_code == 200, r.text
    return r.json()


def test_contract_shape_and_all_domains_present():
    from app.main import app
    with TestClient(app) as c:
        body = _caps(c)
    caps = body["capabilities"]
    for d in ("hs", "units", "incoterms", "vat", "fx", "carriers",
              "box_profiles", "users", "roles"):
        assert d in caps, f"missing capability domain {d}"
    assert set(body["flags"]) == {"master_role_enforcement", "master_hard_delete_enabled"}


def test_crud_domains_are_available_with_routes():
    from app.main import app
    with TestClient(app) as c:
        caps = _caps(c)["capabilities"]
    for d in ("hs", "units", "incoterms", "vat", "fx", "carriers"):
        cap = caps[d]
        assert cap["available"] is True
        assert cap["read_route"] and cap["write_route"] and cap["delete_route"]
    # PUT (natural-key) vs POST (autoincrement) create kinds are reported correctly
    assert caps["hs"]["create_kind"] == "put"
    assert caps["vat"]["create_kind"] == "post"
    assert caps["fx"]["create_kind"] == "post"


def test_fx_is_reference_only_with_disclaimer():
    from app.main import app
    with TestClient(app) as c:
        fx = _caps(c)["capabilities"]["fx"]
    assert "reference_only" in fx["flags"]
    assert "NEVER read by the calculation engine" in fx["note"]


def test_vat_states_wfirma_codes_not_overridden():
    from app.main import app
    with TestClient(app) as c:
        vat = _caps(c)["capabilities"]["vat"]
    assert "not overridden" in vat["note"].lower() or "NOT overridden" in vat["note"]


def test_box_profiles_no_delete_but_seed():
    from app.main import app
    with TestClient(app) as c:
        bp = _caps(c)["capabilities"]["box_profiles"]
    assert bp["delete_kind"] == "none" and bp["delete_route"] is None
    assert bp["seed_route"] == "/api/v1/box-types/seed-defaults"
    assert "no_delete" in bp["flags"]


def test_users_actions_only_no_edit_delete():
    from app.main import app
    with TestClient(app) as c:
        u = _caps(c)["capabilities"]["users"]
    assert u["edit_available"] is False and u["delete_available"] is False
    assert set(u["actions"]) == {"approve", "reject", "role", "activate", "deactivate"}
    assert u["permission"] == "admin"


def test_roles_immutable_with_real_enum():
    from app.main import app
    from app.auth.service import ROLES
    with TestClient(app) as c:
        roles = _caps(c)["capabilities"]["roles"]
    assert roles["available"] is False
    assert roles["reason_unavailable"]
    # the enum is the REAL backend tuple (not the stale admin/manager/operator/viewer)
    assert roles["values"] == list(ROLES)
    assert "manager" not in roles["values"] and "operator" not in roles["values"]

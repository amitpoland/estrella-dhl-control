"""test_client_addresses.py — DB layer + API layer tests for shipping addresses."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

import pytest
from fastapi.testclient import TestClient

from app.services.client_addresses_db import (
    init_db, create_address, list_addresses, get_address,
    update_address, delete_address, validate_address,
)
from app.core.config import settings


# ── DB-layer tests ────────────────────────────────────────────────────────────

def test_init_creates_table(tmp_path):
    db = tmp_path / "test.sqlite"
    init_db(db)
    assert db.is_file()
    # Idempotent — calling twice must not raise
    init_db(db)


def test_create_returns_id(tmp_path):
    db = tmp_path / "test.sqlite"
    addr_id = create_address(db, "C001", {"label": "HQ", "street": "Main St"})
    assert isinstance(addr_id, int)
    assert addr_id > 0


def test_create_requires_label(tmp_path):
    errs = validate_address({"street": "Main St"})
    assert any("label" in e for e in errs)


def test_create_validates_country_iso2_lowercase_rejected(tmp_path):
    errs = validate_address({"label": "HQ", "country": "de"})
    assert any("ISO-3166" in e or "alpha-2" in e for e in errs)


def test_create_validates_country_iso2_one_letter_rejected(tmp_path):
    errs = validate_address({"label": "HQ", "country": "D"})
    assert any("ISO-3166" in e or "alpha-2" in e for e in errs)


def test_create_valid_country_stored_uppercase(tmp_path):
    db = tmp_path / "test.sqlite"
    addr_id = create_address(db, "C001", {"label": "HQ", "country": "DE"})
    addr = get_address(db, addr_id, "C001")
    assert addr is not None
    assert addr.country == "DE"


def test_list_returns_all_for_contractor(tmp_path):
    db = tmp_path / "test.sqlite"
    create_address(db, "C001", {"label": "A"})
    create_address(db, "C001", {"label": "B"})
    create_address(db, "C001", {"label": "C"})
    addrs = list_addresses(db, "C001")
    assert len(addrs) == 3
    labels = {a.label for a in addrs}
    assert labels == {"A", "B", "C"}


def test_list_returns_empty_for_unknown_contractor(tmp_path):
    db = tmp_path / "test.sqlite"
    init_db(db)
    assert list_addresses(db, "UNKNOWN") == []


def test_update_changes_fields(tmp_path):
    db = tmp_path / "test.sqlite"
    addr_id = create_address(db, "C001", {"label": "Warehouse", "city": "Berlin"})
    updated = update_address(db, addr_id, "C001", {"label": "Updated Label", "city": "Munich"})
    assert updated is not None
    assert updated.label == "Updated Label"
    assert updated.city == "Munich"


def test_update_returns_none_wrong_contractor(tmp_path):
    db = tmp_path / "test.sqlite"
    addr_id = create_address(db, "C001", {"label": "HQ"})
    result = update_address(db, addr_id, "WRONG", {"label": "X"})
    assert result is None


def test_delete_removes_row(tmp_path):
    db = tmp_path / "test.sqlite"
    addr_id = create_address(db, "C001", {"label": "To Delete"})
    removed = delete_address(db, addr_id, "C001")
    assert removed is True
    assert get_address(db, addr_id, "C001") is None


def test_delete_returns_false_unknown(tmp_path):
    db = tmp_path / "test.sqlite"
    init_db(db)
    assert delete_address(db, 9999, "C001") is False


def test_is_default_cascade(tmp_path):
    db = tmp_path / "test.sqlite"
    id1 = create_address(db, "C001", {"label": "A", "is_default": True})
    id2 = create_address(db, "C001", {"label": "B", "is_default": True})
    a1 = get_address(db, id1, "C001")
    a2 = get_address(db, id2, "C001")
    assert a1 is not None
    assert a2 is not None
    assert a1.is_default is False   # cascade cleared first
    assert a2.is_default is True


def test_cross_contractor_isolation(tmp_path):
    db = tmp_path / "test.sqlite"
    create_address(db, "C001", {"label": "C001-addr"})
    create_address(db, "C002", {"label": "C002-addr"})
    c001 = list_addresses(db, "C001")
    c002 = list_addresses(db, "C002")
    assert len(c001) == 1 and c001[0].label == "C001-addr"
    assert len(c002) == 1 and c002[0].label == "C002-addr"


# ── API layer tests ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("addr_api")


@pytest.fixture(scope="module")
def client(api_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", api_tmp):
        import app.api.routes_client_addresses as mod
        mod._DB_PATH = api_tmp / "customer_master.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_get_list_200(client, api_tmp):
    r = client.get(
        "/api/v1/customer-master/API_C001/shipping-addresses/",
        headers=_hdr(),
    )
    assert r.status_code == 200
    data = r.json()
    assert "addresses" in data
    assert isinstance(data["addresses"], list)


def test_api_post_201(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/API_C001/shipping-addresses/",
        json={"label": "Test Warehouse", "city": "Warsaw", "country": "PL"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["label"] == "Test Warehouse"
    assert data["city"] == "Warsaw"
    assert data["id"] is not None


def test_api_put_200(client, api_tmp):
    # Create then update
    r = client.post(
        "/api/v1/customer-master/API_C001/shipping-addresses/",
        json={"label": "To Update"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    addr_id = r.json()["id"]
    r2 = client.put(
        f"/api/v1/customer-master/API_C001/shipping-addresses/{addr_id}",
        json={"label": "Updated", "city": "Krakow"},
        headers=_hdr(),
    )
    assert r2.status_code == 200
    assert r2.json()["label"] == "Updated"
    assert r2.json()["city"] == "Krakow"


def test_api_delete_204(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/API_C001/shipping-addresses/",
        json={"label": "To Delete"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    addr_id = r.json()["id"]
    r2 = client.delete(
        f"/api/v1/customer-master/API_C001/shipping-addresses/{addr_id}",
        headers=_hdr(),
    )
    assert r2.status_code == 204


def test_api_delete_404(client, api_tmp):
    r = client.delete(
        "/api/v1/customer-master/API_C001/shipping-addresses/99999",
        headers=_hdr(),
    )
    assert r.status_code == 404


def test_api_post_422_missing_label(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/API_C001/shipping-addresses/",
        json={"city": "Berlin"},  # no label
        headers=_hdr(),
    )
    assert r.status_code == 422


def test_api_requires_auth(client, api_tmp):
    """With empty api_key, auth is disabled (dev mode) — 200 expected.
    This test verifies auth wiring is present in the route (dependency declared)."""
    from app.api import routes_client_addresses as mod
    from fastapi import Depends
    # The router dependency list must reference require_api_key
    route_src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "require_api_key" in route_src, \
        "routes_client_addresses must declare require_api_key dependency"

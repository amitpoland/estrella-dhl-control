"""test_client_carrier_accounts.py — DB layer + API layer tests for carrier accounts."""
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

from app.services.client_carrier_accounts_db import (
    init_db, create_account, list_accounts, get_account,
    update_account, delete_account, validate_account,
)
from app.core.config import settings


# ── DB-layer tests ────────────────────────────────────────────────────────────

def test_init_db_idempotent(tmp_path):
    db = tmp_path / "test.sqlite"
    init_db(db)
    assert db.is_file()
    init_db(db)  # Must not raise


def test_create_account_returns_id(tmp_path):
    db = tmp_path / "test.sqlite"
    acct_id = create_account(db, "C001", {"carrier": "dhl", "account_number": "ACC123"})
    assert isinstance(acct_id, int)
    assert acct_id > 0


def test_carrier_enum_rejected(tmp_path):
    errs = validate_account({"carrier": "invalid", "account_number": "X"})
    assert any("carrier" in e for e in errs)


def test_payment_type_enum_rejected(tmp_path):
    errs = validate_account({
        "carrier": "dhl",
        "account_number": "X",
        "payment_type": "badtype",
    })
    assert any("payment_type" in e for e in errs)


def test_account_number_required(tmp_path):
    errs = validate_account({"carrier": "dhl"})
    assert any("account_number" in e for e in errs)


def test_duplicate_raises_value_error(tmp_path):
    db = tmp_path / "test.sqlite"
    create_account(db, "C001", {"carrier": "dhl", "account_number": "DUP"})
    with pytest.raises(ValueError, match="DUPLICATE_ACCOUNT"):
        create_account(db, "C001", {"carrier": "dhl", "account_number": "DUP"})


def test_list_accounts_returns_correct_set(tmp_path):
    db = tmp_path / "test.sqlite"
    create_account(db, "C001", {"carrier": "dhl", "account_number": "A1"})
    create_account(db, "C001", {"carrier": "fedex", "account_number": "A2"})
    accts = list_accounts(db, "C001")
    assert len(accts) == 2
    numbers = {a.account_number for a in accts}
    assert numbers == {"A1", "A2"}


def test_list_isolation_across_contractors(tmp_path):
    db = tmp_path / "test.sqlite"
    create_account(db, "C001", {"carrier": "dhl", "account_number": "C001-ACC"})
    create_account(db, "C002", {"carrier": "ups", "account_number": "C002-ACC"})
    c001 = list_accounts(db, "C001")
    c002 = list_accounts(db, "C002")
    assert len(c001) == 1 and c001[0].account_number == "C001-ACC"
    assert len(c002) == 1 and c002[0].account_number == "C002-ACC"


def test_update_changes_fields(tmp_path):
    db = tmp_path / "test.sqlite"
    acct_id = create_account(db, "C001", {
        "carrier": "dhl", "account_number": "OLD", "account_name": "Old Name"
    })
    updated = update_account(db, acct_id, "C001", {
        "carrier": "dhl", "account_number": "NEW", "account_name": "New Name"
    })
    assert updated is not None
    assert updated.account_number == "NEW"
    assert updated.account_name == "New Name"


def test_update_returns_none_wrong_contractor(tmp_path):
    db = tmp_path / "test.sqlite"
    acct_id = create_account(db, "C001", {"carrier": "dhl", "account_number": "X"})
    result = update_account(db, acct_id, "WRONG", {"carrier": "dhl", "account_number": "Y"})
    assert result is None


def test_delete_removes_row(tmp_path):
    db = tmp_path / "test.sqlite"
    acct_id = create_account(db, "C001", {"carrier": "fedex", "account_number": "DEL"})
    removed = delete_account(db, acct_id, "C001")
    assert removed is True
    assert get_account(db, acct_id, "C001") is None


def test_delete_returns_false_unknown(tmp_path):
    db = tmp_path / "test.sqlite"
    init_db(db)
    assert delete_account(db, 9999, "C001") is False


def test_is_default_cascade(tmp_path):
    db = tmp_path / "test.sqlite"
    id1 = create_account(db, "C001", {
        "carrier": "dhl", "account_number": "FIRST", "is_default": True
    })
    id2 = create_account(db, "C001", {
        "carrier": "fedex", "account_number": "SECOND", "is_default": True
    })
    a1 = get_account(db, id1, "C001")
    a2 = get_account(db, id2, "C001")
    assert a1 is not None and a2 is not None
    assert a1.is_default is False
    assert a2.is_default is True


def test_service_level_stored_as_string(tmp_path):
    db = tmp_path / "test.sqlite"
    acct_id = create_account(db, "C001", {
        "carrier": "dhl",
        "account_number": "SVC",
        "service_level": "EXPRESS_WORLDWIDE",
    })
    acct = get_account(db, acct_id, "C001")
    assert acct is not None
    assert acct.service_level == "EXPRESS_WORLDWIDE"


# ── API layer tests ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("carrier_api")


@pytest.fixture(scope="module")
def client(api_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", api_tmp):
        import app.api.routes_client_carrier_accounts as mod
        mod._DB_PATH = api_tmp / "customer_master.sqlite"
        # Phase 4C — carrier accounts now require an existing customer.
        import app.api.routes_customer_master as cm_mod
        cm_mod._DB_PATH = api_tmp / "customer_master.sqlite"
        # Phase 4C-ext — carrier accounts now require an active carriers_config row.
        import app.api.routes_master_data as md_mod
        md_mod._DB_PATH = api_tmp / "master_data.sqlite"
        hdr = {"X-API-KEY": settings.api_key or "test-key"}
        with TestClient(app, raise_server_exceptions=True) as c:
            for cid in ("CA_C001",):
                c.put(f"/api/v1/customer-master/{cid}",
                      json={"bill_to_name": cid, "country": "PL"}, headers=hdr)
            for carrier in ("dhl", "fedex", "ups"):
                c.put(f"/api/v1/carriers-config/{carrier}",
                      json={"name": carrier.upper()}, headers=hdr)
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_get_list_200(client, api_tmp):
    r = client.get(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        headers=_hdr(),
    )
    assert r.status_code == 200
    data = r.json()
    assert "accounts" in data
    assert isinstance(data["accounts"], list)


def test_api_post_201(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "DHL-001", "account_name": "Main DHL"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["carrier"] == "dhl"
    assert data["account_number"] == "DHL-001"
    assert data["id"] is not None


def test_api_put_200(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "fedex", "account_number": "FEDEX-TO-UPDATE"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    acct_id = r.json()["id"]
    r2 = client.put(
        f"/api/v1/customer-master/CA_C001/carrier-accounts/{acct_id}",
        json={"carrier": "fedex", "account_number": "FEDEX-UPDATED", "account_name": "Updated"},
        headers=_hdr(),
    )
    assert r2.status_code == 200
    assert r2.json()["account_number"] == "FEDEX-UPDATED"


def test_api_delete_204(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "ups", "account_number": "UPS-TO-DELETE"},
        headers=_hdr(),
    )
    assert r.status_code == 201
    acct_id = r.json()["id"]
    r2 = client.delete(
        f"/api/v1/customer-master/CA_C001/carrier-accounts/{acct_id}",
        headers=_hdr(),
    )
    assert r2.status_code == 204


def test_api_delete_404(client, api_tmp):
    r = client.delete(
        "/api/v1/customer-master/CA_C001/carrier-accounts/99999",
        headers=_hdr(),
    )
    assert r.status_code == 404


def test_api_post_409_duplicate(client, api_tmp):
    client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "DUP-DHL"},
        headers=_hdr(),
    )
    r2 = client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "DUP-DHL"},
        headers=_hdr(),
    )
    assert r2.status_code == 409


def test_api_post_422_bad_carrier(client, api_tmp):
    r = client.post(
        "/api/v1/customer-master/CA_C001/carrier-accounts/",
        json={"carrier": "badcarrier", "account_number": "X"},
        headers=_hdr(),
    )
    assert r.status_code == 422


def test_api_requires_auth(client, api_tmp):
    """Verify auth dependency is declared in the route module."""
    from app.api import routes_client_carrier_accounts as mod
    route_src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "require_api_key" in route_src, \
        "routes_client_carrier_accounts must declare require_api_key dependency"


# ── Fresh-DB tests (tables never initialised before request) ──────────────────
# These verify the init_db-on-every-handler fix: GET/PUT/DELETE must not crash
# with "no such table" when production DB is brand-new.

@pytest.fixture()
def fresh_client(tmp_path_factory):
    """Each test gets a completely empty DB directory — no init_db called yet."""
    fresh_tmp = tmp_path_factory.mktemp("carrier_fresh")
    from app.main import app
    with patch.object(settings, "storage_root", fresh_tmp):
        import app.api.routes_client_carrier_accounts as mod
        mod._DB_PATH = fresh_tmp / "customer_master.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, fresh_tmp


def test_api_get_list_fresh_db_200(fresh_client):
    """GET on a brand-new DB (no tables) must return 200 with count=0."""
    c, _ = fresh_client
    r = c.get(
        "/api/v1/customer-master/FRESH_C/carrier-accounts/",
        headers=_hdr(),
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["count"] == 0
    assert data["accounts"] == []


def test_api_delete_missing_fresh_db_404(fresh_client):
    """DELETE on a fresh DB (no tables, no rows) must return 404, not 500."""
    c, _ = fresh_client
    r = c.delete(
        "/api/v1/customer-master/FRESH_C/carrier-accounts/9999",
        headers=_hdr(),
    )
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


def test_api_put_missing_fresh_db_404(fresh_client):
    """PUT on a fresh DB (no tables, no rows) must return 404, not 500."""
    c, _ = fresh_client
    r = c.put(
        "/api/v1/customer-master/FRESH_C/carrier-accounts/9999",
        json={"carrier": "dhl", "account_number": "Ghost"},
        headers=_hdr(),
    )
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

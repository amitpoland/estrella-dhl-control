"""tests/test_c24_bill_to_nip_alias.py — C24-FINALIZE phase 3

CustomerMaster bill_to_nip → nip alias fix.

Root bug: frontend Customer Master edit form sends key ``bill_to_nip`` in
the PUT payload, but CustomerMaster dataclass field is ``nip``.  This caused:
    TypeError: CustomerMaster.__init__() got unexpected keyword argument 'bill_to_nip'

Fix:  _parse_body() in routes_customer_master.py now aliases bill_to_nip → nip
before constructing the dataclass.  Blank-string → None coercion also fires for
the alias key, consistent with all other optional string fields.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, headers={"X-API-Key": "test"})

_BASE_BODY = {
    "bill_to_name": "Test NIP Alias GmbH",
    "country": "DE",
}


def test_bill_to_nip_alias_saves_correctly(tmp_path, monkeypatch):
    """PUT with bill_to_nip must save without TypeError and the stored
    record must return the value under the canonical 'nip' key."""
    import app.api.routes_customer_master as rm
    monkeypatch.setattr(rm, "_DB_PATH", tmp_path / "cm.sqlite")

    body = {**_BASE_BODY, "bill_to_nip": "DE987654321"}
    resp = client.put("/api/v1/customer-master/ALIAS001", json=body)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["nip"] == "DE987654321", \
        f"nip must equal 'DE987654321'; got {data.get('nip')!r}"
    # Alias key must NOT appear in the response
    assert "bill_to_nip" not in data, "Response must not expose the alias key bill_to_nip"


def test_bill_to_nip_blank_becomes_none(tmp_path, monkeypatch):
    """PUT with bill_to_nip='' must store nip=None (blank→None coercion)."""
    import app.api.routes_customer_master as rm
    monkeypatch.setattr(rm, "_DB_PATH", tmp_path / "cm.sqlite")

    body = {**_BASE_BODY, "bill_to_nip": ""}
    resp = client.put("/api/v1/customer-master/ALIAS002", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["nip"] is None


def test_nip_takes_precedence_over_alias(tmp_path, monkeypatch):
    """If body contains both nip and bill_to_nip, nip wins."""
    import app.api.routes_customer_master as rm
    monkeypatch.setattr(rm, "_DB_PATH", tmp_path / "cm.sqlite")

    body = {**_BASE_BODY, "nip": "DE111111111", "bill_to_nip": "DE999999999"}
    resp = client.put("/api/v1/customer-master/ALIAS003", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["nip"] == "DE111111111", \
        "When both keys present, nip must win over bill_to_nip alias"


def test_bill_to_nip_absent_no_regression(tmp_path, monkeypatch):
    """PUT without bill_to_nip (standard payload) must still work."""
    import app.api.routes_customer_master as rm
    monkeypatch.setattr(rm, "_DB_PATH", tmp_path / "cm.sqlite")

    body = {**_BASE_BODY, "nip": "DE123456789"}
    resp = client.put("/api/v1/customer-master/ALIAS004", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["nip"] == "DE123456789"


def test_bill_to_nip_none_stored_as_null(tmp_path, monkeypatch):
    """PUT with bill_to_nip=None must store nip=None."""
    import app.api.routes_customer_master as rm
    monkeypatch.setattr(rm, "_DB_PATH", tmp_path / "cm.sqlite")

    body = {**_BASE_BODY, "bill_to_nip": None}
    resp = client.put("/api/v1/customer-master/ALIAS005", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["nip"] is None

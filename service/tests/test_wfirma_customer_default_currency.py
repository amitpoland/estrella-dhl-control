"""
test_wfirma_customer_default_currency.py — Operator endpoint to set
``wfirma_customers.default_currency`` for Proforma pricing fallback.

Pins (each maps to a numbered rule):
  1. setting EUR succeeds for an existing customer
  2. invalid currency rejected (400)
  3. unknown customer rejected (404, no row created)
  4. no other identity fields change (wfirma_customer_id, vat_id,
     country, match_status)
  5. get_customer returns the persisted default_currency

Plus thin guards:
  - set helper returns before/after
  - set helper is idempotent
  - lower-case input is normalised to upper-case
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_db as wfdb


URL = "/api/v1/wfirma/customers/{name}/default-currency"


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _register_customer(name: str, **fields) -> str:
    """Seed a mapped customer with full identity payload."""
    return wfdb.upsert_customer(
        client_name        = name,
        wfirma_customer_id = fields.get("wfirma_customer_id", "9001"),
        vat_id             = fields.get("vat_id",             "PL5252812119"),
        country            = fields.get("country",            "PL"),
        match_status       = fields.get("match_status",       "matched"),
    )


# ── 1. happy path ───────────────────────────────────────────────────────────

def test_set_default_currency_succeeds_for_existing_customer(client, storage):
    _register_customer("Anastazia Panakova")
    r = client.put(URL.format(name="Anastazia%20Panakova"),
                    headers={**_auth(), "X-Operator": "amit"},
                    json={"currency": "EUR"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["client_name"]     == "Anastazia Panakova"
    assert body["before_currency"] == ""
    assert body["after_currency"]  == "EUR"
    assert body["operator"]        == "amit"


def test_set_default_currency_returns_before_after_on_overwrite(client, storage):
    _register_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"currency": "EUR"})
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"currency": "USD"}).json()
    assert r["before_currency"] == "EUR"
    assert r["after_currency"]  == "USD"


def test_set_default_currency_normalises_lowercase(client, storage):
    _register_customer("ACME")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"currency": "eur"}).json()
    assert r["after_currency"] == "EUR"


# ── 2. invalid currency rejected ───────────────────────────────────────────

@pytest.mark.parametrize("bad", ["XYZ", "", "  ", "EURO", "$", "EU"])
def test_invalid_currency_rejected(client, storage, bad):
    _register_customer("ACME")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"currency": bad})
    assert r.status_code == 400, r.text
    # And no value persisted.
    cust = wfdb.get_customer("ACME")
    assert (cust or {}).get("default_currency", "") == ""


# ── 3. unknown customer rejected, no row created ───────────────────────────

def test_unknown_customer_rejected_no_row_created(client, storage):
    r = client.put(URL.format(name="GHOST"), headers=_auth(),
                    json={"currency": "EUR"})
    assert r.status_code == 404
    # No row created.
    assert wfdb.get_customer("GHOST") is None


# ── 4. no identity field change ─────────────────────────────────────────────

def test_identity_fields_unchanged(client, storage):
    _register_customer("ACME",
                        wfirma_customer_id="WID-7",
                        vat_id="PL1112223334",
                        country="PL",
                        match_status="matched")
    before = wfdb.get_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"currency": "EUR"})
    after = wfdb.get_customer("ACME")
    for f in ("wfirma_customer_id", "vat_id", "country", "match_status"):
        assert before[f] == after[f], (
            f"identity field {f} changed: {before[f]!r} → {after[f]!r}"
        )
    assert after["default_currency"] == "EUR"


# ── 5. get_customer surfaces default_currency ──────────────────────────────

def test_get_customer_returns_default_currency(client, storage):
    _register_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"currency": "EUR"})
    cust = wfdb.get_customer("ACME")
    assert cust is not None
    assert cust.get("default_currency") == "EUR"


# ── Helper-level invariants ────────────────────────────────────────────────

def test_helper_returns_none_for_unknown(storage):
    assert wfdb.set_customer_default_currency(
        client_name="GHOST", currency="EUR") is None


def test_helper_raises_value_error_on_invalid_currency(storage):
    _register_customer("ACME")
    with pytest.raises(ValueError, match="not allowed"):
        wfdb.set_customer_default_currency(
            client_name="ACME", currency="XYZ")


def test_helper_idempotent(storage):
    _register_customer("ACME")
    first  = wfdb.set_customer_default_currency(
        client_name="ACME", currency="EUR")
    second = wfdb.set_customer_default_currency(
        client_name="ACME", currency="EUR")
    assert first["after_currency"]  == "EUR"
    assert second["before_currency"] == "EUR"
    assert second["after_currency"]  == "EUR"


def test_helper_does_not_create_row_for_unknown(storage):
    """Defence in depth: even at helper level, no INSERT for unknown."""
    wfdb.set_customer_default_currency(client_name="GHOST", currency="EUR")
    with sqlite3.connect(str(wfdb._db_path)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM wfirma_customers WHERE client_name=?",
            ("GHOST",),
        ).fetchone()[0]
    assert n == 0

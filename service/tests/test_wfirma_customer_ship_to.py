"""
test_wfirma_customer_ship_to.py — Step 1 of Nabywca/Odbiorca support.

Pins:
  1. ``same_as_bill_to`` succeeds and clears any prior receiver id.
  2. ``bill_to_alt``    succeeds and clears any prior receiver id.
  3. ``separate_contractor`` requires ``ship_to_wfirma_customer_id``.
  4. Unknown mode rejected (400).
  5. Unknown customer rejected (404, no row created).
  6. Identity fields unchanged after every update.
  7. ``get_customer`` surfaces the new fields (default + after stamp).
  8. Endpoint is NOT swallowed by the catch-all PUT /customers/{...}.

Plus thin guards:
  - schema migration adds the two columns (idempotent).
  - helper rejects self-reference (receiver == bill-to wfirma_customer_id).
  - helper is idempotent on identical re-call (returns the same after
    state with before==after on the second invocation).
  - operator header is captured.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_db as wfdb


URL = "/api/v1/wfirma/customers/{name}/ship-to"


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


def _register_customer(name: str, *, wfirma_id: str = "9001",
                        country: str = "PL", vat: str = "PL5252812119") -> str:
    return wfdb.upsert_customer(
        client_name        = name,
        wfirma_customer_id = wfirma_id,
        vat_id             = vat,
        country            = country,
        match_status       = "matched",
    )


# ── Schema migration ───────────────────────────────────────────────────────

def test_schema_migration_adds_ship_to_columns(storage):
    with sqlite3.connect(str(wfdb._db_path)) as con:
        cols = {r[1] for r in con.execute(
            "PRAGMA table_info(wfirma_customers)").fetchall()}
    assert "ship_to_mode"               in cols
    assert "ship_to_wfirma_customer_id" in cols


def test_default_ship_to_mode_is_same_as_bill_to(client, storage):
    _register_customer("ACME")
    cust = wfdb.get_customer("ACME")
    assert cust["ship_to_mode"]               == "same_as_bill_to"
    assert cust["ship_to_wfirma_customer_id"] == ""


# ── 1. same_as_bill_to ──────────────────────────────────────────────────────

def test_same_as_bill_to_clears_receiver(client, storage):
    _register_customer("ACME")
    # Pre-stamp a receiver via separate_contractor so we can assert it clears.
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"mode": "separate_contractor",
                       "ship_to_wfirma_customer_id": "RCV-1"})
    r = client.put(URL.format(name="ACME"),
                    headers={**_auth(), "X-Operator": "amit"},
                    json={"mode": "same_as_bill_to",
                           "ship_to_wfirma_customer_id": "RCV-IGNORE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["mode"]                       == "same_as_bill_to"
    assert body["after"]["ship_to_wfirma_customer_id"] == ""
    assert body["before"]["mode"]                      == "separate_contractor"
    assert body["before"]["ship_to_wfirma_customer_id"] == "RCV-1"
    assert body["operator"]                            == "amit"
    cust = wfdb.get_customer("ACME")
    assert cust["ship_to_mode"]               == "same_as_bill_to"
    assert cust["ship_to_wfirma_customer_id"] == ""


# ── 2. bill_to_alt ──────────────────────────────────────────────────────────

def test_bill_to_alt_clears_receiver(client, storage):
    _register_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"mode": "separate_contractor",
                       "ship_to_wfirma_customer_id": "RCV-2"})
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"mode": "bill_to_alt"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["mode"]                       == "bill_to_alt"
    assert body["after"]["ship_to_wfirma_customer_id"] == ""


# ── 3. separate_contractor requires receiver id ────────────────────────────

def test_separate_contractor_requires_receiver_id(client, storage):
    _register_customer("ACME")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"mode": "separate_contractor"})
    assert r.status_code == 400, r.text
    assert "ship_to_wfirma_customer_id is required" in r.text
    cust = wfdb.get_customer("ACME")
    assert cust["ship_to_mode"]               == "same_as_bill_to"  # unchanged
    assert cust["ship_to_wfirma_customer_id"] == ""


def test_separate_contractor_with_receiver_succeeds(client, storage):
    _register_customer("ACME", wfirma_id="9001")
    r = client.put(URL.format(name="ACME"),
                    headers={**_auth(), "X-Operator": "amit"},
                    json={"mode": "separate_contractor",
                           "ship_to_wfirma_customer_id": "99990004"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["mode"]                       == "separate_contractor"
    assert body["after"]["ship_to_wfirma_customer_id"] == "99990004"


def test_separate_contractor_rejects_self_reference(client, storage):
    """Receiver id equal to the bill-to wfirma_customer_id is a silly
    self-reference — refuse so a typo can't masquerade as Shape B."""
    _register_customer("ACME", wfirma_id="9001")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"mode": "separate_contractor",
                           "ship_to_wfirma_customer_id": "9001"})
    assert r.status_code == 400, r.text
    assert "DIFFERENT receiver" in r.text


# ── 4. Invalid mode rejected ───────────────────────────────────────────────

@pytest.mark.parametrize("bad_mode", [
    "ship_to", "alternate", "default", "", "  ",
    "BillToAlt",   # canonical form must match exactly (lowercased internally)
])
def test_invalid_mode_rejected(client, storage, bad_mode):
    _register_customer("ACME")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"mode": bad_mode,
                           "ship_to_wfirma_customer_id": "X"})
    if bad_mode.lower() == "billtoalt":
        # No underscore — stays out of the allowed set.
        assert r.status_code == 400
    else:
        assert r.status_code == 400, r.text
    cust = wfdb.get_customer("ACME")
    assert cust["ship_to_mode"] == "same_as_bill_to"


# ── 5. Unknown customer rejected ───────────────────────────────────────────

def test_unknown_customer_rejected_no_row_created(client, storage):
    r = client.put(URL.format(name="GHOST"), headers=_auth(),
                    json={"mode": "bill_to_alt"})
    assert r.status_code == 404
    assert wfdb.get_customer("GHOST") is None


# ── 6. Identity fields unchanged ────────────────────────────────────────────

def test_identity_fields_unchanged_after_ship_to_update(client, storage):
    _register_customer("ACME",
                        wfirma_id="WID-7",
                        vat="PL1112223334",
                        country="PL")
    # Stamp default_currency via the existing helper so we can assert it's
    # also preserved across ship-to writes.
    wfdb.set_customer_default_currency(client_name="ACME", currency="EUR")
    before = wfdb.get_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"mode": "separate_contractor",
                       "ship_to_wfirma_customer_id": "99990004"})
    after = wfdb.get_customer("ACME")
    for f in ("wfirma_customer_id", "vat_id", "country",
              "match_status", "default_currency"):
        assert before[f] == after[f], (
            f"identity/non-shipto field {f} changed: "
            f"{before[f]!r} → {after[f]!r}"
        )
    assert after["ship_to_mode"]               == "separate_contractor"
    assert after["ship_to_wfirma_customer_id"] == "99990004"


# ── 7. get_customer surfaces new fields ────────────────────────────────────

def test_get_customer_surfaces_ship_to_fields(client, storage):
    _register_customer("ACME")
    client.put(URL.format(name="ACME"), headers=_auth(),
                json={"mode": "separate_contractor",
                       "ship_to_wfirma_customer_id": "RCV-99"})
    cust = wfdb.get_customer("ACME")
    assert cust is not None
    assert cust["ship_to_mode"]               == "separate_contractor"
    assert cust["ship_to_wfirma_customer_id"] == "RCV-99"


# ── 8. Endpoint not swallowed by catch-all customer upsert ─────────────────

def test_ship_to_endpoint_routes_correctly_not_to_upsert(client, storage):
    """The PUT /customers/{...}/ship-to suffix must resolve to the
    ship-to handler, not the catch-all upsert handler. Pass an obviously
    wrong upsert payload (no wfirma_customer_id) — if the catch-all
    swallowed it, the response would be the upsert shape; if our handler
    fired, we see the ship-to validation error or success."""
    _register_customer("ACME")
    r = client.put(URL.format(name="ACME"), headers=_auth(),
                    json={"mode": "bill_to_alt"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Ship-to response shape carries before/after blocks. Upsert shape
    # would have only {ok, id, client_name}. Both have id+client_name.
    assert "after"  in body
    assert "before" in body
    assert body["after"]["mode"] == "bill_to_alt"


# ── Helper-level guards ─────────────────────────────────────────────────────

def test_helper_returns_none_for_unknown_customer(storage):
    assert wfdb.set_customer_ship_to(
        client_name="GHOST", mode="bill_to_alt") is None


def test_helper_idempotent_on_identical_recall(storage):
    _register_customer("ACME")
    first = wfdb.set_customer_ship_to(
        client_name="ACME", mode="separate_contractor",
        ship_to_wfirma_customer_id="99990004")
    second = wfdb.set_customer_ship_to(
        client_name="ACME", mode="separate_contractor",
        ship_to_wfirma_customer_id="99990004")
    assert first["after_mode"]                          == "separate_contractor"
    assert first["after_ship_to_wfirma_customer_id"]    == "99990004"
    # Second call: before reflects first call's outcome; after is same.
    assert second["before_mode"]                        == "separate_contractor"
    assert second["before_ship_to_wfirma_customer_id"]  == "99990004"
    assert second["after_mode"]                         == "separate_contractor"
    assert second["after_ship_to_wfirma_customer_id"]   == "99990004"


def test_helper_no_inserts_for_unknown(storage):
    """Defence in depth: even at helper level, no INSERT for unknown."""
    wfdb.set_customer_ship_to(client_name="GHOST", mode="bill_to_alt")
    with sqlite3.connect(str(wfdb._db_path)) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM wfirma_customers WHERE client_name=?",
            ("GHOST",),
        ).fetchone()[0]
    assert n == 0


def test_helper_normalises_mode_case(storage):
    """``mode`` is matched against the allowed set after lower-casing.
    Tolerates accidental ``Same_As_Bill_To`` capitalisation."""
    _register_customer("ACME")
    r = wfdb.set_customer_ship_to(client_name="ACME",
                                    mode="SAME_AS_BILL_TO")
    assert r["after_mode"] == "same_as_bill_to"

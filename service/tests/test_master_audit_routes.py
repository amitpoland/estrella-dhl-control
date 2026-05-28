"""test_master_audit_routes.py — Phase 1 wiring tests.

For each of the 5 master-data route files, verify that:

  - a write through the existing endpoint produces exactly one row in
    master_audit with the correct entity / op / pk / before / after shape
  - reads do NOT produce audit rows
  - X-Request-Id and X-Change-Reason headers are propagated
  - actor falls back to "apikey:unknown" when no api_key_label is present
  - audit-write failure does NOT break the primary write (regression
    against the audit_safe contract)

Phase 1 wires audit into:
  hs_codes · units · product_local · incoterms · vat_config · fx_rates ·
  carriers_config · designs · customers · suppliers · client_addresses ·
  client_carrier_accounts

wFirma sync endpoints are intentionally NOT covered — they remain
authority-external and Phase 1 does not touch them.
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

from fastapi.testclient import TestClient

from app.core.audit import list_audit
from app.core.config import settings


# ── Shared fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Inline-composed app — does NOT import app.main, so we don't depend on
    other unrelated routers that may be in transitional state in the working
    tree. Phase 1 only needs the 5 master-data route files plus the audit
    query router."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)

    import app.api.routes_master_data as md
    import app.api.routes_customer_master as cm
    import app.api.routes_suppliers as su
    import app.api.routes_client_addresses as ca
    import app.api.routes_client_carrier_accounts as cca

    md._DB_PATH  = tmp_path / "master_data.sqlite"
    cm._DB_PATH  = tmp_path / "customer_master.sqlite"
    su._DB_PATH  = tmp_path / "suppliers.sqlite"
    # Phase 4B+ — addresses + carrier_accounts share the customer_master DB
    # file. Phase 4C RI checks rely on this.
    ca._DB_PATH  = tmp_path / "customer_master.sqlite"
    cca._DB_PATH = tmp_path / "customer_master.sqlite"

    from fastapi import FastAPI
    app = FastAPI()
    for r in (
        md.hs_router, md.units_router, md.pl_router, md.incoterms_router,
        md.vat_router, md.fx_router, md.carriers_config_router,
        md.designs_router, md.audit_router,
        cm.router, su.router, ca.router, cca.router,
    ):
        app.include_router(r)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _hdr(extra: dict | None = None) -> dict:
    h = {"X-API-Key": settings.api_key or "test-key"}
    if extra:
        h.update(extra)
    return h


# ── HS codes ────────────────────────────────────────────────────────────────

def test_hs_put_writes_audit_create(client):
    r = client.put("/api/v1/hs-codes/71131900",
                   json={"description_pl": "Bizuteria", "duty_rate_pct": "2.5"},
                   headers=_hdr({"X-Request-Id": "req-hs-1",
                                 "X-Change-Reason": "seed"}))
    assert r.status_code == 200, r.text

    rows = list_audit(entity="hs_codes")
    assert len(rows) == 1
    row = rows[0]
    assert row["op"] == "create"
    assert row["pk"] == "71131900"
    assert row["before_json"] is None
    assert row["after_json"]["hs_code"] == "71131900"
    assert row["request_id"] == "req-hs-1"
    assert row["reason"] == "seed"
    # actor fallback (no api_key_label middleware in test).
    assert row["actor"] == "apikey:unknown"


def test_hs_put_writes_audit_update_with_diff(client):
    client.put("/api/v1/hs-codes/71131900",
               json={"duty_rate_pct": "2.5", "active": True}, headers=_hdr())
    client.put("/api/v1/hs-codes/71131900",
               json={"duty_rate_pct": "2.5", "active": False}, headers=_hdr())
    rows = list_audit(entity="hs_codes", pk="71131900")
    assert len(rows) == 2
    update_row = rows[0]   # newest first
    assert update_row["op"] == "update"
    assert update_row["diff_json"] is not None
    assert "active" in update_row["diff_json"]
    assert update_row["diff_json"]["active"] == {"before": True, "after": False}


def test_hs_delete_writes_audit_with_before(client):
    client.put("/api/v1/hs-codes/71131910",
               json={"description_pl": "x"}, headers=_hdr())
    r = client.delete("/api/v1/hs-codes/71131910", headers=_hdr())
    assert r.status_code == 204
    rows = list_audit(entity="hs_codes", pk="71131910")
    [delete_row] = [r for r in rows if r["op"] == "delete"]
    assert delete_row["before_json"]["hs_code"] == "71131910"
    assert delete_row["after_json"] is None


def test_hs_get_does_not_write_audit(client):
    client.put("/api/v1/hs-codes/71131900",
               json={"description_pl": "x"}, headers=_hdr())
    n_before = len(list_audit(entity="hs_codes"))
    client.get("/api/v1/hs-codes/71131900", headers=_hdr())
    client.get("/api/v1/hs-codes/",          headers=_hdr())
    assert len(list_audit(entity="hs_codes")) == n_before


# ── Units ───────────────────────────────────────────────────────────────────

def test_units_put_and_delete_audit(client):
    client.put("/api/v1/units/szt", json={"name_pl": "sztuka"}, headers=_hdr())
    client.delete("/api/v1/units/szt", headers=_hdr())
    rows = list_audit(entity="units", pk="szt")
    ops = [r["op"] for r in rows]
    assert "create" in ops and "delete" in ops


# ── product_local ───────────────────────────────────────────────────────────

def test_product_local_put_audit(client):
    # Need a HS code for FK-style validation later (Phase 4); Phase 1 doesn't
    # check it, so a bare upsert is fine here.
    client.put("/api/v1/hs-codes/71131900",
               json={"description_pl": "x"}, headers=_hdr())
    r = client.put("/api/v1/product-local/SKU-001",
                   json={"hs_code_override": "71131900"}, headers=_hdr())
    assert r.status_code == 200
    [row] = list_audit(entity="product_local", pk="SKU-001")
    assert row["op"] == "create"
    assert row["after_json"]["hs_code_override"] == "71131900"


# ── Incoterms ───────────────────────────────────────────────────────────────

def test_incoterms_put_audit(client):
    r = client.put("/api/v1/incoterms/EXW",
                   json={"name": "Ex Works"}, headers=_hdr())
    assert r.status_code == 200
    [row] = list_audit(entity="incoterms", pk="EXW")
    assert row["op"] == "create"


# ── VAT config ──────────────────────────────────────────────────────────────

def test_vat_config_post_put_delete_audit(client):
    r = client.post("/api/v1/vat-config/",
                    json={"country": "PL", "rate_pct": "23"}, headers=_hdr())
    assert r.status_code == 201, r.text
    vat_id = r.json()["id"]

    # create row present.
    create_rows = list_audit(entity="vat_config", op="create")
    assert any(r["pk"] == str(vat_id) for r in create_rows)

    r = client.put(f"/api/v1/vat-config/{vat_id}",
                   json={"notes": "updated"}, headers=_hdr())
    assert r.status_code == 200

    r = client.delete(f"/api/v1/vat-config/{vat_id}", headers=_hdr())
    assert r.status_code == 204

    all_rows = list_audit(entity="vat_config", pk=str(vat_id))
    ops = {r["op"] for r in all_rows}
    assert ops == {"create", "update", "delete"}


# ── FX rates (REFERENCE-ONLY entity; audit still required) ─────────────────

def test_fx_rates_post_audit(client):
    r = client.post("/api/v1/fx-rates/",
                    json={"rate_date": "2026-05-28", "from_currency": "USD",
                          "to_currency": "PLN", "rate": "3.6506"},
                    headers=_hdr())
    assert r.status_code == 201, r.text
    fx_id = r.json()["id"]
    [row] = [r for r in list_audit(entity="fx_rates", pk=str(fx_id))
             if r["op"] == "create"]
    # Decimal-as-string discipline preserved through audit.
    assert row["after_json"]["rate"] == "3.6506"
    assert isinstance(row["after_json"]["rate"], str)


# ── Carriers config ─────────────────────────────────────────────────────────

def test_carriers_config_put_audit(client):
    r = client.put("/api/v1/carriers-config/dhl",
                   json={"name": "DHL Express", "api_type": "api"},
                   headers=_hdr())
    assert r.status_code == 200
    [row] = list_audit(entity="carriers_config", pk="dhl")
    assert row["op"] == "create"


# ── Designs ─────────────────────────────────────────────────────────────────

def test_designs_put_audit(client):
    r = client.put("/api/v1/designs/D-ROUND-1CT",
                   json={"display_name": "Round 1ct"}, headers=_hdr())
    assert r.status_code == 200
    [row] = list_audit(entity="designs", pk="D-ROUND-1CT")
    assert row["op"] == "create"


# ── Customers (customer_master) ─────────────────────────────────────────────

def test_customer_put_audit(client):
    r = client.put("/api/v1/customer-master/W-001",
                   json={"bill_to_name": "Acme Sp. z o.o.", "country": "PL"},
                   headers=_hdr({"X-Request-Id": "req-c-1"}))
    assert r.status_code == 200, r.text
    [row] = list_audit(entity="customers", pk="W-001")
    assert row["op"] == "create"
    assert row["after_json"]["bill_to_name"] == "Acme Sp. z o.o."
    assert row["request_id"] == "req-c-1"


# ── Suppliers ───────────────────────────────────────────────────────────────

def test_supplier_create_update_delete_audit(client):
    r = client.post("/api/v1/suppliers/",
                    json={"supplier_code": "SUP-001", "name": "Vendor A",
                          "country": "IN"},
                    headers=_hdr())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.put(f"/api/v1/suppliers/{sid}",
                   json={"name": "Vendor A Ltd"}, headers=_hdr())
    assert r.status_code == 200
    r = client.delete(f"/api/v1/suppliers/{sid}", headers=_hdr())
    assert r.status_code == 204

    ops = {r["op"] for r in list_audit(entity="suppliers", pk=str(sid))}
    assert ops == {"create", "update", "delete"}


# ── Client addresses ────────────────────────────────────────────────────────

def test_client_address_create_update_delete_audit(client):
    # Seed customer first (required FK conceptually; Phase 1 doesn't enforce).
    client.put("/api/v1/customer-master/W-200",
               json={"bill_to_name": "X", "country": "PL"}, headers=_hdr())

    r = client.post("/api/v1/customer-master/W-200/shipping-addresses/",
                    json={"label": "HQ", "city": "Warsaw"}, headers=_hdr())
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = client.put(f"/api/v1/customer-master/W-200/shipping-addresses/{aid}",
                   json={"label": "HQ2", "city": "Warsaw"}, headers=_hdr())
    assert r.status_code == 200

    r = client.delete(f"/api/v1/customer-master/W-200/shipping-addresses/{aid}",
                      headers=_hdr())
    assert r.status_code == 204

    rows = list_audit(entity="client_addresses")
    # Phase 4B Wave 2: stable colon-separated composite pk.
    expected_pk = f"customer:W-200:address:{aid}"
    target = [r for r in rows if r["pk"] == expected_pk]
    ops = {r["op"] for r in target}
    assert ops == {"create", "update", "delete"}


# ── Client carrier accounts ─────────────────────────────────────────────────

def test_client_carrier_account_create_update_delete_audit(client):
    client.put("/api/v1/customer-master/W-300",
               json={"bill_to_name": "Y", "country": "PL"}, headers=_hdr())
    # Phase 4C-ext — referenced carrier must be active in carriers_config.
    client.put("/api/v1/carriers-config/dhl",
               json={"name": "DHL"}, headers=_hdr())
    r = client.post("/api/v1/customer-master/W-300/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "ABC123"},
                    headers=_hdr())
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = client.put(f"/api/v1/customer-master/W-300/carrier-accounts/{aid}",
                   json={"carrier": "dhl", "account_number": "ABC123",
                         "notes": "default"},
                   headers=_hdr())
    assert r.status_code == 200
    r = client.delete(f"/api/v1/customer-master/W-300/carrier-accounts/{aid}",
                      headers=_hdr())
    assert r.status_code == 204

    rows = list_audit(entity="client_carrier_accounts")
    expected_pk = f"customer:W-300:carrier_account:{aid}"
    target = [r for r in rows if r["pk"] == expected_pk]
    ops = {r["op"] for r in target}
    assert ops == {"create", "update", "delete"}


# ── Audit failure must not corrupt the primary write ────────────────────────

def test_audit_failure_does_not_break_write(client, monkeypatch):
    """If write_audit raises mid-call, audit_safe must swallow + log.
    The HTTP response of the primary write must remain 200."""
    from app.core import audit as audit_mod

    def boom(*a, **kw):
        raise RuntimeError("simulated audit DB failure")

    monkeypatch.setattr(audit_mod, "write_audit", boom)

    r = client.put("/api/v1/hs-codes/77777700",
                   json={"description_pl": "boom"}, headers=_hdr())
    assert r.status_code == 200, r.text
    # GET back through the read path proves the primary row persisted.
    g = client.get("/api/v1/hs-codes/77777700", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["hs_code"] == "77777700"

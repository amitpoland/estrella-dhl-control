"""test_master_referential_integrity_phase4c.py — Phase 4C RI checks.

Coverage matrix:
  product_local:
    - rejects missing hs_code_override → 409
    - rejects inactive hs_code_override → 409
    - accepts active hs_code_override   → 200
    - empty/null hs_code_override skips the check
  designs:
    - rejects missing hs_code reference → 409
    - rejects inactive hs_code reference → 409
    - accepts active hs_code            → 200
    - omitted hs_code                   → 200 (field is optional)
  client_addresses:
    - create rejects missing customer   → 409
    - create accepts existing customer  → 201
    - restore rejects missing customer  → 409
  client_carrier_accounts:
    - same shape as client_addresses
  Existing-data behavior:
    - GET still returns rows even if references became inactive after creation
  Error contract:
    - response body has {error, field, entity, key, reason}
  Authority isolation (source-grep):
    - PZ engine, wFirma, DHL, proforma, FX engine, inventory engine do NOT
      import master_reference_checks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings


# ── Fixture: minimal inline app composed of just the routes we touch ────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_master_data as md
    import app.api.routes_customer_master as cm
    import app.api.routes_client_addresses as ca
    import app.api.routes_client_carrier_accounts as cca
    md._DB_PATH  = tmp_path / "master_data.sqlite"
    cm._DB_PATH  = tmp_path / "customer_master.sqlite"
    ca._DB_PATH  = tmp_path / "customer_master.sqlite"
    cca._DB_PATH = tmp_path / "customer_master.sqlite"
    app = FastAPI()
    for r in (md.hs_router, md.units_router, md.pl_router, md.designs_router,
              # Phase 4C-ext — carrier-account RI tests need carriers_config too.
              md.carriers_config_router,
              cm.router, ca.router, cca.router):
        app.include_router(r)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


# Helpers ──────────────────────────────────────────────────────────────────

def _seed_hs(client, code: str, *, active: bool = True) -> None:
    r = client.put(f"/api/v1/hs-codes/{code}",
                   json={"description_pl": f"hs {code}"}, headers=_HDR)
    assert r.status_code == 200, r.text
    if not active:
        d = client.delete(f"/api/v1/hs-codes/{code}", headers=_HDR)
        assert d.status_code == 204


def _seed_customer(client, contractor_id: str) -> None:
    r = client.put(f"/api/v1/customer-master/{contractor_id}",
                   json={"bill_to_name": "X", "country": "PL"}, headers=_HDR)
    assert r.status_code == 200, r.text


def _assert_reference_conflict(resp, *, field: str, entity: str,
                               key: str, reason: str) -> None:
    assert resp.status_code == 409, resp.text
    body = resp.json()
    detail = body.get("detail", body)
    assert detail.get("error")  == "reference_conflict", detail
    assert detail.get("field")  == field,  detail
    assert detail.get("entity") == entity, detail
    assert detail.get("key")    == key,    detail
    assert detail.get("reason") == reason, detail


# ── product_local: hs_code_override ─────────────────────────────────────────

def test_product_local_rejects_missing_hs_override(client):
    r = client.put("/api/v1/product-local/SKU-001",
                   json={"hs_code_override": "70131900"}, headers=_HDR)
    _assert_reference_conflict(r, field="hs_code_override",
                               entity="hs_codes", key="70131900",
                               reason="missing")


def test_product_local_rejects_inactive_hs_override(client):
    _seed_hs(client, "70131900", active=False)
    r = client.put("/api/v1/product-local/SKU-002",
                   json={"hs_code_override": "70131900"}, headers=_HDR)
    _assert_reference_conflict(r, field="hs_code_override",
                               entity="hs_codes", key="70131900",
                               reason="inactive")


def test_product_local_accepts_active_hs_override(client):
    _seed_hs(client, "70131900")
    r = client.put("/api/v1/product-local/SKU-003",
                   json={"hs_code_override": "70131900"}, headers=_HDR)
    assert r.status_code == 200, r.text
    assert r.json()["hs_code_override"] == "70131900"


def test_product_local_no_override_skips_check(client):
    """When hs_code_override is omitted/empty the check must NOT fire."""
    r = client.put("/api/v1/product-local/SKU-NORM",
                   json={"notes": "no override"}, headers=_HDR)
    assert r.status_code == 200, r.text


def test_product_local_empty_override_skips_check(client):
    r = client.put("/api/v1/product-local/SKU-EMPTY",
                   json={"hs_code_override": ""}, headers=_HDR)
    assert r.status_code == 200, r.text


# ── designs: hs_code ────────────────────────────────────────────────────────

def test_design_rejects_missing_hs_code_reference(client):
    r = client.put("/api/v1/designs/D-MISSING",
                   json={"display_name": "X", "hs_code": "70131900"},
                   headers=_HDR)
    _assert_reference_conflict(r, field="hs_code", entity="hs_codes",
                               key="70131900", reason="missing")


def test_design_rejects_inactive_hs_code_reference(client):
    _seed_hs(client, "70131900", active=False)
    r = client.put("/api/v1/designs/D-INACTIVE",
                   json={"display_name": "X", "hs_code": "70131900"},
                   headers=_HDR)
    _assert_reference_conflict(r, field="hs_code", entity="hs_codes",
                               key="70131900", reason="inactive")


def test_design_accepts_active_hs_code(client):
    _seed_hs(client, "70131900")
    r = client.put("/api/v1/designs/D-OK",
                   json={"display_name": "X", "hs_code": "70131900"},
                   headers=_HDR)
    assert r.status_code == 200, r.text
    assert r.json()["hs_code"] == "70131900"


def test_design_omitted_hs_code_is_allowed(client):
    r = client.put("/api/v1/designs/D-NO-HS",
                   json={"display_name": "X"}, headers=_HDR)
    assert r.status_code == 200, r.text


# ── client_addresses: contractor must exist ─────────────────────────────────

def test_client_addresses_create_rejects_missing_customer(client):
    r = client.post("/api/v1/customer-master/W-MISSING/shipping-addresses/",
                    json={"label": "HQ"}, headers=_HDR)
    _assert_reference_conflict(r, field="contractor_id", entity="customers",
                               key="W-MISSING", reason="missing")


def test_client_addresses_create_accepts_existing_customer(client):
    _seed_customer(client, "W-ADDR-OK")
    r = client.post("/api/v1/customer-master/W-ADDR-OK/shipping-addresses/",
                    json={"label": "HQ"}, headers=_HDR)
    assert r.status_code == 201, r.text


def test_client_addresses_restore_rejects_missing_customer(client, tmp_path):
    """Soft-delete an address, then directly remove the parent customer row
    from the DB (simulating an external-system rollback), then restore must
    reject with 409."""
    _seed_customer(client, "W-ADDR-RST")
    create = client.post("/api/v1/customer-master/W-ADDR-RST/shipping-addresses/",
                         json={"label": "HQ"}, headers=_HDR)
    addr_id = create.json()["id"]
    # Soft-delete the address.
    client.delete(f"/api/v1/customer-master/W-ADDR-RST/shipping-addresses/{addr_id}",
                  headers=_HDR)
    # Remove the parent customer row directly via SQLite to simulate
    # missing parent (no UI path does this; this is a defensive test).
    import sqlite3
    db = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(db) as cx:
        cx.execute("DELETE FROM customer_master WHERE bill_to_contractor_id = ?",
                   ("W-ADDR-RST",))
        cx.commit()
    r = client.post(f"/api/v1/customer-master/W-ADDR-RST/shipping-addresses/"
                    f"{addr_id}/restore", headers=_HDR)
    _assert_reference_conflict(r, field="contractor_id", entity="customers",
                               key="W-ADDR-RST", reason="missing")


# ── client_carrier_accounts: contractor must exist ──────────────────────────

def test_client_carrier_accounts_create_rejects_missing_customer(client):
    r = client.post("/api/v1/customer-master/W-MISSING/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "X"}, headers=_HDR)
    _assert_reference_conflict(r, field="contractor_id", entity="customers",
                               key="W-MISSING", reason="missing")


def test_client_carrier_accounts_create_accepts_existing_customer(client):
    _seed_customer(client, "W-CARR-OK")
    # Phase 4C-ext — carrier-account create now also requires an active carrier.
    _seed_carrier(client, "dhl")
    r = client.post("/api/v1/customer-master/W-CARR-OK/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "ABC"}, headers=_HDR)
    assert r.status_code == 201, r.text


def test_client_carrier_accounts_restore_rejects_missing_customer(client, tmp_path):
    _seed_customer(client, "W-CARR-RST")
    _seed_carrier(client, "dhl")
    create = client.post("/api/v1/customer-master/W-CARR-RST/carrier-accounts/",
                         json={"carrier": "dhl", "account_number": "ABC"}, headers=_HDR)
    acct_id = create.json()["id"]
    client.delete(f"/api/v1/customer-master/W-CARR-RST/carrier-accounts/{acct_id}",
                  headers=_HDR)
    import sqlite3
    db = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(db) as cx:
        cx.execute("DELETE FROM customer_master WHERE bill_to_contractor_id = ?",
                   ("W-CARR-RST",))
        cx.commit()
    r = client.post(f"/api/v1/customer-master/W-CARR-RST/carrier-accounts/"
                    f"{acct_id}/restore", headers=_HDR)
    _assert_reference_conflict(r, field="contractor_id", entity="customers",
                               key="W-CARR-RST", reason="missing")


# ── Existing-data behavior: GET must still return rows even if parent gone ─

def test_get_returns_existing_product_local_after_parent_hs_goes_inactive(client):
    _seed_hs(client, "70131900")
    client.put("/api/v1/product-local/SKU-LEGACY",
               json={"hs_code_override": "70131900"}, headers=_HDR)
    # Now soft-delete the HS code.
    client.delete("/api/v1/hs-codes/70131900", headers=_HDR)
    # GET the existing product_local row — still returns 200 with the now-stale ref.
    g = client.get("/api/v1/product-local/SKU-LEGACY", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["hs_code_override"] == "70131900"


def test_get_returns_existing_design_after_parent_hs_goes_inactive(client):
    _seed_hs(client, "70131900")
    client.put("/api/v1/designs/D-LEGACY",
               json={"display_name": "X", "hs_code": "70131900"}, headers=_HDR)
    client.delete("/api/v1/hs-codes/70131900", headers=_HDR)
    g = client.get("/api/v1/designs/D-LEGACY", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["hs_code"] == "70131900"


def test_update_existing_product_local_can_clear_inactive_override(client):
    """An operator who finds a legacy row pointing at an inactive HS can
    clear the override (send empty string) without tripping the RI check."""
    _seed_hs(client, "70131900")
    client.put("/api/v1/product-local/SKU-CLEAR",
               json={"hs_code_override": "70131900"}, headers=_HDR)
    client.delete("/api/v1/hs-codes/70131900", headers=_HDR)
    # Clear the stale reference — RI check skips empty/null values.
    r = client.put("/api/v1/product-local/SKU-CLEAR",
                   json={"hs_code_override": ""}, headers=_HDR)
    assert r.status_code == 200, r.text


# ── Error body contract ─────────────────────────────────────────────────────

def test_error_body_contract_includes_all_required_fields(client):
    r = client.put("/api/v1/product-local/SKU-CONTRACT",
                   json={"hs_code_override": "99999998"}, headers=_HDR)
    assert r.status_code == 409
    detail = r.json()["detail"]
    # All four keys are mandatory.
    for k in ("error", "field", "entity", "key", "reason"):
        assert k in detail, f"missing {k} in error body: {detail}"
    assert detail["error"] == "reference_conflict"
    assert detail["reason"] in ("missing", "inactive")


# ── Source-grep authority-isolation tests ───────────────────────────────────

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _files_importing(target: str):
    """Return all .py files under app/ that import the target module name."""
    pat = re.compile(rf"\b{target}\b")
    hits = []
    for py in _APP_ROOT.rglob("*.py"):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pat.search(src):
            hits.append(py)
    return hits


FORBIDDEN_DOMAIN_PREFIXES = (
    # PZ engine
    "pz_", "import_pz_", "global_pz_", "pz_correction_",
    # wFirma
    "wfirma",
    # DHL / customs
    "dhl_", "agency_", "customs_", "zc429", "sad_",
    # Proforma / sales
    "proforma", "sales_",
    # FX engine
    "freight_resolver", "freight_authority", "freight_history_db",
    # Inventory engine writers
    "inventory_state_engine", "inventory_batch_state",
    "inventory_location_writer", "inventory_returns_writer",
    "inventory_sample_writer", "inventory_stage2_aggregator",
)


def _is_forbidden_domain(stem: str) -> bool:
    return any(stem == d or stem.startswith(d) for d in FORBIDDEN_DOMAIN_PREFIXES)


def test_forbidden_domains_do_not_import_master_reference_checks():
    """Lesson F authority isolation — RI helpers must not leak into
    wFirma / PZ / DHL / proforma / FX / inventory-state modules."""
    offenders = []
    for hit in _files_importing("master_reference_checks"):
        rel = hit.relative_to(_APP_ROOT)
        if _is_forbidden_domain(hit.stem):
            offenders.append(str(rel))
    assert not offenders, (
        f"Forbidden domain modules import master_reference_checks: {offenders}"
    )


def test_master_reference_checks_does_not_call_external_systems():
    """The helper module is pure-local: no HTTP, no NBP, no wFirma SDK,
    no DHL SDK, no smtp, no requests/httpx imports."""
    src = (_APP_ROOT / "services" / "master_reference_checks.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "from httpx",
                       "import smtplib", "wfirma_client", "nbp_client",
                       "dhl_client"):
        assert forbidden not in src, f"master_reference_checks must not reference {forbidden!r}"


def test_master_reference_checks_only_imports_local_master_modules():
    src = (_APP_ROOT / "services" / "master_reference_checks.py").read_text(encoding="utf-8")
    # Allowed lazy imports (inside functions only).
    allowed_imports = {"master_data_db", "customer_master_db",
                        "metals_db", "stones_db"}
    # Find every `from .X import` line.
    import_lines = re.findall(r"from\s+\.+([A-Za-z0-9_]+)", src)
    for mod in import_lines:
        assert mod in allowed_imports, \
            f"Unexpected import in master_reference_checks: {mod}"


# ── Phase 4C-ext — carrier reference integrity ─────────────────────────────

def _seed_carrier(client, code: str, *, active: bool = True) -> None:
    r = client.put(f"/api/v1/carriers-config/{code}",
                   json={"name": f"{code.upper()} test"}, headers=_HDR)
    assert r.status_code == 200, r.text
    if not active:
        d = client.delete(f"/api/v1/carriers-config/{code}", headers=_HDR)
        assert d.status_code == 204


def test_carrier_account_create_rejects_missing_carrier(client):
    _seed_customer(client, "W-CARR-MISS")
    # No carriers_config:dhl row exists.
    r = client.post("/api/v1/customer-master/W-CARR-MISS/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "A1"}, headers=_HDR)
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="dhl", reason="missing")


def test_carrier_account_create_rejects_inactive_carrier(client):
    _seed_customer(client, "W-CARR-INACT")
    _seed_carrier(client, "dhl", active=False)
    r = client.post("/api/v1/customer-master/W-CARR-INACT/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "A2"}, headers=_HDR)
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="dhl", reason="inactive")


def test_carrier_account_create_accepts_active_carrier(client):
    _seed_customer(client, "W-CARR-OK2")
    _seed_carrier(client, "dhl")
    r = client.post("/api/v1/customer-master/W-CARR-OK2/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "A3"}, headers=_HDR)
    assert r.status_code == 201, r.text


def test_carrier_account_restore_rejects_inactive_carrier(client):
    """Soft-delete an account, then soft-delete the carrier; restore must
    return 409 with reason=inactive."""
    _seed_customer(client, "W-CARR-RST-INACT")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-RST-INACT/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "RST"}, headers=_HDR,
    )
    assert create.status_code == 201
    acct_id = create.json()["id"]
    # Soft-delete the account.
    d = client.delete(
        f"/api/v1/customer-master/W-CARR-RST-INACT/carrier-accounts/{acct_id}",
        headers=_HDR,
    )
    assert d.status_code == 204
    # Soft-delete the carrier.
    client.delete("/api/v1/carriers-config/dhl", headers=_HDR)
    # Now restore — must fail with carrier inactive.
    r = client.post(
        f"/api/v1/customer-master/W-CARR-RST-INACT/carrier-accounts/{acct_id}/restore",
        headers=_HDR,
    )
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="dhl", reason="inactive")


def test_carrier_account_restore_rejects_missing_carrier(client, tmp_path):
    """Soft-delete an account, then hard-purge the carriers_config row via
    direct SQLite. Restore must return 409 with reason=missing."""
    _seed_customer(client, "W-CARR-RST-MISS")
    _seed_carrier(client, "fedex")
    create = client.post(
        "/api/v1/customer-master/W-CARR-RST-MISS/carrier-accounts/",
        json={"carrier": "fedex", "account_number": "RST2"}, headers=_HDR,
    )
    acct_id = create.json()["id"]
    client.delete(
        f"/api/v1/customer-master/W-CARR-RST-MISS/carrier-accounts/{acct_id}",
        headers=_HDR,
    )
    # Hard-purge the carrier row.
    import sqlite3
    with sqlite3.connect(tmp_path / "master_data.sqlite") as cx:
        cx.execute("DELETE FROM carriers_config WHERE carrier_code = ?",
                   ("fedex",))
        cx.commit()
    r = client.post(
        f"/api/v1/customer-master/W-CARR-RST-MISS/carrier-accounts/{acct_id}/restore",
        headers=_HDR,
    )
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="fedex", reason="missing")


def test_get_returns_existing_carrier_account_after_carrier_goes_inactive(client):
    """Legacy data must remain readable when its referenced carrier later
    becomes inactive."""
    _seed_customer(client, "W-CARR-LEGACY")
    _seed_carrier(client, "ups")
    create = client.post(
        "/api/v1/customer-master/W-CARR-LEGACY/carrier-accounts/",
        json={"carrier": "ups", "account_number": "LEGACY"}, headers=_HDR,
    )
    acct_id = create.json()["id"]
    # Soft-delete the carrier AFTER the account is created.
    client.delete("/api/v1/carriers-config/ups", headers=_HDR)
    # GET the existing account — still returns 200 with the now-stale ref.
    g = client.get(
        "/api/v1/customer-master/W-CARR-LEGACY/carrier-accounts/",
        headers=_HDR,
    )
    assert g.status_code == 200
    target = [a for a in g.json()["accounts"] if a["id"] == acct_id]
    assert len(target) == 1
    assert target[0]["carrier"] == "ups"


# ── Phase 4C-ext Wave 2 — carrier reference integrity on UPDATE ─────────────
# Ordering contract: 422 (body) → 404 (account missing) → 409 (carrier
# reference conflict) → write.

def test_carrier_account_update_rejects_missing_carrier(client):
    """PUT that switches the carrier to one absent from carriers_config must
    return 409 reason=missing — the update bypass is closed."""
    _seed_customer(client, "W-CARR-UPD-MISS")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-MISS/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "U1"}, headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    # fedex is a valid enum value but was never seeded into carriers_config.
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-MISS/carrier-accounts/{acct_id}",
        json={"carrier": "fedex", "account_number": "U1"}, headers=_HDR,
    )
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="fedex", reason="missing")


def test_carrier_account_update_rejects_inactive_carrier(client):
    """PUT that switches the carrier to a soft-deleted carrier must return
    409 reason=inactive."""
    _seed_customer(client, "W-CARR-UPD-INACT")
    _seed_carrier(client, "dhl")
    _seed_carrier(client, "fedex", active=False)
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-INACT/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "U2"}, headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-INACT/carrier-accounts/{acct_id}",
        json={"carrier": "fedex", "account_number": "U2"}, headers=_HDR,
    )
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="fedex", reason="inactive")


def test_carrier_account_update_accepts_active_carrier(client):
    """PUT preserving an active carrier persists the change (200)."""
    _seed_customer(client, "W-CARR-UPD-OK")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-OK/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "OLD"}, headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-OK/carrier-accounts/{acct_id}",
        json={"carrier": "dhl", "account_number": "NEW"}, headers=_HDR,
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_number"] == "NEW"


def test_carrier_account_update_422_wins_over_carrier_check(client):
    """A bad-enum carrier fails body validation (422) before the
    carriers_config authority check ever runs."""
    _seed_customer(client, "W-CARR-UPD-422")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-422/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "V1"}, headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-422/carrier-accounts/{acct_id}",
        json={"carrier": "invalidcarrier", "account_number": "V1"}, headers=_HDR,
    )
    assert r.status_code == 422, r.text


def test_carrier_account_update_404_wins_over_carrier_check(client):
    """A missing account returns 404 even when the supplied carrier would
    itself be a 409 reference conflict — the resource-not-found verdict takes
    precedence over the master-data conflict."""
    _seed_customer(client, "W-CARR-UPD-404")
    # 'fedex' is a valid enum value but is NOT seeded → would be 409 missing
    # if the carrier check ran first. The 404 (account missing) must win.
    r = client.put(
        "/api/v1/customer-master/W-CARR-UPD-404/carrier-accounts/999999",
        json={"carrier": "fedex", "account_number": "GHOST"}, headers=_HDR,
    )
    assert r.status_code == 404, r.text


def test_carrier_account_update_preserving_inactive_carrier_is_rejected(client):
    """INTENDED CONTRACT (task scope: 'set OR preserve'): an update that does
    not change the carrier but PRESERVES a reference to a now-inactive carrier
    is rejected with 409 inactive. This makes update consistent with restore,
    which already rejects inactive-carrier restores. Writes are gated even when
    the carrier value is unchanged; only GET stays readable for legacy rows."""
    _seed_customer(client, "W-CARR-UPD-PRESV")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-PRESV/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "P1", "account_name": "Old"},
        headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    # Carrier goes inactive AFTER the account was created (legacy scenario).
    client.delete("/api/v1/carriers-config/dhl", headers=_HDR)
    # Operator edits only account_name; carrier value is preserved (dhl).
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-PRESV/carrier-accounts/{acct_id}",
        json={"carrier": "dhl", "account_number": "P1", "account_name": "New"},
        headers=_HDR,
    )
    _assert_reference_conflict(r, field="carrier", entity="carriers_config",
                               key="dhl", reason="inactive")


def test_carrier_account_update_changes_name_with_active_carrier(client):
    """Non-carrier edits succeed (200) while the carrier remains active —
    confirms the write gate only blocks on a missing/inactive carrier, not on
    every update."""
    _seed_customer(client, "W-CARR-UPD-NAME")
    _seed_carrier(client, "dhl")
    create = client.post(
        "/api/v1/customer-master/W-CARR-UPD-NAME/carrier-accounts/",
        json={"carrier": "dhl", "account_number": "N1", "account_name": "Old"},
        headers=_HDR,
    )
    assert create.status_code == 201, create.text
    acct_id = create.json()["id"]
    r = client.put(
        f"/api/v1/customer-master/W-CARR-UPD-NAME/carrier-accounts/{acct_id}",
        json={"carrier": "dhl", "account_number": "N1", "account_name": "New"},
        headers=_HDR,
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_name"] == "New"


def test_phase4c_ext_uses_local_storage_only():
    """check_carrier_active must read only the local SQLite file, no
    external HTTP / wFirma / DHL call."""
    src = (_APP_ROOT / "services" / "master_reference_checks.py").read_text(encoding="utf-8")
    m = re.search(r"def check_carrier_active\([\s\S]+?(?=\ndef |\Z)", src)
    assert m, "check_carrier_active function not found"
    body = m.group(0)
    for forbidden in ("requests.", "httpx.", "wfirma_client", "dhl_client",
                       "nbp_client", "smtplib", "import requests",
                       "import httpx"):
        assert forbidden not in body, \
            f"check_carrier_active must not reference {forbidden!r}"


def test_phase4c_ext_dhl_runtime_does_not_import_reference_checks():
    """DHL runtime modules (carrier_actions/carrier_shadow/carrier_webhook/
    dhl_clearance/etc) must NOT import master_reference_checks."""
    offenders = []
    for hit in _files_importing("master_reference_checks"):
        rel = hit.relative_to(_APP_ROOT)
        stem = hit.stem
        if (stem.startswith("dhl_") or stem.startswith("agency_")
            or stem.startswith("customs_") or stem.startswith("carrier_")
            or stem.startswith("routes_carrier_")):
            offenders.append(str(rel))
    assert not offenders, (
        f"DHL/carrier runtime modules must not import master_reference_checks: "
        f"{offenders}"
    )


# ── End Phase 4C-ext ────────────────────────────────────────────────────────


def test_phase4c_does_not_modify_external_authority_writes():
    """Source-grep guarantee that Phase 4C only touched the four route
    files declared in scope. wFirma sync endpoints must remain on _auth
    with no RI check sandwiched in."""
    sync_files = (
        _APP_ROOT / "api" / "routes_customer_master.py",
        _APP_ROOT / "api" / "routes_suppliers.py",
    )
    for f in sync_files:
        src = f.read_text(encoding="utf-8")
        # Phase 4C must NOT have wired RI checks into wFirma sync paths.
        assert "check_customer_exists" not in src, \
            f"{f.name} must not import check_customer_exists (wFirma sync isolation)"
        assert "check_hs_code_active" not in src, \
            f"{f.name} must not import check_hs_code_active"

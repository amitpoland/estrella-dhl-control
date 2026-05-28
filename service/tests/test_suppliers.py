"""test_suppliers.py — DB layer + API layer tests for Suppliers master data.

Local-only registry. No wFirma, no PZ calculation. Pure additive CRUD.
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

from app.services.suppliers_db import (
    Supplier, init_db, validate_supplier,
    create_supplier, get_supplier, get_supplier_by_code,
    list_suppliers, update_supplier, delete_supplier,
)
from app.core.config import settings


# ── DB-layer tests ────────────────────────────────────────────────────────────

def test_init_db_idempotent(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    init_db(db)
    assert db.is_file()
    init_db(db)  # Must not raise


def test_validate_requires_supplier_code():
    errs = validate_supplier({"name": "X", "country": "IN"})
    assert any("supplier_code" in e for e in errs)


def test_validate_requires_name():
    errs = validate_supplier({"supplier_code": "S1", "country": "IN"})
    assert any("name" in e for e in errs)


def test_validate_requires_country():
    errs = validate_supplier({"supplier_code": "S1", "name": "Acme"})
    assert any("country" in e for e in errs)


def test_validate_rejects_non_iso_country():
    errs = validate_supplier({"supplier_code": "S1", "name": "Acme", "country": "INDIA"})
    assert any("country" in e for e in errs)


def test_validate_rejects_bad_email():
    errs = validate_supplier({"supplier_code": "S1", "name": "Acme",
                              "country": "IN", "contact_email": "not-an-email"})
    assert any("contact_email" in e for e in errs)


def test_validate_accepts_minimal_record():
    assert validate_supplier({"supplier_code": "S1", "name": "Acme", "country": "IN"}) == []


def test_create_returns_id(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    new_id = create_supplier(db, {"supplier_code": "ACME-IN", "name": "Acme India", "country": "IN"})
    assert isinstance(new_id, int) and new_id > 0


def test_create_normalises_country_to_upper(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    new_id = create_supplier(db, {"supplier_code": "S1", "name": "X", "country": "in"})
    rec = get_supplier(db, new_id)
    assert rec is not None
    assert rec.country == "IN"


def test_create_duplicate_code_raises(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    create_supplier(db, {"supplier_code": "DUP", "name": "A", "country": "IN"})
    with pytest.raises(ValueError, match="DUPLICATE_CODE"):
        create_supplier(db, {"supplier_code": "DUP", "name": "B", "country": "IN"})


def test_get_supplier_by_code(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    create_supplier(db, {"supplier_code": "CODE-1", "name": "X", "country": "IN"})
    rec = get_supplier_by_code(db, "CODE-1")
    assert rec is not None and rec.supplier_code == "CODE-1"


def test_list_returns_most_recent_first(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    create_supplier(db, {"supplier_code": "OLDER", "name": "Old", "country": "IN"})
    create_supplier(db, {"supplier_code": "NEWER", "name": "New", "country": "IN"})
    recs = list_suppliers(db)
    assert [r.supplier_code for r in recs] == ["NEWER", "OLDER"]


def test_list_filters_by_country(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    create_supplier(db, {"supplier_code": "IN1", "name": "A", "country": "IN"})
    create_supplier(db, {"supplier_code": "DE1", "name": "B", "country": "DE"})
    only_in = list_suppliers(db, country="IN")
    only_de = list_suppliers(db, country="DE")
    assert {r.supplier_code for r in only_in} == {"IN1"}
    assert {r.supplier_code for r in only_de} == {"DE1"}


def test_list_filters_by_active(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    create_supplier(db, {"supplier_code": "ACTIVE", "name": "A", "country": "IN", "active": True})
    create_supplier(db, {"supplier_code": "INACTIVE", "name": "B", "country": "IN", "active": False})
    on   = list_suppliers(db, active=True)
    off  = list_suppliers(db, active=False)
    assert {r.supplier_code for r in on}  == {"ACTIVE"}
    assert {r.supplier_code for r in off} == {"INACTIVE"}


def test_list_on_missing_db_returns_empty(tmp_path):
    assert list_suppliers(tmp_path / "missing.sqlite") == []


def test_update_merges_partial(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    sid = create_supplier(db, {"supplier_code": "P", "name": "Old", "country": "IN",
                                "address": "Old addr"})
    out = update_supplier(db, sid, {"name": "New", "vat_id": "GSTIN-1"})
    assert out is not None
    assert out.name    == "New"
    assert out.address == "Old addr"          # preserved
    assert out.vat_id  == "GSTIN-1"           # added
    assert out.country == "IN"                # preserved


def test_update_missing_returns_none(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    init_db(db)
    assert update_supplier(db, 9999, {"name": "X"}) is None


def test_update_to_duplicate_code_raises(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    a = create_supplier(db, {"supplier_code": "A", "name": "A", "country": "IN"})
    create_supplier(db, {"supplier_code": "B", "name": "B", "country": "IN"})
    with pytest.raises(ValueError, match="DUPLICATE_CODE"):
        update_supplier(db, a, {"supplier_code": "B"})


def test_delete_removes_row(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    sid = create_supplier(db, {"supplier_code": "DEL", "name": "X", "country": "IN"})
    assert delete_supplier(db, sid) is True
    assert get_supplier(db, sid) is None


def test_delete_unknown_returns_false(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    init_db(db)
    assert delete_supplier(db, 9999) is False


# ── API-layer tests ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def supp_api_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("suppliers_api")


@pytest.fixture(scope="module")
def supp_client(supp_api_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", supp_api_tmp):
        import app.api.routes_suppliers as mod
        mod._DB_PATH = supp_api_tmp / "suppliers.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_list_empty_fresh_db_200(supp_client):
    r = supp_client.get("/api/v1/suppliers/", headers=_hdr())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 0
    assert data["suppliers"] == []


def test_api_post_201_then_get(supp_client):
    r = supp_client.post(
        "/api/v1/suppliers/",
        json={"supplier_code": "API-1", "name": "API One", "country": "IN"},
        headers=_hdr(),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    sid = data["id"]
    assert data["supplier_code"] == "API-1"
    assert data["country"]        == "IN"
    g = supp_client.get(f"/api/v1/suppliers/{sid}", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["name"] == "API One"


def test_api_post_422_missing_required(supp_client):
    r = supp_client.post(
        "/api/v1/suppliers/",
        json={"name": "No code"},
        headers=_hdr(),
    )
    assert r.status_code == 422
    assert "validation_errors" in r.json()["detail"]


def test_api_post_409_duplicate_code(supp_client):
    supp_client.post(
        "/api/v1/suppliers/",
        json={"supplier_code": "DUP-API", "name": "First", "country": "IN"},
        headers=_hdr(),
    )
    r2 = supp_client.post(
        "/api/v1/suppliers/",
        json={"supplier_code": "DUP-API", "name": "Second", "country": "IN"},
        headers=_hdr(),
    )
    assert r2.status_code == 409


def test_api_put_200_partial_update(supp_client):
    r = supp_client.post(
        "/api/v1/suppliers/",
        json={"supplier_code": "PUT-API", "name": "Before", "country": "IN",
              "address": "Plot 1"},
        headers=_hdr(),
    )
    sid = r.json()["id"]
    r2 = supp_client.put(
        f"/api/v1/suppliers/{sid}",
        json={"name": "After", "contact_email": "ops@example.com"},
        headers=_hdr(),
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["name"]          == "After"
    assert data["address"]       == "Plot 1"               # preserved
    assert data["contact_email"] == "ops@example.com"      # added


def test_api_put_404_missing(supp_client):
    r = supp_client.put(
        "/api/v1/suppliers/99999",
        json={"name": "Ghost"},
        headers=_hdr(),
    )
    assert r.status_code == 404


def test_api_get_404_missing(supp_client):
    r = supp_client.get("/api/v1/suppliers/99999", headers=_hdr())
    assert r.status_code == 404


def test_api_delete_204_then_404(supp_client):
    r = supp_client.post(
        "/api/v1/suppliers/",
        json={"supplier_code": "DEL-API", "name": "ToDelete", "country": "IN"},
        headers=_hdr(),
    )
    sid = r.json()["id"]
    # Phase 4B Wave 3b-1: default DELETE is soft-delete. GET still returns
    # the (inactive) record.
    d = supp_client.delete(f"/api/v1/suppliers/{sid}", headers=_hdr())
    assert d.status_code == 204
    g = supp_client.get(f"/api/v1/suppliers/{sid}", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["active"] is False


def test_api_list_filters_active_param(supp_client):
    supp_client.post("/api/v1/suppliers/",
        json={"supplier_code": "FLT-A", "name": "A", "country": "IN", "active": True},
        headers=_hdr())
    supp_client.post("/api/v1/suppliers/",
        json={"supplier_code": "FLT-B", "name": "B", "country": "IN", "active": False},
        headers=_hdr())
    r = supp_client.get("/api/v1/suppliers/?active=false", headers=_hdr())
    assert r.status_code == 200
    codes = {s["supplier_code"] for s in r.json()["suppliers"]}
    assert "FLT-B" in codes
    assert "FLT-A" not in codes


def test_api_requires_auth_dependency_declared():
    """Source-grep guard: auth dependency must be wired in the route module."""
    from app.api import routes_suppliers as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "require_api_key" in src, \
        "routes_suppliers must declare require_api_key dependency"

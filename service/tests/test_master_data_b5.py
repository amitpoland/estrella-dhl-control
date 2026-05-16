"""test_master_data_b5.py — B5 HS Codes + Units + Product-Local tests.

DB layer + API layer. Local-only, additive. No wFirma, no PZ calculation.
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

from app.services.master_data_db import (
    init_db,
    validate_hs_code, upsert_hs_code, get_hs_code, list_hs_codes, delete_hs_code,
    validate_unit, upsert_unit, get_unit, list_units, delete_unit,
    validate_product_local, upsert_product_local, get_product_local,
    list_product_local, delete_product_local,
)
from app.core.config import settings


# ── DB: HS codes ──────────────────────────────────────────────────────────────

def test_init_db_idempotent(tmp_path):
    db = tmp_path / "md.sqlite"
    init_db(db); init_db(db)
    assert db.is_file()


def test_hs_validate_requires_code():
    assert any("hs_code" in e for e in validate_hs_code({}))


def test_hs_validate_requires_digits():
    errs = validate_hs_code({"hs_code": "ABC"})
    assert any("digits" in e for e in errs)


def test_hs_validate_rejects_bad_decimal():
    errs = validate_hs_code({"hs_code": "12345678", "duty_rate_pct": "not-a-number"})
    assert any("duty_rate_pct" in e for e in errs)


def test_hs_upsert_create(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = upsert_hs_code(db, {"hs_code": "71131900", "description_pl": "Bizuteria",
                              "duty_rate_pct": "2.5"})
    assert rec.hs_code == "71131900"
    assert rec.duty_rate_pct == "2.5"


def test_hs_upsert_update(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_hs_code(db, {"hs_code": "71131900", "description_pl": "Old"})
    rec = upsert_hs_code(db, {"hs_code": "71131900", "description_pl": "New", "active": False})
    assert rec.description_pl == "New"
    assert rec.active is False


def test_hs_list_filters_active(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_hs_code(db, {"hs_code": "11111111", "active": True})
    upsert_hs_code(db, {"hs_code": "22222222", "active": False})
    on  = list_hs_codes(db, active=True)
    off = list_hs_codes(db, active=False)
    assert {h.hs_code for h in on}  == {"11111111"}
    assert {h.hs_code for h in off} == {"22222222"}


def test_hs_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_hs_code(db, {"hs_code": "33333333"})
    assert delete_hs_code(db, "33333333") is True
    assert get_hs_code(db, "33333333") is None
    assert delete_hs_code(db, "33333333") is False


# ── DB: Units ─────────────────────────────────────────────────────────────────

def test_unit_validate_requires_code():
    assert any("code" in e for e in validate_unit({}))


def test_unit_upsert_create(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = upsert_unit(db, {"code": "pc", "name_pl": "szt.", "name_en": "piece", "unit_type": "count"})
    assert rec.code == "pc"
    assert rec.name_pl == "szt."


def test_unit_upsert_update(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_unit(db, {"code": "kg", "name_pl": "kg", "active": True})
    upsert_unit(db, {"code": "kg", "name_pl": "kg", "active": False})
    assert get_unit(db, "kg").active is False


def test_unit_list_and_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_unit(db, {"code": "g"})
    upsert_unit(db, {"code": "kg"})
    assert {u.code for u in list_units(db)} == {"g", "kg"}
    assert delete_unit(db, "g") is True
    assert {u.code for u in list_units(db)} == {"kg"}


# ── DB: Product local ────────────────────────────────────────────────────────

def test_pl_validate_requires_code():
    assert any("product_code" in e for e in validate_product_local({}))


def test_pl_upsert_create(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = upsert_product_local(db, {"product_code": "SKU1",
                                     "hs_code_override": "71131900",
                                     "unit_override": "pc"})
    assert rec.product_code == "SKU1"
    assert rec.hs_code_override == "71131900"


def test_pl_upsert_update(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_product_local(db, {"product_code": "SKU1", "hs_code_override": "111"})
    rec = upsert_product_local(db, {"product_code": "SKU1", "hs_code_override": "222"})
    assert rec.hs_code_override == "222"


def test_pl_list_and_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_product_local(db, {"product_code": "A"})
    upsert_product_local(db, {"product_code": "B"})
    assert {p.product_code for p in list_product_local(db)} == {"A", "B"}
    assert delete_product_local(db, "A") is True
    assert {p.product_code for p in list_product_local(db)} == {"B"}


def test_empty_db_lists_return_empty(tmp_path):
    db = tmp_path / "missing.sqlite"
    assert list_hs_codes(db) == []
    assert list_units(db) == []
    assert list_product_local(db) == []


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def md_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("master_data_b5")


@pytest.fixture(scope="module")
def md_client(md_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", md_tmp):
        import app.api.routes_master_data as mod
        mod._DB_PATH = md_tmp / "master_data.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── HS codes API ──────────────────────────────────────────────────────────────

def test_api_hs_list_empty_fresh_200(md_client):
    r = md_client.get("/api/v1/hs-codes/", headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0


def test_api_hs_put_then_get(md_client):
    r = md_client.put("/api/v1/hs-codes/71131900",
                      json={"description_pl": "Bizuteria", "duty_rate_pct": "2.5"},
                      headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.json()["hs_code"] == "71131900"
    g = md_client.get("/api/v1/hs-codes/71131900", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["duty_rate_pct"] == "2.5"


def test_api_hs_put_422_bad_code(md_client):
    r = md_client.put("/api/v1/hs-codes/ABCD",
                      json={"description_pl": "x"}, headers=_hdr())
    assert r.status_code == 422


def test_api_hs_delete_204_then_404(md_client):
    md_client.put("/api/v1/hs-codes/99999999", json={}, headers=_hdr())
    d = md_client.delete("/api/v1/hs-codes/99999999", headers=_hdr())
    assert d.status_code == 204
    g = md_client.get("/api/v1/hs-codes/99999999", headers=_hdr())
    assert g.status_code == 404


# ── Units API ─────────────────────────────────────────────────────────────────

def test_api_units_put_then_list(md_client):
    md_client.put("/api/v1/units/pc",
                  json={"name_pl": "szt.", "name_en": "piece", "unit_type": "count"},
                  headers=_hdr())
    md_client.put("/api/v1/units/kg",
                  json={"name_pl": "kg", "name_en": "kg", "unit_type": "weight"},
                  headers=_hdr())
    r = md_client.get("/api/v1/units/", headers=_hdr())
    codes = {u["code"] for u in r.json()["units"]}
    assert {"pc", "kg"}.issubset(codes)


def test_api_units_get_404(md_client):
    r = md_client.get("/api/v1/units/DOES_NOT_EXIST", headers=_hdr())
    assert r.status_code == 404


# ── Product-local API ─────────────────────────────────────────────────────────

def test_api_pl_full_lifecycle(md_client):
    p = md_client.put("/api/v1/product-local/SKU-API-1",
                      json={"hs_code_override": "71131900", "unit_override": "pc",
                            "notes": "set in test"},
                      headers=_hdr())
    assert p.status_code == 200, p.text
    assert p.json()["hs_code_override"] == "71131900"
    g = md_client.get("/api/v1/product-local/SKU-API-1", headers=_hdr())
    assert g.status_code == 200
    d = md_client.delete("/api/v1/product-local/SKU-API-1", headers=_hdr())
    assert d.status_code == 204


def test_api_pl_list_after_lifecycle(md_client):
    md_client.put("/api/v1/product-local/SKU-LIST-1",
                  json={"hs_code_override": "12345678"}, headers=_hdr())
    md_client.put("/api/v1/product-local/SKU-LIST-2",
                  json={"unit_override": "kg"}, headers=_hdr())
    r = md_client.get("/api/v1/product-local/", headers=_hdr())
    assert r.status_code == 200
    codes = {p["product_code"] for p in r.json()["items"]}
    assert "SKU-LIST-1" in codes
    assert "SKU-LIST-2" in codes


def test_api_auth_dependency_declared():
    from app.api import routes_master_data as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "require_api_key" in src

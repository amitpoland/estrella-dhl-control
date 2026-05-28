"""test_master_data_b7.py — B7 Incoterms + VAT config tests.

Local-only, additive. VAT config is reference-only and does NOT override
wFirma invoice VAT codes.
"""
from __future__ import annotations

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

from fastapi.testclient import TestClient

from app.services.master_data_db import (
    init_db,
    validate_incoterm, upsert_incoterm, get_incoterm, list_incoterms, delete_incoterm,
    validate_vat_config, create_vat_config, get_vat_config, list_vat_config,
    update_vat_config, delete_vat_config,
)
from app.core.config import settings


# ── Incoterms DB ──────────────────────────────────────────────────────────────

def test_incoterm_validate_requires_code():
    assert any("code" in e for e in validate_incoterm({}))


def test_incoterm_validate_rejects_bad_code():
    errs = validate_incoterm({"code": "FOOBAR"})
    assert any("3 uppercase letters" in e for e in errs)


def test_incoterm_upsert_create(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = upsert_incoterm(db, {"code": "exw", "name": "Ex Works",
                                "freight_included": False, "active": True})
    assert rec.code == "EXW"
    assert rec.name == "Ex Works"


def test_incoterm_upsert_update(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_incoterm(db, {"code": "FOB", "name": "Old"})
    rec = upsert_incoterm(db, {"code": "FOB", "name": "Free On Board",
                                "freight_included": True})
    assert rec.name == "Free On Board"
    assert rec.freight_included is True


def test_incoterm_list_and_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_incoterm(db, {"code": "EXW"})
    upsert_incoterm(db, {"code": "CIF"})
    assert {i.code for i in list_incoterms(db)} == {"EXW", "CIF"}
    assert delete_incoterm(db, "EXW") is True
    assert get_incoterm(db, "EXW") is None


def test_incoterm_empty_db_lists_empty(tmp_path):
    assert list_incoterms(tmp_path / "missing.sqlite") == []


# ── VAT config DB ─────────────────────────────────────────────────────────────

def test_vat_validate_requires_country():
    assert any("country" in e for e in validate_vat_config({}))


def test_vat_validate_rejects_non_iso():
    errs = validate_vat_config({"country": "POLAND"})
    assert any("country" in e for e in errs)


def test_vat_validate_rejects_bad_rate():
    errs = validate_vat_config({"country": "DE", "rate_pct": "not-a-number"})
    assert any("rate_pct" in e for e in errs)


def test_vat_create_and_get(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_vat_config(db, {"country": "de", "rate_pct": "19", "rate_code": "S"})
    assert rec.country == "DE"
    assert rec.rate_pct == "19"
    got = get_vat_config(db, rec.id)
    assert got is not None


def test_vat_list_filters(tmp_path):
    db = tmp_path / "md.sqlite"
    create_vat_config(db, {"country": "DE", "rate_pct": "19", "active": True})
    create_vat_config(db, {"country": "PL", "rate_pct": "23", "active": True})
    create_vat_config(db, {"country": "DE", "rate_pct": "7", "active": False})
    only_de = list_vat_config(db, country="DE")
    on      = list_vat_config(db, active=True)
    assert len(only_de) == 2
    assert {v.rate_pct for v in on} == {"19", "23"}


def test_vat_update_merges(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_vat_config(db, {"country": "DE", "rate_pct": "19"})
    updated = update_vat_config(db, rec.id, {"rate_pct": "7", "product_type": "books"})
    assert updated.rate_pct      == "7"
    assert updated.product_type  == "books"
    assert updated.country       == "DE"  # preserved


def test_vat_update_missing_returns_none(tmp_path):
    db = tmp_path / "md.sqlite"
    init_db(db)
    assert update_vat_config(db, 9999, {"rate_pct": "0"}) is None


def test_vat_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_vat_config(db, {"country": "FR", "rate_pct": "20"})
    assert delete_vat_config(db, rec.id) is True
    assert get_vat_config(db, rec.id) is None
    assert delete_vat_config(db, rec.id) is False


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def b7_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("master_data_b7")


@pytest.fixture(scope="module")
def b7_client(b7_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", b7_tmp):
        import app.api.routes_master_data as mod
        mod._DB_PATH = b7_tmp / "master_data.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_incoterms_lifecycle(b7_client):
    p = b7_client.put("/api/v1/incoterms/EXW",
                      json={"name": "Ex Works", "freight_included": False},
                      headers=_hdr())
    assert p.status_code == 200
    g = b7_client.get("/api/v1/incoterms/EXW", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["name"] == "Ex Works"
    l = b7_client.get("/api/v1/incoterms/", headers=_hdr())
    assert l.status_code == 200
    assert any(i["code"] == "EXW" for i in l.json()["incoterms"])
    d = b7_client.delete("/api/v1/incoterms/EXW", headers=_hdr())
    assert d.status_code == 204


def test_api_incoterms_put_422_bad_code(b7_client):
    r = b7_client.put("/api/v1/incoterms/foobar", json={"name": "X"}, headers=_hdr())
    assert r.status_code == 422


def test_api_vat_full_lifecycle(b7_client):
    c = b7_client.post("/api/v1/vat-config/",
                       json={"country": "DE", "rate_pct": "19", "rate_code": "S"},
                       headers=_hdr())
    assert c.status_code == 201, c.text
    vid = c.json()["id"]
    u = b7_client.put(f"/api/v1/vat-config/{vid}",
                      json={"rate_pct": "7", "product_type": "books"},
                      headers=_hdr())
    assert u.status_code == 200
    assert u.json()["rate_pct"] == "7"
    l = b7_client.get("/api/v1/vat-config/?country=DE", headers=_hdr())
    assert l.status_code == 200
    # Phase 4B Wave 1: default DELETE is soft-delete — GET still returns
    # the (inactive) record.
    d = b7_client.delete(f"/api/v1/vat-config/{vid}", headers=_hdr())
    assert d.status_code == 204
    g = b7_client.get(f"/api/v1/vat-config/{vid}", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["active"] is False


def test_api_vat_post_422_bad_country(b7_client):
    r = b7_client.post("/api/v1/vat-config/", json={"country": "POL"}, headers=_hdr())
    assert r.status_code == 422

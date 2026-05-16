"""test_master_data_b9.py — Carrier configuration registry tests.

LOCAL, NON-SECRET only. Does NOT mutate any DHL/FedEx/UPS live integration.
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
    validate_carrier_config, upsert_carrier_config, get_carrier_config,
    list_carrier_configs, delete_carrier_config, init_db,
)
from app.core.config import settings


# ── DB ────────────────────────────────────────────────────────────────────────

def test_carrier_validate_requires_code():
    assert any("carrier_code" in e for e in validate_carrier_config({}))


def test_carrier_validate_rejects_uppercase_code():
    errs = validate_carrier_config({"carrier_code": "DHL"})
    assert any("carrier_code" in e for e in errs)


def test_carrier_validate_rejects_special_chars():
    errs = validate_carrier_config({"carrier_code": "dhl-emea"})
    assert any("carrier_code" in e for e in errs)


def test_carrier_validate_rejects_bad_api_type():
    errs = validate_carrier_config({"carrier_code": "dhl", "api_type": "INVALID"})
    assert any("api_type" in e for e in errs)


def test_carrier_validate_rejects_bad_email():
    errs = validate_carrier_config({"carrier_code": "dhl",
                                    "inbox_email": "not-an-email"})
    assert any("inbox_email" in e for e in errs)


def test_carrier_validate_rejects_secret_fields():
    """Hard-rule guard: must NOT accept credential-shaped fields."""
    for forbidden in ("api_key", "api_secret", "password", "token",
                      "client_secret", "credentials"):
        errs = validate_carrier_config({"carrier_code": "dhl", forbidden: "x"})
        assert any("secret" in e.lower() for e in errs), \
            f"validator must reject secret-like field: {forbidden}"


def test_carrier_validate_accepts_minimal():
    assert validate_carrier_config({"carrier_code": "dhl"}) == []


def test_carrier_upsert_create(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = upsert_carrier_config(db, {
        "carrier_code": "dhl", "name": "DHL Express",
        "parser_type": "dhl_emea", "api_type": "api",
        "supported_services": "EXPRESS_WORLDWIDE,EXPRESS_12_00",
    })
    assert rec.carrier_code == "dhl"
    assert rec.api_type == "api"


def test_carrier_upsert_update(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_carrier_config(db, {"carrier_code": "fedex", "name": "Old"})
    rec = upsert_carrier_config(db, {"carrier_code": "fedex", "name": "FedEx Express",
                                      "api_type": "portal"})
    assert rec.name == "FedEx Express"
    assert rec.api_type == "portal"


def test_carrier_lower_case_normalised(tmp_path):
    db = tmp_path / "md.sqlite"
    # The validator rejects upper-case, but if a future call route passed it
    # lower-case anyway, the DB layer normalises on read/write.
    rec = upsert_carrier_config(db, {"carrier_code": "ups", "name": "UPS"})
    assert get_carrier_config(db, "UPS").carrier_code == "ups"


def test_carrier_list_and_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_carrier_config(db, {"carrier_code": "dhl"})
    upsert_carrier_config(db, {"carrier_code": "fedex"})
    assert {c.carrier_code for c in list_carrier_configs(db)} == {"dhl", "fedex"}
    assert delete_carrier_config(db, "dhl") is True
    assert get_carrier_config(db, "dhl") is None


def test_carrier_list_filters_active(tmp_path):
    db = tmp_path / "md.sqlite"
    upsert_carrier_config(db, {"carrier_code": "dhl", "active": True})
    upsert_carrier_config(db, {"carrier_code": "ups", "active": False})
    on = list_carrier_configs(db, active=True)
    assert {c.carrier_code for c in on} == {"dhl"}


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def b9_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("master_data_b9")


@pytest.fixture(scope="module")
def b9_client(b9_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", b9_tmp):
        import app.api.routes_master_data as mod
        mod._DB_PATH = b9_tmp / "master_data.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_carrier_lifecycle(b9_client):
    p = b9_client.put("/api/v1/carriers-config/dhl",
                      json={"name": "DHL Express", "parser_type": "dhl_emea",
                            "api_type": "api"},
                      headers=_hdr())
    assert p.status_code == 200
    g = b9_client.get("/api/v1/carriers-config/dhl", headers=_hdr())
    assert g.status_code == 200
    assert g.json()["name"] == "DHL Express"
    d = b9_client.delete("/api/v1/carriers-config/dhl", headers=_hdr())
    assert d.status_code == 204
    g404 = b9_client.get("/api/v1/carriers-config/dhl", headers=_hdr())
    assert g404.status_code == 404


def test_api_carrier_put_422_bad_code(b9_client):
    r = b9_client.put("/api/v1/carriers-config/DHL", json={"name": "X"}, headers=_hdr())
    assert r.status_code == 422


def test_api_carrier_rejects_secrets(b9_client):
    r = b9_client.put("/api/v1/carriers-config/test",
                      json={"name": "T", "api_key": "should-not-store"},
                      headers=_hdr())
    assert r.status_code == 422
    detail = r.json()["detail"]
    body = detail.get("validation_errors", []) if isinstance(detail, dict) else [str(detail)]
    assert any("secret" in str(e).lower() for e in body)


def test_carrier_config_does_not_touch_runtime():
    """Source-grep guard: routes_master_data must not import or call carrier
    runtime modules (carrier_actions, carrier_shadow, carrier_webhook)."""
    from app.api import routes_master_data as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("routes_carrier_actions", "routes_carrier_shadow",
                      "routes_carrier_webhook", "from .routes_carrier_"):
        assert forbidden not in src, \
            f"routes_master_data must not reference carrier runtime: {forbidden}"

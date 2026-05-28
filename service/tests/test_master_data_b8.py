"""test_master_data_b8.py — B8 FX rates reference table tests.

FX is REFERENCE-ONLY. The PZ engine does not read from this table. CRUD is
local and additive. The override layer (MDC-071) is forbidden by campaign
hard rules and is intentionally NOT implemented.
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
    validate_fx_rate, create_fx_rate, get_fx_rate, list_fx_rates,
    update_fx_rate, delete_fx_rate, init_db,
)
from app.core.config import settings


# ── DB ────────────────────────────────────────────────────────────────────────

def test_fx_validate_requires_date():
    assert any("rate_date" in e for e in validate_fx_rate(
        {"from_currency": "EUR", "to_currency": "PLN", "rate": "4.5"}))


def test_fx_validate_requires_currencies():
    e1 = validate_fx_rate({"rate_date": "2026-05-16", "from_currency": "EUR",
                            "rate": "4.5"})
    assert any("to_currency" in e for e in e1)


def test_fx_validate_rejects_non_iso_currency():
    errs = validate_fx_rate({"rate_date": "2026-05-16",
                              "from_currency": "EURO", "to_currency": "PLN",
                              "rate": "4.5"})
    assert any("from_currency" in e for e in errs)


def test_fx_validate_rejects_bad_date():
    errs = validate_fx_rate({"rate_date": "16/05/2026",
                              "from_currency": "EUR", "to_currency": "PLN",
                              "rate": "4.5"})
    assert any("rate_date" in e for e in errs)


def test_fx_validate_requires_rate():
    errs = validate_fx_rate({"rate_date": "2026-05-16",
                              "from_currency": "EUR", "to_currency": "PLN"})
    assert any("rate" in e for e in errs)


def test_fx_create_and_get(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_fx_rate(db, {"rate_date": "2026-05-16",
                               "from_currency": "eur", "to_currency": "pln",
                               "rate": "4.2580", "source": "NBP"})
    assert rec.from_currency == "EUR"
    assert rec.to_currency == "PLN"
    assert rec.rate == "4.2580"
    assert get_fx_rate(db, rec.id) is not None


def test_fx_list_filters(tmp_path):
    db = tmp_path / "md.sqlite"
    create_fx_rate(db, {"rate_date": "2026-05-15", "from_currency": "EUR",
                         "to_currency": "PLN", "rate": "4.25"})
    create_fx_rate(db, {"rate_date": "2026-05-16", "from_currency": "EUR",
                         "to_currency": "PLN", "rate": "4.26"})
    create_fx_rate(db, {"rate_date": "2026-05-16", "from_currency": "USD",
                         "to_currency": "PLN", "rate": "3.85"})
    pairs = list_fx_rates(db, from_currency="EUR", to_currency="PLN")
    by_date = list_fx_rates(db, rate_date="2026-05-16")
    assert len(pairs)   == 2
    assert len(by_date) == 2


def test_fx_update_merges(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_fx_rate(db, {"rate_date": "2026-05-16",
                               "from_currency": "EUR", "to_currency": "PLN",
                               "rate": "4.25"})
    upd = update_fx_rate(db, rec.id, {"rate": "4.30", "source": "ECB"})
    assert upd.rate   == "4.30"
    assert upd.source == "ECB"
    assert upd.from_currency == "EUR"     # preserved


def test_fx_delete(tmp_path):
    db = tmp_path / "md.sqlite"
    rec = create_fx_rate(db, {"rate_date": "2026-05-16",
                               "from_currency": "EUR", "to_currency": "PLN",
                               "rate": "4.25"})
    assert delete_fx_rate(db, rec.id) is True
    assert get_fx_rate(db, rec.id) is None
    assert delete_fx_rate(db, rec.id) is False


def test_fx_list_empty_db(tmp_path):
    assert list_fx_rates(tmp_path / "missing.sqlite") == []


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def b8_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("master_data_b8")


@pytest.fixture(scope="module")
def b8_client(b8_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", b8_tmp):
        import app.api.routes_master_data as mod
        mod._DB_PATH = b8_tmp / "master_data.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_api_fx_lifecycle(b8_client):
    c = b8_client.post("/api/v1/fx-rates/",
                       json={"rate_date": "2026-05-16",
                             "from_currency": "EUR", "to_currency": "PLN",
                             "rate": "4.2580", "source": "NBP"},
                       headers=_hdr())
    assert c.status_code == 201
    fid = c.json()["id"]
    u = b8_client.put(f"/api/v1/fx-rates/{fid}",
                      json={"rate": "4.30"}, headers=_hdr())
    assert u.status_code == 200
    assert u.json()["rate"] == "4.30"
    g = b8_client.get(f"/api/v1/fx-rates/{fid}", headers=_hdr())
    assert g.status_code == 200
    # Phase 4B Wave 1: default DELETE is soft-delete.
    d = b8_client.delete(f"/api/v1/fx-rates/{fid}", headers=_hdr())
    assert d.status_code == 204
    g_after = b8_client.get(f"/api/v1/fx-rates/{fid}", headers=_hdr())
    assert g_after.status_code == 200
    assert g_after.json()["active"] is False


def test_api_fx_post_422_validation(b8_client):
    r = b8_client.post("/api/v1/fx-rates/",
                       json={"rate_date": "bad-date",
                             "from_currency": "EUR", "to_currency": "PLN",
                             "rate": "4.25"},
                       headers=_hdr())
    assert r.status_code == 422


def test_api_fx_list_filtered(b8_client):
    b8_client.post("/api/v1/fx-rates/",
                   json={"rate_date": "2026-05-15", "from_currency": "USD",
                         "to_currency": "PLN", "rate": "3.85"},
                   headers=_hdr())
    r = b8_client.get("/api/v1/fx-rates/?from_currency=USD", headers=_hdr())
    assert r.status_code == 200
    assert all(f["from_currency"] == "USD" for f in r.json()["fx_rates"])


def test_pz_engine_never_reads_master_data_fx_rates():
    """Hard-rule guard. The PZ engine must never read from master_data.sqlite
    fx_rates table. Search the engine source for any reference."""
    engine_root = Path(__file__).resolve().parents[2]
    suspect_paths = [
        engine_root / "pz_import_processor.py",
        engine_root / "service" / "app" / "services" / "export_service.py",
    ]
    for p in suspect_paths:
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        assert "master_data.sqlite" not in src or "fx_rates" not in src, \
            f"PZ engine file must not reference master_data.sqlite fx_rates: {p}"

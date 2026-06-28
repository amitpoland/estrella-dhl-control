# service/tests/test_customer_master_wdt_series_serializer.py
"""
Pins that routes_customer_master._customer_to_dict serializes
preferred_wdt_invoice_series_id and preferred_export_invoice_series_id.

Regression: the route was returning these fields as absent/null even when
correctly stored in customer_master.sqlite. The bug was in _customer_to_dict,
not in the DB layer.
"""
from __future__ import annotations

import sys
import unittest.mock as _mock
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    api_tmp = tmp_path_factory.mktemp("wdt_series_serializer")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    with _mock.patch.object(settings, "storage_root", api_tmp):
        import app.api.routes_customer_master as mod
        mod._DB_PATH = api_tmp / "customer_master.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _hdr():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


_CID = "173845539"  # OMARA-style contractor ID


def test_wdt_and_export_series_survive_put_and_get(client):
    """PUT with WDT + export series → GET must return both fields."""
    body = {
        "bill_to_name":                     "OMARA s.r.o",
        "country":                          "CZ",
        "preferred_invoice_series_id":      "15827088",
        "preferred_wdt_invoice_series_id":  "15827921",
        "preferred_export_invoice_series_id": "15900001",
    }
    put_r = client.put(f"/api/v1/customer-master/{_CID}", json=body, headers=_hdr())
    assert put_r.status_code == 200, put_r.text

    get_r = client.get(f"/api/v1/customer-master/{_CID}", headers=_hdr())
    assert get_r.status_code == 200, get_r.text
    data = get_r.json()

    assert data.get("preferred_wdt_invoice_series_id") == "15827921", (
        f"preferred_wdt_invoice_series_id missing from GET response: {data}"
    )
    assert data.get("preferred_export_invoice_series_id") == "15900001", (
        f"preferred_export_invoice_series_id missing from GET response: {data}"
    )


def test_wdt_series_not_overwritten_by_null_on_second_put(client):
    """A second PUT that omits WDT series must not clear the stored value."""
    # Seed
    client.put(f"/api/v1/customer-master/{_CID}", headers=_hdr(), json={
        "bill_to_name":                     "OMARA s.r.o",
        "country":                          "CZ",
        "preferred_wdt_invoice_series_id":  "15827921",
        "preferred_export_invoice_series_id": "15900001",
    })
    # Re-PUT without the WDT/export fields
    client.put(f"/api/v1/customer-master/{_CID}", headers=_hdr(), json={
        "bill_to_name": "OMARA s.r.o",
        "country": "CZ",
    })
    get_r = client.get(f"/api/v1/customer-master/{_CID}", headers=_hdr())
    data = get_r.json()
    assert data.get("preferred_wdt_invoice_series_id") == "15827921", (
        "WDT series was wiped by a second PUT that omitted it"
    )

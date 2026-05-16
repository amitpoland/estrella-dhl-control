"""test_finance_postings_breakdown_route.py — Phase 6F.3 route tests.

Covers the single GET endpoint:
    GET /api/v1/finance/postings/{posting_id}/breakdown

Verifies:
  - 404 when posting missing
  - 200 + correct shape when posting exists
  - charges / payments / allocations / settlement / totals populated correctly
  - empty arrays + null settlement when sub-data missing
  - only GET is allowed (POST/PUT/PATCH/DELETE → 405)
  - schema_version surfaces
  - auth dependency declared at route module level
  - no write helpers called by the route module (source-grep)
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

from app.services import finance_postings_db as fpdb
from app.core.config import settings


# ── Test fixture: isolated storage root per module ──────────────────────────

@pytest.fixture(scope="module")
def fp_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("finance_postings_route")


@pytest.fixture(scope="module")
def fp_client(fp_tmp):
    from app.main import app
    with patch.object(settings, "storage_root", fp_tmp):
        import app.api.routes_finance_postings as mod
        mod._DB_PATH = fp_tmp / "finance_postings.sqlite"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, fp_tmp


def _hdr():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── 404 / empty / full lifecycle ────────────────────────────────────────────

def test_breakdown_404_when_posting_missing(fp_client):
    c, _ = fp_client
    r = c.get("/api/v1/finance/postings/99999/breakdown", headers=_hdr())
    assert r.status_code == 404
    body = r.json()
    assert "Posting not found" in body["detail"]


def test_breakdown_200_minimal_posting(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {
        "batch_id": "B1", "client_name": "Acme",
        "posting_kind": "invoice", "issued_total_minor": 0,
        "currency": "EUR",
    })
    r = c.get(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["posting_id"] == p.id
    assert body["schema_version"] == 1
    assert body["posting"]["id"] == p.id
    assert body["posting"]["batch_id"] == "B1"
    assert body["charges"] == []
    assert body["payments"] == []
    assert body["allocations"] == []
    assert body["settlement"] is None
    totals = body["totals"]
    assert totals["charge_total_minor"]  == 0
    assert totals["payment_total_minor"] == 0
    assert totals["balance_minor"]       == 0
    assert totals["is_fully_paid"]       is True  # 0 == 0


def test_breakdown_includes_charges_only_for_target_posting(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p1 = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                    "posting_kind": "invoice",
                                    "issued_total_minor": 0, "currency": "EUR"})
    p2 = fpdb.create_posting(db, {"batch_id": "B2", "client_name": "A",
                                    "posting_kind": "invoice",
                                    "issued_total_minor": 0, "currency": "EUR"})
    fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 100,
                             "currency": "EUR", "source": "operator",
                             "posting_id": p1.id})
    fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                             "charge_type": "insurance", "amount_minor": 50,
                             "currency": "EUR", "source": "operator",
                             "posting_id": p1.id})
    fpdb.create_charge(db, {"batch_id": "B2", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 999,
                             "currency": "EUR", "source": "operator",
                             "posting_id": p2.id})
    r = c.get(f"/api/v1/finance/postings/{p1.id}/breakdown", headers=_hdr())
    body = r.json()
    assert {ch["amount_minor"] for ch in body["charges"]} == {100, 50}
    assert all(ch["posting_id"] == p1.id for ch in body["charges"])


def test_breakdown_includes_payments_and_totals(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B-PAY", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 300, "currency": "EUR"})
    fpdb.create_charge(db, {"batch_id": "B-PAY", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 300,
                             "currency": "EUR", "source": "operator",
                             "posting_id": p.id})
    fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                              "amount_minor": 200, "currency": "EUR",
                              "source": "operator"})
    r = c.get(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    body = r.json()
    totals = body["totals"]
    assert totals["charge_total_minor"]  == 300
    assert totals["payment_total_minor"] == 200
    assert totals["balance_minor"]       == 100
    assert totals["is_fully_paid"]       is False
    assert len(body["payments"]) == 1
    assert body["payments"][0]["amount_minor"] == 200


def test_breakdown_includes_allocations_for_payment_only(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B-ALLOC", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 200, "currency": "EUR"})
    ch = fpdb.create_charge(db, {"batch_id": "B-ALLOC", "client_name": "A",
                                  "charge_type": "freight", "amount_minor": 200,
                                  "currency": "EUR", "source": "operator",
                                  "posting_id": p.id})
    pay = fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                                    "amount_minor": 200, "currency": "EUR",
                                    "source": "operator"})
    alloc = fpdb.create_allocation(db, {
        "payment_id": pay.id, "charge_id": ch.id,
        "applied_minor": 200, "allocation_method": "proportional",
    })
    r = c.get(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    body = r.json()
    assert len(body["allocations"]) == 1
    a = body["allocations"][0]
    assert a["id"] == alloc.id
    assert a["payment_id"] == pay.id
    assert a["charge_id"] == ch.id
    assert a["applied_minor"] == 200
    assert a["allocation_method"] == "proportional"


def test_breakdown_excludes_allocations_for_other_postings_payments(fp_client):
    """Allocations are only returned if their payment is attached to the
    requested posting."""
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p_a = fpdb.create_posting(db, {"batch_id": "B-A", "client_name": "X",
                                    "posting_kind": "invoice",
                                    "issued_total_minor": 100, "currency": "EUR"})
    p_b = fpdb.create_posting(db, {"batch_id": "B-B", "client_name": "X",
                                    "posting_kind": "invoice",
                                    "issued_total_minor": 100, "currency": "EUR"})
    ch_a = fpdb.create_charge(db, {"batch_id": "B-A", "client_name": "X",
                                    "charge_type": "freight", "amount_minor": 100,
                                    "currency": "EUR", "source": "operator",
                                    "posting_id": p_a.id})
    ch_b = fpdb.create_charge(db, {"batch_id": "B-B", "client_name": "X",
                                    "charge_type": "freight", "amount_minor": 100,
                                    "currency": "EUR", "source": "operator",
                                    "posting_id": p_b.id})
    pay_b = fpdb.create_payment(db, {"posting_id": p_b.id, "paid_at": "2026-05-16",
                                      "amount_minor": 100, "currency": "EUR",
                                      "source": "operator"})
    fpdb.create_allocation(db, {"payment_id": pay_b.id, "charge_id": ch_b.id,
                                 "applied_minor": 100,
                                 "allocation_method": "proportional"})
    r = c.get(f"/api/v1/finance/postings/{p_a.id}/breakdown", headers=_hdr())
    body = r.json()
    # The allocation belongs to posting B-B, not B-A — must NOT appear
    assert body["allocations"] == []


def test_breakdown_settlement_when_present(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B-SETTLED", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 100, "currency": "EUR"})
    fpdb.record_settlement(db, {"posting_id": p.id,
                                 "fx_delta_total_minor": 3,
                                 "rounding_diff_minor": 1})
    r = c.get(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    body = r.json()
    assert body["settlement"] is not None
    assert body["settlement"]["posting_id"] == p.id
    assert body["settlement"]["fx_delta_total_minor"] == 3
    assert body["settlement"]["rounding_diff_minor"]  == 1


def test_breakdown_settlement_null_when_absent(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B-NO-SETTLE", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 50, "currency": "EUR"})
    r = c.get(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    body = r.json()
    assert body["settlement"] is None


# ── Method-only and method-not-allowed ─────────────────────────────────────

def test_breakdown_405_on_post(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 0, "currency": "EUR"})
    r = c.post(f"/api/v1/finance/postings/{p.id}/breakdown", json={},
               headers=_hdr())
    assert r.status_code == 405


def test_breakdown_405_on_put(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 0, "currency": "EUR"})
    r = c.put(f"/api/v1/finance/postings/{p.id}/breakdown", json={},
              headers=_hdr())
    assert r.status_code == 405


def test_breakdown_405_on_delete(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 0, "currency": "EUR"})
    r = c.delete(f"/api/v1/finance/postings/{p.id}/breakdown", headers=_hdr())
    assert r.status_code == 405


def test_breakdown_405_on_patch(fp_client):
    c, tmp = fp_client
    db = tmp / "finance_postings.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "X",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 0, "currency": "EUR"})
    r = c.patch(f"/api/v1/finance/postings/{p.id}/breakdown", json={},
                headers=_hdr())
    assert r.status_code == 405


# ── No other routes on the same prefix ─────────────────────────────────────

def test_no_list_endpoint(fp_client):
    """GET /api/v1/finance/postings/ (list) was explicitly EXCLUDED in 6F.3."""
    c, _ = fp_client
    r = c.get("/api/v1/finance/postings/", headers=_hdr())
    # Without /{posting_id}/breakdown, FastAPI returns 404 or 405 for the bare path
    assert r.status_code in (404, 405)


def test_no_post_to_postings_root(fp_client):
    c, _ = fp_client
    r = c.post("/api/v1/finance/postings/", json={"x": 1}, headers=_hdr())
    assert r.status_code in (404, 405)


# ── Source-grep contract on the route module ───────────────────────────────

def test_route_module_imports_only_read_helpers():
    """The route module must NOT import any write helper from finance_postings_db."""
    from app.api import routes_finance_postings as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    forbidden_helpers = (
        "create_charge", "create_posting", "create_payment", "create_allocation",
        "record_settlement", "link_charge_to_posting",
    )
    for h in forbidden_helpers:
        assert h not in src, \
            f"6F.3 route module must NOT import write helper: {h}"


def test_route_module_declares_only_get_decorator():
    """No @router.post/put/patch/delete in the 6F.3 route module."""
    from app.api import routes_finance_postings as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("@router.post", "@router.put",
                      "@router.patch", "@router.delete"):
        assert forbidden not in src, \
            f"6F.3 route module must only use @router.get; found {forbidden}"


def test_route_module_declares_auth_dependency():
    from app.api import routes_finance_postings as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "require_api_key" in src, "auth dependency must be declared"
    assert "dependencies=[_auth]" in src or "Depends(require_api_key)" in src


def test_route_module_prefix_exact():
    from app.api import routes_finance_postings as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert 'prefix="/api/v1/finance/postings"' in src, \
        "Router prefix must be exactly /api/v1/finance/postings"


def test_route_module_no_engine_coupling():
    """The 6F.3 route module must not import from posting/settlement/FX/PZ/
    wFirma engines."""
    from app.api import routes_finance_postings as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "routes_proforma", "routes_wfirma", "routes_pz",
        "wfirma_client", "proforma_pz", "ledger_aggregator",
        "proforma_service_charges_db", "pz_import_processor",
    ):
        assert forbidden not in src, \
            f"6F.3 route must not couple to {forbidden}"

"""Insurance Export Statement — HTTP route tests.

Auth guard, validation, error mapping (422 UNKNOWN_IDS / 502 fetch), and
Lesson G no-store headers on the PDF download route. The service layer is
patched at the route-module import site; the PDF route runs the REAL
renderer against a stub selection.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.api.routes_insurance_export as routes_mod
from app.core.config import settings
from app.services.insurance_export_statement import (
    InsuranceExportFetchError,
    UnknownSelectionError,
)

BASE = "/api/v1/accounting/insurance-export"


def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app

    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


SENTINEL_REPORT = {
    "period": {"from": "2026-05-01", "to": "2026-05-31"},
    "generated_at": "2026-05-31T00:00:00Z",
    "contractors": [],
    "report_totals": {"sum_insured_inr_grand": "0.00"},
    "kpi": {},
    "query_stats": {},
}


def _stub_row(invoice_id="101"):
    return {
        "invoice_id": invoice_id,
        "contractor_id": "C-1",
        "contractor_name": "Alpha Exports Ltd",
        "fullnumber": "FV 1/2026",
        "date": "2026-05-10",
        "currency": "USD",
        "inv_cif": "2600.00",
        "plus_10_pct": "260.00",
        "sum_insured": "2860.00",
        "fx_rate": "88.467460",
        "sum_insured_inr": "253016.94",
        "insurance_recovered": {
            "amount": "45.67", "currency": "USD", "resolution": "manual_amount"
        },
    }


def _stub_selection():
    return {
        "period": {"from": "2026-05-01", "to": "2026-05-31"},
        "generated_at": "2026-05-31T00:00:00Z",
        "selected_rows": [_stub_row()],
        "selected_adjustments": [],
        "declaration_totals": {
            "sum_insured_inr_documents": "253016.94",
            "sum_insured_inr_adjustments": "0.00",
            "sum_insured_inr_grand": "253016.94",
            "insurance_recovered": {"USD": "45.67"},
            "documents": 1,
            "adjustments": 0,
            "rows_without_inr": 0,
        },
    }


# ── GET /insurance-export ────────────────────────────────────────────────


def test_get_report_happy_path(client, monkeypatch):
    calls = {}

    def _stub(df, dt, db_path=None, carrier_db_path=None, force=False):
        calls["args"] = (df, dt, force)
        return SENTINEL_REPORT

    monkeypatch.setattr(routes_mod, "assemble_insurance_export_report", _stub)
    r = client.get(
        BASE, params={"from": "2026-05-01", "to": "2026-05-31"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json() == SENTINEL_REPORT
    assert calls["args"] == ("2026-05-01", "2026-05-31", False)


def test_get_report_refresh_flag_forces(client, monkeypatch):
    calls = {}

    def _stub(df, dt, db_path=None, carrier_db_path=None, force=False):
        calls["force"] = force
        return SENTINEL_REPORT

    monkeypatch.setattr(routes_mod, "assemble_insurance_export_report", _stub)
    r = client.get(
        BASE,
        params={"from": "2026-05-01", "to": "2026-05-31", "refresh": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert calls["force"] is True


def test_get_report_requires_auth(client):
    # Activate the guard: with api_key unset, require_permission is dev-open.
    with patch.object(settings, "api_key", "active-key"):
        r = client.get(BASE, params={"from": "2026-05-01", "to": "2026-05-31"})
    assert r.status_code in (401, 403)


def test_get_report_rejects_bad_date(client):
    r = client.get(
        BASE, params={"from": "bad-date", "to": "2026-05-31"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "YYYY-MM-DD" in r.json()["detail"]


def test_get_report_rejects_inverted_period(client):
    r = client.get(
        BASE, params={"from": "2026-06-01", "to": "2026-05-01"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_get_report_missing_params_is_422(client):
    r = client.get(BASE, headers=_auth_headers())
    assert r.status_code == 422


def test_get_report_fetch_failure_maps_to_502(client, monkeypatch):
    def _boom(df, dt, db_path=None, carrier_db_path=None, force=False):
        raise InsuranceExportFetchError("wFirma unreachable")

    monkeypatch.setattr(routes_mod, "assemble_insurance_export_report", _boom)
    r = client.get(
        BASE, params={"from": "2026-05-01", "to": "2026-05-31"},
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    body = r.json()
    assert body["code"] == "INSURANCE_EXPORT_FETCH_FAILED"
    assert "wFirma unreachable" in body["detail"]


# ── POST declaration-preview ─────────────────────────────────────────────


PREVIEW = BASE + "/declaration-preview"


def test_preview_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        routes_mod,
        "resolve_declaration_selection",
        lambda df, dt, d, a, db_path=None, carrier_db_path=None: _stub_selection(),
    )
    r = client.post(
        PREVIEW,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": ["101"],
            "selected_adjustment_ids": [],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["declaration_totals"]["sum_insured_inr_grand"] == "253016.94"


def test_preview_requires_auth(client):
    with patch.object(settings, "api_key", "active-key"):
        r = client.post(PREVIEW, json={"period_from": "2026-05-01",
                                       "period_to": "2026-05-31"})
    assert r.status_code in (401, 403)


def test_preview_unknown_ids_is_422(client, monkeypatch):
    def _boom(df, dt, d, a, db_path=None, carrier_db_path=None):
        raise UnknownSelectionError(["999"])

    monkeypatch.setattr(routes_mod, "resolve_declaration_selection", _boom)
    r = client.post(
        PREVIEW,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": ["999"],
            "selected_adjustment_ids": [],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json() == {"code": "UNKNOWN_IDS", "unknown": ["999"]}


def test_preview_non_list_ids_is_400(client):
    r = client.post(
        PREVIEW,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": "101",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "must be a list" in r.json()["detail"]


# ── POST declaration.pdf ─────────────────────────────────────────────────


PDF = BASE + "/declaration.pdf"


def test_pdf_route_lesson_g_headers_and_filename(client, monkeypatch):
    monkeypatch.setattr(
        routes_mod,
        "resolve_declaration_selection",
        lambda df, dt, d, a, db_path=None, carrier_db_path=None: _stub_selection(),
    )
    r = client.post(
        PDF,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": ["101"],
            "selected_adjustment_ids": [],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    # Lesson G — regenerable artifact must never be cached.
    assert (
        r.headers["cache-control"]
        == "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert r.headers["pragma"] == "no-cache"
    assert r.headers["expires"] == "0"
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="insurance-export-2026-05-01-2026-05-31.pdf"'
    )


def test_pdf_route_requires_auth(client):
    with patch.object(settings, "api_key", "active-key"):
        r = client.post(PDF, json={"period_from": "2026-05-01",
                                   "period_to": "2026-05-31"})
    assert r.status_code in (401, 403)


def test_pdf_route_rejects_non_object_columns(client, monkeypatch):
    monkeypatch.setattr(
        routes_mod,
        "resolve_declaration_selection",
        lambda df, dt, d, a, db_path=None, carrier_db_path=None: _stub_selection(),
    )
    r = client.post(
        PDF,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": ["101"],
            "columns": ["insurance_recovered"],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    assert "columns must be an object" in r.json()["detail"]


def test_pdf_route_unknown_ids_is_422(client, monkeypatch):
    def _boom(df, dt, d, a, db_path=None, carrier_db_path=None):
        raise UnknownSelectionError(["777"])

    monkeypatch.setattr(routes_mod, "resolve_declaration_selection", _boom)
    r = client.post(
        PDF,
        json={
            "period_from": "2026-05-01",
            "period_to": "2026-05-31",
            "selected_document_ids": ["777"],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "UNKNOWN_IDS"


# ── charge-convergence: run + status ─────────────────────────────────────
#
# The write gate is the campaign's own safety claim, so it is pinned HERE at
# the HTTP layer, not only inside the service.

RUN = BASE + "/charge-convergence/run"
STATUS = BASE + "/charge-convergence/status"

DRY_RUN_SUMMARY = {
    "mode": "dry_run", "processed": 12, "created": 0, "updated": 0,
    "skipped": 4, "errors": 0, "last_error": None,
}


def _stub_run(monkeypatch, calls):
    def _run(**kwargs):
        calls.update(kwargs)
        return DRY_RUN_SUMMARY

    monkeypatch.setattr(routes_mod, "run_charge_convergence", _run)


def test_convergence_run_defaults_to_dry_run(client, monkeypatch):
    calls = {}
    _stub_run(monkeypatch, calls)
    r = client.post(RUN, headers=_auth_headers())

    assert r.status_code == 200
    assert r.json() == DRY_RUN_SUMMARY
    assert calls["apply"] is False          # dry run unless explicitly asked
    assert calls["date_from"] is None and calls["date_to"] is None
    # Lesson G — a reconciliation artifact is regenerable, never cached.
    assert r.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"


def test_convergence_run_passes_the_window_through(client, monkeypatch):
    calls = {}
    _stub_run(monkeypatch, calls)
    r = client.post(RUN, json={"from": "2026-01-01", "to": "2026-08-31"},
                    headers=_auth_headers())

    assert r.status_code == 200
    assert (calls["date_from"], calls["date_to"]) == ("2026-01-01", "2026-08-31")


def test_convergence_run_write_gate_off_is_409(client, monkeypatch):
    def _denied(**kwargs):
        raise routes_mod.ChargeConvergenceWriteDenied(
            "apply requested but COMMERCIAL_CHARGE_CONVERGENCE_APPLY_ENABLED is off")

    monkeypatch.setattr(routes_mod, "run_charge_convergence", _denied)
    r = client.post(RUN, json={"apply": True}, headers=_auth_headers())

    assert r.status_code == 409
    assert r.json()["code"] == "CHARGE_CONVERGENCE_WRITE_DISABLED"


def test_convergence_run_failure_is_502_and_keeps_what_was_measured(
    client, monkeypatch
):
    partial = dict(DRY_RUN_SUMMARY, errors=1, last_error="wFirma unreachable")

    def _boom(**kwargs):
        raise routes_mod.ChargeConvergenceError("wFirma unreachable", partial)

    monkeypatch.setattr(routes_mod, "run_charge_convergence", _boom)
    r = client.post(RUN, json={"months": 2}, headers=_auth_headers())

    assert r.status_code == 502
    body = r.json()
    assert body["code"] == "CHARGE_CONVERGENCE_FAILED"
    assert body["summary"] == partial       # a failure still reports its counts


@pytest.mark.parametrize("payload,fragment", [
    ({"from": "2026-01-01"}, "together"),
    ({"from": "bad-date", "to": "2026-08-31"}, "YYYY-MM-DD"),
    ({"from": "2026-08-31", "to": "2026-01-01"}, "is after"),
    ({"months": "two"}, "integer"),
    ({"months": 0}, "between"),
    ({"months": 121}, "between"),
])
def test_convergence_run_rejects_bad_input(client, monkeypatch, payload, fragment):
    def _never(**kwargs):
        raise AssertionError("validation must reject before the service runs")

    monkeypatch.setattr(routes_mod, "run_charge_convergence", _never)
    r = client.post(RUN, json=payload, headers=_auth_headers())

    assert r.status_code == 400
    assert fragment in r.json()["detail"]


def test_convergence_run_requires_auth(client):
    with patch.object(settings, "api_key", "active-key"):
        r = client.post(RUN, json={})
    assert r.status_code in (401, 403)


def test_convergence_status_answers_the_four_questions(client, monkeypatch):
    status = {
        "healthy": True, "running": False,
        "last_started_at": "2026-08-16T09:00:00Z",
        "last_completed_at": "2026-08-16T09:00:04Z",
        "duration_ms": 4000, "processed": 202, "created": 202, "updated": 0,
        "skipped": 92, "errors": 0, "last_error": None,
    }
    monkeypatch.setattr(routes_mod, "get_charge_convergence_status", lambda: status)
    r = client.get(STATUS, headers=_auth_headers())

    assert r.status_code == 200
    assert r.json() == status
    assert r.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"


def test_convergence_status_requires_auth(client):
    with patch.object(settings, "api_key", "active-key"):
        r = client.get(STATUS)
    assert r.status_code in (401, 403)

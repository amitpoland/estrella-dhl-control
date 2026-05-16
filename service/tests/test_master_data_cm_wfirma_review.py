"""test_master_data_cm_wfirma_review.py — B0 hotfix: Customer Master
identity-only review-and-assign, target selection, and existing-field
preservation.

Covers the defects reported on the production review panel:
1. HTTP 422 'missing bill_to_name and country' — apply now validates before
   constructing the dataclass and rejects gracefully (no TypeError leak).
2. Identity-only upsert preserves freight / insurance / KYC / shipping /
   invoice fields verbatim.
3. Operator target selector enforces explicit choice between
   customer_master / supplier_master / skip.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from decimal import Decimal

from service.app.services import customer_master_db as cmdb
from service.app.services import wfirma_client


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASH      = _REPO_ROOT / "service" / "app" / "static" / "dashboard.html"
_CM_ROUTE  = _REPO_ROOT / "service" / "app" / "api" / "routes_customer_master.py"


def _mk(wfid, name, nip="", country="PL"):
    return wfirma_client.WFirmaContractor(
        wfirma_id=wfid, name=name, nip=nip, country=country, zip="", city=""
    )


@pytest.fixture
def fake_contractors(monkeypatch):
    state = {"pages": [], "calls": 0}

    def _set(items):
        state["pages"] = [list(items), []]

    def _list_contractors_page(page, limit):
        state["calls"] += 1
        idx = page - 1
        if idx < 0 or idx >= len(state["pages"]):
            return []
        return state["pages"][idx]

    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list_contractors_page)
    return SimpleNamespace(set=_set, state=state)


def _make_app(monkeypatch, *, flag: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from service.app.api import routes_customer_master
    from service.app.core import config as core_config
    from service.app.core import security as core_security

    monkeypatch.setattr(core_config.settings, "wfirma_sync_customers_allowed", flag,
                        raising=False)
    app = FastAPI()
    app.include_router(routes_customer_master.router)
    app.dependency_overrides[core_security.require_api_key] = lambda: True
    return TestClient(app)


# ── 1. upsert_identity_only: required-field validation ──────────────────────

def test_upsert_identity_only_rejects_missing_country(tmp_path):
    db = tmp_path / "cm.sqlite"
    with pytest.raises(ValueError) as exc:
        cmdb.upsert_identity_only(
            db, bill_to_contractor_id="X1", bill_to_name="ACME", country="",
        )
    assert "country" in str(exc.value).lower()


def test_upsert_identity_only_rejects_missing_name(tmp_path):
    db = tmp_path / "cm.sqlite"
    with pytest.raises(ValueError) as exc:
        cmdb.upsert_identity_only(
            db, bill_to_contractor_id="X1", bill_to_name="", country="PL",
        )
    assert "bill_to_name" in str(exc.value)


def test_upsert_identity_only_inserts_minimum_row(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    res = cmdb.upsert_identity_only(
        db, bill_to_contractor_id="X1", bill_to_name="ACME LTD",
        country="PL", nip="PL1234567890",
    )
    assert res["action"] == "inserted"
    rec = cmdb.get_customer(db, "X1")
    assert rec is not None
    assert rec.bill_to_name == "ACME LTD"
    assert rec.country == "PL"
    assert rec.nip == "PL1234567890"


# ── 2. identity-only preserves existing freight/insurance/KYC ───────────────

def test_upsert_identity_only_preserves_freight_and_insurance_and_kyc(tmp_path):
    """The whole point of upsert_identity_only: re-running it on an existing
    row MUST NOT wipe freight_*/insurance_*/kuke_*/kyc_*/shipping_to_* values.
    Snapshot before → apply → snapshot after. Identity columns may change;
    everything else must be byte-identical."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    # Seed a real-world-shaped record with freight + insurance + KYC populated.
    seed = cmdb.CustomerMaster(
        bill_to_contractor_id="X42",
        bill_to_name="SUOKKO ORIGINAL",
        country="FI",
        nip="FI11112222",
        freight_service_id="FREIGHT-WF-13002743",
        freight_fixed_amount_eur=Decimal("180.00"),
        freight_label_pl="Koszt wysyłki",
        freight_currency="EUR",
        freight_mode="fixed",
        insurance_service_id="INS-WF-13102217",
        insurance_rate=Decimal("0.0050"),
        insurance_enabled=True,
        kuke_approved=True,
        kuke_limit=Decimal("250000"),
        kuke_currency="EUR",
        kyc_status="approved",
        beneficial_owner="J. Doe",
        compliance_notes="Anchor customer — never blank these.",
        ship_to_use_alternate=True,
        ship_to_street="Kuusamo 1",
        default_currency="EUR",
        preferred_proforma_series_id="PRO-2026",
        vat_mode=229,
        payment_terms_days=30,
    )
    cmdb.upsert_customer(db, seed)
    before = cmdb.get_customer(db, "X42")

    # Now apply identity-only update (rename + same country).
    res = cmdb.upsert_identity_only(
        db, bill_to_contractor_id="X42", bill_to_name="SUOKKO RENAMED",
        country="FI", nip="FI11112222",
    )
    assert res["action"] == "updated"
    after = cmdb.get_customer(db, "X42")

    # Identity changed.
    assert after.bill_to_name == "SUOKKO RENAMED"
    # Everything else preserved.
    for field in (
        "freight_service_id", "freight_fixed_amount_eur", "freight_label_pl",
        "freight_currency", "freight_mode",
        "insurance_service_id", "insurance_rate", "insurance_enabled",
        "kuke_approved", "kuke_limit", "kuke_currency",
        "kyc_status", "beneficial_owner", "compliance_notes",
        "ship_to_use_alternate", "ship_to_street",
        "default_currency", "preferred_proforma_series_id",
        "vat_mode", "payment_terms_days",
    ):
        assert getattr(after, field) == getattr(before, field), \
            f"identity-only upsert wiped {field}"


def test_upsert_identity_only_does_not_blank_existing_nip(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(db, bill_to_contractor_id="X1",
                              bill_to_name="ACME", country="PL", nip="PL999")
    # Apply again with empty nip — should keep existing
    cmdb.upsert_identity_only(db, bill_to_contractor_id="X1",
                              bill_to_name="ACME RENAMED", country="PL", nip=None)
    rec = cmdb.get_customer(db, "X1")
    assert rec.nip == "PL999"


# ── 3. preview endpoint returns proposals + suggested_target ────────────────

def test_cm_preview_returns_proposals_with_suggested_target(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([
        _mk("P1", "ACME LTD",       nip="PL10", country="PL"),  # EU vat → customer
        _mk("P2", "DHL Express",    nip="",     country="DE"),  # expense keyword → skip
        _mk("P3", "ESTRELLA JEWELS LLP", nip="IN12", country="IN"),  # exporter → supplier
        _mk("P4", "WEIRD CO",       nip="",     country=""),    # missing country → review
    ])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.get("/api/v1/customer-master/sync-from-wfirma/preview")
    assert r.status_code == 200
    body = r.json()
    by_id = {p["wfirma_id"]: p for p in body["proposals"]}
    assert by_id["P1"]["suggested_target"] == "customer_master"
    assert by_id["P2"]["suggested_target"] == "skip"
    assert by_id["P3"]["suggested_target"] == "supplier_master"
    assert by_id["P4"]["status"]           == "needs_operator_review"


# ── 4. apply blocked when flag is False ─────────────────────────────────────

def test_cm_apply_blocked_when_flag_false(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([_mk("B1", "ACME", nip="PL10", country="PL")])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["B1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "blocked"
    assert body["ok"] is False
    assert cmdb.list_customers(db, limit=10) == []


# ── 5. apply with valid row writes via identity-only path ──────────────────

def test_cm_apply_writes_via_identity_only(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([_mk("W1", "ACME LTD", nip="PL10", country="PL")])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["W1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "write"
    assert body["inserted"] == 1
    rec = cmdb.get_customer(db, "W1")
    assert rec.bill_to_name == "ACME LTD"
    assert rec.country == "PL"


# ── 6. apply rejects rows missing country WITHOUT 422 TypeError leak ────────

def test_cm_apply_rejects_missing_country_gracefully(tmp_path, fake_contractors, monkeypatch):
    """Reproduces the production 422 'missing bill_to_name and country':
    the apply path now classifies missing-country rows as
    needs_operator_review and returns them in `rejected`, never as 500/422
    from a TypeError on the dataclass constructor."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([_mk("BAD", "NAMEONLY", nip="PL1", country="")])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["BAD"]})
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] == 0
    assert body["updated"] == 0
    assert any(x["wfirma_id"] == "BAD" for x in body["rejected"])
    assert cmdb.list_customers(db, limit=10) == []


# ── 7. apply preserves existing freight/insurance/KYC end-to-end ────────────

def test_cm_apply_preserves_existing_freight_insurance_kyc(tmp_path, fake_contractors, monkeypatch):
    """End-to-end via the HTTP apply endpoint — same KYC isolation as the
    unit-level test but exercising the route."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    seed = cmdb.CustomerMaster(
        bill_to_contractor_id="E2E", bill_to_name="ORIGINAL", country="PL",
        freight_service_id="FRT-X", freight_fixed_amount_eur=Decimal("210.00"),
        insurance_rate=Decimal("0.0050"), kyc_status="approved",
        kuke_limit=Decimal("50000"),
    )
    cmdb.upsert_customer(db, seed)
    fake_contractors.set([_mk("E2E", "RENAMED", nip="PL999", country="PL")])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["E2E"]})
    assert r.status_code == 200
    after = cmdb.get_customer(db, "E2E")
    assert after.bill_to_name           == "RENAMED"
    assert after.freight_service_id     == "FRT-X"
    assert after.freight_fixed_amount_eur == Decimal("210.00")
    assert after.insurance_rate         == Decimal("0.0050")
    assert after.kyc_status             == "approved"
    assert after.kuke_limit             == Decimal("50000")


# ── 8. apply rejects bad input shapes ───────────────────────────────────────

def test_cm_apply_requires_wfirma_ids_list(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply", json={"wfirma_ids": []})
    assert r.status_code == 422
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply", json={"wfirma_ids": [1]})
    assert r.status_code == 422


# ── 9. dashboard: target selector + per-target routing ──────────────────────

def _dash():
    if not _DASH.exists():
        pytest.skip("dashboard.html missing")
    return _DASH.read_text(encoding="utf-8", errors="replace")


def test_dashboard_has_target_selector():
    src = _dash()
    assert "${testidPrefix}-target-select" in src, \
        "WfReviewPanel must expose a per-row target selector"
    for opt in ('value="customer_master"', 'value="supplier_master"', 'value="skip"'):
        assert opt in src, f"target selector missing option {opt}"


def test_dashboard_review_table_has_assign_to_column():
    src = _dash()
    assert "'Assign to'" in src, "review table must show an 'Assign to' header"


def test_dashboard_cm_button_calls_new_preview_url():
    src = _dash()
    btn_idx = src.index('data-testid="master-cm-btn-fetch-wfirma"')
    block = src[btn_idx: btn_idx + 1500]
    assert "/api/v1/customer-master/sync-from-wfirma/preview" in block, \
        "Customer Master fetch button must call /api/v1/customer-master/sync-from-wfirma/preview"
    assert "?write=true" not in block, "must NOT auto-write"


def test_dashboard_review_panel_routes_to_correct_apply_endpoint():
    """The review panel must dispatch per-row by target:
    customer_master → /api/v1/customer-master/sync-from-wfirma/apply
    supplier_master → /api/v1/suppliers/sync-from-wfirma/apply
    """
    src = _dash()
    # Both endpoints referenced somewhere in the panel wiring
    assert "/api/v1/customer-master/sync-from-wfirma/apply" in src
    assert "/api/v1/suppliers/sync-from-wfirma/apply" in src
    # Per-row dispatch: rowTarget() drives the split
    assert "rowTarget(p) === 'customer_master'" in src
    assert "rowTarget(p) === 'supplier_master'" in src


def test_dashboard_assign_all_excludes_skip_and_review_rows():
    """Assign-all must skip rows whose target is skip OR needs_operator_review.
    Verified by the source filter expression."""
    src = _dash()
    # The eligibleRows filter expression in the WfReviewPanel must include
    # explicit guards for both 'skip' and 'needs_operator_review' status.
    assert "p.status !== 'needs_operator_review'" in src
    assert "rowTarget(p) === 'customer_master' || rowTarget(p) === 'supplier_master'" in src


def test_dashboard_per_row_assign_button_disabled_for_skip_target():
    """Save/Assign button must disable when row target is Skip or Needs review."""
    src = _dash()
    assert "rowTarget(p) === 'skip'" in src
    assert "rowTarget(p) === 'needs_operator_review'" in src


# ── 10. no wFirma write call ────────────────────────────────────────────────

def test_no_wfirma_write_method_in_cm_route():
    src = _CM_ROUTE.read_text(encoding="utf-8", errors="replace")
    for forbidden in ("create_customer", "create_contractor",
                      "update_contractor", "delete_contractor",
                      "post_invoice", "create_invoice", "issue_invoice"):
        assert f"{forbidden}(" not in src, \
            f"forbidden wFirma write call '{forbidden}(' present in routes_customer_master.py"


# ── 11. suggested_target deterministic ──────────────────────────────────────

def test_suggested_target_deterministic_examples():
    from service.app.api.routes_customer_master import _cm_suggest_target
    assert _cm_suggest_target("ACME LTD", "PL10", "PL")["suggested_target"] == "customer_master"
    assert _cm_suggest_target("DHL Express", "", "DE")["suggested_target"] == "skip"
    assert _cm_suggest_target("Estrella Jewels LLP", "IN1", "IN")["suggested_target"] == "supplier_master"
    assert _cm_suggest_target("UNKNOWN CO", "", "")["suggested_target"] == "needs_operator_review"

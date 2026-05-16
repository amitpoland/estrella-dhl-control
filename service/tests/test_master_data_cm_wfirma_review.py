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
#
# The rule is generic: for ANY client whose customer_master row carries
# non-empty commercial / settings fields, ``upsert_identity_only`` must
# never overwrite them. We prove this by parametrising across multiple
# distinct client shapes so the test cannot regress to one anchor example.


def _existing_client_with_commercial_defaults(label, **overrides):
    """Build a CustomerMaster seed with the commercial / settings fields
    populated. Each test case uses a different ``bill_to_contractor_id``
    and a different *combination* of populated columns so a pass proves
    the preservation rule, not one specific client."""
    base = dict(
        bill_to_contractor_id=f"CID-{label}",
        bill_to_name=f"CLIENT {label} ORIGINAL",
        country=overrides.pop("country", "PL"),
        nip=overrides.pop("nip", "PL11112222"),
        freight_service_id="FREIGHT-WF-13002743",
        freight_fixed_amount_eur=Decimal("180.00"),
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
        compliance_notes="Anchor client commercial defaults — must not be wiped.",
        ship_to_use_alternate=True,
        ship_to_street="Some street 1",
        default_currency="EUR",
        preferred_proforma_series_id="PRO-2026",
        preferred_invoice_series_id="INV-2026",
        vat_mode=229,
        payment_terms_days=30,
    )
    base.update(overrides)
    return cmdb.CustomerMaster(**base)


_PRESERVATION_CASES = [
    # Three shapes, three different field combinations populated, three
    # different countries — the test passes only if the rule is generic.
    ("ALPHA", {}),
    ("BETA",  {"freight_fixed_amount_usd": Decimal("210"),
               "freight_currency": "USD",
               "country": "DE", "nip": "DE556677",
               "default_currency": "USD",
               "preferred_invoice_series_id": "INV-DE-2026"}),
    ("GAMMA", {"freight_fixed_amount_eur": None,
               "freight_mode": None,
               "kuke_approved": False, "kuke_limit": Decimal("50000"),
               "compliance_notes": "Watch list — manual review only.",
               "country": "IT", "nip": "IT99887766"}),
]

_PRESERVATION_FIELDS = (
    "freight_service_id", "freight_fixed_amount_eur", "freight_fixed_amount_usd",
    "freight_currency", "freight_mode",
    "insurance_service_id", "insurance_rate", "insurance_enabled",
    "kuke_approved", "kuke_limit", "kuke_currency",
    "kyc_status", "beneficial_owner", "compliance_notes",
    "ship_to_use_alternate", "ship_to_street",
    "default_currency",
    "preferred_proforma_series_id", "preferred_invoice_series_id",
    "vat_mode", "payment_terms_days",
)


@pytest.mark.parametrize("label,overrides", _PRESERVATION_CASES)
def test_identity_sync_preserves_commercial_fields_for_any_client(label, overrides, tmp_path):
    """Generic preservation rule: across multiple distinct client shapes,
    a rename-via-identity-sync MUST keep every commercial/settings field
    byte-identical. This test stands in for the rule for all clients —
    not one named example."""
    db = tmp_path / f"cm-{label}.sqlite"
    cmdb.init_db(db)
    seed = _existing_client_with_commercial_defaults(label, **overrides)
    cmdb.upsert_customer(db, seed)
    before = cmdb.get_customer(db, seed.bill_to_contractor_id)

    # Apply identity-only update (rename, same country, same nip).
    res = cmdb.upsert_identity_only(
        db,
        bill_to_contractor_id=seed.bill_to_contractor_id,
        bill_to_name=f"CLIENT {label} RENAMED",
        country=seed.country,
        nip=seed.nip,
    )
    assert res["action"] == "updated"
    after = cmdb.get_customer(db, seed.bill_to_contractor_id)

    # Identity may change.
    assert after.bill_to_name == f"CLIENT {label} RENAMED"
    # Commercial / settings fields must NOT be touched.
    for field in _PRESERVATION_FIELDS:
        assert getattr(after, field) == getattr(before, field), \
            f"identity-only sync wiped {field!r} for client {label!r}"


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
    assert by_id["P1"]["suggested_target"] == "client_master"
    assert by_id["P2"]["suggested_target"] == "ignore"
    assert by_id["P3"]["suggested_target"] == "supplier_master"
    assert by_id["P4"]["status"]           == "needs_operator_review"


# ── 4. local apply is NOT gated by WFIRMA_SYNC_CUSTOMERS_ALLOWED ────────────
#
# B0 semantic fix (2026-05-16): the /sync-from-wfirma/apply endpoint writes
# to LOCAL customer_master only — it is not a wFirma write. Operator's
# authenticated click + X-API-Key are the protection. The legacy
# WFIRMA_SYNC_CUSTOMERS_ALLOWED flag is now reserved for the original
# /api/v1/wfirma/customers/sync (wfirma_customers mapping) endpoint.

def test_cm_apply_works_when_legacy_wfirma_flag_is_false(tmp_path, fake_contractors, monkeypatch):
    """Save/Assign on Customer Master must succeed even with the legacy
    WFIRMA_SYNC_CUSTOMERS_ALLOWED flag OFF — this is a LOCAL master write,
    not a wFirma write."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    fake_contractors.set([_mk("B1", "ACME LTD", nip="PL10", country="PL")])
    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["B1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "write"
    assert body["ok"] is True
    assert body["inserted"] == 1
    rec = cmdb.get_customer(db, "B1")
    assert rec is not None
    assert rec.bill_to_name == "ACME LTD"


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
    for opt in ('value="client_master"', 'value="supplier_master"', 'value="ignore"'):
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
    client_master   → /api/v1/customer-master/sync-from-wfirma/apply (legacy route name preserved)
    supplier_master → /api/v1/suppliers/sync-from-wfirma/apply
    """
    src = _dash()
    # Both endpoints referenced somewhere in the panel wiring
    assert "/api/v1/customer-master/sync-from-wfirma/apply" in src
    assert "/api/v1/suppliers/sync-from-wfirma/apply" in src
    # Per-row dispatch: rowTarget() drives the split on the canonical
    # resolver verdicts client_master / supplier_master.
    assert "rowTarget(p) === 'client_master'" in src
    assert "rowTarget(p) === 'supplier_master'" in src


def test_dashboard_assign_all_excludes_ignore_and_review_rows():
    """Assign-all must exclude rows whose target is ignore OR needs_operator_review."""
    src = _dash()
    assert "p.status !== 'needs_operator_review'" in src
    assert "rowTarget(p) === 'client_master' || rowTarget(p) === 'supplier_master'" in src


def test_dashboard_per_row_assign_button_disabled_for_ignore_target():
    """Save/Assign button must disable when row target is Ignore or Needs review."""
    src = _dash()
    assert "rowTarget(p) === 'ignore'" in src
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

def _mk_full(wfid, name, **kw):
    """Build a WFirmaContractor with optional enrichment fields."""
    base = dict(wfid=wfid, name=name, nip=kw.pop("nip", ""),
                country=kw.pop("country", "PL"))
    c = wfirma_client.WFirmaContractor(
        wfirma_id=base["wfid"], name=base["name"], nip=base["nip"],
        country=base["country"], zip=kw.pop("zip_", ""), city=kw.pop("city", ""),
    )
    # mutate optional attributes after init (dataclass is not frozen here)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ── 12. enrichment: customer apply fills empty bill_to_email + bank ─────────

def test_cm_apply_fills_empty_email_and_bank_account(tmp_path, monkeypatch):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    state = {"contractors": [
        _mk_full("E1", "FRESH LTD", nip="PL10", country="PL",
                 email="ops@fresh.example", account_payments="PL77 1234 5678 0001")
    ]}
    def _list(page, limit):
        return state["contractors"] if page == 1 else []
    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list)

    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["E1"]})
    assert r.status_code == 200
    rec = cmdb.get_customer(db, "E1")
    assert rec.bill_to_email == "ops@fresh.example"
    assert rec.bank_account  == "PL77 1234 5678 0001"
    assert rec.wfirma_sync_source == "review_assign"
    assert rec.last_wfirma_sync_at is not None


def test_cm_apply_does_not_overwrite_existing_email(tmp_path, monkeypatch):
    """COALESCE-NULLIF: existing non-empty local value beats wFirma."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(db, bill_to_contractor_id="E2",
                              bill_to_name="OLD NAME", country="PL",
                              bill_to_email="kept@local.example")
    state = {"contractors": [
        _mk_full("E2", "NEW NAME", nip="PL11", country="PL",
                 email="wfirma@remote.example")
    ]}
    def _list(page, limit):
        return state["contractors"] if page == 1 else []
    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list)

    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["E2"]})
    assert r.status_code == 200
    rec = cmdb.get_customer(db, "E2")
    # name refreshed
    assert rec.bill_to_name == "NEW NAME"
    # but operator-entered email NOT overwritten
    assert rec.bill_to_email == "kept@local.example"


def test_cm_preview_surfaces_mismatches(tmp_path, monkeypatch):
    """For a matched_existing row, when wFirma carries a value that differs
    from a non-empty local value, the preview must surface a mismatch entry
    (informational only — apply will NOT overwrite)."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(db, bill_to_contractor_id="M1",
                              bill_to_name="LOCAL NAME", country="PL",
                              bill_to_email="local@example.com")
    state = {"contractors": [
        _mk_full("M1", "WFIRMA NAME", nip="PL10", country="PL",
                 email="remote@example.com")
    ]}
    def _list(page, limit):
        return state["contractors"] if page == 1 else []
    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list)

    from service.app.api import routes_customer_master
    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.get("/api/v1/customer-master/sync-from-wfirma/preview")
    body = r.json()
    p = next(p for p in body["proposals"] if p["wfirma_id"] == "M1")
    assert p["status"] == "matched_existing"
    fields = {m["field"] for m in p["mismatches"]}
    assert "name" in fields
    assert "email" in fields


def test_dashboard_review_table_has_extended_columns():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    for col in ("'Phone'", "'Pay term'"):
        assert col in src, f"review table missing column header {col}"


# ── Two-master architecture contract (B0 follow-up 2026-05-16) ─────────────
#
# There are ONLY TWO operational masters: Client Master and Supplier Master.
# wFirma contractors are an enrichment source, not a third entity. The UI
# must never show "Customer Master" or any hybrid wording. The resolver
# must surface only the four canonical verdicts:
#   client_master | supplier_master | ignore | needs_operator_review


def test_dashboard_panel_label_is_client_master_only():
    """No visible 'Customer Master' anywhere. The label is 'Client Master'."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "label: 'Client Master'" in src, \
        "Master Data nav label must be 'Client Master'"
    assert "Customer Master" not in src, \
        "No operator-facing 'Customer Master' string is allowed anywhere"
    assert "Clients / Customer Master" not in src, \
        "Hybrid 'Clients / Customer Master' wording must be removed"


def test_dashboard_fetch_button_says_clients():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "Fetch clients from wFirma" in src, \
        "Fetch button label must be 'Fetch clients from wFirma'"
    assert "Fetch customers from wFirma" not in src, \
        "Legacy 'Fetch customers from wFirma' label must be retired"


def test_dashboard_target_selector_uses_canonical_two_master_options():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    # Canonical option values are the four resolver verdicts. Their visible
    # labels are Client Master / Supplier Master / Ignore / Needs review.
    assert '<option value="client_master">Client Master</option>' in src
    assert '<option value="supplier_master">Supplier Master</option>' in src
    assert '<option value="ignore">Ignore</option>' in src
    assert '<option value="needs_operator_review">Needs review</option>' in src
    # The retired hybrid value must be gone.
    assert '<option value="customer_master"' not in src, \
        "Legacy customer_master target value must be removed"
    assert '<option value="skip"' not in src, \
        "Legacy skip target value must be removed (renamed to ignore)"


def test_dashboard_review_title_is_canonical():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'title="wFirma contractor review"' in src
    assert "wFirma → Clients / Suppliers review" not in src
    assert "wFirma → Suppliers / Clients review" not in src
    assert "wFirma → Customer Master / Suppliers review" not in src


def test_dashboard_alerts_use_client_apply_phrasing():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "'Client applied=" in src
    assert "'Client apply blocked:" in src
    assert "'Client apply failed:" in src
    # Old phrasing retired
    assert "'Customer applied=" not in src
    assert "'Customer apply blocked:" not in src


def test_dashboard_invoices_advanced_section_present():
    """Technical wFirma IDs (proforma/invoice series, language) must live
    under an Advanced disclosure so normal-operator view is uncluttered."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="kyc-invoices-advanced"' in src
    assert "Show technical wFirma IDs" in src


def test_dashboard_freight_insurance_service_id_in_advanced_disclosure():
    """Inline freight/insurance edit form must keep the technical service
    ID inputs available for ops/debug (legacy testid contract) BUT collapse
    them behind an Advanced <details> disclosure so the normal-operator
    default view does not show them."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    # Locate the freight service ID input.
    fid_idx = src.index('data-testid="cm-edit-freight-service-id"')
    # Walk back to find the enclosing <details> — must exist between the
    # nearest "Edit freight" heading and the input.
    region = src[src.rindex("Edit freight", 0, fid_idx): fid_idx]
    assert "<details" in region, \
        "freight service ID must be inside a <details> disclosure"
    # Same for insurance.
    iid_idx = src.index('data-testid="cm-edit-insurance-service-id"')
    region2 = src[src.rindex("Insurance", 0, iid_idx): iid_idx]
    assert "<details" in region2, \
        "insurance service ID must be inside a <details> disclosure"


def test_suggested_target_deterministic_examples():
    from service.app.api.routes_customer_master import _cm_suggest_target
    assert _cm_suggest_target("ACME LTD", "PL10", "PL")["suggested_target"]      == "client_master"
    assert _cm_suggest_target("DHL Express", "", "DE")["suggested_target"]       == "ignore"
    assert _cm_suggest_target("Estrella Jewels LLP", "IN1", "IN")["suggested_target"] == "supplier_master"
    assert _cm_suggest_target("UNKNOWN CO", "", "")["suggested_target"]          == "needs_operator_review"


def test_resolver_emits_only_four_canonical_verdicts():
    """The resolver model is closed: every proposal's suggested_target must
    be one of {client_master, supplier_master, ignore, needs_operator_review}.
    No 'customer_master', no 'skip', no other hybrid values."""
    from service.app.api.routes_customer_master import _cm_suggest_target
    from service.app.services.suppliers_db import _suggest_target as _sup_suggest
    allowed = {"client_master", "supplier_master", "ignore", "needs_operator_review"}
    cases = [
        ("ACME LTD",            "PL10", "PL"),
        ("DHL Express",         "",     "DE"),
        ("Estrella Jewels LLP", "IN1",  "IN"),
        ("UNKNOWN CO",          "",     ""),
        ("Some Hotel",          "",     "FR"),
        ("Bank of Poland",      "PL5",  "PL"),
    ]
    for nm, vat, cty in cases:
        v_cm  = _cm_suggest_target(nm, vat, cty)["suggested_target"]
        v_sup = _sup_suggest(nm, vat, cty)["suggested_target"]
        assert v_cm  in allowed, f"resolver (CM)  emitted non-canonical verdict: {v_cm} for {nm}"
        assert v_sup in allowed, f"resolver (sup) emitted non-canonical verdict: {v_sup} for {nm}"

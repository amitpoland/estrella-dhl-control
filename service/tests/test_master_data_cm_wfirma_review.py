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
    """No visible 'Customer Master' anywhere (any case). The label is
    'Client Master'."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "label: 'Client Master'" in src, \
        "Master Data nav label must be 'Client Master'"
    # Case-insensitive scan: 'customer master' / 'CUSTOMER MASTER' / etc.
    import re as _re
    hits = _re.findall(r"customer\s+master", src, _re.IGNORECASE)
    assert hits == [], \
        f"No operator-facing 'customer master' string allowed anywhere (found {len(hits)}: {hits[:3]})"
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
    # B0 deep-enrichment 2026-05-16: Advanced disclosure now scopes to
    # the raw wFirma series IDs (language moved to default view as a
    # labelled dropdown).
    assert ("wFirma series IDs" in src) or ("Show technical wFirma IDs" in src), \
        "Advanced disclosure must have a summary label"


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


# ── B0 consolidation contract (Client Master single surface) ──────────────


def test_sidebar_has_no_separate_clients_entry():
    """Batch 2: the legacy 'Clients' sidebar entry is gone. Only the unified
    Client Master entry is offered."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    # The ENTITIES array must not declare a sidebar entry with id 'clients'.
    import re as _re
    hits = _re.findall(r"\{\s*id:\s*'clients'\s*,\s*label:", src)
    assert hits == [], "Legacy 'clients' sidebar entry must be removed from ENTITIES"
    # The unified Client Master entry stays.
    assert "id: 'customer_master',label: 'Client Master'" in src \
        or "id: 'customer_master', label: 'Client Master'" in src \
        or "id: 'customer_master',label: 'Client Master',   icon:" in src, \
        "Unified Client Master sidebar entry must be present"


def test_default_master_data_tab_is_customer_master():
    """Default activeEntity = customer_master so the consolidated tab opens
    on first load."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "React.useState('customer_master')" in src, \
        "Default activeEntity must be 'customer_master' so Client Master opens by default"


def test_view_mode_chips_present():
    """Batch 1: three view-mode chips inside the Client Master panel."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    for tid in ("cm-view-mode-chips", "cm-view-mode-master",
                "cm-view-mode-identity", "cm-view-mode-review"):
        assert f'data-testid="{tid}"' in src or f"data-testid={{`{tid}`}}" in src or \
               f'data-testid={{`cm-view-mode-${{m.id}}`}}' in src, \
            f"view-mode chip testid missing: {tid}"


def test_default_view_mode_is_master():
    """Default cmViewMode = 'master' so the existing CM table renders first."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "React.useState('master')" in src and "cmViewMode" in src, \
        "Default view-mode must be 'master'"


def test_identity_view_mode_renders_legacy_clients_panel():
    """The Clients/Identity panel renders BOTH when sidebar activeEntity is
    'clients' (legacy direct reach) AND when the operator switches to
    Identity view inside Client Master. The existing testids
    (master-clients-panel, master-customers-row, master-clients-btn-kyc,
    master-customers-sync) remain reachable through the view-mode switch."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    # The render-gate must include the Client-Master+Identity combination.
    assert "cmViewMode === 'identity'" in src
    # All legacy testids stay.
    for tid in ("master-clients-panel", "master-customers-row",
                "master-clients-btn-kyc", "master-customers-sync"):
        assert f'data-testid="{tid}"' in src, \
            f"legacy clients testid must remain reachable: {tid}"


def test_review_view_mode_pane_present():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="cm-view-mode-review-pane"' in src, \
        "Review view-mode must render a dedicated pane container"
    # Fetch button + review panel testids unchanged.
    assert 'data-testid="master-cm-btn-fetch-wfirma"' in src
    assert "${testidPrefix}-review-table" in src


def test_master_view_mode_wraps_existing_cm_content():
    """Master view-mode must still render the existing CM table and inline
    edit testids."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "cmViewMode === 'master'" in src
    for tid in ("master-customer-master-panel", "master-cm-btn-edit",
                "master-cm-btn-open-profile"):
        assert f'data-testid="{tid}"' in src, \
            f"legacy CM testid must remain reachable: {tid}"


def test_no_backend_routes_renamed_in_dashboard():
    """Backend route paths are unchanged. The dashboard still calls the
    legacy /api/v1/customer-master/* endpoints."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert "/api/v1/customer-master/" in src
    assert "/api/v1/customer-master/sync-from-wfirma/preview" in src
    assert "/api/v1/customer-master/sync-from-wfirma/apply" in src
    # No accidental rename to /api/v1/client-master/.
    assert "/api/v1/client-master/" not in src, \
        "Backend route path must remain /api/v1/customer-master/* (no rename in this batch)"


# ── B0 deep-enrichment 2026-05-16 ──────────────────────────────────────────


def test_upsert_identity_only_fills_empty_series_and_language(tmp_path):
    """Deep-enrichment new fields: language + series IDs + currency +
    payment terms all populate via the same fill-when-empty rule."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    res = cmdb.upsert_identity_only(
        db, bill_to_contractor_id="DE1", bill_to_name="DEEP CO",
        country="PL",
        bill_to_email="ops@deep.example",
        default_currency="EUR",
        payment_terms_days=30,
        default_language_id="LANG-EN",
        preferred_proforma_series_id="PRO-EUR-2026",
        preferred_invoice_series_id="INV-EUR-2026",
    )
    rec = cmdb.get_customer(db, "DE1")
    assert rec.default_currency             == "EUR"
    assert rec.payment_terms_days           == 30
    assert rec.default_language_id          == "LANG-EN"
    assert rec.preferred_proforma_series_id == "PRO-EUR-2026"
    assert rec.preferred_invoice_series_id  == "INV-EUR-2026"
    assert rec.wfirma_sync_source           == "review_assign"


def test_upsert_identity_only_preserves_operator_set_series(tmp_path):
    """Operator-set series and language survive a re-sync."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="DE2", bill_to_name="OLD NAME", country="PL",
        preferred_invoice_series_id="OPERATOR-INV-001",
        default_language_id="LANG-PL",
    )
    # Resync with new wFirma values — must NOT overwrite operator values.
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="DE2", bill_to_name="NEW NAME", country="PL",
        preferred_invoice_series_id="WF-INV-999",
        default_language_id="LANG-DE",
    )
    rec = cmdb.get_customer(db, "DE2")
    assert rec.bill_to_name                == "NEW NAME"  # identity refreshed
    assert rec.preferred_invoice_series_id == "OPERATOR-INV-001"
    assert rec.default_language_id         == "LANG-PL"


def test_dashboard_shipping_has_copy_billing_address_action():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="kyc-shipping-copy-billing"' in src, \
        "Shipping tab must expose a 'Copy billing address' affordance"


def test_wfirma_contractor_fetch_result_has_deep_enrichment_fields():
    """ContractorFetchResult dataclass must carry the deep-enrichment
    fields so the apply path can pull them through."""
    from service.app.services.wfirma_client import ContractorFetchResult
    r = ContractorFetchResult(ok=False)
    # B0 deep-enrichment 2026-05-17 — field names verified against live
    # wFirma XML (contractor 75483443). The old guess-based fields
    # (account_payments, payment_term, default_currency, invoiceseries_id,
    # proformaseries_id) were removed because wFirma does not expose them
    # at the contractor-detail endpoint.
    for field in ("email", "phone", "mobile",
                  "account_number",        # was account_payments
                  "payment_days",          # was payment_term
                  "translation_language_id",
                  "regon", "skype", "fax", "url", "description",
                  "buyer", "seller", "receiver", "tags",
                  "discount_percent", "payment_method"):
        assert hasattr(r, field), f"ContractorFetchResult missing field: {field}"


def test_apply_deep_fetches_and_preserves_local(tmp_path, monkeypatch):
    """End-to-end: apply uses fetch_contractor_by_id to pull commercial
    defaults and writes them ONLY into empty local cells. Pre-existing
    operator values in default_currency / payment_terms_days survive."""
    from service.app.services import wfirma_client
    from service.app.api import routes_customer_master

    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    # Pre-seed with an operator-set default_currency and a series id
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="DEEP1", bill_to_name="ALPHA", country="PL",
        default_currency="USD",
        preferred_invoice_series_id="OPERATOR-INV-100",
    )

    # Fake list-page → returns the bare identity row
    def _list(page, limit):
        if page == 1:
            return [wfirma_client.WFirmaContractor(
                wfirma_id="DEEP1", name="ALPHA", nip="PL10", country="PL")]
        return []
    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list)

    # Fake fetch_contractor_by_id → returns rich data using the VERIFIED
    # wFirma XML field names (PR #154 after live probe of contractor
    # 75483443). The operator's local default_currency override is preserved
    # because wFirma does NOT expose default_currency at the contractor
    # level — it stays operator-only.
    def _fetch(cid):
        return wfirma_client.ContractorFetchResult(
            ok=True, contractor_id=cid, name="ALPHA", nip="PL10", country="PL",
            email="deep@example.com", phone="+48 555 1111",
            account_number="PL90 1234 5678",   # was account_payments (wrong key)
            payment_days="14",                  # was payment_term (wrong key)
            translation_language_id="2",        # English in baseline dict
            street="ul. Test 1", city="Warsaw", zip="00-001",
        )
    monkeypatch.setattr(wfirma_client, "fetch_contractor_by_id", _fetch)

    monkeypatch.setattr(routes_customer_master, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/customer-master/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["DEEP1"]})
    assert r.status_code == 200

    rec = cmdb.get_customer(db, "DEEP1")
    # Fields the operator HAD NOT set get filled from deep-fetch:
    assert rec.bill_to_email      == "deep@example.com"
    assert rec.bill_to_phone      == "+48 555 1111"
    assert rec.bank_account       == "PL90 1234 5678"
    assert rec.payment_terms_days == 14
    assert rec.default_language_id == "2"
    assert rec.bill_to_street     == "ul. Test 1"
    assert rec.bill_to_city       == "Warsaw"
    assert rec.bill_to_postal_code == "00-001"
    # Fields the operator HAD set — preserved (operator authority wins):
    assert rec.default_currency             == "USD"
    assert rec.preferred_invoice_series_id  == "OPERATOR-INV-100"


# ── B0 deep-enrichment 2026-05-17 — parser keys verified against live XML ──


def test_parser_extracts_address_fields_from_fixture():
    """Real wFirma XML (contractor 75483443 / Railing) carries flat
    <street>, <zip>, <city>, <country>. The parser must extract them."""
    import xml.etree.ElementTree as ET
    from service.app.services import wfirma_client as wfc
    fixture = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <contractor>
      <id>75483443</id>
      <name>Railing sp z o.o.</name>
      <nip>5342428293</nip>
      <regon></regon>
      <street>302, KUSHWAH CHAMBERS,MAKWANA ROAD,MAROL NAKA,</street>
      <zip>40005</zip>
      <city>Katowice</city>
      <country>IN</country>
      <different_contact_address>0</different_contact_address>
      <email>Jyoti.b@estrellajewels.com</email>
      <payment_days>14</payment_days>
      <account_number>PL12 3456 7890</account_number>
      <translation_language><id>2</id></translation_language>
      <buyer>1</buyer>
      <seller>0</seller>
      <receiver>0</receiver>
    </contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""
    # Monkey-patch the underlying HTTP call via the public function path.
    import unittest.mock as _mock
    with _mock.patch.object(wfc, "_http_request", return_value=(200, fixture)):
        r = wfc.fetch_contractor_by_id("75483443")
    assert r.ok is True
    assert r.street    == "302, KUSHWAH CHAMBERS,MAKWANA ROAD,MAROL NAKA,"
    assert r.zip       == "40005"
    assert r.city      == "Katowice"
    assert r.country   == "IN"
    assert r.email     == "Jyoti.b@estrellajewels.com"
    assert r.payment_days       == "14"
    assert r.account_number     == "PL12 3456 7890"
    # Nested <translation_language><id>2</id></translation_language>
    assert r.translation_language_id == "2"
    # Role flags
    assert r.buyer    == "1"
    assert r.seller   == "0"
    assert r.receiver == "0"


def test_parser_drops_translation_language_id_zero_sentinel():
    """wFirma uses <translation_language><id>0</id></translation_language> as
    'no preference'. The parser must surface that as empty string, not '0'."""
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    fixture = """<?xml version="1.0"?><api><contractors><contractor>
      <id>1</id><name>X</name>
      <translation_language><id>0</id></translation_language>
    </contractor></contractors><status><code>OK</code></status></api>"""
    with _mock.patch.object(wfc, "_http_request", return_value=(200, fixture)):
        r = wfc.fetch_contractor_by_id("1")
    assert r.translation_language_id == ""


def test_parser_pulls_bank_account_from_nested_contractor_account():
    """Some contractors carry the bank account inside
    <contractor_account><number>X</number>; the parser must fall back to
    that when the flat <account_number> is empty."""
    import unittest.mock as _mock
    from service.app.services import wfirma_client as wfc
    fixture = """<?xml version="1.0"?><api><contractors><contractor>
      <id>2</id><name>Y</name>
      <account_number></account_number>
      <contractor_account>
        <number>PL99 NESTED 1234</number>
      </contractor_account>
    </contractor></contractors><status><code>OK</code></status></api>"""
    with _mock.patch.object(wfc, "_http_request", return_value=(200, fixture)):
        r = wfc.fetch_contractor_by_id("2")
    assert r.account_number == "PL99 NESTED 1234"


# ── B0 deep-enrichment 2026-05-17 — schema columns for bill-to address ─────


def test_upsert_identity_only_writes_bill_to_address(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    res = cmdb.upsert_identity_only(
        db, bill_to_contractor_id="ADDR1", bill_to_name="ADDR CO",
        country="PL",
        bill_to_street="ul. Marszalkowska 1",
        bill_to_city="Warsaw",
        bill_to_postal_code="00-001",
        regon="123456789",
    )
    assert res["action"] == "inserted"
    rec = cmdb.get_customer(db, "ADDR1")
    assert rec.bill_to_street      == "ul. Marszalkowska 1"
    assert rec.bill_to_city        == "Warsaw"
    assert rec.bill_to_postal_code == "00-001"
    assert rec.regon               == "123456789"


def test_upsert_identity_only_preserves_existing_bill_to_address(tmp_path):
    """Re-sync must NOT overwrite operator-edited address."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="ADDR2", bill_to_name="ADDR CO", country="PL",
        bill_to_street="OPERATOR EDIT", bill_to_city="OPERATOR CITY",
    )
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="ADDR2", bill_to_name="ADDR CO", country="PL",
        bill_to_street="WFIRMA STREET", bill_to_city="WFIRMA CITY",
    )
    rec = cmdb.get_customer(db, "ADDR2")
    assert rec.bill_to_street == "OPERATOR EDIT"
    assert rec.bill_to_city   == "OPERATOR CITY"


def test_inheritance_helper_surfaces_bill_to_address_when_alternate_off(tmp_path):
    """When ship_to_use_alternate=False, the effective ship-to address comes
    from bill_to_street/city/postal_code (now stored locally after deep-fetch)."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="INH1", bill_to_name="INH CO", country="PL",
        bill_to_street="ul. Wiejska 1", bill_to_city="Warsaw",
        bill_to_postal_code="00-002",
    )
    rec = cmdb.get_customer(db, "INH1")
    eff = cmdb.get_effective_defaults(rec)
    assert eff["ship_to_use_alternate"] is False
    assert eff["ship_to_street"] == "ul. Wiejska 1"
    assert eff["ship_to_city"]   == "Warsaw"
    assert eff["ship_to_zip"]    == "00-002"


def test_customer_to_dict_serializes_new_fields(tmp_path):
    """The API response shape must carry the new columns so the dashboard
    can render them in the Company / Basic and Shipping tabs."""
    from service.app.api.routes_customer_master import _customer_to_dict
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="SER1", bill_to_name="SER CO", country="PL",
        bill_to_street="X", bill_to_city="Y", bill_to_postal_code="00-9",
        regon="REG-1",
    )
    rec = cmdb.get_customer(db, "SER1")
    d = _customer_to_dict(rec)
    assert d["bill_to_street"]       == "X"
    assert d["bill_to_city"]         == "Y"
    assert d["bill_to_postal_code"]  == "00-9"
    assert d["regon"]                == "REG-1"
    # Operator-entered profile columns surface even when unset.
    for k in ("short_code", "client_type", "industry", "eori"):
        assert k in d


# ── B0 Client Profile UI polish — generic field binding (PR after #154) ───
#
# Rule: every Company / Basic field that has backend storage must be wired
# in the dashboard form, must have a real (non-disabled) input, and must NOT
# carry a BACKEND PENDING badge. The wiring is generic for every country —
# no Polish-only logic, no Railing/SUOKKO-specific code paths.


_BACKEND_WIRED_BASIC_FIELDS = (
    "kyc-basic-short-code",
    "kyc-basic-client-type",
    "kyc-basic-industry",
    "kyc-basic-bill-to-street",
    "kyc-basic-bill-to-postal",
    "kyc-basic-bill-to-city",
    "kyc-basic-bill-to-email",
    "kyc-basic-bill-to-phone",
    "kyc-basic-bill-to-mobile",
    "kyc-basic-eori",
    "kyc-basic-regon",
)


def test_company_basic_tab_binds_wired_fields():
    """Every wired Company / Basic field must render a real input with
    its testid present in the dashboard."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    for tid in _BACKEND_WIRED_BASIC_FIELDS:
        assert f'data-testid="{tid}"' in src, f"missing wired Basic field: {tid}"


def test_no_backend_pending_badge_for_wired_fields():
    """The Company / Basic tab must not show 'BACKEND PENDING' for any
    field that now has backend storage. We allow the badge to appear
    elsewhere in the dashboard (other genuinely-pending modules)."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    # Grab the Company / Basic panel block specifically.
    start = src.index('data-testid="kyc-panel-basic"')
    end = src.index('kycTab === \'shipping\'')
    block = src[start: end]
    # Each newly-wired field name must NOT carry the pendingBadge.
    for fname in ("short_code", "client_type", "industry", "EORI", "REGON",
                  "Short code", "Industry"):
        # Look for "<fname>{pendingBadge}" patterns specifically.
        bad = f"{fname}{{pendingBadge}}"
        assert bad not in block, \
            f"BACKEND PENDING badge still attached to wired field text {fname!r}"


def test_kyc_basic_form_state_binds_new_fields():
    """The ClientKycModal form-state initializer must read the new columns
    from custMasterRec so the inputs render their saved values."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    for field in ("bill_to_street", "bill_to_city", "bill_to_postal_code",
                  "bill_to_email", "bill_to_phone", "bill_to_mobile",
                  "regon", "short_code", "client_type", "industry", "eori",
                  "bank_account"):
        assert f"{field}:" in src and f"cm.{field}" in src, \
            f"form state must initialise from cm.{field}"


def test_put_payload_allow_list_includes_new_fields():
    """The dashboard PUT payload must coerce '' → null for every newly
    wired optional string field."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    start = src.index("CM_OPT_STR = [")
    end = src.index("];", start)
    block = src[start: end]
    for f in ("bill_to_street", "bill_to_city", "bill_to_postal_code",
              "bill_to_email", "bill_to_phone", "bill_to_mobile",
              "bank_account",
              "regon", "short_code", "client_type", "industry", "eori"):
        assert f"'{f}'" in block, f"CM_OPT_STR missing {f!r}"


def test_backend_put_allow_list_includes_new_fields():
    """routes_customer_master must accept the new fields and coerce '' →
    None for them (so blank inputs do not save as the empty string)."""
    route_src = (_REPO_ROOT / "service" / "app" / "api" /
                 "routes_customer_master.py").read_text(encoding="utf-8")
    start = route_src.index("_OPTIONAL_STR_FIELDS")
    end = route_src.index("})", start)
    block = route_src[start: end]
    for f in ("bill_to_street", "bill_to_city", "bill_to_postal_code",
              "bill_to_email", "bill_to_phone", "bill_to_mobile",
              "bank_account",
              "regon", "short_code", "client_type", "industry", "eori",
              "default_currency"):
        assert f'"{f}"' in block, f"backend _OPTIONAL_STR_FIELDS missing {f!r}"


def test_shipping_tab_renders_bill_to_summary():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="kyc-shipping-bill-to-summary"' in src, \
        "Shipping tab must render a bill-to address summary block"
    # The summary references the bill-to address fields generically.
    # Take the next ~1500 chars (covers the whole summary grid).
    start = src.index('data-testid="kyc-shipping-bill-to-summary"')
    block = src[start: start + 1500]
    assert "form.bill_to_street" in block
    assert "form.bill_to_postal_code" in block
    assert "form.bill_to_city" in block


def test_copy_billing_address_copies_full_address():
    """Copy billing address must populate street / city / zip / country /
    email / phone — not just name."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    start = src.index('data-testid="kyc-shipping-copy-billing"')
    end = src.index("title=", start)
    block = src[start: end]
    for fn in ("ship_to_street", "ship_to_city", "ship_to_zip",
               "ship_to_country", "ship_to_email", "ship_to_phone",
               "ship_to_name"):
        assert fn in block, f"Copy billing address must set {fn}"


def test_inheritance_hint_mentions_address_fields():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    start = src.index('data-testid="kyc-shipping-inheritance-hint"')
    end = src.index("</div>", start)
    block = src[start: end]
    # Hint must list the inherited fields generically (street / city / postal).
    assert "street" in block.lower()
    assert "postal" in block.lower() or "code" in block.lower()


def test_modal_subtitle_present():
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="client-kyc-modal-subtitle"' in src, \
        "Modal must show a tab-map subtitle under the title"


# ── Generic-across-countries contract ─────────────────────────────────────
#
# Every newly-wired Client Profile field must work for any country. These
# tests verify the code paths do not bake in a specific country.


def test_pl_client_round_trip_preserves_regon_and_nip(tmp_path):
    """PL client uses both NIP and REGON — both must round-trip."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="PL-1", bill_to_name="POL CO", country="PL",
        nip="PL1234567890", regon="987654321",
        bill_to_street="ul. Marszalkowska 1", bill_to_city="Warsaw",
        bill_to_postal_code="00-001",
    )
    rec = cmdb.get_customer(db, "PL-1")
    assert rec.country  == "PL"
    assert rec.nip      == "PL1234567890"
    assert rec.regon    == "987654321"
    assert rec.bill_to_street == "ul. Marszalkowska 1"


def test_eu_non_pl_client_uses_vat_eu_and_blank_regon(tmp_path):
    """EU non-PL client (e.g. DE) uses VAT EU number; REGON is blank."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="DE-1", bill_to_name="GERMAN GMBH",
        country="DE", nip="DE111222333",
        bill_to_street="Hauptstrasse 1", bill_to_city="Berlin",
        bill_to_postal_code="10115",
    )
    rec = cmdb.get_customer(db, "DE-1")
    assert rec.country  == "DE"
    assert rec.nip      == "DE111222333"
    assert rec.regon    is None
    assert rec.bill_to_city == "Berlin"
    # Inheritance helper must surface the non-PL address verbatim.
    eff = cmdb.get_effective_defaults(rec)
    assert eff["country"]      == "DE"
    assert eff["bill_to_city"] == "Berlin"
    assert eff["regon"]        is None


def test_non_eu_client_supports_any_address_format(tmp_path):
    """Non-EU client (e.g. IN) — address has no PL-specific format; the
    schema accepts any string for street/city/postal."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="IN-1", bill_to_name="INDIAN PVT LTD",
        country="IN", nip="GSTIN29ABCDE1234F1Z5",
        bill_to_street="Plot 12, MIDC Industrial Area", bill_to_city="Mumbai",
        bill_to_postal_code="400093",
    )
    rec = cmdb.get_customer(db, "IN-1")
    assert rec.country  == "IN"
    assert rec.nip      == "GSTIN29ABCDE1234F1Z5"
    assert rec.regon    is None
    assert rec.bill_to_postal_code == "400093"


def test_shipping_inheritance_works_across_countries(tmp_path):
    """ship_to_use_alternate=False inheritance must work for PL, DE, IN
    clients identically — no country-gating."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    for cid, country, city, postal, street in (
        ("PL-A", "PL", "Warsaw", "00-001", "ul. Test 1"),
        ("DE-A", "DE", "Berlin", "10115",  "Hauptstr 1"),
        ("IN-A", "IN", "Mumbai", "400001", "Marine Drive 1"),
    ):
        cmdb.upsert_identity_only(
            db, bill_to_contractor_id=cid, bill_to_name=f"{cid} CO",
            country=country, bill_to_street=street,
            bill_to_city=city, bill_to_postal_code=postal,
        )
        rec = cmdb.get_customer(db, cid)
        eff = cmdb.get_effective_defaults(rec)
        assert eff["ship_to_use_alternate"] is False
        assert eff["ship_to_street"]  == street, f"{cid}: street inheritance"
        assert eff["ship_to_city"]    == city,   f"{cid}: city inheritance"
        assert eff["ship_to_zip"]     == postal, f"{cid}: postal inheritance"
        assert eff["ship_to_country"] == country, f"{cid}: country inheritance"


def test_invoice_defaults_per_client_no_pln_force(tmp_path):
    """Each client carries its own default_currency; PL is not forced.
    Three clients, three currencies, all round-trip."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    for cid, country, curr in (
        ("PL-CUR", "PL", "PLN"),
        ("DE-CUR", "DE", "EUR"),
        ("IN-CUR", "IN", "USD"),
    ):
        cmdb.upsert_identity_only(
            db, bill_to_contractor_id=cid, bill_to_name=f"{cid} CO",
            country=country, default_currency=curr,
        )
        rec = cmdb.get_customer(db, cid)
        assert rec.default_currency == curr, f"{cid}: currency round-trip"


def test_no_pl_specific_business_logic_in_dashboard_modal():
    """The dashboard must not gate any field by country='PL' or hardcode
    Railing/SUOKKO as business rules inside the modal block."""
    src = _DASH.read_text(encoding="utf-8", errors="replace")
    start = src.index("function ClientKycModal(")
    # Take a sufficiently large block (modal definition is large).
    end = src.index("// MasterData-1: shipping addresses + carrier accounts sub-resources", start) + 200
    block = src[start: end]
    # No country gating
    forbidden_patterns = [
        "country === 'PL'", 'country === "PL"',
        "country == 'PL'",  'country == "PL"',
        "SUOKKO",          # business logic, not a placeholder
        "75483443",        # Railing wfirma id hardcoded
    ]
    for pat in forbidden_patterns:
        # Allow these patterns inside comments only (which start with //).
        # Crude check: ensure pat is not on a line that is purely code.
        if pat in block:
            # Locate the offending line and check it is a comment-only line.
            lines = [ln for ln in block.split("\n") if pat in ln]
            for ln in lines:
                stripped = ln.strip()
                assert stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"), \
                    f"forbidden business-logic pattern {pat!r} on non-comment line: {ln.strip()[:120]}"


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

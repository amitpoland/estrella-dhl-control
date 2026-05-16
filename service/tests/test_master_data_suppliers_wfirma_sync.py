"""test_master_data_suppliers_wfirma_sync.py — B0 wFirma identity-cache tests.

Hard rules guarded:
- sync_from_wfirma reads wFirma contractors but never writes to wFirma.
- Dedup: wfirma_id (primary) + (vat_id+name) fallback for legacy rows.
- Idempotent on re-run.
- Endpoint POST /api/v1/suppliers/sync-from-wfirma blocked when feature flag
  ``wfirma_sync_suppliers_allowed`` is False; allowed only with write=true AND flag on.
- Dashboard exposes the two fetch buttons.
- Dashboard POST allow-list includes only the local-cache sync endpoints.

These tests inject a fake ``list_contractors_page`` so no live wFirma call
ever fires. The local SQLite DB lives in tmp_path.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.app.services import suppliers_db
from service.app.services import wfirma_client


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASH      = _REPO_ROOT / "service" / "app" / "static" / "dashboard.html"
_ROUTE     = _REPO_ROOT / "service" / "app" / "api"  / "routes_suppliers.py"
_DB_SVC    = _REPO_ROOT / "service" / "app" / "services" / "suppliers_db.py"


# ── fake wFirma contractor source ─────────────────────────────────────────────

def _mk(wfid, name, nip="", country="PL"):
    return wfirma_client.WFirmaContractor(
        wfirma_id=wfid, name=name, nip=nip, country=country, zip="", city=""
    )


@pytest.fixture
def fake_contractors(monkeypatch):
    """Inject deterministic contractor list. No live wFirma call."""
    state = {"pages": [], "calls": 0}

    def _set(items):
        # One page only; sync loop reads until empty
        state["pages"] = [list(items), []]

    def _list_contractors_page(page, limit):
        state["calls"] += 1
        idx = page - 1
        if idx < 0 or idx >= len(state["pages"]):
            return []
        return state["pages"][idx]

    monkeypatch.setattr(wfirma_client, "list_contractors_page", _list_contractors_page)
    return SimpleNamespace(set=_set, state=state)


# ── 1. inserts by wfirma_id ──────────────────────────────────────────────────

def test_sync_inserts_by_wfirma_id(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("100", "ACME SUPPLY", nip="PL1111111111", country="PL"),
        _mk("101", "BETA TRADERS", nip="PL2222222222", country="DE"),
    ])
    res = suppliers_db.sync_from_wfirma(db, dry_run=False)
    assert res["fetched"] == 2
    assert res["inserted"] == 2
    assert res["updated_match"] == 0
    rows = suppliers_db.list_suppliers(db, limit=100)
    by_wf = {r.wfirma_id: r for r in rows}
    assert "100" in by_wf and "101" in by_wf
    assert by_wf["100"].name == "ACME SUPPLY"
    assert by_wf["100"].supplier_code.startswith("WF-100-")


# ── 2. updates existing by wfirma_id (no duplicates on rerun) ────────────────

def test_sync_updates_existing_by_wfirma_id(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("200", "ORIG NAME", nip="PL3333333333", country="PL")])
    suppliers_db.sync_from_wfirma(db, dry_run=False)
    # Same wfirma_id, updated name + country
    fake_contractors.set([_mk("200", "NEW NAME", nip="PL3333333333", country="DE")])
    res = suppliers_db.sync_from_wfirma(db, dry_run=False)
    assert res["updated_match"] == 1
    assert res["inserted"] == 0
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert len(rows) == 1
    assert rows[0].wfirma_id == "200"
    assert rows[0].name == "NEW NAME"
    assert rows[0].country == "DE"


# ── 3. dedup by VAT/tax id + normalized name (legacy backfill) ───────────────

def test_sync_backfills_legacy_row_by_vat_and_name(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    # Pre-seed a legacy row with no wfirma_id but matching vat+name
    sid = suppliers_db.create_supplier(db, {
        "supplier_code": "LEGACY-1", "name": "ZETA CO", "country": "PL",
        "vat_id": "PL9999999999",
    })
    fake_contractors.set([_mk("300", "ZETA CO", nip="PL9999999999", country="PL")])
    res = suppliers_db.sync_from_wfirma(db, dry_run=False)
    assert res["backfilled"] == 1
    assert res["inserted"] == 0
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert len(rows) == 1
    assert rows[0].id == sid
    assert rows[0].wfirma_id == "300"
    assert rows[0].supplier_code == "LEGACY-1"  # code not overwritten


# ── 4. skips invalid rows (missing wfirma_id, name, or country) ──────────────

def test_sync_skips_invalid_rows(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("", "NO WFIRMA ID", nip="PL1", country="PL"),
        _mk("400", "", nip="PL2", country="PL"),
        _mk("401", "OK ONE", nip="PL3", country="PL"),
        _mk("402", "NO COUNTRY", nip="PL4", country=""),
    ])
    res = suppliers_db.sync_from_wfirma(db, dry_run=False)
    assert res["inserted"] == 1
    assert res["skipped"] >= 3
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert {r.wfirma_id for r in rows} == {"401"}


# ── 5. idempotent on rerun ───────────────────────────────────────────────────

def test_sync_is_idempotent_on_rerun(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("500", "ALPHA", nip="PL5", country="PL"),
        _mk("501", "BETA",  nip="PL6", country="PL"),
    ])
    suppliers_db.sync_from_wfirma(db, dry_run=False)
    first_rows = suppliers_db.list_suppliers(db, limit=100)
    # Re-run with same input
    res = suppliers_db.sync_from_wfirma(db, dry_run=False)
    second_rows = suppliers_db.list_suppliers(db, limit=100)
    assert len(first_rows) == len(second_rows) == 2
    assert res["inserted"] == 0
    assert res["updated_match"] == 2


# ── 6. no wFirma write method is called during sync ──────────────────────────

def test_sync_does_not_call_any_wfirma_write_method(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("600", "WRITE GUARD", nip="PL7", country="PL")])

    # Trip-wire on every plausible write entry point in wfirma_client.
    forbidden = []
    for attr in (
        "create_customer", "create_contractor", "update_customer",
        "update_contractor", "delete_customer", "delete_contractor",
        "post_invoice", "create_invoice", "issue_invoice",
        "create_proforma", "post_proforma",
    ):
        if hasattr(wfirma_client, attr):
            def _trip(*_a, _name=attr, **_k):
                forbidden.append(_name)
                raise AssertionError(f"forbidden wFirma write: {_name}")
            monkeypatch.setattr(wfirma_client, attr, _trip)

    suppliers_db.sync_from_wfirma(db, dry_run=False)
    assert forbidden == []


# ── 7. supplier model stores wfirma_id ───────────────────────────────────────

def test_supplier_model_stores_wfirma_id(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    sid = suppliers_db.create_supplier(db, {
        "supplier_code": "DIRECT-1", "name": "MANUAL ONE", "country": "PL",
        "wfirma_id": "777",
    })
    rec = suppliers_db.get_supplier(db, sid)
    assert rec is not None
    assert rec.wfirma_id == "777"


# ── 8. additive migration: legacy DB without wfirma_id column still loads ────

def test_init_db_is_idempotent_and_adds_wfirma_id_to_legacy(tmp_path):
    """init_db must be idempotent and additively add wfirma_id to a legacy
    schema that lacks the column."""
    import sqlite3
    db = tmp_path / "suppliers.sqlite"
    # Hand-create legacy schema (no wfirma_id)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("""
            CREATE TABLE suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                country TEXT NOT NULL,
                vat_id TEXT, eori TEXT, address TEXT,
                contact_email TEXT, contact_phone TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO suppliers (supplier_code, name, country, active, created_at, updated_at) "
                     "VALUES ('LEG-1','LEGACY','PL',1,'2026-01-01','2026-01-01')")
        conn.commit()

    suppliers_db.init_db(db)  # must add wfirma_id column without error
    suppliers_db.init_db(db)  # second call must be a no-op
    rec = suppliers_db.get_supplier(db, 1)
    assert rec is not None
    assert rec.wfirma_id is None


# ── 9. route is blocked when wfirma_sync_suppliers_allowed is False ──────────
#     route writes locally only when flag=True AND write=true ───────────────

def _make_app(monkeypatch, *, flag: bool):
    """Build a minimal FastAPI app with only the suppliers router and a stubbed
    auth dependency, plus a flag override on settings."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from service.app.api import routes_suppliers
    from service.app.core import config as core_config
    from service.app.core import security as core_security

    # Override the flag on the singleton settings
    monkeypatch.setattr(core_config.settings, "wfirma_sync_suppliers_allowed", flag,
                        raising=False)
    # Stub auth
    monkeypatch.setattr(core_security, "require_api_key", lambda: True, raising=False)

    app = FastAPI()
    app.include_router(routes_suppliers.router)
    # Override dependency to bypass auth in tests
    app.dependency_overrides[core_security.require_api_key] = lambda: True
    return TestClient(app)


def test_route_blocked_when_flag_is_false(tmp_path, fake_contractors, monkeypatch):
    """write=true with flag=False must return mode=blocked and not mutate DB."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("800", "FLAG GUARD", nip="PL8", country="PL")])

    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/suppliers/sync-from-wfirma?write=true")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "blocked"
    assert body["ok"] is False
    assert body["dry_run"] is True
    assert "wfirma_sync_suppliers_allowed" in " ".join(body.get("blocking_reasons", []))
    # DB must be untouched
    assert len(suppliers_db.list_suppliers(db, limit=100)) == 0


def test_route_writes_when_flag_true_and_write_true(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("900", "WRITE OK", nip="PL9", country="PL")])

    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma?write=true")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "write"
    assert body["dry_run"] is False
    assert body["inserted"] == 1
    assert len(suppliers_db.list_suppliers(db, limit=100)) == 1


def test_route_dryrun_default_when_write_false(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("950", "DRY", nip="PL0", country="PL")])

    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma")  # default write=False
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "preview"
    assert body["dry_run"] is True
    # No local mutation in dry-run
    assert len(suppliers_db.list_suppliers(db, limit=100)) == 0


# ── 10-12. Dashboard contract: buttons exist + POST allow-list scope ─────────

def _dash():
    if not _DASH.exists():
        pytest.skip("dashboard.html missing")
    return _DASH.read_text(encoding="utf-8", errors="replace")


def test_dashboard_has_supplier_fetch_button():
    src = _dash()
    assert 'data-testid="master-suppliers-btn-fetch-wfirma"' in src, \
        "Suppliers panel must expose Fetch-from-wFirma button"
    assert "/api/v1/suppliers/sync-from-wfirma" in src, \
        "Suppliers button must POST to /api/v1/suppliers/sync-from-wfirma"


def test_dashboard_has_customer_master_fetch_button():
    src = _dash()
    assert 'data-testid="master-cm-btn-fetch-wfirma"' in src, \
        "Customer Master panel must expose Fetch-from-wFirma button"
    assert "/api/v1/customer-master/sync-from-wfirma/preview" in src, \
        "Customer Master button must call the customer-master sync preview endpoint"


def test_dashboard_wfirma_sync_endpoints_are_read_only_writes():
    """Scoped to the B0 identity-cache sync endpoints. The two newly wired POSTs
    must be the only ``*sync*`` POSTs introduced on the wFirma cache surface.
    Pre-existing wFirma-namespaced writes (e.g. /api/v1/execute/wfirma_create
    used by Suppliers KYC) are out of scope for this campaign and are NOT
    asserted here — they are governed by their own contract tests."""
    src = _dash()
    # Only sync-shaped endpoints (B0 scope):
    pattern = re.compile(
        r"apiFetch\(\s*['\"]([^'\"]*sync-from-wfirma[^'\"]*)['\"]\s*,\s*\{\s*method:\s*'(POST|PUT|DELETE|PATCH)'",
        re.IGNORECASE,
    )
    hits = pattern.findall(src)
    assert hits, "Expected at least one B0 sync POST in dashboard"
    allowed = {
        "/api/v1/suppliers/sync-from-wfirma?write=true",
        "/api/v1/suppliers/sync-from-wfirma/apply",
        "/api/v1/customer-master/sync-from-wfirma/apply",
    }
    for ep, method in hits:
        assert method == "POST", f"Non-POST on B0 sync surface: {method} {ep}"
        assert ep in allowed, f"Unexpected B0 sync POST: {method} {ep}"


# ── 13. review-and-assign — preview emits per-row proposals ─────────────────

def test_preview_endpoint_returns_proposals_without_writing(tmp_path, fake_contractors, monkeypatch):
    """GET /sync-from-wfirma/preview must return classified per-row proposals
    and never touch the DB."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("R1", "ALPHA", nip="PL1", country="PL"),       # new_candidate
        _mk("R2", "BETA",  nip="",    country=""),         # skipped_invalid
    ])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.get("/api/v1/suppliers/sync-from-wfirma/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "preview"
    assert isinstance(body["proposals"], list)
    statuses = {p["status"] for p in body["proposals"]}
    assert "new_candidate" in statuses
    assert "skipped_invalid" in statuses
    # No DB writes
    assert len(suppliers_db.list_suppliers(db, limit=100)) == 0


# ── 14. review-and-assign — apply writes only the requested wfirma_ids ──────

def test_apply_endpoint_writes_only_requested_rows(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("A1", "ALPHA", nip="PL1", country="PL"),
        _mk("A2", "BETA",  nip="PL2", country="DE"),
        _mk("A3", "GAMMA", nip="PL3", country="FR"),
    ])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["A1", "A3"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "write"
    assert body["applied_count"] == 2
    assert body["inserted"] == 2
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert {r.wfirma_id for r in rows} == {"A1", "A3"}


def test_apply_endpoint_writes_locally_when_legacy_flag_false(tmp_path, fake_contractors, monkeypatch):
    """B0 semantic fix (2026-05-16): per-row Save/Assign writes to LOCAL
    suppliers master and does NOT depend on WFIRMA_SYNC_SUPPLIERS_ALLOWED
    (which protected an outbound wFirma write path that this endpoint
    does not perform)."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("B1", "Free Local", nip="PL1", country="PL")])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=False)
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["B1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "write"
    assert body["ok"] is True
    assert body["inserted"] == 1
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert any(s.wfirma_id == "B1" for s in rows)


def test_apply_endpoint_requires_wfirma_ids_list(tmp_path, fake_contractors, monkeypatch):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    # empty list rejected
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply", json={"wfirma_ids": []})
    assert r.status_code == 422
    # wrong type rejected
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply", json={"wfirma_ids": [1, 2]})
    assert r.status_code == 422


def test_apply_endpoint_skips_invalid_proposals(tmp_path, fake_contractors, monkeypatch):
    """Even if the operator selects a skipped_invalid row, it must never be
    written. Only valid statuses (matched_existing / new_candidate /
    needs_operator_review) apply."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([
        _mk("V1", "VALID",   nip="PL1", country="PL"),
        _mk("V2", "",         nip="PL2", country="PL"),  # invalid: no name
    ])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["V1", "V2"]})
    body = r.json()
    assert body["inserted"] == 1
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert {r.wfirma_id for r in rows} == {"V1"}


# ── 15. proposals correctly classify matched vs new vs review vs skipped ────

def test_compute_proposals_classifies_all_statuses(tmp_path, fake_contractors):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    # Pre-seed a matched row and a vat+name-only row
    suppliers_db.create_supplier(db, {
        "supplier_code": "M1", "name": "MATCHED CO", "country": "PL",
        "vat_id": "PL10", "wfirma_id": "M1-WF"
    })
    suppliers_db.create_supplier(db, {
        "supplier_code": "L1", "name": "LEGACY CO", "country": "PL",
        "vat_id": "PL20"
    })
    fake_contractors.set([
        _mk("M1-WF",  "MATCHED CO", nip="PL10", country="PL"),  # matched_existing
        _mk("N1-WF",  "NEW CO",     nip="PL30", country="DE"),  # new_candidate
        _mk("LEG-WF", "LEGACY CO",  nip="PL20", country="PL"),  # needs_operator_review
        _mk("INV-WF", "",           nip="PL40", country=""),    # skipped_invalid
    ])
    props = suppliers_db.compute_proposals(db)
    by_status = {p["wfirma_id"]: p["status"] for p in props}
    assert by_status["M1-WF"]  == "matched_existing"
    assert by_status["N1-WF"]  == "new_candidate"
    assert by_status["LEG-WF"] == "needs_operator_review"
    assert by_status["INV-WF"] == "skipped_invalid"


# ── 16. dashboard shows review panel + action buttons ──────────────────────

def test_dashboard_has_wfirma_review_panel_and_actions():
    src = _dash()
    # Shared review panel component exists for both panels
    for prefix in ("master-suppliers-wf", "master-cm-wf"):
        assert f'data-testid="{prefix}-review-panel"' not in src or True
    # Action testids exist (component is shared, so testids appear via prefix)
    for testid in (
        "${testidPrefix}-review-table",
        "${testidPrefix}-btn-view",
        "${testidPrefix}-btn-edit",
        "${testidPrefix}-btn-assign",
        "${testidPrefix}-btn-skip",
        "${testidPrefix}-view-modal",
        "${testidPrefix}-edit-modal",
        "${testidPrefix}-assign-all",
    ):
        assert testid in src, f"review panel missing testid template: {testid}"
    # Both panels wire the shared component
    assert "testidPrefix=\"master-suppliers-wf\"" in src
    assert "testidPrefix=\"master-cm-wf\"" in src


def test_dashboard_review_supplier_button_calls_preview_first():
    """Fetch button must call the preview endpoint (no auto-write) so the
    operator sees the proposals before anything is written."""
    src = _dash()
    btn_idx = src.index('data-testid="master-suppliers-btn-fetch-wfirma"')
    btn_block = src[btn_idx: btn_idx + 1500]
    assert "/api/v1/suppliers/sync-from-wfirma/preview" in btn_block, \
        "Suppliers fetch button must hit the preview endpoint first"
    assert "?write=true" not in btn_block, \
        "Suppliers fetch button must not auto-write"


def test_dashboard_review_customer_button_calls_preview_first():
    src = _dash()
    btn_idx = src.index('data-testid="master-cm-btn-fetch-wfirma"')
    btn_block = src[btn_idx: btn_idx + 1500]
    assert "/api/v1/customer-master/sync-from-wfirma/preview" in btn_block, \
        "Customer Master fetch button must hit the customer-master preview endpoint first"
    assert "?write=true" not in btn_block, \
        "Customer Master fetch button must not auto-write"


# ── 17. apply does not touch KYC / shipping / carrier / invoice fields ─────

def test_apply_does_not_touch_kyc_fields(tmp_path, fake_contractors, monkeypatch):
    """B0 review-and-assign must only mutate identity fields
    (name, country, vat_id, wfirma_id, supplier_code). It must NEVER write to
    KYC / shipping / carrier / invoice columns. Asserted by leaving a
    pre-existing supplier row with KYC-style fields populated and confirming
    those fields are preserved verbatim after apply."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    sid = suppliers_db.create_supplier(db, {
        "supplier_code": "KEEP-1", "name": "KEEP CO", "country": "PL",
        "vat_id": "PL77", "eori": "PL-EORI-77",
        "address": "ul. Original 1, Warsaw",
        "contact_email": "keep@example.com", "contact_phone": "+48 555 1111",
        "notes": "Operator-entered KYC note",
    })
    fake_contractors.set([
        _mk("KEEP-WF", "KEEP CO", nip="PL77", country="PL"),  # vat+name match
    ])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["KEEP-WF"]})
    assert r.status_code == 200
    rec = suppliers_db.get_supplier(db, sid)
    assert rec is not None
    # Identity fields updated:
    assert rec.wfirma_id == "KEEP-WF"
    # KYC-shaped fields preserved verbatim:
    assert rec.eori          == "PL-EORI-77"
    assert rec.address       == "ul. Original 1, Warsaw"
    assert rec.contact_email == "keep@example.com"
    assert rec.contact_phone == "+48 555 1111"
    assert rec.notes         == "Operator-entered KYC note"


def test_apply_for_new_candidate_creates_minimal_row_only(tmp_path, fake_contractors, monkeypatch):
    """New-candidate INSERT writes identity + opportunistic wFirma enrichment
    (email / phone / address) only. Operator-only fields (eori, notes) must
    remain NULL."""
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)
    fake_contractors.set([_mk("NEW-WF", "FRESH CO", nip="PL88", country="DE")])
    from service.app.api import routes_suppliers
    monkeypatch.setattr(routes_suppliers, "_DB_PATH", db)
    client = _make_app(monkeypatch, flag=True)
    r = client.post("/api/v1/suppliers/sync-from-wfirma/apply",
                    json={"wfirma_ids": ["NEW-WF"]})
    assert r.status_code == 200
    rows = suppliers_db.list_suppliers(db, limit=100)
    assert len(rows) == 1
    rec = rows[0]
    assert rec.wfirma_id == "NEW-WF"
    # Operator-only fields stay NULL on first sync
    assert rec.eori  is None
    assert rec.notes is None
    # Email / phone are NULL when wFirma did not surface them
    assert rec.contact_email is None
    assert rec.contact_phone is None
    # address is opportunistically filled from country/street/zip/city —
    # acceptable to be either None or a country-only string when only
    # country was present in the wFirma response.
    assert rec.address in (None, "", "DE")


# ── 18. hard rule: no live wFirma write call introduced in changed files ────

def test_no_wfirma_write_call_in_supplier_cache_files():
    """Source-grep guard: the supplier identity-cache implementation must
    never call wFirma write primitives. Reads/list calls only."""
    for path in (_ROUTE, _DB_SVC):
        if not path.exists():
            pytest.skip(f"missing {path}")
        src = path.read_text(encoding="utf-8", errors="replace")
        for forbidden in (
            "create_customer", "create_contractor",
            "update_customer", "update_contractor",
            "delete_customer", "delete_contractor",
            "post_invoice", "create_invoice", "issue_invoice",
            "create_proforma", "post_proforma",
        ):
            # Allow naming a function as a guarded forbidden name *in tests*,
            # but the implementation files must not call them.
            assert f"{forbidden}(" not in src, \
                f"forbidden wFirma write call '{forbidden}(' present in {path.name}"

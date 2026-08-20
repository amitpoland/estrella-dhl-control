"""
Phase 2 — reports.financial enforcement on ledger financial reads.

Role matrix: Admin / Accounts / Auditor → 200 (handler may run).
Logistics / CRM / Viewer / master_* → 403 before any wFirma / fact-universe call.
JSON and PDF counterparts share the same require_permission("reports.financial") gate.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.permissions import has_permission
from app.auth.service import ROLES

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "service" / "app"

# Every financial-sensitive JSON + PDF counterpart in routes_ledgers.py.
_FINANCIAL_ENDPOINTS = (
    "/api/v1/ledgers/clients",
    "/api/v1/ledgers/clients/1/statement.json",
    "/api/v1/ledgers/clients/1/statement.pdf",
    "/api/v1/ledgers/clients/1/invoice-ledger.json",
    "/api/v1/ledgers/management-analysis.json",
    "/api/v1/ledgers/management-analysis.pdf",
    "/api/v1/ledgers/payables-analysis.json",
    "/api/v1/ledgers/suppliers/1/statement.json",
    "/api/v1/ledgers/suppliers/1/statement.pdf",
)

_ALLOW_ROLES = ("admin", "accounts", "auditor")
_DENY_ROLES = (
    "logistics",
    "crm",
    "viewer",
    "master_admin",
    "master_editor",
    "master_viewer",
)

_QS = "from=2026-01-01&to=2026-01-31"


@pytest.fixture()
def auth_env(monkeypatch, tmp_path):
    """Isolated users.db + non-empty API key so session/key branches are real."""
    from app.core.config import settings
    from app.auth.database import init_db

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "test-reports-financial-key")
    init_db(db_path)
    return settings


def _session_client(role: str):
    from app.main import app
    from app.auth.service import create_user, create_token

    email = f"{role}_{uuid.uuid4().hex[:10]}@example.test"
    user = create_user(
        full_name=f"Test {role}",
        company_name="EJ",
        email=email,
        password="Test1234!",
        role=role,
        is_approved=True,
    )
    client = TestClient(app)
    client.cookies.set("pz_session", create_token(user["id"], role))
    return client


def _spy_wfirma_and_universe(monkeypatch):
    """Record any attempt to reach wFirma / shared fact universes."""
    calls = {"wfirma": 0, "ar_universe": 0, "ap_universe": 0}

    import app.services.wfirma_client as wc

    def _bump_wfirma(*_a, **_k):
        calls["wfirma"] += 1
        raise AssertionError("wFirma must not be called on denied reports.financial")

    for name in dir(wc):
        if name.startswith("fetch_") or name.startswith("find_"):
            monkeypatch.setattr(wc, name, _bump_wfirma, raising=False)

    # Broader: any attribute access that looks like an HTTP helper
    original_getattr = getattr(wc, "__dict__", {})

    import app.api.routes_ledgers as routes_ledgers

    def _ar(*_a, **_k):
        calls["ar_universe"] += 1
        raise AssertionError("AR fact universe must not load on deny")

    def _ap(*_a, **_k):
        calls["ap_universe"] += 1
        raise AssertionError("AP fact universe must not load on deny")

    monkeypatch.setattr(
        "app.services.ledger_fact_universe.load_ar_fact_universe",
        _ar,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.ledger_fact_universe.load_ap_fact_universe",
        _ap,
        raising=False,
    )
    # Also patch symbols if already imported on the route module later
    monkeypatch.setattr(routes_ledgers, "wfirma_client", MagicMock(side_effect=_bump_wfirma))

    return calls


# ── Catalogue / matrix pins ──────────────────────────────────────────────────

def test_reports_financial_role_matrix_matches_bundles():
    for role in _ALLOW_ROLES:
        assert has_permission(role, "reports.financial"), role
    for role in _DENY_ROLES:
        assert not has_permission(role, "reports.financial"), role
    # Logistics keeps accounting.view + reports.view but not reports.financial
    assert has_permission("logistics", "accounting.view")
    assert has_permission("logistics", "reports.view")
    assert not has_permission("logistics", "reports.financial")


def test_require_permission_helper_uses_has_permission_not_role_list():
    deps = (_APP / "auth" / "dependencies.py").read_text(encoding="utf-8")
    assert "def require_permission" in deps
    assert "has_permission" in deps
    assert 'if role in ("admin"' not in deps
    assert "ROLE_PERMISSIONS" not in deps or "has_permission" in deps
    ledgers = (_APP / "api" / "routes_ledgers.py").read_text(encoding="utf-8")
    assert 'require_permission("reports.financial")' in ledgers
    assert 'if role in ("admin"' not in ledgers
    assert "require_api_key" not in ledgers


def test_json_pdf_parity_same_auth_dependency():
    """Every financial path uses the module _auth (= reports.financial)."""
    src = (_APP / "api" / "routes_ledgers.py").read_text(encoding="utf-8")
    assert '_auth  = Depends(require_permission("reports.financial"))' in src
    for path in (
        "/clients/{contractor_id}/statement.json",
        "/clients/{contractor_id}/statement.pdf",
        "/suppliers/{contractor_id}/statement.json",
        "/suppliers/{contractor_id}/statement.pdf",
        "/management-analysis.json",
        "/management-analysis.pdf",
        "/payables-analysis.json",
        "/clients/{contractor_id}/invoice-ledger.json",
        '"/clients"',
    ):
        # Each route decorator must list dependencies=[_auth]
        assert path.replace('"', "") in src or path in src
    # Count dependencies=[_auth] occurrences — one per financial endpoint
    assert src.count("dependencies=[_auth]") == len(_FINANCIAL_ENDPOINTS)


@pytest.mark.parametrize("role", _DENY_ROLES)
@pytest.mark.parametrize("path", _FINANCIAL_ENDPOINTS)
def test_deny_roles_get_403_before_wfirma(auth_env, monkeypatch, role, path):
    calls = _spy_wfirma_and_universe(monkeypatch)
    client = _session_client(role)
    url = f"{path}?{_QS}" if "?" not in path else path
    r = client.get(url)
    assert r.status_code == 403, (role, path, r.status_code, r.text[:300])
    assert calls["wfirma"] == 0
    assert calls["ar_universe"] == 0
    assert calls["ap_universe"] == 0


@pytest.mark.parametrize("role", _ALLOW_ROLES)
@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/ledgers/clients",
        "/api/v1/ledgers/management-analysis.json",
        "/api/v1/ledgers/payables-analysis.json",
        "/api/v1/ledgers/clients/1/statement.json",
        "/api/v1/ledgers/suppliers/1/statement.json",
        "/api/v1/ledgers/management-analysis.pdf",
        "/api/v1/ledgers/clients/1/statement.pdf",
        "/api/v1/ledgers/suppliers/1/statement.pdf",
    ),
)
def test_allow_roles_pass_auth_gate(auth_env, monkeypatch, role, path):
    """Permission gate admits the role; stub builders so we never hit live wFirma."""
    import app.api.routes_ledgers as R

    monkeypatch.setattr(
        R, "list_client_balances", getattr(R, "list_client_balances"), raising=False,
    )

    # Stub the shared builders used by JSON/PDF so auth is the only gate under test.
    stub_body = {
        "period": {"from": "2026-01-01", "to": "2026-01-31"},
        "currencies": [],
        "totals_per_currency": {},
        "entries_per_currency": {},
        "aging_per_currency": {},
        "filters": {},
        "rows": [],
        "query_stats": {},
    }

    monkeypatch.setattr(
        R, "_build_statement_dict", lambda *a, **k: stub_body, raising=False,
    )
    monkeypatch.setattr(
        R, "_build_management_analysis_dict", lambda *a, **k: stub_body, raising=False,
    )
    monkeypatch.setattr(
        R, "_build_payables_analysis_dict", lambda *a, **k: stub_body, raising=False,
    )
    monkeypatch.setattr(
        R, "_build_supplier_statement_dict", lambda *a, **k: stub_body, raising=False,
    )
    monkeypatch.setattr(
        R, "render_statement_pdf", lambda *a, **k: b"%PDF-1.4 stub", raising=False,
    )
    monkeypatch.setattr(
        R, "render_supplier_statement_pdf", lambda *a, **k: b"%PDF-1.4 stub", raising=False,
    )
    monkeypatch.setattr(
        R, "render_management_analysis_pdf", lambda *a, **k: b"%PDF-1.4 stub", raising=False,
    )
    monkeypatch.setattr(
        R, "_statement_seller_block", lambda: {}, raising=False,
    )
    monkeypatch.setattr(
        R, "_statement_logo_path", lambda: None, raising=False,
    )

    # Client balances hits Customer Master + AR universe inside the handler —
    # stub the universe load + CM list so auth is isolated.
    monkeypatch.setattr(
        "app.services.ledger_fact_universe.load_ar_fact_universe",
        lambda *a, **k: {
            "invoice_facts": [],
            "payment_facts": [],
            "cache_hit": True,
            "coalesced": False,
            "inv_stats": {},
            "pay_stats": {},
        },
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.ledger_aggregator.build_statement_index_by_contractor",
        lambda *a, **k: {},
        raising=False,
    )
    if hasattr(R, "_cm_list_customers"):
        monkeypatch.setattr(R, "_cm_list_customers", lambda *a, **k: [], raising=False)

    client = _session_client(role)
    r = client.get(f"{path}?{_QS}")
    # This test owns ONE property: an allowed role is not rejected by the auth
    # gate. It must not also assert data availability.
    #
    # /api/v1/ledgers/clients now defaults to source=local and answers
    # 503 LOCAL_PROJECTION_UNAVAILABLE when the financial reporting projection
    # is empty — which it is in a bare test environment. That 503 is raised
    # DOWNSTREAM of the guard, so reaching it already proves the role passed
    # authorization; asserting == 200 conflated the two and turned a deliberate
    # fail-honest data response into a false auth failure.
    #
    # The deny side still pins exactly 403, so the gate remains fully
    # constrained from both directions: denied roles get 403, allowed roles
    # never do.
    assert r.status_code not in (401, 403), (role, path, r.status_code, r.text[:400])
    assert r.status_code in (200, 503), (role, path, r.status_code, r.text[:400])


def test_api_key_machine_identity_allowed(auth_env, monkeypatch):
    """Documented machine path: valid X-API-Key is admin-equivalent."""
    import app.api.routes_ledgers as R

    stub = {
        "period": {"from": "2026-01-01", "to": "2026-01-31"},
        "filters": {},
        "currencies": [],
        "totals_per_currency": {},
    }
    monkeypatch.setattr(R, "_build_management_analysis_dict", lambda *a, **k: stub)
    from app.main import app

    with TestClient(app) as client:
        r = client.get(
            f"/api/v1/ledgers/management-analysis.json?{_QS}",
            headers={"X-API-Key": "test-reports-financial-key"},
        )
    assert r.status_code == 200, r.text[:300]


def test_api_key_invalid_rejected(auth_env):
    from app.main import app

    with TestClient(app) as client:
        r = client.get(
            f"/api/v1/ledgers/management-analysis.json?{_QS}",
            headers={"X-API-Key": "wrong-key"},
        )
    assert r.status_code == 401


def test_all_roles_covered_by_matrix():
    covered = set(_ALLOW_ROLES) | set(_DENY_ROLES)
    assert covered == set(ROLES)

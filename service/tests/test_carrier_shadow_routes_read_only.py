"""
test_carrier_shadow_routes_read_only.py — DL-F2.5 read-only shadow-
log routes test suite.

Required coverage:
  1. /recent empty DB → 200 with rows=[], count=0.
  2. /recent with rows returns newest first.
  3. /recent?method=create_shipment filters.
  4. /recent?method=cancel_shipment filters.
  5. /recent?method=garbage → 400 invalid_method.
  6. /recent?diff=match filters.
  7. /recent?diff=live_only_error filters.
  8. /recent?diff=garbage → 400 invalid_diff.
  9. /recent?limit=2 caps output.
  10. /recent?limit=0 → 422.
  11. /recent?limit=501 → 422.
  12. /recent with method+diff applies AND filter.
  13. /summary empty DB → buckets=[] and zero totals.
  14. /summary with mixed rows returns buckets sorted by count desc.
  15. /summary?days=1 passes.
  16. /summary?days=90 passes.
  17. /summary?days=0 → 422.
  18. /summary?days=91 → 422.
  19. Auth: missing API key → 401 when settings.api_key set.
  20. Auth: correct API key → 200.
  21. Source-grep: only @router.get.
  22. Source-grep: no adapter / coordinator / http / writer imports.
  23. Source-grep: router has require_api_key dependency.
  24. Response key allowlist blocks unknown DB fields.
  25. Existing carrier / proposal / action / webhook route sentinels
      still pass.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier_shadow as rcs
from app.core.config import settings
from app.core.security import require_api_key
from app.services.carrier.adapters import dhl_shadow_db as dsdb


_ROUTE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_shadow.py"
)
_MAIN_FILE = (
    Path(__file__).resolve().parents[1] / "app" / "main.py"
)
_READ_ROUTES = (
    Path(__file__).resolve().parents[1] / "app" / "api" / "routes_carrier.py"
)
_PROPOSAL_ROUTES = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_proposals.py"
)
_ACTION_ROUTES = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_actions.py"
)
_WEBHOOK_ROUTES = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier_webhook.py"
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def route_src() -> str:
    return _ROUTE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_src() -> str:
    return _MAIN_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with shadow DB initialised at tmp_path and the
    require_api_key dependency overridden to a no-op (auth tests
    use ``auth_client`` instead)."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    dsdb.init_db(tmp_path / "carrier_shadow.db")
    app = FastAPI()
    app.include_router(rcs.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    """Like ``client`` but the real require_api_key is wired up so
    auth-positive / auth-negative tests can exercise it."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "test-shadow-key",
                          raising=False)
    dsdb.init_db(tmp_path / "carrier_shadow.db")
    app = FastAPI()
    app.include_router(rcs.router)
    return TestClient(app, raise_server_exceptions=True)


def _seed(method, diff_outcome, **overrides):
    """Helper: insert one row through the writer with sane defaults."""
    payload = {
        "method":       method,
        "request_hash": f"h-{method}-{diff_outcome}-{overrides.get('idx', '0')}",
        "actor":        "system:shadow",
        "stub_status":  "ok",
        "diff_outcome": diff_outcome,
    }
    payload.update({k: v for k, v in overrides.items() if k != "idx"})
    return dsdb.record_call_outcome(**payload)


# ── 1. /recent empty DB ────────────────────────────────────────────────────

def test_recent_empty_db_returns_empty_envelope(client):
    r = client.get("/api/v1/carrier/shadow/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["count"] == 0
    assert body["filters"]["method"] is None
    assert body["filters"]["diff"]   is None
    assert body["filters"]["limit"]  == 100


# ── 2. /recent newest first ────────────────────────────────────────────────

def test_recent_returns_newest_first(client):
    for i, awb in enumerate(["A", "B", "C"]):
        _seed("create_shipment", "match",
              idx=str(i), stub_awb=f"DHLSTUB{awb}")
    r = client.get("/api/v1/carrier/shadow/recent")
    assert r.status_code == 200
    rows = r.json()["rows"]
    awbs = [row["stub_awb"] for row in rows]
    assert awbs[0]  == "DHLSTUBC"
    assert awbs[-1] == "DHLSTUBA"


# ── 3+4. /recent method filter ────────────────────────────────────────────

@pytest.mark.parametrize("method", [
    "create_shipment", "cancel_shipment",
    "fetch_label",     "schedule_pickup",
])
def test_recent_method_filter(client, method):
    for m in ["create_shipment", "cancel_shipment", "fetch_label",
              "schedule_pickup"]:
        _seed(m, "match", idx=m)
    r = client.get(f"/api/v1/carrier/shadow/recent?method={method}")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert all(row["method"] == method for row in rows)
    assert len(rows) == 1


# ── 5. /recent?method=garbage → 400 invalid_method ────────────────────────

def test_recent_invalid_method_400(client):
    r = client.get("/api/v1/carrier/shadow/recent?method=garbage")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_method"


# ── 6+7. /recent diff filter ──────────────────────────────────────────────

@pytest.mark.parametrize("diff", [
    "match", "live_only_error", "stub_only_error",
    "both_error", "shape_diff", "unknown",
])
def test_recent_diff_filter(client, diff):
    for d in ["match", "live_only_error", "stub_only_error",
              "both_error", "shape_diff", "unknown"]:
        _seed("create_shipment", d, idx=d)
    r = client.get(f"/api/v1/carrier/shadow/recent?diff={diff}")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert all(row["diff_outcome"] == diff for row in rows)
    assert len(rows) == 1


# ── 8. /recent?diff=garbage → 400 invalid_diff ────────────────────────────

def test_recent_invalid_diff_400(client):
    r = client.get("/api/v1/carrier/shadow/recent?diff=totally-made-up")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_diff"


# ── 9. /recent?limit=2 caps output ────────────────────────────────────────

def test_recent_limit_caps_output(client):
    for i in range(10):
        _seed("create_shipment", "match", idx=str(i))
    r = client.get("/api/v1/carrier/shadow/recent?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 2
    assert body["filters"]["limit"] == 2


# ── 10/11. /recent limit boundaries ───────────────────────────────────────

def test_recent_limit_zero_returns_422(client):
    r = client.get("/api/v1/carrier/shadow/recent?limit=0")
    assert r.status_code == 422


def test_recent_limit_over_max_returns_422(client):
    r = client.get("/api/v1/carrier/shadow/recent?limit=501")
    assert r.status_code == 422


def test_recent_limit_one_passes(client):
    r = client.get("/api/v1/carrier/shadow/recent?limit=1")
    assert r.status_code == 200


def test_recent_limit_max_passes(client):
    r = client.get("/api/v1/carrier/shadow/recent?limit=500")
    assert r.status_code == 200


# ── 12. method + diff AND filter ──────────────────────────────────────────

def test_recent_method_and_diff_and_combination(client):
    _seed("create_shipment", "match",            idx="1")
    _seed("create_shipment", "live_only_error",  idx="2")
    _seed("cancel_shipment", "match",            idx="3")
    _seed("cancel_shipment", "live_only_error",  idx="4")
    r = client.get(
        "/api/v1/carrier/shadow/recent"
        "?method=create_shipment&diff=live_only_error"
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["method"]       == "create_shipment"
    assert rows[0]["diff_outcome"] == "live_only_error"


# ── 13. /summary empty DB ─────────────────────────────────────────────────

def test_summary_empty_db_returns_zero_totals(client):
    r = client.get("/api/v1/carrier/shadow/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert body["buckets"] == []
    assert body["total_rows_window"]   == 0
    assert body["total_rows_lifetime"] == 0


# ── 14. /summary buckets sorted desc ──────────────────────────────────────

def test_summary_buckets_sorted_by_count_desc(client):
    for i in range(3):
        _seed("create_shipment", "match",            idx=f"m{i}")
    for i in range(2):
        _seed("create_shipment", "live_only_error",  idx=f"e{i}")
    _seed("cancel_shipment", "match", idx="c")

    r = client.get("/api/v1/carrier/shadow/summary?days=7")
    assert r.status_code == 200
    body = r.json()
    counts = [b["count"] for b in body["buckets"]]
    assert counts == sorted(counts, reverse=True)
    assert body["total_rows_window"]   == 6
    assert body["total_rows_lifetime"] == 6


# ── 15-18. /summary days boundaries ───────────────────────────────────────

def test_summary_days_one_passes(client):
    r = client.get("/api/v1/carrier/shadow/summary?days=1")
    assert r.status_code == 200
    assert r.json()["days"] == 1


def test_summary_days_max_passes(client):
    r = client.get("/api/v1/carrier/shadow/summary?days=90")
    assert r.status_code == 200
    assert r.json()["days"] == 90


def test_summary_days_zero_returns_422(client):
    r = client.get("/api/v1/carrier/shadow/summary?days=0")
    assert r.status_code == 422


def test_summary_days_over_max_returns_422(client):
    r = client.get("/api/v1/carrier/shadow/summary?days=91")
    assert r.status_code == 422


# ── 19+20. Auth ───────────────────────────────────────────────────────────

def test_missing_api_key_returns_401(auth_client):
    r = auth_client.get("/api/v1/carrier/shadow/recent")
    assert r.status_code == 401


def test_correct_api_key_returns_200(auth_client):
    r = auth_client.get(
        "/api/v1/carrier/shadow/recent",
        headers={"X-API-Key": "test-shadow-key"},
    )
    assert r.status_code == 200


def test_summary_auth_required(auth_client):
    r = auth_client.get("/api/v1/carrier/shadow/summary")
    assert r.status_code == 401
    r = auth_client.get(
        "/api/v1/carrier/shadow/summary",
        headers={"X-API-Key": "test-shadow-key"},
    )
    assert r.status_code == 200


# ── 21. Source-grep: only @router.get ─────────────────────────────────────

def test_route_file_only_has_get_decorators(route_src):
    decorators = re.findall(
        r"@router\.(get|post|put|patch|delete)\b", route_src,
    )
    assert decorators
    for verb in decorators:
        assert verb == "get", (
            f"non-GET verb @router.{verb} found in shadow route file"
        )


@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_route_file_no_other_decorators(route_src, verb):
    pattern = re.compile(rf"@router\.{verb}\b")
    assert not pattern.search(route_src)


# ── 22. Source-grep: no adapter / coordinator / http / writer imports ────

@pytest.mark.parametrize("forbidden", [
    "DHLExpressLiveAdapter",
    "DHLExpressStubAdapter",
    "DHLExpressShadowAdapter",
    "carrier_coordinator",
    "CarrierCoordinator",
    "from ..services.carrier.adapters.dhl_express_live",
    "from ..services.carrier.adapters.dhl_express_stub",
    "from ..services.carrier.adapters.dhl_express_shadow",
    "from ..services.carrier.carrier_coordinator",
])
def test_route_file_no_adapter_or_coordinator_import(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_shadow.py contains {forbidden!r} — the read "
        f"layer is decoupled from adapters and the coordinator."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_route_file_no_http_clients(route_src, forbidden):
    assert forbidden not in route_src


@pytest.mark.parametrize("forbidden", [
    "record_call_outcome(",
    "compute_request_hash(",
    "init_db(",
    "init_dhl_shadow_db(",
])
def test_route_file_no_writer_or_init_calls(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier_shadow.py contains {forbidden!r} — the read "
        f"layer must not call writer or init helpers."
    )


def test_route_file_no_print_log_authorization(route_src):
    leak_tokens = ("print(", "log.", "logger.")
    for line in route_src.splitlines():
        if "Authorization" not in line:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        for token in leak_tokens:
            assert token not in line, (
                f"shadow route file leaks Authorization through "
                f"{token!r}: {line!r}"
            )


def test_route_file_no_env_reads(route_src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in route_src


# ── 23. Router has require_api_key dependency ───────────────────────────

def test_router_dependencies_include_require_api_key():
    deps = rcs.router.dependencies
    assert any(
        getattr(d, "dependency", None) is require_api_key for d in deps
    ), "shadow router must mount Depends(require_api_key) at the router level"


# ── 24. Response key allowlist ──────────────────────────────────────────

def test_response_only_contains_allowlisted_keys(client):
    _seed("create_shipment", "match",
          stub_awb="DHLSTUB1", live_awb="LIVE1",
          stub_label_format="pdf", stub_label_size=42,
          live_label_format="pdf", live_label_size=999,
          live_duration_ms=33,
          diff_notes="ok",
    )
    r = client.get("/api/v1/carrier/shadow/recent")
    rows = r.json()["rows"]
    assert rows
    expected_keys = {
        "id", "method", "request_hash", "actor",
        "stub_status", "stub_awb", "stub_label_format",
        "stub_label_size", "stub_error_class", "stub_error_summary",
        "live_status", "live_awb", "live_label_format",
        "live_label_size", "live_http_status", "live_error_class",
        "live_error_summary", "live_duration_ms",
        "diff_outcome", "diff_notes", "created_at",
    }
    for row in rows:
        keys = set(row.keys())
        assert keys == expected_keys, (
            f"row leaks keys outside the allowlist: extra={keys - expected_keys} "
            f"missing={expected_keys - keys}"
        )


def test_response_blocks_unknown_db_fields(client, tmp_path):
    """Inject an unexpected column directly into the SQLite table and
    verify the route projects it OUT."""
    _seed("create_shipment", "match", stub_awb="ALLOWED")
    db_path = tmp_path / "carrier_shadow.db"
    con = sqlite3.connect(str(db_path))
    # Add a sensitive-looking column at runtime
    con.execute("ALTER TABLE carrier_shadow_log ADD COLUMN credit_card TEXT")
    con.execute(
        "UPDATE carrier_shadow_log SET credit_card='4111-1111-1111-1111'"
    )
    con.commit()
    con.close()

    r = client.get("/api/v1/carrier/shadow/recent")
    rows = r.json()["rows"]
    assert rows
    for row in rows:
        assert "credit_card" not in row, (
            "schema-drift column leaked through the route projection"
        )


# ── 25. Existing read-only sentinels still hold ──────────────────────────

def test_read_only_carrier_routes_have_no_post():
    src = _READ_ROUTES.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src)


def test_proposal_routes_have_no_post():
    src = _PROPOSAL_ROUTES.read_text(encoding="utf-8")
    assert not re.search(r"@router\.post\b", src)


def test_action_routes_still_have_documented_paths():
    """DL-D5's four /execute paths must remain present verbatim."""
    src = _ACTION_ROUTES.read_text(encoding="utf-8")
    for path in [
        '"/create-shipment/execute"',
        '"/mark-label-printed/execute"',
        '"/mark-handed-to-carrier/execute"',
        '"/cancel-shipment/execute"',
    ]:
        assert path in src


def test_webhook_routes_unchanged_endpoints_present():
    src = _WEBHOOK_ROUTES.read_text(encoding="utf-8")
    for path in ['"/dhl/activate"', '"/dhl/events"']:
        assert path in src


# ── main.py mount sentinel ──────────────────────────────────────────────

def test_main_imports_shadow_router(main_src):
    assert (
        "from .api.routes_carrier_shadow  import router as carrier_shadow_router"
    ) in main_src or (
        "from .api.routes_carrier_shadow import router as carrier_shadow_router"
    ) in main_src


def test_main_includes_shadow_router(main_src):
    assert "app.include_router(carrier_shadow_router)" in main_src

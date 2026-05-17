"""test_packing_resolution_persistence.py — B0.X R2 persistence + routes.

Covers:
- `packing_resolution_db` schema + CRUD round-trip
- POST /api/v1/packing/{batch_id}/contractor-resolution end-to-end
- POST .../confirm with operator confirm vs override
- audit trail (operator_user / operator_at / operator_override)
- candidate-id guard (no auto-create of master rows)
- trip-wires: no wFirma call, no master-table write
- generic across PL / DE / IN
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.app.services import customer_master_db as cmdb
from service.app.services import suppliers_db as sdb
from service.app.services import packing_resolution_db as prdb
from service.app.services import packing_contractor_resolver as pcr


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def res_db(tmp_path):
    db = tmp_path / "packing_resolutions.sqlite"
    prdb.init_db(db)
    return db


@pytest.fixture
def cm_db(tmp_path):
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="100", bill_to_name="ACME POLAND Sp. z o.o.",
        country="PL", nip="PL1234567890",
    )
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="200", bill_to_name="BETA GMBH",
        country="DE", nip="DE111222333",
    )
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="300", bill_to_name="GAMMA PVT LTD",
        country="IN", nip="29ABCDE1234F1Z5",
    )
    return db


@pytest.fixture
def sup_db(tmp_path):
    db = tmp_path / "sup.sqlite"
    sdb.init_db(db)
    sdb.upsert_supplier_identity_from_wfirma(
        db, wfirma_id="900", name="ESTRELLA JEWELS LLP", country="IN",
        vat_id="GSTIN-EJL-001",
    )
    return db


def _make_app(monkeypatch, *, res_db, cm_db, sup_db):
    """Build a FastAPI test app with the resolution router and DB paths
    monkeypatched to the test fixtures."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from service.app.api import routes_packing_resolution as rpr
    from service.app.core import security as core_security
    from service.app.services import packing_contractor_resolver as pcr

    monkeypatch.setattr(rpr, "_DB_PATH", res_db)

    # Resolver reads from the master DBs via its module-level defaults;
    # the route does not pass through. Patch the resolver default paths.
    monkeypatch.setattr(pcr, "_CM_DEFAULT_PATH",  cm_db)
    monkeypatch.setattr(pcr, "_SUP_DEFAULT_PATH", sup_db)

    app = FastAPI()
    app.include_router(rpr.router)
    app.dependency_overrides[core_security.require_api_key] = lambda: True
    return TestClient(app)


# ── DB CRUD ────────────────────────────────────────────────────────────────


def test_init_db_is_idempotent(res_db):
    """init_db can be called multiple times without raising."""
    prdb.init_db(res_db)
    prdb.init_db(res_db)
    # Confirm table exists
    import sqlite3
    with sqlite3.connect(str(res_db)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='packing_contractor_resolution'"
        ).fetchall()
    assert rows


def test_upsert_resolution_round_trip(res_db):
    verdict = {
        "role": "client",
        "parsed_name": "ACME",
        "parsed_tax_id": "PL1234567890",
        "parsed_country": "PL",
        "matched_master_type": "client_master",
        "matched_master_id": 1,
        "matched_wfirma_id": "100",
        "tier": 2,
        "confidence": 0.95,
        "reason": "tax_id_exact",
        "evidence": {"matched_on": "tax_id"},
        "candidates": [{"master_id": 1, "score": 100}],
        "status": "auto",
    }
    prdb.upsert_resolution(res_db, batch_id="B1", role="client", verdict=verdict)
    row = prdb.get_resolution(res_db, batch_id="B1", role="client")
    assert row is not None
    assert row["batch_id"]    == "B1"
    assert row["role"]        == "client"
    assert row["tier"]        == 2
    assert row["confidence"]  == 0.95
    assert row["reason"]      == "tax_id_exact"
    assert row["status"]      == "auto"
    assert row["evidence"]    == {"matched_on": "tax_id"}
    assert row["candidates"]  == [{"master_id": 1, "score": 100}]
    assert row["operator_override"] is False
    assert row["operator_user"] == "anonymous"
    assert row["created_at"]
    assert row["updated_at"]


def test_upsert_resolution_uniqueness_per_batch_role(res_db):
    """Re-upserting the same (batch, role) UPDATEs in place; created_at preserved."""
    v1 = {"parsed_name": "ALPHA", "tier": 6, "confidence": 0.0,
          "reason": "no_match", "status": "unresolved"}
    v2 = {"parsed_name": "ALPHA", "tier": 5, "confidence": 0.7,
          "reason": "fuzzy_name_country:90", "status": "auto"}
    a = prdb.upsert_resolution(res_db, batch_id="B2", role="client", verdict=v1)
    b = prdb.upsert_resolution(res_db, batch_id="B2", role="client", verdict=v2)
    rows = prdb.list_resolutions_for_batch(res_db, "B2")
    assert len(rows) == 1
    assert rows[0]["status"] == "auto"
    assert rows[0]["tier"]   == 5
    assert rows[0]["created_at"] == a["created_at"], \
        "created_at must be preserved across UPSERT"
    assert b["updated_at"] >= a["updated_at"]


def test_upsert_resolution_rejects_bad_role(res_db):
    with pytest.raises(ValueError):
        prdb.upsert_resolution(res_db, batch_id="B3", role="kontrahent",
                               verdict={"parsed_name": "X"})


def test_upsert_resolution_rejects_empty_batch(res_db):
    with pytest.raises(ValueError):
        prdb.upsert_resolution(res_db, batch_id="", role="client",
                               verdict={"parsed_name": "X"})


def test_upsert_resolution_rejects_empty_parsed_name(res_db):
    with pytest.raises(ValueError):
        prdb.upsert_resolution(res_db, batch_id="B4", role="client",
                               verdict={"parsed_name": ""})


def test_list_resolutions_for_batch_returns_both_roles(res_db):
    base = {"parsed_name": "X", "tier": 6, "confidence": 0.0,
            "reason": "no_match", "status": "unresolved"}
    prdb.upsert_resolution(res_db, batch_id="B5", role="client",   verdict=base)
    prdb.upsert_resolution(res_db, batch_id="B5", role="supplier", verdict=base)
    rows = prdb.list_resolutions_for_batch(res_db, "B5")
    assert {r["role"] for r in rows} == {"client", "supplier"}


def test_get_resolution_returns_none_for_missing(res_db):
    assert prdb.get_resolution(res_db, batch_id="MISSING", role="client") is None


# ── POST /contractor-resolution end-to-end ────────────────────────────────


def test_post_resolve_persists_auto_match(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post(
        "/api/v1/packing/BATCH-A/contractor-resolution",
        json={"role": "client", "parsed_name": "ACME POLAND Sp. z o.o.",
              "parsed_country": "PL"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"]               == "auto"
    assert body["tier"]                  == 3
    assert body["matched_master_type"]  == "client_master"
    assert body["matched_wfirma_id"]     == "100"
    # Stored row reads back
    g = client.get("/api/v1/packing/BATCH-A/contractor-resolution/client")
    assert g.status_code == 200
    assert g.json()["matched_wfirma_id"] == "100"


def test_post_resolve_persists_unresolved(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post(
        "/api/v1/packing/BATCH-B/contractor-resolution",
        json={"role": "client", "parsed_name": "ZZZZ COMPANY", "parsed_country": "PL"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unresolved"
    assert body["tier"]   == 6
    # Candidates still surfaced even when unresolved
    assert isinstance(body["candidates"], list)


def test_post_resolve_missing_role_422(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post(
        "/api/v1/packing/BATCH-C/contractor-resolution",
        json={"parsed_name": "X"},
    )
    assert r.status_code == 422


def test_post_resolve_empty_parsed_name_422(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post(
        "/api/v1/packing/BATCH-D/contractor-resolution",
        json={"role": "client", "parsed_name": ""},
    )
    assert r.status_code == 422


def test_list_endpoint_returns_count(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/B6/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND", "parsed_country": "PL"})
    client.post("/api/v1/packing/B6/contractor-resolution",
                json={"role": "supplier", "parsed_name": "ESTRELLA JEWELS LLP", "parsed_country": "IN"})
    r = client.get("/api/v1/packing/B6/contractor-resolution")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert {x["role"] for x in body["resolutions"]} == {"client", "supplier"}


def test_get_one_404_when_missing(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.get("/api/v1/packing/UNKNOWN/contractor-resolution/client")
    assert r.status_code == 404


# ── POST /confirm operator confirm vs override ────────────────────────────


def test_confirm_locks_auto_match(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/B7/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND Sp. z o.o.",
                      "parsed_country": "PL"})
    r = client.post(
        "/api/v1/packing/B7/contractor-resolution/confirm",
        headers={"X-Operator-User": "alice"},
        json={"role": "client"},   # no override fields → confirm current auto
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"]            == "confirmed"
    assert body["operator_override"] is False
    assert body["operator_user"]      == "alice"
    assert body["operator_at"]
    # Stored
    g = client.get("/api/v1/packing/B7/contractor-resolution/client")
    assert g.json()["status"] == "confirmed"


def test_override_must_pick_from_candidate_list(monkeypatch, res_db, cm_db, sup_db):
    """Hard rule: operator override must reference a master_id already in
    the candidate list. Free-form ids are rejected → no master row gets
    auto-created from this path."""
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/B8/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND",
                      "parsed_country": "PL"})
    r = client.post(
        "/api/v1/packing/B8/contractor-resolution/confirm",
        headers={"X-Operator-User": "bob"},
        json={"role": "client",
              "matched_master_type": "client_master",
              "matched_master_id":   999999,         # not a real id
              "matched_wfirma_id":   "999999"},
    )
    assert r.status_code == 422
    assert "candidate list" in r.json()["detail"].lower()


def test_override_records_operator_audit(monkeypatch, res_db, cm_db, sup_db):
    """Pick a DIFFERENT candidate from the candidate list → status flips to
    overridden, operator_override=1, operator_user/at recorded."""
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    # First resolve so that we know what candidates exist
    res = client.post("/api/v1/packing/B9/contractor-resolution",
                      json={"role": "client", "parsed_name": "ACME POLAND",
                            "parsed_country": "PL"}).json()
    auto_id = res["matched_master_id"]
    # Find another PL candidate id to override to
    other = next((c for c in res["candidates"] if c["master_id"] != auto_id), None)
    if other is None:
        pytest.skip("only one PL candidate in test seed; override path not exercisable here")
    r = client.post(
        "/api/v1/packing/B9/contractor-resolution/confirm",
        headers={"X-Operator-User": "carol"},
        json={"role": "client",
              "matched_master_type": "client_master",
              "matched_master_id":   other["master_id"],
              "matched_wfirma_id":   other["wfirma_id"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"]            == "overridden"
    assert body["operator_override"] is True
    assert body["operator_user"]      == "carol"


def test_confirm_404_when_no_prior_resolution(monkeypatch, res_db, cm_db, sup_db):
    """Operator can't confirm a batch that was never resolved."""
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post("/api/v1/packing/NOPE/contractor-resolution/confirm",
                    json={"role": "client"})
    assert r.status_code == 404


def test_operator_user_defaults_to_anonymous(monkeypatch, res_db, cm_db, sup_db):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/B10/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND",
                      "parsed_country": "PL"})
    r = client.post("/api/v1/packing/B10/contractor-resolution/confirm",
                    json={"role": "client"})   # no X-Operator-User header
    assert r.status_code == 200
    assert r.json()["operator_user"] == "anonymous"


# ── Trip-wires ────────────────────────────────────────────────────────────


def test_routes_module_does_not_import_wfirma_write_paths():
    src = (Path(__file__).resolve().parents[1] / "app" / "api" /
           "routes_packing_resolution.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_customer(", "create_contractor(",
        "update_customer(", "update_contractor(",
        "delete_customer(", "delete_contractor(",
        "post_invoice(", "create_invoice(", "issue_invoice(",
        "create_proforma(", "post_proforma(",
        "from ..services import proforma",
        "from ..services import wfirma_client",
        "import wfirma_client",
    ):
        assert forbidden not in src, \
            f"forbidden ref '{forbidden}' in routes_packing_resolution.py"


def test_resolve_route_does_not_call_wfirma_client(monkeypatch, res_db, cm_db, sup_db):
    """Trip-wire on every wFirma client attribute — none fires during a
    resolve+persist POST."""
    from service.app.services import wfirma_client as wfc
    called: list = []
    for attr in dir(wfc):
        if attr.startswith("_"):
            continue
        try:
            obj = getattr(wfc, attr)
        except Exception:
            continue
        if callable(obj):
            def _trip(*_a, _n=attr, **_k):
                called.append(_n)
                raise AssertionError(f"resolution route called wfirma_client.{_n}")
            try:
                monkeypatch.setattr(wfc, attr, _trip)
            except (AttributeError, TypeError):
                pass

    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/TW-1/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND",
                      "parsed_country": "PL"})
    client.post("/api/v1/packing/TW-1/contractor-resolution/confirm",
                json={"role": "client"})
    assert called == [], f"wfirma_client called: {called}"


def test_resolve_route_does_not_write_to_master_tables(monkeypatch, res_db, cm_db, sup_db):
    """Trip-wire on every customer_master / suppliers write entry point."""
    write_calls: list = []
    for attr in ("upsert_customer", "upsert_identity_only", "delete_customer"):
        if hasattr(cmdb, attr):
            original = getattr(cmdb, attr)
            def _trip(*a, _n=attr, _orig=original, **k):
                write_calls.append(f"cmdb.{_n}")
                raise AssertionError(f"resolution route wrote to cmdb.{_n}")
            monkeypatch.setattr(cmdb, attr, _trip)
    for attr in ("create_supplier", "update_supplier", "delete_supplier",
                 "sync_from_wfirma", "upsert_supplier_identity_from_wfirma"):
        if hasattr(sdb, attr):
            original = getattr(sdb, attr)
            def _trip(*a, _n=attr, _orig=original, **k):
                write_calls.append(f"sdb.{_n}")
                raise AssertionError(f"resolution route wrote to sdb.{_n}")
            monkeypatch.setattr(sdb, attr, _trip)

    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    client.post("/api/v1/packing/TW-2/contractor-resolution",
                json={"role": "client", "parsed_name": "ACME POLAND",
                      "parsed_country": "PL"})
    client.post("/api/v1/packing/TW-2/contractor-resolution/confirm",
                json={"role": "client"})
    assert write_calls == [], f"master writes triggered: {write_calls}"


# ── Generic across countries (PL / DE / IN) ───────────────────────────────


@pytest.mark.parametrize("name,country,expected_wfid", [
    ("ACME POLAND",   "PL", "100"),
    ("BETA",          "DE", "200"),
    ("GAMMA PVT LTD", "IN", "300"),
])
def test_resolve_route_generic_across_countries(
    monkeypatch, res_db, cm_db, sup_db, name, country, expected_wfid,
):
    client = _make_app(monkeypatch, res_db=res_db, cm_db=cm_db, sup_db=sup_db)
    r = client.post(f"/api/v1/packing/GEN-{country}/contractor-resolution",
                    json={"role": "client", "parsed_name": name,
                          "parsed_country": country})
    assert r.status_code == 200
    body = r.json()
    assert body["status"]            == "auto", f"{country}: expected auto, got {body}"
    assert body["matched_wfirma_id"] == expected_wfid

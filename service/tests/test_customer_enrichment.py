"""
Client Master external enrichment — classification pins, task lifecycle,
fail-closed validation, acceptance authority, audit, MCP surface.

Lesson A discipline: every acceptance test runs against real sqlite files
(customer_master.sqlite / customer_enrichment.sqlite / master_audit.sqlite
under tmp_path via the storage_root monkeypatch) — no stubs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import customer_external_enrichment as enrich  # noqa: E402
from app.services.customer_external_enrichment import (  # noqa: E402
    IDENTITY_CONTEXT_ONLY,
    RESEARCHABLE_PHASE_1,
    SENSITIVE_NEVER_DISCLOSE,
    EnrichmentValidationError,
    ProposalStateError,
    StaleProposalError,
    _build_identity_context,
)
from app.services.customer_master_db import (  # noqa: E402
    CustomerMaster,
    get_customer,
    init_db,
    upsert_customer,
)

HEADERS = {"X-API-Key": "test-key"}
MCP_URL = "/api/v1/mcp/customer-enrichment"
MCP_HEADERS = {"Authorization": "Bearer mcp-secret"}

SIX = frozenset({"bill_to_street", "bill_to_city", "bill_to_postal_code",
                 "bill_to_phone", "bill_to_email", "industry"})

_EVIDENCE = [{"source_url": "https://example.com/registry",
              "source_type": "registry"}]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")
    yield


@pytest.fixture()
def client():
    return TestClient(app_main.app)


def _cm(tmp_path):
    return tmp_path / "customer_master.sqlite"


def _en(tmp_path):
    return tmp_path / "customer_enrichment.sqlite"


def _seed_customer(tmp_path, contractor_id="C001", **overrides):
    db = _cm(tmp_path)
    init_db(db)
    upsert_customer(db, CustomerMaster(
        contractor_id, overrides.pop("bill_to_name", "Test GmbH"),
        overrides.pop("country", "DE"), **overrides))
    return db


def _full_sensitive_customer():
    """Fully populated customer incl. every sensitive family — for the
    disclosure pins. Never persisted; the serializer is what's under test."""
    return CustomerMaster(
        "C900", "Sensitive Sp. z o.o.", "PL",
        nip="5262759784",
        vat_eu_number="PL5262759784",
        bill_to_street="ul. Testowa 1",
        bill_to_city="Warszawa",
        bill_to_postal_code="00-001",
        bill_to_phone="+48 22 000 00 00",
        bill_to_email="office@example.com",
        industry="jewellery",
        bank_account="PL61109010140000071219812874",
        credit_limit=Decimal("50000"),
        credit_currency="EUR",
        kuke_approved=True,
        payment_terms_days=30,
        beneficial_owner="Jan Kowalski",
        aml_risk_rating="low",
        pep_check_result="clear",
        compliance_notes="internal only",
        notes="do not disclose",
        preferred_proforma_series_id=5,
    )


def _pipeline(tmp_path, field="bill_to_city", value="Berlin"):
    """Seed → build → claim → submit one proposal; return (task_id, proposal_id)."""
    cm, en = _seed_customer(tmp_path), _en(tmp_path)
    task = enrich.build_customer_enrichment_task("C001", cm, en)
    enrich.claim_enrichment_task(en, task["id"])
    enrich.submit_enrichment_result(en, task["id"], [
        {"field": field, "proposed_value": value, "confidence": "high",
         "reason": "public registry entry", "evidence": _EVIDENCE},
    ])
    conn = sqlite3.connect(en)
    try:
        pid = conn.execute(
            "SELECT id FROM customer_enrichment_proposals "
            "WHERE task_id = ? AND field = ?", (task["id"], field),
        ).fetchone()[0]
    finally:
        conn.close()
    return task["id"], pid


# ── 1-5: classification pins ─────────────────────────────────────────────────

def test_researchable_phase1_is_exactly_six_fields():
    assert RESEARCHABLE_PHASE_1 == SIX


def test_sensitive_set_contains_required_members():
    required = {"bank_account", "credit_limit", "kuke_approved",
                "aml_risk_rating", "pep_check_result", "compliance_notes",
                "notes", "preferred_proforma_series_id", "beneficial_owner"}
    assert required <= SENSITIVE_NEVER_DISCLOSE


def test_identity_context_never_leaks_sensitive_fields():
    ctx = _build_identity_context(_full_sensitive_customer())
    assert set(ctx.keys()) & SENSITIVE_NEVER_DISCLOSE == set()
    blob = json.dumps(ctx)
    assert "PL61109010140000071219812874" not in blob
    assert "do not disclose" not in blob
    assert "Jan Kowalski" not in blob


def test_identity_context_keys_are_exactly_the_eleven_allowed():
    ctx = _build_identity_context(_full_sensitive_customer())
    assert set(ctx.keys()) == IDENTITY_CONTEXT_ONLY | RESEARCHABLE_PHASE_1
    assert len(ctx) == 11


def test_identity_context_excludes_provenance_columns():
    ctx = _build_identity_context(_full_sensitive_customer())
    assert "last_enrichment_sync_at" not in ctx
    assert "enrichment_sync_source" not in ctx


# ── 6-9: task builder ────────────────────────────────────────────────────────

def test_task_builder_all_fields_missing(tmp_path):
    cm = _seed_customer(tmp_path)
    task = enrich.build_customer_enrichment_task("C001", cm, _en(tmp_path))
    assert task["status"] == "pending"
    assert task["missing_fields"] == sorted(SIX)


def test_task_builder_zero_work_returns_none(tmp_path):
    cm = _seed_customer(
        tmp_path,
        bill_to_street="Hauptstr. 1", bill_to_city="Berlin",
        bill_to_postal_code="10115", bill_to_phone="+49 30 1234567",
        bill_to_email="info@example.de", industry="jewellery")
    assert enrich.build_customer_enrichment_task(
        "C001", cm, _en(tmp_path)) is None


def test_task_builder_partial_missing_exact_list(tmp_path):
    cm = _seed_customer(tmp_path, bill_to_city="Berlin",
                        bill_to_phone="+49 30 1234567")
    task = enrich.build_customer_enrichment_task("C001", cm, _en(tmp_path))
    assert task["missing_fields"] == sorted(
        SIX - {"bill_to_city", "bill_to_phone"})


def test_task_snapshot_captures_current_values(tmp_path):
    cm = _seed_customer(tmp_path, bill_to_city="Berlin")
    task = enrich.build_customer_enrichment_task("C001", cm, _en(tmp_path))
    assert task["snapshot"]["bill_to_city"] == "Berlin"
    assert not task["snapshot"]["industry"]


# ── 10-13: validation fail-closed ────────────────────────────────────────────

def test_validation_rejects_unknown_field():
    with pytest.raises(EnrichmentValidationError):
        enrich.validate_enrichment_submission([
            {"field": "bank_account", "proposed_value": "PL61...",
             "confidence": "high", "evidence": _EVIDENCE}])


def test_validation_rejects_value_without_evidence():
    with pytest.raises(EnrichmentValidationError):
        enrich.validate_enrichment_submission([
            {"field": "bill_to_city", "proposed_value": "Berlin",
             "confidence": "high"}])


def test_validation_rejects_non_http_evidence_url():
    with pytest.raises(EnrichmentValidationError):
        enrich.validate_enrichment_submission([
            {"field": "bill_to_city", "proposed_value": "Berlin",
             "confidence": "high",
             "evidence": [{"source_url": "ftp://example.com/x"}]}])


def test_validation_rejects_oversized_value():
    with pytest.raises(EnrichmentValidationError):
        enrich.validate_enrichment_submission([
            {"field": "bill_to_city", "proposed_value": "x" * 501,
             "confidence": "high", "evidence": _EVIDENCE}])


# ── 14-15: lifecycle ─────────────────────────────────────────────────────────

def test_claim_moves_pending_to_researching(tmp_path):
    cm, en = _seed_customer(tmp_path), _en(tmp_path)
    task = enrich.build_customer_enrichment_task("C001", cm, en)
    claimed = enrich.claim_enrichment_task(en)
    assert claimed["id"] == task["id"]
    assert claimed["status"] == "researching"
    conn = sqlite3.connect(en)
    try:
        row = conn.execute(
            "SELECT status FROM customer_enrichment_tasks WHERE id = ?",
            (task["id"],)).fetchone()
    finally:
        conn.close()
    assert row[0] == "researching"


def test_stale_snapshot_blocks_acceptance(tmp_path, client, monkeypatch):
    task_id, pid = _pipeline(tmp_path)
    # Canonical changed since the snapshot: fingerprint mismatch -> stale.
    upsert_customer(_cm(tmp_path),
                    CustomerMaster("C001", "Test GmbH", "DE",
                                   bill_to_street="Neue Str. 9"))
    with pytest.raises(StaleProposalError):
        enrich.accept_enrichment_proposal(
            _en(tmp_path), _cm(tmp_path), pid, actor="tester")
    monkeypatch.setattr(settings, "customer_external_enrichment_enabled", True)
    r = client.post(
        f"/api/v1/customer-enrichment/proposals/{pid}/accept",
        headers=HEADERS)
    assert r.status_code == 409
    assert "ENRICHMENT_PROPOSAL_STALE" in json.dumps(r.json())


# ── 16-18: acceptance authority (real sqlite, no stubs) ──────────────────────

def test_accept_fills_empty_field_and_stamps_provenance(tmp_path):
    task_id, pid = _pipeline(tmp_path, field="bill_to_city", value="Berlin")
    result = enrich.accept_enrichment_proposal(
        _en(tmp_path), _cm(tmp_path), pid, actor="tester")
    assert result["wrote_to_master"] is True
    assert result["conflict_flag"] is False
    assert result["field_status"] == "accepted"
    assert get_customer(_cm(tmp_path), "C001").bill_to_city == "Berlin"
    conn = sqlite3.connect(_cm(tmp_path))
    try:
        src, at = conn.execute(
            "SELECT enrichment_sync_source, last_enrichment_sync_at "
            "FROM customer_master WHERE bill_to_contractor_id = 'C001'",
        ).fetchone()
    finally:
        conn.close()
    assert src == "cowork_external_enrichment"
    assert at


def test_accept_never_overwrites_existing_value(tmp_path):
    task_id, pid = _pipeline(tmp_path, field="bill_to_city", value="Berlin")
    # Canonical value appears after research. A real six-field change would
    # (correctly) trip the stale gate first, so to exercise the conflict
    # branch we refresh the task's snapshot_fp to the current canonical
    # fingerprint — real code, no stubs.
    upsert_customer(_cm(tmp_path),
                    CustomerMaster("C001", "Test GmbH", "DE",
                                   bill_to_city="Existing City"))
    fp = enrich.compute_snapshot_fingerprint(get_customer(_cm(tmp_path), "C001"))
    conn = sqlite3.connect(_en(tmp_path))
    try:
        conn.execute(
            "UPDATE customer_enrichment_tasks SET snapshot_fp = ? WHERE id = ?",
            (fp, task_id))
        conn.commit()
    finally:
        conn.close()
    result = enrich.accept_enrichment_proposal(
        _en(tmp_path), _cm(tmp_path), pid, actor="tester")
    assert result["conflict_flag"] is True
    assert result["wrote_to_master"] is False
    assert get_customer(_cm(tmp_path), "C001").bill_to_city == "Existing City"
    conn = sqlite3.connect(_en(tmp_path))
    try:
        status, flag = conn.execute(
            "SELECT field_status, conflict_flag FROM "
            "customer_enrichment_proposals WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    assert status == "accepted"
    assert flag == 1


def test_accept_writes_master_audit_row(tmp_path):
    task_id, pid = _pipeline(tmp_path, field="bill_to_email",
                             value="office@example.de")
    enrich.accept_enrichment_proposal(
        _en(tmp_path), _cm(tmp_path), pid, actor="tester")
    conn = sqlite3.connect(tmp_path / "master_audit.sqlite")
    try:
        row = conn.execute(
            "SELECT entity, after_json, reason FROM master_audit "
            "WHERE reason LIKE 'enrichment_proposal:%'").fetchone()
    finally:
        conn.close()
    assert row is not None
    entity, after_json, reason = row
    assert entity == "customers"
    assert pid in after_json
    assert reason == f"enrichment_proposal:{pid}"


# ── 19-22: MCP surface ───────────────────────────────────────────────────────

def _rpc(client, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(MCP_URL, json=body,
                       headers=headers if headers is not None else MCP_HEADERS)


def _enable_mcp(monkeypatch):
    monkeypatch.setattr(settings, "customer_enrichment_mcp_enabled", True)
    monkeypatch.setattr(settings, "customer_enrichment_mcp_token", "mcp-secret")


def test_mcp_dark_by_default_returns_503(client):
    r = _rpc(client, "initialize", headers={})
    assert r.status_code == 503


def test_mcp_wrong_bearer_returns_401(client, monkeypatch):
    _enable_mcp(monkeypatch)
    r = _rpc(client, "initialize",
             headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_mcp_tools_list_exposes_exactly_three_tools(client, monkeypatch):
    _enable_mcp(monkeypatch)
    r = _rpc(client, "tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "get_customer_enrichment_task",
        "submit_customer_enrichment_result",
        "get_customer_enrichment_task_status"}
    assert all("inputSchema" in t for t in tools)


def test_mcp_get_task_claims_pending_task(tmp_path, client, monkeypatch):
    _enable_mcp(monkeypatch)
    cm = _seed_customer(tmp_path)
    task = enrich.build_customer_enrichment_task("C001", cm, _en(tmp_path))
    r = _rpc(client, "tools/call",
             params={"name": "get_customer_enrichment_task", "arguments": {}})
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["task_id"] == task["id"]
    assert payload["status"] == "researching"
    assert payload["missing_fields"] == sorted(SIX)
    assert payload["identity_context"]["bill_to_name"] == "Test GmbH"
    assert "bank_account" not in json.dumps(payload)


# ── 23-24: contracts ─────────────────────────────────────────────────────────

def test_status_endpoint_has_canonical_shape(client, monkeypatch):
    monkeypatch.setattr(settings, "customer_external_enrichment_enabled", True)
    r = client.get("/api/v1/customer-enrichment/status", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    for key in ("healthy", "running", "last_started_at", "last_completed_at",
                "duration_ms", "processed", "created", "updated", "skipped",
                "errors", "last_error", "tasks_by_status"):
        assert key in body, key


def test_main_registers_both_enrichment_routers():
    source = Path(app_main.__file__).read_text(encoding="utf-8")
    assert ("from .api.routes_customer_enrichment import router "
            "as customer_enrichment_router") in source
    assert ("from .api.routes_customer_enrichment_mcp import router "
            "as customer_enrichment_mcp_router") in source
    assert "app.include_router(customer_enrichment_router)" in source
    assert "app.include_router(customer_enrichment_mcp_router)" in source

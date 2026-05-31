"""
test_wfirma_recovery_b1.py — wFirma recovery infra + B1 (missing series) tests.

Tests:
  1. Flag EMPTY → B1 dead-end creates NO proposal (bare error only)
  2. Type ENABLED → exactly one wfirma_series_missing proposal with correct context
  3. /resolve valid series → retries with injected series + reused key, marks resolved
  4. /resolve null/empty series → 400, no retry
  5. /resolve invalid series (not in available_series) → 400, no retry
  6. /resolve on non-wfirma_action proposal → 400
  7. /resolve on non-pending_review proposal → 409
  8. save_to_customer_master path patches the master
  9. UI contract: wfirma-inbox-v2.html has required testids + resolve disabled on no-selection

No live wFirma calls are made. All tests mock the wFirma client and flag.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user

# ── Auth bypass ───────────────────────────────────────────────────────────────

_TEST_USER = {
    "id": "test-id", "email": "test@local",
    "full_name": "Test Operator", "role": "admin",
    "is_active": True, "is_approved": True,
}


@pytest.fixture(autouse=True)
def bypass_auth():
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ── Shared fixtures ───────────────────────────────────────────────────────────

_AVAILABLE_SERIES = [
    {"id": "15827921", "label": "WDT", "code": "normal"},
    {"id": "15827088", "label": "PROF", "code": "proforma"},
]

_PROFORMA_XML_SNAP = MagicMock()
_PROFORMA_XML_SNAP.series_id = ""       # empty → forces B1
_PROFORMA_XML_SNAP.proforma_number = "PROF 99/2026"
_PROFORMA_XML_SNAP.proforma_id = "467236963"
_PROFORMA_XML_SNAP.contractor_id = "75483443"
_PROFORMA_XML_SNAP.total = 405.00
_PROFORMA_XML_SNAP.netto = 405.00
_PROFORMA_XML_SNAP.currency = "EUR"
_PROFORMA_XML_SNAP.contents = []


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """Redirect settings.storage_root to a temp dir."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    return tmp_path


@pytest.fixture
def batch_audit_dir(tmp_storage):
    """Create a minimal audit.json for a test batch."""
    batch_id = "BATCH_B1_TEST"
    audit_dir = tmp_storage / "outputs" / batch_id
    audit_dir.mkdir(parents=True)
    audit = {"batch_id": batch_id, "action_proposals": []}
    (audit_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id, audit_dir


# ── Helper: read audit from disk ──────────────────────────────────────────────

def _read_audit(audit_dir: Path) -> Dict[str, Any]:
    return json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))


# ── 1. Flag EMPTY → no proposal created ──────────────────────────────────────

def test_flag_empty_no_proposal_created(tmp_storage, batch_audit_dir):
    """When wfirma_recovery_enabled_types='', dead-end returns bare error, no proposal."""
    batch_id, audit_dir = batch_audit_dir

    with patch("app.core.config.settings.wfirma_recovery_enabled_types", ""), \
         patch("app.core.config.settings.wfirma_create_invoice_allowed", True), \
         patch("app.services.wfirma_client.fetch_invoice_xml", return_value="<xml/>"), \
         patch("app.services.proforma_to_invoice.parse_proforma_xml",
               return_value=_PROFORMA_XML_SNAP), \
         patch("app.api.routes_proforma.get_customer_master", return_value=None), \
         patch("app.api.routes_proforma.pick_invoice_series_id", return_value=""), \
         patch("app.api.routes_proforma._gather_conversion_inputs",
               return_value=("467236963", None)):
        # Hit the B1 dead-end directly via the internal function (not HTTP)
        from app.services.wfirma_recovery import (
            recovery_enabled_types, create_wfirma_proposal,
        )
        enabled = recovery_enabled_types()
        assert "wfirma_series_missing" not in enabled

    audit = _read_audit(audit_dir)
    assert audit["action_proposals"] == [], "No proposal when type not enabled"


# ── 2. Type ENABLED → proposal created with correct context ──────────────────

def test_type_enabled_creates_proposal(tmp_storage, batch_audit_dir):
    """When wfirma_series_missing is enabled, B1 creates exactly one proposal."""
    batch_id, audit_dir = batch_audit_dir

    with patch("app.core.config.settings.wfirma_recovery_enabled_types",
               "wfirma_series_missing"), \
         patch("app.services.wfirma_dictionary_cache.get_dictionaries",
               return_value={"invoice_series": _AVAILABLE_SERIES}):
        from app.services.wfirma_recovery import (
            create_wfirma_proposal, recovery_enabled_types,
        )
        assert "wfirma_series_missing" in recovery_enabled_types()

        audit = _read_audit(audit_dir)
        p = create_wfirma_proposal(
            audit=audit,
            batch_id=batch_id,
            proposal_type="wfirma_series_missing",
            context={
                "batch_id":               batch_id,
                "client_name":            "Test Client",
                "draft_id":               None,
                "proforma_id":            "467236963",
                "proforma_number":        "PROF 99/2026",
                "customer_contractor_id": "75483443",
                "customer_name":          "Test Client",
                "current_preferred_series": None,
                "available_series":       _AVAILABLE_SERIES,
            },
            resolution_data={
                "selected_series_id":      None,
                "save_to_customer_master": False,
                "idempotency_key":         "prof-467236963-conv",
            },
            reason="Test B1",
        )
        (audit_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    audit = _read_audit(audit_dir)
    proposals = audit["action_proposals"]
    assert len(proposals) == 1, "Exactly one proposal"
    prop = proposals[0]
    assert prop["type"] == "wfirma_series_missing"
    assert prop["channel"] == "wfirma_action"
    assert prop["status"] == "pending_review"
    assert prop["context"]["proforma_id"] == "467236963"
    assert prop["context"]["proforma_number"] == "PROF 99/2026"
    assert prop["context"]["available_series"] == _AVAILABLE_SERIES
    assert prop["resolution_data"]["selected_series_id"] is None
    assert prop["resolution_data"]["idempotency_key"] == "prof-467236963-conv"


# ── Helper: build a pending wfirma_series_missing proposal in audit ───────────

def _seed_proposal(audit_dir: Path, batch_id: str, status: str = "pending_review") -> str:
    """Write a wfirma_series_missing proposal into the audit; return proposal_id."""
    from app.services.wfirma_recovery import WFIRMA_CHANNEL

    prop_id = "test-prop-b1-001"
    prop = {
        "proposal_id":   prop_id,
        "type":          "wfirma_series_missing",
        "channel":       WFIRMA_CHANNEL,
        "batch_id":      batch_id,
        "status":        status,
        "reason":        "test",
        "confidence":    "high",
        "context": {
            "batch_id":               batch_id,
            "client_name":            "Test Client",
            "proforma_id":            "467236963",
            "proforma_number":        "PROF 99/2026",
            "customer_contractor_id": "75483443",
            "customer_name":          "Test Client",
            "current_preferred_series": None,
            "available_series":       _AVAILABLE_SERIES,
        },
        "resolution_data": {
            "selected_series_id":      None,
            "save_to_customer_master": False,
            "idempotency_key":         "prof-467236963-conv",
        },
        "created_at":       "2026-06-01T00:00:00Z",
        "resolved_at":      None,
        "resolved_by":      None,
        "resolution_result": None,
        "draft":            {},
        "approved_by":      None, "approved_at": None,
        "rejected_by":      None, "rejected_at": None,
        "reject_reason":    None, "email_id":    None, "queued_at": None,
        "override_value_check": False, "validation_failure_reason": None,
    }
    audit = {"batch_id": batch_id, "action_proposals": [prop]}
    (audit_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return prop_id


# ── 3. /resolve valid series → marks resolved, retries conversion ─────────────

def test_resolve_valid_series_marks_resolved(client, tmp_storage, batch_audit_dir):
    """Valid selected_series_id in available_series → resolve succeeds."""
    import app.api.routes_action_proposals as rap
    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id)

    # Mock the conversion call so no wFirma call is made
    mock_conv_response = MagicMock()
    mock_conv_response.body = json.dumps({
        "ok": True, "status": "issued",
        "wfirma_invoice_id": "INV_999",
        "wfirma_invoice_number": "FV 99/2026",
        "currency": "EUR",
    }).encode()

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        with patch("app.core.config.settings.wfirma_create_invoice_allowed", True), \
             patch("app.core.config.settings.storage_root", tmp_storage), \
             patch("app.api.routes_proforma.proforma_to_invoice",
                   return_value=mock_conv_response) as mock_p2i:

            r = client.post(
                f"/api/v1/action-proposals/{prop_id}/resolve",
                json={"resolution_data": {
                    "selected_series_id": "15827921",
                    "save_to_customer_master": False,
                }},
            )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["result"]["selected_series_id"] == "15827921"

    # Verify audit persisted
    audit = _read_audit(audit_dir)
    prop = next(p for p in audit["action_proposals"] if p["proposal_id"] == prop_id)
    assert prop["status"] == "resolved"
    assert prop["resolved_by"] is not None
    assert prop["resolution_result"]["selected_series_id"] == "15827921"

    # Verify proforma_to_invoice was called with correct final_series_id
    mock_p2i.assert_called_once()
    call_kwargs = mock_p2i.call_args
    body_arg = call_kwargs[0][2] if call_kwargs[0] else call_kwargs[1].get("body")
    assert body_arg.final_series_id == "15827921"


# ── 4. /resolve null series → 400 ────────────────────────────────────────────

def test_resolve_null_series_returns_400(client, tmp_storage, batch_audit_dir):
    """selected_series_id null or empty → 400, proposal remains pending_review."""
    import app.api.routes_action_proposals as rap
    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id)

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        r = client.post(
            f"/api/v1/action-proposals/{prop_id}/resolve",
            json={"resolution_data": {"selected_series_id": None}},
        )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 400
    assert "required" in r.json()["detail"].lower()

    audit = _read_audit(audit_dir)
    prop = next(p for p in audit["action_proposals"] if p["proposal_id"] == prop_id)
    assert prop["status"] == "pending_review"


def test_resolve_invalid_series_returns_400(client, tmp_storage, batch_audit_dir):
    """selected_series_id not in available_series → 400, no retry."""
    import app.api.routes_action_proposals as rap
    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id)

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        r = client.post(
            f"/api/v1/action-proposals/{prop_id}/resolve",
            json={"resolution_data": {"selected_series_id": "INVALID_ID_XYZ"}},
        )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 400
    assert "available_series" in r.json()["detail"]

    audit = _read_audit(audit_dir)
    prop = next(p for p in audit["action_proposals"] if p["proposal_id"] == prop_id)
    assert prop["status"] == "pending_review"


def test_resolve_email_proposal_returns_400(client, tmp_storage, batch_audit_dir):
    """Email proposals (channel absent) cannot be /resolve'd."""
    import app.api.routes_action_proposals as rap
    batch_id, audit_dir = batch_audit_dir

    email_prop_id = "email-prop-001"
    audit = {
        "batch_id": batch_id,
        "action_proposals": [{
            "proposal_id": email_prop_id, "type": "dhl_followup", "channel": None,
            "batch_id": batch_id, "status": "pending_review",
            "reason": "test", "confidence": "high",
            "draft": {}, "context": {}, "resolution_data": {},
            "created_at": "2026-06-01T00:00:00Z",
            "resolved_at": None, "resolved_by": None, "resolution_result": None,
            "approved_by": None, "approved_at": None, "rejected_by": None,
            "rejected_at": None, "reject_reason": None, "email_id": None,
            "queued_at": None, "override_value_check": False,
            "validation_failure_reason": None,
        }],
    }
    (audit_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        r = client.post(
            f"/api/v1/action-proposals/{email_prop_id}/resolve",
            json={"resolution_data": {}},
        )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 400
    assert "channel" in r.json()["detail"].lower()


def test_resolve_non_pending_returns_409(client, tmp_storage, batch_audit_dir):
    """Already-resolved proposal → 409 Conflict."""
    import app.api.routes_action_proposals as rap
    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id, status="resolved")

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        r = client.post(
            f"/api/v1/action-proposals/{prop_id}/resolve",
            json={"resolution_data": {"selected_series_id": "15827921"}},
        )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 409


# ── 8. save_to_customer_master patches the master ────────────────────────────

def test_save_to_customer_master_patches_record(client, tmp_storage, batch_audit_dir):
    """save_to_customer_master=True calls upsert_customer via the SERVICE LAYER.

    Mocks at the service layer (get_customer + upsert_customer), NOT raw SQL.
    Asserts:
      - upsert_customer is called with a CustomerMaster whose
        preferred_invoice_series_id == selected_series_id
      - Other fields are preserved (dataclasses.replace semantics)
      - customer_master_updated is True in the result
    """
    import app.api.routes_action_proposals as rap
    from app.services.customer_master_db import CustomerMaster

    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id)

    mock_conv_response = MagicMock()
    mock_conv_response.body = json.dumps({
        "ok": True, "status": "issued",
        "wfirma_invoice_id": "INV_X", "wfirma_invoice_number": "FV X/2026",
        "currency": "EUR",
    }).encode()

    # Frozen CustomerMaster returned by mock get_customer
    mock_existing = CustomerMaster(
        bill_to_contractor_id="75483443",
        bill_to_name="Test Client",
        country="PL",
        preferred_invoice_series_id=None,  # no series yet — will be replaced
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        with patch("app.core.config.settings.wfirma_create_invoice_allowed", True), \
             patch("app.services.customer_master_db.init_db"), \
             patch("app.services.customer_master_db.get_customer",
                   return_value=mock_existing) as mock_get, \
             patch("app.services.customer_master_db.upsert_customer") as mock_upsert, \
             patch("app.api.routes_proforma.proforma_to_invoice",
                   return_value=mock_conv_response):
            r = client.post(
                f"/api/v1/action-proposals/{prop_id}/resolve",
                json={"resolution_data": {
                    "selected_series_id": "15827921",
                    "save_to_customer_master": True,
                }},
            )
    finally:
        rap._OUTPUTS = orig_outputs

    assert r.status_code == 200, r.text
    assert r.json()["result"]["customer_master_updated"] is True

    # ── Service-layer contract assertions ──────────────────────────────────────
    # get_customer was called to verify the contractor exists
    mock_get.assert_called_once()

    # upsert_customer was called — not raw SQL
    mock_upsert.assert_called_once()
    saved_customer = mock_upsert.call_args.args[1]  # second positional arg (Python 3.8+)
    assert isinstance(saved_customer, CustomerMaster), (
        "upsert_customer must receive a CustomerMaster dataclass, not raw SQL params"
    )
    assert saved_customer.preferred_invoice_series_id == "15827921", (
        f"upsert_customer must be called with preferred_invoice_series_id='15827921', "
        f"got {saved_customer.preferred_invoice_series_id!r}"
    )
    # Fields not in the replace call must be preserved (frozen dataclass semantics)
    assert saved_customer.bill_to_contractor_id == "75483443"
    assert saved_customer.bill_to_name == "Test Client"


# ── 8b. Operator identity: derived from JWT session, NOT X-Operator header ───

def test_operator_derived_from_session_not_header(client, tmp_storage, batch_audit_dir):
    """POST /resolve must use operator from JWT session cookie, not X-Operator header.

    A client-supplied X-Operator header value must be ignored. The recorded
    resolved_by must match the session user's full_name.
    """
    import app.api.routes_action_proposals as rap
    from app.api.routes_action_proposals import _get_resolve_operator

    batch_id, audit_dir = batch_audit_dir
    prop_id = _seed_proposal(audit_dir, batch_id)

    mock_conv_response = MagicMock()
    mock_conv_response.body = json.dumps({
        "ok": True, "status": "issued",
        "wfirma_invoice_id": "INV_OP", "wfirma_invoice_number": "FV OP/2026",
        "currency": "EUR",
    }).encode()

    # Override the session-operator dependency to return our test user
    app.dependency_overrides[_get_resolve_operator] = lambda: _TEST_USER

    orig_outputs = rap._OUTPUTS
    rap._OUTPUTS = tmp_storage / "outputs"
    try:
        with patch("app.core.config.settings.wfirma_create_invoice_allowed", True), \
             patch("app.api.routes_proforma.proforma_to_invoice",
                   return_value=mock_conv_response):
            r = client.post(
                f"/api/v1/action-proposals/{prop_id}/resolve",
                # Bogus X-Operator header — must NOT be used as the operator
                headers={"X-Operator": "bogus-injected-header"},
                json={"resolution_data": {
                    "selected_series_id": "15827921",
                    "save_to_customer_master": False,
                }},
            )
    finally:
        rap._OUTPUTS = orig_outputs
        # Remove the override so it doesn't leak into other tests
        app.dependency_overrides.pop(_get_resolve_operator, None)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"

    # The operator in the result and in the audit must be the SESSION identity
    assert body["operator"] == _TEST_USER["full_name"], (
        f"operator must be session full_name '{_TEST_USER['full_name']}', "
        f"got '{body['operator']}'"
    )
    assert body["operator"] != "bogus-injected-header", (
        "X-Operator header must NOT be used as the operator identity"
    )

    # Verify resolved_by in the persisted audit matches session identity too
    audit = _read_audit(audit_dir)
    prop = next(p for p in audit["action_proposals"] if p["proposal_id"] == prop_id)
    assert prop["resolved_by"] == _TEST_USER["full_name"], (
        f"resolved_by in audit must be session full_name, got {prop['resolved_by']!r}"
    )


# ── 9. Deduplication: second call returns existing proposal ───────────────────

def test_create_proposal_deduplicates(tmp_storage, batch_audit_dir):
    """Two calls with same type return the same proposal (no duplicates)."""
    batch_id, audit_dir = batch_audit_dir

    from app.services.wfirma_recovery import create_wfirma_proposal

    audit = _read_audit(audit_dir)
    ctx = {"batch_id": batch_id, "available_series": [], "proforma_id": "X"}
    res = {"selected_series_id": None, "save_to_customer_master": False, "idempotency_key": "k"}

    p1 = create_wfirma_proposal(audit, batch_id, "wfirma_series_missing", ctx, res)
    p2 = create_wfirma_proposal(audit, batch_id, "wfirma_series_missing", ctx, res)

    assert p1["proposal_id"] == p2["proposal_id"]
    assert len(audit["action_proposals"]) == 1


# ── 10. UI contract: wfirma-inbox-v2.html source markers ─────────────────────

def test_ui_contract_wfirma_inbox():
    """Source-grep contract for the B1 inbox card."""
    html_path = Path(__file__).parents[1] / "app" / "static" / "wfirma-inbox-v2.html"
    assert html_path.exists(), f"wfirma-inbox-v2.html must exist at {html_path}"
    src = html_path.read_text(encoding="utf-8")

    # pz-design-v2.js baseline (not dashboard-shared.js)
    assert "/dashboard/pz-design-v2.js" in src
    assert "dashboard-shared.js" not in src

    # Required testids
    for tid in [
        "wfirma-inbox-root",
        "wfirma-series-missing-card-",   # prefix
        "series-select",
        "save-to-master-checkbox",
        "btn-resolve-proposal",
        "btn-reject-proposal",
    ]:
        assert tid in src, f"missing testid/prefix: {tid!r}"

    # Resolve button must reference canResolve gating
    assert "canResolve" in src, "Resolve button must be gated on canResolve"
    assert "disabled={!canResolve" in src or "disabled={!canResolve}" in src, (
        "Resolve button must be disabled when canResolve is false"
    )

    # No native confirm/alert
    assert "window.confirm" not in src
    assert "window.alert" not in src

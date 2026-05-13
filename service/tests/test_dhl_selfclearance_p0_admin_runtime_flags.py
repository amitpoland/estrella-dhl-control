"""
test_dhl_selfclearance_p0_admin_runtime_flags.py — admin endpoint round-trip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


_RUNTIME_FLAG_NAMES = (
    "dhl_selfclearance_p2_live_enabled",
    "dhl_selfclearance_p2_shadow_mode",
    "dhl_selfclearance_p3_live_enabled",
    "dhl_selfclearance_p3_shadow_mode",
    "dhl_selfclearance_p3_tracker_paused",
    "dhl_selfclearance_p4_live_enabled",
    "dhl_selfclearance_p4_shadow_mode",
    "dhl_selfclearance_p5_live_enabled",
    "dhl_selfclearance_p5_shadow_mode",
    "dhl_selfclearance_p5_pz_trigger_enabled",
    "dhl_selfclearance_p4_classifier_min_confidence",
    "dhl_selfclearance_p5_classifier_min_confidence",
    "dhl_selfclearance_followup_working_interval_sec",
    "dhl_selfclearance_followup_offhours_interval_sec",
    "dhl_selfclearance_followup_working_hours_window",
    "dhl_selfclearance_followup_livelock_budget_hours",
    "dhl_selfclearance_value_threshold_usd",
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # Snapshot current flag values so endpoint setattr() does not leak across tests.
    snapshot = {name: getattr(settings, name) for name in _RUNTIME_FLAG_NAMES}

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    from app.main import app
    yield TestClient(app)

    # Restore — the admin endpoint flips settings via direct setattr(); restore
    # via the same channel so subsequent tests see the documented defaults.
    for name, value in snapshot.items():
        try:
            setattr(settings, name, value)
        except Exception:
            pass


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_post_without_api_key_returns_401(client):
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": True, "actor": "amit"},
    )
    assert r.status_code == 401


def test_post_with_wrong_api_key_returns_401(client):
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers={"X-API-Key": "wrong-key"},
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": True, "actor": "amit"},
    )
    assert r.status_code == 401


def test_get_without_api_key_returns_401(client):
    r = client.get("/api/v1/admin/runtime-flags/self-clearance")
    assert r.status_code == 401


# ── Happy path round-trip ─────────────────────────────────────────────────────

def test_flip_then_read_back(client):
    headers = {"X-API-Key": "test-key-secret"}
    pre = client.get("/api/v1/admin/runtime-flags/self-clearance", headers=headers)
    assert pre.status_code == 200
    assert pre.json()["dhl_selfclearance_p2_live_enabled"] is False

    flip = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": True, "actor": "amit", "reason": "P2 promotion test"},
    )
    assert flip.status_code == 200
    body = flip.json()
    assert body["status"] == "ok"
    assert body["old_value"] is False
    assert body["new_value"] is True

    post = client.get("/api/v1/admin/runtime-flags/self-clearance", headers=headers)
    assert post.json()["dhl_selfclearance_p2_live_enabled"] is True


def test_audit_log_entry_written(client, tmp_path):
    headers = {"X-API-Key": "test-key-secret"}
    # Issue #49: P4 live requires P3 + P2 live. Seed chain via direct setattr
    # (bypassing the admin endpoint to avoid noisy audit entries).
    setattr(settings, "dhl_selfclearance_p2_live_enabled", True)
    setattr(settings, "dhl_selfclearance_p3_live_enabled", True)
    client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p4_live_enabled",
              "value": True, "actor": "tejal", "reason": "shadow promotion"},
    )
    audit_log = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    assert audit_log.exists()
    lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert any(
        json.loads(line).get("event") == "admin_runtime_flag_flipped"
        and json.loads(line).get("flag_name") == "dhl_selfclearance_p4_live_enabled"
        and json.loads(line).get("actor") == "tejal"
        for line in lines
    )


def test_runtime_store_json_written(client, tmp_path):
    headers = {"X-API-Key": "test-key-secret"}
    client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p3_tracker_paused",
              "value": True, "actor": "amit"},
    )
    store = tmp_path / "dhl_selfclearance_runtime_flags.json"
    assert store.exists()
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data["dhl_selfclearance_p3_tracker_paused"] is True


# ── Validation paths (templated errors) ───────────────────────────────────────

def test_unknown_flag_returns_400_with_templated_error(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "not_a_real_flag", "value": True, "actor": "amit"},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "UNKNOWN_FLAG"
    assert detail["field"] == "flag_name"
    assert "hint" in detail


def test_wrong_type_for_bool_flag_returns_400(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": "yes", "actor": "amit"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "WRONG_TYPE"


def test_wrong_type_for_int_flag_returns_400(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_followup_working_interval_sec",
              "value": "two_hours", "actor": "amit"},
    )
    assert r.status_code == 400


def test_missing_flag_name_returns_400(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "", "value": True, "actor": "amit"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["field"] == "flag_name"
    assert r.json()["detail"]["error_code"] == "MISSING_FIELD"


def test_missing_actor_returns_400(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": True, "actor": ""},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["field"] == "actor"
    assert r.json()["detail"]["error_code"] == "MISSING_FIELD"


def test_float_flag_accepts_int_or_float(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p4_classifier_min_confidence",
              "value": 0.9, "actor": "amit"},
    )
    assert r.status_code == 200


def test_response_carries_no_raw_exception_strings(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "not_a_flag", "value": 1, "actor": "amit"},
    )
    detail_text = json.dumps(r.json())
    assert "Traceback" not in detail_text
    assert "Exception" not in detail_text
    assert "KeyError" not in detail_text


def test_get_returns_all_allowed_flags(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.get("/api/v1/admin/runtime-flags/self-clearance", headers=headers)
    body = r.json()
    for name in [
        "dhl_selfclearance_p2_live_enabled",
        "dhl_selfclearance_p3_tracker_paused",
        "dhl_selfclearance_p5_pz_trigger_enabled",
        "dhl_selfclearance_p4_classifier_min_confidence",
        "dhl_selfclearance_value_threshold_usd",
    ]:
        assert name in body


# ── Boot-time replay of persisted store ──────────────────────────────────────

def test_load_persisted_flags_replays_store_onto_settings(monkeypatch, tmp_path):
    """Backend-safety MEDIUM remediation: after a service restart, the JSON
    store must be replayed onto in-memory `settings`."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    snapshot = settings.dhl_selfclearance_p2_live_enabled  # default False

    # Simulate a previous operator flip persisted to the store.
    import json as _json
    store_path = tmp_path / "dhl_selfclearance_runtime_flags.json"
    store_path.write_text(
        _json.dumps({"dhl_selfclearance_p2_live_enabled": True}),
        encoding="utf-8",
    )

    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    applied = load_persisted_flags_into_settings()
    try:
        assert "dhl_selfclearance_p2_live_enabled" in applied
        assert applied["dhl_selfclearance_p2_live_enabled"] is True
        assert settings.dhl_selfclearance_p2_live_enabled is True
    finally:
        setattr(settings, "dhl_selfclearance_p2_live_enabled", snapshot)


def test_load_persisted_flags_skips_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    import json as _json
    (tmp_path / "dhl_selfclearance_runtime_flags.json").write_text(
        _json.dumps({"not_a_real_flag": True}),
        encoding="utf-8",
    )
    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    applied = load_persisted_flags_into_settings()
    assert "not_a_real_flag" not in applied


def test_load_persisted_flags_skips_wrong_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    import json as _json
    (tmp_path / "dhl_selfclearance_runtime_flags.json").write_text(
        _json.dumps({"dhl_selfclearance_p2_live_enabled": "not_a_bool"}),
        encoding="utf-8",
    )
    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    applied = load_persisted_flags_into_settings()
    assert "dhl_selfclearance_p2_live_enabled" not in applied


def test_load_persisted_flags_absent_store_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    assert load_persisted_flags_into_settings() == {}


# ── Rejected-audit (tamper-evidence) ─────────────────────────────────────────

def test_rejected_audit_row_written_on_unknown_flag(client, tmp_path):
    headers = {"X-API-Key": "test-key-secret"}
    client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "not_a_real_flag", "value": True, "actor": "amit"},
    )
    audit_log = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    assert audit_log.exists()
    text = audit_log.read_text(encoding="utf-8")
    assert "admin_runtime_flag_rejected" in text
    assert "UNKNOWN_FLAG" in text


# ── Audit-write-failure surfaces ─────────────────────────────────────────────

def test_post_200_response_carries_audit_write_failed_flag(client):
    headers = {"X-API-Key": "test-key-secret"}
    r = client.post(
        "/api/v1/admin/runtime-flags/self-clearance",
        headers=headers,
        json={"flag_name": "dhl_selfclearance_p2_live_enabled",
              "value": True, "actor": "amit"},
    )
    assert r.status_code == 200
    assert "audit_write_failed" in r.json()
    assert r.json()["audit_write_failed"] is False

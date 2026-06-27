"""
Tests for GET /api/v1/deploy/status.

Coverage:
  - 401 without API key
  - 200 with version.json only (no TASK_STATE.md configured)
  - 200 with version.json + TASK_STATE.md (full enrichment)
  - Graceful degradation when version.json is missing
  - Graceful degradation when TASK_STATE.md path is missing file
  - GATE 2 blocked flag set correctly when impl count > 3
  - Cache-Control: no-store header present
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("deploy_status_storage")


@pytest.fixture(scope="module")
def client(tmp_storage):
    with patch.object(settings, "storage_root", tmp_storage), \
         patch.object(settings, "deploy_state_md_path", None):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-Key": settings.api_key or "test-key"}


_TASK_STATE_CLOSED = """\
---
name: task-state-deploy-closed
metadata:
  type: project
---

# DEPLOYMENT STATUS (2026-06-27)

**CLOSED** — SHA `361547115a` is live on production.

| Gate | Result |
|---|---|
| PZ regression | 160/160 |
| Carrier tests | 509/469 |
| PZService | Running |
| Logs | clean |

---

# GATE 2 — CURRENT STATE (2026-06-27)

| # | Title | Type | Notes |
|---|---|---|---|
| #771 | fix(deploy): poll-until-Running | governance/script | deploy gate only |
| #768 | fix(dhl-monitor): DSK-chase START lock | impl | GATE-4 salvage |
| #767 | fix(ui): preview-result panel response keys | impl | |
| #766 | fix(routes-pz): VerificationSummary fields | impl | |
| #765 | fix(authority): six authorities + two-signal | impl | |

**GATE 2 = 4 impl PRs open** (+ #771 governance-only). No new impl PRs until queue reduces to ≤3.
"""

_TASK_STATE_OPEN = """\
# DEPLOYMENT STATUS

**OPEN** — SHA `abc1234` is live on production.

**GATE 2 = 2 impl PRs open**.
"""


class TestAuthGate:
    def test_requires_api_key(self, tmp_path):
        # Auth only enforces when api_key is non-empty (dev mode has "" = no auth).
        # Patch a non-empty key so the guard is active, then call without a key.
        storage = tmp_path / "auth_test_storage"
        storage.mkdir()
        with patch.object(settings, "storage_root", storage), \
             patch.object(settings, "api_key", "secret-key-for-test"), \
             patch.object(settings, "deploy_state_md_path", None):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status")
        assert r.status_code == 401


class TestVersionJsonOnly:
    def test_returns_200_no_task_state(self, tmp_storage):
        version_file = tmp_storage / "version.json"
        version_file.write_text(json.dumps({
            "commit":      "deadbeef",
            "deployed_at": "2026-06-27T10:00:00+00:00",
        }))
        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", None):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        assert r.status_code == 200
        data = r.json()
        assert data["live_sha"] == "deadbeef"
        assert data["deployed_at"] == "2026-06-27T10:00:00+00:00"
        assert data["data_sources"]["version_json"] is True
        assert data["data_sources"]["task_state_md"] is False
        assert any("DEPLOY_STATE_MD_PATH" in w for w in data["warnings"])

    def test_no_cache_headers(self, tmp_storage):
        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", None):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())
        assert "no-store" in r.headers.get("cache-control", "")


class TestVersionJsonMissing:
    def test_degrades_gracefully(self, tmp_path):
        empty_storage = tmp_path / "empty_storage"
        empty_storage.mkdir()
        with patch.object(settings, "storage_root", empty_storage), \
             patch.object(settings, "deploy_state_md_path", None):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        assert r.status_code == 200
        data = r.json()
        assert data["live_sha"] == "dev"
        assert data["deployed_at"] == "not deployed"
        assert data["data_sources"]["version_json"] is False


class TestTaskStateMd:
    def test_full_enrichment(self, tmp_storage, tmp_path):
        version_file = tmp_storage / "version.json"
        version_file.write_text(json.dumps({
            "commit": "361547115a",
            "deployed_at": "2026-06-27T10:00:00+00:00",
        }))
        md_file = tmp_path / "TASK_STATE.md"
        md_file.write_text(_TASK_STATE_CLOSED, encoding="utf-8")

        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", str(md_file)):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        assert r.status_code == 200
        data = r.json()

        assert data["deployment_status"] == "CLOSED"
        assert data["task_state_sha"] == "361547115a"
        assert data["data_sources"]["task_state_md"] is True
        assert data["warnings"] == []

        # PR classification
        impl_numbers = [p["number"] for p in data["open_impl_prs"]]
        gov_numbers  = [p["number"] for p in data["open_governance_prs"]]
        assert 768 in impl_numbers
        assert 771 in gov_numbers

        # Gates parsed
        gates = data["verification_gates"]
        assert "pz_regression" in gates or "carrier_tests" in gates

    def test_gate2_blocked_when_over_limit(self, tmp_storage, tmp_path):
        md_file = tmp_path / "TASK_STATE_blocked.md"
        md_file.write_text(_TASK_STATE_CLOSED, encoding="utf-8")  # 4 impl PRs → blocked

        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", str(md_file)):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        data = r.json()
        assert data["open_impl_pr_count"] == 4
        assert data["gate_2_limit"] == 3
        assert data["gate_2_blocked"] is True

    def test_gate2_clear_when_under_limit(self, tmp_storage, tmp_path):
        md_file = tmp_path / "TASK_STATE_open.md"
        md_file.write_text(_TASK_STATE_OPEN, encoding="utf-8")  # 2 impl PRs → not blocked

        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", str(md_file)):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        data = r.json()
        assert data["deployment_status"] == "OPEN"
        assert data["open_impl_pr_count"] == 2
        assert data["gate_2_blocked"] is False

    def test_missing_file_produces_warning(self, tmp_storage, tmp_path):
        missing = tmp_path / "nonexistent_TASK_STATE.md"

        with patch.object(settings, "storage_root", tmp_storage), \
             patch.object(settings, "deploy_state_md_path", str(missing)):
            with TestClient(app, raise_server_exceptions=True) as c:
                r = c.get("/api/v1/deploy/status", headers=_auth())

        assert r.status_code == 200
        data = r.json()
        assert data["data_sources"]["task_state_md"] is False
        assert any("not found" in w for w in data["warnings"])

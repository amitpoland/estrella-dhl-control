"""
test_proposal_refresh.py — Proposal refresh integration tests.

Tests:
  1. monitor sweep creates proposal when trigger detected
  2. repeated sweep does not duplicate proposal (last_seen_at updated)
  3. proposal resolves when trigger disappears
  4. created_at preserved, last_seen_at updated on repeat
  5. manual refresh endpoint works
  6. no financial fields modified
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ── Path + env ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TMP_ROOT = Path("/tmp/test_proposal_refresh")
os.environ.setdefault("API_KEY",      "test-key")
os.environ.setdefault("STORAGE_ROOT", str(_TMP_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(hours_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _make_batch(awb: str = "1234567890", extra: Dict[str, Any] | None = None) -> tuple[str, Path, Path]:
    bid = "TEST_" + str(uuid.uuid4())[:8]
    from app.core.config import settings
    batch_dir = settings.storage_root / "outputs" / bid
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id":        bid,
        "awb":             awb,
        "clearance_status": "awaiting_dhl_customs_email",
        "clearance_decision": {"total_value_usd": 500.0},
        "carrier":         "DHL",
        "tracking":        {},
        "timeline":        [],
        "service_invoices": [],
    }
    if extra:
        audit.update(extra)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return bid, batch_dir, audit_path


def _load(audit_path: Path) -> Dict[str, Any]:
    return json.loads(audit_path.read_text(encoding="utf-8"))


# ── DSK_MISSING trigger — causes "dhl_followup" proposal ──────────────────────

def _dsk_trigger():
    return [{
        "trigger":    "DSK_MISSING",
        "reason":     "DSK required but not present",
        "confidence": "high",
        "action":     "Generate DSK",
        "batch_id":   "x",
        "awb":        "1234567890",
    }]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestProposalRefresh:

    def setup_method(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_sweep_creates_proposal_when_trigger_detected(self, tmp_path):
        """Monitor sweep must create a pending_review proposal for a detected trigger."""
        bid, _, audit_path = _make_batch()
        audit = _load(audit_path)

        from app.api.routes_action_proposals import refresh_proposals
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            result = refresh_proposals(audit_path, audit, bid)

        assert result["created"] == 1
        assert result["resolved"] == 0
        saved = _load(audit_path)
        props = saved.get("action_proposals", [])
        assert len(props) == 1
        assert props[0]["type"] == "dhl_followup"
        assert props[0]["status"] == "pending_review"
        assert "last_seen_at" in props[0]

    def test_repeated_sweep_does_not_duplicate(self, tmp_path):
        """A second sweep with the same trigger must NOT create a second proposal."""
        bid, _, audit_path = _make_batch()
        audit = _load(audit_path)

        from app.api.routes_action_proposals import refresh_proposals
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            r1 = refresh_proposals(audit_path, audit, bid)
            audit2 = _load(audit_path)
            r2 = refresh_proposals(audit_path, audit2, bid)

        assert r1["created"] == 1
        assert r2["created"] == 0
        assert r2["updated"] == 1
        saved = _load(audit_path)
        assert len(saved.get("action_proposals", [])) == 1

    def test_proposal_resolves_when_trigger_disappears(self, tmp_path):
        """A pending_review proposal must be resolved when its trigger is no longer detected."""
        bid, _, audit_path = _make_batch()
        audit = _load(audit_path)

        from app.api.routes_action_proposals import refresh_proposals
        # First sweep: trigger present → proposal created
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            refresh_proposals(audit_path, _load(audit_path), bid)

        # Second sweep: no triggers → proposal resolved
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=[]):
            result = refresh_proposals(audit_path, _load(audit_path), bid)

        assert result["resolved"] == 1
        saved = _load(audit_path)
        props = saved.get("action_proposals", [])
        assert props[0]["status"] == "resolved"
        assert props[0]["resolution_reason"] == "trigger_no_longer_detected"
        assert "resolved_at" in props[0]

    def test_created_at_preserved_last_seen_at_updated(self, tmp_path):
        """created_at must be stable; last_seen_at must advance on each sweep."""
        bid, _, audit_path = _make_batch()

        from app.api.routes_action_proposals import refresh_proposals
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            refresh_proposals(audit_path, _load(audit_path), bid)

        first = _load(audit_path)["action_proposals"][0]
        first_created = first["created_at"]
        first_seen = first["last_seen_at"]

        # Small delay so timestamps differ
        import time; time.sleep(0.05)

        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            refresh_proposals(audit_path, _load(audit_path), bid)

        second = _load(audit_path)["action_proposals"][0]
        assert second["created_at"] == first_created      # unchanged
        assert second["last_seen_at"] >= first_seen       # updated (or same if <1ms)

    def test_manual_refresh_endpoint(self, tmp_path):
        """POST /api/v1/action-proposals/{batch_id}/refresh must return summary dict."""
        bid, _, audit_path = _make_batch()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            resp = client.post(f"/api/v1/action-proposals/{bid}/refresh",
                               headers={"X-API-Key": "test-key"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] == bid
        assert "created" in data
        assert "resolved" in data
        assert "active_trigger_types" in data

    def test_no_financial_fields_modified(self, tmp_path):
        """refresh_proposals must never touch financial fields."""
        bid, _, audit_path = _make_batch(extra={
            "clearance_decision": {
                "total_value_usd": 9999.99,
                "total_value_pln": 42000.0,
                "duty_pln":        500.0,
                "vat_pln":         1000.0,
            },
            "service_invoices": [{"invoice_no": "INV-001", "amount_pln": 250.0}],
        })

        before = _load(audit_path)
        from app.api.routes_action_proposals import refresh_proposals
        with patch("app.agents.cowork_coordinator.detect_triggers", return_value=_dsk_trigger()):
            refresh_proposals(audit_path, _load(audit_path), bid)

        after = _load(audit_path)
        assert after["clearance_decision"] == before["clearance_decision"]
        assert after["service_invoices"] == before["service_invoices"]

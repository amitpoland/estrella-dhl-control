"""
test_milestone_skip.py

Tests for the global milestone-based skip layer.

Coverage:
  engine — execute_action("dhl_send_reply"):
    1. skip when customs_docs.received=True
    2. skip when pz_generated=True
    3. skip when status=completed
    4. proceed when no milestone (normal path)

  cowork_action_runner — run_actions:
    5. build_and_send_dhl_reply skipped when customs_docs.received=True
    6. validate_and_forward_dhl_docs_to_agency NOT skipped (milestone guard
       does not apply to agency forward)
    7. build_and_send_dhl_self_clearance_reply skipped when pz_generated=True
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_storage(tmp_path):
    return tmp_path


def _write_audit(storage: Path, batch_id: str, data: dict) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_exec_log(storage: Path, entries: list) -> None:
    p = storage / "execution_log.json"
    p.write_text(json.dumps(entries), encoding="utf-8")


def _readiness_stubs():
    """Return patches that make all readiness checks pass for dhl_send_reply."""
    batch_ready = {
        "overall": {"ready_for_closure": True, "blocked_domains": [], "next_step": None}
    }
    dhl_ready = {"dhl_status": "dhl_contacted"}
    wfirma_ready = {"ready_to_create": True}
    return (
        patch("app.services.batch_readiness.get_batch_readiness", return_value=batch_ready),
        patch("app.services.dhl_readiness.get_dhl_readiness", return_value=dhl_ready),
        patch("app.services.wfirma_reservation.get_reservation_preview", return_value=wfirma_ready),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# execute_action milestone skip tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecuteActionMilestoneSkip:

    def test_skip_when_customs_docs_received(self, tmp_storage):
        """dhl_send_reply → skipped when customs_docs.received=True."""
        _write_audit(tmp_storage, "MS_CUSTOMS", {
            "batch_id":    "MS_CUSTOMS",
            "awb":         "1111111111",
            "customs_docs": {"received": True},
        })
        from app.core.config import settings
        from app.services.execution_engine import execute_action

        p0, p1, p2 = _readiness_stubs()
        with patch.object(settings, "storage_root", tmp_storage), p0, p1, p2:
            result = execute_action("dhl_send_reply", "MS_CUSTOMS")

        assert result["ok"] is True
        assert result["status"] == "skipped"
        assert result["reason"] == "customs_docs_received"
        assert result.get("stage") == "milestone_skip"

    def test_skip_when_pz_generated(self, tmp_storage):
        """dhl_send_reply → skipped when pz_generated=True."""
        _write_audit(tmp_storage, "MS_PZ", {
            "batch_id":   "MS_PZ",
            "awb":        "2222222222",
            "pz_generated": True,
        })
        from app.core.config import settings
        from app.services.execution_engine import execute_action

        p0, p1, p2 = _readiness_stubs()
        with patch.object(settings, "storage_root", tmp_storage), p0, p1, p2:
            result = execute_action("dhl_send_reply", "MS_PZ")

        assert result["ok"] is True
        assert result["status"] == "skipped"
        assert result["reason"] == "pz_generated"
        assert result.get("stage") == "milestone_skip"

    def test_skip_when_status_completed(self, tmp_storage):
        """dhl_send_reply → skipped when status=completed."""
        _write_audit(tmp_storage, "MS_CLOSED", {
            "batch_id": "MS_CLOSED",
            "awb":      "3333333333",
            "status":   "completed",
        })
        from app.core.config import settings
        from app.services.execution_engine import execute_action

        p0, p1, p2 = _readiness_stubs()
        with patch.object(settings, "storage_root", tmp_storage), p0, p1, p2:
            result = execute_action("dhl_send_reply", "MS_CLOSED")

        assert result["ok"] is True
        assert result["status"] == "skipped"
        assert result["reason"] == "already_completed"
        assert result.get("stage") == "milestone_skip"

    def test_proceeds_when_no_milestone(self, tmp_storage):
        """dhl_send_reply → calls _call_dhl_reply when no milestone blocks."""
        _write_audit(tmp_storage, "MS_OPEN", {
            "batch_id": "MS_OPEN",
            "awb":      "4444444444",
        })
        from app.core.config import settings
        from app.services.execution_engine import execute_action

        p0, p1, p2 = _readiness_stubs()
        fake_result = {"ok": True, "queued": True, "email_id": "eid-999",
                       "to": "dhl@test.com", "subject": "Sub"}
        with (
            patch.object(settings, "storage_root", tmp_storage),
            p0, p1, p2,
            patch("app.services.execution_engine._call_dhl_reply",
                  return_value=fake_result) as mock_call,
        ):
            result = execute_action("dhl_send_reply", "MS_OPEN")

        mock_call.assert_called_once_with("MS_OPEN")
        assert result["ok"] is True
        assert result.get("stage") != "milestone_skip"


# ═══════════════════════════════════════════════════════════════════════════════
# cowork_action_runner milestone skip tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoworkRunnerMilestoneSkip:

    def _make_actions(self, *action_names) -> list:
        return [
            {"action": name, "task_id": "task-001", "reason": "test"}
            for name in action_names
        ]

    def test_dhl_reply_skipped_when_customs_docs_received(self, tmp_storage):
        """build_and_send_dhl_reply is skipped when customs_docs.received=True."""
        _write_audit(tmp_storage, "CAR_CUSTOMS", {
            "batch_id":    "CAR_CUSTOMS",
            "awb":         "5555555555",
            "customs_docs": {"received": True},
        })
        from app.core.config import settings
        from app.services.cowork_action_runner import run_actions

        with patch.object(settings, "storage_root", tmp_storage):
            result = run_actions(
                "CAR_CUSTOMS",
                self._make_actions("build_and_send_dhl_reply"),
            )

        assert result["ok"] is True
        assert len(result["skipped"]) == 1
        skip = result["skipped"][0]
        assert skip["action"] == "build_and_send_dhl_reply"
        assert "milestone_skip" in skip["reason"]
        assert len(result["failed"]) == 0

    def test_self_clearance_reply_skipped_when_pz_generated(self, tmp_storage):
        """build_and_send_dhl_self_clearance_reply skipped when pz_generated=True."""
        _write_audit(tmp_storage, "CAR_PZ", {
            "batch_id":   "CAR_PZ",
            "awb":        "6666666666",
            "pz_generated": True,
        })
        from app.core.config import settings
        from app.services.cowork_action_runner import run_actions

        with patch.object(settings, "storage_root", tmp_storage):
            result = run_actions(
                "CAR_PZ",
                self._make_actions("build_and_send_dhl_self_clearance_reply"),
            )

        assert result["ok"] is True
        assert len(result["skipped"]) == 1
        assert "milestone_skip" in result["skipped"][0]["reason"]
        assert len(result["failed"]) == 0

    def test_agency_forward_not_blocked_by_milestone(self, tmp_storage):
        """validate_and_forward_dhl_docs_to_agency is NOT subject to milestone skip."""
        _write_audit(tmp_storage, "CAR_AGENCY", {
            "batch_id":    "CAR_AGENCY",
            "awb":         "7777777777",
            "customs_docs": {"received": True},
            "pz_generated": True,
        })
        from app.core.config import settings
        from app.services.cowork_action_runner import run_actions

        # Patch the actual handler so it doesn't fail on missing state
        fake_dispatch = MagicMock(return_value={"ok": True, "skipped": False})
        with (
            patch.object(settings, "storage_root", tmp_storage),
            patch("app.services.cowork_action_runner._dispatch_action",
                  fake_dispatch),
        ):
            result = run_actions(
                "CAR_AGENCY",
                self._make_actions("validate_and_forward_dhl_docs_to_agency"),
            )

        # Should have been dispatched (not skipped by milestone guard)
        fake_dispatch.assert_called_once()
        assert not any(
            "milestone_skip" in s.get("reason", "")
            for s in result["skipped"]
        )


# ═══════════════════════════════════════════════════════════════════════════════
# _handle_email_draft milestone skip tests
# ═══════════════════════════════════════════════════════════════════════════════

def _make_draft_action(draft_type: str, task_id: str = "task-draft") -> dict:
    return {
        "action":  "send_cowork_email_draft",
        "task_id": task_id,
        "reason":  "test",
        "draft": {
            "type":     draft_type,
            "subject":  "Test subject",
            "body":     "Test body text for milestone skip tests.",
            "language": "en",
            "tone":     "professional",
        },
    }


class TestDraftMilestoneSkip:

    def _run_draft(self, tmp_storage, batch_id: str, draft_type: str):
        from app.core.config import settings
        from app.services.cowork_action_runner import run_actions
        with patch.object(settings, "storage_root", tmp_storage):
            return run_actions(batch_id, [_make_draft_action(draft_type)])

    # ── DHL-directed types blocked by each milestone ────────────────────────

    def _assert_draft_skipped(self, result: dict, milestone_reason: str) -> None:
        """
        Handler-returned skips land in both result["skipped"] and result["executed"]
        (run_actions adds them to executed for observability). The authoritative
        signal is result["skipped"][0]["reason"] and the absence of failures.
        """
        assert result["ok"] is True
        assert len(result["failed"]) == 0
        skip_reasons = [s.get("reason", "") for s in result["skipped"]]
        assert any("milestone_skip" in r for r in skip_reasons), (
            f"Expected milestone_skip in skipped reasons, got: {skip_reasons}"
        )
        # If it landed in executed it must carry skipped=True — never actually queued
        for ex in result["executed"]:
            if ex.get("action") == "send_cowork_email_draft":
                assert ex.get("result", {}).get("skipped") is True, (
                    "Draft appeared in executed without skipped=True"
                )
        assert milestone_reason in str(result["skipped"]), (
            f"Expected '{milestone_reason}' in skip reason"
        )

    def test_dhl_followup_skipped_when_customs_docs_received(self, tmp_storage):
        _write_audit(tmp_storage, "DFT_CUSTOMS", {
            "batch_id":    "DFT_CUSTOMS",
            "awb":         "1111111111",
            "customs_docs": {"received": True},
        })
        result = self._run_draft(tmp_storage, "DFT_CUSTOMS", "dhl_followup")
        self._assert_draft_skipped(result, "customs_docs_received")

    def test_dhl_followup_skipped_when_pz_generated(self, tmp_storage):
        _write_audit(tmp_storage, "DFT_PZ", {
            "batch_id":   "DFT_PZ",
            "awb":        "2222222222",
            "pz_generated": True,
        })
        result = self._run_draft(tmp_storage, "DFT_PZ", "dhl_followup")
        self._assert_draft_skipped(result, "pz_generated")

    def test_dhl_followup_skipped_when_status_completed(self, tmp_storage):
        _write_audit(tmp_storage, "DFT_CLOSED", {
            "batch_id": "DFT_CLOSED",
            "awb":      "3333333333",
            "status":   "completed",
        })
        result = self._run_draft(tmp_storage, "DFT_CLOSED", "dhl_followup")
        self._assert_draft_skipped(result, "already_completed")

    def test_dhl_dsk_request_skipped_when_customs_docs_received(self, tmp_storage):
        _write_audit(tmp_storage, "DFT_DSK", {
            "batch_id":    "DFT_DSK",
            "awb":         "4444444444",
            "customs_docs": {"received": True},
        })
        result = self._run_draft(tmp_storage, "DFT_DSK", "dhl_dsk_request")
        self._assert_draft_skipped(result, "customs_docs_received")

    def test_missing_document_request_skipped_when_customs_docs_received(self, tmp_storage):
        _write_audit(tmp_storage, "DFT_MDR", {
            "batch_id":    "DFT_MDR",
            "awb":         "5555555555",
            "customs_docs": {"received": True},
        })
        result = self._run_draft(tmp_storage, "DFT_MDR", "missing_document_request")
        self._assert_draft_skipped(result, "customs_docs_received")

    # ── Agency types NOT blocked ────────────────────────────────────────────

    def test_agency_followup_not_blocked_by_milestone(self, tmp_storage):
        """agency_followup draft must not be blocked even when all milestones are set."""
        _write_audit(tmp_storage, "DFT_AGCY", {
            "batch_id":    "DFT_AGCY",
            "awb":         "6666666666",
            "customs_docs": {"received": True},
            "pz_generated": True,
            "status":      "completed",
        })
        fake_queue = MagicMock(return_value="email-id-agcy")
        with (
            patch.object(__import__("app.core.config", fromlist=["settings"]).settings,
                         "storage_root", tmp_storage),
            patch("app.services.email_service.queue_email", fake_queue),
            patch("app.config.email_routing.AGENCY_TO", ["agency@test.com"]),
            patch("app.config.email_routing.AGENCY_CC", []),
            patch("app.config.email_routing.INTERNAL_CC", []),
            patch("app.config.email_routing.format_to",
                  side_effect=lambda lst: ", ".join(lst)),
            patch("app.config.email_routing.format_cc",
                  side_effect=lambda lst: ", ".join(lst)),
        ):
            from app.services.cowork_action_runner import run_actions
            result = run_actions("DFT_AGCY", [_make_draft_action("agency_followup")])

        assert not any(
            "milestone_skip" in s.get("reason", "")
            for s in result["skipped"]
        )
        fake_queue.assert_called_once()

    # ── No milestone → draft proceeds ───────────────────────────────────────

    def test_dhl_followup_proceeds_when_no_milestone(self, tmp_storage):
        """When no milestone is set, dhl_followup draft queues normally."""
        _write_audit(tmp_storage, "DFT_OPEN", {
            "batch_id": "DFT_OPEN",
            "awb":      "7777777777",
        })
        fake_queue = MagicMock(return_value="email-id-open")
        with (
            patch.object(__import__("app.core.config", fromlist=["settings"]).settings,
                         "storage_root", tmp_storage),
            patch("app.services.email_service.queue_email", fake_queue),
            patch("app.config.email_routing.DHL_TO", ["dhl@test.com"]),
            patch("app.config.email_routing.INTERNAL_CC", []),
            patch("app.config.email_routing.format_to",
                  side_effect=lambda lst: ", ".join(lst)),
            patch("app.config.email_routing.format_cc",
                  side_effect=lambda lst: ", ".join(lst)),
        ):
            from app.services.cowork_action_runner import run_actions
            result = run_actions("DFT_OPEN", [_make_draft_action("dhl_followup")])

        assert not any(
            "milestone_skip" in s.get("reason", "")
            for s in result["skipped"]
        )
        fake_queue.assert_called_once()

"""
test_ai_bridge.py — AI Bridge service and API integration tests.

Tests:
  1.  create_task() writes file to ai_bridge/tasks/
  2.  create_task() rejects unknown task_type
  3.  list_tasks() returns pending tasks
  4.  get_task() returns task or None
  5.  import_result() applies allowed keys to audit
  6.  import_result() rejects forbidden fields
  7.  import_result() rejects disallowed audit keys for task_type
  8.  import_result() moves task to processed/
  9.  EV_AI_BRIDGE_TASK_CREATED in timeline after POST /tasks/{batch_id}
  10. EV_AI_BRIDGE_RESULT_RECEIVED in timeline after POST /results/{task_id}
  11. POST /tasks/{batch_id} → 404 for unknown batch
  12. POST /tasks/{batch_id} → 422 for unknown task_type
  13. GET /tasks lists pending tasks
  14. GET /tasks/{task_id} returns task
  15. POST /results/{task_id} for tracking_lookup clears cowork_tracking_required
  16. POST /results/{task_id} → 422 when forbidden field present
  17. import_result() rejects forbidden fields nested inside allowed keys
  18. import_result() rejects duplicate import of same task_id
  19. email_scan import logs derived timeline events
  20. Concurrent import blocked by atomic lock file
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Path + env ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY",      "test-key")
# NOTE: no STORAGE_ROOT setdefault — tests use tmp_path for isolation


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point settings.storage_root at tmp_path so all service code is isolated."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    # Patch cached module-level _OUTPUTS in all route/service modules
    from app.api import routes_ai_bridge, routes_action_proposals, routes_tracking
    for mod in (routes_ai_bridge, routes_action_proposals, routes_tracking):
        monkeypatch.setattr(mod, "_OUTPUTS", tmp_path / "outputs")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_batch(root: Path, extra: Dict[str, Any] | None = None, batch_id: str | None = None):
    bid = batch_id or str(uuid.uuid4())[:8]
    batch_dir = root / "outputs" / bid
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id":    bid,
        "awb":         "1234567890",
        "tracking_no": "1234567890",
        "status":      "processing",
        "carrier":     "DHL",
        "clearance_decision": {"total_value_usd": 800.0},
        "timeline": [],
    }
    if extra:
        audit.update(extra)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return bid, batch_dir, ap


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))




# ── Test 1–4: Service-layer unit tests ────────────────────────────────────────

class TestCreateTask:
    def test_create_task_writes_file(self, tmp_path):
        """create_task() writes a JSON file to ai_bridge/tasks/."""
        bid, _, _ = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, _tasks_dir
        task = create_task(bid, "tracking_lookup", {"awb": "1234567890"})

        assert "task_id" in task
        assert task["task_type"] == "tracking_lookup"
        assert task["status"] == "pending"

        task_file = _tasks_dir() / f"{task['task_id']}.json"
        assert task_file.exists(), "Task file not written to tasks/"
        on_disk = json.loads(task_file.read_text(encoding="utf-8"))
        assert on_disk["task_id"] == task["task_id"]

    def test_create_task_rejects_unknown_type(self, tmp_path):
        """create_task() raises ValueError for unknown task_type."""

        bid, _, _ = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task
        with pytest.raises(ValueError, match="Unknown task_type"):
            create_task(bid, "destroy_everything", {})

    def test_list_tasks_returns_pending(self, tmp_path):
        """list_tasks() returns tasks from ai_bridge/tasks/."""

        bid, _, _ = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, list_tasks
        t = create_task(bid, "general_research", {"research_question": "test"})
        tasks = list_tasks(status="pending")
        ids = [x["task_id"] for x in tasks]
        assert t["task_id"] in ids

    def test_get_task_returns_task(self, tmp_path):
        """get_task() returns task dict for known ID, None for unknown."""

        bid, _, _ = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, get_task
        t = create_task(bid, "document_summary", {})
        found = get_task(t["task_id"])
        assert found is not None
        assert found["task_id"] == t["task_id"]

        assert get_task("nonexistent-task-id") is None


# ── Tests 5–8: import_result ──────────────────────────────────────────────────

class TestImportResult:
    def test_import_applies_allowed_keys(self, tmp_path):
        """import_result() writes allowed result_data keys into audit."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result
        task = create_task(bid, "tracking_lookup", {"awb": "1234567890"})

        audit = _read_audit(ap)
        result = {
            "task_id":     task["task_id"],
            "result_data": {
                "tracking": {
                    "status":     "in_transit",
                    "last_event": "Departed Warsaw",
                }
            },
        }
        outcome = import_result(task["task_id"], result, audit, ap)
        assert outcome["ok"] is True
        assert "tracking" in outcome["applied_keys"]

        updated = _read_audit(ap)
        assert updated["tracking"]["status"] == "in_transit"

    def test_import_rejects_forbidden_field_flat(self, tmp_path):
        """import_result() raises ValueError when forbidden field is in result root."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result
        task = create_task(bid, "tracking_lookup", {})

        audit = _read_audit(ap)
        result = {
            "task_id":           task["task_id"],
            "clearance_decision": {"total_value_usd": 9999},   # FORBIDDEN
        }
        with pytest.raises(ValueError, match="Forbidden field"):
            import_result(task["task_id"], result, audit, ap)

    def test_import_rejects_disallowed_audit_key(self, tmp_path):
        """import_result() raises ValueError when result_data touches disallowed audit key."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result
        task = create_task(bid, "tracking_lookup", {})

        audit = _read_audit(ap)
        result = {
            "task_id":     task["task_id"],
            "result_data": {
                "clearance_decision": {"total_value_usd": 9999},  # not allowed for tracking_lookup
            },
        }
        with pytest.raises(ValueError, match="disallowed audit key"):
            import_result(task["task_id"], result, audit, ap)

    def test_import_moves_task_to_processed(self, tmp_path):
        """After successful import, task file moves from tasks/ to processed/."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import (
            create_task, import_result, _tasks_dir, _processed_dir
        )
        task = create_task(bid, "tracking_lookup", {})
        task_id = task["task_id"]

        assert (_tasks_dir() / f"{task_id}.json").exists()

        audit = _read_audit(ap)
        result = {
            "task_id":     task_id,
            "result_data": {"tracking": {"status": "delivered"}},
        }
        import_result(task_id, result, audit, ap)

        assert not (_tasks_dir() / f"{task_id}.json").exists(), "Task still in tasks/ after import"
        assert (_processed_dir() / f"{task_id}.json").exists(), "Task not in processed/ after import"


# ── Tests 9–16: API endpoint tests ───────────────────────────────────────────

class TestAiBridgeEndpoints:
    def test_create_task_logs_timeline_event(self, tmp_path):
        """POST /tasks/{batch_id} logs EV_AI_BRIDGE_TASK_CREATED to timeline."""

        bid, _, ap = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, CreateTaskBody
        from app.core import timeline as tl

        body = CreateTaskBody(task_type="tracking_lookup", payload={})
        create_bridge_task(bid, body)

        updated = _read_audit(ap)
        events = [ev["event"] for ev in updated.get("timeline", [])]
        assert tl.EV_AI_BRIDGE_TASK_CREATED in events

    def test_import_result_logs_timeline_event(self, tmp_path):
        """POST /results/{task_id} logs EV_AI_BRIDGE_RESULT_RECEIVED to timeline."""

        bid, _, ap = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody
        from app.core import timeline as tl

        # Create task
        task_resp = create_bridge_task(bid, CreateTaskBody(task_type="tracking_lookup"))
        task_id = task_resp["task_id"]

        # Import result
        body = ImportResultBody(
            task_id=task_id,
            result_data={"tracking": {"status": "in_transit", "last_event": "test"}},
            summary="test import",
            source="test",
        )
        import_bridge_result(task_id, body)

        updated = _read_audit(ap)
        events = [ev["event"] for ev in updated.get("timeline", [])]
        assert tl.EV_AI_BRIDGE_RESULT_RECEIVED in events

    def test_create_task_404_unknown_batch(self, tmp_path):
        """POST /tasks/{batch_id} → 404 for unknown batch."""

        from app.api.routes_ai_bridge import create_bridge_task, CreateTaskBody
        from fastapi import HTTPException

        body = CreateTaskBody(task_type="tracking_lookup")
        with pytest.raises(HTTPException) as exc_info:
            create_bridge_task("nonexistent_batch_xyz", body)
        assert exc_info.value.status_code == 404

    def test_create_task_422_unknown_type(self, tmp_path):
        """POST /tasks/{batch_id} → 422 for unknown task_type."""

        bid, _, _ = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, CreateTaskBody
        from fastapi import HTTPException

        body = CreateTaskBody(task_type="destroy_everything")
        with pytest.raises(HTTPException) as exc_info:
            create_bridge_task(bid, body)
        assert exc_info.value.status_code == 422

    def test_list_tasks_endpoint(self, tmp_path):
        """GET /tasks lists pending tasks."""

        bid, _, _ = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, list_bridge_tasks, CreateTaskBody

        create_bridge_task(bid, CreateTaskBody(task_type="general_research"))
        resp = list_bridge_tasks(status="pending")
        assert "tasks" in resp
        assert resp["count"] >= 1

    def test_get_task_endpoint(self, tmp_path):
        """GET /tasks/{task_id} returns the task."""

        bid, _, _ = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, get_bridge_task, CreateTaskBody

        task_resp = create_bridge_task(bid, CreateTaskBody(task_type="document_summary"))
        task_id = task_resp["task_id"]

        task = get_bridge_task(task_id)
        assert task["task_id"] == task_id
        assert task["task_type"] == "document_summary"

    def test_tracking_result_clears_cowork_required(self, tmp_path):
        """POST /results/{task_id} for tracking_lookup clears cowork_tracking_required."""

        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {
                "cowork_tracking_required": True,
                "cowork_result_received":   False,
                "tracking_url":             "https://www.dhl.com/test",
            }
        })
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody

        task_resp = create_bridge_task(bid, CreateTaskBody(task_type="tracking_lookup"))
        task_id = task_resp["task_id"]

        body = ImportResultBody(
            task_id=task_id,
            result_data={"tracking": {"status": "customs", "last_event": "At customs"}},
            summary="customs status",
            source="claude_cowork",
        )
        result = import_bridge_result(task_id, body)
        assert result["ok"] is True

        updated = _read_audit(ap)
        tr = updated.get("tracking", {})
        assert tr.get("cowork_result_received") is True
        assert tr.get("cowork_tracking_required") is False
        # Fields the shared tracking_patch adds — asserted at the ENDPOINT,
        # not only in the helper's unit tests.
        assert tr.get("api_status") == "manual"
        assert tr.get("updated_at")
        assert tr.get("status_label") == "Customs"

    def test_tracking_result_does_not_close_checkpoint_without_operator_role(self, tmp_path):
        """Bridge is guarded by get_current_user only — any authenticated user.

        It must record the tracking evidence but NOT close the tracking_complete
        checkpoint, which the /tracking/* routes gate behind
        require_role("admin","logistics"). Called directly here, `user` is not a
        dict, so the gate must fail closed.
        """
        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {"cowork_tracking_required": True},
        })
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody

        task_id = create_bridge_task(bid, CreateTaskBody(task_type="tracking_lookup"))["task_id"]
        import_bridge_result(task_id, ImportResultBody(
            task_id=task_id,
            result_data={"tracking": {"status": "customs"}},
            source="claude_cowork",
        ))
        updated = _read_audit(ap)
        assert updated.get("tracking", {}).get("status") == "customs", (
            "tracking evidence must still be recorded"
        )
        for k in ("tracking_complete", "tracking_complete_source", "tracking_complete_at"):
            assert k not in updated, (
                f"{k} was written by a non-operator caller — closing the "
                "workflow checkpoint requires admin/logistics"
            )

    def test_tracking_result_closes_checkpoint_for_operator_role(self, tmp_path):
        """An admin/logistics caller DOES close the checkpoint."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {"cowork_tracking_required": True},
        })
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody

        task_id = create_bridge_task(bid, CreateTaskBody(task_type="tracking_lookup"))["task_id"]
        import_bridge_result(task_id, ImportResultBody(
            task_id=task_id,
            result_data={"tracking": {"status": "customs"}},
            source="claude_cowork",
        ), user={"id": "u1", "role": "logistics"})
        updated = _read_audit(ap)
        assert updated.get("tracking_complete") is True
        assert updated.get("tracking_complete_source") == "claude_cowork"

    def test_import_result_422_forbidden_field(self, tmp_path):
        """POST /results/{task_id} → 422 when result_data contains forbidden key."""

        bid, _, ap = _make_batch(tmp_path)
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody
        from fastapi import HTTPException

        task_resp = create_bridge_task(bid, CreateTaskBody(task_type="tracking_lookup"))
        task_id = task_resp["task_id"]

        body = ImportResultBody(
            task_id=task_id,
            result_data={"clearance_decision": {"total_value_usd": 9999}},
            summary="attempt forbidden write",
            source="attacker",
        )
        with pytest.raises(HTTPException) as exc_info:
            import_bridge_result(task_id, body)
        assert exc_info.value.status_code == 422


# ── Tests 17–19: Security hardening tests ────────────────────────────────────

class TestSecurityHardening:
    def test_import_rejects_nested_forbidden_field(self, tmp_path):
        """import_result() rejects forbidden fields nested inside allowed result_data keys."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result, _tasks_dir

        task = create_task(bid, "tracking_lookup", {"awb": "1234567890"})
        task_id = task["task_id"]

        audit = _read_audit(ap)
        result = {
            "task_id":     task_id,
            "result_data": {
                "tracking": {
                    "status": "in_transit",
                    "customs_values": {"total": 9999},
                    "vat": 0.23,
                }
            },
        }
        with pytest.raises(ValueError, match="Forbidden field nested"):
            import_result(task_id, result, audit, ap)

        assert (_tasks_dir() / f"{task_id}.json").exists(), "Task should remain in tasks/"
        updated = _read_audit(ap)
        assert "customs_values" not in json.dumps(updated)

    def test_import_rejects_duplicate(self, tmp_path):
        """import_result() rejects a second import of the same task_id."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result

        task = create_task(bid, "tracking_lookup", {"awb": "1234567890"})
        task_id = task["task_id"]

        audit = _read_audit(ap)
        result = {
            "task_id":     task_id,
            "result_data": {"tracking": {"status": "delivered"}},
        }
        outcome = import_result(task_id, result, audit, ap)
        assert outcome["ok"] is True

        audit_after_first = _read_audit(ap)
        with pytest.raises(ValueError, match="already imported"):
            import_result(task_id, result, audit_after_first, ap)

        audit_after_second = _read_audit(ap)
        assert audit_after_first == audit_after_second, "Audit should not change on duplicate import"

    def test_email_scan_import_derives_events(self, tmp_path):
        """POST /results/{task_id} for email_scan logs derived timeline events."""

        bid, _, ap = _make_batch(tmp_path, extra={"clearance_status": ""})
        from app.api.routes_ai_bridge import create_bridge_task, import_bridge_result
        from app.api.routes_ai_bridge import CreateTaskBody, ImportResultBody

        task_resp = create_bridge_task(bid, CreateTaskBody(task_type="email_scan", payload={}))
        task_id = task_resp["task_id"]

        body = ImportResultBody(
            task_id=task_id,
            result_data={
                "email_scan_results": {
                    "awb": "1234567890",
                    "scanned_at": "2026-04-30T12:00:00Z",
                    "matched": 2,
                    "confidence": "high",
                    "threads": [{
                        "thread_id": "t1",
                        "emails": [{
                            "subject": "Customs clearance T#12345",
                            "from": "odprawacelna@dhl.com",
                            "received_at": "2026-04-29T10:00:00Z",
                            "classification": "dhl_customs_request",
                        }],
                    }],
                    "derived_events": [
                        {
                            "event": "dhl_customs_email_received",
                            "source_email_subject": "Customs clearance T#12345",
                            "source_email_from": "odprawacelna@dhl.com",
                            "timestamp": "2026-04-29T10:00:00Z",
                            "ticket": "T#12345",
                            "confidence": "high",
                        },
                    ],
                    "recommended_next_action": "generate_polish_description",
                    "searched": {"awb": "1234567890", "terms": ["1234567890"]},
                },
            },
            summary="email scan complete",
            source="claude_cowork",
        )
        result = import_bridge_result(task_id, body)
        assert result["ok"] is True

        updated = _read_audit(ap)
        events = [ev["event"] for ev in updated.get("timeline", [])]
        assert "dhl_customs_email_received" in events
        assert updated.get("dhl_email", {}).get("received") is True
        assert updated.get("clearance_status") == "dhl_email_received"

    def test_concurrent_import_blocked_by_lock(self, tmp_path):
        """Only one concurrent import wins; the other gets 'already in progress'."""

        bid, _, ap = _make_batch(tmp_path)
        from app.services.ai_bridge import create_task, import_result, _bridge_root

        task = create_task(bid, "tracking_lookup", {"awb": "1234567890"})
        task_id = task["task_id"]

        lock_path = _bridge_root() / f".lock_{task_id}"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        try:
            audit = _read_audit(ap)
            result = {
                "task_id":     task_id,
                "result_data": {"tracking": {"status": "delivered"}},
            }
            with pytest.raises(ValueError, match="already in progress"):
                import_result(task_id, result, audit, ap)
        finally:
            lock_path.unlink(missing_ok=True)

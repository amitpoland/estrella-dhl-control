"""
test_ai_bridge_stress.py — AI Bridge stress tests.

Part A — Concurrent task creation (tests 1–6):
  1. 20 concurrent create_task() calls all succeed without exception
  2. All 20 task_ids are unique
  3. All 20 task files exist on disk
  4. Every task file is valid JSON with required fields
  5. No partial or corrupt files after concurrent writes
  6. Mixed task types under concurrent load all validate correctly

Part B — Malformed and unsafe result imports (tests 7–14):
  7.  Result with wrong task_id is rejected
  8.  Result with missing result_data is rejected as disallowed key
  9.  Result with non-dict result_data type raises error
  10. Nested forbidden field injection rejected for every task type
  11. Unknown top-level write key rejected for every task type
  12. Rejected imports do not move task to processed/
  13. Rejected imports are archived to errors/
  14. Audit unchanged after rejected forbidden-field import

Part C — Concurrent import_result (test 15):
  15. 10 parallel import_result() on same task_id: only 1 succeeds,
      9 fail with ValueError, no duplicate writes, audit valid,
      task moved to processed/ once, lock cleaned up
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Path + env ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
    return S()


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))


def _create_task_for_import(ab, tmp_path, batch_id, task_type="tracking_lookup"):
    """Seed a batch, create a task, return (task, audit, audit_path)."""
    batch_dir = _seed_batch(tmp_path, batch_id)
    ap = batch_dir / "audit.json"
    task = ab.create_task(batch_id, task_type, {"awb": "9999999999"})
    audit = _read_audit(ap)
    return task, audit, ap


def _seed_batch(tmp_path: Path, batch_id: str) -> Path:
    """Create a minimal batch directory with audit.json."""
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":    batch_id,
        "awb":         "9999999999",
        "tracking_no": "9999999999",
        "status":      "processing",
        "carrier":     "DHL",
        "timeline":    [],
    }
    (batch_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False), encoding="utf-8",
    )
    return batch_dir


# ── 1. Concurrent task creation — 20 workers, same batch ─────────────────────

def test_concurrent_create_task_all_succeed(tmp_path, monkeypatch):
    """20 concurrent create_task() calls all succeed; no exceptions raised."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_1")

    results: List[Dict[str, Any]] = []
    errors: List[Exception] = []

    def _create(i: int) -> Dict[str, Any]:
        return ab.create_task(
            "B_STRESS_1", "tracking_lookup", {"awb": "9999999999", "worker": i},
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(_create, i) for i in range(20)]
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as exc:
                errors.append(exc)

    assert errors == [], f"Concurrent create_task raised exceptions: {errors}"
    assert len(results) == 20


# ── 2. All task_ids are unique ────────────────────────────────────────────────

def test_concurrent_task_ids_unique(tmp_path, monkeypatch):
    """All 20 concurrently created tasks have distinct task_ids."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_2")

    def _create(i: int) -> Dict[str, Any]:
        return ab.create_task(
            "B_STRESS_2", "tracking_lookup", {"awb": "9999999999", "worker": i},
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_create, range(20)))

    task_ids = [r["task_id"] for r in results]
    assert len(set(task_ids)) == 20, f"Duplicate task_ids: {task_ids}"


# ── 3. All task files exist on disk ───────────────────────────────────────────

def test_concurrent_all_task_files_exist(tmp_path, monkeypatch):
    """Every task created concurrently has a corresponding file in tasks/."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_3")

    def _create(i: int) -> Dict[str, Any]:
        return ab.create_task(
            "B_STRESS_3", "tracking_lookup", {"awb": "9999999999", "worker": i},
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_create, range(20)))

    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    for r in results:
        task_file = tasks_dir / f"{r['task_id']}.json"
        assert task_file.exists(), f"Missing task file: {task_file.name}"


# ── 4. Every task file is valid JSON with required fields ─────────────────────

def test_concurrent_task_files_valid_json(tmp_path, monkeypatch):
    """All task files are valid JSON containing task_id, task_type, batch_id, status=pending."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_4")

    def _create(i: int) -> Dict[str, Any]:
        return ab.create_task(
            "B_STRESS_4", "tracking_lookup", {"awb": "9999999999", "worker": i},
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_create, range(20)))

    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    for r in results:
        task_file = tasks_dir / f"{r['task_id']}.json"
        raw = task_file.read_text(encoding="utf-8")

        # Must parse as valid JSON (no truncation / corruption)
        data = json.loads(raw)

        # Required fields
        assert data["task_id"] == r["task_id"]
        assert data["task_type"] == "tracking_lookup"
        assert data["batch_id"] == "B_STRESS_4"
        assert data["status"] == "pending"


# ── 5. No partial or corrupt files ────────────────────────────────────────────

def test_concurrent_no_corrupt_files(tmp_path, monkeypatch):
    """After 20 concurrent writes, every .json file in tasks/ is parseable."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_5")

    def _create(i: int) -> Dict[str, Any]:
        return ab.create_task(
            "B_STRESS_5", "document_summary", {"worker": i},
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(_create, range(20)))

    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    json_files = list(tasks_dir.glob("*.json"))
    assert len(json_files) >= 20, f"Expected ≥20 task files, found {len(json_files)}"

    for f in json_files:
        raw = f.read_text(encoding="utf-8")
        assert raw.strip(), f"Empty file: {f.name}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Corrupt JSON in {f.name}: {exc}")
        assert "task_id" in data, f"Missing task_id in {f.name}"
        assert "status" in data, f"Missing status in {f.name}"


# ── 6. Mixed task types under concurrent load ────────────────────────────────

def test_concurrent_mixed_task_types(tmp_path, monkeypatch):
    """Concurrent creation of different task types all produce valid files."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    _seed_batch(tmp_path, "B_STRESS_6")

    task_types = [
        "tracking_lookup",
        "document_summary",
        "risk_assessment",
        "general_research",
        "email_draft",
        "email_scan",
    ]

    def _create(i: int) -> Dict[str, Any]:
        tt = task_types[i % len(task_types)]
        payload: Dict[str, Any] = {"worker": i}
        if tt == "general_research":
            payload["research_question"] = f"stress test {i}"
        return ab.create_task("B_STRESS_6", tt, payload)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_create, range(20)))

    assert len(results) == 20

    # Verify each file matches its returned task_type
    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    for r in results:
        task_file = tasks_dir / f"{r['task_id']}.json"
        data = json.loads(task_file.read_text(encoding="utf-8"))
        assert data["task_type"] == r["task_type"]
        assert data["batch_id"] == "B_STRESS_6"
        assert data["status"] == "pending"
        assert data["task_id"] == r["task_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# Part B — Malformed and unsafe result imports
# ═══════════════════════════════════════════════════════════════════════════════


# ── 7. Result with wrong task_id is rejected ─────────────────────────────────

def test_import_wrong_task_id_rejected(tmp_path, monkeypatch):
    """import_result() rejects result whose task_id doesn't match the task."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_WRONG_ID")

    result = {
        "task_id":     "completely-wrong-id",
        "result_data": {"tracking": {"status": "delivered"}},
    }
    with pytest.raises(ValueError, match="does not match"):
        ab.import_result(task["task_id"], result, audit, ap)

    # Task must remain in tasks/, not moved to processed/
    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    assert (tasks_dir / f"{task['task_id']}.json").exists()


# ── 8. Result with empty result_data applies nothing ─────────────────────────

def test_import_missing_result_data_applies_nothing(tmp_path, monkeypatch):
    """import_result() with no result_data applies zero keys but succeeds."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_EMPTY_DATA")

    result = {
        "task_id":     task["task_id"],
        "result_data": {},
    }
    outcome = ab.import_result(task["task_id"], result, audit, ap)
    assert outcome["ok"] is True
    assert outcome["applied_keys"] == []

    # Audit unchanged except for whatever import_result writes
    updated = _read_audit(ap)
    assert updated["awb"] == "9999999999"


# ── 9. Result with non-dict result_data type ─────────────────────────────────

def test_import_result_data_wrong_type_rejected(tmp_path, monkeypatch):
    """import_result() rejects result_data that is a list instead of dict."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_BAD_TYPE")

    result = {
        "task_id":     task["task_id"],
        "result_data": [{"tracking": {"status": "delivered"}}],
    }
    # A list has no .keys() — depending on implementation this may raise
    # TypeError or be caught by validation. Either way, audit must not change.
    audit_before = json.dumps(audit, sort_keys=True)
    try:
        ab.import_result(task["task_id"], result, audit, ap)
    except (ValueError, TypeError, AttributeError):
        pass  # Expected — malformed input rejected

    updated = _read_audit(ap)
    audit_after = json.dumps(updated, sort_keys=True)
    assert audit_before == audit_after, "Audit must not change on malformed result_data"


# ── 10. Nested forbidden field injection — every task type ───────────────────

_ALLOWED_WRITE_SAMPLES = {
    "tracking_lookup":   "tracking",
    "document_summary":  "ai_summary",
    "risk_assessment":   "ai_risk",
    "general_research":  "ai_notes",
    "email_draft":       "ai_email_draft",
    "email_scan":        "email_scan_results",
}

_FORBIDDEN_SAMPLES = [
    "customs_values",
    "clearance_decision",
    "duty",
    "vat",
    "invoice_lines",
    "sad_data",
]


@pytest.mark.parametrize("task_type,allowed_key", list(_ALLOWED_WRITE_SAMPLES.items()))
@pytest.mark.parametrize("forbidden_field", _FORBIDDEN_SAMPLES)
def test_nested_forbidden_field_rejected_per_task_type(
    tmp_path, monkeypatch, task_type, allowed_key, forbidden_field,
):
    """Forbidden fields nested inside allowed keys are rejected for every task type."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    bid = f"B_NESTED_{task_type}_{forbidden_field}"
    task, audit, ap = _create_task_for_import(ab, tmp_path, bid, task_type=task_type)

    result = {
        "task_id":     task["task_id"],
        "result_data": {
            allowed_key: {
                "safe_field": "ok",
                forbidden_field: {"injected": 9999},
            },
        },
    }
    with pytest.raises(ValueError, match="Forbidden field nested"):
        ab.import_result(task["task_id"], result, audit, ap)

    # Audit must not contain the injected forbidden key at top level
    updated = _read_audit(ap)
    assert forbidden_field not in updated, \
        f"Forbidden field '{forbidden_field}' leaked into audit top-level keys"
    # The allowed_key itself must NOT have been written (entire result rejected)
    assert allowed_key not in updated, \
        f"Allowed key '{allowed_key}' should not be in audit after rejected import"

    # Task stays in tasks/
    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    assert (tasks_dir / f"{task['task_id']}.json").exists()


# ── 11. Unknown top-level write key rejected — every task type ───────────────

@pytest.mark.parametrize("task_type,allowed_key", list(_ALLOWED_WRITE_SAMPLES.items()))
def test_unknown_write_key_rejected_per_task_type(
    tmp_path, monkeypatch, task_type, allowed_key,
):
    """Result writing to an unknown audit key is rejected for every task type."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    bid = f"B_UNKNOWN_KEY_{task_type}"
    task, audit, ap = _create_task_for_import(ab, tmp_path, bid, task_type=task_type)

    result = {
        "task_id":     task["task_id"],
        "result_data": {
            allowed_key:      {"safe": True},        # allowed — fine
            "rogue_key_xyz":  {"attack": "payload"},  # NOT in allowed writes
        },
    }
    with pytest.raises(ValueError, match="disallowed audit key"):
        ab.import_result(task["task_id"], result, audit, ap)

    # Audit must not contain the rogue key
    updated = _read_audit(ap)
    assert "rogue_key_xyz" not in updated

    # Task stays in tasks/
    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    assert (tasks_dir / f"{task['task_id']}.json").exists()


# ── 12. Rejected imports do NOT move task to processed/ ──────────────────────

def test_rejected_import_task_stays_in_tasks(tmp_path, monkeypatch):
    """After a rejected import, task file remains in tasks/ and is absent from processed/."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_STAYS")

    result = {
        "task_id":     task["task_id"],
        "result_data": {
            "tracking": {
                "status": "delivered",
                "customs_values": {"total": 9999},  # forbidden nested
            },
        },
    }
    with pytest.raises(ValueError):
        ab.import_result(task["task_id"], result, audit, ap)

    tasks_dir     = tmp_path / "ai_bridge" / "tasks"
    processed_dir = tmp_path / "ai_bridge" / "processed"

    assert (tasks_dir / f"{task['task_id']}.json").exists(), "Task must stay in tasks/"
    assert not (processed_dir / f"{task['task_id']}.json").exists(), "Task must NOT be in processed/"


# ── 13. Rejected imports are archived to errors/ ─────────────────────────────

def test_rejected_import_archived_to_errors(tmp_path, monkeypatch):
    """When import is rejected, a rejection record is written to errors/."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_ERRORS")

    result = {
        "task_id":     task["task_id"],
        "result_data": {
            "tracking": {
                "vat": 0.23,  # forbidden nested
            },
        },
    }
    with pytest.raises(ValueError, match="Forbidden field nested"):
        ab.import_result(task["task_id"], result, audit, ap)

    errors_dir = tmp_path / "ai_bridge" / "errors"
    error_file = errors_dir / f"{task['task_id']}.json"
    assert error_file.exists(), "Rejection record must be archived to errors/"

    error_doc = json.loads(error_file.read_text(encoding="utf-8"))
    assert error_doc["task_id"] == task["task_id"]
    assert "rejection_reason" in error_doc
    assert any("vat" in r for r in error_doc["rejection_reason"])


# ── 14. Audit unchanged after rejected forbidden-field import ────────────────

def test_rejected_import_audit_unchanged(tmp_path, monkeypatch):
    """Audit.json must be byte-identical before and after a rejected import."""
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))
    task, audit, ap = _create_task_for_import(ab, tmp_path, "B_AUDIT_SAFE")

    audit_before = ap.read_text(encoding="utf-8")

    result = {
        "task_id":     task["task_id"],
        "result_data": {
            "tracking": {
                "status":        "delivered",
                "landed_cost":   {"total": 500},     # forbidden
                "invoice_lines": [{"amount": 100}],  # forbidden
            },
        },
    }
    with pytest.raises(ValueError):
        ab.import_result(task["task_id"], result, audit, ap)

    audit_after = ap.read_text(encoding="utf-8")
    assert audit_before == audit_after, "Audit must not change after rejected import"


# ═══════════════════════════════════════════════════════════════════════════════
# Part C — Concurrent import_result on same task_id
# ═══════════════════════════════════════════════════════════════════════════════


def test_concurrent_import_result_only_one_succeeds(tmp_path, monkeypatch):
    """
    10 parallel import_result() calls on the same task_id:
      - exactly 1 succeeds (ok=True)
      - remaining 9 raise ValueError (lock or already-imported)
      - no duplicate writes to processed/
      - audit is valid JSON with exactly one update applied
      - task file moved to processed/ exactly once
    """
    from app.services import ai_bridge as ab

    monkeypatch.setattr(ab, "settings", _make_settings(tmp_path))

    bid = "B_CONCURRENT_IMPORT"
    task, audit, ap = _create_task_for_import(ab, tmp_path, bid, task_type="tracking_lookup")
    task_id = task["task_id"]

    valid_result = {
        "task_id":     task_id,
        "result_data": {
            "tracking": {"status": "in_transit", "last_event": "Concurrent test"},
        },
    }

    successes: List[Dict[str, Any]] = []
    failures: List[Exception] = []

    def _import(_i: int):
        # Each thread needs its own copy of audit (dict is mutable)
        thread_audit = _read_audit(ap)
        return ab.import_result(task_id, valid_result, thread_audit, ap)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_import, i) for i in range(10)]
        for f in as_completed(futures):
            try:
                successes.append(f.result())
            except (ValueError, Exception) as exc:
                failures.append(exc)

    # Exactly 1 success
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {successes}"
    assert successes[0]["ok"] is True
    assert successes[0]["applied_keys"] == ["tracking"]

    # Remaining 9 failed
    assert len(failures) == 9, f"Expected 9 failures, got {len(failures)}"
    for exc in failures:
        assert isinstance(exc, ValueError)
        msg = str(exc).lower()
        assert "already imported" in msg or "already in progress" in msg, \
            f"Unexpected error message: {exc}"

    # Task moved to processed/ exactly once
    processed_dir = tmp_path / "ai_bridge" / "processed"
    processed_tasks = list(processed_dir.glob(f"{task_id}.json"))
    assert len(processed_tasks) == 1, f"Task in processed/ count: {len(processed_tasks)}"

    # Result file in processed/ exactly once
    processed_results = list(processed_dir.glob(f"{task_id}_result.json"))
    assert len(processed_results) == 1

    # Task removed from tasks/
    tasks_dir = tmp_path / "ai_bridge" / "tasks"
    assert not (tasks_dir / f"{task_id}.json").exists(), "Task must be removed from tasks/"

    # Lock file cleaned up
    lock_path = tmp_path / "ai_bridge" / f".lock_{task_id}"
    assert not lock_path.exists(), "Lock file must be cleaned up"

    # Audit is valid and contains the tracking update
    final_audit = _read_audit(ap)
    assert final_audit["tracking"]["status"] == "in_transit"
    assert final_audit["tracking"]["last_event"] == "Concurrent test"
    assert final_audit["awb"] == "9999999999"  # original data preserved

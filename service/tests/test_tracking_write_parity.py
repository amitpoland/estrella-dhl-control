"""The two tracking write paths must produce the same audit shape.

routes_tracking.update_tracking_for_batch and routes_ai_bridge.import_bridge_result
both patch audit.tracking. They were separate hand-written copies and drifted:
when api_status, updated_at and the top-level tracking_complete* keys were added
to the first, the second never got them, so a batch whose lookup was closed
through the AI bridge still rendered "tracking required" and was reverted by the
next re-process.

Both now call services.tracking_patch.apply_tracking_update. These tests pin the
shared contract and the parity, so a future edit to one path cannot silently
diverge again.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.tracking_patch import (  # noqa: E402
    apply_tracking_update,
    close_tracking_proposal,
)

# Every key the shared patch is responsible for writing.
_TRACKING_KEYS = {
    "status", "status_label", "last_event", "last_location", "last_update",
    "source", "api_status", "updated_at", "available", "cowork_result_received",
    "cowork_tracking_required", "cowork_result_at",
}
_TOP_LEVEL_KEYS = {"tracking_complete", "tracking_complete_source", "tracking_complete_at"}


def _apply(**kw):
    audit = {"batch_id": "B1"}
    now = apply_tracking_update(audit, **kw)
    return audit, now


# ── shared contract ───────────────────────────────────────────────────────────

def test_writes_every_tracking_key():
    audit, _ = _apply(status="delivered", source="manual")
    assert _TRACKING_KEYS <= set(audit["tracking"]), (
        f"missing: {_TRACKING_KEYS - set(audit['tracking'])}"
    )


def test_writes_top_level_completion_keys():
    audit, now = _apply(status="in_transit", source="cowork")
    assert audit["tracking_complete"] is True
    assert audit["tracking_complete_source"] == "cowork"
    assert audit["tracking_complete_at"] == now


def test_api_status_is_manual_for_every_source():
    """Neither path is the live carrier API, whoever submitted the update."""
    for src in ("manual", "operator", "cowork", "ai_bridge", "claude_cowork"):
        audit, _ = _apply(status="in_transit", source=src)
        assert audit["tracking"]["api_status"] == "manual", f"source={src}"
        assert audit["tracking"]["source"] == src


def test_clears_the_lookup_task():
    audit = {"batch_id": "B1", "tracking": {"cowork_tracking_required": True}}
    apply_tracking_update(audit, status="customs", source="ai_bridge")
    assert audit["tracking"]["cowork_tracking_required"] is False
    assert audit["tracking"]["cowork_result_received"] is True


@pytest.mark.parametrize("status,expected", [
    ("delivered", True), ("out_for_delivery", True),
    ("in_transit", False), ("customs", False),
])
def test_arrived_warehouse_only_on_arrival_statuses(status, expected):
    audit, _ = _apply(status=status, source="manual")
    assert audit["tracking"].get("arrived_warehouse", False) is expected


def test_timestamps_are_one_consistent_instant():
    audit, now = _apply(status="delivered", source="manual")
    assert audit["tracking"]["updated_at"] == now
    assert audit["tracking"]["cowork_result_at"] == now
    assert audit["tracking_complete_at"] == now


def test_note_is_optional():
    audit, _ = _apply(status="in_transit", source="manual")
    assert "cowork_result_note" not in audit["tracking"]
    audit2, _ = _apply(status="in_transit", source="manual", note="hi")
    assert audit2["tracking"]["cowork_result_note"] == "hi"


def test_preexisting_tracking_fields_are_not_wiped():
    audit = {"batch_id": "B1", "tracking": {"tracking_url": "https://x", "carrier": "DHL"}}
    apply_tracking_update(audit, status="delivered", source="manual")
    assert audit["tracking"]["tracking_url"] == "https://x"
    assert audit["tracking"]["carrier"] == "DHL"


# ── parity: the defect this module exists to prevent ─────────────────────────

def test_both_write_paths_produce_identical_shape():
    """Same inputs through either caller must yield the same keys.

    routes_tracking passes a note; ai_bridge does not. Nothing else may differ.
    """
    from_tracking, _ = _apply(
        status="delivered", source="manual",
        last_event="Delivered", location="Warsaw", event_time="2026-07-21T10:00:00Z",
    )
    from_bridge, _ = _apply(
        status="delivered", source="claude_cowork",
        last_event="Delivered", location="Warsaw", event_time="2026-07-21T10:00:00Z",
    )
    assert set(from_tracking["tracking"]) == set(from_bridge["tracking"])
    assert set(from_tracking) == set(from_bridge)
    assert _TOP_LEVEL_KEYS <= set(from_bridge), (
        "the AI-bridge path must also advance the workflow — this is the exact "
        "asymmetry that left bridge-closed batches asking for a lookup again"
    )


def _function_source(path, func_name):
    """Source of ONE function, so pins bind per call site rather than per file."""
    import ast
    src = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{func_name} not found in {path.name}")


_CALL_SITES = [
    ("routes_tracking.py",  "update_tracking_for_batch"),
    ("routes_tracking.py",  "submit_cowork_tracking_result"),
    ("routes_ai_bridge.py", "import_bridge_result"),
]


@pytest.mark.parametrize("filename,func", _CALL_SITES)
def test_each_call_site_calls_the_shared_helper(filename, func):
    """Per-FUNCTION pin.

    A whole-file grep is too weak: routes_tracking.py holds TWO call sites, so
    dropping the helper from submit_cowork_tracking_result while leaving
    update_tracking_for_batch intact would pass a file-level check silently —
    and that is precisely the call site the file-level pin only caught by luck.
    """
    body = _function_source(_SVC / "app" / "api" / filename, func)
    assert "apply_tracking_update" in body, (
        f"{filename}::{func} no longer calls apply_tracking_update — removed, "
        "or the patch was re-inlined"
    )
    assert '"cowork_tracking_required": False' not in body, (
        f"{filename}::{func} re-inlines the tracking patch instead of calling "
        "apply_tracking_update — that is how the paths drifted before"
    )


# ── the workflow checkpoint is authorisation-gated ───────────────────────────

def test_advance_workflow_false_still_records_the_evidence():
    """A non-operator caller records tracking but must not close the step."""
    audit, _ = _apply(status="delivered", source="claude_cowork",
                      advance_workflow=False)
    assert audit["tracking"]["status"] == "delivered"
    assert audit["tracking"]["api_status"] == "manual"
    assert audit["tracking"]["cowork_tracking_required"] is False
    for k in _TOP_LEVEL_KEYS:
        assert k not in audit, f"{k} written without operator authority"


def test_advance_workflow_true_closes_the_step():
    audit, now = _apply(status="delivered", source="manual", advance_workflow=True)
    assert audit["tracking_complete"] is True
    assert audit["tracking_complete_at"] == now


def test_advance_workflow_defaults_to_true():
    """Operator routes must not opt in — only the weaker caller opts out."""
    audit, _ = _apply(status="delivered", source="manual")
    assert audit["tracking_complete"] is True


def test_bridge_gates_the_checkpoint_on_operator_role():
    """The bridge must derive advance_workflow from the caller's role.

    /ai-bridge/results/{task_id} is guarded by get_current_user alone, while
    both /tracking/* writers require require_role("admin","logistics").
    Consolidating the paths must not let the weakest one close a checkpoint
    that previously needed an operator.
    """
    path = _SVC / "app" / "api" / "routes_ai_bridge.py"
    body = _function_source(path, "import_bridge_result")
    # Match the EXPRESSION, not a bare identifier: a docstring mentioning
    # _OPERATOR_ROLES satisfies a substring check while the code passes
    # advance_workflow=True. That exact false pass happened while writing this.
    assert "advance_workflow = _may_close_checkpoint(user)" in body, (
        "the bridge must derive advance_workflow from the caller — a hardcoded "
        "advance_workflow=True silently widens who can close the tracking "
        "checkpoint from operator-only to any authenticated user"
    )
    gate = _function_source(path, "_may_close_checkpoint")
    assert "_OPERATOR_ROLES" in gate and 'get("role")' in gate, (
        "_may_close_checkpoint must decide on the caller's role"
    )
    assert "isinstance(user, dict)" in gate, (
        "_may_close_checkpoint must fail closed for a non-dict caller: on a "
        "direct Python call `user` is a FastAPI Depends object, and .get would "
        "raise AttributeError straight into `except Exception: pass`"
    )
    src = (_SVC / "app" / "api" / "routes_ai_bridge.py").read_text(encoding="utf-8")
    assert 'frozenset({"admin", "logistics"})' in src, (
        '_OPERATOR_ROLES must mirror require_role("admin", "logistics")'
    )


def test_ai_bridge_patch_holds_the_batch_lock():
    """The bridge patch is a read-modify-write and used to run unlocked."""
    src = (_SVC / "app" / "api" / "routes_ai_bridge.py").read_text(encoding="utf-8")
    assert "batch_write_lock(batch_id)" in src, (
        "routes_ai_bridge must hold batch_write_lock around its audit "
        "read-modify-write or a concurrent writer's changes can be lost"
    )


# ── proposal closure ─────────────────────────────────────────────────────────

def test_close_tracking_proposal_matches_only_the_right_one():
    audit = {"action_proposals": [
        {"proposal_id": "p1", "type": "other"},
        {"proposal_id": "p2", "type": "tracking_lookup"},
    ]}
    assert close_tracking_proposal(audit, "p2", "manual", "T") is True
    assert audit["action_proposals"][1]["status"] == "done"
    assert audit["action_proposals"][1]["done_source"] == "manual"
    assert "status" not in audit["action_proposals"][0]


def test_close_tracking_proposal_wrong_type_is_not_closed():
    audit = {"action_proposals": [{"proposal_id": "p1", "type": "other"}]}
    assert close_tracking_proposal(audit, "p1", "manual", "T") is False


def test_close_tracking_proposal_tolerates_missing_list():
    assert close_tracking_proposal({}, "p1", "manual", "T") is False

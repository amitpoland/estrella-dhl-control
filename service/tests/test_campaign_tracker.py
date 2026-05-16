"""test_campaign_tracker.py — unit tests for the file-based campaign tracker.

Tests the CLI/library in `service/scripts/campaign_status.py`. Pure file I/O;
no service, no DB, no HTTP. Each test uses a temporary state file via the
optional `state_file=` argument on every public function.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    scripts_dir = service_dir / "scripts"
    repo_root = here.parents[2]
    for p in (str(service_dir), str(repo_root), str(scripts_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

import campaign_status as cs  # type: ignore


# ── load/save ────────────────────────────────────────────────────────────────

def test_load_missing_file_returns_skeleton(tmp_path):
    sf = tmp_path / "campaign-state.json"
    state = cs.load_state(sf)
    assert state == {"schema_version": 1, "campaigns": []}


def test_save_round_trip(tmp_path):
    sf = tmp_path / "campaign-state.json"
    state = {"schema_version": 1, "campaigns": [
        {"campaign_id": "X", "title": "x", "status": "active",
         "started_at": "2026-01-01T00:00:00Z", "closed_at": None, "batches": []}
    ]}
    cs.save_state(state, sf)
    reloaded = cs.load_state(sf)
    assert reloaded == state


def test_save_writes_atomically_no_temp_left_behind(tmp_path):
    sf = tmp_path / "campaign-state.json"
    cs.save_state({"schema_version": 1, "campaigns": []}, sf)
    assert sf.exists()
    assert not (tmp_path / "campaign-state.json.tmp").exists()


# ── create / add ─────────────────────────────────────────────────────────────

def test_create_campaign(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    c = cs.create_campaign(state, "TEST-1", "Test campaign")
    assert c["campaign_id"] == "TEST-1"
    assert c["status"] == "active"
    assert c["started_at"]  # non-empty
    assert c["batches"] == []


def test_create_campaign_duplicate_raises(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "X", "X")
    with pytest.raises(ValueError, match="already exists"):
        cs.create_campaign(state, "X", "again")


def test_add_batch(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    b = cs.add_batch(state, "C", "B1", "first batch")
    assert b["batch_id"] == "B1"
    assert b["status"] == "planned"


def test_add_batch_duplicate_raises(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="already exists"):
        cs.add_batch(state, "C", "B1", "x")


def test_add_batch_unknown_campaign_raises(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    with pytest.raises(KeyError):
        cs.add_batch(state, "MISSING", "B1", "x")


# ── update ───────────────────────────────────────────────────────────────────

def test_update_batch_records_pr(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="pr_open",
                    pr_url="https://github.com/x/y/pull/1", pr_number=1)
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "pr_open"
    assert b["pr_number"] == 1
    assert b["pr_url"].endswith("/1")


def test_update_batch_records_merge_and_deploy(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="merged", merge_sha="abc123")
    cs.update_batch(state, "C", "B1", status="deployed", deployed_sha="abc123")
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "deployed"
    assert b["merge_sha"] == "abc123"
    assert b["deployed_sha"] == "abc123"
    assert b["deployed_at"]  # auto-stamped


def test_update_batch_records_tests(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", tests={"pz_regression": "160/160"})
    cs.update_batch(state, "C", "B1", tests={"master_suite": "100/100"})
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["tests"] == {"pz_regression": "160/160", "master_suite": "100/100"}


def test_update_batch_invalid_status_raises(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="Invalid status"):
        cs.update_batch(state, "C", "B1", status="exploded")


# ── block / unblock ──────────────────────────────────────────────────────────

def test_block_batch(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.block_batch(state, "C", "B1", "security review needed")
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "blocked"
    assert "security" in b["block_reason"]


def test_block_batch_requires_reason(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="reason"):
        cs.block_batch(state, "C", "B1", "")


def test_unblock_batch_clears_reason(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.block_batch(state, "C", "B1", "wait for operator")
    cs.unblock_batch(state, "C", "B1", "active")
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "active"
    assert b["block_reason"] is None


def test_unblock_cannot_resume_to_blocked(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.block_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError):
        cs.unblock_batch(state, "C", "B1", "blocked")


# ── smoke ─────────────────────────────────────────────────────────────────────

def test_attach_smoke_requires_existing_file(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(FileNotFoundError):
        cs.attach_smoke(state, "C", "B1", "tasks/smoke-reports/nope.md")


def test_attach_smoke_skip_exists_ok(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.attach_smoke(state, "C", "B1", "tasks/smoke-reports/test.md",
                   verify_exists=False)
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "smoked"
    assert b["smoke_report"].endswith("test.md")


# ── export ────────────────────────────────────────────────────────────────────

def test_export_markdown_contains_batch_rows(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "Demo")
    cs.add_batch(state, "C", "B1", "first")
    cs.add_batch(state, "C", "B2", "second")
    cs.update_batch(state, "C", "B1", status="merged",
                    pr_number=42, merge_sha="abcd1234ef56")
    md = cs.export_markdown(state, "C")
    assert "# Campaign: Demo" in md
    assert "B1" in md and "B2" in md
    assert "#42" in md
    assert "abcd1234" in md


def test_export_unknown_campaign_raises(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    with pytest.raises(KeyError):
        cs.export_markdown(state, "MISSING")


# ── CLI main() smoke ──────────────────────────────────────────────────────────

def test_cli_list_runs_without_state_file(tmp_path, monkeypatch, capsys):
    # Point _state_path to an empty dir
    monkeypatch.setattr(cs, "_state_path", lambda root=None: tmp_path / "s.json")
    rc = cs.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CAMPAIGN" in out


def test_cli_update_round_trip(tmp_path, monkeypatch):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "CLI", "x")
    cs.add_batch(state, "CLI", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["update", "CLI", "B1", "--status", "merged",
                  "--pr", "42", "--sha", "abc"])
    assert rc == 0
    s2 = cs.load_state(sf)
    b = cs._get_batch(cs._get_campaign(s2, "CLI"), "B1")
    assert b["status"] == "merged"
    assert b["pr_number"] == 42
    assert b["merge_sha"] == "abc"


# ── State integrity: cannot lose merge_sha ───────────────────────────────────
# This is a documented contract — once a batch records a merge_sha, no further
# update should be able to silently unset it. (The current implementation
# only sets fields when their argument is not None — verify this.)

def test_update_with_none_does_not_clear_merge_sha(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="merged", merge_sha="abc")
    cs.update_batch(state, "C", "B1", status="deployed")  # no sha passed
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["merge_sha"] == "abc", "merge_sha must survive subsequent updates"


# ── P3 hardening: deploy + stack metadata ───────────────────────────────────

def test_record_deploy_sets_status_and_metadata(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.record_deploy(state, "C", "B1",
                     deployed_sha="abc123def456",
                     previous_main_sha="000111222333",
                     robocopy_exit_codes=[1, 1, 1, 0],
                     restart_seconds=10)
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["status"] == "deployed"
    assert b["deployed_sha"] == "abc123def456"
    assert b["previous_main_sha"] == "000111222333"
    assert b["deployed_at"]  # auto-stamped
    assert b["rollback_command"].startswith("git revert -m 1 abc123d")
    assert b["deploy_metadata"]["robocopy_ok"] is True
    assert b["deploy_metadata"]["restart_seconds"] == 10


def test_record_deploy_flags_robocopy_errors(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.record_deploy(state, "C", "B1",
                     deployed_sha="abc",
                     robocopy_exit_codes=[1, 4, 1])  # 4 = error
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["deploy_metadata"]["robocopy_ok"] is False


def test_record_deploy_requires_sha(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="deployed_sha"):
        cs.record_deploy(state, "C", "B1", deployed_sha="")


def test_record_branch_stack_root(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.record_branch_stack(state, "C", "B1", base_branch="main", stack_depth=0)
    b = cs._get_batch(cs._get_campaign(state, "C"), "B1")
    assert b["branch_stack"]["base_branch"] == "main"
    assert b["branch_stack"]["stack_depth"] == 0
    assert "warning" not in b["branch_stack"]


def test_record_branch_stack_stacked(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B2", "x")
    cs.record_branch_stack(state, "C", "B2",
                           base_branch="feat/b1",
                           stack_depth=1,
                           stacked_on="B1")
    b = cs._get_batch(cs._get_campaign(state, "C"), "B2")
    assert b["branch_stack"]["stack_depth"] == 1
    assert b["branch_stack"]["stacked_on"] == "B1"


def test_record_branch_stack_warns_on_misroute(tmp_path):
    """stack_depth > 0 with base_branch == 'main' is suspicious — flag it."""
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B2", "x")
    cs.record_branch_stack(state, "C", "B2",
                           base_branch="main",  # misroute: should be feat/*
                           stack_depth=1,
                           stacked_on="B1")
    b = cs._get_batch(cs._get_campaign(state, "C"), "B2")
    assert "warning" in b["branch_stack"]
    assert "forward-merge" in b["branch_stack"]["warning"]


def test_record_branch_stack_requires_stacked_on(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="stacked_on"):
        cs.record_branch_stack(state, "C", "B1",
                               base_branch="feat/x", stack_depth=2)


def test_record_branch_stack_rejects_negative_depth(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    with pytest.raises(ValueError, match="stack_depth"):
        cs.record_branch_stack(state, "C", "B1",
                               base_branch="main", stack_depth=-1)


# ── P3: summary dashboard ────────────────────────────────────────────────────

def test_summary_renders_open_prs_blocked_deploys(tmp_path):
    state = cs.load_state(tmp_path / "s.json")
    cs.create_campaign(state, "A", "Active campaign")
    cs.add_batch(state, "A", "B1", "first")
    cs.update_batch(state, "A", "B1", status="pr_open",
                    pr_url="https://example.com/pr/1", pr_number=1)
    cs.add_batch(state, "A", "B2", "blocked one")
    cs.block_batch(state, "A", "B2", "needs operator approval")
    cs.add_batch(state, "A", "B3", "deployed one")
    cs.record_deploy(state, "A", "B3", deployed_sha="abcdef12345",
                     robocopy_exit_codes=[1, 1])

    out = cs._state_summary(state)
    assert "OPERATOR DASHBOARD" in out
    assert "Active campaign" in out
    assert "Open PRs: 1" in out
    assert "https://example.com/pr/1" in out
    assert "Blocked items: 1" in out
    assert "needs operator approval" in out
    assert "abcdef12" in out
    assert "[robocopy ok]" in out


def test_cli_summary_command(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "TEST", "Test")
    cs.save_state(state, sf)
    rc = cs.main(["summary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OPERATOR DASHBOARD" in out


def test_cli_deploy_command(tmp_path, monkeypatch):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["deploy", "C", "B1", "--sha", "deadbeef",
                  "--previous-main-sha", "cafebabe",
                  "--robocopy-exit-codes", "1,0,1",
                  "--restart-seconds", "10"])
    assert rc == 0
    s2 = cs.load_state(sf)
    b = cs._get_batch(cs._get_campaign(s2, "C"), "B1")
    assert b["status"] == "deployed"
    assert b["deployed_sha"] == "deadbeef"
    assert b["deploy_metadata"]["restart_seconds"] == 10
    assert b["deploy_metadata"]["robocopy_ok"] is True


def test_cli_stack_command(tmp_path, monkeypatch):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B2", "x")
    cs.save_state(state, sf)
    rc = cs.main(["stack", "C", "B2",
                  "--base-branch", "feat/b1",
                  "--stack-depth", "1",
                  "--stacked-on", "B1"])
    assert rc == 0
    s2 = cs.load_state(sf)
    b = cs._get_batch(cs._get_campaign(s2, "C"), "B2")
    assert b["branch_stack"]["base_branch"] == "feat/b1"
    assert b["branch_stack"]["stacked_on"] == "B1"


# ── Real state file sanity (read-only — does not mutate) ─────────────────────
# Confirms the production tasks/campaign-state.json is valid JSON and matches
# the expected schema.

def test_real_state_file_is_valid_json():
    sp = Path(__file__).resolve().parents[2] / "tasks" / "campaign-state.json"
    if not sp.exists():
        pytest.skip(f"State file not yet committed: {sp}")
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert isinstance(data["campaigns"], list)
    for c in data["campaigns"]:
        assert "campaign_id" in c and "status" in c and "batches" in c
        for b in c["batches"]:
            assert "batch_id" in b and "status" in b
            assert b["status"] in cs.VALID_STATUSES, \
                f"Invalid status in real state: {b['batch_id']} → {b['status']!r}"

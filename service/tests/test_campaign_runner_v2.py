"""test_campaign_runner_v2.py — queue / gates / failure recovery engine tests.

These cover the v2 additions to campaign_status.py:
  - dependency graph + readiness
  - next-recommended batch
  - blocker enumeration
  - stuck-batch detection
  - verification gates + batch verification
  - branch-stack misroute detection
  - rollback plan generation
  - interrupted-campaign detection
  - operator dashboard rendering
  - new CLI subcommands: queue / next / blockers / verify / graph / resume /
    pause / retry / doctor / dashboard
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2]),
              str(here.parents[1] / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

import campaign_status as cs  # type: ignore


def _mk_state(tmp_path):
    sf = tmp_path / "s.json"
    state = cs.load_state(sf)
    return sf, state


# ── Dependency graph + readiness ────────────────────────────────────────────

def test_batch_is_ready_when_no_deps(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    assert cs.batch_is_ready(state, "C", b1) is True


def test_batch_not_ready_when_dep_unfinished(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.add_batch(state, "C", "B2", "y")
    c = cs._get_campaign(state, "C")
    b2 = cs._get_batch(c, "B2")
    b2["depends_on"] = ["B1"]
    assert cs.batch_is_ready(state, "C", b2) is False


def test_batch_ready_after_dep_smoked(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.add_batch(state, "C", "B2", "y")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    b1["status"] = "smoked"
    b2 = cs._get_batch(c, "B2")
    b2["depends_on"] = ["B1"]
    assert cs.batch_is_ready(state, "C", b2) is True


def test_batch_not_ready_when_status_blocked(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.block_batch(state, "C", "B1", "wait")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    assert cs.batch_is_ready(state, "C", b1) is False


def test_next_recommended_batch_picks_first_ready(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "first")
    cs.add_batch(state, "C", "B2", "second")
    cs.update_batch(state, "C", "B1", status="smoked")
    nb = cs.next_recommended_batch(state, "C")
    assert nb is not None
    assert nb["batch_id"] == "B2"


def test_next_recommended_returns_none_when_all_done_or_blocked(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "C")
    cs.add_batch(state, "C", "B1", "x")
    cs.add_batch(state, "C", "B2", "y")
    cs.update_batch(state, "C", "B1", status="smoked")
    cs.block_batch(state, "C", "B2", "needs review")
    assert cs.next_recommended_batch(state, "C") is None


# ── list_blockers ───────────────────────────────────────────────────────────

def test_list_blockers_across_campaigns(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C1", "x")
    cs.create_campaign(state, "C2", "y")
    cs.add_batch(state, "C1", "B1", "a")
    cs.add_batch(state, "C2", "B1", "b")
    cs.block_batch(state, "C1", "B1", "r1")
    cs.block_batch(state, "C2", "B1", "r2")
    out = cs.list_blockers(state)
    assert len(out) == 2
    assert {x["campaign_id"] for x in out} == {"C1", "C2"}


def test_list_blockers_filters_by_campaign(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C1", "x")
    cs.create_campaign(state, "C2", "y")
    cs.add_batch(state, "C1", "B1", "a")
    cs.add_batch(state, "C2", "B1", "b")
    cs.block_batch(state, "C1", "B1", "r1")
    cs.block_batch(state, "C2", "B1", "r2")
    out = cs.list_blockers(state, campaign_id="C1")
    assert len(out) == 1
    assert out[0]["campaign_id"] == "C1"


# ── Stuck-batch detection ───────────────────────────────────────────────────

def test_detect_stuck_pr_open(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "stuck")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    b1["status"] = "pr_open"
    b1["opened_at"] = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    out = cs.detect_stuck_batches(state)
    assert any(x["batch_id"] == "B1" and "pr_open" in x["reason"] for x in out)


def test_detect_stuck_merged_no_deploy(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "stuck")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    b1["status"] = "merged"
    b1["merged_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    out = cs.detect_stuck_batches(state)
    assert any(x["batch_id"] == "B1" and "merged" in x["reason"] for x in out)


def test_detect_stuck_deployed_no_smoke(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    b1["status"] = "deployed"
    b1["deployed_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    out = cs.detect_stuck_batches(state)
    assert any(x["batch_id"] == "B1" and "smoke" in x["reason"] for x in out)


def test_detect_stuck_clean_when_fresh(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="pr_open")
    c = cs._get_campaign(state, "C")
    b1 = cs._get_batch(c, "B1")
    b1["opened_at"] = datetime.now(timezone.utc).isoformat()
    out = cs.detect_stuck_batches(state)
    assert not any(x["batch_id"] == "B1" for x in out)


# ── Verification gates ──────────────────────────────────────────────────────

def test_verification_gates_all_false_for_planned(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    c = cs._get_campaign(state, "C")
    g = cs.verification_gates(cs._get_batch(c, "B1"))
    assert g["tests_recorded"] is False
    assert g["pz_regression_ok"] is False
    assert g["pr_present"] is False
    assert g["no_block"] is True  # planned is not blocked


def test_verification_gates_all_true_for_complete(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="smoked",
                    pr_url="https://x/y/1", merge_sha="abc",
                    deployed_sha="abc",
                    tests={"pz_regression": "160/160"})
    cs.attach_smoke(state, "C", "B1", "tasks/x.md", verify_exists=False)
    c = cs._get_campaign(state, "C")
    g = cs.verification_gates(cs._get_batch(c, "B1"))
    assert all(g.values())


def test_verify_batch_returns_missing_gates(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="merged",
                    pr_url="https://x/y/1", merge_sha="abc")
    rep = cs.verify_batch(state, "C", "B1")
    # merged status doesn't require tests yet (only pz_regression_ok if set)
    assert rep["status"] == "merged"
    assert "missing" in rep
    # pz_regression_ok is required, and not satisfied
    assert "pz_regression_ok" in rep["missing"]


def test_verify_batch_ok_when_status_matches(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="merged",
                    pr_url="https://x/y/1", merge_sha="abc",
                    tests={"pz_regression": "160/160"})
    rep = cs.verify_batch(state, "C", "B1")
    assert rep["ok"] is True


def test_verify_batch_custom_gates(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    rep = cs.verify_batch(state, "C", "B1", required=["no_block"])
    assert rep["ok"] is True
    assert rep["required"] == ["no_block"]


# ── Branch-stack misroute detection ─────────────────────────────────────────

def test_detect_branch_stack_misroutes(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "ok stacking")
    cs.add_batch(state, "C", "B2", "misroute")
    cs.record_branch_stack(state, "C", "B1",
                           base_branch="feat/parent", stack_depth=1, stacked_on="parent")
    cs.record_branch_stack(state, "C", "B2",
                           base_branch="main", stack_depth=1, stacked_on="B1")
    out = cs.detect_branch_stack_misroutes(state)
    assert len(out) == 1
    assert out[0]["batch_id"] == "B2"


def test_detect_branch_stack_clean_when_no_warning(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "fine")
    cs.record_branch_stack(state, "C", "B1", base_branch="main", stack_depth=0)
    assert cs.detect_branch_stack_misroutes(state) == []


# ── Rollback plan ───────────────────────────────────────────────────────────

def test_rollback_plan_ok_with_previous_sha(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.record_deploy(state, "C", "B1", deployed_sha="abcdef123",
                     previous_main_sha="000111222")
    c = cs._get_campaign(state, "C")
    plan = cs.rollback_plan(cs._get_batch(c, "B1"))
    assert plan["ok"] is True
    assert plan["previous_sha"] == "000111222"
    assert "git revert" in plan["command"]


def test_rollback_plan_no_deploy(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    c = cs._get_campaign(state, "C")
    plan = cs.rollback_plan(cs._get_batch(c, "B1"))
    assert plan["ok"] is False
    assert "deployed_sha" in plan["reason"]


def test_rollback_plan_no_previous_sha_has_fallback(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.record_deploy(state, "C", "B1", deployed_sha="abcdef123")
    c = cs._get_campaign(state, "C")
    plan = cs.rollback_plan(cs._get_batch(c, "B1"))
    assert plan["ok"] is False
    assert "fallback_command" in plan
    assert "abcdef1" in plan["fallback_command"]


# ── Interrupted campaign detection ──────────────────────────────────────────

def test_detect_interrupted_campaign_when_all_smoked_or_blocked(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.add_batch(state, "C", "B2", "y")
    cs.update_batch(state, "C", "B1", status="smoked")
    cs.block_batch(state, "C", "B2", "wait")
    out = cs.detect_interrupted_campaigns(state)
    assert any(x["campaign_id"] == "C" for x in out)


def test_detect_interrupted_skips_completed_campaign(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.update_batch(state, "C", "B1", status="smoked")
    c = cs._get_campaign(state, "C")
    c["status"] = "completed"
    out = cs.detect_interrupted_campaigns(state)
    assert not any(x["campaign_id"] == "C" for x in out)


# ── Dashboard rendering ─────────────────────────────────────────────────────

def test_render_dashboard_includes_sections(tmp_path):
    sf, state = _mk_state(tmp_path)
    cs.create_campaign(state, "C", "Demo")
    cs.add_batch(state, "C", "B1", "first")
    cs.add_batch(state, "C", "B2", "blocked")
    cs.block_batch(state, "C", "B2", "needs operator")
    cs.record_deploy(state, "C", "B1", deployed_sha="abc",
                     robocopy_exit_codes=[1, 0])
    md = cs.render_dashboard(state)
    assert "Operator Dashboard" in md
    assert "Next recommended batch" in md
    assert "Blockers" in md
    assert "needs operator" in md
    assert "Recent deploys" in md


# ── New CLI subcommands ─────────────────────────────────────────────────────

def test_cli_queue(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["queue", "C"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "B1" in out


def test_cli_next_returns_1_when_empty(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.save_state(state, sf)
    rc = cs.main(["next", "C"])
    assert rc == 1


def test_cli_verify_ok_returns_0(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["verify", "C", "B1", "--gate", "no_block"])
    assert rc == 0


def test_cli_verify_failing_returns_1(tmp_path, monkeypatch):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["verify", "C", "B1", "--gate", "pz_regression_ok"])
    assert rc == 1


def test_cli_doctor_clean(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.save_state(state, sf)
    rc = cs.main(["doctor"])
    assert rc == 0


def test_cli_doctor_flags_stack_misroute(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "misroute")
    cs.record_branch_stack(state, "C", "B1",
                           base_branch="main", stack_depth=1, stacked_on="X")
    cs.save_state(state, sf)
    rc = cs.main(["doctor"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "stack" in out


def test_cli_retry_resets_to_planned(tmp_path, monkeypatch):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.block_batch(state, "C", "B1", "fail")
    cs.save_state(state, sf)
    rc = cs.main(["retry", "C", "B1"])
    assert rc == 0
    s2 = cs.load_state(sf)
    b = cs._get_batch(cs._get_campaign(s2, "C"), "B1")
    assert b["status"] == "planned"
    assert b["block_reason"] is None
    assert b["retries"] == 1


def test_cli_dashboard_emits_markdown(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.save_state(state, sf)
    rc = cs.main(["dashboard"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Campaign Runner" in out


def test_cli_resume_prints_action_hint(tmp_path, monkeypatch, capsys):
    sf = tmp_path / "s.json"
    monkeypatch.setattr(cs, "_state_path", lambda root=None: sf)
    state = cs.load_state(sf)
    cs.create_campaign(state, "C", "x")
    cs.add_batch(state, "C", "B1", "x")
    cs.save_state(state, sf)
    rc = cs.main(["resume", "C"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "B1" in out
    assert "create branch" in out

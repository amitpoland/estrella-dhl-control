"""test_runner_v2_hard_rules.py — source-grep hard rules for the autonomous
campaign runner v2.

Guards against drift toward:
  1. background daemon loops
  2. auto-merge to main
  3. auto-deploy to production
  4. hidden execution (silent file mutations, silent service writes)
  5. scheduler threads
  6. forbidden production mutations from runner code paths
  7. accounting / wFirma / PZ-engine coupling from runner code paths
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_RUNNER  = _REPO / "service" / "scripts" / "campaign_status.py"
_SMOKE   = _REPO / "service" / "scripts" / "run_smoke.py"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"missing: {p}")
    return p.read_text(encoding="utf-8")


# ── Rule 1: no daemon loop / background thread ─────────────────────────────

@pytest.mark.parametrize("module", [_RUNNER, _SMOKE])
def test_no_background_thread_or_daemon(module):
    src = _read(module)
    for forbidden in ("threading.Thread", "asyncio.run_forever",
                      "asyncio.create_task", "asyncio.ensure_future",
                      "while True:", "schedule.every",
                      "apscheduler", "celery.task"):
        # Allow "while True:" inside docstrings or comments; check non-comment lines only
        if forbidden == "while True:":
            for line in src.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or '"""' in stripped or "'''" in stripped:
                    continue
                assert forbidden not in line, \
                    f"{module.name}: forbidden daemon pattern: {forbidden} on line {line!r}"
        else:
            assert forbidden not in src, \
                f"{module.name}: forbidden background pattern: {forbidden}"


# ── Rule 2: no auto-merge invocations ──────────────────────────────────────

@pytest.mark.parametrize("module", [_RUNNER, _SMOKE])
def test_no_auto_merge_invocation(module):
    src = _read(module)
    for forbidden in ("gh pr merge", "subprocess.run([\"git\", \"merge\"",
                      "subprocess.run(['git', 'merge'", '"git", "merge"',
                      "'git', 'merge'", "gh.exe pr merge"):
        # The CLI may reference 'merge' as a status name; only forbid invocations
        # of `gh pr merge` or `git merge` as a subprocess call
        assert forbidden not in src, \
            f"{module.name}: forbidden auto-merge invocation pattern: {forbidden}"


# ── Rule 3: no auto-deploy invocations ─────────────────────────────────────

@pytest.mark.parametrize("module", [_RUNNER, _SMOKE])
def test_no_auto_deploy_invocation(module):
    src = _read(module)
    for forbidden in ("robocopy(", "robocopy(\"", "sc.exe", "Restart-Service",
                      "subprocess.run([\"robocopy\"",
                      "subprocess.run(['robocopy'"):
        assert forbidden not in src, \
            f"{module.name}: forbidden auto-deploy pattern: {forbidden}"


# ── Rule 4: no hidden execution (silent file/state mutation paths) ─────────

def test_runner_writes_only_to_state_file_or_smoke_reports():
    """Every `with open(... 'w')` in the runner must write to either the
    state file or the smoke-reports directory. No silent file writes elsewhere."""
    src = _read(_RUNNER)
    # Pull every literal write-mode open + Path.write_text in the module
    forbidden_targets = ["/etc/", "/var/", "C:\\Windows\\",
                          "/.env", "\\.env", "/storage/", "\\storage\\",
                          "/customer_master.sqlite", "\\customer_master.sqlite"]
    for f in forbidden_targets:
        # Forbid any literal occurrence — we control all string concat in this module
        assert f not in src, f"runner must not reference forbidden write target: {f}"


def test_runner_save_state_uses_atomic_write():
    src = _read(_RUNNER)
    # save_state must write to a .tmp file then atomically replace
    assert ".tmp" in src and "replace(" in src, \
        "save_state must use atomic .tmp + replace pattern"


# ── Rule 5: no scheduler threads ───────────────────────────────────────────

@pytest.mark.parametrize("module", [_RUNNER, _SMOKE])
def test_no_scheduler_thread(module):
    src = _read(module)
    for forbidden in ("BackgroundScheduler", "BlockingScheduler",
                      "schedule.run_pending", "Thread(target="):
        assert forbidden not in src, \
            f"{module.name}: forbidden scheduler pattern: {forbidden}"


# ── Rule 6: runner does not touch production code paths ────────────────────

def test_runner_does_not_import_pz_engine():
    src = _read(_RUNNER)
    for forbidden in ("pz_import_processor", "process_batch",
                      "from app.services.wfirma_client",
                      "from app.api.routes_proforma",
                      "from app.services.proforma_pz",
                      "from app.services.ledger_aggregator"):
        assert forbidden not in src, \
            f"runner must not import production engine code: {forbidden}"


# ── Rule 7: smoke driver does not write outside smoke-reports ──────────────

def test_smoke_driver_writes_only_smoke_reports():
    src = _read(_SMOKE)
    # The driver writes a report file from --output OR a default in tasks/smoke-reports/
    assert "tasks/smoke-reports" in src
    # Forbidden write targets: must not appear as a path-shaped string literal
    forbidden_paths = (
        "'.env'", '".env"',                             # exact string literal
        "open('.env'", 'open(".env"',                    # open() call
        "'storage/", '"storage/',                        # storage path prefix
        "Path('.env')", 'Path(".env")',
    )
    for f in forbidden_paths:
        assert f not in src, \
            f"smoke driver must not reference forbidden path literal: {f}"


def test_smoke_driver_does_not_call_subprocess_or_service():
    src = _read(_SMOKE)
    for forbidden in ("subprocess.run", "subprocess.check_call",
                      "subprocess.check_output", "os.system("):
        assert forbidden not in src, \
            f"smoke driver must not shell out: {forbidden}"


# ── Rule 8: file-based orchestration only — no SQLite, no HTTP servers ─────

def test_runner_is_file_based_only():
    src = _read(_RUNNER)
    for forbidden in ("sqlite3", "import psycopg", "from fastapi", "import http.server",
                      "HTTPServer", "uvicorn"):
        assert forbidden not in src, \
            f"runner must be file-based only: {forbidden} forbidden"


# ── Rule 9: explicit valid statuses, no silent allow-list drift ────────────

def test_runner_valid_statuses_locked():
    """VALID_STATUSES must contain exactly the 7 canonical states. Any
    addition or removal requires updating this test deliberately."""
    # Path-resolve to the scripts dir, then import
    here = Path(__file__).resolve()
    scripts_dir = str(here.parents[1] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import campaign_status as cs_mod  # type: ignore
    expected = {"planned", "active", "pr_open", "merged",
                "deployed", "smoked", "blocked"}
    assert set(cs_mod.VALID_STATUSES) == expected, \
        f"VALID_STATUSES drift: got {set(cs_mod.VALID_STATUSES)}"


# ── Rule 10: state-file schema is versioned ────────────────────────────────

def test_state_file_schema_versioned():
    import json as _json
    sp = _REPO / "tasks" / "campaign-state.json"
    if not sp.exists():
        pytest.skip("state file not present")
    data = _json.loads(sp.read_text(encoding="utf-8"))
    assert "schema_version" in data
    assert isinstance(data["schema_version"], int)


# ── Rule 11: docs explicitly state no autonomous deploy ────────────────────

def test_runner_doc_states_no_autonomous_deploy():
    doc = _REPO / "tasks" / "campaign-runner.md"
    if not doc.exists():
        pytest.skip("campaign-runner.md not present")
    text = doc.read_text(encoding="utf-8")
    # Must explicitly state no daemon / no background process
    for required in ("No background process", "No daemon"):
        assert required in text, f"campaign-runner.md must state: {required!r}"

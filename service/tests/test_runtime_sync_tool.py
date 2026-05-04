"""
test_runtime_sync_tool.py — unit tests for verify_runtime_sync.

Coverage
--------
  1.  _check returns STALE when runtime file differs from dev source
  2.  _check returns OK when runtime and dev source match
  3.  _check returns MISSING when dev source does not exist
  4.  main() exits 0 when no mismatches
  5.  main() exits 1 when any mismatch present
  6.  --sync copies a mismatched file to the runtime path
  7.  --sync does NOT overwrite when files already match
  8.  --sync refuses to copy into a 'storage' path
  9.  --sync refuses to copy into an 'archived' path
 10.  --sync skips entries with no runtime path
 11.  --restart-hint prints kill/restart command without executing it
 12.  pz_import_processor dev_path resolves inside CLI root (not service/app)
 13.  dashboard.html is in the critical list with module=None
 14.  _sha256 returns identical hashes for identical content, different for different
 15.  _is_forbidden blocks paths containing 'storage' or 'archived'
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest

# ── Import the module under test ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))   # service/
from app.tools.verify_runtime_sync import (
    _CLI_DIR,
    _APP_DIR,
    _CRITICAL,
    _Entry,
    _Result,
    _check,
    _is_forbidden,
    _sha256,
    _sync_file,
    _status,
    _RESTART_CMD,
    main,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_DEFAULT_PATH = Path("/tmp/fake_source/mod.py")


def _make_result(
    *,
    label="test_mod",
    dev_path: Optional[Path] = None,
    runtime_path: Optional[Path] = _DEFAULT_PATH,
    dev_exists=True,
    rt_exists=True,
    shadowed=False,
    mismatch=False,
    dev_hash="aaa",
    rt_hash="aaa",
) -> _Result:
    return _Result(
        label=label,
        dev_path=dev_path if dev_path is not None else _DEFAULT_PATH,
        runtime_path=runtime_path,   # None is valid — means "not found"
        dev_exists=dev_exists,
        rt_exists=rt_exists,
        shadowed=shadowed,
        mismatch=mismatch,
        dev_hash=dev_hash,
        rt_hash=rt_hash,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1–3: _status helper
# ═══════════════════════════════════════════════════════════════════════════════

def test_status_stale_when_mismatch():
    r = _make_result(shadowed=True, mismatch=True, dev_hash="aaa", rt_hash="bbb")
    assert _status(r) == "STALE"


def test_status_ok_when_match():
    r = _make_result(shadowed=False, mismatch=False)
    assert _status(r) == "OK"


def test_status_missing_when_dev_absent():
    r = _make_result(dev_exists=False)
    assert _status(r) == "MISSING"


# ═══════════════════════════════════════════════════════════════════════════════
# 4–5: main() exit codes
# ═══════════════════════════════════════════════════════════════════════════════

def test_main_exits_0_when_all_match(tmp_path, monkeypatch):
    """main() returns 0 when every _check produces no mismatch."""
    ok = _make_result(mismatch=False, dev_exists=True)
    monkeypatch.setattr(
        "app.tools.verify_runtime_sync._CRITICAL",
        [_Entry("mod", Path(tmp_path / "mod.py"), "mod")],
    )
    with patch("app.tools.verify_runtime_sync._check", return_value=ok):
        rc = main([])
    assert rc == 0


def test_main_exits_1_when_mismatch(monkeypatch):
    """main() returns 1 when at least one _check reports mismatch."""
    stale = _make_result(shadowed=True, mismatch=True, dev_hash="aaa", rt_hash="bbb")
    with patch("app.tools.verify_runtime_sync._check", return_value=stale):
        rc = main([])
    assert rc == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6–7: --sync behaviour
# ═══════════════════════════════════════════════════════════════════════════════

def test_sync_copies_mismatched_file(tmp_path):
    """--sync copies dev_path content to runtime_path when they differ."""
    dev  = tmp_path / "dev" / "mod.py"
    rt   = tmp_path / "rt"  / "mod.py"
    dev.parent.mkdir(); dev.write_text("NEW CONTENT")
    rt.parent.mkdir();  rt.write_text("OLD CONTENT")

    stale = _make_result(
        dev_path=dev, runtime_path=rt,
        dev_exists=True, rt_exists=True,
        shadowed=True, mismatch=True,
        dev_hash="new", rt_hash="old",
    )
    with patch("app.tools.verify_runtime_sync._check", return_value=stale):
        main(["--sync"])

    assert rt.read_text() == "NEW CONTENT"


def test_sync_skips_when_files_match(tmp_path):
    """--sync does not overwrite when dev and runtime already match."""
    dev = tmp_path / "mod.py"
    rt  = tmp_path / "mod_rt.py"
    dev.write_text("SAME"); rt.write_text("SAME")

    ok = _make_result(
        dev_path=dev, runtime_path=rt,
        dev_exists=True, rt_exists=True,
        shadowed=False, mismatch=False,
        dev_hash="x", rt_hash="x",
    )
    rt_mtime_before = rt.stat().st_mtime
    with patch("app.tools.verify_runtime_sync._check", return_value=ok):
        main(["--sync"])

    # File not touched — mtime unchanged
    assert rt.stat().st_mtime == rt_mtime_before


# ═══════════════════════════════════════════════════════════════════════════════
# 8–9: --sync refuses forbidden destination paths
# ═══════════════════════════════════════════════════════════════════════════════

def test_sync_refuses_storage_path(tmp_path, capsys):
    dev = tmp_path / "mod.py"
    dev.write_text("DATA")
    rt  = tmp_path / "storage" / "mod.py"
    rt.parent.mkdir()
    rt.write_text("OLD")

    stale = _make_result(
        dev_path=dev, runtime_path=rt,
        dev_exists=True, rt_exists=True,
        shadowed=True, mismatch=True,
    )
    _sync_file(stale)
    assert rt.read_text() == "OLD"   # not overwritten


def test_sync_refuses_archived_path(tmp_path):
    dev = tmp_path / "mod.py"
    dev.write_text("DATA")
    rt  = tmp_path / "archived" / "batches" / "mod.py"
    rt.parent.mkdir(parents=True)
    rt.write_text("OLD")

    stale = _make_result(
        dev_path=dev, runtime_path=rt,
        dev_exists=True, rt_exists=True,
        shadowed=True, mismatch=True,
    )
    _sync_file(stale)
    assert rt.read_text() == "OLD"   # not overwritten


# ═══════════════════════════════════════════════════════════════════════════════
# 10: --sync skips entries with no runtime path
# ═══════════════════════════════════════════════════════════════════════════════

def test_sync_skips_when_no_runtime_path(tmp_path, capsys):
    dev = tmp_path / "mod.py"
    dev.write_text("X")
    r = _make_result(dev_path=dev, runtime_path=None, rt_exists=False)
    _sync_file(r)   # must not raise
    out = capsys.readouterr().out
    assert "SKIP" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 11: --restart-hint
# ═══════════════════════════════════════════════════════════════════════════════

def test_restart_hint_printed_not_executed(monkeypatch, capsys):
    ok = _make_result(mismatch=False, dev_exists=True)
    with patch("app.tools.verify_runtime_sync._check", return_value=ok):
        main(["--restart-hint"])
    out = capsys.readouterr().out
    assert "pkill" in out
    assert "uvicorn" in out


def test_restart_hint_does_not_call_subprocess(monkeypatch, capsys):
    """subprocess must never be called by --restart-hint."""
    ok = _make_result(mismatch=False, dev_exists=True)
    with patch("app.tools.verify_runtime_sync._check", return_value=ok):
        with patch("subprocess.run") as mock_run:
            main(["--restart-hint"])
            mock_run.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 12: pz_import_processor maps to CLI root
# ═══════════════════════════════════════════════════════════════════════════════

def test_pz_import_processor_dev_path_in_cli_root():
    entry = next(e for e in _CRITICAL if e.label == "pz_import_processor")
    assert entry.dev_path.parent.resolve() == _CLI_DIR.resolve(), (
        f"pz_import_processor dev_path should be in CLI root ({_CLI_DIR}), "
        f"got {entry.dev_path.parent}"
    )


def test_pz_import_processor_module_is_top_level():
    entry = next(e for e in _CRITICAL if e.label == "pz_import_processor")
    assert entry.module == "pz_import_processor"
    assert "." not in entry.module


# ═══════════════════════════════════════════════════════════════════════════════
# 13: dashboard.html has module=None
# ═══════════════════════════════════════════════════════════════════════════════

def test_dashboard_html_in_critical_list():
    entry = next((e for e in _CRITICAL if e.label == "dashboard.html"), None)
    assert entry is not None, "dashboard.html must be in _CRITICAL"
    assert entry.module is None


def test_dashboard_html_dev_path_is_static():
    entry = next(e for e in _CRITICAL if e.label == "dashboard.html")
    assert "static" in str(entry.dev_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 14: _sha256 correctness
# ═══════════════════════════════════════════════════════════════════════════════

def test_sha256_identical_content(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"hello world")
    b.write_bytes(b"hello world")
    assert _sha256(a) == _sha256(b)


def test_sha256_different_content(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"old code")
    b.write_bytes(b"new code")
    assert _sha256(a) != _sha256(b)


# ═══════════════════════════════════════════════════════════════════════════════
# 15: _is_forbidden
# ═══════════════════════════════════════════════════════════════════════════════

def test_is_forbidden_storage():
    assert _is_forbidden(Path("/opt/service/storage/outputs/batch/mod.py"))


def test_is_forbidden_archived():
    assert _is_forbidden(Path("/opt/service/archived/2024/mod.py"))


def test_is_forbidden_false_for_app_path():
    assert not _is_forbidden(Path("/opt/venv/lib/python3.9/site-packages/pz_import_processor.py"))


def test_is_forbidden_false_for_service_path():
    assert not _is_forbidden(Path("/Users/amitgupta/Downloads/CLI/service/app/services/audit_merge.py"))
